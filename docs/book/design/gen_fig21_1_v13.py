"""圖 21-1（全書 v1.3）：TLE 半長軸雜訊底與大氣阻力之對照，依結案報告 §7.7 改用弧尺度變異。

與原圖（docs/gen_fig_sigma_drag_altitude.py）的差異：
  - (A) 雜訊底改為 DORIS 13 顆測高衛星無機動弧段之弧尺度變異 σ_res（結案報告圖 6 同一資料
    data/benchmark/paperA_rv1_estimators.csv 之 s_res_c，誤差棒為弧段 bootstrap 95% 區間）；
    移除相鄰差值 σ_diff、Starlink 24–75 m 色帶與 50 m 門檻假設（舊估計，已由結案報告取代）。
  - (B) NRLMSIS 2.1 密度曲線保留；移除以 σ_diff 擬合之「雜訊底標高」框。
阻力曲線與密度計算沿用原程式之函式（pymsis 預設 NRLMSIS 2.1）。

用法（repo 根目錄）：python docs/book/design/gen_fig21_1_v13.py
輸出：docs/book/v1.0_送審版/img/fig21_1_noise_drag_v13.png
"""
import importlib.util
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("g", ROOT / "docs" / "gen_fig_sigma_drag_altitude.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
g.LBL["SARAL"] = (14, 10, "left", "bottom")      # 與 Envisat 幾乎重疊，標籤移到右上

OUT = ROOT / "docs" / "book" / "v1.0_送審版" / "img" / "fig21_1_noise_drag_v13.png"
E = pd.read_csv(ROOT / "data" / "benchmark" / "paperA_rv1_estimators.csv").sort_values("alt_km")
ci = np.array([json.loads(s) for s in E["ci_s_res_c"]])
med = float(np.median(E["s_res_c"]))

plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
fig, (axA, axB) = plt.subplots(1, 2, figsize=(16.4, 7.6), gridspec_kw={"width_ratios": [1.6, 1.0]})
h = np.linspace(300, 1400, 200)

# ---------- (A) ----------
axA.fill_between(h, g.drag_dadt(h, g.BSTAR_LO) * g.DT_TLE, g.drag_dadt(h, g.BSTAR_HI) * g.DT_TLE,
                 color=g.C_REF, alpha=0.15, lw=0, zorder=1,
                 label="大氣阻力 8 h 內 |Δa|（Cd·A/m = 0.005–0.04 m²/kg）")
axA.plot(h, g.drag_dadt(h, 0.02) * g.DT_TLE, color=g.C_REF, ls="--", lw=2.0, zorder=2,
         label="阻力 |Δa|（Cd·A/m = 0.02 m²/kg）")
y = E["s_res_c"].to_numpy()
axA.errorbar(E["alt_km"], y, yerr=[y - ci[:, 0], ci[:, 1] - y], fmt="o", color=g.C_IDS, ms=9,
             mec="white", mew=1.0, elinewidth=1.4, capsize=3, zorder=7,
             label="DORIS 測高衛星弧尺度變異 σ_res（13 顆，無機動弧段，95% 區間）")
axA.axhline(med, color=g.C_IDS, ls=":", lw=1.4, zorder=3)
axA.text(310, med * 1.12, f"13 顆中位 {med:.2f} m", color=g.C_IDS, fontsize=10, ha="left", va="bottom")
for _, r in E.iterrows():
    nm = r["sat"]
    if nm in g.LBL:
        dx, dy, ha, va = g.LBL[nm]
        axA.annotate(nm, xy=(r["alt_km"], r["s_res_c"]), xytext=(dx, dy), textcoords="offset points",
                     ha=ha, va=va, fontsize=9.5, color=g.INK,
                     arrowprops=dict(arrowstyle="-", color="#aaaab2", lw=0.8, shrinkA=2, shrinkB=4))
axA.set_yscale("log")
axA.yaxis.set_major_locator(FixedLocator([0.1, 1, 10, 100, 1000]))
axA.yaxis.set_major_formatter(FuncFormatter(lambda v, _: "%g" % v))
axA.yaxis.set_minor_formatter(NullFormatter())
axA.set_xlim(300, 1400)
axA.set_ylim(0.04, 6000)
axA.set_xlabel("高度 (km)", fontsize=11.5, color=g.INK)
axA.set_ylabel("半長軸變化量 (m，對數軸)", fontsize=11.5, color=g.INK)
axA.set_title("(A) TLE 半長軸弧尺度變異 σ_res 與阻力在 8 小時內造成之 |Δa|（同一軸，單位皆為公尺）",
              fontsize=11.5, fontweight="bold", color=g.INK, pad=10)
axA.grid(True, which="major", alpha=0.22, color="#c9c9d1")
axA.legend(loc="upper right", fontsize=9.4, framealpha=0.96)

# ---------- (B) ----------
for f107, col, lab in zip([70.0, 150.0, 220.0], g.SEQ, ["太陽活動低 F10.7=70", "中等 F10.7=150", "高 F10.7=220"]):
    axB.plot(h, g.msis_rho(h, f107=f107), color=col, lw=2.3, label=lab, zorder=4)
axB.axvspan(350, 550, color=g.C_SL, alpha=0.10, lw=0, zorder=1)
axB.axvspan(700, 1400, color=g.C_IDS, alpha=0.07, lw=0, zorder=1)
axB.text(450, 2.2e-16, "Starlink\n350–550 km", color=g.C_SL, fontsize=10, ha="center", va="bottom", fontweight="bold")
axB.text(1050, 2.2e-16, "DORIS 測高衛星\n700 km 以上", color=g.C_IDS, fontsize=10, ha="center", va="bottom", fontweight="bold")
axB.set_yscale("log")
axB.set_xlim(300, 1400)
axB.set_ylim(1e-16, 3e-11)
axB.yaxis.set_major_locator(FixedLocator([1e-16, 1e-15, 1e-14, 1e-13, 1e-12, 1e-11]))
axB.yaxis.set_major_formatter(FuncFormatter(lambda v, _: r"$10^{%d}$" % int(round(np.log10(v)))))
axB.yaxis.set_minor_formatter(NullFormatter())
axB.set_xlabel("高度 (km)", fontsize=11.5, color=g.INK)
axB.set_ylabel("大氣質量密度 ρ (kg/m³，對數軸)", fontsize=11.5, color=g.INK)
axB.set_title("(B) NRLMSIS 2.1 中性大氣質量密度 ρ(h)", fontsize=11.5, fontweight="bold", color=g.INK, pad=10)
axB.grid(True, which="major", alpha=0.22, color="#c9c9d1")
axB.legend(loc="upper right", fontsize=9.5, framealpha=0.96)

for ax in (axA, axB):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#c9c9d1")
    ax.tick_params(colors=g.MUTE, labelsize=10)

fig.suptitle("TLE 半長軸雜訊底之高度相依性，與大氣阻力之對照", fontsize=14.5, fontweight="bold", color=g.INK, y=0.975)
fig.text(0.012, 0.015,
         "註1　(A) 之阻力曲線為 NRLMSIS 2.1 密度代入圓軌道阻力式 |da/dt| = (Cd·A/m)·ρ·√(μa) 之量級估算（2026 春分、赤道、Ap=10），僅作趨勢對照，非誤差模型。\n"
         "註2　σ_res 為 DORIS 營運方紀錄之無機動弧段上，TLE 半長軸對弧段趨勢之殘差尺度（結案報告 §7.7、圖 6）；相鄰兩筆 TLE 之差值只反映數小時內的變化，會低估單筆 TLE 的誤差。\n"
         "註3　低軌衛星（如 Starlink）缺乏認證安靜期，未在圖中標示；其偵測下限依結案報告以各星未標記相鄰轉換之逐月穩健標準差估計（5σ 候選下限、20σ 高顯著下限），隨太陽活動與阻力變動。",
         fontsize=8.5, color=g.MUTE, va="bottom", linespacing=1.6)
fig.tight_layout(rect=(0, 0.1, 1, 0.945))
fig.savefig(OUT, dpi=170, facecolor="white")
print(f"saved {OUT.name}  ({OUT.stat().st_size // 1024} KB)；中位 σ_res = {med:.3f} m")
