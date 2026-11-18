#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_fig_paperC_threshold_oos.py — 論文 C：阻力殘差門檻方案之樣本外驗證圖。

只讀 docs/paperC_numbers.py oos 之輸出（不重算）：
  data/benchmark/paperC_thr_oos_bins_20261118.csv
面板：(a) 衛星分組 5-fold（重複 20 次）各檔樣本外誤報率（中位數與 5–95 百分位）；
      (b) 時間切分（2024-01～2025-06 決定門檻、2025-07 以後測試；B_eff 亦只以訓練期校準）；
      (c) 衛星分組 5-fold 之 90% 可偵測下限（注入測試）。
用法：python docs/gen_fig_paperC_threshold_oos.py          → docs/fig_paperC_threshold_oos.png（600 dpi）＋ .pdf（英文白底）
      python docs/gen_fig_paperC_threshold_oos.py --pub    → docs/figures_pub/fig_paperC_threshold_oos/ 中英 × 白底／黑底四版本
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fs7_fig_style as st  # noqa: E402
from fig_pub import t  # noqa: E402

BM = st.BM
SRC = BM / "paperC_thr_oos_bins_20261118.csv"
TARGET = 0.43
FLOOR = 0.02            # 誤報率 0 之繪圖位置（對數軸）
SCH = [("A", st.RED, "o", ("A 現行 0.30 km", "A fixed 0.30 km")),
       ("B", st.BLUE, "s", ("B 等誤報率查表", "B per-bin lookup")),
       ("C", st.GREEN, "^", ("C 高度公式", "C log-linear formula")),
       ("D", st.PURPLE, "D", ("D 單調包絡（建議）", "D monotone envelope (proposed)")),
       ("E", st.ORANGE, "v", ("E 保序迴歸", "E isotonic fit"))]


def _panel_fp(ax, g, title, band=True):
    for k, (s, c, m, lab) in enumerate(SCH):
        d = g[g.scheme == s].sort_values("hbin")
        x = d.hbin + (k - 2) * 6
        y = d.fp_med.clip(lower=FLOOR)
        if band and (d.fp_p95 > d.fp_p05).any():
            ax.vlines(x, d.fp_p05.clip(lower=FLOOR), d.fp_p95.clip(lower=FLOOR), color=c, lw=0.6, alpha=0.6)
        ax.plot(x, y, color=c, marker=m, ms=2.6, lw=0.8 if s != "D" else 1.2, label=t(*lab))
        z = d.evaluable == False  # noqa: E712
        ax.scatter(x[z], y[z], s=14, facecolors="none", edgecolors="#9ca3af", lw=0.5, zorder=4)
    ax.axhline(TARGET, color=st.GRAY, ls="--", lw=0.7)
    ax.set_yscale("log")
    ax.set_ylim(FLOOR * 0.8, 150)
    ax.set_yticks([0.02, 0.1, 0.43, 1, 10, 100])
    ax.set_yticklabels([t("0", "0"), "0.1", "0.43", "1", "10", "100"])
    ax.set_xticks(range(300, 1001, 100))
    ax.set_xlabel(t("高度檔（km）", "Altitude bin (km)"))
    ax.set_ylabel(t("樣本外誤報／千星日", "Out-of-sample false alarms\nper 1,000 satellite-days"))
    ax.set_title(title, loc="left")
    ax.grid(alpha=0.3, which="major")


def draw():
    import matplotlib.pyplot as plt
    A = pd.read_csv(SRC)
    A = A[A.hbin > 0]
    fig, ax = plt.subplots(1, 3, figsize=(st.DOUBLE, 6.6 * st.CM))
    _panel_fp(ax[0], A[A["eval"] == "sat-5fold"],
              t("(a) 衛星分組 5-fold（20 次）", "(a) Satellite-grouped 5-fold CV (20 repeats)"))
    _panel_fp(ax[1], A[A["eval"] == "time early→late (B_eff train)"],
              t("(b) 時間切分：≤2025-06 訓練、≥2025-07 測試", "(b) Time split: train ≤ 2025-06, test ≥ 2025-07"), band=False)
    g = A[A["eval"] == "sat-5fold"]
    for k, (s, c, m, lab) in enumerate(SCH):
        d = g[g.scheme == s].sort_values("hbin")
        ax[2].plot(d.hbin, d.min90_med, color=c, marker=m, ms=2.6, lw=0.8 if s != "D" else 1.2, label=t(*lab))
    ax[2].set_yscale("log")
    ax[2].set_yticks([0.05, 0.1, 0.2, 0.5, 1, 2])
    ax[2].set_yticklabels(["0.05", "0.1", "0.2", "0.5", "1", "2"])
    ax[2].set_xticks(range(300, 1001, 100))
    ax[2].set_xlabel(t("高度檔（km）", "Altitude bin (km)"))
    ax[2].set_ylabel(t("90% 偵測之最小 |Δa|（km）", "Minimum |Δa| for 90% detection (km)"))
    ax[2].set_title(t("(c) 注入測試（5-fold 測試集）", "(c) Injection test (5-fold test sets)"), loc="left")
    ax[2].grid(alpha=0.3, which="major")
    h, l = ax[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=5, bbox_to_anchor=(0.5, -0.02), fontsize=6.3)
    fig.text(0.01, -0.075, t("虛線：目標每千星日 0.43 件。空心灰圈：訓練或測試星日不足 1000/0.43 之檔（一件即超過目標，無法驗證）。(a) 直線為 20 次重複之 5–95 百分位。",
                             "Dashed line: target 0.43 false alarms per 1,000 satellite-days. Open grey circles: bins with fewer than 1000/0.43 training or test satellite-days (a single event "
                             "exceeds the target). Vertical lines in (a): 5th–95th percentiles over 20 repeats."),
             fontsize=5.8, color=st.GRAY)
    fig.tight_layout(rect=(0, 0.08, 1, 1), w_pad=1.2)
    return fig


if __name__ == "__main__":
    st.run({"fig_paperC_threshold_oos": draw})
