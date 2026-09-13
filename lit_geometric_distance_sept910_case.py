#!/usr/bin/env python3
"""lit_geometric_distance_sept910_case.py — 案例十一 Tier1 第 6 篇補充驗證：
用「近乎同時」的 TLE（tle_downloads/historical_daily_2026-09-10.tle，epoch
2026-09-09 20:04）配對 MEME（data/raw/STARLINK-5367/2026-09-09T19-19-42Z.txt，
覆蓋 2026-09-09 19:19 ~ 2026-09-12 19:19），排除先前「TLE落後3-6天」造成的
雜訊污染，得到一組乾淨、貼近即時的幾何距離殘差。

發現：沿軌（along-track, dr_t_km）殘差從 ~3km 快速成長至 ~81km 並在約
2026-09-11 21:00 後趨於平緩（plateau），徑向(dr_r_km)與法向(dr_n_km)全程
維持在 <1.5km——典型的「相位調整（phasing）」機動訊號特徵：不改變半長軸
（本專案 raw_tle_archive 同期 sma_km 幾乎持平，6860.7~6861.2km 內波動），
純粹調整衛星在軌道內的前後位置。**這正是本專案其餘 5 篇（全部作用於
sma_km 或其差分）在設計上絕對抓不到的機動類型**——幾何距離法（比較完整
3D 位置而非僅比較 sma 純量）在此展現了與眾不同、互補的偵測能力。

用法：python lit_geometric_distance_sept910_case.py
輸出：data/benchmark/lit_geometric_distance_sept910_case_20260913.csv
"""
from __future__ import annotations
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from starlink_ephemeris.parser import parse_ephemeris_file
from compare_tle_vs_ephemeris import propagate_tle, compute_residuals
from skyfield.api import load as skyfield_load

NORAD = 55501
SAT_NAME = "STARLINK-5367"
TLE_LINE1 = "1 55501U 23015BE  26252.83652551 -.00029524  00000-0 -10630-2 0  9995"
TLE_LINE2 = "2 55501  43.0029  20.1317 0001828 285.4754  74.5896 15.27719392198759"
MEME_FILE = Path("data/raw/STARLINK-5367/2026-09-09T19-19-42Z.txt")


def main():
    meta, meme_df = parse_ephemeris_file(MEME_FILE, sat_id=SAT_NAME)
    print(f"MEME 點數：{len(meme_df)}，{meme_df['t'].min()} ~ {meme_df['t'].max()}")

    ts = skyfield_load.timescale()
    prop = propagate_tle(TLE_LINE1, TLE_LINE2, SAT_NAME, meme_df["t"], ts)
    res = compute_residuals(meme_df, prop)
    print(f"幾何距離：均值={res['pos_err_km'].mean():.2f}km "
          f"最大={res['pos_err_km'].max():.2f}km")
    print("\n沿軌/徑向/法向分解（每 300 點取樣）：")
    print(res.iloc[::300][["t", "dr_r_km", "dr_t_km", "dr_n_km", "pos_err_km"]].to_string())

    con = duckdb.connect("space_db.duckdb", read_only=True)
    sma = con.execute(
        "SELECT epoch_utc, sma_km FROM raw_tle_archive WHERE norad_id=? "
        "AND epoch_utc BETWEEN '2026-09-07' AND '2026-09-13' ORDER BY epoch_utc",
        [NORAD]).fetchdf()
    con.close()
    print("\n同期 TLE sma_km（獨立交叉核對，應近乎持平才符合『相位調整』假設）：")
    print(sma.to_string())

    res["norad_id"] = NORAD; res["sat_name"] = SAT_NAME
    out = Path("data/benchmark/lit_geometric_distance_sept910_case_20260913.csv")
    res[["t", "norad_id", "sat_name", "pos_err_km", "dr_r_km", "dr_t_km", "dr_n_km"]].to_csv(
        out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}")


if __name__ == "__main__":
    main()
