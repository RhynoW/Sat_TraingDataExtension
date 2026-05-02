"""
Starlink ephemeris maneuver-detection pipeline — example usage.

Quick-start (two modes)
-----------------------
1. Dry-run with synthetic data (no Internet required):
       python main.py --demo

2. Real data (Internet + valid Starlink ephemeris URLs):
       python main.py

Configuration
-------------
Edit the constants below, or adapt them into a config file / CLI parser.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from starlink_ephemeris import (
    analyze_satellite_maneuvers,
    download_batch,
    download_ephemeris,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_ROOT = Path("data")
SAT_ID = "STARLINK-32283"
TOP_N = 5

# List of Starlink ephemeris URLs to download (one per day, same satellite).
# Replace with real URLs from the Starlink public ephemeris API.
EXAMPLE_URLS: list[str] = [
    "https://api.starlink.com/public-files/ephemerides/"
    "MEME_62425_STARLINK-32283_1212137_Operational_1461965880_UNCLASSIFIED.txt",
    # Add more daily URLs here …
]


# ---------------------------------------------------------------------------
# Synthetic demo helper
# ---------------------------------------------------------------------------

_MU = 398600.4418  # km³/s²


def _deriv(state: np.ndarray) -> np.ndarray:
    """Two-body equation of motion: d/dt [r; v] = [v; -MU/|r|³ * r]."""
    r, v = state[:3], state[3:]
    a = -_MU / np.linalg.norm(r) ** 3 * r
    return np.concatenate([v, a])


def _rk4_step(r: np.ndarray, v: np.ndarray, dt: float, n_sub: int = 20) -> tuple[np.ndarray, np.ndarray]:
    """Advance a 2-body state by dt seconds using RK4 with n_sub sub-steps."""
    h = dt / n_sub
    state = np.concatenate([r, v])
    for _ in range(n_sub):
        k1 = _deriv(state)
        k2 = _deriv(state + 0.5 * h * k1)
        k3 = _deriv(state + 0.5 * h * k2)
        k4 = _deriv(state + h * k3)
        state += (h / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
    return state[:3].copy(), state[3:].copy()


def _fmt_itc(dt: datetime) -> str:
    """Format a datetime as a Modified ITC timestamp string."""
    doy = dt.timetuple().tm_yday
    ms = dt.microsecond // 1000
    return f"{dt.year}{doy:03d}{dt.hour:02d}{dt.minute:02d}{dt.second:02d}.{ms:03d}"


def _fmt_ccsds(dt: datetime) -> str:
    doy = dt.timetuple().tm_yday
    return f"{dt.year}-{doy:03d}T{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}.000"


def _propagate_to(
    r0: np.ndarray,
    v0: np.ndarray,
    dt_total_s: float,
    step_s: float = 300.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Propagate state (r0, v0) forward by dt_total_s seconds in step_s chunks."""
    r, v = r0.copy(), v0.copy()
    n = max(1, int(round(dt_total_s / step_s)))
    h = dt_total_s / n
    for _ in range(n):
        r, v = _rk4_step(r, v, h)
    return r, v


def _write_synthetic_ephemeris(
    path: Path,
    sat_name: str,
    file_epoch: datetime,
    r_init: np.ndarray,
    v_init: np.ndarray,
    *,
    duration_hours: float = 72.0,
    step_minutes: float = 5.0,
) -> None:
    """
    Write a synthetic Modified ITC ephemeris file starting from (r_init, v_init).

    Propagates forward from file_epoch using 2-body RK4 dynamics.
    The caller is responsible for providing the correct physical state at
    file_epoch, including any delta-v already applied at that point.
    """
    step_s = step_minutes * 60.0
    n_steps = int(duration_hours * 60 / step_minutes) + 1
    stop_dt = file_epoch + timedelta(hours=duration_hours)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        fh.write("CCSDS_OEM_VERS = 2.0\n")
        fh.write(f"OBJECT_NAME = {sat_name}\n")
        fh.write("CENTER_NAME = EARTH\n")
        fh.write("REF_FRAME = EME2000\n")
        fh.write("TIME_SYSTEM = UTC\n")
        fh.write(f"START_TIME = {_fmt_ccsds(file_epoch)}\n")
        fh.write(f"STOP_TIME  = {_fmt_ccsds(stop_dt)}\n\n")

        r, v = r_init.copy(), v_init.copy()
        for i in range(n_steps):
            t = file_epoch + timedelta(seconds=step_s * i)
            ts = _fmt_itc(t)
            fh.write(
                f"{ts}  {r[0]:.6f}  {r[1]:.6f}  {r[2]:.6f}"
                f"  {v[0]:.9f}  {v[1]:.9f}  {v[2]:.9f}\n"
            )
            for _ in range(3):
                fh.write("  ".join(f"{1e-9:.6e}" for _ in range(7)) + "\n")
            if i < n_steps - 1:
                r, v = _rk4_step(r, v, step_s)


