#!/usr/bin/env python3
"""
train_l3_common_arena.py
========================
離線訓練「逐 epoch 滑動窗」版 L3 融合評分器，供 StoryMap 案例二十七的 L3 決策動畫做即時推論。

為何不直接用擂台的 L3：擂台（three_layer_common_eval.py）的 unit 是「整個機動 episode ±24 h」，
是「已知這裡有事件時」的評分（AUC 0.98 見報告 §13.2），並非逐 epoch 的串流偵測器；models_fusion/
fusion_scorer.pkl 為 2026-07-15 舊版，餵入現行特徵時在安靜窗上 94.5% 亮燈，亦不可用。
故此處以 15 維通道特徵（5 通道 × max/mean/p90，窗＝該 epoch 置中 ±24 h）＋ 2 維階躍特徵（窗內最大 |Δa|、σ-SNR），HGB 超參數同擂台，
改成對每個原始 TLE epoch 都打分；標籤＝該 epoch ±24 h 內有無 MEME medium+ 機動轉移。
衛星分組 GroupKFold(5) 取 OOF；門檻＝負窗上 FPR≤0.05（與擂台操作點相同）。

輸出：models_fusion/l3_common_arena.pkl（clf, feats, channels, thr, oof_auc, recall_at_thr, n_units,
      fpr_budget, l2_best, l2_thr, l2_auc, l2_recall, l1_recall, l1_fpr, mode）
用法：python train_l3_common_arena.py
"""
from __future__ import annotations

import glob
import sys

import duckdb
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import maneuver_strategies_july as ms
import three_layer_common_eval as T3E
from compare_tle_vs_ephemeris import load_registry
from satdet import config, episodes_by_sat, fpr_floor_threshold, load_drag_map, to_ns
from statistical_detectors import run_all

OUT = "models_fusion/l3_common_arena.pkl"
HALF_NS = int(24 * 3.6e12)


