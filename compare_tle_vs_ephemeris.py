#!/usr/bin/env python3
"""
Compare TLE-propagated state vectors against downloaded Starlink MEME ephemeris,
and optionally detect & evaluate orbital maneuvers from both data sources.

For each satellite that has both:
  - One or more MEME ephemeris files under data/raw/{sat_name}/*.txt
  - TLE records in space_db.duckdb raw_tle_archive

this script:
  1. Loads ALL ephemeris files per satellite (default), each covering 72 h at 1-min
     cadence.  Files are concatenated and de-duplicated, keeping the freshest
     prediction for any overlapping timestamp.  Use --latest-only to restore the
     original single-file behaviour.
  2. Selects the best TLE for *each* MEME timestamp independently (most recent
     TLE whose epoch precedes that timestamp), so a 9-day MEME window does not
     depend on a single ageing TLE.
  3. Propagates each TLE segment with SGP4 (Skyfield) and computes position /
     velocity residuals in ECI and RTN coordinates.

Coordinate frame note
---------------------
MEME files use UVW = EME2000 (J2000 ECI).
Skyfield SGP4 returns GCRS (geocentric celestial), which for sub-km
accuracy analysis is interchangeable with J2000/EME2000.

Orbital Maneuver Detection (--maneuver-detection)
-------------------------------------------------
When enabled, two independent detectors run in parallel:

  MEME detector — extracts the first state vector from each successive
  ephemeris file (~8 h cadence) and converts it to Keplerian elements.
  A jump in {a, e, i, RAAN (J2-corrected)} between consecutive snapshots
  indicates a burn.  This is a high-fidelity ground truth because SpaceX
  re-generates the ephemeris after every maneuver.

  TLE detector — parses Keplerian elements directly from consecutive TLE
  strings (no SGP4 propagation; mean motion → a, plus i/RAAN/e from line 2)
  and applies the same threshold logic.  Coverage is restricted to the same
  date window as the MEME data.

  Alignment — both detectors produce ragged event windows.  A fixed 8 h
  binning grid (matching MEME cadence) converts them into a binary
  classification dataset: y_true = MEME flagged, y_score = TLE composite
  score.

  Metrics computed without sklearn (trapezoidal / step-integral):
    TPR / FPR at score ≥ 1.0 (natural operating point)
    ROC-AUC
    Average Precision (area under PR curve)
    F1-macro at Youden-optimal threshold

Output
------
  data/comparison/residuals_{date}.csv
  data/comparison/summary_{date}.csv
  data/comparison/plots/fleet_overview_*.png
  data/comparison/plots/timeseries_*.png
  data/comparison/plots/ecdf_*.png
  data/comparison/plots/rtn_*.png

  (with --maneuver-detection)
  data/comparison/meme_maneuvers_{date}.csv
  data/comparison/tle_maneuvers_{date}.csv
  data/comparison/maneuver_classification_{date}.csv
  data/comparison/maneuver_sat_metrics_{date}.csv
  data/comparison/plots/maneuver_roc_pr_{date}.png

Usage
-----
  python compare_tle_vs_ephemeris.py
  python compare_tle_vs_ephemeris.py --maneuver-detection
  python compare_tle_vs_ephemeris.py --maneuver-detection --no-plot
  python compare_tle_vs_ephemeris.py --data-root data --db space_db.duckdb
  python compare_tle_vs_ephemeris.py --max-sats 10 --no-residuals
  python compare_tle_vs_ephemeris.py --rtn-top 10
  python compare_tle_vs_ephemeris.py --latest-only
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from skyfield.api import EarthSatellite, load as skyfield_load

from starlink_ephemeris.parser import parse_ephemeris_file

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("compare")


# ── maneuver detection constants ──────────────────────────────────────────────
# Physical constants (WGS-84 / EGM-96)
_MU_M   = 398_600.4418    # km³/s²  Earth GM
_R_E_M  = 6_378.137       # km      Earth equatorial radius
_J2_M   = 1.082_63e-3     # J2 zonal harmonic

# Detection thresholds — validated against quiet-transition noise floor in
# detect_maneuvers.py (J2 RAAN residual std ≈ 0.021 deg on quiet transitions)
_THR_DA    = 1.0    # km   semi-major axis change
_THR_DI    = 0.02   # deg  inclination change
_THR_DE    = 0.001  # —    eccentricity change
_THR_DRAAN = 0.1    # deg  J2-corrected RAAN residual

# Regex matching a single MEME state-vector line:
#   YYYYDDDHHMMSS.sss  rx  ry  rz  vx  vy  vz
_FLOAT = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
_MEME_LINE_RE = re.compile(
    r"^(\d{4})(\d{3})(\d{2})(\d{2})(\d{2}\.\d+)"
    r"\s+(" + _FLOAT + r")"
    r"\s+(" + _FLOAT + r")"
    r"\s+(" + _FLOAT + r")"
    r"\s+(" + _FLOAT + r")"
    r"\s+(" + _FLOAT + r")"
    r"\s+(" + _FLOAT + r")"
)


# ── maneuver detection helpers ────────────────────────────────────────────────

def _meme_first_state(path: Path) -> dict | None:
    """
    Read the first valid state-vector line from a MEME ephemeris file.

    Returns a dict {t, r_x, r_y, r_z, v_x, v_y, v_z} with a UTC-aware
    timestamp, or None if the file is unreadable or has no data lines.
    This is intentionally fast — we read only until we hit the first match,
    skipping headers and covariance blocks without parsing them.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _MEME_LINE_RE.match(line.strip())
                if m:
                    yr, doy = int(m.group(1)), int(m.group(2))
                    hh, mm  = int(m.group(3)), int(m.group(4))
                    ss_f = float(m.group(5))
                    ss_i = int(ss_f)
                    us   = round((ss_f - ss_i) * 1_000_000)
                    t = (
                        pd.Timestamp(yr, 1, 1, tzinfo=timezone.utc)
                        + pd.Timedelta(days=doy - 1)
                        + pd.Timedelta(hours=hh, minutes=mm,
                                       seconds=ss_i, microseconds=us)
                    )
                    return {
                        "t":   t,
                        "r_x": float(m.group(6)),
                        "r_y": float(m.group(7)),
                        "r_z": float(m.group(8)),
                        "v_x": float(m.group(9)),
                        "v_y": float(m.group(10)),
                        "v_z": float(m.group(11)),
                    }
    except Exception:
        pass
    return None


def _eci_to_elements(rx: float, ry: float, rz: float,
                     vx: float, vy: float, vz: float) -> dict:
    """
    Convert an EME2000 state vector (km, km/s) to Keplerian elements.

    Returns a, e, i (deg), raan (deg).  Argument of perigee and mean
    anomaly are omitted because Starlink eccentricities are < 0.005,
    making omega ill-conditioned.  We only need the shape/plane elements
    to detect maneuver signatures.
    """
    r = np.array([rx, ry, rz], dtype=float)
    v = np.array([vx, vy, vz], dtype=float)
    r_m = float(np.linalg.norm(r))
    v_m = float(np.linalg.norm(v))

    eps = v_m**2 / 2.0 - _MU_M / r_m
    a   = -_MU_M / (2.0 * eps)

    h   = np.cross(r, v)
    h_m = float(np.linalg.norm(h))
    i_rad = float(np.arccos(np.clip(h[2] / h_m, -1.0, 1.0)))

    K = np.array([0.0, 0.0, 1.0])
    N = np.cross(K, h)
    N_m = float(np.linalg.norm(N))
    if N_m < 1e-10:
        raan_rad = 0.0
    else:
        raan_rad = float(np.arccos(np.clip(N[0] / N_m, -1.0, 1.0)))
        if N[1] < 0.0:
            raan_rad = 2.0 * np.pi - raan_rad

    e_vec = np.cross(v, h) / _MU_M - r / r_m
    e = float(np.linalg.norm(e_vec))

    return {
        "a":    a,
        "e":    e,
        "i":    np.degrees(i_rad),
        "raan": np.degrees(raan_rad),
    }


def _j2_raan_drift(a: float, e: float, i_deg: float, dt_s: float) -> float:
    """
    Expected secular J2 RAAN precession over dt_s seconds (degrees).

    Formula: dΩ/dt = -3/2 * n * J2 * (R_E/p)² * cos(i)
    where p = a*(1-e²) is the semi-latus rectum and n = sqrt(μ/a³).
    """
    i = np.radians(i_deg)
    n = np.sqrt(_MU_M / a**3)
    p = a * (1.0 - e**2)
    rate_deg_s = np.degrees(-1.5 * n * _J2_M * (_R_E_M / p)**2 * np.cos(i))
    return rate_deg_s * dt_s


def _ang(a1: float, a2: float) -> float:
    """Signed difference (a2 − a1) wrapped to (−180, +180]."""
    d = (a2 - a1) % 360.0
    return d - 360.0 if d > 180.0 else d


def _maneuver_score(da: float, di: float, de: float, draan_res: float) -> float:
    """
    Max-of-ratios composite score.

    Each indicator is normalised by its detection threshold so the result
    is dimensionless: a score > 1.0 means at least one threshold was
    exceeded.  Using max (rather than sum) avoids double-counting correlated
    indicators (e.g. a Hohmann burn changes both a and e simultaneously).
    """
    return max(
        abs(da)       / _THR_DA,
        abs(di)       / _THR_DI,
        abs(de)       / _THR_DE,
        abs(draan_res)/ _THR_DRAAN,
    )


