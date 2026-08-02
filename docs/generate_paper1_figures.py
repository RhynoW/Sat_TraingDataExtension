"""generate_paper1_figures.py
產生論文一所需的全部 6 張圖，儲存於 docs/ 資料夾。
執行：python docs/generate_paper1_figures.py
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Arc
from matplotlib.gridspec import GridSpec

# ── 字體設定（Windows 中文）──────────────────────────────────────────────────
plt.rcParams.update({
    "font.family":        "Microsoft YaHei",
    "axes.unicode_minus": False,
    "figure.dpi":         150,
    "savefig.dpi":        200,
    "savefig.bbox":       "tight",
})

OUT = os.path.dirname(os.path.abspath(__file__))   # 存到 docs/

# ─────────────────────────────────────────────────────────────────────────────
# 圖一：軌道根數幾何示意圖
# ─────────────────────────────────────────────────────────────────────────────
def fig1_orbital_geometry():
    """軌道六元素 3D 幾何示意圖（參照標準教科書畫法）。"""
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from mpl_toolkits.mplot3d.proj3d import proj_transform
    from matplotlib.patches import FancyArrowPatch

    class Arrow3D(FancyArrowPatch):
        def __init__(self, xs, ys, zs, *a, **k):
            super().__init__((0, 0), (0, 0), *a, **k); self._v = (xs, ys, zs)
        def do_3d_projection(self, renderer=None):
            xs, ys, zs = proj_transform(self._v[0], self._v[1], self._v[2], self.axes.M)
            self.set_positions((xs[0], ys[0]), (xs[1], ys[1])); return min(zs)

    def Rz(t): c, s = np.cos(t), np.sin(t); return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    def Rx(t): c, s = np.cos(t), np.sin(t); return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])

    Om, inc, w = np.radians(40), np.radians(35), np.radians(55)   # RAAN, 傾角, 近地點幅角
    e, a = 0.5, 1.4
    Q = Rz(Om) @ Rx(inc) @ Rz(w)                                   # 近焦點座標 → ECI

    def P(nu):
        r = a * (1 - e**2) / (1 + e * np.cos(nu))
        return Q @ np.array([r * np.cos(nu), r * np.sin(nu), 0.0])

    nu = np.linspace(0, 2 * np.pi, 400)
    r = a * (1 - e**2) / (1 + e * np.cos(nu))
    orbit = Q @ np.vstack([r * np.cos(nu), r * np.sin(nu), np.zeros_like(nu)])
    perigee, apogee = P(0.0), P(np.pi)
    nu_sat = np.radians(62); sat = P(nu_sat)
    an, dn = P(-w), P(np.pi - w)                                   # 升 / 降交點
    node_dir = Rz(Om) @ np.array([1., 0, 0])

    fig = plt.figure(figsize=(9.8, 8))
    ax = fig.add_subplot(111, projection="3d")
    ax.set_box_aspect((1, 1, 0.66)); ax.view_init(elev=24, azim=-62); ax.set_axis_off()
    ang = np.linspace(0, 2 * np.pi, 90)

    # 赤道面（灰）與軌道面（藍）半透明圓盤
    Req, Rop = 1.75, 2.3
    eq = np.vstack([Req * np.cos(ang), Req * np.sin(ang), np.zeros_like(ang)]).T
    ax.add_collection3d(Poly3DCollection([eq], facecolor="#b7c2cb", alpha=0.34,
                                         edgecolor="#8a99a6", lw=0.6))
    op = (Q @ np.vstack([Rop * np.cos(ang), Rop * np.sin(ang), np.zeros_like(ang)])).T
    ax.add_collection3d(Poly3DCollection([op], facecolor="#c3dcf0", alpha=0.22,
                                         edgecolor="#7fa8d0", lw=0.6))

    ax.plot(1.2 * np.cos(ang), 1.2 * np.sin(ang), 0 * ang, color="#1a1a1a", lw=1.1)  # 赤道圈
    ax.plot(orbit[0], orbit[1], orbit[2], color="#1f4e9c", lw=3.2, zorder=10)        # 軌道

    ax.scatter([0], [0], [0], color="#222", s=22, depthshade=False, zorder=11)
    for pt in (perigee, apogee, sat):
        ax.plot([0, pt[0]], [0, pt[1]], [0, pt[2]], color="#e6a3b8", lw=0.9, zorder=5)
    ax.plot([0, apogee[0]], [0, apogee[1]], [0, apogee[2]], color="#7a7a7a",
            lw=1.4, ls=":", zorder=6)                             # a(1+e)
    ax.plot([dn[0], an[0]], [dn[1], an[1]], [dn[2], an[2]], color="#3a6ea5",
            lw=1.0, alpha=0.7)                                    # 交點線

    def dot(pt, lab, col="#111", off=(0.12, 0.12, 0.16), m="o", s=45):
        ax.scatter([pt[0]], [pt[1]], [pt[2]], color=col, marker=m, s=s,
                   depthshade=False, zorder=13)
        ax.text(pt[0] + off[0], pt[1] + off[1], pt[2] + off[2], lab, fontsize=10.5,
                fontweight="bold", color=col, zorder=14)
    dot(perigee, "Perigee", off=(0.12, 0.18, 0.22))
    dot(apogee, "Apogee", off=(-0.1, -0.25, -0.28))
    dot(an, "Ascending\nNode", off=(0.2, -0.05, -0.42))
    dot(dn, "Descending\nNode", off=(-0.35, 0.15, 0.28))
    dot(sat, "Satellite", col="#c1121f", m="s", s=85, off=(-0.15, 0.1, 0.5))

    # 春分點方向（+X）；以 γ 代 ♈（字型無 ♈ 字符）
    ax.add_artist(Arrow3D([0, 2.4], [0, 0], [0, 0], mutation_scale=15, lw=1.7,
                          arrowstyle="-|>", color="#111"))
    ax.text(2.55, 0, 0.04, "γ  Vernal Equinox", fontsize=10.5, fontweight="bold", color="#111")

    # 平面 / 軌道文字
    ax.text(*(Q @ np.array([Rop - 0.05, -0.2, 0])), "Orbital Plane", color="#2f6090",
            fontsize=10, fontweight="bold")
    ax.text(*np.array([Req * np.cos(np.radians(-46)), Req * np.sin(np.radians(-46)), 0]),
            "Equatorial Plane", color="#5a6672", fontsize=10, fontweight="bold")
    ax.text(orbit[0, 182] - 0.5, orbit[1, 182] - 0.1, orbit[2, 182] - 0.05, "Orbit",
            color="#1f4e9c", fontsize=11, fontweight="bold")
    ax.text(1.2 * np.cos(np.radians(212)), 1.2 * np.sin(np.radians(212)), -0.02,
            "Equator", color="#1a1a1a", fontsize=9.5)

    # 角度弧與希臘字母（不同半徑，避免投影後重疊）
    def arc(pts, col, lw=2.4): ax.plot(pts[0], pts[1], pts[2], color=col, lw=lw, zorder=9)
    ph = np.linspace(0, Om, 40)                                   # Ω 於赤道面
    arc(np.vstack([0.62 * np.cos(ph), 0.62 * np.sin(ph), 0 * ph]), "#2ca02c")
    ax.text(*(0.82 * np.array([np.cos(Om / 2), np.sin(Om / 2), 0])), "Ω",
            color="#2ca02c", fontsize=15, fontweight="bold")
    ph = np.linspace(-w, 0, 40)                                   # ω 於軌道面
    arc(Q @ np.vstack([0.92 * np.cos(ph), 0.92 * np.sin(ph), 0 * ph]), "#7b3fbf")
    ax.text(*(Q @ (1.12 * np.array([np.cos(-w / 2), np.sin(-w / 2), 0]))), "ω",
            color="#7b3fbf", fontsize=15, fontweight="bold")
    ph = np.linspace(0, nu_sat, 40)                              # ν 真近點角
    arc(Q @ np.vstack([0.46 * np.cos(ph), 0.46 * np.sin(ph), 0 * ph]), "#d62728")
    ax.text(*(Q @ (0.6 * np.array([np.cos(nu_sat / 2), np.sin(nu_sat / 2), 0]))), "ν",
            color="#d62728", fontsize=15, fontweight="bold")
    # i 傾角（兩平面二面角，置於升交點外側較開闊處）
    e_eq = np.cross(np.array([0, 0, 1.]), node_dir); e_eq /= np.linalg.norm(e_eq)
    e_orb = np.cross(Q @ np.array([0, 0, 1.]), node_dir); e_orb /= np.linalg.norm(e_orb)
    if np.dot(e_eq, e_orb) < 0:
        e_orb = -e_orb
    ii = np.arccos(np.clip(np.dot(e_eq, e_orb), -1, 1))
    t = np.linspace(0, 1, 40)
    iv = (np.sin((1 - t) * ii)[:, None] * e_eq + np.sin(t * ii)[:, None] * e_orb) / np.sin(ii)
    cen = 1.6 * node_dir                                          # 升交點外側（右下）
    arc(cen[:, None] + 0.5 * iv.T, "#0e8ba8")
    ax.text(*(cen + 0.62 * iv[len(iv) // 2]), "i", color="#0e8ba8",
            fontsize=15, fontweight="bold", style="italic")

    ax.set_xlim(-2.3, 3.2); ax.set_ylim(-2.3, 2.3); ax.set_zlim(-1.7, 1.7)
    fig.text(0.5, 0.065, "圖 A-1　軌道六元素", ha="center", fontsize=14, fontweight="bold")

    out = os.path.join(OUT, "fig1_orbital_geometry.png")
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved {out}")


# ─────────────────────────────────────────────────────────────────────────────
# 圖二：半長軸時序對比（大氣阻力 vs 機動 vs P4 案例）
# ─────────────────────────────────────────────────────────────────────────────
def fig2_timeseries():
    rng = np.random.default_rng(42)
    days = np.arange(0, 31)

    fig, axes = plt.subplots(1, 3, figsize=(13, 4.5), sharey=False)
    colors = {"drag": "#2266cc", "maneuver": "#cc2200", "ref": "#888888"}

    # ─ 左：大氣阻力自然衰減（單調下降）────────────────────────
    a_drag = 6920.0 - days * 0.18 + rng.normal(0, 0.08, len(days))
    axes[0].plot(days, a_drag, "o-", color=colors["drag"], ms=4, lw=1.5)
    axes[0].set_title("(a) 大氣阻力自然衰減", fontsize=11, fontweight="bold")
    axes[0].set_xlabel("天（Day）", fontsize=10)
    axes[0].set_ylabel("半長軸 a（km）", fontsize=10)
    axes[0].annotate("單調連續下降\n（P1 識別為大氣阻力）",
                     xy=(15, a_drag[15]), xytext=(5, a_drag[15] - 0.8),
                     fontsize=9, color=colors["drag"],
                     arrowprops=dict(arrowstyle="->", color=colors["drag"]))

    # ─ 中：軌道機動（突然跳升）─────────────────────────────────
    a_man = 6920.0 - days * 0.10 + rng.normal(0, 0.08, len(days))
    a_man[18:] += 5.5   # Day 18 機動：+5.5 km
    axes[1].plot(days[:19], a_man[:19], "o-", color=colors["ref"], ms=4, lw=1.5)
    axes[1].plot(days[18:], a_man[18:], "o-", color=colors["maneuver"], ms=4, lw=1.5)
    axes[1].axvline(x=18, color="#ff8800", lw=1.5, ls="--", alpha=0.8)
    axes[1].annotate("機動點\nΔa ≈ +5.5 km",
                     xy=(18, a_man[18]), xytext=(20, a_man[18]+1.5),
                     fontsize=9, color="#cc6600",
                     arrowprops=dict(arrowstyle="->", color="#cc6600"))
    axes[1].set_title("(b) 主動軌道機動（跳升）", fontsize=11, fontweight="bold")
    axes[1].set_xlabel("天（Day）", fontsize=10)
    axes[1].set_ylabel("半長軸 a（km）", fontsize=10)

    # ─ 右：P4 補充偵測案例────────────────────────────────────
    a_p4 = 6920.0 - days * 0.12 + rng.normal(0, 0.08, len(days))
    # 機動集中在 Day 8–14（第二個 7 天窗口）
    a_p4[8:15] += np.array([0.3, 1.5, 3.0, 3.8, 3.6, 3.5, 3.4])
    a_p4[15:] += 3.4
    ax3 = axes[2]
    ax3.plot(days, a_p4, "o-", color="#555555", ms=4, lw=1.5, alpha=0.5,
             label="30 天整體")
    # y 軸上下各留白，供圖內標註使用（避免文字掉到 x 軸刻度上）
    ymin, ymax = float(a_p4.min()), float(a_p4.max())
    ax3.set_ylim(ymin - 0.9, ymax + 1.05)
    # 標出 4 個子窗口；標籤以「軸分數座標」置於圖內底部，不與 x 軸刻度重疊
    win_colors = ["#cce8ff", "#ffe4cc", "#d4f0d0", "#f5d0f5"]
    win_labels = ["窗口1\n(D1-7)", "窗口2\n(D8-14)", "窗口3\n(D15-21)", "窗口4\n(D22-28)"]
    for k, (ws, we) in enumerate([(1,7),(8,14),(15,21),(22,28)]):
        ax3.axvspan(ws, we, alpha=0.35, color=win_colors[k], zorder=0)
        ax3.text((ws+we)/2, 0.03, win_labels[k],
                 transform=ax3.get_xaxis_transform(),
                 ha="center", va="bottom", fontsize=7, color="#555555")
    # 兩個標註分置頂部左右開放區，彼此不重疊、也不壓到座標軸
    ax3.annotate("P4 在窗口2偵測到機動！",
                 xy=(11, a_p4[11]), xytext=(0.5, ymax + 0.55),
                 fontsize=8.5, color="#880099", ha="left",
                 arrowprops=dict(arrowstyle="->", color="#880099"))
    ax3.annotate("主窗口未觸發（整體 flag_rate 偏低）",
                 xy=(27, a_p4[27]), xytext=(30.3, ymax + 0.55),
                 fontsize=8, color="#555555", ha="right",
                 arrowprops=dict(arrowstyle="->", color="#555555"))
    ax3.set_title("(c) P4 多窗口補充偵測案例", fontsize=11, fontweight="bold")
    ax3.set_xlabel("天（Day）", fontsize=10)
    ax3.set_ylabel("半長軸 a（km）", fontsize=10)

    fig.suptitle("圖 A-2：半長軸時序變化三種典型模式",
                 fontsize=13, fontweight="bold", y=1.01)
    fig.tight_layout()
    out = os.path.join(OUT, "fig2_timeseries.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  saved {out}")


# ─────────────────────────────────────────────────────────────────────────────
# 圖三：偵測流程圖（含 P1–P4）
# ─────────────────────────────────────────────────────────────────────────────
def fig3_flowchart():
    fig, ax = plt.subplots(figsize=(10, 13))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 13)
    ax.axis("off")

    def box(cx, cy, w, h, txt, fc="#dce9f8", ec="#336699", fs=9.5, fw="normal"):
        rect = FancyBboxPatch((cx - w/2, cy - h/2), w, h,
                              boxstyle="round,pad=0.1",
                              fc=fc, ec=ec, lw=1.5, zorder=3)
        ax.add_patch(rect)
        ax.text(cx, cy, txt, ha="center", va="center",
                fontsize=fs, fontweight=fw, zorder=4,
                multialignment="center")

    def diamond(cx, cy, w, h, txt, fc="#fff3cc", ec="#aa7700", fs=9):
        xs = [cx, cx+w/2, cx, cx-w/2, cx]
        ys = [cy+h/2, cy, cy-h/2, cy, cy+h/2]
        ax.fill(xs, ys, fc=fc, ec=ec, lw=1.5, zorder=3)
        ax.text(cx, cy, txt, ha="center", va="center",
                fontsize=fs, zorder=4, multialignment="center")

    def arrow(x1, y1, x2, y2, txt="", col="#336699"):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="-|>",
                                   color=col, lw=1.4),
                    zorder=2)
        if txt:
            mx, my = (x1+x2)/2, (y1+y2)/2
            ax.text(mx+0.15, my, txt, fontsize=8.5, color=col, va="center")

    # ── 節點定義（從上到下）──
    box(5, 12.3, 3.5, 0.75, "讀入 TLE 資料庫\n（Space-Track，14,019 顆）",
        fc="#cce4ff", fs=9.5, fw="bold")
    arrow(5, 11.93, 5, 11.33)

    box(5, 11.0, 3.5, 0.60, "計算相鄰 TLE 差值\nΔa、Δi、ΔΩ_res（J2 修正）", fs=9)
    arrow(5, 10.70, 5, 10.15)

    diamond(5, 9.75, 3.5, 0.70, "|Δa| > θa 或\n|Δi| > θi 或 |ΔΩ| > θΩ ?", fs=8.5)
    arrow(5, 9.40, 5, 8.85)
    ax.text(5.15, 9.12, "是", fontsize=9, color="#008800")
    arrow(6.75, 9.75, 8.5, 9.75, "否", "#aa0000")
    box(9.0, 9.75, 1.6, 0.55, "未觸發旗標\n（跳至 P4）", fc="#f0f0f0", ec="#aaaaaa", fs=8)

    box(5, 8.52, 3.5, 0.60, "旗標：maneuver_candidate = True")
    arrow(5, 8.22, 5, 7.62)

    # P1
    box(5, 7.30, 3.8, 0.60,
        "P1：單調衰減判斷\nneg_streak≥5 AND drop>5km AND net_da<−3km ?",
        fc="#ffe8d0", ec="#cc6600", fs=8.5)
    arrow(5, 7.00, 5, 6.42)
    ax.text(5.15, 6.70, "否（非單調衰減）", fontsize=9, color="#008800")
    arrow(6.90, 7.30, 8.5, 7.30, "是，且無激增點", "#cc6600")
    box(9.0, 7.30, 1.6, 0.55, "P1 抑制\n（誤報排除）", fc="#ffe0c0", ec="#cc6600", fs=8)

    # 激增點救援
    box(5, 6.10, 3.8, 0.60,
        "P1 救援：monotone_decay=T 且 pos_spikes≥2 ?\n（活躍離軌衛星）",
        fc="#ffe8d0", ec="#cc6600", fs=8.5)
    arrow(5, 5.80, 5, 5.22)
    ax.text(5.15, 5.50, "否或救援成立", fontsize=9, color="#008800")

    # P2
    box(5, 4.90, 3.8, 0.60,
        "P2：高度自適應閾值\nθa = 2.0/1.0/0.5 km（依 alt < 400/600 km）",
        fc="#d8f0d0", ec="#336600", fs=8.5)
    arrow(5, 4.60, 5, 4.02)

    # P3
    box(5, 3.70, 3.8, 0.60,
        "P3：B* 輔助\nbstar_mean>0.0005 AND sma<RE+450km\n→ 放寬 neg_streak 門檻 5→3",
        fc="#ead8f5", ec="#660099", fs=8.5)
    arrow(5, 3.40, 5, 2.82)

    box(5, 2.52, 3.5, 0.60, "maneuver_detected = True\n（主偵測輸出）",
        fc="#ccf0cc", ec="#006600", fs=9.5, fw="bold")

    # P4 分支
    arrow(8.5, 9.75, 8.5, 1.75)
    ax.text(8.62, 5.5, "未觸發主偵測的衛星", fontsize=8.5, color="#880099",
            rotation=90, va="center")
    box(8.5, 1.50, 2.6, 0.65,
        "P4：4 × 7 天子窗口\n逐窗口重新偵測",
        fc="#f0d8f5", ec="#660099", fs=8.5)
    arrow(8.5, 1.17, 8.5, 0.68)
    box(8.5, 0.45, 2.6, 0.45,
        "multi_window_detected = True",
        fc="#ccf0cc", ec="#006600", fs=8)

    ax.set_title("圖 A-4：TLE 差分機動偵測流程（含 P1–P4 改進策略）",
                 fontsize=13, fontweight="bold", y=0.995)

    out = os.path.join(OUT, "fig3_flowchart.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  saved {out}")


# ─────────────────────────────────────────────────────────────────────────────
# 圖四：P2 高度自適應閾值示意圖
# ─────────────────────────────────────────────────────────────────────────────
def fig4_p2_threshold():
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))

    # ─ 左：閾值 vs 高度折線圖 ─────────────────────────────────
    alts = np.array([200, 400, 400, 600, 600, 1000])
    thrs = np.array([2.0, 2.0, 1.0, 1.0, 0.5,  0.5])
    axes[0].plot(alts, thrs, "b-o", lw=2.0, ms=7)
    axes[0].axvspan(200, 400, alpha=0.12, color="#ff8800", label="<400 km（高阻力）")
    axes[0].axvspan(400, 600, alpha=0.12, color="#2288ff", label="400–600 km（標準）")
    axes[0].axvspan(600, 1000, alpha=0.12, color="#22aa22", label=">600 km（低阻力）")

    axes[0].text(300, 2.12, "θa = 2.0 km", ha="center", fontsize=10, color="#cc5500")
    axes[0].text(500, 1.12, "θa = 1.0 km", ha="center", fontsize=10, color="#1155cc")
    axes[0].text(780, 0.62, "θa = 0.5 km", ha="center", fontsize=10, color="#118822")

    axes[0].set_xlabel("軌道高度（km）", fontsize=11)
    axes[0].set_ylabel("Δa 偵測閾值 θa（km）", fontsize=11)
    axes[0].set_title("(a) P2 高度自適應閾值設定", fontsize=11, fontweight="bold")
    axes[0].set_ylim(0, 2.8)
    axes[0].legend(fontsize=9, loc="upper right")
    axes[0].grid(True, alpha=0.3)

    # ─ 右：不同高度的大氣阻力噪音示意 ──────────────────────────
    rng = np.random.default_rng(0)
    n = 30
    for alt_center, noise_std, color, lbl in [
        (400,  0.55, "#ff8800", "350 km（高噪音，θ=2.0 km）"),
        (550,  0.25, "#2266cc", "550 km（標準，θ=1.0 km）"),
        (700,  0.10, "#22aa22", "700 km（低噪音，θ=0.5 km）"),
    ]:
        da = rng.normal(0, noise_std, n)
        axes[1].scatter(np.arange(n), da, s=20, alpha=0.6, color=color)

    axes[1].axhline(2.0,  color="#ff8800", lw=1.5, ls="--", alpha=0.8)
    axes[1].axhline(-2.0, color="#ff8800", lw=1.5, ls="--", alpha=0.8)
    axes[1].axhline(1.0,  color="#2266cc", lw=1.5, ls="--", alpha=0.8)
    axes[1].axhline(-1.0, color="#2266cc", lw=1.5, ls="--", alpha=0.8)
    axes[1].axhline(0.5,  color="#22aa22", lw=1.5, ls="--", alpha=0.8)
    axes[1].axhline(-0.5, color="#22aa22", lw=1.5, ls="--", alpha=0.8)

    axes[1].text(31, 2.05, "θ=2.0", fontsize=8, color="#ff8800", va="bottom")
    axes[1].text(31, 1.05, "θ=1.0", fontsize=8, color="#2266cc", va="bottom")
    axes[1].text(31, 0.55, "θ=0.5", fontsize=8, color="#22aa22", va="bottom")

    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0],[0], marker='o', color='w', markerfacecolor='#ff8800',
               markersize=8, label="350 km（θa=2.0 km）"),
        Line2D([0],[0], marker='o', color='w', markerfacecolor='#2266cc',
               markersize=8, label="550 km（θa=1.0 km）"),
        Line2D([0],[0], marker='o', color='w', markerfacecolor='#22aa22',
               markersize=8, label="700 km（θa=0.5 km）"),
    ]
    axes[1].legend(handles=legend_elements, fontsize=8.5, loc="upper right")
    axes[1].set_xlabel("TLE 觀測序號", fontsize=11)
    axes[1].set_ylabel("Δa 噪音水準（km）", fontsize=11)
    axes[1].set_title("(b) 不同高度的 Δa 噪音水準與閾值對照", fontsize=11, fontweight="bold")
    axes[1].set_xlim(-1, 33)
    axes[1].grid(True, alpha=0.3)

    fig.suptitle("圖 A-3：P2 高度自適應閾值示意圖",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    out = os.path.join(OUT, "fig4_p2_threshold.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  saved {out}")


# ─────────────────────────────────────────────────────────────────────────────
# 圖五：消融實驗結果（分組柱狀圖）
# ─────────────────────────────────────────────────────────────────────────────
def fig5_ablation():
    configs = [
        "基準版\n（無改進）",
        "+P1\n（單調抑制）",
        "+P1+P2\n（高度自適應）",
        "+P1+P2+P3\n（B*輔助）",
        "完整 P1–P4\n（含多窗口）",
    ]
    fp_vals  = [68,    41,    27,    25,    29   ]
    prec     = [94.8,  96.6,  97.6,  97.8,  97.5 ]
    recall   = [12.2,  11.3,  10.9,  10.8,  11.1 ]
    f1       = [21.7,  20.2,  19.6,  19.5,  19.9 ]

    x = np.arange(len(configs))
    w = 0.22

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 9))
    fig.subplots_adjust(hspace=0.45)

    # ─ 上圖：精確率 / 召回率 / F1 ─────────────────────────────
    b1 = ax1.bar(x - w,   prec,   w, label="精確率 Precision",
                 color="#2266cc", alpha=0.85)
    b2 = ax1.bar(x,       recall, w, label="召回率 Recall",
                 color="#22aa44", alpha=0.85)
    b3 = ax1.bar(x + w,   f1,     w, label="F1 分數",
                 color="#cc6622", alpha=0.85)

    # 數字標籤
    for bar in b1:
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                 f"{bar.get_height():.1f}%", ha="center", va="bottom",
                 fontsize=7.5, color="#2266cc")
    for bar in b2:
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                 f"{bar.get_height():.1f}%", ha="center", va="bottom",
                 fontsize=7.5, color="#22aa44")
    for bar in b3:
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                 f"{bar.get_height():.1f}%", ha="center", va="bottom",
                 fontsize=7.5, color="#cc6622")

    ax1.set_xticks(x)
    ax1.set_xticklabels(configs, fontsize=9)
    ax1.set_ylabel("指標值（%）", fontsize=11)
    ax1.set_ylim(0, 115)
    ax1.legend(fontsize=10, loc="upper right")
    ax1.set_title("(a) 精確率、召回率與 F1 分數", fontsize=11, fontweight="bold")
    ax1.grid(True, axis="y", alpha=0.3)

    # ─ 下圖：假陽性數量 ────────────────────────────────────────
    bar_colors = ["#ff4444", "#ff7722", "#ffaa00", "#88cc00", "#5588ff"]
    bars = ax2.bar(x, fp_vals, color=bar_colors, alpha=0.85, width=0.5)
    for bar, v in zip(bars, fp_vals):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                 f"{v}", ha="center", va="bottom",
                 fontsize=11, fontweight="bold")
    # 箭頭標示改善
    for i in range(len(fp_vals)-1):
        diff = fp_vals[i+1] - fp_vals[i]
        col = "#008800" if diff < 0 else "#cc0000"
        sign = "▼" if diff < 0 else "▲"
        ax2.annotate(f"{sign}{abs(diff)}", xy=(i+0.5, max(fp_vals[i], fp_vals[i+1])+1.5),
                     ha="center", fontsize=9, color=col)

    ax2.set_xticks(x)
    ax2.set_xticklabels(configs, fontsize=9)
    ax2.set_ylabel("假陽性數量（FP）", fontsize=11)
    ax2.set_ylim(0, 85)
    ax2.set_title("(b) 各改進策略對假陽性數量的影響", fontsize=11, fontweight="bold")
    ax2.grid(True, axis="y", alpha=0.3)

    fig.suptitle("圖 A-5：P1–P4 消融實驗結果\n（2026年5月，14,019顆LEO衛星）",
                 fontsize=13, fontweight="bold")
    out = os.path.join(OUT, "fig5_ablation.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  saved {out}")


# ─────────────────────────────────────────────────────────────────────────────
# 圖六：假陽性縮減瀑布圖 + 誤報來源拆解
# ─────────────────────────────────────────────────────────────────────────────
def fig6_fp_waterfall():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5.5))

    # ─ 左：瀑布圖 ─────────────────────────────────────────────
    stages = ["基準版", "+P1\n（大氣阻力\n識別）", "+P2\n（高度\n自適應）",
              "+P3\n（B*\n輔助）", "+P4\n（多窗口）"]
    fp_seq  = [68, 41, 27, 25, 29]
    bottoms = [0, 0, 0, 0, 0]

    bars = ax1.bar(stages, fp_seq,
                   color=["#cc3333", "#ee6622", "#ffaa00", "#77bb00", "#5588ee"],
                   alpha=0.85, width=0.55)
    for b, v in zip(bars, fp_seq):
        ax1.text(b.get_x() + b.get_width()/2, b.get_height() + 0.8,
                 str(v), ha="center", fontsize=12, fontweight="bold")

    # 差值標示
    diffs = [fp_seq[i+1]-fp_seq[i] for i in range(len(fp_seq)-1)]
    labels = ["−27", "−14", "−2", "+4"]
    cols_d = ["#006600","#006600","#006600","#cc0000"]
    for i, (d, lbl, col) in enumerate(zip(diffs, labels, cols_d)):
        y_mid = (fp_seq[i] + fp_seq[i+1]) / 2
        ax1.annotate(lbl,
                     xy=(i+0.5, max(fp_seq[i], fp_seq[i+1])+1.5),
                     ha="center", fontsize=10, fontweight="bold", color=col)

    ax1.set_ylabel("假陽性數量（FP）", fontsize=11)
    ax1.set_ylim(0, 85)
    ax1.set_title("(a) P1–P4 假陽性逐步縮減過程", fontsize=11, fontweight="bold")
    ax1.grid(True, axis="y", alpha=0.3)

    # ─ 右：誤報來源拆解（堆疊示意）──────────────────────────────
    # 假設誤報來源分析（文中說：60%來自大氣阻力，20%來自磁暴，20%其他）
    cats  = ["大氣阻力\n連續衰減", "太陽活動\n引起的波動", "其他軌道\n攝動"]
    base  = np.array([41, 14, 13])   # 構成基準版 68 FP 的來源比例
    after = np.array([4,  12, 13])   # P1 後剩餘（P1 主要消除大氣阻力 FP）

    x2 = np.arange(len(cats))
    w2 = 0.3
    ax2.bar(x2 - w2/2, base,  w2, label="基準版（共 68 FP）",
            color=["#cc3333","#cc3333","#cc3333"], alpha=0.7)
    ax2.bar(x2 + w2/2, after, w2, label="完整 P1–P4（共 29 FP）",
            color=["#5588ee","#ee6622","#aaaaaa"], alpha=0.85)

    for b in ax2.patches:
        ax2.text(b.get_x() + b.get_width()/2, b.get_height() + 0.3,
                 str(int(b.get_height())), ha="center", fontsize=9.5)

    ax2.set_xticks(x2)
    ax2.set_xticklabels(cats, fontsize=10)
    ax2.set_ylabel("假陽性數量（FP）", fontsize=11)
    ax2.set_ylim(0, 55)
    ax2.legend(fontsize=9.5)
    ax2.set_title("(b) 誤報來源類別拆解（估算）", fontsize=11, fontweight="bold")
    ax2.grid(True, axis="y", alpha=0.3)

    fig.suptitle("圖 A-6：假陽性縮減路徑與誤報來源分析",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    out = os.path.join(OUT, "fig6_fp_waterfall.png")
    fig.savefig(out)
    plt.close(fig)
    print(f"  saved {out}")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("產生論文一圖片中...")
    fig1_orbital_geometry()
    fig2_timeseries()
    fig3_flowchart()
    fig4_p2_threshold()
    fig5_ablation()
    fig6_fp_waterfall()
    print("全部完成。")
