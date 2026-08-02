#!/usr/bin/env python3
"""
benchmark_v1.py — 三層偵測器統一指標基準（Benchmark v1）
========================================================
契約交付物「Benchmark v1」。將散落於三處的指標彙整為單一對照表 + 圖：
  Layer 1（閾值規則 P1–P6）  ← leo_annotator/output/recall_at_n_report.txt
  Layer 2（統計 CUSUM/BOCPD/SSA/MAD）← data/statistical_layer/metrics_*.csv
  Layer 3（監督式 RF/XGB/LightGBM）  ← Orbital_Maneuver_V2/output/model_comparison.csv

**重要（誠實揭露）**：三層並非在同一測試集/同一 Ground Truth 上評估，指標**不可直接橫向比較**——
  L1：推進能力代理 GT，54 天、14,090 顆；
  L2：MEME 精密星曆 V 型事件（1,758 episodes、283 顆），輸入分 TLE / MEME 兩種序列；
  L3：Plan B 自標籤獨立測試集；另列 Plan A（MEME 外部驗證）以揭露泛化落差。
表中 `eval_basis` 欄明確標註各列的評估基礎。

輸出：data/benchmark/benchmark_v1_{date}.csv、docs/benchmark_v1.png
用法：python benchmark_v1.py
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

ROOT = Path(".")


def _f1(p, r):
    p, r = p / 100.0, r / 100.0
    return round(200 * p * r / (p + r), 1) if (p + r) else 0.0


def collect() -> pd.DataFrame:
    rows = []

    # ── Layer 1（規則 P1–P6，推進代理 GT）──────────────────────────────────────
    # 來源：leo_annotator/output/recall_at_n_report.txt（總體 TP=2744 FP=156 FN=7442）
    rows += [
        {"layer": "L1 規則", "detector": "P1–P6 (overall)", "input": "TLE",
         "eval_basis": "推進代理GT · 54d · 14,090顆", "precision": 94.6, "recall": 26.9,
         "aux": "FAR 5.4%", "n_truth": 10186},
        {"layer": "L1 規則", "detector": "P1–P6 @Top-1000", "input": "TLE",
         "eval_basis": "推進代理GT · Recall@N 排名", "precision": 98.2, "recall": 9.6,
         "aux": "P@1000", "n_truth": 10186},
    ]

    # ── Layer 2（統計，vs MEME episodes）─────────────────────────────────────────
    m2p = sorted((ROOT / "data" / "statistical_layer").glob("metrics_*.csv"))
    if m2p:
        m2 = pd.read_csv(m2p[-1])
        m2.columns = [c.strip().lstrip("﻿") for c in m2.columns]
        for _, r in m2.iterrows():
            rows.append({
                "layer": "L2 統計", "detector": r["method"].upper(), "input": r["input"],
                "eval_basis": f"MEME episodes · {int(r['n_truth'])}事件 · {int(r['n_sat'])}顆",
                "precision": round(float(r["precision"]) * 100, 1),
                "recall": round(float(r["recall"]) * 100, 1),
                "aux": f"lead {r['lead_time_h_median']:.0f}h", "n_truth": int(r["n_truth"])})

    # ── Layer 3（監督式，Plan B 測試集）─────────────────────────────────────────
    m3p = ROOT / "Orbital_Maneuver_V2" / "output" / "model_comparison.csv"
    if m3p.exists():
        m3 = pd.read_csv(m3p)
        for _, r in m3.iterrows():
            nm = str(r["model"])
            rows.append({
                "layer": "L3 監督式", "detector": nm.replace(" (ours)", ""), "input": "TLE特徵",
                "eval_basis": "Plan B 自標籤測試集 · 2,104顆",
                "precision": round(float(r["precision"]), 1), "recall": round(float(r["recall"]), 1),
                "aux": f"AUC {float(r['auc_roc']):.3f}", "n_truth": 435})
    # L3 外部驗證（Plan A MEME）——泛化落差誠實揭露
    rows.append({"layer": "L3 監督式", "detector": "LightGBM (MEME 外部)", "input": "TLE特徵",
                 "eval_basis": "Plan A · MEME真值 · 252顆（外部）", "precision": 100.0,
                 "recall": 39.7, "aux": "泛化落差", "n_truth": 252})

    df = pd.DataFrame(rows)
    df["f1"] = [_f1(p, r) for p, r in zip(df["precision"], df["recall"])]
    return df[["layer", "detector", "input", "eval_basis", "precision", "recall", "f1", "aux", "n_truth"]]


def plot(df: pd.DataFrame, out_png: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for f in ["Microsoft JhengHei", "Microsoft YaHei", "SimHei", "Noto Sans CJK TC"]:
        if any(f.lower() in x.name.lower() for x in font_manager.fontManager.ttflist):
            plt.rcParams["font.sans-serif"] = [f]; break
    plt.rcParams["axes.unicode_minus"] = False

    lab = df["detector"] + "  (" + df["input"] + ")"
    y = np.arange(len(df))[::-1]
    lc = {"L1 規則": "#0072B2", "L2 統計": "#E69F00", "L3 監督式": "#009E73"}
    colors = [lc[l] for l in df["layer"]]

    fig, ax = plt.subplots(figsize=(11, 0.52 * len(df) + 1.8))
    h = 0.38
    ax.barh(y + h / 2, df["recall"], height=h, color=colors, alpha=.55, label="Recall")
    ax.barh(y - h / 2, df["precision"], height=h, color=colors, alpha=1.0, label="Precision")
    for yi, p, r in zip(y, df["precision"], df["recall"]):
        ax.text(p + 1, yi - h / 2, f"{p:.0f}", va="center", fontsize=8)
        ax.text(r + 1, yi + h / 2, f"{r:.0f}", va="center", fontsize=8, color="#444")
    ax.set_yticks(y); ax.set_yticklabels(lab, fontsize=9)
    ax.set_xlabel("Precision（深）／Recall（淺）  %"); ax.set_xlim(0, 108)
    ax.set_title("Benchmark v1 — 三層偵測器統一指標\n"
                 "註：三層評估基礎不同（見 eval_basis），不可直接橫向比較", fontsize=11)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=c, label=l) for l, c in lc.items()],
              loc="lower right", fontsize=9, framealpha=.9)
    ax.grid(axis="x", alpha=.25); ax.set_axisbelow(True)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    print(f"圖 → {out_png}")


def main():
    df = collect()
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    out_dir = ROOT / "data" / "benchmark"; out_dir.mkdir(parents=True, exist_ok=True)
    csv = out_dir / f"benchmark_v1_{date}.csv"
    df.to_csv(csv, index=False, encoding="utf-8-sig")
    print(f"表 → {csv}  ({len(df)} 列)\n")
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(df.to_string(index=False))
    plot(df, ROOT / "docs" / "benchmark_v1.png")


if __name__ == "__main__":
    main()