def detect_meme_maneuvers(sat_name: str, ephem_files: list[Path]) -> pd.DataFrame:
    """
    MEME-based maneuver detector.

    Strategy: SpaceX re-generates the MEME ephemeris after every burn, so
    the first state vector of each file is a fresh "snapshot" of the orbital
    state at that moment.  Comparing consecutive snapshots (~8 h apart)
    reveals element jumps that cannot be explained by natural perturbations.

    The J2 secular RAAN drift is removed analytically so only non-gravitational
    RAAN changes remain.  All other perturbations (solar pressure, atmospheric
    drag) are small relative to the thresholds over an 8 h window.

    Returns a DataFrame with one row per consecutive file-pair:
        sat_name, t_from, t_to, dt_h,
        da_km, di_deg, de, draan_res_deg,
        score, flagged, source='meme'
    """
    # _meme_first_state bypasses parse_ephemeris_file intentionally: we only
    # need the first state vector per file (one snapshot per ~8 h), so we read
    # until the first matching line and stop — much faster than parsing all 4320
    # rows.  parse_ephemeris_file is used in load_all_meme for full residuals.
    snaps: list[dict] = []
    for f in sorted(ephem_files, key=lambda p: p.name):
        s = _meme_first_state(f)
        if s is not None:
            elems = _eci_to_elements(
                s["r_x"], s["r_y"], s["r_z"],
                s["v_x"], s["v_y"], s["v_z"],
            )
            snaps.append({"t": s["t"], **elems})

    if len(snaps) < 2:
        return pd.DataFrame()

    rows: list[dict] = []
    for k in range(len(snaps) - 1):
        s1, s2 = snaps[k], snaps[k + 1]
        dt_s  = (s2["t"] - s1["t"]).total_seconds()
        if dt_s <= 0:
            continue
        dt_h  = dt_s / 3600.0

        a_ref = 0.5 * (s1["a"] + s2["a"])
        e_ref = 0.5 * (s1["e"] + s2["e"])
        i_ref = 0.5 * (s1["i"] + s2["i"])

        da        = s2["a"]    - s1["a"]
        de        = s2["e"]    - s1["e"]
        di        = s2["i"]    - s1["i"]
        draan_raw = _ang(s1["raan"], s2["raan"])
        draan_res = draan_raw - _j2_raan_drift(a_ref, e_ref, i_ref, dt_s)
        score     = _maneuver_score(da, di, de, draan_res)

        rows.append({
            "sat_name":      sat_name,
            "t_from":        s1["t"],
            "t_to":          s2["t"],
            "dt_h":          round(dt_h, 2),
            "da_km":         round(da, 4),
            "di_deg":        round(di, 5),
            "de":            round(de, 6),
            "draan_res_deg": round(draan_res, 4),
            "score":         round(score, 4),
            "flagged":       bool(score > 1.0),
            "source":        "meme",
        })

    return pd.DataFrame(rows)


def _parse_tle_at_epoch(line1: str, line2: str) -> dict:
    """
    Extract Keplerian mean elements at TLE epoch without SGP4 propagation.

    We parse TLE line 2 directly (inclination, RAAN, eccentricity) and derive
    the semi-major axis from the Kozai mean motion (rev/day → rad/s → a via
    Kepler's third law).  The resulting elements are Kozai/Brouwer mean
    elements — slightly different from osculating elements derived from MEME
    state vectors, but the *jumps* at maneuver times are clearly visible in
    both representations.  This approach avoids a second SGP4 propagation pass.

    TLE field layout (0-indexed columns in line2):
        8-15:   inclination [deg]
        17-24:  RAAN [deg]
        26-32:  eccentricity (no decimal point, implicit 0.XXXXXXX)
        52-62:  mean motion [rev/day]
    """
    # Epoch from line 1
    yr = int(line1[18:20])
    yr += 2000 if yr < 57 else 1900
    doyf = float(line1[20:32])
    day  = int(doyf)
    frac = doyf - day
    t = (
        pd.Timestamp(yr, 1, 1, tz="UTC")
        + pd.Timedelta(days=day - 1 + frac)
    )

    i_deg    = float(line2[8:16])
    raan_deg = float(line2[17:25])
    e        = float("0." + line2[26:33].strip())
    n_rev_d  = float(line2[52:63])

    n_rad_s  = n_rev_d * 2.0 * np.pi / 86400.0
    a        = (_MU_M / n_rad_s**2) ** (1.0 / 3.0)

    return {"t": t, "a": a, "e": e, "i": i_deg, "raan": raan_deg}


def detect_tle_maneuvers(
    sat_name: str,
    tle_df: pd.DataFrame,
    t_start: "pd.Timestamp",
    t_end: "pd.Timestamp",
) -> pd.DataFrame:
    """
    TLE-based maneuver detector (restricted to the MEME coverage window).

    Parses Keplerian mean elements from consecutive TLEs and applies the same
    threshold logic as detect_meme_maneuvers.  A 2-day look-back before
    t_start ensures the first MEME window always has a prior TLE neighbour.

    Only transitions whose t_from falls within [t_start, t_end] are emitted,
    so the resulting events are temporally aligned with the MEME ground truth.

    Returns a DataFrame with the same columns as detect_meme_maneuvers
    (source='tle').
    """
    if tle_df.empty:
        return pd.DataFrame()

    lookback = t_start - pd.Timedelta(days=2)
    epochs   = pd.to_datetime(tle_df["epoch_utc"], utc=True)
    mask     = (epochs >= lookback) & (epochs <= t_end + pd.Timedelta(hours=1))
    window   = tle_df[mask].sort_values("epoch_utc").reset_index(drop=True)

    if len(window) < 2:
        return pd.DataFrame()

    snaps: list[dict] = []
    for _, row in window.iterrows():
        try:
            snaps.append(_parse_tle_at_epoch(row["line1"], row["line2"]))
        except Exception as exc:
            log.warning("  [%s] skipping malformed TLE epoch %s: %s",
                        sat_name, row.get("epoch_utc", "?"), exc)

    if len(snaps) < 2:
        return pd.DataFrame()

    rows: list[dict] = []
    for k in range(len(snaps) - 1):
        s1, s2 = snaps[k], snaps[k + 1]

        # Restrict to transitions that start within the MEME window.
        # Use an 8 h tolerance (= bin width) so a TLE whose epoch sits just
        # before t_start isn't dropped when the burn straddles the boundary.
        if s1["t"] < t_start - pd.Timedelta(hours=8):
            continue
        if s1["t"] > t_end:
            break

        dt_s = (s2["t"] - s1["t"]).total_seconds()
        if dt_s <= 0:
            continue
        dt_h  = dt_s / 3600.0

        a_ref = 0.5 * (s1["a"] + s2["a"])
        e_ref = 0.5 * (s1["e"] + s2["e"])
        i_ref = 0.5 * (s1["i"] + s2["i"])

        da        = s2["a"]    - s1["a"]
        de        = s2["e"]    - s1["e"]
        di        = s2["i"]    - s1["i"]
        draan_raw = _ang(s1["raan"], s2["raan"])
        draan_res = draan_raw - _j2_raan_drift(a_ref, e_ref, i_ref, dt_s)
        score     = _maneuver_score(da, di, de, draan_res)

        rows.append({
            "sat_name":      sat_name,
            "t_from":        s1["t"],
            "t_to":          s2["t"],
            "dt_h":          round(dt_h, 2),
            "da_km":         round(da, 4),
            "di_deg":        round(di, 5),
            "de":            round(de, 6),
            "draan_res_deg": round(draan_res, 4),
            "score":         round(score, 4),
            "flagged":       bool(score > 1.0),
            "source":        "tle",
        })

    return pd.DataFrame(rows)


def build_classification_dataset(
    meme_ev: pd.DataFrame,
    tle_ev: pd.DataFrame,
    t_start: "pd.Timestamp",
    t_end: "pd.Timestamp",
    window_h: float = 8.0,
    min_da: float = 0.0,
) -> pd.DataFrame:
    """
    Map MEME and TLE events onto a fixed 8 h grid to create a binary
    classification dataset.

    Each bin gets:
        y_true  — 1 if any MEME transition starting in this bin qualifies
                  as a positive event (see min_da below)
        y_score — maximum TLE composite score among TLE transitions starting
                  in this bin (0.0 if no TLE transition falls in the bin)

    Parameters
    ----------
    min_da : float
        Minimum |da_km| required for a MEME transition to count as a positive
        ground-truth event.  When 0.0 (default) any flagged MEME transition
        (score > 1.0 on any indicator) counts as positive.  Set to e.g. 5.0
        to restrict positives to medium/large manoeuvres (|da| ≥ 5 km).

    The choice of 8 h matches the MEME file cadence so each MEME transition
    maps to at most one bin.  Taking the MAX TLE score per bin handles the
    case where multiple TLEs land in the same bin: we credit the strongest
    signal.

    Returns a DataFrame with:
        t_bin, y_true, y_score, n_meme_trans, n_tle_trans
    """
    bins = pd.date_range(t_start, t_end, freq=f"{window_h}h", tz="UTC")
    if len(bins) < 2:
        return pd.DataFrame()

    records: list[dict] = []
    for i in range(len(bins) - 1):
        b0, b1 = bins[i], bins[i + 1]

        m_in = pd.DataFrame()
        if not meme_ev.empty:
            mt = pd.to_datetime(meme_ev["t_from"], utc=True)
            m_in = meme_ev[(mt >= b0) & (mt < b1)]

        t_in = pd.DataFrame()
        if not tle_ev.empty:
            tt = pd.to_datetime(tle_ev["t_from"], utc=True)
            t_in = tle_ev[(tt >= b0) & (tt < b1)]

        if min_da > 0.0:
            # Positive only if MEME saw a burn large enough to be detectable
            positive = (
                not m_in.empty
                and bool((m_in["da_km"].abs() >= min_da).any())
            )
        else:
            # Default: positive if any MEME indicator exceeded its threshold
            positive = not m_in.empty and bool(m_in["flagged"].any())

        y_true  = int(positive)
        y_score = float(t_in["score"].max()) if not t_in.empty else 0.0

        records.append({
            "t_bin":        b0,
            "y_true":       y_true,
            "y_score":      y_score,
            "n_meme_trans": len(m_in),
            "n_tle_trans":  len(t_in),
        })

    return pd.DataFrame(records)


# ── detection evaluation metrics ──────────────────────────────────────────────

