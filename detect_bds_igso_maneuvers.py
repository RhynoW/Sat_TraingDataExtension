#!/usr/bin/env python3
"""
Phase 2: BDS IGSO SP3 velocity-jump maneuver detection.

Detects orbital maneuvers in BDS IGSO satellites (C38, C39, C40) by analysing
position discontinuities in MGEX SP3 precise orbits — no TLE dependency.

Algorithm
---------
For each continuous arc (no gap > MAX_GAP_S), at every interior epoch i:
  1. Fit a degree-3 polynomial to the 5 preceding positions (i-4 .. i).
  2. Predict r at epoch i+1.  Residual = |r_pred - r_actual|.
  3. If residual > THRESHOLD_M, estimate ΔV via 5-point Lagrange derivative
     evaluated at the boundary (before arc i .. i; after arc i+1 .. i+5).
  4. Decompose ΔV into Radial / Transverse / Normal (RTN) components.
  5. Cluster adjacent detections (< 30 min apart) → keep peak residual per cluster.

Physical interpretation
-----------------------
5-min SP3 spacing, IGSO orbit ~35 800 km, v_orb ≈ 3.075 km/s:
  ΔV = 0.05 m/s  →  position shift at i+1 ≈ 15 m
  ΔV = 0.17 m/s  →  ~50 m   (default confirmation threshold)
  ΔV = 1 m/s     →  ~300 m
COD MGEX orbit precision ≈ 5–15 cm → normal polynomial residual < 1 m.
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
log = logging.getLogger("bds_igso_maneuver")

# ── Constants ──────────────────────────────────────────────────────────────────
IGSO_PRNS      = ["C38", "C39", "C40"]
SP3_INTERVAL_S = 300.0        # 5-minute SP3 spacing
MAX_GAP_S      = 420.0        # > 7 min → treat as arc boundary

DETECTION_THRESHOLD_M    = 20.0   # m  → ~0.067 m/s ΔV
CONFIRMATION_THRESHOLD_M = 50.0   # m  → ~0.167 m/s ΔV
CLUSTER_WINDOW_S         = 1800.0 # 30 min — nearby flags belong to one event

# Skip this many epochs at the start of an arc that follows a long gap,
# because the orbit may be in a non-polynomial state (transfer, post-maneuver oscillation)
LONG_GAP_SKIP_EPOCHS = 8          # 8 × 5 min = 40 min
LONG_GAP_THRESHOLD_S = 3_600.0    # 1 hour — "long" gap = possible manoeuvre during gap

IGSO_ALTITUDE_KM_MIN = 35_000.0   # sanity filter: IGSO r should be 40-45 Mm
IGSO_ALTITUDE_KM_MAX = 50_000.0


# ── Data loading ───────────────────────────────────────────────────────────────

def load_igso_data(orbits_dir: Path, prns: list[str]) -> dict[str, pd.DataFrame]:
    """Load sorted SP3 parquets; return per-satellite DataFrames (positions only)."""
    frames: dict[str, list[pd.DataFrame]] = {p: [] for p in prns}
    for f in sorted(orbits_dir.glob("bds_sp3_*.parquet")):
        df = pd.read_parquet(f, columns=["sat_id", "t_gps", "x_m", "y_m", "z_m"])
        for prn in prns:
            sub = df[df["sat_id"] == prn]
            if not sub.empty:
                frames[prn].append(sub)

    result: dict[str, pd.DataFrame] = {}
    for prn in prns:
        if not frames[prn]:
            continue
        merged = pd.concat(frames[prn], ignore_index=True)
        merged["t_gps"] = pd.to_datetime(merged["t_gps"], utc=True)
        merged = (merged
                  .sort_values("t_gps")
                  .drop_duplicates("t_gps")
                  .reset_index(drop=True))
        result[prn] = merged
        log.info("  %s: %d epochs  %s → %s",
                 prn, len(merged),
                 merged["t_gps"].iloc[0].date(),
                 merged["t_gps"].iloc[-1].date())
    return result


def split_into_arcs(
    t_s: np.ndarray, max_gap: float
) -> list[tuple[np.ndarray, bool]]:
    """
    Return list of (index_array, long_gap_before) tuples, one per continuous arc.
    long_gap_before=True when the preceding gap exceeded LONG_GAP_THRESHOLD_S
    (used to skip warm-up epochs at arc start).
    """
    diffs = np.diff(t_s)
    breaks = np.where(diffs > max_gap)[0] + 1
    starts = np.concatenate([[0], breaks])
    ends   = np.concatenate([breaks, [len(t_s)]])
    gap_before = np.concatenate([[False], diffs[breaks - 1] > LONG_GAP_THRESHOLD_S])
    return [(np.arange(s, e), bool(lb))
            for s, e, lb in zip(starts, ends, gap_before)]


# ── Numerical tools ────────────────────────────────────────────────────────────

# 5-point equal-step extrapolation coefficients (applied to [r[k-4]..r[k]],
# predicting r[k+1]).  Exact for any polynomial of degree ≤ 4; error O(h⁵).
# Derived from Lagrange basis at u=1 with nodes u∈{-4,-3,-2,-1,0}.
# Avoids Vandermonde conditioning issues entirely — pure integer arithmetic.
_EXTRAP_COEFF = np.array([1.0, -5.0, 10.0, -10.0, 5.0])   # weights for [k-4,..,k]

def extrapolate_one_step(r_back5: np.ndarray) -> np.ndarray:
    """
    Predict r[k+1] from 5 equally-spaced backward positions r[k-4..k].
    r_back5: (5, 3) metres.  Returns (3,) predicted position.
    """
    return _EXTRAP_COEFF @ r_back5   # shape (3,)


# 4th-order backward first-derivative coefficients for equally-spaced data.
# Applied to [r[k-4], r[k-3], r[k-2], r[k-1], r[k]], gives v[k] in m/s
# when divided by h (step size in seconds).
_DCOEFF_BWD = np.array([-1.0/12, 1.0/2, -3.0/2, 1.0, 25.0/12])

# Wait: standard 4th-order backward differences at the last point:
# v[k] = (1/h)(1/4 r[k-4] - 4/3 r[k-3] + 3 r[k-2] - 4 r[k-1] + 25/12 r[k])
_DCOEFF_BWD = np.array([1.0/4, -4.0/3, 3.0, -4.0, 25.0/12])

def velocity_backward(r_back5: np.ndarray, h: float) -> np.ndarray:
    """
    4th-order backward first derivative at the last point.
    r_back5: (5, 3) metres at equally-spaced epochs with step h seconds.
    Returns velocity (3,) in m/s.
    """
    return (_DCOEFF_BWD @ r_back5) / h


def rtn_basis(r: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return unit vectors (R_hat, T_hat, N_hat) for RTN decomposition."""
    R_hat = r / np.linalg.norm(r)
    h = np.cross(r, v)
    h_mag = np.linalg.norm(h)
    N_hat = h / h_mag if h_mag > 1e-6 else np.array([0.0, 0.0, 1.0])
    T_hat = np.cross(N_hat, R_hat)
    return R_hat, T_hat, N_hat


