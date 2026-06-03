#!/usr/bin/env python3
"""
GEO Satellite Maneuver Detection from TLE Data.

Core principle: SGP4 propagation is abandoned entirely for GEO.
All detection is performed on raw Keplerian elements — no orbit propagation.

Observables computed directly from TLE elements:
  λ       — mean sub-satellite longitude  (East-West position)
  dλ/dt   — longitude drift rate          (EW maneuver signature)
  i       — inclination                   (NS maneuver signature)
  Δi      — inclination step              (NS burn detection)
  Δn      — mean motion deviation from GEO nominal

Detection algorithms (no SGP4 used):
  A. EW maneuver   — drift rate sign change or sudden |Δn| spike
  B. NS maneuver   — negative inclination step (Δi < threshold)
  C. Repositioning — sustained longitude drift beyond station-keeping box
  D. Disposal      — semi-major axis permanently above graveyard threshold
  E. TLE gap       — publication silence > GAP_DAYS → unknown event

Usage:
  python detect_geo_maneuvers.py
  python detect_geo_maneuvers.py --db space_db.duckdb --out data/geo_maneuvers
  python detect_geo_maneuvers.py --norad 36032 41552   # specific satellites
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("geo_maneuver")

# ── Physical constants ─────────────────────────────────────────────────────────
GM_EARTH    = 3.986_004_418e14   # m³ s⁻²
R_EARTH_KM  = 6378.137
J2          = 1.082_626_68e-3
N_GEO       = 1.002_737_909_35   # rev/day  (mean solar day basis, ~1 sidereal rev/day)
SMA_GEO_KM  = 42_164.17          # km

# ── Detection thresholds ───────────────────────────────────────────────────────
GEO_SMA_MIN_KM   = 40_000.0      # filter: must be above this to be GEO candidate
GEO_SMA_MAX_KM   = 45_000.0
GEO_INC_MAX_DEG  = 15.0          # max inclination for inclusion

EW_DRIFT_THRESHOLD_DEG_DAY  = 0.020  # |Δ(dλ/dt)| > this  → EW candidate
EW_SIGN_FLIP_REQUIRED       = True   # must reverse direction to confirm EW

NS_INC_STEP_THRESHOLD_DEG   = -0.003 # Δi < this  → NS maneuver candidate
NS_RAAN_STEP_THRESHOLD_DEG  =  0.10  # |ΔΩ - J2_correction| → NS confirmation

REPO_LONGITUDE_BOX_DEG      = 1.0    # |λ - λ_nominal| > this → repositioning
DISPOSAL_SMA_THRESHOLD_KM   = 42_300.0  # above this = graveyard candidate

TLE_GAP_THRESHOLD_DAYS      = 4.0    # gap > this → unknown event

# Deduplication: TLEs closer than this (same epoch re-uploaded) are merged
TLE_DEDUP_MIN_DT_DAYS       = 0.04   # 1 hour — below this, keep only the first
# Minimum inter-TLE interval for computing drift rate (avoids near-zero dt)
MIN_DT_FOR_DRIFT_DAYS       = 0.05   # 1.2 hours

# ── GMST / longitude ───────────────────────────────────────────────────────────

def gmst_deg(jd: float | np.ndarray) -> float | np.ndarray:
    """Greenwich Mean Sidereal Time in degrees [0, 360) for Julian Date(s)."""
    T = (jd - 2_451_545.0)
    gmst = 280.460_618_37 + 360.985_647_366_29 * T
    return gmst % 360.0


def mean_longitude_deg(raan: np.ndarray, argp: np.ndarray,
                        ma: np.ndarray, jd: np.ndarray) -> np.ndarray:
    """
    GEO sub-satellite mean longitude [degrees, wrapped to (-180, 180]].

    λ = (Ω + ω + M) − GMST(JD)

    All inputs in degrees.  JD is the TLE epoch Julian Date.
    For a stationary GEO this is nearly constant; drift and reversals
    indicate EW manoeuvres.
    """
    raw = (raan + argp + ma - gmst_deg(jd)) % 360.0
    # Wrap to (-180, 180]
    return np.where(raw > 180.0, raw - 360.0, raw)


def j2_raan_drift_deg_per_day(sma_km: float, inc_deg: float,
                               ecc: float) -> float:
    """
    Secular J2 RAAN drift rate [degrees/day].
    Negative for prograde orbits (Ω drifts westward).
    """
    a_m = sma_km * 1_000.0
    n_rad_s = np.sqrt(GM_EARTH / a_m**3)        # mean motion rad/s
    cos_i = np.cos(np.deg2rad(inc_deg))
    factor = -1.5 * J2 * n_rad_s * (R_EARTH_KM * 1_000.0 / a_m)**2
    drift_rad_s = factor * cos_i / (1 - ecc**2)**2
    return np.rad2deg(drift_rad_s) * 86_400.0    # deg/day


# ── Data loading ───────────────────────────────────────────────────────────────

def load_geo_tles(db_path: str, norad_ids: list[int] | None = None) -> pd.DataFrame:
    """
    Load GEO TLE records from raw_tle_archive.

    Returns DataFrame sorted by (norad_id, epoch_jd) with columns:
      norad_id, object_name, epoch_utc, epoch_jd,
      sma_km, inclination_deg, raan_deg, argp_deg,
      mean_anomaly_deg, mean_motion, eccentricity
    """
    import duckdb

    con = duckdb.connect(db_path, read_only=True)

    id_filter = ""
    if norad_ids:
        ids_str = ", ".join(str(i) for i in norad_ids)
        id_filter = f"AND norad_id IN ({ids_str})"

    q = f"""
    SELECT
        norad_id,
        COALESCE(object_name, 'NORAD-' || CAST(norad_id AS VARCHAR)) AS object_name,
        epoch_utc,
        epoch_jd,
        sma_km,
        inclination_deg,
        raan_deg,
        argp_deg,
        mean_anomaly_deg,
        mean_motion,
        eccentricity
    FROM raw_tle_archive
    WHERE sma_km        BETWEEN {GEO_SMA_MIN_KM} AND {GEO_SMA_MAX_KM}
      AND inclination_deg < {GEO_INC_MAX_DEG}
      {id_filter}
    ORDER BY norad_id, epoch_jd
    """
    df = con.execute(q).df()
    con.close()

    df["epoch_utc"] = pd.to_datetime(df["epoch_utc"], utc=True, format="mixed")

    # Deduplicate: multiple downloads of the same TLE produce near-identical
    # epoch_jd values (dt ~ nanoseconds).  Keep the first per satellite per
    # coarse epoch bucket (1 hour resolution).
    df["_epoch_bucket"] = (df["epoch_jd"] / TLE_DEDUP_MIN_DT_DAYS).astype(int)
    df = (df
          .sort_values(["norad_id", "epoch_jd"])
          .drop_duplicates(subset=["norad_id", "_epoch_bucket"])
          .drop(columns=["_epoch_bucket"])
          .reset_index(drop=True))

    log.info("Loaded %d TLE records for %d GEO satellites (after dedup)",
             len(df), df["norad_id"].nunique())
    return df


# ── Per-satellite feature computation ─────────────────────────────────────────

def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    For a single satellite's TLE time-series, compute all observables.

    Input df columns: epoch_jd, sma_km, inclination_deg, raan_deg,
                      argp_deg, mean_anomaly_deg, mean_motion, eccentricity

    Returns df with additional columns:
      lambda_deg      — mean longitude (°)
      dt_days         — time since previous TLE (days)
      dlambda_dt      — longitude drift rate (°/day)
      dn_rev_day      — mean-motion deviation from N_GEO (rev/day)
      delta_i         — inclination change from previous TLE (°)
      delta_raan      — RAAN change from previous TLE (°)
      j2_raan_delta   — expected J2 RAAN change over dt_days (°)
      delta_raan_res  — RAAN residual after removing J2 (°)
    """
    df = df.copy().reset_index(drop=True)

    df["lambda_deg"] = mean_longitude_deg(
        df["raan_deg"].values,
        df["argp_deg"].values,
        df["mean_anomaly_deg"].values,
        df["epoch_jd"].values,
    )

    df["dt_days"] = df["epoch_jd"].diff()          # NaN for first row

    # Longitude drift rate [°/day] — forward-differenced.
    # Suppress pairs where dt < MIN_DT_FOR_DRIFT_DAYS: remaining near-duplicates
    # after bucket dedup produce |dλ/dt| ≈ Earth rotation rate (±361 °/day).
    dl = df["lambda_deg"].diff()
    dl = ((dl + 180.0) % 360.0) - 180.0          # unwrap ±180°
    valid_dt = df["dt_days"] >= MIN_DT_FOR_DRIFT_DAYS
    df["dlambda_dt"] = np.where(valid_dt, dl / df["dt_days"], np.nan)

    df["dn_rev_day"] = df["mean_motion"] - N_GEO

    # Inclination change
    df["delta_i"] = df["inclination_deg"].diff()

    # RAAN change and J2 residual
    draan = df["raan_deg"].diff()
    draan = ((draan + 180.0) % 360.0) - 180.0     # unwrap
    df["delta_raan"] = draan

    j2 = df.apply(
        lambda r: j2_raan_drift_deg_per_day(r["sma_km"], r["inclination_deg"],
                                             r["eccentricity"])
                  * r["dt_days"] if pd.notna(r["dt_days"]) else np.nan,
        axis=1,
    )
    df["j2_raan_delta"]  = j2
    df["delta_raan_res"] = df["delta_raan"] - df["j2_raan_delta"]

    return df