def _compute_curves(
    y_true: np.ndarray,
    y_score: np.ndarray,
) -> dict | None:
    """
    Compute ROC and PR curves without sklearn.

    Returns a dict with:
        fprs, tprs             — ROC curve arrays (include (0,0) and (1,1))
        thresholds             — score thresholds corresponding to tprs[1:-1]
        roc_auc                — area under ROC (trapezoidal rule)
        precisions, recalls    — PR curve arrays (start at precision=1, recall=0)
        avg_precision          — area under PR curve (step-function integral)

    Returns None when there are no positives or no negatives (degenerate case).
    """
    y_true  = np.asarray(y_true,  dtype=int)
    y_score = np.asarray(y_score, dtype=float)

    P = int(y_true.sum())
    N = len(y_true) - P

    if P == 0 or N == 0 or len(y_true) < 2:
        return None

    # Unique thresholds in descending order — one ROC point per threshold
    thresholds = np.unique(y_score)[::-1]

    # ROC: accumulate (FPR, TPR) at each unique threshold
    tprs = np.zeros(len(thresholds) + 2)
    fprs = np.zeros(len(thresholds) + 2)
    # Closing point at (1, 1) — all samples predicted positive
    tprs[-1] = 1.0
    fprs[-1] = 1.0

    for k, thr in enumerate(thresholds):
        mask = y_score >= thr
        tp   = int(y_true[mask].sum())
        fp   = int((1 - y_true[mask]).sum())
        tprs[k + 1] = tp / P
        fprs[k + 1] = fp / N

    # np.trapezoid added in NumPy 2.0; fall back to np.trapz via string lookup
    # to avoid a deprecation lint warning on the np.trapz reference itself.
    _trapz = getattr(np, "trapezoid", getattr(np, "trapz"))
    roc_auc = float(abs(_trapz(tprs, fprs)))

    # PR curve: accumulate (recall, precision) at each threshold
    # Start at (recall=0, precision=1) — threshold = ∞, no predictions
    precs = np.ones(len(thresholds) + 1)
    recs  = np.zeros(len(thresholds) + 1)

    for k, thr in enumerate(thresholds):
        mask = y_score >= thr
        tp   = int(y_true[mask].sum())
        pp   = int(mask.sum())          # predicted positives
        precs[k + 1] = tp / pp if pp > 0 else 0.0
        recs [k + 1] = tp / P

    # Area under PR step function: sum(ΔRecall * Precision)
    avg_precision = float(np.sum(np.diff(recs) * precs[1:]))

    return {
        "fprs":          fprs,
        "tprs":          tprs,
        "thresholds":    thresholds,
        "roc_auc":       roc_auc,
        "precisions":    precs,
        "recalls":       recs,
        "avg_precision": avg_precision,
    }


def compute_detection_metrics(
    y_true: np.ndarray,
    y_score: np.ndarray,
) -> dict:
    """
    Compute all required maneuver-detection evaluation metrics.

    Parameters
    ----------
    y_true  : binary array — 1 = MEME confirmed maneuver (ground truth)
    y_score : continuous TLE composite score (higher = more likely maneuver)

    Returned dict keys
    ------------------
    n_total           — number of time bins evaluated
    n_pos             — number of positive bins (MEME flagged)
    n_neg             — number of negative bins
    prevalence        — fraction of positive bins
    tpr_at_thr1       — TPR at the natural threshold score≥1.0
    fpr_at_thr1       — FPR at the natural threshold score≥1.0
    roc_auc           — area under ROC curve
    avg_precision     — area under PR curve (Average Precision)
    f1_positive       — F1 of the positive class at Youden-optimal threshold
    f1_macro          — macro-averaged F1 at Youden-optimal threshold
    optimal_threshold — Youden's J optimal score threshold
    """
    y_true  = np.asarray(y_true,  dtype=int)
    y_score = np.asarray(y_score, dtype=float)

    P = int(y_true.sum())
    N = len(y_true) - P

    result: dict = {
        "n_total":           int(len(y_true)),
        "n_pos":             P,
        "n_neg":             N,
        "prevalence":        round(float(y_true.mean()), 4),
        "tpr_at_thr1":       float("nan"),
        "fpr_at_thr1":       float("nan"),
        "roc_auc":           float("nan"),
        "avg_precision":     float("nan"),
        "f1_positive":       float("nan"),
        "f1_macro":          float("nan"),
        "optimal_threshold": float("nan"),
    }

    if P == 0 or N == 0 or len(y_true) < 2:
        log.debug("compute_detection_metrics: degenerate case P=%d N=%d", P, N)
        return result

    # ── metrics at the natural operating point (score ≥ 1.0) ─────────────────
    # score ≥ 1.0 means at least one Keplerian indicator exceeded its threshold,
    # which is exactly the rule both detectors use to raise a maneuver flag.
    y_pred1 = (y_score >= 1.0).astype(int)
    tp1 = int(((y_pred1 == 1) & (y_true == 1)).sum())
    fp1 = int(((y_pred1 == 1) & (y_true == 0)).sum())
    result["tpr_at_thr1"] = round(tp1 / P, 4)
    result["fpr_at_thr1"] = round(fp1 / N, 4)

    # ── ROC / PR curves ───────────────────────────────────────────────────────
    curves = _compute_curves(y_true, y_score)
    if curves is None:
        return result

    result["roc_auc"]       = round(curves["roc_auc"],       4)
    result["avg_precision"] = round(curves["avg_precision"],  4)

    # ── Youden-optimal threshold: maximises TPR − FPR ─────────────────────────
    # tprs and fprs both have len(thresholds)+2 entries.
    # tprs[0]=0, tprs[k+1] corresponds to thresholds[k], tprs[-1]=1.
    j_stat = curves["tprs"] - curves["fprs"]
    best   = int(np.argmax(j_stat))

    thresholds = curves["thresholds"]
    # Map back: best in [0, len(thresholds)+1]; threshold index is best-1.
    thr_idx = max(0, min(best - 1, len(thresholds) - 1))
    opt_thr = float(thresholds[thr_idx])
    result["optimal_threshold"] = round(opt_thr, 4)

    y_pred_opt = (y_score >= opt_thr).astype(int)
    tp_o = int(((y_pred_opt == 1) & (y_true == 1)).sum())
    fp_o = int(((y_pred_opt == 1) & (y_true == 0)).sum())
    fn_o = int(((y_pred_opt == 0) & (y_true == 1)).sum())
    tn_o = int(((y_pred_opt == 0) & (y_true == 0)).sum())

    prec_pos = tp_o / (tp_o + fp_o) if (tp_o + fp_o) > 0 else 0.0
    rec_pos  = tp_o / (tp_o + fn_o) if (tp_o + fn_o) > 0 else 0.0
    f1_pos   = (2.0 * prec_pos * rec_pos / (prec_pos + rec_pos)
                if (prec_pos + rec_pos) > 0 else 0.0)

    prec_neg = tn_o / (tn_o + fn_o) if (tn_o + fn_o) > 0 else 0.0
    rec_neg  = tn_o / (tn_o + fp_o) if (tn_o + fp_o) > 0 else 0.0
    f1_neg   = (2.0 * prec_neg * rec_neg / (prec_neg + rec_neg)
                if (prec_neg + rec_neg) > 0 else 0.0)

    result["f1_positive"] = round(f1_pos, 4)
    result["f1_macro"]    = round((f1_pos + f1_neg) / 2.0, 4)

    return result


# ── helpers ───────────────────────────────────────────────────────────────────

def load_registry(registry_csv: Path) -> pd.DataFrame:
    """Return norad_id → sat_name mapping from url_registry.csv."""
    reg = pd.read_csv(registry_csv, usecols=["norad_id", "sat_name"])
    return reg.drop_duplicates("norad_id").set_index("norad_id")


def find_latest_ephemeris(sat_dir: Path) -> Path | None:
    """Return the lexicographically last .txt file (= most recent by filename timestamp)."""
    files = list(sat_dir.glob("*.txt"))
    if not files:
        return None
    return max(files, key=lambda p: p.name)


def find_all_ephemeris_files(sat_dir: Path) -> list[Path]:
    """Return all .txt files in a satellite directory sorted chronologically by filename."""
    return sorted(sat_dir.glob("*.txt"), key=lambda p: p.name)


def load_all_meme(sat_name: str, ephem_files: list[Path]) -> pd.DataFrame:
    """
    Parse and concatenate multiple MEME ephemeris files for one satellite.

    Each file covers 72 h at 1-min cadence; adjacent files (8 h apart) overlap
    by ~88 %.  De-duplication keeps the *freshest* prediction for each timestamp
    (from the latest-released file that covers that epoch), because newer files
    incorporate more recent tracking data and are typically more accurate.

    Returns a single DataFrame with the same columns as parse_ephemeris_file,
    sorted by 't', with UTC-aware timestamps.
    """
    frames: list[pd.DataFrame] = []
    for path in ephem_files:          # already sorted old → new
        try:
            _, df = parse_ephemeris_file(path, sat_id=sat_name)
        except Exception as exc:
            log.debug("  [%s] skipping %s: %s", sat_name, path.name, exc)
            continue
        if not df.empty:
            df["t"] = pd.to_datetime(df["t"], utc=True)
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined = (
        combined
        .sort_values("t")
        .drop_duplicates(subset="t", keep="last")
        .reset_index(drop=True)
    )
    return combined


