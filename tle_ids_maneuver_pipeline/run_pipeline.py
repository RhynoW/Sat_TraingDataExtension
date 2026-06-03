from __future__ import annotations

"""
run_pipeline.py
───────────────
Orchestrates the full TLE vs IDS maneuver detection pipeline.

Usage:
  python run_pipeline.py --config config.yaml --satellite jason-3
  python run_pipeline.py --config config.yaml --satellite jason-3 --start 2024-01-01T00:00:00Z --end 2024-03-31T23:59:59Z
  python run_pipeline.py --config config.yaml --all       # run all IDS satellites
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import pandas as pd

from utils import load_config, ensure_dir


def _load_dotenv(dotenv_path: Path) -> None:
    """Load key=value pairs from a .env file into os.environ (skip already-set vars)."""
    if not dotenv_path.exists():
        return
    with open(dotenv_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = val


# Load .env from the project root (parent of this pipeline directory)
_load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from ingest_ilrs import fetch_ilrs_satellites
from download_ids import download_ids_products, load_ids_states
from compare_residuals import run_compare
from detect_maneuver import detect_candidates, save_candidates

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)s  %(message)s')


def run_one(config_path: str, satellite: str, start: str | None, end: str | None, force: bool):
    cfg = load_config(config_path)
    out_dir = cfg['project']['output_dir']
    ids_cfg = cfg['ids']
    sat_code = ids_cfg['satellite_code_map'].get(satellite)
    if not sat_code:
        log.error(f'No satellite_code_map entry for "{satellite}". Check config.yaml.')
        return

    log.info(f'=== Processing {satellite} (code: {sat_code}) ===')

    # Step 1 – Download IDS products
    sp3_paths = download_ids_products(config_path, satellite, start=start, end=end, force=force)
    if not sp3_paths:
        log.error(f'No SP3 files downloaded for {satellite}. Cannot continue.')
        return

    # Step 2 – Parse IDS states
    ids_states = load_ids_states(sp3_paths, sat_code)
    if ids_states.empty:
        log.error(f'IDS SP3 files parse to empty DataFrame for sat_code={sat_code}.')
        return
    log.info(f'IDS states: {len(ids_states)} epochs,  '
             f'{ids_states["epoch"].min()} – {ids_states["epoch"].max()}')

    # Step 3 – Compute residuals
    residuals = run_compare(config_path, satellite, ids_states)
    log.info(f'Residuals: {len(residuals)} points.  '
             f'Mean |dr| = {residuals["dr_km"].mean():.3f} km,  '
             f'Max |dr| = {residuals["dr_km"].max():.3f} km')

    # Step 4 – Detect maneuver candidates
    candidates = detect_candidates(residuals, config_path)
    save_candidates(candidates, out_dir, satellite)

    if candidates.empty:
        log.info('No maneuver candidates detected in this window.')
    else:
        log.info(f'Detected {len(candidates)} maneuver candidate cluster(s):')
        for _, row in candidates.iterrows():
            log.info(
                f"  Cluster | Start: {row['start_epoch']} | End: {row['end_epoch']} | "
                f"Peak dr: {row['peak_dr_km']:.3f} km | "
                f"In-track: {row['peak_abs_in_track_km']:.3f} km | "
                f"n_pts: {row['n_points']}"
            )

    # Step 5 – Save summary
    summary = {
        'satellite': satellite,
        'sat_code': sat_code,
        'ids_epochs': len(ids_states),
        'residual_points': len(residuals),
        'mean_dr_km': round(residuals['dr_km'].mean(), 4),
        'max_dr_km': round(residuals['dr_km'].max(), 4),
        'maneuver_candidates': len(candidates),
    }
    summary_path = Path(out_dir) / 'candidates' / satellite / 'summary.csv'
    pd.DataFrame([summary]).to_csv(summary_path, index=False)
    log.info(f'Summary written to {summary_path}')
    return candidates


def main():
    ap = argparse.ArgumentParser(description='TLE vs IDS Maneuver Detection Pipeline')
    ap.add_argument('--config',    required=True,       help='Path to config.yaml')
    ap.add_argument('--satellite', default=None,        help='Satellite name, e.g. jason-3')
    ap.add_argument('--all',       action='store_true', help='Run all satellites on ILRS maneuver page')
    ap.add_argument('--start',     default=None,        help='Override analysis start (ISO8601 UTC)')
    ap.add_argument('--end',       default=None,        help='Override analysis end   (ISO8601 UTC)')
    ap.add_argument('--force',     action='store_true', help='Force re-download of SP3 files')
    args = ap.parse_args()

    cfg = load_config(args.config)
    ensure_dir(cfg['project']['output_dir'])

    # Resolve satellite list
    if args.all:
        ilrs_df = fetch_ilrs_satellites(args.config)
        sat_list = list(ilrs_df['satellite'])
        log.info(f'Running all {len(sat_list)} ILRS maneuver satellites.')
    elif args.satellite:
        sat_list = [args.satellite]
    else:
        ap.error('Specify --satellite <name> or --all')

    # Filter to satellites present in config satellite_code_map
    known = set(cfg['ids']['satellite_code_map'])
    sat_list = [s for s in sat_list if s in known]
    unknown  = [s for s in sat_list if s not in known]
    if unknown:
        log.warning(f'Skipping (no code mapping): {unknown}')

    all_results = []
    for sat in sat_list:
        try:
            cands = run_one(args.config, sat, args.start, args.end, args.force)
            if cands is not None:
                all_results.append(cands.assign(satellite=sat))
        except Exception as e:
            log.error(f'Failed for {sat}: {e}', exc_info=True)

    if all_results:
        combined = pd.concat(all_results, ignore_index=True)
        out_path = Path(cfg['project']['output_dir']) / 'all_maneuver_candidates.csv'
        combined.to_csv(out_path, index=False)
        log.info(f'Combined results: {out_path}  ({len(combined)} total candidates)')


if __name__ == '__main__':
    main()