# ── Detection algorithms ───────────────────────────────────────────────────────

def detect_ew(df: pd.DataFrame) -> pd.DataFrame:
    """
    Algorithm A: East-West maneuver detection.

    Conditions (both required for 'confirmed'):
      1. Sudden |Δ(dλ/dt)| > EW_DRIFT_THRESHOLD
      2. Sign of dλ/dt reverses (drift direction flips)

    A large |Δ(dλ/dt)| without sign flip = weak candidate
    (could be a velocity adjustment without full reversal).
    """
    df = df.copy()
    d_drift = df["dlambda_dt"].diff()              # change in drift rate
    sign_flip = np.sign(df["dlambda_dt"]) != np.sign(df["dlambda_dt"].shift(1))

    mask = d_drift.abs() > EW_DRIFT_THRESHOLD_DEG_DAY
    if EW_SIGN_FLIP_REQUIRED:
        confirmed = mask & sign_flip
        weak      = mask & ~sign_flip
    else:
        confirmed = mask
        weak      = pd.Series(False, index=df.index)

    events = []
    for idx in df.index[confirmed | weak]:
        row = df.loc[idx]
        events.append({
            "epoch_utc":   row["epoch_utc"],
            "type":        "EW",
            "confirmed":   bool(confirmed[idx]),
            "delta_drift": float(d_drift[idx]),
            "drift_before": float(df.loc[idx - 1, "dlambda_dt"]) if idx > 0 else np.nan,
            "drift_after":  float(row["dlambda_dt"]),
            "lambda_deg":   float(row["lambda_deg"]),
            "inc_deg":      float(row["inclination_deg"]),
            "sma_km":       float(row["sma_km"]),
            "dt_days":      float(row["dt_days"]),
        })
    return pd.DataFrame(events)