def query_best_tle(
    con: duckdb.DuckDBPyConnection,
    norad_id_to_ephem_start: dict[int, "pd.Timestamp"],
) -> pd.DataFrame:
    """
    For each norad_id, return the single TLE whose epoch is closest to ephem_start,
    preferring a TLE whose epoch is ≤ ephem_start (pre-observation).
    Falls back to the earliest post-observation TLE when no earlier one exists.

    Used by --latest-only mode.  Multi-file mode uses query_tles_in_range instead.

    Returns DataFrame with columns:
        norad_id, line1, line2, epoch_utc, space_track_name

    Notes
    -----
    ``space_track_name`` is the Space-Track official designation stored in TLE
    line 0 (e.g. "STARLINK-1008").  This is Space-Track's own sequential number
    and is unrelated to both the NORAD catalog ID and the SpaceX-internal name
    found in MEME ephemeris URLs (e.g. "STARLINK-32283").
    It is NULL for TLEs downloaded before format='3le' was adopted.
    """
    if not norad_id_to_ephem_start:
        return pd.DataFrame(columns=["norad_id", "line1", "line2", "epoch_utc", "space_track_name"])

    ids_str = ",".join(str(i) for i in norad_id_to_ephem_start)
    all_tles = con.execute(f"""
        SELECT norad_id, line1, line2, epoch_utc,
               object_name AS space_track_name
        FROM raw_tle_archive
        WHERE norad_id IN ({ids_str})
        ORDER BY norad_id, epoch_utc
    """).fetchdf()

    if all_tles.empty:
        return all_tles

    all_tles["epoch_utc"] = pd.to_datetime(all_tles["epoch_utc"], utc=True)

    best: list[pd.Series] = []
    for norad_id, ephem_start in norad_id_to_ephem_start.items():
        sat_tles = all_tles[all_tles["norad_id"] == norad_id]
        if sat_tles.empty:
            continue
        before = sat_tles[sat_tles["epoch_utc"] <= ephem_start]
        if not before.empty:
            best.append(before.iloc[-1])
        else:
            best.append(sat_tles.iloc[0])

    if not best:
        return pd.DataFrame(columns=all_tles.columns)
    return pd.DataFrame(best).reset_index(drop=True)


def query_tles_in_range(
    con: duckdb.DuckDBPyConnection,
    norad_id_to_window: "dict[int, tuple[pd.Timestamp, pd.Timestamp]]",
    pre_window_days: float = 2.0,
) -> "dict[int, pd.DataFrame]":
    """
    For each satellite, fetch all TLEs within its MEME observation window plus a
    ``pre_window_days`` look-back so the first MEME epoch always has a prior TLE.

    De-duplicates near-identical TLEs (same line1/line2, epoch differing by < 1 s).

    Returns dict mapping norad_id → DataFrame(norad_id, line1, line2, epoch_utc,
    space_track_name) sorted ascending by epoch_utc.
    """
    if not norad_id_to_window:
        return {}

    ids_str = ",".join(str(i) for i in norad_id_to_window)
    all_tles = con.execute(f"""
        SELECT norad_id, line1, line2, epoch_utc,
               object_name AS space_track_name
        FROM raw_tle_archive
        WHERE norad_id IN ({ids_str})
        ORDER BY norad_id, epoch_utc
    """).fetchdf()

    if all_tles.empty:
        return {}

    all_tles["epoch_utc"] = pd.to_datetime(all_tles["epoch_utc"], utc=True)
    pre_delta = pd.Timedelta(days=pre_window_days)

    result: dict[int, pd.DataFrame] = {}
    for norad_id, (t_start, t_end) in norad_id_to_window.items():
        sat = all_tles[all_tles["norad_id"] == norad_id]
        if sat.empty:
            continue

        window = sat[
            (sat["epoch_utc"] >= t_start - pre_delta) &
            (sat["epoch_utc"] <= t_end + pd.Timedelta(hours=1))
        ]
        if window.empty:
            window = sat

        window = window.copy()
        window["_epoch_s"] = window["epoch_utc"].dt.round("s")
        window = (
            window
            .drop_duplicates(subset="_epoch_s")
            .drop(columns="_epoch_s")
            .sort_values("epoch_utc")
            .reset_index(drop=True)
        )
        result[norad_id] = window

    return result


def propagate_tle(
    line1: str,
    line2: str,
    sat_name: str,
    times_utc: pd.Series,
    ts,
) -> pd.DataFrame:
    """
    Propagate a TLE at the given UTC timestamps using Skyfield SGP4.

    Returns DataFrame with columns: t, r_x, r_y, r_z, v_x, v_y, v_z.
    """
    sat = EarthSatellite(line1, line2, name=sat_name, ts=ts)

    t_arr = ts.from_datetimes(
        [dt.to_pydatetime() if dt.tzinfo else dt.replace(tzinfo=timezone.utc).to_pydatetime()
         for dt in times_utc]
    )

    geo = sat.at(t_arr)
    pos = geo.position.km
    vel = geo.velocity.km_per_s

    df = pd.DataFrame({
        "t":   times_utc.values,
        "r_x": pos[0], "r_y": pos[1], "r_z": pos[2],
        "v_x": vel[0], "v_y": vel[1], "v_z": vel[2],
    })
    df["t"] = pd.to_datetime(df["t"], utc=True)
    return df


def propagate_with_best_tles(
    meme_df: pd.DataFrame,
    tle_df: pd.DataFrame,
    sat_name: str,
    ts,
) -> pd.DataFrame:
    """
    Propagate MEME timestamps using the best TLE for each individual timestamp.

    For each MEME state-vector epoch the function selects the most recent TLE
    whose epoch ≤ that timestamp (pre-observation), falling back to the earliest
    available TLE when no prior one exists.  Timestamps are then grouped by their
    assigned TLE and propagated together to avoid O(N) SGP4 object creation.

    Returns a DataFrame with the same columns as propagate_tle, sorted by 't'.
    """
    if tle_df.empty:
        return pd.DataFrame()

    times  = pd.to_datetime(meme_df["t"], utc=True)
    epochs = tle_df["epoch_utc"].values

    idx = np.searchsorted(epochs, times.values, side="right") - 1
    idx = np.clip(idx, 0, len(tle_df) - 1)

    # A2: warn on consecutive TLE epoch gaps > 3 days (coverage hole in the archive)
    if len(epochs) > 1:
        epoch_gaps_days = np.diff(epochs.astype("datetime64[s]").astype(np.int64)) / 86400.0
        for gi in np.where(epoch_gaps_days > 3.0)[0]:
            log.warning(
                "  [%s] A2 TLE gap %.1f days: %s → %s",
                sat_name, epoch_gaps_days[gi],
                pd.Timestamp(epochs[gi]).isoformat(),
                pd.Timestamp(epochs[gi + 1]).isoformat(),
            )

    meme_copy = meme_df.copy()
    meme_copy["_tle_idx"] = idx

    frames: list[pd.DataFrame] = []
    for tle_idx, group in meme_copy.groupby("_tle_idx", sort=True):
        row = tle_df.iloc[int(tle_idx)]
        # C1: warn when a single TLE is extrapolated more than 72 h beyond its epoch
        seg_times   = pd.to_datetime(group["t"], utc=True)
        tle_epoch_t = pd.Timestamp(row["epoch_utc"])
        if tle_epoch_t.tzinfo is None:
            tle_epoch_t = tle_epoch_t.tz_localize("UTC")
        max_prop_h = (seg_times.max() - tle_epoch_t).total_seconds() / 3600.0
        if max_prop_h > 72.0:
            log.warning(
                "  [%s] C1 TLE %s extrapolated %.0f h (>72 h); SGP4 accuracy degraded",
                sat_name,
                tle_epoch_t.strftime("%Y-%m-%dT%H:%M"),
                max_prop_h,
            )
        try:
            chunk = propagate_tle(
                row["line1"], row["line2"], sat_name,
                group["t"].reset_index(drop=True), ts,
            )
            frames.append(chunk)
        except Exception as exc:
            log.debug("  [%s] SGP4 error for TLE %s: %s", sat_name, row["epoch_utc"], exc)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("t").reset_index(drop=True)


