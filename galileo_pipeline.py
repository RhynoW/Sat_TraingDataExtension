#!/usr/bin/env python3
"""
Multi-GNSS SP3 完整流程腳本（Galileo / BDS / GPS / GLONASS）

步驟：
  1. 下載 MGEX SP3 精密星曆（COD / GFZ）
  2. 建立 DuckDB 索引
  3. 匯出每日 Parquet（ECEF，公尺）
  4. 與 space_db.duckdb 中的 TLE 比對，輸出 RTN 殘差 CSV

用法範例：
  python galileo_pipeline.py                               # Galileo 全流程
  python galileo_pipeline.py --constellation C             # BDS
  python galileo_pipeline.py --skip-download               # 跳過下載
  python galileo_pipeline.py --start 2026-02-01 --end 2026-02-28
  python galileo_pipeline.py --skip-export --skip-compare  # 只下載+索引
"""
from __future__ import annotations

import argparse
import datetime
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("gnss_pipeline")

_CONSTELLATION_NAMES = {
    "E": "galileo",
    "C": "bds",
    "G": "gps",
    "R": "glonass",
    "J": "qzss",
}


def _step_download(start: datetime.date, end: datetime.date, sp3_dir: Path,
                   ac_priority: list[str]) -> list[Path]:
    from mgex_galileo import download_galileo_sp3
    log.info("[1/4] 下載 SP3  %s → %s  ACs=%s", start, end, ac_priority)
    paths = download_galileo_sp3(start, end, sp3_dir, ac_priority=ac_priority)
    log.info("      %d 個檔案已就緒", len(paths))
    return paths


def _step_index(sp3_dir: Path, index_db: Path) -> None:
    from mgex_galileo import build_sp3_index
    patterns = ["**/*.SP3", "**/*.sp3", "**/*.eph", "**/*.EPH"]
    sp3_files: list[Path] = []
    for pat in patterns:
        sp3_files.extend(sp3_dir.glob(pat))
    sp3_files = sorted(set(sp3_files))
    log.info("[2/4] 索引 %d 個 SP3 檔案 → %s", len(sp3_files), index_db)
    build_sp3_index(sp3_files, index_db)