def main():
    tp = sorted(glob.glob("data/meme_truth/transitions_full_*.csv"))[-1]
    truth = pd.read_csv(tp)
    truth["t_to"] = pd.to_datetime(truth["t_to"], utc=True, format="ISO8601")
    eps_by = episodes_by_sat(truth)
    reg = load_registry("data/url_registry.csv")
    n2n = {v: k for k, v in reg["sat_name"].items()}
    sats = list(n2n.items())
    drag_by = load_drag_map()
    con = duckdb.connect(config.SPACE_DB, read_only=True)
    print(f"truth={tp}；{len(sats)} 顆；逐 epoch 建窗 …", flush=True)

    rows_F, rows_y, rows_g, rows_l1 = [], [], [], []
    for name, nid in sats:
        df = con.execute(
            "SELECT epoch_utc AS epoch, sma_km, inclination_deg, eccentricity, raan_deg, bstar "
            "FROM raw_tle_archive WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc",
            [int(nid)]).fetchdf()
        if len(df) < 30:
            continue
        df["epoch"] = pd.to_datetime(df["epoch"], utc=True, format="ISO8601")
        ep = to_ns(df["epoch"])
        sma = df["sma_km"].to_numpy(float)
        r = run_all(sma)
        drg = drag_by.get(int(nid), {})
        C = np.nan_to_num(np.column_stack([
            np.abs(r["cusum"]["scores"]), np.abs(r["bocpd"]["scores"]),
            np.abs(r["ssa"]["scores"]), np.abs(r["mad3sig"]["scores"]),
            np.array([drg.get(e, 0.0) for e in ep]) / 0.10]))
        lo = np.searchsorted(ep, ep - HALF_NS, side="left")
        hi = np.searchsorted(ep, ep + HALF_NS, side="right")
        # 階躍特徵（擂台基線「σ 正規化 |Δa|」AUC 0.878）：窗內最大 |Δa|（m）與其相對該星雜訊 σ 的 SNR
        dsma = np.diff(sma)
        sig_m = 1.4826 * float(np.median(np.abs(dsma - np.median(dsma)))) * 1000.0
        ad = np.r_[0.0, np.abs(dsma)] * 1000.0
        F = np.zeros((len(ep), 17))
        for j in range(len(ep)):
            sub = C[lo[j]:hi[j]]
            for i in range(5):
                col = sub[:, i]
                F[j, 3 * i:3 * i + 3] = (col.max(), col.mean(), np.percentile(col, 90))
            seg = ad[lo[j] + 1:hi[j]]
            dm_ = float(seg.max()) if len(seg) else 0.0
            F[j, 15] = dm_
            F[j, 16] = dm_ / sig_m if sig_m > 0 else 0.0
        # 標籤：±24 h 內有 medium+ 機動轉移
        y = np.zeros(len(ep), bool)
        for times, rk in eps_by.get(int(nid), []):
            for t in times:
                y |= np.abs(ep - t) <= HALF_NS
        # L1：P1–P6 combined 旗標，窗內任一（與 L3 同窗）
        orbit = ms.classify_orbit(float(sma[-1]), float(df["eccentricity"].iloc[-1]),
                                  float(df["inclination_deg"].iloc[-1]))
        trn = ms.build_transitions(df)
        l1_pt = np.zeros(len(ep), bool)
        if len(trn):
            comb = ms.apply_strategies(trn, orbit).get("combined", np.array([], bool))
            if len(comb):
                l1_pt = np.isin(ep, to_ns(trn["epoch"])[comb])
        l1w = np.array([l1_pt[lo[j]:hi[j]].any() for j in range(len(ep))])
        rows_F.append(F)
        rows_y.append(y)
        rows_g.append(np.full(len(ep), int(nid)))
        rows_l1.append(l1w)
    con.close()

    F = np.vstack(rows_F)
    y = np.concatenate(rows_y)
    groups = np.concatenate(rows_g)
    l1 = np.concatenate(rows_l1)
    neg = ~y
    feats = [f"f_{c}_{st}" for c in T3E.CH for st in ("max", "mean", "p90")] + ["da_max_m", "snr_window"]
    print(f"窗 {len(y)}：正 {int(y.sum())}、負 {int(neg.sum())}、衛星 {len(set(groups))}", flush=True)

    oof = np.zeros(len(y))
    for tr_i, te_i in GroupKFold(5).split(F, y, groups):
        oof[te_i] = HistGradientBoostingClassifier(**T3E.HGB).fit(F[tr_i], y[tr_i]).predict_proba(F[te_i])[:, 1]
    thr = float(fpr_floor_threshold(oof[neg], 0.05))
    auc = float(roc_auc_score(y, oof))
    rec = float((oof[y] >= thr).mean())
    print(f"L3 OOF AUC={auc:.3f}  thr(FPR≤0.05)={thr:.4f}  recall@thr={rec:.3f}", flush=True)

    # L2：最佳單統計通道（窗內 max，AUC 最高），同為 FPR≤0.05 門檻
    l2_aucs = {c: float(roc_auc_score(y, F[:, 3 * i])) for i, c in enumerate(T3E.CH[:4])}
    l2_best = max(l2_aucs, key=l2_aucs.get)
    col = F[:, 3 * T3E.CH.index(l2_best)]
    l2_thr = float(fpr_floor_threshold(col[neg], 0.05))
    l2_rec = float((col[y] >= l2_thr).mean())
    print(f"L2 最佳單通道 {l2_best}（AUC {l2_aucs[l2_best]:.3f}），thr={l2_thr:.3f}，recall={l2_rec:.3f}", flush=True)
    l1_rec, l1_fpr = float(l1[y].mean()), float(l1[neg].mean())
    print(f"單特徵 σ-SNR AUC={roc_auc_score(y, F[:, 16]):.3f}", flush=True)
    print(f"L1 規則：recall={l1_rec:.3f}  FPR={l1_fpr:.3f}", flush=True)

    clf = HistGradientBoostingClassifier(**T3E.HGB).fit(F, y)
    joblib.dump({"clf": clf, "feats": feats, "channels": T3E.CH, "thr": thr, "oof_auc": auc,
                 "recall_at_thr": rec, "n_units": int(len(y)), "fpr_budget": 0.05,
                 "l2_best": l2_best, "l2_thr": l2_thr, "l2_auc": l2_aucs[l2_best], "l2_recall": l2_rec,
                 "l1_recall": l1_rec, "l1_fpr": l1_fpr, "mode": "sliding_epoch_centered_pm24h", "n_feat": 17,
                 "auc_snr_only": float(roc_auc_score(y, F[:, 16]))}, OUT)
    print("saved →", OUT)


if __name__ == "__main__":
    main()
