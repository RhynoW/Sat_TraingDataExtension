# -*- coding: utf-8 -*-
"""batch_detect_starlink_v3.py — 案例研究簡報第六節：批次偵測 Starlink V3（Flight 14）26 顆之軌道機動

與簡報其餘 30 顆衛星同一套方法（見 gen_case_study_timeseries_figs.py 與原 timeseries10.py／overview20.py）：
  ① 統一偵測摘要：orbit_anomaly_detector.OrbitAnomalyDetector.detect()
  ② 融合評分器時間序列：maneuver_report_builder.compute_fusion_detection()，門檻 0.659；
     相隔 48 小時內之判定點合併為同一事件（gen_case_study_timeseries_figs.merge_episodes）
  ③ L1 規則層：maneuver_strategies_july.apply_strategies 之 combined 旗標，同樣以 48 小時合併
對照（代理真值，非精密星曆）：由 TLE 高度自身推得之「升軌日」——當日中位高度較前一日高 > 1 km。

輸出：data/benchmark/case_study_v3_20261021/{overview.json, <norad>_fusion.csv}
      docs/case_study_figs/v3_{altitude,raster}.png（深色主題，供簡報嵌入）
用法：python docs/batch_detect_starlink_v3.py
"""
import json
import sys
from pathlib import Path

import duckdb
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

DOCS = Path(__file__).parent
ROOT = DOCS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DOCS))

import maneuver_report_builder as rb  # noqa: E402
import maneuver_strategies_july as ms  # noqa: E402
import orbit_anomaly_detector as oad  # noqa: E402
from gen_case_study_timeseries_figs import (BG, C_HIGH, C_MID, GRID, INK, MUTE, PANEL,  # noqa: E402
                                            merge_episodes)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = ROOT / "data" / "benchmark" / "case_study_v3_20261021"
OUT.mkdir(parents=True, exist_ok=True)
FIG = DOCS / "case_study_figs"
NORADS = range(100855, 100881)
LAGGARDS = {100858: "#EF5350", 100865: "#4FC3F7", 100870: "#FFD54F"}
RAISE_KM_PER_DAY = 1.0
EP_GAP_H = 48


def l1_episodes(tle: pd.DataFrame) -> list:
    tr = ms.build_transitions(tle.rename(columns={"epoch": "epoch"}))
    if tr.empty:
        return []
    oc = ms.classify_orbit(float(tle.sma_km.median()), float(tle.eccentricity.median()),
                           float(tle.inclination_deg.median()))
    flags = ms.apply_strategies(tr, oc)["combined"]
    ep = pd.to_datetime(tr.loc[flags, "epoch"], utc=True).sort_values().tolist()
    out, cur = [], []
    for t in ep:
        if cur and (t - cur[-1]).total_seconds() / 3600 > EP_GAP_H:
            out.append(cur); cur = []
        cur.append(t)
    if cur:
        out.append(cur)
    return [[str(c[0].date()), str(c[-1].date()), len(c)] for c in out]


def raising_days(tle: pd.DataFrame) -> list:
    alt = (tle.set_index("epoch").sma_km - 6378.137).resample("1D").median().dropna()
    d = alt.diff()
    return [str(t.date()) for t in d[d > RAISE_KM_PER_DAY].index]


def main():
    con = duckdb.connect(str(ROOT / "space_db.duckdb"), read_only=True)
    det = oad.OrbitAnomalyDetector(str(ROOT / "space_db.duckdb"))
    res, series = {}, {}
    for nid in NORADS:
        tle = con.execute("SELECT epoch_utc AS epoch, object_name, sma_km, inclination_deg, eccentricity, raan_deg, bstar "
                          "FROM raw_tle_archive WHERE norad_id=? ORDER BY epoch_utc", [nid]).fetchdf()
        tle["epoch"] = pd.to_datetime(tle.epoch, utc=True)
        tle = tle.drop_duplicates("epoch").reset_index(drop=True)
        name = str(tle.object_name.iloc[0]).replace("0 ", "", 1).strip()
        r = det.detect(nid)
        fus = rb.compute_fusion_detection(nid, tle.epoch.min().date(), tle.epoch.max().date())
        f_eps = []
        if fus is not None and len(fus):
            fdf = fus[["epoch", "fusion"]].copy()
            fdf["thr"] = fus.attrs.get("thr", 0.659)
            fdf["epoch"] = pd.to_datetime(fdf.epoch, utc=True)
            fdf.to_csv(OUT / f"{nid}_fusion.csv", index=False)
            f_eps = [[e["d0"], e["d1"], e["n"], round(e["val"], 3)] for e in merge_episodes(fdf, "fusion")]
        res[nid] = dict(name=name, n_tle=len(tle), routed=r.get("routed_primary"),
                        fusion_flags=r.get("fusion_flags"), fusion_max=r.get("fusion_max_prob"),
                        model2=r.get("model2_anomalies"), alt_now=round(float(tle.sma_km.iloc[-1] - 6378.137), 1),
                        fusion_episodes=f_eps, l1_episodes=l1_episodes(tle), raising_days=raising_days(tle),
                        last_epoch=str(tle.epoch.max()))
        series[nid] = tle[["epoch", "sma_km"]]
        print(f"{name} ({nid}): TLE {len(tle)}，融合事件 {len(f_eps)}，L1 事件 {len(res[nid]['l1_episodes'])}，"
              f"升軌日 {len(res[nid]['raising_days'])}", flush=True)
    con.close()

    # 對照統計：事件（任一天）落在升軌日 ±1 天內者視為「與升軌期重合」
    def overlap(eps, days):
        rd = pd.DatetimeIndex(pd.to_datetime(days))
        hit = 0
        for d0, d1, *_ in eps:
            span = pd.date_range(pd.Timestamp(d0) - pd.Timedelta(days=1), pd.Timestamp(d1) + pd.Timedelta(days=1))
            hit += int(len(rd) and span.isin(rd).any())
        return hit
    for v in res.values():
        v["fusion_in_raise"] = overlap(v["fusion_episodes"], v["raising_days"])
        v["l1_in_raise"] = overlap(v["l1_episodes"], v["raising_days"])
    with open(OUT / "overview.json", "w", encoding="utf-8") as fh:
        json.dump({str(k): v for k, v in res.items()}, fh, ensure_ascii=False, indent=2)
    print("→", OUT / "overview.json")
    plot_altitude(series, res)
    plot_raster(res)


