"""
mgex_galileo command-line interface.

Usage
-----
Download SP3 files::

    python -m mgex_galileo.cli download \\
        --start 2023-01-01 --end 2023-01-07 \\
        --out-dir data/mgex/sp3 \\
        --ac-priority COD GFZ

Build / update index::

    python -m mgex_galileo.cli index \\
        --sp3-root data/mgex/sp3 \\
        --db data/mgex/sp3_index.duckdb

Parse and dump one day to Parquet::

    python -m mgex_galileo.cli dump-day \\
        --date 2023-01-01 \\
        --db data/mgex/sp3_index.duckdb \\
        --out data/mgex/galileo_orbits_2023-01-01.parquet
"""
from __future__ import annotations

import argparse
import datetime
import logging
import sys
from pathlib import Path

import pandas as pd


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
        level=level,
    )


# ── Sub-command: download ──────────────────────────────────────────────────────

def cmd_download(args: argparse.Namespace) -> int:
    from .download import download_galileo_sp3

    start = datetime.date.fromisoformat(args.start)
    end = datetime.date.fromisoformat(args.end)
    out_dir = Path(args.out_dir)
    acs = args.ac_priority or None

    print(f"[download] {start} → {end}  ACs={acs or 'default'}  out={out_dir}")
    paths = download_galileo_sp3(start, end, out_dir, ac_priority=acs,
                                  use_gnss_lib_py=args.use_gnss_lib_py)
    print(f"[download] Done — {len(paths)} file(s) ready.")
    return 0


# ── Sub-command: index ─────────────────────────────────────────────────────────

def cmd_index(args: argparse.Namespace) -> int:
    from .index import build_sp3_index

    sp3_root = Path(args.sp3_root)
    db_path = Path(args.db)

    patterns = ["**/*.sp3", "**/*.SP3", "**/*.eph", "**/*.EPH"]
    sp3_files: list[Path] = []
    for pat in patterns:
        sp3_files.extend(sp3_root.glob(pat))
    sp3_files = sorted(set(sp3_files))

    if not sp3_files:
        print(f"[index] No SP3 files found under {sp3_root}")
        return 1

    print(f"[index] Found {len(sp3_files)} file(s) under {sp3_root}")
    build_sp3_index(sp3_files, db_path)
    return 0


# ── Sub-command: dump-day ──────────────────────────────────────────────────────

def cmd_dump_day(args: argparse.Namespace) -> int:
    from .index import query_sp3_files_for_interval
    from .sp3_parser import parse_sp3_galileo

    day = datetime.date.fromisoformat(args.date)
    db_path = Path(args.db)
    out_path = Path(args.out)

    t_start = pd.Timestamp(day, tz="UTC")
    t_end = pd.Timestamp(day) + pd.Timedelta(hours=23, minutes=59, seconds=59)
    t_end = t_end.tz_localize("UTC")

    files = query_sp3_files_for_interval(db_path, t_start, t_end, require_galileo=True)
    if not files:
        print(f"[dump-day] No indexed SP3 files cover {day} — run 'index' first.")
        return 1

    print(f"[dump-day] {len(files)} SP3 file(s) cover {day}")
    frames: list[pd.DataFrame] = []
    for f in files:
        print(f"  parsing {f.name} …")
        df = parse_sp3_galileo(f)
        if not df.empty:
            # Keep only epochs within [t_start, t_end]
            mask = (df["t_gps"] >= t_start) & (df["t_gps"] <= t_end)
            frames.append(df[mask])

    if not frames:
        print("[dump-day] No Galileo data found in those files.")
        return 1

    result = pd.concat(frames, ignore_index=True)
    result = result.sort_values(["sat_id", "t_gps"]).reset_index(drop=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix == ".parquet":
        result.to_parquet(out_path, index=False)
    else:
        result.to_csv(out_path, index=False)

    n_sats = result["sat_id"].nunique()
    n_epochs = result["t_gps"].nunique()
    print(
        f"[dump-day] {len(result)} rows  "
        f"({n_sats} satellites, {n_epochs} epochs) → {out_path}"
    )
    return 0


# ── Parser ─────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m mgex_galileo.cli",
        description="Download and process MGEX Galileo SP3 precise ephemerides.",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    sub = p.add_subparsers(dest="command", required=True)

    # download
    dl = sub.add_parser("download", help="Fetch SP3 files from MGEX servers")
    dl.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    dl.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    dl.add_argument("--out-dir", required=True, help="Output directory for SP3 files")
    dl.add_argument(
        "--ac-priority", nargs="+", metavar="AC",
        help="AC codes in preference order (default: COD GFZ)"
    )
    dl.add_argument(
        "--use-gnss-lib-py", action="store_true",
        help="Use gnss_lib_py downloader instead of built-in HTTP fetch"
    )

    # index
    idx = sub.add_parser("index", help="Build/update DuckDB index of local SP3 files")
    idx.add_argument("--sp3-root", required=True, help="Root directory to scan for SP3 files")
    idx.add_argument("--db", required=True, help="DuckDB index file path")

    # dump-day
    dd = sub.add_parser("dump-day", help="Export one day of Galileo orbits to Parquet/CSV")
    dd.add_argument("--date", required=True, help="Date YYYY-MM-DD")
    dd.add_argument("--db", required=True, help="DuckDB index file")
    dd.add_argument("--out", required=True, help="Output file (.parquet or .csv)")

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    dispatch = {
        "download": cmd_download,
        "index": cmd_index,
        "dump-day": cmd_dump_day,
    }
    rc = dispatch[args.command](args)
    sys.exit(rc)


if __name__ == "__main__":
    main()
