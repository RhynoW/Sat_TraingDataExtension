"""
Daily Starlink ephemeris download runner.

Usage
-----
    python download_daily.py                         # defaults
    python download_daily.py --workers 8 --delay 0.05
    python download_daily.py --catalog custom.csv --data-root /mnt/data

Schedule with cron (Linux/macOS)
    0 23 * * * cd /path/to/repo && python download_daily.py >> logs/daily.log 2>&1

Schedule with Task Scheduler (Windows)
    schtasks /create /tn "Starlink-Ephemeris-Daily" ^
             /tr "python C:\\path\\to\\download_daily.py" ^
             /sc daily /st 07:00

Output
------
- Downloaded files: data/raw/{sat_id}/{file_start_iso}.txt
- Registry (updated): data/url_registry.csv
- Run summary CSV: data/logs/download_log_{YYYY-MM-DD}.csv
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from starlink_ephemeris.downloader import run_daily_batch, seed_from_manifest

# ── logging setup ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    stream=sys.stdout,
)
logger = logging.getLogger("download_daily")


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Download daily Starlink ephemeris files for the satellite catalog."
    )
    p.add_argument(
        "--catalog", type=Path, default=Path("starlink_satellites.csv"),
        help="Path to the satellite catalog CSV (default: starlink_satellites.csv)",
    )
    p.add_argument(
        "--data-root", type=Path, default=Path("data"),
        help="Root directory for downloaded files (default: data/)",
    )
    p.add_argument(
        "--registry", type=Path, default=None,
        help="URL registry CSV (default: {data-root}/url_registry.csv)",
    )
    p.add_argument(
        "--workers", type=int, default=4,
        help="Parallel download threads (default: 4).",
    )
    p.add_argument(
        "--delay", type=float, default=0.05,
        help="Per-thread inter-request delay in seconds (default: 0.05).",
    )
    p.add_argument(
        "--download-timeout", type=int, default=60,
        help="HTTP timeout per file download (default: 60 s).",
    )
    p.add_argument(
        "--skip-manifest", action="store_true",
        help="Skip the MANIFEST.txt refresh step.",
    )
    p.add_argument(
        "--no-log-csv", action="store_true",
        help="Skip writing the per-run CSV log.",
    )
    return p


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    args = build_parser().parse_args()

    registry_csv = args.registry or (args.data_root / "url_registry.csv")

    run_start = datetime.now(tz=timezone.utc)
    logger.info(
        "=== Daily batch start  catalog=%s  data_root=%s  workers=%d ===",
        args.catalog, args.data_root, args.workers,
    )

    if not args.catalog.exists():
        logger.error(
            "Catalog not found: %s\nRun 'python generate_catalog.py' first.",
            args.catalog,
        )
        return 1

    # ── step 1: refresh registry from manifest ────────────────────────────────
    if not args.skip_manifest:
        logger.info("Refreshing catalog + registry from MANIFEST.txt …")
        try:
            seeded = seed_from_manifest(
                catalog_csv=args.catalog,
                registry_csv=registry_csv,
            )
            logger.info("Manifest refresh complete — %d new/updated entries.", len(seeded))
        except Exception as exc:
            logger.warning("Manifest refresh failed (%s) — continuing with existing registry.", exc)

    # ── step 2: batch download ────────────────────────────────────────────────
    results: pd.DataFrame = run_daily_batch(
        catalog_csv=args.catalog,
        data_root=args.data_root,
        registry_csv=registry_csv,
        download_timeout=args.download_timeout,
        max_workers=args.workers,
        inter_request_delay_s=args.delay,
    )

    run_end = datetime.now(tz=timezone.utc)
    elapsed = (run_end - run_start).total_seconds()
    logger.info("=== Daily batch complete  elapsed=%.1f s ===", elapsed)

    # ── step 3: save per-run log ──────────────────────────────────────────────
    if not args.no_log_csv:
        log_dir = args.data_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        date_tag = run_start.strftime("%Y-%m-%d")
        log_path = log_dir / f"download_log_{date_tag}.csv"
        results.to_csv(log_path, index=False)
        logger.info("Run log saved → %s", log_path)

    # ── step 4: print batch summary ───────────────────────────────────────────
    print("\n--- Batch summary ---")
    summary = (
        results.groupby(["mission_batch", "status"])
        .size()
        .unstack(fill_value=0)
    )
    print(summary.to_string())

    errors = results[results["status"] == "error"]
    if not errors.empty:
        print("\n--- Errors ---")
        print(errors[["norad_id", "mission_batch", "error"]].to_string(index=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
