#!/usr/bin/env python3
"""
lstm_autoencoder.py — 無監督 LSTM 自編碼器機動偵測器（契約 M3 深度學習項目）
==========================================================================
定位（與失敗的 bi-GRU 序列標註器 [project_bigru_labeler] 不同）：
  bi-GRU 是**監督式**、需 MEME 標籤、在點級退化＋OOD 慘敗。
  本檔是**無監督重構式**：LSTM-AE 學習「正常軌道演化」的物理殘差序列，
  重構誤差高 = 異常/機動。無需標籤、regime-agnostic（同 Model 2 精神但帶時序記憶）。

輸入：ml_model2_anomaly.physical_residuals 的 z_drag/z_di/z_de 三通道（丟棄壞掉的 z_draan），
      切成長度 L 的滑窗序列。訓練 seq2seq LSTM-AE 最小化重構 MSE。
評估：unit 級（機動 episode 窗 vs 等寬安靜窗）以窗最大重構誤差為分數 → ROC-AUC + 分層 recall。

用法：python lstm_autoencoder.py [--epochs 30] [--max-sats N]
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
from sklearn.metrics import roc_auc_score, average_precision_score

from ml_model2_anomaly import physical_residuals, _load
from atmospheric_drag import load_space_weather
from compare_tle_vs_ephemeris import load_registry
from satdet import (TOL_NS, config, episodes_by_sat, episode_masks,
                    input_file, quiet_blocks, to_ns)
from satdet.common import RANK_SEV, SEV_RANK as _RANK

CH = ["z_drag", "z_di", "z_de"]
L = 16                      # 序列窗長


class LSTMAutoencoder(nn.Module):
    def __init__(self, n_ch=3, hidden=32, layers=1):
        super().__init__()
        self.enc = nn.LSTM(n_ch, hidden, layers, batch_first=True)
        self.dec = nn.LSTM(hidden, hidden, layers, batch_first=True)
        self.out = nn.Linear(hidden, n_ch)

    def forward(self, x):                       # x:[B,L,C]
        _, (h, _) = self.enc(x)                 # h:[layers,B,H]
        z = h[-1].unsqueeze(1).repeat(1, x.size(1), 1)   # [B,L,H] 重複潛向量
        d, _ = self.dec(z)
        return self.out(d)


def build_windows(db, sats, sw):
    """回傳 windows[N,L,3]、每窗 (norad, epoch_end_ns)。"""
    con = duckdb.connect(db, read_only=True)
    W, meta = [], []
    for name, nid in sats:
        r = physical_residuals(_load(con, nid), sw)
        if r.empty or len(r) < L + 2:
            continue
        X = np.clip(np.nan_to_num(r[CH].to_numpy(np.float32)), -50, 50)
        ep = to_ns(r["epoch"])
        for s in range(0, len(X) - L + 1):
            W.append(X[s:s + L]); meta.append((int(nid), ep[s + L - 1]))
    con.close()
    return np.asarray(W, np.float32), meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=config.SPACE_DB)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--max-sats", type=int, default=None)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    torch.manual_seed(args.seed); np.random.seed(args.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    sw = load_space_weather()
    reg = load_registry("data/url_registry.csv"); n2n = {v: k for k, v in reg["sat_name"].items()}
    sats = list(n2n.items())[: args.max_sats] if args.max_sats else list(n2n.items())
    print(f"device={dev}  建視窗（L={L}, 通道{CH}）…")
    W, meta = build_windows(args.db, sats, sw)
    print(f"  視窗 {len(W)}，衛星 {len({m[0] for m in meta})}")

    # 標準化（用全體 median/IQR，robust）
    flat = W.reshape(-1, len(CH))
    med = np.median(flat, 0); iqr = np.subtract(*np.percentile(flat, [75, 25], 0)) + 1e-6
    Wn = ((W - med) / iqr).astype(np.float32)

    # 衛星分組 80/20（避免同星洩漏）
    rng = np.random.default_rng(args.seed)
    sat_ids = np.array([m[0] for m in meta])
    uniq = np.unique(sat_ids); rng.shuffle(uniq)
    val_s = set(uniq[: max(1, len(uniq) // 5)].tolist())
    tr_m = np.array([s not in val_s for s in sat_ids])

    Xtr = torch.tensor(Wn[tr_m], device=dev)
    model = LSTMAutoencoder(n_ch=len(CH)).to(dev)
    opt = torch.optim.Adam(model.parameters(), lr=2e-3)
    lossf = nn.MSELoss()
    print("訓練 LSTM-AE（僅用訓練衛星、無標籤）…")
    bs = 256
    for ep in range(args.epochs):
        model.train(); perm = torch.randperm(len(Xtr), device=dev); tot = 0.0
        for i in range(0, len(Xtr), bs):
            idx = perm[i:i + bs]; xb = Xtr[idx]
            loss = lossf(model(xb), xb)
            opt.zero_grad(); loss.backward(); opt.step()
            tot += loss.item() * len(idx)
        if (ep + 1) % 10 == 0 or ep == 0:
            print(f"  epoch {ep+1:>3}/{args.epochs}  recon_mse={tot/len(Xtr):.4f}")

    # 每窗重構誤差
    model.eval()
    with torch.no_grad():
        err = np.concatenate([
            ((model(torch.tensor(Wn[i:i+1024], device=dev)) -
              torch.tensor(Wn[i:i+1024], device=dev)) ** 2).mean((1, 2)).cpu().numpy()
            for i in range(0, len(Wn), 1024)])

    # ── 評估：unit 級（僅 val 衛星）─────────────────────────────────────────────
    truth_path = input_file("data/meme_truth/transitions_full_*.csv",
                            step="meme_truth", key="transitions_full")
    truth = pd.read_csv(truth_path)
    eps = episodes_by_sat(truth)
    dfw = pd.DataFrame({"nid": sat_ids, "ep": [m[1] for m in meta], "err": err})
    dfw = dfw[dfw["nid"].isin(val_s)]

    # 正 unit＝落在 episode ±24h 的窗（取窗集合最大誤差）；負＝其餘窗切等寬塊
    y, score, sev = [], [], []
    for nid, g in dfw.groupby("nid"):
        e = g["ep"].to_numpy(); er = g["err"].to_numpy(); order = np.argsort(e)
        e, er = e[order], er[order]
        masks, assigned = episode_masks(e, eps.get(nid, []), TOL_NS)
        for m, rk, _lat in masks:
            y.append(1); score.append(float(er[m].max())); sev.append(RANK_SEV[rk])
        for w in quiet_blocks(e, np.where(~assigned)[0], 2 * TOL_NS):
            y.append(0); score.append(float(er[w].max())); sev.append("none")
    y = np.array(y); score = np.array(score); sev = np.array(sev)
    auc = roc_auc_score(y, score); ap = average_precision_score(y, score)
    thr = float(np.quantile(score[y == 0], 0.95))
    print(f"\n=== LSTM-AE unit 級（val 衛星）===")
    print(f"  ROC-AUC={auc:.4f}  AP={ap:.4f}  (正 {int(y.sum())}/負 {int((y==0).sum())})")
    for s in ("large", "medium", "small"):
        m = (y == 1) & (sev == s)
        rc = float((score[m] >= thr).mean()) if m.any() else 0.0
        print(f"  {s:6} recall@FPR5%={rc:.3f}  (n={int(m.sum())})")

    Path("models_lstm_ae").mkdir(exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "med": med, "iqr": iqr,
                "channels": CH, "L": L, "thr": thr}, "models_lstm_ae/lstm_ae.pt")
    print("\n模型 → models_lstm_ae/lstm_ae.pt")
    print("結論：無監督重構式 AE，作為 Model 2 的時序版對照；與監督式 bi-GRU 的 OOD 病理不同。")


if __name__ == "__main__":
    main()
