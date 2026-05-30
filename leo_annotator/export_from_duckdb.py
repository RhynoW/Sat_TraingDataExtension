"""
export_from_duckdb.py
=====================
從 space_db.duckdb 的 sat_n2yo_metadata 匯出 LEO 衛星清單，
產生 leo_satellite_annotator.py 所需的輸入 CSV。

輸出：
  input_leo_non_starlink.csv  — 非 Starlink LEO（優先處理，較可能有質量資料）
  input_leo_starlink.csv      — Starlink LEO（軌道資料完整，但質量需另行估算）
  input_leo_all.csv           — 全部合併（非 Starlink 在前）

執行：
  python export_from_duckdb.py
  python export_from_duckdb.py --db "C:\\path\\to\\space_db.duckdb"
"""

import argparse
from pathlib import Path

import duckdb
import pandas as pd

DEFAULT_DB = r"C:\STK_Python\CCIT_Orbit_Maneuvers\GCP_Version\space_db.duckdb"
OUTPUT_DIR = Path(__file__).parent


def export(db_path: str) -> None:
    con = duckdb.connect(db_path, read_only=True)

    df = con.execute("""
        SELECT
            norad_id,
            intl_code                                  AS COSPAR_ID,
            name_en                                    AS NAME,
            ROUND((perigee_km + apogee_km) / 2.0, 1)  AS MEAN_ALT_KM,
            perigee_km,
            apogee_km,
            inclination_deg,
            rcs_text,
            source_code,
            launch_date
        FROM sat_n2yo_metadata
        WHERE perigee_km IS NOT NULL
          AND apogee_km  IS NOT NULL
          AND (perigee_km + apogee_km) / 2.0 BETWEEN 300 AND 1000
          AND name_en NOT LIKE '%DEB%'
          AND name_en NOT LIKE '%*%'
        ORDER BY
            CASE WHEN name_en LIKE 'STARLINK%' THEN 1 ELSE 0 END,
            norad_id
    """).df()

    con.close()

    df.rename(columns={"norad_id": "NORAD_ID"}, inplace=True)

    is_starlink = df["NAME"].str.startswith("STARLINK")
    non_sl = df[~is_starlink].reset_index(drop=True)
    sl     = df[is_starlink].reset_index(drop=True)

    # 只保留 annotator 所需的欄位輸出（其餘欄位保留在 _full 版本以便查閱）
    core_cols = ["NORAD_ID", "COSPAR_ID", "NAME", "MEAN_ALT_KM"]

    non_sl[core_cols].to_csv(OUTPUT_DIR / "input_leo_non_starlink.csv", index=False)
    sl[core_cols].to_csv(OUTPUT_DIR / "input_leo_starlink.csv",     index=False)
    df[core_cols].to_csv(OUTPUT_DIR / "input_leo_all.csv",          index=False)

    # 完整版（含軌道細節，供人工查閱）
    non_sl.to_csv(OUTPUT_DIR / "input_leo_non_starlink_full.csv", index=False)

    print(f"非 Starlink LEO：{len(non_sl):>5} 顆 → input_leo_non_starlink.csv")
    print(f"Starlink LEO   ：{len(sl):>5} 顆 → input_leo_starlink.csv")
    print(f"合計            ：{len(df):>5} 顆 → input_leo_all.csv")


def main() -> None:
    p = argparse.ArgumentParser(description="Export LEO satellites from space_db.duckdb")
    p.add_argument("--db", default=DEFAULT_DB, help="DuckDB 檔案路徑")
    args = p.parse_args()
    export(args.db)


if __name__ == "__main__":
    main()
