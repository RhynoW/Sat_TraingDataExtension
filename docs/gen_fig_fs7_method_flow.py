#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_fig_fs7_method_flow.py — 論文二 Fig. 1：資料與方法流程圖（純繪圖，無資料輸入）。

三條泳道：
  SP3 真值（TACC leoOrb）→ SP3 端偵測（整數週期平滑＋差分、4σ）→ 四項一致性檢查 → 事件譜系 131 → 96 → 5 箱
    （n = 37/16/18/8/17；35 件排除）→ 真實事件比較（Table 4、Fig. 6）
  TLE 序列 → 注入網格（11 振幅 × 更新間隔 {1×, 2×, 4×} × 阻力三分位；478 窗；15,774 次試驗）
    → TLE 端偵測器（MAD/CUSUM 用於注入；事件前局部趨勢用於真實事件）→ SNR_eff 模型 → 時間切分留出驗證
  太空天氣指數（Dst、Kp、F10.7）→ 2024 年 5 月磁暴區間 → 21 件假候選（獨立誤報案例，不在 131 件內）
方框畫法參考 docs/gen_fig_system_flow.py。所有數字取自論文 §2–§6（固定字串，不讀檔）。

輸入：無
輸出：docs/fig_fs7_method_flow.png（600 dpi）＋ .pdf
用法：python docs/gen_fig_fs7_method_flow.py          （docs/ 英文白底）
      python docs/gen_fig_fs7_method_flow.py --pub    （docs/figures_pub/ 四版本）