def _rtn_basis(
    rx: np.ndarray, ry: np.ndarray, rz: np.ndarray,
    vx: np.ndarray, vy: np.ndarray, vz: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute RTN unit vectors from ECI position/velocity arrays (shape N).

    Returns (R, T, N) each of shape (N, 3) — note the return order is R, T, N:
      R — radial (outward):                r / |r|
      N — normal / cross-track:            h / |h|  where h = r × v
      T — along-track (tangential):        N × R   (completes right-hand frame)
    T = N × R, not R × N, so that (R, T, N) is right-handed for prograde orbits.
    """
    r = np.stack([rx, ry, rz], axis=1)
    v = np.stack([vx, vy, vz], axis=1)
    r_norm = np.linalg.norm(r, axis=1, keepdims=True)
    if np.any(r_norm == 0):
        raise ValueError(
            f"Zero position vector(s) in RTN basis — {int((r_norm[:, 0] == 0).sum())} bad rows"
        )
    R = r / r_norm
    h = np.cross(r, v)
    h_norm = np.linalg.norm(h, axis=1, keepdims=True)
    if np.any(h_norm == 0):
        raise ValueError(
            f"Zero angular momentum in RTN basis — collinear r/v in "
            f"{int((h_norm[:, 0] == 0).sum())} rows"
        )
    N = h / h_norm
    T = np.cross(N, R)
    return R, T, N


def compute_residuals(
    meme: pd.DataFrame,
    tle: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge MEME and TLE DataFrames on timestamp 't' and compute 3-D residuals.
    Returns DataFrame with added columns:
      dr_x, dr_y, dr_z  — ECI position residuals (km)
      dv_x, dv_y, dv_z  — ECI velocity residuals (km/s)
      pos_err_km         — 3-D position error norm (km)
      vel_err_kms        — 3-D velocity error norm (km/s)
      dr_r_km            — radial residual (km)
      dr_t_km            — along-track residual (km)
      dr_n_km            — cross-track residual (km)
    """
    m = meme.rename(columns={c: f"{c}_m" for c in ["r_x","r_y","r_z","v_x","v_y","v_z"]})
    t = tle.rename(columns={c: f"{c}_t" for c in ["r_x","r_y","r_z","v_x","v_y","v_z"]})
    df = pd.merge(m, t, on="t", how="inner")
    if len(m) > 0 and len(df) / len(m) < 0.9:
        log.warning(
            "  Merge retained only %.0f%% of MEME rows — possible timestamp precision mismatch",
            100.0 * len(df) / len(m),
        )

    df["dr_x"] = df["r_x_t"] - df["r_x_m"]
    df["dr_y"] = df["r_y_t"] - df["r_y_m"]
    df["dr_z"] = df["r_z_t"] - df["r_z_m"]
    df["dv_x"] = df["v_x_t"] - df["v_x_m"]
    df["dv_y"] = df["v_y_t"] - df["v_y_m"]
    df["dv_z"] = df["v_z_t"] - df["v_z_m"]
    df["pos_err_km"] = np.sqrt(df["dr_x"]**2 + df["dr_y"]**2 + df["dr_z"]**2)
    df["vel_err_kms"] = np.sqrt(df["dv_x"]**2 + df["dv_y"]**2 + df["dv_z"]**2)

    R, T, N = _rtn_basis(
        df["r_x_m"].values, df["r_y_m"].values, df["r_z_m"].values,
        df["v_x_m"].values, df["v_y_m"].values, df["v_z_m"].values,
    )
    dr = np.stack([df["dr_x"].values, df["dr_y"].values, df["dr_z"].values], axis=1)
    df["dr_r_km"] = (dr * R).sum(axis=1)
    df["dr_t_km"] = (dr * T).sum(axis=1)
    df["dr_n_km"] = (dr * N).sum(axis=1)

    return df


# ── visualisation ─────────────────────────────────────────────────────────────

def _try_import_mpl():
    """Return (plt, mcolors) or (None, None) if matplotlib is unavailable."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
        return plt, mcolors
    except ImportError:
        return None, None


def _apply_style(plt):
    for name in ("seaborn-v0_8-whitegrid", "seaborn-whitegrid", "ggplot"):
        try:
            plt.style.use(name)
            return
        except OSError:
            pass


def _plot_fleet_overview(
    ok: pd.DataFrame,
    plots_dir: Path,
    date_tag: str,
    plt,
    mcolors,
) -> None:
    """2×2 per-satellite summary: age scatter, error histogram, pos/vel scatter, worst-20 bar."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(
        f"TLE vs MEME Ephemeris — Fleet Overview  ({date_tag})",
        fontsize=13, y=1.01,
    )

    pos_min = max(ok["pos_err_mean_km"].min(), 0.01)
    pos_max = ok["pos_err_mean_km"].max()

    ax = axes[0, 0]
    sc = ax.scatter(
        ok["tle_age_days"], ok["pos_err_mean_km"],
        c=ok["pos_err_mean_km"],
        cmap="RdYlGn_r",
        norm=mcolors.LogNorm(vmin=pos_min, vmax=pos_max),
        alpha=0.75, s=35, linewidths=0,
    )
    fig.colorbar(sc, ax=ax, label="Mean pos error (km)")
    ax.set_xlabel("TLE age (days)")
    ax.set_ylabel("Mean position error (km)")
    ax.set_title("TLE Age vs Position Error")
    ax.set_yscale("log")

    ax = axes[0, 1]
    ax.hist(ok["pos_err_mean_km"], bins=40, color="steelblue", edgecolor="white", linewidth=0.4)
    med = ok["pos_err_mean_km"].median()
    ax.axvline(med, color="tomato", linestyle="--", linewidth=1.5,
               label=f"Median  {med:.1f} km")
    ax.set_xlabel("Mean position error (km)")
    ax.set_ylabel("Number of satellites")
    ax.set_title("Distribution of Mean Position Errors")
    ax.legend(fontsize=9)

    ax = axes[1, 0]
    ax.scatter(
        ok["pos_err_mean_km"], ok["vel_err_mean_kms"],
        alpha=0.6, s=25, color="teal", linewidths=0,
    )
    ax.set_xlabel("Mean position error (km)")
    ax.set_ylabel("Mean velocity error (km/s)")
    ax.set_title("Position Error vs Velocity Error")

    ax = axes[1, 1]
    n = min(20, len(ok))
    worst = (
        ok.nlargest(n, "pos_err_mean_km")[["sat_name", "pos_err_mean_km"]]
        .reset_index(drop=True)
    )
    ax.barh(worst["sat_name"][::-1], worst["pos_err_mean_km"][::-1],
            color="tomato", height=0.65)
    ax.set_xlabel("Mean position error (km)")
    ax.set_title(f"Top {n} Worst Satellites")
    ax.tick_params(axis="y", labelsize=7)

    fig.tight_layout()
    out = plots_dir / f"fleet_overview_{date_tag}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Fleet overview → %s", out)


def _plot_timeseries(
    ok: pd.DataFrame,
    resid_df: pd.DataFrame,
    plots_dir: Path,
    date_tag: str,
    plt,
) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(14, 13), sharex=False)
    fig.suptitle(f"Position Error Over Time  ({date_tag})", fontsize=13)

    ax = axes[0]
    fleet = (
        resid_df.groupby("t")["pos_err_km"]
        .agg(
            p05=lambda x: x.quantile(0.05),
            p25=lambda x: x.quantile(0.25),
            p50="median",
            p75=lambda x: x.quantile(0.75),
            p95=lambda x: x.quantile(0.95),
        )
        .reset_index()
        .sort_values("t")
    )
    ax.fill_between(fleet["t"], fleet["p05"], fleet["p95"],
                    alpha=0.15, color="steelblue", label="5–95th pct")
    ax.fill_between(fleet["t"], fleet["p25"], fleet["p75"],
                    alpha=0.30, color="steelblue", label="25–75th pct")
    ax.plot(fleet["t"], fleet["p50"], color="steelblue", linewidth=1.5, label="Median")
    ax.set_ylabel("Position error (km)")
    ax.set_title("Fleet-wide position error (all satellites)")
    ax.legend(fontsize=9)
    ax.set_yscale("log")

    ax = axes[1]
    worst5 = ok.nlargest(5, "pos_err_mean_km")["sat_name"].tolist()
    reds = plt.cm.Reds(np.linspace(0.45, 0.90, len(worst5)))
    for sat, color in zip(worst5, reds):
        sub = resid_df[resid_df["sat_name"] == sat].sort_values("t")
        ax.plot(sub["t"], sub["pos_err_km"], color=color,
                linewidth=0.9, alpha=0.9, label=sat)
    ax.set_ylabel("Position error (km)")
    ax.set_title("Top-5 Worst Satellites")
    ax.legend(fontsize=8, ncol=2)

    ax = axes[2]
    best5 = ok.nsmallest(5, "pos_err_mean_km")["sat_name"].tolist()
    blues = plt.cm.Blues(np.linspace(0.45, 0.90, len(best5)))
    for sat, color in zip(best5, blues):
        sub = resid_df[resid_df["sat_name"] == sat].sort_values("t")
        ax.plot(sub["t"], sub["pos_err_km"], color=color,
                linewidth=0.9, alpha=0.9, label=sat)
    ax.set_ylabel("Position error (km)")
    ax.set_title("Top-5 Best Satellites")
    ax.legend(fontsize=8, ncol=2)

    for ax in axes:
        ax.set_xlabel("UTC time")
        ax.tick_params(axis="x", labelrotation=20)

    fig.tight_layout()
    out = plots_dir / f"timeseries_{date_tag}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Time-series → %s", out)


def _plot_ecdfs(
    resid_df: pd.DataFrame,
    plots_dir: Path,
    date_tag: str,
    plt,
) -> None:
    def ecdf(series: pd.Series):
        x = np.sort(series.dropna().values)
        y = np.arange(1, len(x) + 1) / len(x)
        return x, y

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle(f"Error CDFs  (all state vectors, {date_tag})", fontsize=13)

    ax = axes[0]
    x, y = ecdf(resid_df["pos_err_km"])
    ax.plot(x, y, color="steelblue", linewidth=1.4)
    for pct in (50, 95, 99):
        val = float(np.percentile(x, pct))
        ax.axvline(val, linestyle="--", linewidth=0.9,
                   label=f"P{pct}: {val:.1f} km")
    ax.set_xlabel("Position error (km)")
    ax.set_ylabel("CDF")
    ax.set_title("Position Error CDF")
    ax.legend(fontsize=9)
    ax.set_ylim(0, 1.02)

    ax = axes[1]
    x, y = ecdf(resid_df["vel_err_kms"])
    ax.plot(x, y, color="tomato", linewidth=1.4)
    for pct in (50, 95, 99):
        val = float(np.percentile(x, pct))
        ax.axvline(val, linestyle="--", linewidth=0.9,
                   label=f"P{pct}: {val:.5f} km/s")
    ax.set_xlabel("Velocity error (km/s)")
    ax.set_ylabel("CDF")
    ax.set_title("Velocity Error CDF")
    ax.legend(fontsize=9)
    ax.set_ylim(0, 1.02)

    fig.tight_layout()
    out = plots_dir / f"ecdf_{date_tag}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("ECDF → %s", out)


def _plot_rtn_satellite(
    resid_df: pd.DataFrame,
    sat_name: str,
    plots_dir: Path,
    date_tag: str,
    plt,
) -> None:
    sub = resid_df[resid_df["sat_name"] == sat_name].sort_values("t").copy()
    if sub.empty:
        return

    t0    = sub["t"].iloc[0]
    hours = (sub["t"] - t0).dt.total_seconds() / 3600.0

    fig, axes = plt.subplots(4, 1, figsize=(12, 10), sharex=True)
    fig.suptitle(f"TLE vs MEME — RTN & RSS  {sat_name}  ({date_tag})", fontsize=13)

    panels = [
        ("dr_r_km",    "tab:blue",   "R (km)",   "Radial residual"),
        ("dr_t_km",    "tab:orange", "T (km)",   "Along-track residual"),
        ("dr_n_km",    "tab:green",  "N (km)",   "Cross-track residual"),
        ("pos_err_km", "k",          "RSS (km)", "3D position error norm"),
    ]
    for ax, (col, color, ylabel, title) in zip(axes, panels):
        ax.plot(hours, sub[col], color=color, linewidth=1.0)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(True, alpha=0.4)

    axes[3].set_xlabel(f"Hours from {t0.isoformat()}")
    fig.tight_layout(rect=[0, 0.02, 1, 0.96])

    safe = sat_name.replace(" ", "_")
    out  = plots_dir / f"rtn_{safe}_{date_tag}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("RTN plot → %s", out)


