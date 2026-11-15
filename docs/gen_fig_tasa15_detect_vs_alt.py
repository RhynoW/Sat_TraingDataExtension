"""TASA 15 星：軌道高度 vs 可偵測機動大小（Δa）。
資料：R6 報表 detect_cap（σΔa＝未標記相鄰 TLE 轉換逐月穩健標準差之中位數）。
  下緣＝5σ（SNR 中：可成為候選事件，等級最高 E2）
  上緣＝20σ（SNR 高：單筆即可高顯著辨識＝報表 min_detect_m）
下圖灰點：IDS 測高衛星（DORIS 認證安靜期 σ_diff×20），作為 700–1400 km 參考，估計條件不同。
用法：python docs/gen_fig_tasa15_detect_vs_alt.py <r15.json> [out.png] [版本，預設 R7]"""
import json, sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

src = Path(sys.argv[1])
out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).with_name("fig_tasa15_detect_vs_alt.png")
d = json.loads(src.read_text(encoding="utf-8"))
VER = sys.argv[3] if len(sys.argv) > 3 else "R7"   # 報表版本（標題用）
END = max(str(r.get("end_date", "")) for r in d.values())
plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
NAVY, RED, GRAY = "#002B8A", "#C0392B", "#9AA5B1"
IDS = [(803, .2), (1338, .1), (893, .3), (803, .3), (1311, .1), (1338, .1), (952, .2), (952, .2),
       (1325, .2), (719, .3), (785, .2), (766, .5), (968, 1.2)]

rows = sorted(d.values(), key=lambda x: x["detect_cap"]["sigma_med_m"])
fig = plt.figure(figsize=(13.3, 8.2), dpi=150)
gs = fig.add_gridspec(2, 2, width_ratios=[1.75, 1], height_ratios=[2.2, 1], hspace=0.38, wspace=0.04)
ax, at, ab = fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1]), fig.add_subplot(gs[1, :])

for i, x in enumerate(rows, 1):
    h, s = x["alt_km_avg"], x["detect_cap"]["sigma_med_m"]
    c = RED if x["name"].upper().startswith("STARLINK") else NAVY
    ax.vlines(h, 5 * s, 20 * s, color=c, lw=3, alpha=0.45)
    ax.plot(h, 20 * s, "s" if c == RED else "o", color=c, ms=13, mec="white", mew=1, zorder=3)
    ax.text(h, 20 * s, str(i), color="white", fontsize=7.5, ha="center", va="center", fontweight="bold", zorder=4)
    ax.plot(h, 5 * s, "_", color=c, ms=9, mew=2)
    ab.plot(h, 20 * s, "s" if c == RED else "o", color=c, ms=6, mec="white", mew=.8, zorder=3)
ax.set_yscale("log"); ax.set_xlim(350, 605); ax.set_ylim(8, 1500)
ax.set_xlabel("平均軌道高度 (km)"); ax.set_ylabel("可偵測 |Δa|（m，對數軸）")
ax.grid(True, which="both", color="#E3E8EF", lw=.7)
ax.set_title("TASA 15 星：每顆星的可偵測範圍（線段＝5σ～20σ）", fontsize=11.5, fontweight="bold", loc="left")
ax.legend(handles=[Line2D([0], [0], marker="o", color=NAVY, ls="", ms=8, label="非 Starlink（點＝20σ 高顯著）"),
                   Line2D([0], [0], marker="s", color=RED, ls="", ms=8, label="Starlink（點＝20σ 高顯著）"),
                   Line2D([0], [0], marker="_", color="#555", ls="", ms=9, mew=2, label="橫槓＝5σ 候選下限")],
          loc="lower left", fontsize=8.5, framealpha=.95)

at.axis("off")
at.text(0, 1.0, "編號  衛星（NORAD）        高度   5σ～20σ", fontsize=9, fontweight="bold", va="top", family="Microsoft JhengHei")
for i, x in enumerate(rows, 1):
    s = x["detect_cap"]["sigma_med_m"]
    c = RED if x["name"].upper().startswith("STARLINK") else NAVY
    y = 1.0 - i * 0.062
    at.text(0.01, y, f"{i:>2}", fontsize=8.5, color=c, fontweight="bold", va="top")
    at.text(0.09, y, f"{x['name']}（{x['norad']}）", fontsize=8.5, color="#222", va="top")
    at.text(0.64, y, f"{x['alt_km_avg']:.0f}", fontsize=8.5, color="#222", va="top")
    at.text(0.76, y, f"{5 * s:,.0f}～{20 * s:,.0f} m", fontsize=8.5, color="#222", va="top")

for h, sd in IDS:
    ab.plot(h, 20 * sd, "o", color=GRAY, ms=6, mec="white", mew=.8)
ab.axvspan(350, 605, color="#126BFA", alpha=.06, lw=0)
ab.set_yscale("log"); ab.set_xlim(300, 1400); ab.set_ylim(1, 2000)
ab.set_xlabel("平均軌道高度 (km)"); ab.set_ylabel("20σ 可辨識 |Δa| (m)")
ab.grid(True, which="both", color="#E3E8EF", lw=.7)
ab.set_title("全高度帶總覽：高度愈高、阻力愈小，可辨識量級由數百公尺降到公尺級（灰點＝IDS 測高衛星參考，估計條件不同）",
             fontsize=10.5, fontweight="bold", loc="left")
fig.suptitle(f"軌道高度 vs 可偵測機動大小（{VER} 偵測能力估計，資料至 {END}）", fontsize=14, fontweight="bold", y=.985)
fig.savefig(out, bbox_inches="tight")
print(out)
