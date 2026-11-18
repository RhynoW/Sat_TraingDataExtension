#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_fig_paperA_rv1.py — 論文 A 審查修訂版（Review V1）圖 1–3（中英 × 白底／黑底，600 dpi＋PDF）。

輸入：docs/paperA_reviewV1_analysis.py 之輸出（data/benchmark/paperA_reviewV1.json、paperA_rv1_*.csv）。
輸出：docs/figures_pub/fig_paperA_rv1_fig{1,2,3}/…_{zh,en}_{light,dark}.{png,pdf}

  圖 1：(A) 13 顆測高衛星之弧尺度 σ_res 與短間隔增量尺度 s_Δ 對高度（95% 弧段 bootstrap CI）；
        (B) 增量尺度隨實際時間間隔之變化 s(τ)/σ_res（逐星細線、跨星中位粗線）。
  圖 2：Jason-3 (A) 靜默弧段虛擬事件窗之 |步階| 經驗分布與門檻；(B) 觀測對真值 |Δa|。
  圖 3：(A) 沿軌 Δv 回復（乾淨括號，逐星）；(B) 法向 Δv：IDS 真值幅度對 TLE 法向 Δv 雜訊底。
用法：python docs/gen_fig_paperA_rv1.py
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docs"))
import fig_pub as fp  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, NullFormatter  # noqa: E402

B = ROOT / "data" / "benchmark"
J = json.loads((B / "paperA_reviewV1.json").read_text(encoding="utf-8"))
EST = pd.read_csv(B / "paperA_rv1_estimators.csv")
LAG = pd.read_csv(B / "paperA_rv1_lag.csv")
PS = pd.read_csv(B / "paperA_rv1_pseudo_steps.csv")
DET = pd.read_csv(B / "paperA_rv1_jason3_det.csv")
DV = pd.read_csv(B / "paperA_rv1_dv_vector.csv")
t = fp.t
C1, C2, C3, CG = "#1a6fc4", "#e8871a", "#2e9e5b", "#888888"
plain = FuncFormatter(lambda y, _: f"{y:g}")


def _ci(col):
    return np.array([ast.literal_eval(x) for x in EST[col]])


def fig1():
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.5, 5.2), gridspec_kw=dict(width_ratios=[1.25, 1]))
    h = EST.alt_km.values
    for col, cic, c, mk, lab, dx in (
            ("s_res_c", "ci_s_res_c", C1, "o", t("弧尺度 σ_res（去趨勢殘差）", "Arc-scale σ_res (detrended residual)"), -6),
            ("s_diff_dt", "ci_s_diff_dt", C2, "s", t("短間隔增量尺度 s_Δ（去趨勢相鄰差）", "Short-lag increment scale s_Δ (detrended adjacent difference)"), 6)):
        y = EST[col].values; ci = _ci(cic)
        a1.errorbar(h + dx, y, yerr=[y - ci[:, 0], ci[:, 1] - y], fmt=mk, color=c, ms=7, mec="white", mew=0.8,
                    ecolor=c, elinewidth=1.1, capsize=2.5, label=lab, zorder=4)
    OFF = {"HY-2A": (8, 6), "Envisat": (-8, 8), "SARAL": (10, 8), "Sentinel-3A": (8, -4), "Jason-3": (8, -4),
           "Sentinel-6A": (8, 4), "CryoSat-2": (8, 4)}
    for _, r in EST.iterrows():
        if r.sat in OFF:
            dx_, dy_ = OFF[r.sat]
            a1.annotate(r.sat, (r.alt_km - 6, r.s_res_c), xytext=(dx_, dy_), textcoords="offset points", fontsize=8.5,
                        color="#333333", ha="right" if dx_ < 0 else "left")
    a1.axhline(50, color=CG, ls="--", lw=1.2)
    a1.text(1350, 40, t("固定 σ = 50 m 假設", "Fixed σ = 50 m assumption"), ha="right", va="top", fontsize=9, color="#555555")
    a1.set_yscale("log"); a1.yaxis.set_major_formatter(plain); a1.yaxis.set_minor_formatter(NullFormatter())
    a1.set_ylim(0.03, 120); a1.set_xlim(690, 1380)
    a1.set_xlabel(t("高度（km）", "Altitude (km)")); a1.set_ylabel(t("尺度（m）", "Scale (m)"))
    a1.set_title(t("(A) 認證靜默弧段之 TLE 半長軸變異", "(A) TLE SMA variability on certified quiescent arcs"), fontsize=11)
    a1.grid(True, which="both", alpha=0.25); a1.legend(loc="upper right", bbox_to_anchor=(1.0, 0.80), fontsize=8.8, framealpha=0.95)
    bins = ["3-6h", "6-12h", "12-24h", "24-48h", "48-96h", "96-192h"]
    xc = np.array([4.24, 8.49, 16.97, 33.9, 67.9, 135.8])
    for s_, g in LAG.groupby("sat"):
        g = g.set_index("lag_bin").reindex(bins)
        a2.plot(xc, g.ratio.values, color=C1, alpha=0.28, lw=0.9)
    med = LAG.groupby("lag_bin").ratio.median().reindex(bins).values
    a2.plot(xc, med, color=C1, lw=2.6, marker="o", label=t("13 顆中位", "Median of 13 satellites"))
    a2.axhline(1.0, color=CG, ls=":", lw=1.2)
    a2.text(4, 1.03, t("獨立同分布高斯殘差之參考值", "Reference for i.i.d. Gaussian residuals"), fontsize=8.8, color="#555555", va="bottom")
    a2.set_xscale("log"); a2.xaxis.set_major_formatter(plain); a2.xaxis.set_minor_formatter(NullFormatter())
    a2.set_xticks([3, 6, 12, 24, 48, 96, 192])
    a2.set_ylim(0, 1.6)
    a2.set_xlabel(t("兩筆 TLE 之時間間隔 τ（h）", "Separation τ between element sets (h)"))
    a2.set_ylabel(t("s(τ) / σ_res", "s(τ) / σ_res"))
    a2.set_title(t("(B) 增量尺度隨間隔增大：相鄰誤差強烈正相關", "(B) Increment scale grows with separation"), fontsize=11)
    a2.grid(True, which="both", alpha=0.25); a2.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    return fig