def run_demo(data_root: Path, sat_id: str = "STARLINK-DEMO") -> pd.DataFrame:
    """
    Create synthetic daily ephemeris files and run the full pipeline.

    Design
    ------
    - Days 0–1: satellite on the reference circular orbit.
    - Day 2 (maneuver day): the day-2 file starts from the physical state at
      that epoch PLUS a 50 m/s prograde delta-v. It therefore predicts a
      different (higher) orbit going forward.
    - Days 3–4: files start from the *post-maneuver* physical state, so they
      agree with the day-2 prediction in their overlap window.

    Expected pipeline output: only the day-1 → day-2 pair shows a large
    divergence (~hundreds of km after 24 h) and gets flagged.
    """
    print("\n[demo] Generating synthetic ephemeris files …")

    R0 = 6928.0                             # km  (≈ 550 km altitude)
    V0 = float(np.sqrt(_MU / R0))          # km/s  ≈ 7.6

    ref_epoch = datetime(2024, 1, 1, tzinfo=timezone.utc)
    r_ref = np.array([R0, 0.0, 0.0])
    v_ref = np.array([0.0, V0, 0.0])

    maneuver_day_idx = 2        # the file for day 2 reflects post-maneuver state
    dv_magnitude     = 0.05     # km/s  prograde (~50 m/s, realistic Starlink raise)

    # Pre-compute the post-maneuver state at the maneuver epoch so that
    # all subsequent files are consistent with it.
    maneuver_epoch = ref_epoch + timedelta(days=maneuver_day_idx)
    r_man, v_man = _propagate_to(r_ref, v_ref, (maneuver_epoch - ref_epoch).total_seconds())
    v_hat = v_man / np.linalg.norm(v_man)
    r_post_man = r_man.copy()
    v_post_man = v_man + dv_magnitude * v_hat

    for day in range(6):
        file_epoch = ref_epoch + timedelta(days=day)
        fname = f"synthetic_day{day:02d}.txt"
        path = data_root / "raw" / sat_id / fname

        dt_s = (file_epoch - ref_epoch).total_seconds()

        if day < maneuver_day_idx:
            # Pre-maneuver: propagate along the reference orbit
            r_init, v_init = _propagate_to(r_ref, v_ref, dt_s)
            tag = ""
        elif day == maneuver_day_idx:
            # This file represents the satellite AFTER the maneuver
            r_init, v_init = r_post_man.copy(), v_post_man.copy()
            tag = " ← MANEUVER (day-2 file starts from post-Δv state)"
        else:
            # Post-maneuver: propagate from the post-maneuver state
            dt_post = (file_epoch - maneuver_epoch).total_seconds()
            r_init, v_init = _propagate_to(r_post_man, v_post_man, dt_post)
            tag = " (post-maneuver orbit)"

        _write_synthetic_ephemeris(
            path, sat_id, file_epoch, r_init, v_init,
            duration_hours=72.0, step_minutes=5.0,
        )
        print(f"  day {day}: {path.name}{tag}")

    return analyze_satellite_maneuvers(sat_id, data_root)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Starlink maneuver detection pipeline")
    parser.add_argument(
        "--demo", action="store_true",
        help="Run with synthetic data (no Internet required)."
    )
    parser.add_argument(
        "--download", action="store_true",
        help="Download EXAMPLE_URLS before running analysis."
    )
    parser.add_argument(
        "--sat-id", default=SAT_ID,
        help=f"Satellite ID to analyse (default: {SAT_ID})."
    )
    parser.add_argument(
        "--data-root", type=Path, default=DATA_ROOT,
        help=f"Root directory for local data store (default: {DATA_ROOT})."
    )
    parser.add_argument(
        "--top-n", type=int, default=TOP_N,
        help=f"Number of top divergence days to print (default: {TOP_N})."
    )
    parser.add_argument(
        "--threshold-k", type=float, default=5.0,
        help="MAD multiplier for maneuver flagging (default: 5)."
    )
    args = parser.parse_args()

    data_root: Path = args.data_root
    sat_id: str = args.sat_id

    # --- Demo mode ---
    if args.demo:
        results = run_demo(data_root, sat_id="STARLINK-DEMO")

    else:
        # --- Optional download ---
        if args.download:
            print(f"\n[download] Fetching {len(EXAMPLE_URLS)} URL(s) …")
            download_batch(EXAMPLE_URLS, data_root)

        results = analyze_satellite_maneuvers(
            sat_id,
            data_root,
            maneuver_threshold_k=args.threshold_k,
        )

    # --- Print results ---
    if results.empty:
        print("\nNo results. Ensure at least 2 ephemeris files are stored, or use --demo.")
        return

    print("\n--- Full divergence table ---")
    print(results.to_string(index=False))

    print(f"\n--- Top {args.top_n} days by divergence ---")
    top = results.nlargest(args.top_n, "divergence_km")
    print(top[["file_start_new", "divergence_km", "is_candidate_maneuver"]].to_string(index=False))

    n_flagged = int(results["is_candidate_maneuver"].sum())
    print(f"\nCandidate maneuver days: {n_flagged} of {len(results)}")

    # --- Save CSV ---
    out_dir = data_root
    out_dir.mkdir(parents=True, exist_ok=True)
    used_id = "STARLINK-DEMO" if args.demo else sat_id
    csv_path = out_dir / f"{used_id}_maneuver_analysis.csv"
    results.to_csv(csv_path, index=False)
    print(f"\nResults saved → {csv_path}")


if __name__ == "__main__":
    main()
