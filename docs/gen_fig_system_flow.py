#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_fig_system_flow.py — 期末報告流程圖：
  fig_sys_architecture.png  系統總架構（資料 → 管線 → 偵測方法 → 兩種輸出 → 分析人員複核）
  fig_sys_r7_flow.png       R7 單星報表判定流程（候選事件主線＋低置信複核項支線）
  fig_sys_routing.png       App 統一偵測摘要之路由（Starlink／非 Starlink／再入）

用法：python docs/gen_fig_system_flow.py
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

plt.rcParams["font.family"] = ["Microsoft JhengHei", "Microsoft YaHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
OUT = Path(__file__).resolve().parent

INK, MUTED = "#1f2937", "#4b5563"
C_DATA = ("#eef2f7", "#64748b")     # 資料／管線：灰藍
C_RULE = ("#e8f1fb", "#1f4e79")     # 非 AI 方法：藍
C_AI = ("#fdf0e6", "#c2410c")       # AI 方法：橙
C_OUT = ("#ecf7ef", "#2f7d4a")      # 輸出：綠
C_HUMAN = ("#f5f0fa", "#6b4c9a")    # 人工：紫


def box(ax, x, y, w, h, title, body="", col=C_RULE, title_size=11.5, body_size=9.2, dashed=False):
    fill, edge = col
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.006,rounding_size=0.014",
                                fc=fill, ec=edge, lw=1.8, ls="--" if dashed else "-"))
    if body:
        ax.text(x + w / 2, y + h - 0.022, title, ha="center", va="top", fontsize=title_size,
                color=edge, fontweight="bold")
        ax.text(x + w / 2, y + h - 0.062, body, ha="center", va="top", fontsize=body_size,
                color=INK, linespacing=1.45)
    else:
        ax.text(x + w / 2, y + h / 2, title, ha="center", va="center", fontsize=title_size,
                color=edge, fontweight="bold")


def arrow(ax, p0, p1, color=MUTED, lw=1.6, ls="-", text="", tpos=0.5, toff=(0, 0.012), ts=8.8):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=13, color=color, lw=lw,
                                 ls=ls, shrinkA=0, shrinkB=0))
    if text:
        tx = p0[0] + (p1[0] - p0[0]) * tpos + toff[0]
        ty = p0[1] + (p1[1] - p0[1]) * tpos + toff[1]
        ax.text(tx, ty, text, ha="center", va="bottom", fontsize=ts, color=color)


