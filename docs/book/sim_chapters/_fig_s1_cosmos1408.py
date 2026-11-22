"""延伸篇 S1 圖 S1-1：Cosmos 1408 碎片存活曲線（觀測 vs 碎片連鎖 v0.1.18／v0.1.19）。

觀測：../sim_validation/cosmos1408/survival_curves.csv 的 observed 欄（CelesTrak SATCAT 1,805 件，第 15 天正規化）。
模擬：RUST_SatDashboard/docs/games_debris_validation_report.md 表 3.1 的 A 組（v0.1.18 基準）與 F 組（v0.1.19 預設），
30 個種子的中位數與 IQR；驗證 JSON 未存檔，數值照報告表格抄錄。
用法：python docs/book/sim_chapters/_fig_s1_cosmos1408.py
"""
from pathlib import Path
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "sim_validation/cosmos1408/survival_curves.csv"
plt.rcParams["font.family"] = ["Microsoft JhengHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

day, obs = [], []
for r in csv.DictReader(open(SRC, encoding="utf-8")):
    v = float(r["observed"])
    if v > 0:
        day.append(int(r["day"]) / 365.25); obs.append(v * 100)

yrs = [1, 2, 3, 5]
A = {"med": [31.4, 11.4, 4.8, 2.5], "lo": [28.6, 9.9, 4.4, 2.1], "hi": [33.0, 12.4, 5.3, 3.1]}
F = {"med": [25.3, 6.7, 1.6, 0.4], "lo": [24.0, 5.6, 1.1, 0.3], "hi": [28.8, 7.8, 2.1, 0.5]}

BLUE, ORANGE, GRAY, INK, INK2 = "#2a78d6", "#eb6834", "#8a8984", "#0b0b0b", "#52514e"
fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=200)
fig.patch.set_facecolor("#ffffff"); ax.set_facecolor("#ffffff")
ax.plot(day, obs, color=BLUE, lw=2, label="觀測（SATCAT 編目碎片）", zorder=3)
for d, c, off, lab, mk in [(A, GRAY, -0.06, "v0.1.18 基準（不截斷 Δv）", "s"),
                           (F, ORANGE, 0.06, "v0.1.19 預設（Δv 截斷 1σ）", "o")]:
    x = [y + off for y in yrs]
    err = [[m - l for m, l in zip(d["med"], d["lo"])], [h - m for m, h in zip(d["med"], d["hi"])]]
    ax.errorbar(x, d["med"], yerr=err, fmt=mk, ms=7, color=c, ecolor=c, elinewidth=2, capsize=0,
                mec="#ffffff", mew=1, label=lab + "：中位數與四分位距", zorder=4)
ax.set_yscale("log"); ax.set_ylim(0.1, 120); ax.set_xlim(0, 5.3)
ax.set_yticks([0.1, 1, 10, 100]); ax.set_yticklabels(["0.1%", "1%", "10%", "100%"])
ax.set_xlabel("試射後年數", color=INK2); ax.set_ylabel("仍在軌比例（第 15 天 = 100%）", color=INK2)
ax.grid(True, which="major", color="#e6e5e1", lw=0.8); ax.set_axisbelow(True)
for s in ["top", "right"]: ax.spines[s].set_visible(False)
for s in ["left", "bottom"]: ax.spines[s].set_color("#c9c8c3")
ax.tick_params(colors=INK2)
ax.legend(frameon=False, fontsize=8.5, loc="upper right", labelcolor=INK)
fig.tight_layout()
out = HERE / "img/s1_cosmos1408_survival.png"
fig.savefig(out); print(out)
