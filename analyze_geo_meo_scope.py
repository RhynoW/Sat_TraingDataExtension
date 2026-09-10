#!/usr/bin/env python3
"""
analyze_geo_meo_scope.py — 量化 StoryMap 案例十二③「GEO/MEO 路由正確、但缺乏量化驗證」的實際規模。

背景：技術附錄只用 2 個手選案例（TJS-10×TJS-3、Shenlong）驗證「路由邏輯把 GEO 目標送對地方」。
但目前資料庫裡實際被路由到 Model 2 的 GEO/MEO 目標到底有多少顆？這個問題本身沒人問過。
本腳本不做偵測準確率驗證（那需要外部真值，見案例十二③的「下一步驗證路線」），
而是先把「目前完全沒有個案核對過的範圍」量到多大，讓誠實揭露更具體。

方法：對資料庫中每顆衛星取最新一筆 TLE，用專案既有的 `classify_orbit()` 分類軌道，
統計 GEO/MEO/GEO+ 類別的衛星數，並列出其中名稱可辨識的知名目標作為範例。

用法：
  python analyze_geo_meo_scope.py
"""
from __future__ import annotations

import duckdb
import pandas as pd

from maneuver_strategies_july import classify_orbit

DB_PATH = "space_db.duckdb"
OUT_CSV = "data/benchmark/geo_meo_routing_scope_20260910.csv"


def main() -> None:
    con = duckdb.connect(DB_PATH, read_only=True)
    df = con.execute("""
        SELECT norad_id, object_name, sma_km, eccentricity, inclination_deg
        FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY norad_id ORDER BY epoch_utc DESC) rn
            FROM raw_tle_archive WHERE sma_km IS NOT NULL
        ) WHERE rn = 1
    """).fetchdf()
    con.close()

    df["orbit_class"] = [classify_orbit(a, e, i) for a, e, i in
                         zip(df["sma_km"], df["eccentricity"], df["inclination_deg"])]
    geo_meo = df[df["orbit_class"].isin(["GEO", "MEO", "GEO+"])].copy()
    geo_meo["is_starlink"] = geo_meo["object_name"].str.upper().str.startswith("STARLINK")
    # 路由邏輯（orbit_anomaly_detector.py）：非 (Starlink 且 orbit∈{LEO,MEO}) → 一律走 Model 2。
    # GEO/GEO+ 全數、以及非 Starlink 的 MEO，皆屬此範圍。
    routed_model2 = geo_meo[~(geo_meo["is_starlink"] & (geo_meo["orbit_class"] == "MEO"))]
    routed_model2.to_csv(OUT_CSV, index=False)

    print(f"資料庫最新快照涵蓋衛星總數：{len(df)}")
    print(f"分類為 GEO/MEO/GEO+ 者：{len(geo_meo)} 顆")
    print(routed_model2["orbit_class"].value_counts().to_string())
    print(f"其中路由至 Model 2（GEO/GEO+ 全數＋非-Starlink MEO）：{len(routed_model2)} 顆")
    print(f"\n輸出 → {OUT_CSV}")


if __name__ == "__main__":
    main()
