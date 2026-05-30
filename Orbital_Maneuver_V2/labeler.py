"""
labeler.py
==========
Assign maneuver labels to TLE epochs using MEME residuals as ground truth.

Label scheme
------------
LABEL_NOMINAL     = 0   — confirmed quiet (valid_for_training, no nearby event)
LABEL_MANEUVERING = 1   — within ±24 h of a detected MEME maneuver event
LABEL_EXCLUDED    = -1  — Mode A divergence or ambiguous — drop from training

Residual CSV schema (produced by compare_tle_vs_ephemeris.py with --residuals):
    norad_id, sat_name, t, pos_err_km, dr_r_km, dr_t_km, dr_n_km,
    tle_age_days, valid_for_training
"""
from __future__ import annotations

import glob
import logging
from typing import Optional

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# ── label constants ───────────────────────────────────────────────────────────
LABEL_NOMINAL     =  0
LABEL_MANEUVERING =  1
LABEL_EXCLUDED    = -1

# ── detection thresholds ──────────────────────────────────────────────────────
MEME_EVENT_WINDOW_H   = 24.0    # ±24 h around a MEME maneuver peak
MODE_A_POS_THRESHOLD  = 500.0   # km  — persistent divergence threshold
MODE_A_MONOTONE_FRAC  = 0.80    # fraction of consecutive diffs > 0 required

# Internal event-detection thresholds
_PEAK_THRESHOLD_KM    = 50.0    # km  — pos_err_km must exceed to be a candidate peak
_RECOVERY_THRESHOLD_KM = 20.0   # km  — pos_err_km must fall below after peak

