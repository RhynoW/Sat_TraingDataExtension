"""延伸篇 S1–S3 的示意圖與重點數據圖。

數據來源（不新跑模擬）：
- S1 誇張倍率：RUST_SatDashboard/docs/games_debris_architecture.md 第 6 節（Envisat、300 個碎片、×1,000）
- S2 協調假設：s2_data/s2_results.json（run_s2.py，殼層相位修正後）
- S2 地影幾何：圓柱形地影；天頂方向高度 h 的衛星被照亮的條件為 h > R⊕·(1/cos δ − 1)，δ 為太陽俯角
- S3 配對差值：docs/book/sim_wargame/sensitivity/敏感度分析_四想定.md「配對差值」表
用法：python docs/book/sim_chapters/_fig_concepts.py
"""
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle, Wedge

HERE = Path(__file__).resolve().parent
IMG = HERE / "img"
plt.rcParams["font.family"] = ["Microsoft JhengHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

BLUE, ORANGE, AQUA, YELLOW, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#8a8984"
INK, INK2, GRID, LINE = "#0b0b0b", "#52514e", "#e6e5e1", "#c9c8c3"
TINT_B, TINT_O, TINT_G = "#e8f1fc", "#fdeee7", "#f2f1ee"
RE = 6378.137


def style(ax, grid_axis="y"):
    ax.grid(True, axis=grid_axis, color=GRID, lw=0.8); ax.set_axisbelow(True)
    for s in ["top", "right"]: ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]: ax.spines[s].set_color(LINE)
    ax.tick_params(colors=INK2)


def box(ax, x, y, w, h, title, sub="", fc=TINT_B, ec=BLUE):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.06", fc=fc, ec=ec, lw=1.4))
    ax.text(x + w / 2, y + h * (0.64 if sub else 0.5), title, ha="center", va="center", fontsize=10.5, color=INK, weight="bold")
    if sub:
        ax.text(x + w / 2, y + h * 0.3, sub, ha="center", va="center", fontsize=8.2, color=INK2, linespacing=1.35)


def arrow(ax, a, b, color=INK2, rad=0.0, lw=1.4):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=12, color=color, lw=lw,
                                 connectionstyle=f"arc3,rad={rad}", shrinkA=2, shrinkB=2))


def save(fig, name):
    fig.savefig(IMG / name, facecolor="#ffffff"); plt.close(fig); print(name)


# ── S1：模擬流程 ────────────────────────────────────────────────────────────
def s1_pipeline():
    fig, ax = plt.subplots(figsize=(7.4, 3.3), dpi=200)
    fig.subplots_adjust(0.01, 0.01, 0.99, 0.99)
    ax.set_xlim(0, 10); ax.set_ylim(0.1, 4.95); ax.axis("off")
    W, H, y = 2.2, 1.5, 2.9
    xs = [0.05, 2.6, 5.15, 7.7]
    box(ax, xs[0], y, W, H, "① 解體", "NASA 標準解體模型\n尺寸、A/M、Δv")
    box(ax, xs[1], y, W, H, "② 傳播與衰減", "克卜勒根數＋J2\n大氣隨太陽活動變化")
    box(ax, xs[2], y, W, H, "③ 快照找鄰居", "每步 3 個快照\nKD-tree：50 km 內")
    box(ax, xs[3], y, W, H, "④ 期望碰撞與擲骰", "λ ∝ 相對速度 × 截面\n機率 1 − exp(−λ)")
    for i in range(3):
        arrow(ax, (xs[i] + W, y + H / 2), (xs[i + 1], y + H / 2))
    # 擲中 → 下一代
    box(ax, 5.15, 0.35, 4.75, 1.25, "⑤ 擲中：下一代碎片", "能量質量比 > 40 J/g 為完全解體\n以碰撞模型產生，代數 +1",
        fc=TINT_O, ec=ORANGE)
    arrow(ax, (xs[3] + W / 2, y), (xs[3] + W / 2, 1.6), color=ORANGE)
    ax.text(xs[3] + W / 2 + 0.1, 2.25, "擲中", fontsize=8.5, color=ORANGE, va="center")
    arrow(ax, (5.15, 0.98), (xs[1] + W / 2, y), color=ORANGE, rad=-0.25)
    ax.text(3.0, 1.45, "加入族群，回到②", fontsize=8.5, color=ORANGE, ha="center")
    # 再入
    ax.text(xs[1] + W / 2, y + H + 0.2, "近地點 < 120 km 即再入、移出族群", fontsize=8.2, color=INK2, ha="center")
    ax.text(0.05, 0.7, "時間步：前 30 天每 1 天，\n之後每 5／10／30 天；\n每一步重複②–⑤", fontsize=8.2, color=INK2, va="center", linespacing=1.4)
    save(fig, "s1_pipeline.png")