def fig2():
    d = J["det"]; f = J["far"]["per_sat"]["Jason-3"]
    thr = d["thresholds_m"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.5, 5.2))
    v = np.sort(PS[PS.sat == "Jason-3"].step_m.abs().values)
    sf = 1.0 - np.arange(1, len(v) + 1) / len(v)
    a1.step(v, np.maximum(sf, 1e-4), where="post", color=C1, lw=1.8,
            label=t(f"虛擬事件窗 n = {len(v):,}（58 弧段）", f"Pseudo-event windows, n = {len(v):,} (58 arcs)"))
    for key, c, ls, lab in (("3sres", C2, "--", t(f"3σ_res = {thr['3sres']:.2f} m（誤報 {f['far_3sres']*100:.0f}%）",
                                                    f"3σ_res = {thr['3sres']:.2f} m (false alarm {f['far_3sres']*100:.0f}%)")),
                            ("p99", C3, "-", t(f"經驗 p99 = {thr['p99']:.2f} m", f"Empirical p99 = {thr['p99']:.2f} m")),
                            ("p997", "#7b4fbf", "-.", t(f"經驗 p99.7 = {thr['p997']:.2f} m", f"Empirical p99.7 = {thr['p997']:.2f} m"))):
        a1.axvline(thr[key], color=c, ls=ls, lw=1.5, label=lab)
    a1.axvline(150, color=CG, ls=":", lw=1.3, label=t("固定 σ = 50 m 之 3σ = 150 m", "3σ of fixed σ = 50 m: 150 m"))
    a1.set_xscale("log"); a1.set_yscale("log")
    for ax in (a1,):
        ax.xaxis.set_major_formatter(plain); ax.yaxis.set_major_formatter(plain)
        ax.xaxis.set_minor_formatter(NullFormatter()); ax.yaxis.set_minor_formatter(NullFormatter())
    a1.set_xlim(0.01, 300); a1.set_ylim(1e-4, 1.2)
    a1.set_xlabel(t("|步階判定量|（m）", "|Step statistic| (m)")); a1.set_ylabel(t("超越機率", "Exceedance probability"))
    a1.set_title(t("(A) 靜默弧段上之零假設分布（Jason-3）", "(A) Null distribution on maneuver-free arcs (Jason-3)"), fontsize=11)
    a1.grid(True, which="both", alpha=0.25); a1.legend(loc="lower left", fontsize=8.3, framealpha=0.95)
    nz = DET[DET.da_true_m > 0]; z = DET[DET.da_true_m == 0]
    det = nz.abs_obs_m >= thr["p99"]
    a2.scatter(nz.da_true_m[det], nz.abs_obs_m[det], s=34, color=C1, edgecolor="white", lw=0.6, zorder=4,
               label=t(f"真值非零、檢出（p99）{int(det.sum())}", f"Non-zero truth, detected (p99): {int(det.sum())}"))
    a2.scatter(nz.da_true_m[~det], nz.abs_obs_m[~det], s=70, marker="x", color="#c0392b", lw=1.8, zorder=5,
               label=t(f"真值非零、未檢出 {int((~det).sum())}", f"Non-zero truth, missed: {int((~det).sum())}"))
    if len(z):
        zr = z.iloc[0]
        a2.text(0.98, 0.04, t(f"另有 1 窗 SMA 真值為零（2016-01-21，兩次反向法向點火）：\n觀測 |步階| {zr.abs_obs_m:.0f} m，未繪於對數軸",
                              f"Not plotted: 1 window with zero logged SMA change (2016-01-21,\ntwo opposite normal burns); observed |step| {zr.abs_obs_m:.0f} m"),
                transform=a2.transAxes, ha="right", va="bottom", fontsize=8.2, color="#555555",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#bbbbbb", lw=0.8))
    lim = [0.2, 2e4]
    a2.plot(lim, lim, color=CG, lw=1.0, ls=":")
    a2.axhline(thr["p99"], color=C3, lw=1.3)
    a2.set_xscale("log"); a2.set_yscale("log"); a2.set_xlim(*lim); a2.set_ylim(*lim)
    for ax in (a2,):
        ax.xaxis.set_major_formatter(plain); ax.yaxis.set_major_formatter(plain)
        ax.xaxis.set_minor_formatter(NullFormatter()); ax.yaxis.set_minor_formatter(NullFormatter())
    a2.set_xlabel(t("IDS 真值 |Δa|（窗內淨變化，m）", "IDS truth |Δa| (net per window, m)"))
    a2.set_ylabel(t("TLE 觀測 |步階|（m）", "TLE-observed |step| (m)"))
    a2.set_title(t(f"(B) {len(nz)} 個 SMA 真值非零之機動窗", f"(B) {len(nz)} logged windows with non-zero SMA change"), fontsize=11)
    a2.grid(True, which="both", alpha=0.25); a2.legend(loc="upper left", fontsize=8.3, framealpha=0.95)
    fig.tight_layout()
    return fig


def fig3():
    X = J["xtrack"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.5, 5.2))
    c = DV[(DV.clean == 1) & (DV.dv_along_truth.abs() > 1e-6)]
    for s_, col, mk in (("CryoSat-2", C1, "o"), ("SWOT", C2, "s")):
        g = c[c.sat == s_]; st = X["along"]["clean"][s_]
        a1.scatter(g.dv_along_truth * 1e3, g.dv_along_rec * 1e3, s=22, marker=mk, color=col, alpha=0.75,
                   edgecolor="none", label=f"{s_}: n = {st['n']}, r = {st['r']:.3f}, " + t("斜率", "slope") + f" {st['slope']:.2f}")
    lim = [-60, 230]
    a1.plot(lim, lim, color=CG, ls=":", lw=1.0)
    a1.set_xlim(*lim); a1.set_ylim(*lim)
    a1.set_xlabel(t("IDS 真值沿軌 Δv（mm/s）", "IDS truth along-track Δv (mm/s)"))
    a1.set_ylabel(t("TLE 回復沿軌 Δv（mm/s）", "TLE-recovered along-track Δv (mm/s)"))
    a1.set_title(t("(A) 沿軌：乾淨括號", "(A) Along-track, clean brackets"), fontsize=11)
    a1.grid(True, alpha=0.25); a1.legend(loc="upper left", fontsize=8.6)
    cc = DV[DV.dv_cross_abs_truth > 0]
    nf = X["noise_quiet"]
    nq = J["rv2"]["normal"]["null_quantiles"]
    floor = np.mean([nq[s_]["median_planechange_dvN_mm_s"] for s_ in nq])
    a2.axhspan(0, floor, color=C2, alpha=0.13, lw=0)
    a2.axhline(floor, color=C2, lw=1.4,
               label=t(f"靜默弧段平面變化向量範數中位 ≈ {floor:.1f} mm/s（等效法向 Δv）",
                       f"Median quiet-arc plane-change norm ≈ {floor:.1f} mm/s (equivalent normal Δv)"))
    a2.axhline(3 * floor, color=C2, lw=1.2, ls="--", label=t(f"3 倍 ≈ {3*floor:.0f} mm/s（描述性參考，非偵測極限）", f"3× ≈ {3*floor:.0f} mm/s (descriptive reference, not a detection limit)"))
    for s_, col, mk in (("CryoSat-2", C1, "o"), ("SWOT", "#7b4fbf", "s")):
        g = cc[cc.sat == s_]
        a2.scatter(np.arange(len(g)) + (0 if s_ == "CryoSat-2" else len(cc[cc.sat == "CryoSat-2"])),
                   g.dv_cross_abs_truth * 1e3, s=14, marker=mk, color=col, alpha=0.8, edgecolor="none",
                   label=t(f"{s_} IDS 法向真值 |Δv_N|", f"{s_} IDS normal-component truth |Δv_N|"))
    a2.set_yscale("log"); a2.yaxis.set_major_formatter(plain); a2.yaxis.set_minor_formatter(NullFormatter())
    a2.set_ylim(0.005, 100)
    a2.set_xlabel(t("機動窗（依衛星排列）", "Maneuver window (grouped by satellite)"))
    a2.set_ylabel(t("|Δv_N|（mm/s）", "|Δv_N| (mm/s)"))
    a2.set_title(t("(B) 法向：真值遠低於 TLE 可解析尺度", "(B) Normal component: truth far below TLE resolution"), fontsize=11)
    a2.grid(True, which="both", alpha=0.25); a2.legend(loc="upper right", fontsize=8.3, framealpha=0.95)
    fig.tight_layout()
    return fig


if __name__ == "__main__":
    for fn, stem in ((fig1, "fig_paperA_rv1_fig1"), (fig2, "fig_paperA_rv1_fig2"), (fig3, "fig_paperA_rv1_fig3")):
        fp.export_variants(fn, stem)