def _style(ax):
    ax.set_facecolor(PANEL)
    ax.grid(color=GRID, lw=0.6)
    for sp in ax.spines.values():
        sp.set_color(GRID)
    ax.tick_params(colors=MUTE, labelsize=10)


def plot_altitude(series, res):
    fig, ax = plt.subplots(figsize=(12.8, 5.0), dpi=150)
    fig.patch.set_facecolor(BG); _style(ax)
    for nid, s in series.items():
        if nid not in LAGGARDS:
            ax.plot(s.epoch, s.sma_km - 6378.137, color="#5F7896", lw=1.0)
    for nid, c in LAGGARDS.items():
        s = series[nid]
        ax.plot(s.epoch, s.sma_km - 6378.137, color=c, lw=2.2, label=f"{nid} {res[nid]['name']}")
    ax.set_ylabel("平均高度（km）", color=MUTE, fontsize=11)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.legend(loc="lower right", facecolor=PANEL, edgecolor=GRID, labelcolor=INK, fontsize=10)
    ax.set_title("Starlink V3（26 顆）入軌後平均高度——灰線為主隊 23 顆，彩色為落後星", color=INK, fontsize=13, loc="left")
    fig.tight_layout(); fig.savefig(FIG / "v3_altitude.png", facecolor=BG); plt.close(fig)
    print("→", FIG / "v3_altitude.png")


def plot_raster(res):
    nids = sorted(res)
    fig, ax = plt.subplots(figsize=(12.8, 5.6), dpi=150)
    fig.patch.set_facecolor(BG); _style(ax)
    for y, nid in enumerate(nids):
        days = [mdates.date2num(pd.Timestamp(d)) for d in res[nid]["raising_days"]]
        ax.broken_barh([(x, 1.0) for x in days], (y - 0.42, 0.84), color="#2E5E4E", lw=0)
        for d0, d1, *_ in res[nid]["l1_episodes"]:
            ax.plot([pd.Timestamp(d0), pd.Timestamp(d1) + pd.Timedelta(hours=12)], [y + 0.18, y + 0.18],
                    color=C_MID, lw=3, solid_capstyle="butt")
        for d0, d1, *_ in res[nid]["fusion_episodes"]:
            ax.plot([pd.Timestamp(d0), pd.Timestamp(d1) + pd.Timedelta(hours=12)], [y - 0.18, y - 0.18],
                    color=C_HIGH, lw=3, solid_capstyle="butt")
    ax.set_yticks(range(len(nids)))
    ax.set_yticklabels([str(n) for n in nids], fontsize=8)
    ax.set_ylim(-0.7, len(nids) - 0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    handles = [plt.Line2D([], [], color="#2E5E4E", lw=8, label="升軌日（TLE 高度日增 > 1 km，代理真值）"),
               plt.Line2D([], [], color=C_MID, lw=3, label="L1 規則層事件"),
               plt.Line2D([], [], color=C_HIGH, lw=3, label="融合評分器事件（門檻 0.659）")]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.07), ncol=3, frameon=False,
              labelcolor=INK, fontsize=10)
    ax.set_title("26 顆逐星偵測事件 vs 升軌日", color=INK, fontsize=13, loc="left")
    fig.tight_layout(); fig.savefig(FIG / "v3_raster.png", facecolor=BG); plt.close(fig)
    print("→", FIG / "v3_raster.png")


if __name__ == "__main__":
    main()
