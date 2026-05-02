"""High-level pipeline API: load → compute → flag → return tidy DataFrame."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .analysis import compute_daily_indicators, flag_maneuver_candidates
from .storage import load_all_ephemerides


def analyze_satellite_maneuvers(
    sat_id: str,
    data_root: Path,
    divergence_window_hours: float = 24.0,
    divergence_n_samples: int = 24,
    maneuver_threshold_k: float = 5.0,
) -> pd.DataFrame:
    """
    Full analysis pipeline for a single satellite.

    Steps
    -----
    1. Load every stored ephemeris file for `sat_id` from
       ``data_root/raw/{sat_id}/``.
    2. Sort versions by ``file_start`` ascending.
    3. Compute pairwise divergence indicators between adjacent versions.
    4. Flag outlier days as candidate maneuver events.

    Parameters
    ----------
    sat_id : str
        Satellite identifier, e.g. "STARLINK-32283".
    data_root : Path
        Root of the local data store.
    divergence_window_hours : float
        How many hours of the overlapping time window to use for comparison.
    divergence_n_samples : int
        Number of equally spaced sample points in that window.
    maneuver_threshold_k : float
        Multiplier on MAD for the outlier threshold (default 5 = conservative).

    Returns
    -------
    pd.DataFrame with UTC-aware datetime columns:
        file_start_old, file_start_new, divergence_km, is_candidate_maneuver
    Returns an empty DataFrame (with those columns) if fewer than 2 versions
    are available.
    """
    _empty = pd.DataFrame(
        columns=["file_start_old", "file_start_new", "divergence_km", "is_candidate_maneuver"]
    )

    print(f"\n=== analyze_satellite_maneuvers: {sat_id} ===")
    versions = load_all_ephemerides(sat_id, data_root)

    if len(versions) < 2:
        print(f"  Need ≥ 2 versions, found {len(versions)}. Returning empty result.")
        return _empty

    indicators = compute_daily_indicators(
        versions,
        window_hours=divergence_window_hours,
        n_samples=divergence_n_samples,
    )
    indicators = flag_maneuver_candidates(indicators, k=maneuver_threshold_k)

    rows = [
        {
            "file_start_old":         ind.file_start_old,
            "file_start_new":         ind.file_start_new,
            "divergence_km":          ind.divergence_km,
            "is_candidate_maneuver":  ind.is_candidate_maneuver,
        }
        for ind in indicators
    ]

    df = pd.DataFrame(rows)
    if not df.empty:
        df["file_start_old"] = pd.to_datetime(df["file_start_old"], utc=True)
        df["file_start_new"] = pd.to_datetime(df["file_start_new"], utc=True)

    return df
