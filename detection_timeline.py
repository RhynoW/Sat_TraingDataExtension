# -*- coding: utf-8 -*-
"""detection_timeline.py — 機動偵測時間序列圖（共用繪圖模組，2026-10-29 自
docs/gen_case_study_timeseries_figs.py 抽出）

供兩處共用同一份繪圖邏輯，避免各存一份、改一邊忘了另一邊：
  * docs/gen_case_study_timeseries_figs.py：案例研究簡報的 {norad}_timeline.png
  * maneuver_report_builder.py：F2 PDF 報表的「機動偵測時間序列」頁

輸入序列兩種（如實標示，不假造）：
  - kind="fusion"（Starlink）：融合評分器 0–1 校準機率，欄位 epoch, fusion[, thr]，
    y 軸標「融合評分器信心指數」，可直接依分數上色。
  - kind="drag"（非 Starlink）：NRLMSIS 阻力殘差，欄位 epoch, drag_resid_da[, reentry]；
    無校準機率，y 軸改標「阻力殘差量級（公里，對數座標）」，依量級分級上色，
    不冠以「信心指數」之名，避免誤導為機率。

研判為機動之日期標註：連續 48 小時內的判定點合併為同一事件（episode，與全專案
episode 定義一致），取事件內峰值時刻為代表點，於圖下方以「日期標籤 + 連結線」標出，
並以貪婪演算法分配到多個橫向車道（lane）避免重疊；事件多時車道自動增加、字體自動
縮小，仍逐一標出而不省略。

本模組不設定字型（呼叫端各自負責：簡報腳本用 Windows 微軟正黑體，PDF 報表用
bundle 的 Noto Sans TC）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib.dates as mdates
from matplotlib.lines import Line2D

BG = "#0E1B2E"; PANEL = "#16273F"; GRID = "#2A3F5C"
INK = "#ECF2F9"; MUTE = "#9FB3C8"
C_LOW = "#4FC3F7"; C_MID = "#FFD54F"; C_HIGH = "#EF5350"
LEADER = "#6E86A8"


def color_for(val, kind):
    if kind == "fusion":
        if val >= 0.659:
            return C_HIGH
        if val >= 0.3:
            return C_MID
        return C_LOW
    else:  # drag residual km (abs)
        if val >= 2.0:
            return C_HIGH
        if val >= 0.30:
            return C_MID
        return C_LOW


def merge_episodes(df, kind):
    """合併連續 <=48h 之判定點為事件，回傳每事件的代表點 (x_num, y_for_plot, raw_val, date_str)。"""
    if kind == "fusion":
        thr = float(df["thr"].iloc[0]) if "thr" in df.columns else 0.659
        flagged = df[df["fusion"] >= thr].copy()
        flagged["val"] = flagged["fusion"]
        flagged["yplot"] = flagged["fusion"]
    else:
        reentry = bool(df["reentry"].iloc[0]) if "reentry" in df.columns else False
        flagged = df[df["drag_resid_da"].abs() > 0.30].copy() if not reentry else df.iloc[0:0].copy()
        flagged["val"] = flagged["drag_resid_da"].abs()
        flagged["yplot"] = np.log10(np.clip(flagged["val"].to_numpy(), 1e-3, None))
    if flagged.empty:
        return []
    flagged = flagged.sort_values("epoch").reset_index(drop=True)
    episodes = []
    cur_idx = [0]
    for i in range(1, len(flagged)):
        gap_h = (flagged["epoch"].iloc[i] - flagged["epoch"].iloc[cur_idx[-1]]).total_seconds() / 3600
        if gap_h <= 48:
            cur_idx.append(i)
        else:
            episodes.append(cur_idx); cur_idx = [i]
    episodes.append(cur_idx)
    reps = []
    for idxs in episodes:
        sub = flagged.iloc[idxs]
        peak_row = sub.loc[sub["val"].idxmax()]
        reps.append({"epoch": peak_row["epoch"], "yplot": float(peak_row["yplot"]),
                     "val": float(peak_row["val"]),
                     "d0": str(sub["epoch"].min().date()), "d1": str(sub["epoch"].max().date()),
                     "n": int(len(sub))})
    return reps


def assign_lanes(reps, xmin, xmax, max_lanes=8):
    """貪婪分配標籤車道：同車道內日期間隔需 >= min_gap，避免水平重疊。"""
    span_days = max((xmax - xmin).days, 1)
    min_gap = max(span_days * 0.016, 0.6)
    items = sorted(reps, key=lambda r: r["epoch"])
    lane_last = []  # 每車道最後放置的時間
    for it in items:
        placed = False
        for li, last in enumerate(lane_last):
            if (it["epoch"] - last).total_seconds() / 86400 >= min_gap:
                lane_last[li] = it["epoch"]; it["lane"] = li; placed = True; break
        if not placed:
            if len(lane_last) < max_lanes:
                lane_last.append(it["epoch"]); it["lane"] = len(lane_last) - 1
            else:
                # 找重疊最少的車道，容許些微重疊而非捨棄資料
                gaps = [(it["epoch"] - last).total_seconds() for last in lane_last]
                li = int(np.argmax(gaps))
                lane_last[li] = it["epoch"]; it["lane"] = li
    return items, len(lane_last)


def prepare(df, kind):
    """回傳 (reps, n_lanes)：事件代表點（含車道）與車道數（至少 1），供決定圖高與繪圖。"""
    reps = merge_episodes(df, kind)
    reps, n_lanes = assign_lanes(reps, df["epoch"].min(), df["epoch"].max(), max_lanes=8)
    return reps, max(n_lanes, 1)


def fig_height(n_lanes: int) -> float:
    """簡報版圖高（英吋）：基本高度 + 每車道 0.34 吋。"""
    return 4.6 + 0.34 * n_lanes


def draw_timeline(ax, df, kind, title, reps, n_lanes, event_epoch=None, note=None):
    """在 ax 上畫機動偵測時間序列（深色主題）。df["epoch"] 須為 tz-aware datetime。
    event_epoch：選定事件時刻字串（UTC），畫白色垂直線；note：左上角補充說明文字。"""
    ax.figure.patch.set_facecolor(BG); ax.set_facecolor(PANEL)

    if kind == "fusion":
        y = df["fusion"].to_numpy()
        thr = float(df["thr"].iloc[0]) if "thr" in df.columns else 0.659
        x = df["epoch"].to_numpy()
        cols = [color_for(v, "fusion") for v in y]
        ax.scatter(x, y, c=cols, s=10, zorder=3, edgecolors="none")
        ax.plot(x, y, color=MUTE, linewidth=0.5, alpha=0.5, zorder=2)
        ax.axhline(thr, color=C_HIGH, linestyle="--", linewidth=1.1, alpha=0.8)
        ax.text(x[0] if len(x) else 0, thr, f"  操作門檻 {thr:.3f}", color=C_HIGH,
                fontsize=9, va="bottom")
        y_top = 1.03
        lane_unit = 0.085
        y_bottom = -0.03 - lane_unit * n_lanes
        ax.set_ylim(y_bottom, y_top)
        ax.set_yticks([0, 0.2, 0.4, 0.6, 0.659, 0.8, 1.0])
        ax.set_ylabel("融合評分器信心指數（0–1 機率）", color=INK, fontsize=11)

        def lane_y(li):
            return -0.03 - lane_unit * (li + 1)
    else:
        y = df["drag_resid_da"].abs().to_numpy()
        x = df["epoch"].to_numpy()
        cols = [color_for(v, "drag") for v in y]
        yplot = np.log10(np.clip(y, 1e-3, None))
        ax.scatter(x, yplot, c=cols, s=10, zorder=3, edgecolors="none")
        ax.plot(x, yplot, color=MUTE, linewidth=0.5, alpha=0.5, zorder=2)
        for lv in (np.log10(0.30), np.log10(2.0)):
            ax.axhline(lv, color=MUTE, linestyle=":", linewidth=0.9, alpha=0.6)
        ax.set_ylabel("阻力殘差量級｜Δa 殘差絕對值（km，log10 座標）", color=INK, fontsize=10.5)
        y_data_min = float(np.nanmin(yplot)); y_data_max = float(np.nanmax(yplot))
        yt_lo, yt_hi = int(np.floor(y_data_min)), int(np.ceil(y_data_max))
        yt = list(range(yt_lo, yt_hi + 1))
        ax.set_yticks(yt); ax.set_yticklabels([f"{10**v:g}" for v in yt])
        lane_unit = (y_data_max - yt_lo + 0.4) / 10 + 0.42
        axis_zero = yt_lo - 0.15
        y_bottom = axis_zero - lane_unit * n_lanes
        ax.set_ylim(y_bottom, y_data_max + 0.5)

        def lane_y(li):
            return axis_zero - lane_unit * (li + 1)

    if note:
        ax.text(0.01, 0.98, note, transform=ax.transAxes, color=C_MID,
                fontsize=9, va="top", ha="left")

    # ── 研判為機動之日期標籤（連結線 + 車道避讓）──────────────────────────
    small_font = 7.6 if len(reps) > 20 else (8.3 if len(reps) > 10 else 9.2)
    date_fmt = "%Y-%m-%d" if len(reps) <= 14 else "%m-%d"
    for r in reps:
        xd = r["epoch"]
        ly = lane_y(r["lane"])
        ax.plot([xd, xd], [r["yplot"], ly + lane_unit * 0.32], color=LEADER,
                linewidth=0.7, alpha=0.75, zorder=1, linestyle=(0, (2, 1.4)))
        label = xd.strftime(date_fmt)
        ax.text(xd, ly, label, color=INK, fontsize=small_font, ha="center", va="top",
                rotation=55, rotation_mode="anchor", zorder=5)
        ax.plot([xd], [ly + lane_unit * 0.32], marker="o", markersize=2.6,
                color=LEADER, zorder=4)

    xmin, xmax = pd.Timestamp(x.min()), pd.Timestamp(x.max())
    if event_epoch:
        evt = pd.Timestamp(event_epoch, tz="UTC")
        if xmin <= evt <= xmax:
            ax.axvline(evt, color="#FFFFFF", linestyle="-", linewidth=1.0, alpha=0.4, zorder=0)
            ax.text(evt, ax.get_ylim()[1], "  本報告逐層解析選定事件", color="#FFFFFF",
                    fontsize=8.5, va="top", rotation=90, alpha=0.75)
        else:
            ax.text(0.99, 0.90,
                    f"（本報告逐層解析選定事件為 {evt.date()}，早於本圖資料起點，未顯示）",
                    transform=ax.transAxes, color=MUTE, fontsize=8.5, ha="right", va="top")

    ax.set_title(f"{title}　機動偵測時間序列（共 {len(reps)} 次研判為機動之事件，日期見下方標註）",
                 color=INK, fontsize=14.5, pad=12, loc="left")
    ax.tick_params(colors=MUTE, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.grid(True, color=GRID, linewidth=0.5, alpha=0.5)
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=9))
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
    ax.xaxis.set_label_position("top")
    ax.xaxis.tick_top()
    ax.spines["bottom"].set_visible(False)

    if kind == "fusion":
        items = [("低（<0.30）", C_LOW), ("中（0.30–0.66）", C_MID), ("高／已判定（0.66以上）", C_HIGH)]
    else:
        items = [("低（<0.30km）", C_LOW), ("中（0.30–2km）", C_MID), ("高（2km以上）", C_HIGH)]
    handles = [Line2D([0], [0], marker="o", color="none", markerfacecolor=c, markersize=8, label=l)
               for l, c in items]
    ax.legend(handles=handles, loc="upper right", frameon=False, fontsize=9,
              labelcolor=INK, ncol=3, bbox_to_anchor=(1.0, 1.0))
