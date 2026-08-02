#!/usr/bin/env python3
"""
fusion_fpr_sweep.py — 情境②#7：融合器操作點掃描與「small 召回 vs FPR」權衡曲線
==============================================================================
低成本、免重訓：直接沿用融合評分器之 per-unit OOF 連續分數（three_layer_perunit_*.csv），
在契約情境② 之 unit 集（含 n=11 small）上掃描 FPR 操作點，量各嚴重度**窗級（unit 級）召回**
隨 FPR 之變化，產出：
  · small/medium/large 召回 vs FPR 表；
  · 達 small 召回 ≥0.65 所需之 FPR（若可達）與對應誤報代價；
  · 報告用曲線圖 fig_small_recall_vs_fpr.png。

窗級（非 episode 級）：每個 unit 為一筆，正 unit＝機動窗、負 unit＝等寬安靜窗——即報告主口徑，
非被 naive 對照否定之 episode 級指標。
用法：python fusion_fpr_sweep.py
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

from satdet import fpr_floor_threshold

SEV = {3: "large", 2: "medium", 1: "small"}


def main():
    p = sorted(glob.glob("data/benchmark/three_layer_perunit_*.csv"))[-1]
    d = pd.read_csv(p)
    s = d["l3_score"].to_numpy(float)
    y = d["label"].to_numpy(int)
    sev = d["sev"].to_numpy(int)
    neg = s[y == 0]
    n_small = int((sev == 1).sum())
    print(f"融合器操作點掃描 ← {Path(p).name}｜正 {int((y==1).sum())}"
          f"（large {int((sev==3).sum())}/medium {int((sev==2).sum())}/small {n_small}）、負 {len(neg)}\n")

    budgets = [0.02, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
    rows = []
    for b in budgets:
        thr = fpr_floor_threshold(neg, b)
        pred = (s >= thr).astype(int)
        fpr = float(pred[y == 0].mean())
        rec = {}
        for k, name in SEV.items():
            m = (y == 1) & (sev == k)
            rec[name] = float(pred[m].mean()) if m.sum() else float("nan")
        rec_all = float(pred[y == 1].mean())
        rows.append({"fpr_budget": b, "fpr_actual": round(fpr, 4), "thr": round(float(thr), 4),
                     "rec_small": round(rec["small"], 3), "rec_medium": round(rec["medium"], 3),
                     "rec_large": round(rec["large"], 3), "rec_all": round(rec_all, 3),
                     "small_hit": int(round(rec["small"] * n_small))})
    R = pd.DataFrame(rows)

    print("=" * 82)
    print(f"{'FPR預算':>8}{'實際FPR':>9}{'門檻':>9}{'small召回':>10}{'(抓/11)':>8}"
          f"{'medium':>9}{'large':>9}{'總召回':>9}")
    print("-" * 82)
    for _, r in R.iterrows():
        print(f"{r.fpr_budget:>8.2f}{r.fpr_actual:>9.3f}{r.thr:>9.3f}{r.rec_small:>10.3f}"
              f"{f'{r.small_hit}/{n_small}':>8}{r.rec_medium:>9.3f}{r.rec_large:>9.3f}{r.rec_all:>9.3f}")
    print("=" * 82)

    # 達 small≥0.65 所需 FPR
    ok = R[R.rec_small >= 0.65]
    if len(ok):
        r0 = ok.iloc[0]
        print(f"★ small 召回達 0.65：需 FPR≥{r0.fpr_actual:.3f}"
              f"（門檻 {r0.thr:.3f}，抓 {r0.small_hit}/{n_small}）——代價為誤報率由 5% 升至 {r0.fpr_actual*100:.0f}%")
    else:
        best = R.loc[R.rec_small.idxmax()]
        print(f"★ 掃描範圍內 small 召回最高 {best.rec_small:.3f}（FPR {best.fpr_actual:.3f}，抓 {best.small_hit}/{n_small}）"
              f"——未達 0.65；反映 small 貼近雜訊底（SNR<2）之物理下限，須精密星曆治本（F.2）")
    r5 = R.iloc[1]
    print(f"對照｜報告操作點 FPR≤0.05：small 召回 {r5.rec_small:.3f}（{r5.small_hit}/{n_small}）——"
          f"嚴格操作點之保守取捨，非能力上限")

    out = Path("data/benchmark/fusion_fpr_sweep_20260724.csv")
    R.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}")

    # ── 曲線圖 ──
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Microsoft YaHei", "SimHei", "sans-serif"]
        plt.rcParams["axes.unicode_minus"] = False
        fig, ax = plt.subplots(figsize=(8.2, 5.0), dpi=200)
        for col, name, c in [("rec_small", "small (n=11)", "#c0392b"),
                             ("rec_medium", "medium", "#9a6a00"),
                             ("rec_large", "large", "#1f7a4d")]:
            ax.plot(R.fpr_actual, R[col], "o-", color=c, lw=2, ms=6, label=name)
        ax.axhline(0.65, ls="--", color="#8a8f98", lw=1.2)
        ax.text(R.fpr_actual.max(), 0.665, "門檻 0.65", ha="right", fontsize=9, color="#55585f")
        ax.axvline(0.05, ls=":", color="#8a8f98", lw=1.2)
        ax.text(0.052, 0.02, "報告操作點 FPR≤0.05", fontsize=9, color="#55585f")
        ax.set_xlabel("實際 FPR（誤報率）"); ax.set_ylabel("窗級召回率")
        ax.set_title("融合器操作點掃描：small/medium/large 召回 vs FPR（情境② unit 集）",
                     fontsize=13, color="#1f2a44", fontweight="bold")
        ax.set_ylim(-0.03, 1.03); ax.grid(alpha=0.25); ax.legend(loc="lower right")
        figp = "docs/fig_small_recall_vs_fpr.png"
        fig.savefig(figp, bbox_inches="tight", facecolor="white", pad_inches=0.25)
        print(f"曲線圖 → {figp}")
    except Exception as e:
        print(f"（繪圖略過：{e}）")


if __name__ == "__main__":
    main()