# ── Core detector ──────────────────────────────────────────────────────────────

def detect_maneuvers(
    df: pd.DataFrame,
    prn: str,
    detect_threshold_m: float  = DETECTION_THRESHOLD_M,
    confirm_threshold_m: float = CONFIRMATION_THRESHOLD_M,
) -> pd.DataFrame:
    """
    Run maneuver detection on a single satellite's full SP3 time-series.

    Returns DataFrame (one row per maneuver candidate, clustered):
      t_maneuver, prn, poly_residual_m, dv_r_ms, dv_t_ms, dv_n_ms,
      dv_total_ms, r_km, confirmed
    """
    t_gps = df["t_gps"].values
    r_arr = df[["x_m", "y_m", "z_m"]].values.astype(np.float64)

    # Seconds from first epoch (avoids float64 precision issues with large abs times)
    _epoch = t_gps[0]
    t_s = (t_gps - _epoch).astype("float64") / 1e9

    arcs = split_into_arcs(t_s, MAX_GAP_S)
    log.info("  %s: %d arcs", prn, len(arcs))

    raw_candidates: list[dict] = []

    for arc_idx, long_gap_before in arcs:
        if len(arc_idx) < 10:   # need at least 10 epochs to run detector
            continue

        t_arc = t_s[arc_idx]
        r_arc = r_arr[arc_idx]

        # Skip warm-up epochs at the start of arcs following a long gap,
        # where the orbit may be in a non-polynomial state.
        k_start = (LONG_GAP_SKIP_EPOCHS if long_gap_before else 4)

        # Iterate interior epochs (need 4 before, 4 after for Lagrange windows)
        for k in range(max(4, k_start), len(arc_idx) - 5):
            # Local epoch time (seconds from t[k])
            t_k = t_arc[k]
            t_back = t_arc[k-4:k+1] - t_k    # [-1200, -900, -600, -300, 0]
            r_back = r_arc[k-4:k+1]

            # ── Altitude sanity check ────────────────────────────────────────
            r_mag = np.linalg.norm(r_arc[k])
            if not (IGSO_ALTITUDE_KM_MIN * 1e3 <= r_mag <= IGSO_ALTITUDE_KM_MAX * 1e3):
                continue

            # ── Step-ahead prediction: 5-point integer extrapolation ─────────
            # Exact for polynomials up to degree 4; no Vandermonde conditioning.
            # Only valid for uniform spacing — verify step.
            dt_fwd = t_arc[k+1] - t_k
            if abs(dt_fwd - SP3_INTERVAL_S) > 5.0:
                continue

            r_pred = extrapolate_one_step(r_back)    # (3,) metres
            residual = np.linalg.norm(r_arc[k+1] - r_pred)
            if residual < detect_threshold_m:
                continue

            # ── ΔV estimate and RTN decomposition ────────────────────────────
            # Displacement at k+1 = ΔV × h (for instantaneous kick at k).
            # Use 4th-order backward derivative for velocity at k (RTN basis only).
            disp = r_arc[k+1] - r_pred               # (3,) metres
            dv_total = float(residual / SP3_INTERVAL_S)

            ri = r_arc[k]
            vi = velocity_backward(r_back, SP3_INTERVAL_S)
            try:
                R_hat, T_hat, N_hat = rtn_basis(ri, vi)
                dv_r = float(np.dot(disp, R_hat) / SP3_INTERVAL_S)
                dv_t = float(np.dot(disp, T_hat) / SP3_INTERVAL_S)
                dv_n = float(np.dot(disp, N_hat) / SP3_INTERVAL_S)
            except Exception:
                dv_r = dv_t = dv_n = np.nan

            raw_candidates.append({
                "t_maneuver":      pd.Timestamp(t_gps[arc_idx[k]]),
                "prn":             prn,
                "poly_residual_m": float(residual),
                "dv_r_ms":         dv_r,
                "dv_t_ms":         dv_t,
                "dv_n_ms":         dv_n,
                "dv_total_ms":     dv_total,
                "r_km":            float(np.linalg.norm(ri) / 1000),
            })

    if not raw_candidates:
        return pd.DataFrame()

    cdf = pd.DataFrame(raw_candidates).sort_values("t_maneuver").reset_index(drop=True)

    # ── Cluster adjacent detections (same maneuver triggers multiple epochs) ──
    cluster_id = 0
    clusters = []
    prev_t = None
    for t in cdf["t_maneuver"]:
        if prev_t is None or (t - prev_t).total_seconds() > CLUSTER_WINDOW_S:
            cluster_id += 1
        clusters.append(cluster_id)
        prev_t = t
    cdf["cluster"] = clusters

    # Keep the epoch with the largest residual per cluster
    peak_idx = cdf.groupby("cluster")["poly_residual_m"].idxmax()
    cdf = cdf.loc[peak_idx].drop(columns=["cluster"]).reset_index(drop=True)

    cdf["confirmed"] = cdf["poly_residual_m"] >= confirm_threshold_m

    return cdf