def detect_ns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Algorithm B: North-South maneuver detection.

    Primary signal: Δi < NS_INC_STEP_THRESHOLD_DEG
    Confirmation:   |ΔΩ_residual| > NS_RAAN_STEP_THRESHOLD_DEG
      (NS burns change both inclination and RAAN simultaneously)

    Natural perturbations only INCREASE inclination for i < 5°.
    Any negative Δi is therefore a strong maneuver indicator.
    """
    events = []
    for idx in df.index[1:]:
        di = df.loc[idx, "delta_i"]
        if pd.isna(di) or di >= NS_INC_STEP_THRESHOLD_DEG:
            continue
        draan_res = df.loc[idx, "delta_raan_res"]
        confirmed = abs(draan_res) > NS_RAAN_STEP_THRESHOLD_DEG if pd.notna(draan_res) else False
        row = df.loc[idx]
        events.append({
            "epoch_utc":    row["epoch_utc"],
            "type":         "NS",
            "confirmed":    confirmed,
            "delta_i_deg":  float(di),
            "delta_raan_residual_deg": float(draan_res) if pd.notna(draan_res) else np.nan,
            "i_before":    float(df.loc[idx - 1, "inclination_deg"]),
            "i_after":     float(row["inclination_deg"]),
            "lambda_deg":  float(row["lambda_deg"]),
            "sma_km":      float(row["sma_km"]),
            "dt_days":     float(row["dt_days"]),
        })
    return pd.DataFrame(events)


def detect_repositioning(df: pd.DataFrame, nominal_lon: float) -> pd.DataFrame:
    """
    Algorithm C: Slot repositioning detection.

    Conditions (all required to avoid false-positives from static drift):
      1. |λ - nominal| > REPO_LONGITUDE_BOX_DEG  (satellite left its box)
      2. The drift is GROWING over time (satellite moving away, not oscillating)
      3. Median |dλ/dt| > 0.05 °/day  (satellite is actively drifting, not noise)

    A slowly drifting satellite oscillating ±0.05° around a slightly wrong
    nominal will NOT trigger; a repositioning satellite moving continuously
    away from its slot WILL trigger.
    """
    df = df.copy()
    dist = (df["lambda_deg"] - nominal_lon + 180.0) % 360.0 - 180.0
    outside_box = dist.abs() > REPO_LONGITUDE_BOX_DEG

    if not outside_box.any():
        return pd.DataFrame()

    # Require the drift rate to be large (active repositioning, not slow drift)
    valid_drift = df["dlambda_dt"].dropna()
    median_abs_drift = valid_drift.abs().median() if len(valid_drift) > 0 else 0.0
    if median_abs_drift < 0.05:          # station-keeping regime — not repositioning
        return pd.DataFrame()

    # Require the longitude spread to be large (> 2× box → definite repositioning)
    max_dev = float(dist.abs().max())
    if max_dev < 2 * REPO_LONGITUDE_BOX_DEG:
        return pd.DataFrame()

    first_idx = outside_box.idxmax()
    row = df.loc[first_idx]
    return pd.DataFrame([{
        "epoch_utc":     row["epoch_utc"],
        "type":          "REPOSITIONING",
        "confirmed":     max_dev > 5 * REPO_LONGITUDE_BOX_DEG,
        "nominal_lon":   float(nominal_lon),
        "current_lon":   float(row["lambda_deg"]),
        "max_deviation": max_dev,
        "drift_rate":    float(valid_drift.abs().median()),
        "sma_km":        float(row["sma_km"]),
        "dt_days":       float(row["dt_days"]) if pd.notna(row["dt_days"]) else np.nan,
    }])


def detect_disposal(df: pd.DataFrame) -> pd.DataFrame:
    """
    Algorithm D: Graveyard orbit insertion.

    SMA rises permanently above DISPOSAL_SMA_THRESHOLD_KM
    AND subsequent TLEs remain above threshold (sustained, not transient).
    """
    above = df["sma_km"] > DISPOSAL_SMA_THRESHOLD_KM
    events = []
    if above.sum() >= 3:                           # at least 3 consecutive high-SMA TLEs
        first_idx = above.idxmax()
        row = df.loc[first_idx]
        events.append({
            "epoch_utc":    row["epoch_utc"],
            "type":         "DISPOSAL",
            "confirmed":    True,
            "sma_before_km": float(df["sma_km"].iloc[first_idx - 1]) if first_idx > 0 else np.nan,
            "sma_after_km": float(df.loc[first_idx:, "sma_km"].mean()),
            "delta_sma_km": float(df.loc[first_idx:, "sma_km"].mean() - SMA_GEO_KM),
            "sma_km":       float(row["sma_km"]),
            "dt_days":      float(row["dt_days"]) if pd.notna(row["dt_days"]) else np.nan,
        })
    return pd.DataFrame(events)


def detect_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """
    Algorithm E: TLE publication gap — possible manoeuvre during silence.
    """
    events = []
    for idx in df.index[1:]:
        dt = df.loc[idx, "dt_days"]
        if pd.notna(dt) and dt > TLE_GAP_THRESHOLD_DAYS:
            row = df.loc[idx]
            events.append({
                "epoch_utc": row["epoch_utc"],
                "type":      "TLE_GAP",
                "confirmed": dt > 2 * TLE_GAP_THRESHOLD_DAYS,
                "gap_days":  float(dt),
                "lambda_before": float(df.loc[idx - 1, "lambda_deg"]),
                "lambda_after":  float(row["lambda_deg"]),
                "sma_km":    float(row["sma_km"]),
                "dt_days":   float(dt),
            })
    return pd.DataFrame(events)


# ── Per-satellite pipeline ─────────────────────────────────────────────────────

def analyse_satellite(df_sat: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run all five detection algorithms for one satellite.

    Returns (features_df, events_df).
    """
    norad = int(df_sat["norad_id"].iloc[0])
    name  = str(df_sat["object_name"].iloc[0])

    feat = compute_features(df_sat)

    # Nominal longitude = mode of longitude over the time series
    # (robust to a single repositioning event)
    lambda_hist, bin_edges = np.histogram(feat["lambda_deg"].dropna(), bins=72)
    nominal_lon = float(bin_edges[lambda_hist.argmax()] + bin_edges[1] / 2)

    parts = []
    for fn, kwargs in [
        (detect_ew,           {"df": feat}),
        (detect_ns,           {"df": feat}),
        (detect_repositioning, {"df": feat, "nominal_lon": nominal_lon}),
        (detect_disposal,     {"df": feat}),
        (detect_gaps,         {"df": feat}),
    ]:
        result = fn(**kwargs)
        if not result.empty:
            result.insert(0, "norad_id",    norad)
            result.insert(1, "object_name", name)
            parts.append(result)

    events = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    n_ew    = (events["type"] == "EW").sum()   if not events.empty else 0
    n_ns    = (events["type"] == "NS").sum()   if not events.empty else 0
    n_gap   = (events["type"] == "TLE_GAP").sum() if not events.empty else 0
    n_repo  = (events["type"] == "REPOSITIONING").sum() if not events.empty else 0
    n_disp  = (events["type"] == "DISPOSAL").sum() if not events.empty else 0

    log.info("  NORAD %6d  %-28s  EW:%d  NS:%d  GAP:%d  REPO:%d  DISP:%d",
             norad, name[:28], n_ew, n_ns, n_gap, n_repo, n_disp)

    return feat, events


