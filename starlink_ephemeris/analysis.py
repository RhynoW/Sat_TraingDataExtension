"""
Divergence analysis and maneuver candidate detection.

Core idea (per Liu et al. 2023 and related Starlink maneuver-detection work):
  When a satellite maneuvers, its *next* ephemeris file will predict a
  noticeably different trajectory than the previous file for the same future
  time window.  We quantify this by interpolating both ephemerides onto a
  shared time grid and taking the max position-difference norm.
  A simple median + k*MAD threshold flags statistical outliers as candidate
  maneuver days.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .models import DailyManeuverIndicator, EphemerisMetadata

# Column names used throughout
_STATE_COLS = ["r_x", "r_y", "r_z", "v_x", "v_y", "v_z"]


# ------------------------------------------------------------------
# Interpolation
# ------------------------------------------------------------------

def interpolate_state(df: pd.DataFrame, t_query: datetime) -> np.ndarray | None:
    """
    Linearly interpolate state [r_x, r_y, r_z, v_x, v_y, v_z] at t_query.

    Parameters
    ----------
    df : DataFrame with columns ['t', 'r_x', 'r_y', 'r_z', 'v_x', 'v_y', 'v_z']
         Assumed sorted by 't' ascending.
    t_query : UTC-aware datetime

    Returns
    -------
    np.ndarray of shape (6,) in km / km·s⁻¹, or None if t_query is outside range.
    """
    t_ns = int(pd.Timestamp(t_query).value)          # nanoseconds since epoch
    t_arr = df["t"].values.astype("int64")            # same unit

    if t_ns < t_arr[0] or t_ns > t_arr[-1]:
        return None

    idx = int(np.searchsorted(t_arr, t_ns))
    if idx == 0:
        return df[_STATE_COLS].iloc[0].to_numpy(dtype=float)
    if idx >= len(df):
        return df[_STATE_COLS].iloc[-1].to_numpy(dtype=float)

    t0, t1 = t_arr[idx - 1], t_arr[idx]
    w = (t_ns - t0) / (t1 - t0)                      # weight ∈ [0, 1]
    s0 = df[_STATE_COLS].iloc[idx - 1].to_numpy(dtype=float)
    s1 = df[_STATE_COLS].iloc[idx].to_numpy(dtype=float)
    return s0 + w * (s1 - s0)


# ------------------------------------------------------------------
# Divergence indicator
# ------------------------------------------------------------------

def compute_state_divergence_indicator(
    eph_old: pd.DataFrame,
    eph_new: pd.DataFrame,
    window_hours: float = 24.0,
    n_samples: int = 24,
) -> float:
    """
    Scalar indicator of how much the predicted position changed between two
    ephemeris versions of the same satellite.

    Approach
    --------
    1. Find the overlapping time window [t_start, t_end]:
       - t_start = max of each DataFrame's earliest epoch
       - t_end   = min(t_start + window_hours, end of both DataFrames)
    2. Sample n_samples equally spaced times in [t_start, t_end].
    3. For each sample, interpolate both ephemerides and compute |Δr(t)|.
    4. Return max |Δr| as the divergence indicator (km).

    Returns 0.0 if there is no usable overlapping window.
    """
    t_start = max(eph_old["t"].min(), eph_new["t"].min()).to_pydatetime()
    window_end = t_start + timedelta(hours=window_hours)
    t_end = min(
        eph_old["t"].max().to_pydatetime(),
        eph_new["t"].max().to_pydatetime(),
        window_end,
    )

    if t_start >= t_end or n_samples < 2:
        return 0.0

    dt = (t_end - t_start) / (n_samples - 1)
    sample_times = [t_start + dt * i for i in range(n_samples)]

    diffs: list[float] = []
    for t in sample_times:
        s_old = interpolate_state(eph_old, t)
        s_new = interpolate_state(eph_new, t)
        if s_old is not None and s_new is not None:
            diffs.append(float(np.linalg.norm(s_new[:3] - s_old[:3])))

    return max(diffs) if diffs else 0.0


# ------------------------------------------------------------------
# Daily indicators
# ------------------------------------------------------------------

def compute_daily_indicators(
    versions: list[tuple[EphemerisMetadata, pd.DataFrame]],
    window_hours: float = 24.0,
    n_samples: int = 24,
) -> list[DailyManeuverIndicator]:
    """
    Compute a divergence indicator for every adjacent pair of ephemeris versions.

    `versions` must already be sorted by file_start ascending.
    """
    if len(versions) < 2:
        return []

    indicators: list[DailyManeuverIndicator] = []
    n_pairs = len(versions) - 1

    for idx in range(1, len(versions)):
        meta_old, df_old = versions[idx - 1]
        meta_new, df_new = versions[idx]

        divergence = compute_state_divergence_indicator(
            df_old, df_new, window_hours=window_hours, n_samples=n_samples
        )

        print(
            f"  [{idx}/{n_pairs}] "
            f"{meta_old.file_start.date()} → {meta_new.file_start.date()}: "
            f"divergence = {divergence:.3f} km"
        )

        indicators.append(DailyManeuverIndicator(
            sat_id=meta_new.sat_id,
            day_index=idx,
            file_start_old=meta_old.file_start,
            file_start_new=meta_new.file_start,
            divergence_km=divergence,
        ))

    return indicators


# ------------------------------------------------------------------
# Flagging
# ------------------------------------------------------------------

def flag_maneuver_candidates(
    indicators: list[DailyManeuverIndicator],
    k: float = 5.0,
    min_threshold_km: float = 1.0,
) -> list[DailyManeuverIndicator]:
    """
    Flag candidate maneuver days using a median + k*MAD outlier test.

    A day is flagged when: divergence_km > max(median + k*MAD, min_threshold_km)

    MAD = median absolute deviation; robust to the very outliers we detect.
    `min_threshold_km` guards against numerical noise when MAD collapses to
    zero (e.g. perfectly deterministic synthetic data or identical propagators).
    k=5 is conservative; lower k catches subtler maneuvers.
    """
    if not indicators:
        return indicators

    values = np.array([ind.divergence_km for ind in indicators])
    median_d = float(np.median(values))
    mad_d = float(np.median(np.abs(values - median_d)))
    threshold = max(median_d + k * mad_d, min_threshold_km)

    print(
        f"\n[flag] median={median_d:.3f} km  MAD={mad_d:.3f} km  "
        f"threshold={threshold:.3f} km  (k={k}, floor={min_threshold_km} km)"
    )

    for ind in indicators:
        ind.is_candidate_maneuver = bool(ind.divergence_km > threshold)

    n_flagged = sum(1 for ind in indicators if ind.is_candidate_maneuver)
    print(f"[flag] {n_flagged} candidate maneuver day(s) flagged out of {len(indicators)}")
    return indicators