# ── S1：誇張倍率的換算偏差 ──────────────────────────────────────────────────
def s1_accel_bias():
    fig, ax = plt.subplots(figsize=(7.2, 2.6), dpi=200)
    labels = ["線性反推\n（全部期望碰撞 ÷ 倍率）", "第一代碎片近似風險\n（只計第一代 ÷ 倍率）"]
    vals, cols = [1.71, 0.11], [GRAY, BLUE]
    ax.barh(labels, vals, color=cols, height=0.5)
    for i, v in enumerate(vals):
        ax.text(v + 0.03, i, f"{v:.2f} 次", va="center", fontsize=10, color=INK)
    ax.text(0.5, 0.5, "兩種換算相差約 15 倍", fontsize=9.5, color=INK2, ha="left", va="center")
    ax.set_xlim(0, 2.0); ax.set_xlabel("10 年期望碰撞次數（換算回寫實倍率）", color=INK2)
    style(ax, "x"); ax.tick_params(axis="y", length=0)
    fig.tight_layout(); save(fig, "s1_accel_bias.png")


# ── S2：地影幾何 ────────────────────────────────────────────────────────────
def s2_shadow():
    fig, axs = plt.subplots(1, 2, figsize=(7.4, 2.75), dpi=200)
    for ax, dep, lab in [(axs[0], 13, "昏影結束：太陽俯角 13°"), (axs[1], 26, "約 1 小時後：太陽俯角 26°")]:
        hmin = RE * (1 / math.cos(math.radians(dep)) - 1)
        # 座標：地心為原點，觀測者在 (0, RE)、天頂朝上；s 為指向太陽的單位向量（太陽在左下、俯角 dep）
        s = (-math.cos(math.radians(dep)), -math.sin(math.radians(dep)))
        # 地影：與太陽方向平行、寬 2RE 的帶，位於地球背日側
        n = (-s[1], s[0])
        pts = [(n[0] * RE, n[1] * RE), (n[0] * RE - s[0] * 3e4, n[1] * RE - s[1] * 3e4),
               (-n[0] * RE - s[0] * 3e4, -n[1] * RE - s[1] * 3e4), (-n[0] * RE, -n[1] * RE)]
        ax.add_patch(Polygon(pts, closed=True, fc="#d9d8d3", ec="none", zorder=1))
        ax.add_patch(Circle((0, 0), RE, fc="#b7d3f6", ec=BLUE, lw=1.2, zorder=2))
        # 殼層
        for h, c, nm in [(550, ORANGE, "550 km"), (1100, AQUA, "1,100 km")]:
            ax.add_patch(Wedge((0, 0), RE + h, 62, 118, width=0, fill=False, ec=c, lw=1.6, ls=(0, (4, 2)), zorder=3))
            a = math.radians(105)
            ax.text((RE + h) * math.cos(a), (RE + h) * math.sin(a) + 40, nm, fontsize=8, color=c, ha="center", va="bottom", zorder=5)
        # 觀測者與天頂
        ax.plot([0, 0], [RE, RE + 1500], color=INK, lw=1.2, zorder=4)
        ax.plot(0, RE, marker="o", ms=5, color=INK, zorder=5)
        ax.text(60, RE - 90, "觀測者", fontsize=8.5, color=INK, va="top")
        # 照亮界線（天頂方向）
        ax.plot([-260, 260], [RE + hmin] * 2, color=YELLOW, lw=2.2, zorder=5)
        ax.text(-300, RE + hmin, f"{hmin:,.0f} km 以上被照亮", fontsize=8.5, color=INK, ha="right", va="center", zorder=5)
        # 陽光方向（由太陽射來）
        P = (-2200, RE - 250)
        ax.add_patch(FancyArrowPatch((P[0] + s[0] * 700, P[1] + s[1] * 700), P, arrowstyle="-|>",
                                     mutation_scale=12, color=YELLOW, lw=1.8, zorder=5))
        ax.text(P[0] + 80, P[1] + 60, "陽光", fontsize=8.5, color=INK2)
        ax.set_xlim(-3000, 3000); ax.set_ylim(RE - 600, RE + 1700); ax.set_aspect("equal"); ax.axis("off")
        ax.set_title(lab, fontsize=10, color=INK)
    fig.text(0.5, 0.03, "灰色為地球的影子（圓柱形地影模型）；彩色弧線為假想星座殼層。比例為實際比例，只畫觀測者附近。", ha="center",
             fontsize=8, color=INK2)
    fig.subplots_adjust(0.01, 0.1, 0.99, 0.9, wspace=0.04); save(fig, "s2_shadow_geometry.png")


