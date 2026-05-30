"""
data_loader.py
==============
Load TLE archive from DuckDB and compute orbital features for maneuver detection.
No MEME data is loaded or referenced here.

DB schema referenced (raw_tle_archive in space_db.duckdb):
    norad_id, object_name, line1, line2, epoch_utc,
    mean_motion, eccentricity, inclination_deg, raan_deg,
    argp_deg, mean_anomaly_deg, energy, sma_km, rmin_km, rmax_km
    (bstar is joined from tle_raw on norad_id + line1)
"""
from __future__ import annotations

import logging
from typing import Optional

import duckdb
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# ── physical constants ────────────────────────────────────────────────────────
DB_PATH       = "../space_db.duckdb"
R_EARTH_KM    = 6_378.137          # km  WGS-84 equatorial radius
MU            = 398_600.4418       # km³ s⁻²  Earth GM
J2            = 1.082_63e-3        # J2 zonal harmonic (EGM-96)
_TWO_PI       = 2.0 * np.pi

# ── empty-column sentinels ────────────────────────────────────────────────────
_LOADER_COLS = [
    "norad_id", "epoch_utc", "line1", "line2",
    "mean_motion", "eccentricity", "inclination", "raan",
    "arg_perigee", "mean_anomaly", "bstar",
]
_ELEM_COLS = [
    "norad_id", "epoch_utc",
    "sma_km", "altitude_km", "period_min",
    "eccentricity", "inclination", "raan", "bstar",
]
_DELTA_COLS = [
    "norad_id", "epoch_utc",
    "sma_km", "altitude_km", "eccentricity", "inclination", "raan", "bstar",
    "d_sma_km", "d_ecc", "d_inc_deg",
    "tle_gap_hours", "d_raan_res_deg", "d_sma_per_day", "d_bstar",
]
_ROLL_COLS = [
    "norad_id", "epoch_utc",
    "sma_km", "altitude_km", "period_min",
    "eccentricity", "inclination", "raan", "bstar",
    "d_sma_km", "d_ecc", "d_inc_deg",
    "tle_gap_hours", "d_raan_res_deg", "d_sma_per_day", "d_bstar",
    "sma_slope_km_day", "sma_std_km", "bstar_mean", "max_gap_h", "tle_count_7d",
]


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def load_tle_for_satellite(
    norad_id: int,
    db_path: str = DB_PATH,
    start_utc: Optional[pd.Timestamp] = None,
    end_utc: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """
    Query raw_tle_archive (joined with tle_raw for bstar) for one satellite.

    Parameters
    ----------
    norad_id  : NORAD catalog ID
    db_path   : path to space_db.duckdb
    start_utc : optional inclusive lower bound on epoch_utc (tz-aware)
    end_utc   : optional inclusive upper bound on epoch_utc (tz-aware)

    Returns
    -------
    DataFrame with columns:
        norad_id, epoch_utc, line1, line2,
        mean_motion, eccentricity, inclination, raan,
        arg_perigee, mean_anomaly, bstar
    Sorted ascending by epoch_utc with timezone-aware UTC timestamps.
    Empty DataFrame (correct columns) when no rows are found.
    """
    where_clauses = ["a.norad_id = ?"]
    params: list = [int(norad_id)]

    if start_utc is not None:
        # Store as naive UTC in DB; compare naively
        start_naive = _to_naive_utc(start_utc)
        where_clauses.append("a.epoch_utc >= ?")
        params.append(start_naive)

    if end_utc is not None:
        end_naive = _to_naive_utc(end_utc)
        where_clauses.append("a.epoch_utc <= ?")
        params.append(end_naive)

    where_sql = " AND ".join(where_clauses)

    sql = f"""
        SELECT
            a.norad_id,
            a.epoch_utc,
            a.line1,
            a.line2,
            a.mean_motion,
            a.eccentricity,
            a.inclination_deg   AS inclination,
            a.raan_deg          AS raan,
            a.argp_deg          AS arg_perigee,
            a.mean_anomaly_deg  AS mean_anomaly,
            r.bstar
        FROM raw_tle_archive a
        LEFT JOIN tle_raw r
            ON  r.norad_id = a.norad_id
            AND r.line1    = a.line1
        WHERE {where_sql}
        ORDER BY a.epoch_utc ASC
    """

    try:
        con = duckdb.connect(database=db_path, read_only=True)
        df = con.execute(sql, params).fetchdf()
        con.close()
    except Exception:
        log.exception("load_tle_for_satellite: DB query failed for norad_id=%s", norad_id)
        return _empty(_LOADER_COLS)

    if df.empty:
        log.debug("load_tle_for_satellite: no rows for norad_id=%s", norad_id)
        return _empty(_LOADER_COLS)

    # Make epoch_utc timezone-aware UTC
    df["epoch_utc"] = pd.to_datetime(df["epoch_utc"], utc=True)
    df = df.sort_values("epoch_utc").reset_index(drop=True)

    # Deduplicate on (norad_id, epoch_utc); prefer rows with bstar (from tle_raw join)
    before_dedup = len(df)
    df = df.sort_values("bstar", ascending=False, na_position="last")
    df = df.drop_duplicates(subset=["norad_id", "epoch_utc"], keep="first")
    df = df.sort_values("epoch_utc").reset_index(drop=True)
    if len(df) < before_dedup:
        log.debug(
            "load_tle_for_satellite: dropped %d duplicate epoch rows for norad_id=%s",
            before_dedup - len(df), norad_id,
        )

    log.debug(
        "load_tle_for_satellite: norad_id=%s  rows=%d  span=%s – %s",
        norad_id, len(df),
        df["epoch_utc"].iloc[0].isoformat(),
        df["epoch_utc"].iloc[-1].isoformat(),
    )
    return df


def extract_tle_elements(tle_df: pd.DataFrame) -> pd.DataFrame:
    """
    Derive orbital elements from already-parsed TLE fields in tle_df.
    No SGP4 propagation — all quantities come from DB columns.

    Added columns
    -------------
    sma_km       : semi-major axis  a = (μ / n²)^(1/3)  where n is in rad/s
    altitude_km  : mean altitude above Earth surface  a − R_earth
    period_min   : orbital period  1440 / mean_motion  (mean_motion in rev/day)

    Passed through unchanged
    ------------------------
    eccentricity, inclination, raan, bstar

    Returns
    -------
    DataFrame with columns defined in _ELEM_COLS.
    """
    if tle_df.empty:
        return _empty(_ELEM_COLS)

    df = tle_df.copy()

    # mean_motion is stored in rev/day → convert to rad/s
    n_rad_s = df["mean_motion"] * _TWO_PI / 86_400.0    # rad s⁻¹

    # Kepler's third law: a³ = μ / n²
    df["sma_km"]      = (MU / n_rad_s**2) ** (1.0 / 3.0)
    df["altitude_km"] = df["sma_km"] - R_EARTH_KM
    df["period_min"]  = 1440.0 / df["mean_motion"]      # rev/day → min/rev

    out_cols = [
        "norad_id", "epoch_utc",
        "sma_km", "altitude_km", "period_min",
        "eccentricity", "inclination", "raan", "bstar",
    ]
    # Keep any extra columns already present (line1/line2 needed downstream)
    extra = [c for c in df.columns if c not in out_cols]
    return df[out_cols + extra].reset_index(drop=True)


def compute_delta_features(elem_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute first-difference features between consecutive TLE epochs.

    New columns
    -----------
    d_sma_km        : change in semi-major axis (km)
    d_ecc           : change in eccentricity
    d_inc_deg       : change in inclination (deg)
    tle_gap_hours   : time between consecutive TLEs (hours)
    d_raan_res_deg  : RAAN diff minus J2 secular drift, wrapped to [-180, 180]
    d_sma_per_day   : d_sma_km per day (tle_gap_hours clipped to ≥ 0.1 h)
    d_bstar         : change in B* drag coefficient

    First row will have NaN for all diff-based columns.
    """
    if elem_df.empty:
        return _empty(_DELTA_COLS)

    df = elem_df.copy().sort_values("epoch_utc").reset_index(drop=True)

    df["d_sma_km"]      = df["sma_km"].diff()
    df["d_ecc"]         = df["eccentricity"].diff()
    df["d_inc_deg"]     = df["inclination"].diff()
    df["d_bstar"]       = df["bstar"].diff()

    dt_seconds = df["epoch_utc"].diff().dt.total_seconds()
    df["tle_gap_hours"] = dt_seconds / 3_600.0

    # ── J2-corrected RAAN residual ────────────────────────────────────────────
    # Expected secular drift: dΩ/dt = -3/2 * n * J2 * (R_e/p)² * cos(i)
    # where p = a(1 - e²), n in rad/s
    a      = df["sma_km"].values
    e      = df["eccentricity"].values
    i_rad  = np.radians(df["inclination"].values)
    n_rs   = df["mean_motion"].values * _TWO_PI / 86_400.0   # rad/s
    p      = a * (1.0 - e**2)

    # rate in deg/s; multiply by dt in seconds → expected drift in degrees
    rate_deg_s = np.degrees(
        -1.5 * n_rs * J2 * (R_EARTH_KM / p)**2 * np.cos(i_rad)
    )
    expected_drift_deg = rate_deg_s * dt_seconds.values

    # Actual RAAN diff wrapped to (-180, 180]
    raan_vals   = df["raan"].values
    raan_diff   = np.diff(raan_vals, prepend=np.nan)           # same length
    raan_diff   = _wrap_180(raan_diff)

    df["d_raan_res_deg"] = raan_diff - expected_drift_deg

    # Wrap residual itself into [-180, 180]
    df["d_raan_res_deg"] = df["d_raan_res_deg"].apply(
        lambda x: _wrap_180_scalar(x) if pd.notna(x) else np.nan
    )

    # ── d_sma per day — guard against tiny gaps ────────────────────────────
    gap_safe = df["tle_gap_hours"].clip(lower=0.1)
    df["d_sma_per_day"] = df["d_sma_km"] / (gap_safe / 24.0)

    keep = [c for c in _DELTA_COLS if c in df.columns]
    return df[keep].reset_index(drop=True)


def compute_rolling_features(
    delta_df: pd.DataFrame,
    window_days: float = 7.0,
) -> pd.DataFrame:
    """
    Compute backward-looking rolling statistics over a fixed time window.

    For each TLE epoch, aggregates all rows in the preceding `window_days`
    (inclusive of the current row, exclusive of rows outside the window).

    New columns
    -----------
    sma_slope_km_day : linear-regression slope of sma_km vs elapsed days
                       (km per day); NaN when fewer than 2 points in window
    sma_std_km       : standard deviation of sma_km in window
    bstar_mean       : mean of bstar in window
    max_gap_h        : maximum tle_gap_hours in window
    tle_count_7d     : number of TLEs within the window

    Returns
    -------
    Original columns plus the five rolling columns above.
    """
    if delta_df.empty:
        return _empty(_ROLL_COLS)

    df = delta_df.copy().sort_values("epoch_utc").reset_index(drop=True)
    window_td = pd.Timedelta(days=window_days)

    sma_slopes: list[float] = []
    sma_stds:   list[float] = []
    bstar_means: list[float] = []
    max_gaps:    list[float] = []
    counts:      list[int]   = []

    epochs = df["epoch_utc"].values  # numpy datetime64[ns, UTC] array
    sma    = df["sma_km"].values
    bstar  = df["bstar"].values
    gaps   = df["tle_gap_hours"].values

    for idx in range(len(df)):
        t_cur  = df["epoch_utc"].iloc[idx]
        t_lo   = t_cur - window_td
        mask   = (df["epoch_utc"] >= t_lo) & (df["epoch_utc"] <= t_cur)
        sub_idx = np.where(mask)[0]

        n = len(sub_idx)
        counts.append(n)

        sub_sma   = sma[sub_idx]
        sub_bstar = bstar[sub_idx]
        sub_gap   = gaps[sub_idx]

        # bstar_mean — ignore NaN
        bstar_valid = sub_bstar[~np.isnan(sub_bstar.astype(float))]
        bstar_means.append(float(np.mean(bstar_valid)) if len(bstar_valid) > 0 else np.nan)

        # max_gap_h — ignore NaN (first row gap is NaN)
        gap_valid = sub_gap[~np.isnan(sub_gap.astype(float))]
        max_gaps.append(float(np.max(gap_valid)) if len(gap_valid) > 0 else np.nan)

        if n < 2:
            sma_slopes.append(np.nan)
            sma_stds.append(float(np.std(sub_sma)) if n == 1 else np.nan)
            continue

        # Time axis in days relative to first point in window
        sub_times = df["epoch_utc"].iloc[sub_idx]
        t0_days   = (sub_times - sub_times.iloc[0]).dt.total_seconds() / 86_400.0
        slope, _  = np.polyfit(t0_days.values, sub_sma, 1)
        sma_slopes.append(float(slope))
        sma_stds.append(float(np.std(sub_sma)))

    df["sma_slope_km_day"] = sma_slopes
    df["sma_std_km"]       = sma_stds
    df["bstar_mean"]       = bstar_means
    df["max_gap_h"]        = max_gaps
    df["tle_count_7d"]     = counts

    keep = [c for c in _ROLL_COLS if c in df.columns]
    return df[keep].reset_index(drop=True)


def list_norad_ids(db_path: str = DB_PATH) -> list[int]:
    """Return all NORAD IDs present in raw_tle_archive."""
    try:
        con = duckdb.connect(database=db_path, read_only=True)
        rows = con.execute(
            "SELECT DISTINCT norad_id FROM raw_tle_archive ORDER BY norad_id"
        ).fetchall()
        con.close()
        return [int(r[0]) for r in rows]
    except Exception:
        log.exception("list_norad_ids: DB query failed")
        return []


def build_feature_matrix(
    norad_id: int,
    db_path: str = DB_PATH,
    start_utc: Optional[pd.Timestamp] = None,
    end_utc: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """
    Full pipeline: load → extract elements → delta features → rolling features.

    Returns one row per TLE epoch with all features plus [norad_id, epoch_utc].
    Returns an empty DataFrame (with _ROLL_COLS columns) if no data is available.
    """
    log.info("build_feature_matrix: norad_id=%s", norad_id)

    raw_df  = load_tle_for_satellite(norad_id, db_path, start_utc, end_utc)
    if raw_df.empty:
        log.warning("build_feature_matrix: no TLE data for norad_id=%s", norad_id)
        return _empty(_ROLL_COLS)

    elem_df  = extract_tle_elements(raw_df)
    if elem_df.empty:
        return _empty(_ROLL_COLS)

    delta_df = compute_delta_features(elem_df)
    if delta_df.empty:
        return _empty(_ROLL_COLS)

    feat_df  = compute_rolling_features(delta_df)
    log.info(
        "build_feature_matrix: norad_id=%s  final_rows=%d", norad_id, len(feat_df)
    )
    return feat_df


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _empty(columns: list[str]) -> pd.DataFrame:
    """Return an empty DataFrame with the given column names."""
    return pd.DataFrame(columns=columns)


def _to_naive_utc(ts: pd.Timestamp) -> pd.Timestamp:
    """Convert a tz-aware Timestamp to a naive UTC Timestamp for DB comparison."""
    if ts.tzinfo is not None:
        return ts.tz_convert("UTC").tz_localize(None)
    return ts


def _wrap_180(arr: np.ndarray) -> np.ndarray:
    """Wrap an array of angles (degrees) into (-180, 180]."""
    out = arr.copy().astype(float)
    valid = ~np.isnan(out)
    out[valid] = (out[valid] + 180.0) % 360.0 - 180.0
    return out


def _wrap_180_scalar(x: float) -> float:
    """Wrap a scalar angle (degrees) into (-180, 180]."""
    return (x + 180.0) % 360.0 - 180.0
