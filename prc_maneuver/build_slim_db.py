#!/usr/bin/env python3
"""
build_slim_db.py
================
兩項輸出：

  1. space_db_slim.duckdb
     本地精簡 DB（刪除冗餘表/欄位，保留 2024-01-01 以後資料）
     節省目標：6.7 GB → ~600 MB

  2. data/tle_parquet/
     GitHub / Streamlit Cloud 用月份 parquet
     - prc/YYYY_MM.parquet     中國衛星 TLE（偵測用欄位）
     - sat_metadata.parquet    sat_n2yo_metadata 全表
     節省目標：單檔 < 5 MB，總量 < 150 MB

精簡策略：
  DROP  tle_table (47.6M rows) — 最大元兇，偵測 pipeline 不需要
  DROP  tle_raw   (3.7M rows)  — 與 raw_tle_archive 高度重疊
  DROP  sp_ephem_raw, tle_sp_ric_residuals  — 空表
  DROP  maneuver_labels         — 無任何程式碼引用
  PRUNE raw_tle_archive: 移除 object_name, line1, line2 (佔空間最大),
        epoch_jd, downloaded_at_utc (可由 epoch_utc 還原),
        energy, rmin_km, rmax_km (可由 sma_km/eccentricity 計算)
  RANGE 只保留 2024-01-01 以後（之前資料僅有 270 筆，幾乎為單次快照）

  ⚠️  注意: 刪除 line1/line2 後 conjunction_pipeline.py 將無法
      在 slim DB 上執行 SGP4 傳播。如需保留該功能，改用原始 DB
      或在匯出時加回 line1/line2。

Usage:
  python build_slim_db.py                    # 執行全部
  python build_slim_db.py --slim-only        # 只建立 slim DB
  python build_slim_db.py --parquet-only     # 只匯出 parquet
  python build_slim_db.py --keep-lines       # slim DB 中保留 line1/line2
  python build_slim_db.py --from 2023-01-01  # 自訂起始日期
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

# ── 路徑設定 ─────────────────────────────────────────────────────────────────
REPO         = Path(__file__).resolve().parent.parent   # prc_maneuver/../
SRC_DB       = REPO / "space_db.duckdb"
SLIM_DB      = REPO / "space_db_slim.duckdb"
PARQUET_DIR  = REPO / "data" / "tle_parquet"
ANNO_XLSX    = REPO / "leo_annotator" / "output" / "annotations_leo_full_with_source中國衛星.xlsx"

# ── 精簡用欄位（raw_tle_archive 留下的欄位）────────────────────────────────
SLIM_COLS = [
    "norad_id", "epoch_utc",
    "sma_km", "eccentricity", "inclination_deg", "raan_deg",
    "argp_deg", "mean_anomaly_deg", "mean_motion", "bstar",
]
SLIM_COLS_WITH_LINES = SLIM_COLS + ["line1", "line2"]

# ── parquet 偵測欄位（最小化） ────────────────────────────────────────────
PARQUET_DETECT_COLS = [
    "norad_id", "epoch_utc",
    "sma_km", "eccentricity", "inclination_deg", "raan_deg",
]

# ── latest30day parquet 欄位（含 line1/line2，供 SGP4 傳播用）───────────────
LATEST30_COLS = [
    "norad_id", "object_name", "epoch_utc",
    "line1", "line2",
    "mean_motion", "eccentricity", "inclination_deg",
    "raan_deg", "argp_deg", "mean_anomaly_deg", "bstar", "sma_km",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("slim")


def fmt_mb(path: Path) -> str:
    if path.exists():
        return f"{path.stat().st_size / 1024**2:.1f} MB"
    return "不存在"


# ─────────────────────────────────────────────────────────────────────────────
# Part 1: 建立 space_db_slim.duckdb
# ─────────────────────────────────────────────────────────────────────────────

def build_slim_db(date_from: str, keep_lines: bool,
                  recent_days: int = 0, whitelist: list[int] | None = None) -> None:
    if SLIM_DB.exists():
        log.info("刪除舊的 slim DB: %s", SLIM_DB)
        SLIM_DB.unlink()

    log.info("=== Part 1: 建立 %s ===", SLIM_DB.name)
    log.info("原始 DB 大小: %s", fmt_mb(SRC_DB))

    # 用 dst（slim DB）attach 源 DB，再複製
    dst = duckdb.connect(str(SLIM_DB), read_only=False)
    dst.execute("SET preserve_insertion_order = false;")
    dst.execute(f"ATTACH '{SRC_DB}' AS src (READ_ONLY);")

    cols = SLIM_COLS_WITH_LINES if keep_lines else SLIM_COLS
    col_str = ", ".join(cols)

    # ── 1. raw_tle_archive ────────────────────────────────────────────────
    #   發布用精簡：全衛星只留最近 recent_days 天（live app 只取每顆最新一筆，故足夠），
    #   白名單衛星則保留完整歷史（供 RPO 3D 反演之展示，如神龍 58573×59884）。
    #   recent_days<=0 → 沿用舊行為（date_from 以後全歷史）。
    t0 = time.time()
    whitelist = whitelist or []
    if recent_days and recent_days > 0:
        wl_clause = (" OR norad_id IN ({})".format(
            ", ".join(str(int(x)) for x in whitelist)) if whitelist else "")
        where = (
            f"epoch_utc >= '{date_from}' AND ("
            f"epoch_utc >= (SELECT max(epoch_utc) FROM src.raw_tle_archive) "
            f"- INTERVAL '{int(recent_days)}' DAY{wl_clause})"
        )
        log.info("複製 raw_tle_archive（全衛星最近 %d 天 + 白名單%s 完整歷史，%d 欄）…",
                 recent_days, whitelist or "（無）", len(cols))
    else:
        where = f"epoch_utc >= '{date_from}'"
        log.info("複製 raw_tle_archive（%s 以後全歷史，%d 欄）…", date_from, len(cols))
    dst.execute(f"""
        CREATE TABLE raw_tle_archive AS
        SELECT {col_str}
        FROM src.raw_tle_archive
        WHERE {where}
    """)
    n = dst.execute("SELECT COUNT(*) FROM raw_tle_archive").fetchone()[0]
    nwl = 0
    if whitelist:
        nwl = dst.execute(
            "SELECT COUNT(*) FROM raw_tle_archive WHERE norad_id IN ({})".format(
                ", ".join(str(int(x)) for x in whitelist))).fetchone()[0]
    log.info("  raw_tle_archive: %d 列（其中白名單 %d 列）(%.1f s)", n, nwl, time.time() - t0)

    # ── 2. sat_n2yo_metadata（全部） ───────────────────────────────────────
    t0 = time.time()
    log.info("複製 sat_n2yo_metadata …")
    dst.execute("CREATE TABLE sat_n2yo_metadata AS SELECT * FROM src.sat_n2yo_metadata")
    n = dst.execute("SELECT COUNT(*) FROM sat_n2yo_metadata").fetchone()[0]
    log.info("  sat_n2yo_metadata: %d 列 (%.1f s)", n, time.time() - t0)

    # ── 3. 小型業務表 ────────────────────────────────────────────────────────
    for tbl in ["training_samples_plan_b", "training_samples", "conjunction_events"]:
        t0 = time.time()
        log.info("複製 %s …", tbl)
        dst.execute(f"CREATE TABLE {tbl} AS SELECT * FROM src.{tbl}")
        n = dst.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        log.info("  %s: %d 列 (%.1f s)", tbl, n, time.time() - t0)

    dst.execute("DETACH src;")

    # ── 4. 建立索引 ──────────────────────────────────────────────────────────
    log.info("建立索引 …")
    try:
        dst.execute(
            "CREATE INDEX idx_rta_norad_epoch ON raw_tle_archive(norad_id, epoch_utc);"
        )
    except Exception as e:
        log.warning("索引建立失敗（可能已存在）: %s", e)

    try:
        dst.execute("CHECKPOINT;")   # 壓縮檔案、釋放未用空間
    except Exception as e:
        log.warning("CHECKPOINT 失敗: %s", e)
    dst.close()

    log.info("✅ slim DB 完成: %s", fmt_mb(SLIM_DB))
    log.info("   省下: %.1f GB",
             (SRC_DB.stat().st_size - SLIM_DB.stat().st_size) / 1024**3)

    # 說明刪除的表
    dropped = ["tle_table (47.6M rows)", "tle_raw (3.7M rows)",
               "sp_ephem_raw (0 rows)", "tle_sp_ric_residuals (0 rows)",
               "maneuver_labels (346 rows)"]
    log.info("   已刪除: %s", ", ".join(dropped))
    if not keep_lines:
        log.info("   ⚠️  line1/line2 已刪除 → conjunction_pipeline 需改用原始 DB")


# ─────────────────────────────────────────────────────────────────────────────
# Part 2: 匯出月份 parquet
# ─────────────────────────────────────────────────────────────────────────────

def export_parquet(date_from: str, db_path: Path) -> None:
    log.info("=== Part 2: 匯出月份 parquet 至 %s ===", PARQUET_DIR)

    prc_dir = PARQUET_DIR / "prc"
    prc_dir.mkdir(parents=True, exist_ok=True)

    # 讀取中國衛星清單
    log.info("讀取中國衛星清單 …")
    ann = pd.read_excel(ANNO_XLSX)
    prc = ann[ann["source_code"].str.contains("China|PRC", case=False, na=False)]
    prc_ids = sorted(prc["norad_id"].astype(int).unique().tolist())
    log.info("中國衛星 NORAD IDs: %d 顆", len(prc_ids))

    con = duckdb.connect(str(db_path), read_only=True)

    # 取得所有月份清單
    months_df = con.execute(f"""
        SELECT DISTINCT
            YEAR(epoch_utc)  AS yr,
            MONTH(epoch_utc) AS mo
        FROM raw_tle_archive
        WHERE epoch_utc >= '{date_from}'
        ORDER BY yr, mo
    """).fetchdf()

    total_size = 0
    col_str = ", ".join(PARQUET_DETECT_COLS)
    id_str   = ",".join(map(str, prc_ids))

    log.info("共 %d 個月份需要匯出", len(months_df))

    for _, row in months_df.iterrows():
        yr, mo = int(row["yr"]), int(row["mo"])
        month_start = f"{yr:04d}-{mo:02d}-01"
        # 月末：下個月01日前一秒
        next_mo = (pd.Timestamp(month_start) + pd.offsets.MonthEnd(0))
        month_end = (next_mo + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

        out_path = prc_dir / f"{yr:04d}_{mo:02d}.parquet"

        df = con.execute(f"""
            SELECT {col_str}
            FROM raw_tle_archive
            WHERE norad_id IN ({id_str})
              AND epoch_utc >= '{month_start}'
              AND epoch_utc <  '{month_end}'
            ORDER BY norad_id, epoch_utc
        """).fetchdf()

        if df.empty:
            log.debug("  %04d-%02d: 無中國衛星資料，略過", yr, mo)
            continue

        df.to_parquet(out_path, index=False, compression="snappy")
        sz = out_path.stat().st_size / 1024
        total_size += out_path.stat().st_size
        log.info("  %04d-%02d: %6d 列 → %s  (%d KB)",
                 yr, mo, len(df), out_path.name, sz)

    # ── sat_n2yo_metadata 單一 parquet ───────────────────────────────────────
    log.info("匯出 sat_n2yo_metadata.parquet …")
    meta_df = con.execute("SELECT * FROM sat_n2yo_metadata").fetchdf()
    meta_path = PARQUET_DIR / "sat_metadata.parquet"
    meta_df.to_parquet(meta_path, index=False, compression="snappy")
    total_size += meta_path.stat().st_size
    log.info("  sat_metadata.parquet: %d 列, %d KB",
             len(meta_df), meta_path.stat().st_size // 1024)

    # ── 產生月份索引檔 ────────────────────────────────────────────────────────
    index_path = PARQUET_DIR / "prc" / "_index.csv"
    files = sorted(prc_dir.glob("*.parquet"))
    idx_rows = []
    for f in files:
        parts = f.stem.split("_")
        if len(parts) == 2:
            idx_rows.append({"file": f.name,
                              "year": int(parts[0]),
                              "month": int(parts[1]),
                              "size_kb": f.stat().st_size // 1024})
    pd.DataFrame(idx_rows).to_csv(index_path, index=False)
    log.info("月份索引: %s (%d 個月)", index_path, len(idx_rows))

    con.close()

    log.info("✅ parquet 匯出完成  總計 %.1f MB", total_size / 1024**2)
    log.info("   目錄: %s", PARQUET_DIR)
    log.info("   建議加入 .gitattributes: *.parquet filter=lfs diff=lfs ...")


# ─────────────────────────────────────────────────────────────────────────────
# Part 3: 匯出 latest30day_tle.parquet（含 line1/line2）+ conjunction_events.parquet
# ─────────────────────────────────────────────────────────────────────────────

def export_latest30day_parquet() -> None:
    """
    從 SRC_DB（原始全量 DB）匯出：
      - latest30day_tle.parquet：每顆衛星最新一筆 TLE（30 天內），含 line1/line2
      - conjunction_events.parquet：預計算合相事件表

    必須讀原始 DB（slim DB 已移除 line1/line2 與 object_name）。
    """
    log.info("=== Part 3: 匯出 latest30day parquet ===")
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)

    if not SRC_DB.exists():
        log.error("找不到原始 DB: %s", SRC_DB)
        return

    con = duckdb.connect(str(SRC_DB), read_only=True)
    col_str = ", ".join(LATEST30_COLS)

    # ── latest30day_tle.parquet ──────────────────────────────────────────────
    t0 = time.time()
    log.info("查詢 latest30day TLE（每顆衛星最新一筆，30 天內）…")
    df_tle = con.execute(f"""
        WITH latest AS (
            SELECT {col_str},
                   ROW_NUMBER() OVER (
                       PARTITION BY norad_id
                       ORDER BY epoch_utc DESC
                   ) AS rn
            FROM raw_tle_archive
            WHERE epoch_utc >= current_timestamp - INTERVAL '30' DAY
              AND line1 IS NOT NULL
              AND line2 IS NOT NULL
        )
        SELECT {col_str}
        FROM latest
        WHERE rn = 1
        ORDER BY norad_id
    """).fetchdf()

    out_tle = PARQUET_DIR / "latest30day_tle.parquet"
    df_tle.to_parquet(out_tle, index=False, compression="snappy")
    sz_tle = out_tle.stat().st_size
    log.info("  latest30day_tle.parquet: %d 顆衛星, %.0f KB  (%.1f s)",
             len(df_tle), sz_tle / 1024, time.time() - t0)

    # ── conjunction_events.parquet ───────────────────────────────────────────
    t0 = time.time()
    try:
        df_ce = con.execute(
            "SELECT * FROM conjunction_events ORDER BY tca_utc DESC"
        ).fetchdf()
        out_ce = PARQUET_DIR / "conjunction_events.parquet"
        df_ce.to_parquet(out_ce, index=False, compression="snappy")
        log.info("  conjunction_events.parquet: %d 列, %.0f KB  (%.1f s)",
                 len(df_ce), out_ce.stat().st_size / 1024, time.time() - t0)
    except Exception as e:
        log.warning("conjunction_events 匯出失敗（表可能不存在）: %s", e)

    con.close()
    log.info("✅ latest30day parquet 完成  (%.1f MB)", sz_tle / 1024**2)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="建立 slim DB 與月份 parquet")
    ap.add_argument("--slim-only",    action="store_true", help="只建立 slim DB")
    ap.add_argument("--parquet-only", action="store_true", help="只匯出 parquet")
    ap.add_argument("--keep-lines",   action="store_true",
                    help="slim DB 中保留 line1/line2（conjunction 需要，但增加體積）")
    ap.add_argument("--from",  dest="date_from", default="2024-01-01",
                    help="資料起始日期 YYYY-MM-DD（預設 2024-01-01）")
    ap.add_argument("--recent-days", type=int, default=0,
                    help="發布用精簡：全衛星只保留最近 N 天歷史（live app 只取每顆最新一筆即足）；"
                         "0=停用（沿用 --from 全歷史）。建議搭配 --keep-lines。")
    ap.add_argument("--whitelist", default="58573,59884,67689,69673,58204,43874",
                    help="以逗號分隔之 NORAD，這些衛星保留完整歷史（供 RPO 反演展示，"
                         "如神龍第3次 58573,59884、第4次 2026 太空梭67689/ObjH 69673）；空字串＝無白名單。")
    ap.add_argument("--parquet-src", choices=["original", "slim"], default="original",
                    help="parquet 資料來源：original=原始DB, slim=精簡DB（需先執行slim）")
    ap.add_argument("--latest30day", action="store_true",
                    help="匯出最近 30 天最新 TLE（含 line1/line2）至 latest30day_tle.parquet"
                         " 與 conjunction_events.parquet，供 conjunction_app.py 使用")
    args = ap.parse_args()

    if not SRC_DB.exists():
        log.error("找不到原始 DB: %s", SRC_DB)
        return 1

    do_slim    = not args.parquet_only
    do_parquet = not args.slim_only

    if do_slim:
        wl = [int(x) for x in str(args.whitelist).replace("，", ",").split(",")
              if x.strip().isdigit()]
        build_slim_db(args.date_from, args.keep_lines,
                      recent_days=args.recent_days, whitelist=wl)

    if do_parquet:
        src = SLIM_DB if args.parquet_src == "slim" and SLIM_DB.exists() else SRC_DB
        log.info("parquet 資料來源: %s", src.name)
        export_parquet(args.date_from, src)

    if args.latest30day:
        export_latest30day_parquet()

    # ── 最終大小報告 ───────────────────────────────────────────────────────
    print(f"\n{'='*55}")
    print(f"  完成摘要")
    print(f"{'='*55}")
    print(f"  原始 DB    : {fmt_mb(SRC_DB)}")
    if SLIM_DB.exists():
        print(f"  slim DB    : {fmt_mb(SLIM_DB)}")
        saving = (SRC_DB.stat().st_size - SLIM_DB.stat().st_size) / SRC_DB.stat().st_size
        print(f"  節省       : {saving*100:.0f}%")
    if PARQUET_DIR.exists():
        total = sum(f.stat().st_size for f in PARQUET_DIR.rglob("*.parquet"))
        print(f"  parquet 總量: {total/1024**2:.1f} MB  ({PARQUET_DIR})")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
