#!/usr/bin/env python3
"""
fs7_noise_floor_map_v2.py — 軌道域雜訊底圖強化版：理論等高線 + 實測散點
=======================================================================
理論面：本研究之名目雜訊底模型

    σ_th(h) = sqrt( σ0² + ( A · exp( −(h−400)/H ) )² )

σ0＝高空 TLE 量測底（阻力可忽略時的殘差尺度）、A/H＝阻力項幅度與大氣尺度高，
三參數以 58 顆實測 σ（log 殘差最小平方）擬合。模型不含傾角相依→等高線垂直，
散點跨 24–99° 是否貼合垂直等高線，即「高度主導、傾角無關」之檢驗。

輸入：data/benchmark/tle_noise_floor_map.csv（fs7_noise_floor_map.py 產出）
輸出：docs/fig_tle_noise_floor_map_contour.png
用法：python fs7_noise_floor_map_v2.py
      python fs7_noise_floor_map_v2.py --pub   （另輸出 docs/figures_pub/fig_tle_noise_floor_map_contour/ 中英×白底／黑底四版本）
"""
from __future__ import annotations

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "docs"))
import fig_pub as fp  # noqa: E402
from fig_pub import t  # noqa: E402

GROUP_ZH = {
    "FORMOSAT-7 (calibration)": "福衛七號（校準）",
    "14 altimetry (benchmark)": "14 顆測高衛星（基準）",
    "9 hold-out (SPOT/GRACE/S6B)": "9 顆保留驗證（SPOT／GRACE／S6B）",
    "Starlink sample (train domain)": "Starlink 樣本（訓練域）",
}

MARKERS = {
    "FORMOSAT-7 (calibration)": ("o", 95),
    "14 altimetry (benchmark)": ("s", 75),
    "9 hold-out (SPOT/GRACE/S6B)": ("^", 95),
    "Starlink sample (train domain)": (".", 30),
}


def sigma_th(h, p):
    s0, A, H = p
    return np.sqrt(s0 ** 2 + (A * np.exp(-(h - 400.0) / H)) ** 2)


def main():
    d = pd.read_csv("data/benchmark/tle_noise_floor_map.csv")
    d = d.dropna(subset=["sigma_m"])
    # CSV 存檔取 2 位小數，極安靜星可能捨入為 0 → 以 0.02 m 為量測下限
    d["sigma_m"] = d["sigma_m"].clip(lower=0.02)
    h, sig = d["alt_km"].values, d["sigma_m"].values

    def resid(p):
        return np.log10(sigma_th(h, np.abs(p))) - np.log10(sig)
    fit = least_squares(resid, x0=[0.05, 10.0, 120.0], loss="soft_l1")
    s0, A, H = np.abs(fit.x)
    r2 = 1 - np.sum(resid(fit.x) ** 2) / np.sum(
        (np.log10(sig) - np.log10(sig).mean()) ** 2)
    print(f"理論擬合：σ0={s0:.3f} m  A={A:.1f} m  H={H:.0f} km  (log 空間 R²={r2:.2f})")

    import matplotlib
    matplotlib.use("Agg")

    def draw():
        return draw_map(d, sig, s0, A, H, r2)

    if fp.wants_pub():
        fp.export_variants(draw, "fig_tle_noise_floor_map_contour")
        return
    prev = fp.lang()
    fp.set_lang("en")            # 原圖為英文版；預設輸出維持英文
    try:
        draw().savefig("docs/fig_tle_noise_floor_map_contour.png", dpi=150)
    finally:
        fp.set_lang(prev)
    print("輸出：docs/fig_tle_noise_floor_map_contour.png")