# ── Summary output ─────────────────────────────────────────────────────────────

_TYPE_ORDER = {"DISPOSAL": 0, "TLE_GAP": 1, "REPOSITIONING": 2,
               "NS": 3, "EW": 4}


def print_summary(all_events: pd.DataFrame) -> None:
    if all_events.empty:
        print("\nNo maneuver events detected.")
        return

    sats = all_events["norad_id"].unique()
    print(f"\n{'='*72}")
    print(f"GEO Maneuver Detection Summary  ({len(all_events)} events, "
          f"{len(sats)} satellites)")
    print(f"{'='*72}")

    type_counts = all_events["type"].value_counts()
    for t in sorted(type_counts.index, key=lambda x: _TYPE_ORDER.get(x, 9)):
        conf = all_events[(all_events["type"] == t) &
                          all_events["confirmed"]].shape[0]
        print(f"  {t:<18s}  total={type_counts[t]:3d}  confirmed={conf:3d}")

    print()
    for norad in sorted(sats):
        sub = all_events[all_events["norad_id"] == norad].sort_values("epoch_utc")
        name = sub["object_name"].iloc[0]
        print(f"\n  NORAD {norad}  {name}")
        for _, row in sub.iterrows():
            flag = "CONF" if row.get("confirmed", False) else "weak"
            t    = str(row["epoch_utc"])[:16]
            typ  = row["type"]
            detail = _format_detail(row)
            print(f"    [{flag}] {t}  {typ:<16s}  {detail}")

    print(f"{'='*72}\n")