# Columns expected / produced
_RESIDUAL_COLS = [
    "norad_id", "sat_name", "t",
    "pos_err_km", "dr_r_km", "dr_t_km", "dr_n_km",
    "tle_age_days", "valid_for_training",
]
_EVENT_COLS = [
    "norad_id", "event_peak_t", "event_start_t", "event_end_t", "peak_pos_err_km",
]
_MODE_A_COLS = [
    "norad_id", "window_start_t", "window_end_t",
]


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def load_residuals(residuals_glob: str) -> pd.DataFrame:
    """
    Load MEME residual CSV files matching a glob pattern.

    Parameters
    ----------
    residuals_glob : glob pattern, e.g. "data/comparison/residuals_*.csv"

    Returns
    -------
    Concatenated DataFrame with columns defined in _RESIDUAL_COLS.
    `t` and `tle_epoch` (if present) are parsed as UTC-aware datetimes.
    Returns an empty DataFrame with correct columns when no files match.
    """
    paths = glob.glob(residuals_glob)
    if not paths:
        log.warning("load_residuals: no files matched pattern '%s'", residuals_glob)
        return _empty(_RESIDUAL_COLS)

    frames: list[pd.DataFrame] = []
    for path in sorted(paths):
        try:
            df = pd.read_csv(path, low_memory=False)
        except Exception:
            log.exception("load_residuals: failed to read '%s'", path)
            continue

        # Parse time columns
        for col in ("t", "tle_epoch"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")

        # Coerce numeric columns
        for col in ("pos_err_km", "dr_r_km", "dr_t_km", "dr_n_km", "tle_age_days"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Coerce boolean
        if "valid_for_training" in df.columns:
            df["valid_for_training"] = df["valid_for_training"].astype(bool)

        frames.append(df)

    if not frames:
        return _empty(_RESIDUAL_COLS)

    combined = pd.concat(frames, ignore_index=True)

    # Keep only columns we care about (extra columns are ignored)
    keep = [c for c in _RESIDUAL_COLS if c in combined.columns]
    combined = combined[keep].copy()

    log.info(
        "load_residuals: loaded %d rows from %d file(s)",
        len(combined), len(frames),
    )
    return combined


def detect_meme_events(res_df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect Mode B maneuver events per satellite from MEME residuals.

    A maneuver event is a V-shape in pos_err_km:
      - pos_err_km rises above _PEAK_THRESHOLD_KM (50 km)
      - reaches a local maximum (peak)
      - then falls back below _RECOVERY_THRESHOLD_KM (20 km)

    For each qualifying peak the event window is:
      event_start_t : last time pos_err_km < _PEAK_THRESHOLD_KM before the peak
      event_peak_t  : time of maximum pos_err_km
      event_end_t   : first time pos_err_km < _RECOVERY_THRESHOLD_KM after the peak

    Parameters
    ----------
    res_df : residuals DataFrame as returned by load_residuals

    Returns
    -------
    DataFrame with columns: norad_id, event_peak_t, event_start_t,
                            event_end_t, peak_pos_err_km
    """
    if res_df.empty or "pos_err_km" not in res_df.columns:
        return _empty(_EVENT_COLS)

    all_events: list[dict] = []

    for norad_id, grp in res_df.groupby("norad_id"):
        grp = grp.sort_values("t").reset_index(drop=True)
        pos = grp["pos_err_km"].values
        times = grp["t"].values   # numpy datetime64

        n = len(pos)
        if n < 3:
            continue

        above_mask = pos > _PEAK_THRESHOLD_KM

        # Walk forward: find contiguous "above-threshold" windows
        i = 0
        while i < n:
            if not above_mask[i]:
                i += 1
                continue

            # Start of an above-threshold window
            win_start = i

            # Find end of the above-threshold window
            j = i
            while j < n and above_mask[j]:
                j += 1
            win_end = j - 1   # last index still above threshold

            # Peak within the window
            peak_idx = win_start + int(np.argmax(pos[win_start: win_end + 1]))
            peak_val = pos[peak_idx]

            if peak_val < _PEAK_THRESHOLD_KM:
                i = j
                continue

            # event_start_t: last point BEFORE win_start that was below threshold
            if win_start == 0:
                event_start_t = times[0]
            else:
                event_start_t = times[win_start - 1]

            # event_end_t: first point AFTER peak that falls below recovery threshold
            event_end_t = times[win_end]  # fallback: end of above-threshold window
            for k in range(peak_idx + 1, n):
                if pos[k] < _RECOVERY_THRESHOLD_KM:
                    event_end_t = times[k]
                    break

            all_events.append({
                "norad_id":        int(norad_id),
                "event_peak_t":    pd.Timestamp(times[peak_idx]),
                "event_start_t":   pd.Timestamp(event_start_t),
                "event_end_t":     pd.Timestamp(event_end_t),
                "peak_pos_err_km": float(peak_val),
            })

            i = j  # advance past this window

    if not all_events:
        return _empty(_EVENT_COLS)

    out = pd.DataFrame(all_events)

    # Ensure timezone-aware timestamps
    for col in ("event_peak_t", "event_start_t", "event_end_t"):
        out[col] = pd.to_datetime(out[col], utc=True)

    log.info("detect_meme_events: found %d maneuver events", len(out))
    return out.reset_index(drop=True)


def detect_mode_a(res_df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect Mode A (persistent divergence) windows per satellite.

    A Mode A window is a contiguous run where pos_err_km > MODE_A_POS_THRESHOLD
    AND at least MODE_A_MONOTONE_FRAC of consecutive diffs within the run are
    positive (monotonically increasing majority).

    TLE epochs that fall inside any Mode A window should be excluded from
    training (label = LABEL_EXCLUDED).

    Parameters
    ----------
    res_df : residuals DataFrame as returned by load_residuals

    Returns
    -------
    DataFrame with columns: norad_id, window_start_t, window_end_t
    """
    if res_df.empty or "pos_err_km" not in res_df.columns:
        return _empty(_MODE_A_COLS)

    all_windows: list[dict] = []

    for norad_id, grp in res_df.groupby("norad_id"):
        grp = grp.sort_values("t").reset_index(drop=True)
        pos   = grp["pos_err_km"].values.astype(float)
        times = grp["t"].values

        n = len(pos)
        above_mask = pos > MODE_A_POS_THRESHOLD

        i = 0
        while i < n:
            if not above_mask[i]:
                i += 1
                continue

            # Start of an above-threshold run
            win_start = i
            j = i
            while j < n and above_mask[j]:
                j += 1
            win_end = j - 1   # inclusive

            # Check monotone fraction within this run
            run_pos = pos[win_start: win_end + 1]
            if len(run_pos) >= 2:
                diffs = np.diff(run_pos)
                monotone_frac = float((diffs > 0).sum()) / len(diffs)
            else:
                # Single point: cannot be monotone by definition — skip
                i = j
                continue

            if monotone_frac >= MODE_A_MONOTONE_FRAC:
                all_windows.append({
                    "norad_id":       int(norad_id),
                    "window_start_t": pd.Timestamp(times[win_start]),
                    "window_end_t":   pd.Timestamp(times[win_end]),
                })

            i = j

    if not all_windows:
        return _empty(_MODE_A_COLS)

    out = pd.DataFrame(all_windows)
    for col in ("window_start_t", "window_end_t"):
        out[col] = pd.to_datetime(out[col], utc=True)

    log.info("detect_mode_a: found %d Mode A exclusion window(s)", len(out))
    return out.reset_index(drop=True)


def assign_labels(
    tle_epochs_df: pd.DataFrame,
    res_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Assign maneuver labels to TLE epochs using MEME residuals as ground truth.

    Parameters
    ----------
    tle_epochs_df : DataFrame with at least [norad_id, epoch_utc] columns
    res_df        : MEME residuals as returned by load_residuals

    Algorithm
    ---------
    1. Run detect_meme_events → maneuver event windows (Mode B)
    2. Run detect_mode_a     → exclusion windows (Mode A)
    3. For each TLE epoch (norad_id, epoch_utc):
       a. LABEL_EXCLUDED    if inside any Mode A window for that satellite
       b. LABEL_MANEUVERING if within ±MEME_EVENT_WINDOW_H of any event peak
       c. LABEL_NOMINAL     if majority of residual points near this epoch
                            have valid_for_training == True
       d. LABEL_EXCLUDED    otherwise (ambiguous / insufficient coverage)

    Returns
    -------
    tle_epochs_df with an added `label` column.
    """
    if tle_epochs_df.empty:
        out = tle_epochs_df.copy()
        out["label"] = pd.Series(dtype=int)
        return out

    # Ensure epoch_utc is timezone-aware
    df = tle_epochs_df.copy()
    df["epoch_utc"] = pd.to_datetime(df["epoch_utc"], utc=True)

    # Step 1 & 2: detect events and exclusion windows
    events_df  = detect_meme_events(res_df)
    mode_a_df  = detect_mode_a(res_df)

    window_h_td = pd.Timedelta(hours=MEME_EVENT_WINDOW_H)

    # Pre-build per-satellite lookup structures for performance
    #   events_by_sat  : { norad_id -> list of (peak_t,) }
    #   mode_a_by_sat  : { norad_id -> list of (start_t, end_t) }
    events_by_sat: dict[int, list[pd.Timestamp]] = {}
    if not events_df.empty:
        for nid, eg in events_df.groupby("norad_id"):
            events_by_sat[int(nid)] = eg["event_peak_t"].tolist()

    mode_a_by_sat: dict[int, list[tuple[pd.Timestamp, pd.Timestamp]]] = {}
    if not mode_a_df.empty:
        for nid, mg in mode_a_df.groupby("norad_id"):
            mode_a_by_sat[int(nid)] = list(
                zip(mg["window_start_t"].tolist(), mg["window_end_t"].tolist())
            )

    # Pre-build residual lookup: { norad_id -> sorted sub-df } for nominal check
    res_by_sat: dict[int, pd.DataFrame] = {}
    if not res_df.empty and "valid_for_training" in res_df.columns:
        for nid, rg in res_df.groupby("norad_id"):
            res_by_sat[int(nid)] = rg.sort_values("t").reset_index(drop=True)

    # Assign window for "near this epoch" nominal check: ±12 h
    _nominal_check_h = pd.Timedelta(hours=12.0)

    labels: list[int] = []

    for _, row in df.iterrows():
        nid   = int(row["norad_id"])
        epoch = row["epoch_utc"]

        # ── a. Mode A exclusion ───────────────────────────────────────────────
        if _in_mode_a(nid, epoch, mode_a_by_sat):
            labels.append(LABEL_EXCLUDED)
            continue

        # ── b. Within ±MEME_EVENT_WINDOW_H of a maneuver event ───────────────
        if _near_event(nid, epoch, events_by_sat, window_h_td):
            labels.append(LABEL_MANEUVERING)
            continue

        # ── c. Nominal check — majority of nearby residuals valid ─────────────
        sat_res = res_by_sat.get(nid)
        if sat_res is not None and not sat_res.empty:
            t_lo = epoch - _nominal_check_h
            t_hi = epoch + _nominal_check_h
            nearby = sat_res[
                (sat_res["t"] >= t_lo) & (sat_res["t"] <= t_hi)
            ]
            if not nearby.empty:
                frac_valid = nearby["valid_for_training"].mean()
                if frac_valid > 0.5:
                    labels.append(LABEL_NOMINAL)
                    continue

        # ── d. Ambiguous / no coverage → exclude ─────────────────────────────
        labels.append(LABEL_EXCLUDED)

    df["label"] = labels
    log.info(
        "assign_labels: total=%d  nominal=%d  maneuvering=%d  excluded=%d",
        len(df),
        int((df["label"] == LABEL_NOMINAL).sum()),
        int((df["label"] == LABEL_MANEUVERING).sum()),
        int((df["label"] == LABEL_EXCLUDED).sum()),
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _empty(columns: list[str]) -> pd.DataFrame:
    """Return an empty DataFrame with the given column names."""
    return pd.DataFrame(columns=columns)


def _in_mode_a(
    norad_id: int,
    epoch: pd.Timestamp,
    mode_a_by_sat: dict[int, list[tuple[pd.Timestamp, pd.Timestamp]]],
) -> bool:
    """Return True if `epoch` falls inside any Mode A window for `norad_id`."""
    windows = mode_a_by_sat.get(norad_id, [])
    for start_t, end_t in windows:
        if start_t <= epoch <= end_t:
            return True
    return False


def _near_event(
    norad_id: int,
    epoch: pd.Timestamp,
    events_by_sat: dict[int, list[pd.Timestamp]],
    window_td: pd.Timedelta,
) -> bool:
    """Return True if `epoch` is within `window_td` of any event peak for `norad_id`."""
    peaks = events_by_sat.get(norad_id, [])
    for peak_t in peaks:
        if abs((epoch - peak_t).total_seconds()) <= window_td.total_seconds():
            return True
    return False
