"""延伸篇 S2 的兩張圖：高度密度剖面、鹿林整夜每次曝光的光跡數。資料：s2_data/s2_results.json（run_s2.py 產生）。
用法：python docs/book/sim_chapters/_fig_s2.py
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
d = json.loads((HERE / "s2_data/s2_results.json").read_text(encoding="utf-8"))
plt.rcParams["font.family"] = ["Microsoft JhengHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
BLUE, ORANGE, AQUA, INK2, GRID = "#2a78d6", "#eb6834", "#1baf7a", "#52514e", "#e6e5e1"


def style(ax):
    ax.grid(True, color=GRID, lw=0.8); ax.set_axisbelow(True)
    for s in ["top", "right"]: ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]: ax.spines[s].set_color("#c9c8c3")
    ax.tick_params(colors=INK2)


# 圖 S2-1 高度密度剖面
den = d["crowd"]["plan_skip1"]["density"]
alt = den["alt_km"]
mega = d["crowd"]["mega_skip1"]["density"]["scenario"]
fig, ax = plt.subplots(figsize=(7.2, 4.0), dpi=200)
for y, c, lab, lw in [(den["baseline"], BLUE, "現況目錄（32,898 個物件）", 2),
                      (den["scenario"], AQUA, "各家計畫全數（82,471）", 2),
                      (mega, ORANGE, "10 萬 Starlink 情境（151,300）", 2)]:
    xs = [a for a, v in zip(alt, y) if a <= 1400]
    ys = [max(v, 1e-12) for a, v in zip(alt, y) if a <= 1400]
    ax.plot(xs, ys, color=c, lw=lw, label=lab)
ax.set_yscale("log"); ax.set_ylim(1e-10, 1e-5); ax.set_xlim(150, 1400)
ax.set_yticks([10.0 ** e for e in range(-10, -4)]); ax.set_yticklabels([f"1e{e}" for e in range(-10, -4)]); ax.minorticks_off()
ax.set_xlabel("高度（km）", color=INK2); ax.set_ylabel("物件密度（個／km³，每 10 km 一格）", color=INK2)
style(ax); ax.legend(frameon=False, fontsize=8.5, loc="upper right")
fig.tight_layout(); fig.savefig(HERE / "img/s2_density.png"); plt.close(fig)

# 圖 S2-3 鹿林、正北仰角 45°，整夜每 10 分鐘一次 30 秒曝光「看得見」的光跡數（s2_data/count_visible.py 的光子模型）
cnt = json.loads((HERE / "s2_data/astro_counts.json").read_text(encoding="utf-8"))
fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=200)
for key, c, lab, off in [("lulin/north/now", BLUE, "現況目錄", -1.6), ("lulin/north/add", ORANGE, "疊加情境（現況＋13 萬顆假想衛星）", 1.6)]:
    pts = [(datetime.fromisoformat(x["t"]) + timedelta(hours=8), x["visible"]) for x in cnt[key] if x]
    ax.bar([t + timedelta(minutes=off) for t, _ in pts], [n for _, n in pts], width=3.0 / 1440, color=c, label=lab)
ax.set_ylabel("每次曝光看得見的光跡數", color=INK2); ax.set_xlabel("當地時間（2026-11-22 晚）", color=INK2)
ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M"))
style(ax); ax.legend(frameon=False, fontsize=8.5, loc="upper right")
fig.tight_layout(); fig.savefig(HERE / "img/s2_lulin_night.png"); plt.close(fig)
print("ok")
