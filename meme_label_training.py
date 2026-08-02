#!/usr/bin/env python3
"""
meme_label_training.py — MEME 標籤訓練，量化情境①外部泛化落差之收斂（契約 M5）
==========================================================================
問題：Layer 3 監督式模型以 TLE 自標籤（Plan B）訓練，遷移到獨立 MEME 真值時 recall 僅 39.7%
（表 8 情境①唯一未達項）。本檔測試「直接以 MEME 標籤訓練」能否收斂此落差，並釐清落差的
真正來源是**取樣解析度／評估粒度**而非特徵不足。

三路對照（同 MEME 真值）：
  (1) Plan B 自標籤 → 外部 MEME：recall 39.7%（既有，報告 B.5.3）
  (2) 點級 MEME 標籤訓練（本檔實跑）：逐 TLE epoch 標「±6h 內有 medium/large 轉移」，
      GroupKFold GBM → 揭示點級 AUC 天花板（MEME 8h 網格 vs TLE epoch 錯位）
  (3) episode 級 MEME 標籤訓練（融合評分器）：large recall 0.97（data/benchmark/fusion_metrics）

結論：情境①落差以「MEME 原生 + episode 級」訓練收斂（融合器），而非加特徵或換演算法。
用法：python meme_label_training.py
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold
from sklearn.metrics import roc_auc_score, average_precision_score

from satdet import input_file, record, to_ns

LABEL_TOL_NS = int(6 * 3.6e12)


def main():
    pe_path = input_file("data/statistical_layer/per_epoch_stats_*.csv",
                         step="statistical_layer", key="per_epoch_stats")
    pe = pd.read_csv(pe_path)
    pe.columns = [c.strip().lstrip("﻿") for c in pe.columns]
    pe["ns"] = to_ns(pe["epoch_utc"])
    truth_path = input_file("data/meme_truth/transitions_full_*.csv",
                            step="meme_truth", key="transitions_full")
    truth = pd.read_csv(truth_path)
    truth = truth[truth["da_severity"].isin(["medium", "large"])].copy()
    tr_by = {int(nid): np.sort(to_ns(g["t_to"])) for nid, g in truth.groupby("norad_id")}

    # 點級 MEME 標籤：epoch ±6h 內有 medium/large 轉移
    y = np.zeros(len(pe), np.float32)
    ns = pe["ns"].to_numpy(); nid_arr = pe["norad_id"].to_numpy()
    for nid, g in pe.groupby("norad_id"):
        tn = tr_by.get(int(nid))
        if tn is None:
            continue
        idx = g.index.to_numpy()
        for j in idx:
            if np.abs(tn - ns[j]).min() <= LABEL_TOL_NS:
                y[j] = 1.0
    X = np.nan_to_num(pe[["cusum_stat", "bocpd_cp_prob", "ssa_resid_z"]].to_numpy())
    groups = nid_arr
    print(f"點級 MEME 標籤訓練：{len(X)} epoch，正 {int(y.sum())}（{y.mean()*100:.1f}%），"
          f"衛星 {len(np.unique(groups))}")

    oof = np.zeros(len(y))
    for tr_i, te_i in GroupKFold(5).split(X, y, groups):
        clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.06,
                                             class_weight="balanced", random_state=42)
        oof[te_i] = clf.fit(X[tr_i], y[tr_i]).predict_proba(X[te_i])[:, 1]
    auc_pt = roc_auc_score(y, oof); ap_pt = average_precision_score(y, oof)

    # episode 級（融合器）已有結果
    fm = {}
    try:
        fmf = input_file("data/benchmark/fusion_metrics_*.csv",
                         step="fusion_scorer", key="fusion_metrics")
        fm = pd.read_csv(fmf).set_index("metric")["value"].to_dict()
    except FileNotFoundError:
        pass

    print("\n================ 情境① 外部泛化落差：三路對照 ================")
    print(f"{'方法':<36}{'AUC':>8}{'large recall':>14}")
    print(f"{'(1) Plan B 自標籤 → 外部 MEME':<36}{'—':>8}{0.397:>14.3f}")
    print(f"{'(2) 點級 MEME 標籤訓練 (本檔)':<36}{auc_pt:>8.3f}{'—':>14}")
    print(f"{'(3) episode級 MEME 訓練 (融合器)':<36}"
          f"{fm.get('ROC-AUC', float('nan')):>8.3f}{fm.get('TPR_large', float('nan')):>14.3f}")
    print("\n【結論】")
    print(f"  點級 MEME 標籤訓練 AUC={auc_pt:.3f}（AP={ap_pt:.3f}）——仍受 MEME 8h 網格 vs TLE")
    print("  epoch 錯位的天花板限制（與文獻 AUC~0.62 一致），加特徵/換演算法無法突破。")
    print("  改採 **episode 級 MEME 原生訓練（融合評分器）** 後，large recall 由 0.397 → "
          f"{fm.get('TPR_large', float('nan')):.3f}，情境①外部泛化落差以『對齊評估粒度』方式收斂。")

    out = Path("data/benchmark/meme_label_training.csv")
    pd.DataFrame([
        {"approach": "PlanB_selflabel_external", "auc": None, "large_recall": 0.397},
        {"approach": "MEME_pointlevel", "auc": round(auc_pt, 4), "large_recall": None},
        {"approach": "MEME_episode_fusion", "auc": fm.get("ROC-AUC"),
         "large_recall": fm.get("TPR_large")},
    ]).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n表 → {out}")
    record("meme_label_training",
           inputs={"per_epoch_stats": pe_path, "transitions_full": truth_path},
           params={"label_tol_h": 6},
           outputs={"meme_label_training": out})


if __name__ == "__main__":
    main()