# ── S2：協調假設 vs 第三方 ──────────────────────────────────────────────────
def s2_third_party():
    d = json.loads((HERE / "s2_data/s2_results.json").read_text(encoding="utf-8"))
    rules = ["全部都計", "同殼層不計", "同星座不計"]
    ratio = {k: [] for k in ["plan", "mega"]}
    other = {k: [] for k in ["now", "plan", "mega"]}
    for i in range(3):
        for k in ["plan", "mega"]:
            v = d["crowd"][f"{k}_skip{i}"]
            ratio[k].append(v["scenario"]["enc_day_1km"] / v["baseline"]["enc_day_1km"])
            other[k].append(next(g["per_sat_year_1km"] for g in v["scenario"]["groups"] if g["key"] == "other"))
        other["now"].append(next(g["per_sat_year_1km"] for g in d["crowd"][f"plan_skip{i}"]["baseline"]["groups"] if g["key"] == "other"))
    fig, axs = plt.subplots(1, 2, figsize=(7.4, 3.4), dpi=200)
    x = range(3); w = 0.36
    ax = axs[0]
    for j, (k, c, lab) in enumerate([("plan", AQUA, "各家計畫全數"), ("mega", ORANGE, "10 萬 Starlink")]):
        xs = [i + (j - 0.5) * w for i in x]
        ax.bar(xs, ratio[k], width=w - 0.04, color=c, label=lab)
        for xi, v in zip(xs, ratio[k]):
            ax.text(xi, v * 1.08, f"×{v:.1f}", ha="center", fontsize=7.5, color=INK)
    ax.set_yscale("log"); ax.set_ylim(1, 150); ax.set_yticks([1, 10, 100]); ax.set_yticklabels(["×1", "×10", "×100"])
    ax.minorticks_off(); ax.set_xticks(list(x)); ax.set_xticklabels(rules, fontsize=8.5)
    ax.set_title("全系統每天 < 1 km 接近，相對現況", fontsize=9.5, color=INK); style(ax)
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    ax = axs[1]; w = 0.26
    for j, (k, c, lab) in enumerate([("now", BLUE, "現況"), ("plan", AQUA, "各家計畫全數"), ("mega", ORANGE, "10 萬 Starlink")]):
        xs = [i + (j - 1) * w for i in x]
        ax.bar(xs, other[k], width=w - 0.03, color=c, label=lab)
        for xi, v in zip(xs, other[k]):
            ax.text(xi, v + 2, f"{v:.0f}", ha="center", fontsize=7.5, color=INK)
    ax.set_ylim(0, 130); ax.set_xticks(list(x)); ax.set_xticklabels(rules, fontsize=8.5)
    ax.set_title("星座以外物件：每顆每年 < 1 km 接近", fontsize=9.5, color=INK); style(ax)
    ax.legend(frameon=False, fontsize=8, loc="upper left", ncol=3)
    fig.tight_layout(); save(fig, "s2_coordination.png")