def _format_detail(row: pd.Series) -> str:
    typ = row["type"]
    if typ == "EW":
        return (f"drift {row.get('drift_before',0):+.4f} -> "
                f"{row.get('drift_after',0):+.4f} deg/day  "
                f"lon={row.get('lambda_deg',0):.2f}°")
    if typ == "NS":
        return (f"Δi={row.get('delta_i_deg',0):+.4f}°  "
                f"({row.get('i_before',0):.4f}° -> {row.get('i_after',0):.4f}°)  "
                f"ΔRAAN_res={row.get('delta_raan_residual_deg',0):+.3f}°")
    if typ == "REPOSITIONING":
        return (f"nom={row.get('nominal_lon',0):.2f}°  "
                f"curr={row.get('current_lon',0):.2f}°  "
                f"max_dev={row.get('max_deviation',0):.2f}°")
    if typ == "DISPOSAL":
        return (f"SMA {row.get('sma_before_km',0):.1f} -> "
                f"{row.get('sma_after_km',0):.1f} km  "
                f"Δ={row.get('delta_sma_km',0):.1f} km")
    if typ == "TLE_GAP":
        return (f"gap={row.get('gap_days',0):.1f} days  "
                f"lon: {row.get('lambda_before',0):.2f}° -> "
                f"{row.get('lambda_after',0):.2f}°")
    return ""


