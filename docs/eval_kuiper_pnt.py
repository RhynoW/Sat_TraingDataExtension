#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_kuiper_pnt.py — 評估 Amazon Kuiper 之公開星曆（CelesTrak SupGP、Space-Track TLE）用於地面端 LEO-PNT 之條件。

比照期末報告技術附錄第十七節（Starlink：TLE vs MEME 星曆誤差即定位天花板）之架構：
  1. 可見度：台北（25.033°N, 121.565°E）未來 24 小時、仰角 ≥ 10° 之可見顆數，及 ≥ 4 顆之時間比例
     （都卜勒定位解三維位置＋時脈頻偏至少需 4 個獨立觀測；實務上以多顆、長時間累積）。
  2. 星曆差異對觀測量之影響：同一時刻以 SupGP 與「SupGP 曆元前最新 TLE」分別推算，
     比較觀測者至衛星之距離（擬距）與距離變化率（都卜勒），並換算成 Ka 頻段都卜勒頻移差
     （以 19 GHz 為代表值；Kuiper 下行實際頻率與訊號結構未公開，此為假設）。
  兩份星曆皆非真值，第 2 項量的是兩條公開路線之差異，可視為星曆不確定度之下限量級。

用法：python docs/eval_kuiper_pnt.py [supgp.json.gz]
輸出：data/benchmark/kuiper_pnt_eval.csv、docs/fig_kuiper_pnt_eval.png
"""
import gzip
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sgp4 import omm
from sgp4.api import Satrec
from skyfield.api import EarthSatellite, load, wgs84

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/operator_ephemeris/supgp/kuiper/kuiper_20261115.json.gz"
C = 299792458.0
F_KA = 19.0e9           # 假設之 Ka 頻段下行代表頻率
F_KU = 11.45e9          # 參考：Starlink 文獻常用之 Ku 頻段音調頻率
ELEV_MIN = 10.0
KEY = SRC.name.split("_")[0]
LABEL = {"kuiper": "Amazon Kuiper", "oneweb": "OneWeb"}.get(KEY, KEY)
# 主要評估頻率：Kuiper 下行為 Ka（實際頻率未公開，取 19 GHz 假設）；OneWeb 下行為 Ku（取 11.45 GHz 代表值）
F_MAIN, F_MAIN_LAB = (F_KA, "Ka 19 GHz（假設）") if KEY == "kuiper" else (F_KU, "Ku 11.45 GHz（代表值）")
STEP_S = 60
TAIPEI = wgs84.latlon(25.033, 121.565, elevation_m=10.0)


def main():
    ts = load.timescale()
    recs = json.load(gzip.open(SRC, "rt", encoding="utf-8"))
    ids = sorted({int(x["NORAD_CAT_ID"]) for x in recs})
    con = duckdb.connect(str(ROOT / "space_db.duckdb"), read_only=True)
    tle = con.execute(f"SELECT norad_id, tle_epoch, line1, line2 FROM tle_raw WHERE norad_id IN ({','.join(map(str, ids))}) "
                      "AND tle_epoch >= TIMESTAMP '2026-11-01'").df()
    con.close()
    tle["tle_epoch"] = pd.to_datetime(tle["tle_epoch"], utc=True)
    t0 = max(pd.Timestamp(x["EPOCH"], tz="UTC") for x in recs)          # 共同起點：最晚之 SupGP 曆元
    n = 24 * 3600 // STEP_S + 1
    secs = np.arange(n) * STEP_S
    T = ts.utc(t0.year, t0.month, t0.day, t0.hour, t0.minute, t0.second + secs)
    vis_count = np.zeros(n, int)
    rows = []
    for rec in recs:
        nid = int(rec["NORAD_CAT_ID"])
        g = tle[(tle["norad_id"] == nid) & (tle["tle_epoch"] <= pd.Timestamp(rec["EPOCH"], tz="UTC"))]
        if g.empty:
            continue
        last = g.sort_values("tle_epoch").iloc[-1]
        s = Satrec(); omm.initialize(s, {k: str(v) for k, v in rec.items()})
        sat_s = EarthSatellite.from_satrec(s, ts)
        sat_t = EarthSatellite(last["line1"], last["line2"], ts=ts)
        tp_s = (sat_s - TAIPEI).at(T)
        alt, _, dist_s = tp_s.altaz()
        vis = alt.degrees >= ELEV_MIN
        vis_count += vis
        if not vis.any():
            continue
        tp_t = (sat_t - TAIPEI).at(T)
        def rng_rate(tp):
            p, v = tp.position.km, tp.velocity.km_per_s
            return np.linalg.norm(p, axis=0), (p * v).sum(0) / np.linalg.norm(p, axis=0)
        r_s, rr_s = rng_rate(tp_s); r_t, rr_t = rng_rate(tp_t)
        dpos = np.linalg.norm(tp_s.position.km - tp_t.position.km, axis=0)
        for k in np.flatnonzero(vis):
            rows.append({"norad": nid, "t_s": secs[k], "elev": alt.degrees[k], "range_km": r_s[k],
                         "d_range_km": r_t[k] - r_s[k], "d_rrate_ms": (rr_t[k] - rr_s[k]) * 1000.0, "d_pos_km": dpos[k],
                         "tle_age_h": (pd.Timestamp(rec["EPOCH"], tz="UTC") - last["tle_epoch"]).total_seconds() / 3600})
    D = pd.DataFrame(rows)
    D["d_dop_ka_hz"] = D["d_rrate_ms"] * F_KA / C
    D["d_dop_ku_hz"] = D["d_rrate_ms"] * F_KU / C
    D["d_dop_main_hz"] = D["d_rrate_ms"] * F_MAIN / C
    D.to_csv(ROOT / f"data/benchmark/{KEY}_pnt_eval.csv", index=False)

    # 過頂時長
    passes = []
    for nid, g in D.sort_values("t_s").groupby("norad"):
        brk = np.flatnonzero(np.diff(g["t_s"].to_numpy()) > STEP_S) + 1
        for seg in np.split(g["t_s"].to_numpy(), brk):
            passes.append((seg[-1] - seg[0] + STEP_S) / 60)
    q = lambda s, p: float(np.nanpercentile(np.abs(s), p))
    print(f"起點 {t0:%Y-%m-%d %H:%M} UTC，24 小時，台北，仰角 ≥ {ELEV_MIN:.0f}°")
    print(f"可見顆數：中位 {np.median(vis_count):.0f}、最少 {vis_count.min()}、最多 {vis_count.max()}；"
          f"≥4 顆之時間 {np.mean(vis_count >= 4):.1%}、≥1 顆 {np.mean(vis_count >= 1):.1%}")
    print(f"單次過頂時長：中位 {np.median(passes):.1f} 分、P90 {np.percentile(passes, 90):.1f} 分；過頂次數 {len(passes)}")
    print(f"可見樣本 {len(D)}；TLE 年齡中位 {D.drop_duplicates('norad')['tle_age_h'].median():.1f} 小時")
    for lab, col, unit in (("衛星位置差", "d_pos_km", "km"), ("擬距差", "d_range_km", "km"),
                           ("距離變化率差", "d_rrate_ms", "m/s"), (f"都卜勒差 {F_MAIN_LAB}", "d_dop_main_hz", "Hz")):
        print(f"  {lab}：|中位| {q(D[col],50):.3f} {unit}、P90 {q(D[col],90):.3f} {unit}")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.4), dpi=150)
    hrs = secs / 3600
    ax[0].plot(hrs, vis_count, color="#002B8A", lw=1.4)
    ax[0].axhline(4, color="#C2410C", ls="--", lw=1.2, label="4 顆（三維＋時脈之最少觀測數）")
    ax[0].set_xlabel("自起點起之小時（UTC）"); ax[0].set_ylabel("可見顆數（仰角 10° 以上）")
    ax[0].set_title(f"台北上空 {LABEL} 可見顆數（SupGP，24 小時）", fontsize=11); ax[0].grid(alpha=0.3); ax[0].legend(fontsize=9)
    ax[1].hist(np.abs(D["d_range_km"]).clip(1e-3), bins=np.logspace(-2, 3, 50), color="#3F7BE0", alpha=0.85)
    ax[1].set_xscale("log"); ax[1].set_xlabel("|擬距差| (km)，SupGP vs TLE"); ax[1].set_ylabel("可見樣本數")
    ax[1].set_title("觀測者至衛星距離之差異", fontsize=11); ax[1].grid(alpha=0.3)
    ax[2].hist(np.abs(D["d_dop_main_hz"]).clip(1e-1), bins=np.logspace(-1, 4, 50), color="#2F7D4A", alpha=0.85)
    ax[2].set_xscale("log"); ax[2].set_xlabel(f"|都卜勒頻移差| (Hz)，{F_MAIN_LAB}"); ax[2].set_ylabel("可見樣本數")
    ax[2].set_title("距離變化率差換算之都卜勒差異", fontsize=11); ax[2].grid(alpha=0.3)
    for a_ in ax[1:]:
        a_.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    fig.suptitle(f"{LABEL} 公開星曆用於地面端 PNT 之評估（台北，SupGP 曆元 {t0:%Y-%m-%d}；兩份星曆皆非真值）", fontsize=12.5)
    fig.tight_layout()
    fig.savefig(ROOT / f"docs/fig_{KEY}_pnt_eval.png", facecolor="white")
    print(f"fig → docs/fig_{KEY}_pnt_eval.png")


if __name__ == "__main__":
    main()