def canvas(w_in, h_in):
    fig = plt.figure(figsize=(w_in, h_in), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax


def legend(ax, y=0.025):
    items = [(C_DATA, "資料與管線"), (C_RULE, "非 AI 方法（規則、統計、物理）"),
             (C_AI, "AI 方法（機器學習）"), (C_OUT, "系統輸出"), (C_HUMAN, "分析人員")]
    x = 0.04
    for col, lab in items:
        ax.add_patch(FancyBboxPatch((x, y), 0.022, 0.018, boxstyle="round,pad=0.002",
                                    fc=col[0], ec=col[1], lw=1.4))
        ax.text(x + 0.03, y + 0.009, lab, va="center", fontsize=9, color=INK)
        x += 0.03 + 0.0105 * len(lab) + 0.035


# ── 圖 1：系統總架構 ─────────────────────────────────────────────────────────
def fig_architecture():
    fig, ax = canvas(12, 8.2)
    ax.text(0.5, 0.975, "系統總架構：由公開 TLE 到分析人員複核", ha="center", va="top",
            fontsize=15, fontweight="bold", color=INK)

    # 第 1 列：資料來源
    y1, h1 = 0.80, 0.115
    box(ax, 0.04, y1, 0.27, h1, "公開 TLE（Space-Track）", "全編目衛星每日更新\n偵測的唯一輸入", C_DATA)
    box(ax, 0.365, y1, 0.27, h1, "太空天氣指數", "F10.7 太陽通量、Ap 地磁指數\n供門檻調整與大氣密度計算", C_DATA)
    box(ax, 0.69, y1, 0.27, h1, "精密星曆真值（MEME、ILRS／IDS）", "僅用於模型訓練與效能驗證\n不參與日常偵測", C_DATA, dashed=True)

    # 第 2 列：資料管線
    y2, h2 = 0.655, 0.095
    box(ax, 0.04, y2, 0.595, h2, "① 資料管線",
        "每日下載入庫 → 資料品質稽核（缺口、異常值標記）→ 資料庫與線上資料集同步（失敗即停、不發佈）", C_DATA,
        body_size=9.2)
    for x in (0.175, 0.50):
        arrow(ax, (x, y1), (x, y2 + h2))
    arrow(ax, (0.825, y1), (0.825, 0.55), ls="--", text="訓練／驗證", tpos=0.35, toff=(0.045, 0))

    # 第 3 列：偵測方法
    y3, h3 = 0.375, 0.2
    ax.add_patch(FancyBboxPatch((0.03, y3 - 0.012), 0.94, h3 + 0.05, boxstyle="round,pad=0.006",
                                fc="white", ec="#cbd5e1", lw=1.2))
    ax.text(0.045, y3 + h3 + 0.03, "② 偵測方法（同一套程式，供兩種輸出共用）", fontsize=11, color=MUTED,
            fontweight="bold", va="center")
    bw, gap = 0.205, 0.03
    xs = [0.045 + i * (bw + gap) for i in range(4)]
    box(ax, xs[0], y3, bw, h3 - 0.02, "L1 規則（P1–P6）",
        "相鄰兩筆 TLE 半長軸變化\n超過高度自適應門檻即標記\n並排除阻力衰減等假警報", C_RULE)
    box(ax, xs[1], y3, bw, h3 - 0.02, "L2 統計變點",
        "CUSUM、BOCPD、SSA、\nMAD 3σ 四種方法\n偵測時間序列的突變", C_RULE)
    box(ax, xs[2], y3, bw, h3 - 0.02, "NRLMSIS 阻力殘差",
        "以大氣模型扣除阻力\n殘差 > 0.3 km 視為\n阻力無法解釋的變化", C_RULE)
    box(ax, xs[3], y3, bw, h3 - 0.02, "機器學習模型",
        "Model 1：LightGBM（監督式）\n融合評分器：HistGBM\nModel 2：Isolation Forest\n（前兩者以 Starlink 資料訓練）", C_AI)
    arrow(ax, (0.3375, y2), (0.3375, y3 + h3 + 0.038))

    # 第 4 列：兩種輸出
    y4, h4 = 0.155, 0.135
    box(ax, 0.06, y4, 0.40, h4, "③-A　App 即時查詢（統一偵測摘要）",
        "依衛星類型選主判方法：\nStarlink → Model 1＋融合評分器\n非 Starlink → NRLMSIS 阻力殘差（Model 2 佐證）", C_OUT)
    box(ax, 0.54, y4, 0.40, h4, "③-B　R7 單星報表（F1／F2 PDF）",
        "所有衛星同一流程：\nL1 規則決定候選事件，其他方法只影響等級\n輸出候選事件、證據等級、低置信複核項", C_OUT)
    arrow(ax, (0.26, y3 - 0.012), (0.26, y4 + h4))
    arrow(ax, (0.74, y3 - 0.012), (0.74, y4 + h4))

    # 第 5 列：人工複核
    y5, h5 = 0.06, 0.06
    box(ax, 0.25, y5, 0.50, h5, "④ 分析人員依優先順序複核，確認是否為機動", col=C_HUMAN, title_size=11)
    arrow(ax, (0.26, y4), (0.36, y5 + h5))
    arrow(ax, (0.74, y4), (0.64, y5 + h5))
    legend(ax, y=0.012)
    fig.savefig(OUT / "fig_sys_architecture.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ── 圖 2：R7 單星報表判定流程 ────────────────────────────────────────────────
def fig_r7_flow():
    fig, ax = canvas(12, 7.6)
    ax.text(0.5, 0.975, "R7 單星報表判定流程：候選事件與低置信複核項", ha="center", va="top",
            fontsize=15, fontweight="bold", color=INK)
    # 主線（上排）
    y, h = 0.58, 0.25
    w = 0.16
    xs = [0.025, 0.215, 0.405, 0.595, 0.785]
    box(ax, xs[0], y, w - 0.02, h, "輸入", "單顆衛星\n指定期間的 TLE\n（品質稽核後）", C_DATA)
    box(ax, xs[1], y, w, h, "步驟 1　L1 規則標點",
        "有效門檻＝P2 高度門檻\n× P5 太陽活動倍率\n× P6 軌道族群倍率\nP4 相鄰窗口補標\nP1 排除阻力衰減", C_RULE, body_size=8.8)
    box(ax, xs[2], y, w, h, "步驟 2　合併為候選事件",
        "相隔 48 小時內的\n規則候選點連鎖合併\n\n連續多日同向者\n再合併為連續機動段", C_RULE, body_size=8.8)
    box(ax, xs[3], y, w, h, "步驟 3　比對輔助通道",
        "事件前後 24 小時內：\nML 窗口模型（AI）\n融合評分器（AI）\n阻力殘差 > 0.3 km\nL2 ≥ 2 種方法觸發\n非 Starlink：AI 不決定 E3", C_AI, body_size=8.8)
    box(ax, xs[4], y, w, h, "步驟 4　給證據等級",
        "依顯著性（SNR）、\n輔助通道數、事件型態\n\nE3 高優先複核\nE2 人工複核\nE1 待觀察　D 資料待查", C_OUT, body_size=8.8)
    for a, b in zip(xs[:-1], xs[1:]):
        x0 = a + (w - 0.02 if a == xs[0] else w)
        arrow(ax, (x0, y + h / 2), (b, y + h / 2), color=INK)
    ax.text(xs[3] + w / 2, y - 0.03, "只影響等級，不新增、不刪除事件", ha="center", va="top",
            fontsize=9.2, color=C_AI[1], fontweight="bold")
    ax.text((xs[1] + xs[2] + w) / 2, y + h + 0.025, "事件是否存在，只由步驟 1、2 的規則決定",
            ha="center", va="bottom", fontsize=9.6, color=C_RULE[1], fontweight="bold")

    # 支線（下排）
    yb, hb = 0.2, 0.22
    box(ax, xs[1], yb, w * 2 + 0.03, hb, "支線　檢查 L1 未標記的時段",
        "阻力殘差超過 0.3 km\n融合評分器超過門檻（AI，限 Starlink）\nL2 統計變點：≥ 2 種方法同時觸發，且淨變化超過 L1 門檻（R7 新增）\n\n"
        "三者任一成立，且不在任何候選事件前後 24 小時內", C_RULE, body_size=9.2)
    box(ax, xs[3] + 0.02, yb, w * 2 + 0.01, hb, "低置信複核項",
        "列入複核清單，但不算候選事件\n\nP1：阻力殘差峰值 ≥ 1 km\nP2：其餘\n\n用途：補 L1 規則漏看的變化", C_OUT, body_size=9.2)
    arrow(ax, (xs[0] + (w - 0.02) / 2, y), (xs[0] + (w - 0.02) / 2, yb + hb / 2), color=INK)
    arrow(ax, (xs[0] + (w - 0.02) / 2, yb + hb / 2), (xs[1], yb + hb / 2), color=INK)
    arrow(ax, (xs[1] + w * 2 + 0.03, yb + hb / 2), (xs[3] + 0.02, yb + hb / 2), color=INK)

    # 下方說明
    ax.text(0.5, 0.085, "證據等級與低置信複核項都是「示警程度」：提示分析人員應優先處理哪些變化，"
            "並非直接判定機動存在；最終由分析人員複核確認。",
            ha="center", va="center", fontsize=10, color=C_HUMAN[1], fontweight="bold")
    legend(ax, y=0.015)
    fig.savefig(OUT / "fig_sys_r7_flow.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ── 圖 3：App 統一偵測摘要之路由 ─────────────────────────────────────────────
def fig_routing():
    fig, ax = canvas(11, 5.6)
    ax.text(0.5, 0.965, "App 統一偵測摘要：依衛星類型選擇主判方法", ha="center", va="top",
            fontsize=14.5, fontweight="bold", color=INK)
    box(ax, 0.03, 0.42, 0.17, 0.2, "輸入", "NORAD 編號\n或衛星名稱", C_DATA)
    box(ax, 0.26, 0.42, 0.20, 0.2, "判斷 1　再入守門",
        "近地點 < 150 km，或\n< 350 km 且下降\n> 2 km／天", C_RULE, body_size=9)
    box(ax, 0.52, 0.42, 0.20, 0.2, "判斷 2　是否 Starlink",
        "編目名稱以\nSTARLINK 開頭\n（固定規則，非 AI）", C_RULE, body_size=9)
    box(ax, 0.26, 0.10, 0.20, 0.17, "自然再入", "判定為阻力衰減\n機動數 = 0", C_OUT, body_size=9)
    box(ax, 0.78, 0.62, 0.20, 0.22, "Starlink",
        "主判：Model 1（AI）\n＋融合評分器（AI）\n佐證：阻力殘差、Model 2", C_AI, body_size=9)
    box(ax, 0.78, 0.18, 0.20, 0.22, "非 Starlink",
        "主判：NRLMSIS 阻力殘差\n（物理模型，非 AI）\n佐證：Model 2（AI）", C_RULE, body_size=9)
    arrow(ax, (0.20, 0.52), (0.26, 0.52), color=INK)
    arrow(ax, (0.46, 0.52), (0.52, 0.52), color=INK, text="否", toff=(0, 0.01))
    arrow(ax, (0.36, 0.42), (0.36, 0.27), color=INK, text="是", tpos=0.5, toff=(0.02, -0.01))
    arrow(ax, (0.72, 0.56), (0.78, 0.70), color=INK, text="是", tpos=0.4, toff=(-0.005, 0.01))
    arrow(ax, (0.72, 0.48), (0.78, 0.30), color=INK, text="否", tpos=0.4, toff=(-0.01, -0.035))
    ax.text(0.5, 0.035, "Model 1 與融合評分器只以 Starlink 資料訓練；非 Starlink 衛星不在其適用範圍，"
            "故改以不分星系的物理模型主判。", ha="center", fontsize=9.4, color=MUTED)
    fig.savefig(OUT / "fig_sys_routing.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ── 圖 4：App 即時查詢與 R7 報表之對照（第九章問答用） ─────────────────────────
def fig_app_vs_r7():
    fig, ax = canvas(12, 5.0)
    ax.text(0.5, 0.965, "兩種輸出之判定方式：App 即時查詢與 R7 單星報表", ha="center", va="top",
            fontsize=14.5, fontweight="bold", color=INK)
    w, g, h = 0.165, 0.035, 0.2
    xs = [0.2 + i * (w + g) for i in range(4)]
    # App：再入守門 → 是否 Starlink → 分支（Starlink／非 Starlink）
    ya = 0.56
    box(ax, 0.02, ya, 0.15, h, "App 即時查詢\n（互動瀏覽）", col=C_OUT, title_size=11)
    box(ax, xs[0], ya, w, h, "再入守門", "近地點過低\n→ 機動數 0", C_RULE, 10.5, 9)
    box(ax, xs[1], ya, w, h, "是否 Starlink", "編目名稱規則\n（非 AI）", C_RULE, 10.5, 9)
    bx, bw = xs[2], w * 2 + g
    box(ax, bx, ya + h / 2 + 0.01, bw, h / 2 - 0.01, "是 → 主判：Model 1＋融合評分器（AI）", col=C_AI, title_size=9.8)
    box(ax, bx, ya, bw, h / 2 - 0.01, "否 → 主判：NRLMSIS 阻力殘差（物理模型）；Model 2（AI）只作佐證", col=C_RULE, title_size=9.8)
    for x0, x1 in ((0.17, xs[0]), (xs[0] + w, xs[1]), (xs[1] + w, bx)):
        arrow(ax, (x0 + 0.003, ya + h / 2), (x1 - 0.004, ya + h / 2), color=INK)
    ax.text(0.02, ya + h + 0.03, "Model 1、Model 2 只用於 App 即時查詢", fontsize=9.6, color=C_AI[1],
            fontweight="bold", va="bottom")
    # R7：四步
    yr = 0.2
    ax.text(0.02, yr + h + 0.03, "R6、R7 是報表程式版本號（Revision），不是模型；R7 不分流、不使用 Model 2", fontsize=9.6,
            color=C_RULE[1], fontweight="bold", va="bottom")
    box(ax, 0.02, yr, 0.15, h, "R7 單星報表\n（正式交付）", col=C_OUT, title_size=11)
    steps = [("L1 規則標點", "P1–P6\n（非 AI）", C_RULE), ("合併候選事件", "48 小時連鎖\n（非 AI）", C_RULE),
             ("比對輔助通道", "含 ML／融合（AI）\n非 Starlink 不決定 E3", C_AI),
             ("證據等級", "E3／E2／E1／D\n＋低置信複核項", C_OUT)]
    prev = 0.17
    for x, (t, bdy, c) in zip(xs, steps):
        box(ax, x, yr, w, h, t, bdy, c, 10.5, 9)
        arrow(ax, (prev + 0.003, yr + h / 2), (x - 0.004, yr + h / 2), color=INK)
        prev = x + w
    ax.text(0.5, 0.09, "App 依衛星類型選主判方法；R7 對所有衛星採同一流程，事件只由 L1 規則產生。"
            "TASA 15 顆衛星之偵測結果皆以 R7 產生。", ha="center", fontsize=9.6, color=MUTED)
    fig.savefig(OUT / "fig_sys_app_vs_r7.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    fig_architecture()
    fig_r7_flow()
    fig_routing()
    fig_app_vs_r7()
    print("ok")