# ── CLI ────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="GEO maneuver detection from TLE Keplerian elements (no SGP4)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--db",  default="space_db.duckdb", help="DuckDB path")
    p.add_argument("--out", default="data/geo_maneuvers", help="Output directory")
    p.add_argument("--norad", nargs="+", type=int, default=None,
                   help="Restrict to specific NORAD IDs")
    p.add_argument("--save-series", action="store_true",
                   help="Save per-satellite longitude/inclination time-series CSV")
    p.add_argument("--ew-threshold", type=float,
                   default=EW_DRIFT_THRESHOLD_DEG_DAY,
                   help="EW drift-rate change threshold (deg/day)")
    p.add_argument("--ns-threshold", type=float,
                   default=NS_INC_STEP_THRESHOLD_DEG,
                   help="NS inclination-step threshold (deg, negative)")
    return p


def main() -> int:
    args = build_parser().parse_args()

    global EW_DRIFT_THRESHOLD_DEG_DAY, NS_INC_STEP_THRESHOLD_DEG
    EW_DRIFT_THRESHOLD_DEG_DAY = args.ew_threshold
    NS_INC_STEP_THRESHOLD_DEG  = args.ns_threshold

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info("Loading GEO TLEs from %s …", args.db)
    all_tles = load_geo_tles(args.db, norad_ids=args.norad)

    if all_tles.empty:
        log.error("No GEO TLEs found. Check --db path and GEO filter criteria.")
        return 1

    all_events_parts: list[pd.DataFrame] = []
    all_features_parts: list[pd.DataFrame] = []

    sats = all_tles["norad_id"].unique()
    log.info("Analysing %d satellites …", len(sats))

    for norad in sorted(sats):
        df_sat = all_tles[all_tles["norad_id"] == norad].copy()
        if len(df_sat) < 5:
            log.warning("  NORAD %d: only %d TLEs — skipped", norad, len(df_sat))
            continue
        feat, events = analyse_satellite(df_sat)
        all_features_parts.append(feat)
        if not events.empty:
            all_events_parts.append(events)

    # ── Save events ────────────────────────────────────────────────────────────
    if all_events_parts:
        all_events = pd.concat(all_events_parts, ignore_index=True)
        all_events = all_events.sort_values(["norad_id", "epoch_utc"]).reset_index(drop=True)
        out_csv = out_dir / "maneuver_candidates.csv"
        all_events.to_csv(out_csv, index=False)
        log.info("Saved %d events → %s", len(all_events), out_csv)
        print_summary(all_events)
    else:
        all_events = pd.DataFrame()
        log.info("No maneuver events detected.")

    # ── Save time-series ───────────────────────────────────────────────────────
    if args.save_series and all_features_parts:
        series_dir = out_dir / "series"
        series_dir.mkdir(exist_ok=True)
        all_feat = pd.concat(all_features_parts, ignore_index=True)
        cols = ["norad_id", "object_name", "epoch_utc",
                "lambda_deg", "dlambda_dt", "inclination_deg",
                "delta_i", "sma_km", "dn_rev_day", "dt_days",
                "delta_raan_res"]
        all_feat[cols].to_csv(out_dir / "all_series.csv", index=False)
        log.info("Saved time-series → %s", out_dir / "all_series.csv")

    return 0


if __name__ == "__main__":
    sys.exit(main())
