#!/usr/bin/env python3
"""
patch_transformer.py — PatchTST 式時序 Transformer 機動偵測器（契約 M4 深度學習）
=============================================================================
把物理殘差序列（z_drag/z_di/z_de）切成 patch、線性嵌入、Transformer 編碼、分類頭，
於 **unit 級**（機動 episode 序列窗 vs 等寬安靜序列窗）做監督分類（避開 MEME/TLE 點級錯位）。
與融合評分器（表格特徵 GBM）互為對照：此為原始序列的深度模型。

用法：python patch_transformer.py [--epochs 40] [--max-sats N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.model_selection import GroupKFold
from sklearn.metrics import roc_auc_score, average_precision_score

from statistical_detectors import run_all
from atmospheric_drag import load_space_weather
from compare_tle_vs_ephemeris import load_registry
from satdet import config, episodes_by_sat, input_file, load_drag_map, to_ns
from satdet.common import RANK_SEV, SEV_RANK as _RANK

CH = ["cusum", "bocpd", "ssa", "mad3sig", "drag"]   # 與融合器同通道（序列輸入）
L = 16; PATCH = 4


class PatchTST(nn.Module):
    def __init__(self, n_ch=3, L=16, patch=4, d=64, heads=4, layers=2):
        super().__init__()
        self.np_ = L // patch
        self.embed = nn.Linear(patch * n_ch, d)
        self.pos = nn.Parameter(torch.randn(1, self.np_, d) * 0.02)
        enc = nn.TransformerEncoderLayer(d, heads, d * 2, dropout=0.1, batch_first=True)
        self.tr = nn.TransformerEncoder(enc, layers)
        self.head = nn.Sequential(nn.LayerNorm(d), nn.Linear(d, 1))
        self.patch = patch; self.n_ch = n_ch

    def forward(self, x):                        # x:[B,L,C]
        B = x.size(0)
        p = x.reshape(B, self.np_, self.patch * self.n_ch)   # 切 patch 攤平
        h = self.tr(self.embed(p) + self.pos)                # [B,np,d]
        return self.head(h.mean(1)).squeeze(-1)              # [B] logit


def _window_at(X, ep, center_ns):
    """取最接近 center 的 L 筆（不足前補零）。"""
    i = int(np.argmin(np.abs(ep - center_ns)))
    lo = max(0, i - L // 2); hi = lo + L
    if hi > len(X):
        hi = len(X); lo = max(0, hi - L)
    w = X[lo:hi]
    if len(w) < L:
        w = np.vstack([np.zeros((L - len(w), X.shape[1]), np.float32), w])
    return w


def build_units(db, sats, sw, eps):
    con = duckdb.connect(db, read_only=True)
    drag_by = load_drag_map()
    Xs, ys, gs, sevs = [], [], [], []
    inv = RANK_SEV
    for name, nid in sats:
        d = con.execute("SELECT epoch_utc, sma_km FROM raw_tle_archive WHERE norad_id=? "
                        "AND sma_km IS NOT NULL ORDER BY epoch_utc", [int(nid)]).fetchdf()
        if len(d) < L:
            continue
        ep = to_ns(d["epoch_utc"]); rr = run_all(d["sma_km"].to_numpy(float))
        drg = drag_by.get(int(nid), {})
        X = np.clip(np.nan_to_num(np.column_stack([
            np.abs(rr["cusum"]["scores"]), np.abs(rr["bocpd"]["scores"]),
            np.abs(rr["ssa"]["scores"]), np.abs(rr["mad3sig"]["scores"]),
            np.array([drg.get(e, 0.0) for e in ep]) / 0.10])).astype(np.float32), -50, 50)
        used = np.zeros(len(ep), bool)
        for times, rk in eps.get(int(nid), []):
            c = int(np.median(times))
            Xs.append(_window_at(X, ep, c)); ys.append(1); gs.append(int(nid)); sevs.append(inv[rk])
            i = int(np.argmin(np.abs(ep - c)))
            used[max(0, i - L // 2):i + L // 2] = True
        # 安靜窗：未用到的區段每 L 筆一窗
        idx = np.where(~used)[0]
        p = 0
        while p + L <= len(idx):
            seg = idx[p:p + L]
            if np.all(np.diff(seg) == 1):
                Xs.append(X[seg]); ys.append(0); gs.append(int(nid)); sevs.append("none")
            p += L
    con.close()
    return (np.asarray(Xs, np.float32), np.array(ys), np.array(gs), np.array(sevs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=config.SPACE_DB)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--max-sats", type=int, default=None)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    torch.manual_seed(args.seed); np.random.seed(args.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    sw = load_space_weather()
    reg = load_registry("data/url_registry.csv"); n2n = {v: k for k, v in reg["sat_name"].items()}
    sats = list(n2n.items())[: args.max_sats] if args.max_sats else list(n2n.items())
    truth_path = input_file("data/meme_truth/transitions_full_*.csv",
                            step="meme_truth", key="transitions_full")
    truth = pd.read_csv(truth_path)

    print(f"device={dev}  建 unit 序列窗（L={L}, patch={PATCH}）…")
    X, y, g, sev = build_units(args.db, sats, sw, episodes_by_sat(truth))
    # robust 標準化
    flat = X.reshape(-1, len(CH)); med = np.median(flat, 0)
    iqr = np.subtract(*np.percentile(flat, [75, 25], 0)) + 1e-6
    Xn = ((X - med) / iqr).astype(np.float32)
    print(f"  units {len(X)}（正 {int(y.sum())}/負 {int((y==0).sum())}），衛星 {len(np.unique(g))}")

    oof = np.zeros(len(y))
    for tr_i, te_i in GroupKFold(5).split(Xn, y, g):
        model = PatchTST(len(CH), L, PATCH).to(dev)
        opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
        pw = torch.tensor([(y[tr_i] == 0).sum() / max(1, (y[tr_i] == 1).sum())], device=dev)
        lossf = nn.BCEWithLogitsLoss(pos_weight=pw)
        Xtr = torch.tensor(Xn[tr_i], device=dev); ytr = torch.tensor(y[tr_i], dtype=torch.float32, device=dev)
        for ep in range(args.epochs):
            model.train(); perm = torch.randperm(len(Xtr), device=dev)
            for i in range(0, len(Xtr), 128):
                idx = perm[i:i + 128]
                loss = lossf(model(Xtr[idx]), ytr[idx])
                opt.zero_grad(); loss.backward(); opt.step()
        model.eval()
        with torch.no_grad():
            oof[te_i] = torch.sigmoid(model(torch.tensor(Xn[te_i], device=dev))).cpu().numpy()

    auc = roc_auc_score(y, oof); ap = average_precision_score(y, oof)
    thr = float(np.quantile(oof[y == 0], 0.95))
    print(f"\n=== PatchTST unit 級 OOF ===")
    print(f"  ROC-AUC={auc:.4f}  AP={ap:.4f}  (正 {int(y.sum())}/負 {int((y==0).sum())})")
    for s in ("large", "medium", "small"):
        m = (y == 1) & (sev == s)
        rc = float((oof[m] >= thr).mean()) if m.any() else 0.0
        print(f"  {s:6} recall@FPR5%={rc:.3f}  (n={int(m.sum())})")
    Path("models_patchtst").mkdir(exist_ok=True)
    torch.save({"med": med, "iqr": iqr, "L": L, "patch": PATCH, "channels": CH, "thr": thr},
               "models_patchtst/patchtst_meta.pt")
    print("\nmeta → models_patchtst/patchtst_meta.pt")


if __name__ == "__main__":
    main()