# ── S3：回合結構 ────────────────────────────────────────────────────────────
def s3_wego():
    fig, ax = plt.subplots(figsize=(7.4, 3.6), dpi=200)
    fig.subplots_adjust(0.01, 0.01, 0.99, 0.99)
    ax.set_xlim(0, 10); ax.set_ylim(-0.25, 5.2); ax.axis("off")
    # 上：一局 8 回合
    for k in range(8):
        x = 0.4 + k * 1.15
        ax.add_patch(Rectangle((x, 4.25), 1.05, 0.55, fc=TINT_G if k else TINT_O, ec=LINE, lw=1))
        ax.text(x + 0.525, 4.525, f"回合 {k + 1}", ha="center", va="center", fontsize=8.5, color=INK)
    ax.text(0.4, 5.0, "一局：8 回合 × 6 小時 = 48 小時（開場：約三成國際海纜與馬祖海纜中斷）", fontsize=8.8, color=INK2)
    # 下：一個回合內
    y, H = 1.6, 1.55
    box(ax, 0.2, y + 0.95, 2.3, H * 0.75, "藍方下令", "5 行動點\n租 GEO、部署、修纜…")
    box(ax, 0.2, y - 0.95, 2.3, H * 0.75, "紅方下令", "5 行動點\n切纜、干擾、網攻…", fc=TINT_O, ec=ORANGE)
    box(ax, 3.3, y, 2.2, H * 0.75, "白方事件", "天候、颱風\n（隨機）", fc=TINT_G, ec=GRAY)
    box(ax, 6.2, y, 1.9, H * 0.75, "同時裁決", "依規則與\n亂數結算")
    box(ax, 8.6, y, 1.25, H * 0.75, "更新", "可用率\n分數、升級")
    arrow(ax, (2.5, y + 0.95 + H * 0.37), (3.3, y + H * 0.5))
    arrow(ax, (2.5, y - 0.95 + H * 0.37), (3.3, y + H * 0.25))
    arrow(ax, (5.5, y + H * 0.37), (6.2, y + H * 0.37))
    arrow(ax, (8.1, y + H * 0.37), (8.6, y + H * 0.37))
    ax.text(0.2, 3.9, "每個回合內：", fontsize=8.8, color=INK2)
    ax.text(0.2, -0.05, "雙方同時下令，看不到對方本回合的命令（WEGO）。\n蒙地卡羅：每組設定 500 局，種子 1000–1499；各設定共用同一組種子（共同亂數）。",
            fontsize=8.2, color=INK2, linespacing=1.5)
    save(fig, "s3_wego.png")


# ── S3：配對差值 vs 獨立樣本 ────────────────────────────────────────────────
def s3_paired_ci():
    rows = [("A：想定 A − 對照（均衡）", -3.21, 0.01, 0.63), ("B：紅方不干擾 − 基準（均衡）", -6.75, 0.25, 0.53),
            ("C：想定 C − 只接近（重 GEO，升級）", -12.32, 0.04, 0.62), ("D：想定 D − 不用反衛星（重 GEO，升級）", 1.06, 0.29, 0.61)]
    fig, ax = plt.subplots(figsize=(7.4, 3.2), dpi=200)
    for i, (lab, m, p, ind) in enumerate(rows):
        y = len(rows) - 1 - i
        ax.plot([m - ind, m + ind], [y - 0.13] * 2, color=GRAY, lw=2.2, solid_capstyle="round")
        ax.plot([m - p, m + p], [y + 0.13] * 2, color=BLUE, lw=4, solid_capstyle="round")
        ax.plot(m, y + 0.13, "o", ms=6, color=BLUE, mec="#ffffff", mew=1)
        ax.text(m + ind + 0.25, y - 0.13, f"±{ind:.2f}", fontsize=7.8, color=INK2, va="center")
        ax.text(m + ind + 0.25, y + 0.15, f"±{p:.2f}", fontsize=7.8, color=BLUE, va="center")
    ax.set_yticks(range(len(rows))); ax.set_yticklabels([r[0] for r in rows][::-1], fontsize=8.5)
    ax.axvline(0, color=LINE, lw=1)
    ax.set_xlim(-14, 3.5); ax.set_xlabel("兩組設定的平均可用率差值（百分點）與 95% 信賴區間", color=INK2)
    ax.plot([], [], color=BLUE, lw=4, label="逐局配對差值"); ax.plot([], [], color=GRAY, lw=2.2, label="當作兩組獨立樣本")
    ax.legend(frameon=False, fontsize=8, loc="upper left"); style(ax, "x"); ax.tick_params(axis="y", length=0)
    fig.tight_layout(); save(fig, "s3_paired_ci.png")


if __name__ == "__main__":
    for f in [s1_pipeline, s1_accel_bias, s2_shadow, s2_third_party, s3_wego, s3_paired_ci]:
        f()