"""
from __future__ import annotations

import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent
sys.path.insert(0, str(DOCS))
import fs7_fig_style as st  # noqa: E402
from fig_pub import t  # noqa: E402

INK, MUTED = "#1f2937", "#4b5563"
C_SP3 = ("#e8f1fb", "#1f4e79")      # SP3 真值：藍
C_TLE = ("#fdf0e6", "#b45309")      # TLE／注入：橙
C_SW = ("#f5f0fa", "#6b4c9a")       # 太空天氣：紫
C_MOD = ("#ecf7ef", "#2f7d4a")      # 模型與評估：綠
C_FP = ("#fbeaea", "#a12a2a")       # 誤報案例：紅

W = 0.180                                        # 方框寬（軸座標）
COLS = [0.0 + i * 0.205 for i in range(5)]       # 五欄左緣；欄間空隙 0.025
ROWS = {"sp3": (0.665, 0.335), "tle": (0.250, 0.320), "sw": (0.000, 0.175)}   # (下緣, 高)
FIG_H_CM = 7.6


def box(ax, col, row, title, body, c, *, w=W, dashed=False):
    from matplotlib.patches import FancyBboxPatch
    x = COLS[col]
    y, hh = ROWS[row]
    fill, edge = c
    ax.add_patch(FancyBboxPatch((x, y), w, hh, boxstyle="round,pad=0.004,rounding_size=0.012",
                                fc=fill, ec=edge, lw=0.9, ls="--" if dashed else "-"))
    ax.text(x + w / 2, y + hh - 0.020, title, ha="center", va="top", fontsize=6.5, color=edge,
            fontweight="bold")
    ax.text(x + w / 2, y + hh - 0.080, body, ha="center", va="top", fontsize=5.6, color=INK,
            linespacing=1.3)
    return x, y, w, hh


def arrow(ax, p0, p1, color=MUTED):
    from matplotlib.patches import FancyArrowPatch
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=6.5, color=color, lw=0.8,
                                 shrinkA=0, shrinkB=0))


def draw():
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(st.DOUBLE, FIG_H_CM * st.CM))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(-0.005, 1.005)
    ax.set_ylim(-0.005, 1.005)
    ax.axis("off")

    # ── SP3 泳道 ─────────────────────────────────────────────────────────────
    b_sp3 = box(ax, 0, "sp3", t("SP3 真值（TACC leoOrb）", "SP3 truth (TACC leoOrb)"),
                t("6 顆 FS7，60 s 取樣\n每弧 ≈ 2.1 h，4–6 重重疊\nITRF 速度 → 慣性系\n5 個 campaign＋磁暴樣本",
                  "6 satellites, 60 s sampling\n≈ 2.1 h arcs, 4–6-fold overlap\nITRF velocity → inertial\n5 campaigns + storm sample"),
                C_SP3)
    b_det = box(ax, 1, "sp3", t("SP3 端偵測", "SP3-side detection"),
                t("弧段合併，60 s 均勻網格\n整數週期滑動平均\n整數週期差分\n門檻 4σ（MAD）\n最小驗證振幅 26 m",
                  "Arcs merged, 60 s grid\nInteger-period rolling mean\nInteger-period difference\nThreshold 4σ (MAD)\nSmallest validated step 26 m"),
                C_SP3)
    b_chk = box(ax, 2, "sp3", t("四項一致性檢查", "Four consistency checks"),
                t("1 均值階躍持續性\n2 重疊弧一致\n3 跨星共模篩除\n4 傾角通道佐證\n（共用同一 SP3 來源）",
                  "1 Persistence of mean step\n2 Overlapping-arc agreement\n3 Common-mode screen\n4 Inclination channel\n(shared SP3 source)"),
                C_SP3)
    b_lin = box(ax, 3, "sp3", t("事件譜系", "Event lineage"),
                t("131 件已驗證機動（46 + 85）\n↓ TLE 前後覆蓋足夠\n96 件可比對\n（35 件排除）\n↓ 5 個振幅箱\nn = 37 / 16 / 18 / 8 / 17",
                  "131 verified (46 + 85)\n↓ adequate TLE coverage\n96 TLE-comparable\n(35 excluded)\n↓ 5 amplitude bins\nn = 37 / 16 / 18 / 8 / 17"),
                C_SP3)
    b_rec = box(ax, 4, "sp3", t("真實事件比較", "Real-event comparison"),
                t("FS7 內之留出驗證\n觀測召回：45 m 與統一 3σ\n（Wilson 95% CI）\n對照 SNR_eff 模型\n平均預測機率\nTable 4、Fig. 6",
                  "Held-out within FS7\nObserved recall at 45 m\nand unified 3σ (Wilson CI)\nvs SNR_eff model mean\npredicted probability\nTable 4, Fig. 6"),
                C_MOD)

    # ── TLE 泳道 ─────────────────────────────────────────────────────────────
    b_tle = box(ax, 0, "tle", t("TLE 序列", "TLE series"),
                t("Space-Track\n2024-01 至 2026-08\n每星 ≈ 1,900 筆\n中位更新間隔 8–12 h\n（2025 campaign 21.6 h）",
                  "Space-Track\n2024-01 to 2026-08\n≈ 1,900 records per satellite\nmedian interval 8–12 h\n(21.6 h, 2025 campaign)"),
                C_TLE)
    b_inj = box(ax, 1, "tle", t("注入網格", "Injection grid"),
                t("478 個安靜窗\n（每窗 40 筆，步幅 20）\n11 振幅（20 m – 2 km）\n× 更新間隔 {1×, 2×, 4×}\n× 阻力 |ȧ| 三分位\n= 15,774 次試驗",
                  "478 quiet windows\n(40 TLEs, stride 20)\n11 amplitudes (20 m – 2 km)\n× cadence {1×, 2×, 4×}\n× drag |ȧ| terciles\n= 15,774 trials"),
                C_TLE)
    b_tdet = box(ax, 2, "tle", t("TLE 端偵測器", "TLE-side detectors"),
                 t("注入：MAD ∪ CUSUM\n命中容差 ±2 樣本\n真實事件：事件前 3 天\n局部趨勢；事件後首筆\n殘差，符號須相符",
                   "Injections: MAD ∪ CUSUM\nhit tolerance ±2 samples\nReal events: 3-day pre-event\nlocal trend; first post-event\nresidual, sign-matched"),
                 C_TLE)
    b_mod = box(ax, 3, "tle", t("SNR_eff 模型", "SNR_eff model"),
                "SNR_eff = |Δa| / σ_eff\nσ_eff = √(σ_TLE² + (c|ȧ|Δt)²)\n"
                + t("P = logistic(log₁₀ SNR_eff)\n參數 c、SNR₅₀、β\n叢集自助（衛星 × 窗）",
                    "P = logistic(log₁₀ SNR_eff)\nparameters c, SNR₅₀, β\ncluster bootstrap\n(satellite × window)"),
                C_MOD)
    b_ho = box(ax, 4, "tle", t("時間切分留出驗證", "Temporal hold-out"),
               t("校準 < 2025-07-01：8,778\n測試 ≥ 2025-07-01：6,996\n校準期係數固定\n對照僅振幅模型 Δa/σ\n＋ blocked 交叉驗證",
                 "Calib. < 2025-07-01: 8,778\nTest ≥ 2025-07-01: 6,996\ncoefficients fixed\nvs amplitude-only Δa/σ\n+ blocked cross-validation"),
               C_MOD)

    # ── 太空天氣泳道 ─────────────────────────────────────────────────────────
    b_sw = box(ax, 0, "sw", t("太空天氣指數", "Space-weather indices"),
               t("Dst、Kp、F10.7\n辨識地磁擾動區間", "Dst, Kp, F10.7\ndisturbed intervals"), C_SW)
    b_st = box(ax, 1, "sw", t("2024 年 5 月磁暴區間", "May 2024 storm interval"),
               t("20 天 SP3 樣本\n平均 ȧ：−49 → −182 m/d", "20-day SP3 sample\nmean ȧ: −49 → −182 m/d"), C_SW)
    b_fp = box(ax, 2, "sw", t("磁暴假候選（獨立誤報案例）", "Storm candidates (separate false-positive case)"),
               t("同一 SP3 端偵測與四項檢查：87 件原始候選 → 21 件通過\n全為負向（−47 至 −16 m）之阻力非推力訊號；非機動、不在 131 件內",
                 "Same SP3-side detection and checks: 87 raw candidates → 21 pass\nall negative-going (−47 to −16 m), drag-driven, non-thrust;\nnot maneuvers and not part of the 131"),
               C_FP, w=COLS[4] + W - COLS[2], dashed=True)

    # ── 箭頭 ─────────────────────────────────────────────────────────────────
    def right(b, y=None):
        return (b[0] + b[2], y if y is not None else b[1] + b[3] * 0.5)

    def left(b, y=None):
        return (b[0], y if y is not None else b[1] + b[3] * 0.5)

    for a_, b_ in ((b_sp3, b_det), (b_det, b_chk), (b_chk, b_lin), (b_lin, b_rec),
                   (b_tle, b_inj), (b_inj, b_tdet), (b_tdet, b_mod), (b_mod, b_ho),
                   (b_sw, b_st), (b_st, b_fp)):
        arrow(ax, right(a_), left(b_))
    # 真實事件路徑：TLE 端偵測器 → 列間空隙 → 真實事件比較（折線）
    yg = (ROWS["tle"][0] + ROWS["tle"][1] + ROWS["sp3"][0]) / 2
    x0 = b_tdet[0] + b_tdet[2] * 0.5
    x1 = b_rec[0] + b_rec[2] * 0.5
    ax.plot([x0, x0, x1], [b_tdet[1] + b_tdet[3], yg, yg], color=C_TLE[1], lw=0.8)
    arrow(ax, (x1, yg), (x1, b_rec[1]), color=C_TLE[1])
    ax.text((x0 + b_lin[0]) / 2 + 0.06, yg + 0.006, t("真實事件偵測", "real-event detector"),
            ha="center", va="bottom", fontsize=5.3, color=C_TLE[1])
    # 模型 → 真實事件比較：校準期係數（同一列間空隙，於右段併入）
    xm = b_mod[0] + b_mod[2] * 0.5
    ax.plot([xm, xm], [b_mod[1] + b_mod[3], yg], color=C_MOD[1], lw=0.8)
    ax.plot([xm], [yg], "o", ms=2.0, color=C_MOD[1])
    ax.text(xm + 0.012, yg + 0.006, t("模型係數", "model coefficients"), ha="left", va="bottom",
            fontsize=5.3, color=C_MOD[1])
    return fig


if __name__ == "__main__":
    st.run({"fig_fs7_method_flow": draw})
