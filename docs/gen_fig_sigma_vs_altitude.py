#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_fig_sigma_vs_altitude.py — 重繪 Figure 1（中英文兩版）。
資料來自 ids_truth_set/ids_sigma_calibration.csv；加入 FORMOSAT-3 在地對照與 Starlink 帶。
標籤要求：Sentinel-3B 置於數據點正上方；Sentinel-6A 置於數據點右上方。
輸出：docs/fig_sigma_vs_altitude_EN.png（英）、docs/fig_sigma_vs_altitude.png（中）
--pub：另輸出 docs/figures_pub/fig_sigma_vs_altitude/ 之中英 × 白底／黑底四版本（600 dpi PNG＋PDF）
--paper：論文 A 修訂版（預設輸出保持不變）→ docs/fig_sigma_vs_altitude_paperA.png（英）、
         docs/fig_sigma_vs_altitude_paperA_ZH.png（中）；加 --pub 則輸出
         docs/figures_pub/fig_sigma_vs_altitude_paperA/ 四版本。修訂內容：
         · 移除「Starlink σ ≈ 24–75 m」紅框，改畫 TLE 對 SpaceX 星曆 |Δa| 之中位數與 IQR
           （data/benchmark/starlink_tle_meme_error_floor_20260918.csv；高度帶取逐點高度 P1–P99），
           並標明為不同物理量；
         · 灰虛線標籤改為 "Fixed 50 m threshold"；
         · 福衛三號點改用 docs/paperA_numbers.py 重算之代表值（六星 σ_diff 中位、高度中位）。"""
import sys
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "ids_truth_set" / "ids_sigma_calibration.csv"
DOCS = Path(__file__).resolve().parent

D = pd.read_csv(CSV)
D["sigma_m"] = D["sigma_diff_km"] * 1000.0
D = D.sort_values("alt_km").reset_index(drop=True)
MED = float(np.median(D["sigma_m"]))

# 標籤位置（dx, dy 點偏移；ha/va）。Sentinel-3B 正上方；Sentinel-6A 右上方。
LBL = {
    "CryoSat-2":   (-16,  6, "right",  "center"),
    "Envisat":     (-14, 14, "right",  "bottom"),
    "SARAL":       (-14,-16, "right",  "top"),
    "Sentinel-3A": (  4,-20, "left",   "top"),
    "Sentinel-3B": (  0, 24, "center", "bottom"),   # 正上方
    "SWOT":        (  6, 16, "left",   "bottom"),
    "HY-2C":       ( 16,  8, "left",   "center"),
    "HY-2D":       ( 14,-16, "left",   "top"),
    "HY-2A":       ( 16,  4, "left",   "center"),
    "Jason-1":     (  0, 20, "center", "bottom"),
    "Jason-2":     (-16,-10, "right",  "top"),
    "Jason-3":     ( 14,-14, "left",   "top"),
    "Sentinel-6A": ( 30, 20, "left",   "bottom"),   # 右上方
}

TXT = {
    "en": dict(
        font=["Arial", "DejaVu Sans"],
        title="TLE-derived SMA noise floor versus altitude (DORIS-certified quiescent arcs)",
        xlabel="Altitude (km)",
        ylabel="TLE-derived SMA noise σ_diff (m, log scale)",
        starlink="Starlink LEO band\nσ ≈ 24–75 m",
        ref="Reference-table assumption: 50 m",
        median=f"median σ_diff = {MED:.1f} m (13 satellites)",
        ids="IDS altimetry satellites (13; certified quiescent arcs)",
        f3="FORMOSAT-3 (788 km, non-propulsive; ~1 m control)",
        f3lab="FORMOSAT-3",
        out=DOCS / "fig_sigma_vs_altitude_EN.png"),
    "zh": dict(
        font=["Microsoft JhengHei", "Yu Gothic", "DejaVu Sans"],
        title="TLE 半長軸雜訊底隨高度之關係（DORIS 認證安靜期實測）",
        xlabel="高度 (km)",
        ylabel="TLE 半長軸雜訊 σ_diff（m，對數軸）",
        starlink="Starlink 低軌帶\nσ 約 24–75 m",
        ref="既有門檻表假設：50 m",
        median=f"13 顆 σ_diff 中位 = {MED:.1f} m",
        ids="IDS 測高衛星（13 顆，認證安靜期實測）",
        f3="福衛三號（788 km、無推進，在地對照 約 1 m）",
        f3lab="福衛三號",
        out=DOCS / "fig_sigma_vs_altitude.png"),
}

F3_ALT, F3_SIG = 788.0, 0.95
PAPER = "--paper" in sys.argv


def _paper_inputs():
    """論文 A 版之 Starlink 帶與福衛三號代表值（皆由檔案計算，不寫死）。"""
    import json
    sl = pd.read_csv(ROOT / "data" / "benchmark" / "starlink_tle_meme_error_floor_20260918.csv",
                     usecols=["a_meme_km", "da_km"])
    ada = sl["da_km"].abs() * 1000.0
    alt = sl["a_meme_km"] - 6378.137
    out = dict(sl_lo=float(alt.quantile(0.01)), sl_hi=float(alt.quantile(0.99)),
               sl_med=float(ada.median()), sl_q1=float(ada.quantile(0.25)), sl_q3=float(ada.quantile(0.75)),
               f3_alt=786.5, f3_sig=1.04)   # 後二者為 paperA_numbers.json 缺檔時之後備值
    js = ROOT / "data" / "benchmark" / "paperA_numbers.json"
    if js.exists():
        rep = json.loads(js.read_text(encoding="utf-8")).get("fs", {}).get("FS3", {}).get("fig1_representative")
        if rep:
            out["f3_alt"], out["f3_sig"] = float(rep["alt_km"]), float(rep["sigma_diff_m"])
    return out


if PAPER:
    PI = _paper_inputs()
    F3_ALT, F3_SIG = PI["f3_alt"], PI["f3_sig"]
    TXT["en"].update(
        starlink=(f"Starlink: TLE vs SpaceX ephemeris |Δa|\n(median {PI['sl_med']:.0f} m, "
                  f"IQR {PI['sl_q1']:.0f}–{PI['sl_q3']:.0f} m)\n— a different quantity, not σ_diff"),
        ref="Fixed 50 m threshold",
        f3=f"FORMOSAT-3 ({F3_ALT:.0f} km, non-propulsive; median of 6, last 30 d)",
        out=DOCS / "fig_sigma_vs_altitude_paperA.png")
    TXT["zh"].update(
        starlink=(f"Starlink：TLE 對 SpaceX 星曆 |Δa|\n（中位 {PI['sl_med']:.0f} m，"
                  f"IQR {PI['sl_q1']:.0f}–{PI['sl_q3']:.0f} m）\n— 不同物理量，非 σ_diff"),
        ref="固定 50 m 門檻",
        f3=f"福衛三號（{F3_ALT:.0f} km、無推進；六星近 30 天中位）",
        out=DOCS / "fig_sigma_vs_altitude_paperA_ZH.png")


def draw(cfg):
    """繪圖（不設字型、不存檔），回傳 Figure；供預設輸出與 --pub 四版本共用。"""
    fig, ax = plt.subplots(figsize=(11.5, 7.2))

    if PAPER:
        lo, hi = PI["sl_lo"], PI["sl_hi"]
        ax.add_patch(Rectangle((lo, PI["sl_q1"]), hi - lo, PI["sl_q3"] - PI["sl_q1"], facecolor="#b0339c",
                               alpha=0.13, edgecolor="#b0339c", lw=1.0, ls=(0, (4, 2)), zorder=1))
        ax.plot([lo, hi], [PI["sl_med"]] * 2, color="#b0339c", lw=2.2, zorder=2)
        ax.text(lo + 6, PI["sl_q1"] * 0.92, cfg["starlink"], color="#7d1f6f", fontsize=9.6,
                va="top", ha="left", linespacing=1.35)
    else:
        ax.add_patch(Rectangle((350, 24), 200, 75 - 24, facecolor="#d9534f", alpha=0.12,
                               edgecolor="#d9534f", lw=1.0, zorder=1))
        ax.text(360, 88, cfg["starlink"], color="#c0392b", fontsize=11, va="top", fontweight="bold")

    ax.axhline(50, color="#888888", ls="--", lw=1.4, zorder=1)
    ax.text(1330, 56, cfg["ref"], color="#666666", fontsize=10.5, ha="right", va="bottom")

    ax.axhline(MED, color="#1a6fc4", ls=":", lw=1.4, zorder=1)
    ax.text(352, MED * 1.08, cfg["median"], color="#1a6fc4", fontsize=10.5, va="bottom")

    ax.scatter(D["alt_km"], D["sigma_m"], s=90, color="#1a6fc4", edgecolor="white",
               lw=1.0, zorder=5, label=cfg["ids"])
    ax.scatter([F3_ALT], [F3_SIG], s=170, marker="^", color="#e8871a", edgecolor="white",
               lw=1.0, zorder=6, label=cfg["f3"])

    for _, row in D.iterrows():
        nm = row["name"]
        if nm not in LBL:
            continue
        dx, dy, ha, va = LBL[nm]
        ax.annotate(nm, xy=(row["alt_km"], row["sigma_m"]), xytext=(dx, dy),
                    textcoords="offset points", ha=ha, va=va, fontsize=10.5, color="#222222",
                    arrowprops=dict(arrowstyle="-", color="#999999", lw=0.9, shrinkA=2, shrinkB=4))
    ax.annotate(cfg["f3lab"], xy=(F3_ALT, F3_SIG), xytext=(0, 20), textcoords="offset points",
                ha="center", va="bottom", fontsize=10.5, color="#c8760f",
                arrowprops=dict(arrowstyle="-", color="#e8871a", lw=1.0, shrinkA=2, shrinkB=4))

    ax.set_yscale("log")
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter
    ax.yaxis.set_major_locator(FixedLocator([0.1, 1, 10, 100]))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: ("%g" % y)))
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.set_xlim(340, 1420); ax.set_ylim(0.05, 160)
    ax.set_xlabel(cfg["xlabel"], fontsize=12)
    ax.set_ylabel(cfg["ylabel"], fontsize=12)
    ax.set_title(cfg["title"], fontsize=12.5, fontweight="bold")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend(loc="lower left", fontsize=10, framealpha=0.95)
    fig.tight_layout()
    return fig


def render(cfg):
    plt.rcParams["font.sans-serif"] = cfg["font"]
    plt.rcParams["axes.unicode_minus"] = False
    fig = draw(cfg)
    fig.savefig(cfg["out"], dpi=180); plt.close(fig)
    print(f"saved {cfg['out'].name}  ({cfg['out'].stat().st_size//1024} KB)")


if __name__ == "__main__":
    if "--pub" in sys.argv:          # 中英 × 白底／黑底四版本 → docs/figures_pub/fig_sigma_vs_altitude[_paperA]/
        import fig_pub as fp
        fp.export_variants(lambda: draw(TXT[fp.lang()]),
                           "fig_sigma_vs_altitude_paperA" if PAPER else "fig_sigma_vs_altitude")
        sys.exit(0)
    for k in ("en", "zh"):
        render(TXT[k])
    print("labels: Sentinel-3B directly above point; Sentinel-6A upper-right of point.")
