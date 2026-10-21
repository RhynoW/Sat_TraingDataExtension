"""gen_fig_starlink_v3_raising.py — Starlink V3（Flight 14，NORAD 100855–100880）入軌後升軌高度時序圖。

資料：space_db.duckdb tle_table（高度 = sma_km − 6378.137）。
輸出：docs/fig_starlink_v3_raising_202610.png
用法：python docs/gen_fig_starlink_v3_raising.py
"""
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "fig_starlink_v3_raising_202610.png"
R_E = 6378.137
LAGGARDS = {100865: ("#2a78d6", "100865 仍在升軌"),
            100870: ("#eb6834", "100870 停在中途高度"),
            100858: ("#1baf7a", "100858 未升軌、緩降")}
MAIN_COLOR = "#c3c2bc"
INK, INK2 = "#0b0b0b", "#52514e"

plt.rcParams["font.family"] = ["Microsoft JhengHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

con = duckdb.connect(str(ROOT / "space_db.duckdb"), read_only=True)
d = con.sql("select norad_id n, epoch_jd - 2440587.5 ux, sma_km from tle_table "
            "where norad_id between 100855 and 100880").df()
d["t"] = pd.to_datetime(d.ux, unit="D")
d["alt"] = d.sma_km - R_E
d = d.sort_values(["n", "t"])

fig, ax = plt.subplots(figsize=(10, 5.2), dpi=200)
fig.patch.set_facecolor("#fcfcfb")
ax.set_facecolor("#fcfcfb")

for n, s in d.groupby("n"):
    if n in LAGGARDS:
        continue
    ax.plot(s.t, s.alt, color=MAIN_COLOR, lw=1.2, zorder=1)
for n, (c, lab) in LAGGARDS.items():
    s = d[d.n == n]
    ax.plot(s.t, s.alt, color=c, lw=2, zorder=3)
    ax.annotate(lab, (s.t.iloc[-1], s.alt.iloc[-1]), xytext=(6, -4 if n == 100858 else 4),
                textcoords="offset points", color=INK, fontsize=9, va="center")

last = d.t.max()
main_alt = d[(~d.n.isin(LAGGARDS)) & (d.t >= last - pd.Timedelta(days=1.0))].alt.median()
ax.annotate(f"其餘 23 顆：{main_alt:.1f} km", (last, main_alt), xytext=(6, 8),
            textcoords="offset points", color=INK2, fontsize=9)

for y, txt in [(296, "第一次停留 ≈296 km"), (316, "第二次停留 ≈316 km")]:
    ax.axhline(y, color="#e4e3df", lw=1, zorder=0)
    ax.text(pd.Timestamp("2026-09-30 12:00"), y + 1.2, txt, color=INK2, fontsize=8.5)

ax.set_ylabel("高度（km，平均半長軸 − 地球赤道半徑）", color=INK2, fontsize=9.5)
ax.set_title("Starlink V3（26 顆）入軌後高度變化，2026-09-30 至 10-19", loc="left",
             color=INK, fontsize=12)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
ax.set_xlim(d.t.min() - pd.Timedelta(hours=6), last + pd.Timedelta(days=3.2))
ax.grid(axis="y", color="#eeede9", lw=0.8)
for sp in ["top", "right"]:
    ax.spines[sp].set_visible(False)
for sp in ["left", "bottom"]:
    ax.spines[sp].set_color("#d6d5d0")
ax.tick_params(colors=INK2, labelsize=8.5)
fig.text(0.01, 0.01, "資料：Space-Track TLE（本專案資料庫）。灰線為其餘 23 顆。",
         color=INK2, fontsize=8)
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(OUT, facecolor=fig.get_facecolor())
print(f"輸出 → {OUT}")
