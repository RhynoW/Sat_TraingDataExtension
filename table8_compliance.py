#!/usr/bin/env python3
"""
table8_compliance.py — 契約表 8「預估訓練樣本效能評估值」合規判定
================================================================
對照兩種評估情境的驗收門檻，輸出 target / actual / verdict 對照：
  情境一 TLE 星曆（單一衛星評估）：Layer 3 LightGBM 分類器
  情境二 Starlink MEME 星曆（星系級評估）：統計偵測層（依嚴重度分層 recall + latency）

情境一數據來源：Orbital_Maneuver_V2/output/model_comparison.csv + 論文二混淆矩陣
              （TP=424 FN=11 FP=2 TN=1667）→ 可算 FPR / macro-F1；外部 Plan A Recall=39.7%。
情境二（本檔實算）：data/statistical_layer/per_epoch_stats_*.csv（cusum/ssa 逐 epoch 統計）
              以組合門檻 (cusum_stat≥5 或 ssa_resid_z≥3) 取偵測時刻，對 transitions_full
              之 da_severity（large/medium/small）逐事件配對（±24h），算分層 recall 與 latency。

輸出：data/benchmark/table8_compliance_{date}.csv
用法：python table8_compliance.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

from satdet import HOUR_NS, episodes_by_sat, input_file, record, to_ns
from satdet.common import RANK_SEV

TOL_H = 24.0  # 事件配對容差（＝TLE latency 目標）


def _f1(p, r):
    return 2 * p * r / (p + r) if (p + r) else 0.0


def constellation_stratified() -> dict:
    """統計偵測層（TLE 輸入）依嚴重度分層 recall + latency。"""
    pe = pd.read_csv(input_file("data/statistical_layer/per_epoch_stats_*.csv",
                                step="statistical_layer", key="per_epoch_stats"))
    pe.columns = [c.strip().lstrip("﻿") for c in pe.columns]
    pe["ns"] = to_ns(pe["epoch_utc"])
    pe["flag"] = (pe["cusum_stat"] >= 5.0) | (pe["ssa_resid_z"] >= 3.0)
    det_by = {s: np.sort(g["ns"].to_numpy())
              for s, g in pe[pe["flag"]].groupby("sat_name")}

    truth = pd.read_csv(input_file("data/meme_truth/transitions_full_*.csv",
                                   step="meme_truth", key="transitions_full"))
    eps_by = episodes_by_sat(truth, key="sat_name")   # episode＝48h 合併、max 嚴重度

    out = {sev: {"hit": 0, "n": 0, "lats": []} for sev in ("large", "medium", "small")}
    for s, eps in eps_by.items():
        dts = det_by.get(s)
        for times, rk in eps:
            b = out[RANK_SEV[rk]]
            b["n"] += 1
            if dts is None or not len(dts):
                continue
            best = float(np.abs(dts[:, None] - times[None, :]).min() / HOUR_NS)
            if best <= TOL_H:
                b["hit"] += 1; b["lats"].append(best)
    return {sev: {"recall": b["hit"] / b["n"] if b["n"] else 0.0, "n": b["n"],
                  "lat_med_h": float(np.median(b["lats"])) if b["lats"] else None}
            for sev, b in out.items()}


def verdict(actual, op, target):
    if actual is None:
        return "🔲 待測"
    ok = actual >= target if op == ">=" else actual <= target
    return "✅ 達標" if ok else "❌ 未達"


def main():
    rows = []

    # ── 情境一：TLE 單一衛星（Layer 3 LightGBM）───────────────────────────────
    m3 = pd.read_csv("Orbital_Maneuver_V2/output/model_comparison.csv")
    lg = m3[m3["model"].str.contains("LightGBM")].iloc[0]
    # 混淆矩陣（論文二 B.5.3）
    TP, FN, FP, TN = 424, 11, 2, 1667
    tpr = TP / (TP + FN); fpr = FP / (FP + TN)
    pos_f1 = _f1(TP / (TP + FP), TP / (TP + FN))
    neg_f1 = _f1(TN / (TN + FN), TN / (TN + FP))
    macro_f1 = (pos_f1 + neg_f1) / 2
    auc = float(lg["auc_roc"])
    ext_recall = 0.397  # Plan A MEME 外部驗證

    S1 = [
        ("TPR (內部測試集)", tpr, ">=", 0.85),
        ("TPR (外部 MEME Plan A)", ext_recall, ">=", 0.85),
        ("FPR", fpr, "<=", 0.15),
        ("ROC-AUC", auc, ">=", 0.90),
        ("Average Precision", 0.9956, ">=", 0.85),  # plot_roc_pr.py 5-fold OOF AUC-PR
        ("F1-score (macro)", macro_f1, ">=", 0.80),
    ]
    for name, act, op, tgt in S1:
        rows.append({"情境": "① TLE 單衛星", "指標": name, "target": f"{op}{tgt}",
                     "actual": None if act is None else round(act, 4), "判定": verdict(act, op, tgt)})

    # ── 情境二：MEME 星系級（融合評分器 fusion_scorer，unit 級 OOF）─────────────
    try:
        fm_path = input_file("data/benchmark/fusion_metrics_*.csv",
                             step="fusion_scorer", key="fusion_metrics")
    except FileNotFoundError:
        fm_path = None
    if fm_path:
        fm = pd.read_csv(fm_path).set_index("metric")["value"].to_dict()
        S2 = [("ROC-AUC", fm.get("ROC-AUC"), ">=", 0.90),
              ("Average Precision", fm.get("Average Precision"), ">=", 0.85),
              ("F1-score (macro)", fm.get("F1-macro"), ">=", 0.80),
              ("FPR", fm.get("FPR"), "<=", 0.05),
              ("TPR/Recall (large)", fm.get("TPR_large"), ">=", 0.90),
              ("TPR/Recall (medium)", fm.get("TPR_medium"), ">=", 0.80),
              ("TPR/Recall (small)", fm.get("TPR_small"), ">=", 0.65)]
        for name, act, op, tgt in S2:
            rows.append({"情境": "② MEME 星系級", "指標": name + "（融合器）", "target": f"{op}{tgt}",
                         "actual": None if act is None else round(act, 4), "判定": verdict(act, op, tgt)})
        # latency 由統計層 episode 配對估（融合器 latency 中位≈0.1h）
        strat = constellation_stratified()
        lat = strat["large"]["lat_med_h"]
        rows.append({"情境": "② MEME 星系級", "指標": "Latency 中位 (TLE)", "target": "<=24h",
                     "actual": None if lat is None else round(lat, 1), "判定": verdict(lat, "<=", 24.0)})
    else:
        rows.append({"情境": "② MEME 星系級", "指標": "（尚未跑 fusion_scorer.py）",
                     "target": "—", "actual": None, "判定": "🔲"})
    # 三項星系級分析（已建置 → constellation_anomaly.py）
    for nm in ["軌道面一致性 (同RAAN面 Δi std)", "批量機動識別 (同天>K顆)",
               "陣型誤差 (相對相位偏離)"]:
        rows.append({"情境": "② 星系級分析", "指標": nm, "target": "契約指定",
                     "actual": None, "判定": "✅ 已建置 (constellation_anomaly.py)"})

    df = pd.DataFrame(rows)
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    out = Path("data/benchmark") / f"table8_compliance_{date}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    record("table8_compliance", outputs={"table8_compliance": out})
    with pd.option_context("display.width", 200, "display.max_colwidth", 40):
        print(df.to_string(index=False))
    print(f"\n表 → {out}")
    # 分層 recall 摘要
    print("\n【情境二 分層 recall 詳情（統計層 cusum≥5∨ssa_z≥3, ±24h）】")
    for sev in ("large", "medium", "small"):
        s = strat[sev]
        lt = f"{s['lat_med_h']:.1f}h" if s["lat_med_h"] is not None else "—"
        print(f"  {sev:6} recall={s['recall']:.3f}  n={s['n']:5d}  中位latency={lt}")


if __name__ == "__main__":
    main()