# ── Summary and output ─────────────────────────────────────────────────────────

def print_summary(all_candidates: pd.DataFrame) -> None:
    if all_candidates.empty:
        log.info("No maneuver candidates detected.")
        return

    print("\n" + "=" * 70)
    print("BDS IGSO Maneuver Candidates (Phase 2 Detection)")
    print("=" * 70)

    for prn in IGSO_PRNS:
        sub = all_candidates[all_candidates["prn"] == prn]
        if sub.empty:
            print(f"\n{prn}: no candidates")
            continue

        conf = sub[sub["confirmed"]]
        print(f"\n{prn}: {len(sub)} candidates  "
              f"({len(conf)} confirmed >= {CONFIRMATION_THRESHOLD_M:.0f} m residual)")

        for _, row in sub.iterrows():
            flag = "★" if row["confirmed"] else "·"
            print(
                f"  {flag} {row['t_maneuver'].strftime('%Y-%m-%d %H:%M')}  "
                f"res={row['poly_residual_m']:6.1f} m  "
                f"ΔV={row['dv_total_ms']:5.3f} m/s  "
                f"[R={row['dv_r_ms']:+.3f}  T={row['dv_t_ms']:+.3f}  N={row['dv_n_ms']:+.3f}]  "
                f"r={row['r_km']:.0f} km"
            )
    print("=" * 70 + "\n")


