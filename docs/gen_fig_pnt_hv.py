# -*- coding: utf-8 -*-
"""gen_fig_pnt_hv.py — 發現④ TLE vs MEME 水平/垂直定位精度對比圖（深色主題）
依據：報告表 18 / 第十七節實測之星曆三軸分解（新鮮 TLE：沿軌 1,524 m、徑向 143 m、法向 181 m），
以一階 RTN→H/V 投影：水平≈沿軌主導、垂直≈徑向。MEME 三軸齊壓公尺級（~5 m）。
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

# CJK 字型
for cand in ["Microsoft JhengHei", "Microsoft YaHei", "SimHei"]:
    if any(cand in f.name for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.sans-serif"] = [cand]
        break
plt.rcParams["axes.unicode_minus"] = False

BG    = "#0E1B2E"
PANEL = "#16273F"
INK   = "#ECF2F9"
MUTE  = "#9FB3C8"
TLE   = "#FFD54F"   # 琥珀＝TLE
MEME  = "#66BB6A"   # 綠＝MEME
ACC   = "#4FC3F7"

# 數據（公尺）
groups = ["水平（沿軌主導）", "垂直（徑向）"]
tle_fresh = [1524.0, 143.0]
meme_val  = [5.0, 5.0]
factors   = [tle_fresh[i] / meme_val[i] for i in range(2)]  # 305, 28.6

fig, ax = plt.subplots(figsize=(7.6, 5.6))
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)

x = np.arange(2)
bw = 0.34
b1 = ax.bar(x - bw/2, tle_fresh, bw, label="TLE（新鮮 <3h）", color=TLE, zorder=3)
b2 = ax.bar(x + bw/2, meme_val, bw, label="MEME（精密星曆）", color=MEME, zorder=3)

ax.set_yscale("log")
ax.set_ylim(2, 6e4)
ax.set_xticks(x)
ax.set_xticklabels(groups, fontsize=14, color=INK)
ax.set_ylabel("衛星星曆位置誤差（公尺，對數軸）", fontsize=12, color=INK)
ax.set_title("TLE vs MEME：水平／垂直定位精度提升比較", fontsize=15, color=INK, pad=14)

# 數值標籤
for rect, v in zip(b1, tle_fresh):
    ax.text(rect.get_x()+rect.get_width()/2, v*1.12, f"{v:,.0f} m",
            ha="center", va="bottom", fontsize=12, color=TLE, fontweight="bold")
for rect, v in zip(b2, meme_val):
    ax.text(rect.get_x()+rect.get_width()/2, v*1.12, f"~{v:.0f} m",
            ha="center", va="bottom", fontsize=12, color=MEME, fontweight="bold")

# 改善倍數標註
for i in range(2):
    ax.annotate(f"×{factors[i]:.0f}",
                xy=(x[i], np.sqrt(tle_fresh[i]*meme_val[i])),
                ha="center", va="center", fontsize=17, color=ACC, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", fc=PANEL, ec=ACC, lw=1.3))

# 陳舊 TLE 水平標註（虛線 + 註）
ax.axhline(32100, xmin=0.06, xmax=0.46, color=TLE, ls="--", lw=1.4, alpha=0.8, zorder=2)
ax.text(x[0]-bw/2, 32100*1.15, "72h 陳舊 TLE 水平 約 32 km（×6,400）",
        ha="left", va="bottom", fontsize=10.5, color=TLE, alpha=0.95)

# 樣式
ax.tick_params(colors=MUTE)
for spine in ax.spines.values():
    spine.set_color(MUTE); spine.set_alpha(0.4)
ax.grid(axis="y", color=MUTE, alpha=0.18, zorder=0)
leg = ax.legend(loc="upper right", fontsize=11, framealpha=0.0)
for t in leg.get_texts():
    t.set_color(INK)

# 底註
fig.text(0.5, 0.015,
         "星曆三軸實測：新鮮 TLE 沿軌 1,524 m 遠大於徑向 143 m。H/V 為 RTN 一階投影，嚴謹使用者 H/V 需定位 DOP 模擬（期末）",
         ha="center", fontsize=8, color=MUTE)

fig.tight_layout(rect=(0, 0.04, 1, 1))
out = Path(__file__).parent / "fig_r11_pnt_hv.png"
fig.savefig(out, dpi=150, facecolor=BG)
print("saved", out)
