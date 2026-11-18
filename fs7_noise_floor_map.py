#!/usr/bin/env python3
"""
fs7_noise_floor_map.py — 軌道域 × 名目 TLE 雜訊底 視覺化
=========================================================
X＝離地高度（km，取各星 TLE 全史 sma 中位 − 6371）
Y＝軌道傾角（deg，TLE 全史中位）
色＝名目 TLE 雜訊底 σ（m，log 色階；統一估計器：安靜窗去趨勢單步差分
    MAD×1.4826/√2，40 筆滑動窗、排除 |Δa|>0.3 km 之窗，取窗中位）
形＝衛星群（次要編碼）：FS7=圓、14 測高星=方、9 hold-out=三角、Starlink 樣本=小點

輸出：docs/fig_tle_noise_floor_map.png、data/benchmark/tle_noise_floor_map.csv
用法：python fs7_noise_floor_map.py
"""
from __future__ import annotations

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd

GROUPS = {
    "FORMOSAT-7 (calibration)": dict(
        norads=[44343, 44349, 44350, 44351, 44353, 44358], marker="o", size=90),
    "14 altimetry (benchmark)": dict(
        norads=[22076, 26997, 33105, 41240, 46984, 27386, 36508, 39086,
                41335, 43437, 54754, 37781, 46469, 48621], marker="s", size=70),
    "9 hold-out (SPOT/GRACE/S6B)": dict(
        norads=[20436, 22823, 25260, 27421, 27391, 27392, 43476, 43477], marker="^", size=90),
    "Starlink sample (train domain)": dict(norads=None, marker=".", size=28),
}
WIN, STEP_MAX_KM = 40, 0.3


def sigma_nominal(t, a):
    sigs = []
    for s0 in range(0, len(a) - WIN, WIN):
        aa, tt = a[s0:s0 + WIN], t[s0:s0 + WIN]
        if np.abs(np.diff(aa)).max() > STEP_MAX_KM:
            continue
        slope = np.polyfit(tt, aa, 1)[0]
        d = np.diff(aa - slope * (tt - tt[0]))
        sigs.append(1.4826 * np.median(np.abs(d - np.median(d))) / np.sqrt(2) * 1000)
    return float(np.nanmedian(sigs)) if sigs else np.nan


def main():
    con = duckdb.connect("space_db.duckdb", read_only=True)
    # S6B NORAD（由名稱查）
    s6b = con.execute("SELECT norad_id, COUNT(*) c FROM raw_tle_archive "
                      "WHERE object_name ILIKE '%SENTINEL-6B%' GROUP BY 1 "
                      "ORDER BY c DESC LIMIT 1").fetchone()
    if s6b:
        GROUPS["9 hold-out (SPOT/GRACE/S6B)"]["norads"].append(int(s6b[0]))
        print(f"Sentinel-6B NORAD = {s6b[0]}（{s6b[1]} 筆 TLE）")
    # Starlink 樣本 30 顆（TLE 筆數足夠者）
    sl = con.execute("SELECT norad_id FROM raw_tle_archive "
                     "WHERE object_name ILIKE '%STARLINK%' GROUP BY norad_id "
                     "HAVING COUNT(*)>300 AND MAX(epoch_utc)>'2026-07-01' "
                     "ORDER BY hash(norad_id) LIMIT 30").df()
    GROUPS["Starlink sample (train domain)"]["norads"] = sl["norad_id"].tolist()

    rows = []
    for gname, g in GROUPS.items():
        for nid in g["norads"]:
            df = con.execute("SELECT epoch_utc, sma_km, inclination_deg FROM raw_tle_archive "
                             "WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc",
                             [int(nid)]).df()
            if len(df) < 100:
                print(f"  跳過 {gname} NORAD {nid}：TLE 僅 {len(df)} 筆")
                continue
            t = df["epoch_utc"].values.astype("datetime64[s]").astype(float) / 86400.0
            a = df["sma_km"].values
            sig = sigma_nominal(t, a)
            rows.append({"group": gname, "norad": int(nid),
                         "alt_km": float(np.median(a)) - 6371.0,
                         "inc_deg": float(df["inclination_deg"].median()),
                         "sigma_m": round(sig, 2), "n_tle": len(df)})
    d = pd.DataFrame(rows)
    d.to_csv("data/benchmark/tle_noise_floor_map.csv", index=False, encoding="utf-8-sig")
    print(d.groupby("group")[["sigma_m"]].agg(["count", "median"]).round(2).to_string())

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    fig, ax = plt.subplots(figsize=(9.5, 6.2))
    norm = LogNorm(vmin=max(d["sigma_m"].min(), 0.02), vmax=d["sigma_m"].max())
    cmap = plt.get_cmap("Blues")
    sc = None
    for gname, g in GROUPS.items():
        sub = d[d["group"] == gname]
        if not len(sub):
            continue
        sc = ax.scatter(sub["alt_km"], sub["inc_deg"], c=sub["sigma_m"],
                        cmap=cmap, norm=norm, marker=g["marker"], s=g["size"],
                        edgecolors="#5f6368", linewidths=0.6, label=gname, zorder=3)
    cb = fig.colorbar(sc, ax=ax, pad=0.015)
    cb.set_label("Nominal TLE noise floor σ (m, unified estimator, log scale)")

    # 直接標註主要群集
    ann = [("FORMOSAT-7", 555, 24, (12, -3)),
           ("Starlink", 545, 53.1, (12, -3)),
           ("GRACE / GRACE-FO", 480, 89, (-30, 10)),
           ("SPOT 2/3/4/5", 700, 98.7, (-40, 12)),
           ("Sun-sync altimetry (Envisat/S3/SARAL)", 830, 98.5, (8, -16)),
           ("CryoSat-2", 725, 92, (10, -3)),
           ("SWOT", 900, 77.5, (10, -3)),
           ("HY-2C/2D", 950, 66, (-20, -16)),
           ("Jason-1/2/3 / TOPEX / S6A·S6B", 1335, 66, (-185, 12))]
    for txt, x, y, off in ann:
        ax.annotate(txt, (x, y), textcoords="offset points", xytext=off,
                    fontsize=8, color="#3c4043")
    ax.set_xlabel("Orbital altitude above ground (km, median of TLE history)")
    ax.set_ylabel("Orbital inclination (deg)")
    ax.set_title("Study satellites in altitude–inclination space, colored by nominal TLE noise floor")
    ax.grid(alpha=0.22, zorder=0)
    ax.legend(loc="lower right", fontsize=8, framealpha=0.9)
    fig.tight_layout()
    fig.savefig("docs/fig_tle_noise_floor_map.png", dpi=150)
    print("輸出：docs/fig_tle_noise_floor_map.png, data/benchmark/tle_noise_floor_map.csv")


if __name__ == "__main__":
    main()