def _plot_maneuver_roc_pr(
    curves: dict,
    metrics: dict,
    plots_dir: Path,
    date_tag: str,
    plt,
) -> None:
    """
    Side-by-side ROC and Precision-Recall curves for fleet-level TLE
    maneuver detection versus MEME ground truth.

    The operating point marker (red dot) shows the TPR/FPR at the natural
    threshold score≥1.0 — i.e., what you get by simply applying the same
    threshold rule used to flag individual events.
    """
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle(
        f"TLE Maneuver Detection vs MEME Ground Truth  ({date_tag})",
        fontsize=12,
    )

    # ── ROC ──────────────────────────────────────────────────────────────────
    ax = axes[0]
    ax.plot(
        curves["fprs"], curves["tprs"],
        color="steelblue", linewidth=2,
        label=f"ROC  AUC = {metrics['roc_auc']:.3f}",
    )
    ax.fill_between(curves["fprs"], curves["tprs"], alpha=0.10, color="steelblue")
    ax.plot([0, 1], [0, 1], "--", color="gray", linewidth=1, label="Random")
    ax.scatter(
        [metrics["fpr_at_thr1"]], [metrics["tpr_at_thr1"]],
        color="tomato", zorder=5, s=70,
        label=(f"Op. point (score≥1)  "
               f"TPR={metrics['tpr_at_thr1']:.3f}  "
               f"FPR={metrics['fpr_at_thr1']:.3f}"),
    )
    ax.set_xlabel("False Positive Rate (FPR)")
    ax.set_ylabel("True Positive Rate (TPR / Recall)")
    ax.set_title("ROC Curve")
    ax.legend(fontsize=8)
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)

    # ── PR ───────────────────────────────────────────────────────────────────
    ax = axes[1]
    ax.plot(
        curves["recalls"], curves["precisions"],
        color="tomato", linewidth=2,
        label=f"PR  AP = {metrics['avg_precision']:.3f}",
    )
    ax.fill_between(curves["recalls"], curves["precisions"], alpha=0.10, color="tomato")
    prev = metrics.get("prevalence", 0.0)
    ax.axhline(prev, linestyle="--", color="gray", linewidth=1,
               label=f"Baseline (prevalence = {prev:.3f})")
    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision")
    ax.set_title("Precision–Recall Curve")
    ax.legend(fontsize=8)
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)

    fig.tight_layout()
    out = plots_dir / f"maneuver_roc_pr_{date_tag}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Maneuver ROC/PR plot → %s", out)


def plot_comparison(
    summary_df: pd.DataFrame,
    resid_df: pd.DataFrame | None,
    out_dir: Path,
    date_tag: str,
    rtn_top: int = 5,
) -> None:
    plt, mcolors = _try_import_mpl()
    if plt is None:
        log.warning("matplotlib not installed — skipping plots (pip install matplotlib).")
        return

    ok = summary_df[summary_df["status"] == "ok"].copy()
    if ok.empty:
        log.warning("No successful comparisons — nothing to plot.")
        return

    plots_dir = out_dir / "plots"
    plots_dir.mkdir(exist_ok=True)
    _apply_style(plt)

    _plot_fleet_overview(ok, plots_dir, date_tag, plt, mcolors)

    if resid_df is not None and not resid_df.empty:
        resid = resid_df.copy()
        resid["t"] = pd.to_datetime(resid["t"], utc=True)
        _plot_timeseries(ok, resid, plots_dir, date_tag, plt)
        _plot_ecdfs(resid, plots_dir, date_tag, plt)

        if rtn_top > 0:
            worst_sats = ok.nlargest(rtn_top, "pos_err_mean_km")["sat_name"].tolist()
            for sat in worst_sats:
                _plot_rtn_satellite(resid, sat, plots_dir, date_tag, plt)


# ── per-satellite processing ──────────────────────────────────────────────────

def process_satellite(
    norad_id: int,
    sat_name: str,
    ephem_files: list[Path],
    sat_tle_df: pd.DataFrame,
    ts,
    save_residuals: bool,
) -> tuple[dict, pd.DataFrame | None]:
    """
    Load ephemeris (one or many files), propagate with per-timestamp best TLE,
    compute residuals.

    ``sat_name`` is the SpaceX-internal MEME API name (e.g. "STARLINK-32283").
    ``sat_tle_df["space_track_name"]`` is Space-Track's official label
    (e.g. "STARLINK-1008") — a different XXXX number, unrelated to the NORAD ID.
    Match satellites across data sources using norad_id only.

    Returns (summary_dict, residuals_df | None).
    """
    meme_df = load_all_meme(sat_name, ephem_files)
    n_files = len(ephem_files)

    if meme_df.empty:
        return {"norad_id": norad_id, "sat_name": sat_name, "status": "empty_ephemeris",
                "n_files": n_files}, None

    ephem_start    = meme_df["t"].min()
    ephem_end      = meme_df["t"].max()
    ephem_span_days = (ephem_end - ephem_start).total_seconds() / 86400.0

    if sat_tle_df.empty:
        return {"norad_id": norad_id, "sat_name": sat_name, "status": "no_tle",
                "n_files": n_files}, None

    before  = sat_tle_df[sat_tle_df["epoch_utc"] <= ephem_start]
    rep_tle = before.iloc[-1] if not before.empty else sat_tle_df.iloc[0]

    tle_epoch = pd.Timestamp(rep_tle["epoch_utc"])
    if tle_epoch.tzinfo is None:
        tle_epoch = tle_epoch.tz_localize("UTC")
    tle_age_days = (ephem_start - tle_epoch).total_seconds() / 86400.0
    if tle_age_days < 0:
        log.warning(
            "  [%s] representative TLE epoch is %.1f days AFTER ephemeris start",
            sat_name, -tle_age_days,
        )

    try:
        prop_df = propagate_with_best_tles(meme_df, sat_tle_df, sat_name, ts)
    except Exception as exc:
        log.warning("  [%s] propagation error: %s", sat_name, exc)
        return {"norad_id": norad_id, "sat_name": sat_name, "status": f"sgp4_error: {exc}",
                "n_files": n_files}, None

    if prop_df.empty:
        return {"norad_id": norad_id, "sat_name": sat_name, "status": "no_propagation",
                "n_files": n_files}, None

    res = compute_residuals(meme_df, prop_df)
    if res.empty:
        return {"norad_id": norad_id, "sat_name": sat_name, "status": "no_match",
                "n_files": n_files}, None

    st_name = rep_tle.get("space_track_name")
    space_track_name = (
        None if (st_name is None or (isinstance(st_name, float) and pd.isna(st_name)))
        else str(st_name)
    )

    summary = {
        "norad_id":          norad_id,
        "sat_name":          sat_name,
        "space_track_name":  space_track_name,
        "status":            "ok",
        "n_files":           n_files,
        "n_points":          len(res),
        "ephem_span_days":   round(ephem_span_days, 2),
        "n_tles_used":       int(sat_tle_df["epoch_utc"].nunique()),
        "tle_epoch":         tle_epoch.isoformat(),
        "tle_age_days":      round(tle_age_days, 2),
        "ephem_start":       ephem_start.isoformat(),
        "ephem_end":         ephem_end.isoformat(),
        "pos_err_mean_km":   round(res["pos_err_km"].mean(), 3),
        "pos_err_std_km":    round(res["pos_err_km"].std(), 3),
        "pos_err_max_km":    round(res["pos_err_km"].max(), 3),
        "vel_err_mean_kms":  round(res["vel_err_kms"].mean(), 6),
        "vel_err_std_kms":   round(res["vel_err_kms"].std(), 6),
        "vel_err_max_kms":   round(res["vel_err_kms"].max(), 6),
    }

    if save_residuals:
        res.insert(0, "sat_name", sat_name)
        res.insert(0, "norad_id", norad_id)
        tle_epochs_utc = pd.to_datetime(sat_tle_df["epoch_utc"], utc=True)
        epochs_arr     = tle_epochs_utc.values
        meme_times     = pd.to_datetime(res["t"], utc=True).values
        idx            = np.searchsorted(epochs_arr, meme_times, side="right") - 1
        idx            = np.clip(idx, 0, len(sat_tle_df) - 1)
        used_epochs    = tle_epochs_utc.iloc[idx].reset_index(drop=True)
        res_times      = pd.to_datetime(res["t"], utc=True).reset_index(drop=True)
        res["tle_epoch"]    = used_epochs.dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        res["tle_age_days"] = (
            (res_times - used_epochs).dt.total_seconds() / 86400.0
        ).round(2)
        # C2: hybrid condition — age AND positional accuracy both must be acceptable
        res["valid_for_training"] = (res["tle_age_days"] <= 2.0) & (res["pos_err_km"] <= 50.0)
        return summary, res

    return summary, None


# ── maneuver detection orchestration ─────────────────────────────────────────

