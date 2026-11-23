"""延伸篇 S3 審查修訂之新增圖（資料：docs/book/sim_wargame/review_v2/games_v2.csv.gz、summary_v2.json）。

  s3_timeseries.png   想定 A 各打法每回合頻寬可用率（48 小時與 7 天）
  s3_distribution.png 四想定各打法 8 回合平均可用率的分布（第 5／25／50／75／95 百分位）
  s3_rank_prob.png    名次機率（排第一、前二、前三），只比原有固定打法
  s3_geo_attack.png   GEO 可受攻擊與 7 天窗口下，想定 A 各打法的頻寬
  s3_ai_sens.png      替代 AI：紅方風險偏好與目標選擇；藍方閾值規則與簡單效用
  s3_c_decomp.png     想定 C 監視打法的分數優勢：嚇阻、歸因與誤歸因
  s3_d_longterm.png   想定 D：48 小時頻寬與賽後碎片殘留分開呈現
用法：python docs/book/sim_chapters/_fig_s3_v2.py
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RV = HERE.parent / "sim_wargame/review_v2"
IMG = HERE / "img"
plt.rcParams["font.family"] = ["Microsoft JhengHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
BLUE, ORANGE, AQUA, YELLOW, GRAY, PURPLE = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#8a8984", "#8b5cf6"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
NB = {"balanced": "均衡", "geo": "重 GEO", "leo": "重低軌", "repair": "重修纜", "hybrid": "均衡＋備援", "sensor": "感測優先",
      "watch": "太空監視", "evade": "監視＋規避", "spread": "分散租用", "imagery": "重 GEO＋商業影像", "avoid": "均衡＋避碰",
      "threshold": "閾值規則", "utility": "簡單效用"}
COL = {"balanced": BLUE, "geo": ORANGE, "leo": AQUA, "repair": YELLOW, "threshold": GRAY, "utility": PURPLE}
S = json.loads((RV / "summary_v2.json").read_text(encoding="utf-8"))["stats"]
DF = pd.read_csv(RV / "games_v2.csv.gz", usecols=["exp", "red", "blue", "seed", "mean_avail", "blue_score"])


def style(ax, axis="y"):
    ax.grid(True, color=GRID, lw=0.8, axis=axis); ax.set_axisbelow(True)
    for s in ["top", "right"]: ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]: ax.spines[s].set_color("#c9c8c3")
    ax.tick_params(colors=INK2)


def save(fig, name):
    fig.tight_layout(); fig.savefig(IMG / name, facecolor="#ffffff"); plt.close(fig); print(name)


# 1 時間序列 ────────────────────────────────────────────────────────────────
fig, axs = plt.subplots(1, 2, figsize=(9.6, 3.6), dpi=200, gridspec_kw={"width_ratios": [1, 2.2]})
for ax, exp, title in [(axs[0], "A0", "48 小時（8 回合）"), (axs[1], "A0_7d", "7 天（28 回合；需求於第 8 回合後持平）")]:
    for b in ["balanced", "geo", "leo", "repair", "utility"]:
        v = S[exp]["balanced"][b]
        x = np.arange(1, len(v["series_mean"]) + 1) * 6
        ax.plot(x, np.array(v["series_mean"]) * 100, color=COL[b], lw=1.8, label=NB[b])
        ax.fill_between(x, np.array(v["series_p10"]) * 100, np.array(v["series_p90"]) * 100, color=COL[b], alpha=0.10, lw=0)
    ax.set_title(title, fontsize=9.5, color=INK); ax.set_xlabel("開戰後小時", color=INK2, fontsize=8.5)
    ax.set_ylim(15, 101); style(ax)
axs[0].set_ylabel("頻寬可用率（%）", color=INK2, fontsize=8.5)
axs[1].legend(frameon=False, fontsize=7.5, loc="lower left", ncol=3)
save(fig, "s3_timeseries.png")

# 2 分布 ───────────────────────────────────────────────────────────────────
fig, axs = plt.subplots(1, 4, figsize=(10.4, 3.4), dpi=200, sharey=True)
for ax, (exp, title) in zip(axs, [("A0", "想定 A"), ("B0", "想定 B"), ("C0", "想定 C"), ("D0", "想定 D")]):
    st = S[exp]["balanced"]
    bl = [b for b in st if b not in ("threshold", "utility")]
    for i, b in enumerate(bl):
        q = np.array(st[b]["q"]) * 100
        ax.plot([i, i], [q[0], q[4]], color=GRAY, lw=1)
        ax.add_patch(plt.Rectangle((i - 0.28, q[1]), 0.56, q[3] - q[1], color=BLUE, alpha=0.35, lw=0))
        ax.plot([i - 0.28, i + 0.28], [q[2], q[2]], color=BLUE, lw=2)
    ax.set_xticks(range(len(bl))); ax.set_xticklabels([NB[b] for b in bl], rotation=55, fontsize=7.2, ha="right")
    ax.set_title(title, fontsize=9.5, color=INK); style(ax)
axs[0].set_ylabel("8 回合平均頻寬可用率（%）", color=INK2, fontsize=8.5)
save(fig, "s3_distribution.png")

# 3 名次機率（只比原有固定打法；以種子重抽 1,000 次）──────────────────────────
rng = np.random.default_rng(7)
fig, axs = plt.subplots(1, 4, figsize=(10.4, 3.4), dpi=200, sharey=True)
for ax, (exp, red, title) in zip(axs, [("C0", "balanced", "想定 C，灰色地帶"), ("C0", "escalate", "想定 C，升級"),
                                        ("D0", "balanced", "想定 D，灰色地帶"), ("D0", "escalate", "想定 D，升級")]):
    g = DF[(DF.exp == exp) & (DF.red == red) & (~DF.blue.isin(["threshold", "utility"]))]
    piv = g.pivot(index="seed", columns="blue", values="mean_avail")
    cnt = {b: np.zeros(3) for b in piv.columns}
    for _ in range(1000):   # 並列（逐局完全相同的打法）同列名次：rank method="min"
        rk = piv.iloc[rng.integers(0, len(piv), len(piv))].mean().round(10).rank(ascending=False, method="min")
        for bb, r in rk.items():
            for k in range(3):
                if r <= k + 1:
                    cnt[bb][k] += 1
    bl = sorted(cnt, key=lambda b: -cnt[b][0] - cnt[b][1] / 10)
    x = np.arange(len(bl))
    for k, (c, lab) in enumerate([(BLUE, "第一"), ("#8fb8e8", "前二"), ("#d4e3f7", "前三")]):
        ax.bar(x + (k - 1) * 0.26, [cnt[b][k] / 10 for b in bl], width=0.25, color=c, label=lab)
    ax.set_xticks(x); ax.set_xticklabels([NB[b] for b in bl], rotation=55, fontsize=7.2, ha="right")
    ax.set_title(title, fontsize=9, color=INK); style(ax)
axs[0].set_ylabel("重抽中的比例（%）", color=INK2, fontsize=8.5); axs[0].legend(frameon=False, fontsize=7.5)
save(fig, "s3_rank_prob.png")

# 4 GEO 可受攻擊與 7 天 ─────────────────────────────────────────────────────
cases = [("A0", "基準"), ("A_geojam0.25", "GEO 干擾 −25%"), ("A_geojam0.5", "GEO 干擾 −50%"),
         ("A_geojam0.5_adapt", "−50%＋紅方適應"), ("A_geoout0.1", "GEO 中斷 10%／回合"), ("A_geoout0.25", "GEO 中斷 25%／回合"), ("A0_7d", "7 天窗口")]
fig, ax = plt.subplots(figsize=(9.6, 3.8), dpi=200)
x = np.arange(len(cases)); w = 0.14
for j, b in enumerate(["geo", "balanced", "repair", "leo", "utility"]):
    ax.bar(x + (j - 2) * w, [S[e]["balanced"][b]["mean"] * 100 for e, _ in cases], width=w - 0.01, color=COL[b], label=NB[b])
ax.set_xticks(x); ax.set_xticklabels([l for _, l in cases], fontsize=8)
ax.set_ylim(40, 100); ax.set_ylabel("頻寬可用率（%，紅方灰色地帶）", color=INK2, fontsize=8.5)
style(ax); ax.legend(frameon=False, fontsize=7.5, ncol=5, loc="upper right")
save(fig, "s3_geo_attack.png")

# 5 替代 AI（四想定；紅方風險偏好、目標選擇）──────────────────────────────────
fig, axs = plt.subplots(1, 4, figsize=(10.4, 3.5), dpi=200, sharey=True)
for ax, sc in zip(axs, "ABCD"):
    base = {"A": "A0", "B": "B0", "C": "C0", "D": "D0"}[sc]
    exps = [(f"{sc}_aggr0.5", "保守"), (base, "基準"), (f"{sc}_aggr1.5", "激進"), (f"{sc}_target_random", "隨機目標"), (f"{sc}_target_adaptive", "適應目標")]
    bl = ["balanced", "geo", "utility", "threshold"] + (["evade"] if sc == "C" else ["hybrid"] if sc == "B" else [])
    for b in bl:
        ax.plot(range(len(exps)), [S[e]["balanced"][b]["mean"] * 100 for e, _ in exps], "o-", ms=3.5, lw=1.4,
                color=COL.get(b, "#c0392b"), label=NB[b])
    ax.set_xticks(range(len(exps))); ax.set_xticklabels([l for _, l in exps], rotation=40, fontsize=7.5, ha="right")
    ax.set_title(f"想定 {sc}", fontsize=9.5, color=INK); style(ax)
    ax.legend(frameon=False, fontsize=6.5, loc="lower left")
axs[0].set_ylabel("頻寬可用率（%，紅方灰色地帶）", color=INK2, fontsize=8.5)
save(fig, "s3_ai_sens.png")

# 6 想定 C 分解 ─────────────────────────────────────────────────────────────
rows = [("C0", "基準（嚇阻＋歸因）"), ("C_nodeter", "只有歸因（被監視不降出手率）"), ("C_rep0.0", "只有嚇阻（歸因不加分）"),
        ("C_nodeter_rep0", "兩者皆無"), ("C_attrib0.5", "歸因成功率 50%"), ("C_misattr0.1", "誤歸因 10%／回合"), ("C_misattr0.3", "誤歸因 30%／回合")]
fig, axs = plt.subplots(1, 2, figsize=(9.6, 3.6), dpi=200, gridspec_kw={"width_ratios": [1.5, 1]})
ax = axs[0]
for k, (red, c, lab) in enumerate([("balanced", BLUE, "灰色地帶紅方"), ("escalate", ORANGE, "升級紅方")]):
    vals = [S[e][red]["watch"]["blue_score"] - S[e][red]["balanced"]["blue_score"] for e, _ in rows]
    ax.barh(np.arange(len(rows)) + (k - 0.5) * 0.36, vals, height=0.34, color=c, label=lab)
ax.axvline(0, color="#c9c8c3", lw=1)
ax.set_yticks(range(len(rows))); ax.set_yticklabels([l for _, l in rows], fontsize=7.8); ax.invert_yaxis()
ax.set_xlabel("「太空監視」總分 − 「均衡」總分", color=INK2, fontsize=8.5); style(ax, "x"); ax.legend(frameon=False, fontsize=7.5)
ax = axs[1]
v = [S[e]["balanced"]["watch"]["struck"] * 100 for e, _ in rows[:4]]
ax.bar(range(4), v, color=GRAY)
ax.set_xticks(range(4)); ax.set_xticklabels(["基準", "只有歸因", "只有嚇阻", "兩者皆無"], fontsize=7.8)
ax.set_ylabel("監視打法遭攻擊率（%，灰色地帶）", color=INK2, fontsize=8.5); style(ax)
save(fig, "s3_c_decomp.png")

# 7 想定 D：48 小時與長期分開 ─────────────────────────────────────────────────
fig, axs = plt.subplots(1, 2, figsize=(9.6, 3.4), dpi=200)
ax = axs[0]
bl = ["balanced", "avoid", "geo", "imagery", "leo"]
x = np.arange(len(bl))
ax.bar(x - 0.18, [S["D_noasat"]["escalate"][b]["mean"] * 100 for b in bl], 0.34, color=GRAY, label="紅方不用反衛星")
ax.bar(x + 0.18, [S["D0"]["escalate"][b]["mean"] * 100 for b in bl], 0.34, color=ORANGE, label="升級紅方（想定 D）")
ax.set_xticks(x); ax.set_xticklabels([NB[b] for b in bl], fontsize=7.5, rotation=20)
ax.set_ylim(60, 95); ax.set_ylabel("48 小時頻寬可用率（%）", color=INK2, fontsize=8.5)
ax.set_title("遊戲窗口內：頻寬幾乎不受影響", fontsize=9, color=INK); style(ax); ax.legend(frameon=False, fontsize=7.5)
ax = axs[1]
ax.plot([0, 0.5, 1, 3], [100, 53.6, 25.3, 0.9], "o-", color=BLUE, lw=1.8)
ax.set_xlabel("解體後年數", color=INK2, fontsize=8.5); ax.set_ylabel("已編目碎片仍在軌比例（%）", color=INK2, fontsize=8.5)
ax.set_title("遊戲窗口外：Cosmos 1408（約 480 km，實測）", fontsize=9, color=INK); style(ax)
ax.text(1.2, 70, "僅示意碎片壽命的量級；\n與遊戲中藍方衛星的高度\n與碎片數不直接可比", fontsize=7.5, color=INK2)
save(fig, "s3_d_longterm.png")
