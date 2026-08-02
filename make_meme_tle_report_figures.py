#!/usr/bin/env python3
"""
make_meme_tle_report_figures.py
===============================
產生 MEME vs TLE 期中報告用圖表（study1/2/3 的 CSV → PNG）。

設計原則（依 dataviz 指南）：
  - 色盤採 Okabe-Ito 色盲友善配色，固定語意指派（不循環）：
      MEME / 純外推 / 參考基準 → 藍 #0072B2
      TLE（凍結/實務）        → 橘 #E69F00（低對比 → 搭配直接標註/圖例）
      機動污染 / 警示          → 朱紅 #D55E00
      輔助綠                   → #009E73
  - 單一 y 軸、細線、克制的格線、圖例＋選擇性直接標註。
  - 英文座標軸標籤（保證跨平台字型渲染）；中文說明置於報告 md。

輸出：docs/meme_tle_report/figs/*.png
"""
from __future__ import annotations

import glob
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

# ── 色盤與樣式 ────────────────────────────────────────────────────────────────
C_MEME   = "#0072B2"   # 藍：MEME / 純外推 / 參考
C_TLE    = "#E69F00"   # 橘：TLE
C_MAN    = "#D55E00"   # 朱紅：機動 / 警示
C_GREEN  = "#009E73"
INK      = "#1a1a1a"
MUTED    = "#6b6b6b"
GRID     = "#e6e6e6"

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": INK, "ytick.color": INK,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 11, "axes.titlesize": 12.5, "axes.titleweight": "bold",
    "legend.frameon": False, "figure.dpi": 150,
})

ROOT   = Path("f:/GitHub/Sat_TraingDataExtension")
FIGDIR = ROOT / "docs" / "meme_tle_report" / "figs"
FIGDIR.mkdir(parents=True, exist_ok=True)


def _latest(pattern: str) -> Path | None:
    hits = sorted(glob.glob(str(ROOT / pattern)))
    return Path(hits[-1]) if hits else None


def _save(fig, name: str):
    out = FIGDIR / name
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[fig] {out}")


# ── 圖1：概念示意圖（MEME 檔結構 / 重疊 / 首筆真值 / 斷點）────────────────────
def fig_concept():
    fig, ax = plt.subplots(figsize=(10, 4.6))
    # 每個檔以水平長條表示（涵蓋 72h），每 8h 發布一次、重疊 ~88%
    starts = [0, 8, 16, 24, 32]          # 發布時刻（小時）
    for i, s in enumerate(starts):
        y = -i * 0.8
        ax.add_patch(mpatches.Rectangle(
            (s, y - 0.28), 72, 0.56,
            linewidth=1.2, edgecolor=C_MEME, facecolor=C_MEME, alpha=0.16))
        # 首筆（外推齡 0 ≈ 近真值）以實心點標示
        ax.plot(s, y, "o", color=C_MEME, ms=9, zorder=5)
        if i == 0:
            ax.annotate("first row ≈ least-extrapolated\n(near-truth snapshot)",
                        (s, y), (s - 1, y + 1.15), color=C_MEME, fontsize=9,
                        ha="left", arrowprops=dict(arrowstyle="->", color=C_MEME))
        ax.text(s + 72 + 1, y, f"file {i+1}\n(72 h span)", va="center",
                fontsize=8, color=MUTED)
    # 斷點示意
    ax.axvspan(40, 40, color="white")
    ax.annotate("", (24, -4.4), (24, -3.6))
    ax.text(35, -4.0,
            "adjacent files ~8 h apart, ~88% overlap → dense de-dup timeline",
            fontsize=9, color=INK)
    ax.set_xlim(-6, 120)
    ax.set_ylim(-4.6, 1.8)
    ax.set_yticks([])
    ax.set_xlabel("Time since first file epoch (hours)")
    ax.set_title("Fig 1 — SpaceX MEME ephemeris structure: 72 h files, 1-min cadence, ~8 h re-release")
    ax.grid(axis="y", visible=False)
    _save(fig, "fig1_concept.png")


