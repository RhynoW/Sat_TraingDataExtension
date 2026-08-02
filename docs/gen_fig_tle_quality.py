# -*- coding: utf-8 -*-
"""gen_fig_tle_quality.py — TLE 品質(σ_sma) vs 高度：精密測高星 vs Starlink 級(深色主題)
資料：精密星為 ids_sigma_calibrate.py 認證安靜期實測；Starlink 級為報告表 11 假設值。
"""
import sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
for cand in ["Microsoft JhengHei", "Microsoft YaHei", "SimHei"]:
    if any(cand in f.name for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.sans-serif"] = [cand]; break
plt.rcParams["axes.unicode_minus"] = False

BG="#0E1B2E"; PANEL="#16273F"; INK="#ECF2F9"; MUTE="#9FB3C8"
STAR="#FFD54F"; PREC="#66BB6A"; ACC="#4FC3F7"

# 精密測高星（實測 σ，公尺）
prec = [("Sentinel-6A",1338,0.1),("Jason-3",1311,0.2),("Sentinel-3B",803,0.4),
        ("Sentinel-3A",803,0.5),("HY-2C",952,0.6),("CryoSat-2",719,0.8),("SWOT",1194,2.6)]
# Starlink 級（表 11 假設，帶中點高度）
star = [(300,150),(575,80),(1000,50)]

fig, ax = plt.subplots(figsize=(8.0,5.7))
fig.patch.set_facecolor(BG); ax.set_facecolor(BG)

# Starlink 級：畫成一條帶（50–150 m）
ax.axhspan(50,150, color=STAR, alpha=0.12, zorder=1)
sx=[s[0] for s in star]; sy=[s[1] for s in star]
ax.plot(sx, sy, "s--", color=STAR, ms=11, lw=1.6, zorder=3, label="Starlink 級（雷達追蹤，表 11 假設）")
for x,y in star:
    ax.text(x, y*1.15, f"{y:.0f} m", ha="center", color=STAR, fontsize=10.5, fontweight="bold")

# 精密星：實測散點
px=[p[1] for p in prec]; py=[p[2] for p in prec]
ax.scatter(px, py, s=130, color=PREC, edgecolor=INK, lw=0.8, zorder=4,
           label="精密測高星（SLR/DORIS/GPS，認證安靜期實測）")
for nm,x,y in prec:
    dy = 1.25 if nm not in ("Sentinel-3A",) else 0.72
    ax.annotate(f"{nm} {y:.1f}m", (x,y), (x, y*dy), ha="center",
                color=PREC, fontsize=9)

ax.set_yscale("log"); ax.set_ylim(0.05, 400)
ax.set_xlim(150, 1500)
import matplotlib.ticker as mticker
ax.yaxis.set_major_locator(mticker.FixedLocator([0.1,1,10,100]))
ax.yaxis.set_minor_locator(mticker.NullLocator())
ax.yaxis.set_major_formatter(mticker.FuncFormatter(
    lambda v,_: ("%g" % v) if v>=1 else ("%.1f" % v)))
ax.set_xlabel("軌道高度（km）", fontsize=12, color=INK)
ax.set_ylabel("TLE 半長軸雜訊 σ_sma（公尺，對數軸）", fontsize=12, color=INK)
ax.set_title("TLE 品質不是常數：追蹤方式決定 σ（差約 100 倍）", fontsize=15, color=INK, pad=12)

# ~100× 差距標註
ax.annotate("", xy=(1250,0.3), xytext=(1250,60),
            arrowprops=dict(arrowstyle="<->", color=ACC, lw=1.6))
ax.text(1275, 4.5, "約 100–250×\n偵測下限之差", color=ACC, fontsize=11, fontweight="bold", va="center")

ax.tick_params(colors=MUTE)
for sp in ax.spines.values(): sp.set_color(MUTE); sp.set_alpha(0.4)
ax.grid(axis="y", color=MUTE, alpha=0.18, zorder=0)
leg=ax.legend(loc="lower left", fontsize=10, framealpha=0.0)
for t in leg.get_texts(): t.set_color(INK)
fig.text(0.5,0.015,"同樣一次 22 m 的機動：在 Starlink 級目標上是 0.4σ（埋在雜訊裡）、在精密星上是數十σ（清楚可見）——偵測與否取決於追蹤品質，非機動大小",
         ha="center", fontsize=8.3, color=MUTE)
fig.tight_layout(rect=(0,0.035,1,1))
out=Path(__file__).parent/"fig_r12_tle_quality.png"
fig.savefig(out, dpi=150, facecolor=BG)
print("saved", out)