def run_maneuver_detection(
    sat_entries: list,
    tle_pool: dict,
    norad_id_to_window: dict,
    out_dir: Path,
    date_tag: str,
    no_plot: bool,
    min_da: float = 0.0,
) -> None:
    """
    Orchestrate per-satellite maneuver detection and fleet-level evaluation.

    For each satellite:
      1. Run the MEME detector (file-snapshot element differences).
      2. Run the TLE detector (consecutive TLE element differences),
         restricted to the same date coverage as the MEME data.
      3. Bin both event lists onto a shared 8 h grid.
      4. Accumulate (y_true, y_score) pairs for fleet-level metrics.
      5. Compute per-satellite metrics where there are both positive and
         negative bins (satellites with no maneuver events are valid negatives
         but cannot contribute ROC/AUC alone).

    Fleet-level metrics treat each (satellite, 8 h bin) pair as an
    independent observation.  This is appropriate because the bins are
    short relative to maneuver intervals and there is no cross-satellite
    correlation in the detection errors.

    Saves:
        meme_maneuvers_{date}.csv         — all MEME transition events
        tle_maneuvers_{date}.csv          — all TLE transition events
        maneuver_classification_{date}.csv — per-(sat, bin) (y_true, y_score)
        maneuver_sat_metrics_{date}.csv   — per-satellite scalar metrics
        plots/maneuver_roc_pr_{date}.png  — fleet ROC + PR curves
    """
    log.info("=== Orbital Maneuver Detection ===")

    all_meme_ev:   list[pd.DataFrame] = []
    all_tle_ev:    list[pd.DataFrame] = []
    all_cls_data:  list[pd.DataFrame] = []
    per_sat_rows:  list[dict]          = []

    for norad_id, sat_name, ephem_files in sat_entries:
        tle_df = tle_pool.get(norad_id, pd.DataFrame())
        window = norad_id_to_window.get(norad_id)
        if window is None:
            continue

        t_start, t_end = window

        def _to_utc(ts) -> pd.Timestamp:
            t = pd.Timestamp(ts)
            return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")

        t_start = _to_utc(t_start)
        t_end   = _to_utc(t_end)

        # ── MEME detection ────────────────────────────────────────────────────
        meme_ev = detect_meme_maneuvers(sat_name, ephem_files)
        if not meme_ev.empty:
            all_meme_ev.append(meme_ev)

        # ── TLE detection ─────────────────────────────────────────────────────
        tle_ev = detect_tle_maneuvers(sat_name, tle_df, t_start, t_end)
        if not tle_ev.empty:
            all_tle_ev.append(tle_ev)

        # ── 8 h classification grid ───────────────────────────────────────────
        cls_df = build_classification_dataset(meme_ev, tle_ev, t_start, t_end, min_da=min_da)
        if cls_df.empty:
            continue
        cls_df.insert(0, "norad_id", norad_id)
        cls_df.insert(1, "sat_name", sat_name)
        all_cls_data.append(cls_df)

        # ── per-satellite metrics (only when both classes present) ────────────
        yt = cls_df["y_true"].values.astype(int)
        ys = cls_df["y_score"].values.astype(float)
        if yt.sum() > 0 and (1 - yt).sum() > 0:
            sat_met = compute_detection_metrics(yt, ys)
            sat_met["sat_name"] = sat_name
            sat_met["norad_id"] = norad_id
            per_sat_rows.append(sat_met)

    if not all_cls_data:
        log.warning("Maneuver detection: no classification data — "
                    "check that satellites have ≥2 ephemeris files each.")
        return

    # ── save per-satellite event CSVs ─────────────────────────────────────────
    meme_cat = pd.concat(all_meme_ev, ignore_index=True) if all_meme_ev else pd.DataFrame()
    tle_cat  = pd.concat(all_tle_ev,  ignore_index=True) if all_tle_ev  else pd.DataFrame()

    if not meme_cat.empty:
        p = out_dir / f"meme_maneuvers_{date_tag}.csv"
        meme_cat.to_csv(p, index=False)
        log.info("MEME maneuver events → %s  (%d rows)", p, len(meme_cat))

    if not tle_cat.empty:
        p = out_dir / f"tle_maneuvers_{date_tag}.csv"
        tle_cat.to_csv(p, index=False)
        log.info("TLE  maneuver events → %s  (%d rows)", p, len(tle_cat))

    # ── fleet classification dataset ──────────────────────────────────────────
    fleet_cls = pd.concat(all_cls_data, ignore_index=True)
    cls_path  = out_dir / f"maneuver_classification_{date_tag}.csv"
    fleet_cls.to_csv(cls_path, index=False)
    log.info("Classification dataset → %s  (%d rows)", cls_path, len(fleet_cls))

    # ── fleet-level metrics ───────────────────────────────────────────────────
    y_true_all  = fleet_cls["y_true"].values.astype(int)
    y_score_all = fleet_cls["y_score"].values.astype(float)

    global_metrics = compute_detection_metrics(y_true_all, y_score_all)
    global_curves  = _compute_curves(y_true_all, y_score_all)

    # ── per-satellite metrics CSV ─────────────────────────────────────────────
    per_sat_df = pd.DataFrame(per_sat_rows) if per_sat_rows else pd.DataFrame()
    if not per_sat_df.empty:
        p = out_dir / f"maneuver_sat_metrics_{date_tag}.csv"
        per_sat_df.to_csv(p, index=False)
        log.info("Per-satellite metrics → %s  (%d satellites)", p, len(per_sat_df))

    # ── console report ────────────────────────────────────────────────────────
    n_sats        = fleet_cls["sat_name"].nunique()
    n_bins        = len(fleet_cls)
    n_pos         = int(y_true_all.sum())
    meme_flagged  = int(meme_cat["flagged"].sum()) if not meme_cat.empty else 0
    tle_flagged   = int(tle_cat["flagged"].sum())  if not tle_cat.empty  else 0
    meme_trans    = len(meme_cat)
    tle_trans     = len(tle_cat)

    print(f"\n{'='*65}")
    print(f"  Orbital Maneuver Detection — TLE vs MEME Ground Truth")
    print(f"  Run date: {date_tag}")
    gt_label = f"|da| ≥ {min_da} km" if min_da > 0.0 else "any flagged indicator (score > 1)"
    print(f"  Ground-truth criterion : {gt_label}")
    print(f"{'='*65}")
    print(f"\n  --- Event counts ---")
    print(f"  Satellites analysed   : {n_sats}")
    print(f"  MEME transitions      : {meme_trans:5d}  flagged: {meme_flagged}")
    print(f"  TLE  transitions      : {tle_trans:5d}  flagged: {tle_flagged}")
    print(f"  8-hour bins (total)   : {n_bins:5d}  positive: {n_pos}"
          f"  ({100.0 * n_pos / n_bins:.1f}%)")

    print(f"\n  --- TLE Detection Performance (MEME = Ground Truth) ---")
    print(f"  TPR  (Recall)     @ score≥1.0 : {global_metrics['tpr_at_thr1']:.4f}")
    print(f"  FPR  (False Alarm)@ score≥1.0 : {global_metrics['fpr_at_thr1']:.4f}")
    print(f"  ROC-AUC                       : {global_metrics['roc_auc']:.4f}")
    print(f"  Average Precision (AP)        : {global_metrics['avg_precision']:.4f}")
    print(f"  F1-score (positive class)     : {global_metrics['f1_positive']:.4f}")
    print(f"  F1-score (macro, both classes): {global_metrics['f1_macro']:.4f}")
    print(f"  Youden-optimal threshold      : {global_metrics['optimal_threshold']:.4f}")
    print(f"  Class prevalence (pos. rate)  : {global_metrics['prevalence']:.4f}")

    if not per_sat_df.empty:
        has_auc = per_sat_df[per_sat_df["roc_auc"].notna() & (per_sat_df["n_pos"] > 0)]
        if not has_auc.empty:
            print(f"\n  --- Per-satellite AUC "
                  f"({len(has_auc)} sats with maneuver events) ---")
            print(f"    mean : {has_auc['roc_auc'].mean():.4f}")
            print(f"    std  : {has_auc['roc_auc'].std():.4f}")
            print(f"    min  : {has_auc['roc_auc'].min():.4f}  "
                  f"({has_auc.loc[has_auc['roc_auc'].idxmin(), 'sat_name']})")
            print(f"    max  : {has_auc['roc_auc'].max():.4f}  "
                  f"({has_auc.loc[has_auc['roc_auc'].idxmax(), 'sat_name']})")

        # Top-10 satellites by maneuver event count for situational awareness
        meme_by_sat = (
            meme_cat[meme_cat["flagged"]]
            .groupby("sat_name")
            .size()
            .rename("meme_events")
            .reset_index()
            .sort_values("meme_events", ascending=False)
            .head(10)
        ) if not meme_cat.empty else pd.DataFrame()

        if not meme_by_sat.empty:
            print(f"\n  Top-10 most active satellites (MEME flagged events):")
            print(meme_by_sat.to_string(index=False))

    print(f"\n  Classification dataset : {cls_path}")
    print(f"  Note: fleet-level AUC weights by coverage length (more bins = more "
          f"influence); per-satellite AUC in maneuver_sat_metrics_{date_tag}.csv "
          f"is more interpretable for individual satellite comparisons.")

    # ── plot ──────────────────────────────────────────────────────────────────
    if not no_plot and global_curves is not None:
        plt_mod, _ = _try_import_mpl()
        if plt_mod is not None:
            _apply_style(plt_mod)
            plots_dir = out_dir / "plots"
            plots_dir.mkdir(exist_ok=True)
            _plot_maneuver_roc_pr(
                global_curves, global_metrics, plots_dir, date_tag, plt_mod
            )
        else:
            log.warning("matplotlib unavailable — skipping maneuver ROC/PR plot.")


# ── main ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compare TLE propagation vs Starlink MEME ephemeris, "
                    "with optional orbital maneuver detection and evaluation."
    )
    p.add_argument("--data-root", type=Path, default=Path("data"),
                   help="Root data directory (default: data/)")
    p.add_argument("--db", type=Path, default=Path("space_db.duckdb"),
                   help="DuckDB database path (default: space_db.duckdb)")
    p.add_argument("--registry", type=Path, default=None,
                   help="URL registry CSV (default: {data-root}/url_registry.csv)")
    p.add_argument("--out-dir", type=Path, default=None,
                   help="Output directory (default: {data-root}/comparison/)")
    p.add_argument("--max-sats", type=int, default=None,
                   help="Limit to first N satellites (for testing).")
    p.add_argument("--no-residuals", action="store_true",
                   help="Skip writing the per-point residuals CSV (much faster).")
    p.add_argument("--no-plot", action="store_true",
                   help="Skip generating comparison plots.")
    p.add_argument("--rtn-top", type=int, default=5, metavar="N",
                   help="Generate RTN plots for worst-N satellites (default: 5, 0=skip).")
    p.add_argument("--latest-only", action="store_true",
                   help="Process only the latest ephemeris file per satellite "
                        "(legacy single-file mode; default processes all files).")
    p.add_argument("--maneuver-detection", action="store_true",
                   help="Run orbital maneuver detection from both TLE and MEME "
                        "independently, use MEME events as ground truth, and "
                        "compute TPR/FPR/ROC-AUC/AP/F1 for TLE detection quality.")
    p.add_argument("--maneuver-min-da", type=float, default=0.0, metavar="KM",
                   help="Minimum |da| (km) for a MEME transition to count as a "
                        "positive ground-truth event.  0 (default) = any flagged "
                        "indicator; 1 = small+; 5 = medium+; 10 = large only.")
    return p