def _step_export(start: datetime.date, end: datetime.date,
                 index_db: Path, out_dir: Path,
                 constellation: str) -> int:
    import pandas as pd
    from mgex_galileo import parse_sp3_gnss, query_sp3_files_for_interval

    cname = _CONSTELLATION_NAMES.get(constellation, constellation.lower())
    log.info("[3/4] 匯出每日 Parquet [%s] → %s", constellation, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    total_rows = 0
    day = start
    while day <= end:
        t0 = pd.Timestamp(day, tz="UTC")
        t1 = t0 + pd.Timedelta(hours=23, minutes=59, seconds=59)
        files = query_sp3_files_for_interval(index_db, t0, t1,
                                             require_galileo=(constellation == "E"))
        if not files:
            log.warning("  %s: 無 SP3 資料", day)
            day += datetime.timedelta(days=1)
            continue

        frames = []
        for f in files:
            try:
                df = parse_sp3_gnss(f, constellation=constellation)
                mask = (df["t_gps"] >= t0) & (df["t_gps"] <= t1)
                frames.append(df[mask])
            except Exception as exc:
                log.warning("  解析失敗 %s: %s", f.name, exc)

        if not frames:
            day += datetime.timedelta(days=1)
            continue

        daily = pd.concat(frames, ignore_index=True)
        daily = daily.sort_values(["sat_id", "t_gps"]).reset_index(drop=True)
        out = out_dir / f"{cname}_sp3_{day}.parquet"
        daily.to_parquet(out, index=False)
        total_rows += len(daily)
        log.info(
            "  %s: %d 列 (%d 衛星, %d epoch) → %s",
            day, len(daily), daily["sat_id"].nunique(),
            daily["t_gps"].nunique(), out.name,
        )
        day += datetime.timedelta(days=1)

    log.info("      匯出完成，共 %d 列", total_rows)
    return total_rows


def _step_compare(start: datetime.date, end: datetime.date,
                  export_dir: Path, space_db: Path, out_dir: Path,
                  constellation: str) -> None:
    cname = _CONSTELLATION_NAMES.get(constellation, constellation.lower())
    log.info("[4/4] SP3 vs TLE 比對 [%s] → %s", constellation, out_dir)

    if constellation == "E":
        try:
            from compare_galileo_sp3_vs_tle import run_comparison
        except ImportError:
            log.error("找不到 compare_galileo_sp3_vs_tle.py，跳過比對步驟")
            return
        run_comparison(
            sp3_parquet_dir=export_dir,
            space_db=space_db,
            out_dir=out_dir,
            start=start,
            end=end,
        )
    elif constellation == "C":
        try:
            from compare_bds_sp3_vs_tle import run_comparison
        except ImportError:
            log.error("找不到 compare_bds_sp3_vs_tle.py，跳過比對步驟")
            return
        run_comparison(
            sp3_parquet_dir=export_dir,
            space_db=space_db,
            out_dir=out_dir,
            start=start,
            end=end,
        )
    else:
        log.warning("星座 %s 尚未有比對腳本，跳過", constellation)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Multi-GNSS SP3 下載→索引→匯出→比對流程",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--constellation", default="E",
                   choices=list(_CONSTELLATION_NAMES.keys()),
                   help="星系前綴: E=Galileo, C=BDS, G=GPS, R=GLONASS, J=QZSS")
    p.add_argument("--start", default="2026-01-01", help="開始日期 YYYY-MM-DD")
    p.add_argument("--end",   default="2026-04-30", help="結束日期 YYYY-MM-DD")
    p.add_argument("--sp3-dir",    default="data/mgex/sp3",
                   help="SP3 檔案下載目錄（多星系共用）")
    p.add_argument("--index-db",   default="data/mgex/sp3_index.duckdb",
                   help="DuckDB 索引路徑")
    p.add_argument("--export-dir", default=None,
                   help="每日 Parquet 輸出目錄（預設 data/<cname>_orbits）")
    p.add_argument("--compare-dir", default=None,
                   help="RTN 殘差輸出目錄（預設 data/<cname>_comparison）")
    p.add_argument("--space-db", default="space_db.duckdb",
                   help="TLE 來源 DuckDB")
    p.add_argument("--ac-priority", nargs="+", default=["COD", "GFZ"],
                   metavar="AC", help="AC 下載優先順序")
    p.add_argument("--skip-download", action="store_true", help="跳過 SP3 下載")
    p.add_argument("--skip-index",    action="store_true", help="跳過索引建立")
    p.add_argument("--skip-export",   action="store_true", help="跳過 Parquet 匯出")
    p.add_argument("--skip-compare",  action="store_true", help="跳過 TLE 比對")
    return p


def main() -> int:
    args = build_parser().parse_args()

    constellation = args.constellation.upper()
    cname = _CONSTELLATION_NAMES.get(constellation, constellation.lower())

    start = datetime.date.fromisoformat(args.start)
    end   = datetime.date.fromisoformat(args.end)
    sp3_dir    = Path(args.sp3_dir)
    index_db   = Path(args.index_db)
    export_dir = Path(args.export_dir) if args.export_dir else Path(f"data/{cname}_orbits")
    compare_dir = Path(args.compare_dir) if args.compare_dir else Path(f"data/{cname}_comparison")
    space_db   = Path(args.space_db)

    sp3_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_download:
        _step_download(start, end, sp3_dir, args.ac_priority)

    if not args.skip_index:
        _step_index(sp3_dir, index_db)

    if not args.skip_export:
        _step_export(start, end, index_db, export_dir, constellation)

    if not args.skip_compare:
        if not space_db.exists():
            log.error("找不到 space_db: %s", space_db)
            return 1
        compare_dir.mkdir(parents=True, exist_ok=True)
        _step_compare(start, end, export_dir, space_db, compare_dir, constellation)

    log.info("流程完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
