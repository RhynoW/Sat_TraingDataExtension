"""延伸篇 S2 的數據圖（修訂版，2026-11-23 目錄快照、推演起點固定）。

資料：s2_data/v2/（run_s2_v2.py、fetch_astro_v2.py、count_visible_v2.py 產生）
圖：
  s2_density.png        高度密度剖面
  s2_convergence.png    收斂測試：取樣長度、快照間隔、推演起點、篩選半徑
  s2_tornado.png        全系統每天 1 km 接近次數之敏感度（計畫全數情境）
  s2_thirdparty.png     第三方物件依類型、高度與傾角分解
  s2_lulin_night.png    鹿林正北整夜每次曝光看得見的光跡數
  s2_astro_sens.png     光跡數對日期、曝光時間、視野與指向之敏感度
用法：python docs/book/sim_chapters/_fig_s2.py
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
V2 = HERE / "s2_data/v2"
IMG = HERE / "img"
plt.rcParams["font.family"] = ["Microsoft JhengHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
BLUE, ORANGE, AQUA, YELLOW, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#8a8984"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e1"


def load(name):
    return json.loads((V2 / name).read_text(encoding="utf-8"))


def style(ax, axis="both"):
    ax.grid(True, color=GRID, lw=0.8, axis=axis); ax.set_axisbelow(True)
    for s in ["top", "right"]: ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]: ax.spines[s].set_color("#c9c8c3")
    ax.tick_params(colors=INK2)


def other(stats):
    return next(g["per_sat_year_1km"] for g in stats["groups"] if g["key"] == "other")


main = load("crowd_main.json")["runs"]

# 圖 S2-1 高度密度剖面 ───────────────────────────────────────────────────────
den = main["plan_skip1"]["density"]
alt = den["alt_km"]
fig, ax = plt.subplots(figsize=(7.2, 4.0), dpi=200)
for y, c, lab in [(den["baseline"], BLUE, f"現況目錄（{main['plan_skip1']['baseline']['objects']:,} 個物件）"),
                  (den["scenario"], AQUA, f"各家計畫全數（{main['plan_skip1']['scenario']['objects']:,}）"),
                  (main["mega_skip1"]["density"]["scenario"], ORANGE, f"10 萬 Starlink 情境（{main['mega_skip1']['scenario']['objects']:,}）")]:
    xs = [a for a, v in zip(alt, y) if a <= 1400]
    ys = [max(v, 1e-12) for a, v in zip(alt, y) if a <= 1400]
    ax.plot(xs, ys, color=c, lw=2, label=lab)
ax.set_yscale("log"); ax.set_ylim(1e-10, 1e-5); ax.set_xlim(150, 1400)
ax.set_yticks([10.0 ** e for e in range(-10, -4)]); ax.set_yticklabels([f"1e{e}" for e in range(-10, -4)]); ax.minorticks_off()
ax.set_xlabel("高度（km）", color=INK2); ax.set_ylabel("物件密度（個／km³，每 10 km 一格）", color=INK2)
style(ax); ax.legend(frameon=False, fontsize=8.5, loc="upper right")
fig.tight_layout(); fig.savefig(IMG / "s2_density.png"); plt.close(fig)

# 圖 S2-3 收斂測試 ──────────────────────────────────────────────────────────
conv = load("crowd_conv.json")["runs"]
ref = {k: main[f"{k}_skip1"]["scenario"]["enc_day_1km"] for k in ("plan", "mega")}
fig, axs = plt.subplots(1, 4, figsize=(9.6, 3.0), dpi=200, sharey=True)
axes = [("hours", "取樣長度（小時）", [2, 6, 12, 24]), ("step_s", "快照間隔（秒）", [10, 30, 60, 120]),
        ("t0_offset_h", "推演起點（T0 後小時）", [0, 3, 6, 9, 12, 15, 18, 21]), ("d_km", "篩選半徑（km）", [10, 20, 50])]
for ax, (axis, lab, vals) in zip(axs, axes):
    for k, c, name in [("plan", AQUA, "各家計畫全數"), ("mega", ORANGE, "10 萬 Starlink")]:
        ys = []
        for v in vals:
            if (axis == "hours" and v == 2) or (axis == "step_s" and v == 60) or (axis == "d_km" and v == 20) or (axis == "t0_offset_h" and v == 0):
                ys.append(1.0)
            else:
                r = next(x for x in conv if x["kind"] == k and x["axis"] == axis and x["value"] == v)
                ys.append(r["scenario"]["enc_day_1km"] / ref[k])
        ax.plot(range(len(vals)), ys, "o-", color=c, lw=1.6, ms=4, label=name)
    ax.axhspan(0.95, 1.05, color=GRID, alpha=0.7, lw=0)
    ax.set_xticks(range(len(vals))); ax.set_xticklabels([str(v) for v in vals], fontsize=7.5)
    ax.set_xlabel(lab, color=INK2, fontsize=8.5); style(ax, "y")
axs[0].set_ylabel("每天 1 km 內接近／基準設定", color=INK2, fontsize=8.5)
axs[0].set_ylim(0.6, 1.15); axs[0].legend(frameon=False, fontsize=7.5, loc="lower left")
fig.tight_layout(); fig.savefig(IMG / "s2_convergence.png"); plt.close(fig)

# 圖 S2-4 敏感度（計畫全數，全系統每天 1 km 接近）────────────────────────────
shells = load("crowd_shells.json")["runs"]
base = main["plan_skip1"]["scenario"]["enc_day_1km"]
sv = lambda cfg, sk: next(r for r in shells if r["config"] == cfg and r["skip"] == sk)["scenario"]["enc_day_1km"]
cv = lambda axis, v: next(r for r in conv if r["kind"] == "plan" and r["axis"] == axis and r["value"] == v)["scenario"]["enc_day_1km"]
t0s = [base] + [cv("t0_offset_h", o) for o in (3, 6, 9, 12, 15, 18, 21)]
rows = [("配對規則（同星座不計 ↔ 全部都計）", main["plan_skip2"]["scenario"]["enc_day_1km"], main["plan_skip0"]["scenario"]["enc_day_1km"]),
        ("Starlink 殼層配置（分散 ↔ 集中兩殼）", sv("spread53", 1), sv("two53", 1)),
        ("Starlink：FCC 2026 核准殼層（400 km 以下 ↔ 475–485 km）", sv("da2636_high", 1), sv("da2636_low", 1)),
        ("篩選半徑（50 ↔ 10 km）", cv("d_km", 50), cv("d_km", 10)),
        ("取樣長度（2–24 小時）", min(base, *[cv("hours", h) for h in (6, 12, 24)]), max(base, *[cv("hours", h) for h in (6, 12, 24)])),
        ("推演起點（一天內 8 個時刻）", min(t0s), max(t0s)),
        ("快照間隔（10–120 秒）", min(base, *[cv("step_s", s) for s in (10, 30, 120)]), max(base, *[cv("step_s", s) for s in (10, 30, 120)]))]
fig, ax = plt.subplots(figsize=(7.6, 3.6), dpi=200)
for i, (lab, lo, hi) in enumerate(rows[::-1]):
    lo, hi = min(lo, hi), max(lo, hi)
    if hi - lo < 1 and False:
        ax.plot([lo], [i], "D", color=YELLOW, ms=6)
        ax.text(lo * 1.05, i, f"{lo:,.0f}", va="center", fontsize=7.5, color=INK)
    else:
        ax.barh(i, hi - lo, left=lo, height=0.55, color=BLUE if i >= 3 else GRAY)
        ax.text(hi * 1.04, i, f"{lo:,.0f}–{hi:,.0f}", va="center", fontsize=7.5, color=INK)
ax.axvline(base, color=ORANGE, lw=1.2); ax.text(base, len(rows) - 0.35, f"基準 {base:,.0f}", color=ORANGE, fontsize=7.5, ha="center")
ax.set_xscale("log"); ax.set_xlim(3000, 120000)
ax.set_yticks(range(len(rows))); ax.set_yticklabels([r[0] for r in rows[::-1]], fontsize=8)
ax.set_xlabel("全系統每天 1 km 內接近次數（各家計畫全數情境，對數軸）", color=INK2, fontsize=8.5)
style(ax, "x"); ax.tick_params(axis="y", length=0)
fig.tight_layout(); fig.savefig(IMG / "s2_tornado.png"); plt.close(fig)

# 圖 S2-5 第三方分解 ────────────────────────────────────────────────────────
CLS = [("payload", "其他衛星（有效載荷）"), ("debris", "碎片"), ("rocket_body", "火箭體"), ("unknown", "不明物體")]
fig, axs = plt.subplots(1, 2, figsize=(9.2, 3.6), dpi=200, gridspec_kw={"width_ratios": [1, 1.25]})
ax = axs[0]; w = 0.26
tp = {k: {c["class"]: c for c in main[f"{k}_skip1"]["third_party"]["scenario"]["classes"]} for k in ("plan", "mega")}
tp["now"] = {c["class"]: c for c in main["plan_skip1"]["third_party"]["baseline"]["classes"]}
for j, (k, c, lab) in enumerate([("now", BLUE, "現況"), ("plan", AQUA, "各家計畫全數"), ("mega", ORANGE, "10 萬 Starlink")]):
    xs = [i + (j - 1) * w for i in range(len(CLS))]
    vals = [tp[k][cl]["per_sat_year_1km"] for cl, _ in CLS]
    ax.bar(xs, vals, width=w - 0.03, color=c, label=lab)
    for xi, v in zip(xs, vals):
        ax.text(xi, v + 4, f"{v:.0f}", ha="center", fontsize=6.8, color=INK)
ax.set_xticks(range(len(CLS))); ax.set_xticklabels([f"{n}\n{tp['now'][cl]['count']:,} 個" for cl, n in CLS], fontsize=7.5)
ax.set_ylabel("每顆每年 1 km 內接近次數", color=INK2, fontsize=8.5); style(ax, "y")
ax.legend(frameon=False, fontsize=7.5, loc="upper left")
ax = axs[1]
grid_b = {(g["alt"], g["inc"]): g for g in main["plan_skip1"]["third_party"]["baseline"]["grid"]}
grid_s = {(g["alt"], g["inc"]): g for g in main["plan_skip1"]["third_party"]["scenario"]["grid"]}
alts = list(range(200, 1500, 50)); incs = list(range(0, 180, 10))
M = np.full((len(incs), len(alts)), np.nan)
for (a, i), g in grid_s.items():
    if a in alts and i in incs:
        add = g["total_year_1km"] - grid_b.get((a, i), {"total_year_1km": 0})["total_year_1km"]
        M[incs.index(i), alts.index(a)] = max(add, 1)
im = ax.imshow(np.log10(M), origin="lower", aspect="auto", cmap="Oranges", vmin=2, vmax=5.5,
               extent=[alts[0], alts[-1] + 50, incs[0], incs[-1] + 10])
cb = fig.colorbar(im, ax=ax, pad=0.02); cb.set_label("新增接近次數／年（log₁₀）", fontsize=7.5, color=INK2); cb.ax.tick_params(labelsize=7)
ax.set_xlabel("第三方物件高度（km，每 50 km）", color=INK2, fontsize=8.5); ax.set_ylabel("傾角（°，每 10°）", color=INK2, fontsize=8.5)
ax.tick_params(colors=INK2, labelsize=7.5)
fig.tight_layout(); fig.savefig(IMG / "s2_thirdparty.png"); plt.close(fig)

# 圖 S2-6 鹿林正北整夜 ──────────────────────────────────────────────────────
summ = json.loads((V2 / "astro_summary.json").read_text(encoding="utf-8"))
pf = summ["base"]["lulin/north"]["per_frame"]
fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=200)
for key, c, lab, off in [("now", BLUE, "現況目錄", -1.6), ("add", ORANGE, "疊加情境（現況＋13 萬顆假想衛星）", 1.6)]:
    pts = [(datetime.fromisoformat(x["t"].replace("Z", "+00:00")) + timedelta(hours=8), x["visible"]) for x in pf[key] if x]
    ax.bar([t + timedelta(minutes=off) for t, _ in pts], [n for _, n in pts], width=3.0 / 1440, color=c, label=lab)
ax.set_ylabel("每次曝光看得見的光跡數", color=INK2); ax.set_xlabel("當地時間（2026-11-22 晚）", color=INK2)
ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M"))
style(ax, "y"); ax.legend(frameon=False, fontsize=8.5, loc="upper right")
fig.tight_layout(); fig.savefig(IMG / "s2_lulin_night.png"); plt.close(fig)

# 圖 S2-8 光跡數之敏感度 ────────────────────────────────────────────────────
fig, axs = plt.subplots(1, 3, figsize=(9.6, 3.3), dpi=200, gridspec_kw={"width_ratios": [1.4, 1, 1]})
ax = axs[0]
dates = [("2026-03-20", "3/20"), ("2026-06-21", "6/21"), ("2026-09-22", "9/22"), ("2026-11-22", "11/22"), ("2026-12-21", "12/21")]
def dget(day, pk):
    if day == "2026-11-22":
        return summ["base"][f"lulin/{pk}"]
    return summ["dates"][f"{day}/{pk}"]
x = np.arange(len(dates)); w = 0.2
for j, (pk, kind, c, lab) in enumerate([("north", "now", BLUE, "正北 現況"), ("north", "add", ORANGE, "正北 疊加"),
                                        ("dusk60", "now", "#8fb8e8", "方位 250° 現況"), ("dusk60", "add", "#f3ad8c", "方位 250° 疊加")]):
    vals = [dget(d, pk)[kind]["night_visible"] for d, _ in dates]
    ax.bar(x + (j - 1.5) * w, vals, width=w - 0.02, color=c, label=lab)
ax.set_xticks(x); ax.set_xticklabels([l for _, l in dates], fontsize=8)
ax.set_ylabel("整夜看得見的光跡總數（鹿林）", color=INK2, fontsize=8.5); style(ax, "y")
ax.legend(frameon=False, fontsize=6.8, ncol=2, loc="upper right")
ax.set_title("日期", fontsize=9, color=INK)
ax = axs[1]
inst = [("exp10", "曝光 10 s"), ("base", "30 s"), ("exp60", "60 s"), ("fov1", "視野 1°"), ("base", "3.5°"), ("fov7", "7°")]
def iget(k, kind):
    if k == "base":
        rows = summ["base"]["lulin/north"]["per_frame"][kind][:13]
        return sum(r["visible"] for r in rows if r)
    return summ["inst"][k][kind]["night_visible"]
xi = np.arange(len(inst))
for j, (kind, c, lab) in enumerate([("now", BLUE, "現況"), ("add", ORANGE, "疊加")]):
    ax.bar(xi + (j - 0.5) * 0.38, [iget(k, kind) for k, _ in inst], width=0.36, color=c, label=lab)
ax.set_xticks(xi); ax.set_xticklabels([l for _, l in inst], fontsize=7.2, rotation=30)
ax.set_ylabel("昏影後 2 小時（13 次曝光）光跡數", color=INK2, fontsize=8); style(ax, "y")
ax.legend(frameon=False, fontsize=7); ax.set_title("曝光時間與視野（鹿林正北）", fontsize=9, color=INK)
ax = axs[2]
scan = [("az0", "北"), ("az90", "東"), ("az180", "南"), ("az270", "西"), ("zenith", "天頂")]
xs = np.arange(len(scan))
for j, (kind, c, lab) in enumerate([("now", BLUE, "現況"), ("add", ORANGE, "疊加")]):
    ax.bar(xs + (j - 0.5) * 0.38, [summ["scan"][k][kind]["first_mean"] for k, _ in scan], width=0.36, color=c, label=lab)
ax.set_xticks(xs); ax.set_xticklabels([l for _, l in scan], fontsize=8)
ax.set_ylabel("昏影後第一小時平均每次曝光", color=INK2, fontsize=8); style(ax, "y")
ax.set_title("指向（仰角 45°）", fontsize=9, color=INK)
fig.tight_layout(); fig.savefig(IMG / "s2_astro_sens.png"); plt.close(fig)
print("ok")
