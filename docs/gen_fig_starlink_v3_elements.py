"""gen_fig_starlink_v3_elements.py — Starlink V3（NORAD 100855–100880）高度／傾角／離心率／相對 RAAN 四聯圖。

相對 RAAN：每筆 TLE 於其自身 epoch 扣除主隊（23 顆）參考曲線，避免不同 epoch 之 J2 退行（約 −7°/天）造成假性差異。
資料：space_db.duckdb tle_table。輸出：docs/fig_starlink_v3_elements_202610.png
用法：python docs/gen_fig_starlink_v3_elements.py
"""
from pathlib import Path

import duckdb
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "fig_starlink_v3_elements_202610.png"
LAGGARDS = {100865: "#2a78d6", 100870: "#eb6834", 100858: "#1baf7a"}
MAIN_COLOR, INK, INK2 = "#c3c2bc", "#0b0b0b", "#52514e"

plt.rcParams["font.family"] = ["Microsoft JhengHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

con = duckdb.connect(str(ROOT / "space_db.duckdb"), read_only=True)
d = con.sql("select norad_id n, epoch_jd jd, sma_km, eccentricity e, inclination_deg i, raan_deg O "
            "from tle_table where norad_id between 100855 and 100880 order by n, jd").df()
d["t"] = pd.to_datetime(d.jd - 2440587.5, unit="D")
d["alt"] = d.sma_km - 6378.137

# 主隊 RAAN 參考曲線：先扣約略退行率再 unwrap，以 6 次多項式擬合
t0, drift = d.jd.min(), 7.2
m = d[~d.n.isin(LAGGARDS)]
ou = np.degrees(np.unwrap(np.radians((m.O + drift * (m.jd - t0)) % 360)))
co = np.polyfit(m.jd - t0, ou, 6)
d["dO"] = ((d.O - (np.polyval(co, d.jd - t0) - drift * (d.jd - t0))) + 180) % 360 - 180

panels = [("alt", "高度（km）"), ("i", "傾角（°）"), ("e", "離心率"), ("dO", "相對主隊 RAAN（°）")]
fig, axes = plt.subplots(2, 2, figsize=(11, 6.6), dpi=200, sharex=True)
fig.patch.set_facecolor("#fcfcfb")
for ax, (col, lab) in zip(axes.flat, panels):
    ax.set_facecolor("#fcfcfb")
    for n, s in d.groupby("n"):
        if n not in LAGGARDS:
            ax.plot(s.t, s[col], color=MAIN_COLOR, lw=1, zorder=1)
    for n, c in LAGGARDS.items():
        s = d[d.n == n]
        ax.plot(s.t, s[col], color=c, lw=1.8, zorder=3, label=str(n))
    ax.set_title(lab, loc="left", fontsize=10, color=INK)
    ax.grid(axis="y", color="#eeede9", lw=0.8)
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    for sp in ["left", "bottom"]:
        ax.spines[sp].set_color("#d6d5d0")
    ax.tick_params(colors=INK2, labelsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
axes[1, 0].set_yscale("log")
axes[1, 0].yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0e}".replace("e-0", "e-")))
axes[1, 1].axhline(0, color="#d6d5d0", lw=1, zorder=0)
handles = [plt.Line2D([], [], color=MAIN_COLOR, lw=1.5, label="主隊 23 顆")] + \
          [plt.Line2D([], [], color=c, lw=1.8, label=str(n)) for n, c in LAGGARDS.items()]
fig.legend(handles=handles, loc="upper right", ncol=4, frameon=False, fontsize=8.5,
           labelcolor=INK2, bbox_to_anchor=(0.99, 0.995))
fig.suptitle("Starlink V3（26 顆）軌道根數變化，2026-09-30 至 10-19", x=0.01, ha="left",
             fontsize=12, color=INK)
fig.text(0.01, 0.005, "資料：Space-Track TLE（本專案資料庫）。相對 RAAN 於各筆 TLE 自身時刻扣除主隊參考曲線。",
         color=INK2, fontsize=7.5)
fig.tight_layout(rect=(0, 0.02, 1, 0.96))
fig.savefig(OUT, facecolor=fig.get_facecolor())
print(f"輸出 → {OUT}")
