# -*- coding: utf-8 -*-
"""gen_case_study_timeseries_figs.py — 為案例研究簡報產生 10 顆衛星的機動偵測時間序列圖
輸入：data/benchmark/case_study_timeseries_20261007/{norad}_{fusion|drag}.csv
      （由 timeseries10.py 批次算出；Starlink 為融合評分器機率序列，
      非 Starlink 為 NRLMSIS 阻力殘差序列）
輸出：docs/case_study_figs/{norad}_timeline.png（深色主題，供簡報直接嵌入）

信心指數說明（如實標示，不假造）：
  - Starlink（STARLINK-37471/30805/5846）：融合評分器輸出為 0–1 校準機率，
    y 軸標「融合評分器信心指數」，可直接依分數上色。
  - 非 Starlink（其餘 7 顆）：Model 2／NRLMSIS 並無校準機率，y 軸改標
    「阻力殘差量級（公里，對數座標）」，依量級分級上色，不冠以「信心指數」之名，
    避免誤導為機率。

研判為機動之日期標註（2026-10-07 新增）：
  連續 48 小時內的判定點合併為同一事件（episode，與全專案 episode 定義一致），
  取事件內峰值所在時刻為代表點，於圖下方以「日期標籤 + 連結線」標出，並以貪婪
  演算法將標籤分配到多個橫向車道（lane），避免日期相近時彼此重疊。事件數較多
  （如太空站）時車道數會自動增加、字體自動縮小，仍逐一標出而不省略。
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import matplotlib.font_manager as fm
for fp in (r"C:\Windows\Fonts\msjh.ttc", r"C:\Windows\Fonts\mingliu.ttc"):
    if Path(fp).exists():
        fm.fontManager.addfont(fp)
        matplotlib.rcParams["font.family"] = fm.FontProperties(fname=fp).get_name()
        break
matplotlib.rcParams["axes.unicode_minus"] = False

DOCS = Path(__file__).parent
TSDIR = DOCS.parent / "data" / "benchmark" / "case_study_timeseries_20261007"
OUTDIR = DOCS / "case_study_figs"
OUTDIR.mkdir(exist_ok=True)

BG = "#0E1B2E"; PANEL = "#16273F"; GRID = "#2A3F5C"
INK = "#ECF2F9"; MUTE = "#9FB3C8"
C_LOW = "#4FC3F7"; C_MID = "#FFD54F"; C_HIGH = "#EF5350"
LEADER = "#6E86A8"

SATS = [
    ("FORMOSAT-5（福衛五號）", 42920, "drag"),
    ("FORMOSAT-8A（福衛八號A星）", 66666, "drag"),
    ("ISS (ZARYA) 國際太空站", 25544, "drag"),
    ("STARLINK-37471", 68802, "fusion"),
    ("STARLINK-30805", 58214, "fusion"),
    ("STARLINK-5846", 56492, "fusion"),
    ("QZS-7", 100270, "drag"),
    ("FORMOSAT7-1/COSMIC2-1", 44349, "drag"),
    ("YAOGAN-35 A", 49390, "drag"),
    ("JASON 3", 41240, "drag"),
]

# 事件時刻（第三、四節逐層解析所選之代表事件；用於在圖上標註垂直虛線）
EVENT_EPOCH = {
    42920: "2017-08-24 22:01",
    66666: "2026-02-02 05:12",
    25544: "1998-11-23 08:22",
    68802: "2026-06-16 20:00",
    58214: "2026-09-21 11:06",
    56492: "2026-04-09 14:00",
    100270: "2026-08-12 12:23",
    44349: "2025-07-17 04:21",
    49390: "2025-03-21 12:38",
    41240: "2016-02-04 19:09",
}


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
                     "val": float(peak_row["val"])})
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


def plot_one(title, nid, kind):
    f = TSDIR / f"{nid}_{kind}.csv"
    if not f.exists():
        print("MISSING", f); return False
    df = pd.read_csv(f)
    if df.empty:
        print("EMPTY", f); return False
    df["epoch"] = pd.to_datetime(df["epoch"], utc=True, format="mixed")

    reps = merge_episodes(df, kind)
    xmin_ts, xmax_ts = df["epoch"].min(), df["epoch"].max()
    reps, n_lanes = assign_lanes(reps, xmin_ts, xmax_ts, max_lanes=8)
    n_lanes = max(n_lanes, 1)

    fig_h = 4.6 + 0.34 * n_lanes
    fig, ax = plt.subplots(figsize=(13.0, fig_h), dpi=150)
    fig.patch.set_facecolor(BG); ax.set_facecolor(PANEL)

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
        axis_zero = -0.03

        def lane_y(li):
            return -0.03 - lane_unit * (li + 1)

        def fmt_val(v):
            return f"{v:.2f}"
    else:
        y = df["drag_resid_da"].abs().to_numpy()
        x = df["epoch"].to_numpy()
        reentry = bool(df["reentry"].iloc[0]) if "reentry" in df.columns else False
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

        def fmt_val(v):
            return f"{v:.2f}km"

        note = "（此星為軌道轉移段，數值量級超出近圓軌道模型假設，詳見報告）" if nid == 100270 else \
               ("（偵測到自然再入衰減模式，物理閘門已抑制機動判定）" if reentry else "")
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

    ev = EVENT_EPOCH.get(nid)
    xmin, xmax = pd.Timestamp(x.min()), pd.Timestamp(x.max())
    if ev:
        evt = pd.Timestamp(ev, tz="UTC")
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

    from matplotlib.lines import Line2D
    if kind == "fusion":
        items = [("低（<0.30）", C_LOW), ("中（0.30–0.66）", C_MID), ("高／已判定（0.66以上）", C_HIGH)]
    else:
        items = [("低（<0.30km）", C_LOW), ("中（0.30–2km）", C_MID), ("高（2km以上）", C_HIGH)]
    handles = [Line2D([0], [0], marker="o", color="none", markerfacecolor=c, markersize=8, label=l)
               for l, c in items]
    ax.legend(handles=handles, loc="upper right", frameon=False, fontsize=9,
              labelcolor=INK, ncol=3, bbox_to_anchor=(1.0, 1.0))

    fig.tight_layout()
    out = OUTDIR / f"{nid}_timeline.png"
    fig.savefig(out, facecolor=BG)
    plt.close(fig)
    print("saved", out, len(df), "pts,", len(reps), "labeled events,", n_lanes, "lanes")
    return True


ok = 0
for title, nid, kind in SATS:
    if plot_one(title, nid, kind):
        ok += 1
print(f"\n{ok}/{len(SATS)} figures generated -> {OUTDIR}")