def draw_map(d, sig, s0, A, H, r2):
    """高度–傾角軌道域圖＋理論雜訊底等高線；回傳 Figure。"""
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    hh = np.linspace(380, 1420, 300)
    ii = np.linspace(18, 103, 60)
    HH, II = np.meshgrid(hh, ii)
    ZZ = sigma_th(HH, (s0, A, H))

    fig, ax = plt.subplots(figsize=(10, 6.4))
    norm = LogNorm(vmin=0.02, vmax=max(sig.max(), ZZ.max()))
    cmap = plt.get_cmap("Blues")

    cf = ax.contourf(HH, II, ZZ, levels=np.logspace(np.log10(0.02), np.log10(20), 25),
                     cmap=cmap, norm=norm, alpha=0.28, zorder=0)
    lv = [0.05, 0.1, 0.3, 1, 3, 10]
    cl = ax.contour(HH, II, ZZ, levels=lv, colors="#5f6368", linewidths=0.7, zorder=1)
    ax.clabel(cl, fmt=lambda v: f"{v:g} m", fontsize=7.5, inline=True)

    sc = None
    for gname, (mk, ms) in MARKERS.items():
        sub = d[d["group"] == gname]
        if not len(sub):
            continue
        sc = ax.scatter(sub["alt_km"], sub["inc_deg"], c=sub["sigma_m"],
                        cmap=cmap, norm=norm, marker=mk, s=ms,
                        edgecolors="#3c4043", linewidths=0.7, label=t(GROUP_ZH[gname], gname), zorder=3)
    cb = fig.colorbar(sc, ax=ax, pad=0.015)
    cb.set_label(t("名目 TLE 雜訊底 σ（m，對數尺度）", "Nominal TLE noise floor σ (m, log scale)"))
    if not fp.is_en():   # 微軟正黑體缺 U+2212，10^{-1} 之負號會成缺字方塊 → 中文版改用一般數字刻度
        from matplotlib.ticker import FuncFormatter
        from matplotlib.ticker import NullFormatter
        cb.formatter = FuncFormatter(lambda v, _: f"{v:g}")
        cb.minorformatter = NullFormatter()
        cb.update_ticks()

    ann = [(t("福衛七號", "FORMOSAT-7"), 555, 24, (12, -3)),
           ("Starlink", 545, 53.1, (12, -3)),
           ("GRACE / GRACE-FO", 480, 89, (-30, 10)),
           ("SPOT 2/3/4/5", 700, 98.7, (-40, 12)),
           (t("太陽同步測高衛星（Envisat／S3／SARAL）", "Sun-sync altimetry (Envisat/S3/SARAL)"), 830, 98.5, (8, -16)),
           ("CryoSat-2", 725, 92, (10, -3)),
           ("SWOT", 900, 77.5, (10, -3)),
           ("HY-2C/2D", 950, 66, (-20, -16)),
           ("Jason-1/2/3 / TOPEX / S6A·S6B", 1335, 66, (-190, 12))]
    for txt, x, y, off in ann:
        ax.annotate(txt, (x, y), textcoords="offset points", xytext=off,
                    fontsize=8, color="#3c4043", zorder=4)

    ax.set_xlabel(t("軌道高度（km，TLE 歷史中位數）", "Orbital altitude above ground (km, median of TLE history)"))
    ax.set_ylabel(t("軌道傾角（度）", "Orbital inclination (deg)"))
    formula = rf"$\sigma_{{th}}(h)=\sqrt{{\sigma_0^2+(A\,e^{{-(h-400)/H}})^2}}$"
    ax.set_title(t("高度–傾角軌道域圖與理論雜訊底等高線\n"
                   + formula + rf"，$\sigma_0$={s0:.2f} m、A={A:.0f} m、H={H:.0f} km"
                   rf"（對數空間 $R^2$={r2:.2f}；不含傾角相依）",
                   "Altitude–inclination domain map with theoretical noise-floor contours\n"
                   + formula + ",  "
                   rf"$\sigma_0$={s0:.2f} m, A={A:.0f} m, H={H:.0f} km  "
                   rf"(log-space $R^2$={r2:.2f}; no inclination dependence)"),
                 fontsize=10.5)
    ax.set_xlim(380, 1420)
    ax.set_ylim(18, 103)
    ax.grid(alpha=0.15, zorder=0)
    ax.legend(loc="lower right", fontsize=8, framealpha=0.95)
    fig.tight_layout()
    return fig


if __name__ == "__main__":
    main()