def main() -> int:
    args = build_parser().parse_args()

    registry_csv = args.registry or (args.data_root / "url_registry.csv")
    raw_root     = args.data_root / "raw"
    out_dir      = args.out_dir   or (args.data_root / "comparison")
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.db.exists():
        log.error("Database not found: %s", args.db)
        return 1
    if not registry_csv.exists():
        log.error("Registry not found: %s", registry_csv)
        return 1

    # ── build satellite list ───────────────────────────────────────────────────
    reg = load_registry(registry_csv)
    sat_entries: list[tuple[int, str, list[Path]]] = []
    for norad_id, row in reg.iterrows():
        sat_name = row["sat_name"]
        sat_dir  = raw_root / sat_name
        if not sat_dir.is_dir():
            continue
        if args.latest_only:
            ephem = find_latest_ephemeris(sat_dir)
            files = [ephem] if ephem else []
        else:
            files = find_all_ephemeris_files(sat_dir)
        if files:
            sat_entries.append((norad_id, sat_name, files))

    log.info(
        "Found %d satellites with local ephemeris files (%s mode).",
        len(sat_entries),
        "latest-only" if args.latest_only else "all-files",
    )

    if args.max_sats:
        sat_entries = sat_entries[: args.max_sats]
        log.info("Limiting to %d satellites (--max-sats).", args.max_sats)

    # ── pre-scan: determine observation window (start, end) per satellite ─────
    log.info("Pre-scanning ephemeris files for observation windows …")
    norad_id_to_window: dict[int, tuple[pd.Timestamp, pd.Timestamp]] = {}
    fallback_time = pd.Timestamp.now(tz="UTC")
    for norad_id, sat_name, files in sat_entries:
        try:
            if args.latest_only or len(files) == 1:
                _, df = parse_ephemeris_file(files[0], sat_id=sat_name)
                t_series = pd.to_datetime(df["t"], utc=True) if not df.empty else pd.Series([fallback_time])
                norad_id_to_window[norad_id] = (t_series.min(), t_series.max())
            else:
                _, df0 = parse_ephemeris_file(files[0],  sat_id=sat_name)
                _, df1 = parse_ephemeris_file(files[-1], sat_id=sat_name)
                t0 = pd.to_datetime(df0["t"], utc=True).min() if not df0.empty else fallback_time
                t1 = pd.to_datetime(df1["t"], utc=True).max() if not df1.empty else fallback_time
                norad_id_to_window[norad_id] = (t0, t1)
        except Exception:
            norad_id_to_window[norad_id] = (fallback_time, fallback_time)

    # ── batch-query TLEs ──────────────────────────────────────────────────────
    con = duckdb.connect(database=str(args.db), read_only=True)
    if args.latest_only:
        norad_id_to_start = {nid: w[0] for nid, w in norad_id_to_window.items()}
        _single_tle_df = query_best_tle(con, norad_id_to_start)
        tle_pool: dict[int, pd.DataFrame] = {
            int(row["norad_id"]): pd.DataFrame([row])
            for _, row in _single_tle_df.iterrows()
        }
        n_found = len(tle_pool)
    else:
        tle_pool = query_tles_in_range(con, norad_id_to_window)
        n_found  = len(tle_pool)
    con.close()

    log.info("TLE pool ready for %d / %d satellites.", n_found, len(sat_entries))

    # A1: pre-scan for satellites whose newest TLE epoch is >3 days before MEME end.
    # These satellites will have large residuals; the report guides targeted re-fetch.
    _stale_sats: list[dict] = []
    for _nid, _sname, _files in sat_entries:
        _sat_tles = tle_pool.get(_nid)
        if _sat_tles is None or _sat_tles.empty:
            continue
        _t_end  = norad_id_to_window[_nid][1]
        _newest = pd.Timestamp(_sat_tles["epoch_utc"].max())
        if _newest.tzinfo is None:
            _newest = _newest.tz_localize("UTC")
        _gap_days = (_t_end - _newest).total_seconds() / 86400.0
        if _gap_days > 3.0:
            _stale_sats.append({
                "norad_id":        _nid,
                "sat_name":        _sname,
                "newest_tle_epoch": _newest.isoformat(),
                "meme_end":        _t_end.isoformat(),
                "gap_days":        round(_gap_days, 1),
            })
    if _stale_sats:
        log.warning(
            "A1: %d/%d satellites have stale TLEs (newest TLE >3 days before MEME end) — "
            "run download_TLE_unified.py to refresh before next comparison.",
            len(_stale_sats), len(sat_entries),
        )

    # ── Skyfield timescale (created once) ─────────────────────────────────────
    ts = skyfield_load.timescale()

    # ── process each satellite ────────────────────────────────────────────────
    summaries:       list[dict]         = []
    residual_frames: list[pd.DataFrame] = []

    for idx, (norad_id, sat_name, files) in enumerate(sat_entries, 1):
        sat_tle_df = tle_pool.get(norad_id, pd.DataFrame())

        if sat_tle_df.empty:
            log.debug("  [%s] no TLE in DB — skipped.", sat_name)
            summaries.append({
                "norad_id": norad_id, "sat_name": sat_name,
                "status": "no_tle", "n_files": len(files),
            })
            continue

        rep_epoch = pd.Timestamp(sat_tle_df["epoch_utc"].iloc[0]).strftime("%Y-%m-%d")
        log.info(
            "[%d/%d] %s  (NORAD %d)  files=%d  TLEs=%d  rep-epoch=%s",
            idx, len(sat_entries), sat_name, norad_id,
            len(files), len(sat_tle_df), rep_epoch,
        )

        summary, res = process_satellite(
            norad_id, sat_name, files, sat_tle_df, ts,
            save_residuals=not args.no_residuals,
        )
        summaries.append(summary)
        if res is not None:
            residual_frames.append(res)

    # ── save outputs ──────────────────────────────────────────────────────────
    date_tag = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    summary_df   = pd.DataFrame(summaries)
    summary_path = out_dir / f"summary_{date_tag}.csv"
    summary_df.to_csv(summary_path, index=False)
    log.info("Summary saved → %s", summary_path)

    resid_df = None
    if not args.no_residuals and residual_frames:
        resid_df  = pd.concat(residual_frames, ignore_index=True)
        resid_path = out_dir / f"residuals_{date_tag}.csv"
        resid_df.to_csv(resid_path, index=False)
        log.info("Residuals saved → %s (%d rows)", resid_path, len(resid_df))

    # A1: write stale TLE report
    stale_path = None
    if _stale_sats:
        stale_df   = pd.DataFrame(_stale_sats).sort_values("gap_days", ascending=False)
        stale_path = out_dir / f"stale_tle_report_{date_tag}.csv"
        stale_df.to_csv(stale_path, index=False)
        log.info("Stale TLE report → %s (%d satellites)", stale_path, len(_stale_sats))

    # ── console summary ───────────────────────────────────────────────────────
    ok = summary_df[summary_df["status"] == "ok"]
    print("\n=== TLE vs MEME Ephemeris Comparison ===")
    print(f"  Satellites processed : {len(sat_entries)}")
    print(f"  With TLE             : {n_found}")
    print(f"  Successfully compared: {len(ok)}")

    if not ok.empty:
        print(f"\n  TLE age (days to ephemeris start)")
        print(f"    mean : {ok['tle_age_days'].mean():.1f}")
        print(f"    min  : {ok['tle_age_days'].min():.1f}")
        print(f"    max  : {ok['tle_age_days'].max():.1f}")

        print(f"\n  3-D Position error (km)")
        print(f"    mean of per-sat means : {ok['pos_err_mean_km'].mean():.1f}")
        print(f"    mean of per-sat max   : {ok['pos_err_max_km'].mean():.1f}")
        print(f"    worst satellite max   : {ok['pos_err_max_km'].max():.1f}")
        print(f"    best  satellite mean  : {ok['pos_err_mean_km'].min():.3f}")

        print(f"\n  3-D Velocity error (km/s)")
        print(f"    mean of per-sat means : {ok['vel_err_mean_kms'].mean():.5f}")
        print(f"    worst satellite max   : {ok['vel_err_max_kms'].max():.5f}")

        has_st = ok["space_track_name"].notna().any()
        cols   = ["norad_id", "sat_name"]
        if has_st:
            cols.append("space_track_name")
        cols += ["tle_age_days", "pos_err_mean_km", "pos_err_max_km", "vel_err_mean_kms"]
        print("\n  Top-10 worst satellites (mean pos error):")
        print(ok.nlargest(10, "pos_err_mean_km")[cols].to_string(index=False))
        print("\n  Top-10 best satellites (mean pos error):")
        print(ok.nsmallest(10, "pos_err_mean_km")[cols].to_string(index=False))

    non_ok = summary_df[summary_df["status"] != "ok"]
    if not non_ok.empty:
        print(f"\n  Non-OK satellites ({len(non_ok)}):")
        print(non_ok[["norad_id", "sat_name", "status"]].to_string(index=False))

    print(f"\n  Summary CSV : {summary_path}")
    if resid_df is not None:
        print(f"  Residuals   : {resid_path}")
    if stale_path is not None:
        worst = _stale_sats[0]  # already sorted descending by gap_days
        print(f"\n  [A1] {len(_stale_sats)} satellites have stale TLEs (newest TLE >3 days before MEME end)")
        print(f"       Worst : {worst['sat_name']}  gap={worst['gap_days']:.1f} d  "
              f"newest-TLE={worst['newest_tle_epoch'][:10]}  MEME-end={worst['meme_end'][:10]}")
        print(f"       Report: {stale_path}")
        print(f"       Refresh: python download_TLE_unified.py --mode spacetrack")

    # ── residual plots ────────────────────────────────────────────────────────
    if not args.no_plot:
        plot_comparison(summary_df, resid_df, out_dir, date_tag, rtn_top=args.rtn_top)

    # ── maneuver detection (optional) ─────────────────────────────────────────
    if args.maneuver_detection:
        run_maneuver_detection(
            sat_entries       = sat_entries,
            tle_pool          = tle_pool,
            norad_id_to_window= norad_id_to_window,
            out_dir           = out_dir,
            date_tag          = date_tag,
            no_plot           = args.no_plot,
            min_da            = args.maneuver_min_da,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