# ── 圖2：Study1 — TLE 誤差分布（ECDF + 隨齡增長）──────────────────────────────
def fig_study1():
    f = _latest("data/study1/study1_tle_residuals_*.csv")
    if not f:
        print("[skip] study1 CSV 不存在"); return
    df = pd.read_csv(f)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.8))

    # (a) ECDF
    x = np.sort(df["pos_err_km"].clip(upper=df["pos_err_km"].quantile(0.99)).values)
    y = np.arange(1, len(x) + 1) / len(x)
    ax1.plot(x, y, color=C_TLE, lw=2.2)
    for pct, lbl in [(50, "P50"), (95, "P95")]:
        v = float(np.percentile(df["pos_err_km"], pct))
        ax1.axvline(v, color=MUTED, ls="--", lw=1)
        ax1.text(v, 0.05, f" {lbl}\n {v:.1f} km", fontsize=8.5, color=INK)
    ax1.set_xlabel("TLE position error vs MEME near-truth (km)")
    ax1.set_ylabel("Cumulative fraction")
    ax1.set_title("(a) TLE error distribution (ECDF)")
    ax1.set_ylim(0, 1.02)

    # (b) error vs TLE age（分箱中位數 + IQR 帶）——限 ≤2 天（其後樣本稀疏）
    d = df[df["tle_age_days"] <= 2].copy()
    d["b"] = (d["tle_age_days"] // 0.25) * 0.25
    g = d.groupby("b")["pos_err_km"].agg(p25=lambda s: s.quantile(.25),
                                         p50="median",
                                         p75=lambda s: s.quantile(.75)).reset_index()
    ax2.fill_between(g["b"] + 0.125, g["p25"], g["p75"], color=C_TLE, alpha=0.18,
                     label="IQR (25–75%)")
    ax2.plot(g["b"] + 0.125, g["p50"], color=C_TLE, lw=2.2, marker="o", ms=5,
             label="Median")
    ax2.set_xlabel("TLE age at prediction time (days)")
    ax2.set_ylabel("TLE position error (km)")
    ax2.set_title("(b) Error grows with TLE age")
    ax2.legend()
    fig.suptitle("Fig 2 — Study 1: public-TLE error against MEME first-row near-truth (50 satellites)",
                 fontsize=12.5, fontweight="bold", y=1.02)
    _save(fig, "fig2_study1_tle_error.png")


# ── 圖3：Study2 — MEME 自我預測誤差 vs 外推時程 ──────────────────────────────
def fig_study2():
    f = _latest("data/study2/study2_meme_residuals_*.csv")
    if not f:
        print("[skip] study2 CSV 不存在"); return
    df = pd.read_csv(f)
    df["hb"] = (np.round(df["horizon_h"] / 8.0) * 8).astype(int)
    g = df.groupby("hb")["pos_err_km"].agg(p50="median",
                                           p90=lambda s: s.quantile(.9)).reset_index()
    g = g[g["hb"] > 0]
    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.fill_between(g["hb"], 0, g["p90"], color=C_MEME, alpha=0.12, label="P90")
    ax.plot(g["hb"], g["p50"], color=C_MEME, lw=2.4, marker="o", ms=6, label="Median")
    for _, r in g.iterrows():
        if int(r["hb"]) in (8, 24, 48, 72):
            ax.annotate(f"{r['p50']:.2f} km", (r["hb"], r["p50"]),
                        (r["hb"], r["p50"] + g["p90"].max()*0.05),
                        fontsize=8.5, color=INK, ha="center")
    ax.set_xlabel("Prediction horizon (hours)")
    ax.set_ylabel("MEME self-prediction position error (km)")
    ax.set_title("Fig 3 — Study 2: MEME vs MEME self-prediction error grows with horizon (0–72 h)")
    ax.legend()
    _save(fig, "fig3_study2_meme_self.png")


# ── 圖4：Study3A — TLE 凍結外推退化曲線 1–7 天 ──────────────────────────────
def fig_study3a():
    f = _latest("data/study3/study3_frozen_curve_*.csv")
    if not f:
        print("[skip] study3 frozen CSV 不存在"); return
    df = pd.read_csv(f)
    clean = df[~df["maneuver_contaminated"]]
    g = clean.groupby("horizon_days")["pos_err_km"].agg(
        p50="median", p90=lambda s: s.quantile(.9)).reset_index()
    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.fill_between(g["horizon_days"], 0, g["p90"], color=C_TLE, alpha=0.15, label="P90")
    ax.plot(g["horizon_days"], g["p50"], color=C_TLE, lw=2.4, marker="o", ms=6,
            label="Median (maneuvers removed)")
    for _, r in g.iterrows():
        ax.annotate(f"{r['p50']:.0f}", (r["horizon_days"], r["p50"]),
                    (r["horizon_days"], r["p50"] + g["p90"].max()*0.04),
                    fontsize=8.5, color=INK, ha="center")
    ax.set_xlabel("Frozen-TLE extrapolation horizon (days)")
    ax.set_ylabel("TLE position error (km)")
    ax.set_title("Fig 4 — Study 3A: frozen-TLE degradation, 1–7 days (50 satellites)")
    ax.legend()
    _save(fig, "fig4_study3a_frozen.png")


# ── 圖5：Study3B — 斷點 spot-check（機動 vs 純外推）────────────────────────
def fig_study3b():
    f = _latest("data/study3/study3_gap_spotcheck_*.csv")
    if not f:
        print("[skip] study3 gap CSV 不存在"); return
    g = pd.read_csv(f)
    clean = g[~g["maneuvered"]]["pos_err_km"].values
    man   = g[g["maneuvered"]]["pos_err_km"].values
    fig, ax = plt.subplots(figsize=(8.6, 5.4))

    data = [clean, man]
    labels = [f"Pure extrapolation\n(no maneuver, n={len(clean)})",
              f"Maneuvered in gap\n(n={len(man)})"]
    colors = [C_MEME, C_MAN]
    # strip + median 標記（log-y）
    for i, (d, col) in enumerate(zip(data, colors)):
        xj = np.random.default_rng(0).normal(i, 0.06, len(d))
        ax.scatter(xj, d, s=34, color=col, alpha=0.55, edgecolor="white",
                   linewidth=0.5, zorder=3)
        med = np.median(d)
        ax.plot([i-0.28, i+0.28], [med, med], color=col, lw=3, zorder=4)
        ax.annotate(f"median\n{med:.0f} km", (i+0.32, med), fontsize=9,
                    color=INK, va="center")
    ax.set_yscale("log")
    ax.set_xticks([0, 1]); ax.set_xticklabels(labels)
    ax.set_ylabel("7-day frozen-TLE position error (km, log scale)")
    ax.set_title("Fig 5 — Study 3B: gap spot-check — maneuver filtering separates two populations")
    ax.grid(axis="x", visible=False)
    # 對比倍數註記
    ax.text(0.5, man.max()*1.1, f"×{np.median(man)/np.median(clean):.0f} median gap",
            ha="center", fontsize=10, color=C_MAN, fontweight="bold")
    _save(fig, "fig5_study3b_gap.png")


# ── 圖6：綜合層級比較（最有意義的比較項目）──────────────────────────────────
def fig_hierarchy():
    """單圖對比三種預測的『誤差 vs 時程』：MEME自我預測、TLE實務(隨齡)、TLE凍結。"""
    fig, ax = plt.subplots(figsize=(9.4, 5.6))

    # MEME 自我預測（0–3 天）
    f2 = _latest("data/study2/study2_meme_residuals_*.csv")
    if f2:
        d = pd.read_csv(f2)
        d["hd"] = np.round(d["horizon_h"] / 8.0) * 8 / 24.0
        gg = d.groupby("hd")["pos_err_km"].median().reset_index()
        gg = gg[gg["hd"] > 0]
        ax.plot(gg["hd"], gg["pos_err_km"], color=C_MEME, lw=2.4, marker="o",
                ms=5, label="MEME vs MEME (self-prediction)")

    # TLE 實務：隨 TLE 齡（study1）——限 ≤1.5 天（其後樣本稀疏且含機動污染）
    f1 = _latest("data/study1/study1_tle_residuals_*.csv")
    if f1:
        d = pd.read_csv(f1); d = d[d["tle_age_days"] <= 1.5].copy()
        d["b"] = (d["tle_age_days"] // 0.25) * 0.25 + 0.125
        gg = d.groupby("b")["pos_err_km"].median().reset_index()
        ax.plot(gg["b"], gg["pos_err_km"], color=C_GREEN, lw=2.4, marker="s",
                ms=5, label="TLE operational (freshest available, ≤1.5 d)")

    # TLE 凍結（study3A）
    f3 = _latest("data/study3/study3_frozen_curve_*.csv")
    if f3:
        d = pd.read_csv(f3); d = d[~d["maneuver_contaminated"]]
        gg = d.groupby("horizon_days")["pos_err_km"].median().reset_index()
        ax.plot(gg["horizon_days"], gg["pos_err_km"], color=C_TLE, lw=2.4,
                marker="^", ms=6, label="TLE frozen (single TLE, aged)")

    ax.set_yscale("log")
    ax.set_xlabel("Prediction / extrapolation horizon (days)")
    ax.set_ylabel("Median position error (km, log scale)")
    ax.set_title("Fig 6 — Prediction-error hierarchy: MEME ≪ operational TLE ≪ frozen TLE")
    ax.legend(loc="upper left")
    _save(fig, "fig6_hierarchy.png")


if __name__ == "__main__":
    fig_concept()
    fig_study1()
    fig_study2()
    fig_study3a()
    fig_study3b()
    fig_hierarchy()
    print("\n完成，圖表位於", FIGDIR)