def save_residual_series(
    df_sat: pd.DataFrame, prn: str, out_dir: Path,
    detect_threshold_m: float = DETECTION_THRESHOLD_M,
) -> None:
    """Save per-satellite residual time-series CSV for plotting."""
    t_gps = df_sat["t_gps"].values
    r_arr = df_sat[["x_m", "y_m", "z_m"]].values.astype(np.float64)
    _epoch = t_gps[0]
    t_s = (t_gps - _epoch).astype("float64") / 1e9

    arcs = split_into_arcs(t_s, MAX_GAP_S)
    rows = []
    for arc_idx, long_gap_before in arcs:
        if len(arc_idx) < 10:
            continue
        t_arc = t_s[arc_idx]
        r_arc = r_arr[arc_idx]
        k_start = LONG_GAP_SKIP_EPOCHS if long_gap_before else 4
        for k in range(max(4, k_start), len(arc_idx) - 5):
            r_back = r_arc[k-4:k+1]
            dt_fwd = t_arc[k+1] - t_arc[k]
            if abs(dt_fwd - SP3_INTERVAL_S) > 5.0:
                continue
            try:
                r_pred = extrapolate_one_step(r_back)
                residual = float(np.linalg.norm(r_arc[k+1] - r_pred))
            except Exception:
                residual = np.nan
            rows.append({"t_gps": pd.Timestamp(t_gps[arc_idx[k]]),
                         "poly_residual_m": residual})

    if rows:
        ts_df = pd.DataFrame(rows)
        out = out_dir / f"{prn}_poly_residuals.csv"
        ts_df.to_csv(out, index=False)
        log.info("  Saved residual series: %s (%d rows)", out.name, len(ts_df))


# ── CLI ────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="BDS IGSO SP3 maneuver detection (Phase 2)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--orbits-dir", default="data/bds_orbits",
                   help="Directory with bds_sp3_*.parquet files")
    p.add_argument("--out-dir", default="data/bds_igso_maneuvers",
                   help="Output directory for CSV results")
    p.add_argument("--prns", nargs="+", default=IGSO_PRNS,
                   help="BDS IGSO PRNs to analyse")
    p.add_argument("--detect-threshold", type=float, default=DETECTION_THRESHOLD_M,
                   help="Minimum polynomial residual to flag (metres)")
    p.add_argument("--confirm-threshold", type=float, default=CONFIRMATION_THRESHOLD_M,
                   help="Residual threshold for 'confirmed' label (metres)")
    p.add_argument("--save-series", action="store_true",
                   help="Also save per-satellite residual time-series CSV")
    return p


def main() -> int:
    args = build_parser().parse_args()

    orbits_dir = Path(args.orbits_dir)
    out_dir    = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info("Loading BDS IGSO SP3 data from %s …", orbits_dir)
    sat_data = load_igso_data(orbits_dir, args.prns)

    if not sat_data:
        log.error("No data found — check --orbits-dir path")
        return 1

    all_parts: list[pd.DataFrame] = []

    for prn, df in sat_data.items():
        log.info("Detecting maneuvers: %s …", prn)
        cands = detect_maneuvers(
            df, prn,
            detect_threshold_m  = args.detect_threshold,
            confirm_threshold_m = args.confirm_threshold,
        )
        if cands.empty:
            log.info("  %s: no candidates above threshold", prn)
        else:
            log.info("  %s: %d candidates (%d confirmed)",
                     prn, len(cands), cands["confirmed"].sum())
            all_parts.append(cands)

        if args.save_series:
            save_residual_series(df, prn, out_dir, args.detect_threshold)

    if all_parts:
        all_cands = pd.concat(all_parts, ignore_index=True)
        all_cands = all_cands.sort_values(["prn", "t_maneuver"]).reset_index(drop=True)
        out_csv = out_dir / "maneuver_candidates.csv"
        all_cands.to_csv(out_csv, index=False)
        log.info("Saved candidates: %s", out_csv)
        print_summary(all_cands)
    else:
        log.info("No maneuver candidates detected in any satellite.")
        all_cands = pd.DataFrame()

    return 0


if __name__ == "__main__":
    sys.exit(main())
