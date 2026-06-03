#!/usr/bin/env python3
"""
Compare Galileo SP3 precise ephemeris vs TLE-propagated positions.

Data flow
---------
  SP3 Parquet (ECEF, m)
      → ECEF → ECI via GMST rotation (GPS→UTC −18 s)
  TLE from space_db.duckdb (raw_tle_archive)
      → Skyfield SGP4 propagation at each SP3 epoch
  Residuals (km, RTN)
      → data/galileo_comparison/residuals_{date}.csv
      → data/galileo_comparison/summary_{date}.csv

Compatible with the "Galileo SP3" tab in maneuver_app.py.

Satellite matching
------------------
SP3 uses PRN identifiers (E01…E36).  This script maps them to NORAD IDs via
GALILEO_PRN_NORAD (below).  Unmapped or unavailable satellites are skipped.
Update the table if a satellite is retired or a new one commissioned.

Usage
-----
  python compare_galileo_sp3_vs_tle.py
  python compare_galileo_sp3_vs_tle.py --sp3-dir data/galileo_orbits --db space_db.duckdb
  python compare_galileo_sp3_vs_tle.py --prn E11 E29 --no-plot
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from skyfield.api import EarthSatellite, load as skyfield_load

log = logging.getLogger("galileo_compare")

# ── PRN → NORAD mapping (Galileo constellation, verified 2026-04-01) ────────
# Derived by position-matching SP3 ephemeris against propagated TLEs:
# each NORAD was selected as the best match (< 250 km error, next candidate
# always > 1000 km away).  Update if PRN reassignments occur.
GALILEO_PRN_NORAD: dict[str, int] = {
    "E02": 41549,  # GALILEO 14 (26B)
    "E03": 41860,  # GALILEO 16 (26C)
    "E04": 41861,  # GALILEO 17 (26D)
    "E05": 41862,  # GALILEO 18 (26E)
    "E06": 59600,  # GALILEO 30 (10E)
    "E07": 41859,  # GALILEO 15 (267)
    "E08": 41175,  # GALILEO 11 (268)
    "E09": 41174,  # GALILEO 12 (269)
    "E10": 49810,  # GALILEO 28 (224)
    "E11": 37846,  # GALILEO-PFM
    "E12": 37847,  # GALILEO-FM2
    "E13": 43567,  # GALILEO 24 (2C0)
    "E14": 40129,  # GALILEO 6  (262)
    "E15": 43564,  # GALILEO 25 (2C1)
    "E16": 61182,  # GALILEO 32 (137)
    "E18": 40128,  # GALILEO 5  (261)
    "E19": 38857,  # GALILEO-FM3
    "E21": 43055,  # GALILEO 19 (2C5)
    "E23": 61183,  # GALILEO 31 (10D)
    "E25": 43056,  # GALILEO 20 (2C6)
    "E26": 40544,  # GALILEO 7  (263)
    "E27": 43057,  # GALILEO 21 (2C7)
    "E28": 67160,  # GALILEO 33 (138)
    "E29": 59598,  # GALILEO 29 (10C)
    "E30": 40890,  # GALILEO 10 (206)
    "E31": 43058,  # GALILEO 22 (2C8)
    "E32": 67162,  # GALILEO 34 (139)
    "E33": 43565,  # GALILEO 26 (2C2)
    "E34": 49809,  # GALILEO 27 (223)
    "E36": 43566,  # GALILEO 23 (2C9)
}

GPS_LEAP_S = 18  # GPS − UTC offset in seconds (update if new leap second added)
EARTH_OMEGA = 7.292115e-5  # rad s⁻¹

_RESID_OUT_COLS = [
    "norad_id", "sat_name", "t",
    "dr_r_km", "dr_t_km", "dr_n_km",
    "pos_err_km", "vel_err_kms",
    "tle_epoch", "tle_age_days",
]


# ── ECEF → ECI (GCRS approx via GMST) ────────────────────────────────────────

def ecef_to_eci(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rotate ECEF positions/velocities to ECI using GMST approximation.

    Input columns : x_m, y_m, z_m [m], v_x_mps, v_y_mps, v_z_mps [m/s], t_gps
    Output columns: r_x, r_y, r_z [km], v_x, v_y, v_z [km/s]

    GPS → UTC correction: subtract GPS_LEAP_S before computing GMST.
    Accuracy: ~100 m at MEO (arcsecond-level, sufficient for km-scale residuals).
    """
    utc = pd.to_datetime(df["t_gps"], utc=True) - pd.Timedelta(seconds=GPS_LEAP_S)
    _epoch = pd.Timestamp("1970-01-01", tz="UTC")
    jd = (utc - _epoch).dt.total_seconds() / 86400.0 + 2_440_587.5
    T = (jd - 2_451_545.0) / 36525.0
    gmst_deg = (
        280.46061837
        + 360.98564736629 * (jd - 2_451_545.0)
        + 0.000387933 * T**2
        - T**3 / 38_710_000.0
    ) % 360.0
    theta = np.deg2rad(gmst_deg.values)
    ct, st = np.cos(theta), np.sin(theta)

    x = df["x_m"].values / 1_000.0
    y = df["y_m"].values / 1_000.0
    z = df["z_m"].values / 1_000.0

    out = df.copy()
    out["r_x"] = ct * x - st * y
    out["r_y"] = st * x + ct * y
    out["r_z"] = z

    if not df["v_x_mps"].isna().all():
        vx = df["v_x_mps"].values / 1_000.0
        vy = df["v_y_mps"].values / 1_000.0
        vz = df["v_z_mps"].values / 1_000.0
        out["v_x"] = ct * vx - st * vy - EARTH_OMEGA * (st * x + ct * y)
        out["v_y"] = st * vx + ct * vy + EARTH_OMEGA * (ct * x - st * y)
        out["v_z"] = vz
    else:
        out["v_x"] = np.nan
        out["v_y"] = np.nan
        out["v_z"] = np.nan

    return out


# ── TLE loading & propagation ─────────────────────────────────────────────────

def load_tles(con: duckdb.DuckDBPyConnection,
              norad_ids: list[int],
              t_start: pd.Timestamp,
              t_end: pd.Timestamp,
              pre_days: float = 3.0) -> dict[int, pd.DataFrame]:
    """
    Fetch TLEs from raw_tle_archive for each NORAD ID in the window
    [t_start − pre_days, t_end + 1 h].  Deduplicates near-identical epochs.
    """
    ids_str = ",".join(str(i) for i in norad_ids)
    t_lo = (t_start - pd.Timedelta(days=pre_days)).isoformat()
    t_hi = (t_end + pd.Timedelta(hours=1)).isoformat()

    raw = con.execute(f"""
        SELECT norad_id, line1, line2, epoch_utc,
               object_name AS space_track_name
        FROM raw_tle_archive
        WHERE norad_id IN ({ids_str})
          AND epoch_utc BETWEEN '{t_lo}' AND '{t_hi}'
        ORDER BY norad_id, epoch_utc
    """).fetchdf()

    if raw.empty:
        # Fallback: all TLEs regardless of time window
        raw = con.execute(f"""
            SELECT norad_id, line1, line2, epoch_utc,
                   object_name AS space_track_name
            FROM raw_tle_archive
            WHERE norad_id IN ({ids_str})
            ORDER BY norad_id, epoch_utc
        """).fetchdf()

    raw["epoch_utc"] = pd.to_datetime(raw["epoch_utc"], utc=True)

    result: dict[int, pd.DataFrame] = {}
    for nid in norad_ids:
        sub = raw[raw["norad_id"] == nid].copy()
        if sub.empty:
            continue
        sub["_epoch_s"] = sub["epoch_utc"].dt.round("s")
        sub = (sub.drop_duplicates("_epoch_s")
                  .drop(columns="_epoch_s")
                  .sort_values("epoch_utc")
                  .reset_index(drop=True))
        result[nid] = sub

    return result


MAX_TLE_AGE_DAYS = 30  # skip SP3 epochs more than this many days from their best TLE


def propagate_best_tles(
    sp3_eci: pd.DataFrame,
    tle_df: pd.DataFrame,
    sat_label: str,
    ts,
    max_age_days: float = MAX_TLE_AGE_DAYS,
) -> pd.DataFrame:
    """
    Propagate MEME-style: pick the best (most recent pre-epoch) TLE for each
    SP3 timestamp, group by TLE, and batch-propagate with Skyfield.

    Epochs more than max_age_days from their assigned TLE are skipped — MEO
    SGP4 accuracy collapses beyond ~2–4 weeks (no drag model), so propagating
    months beyond the TLE epoch produces tens-of-thousands-km errors.

    Returns DataFrame: t, r_x, r_y, r_z, v_x, v_y, v_z  (km, km/s).
    """
    if tle_df.empty:
        return pd.DataFrame()

    # Use total_seconds() to get Unix seconds — avoids the pandas 2.x unit mismatch
    # where epoch_utc (datetime64[us] from DuckDB) and t_gps (datetime64[ns] from
    # parquet) give different int64 magnitudes when cast directly.
    _epoch = pd.Timestamp("1970-01-01", tz="UTC")
    times_s  = (pd.to_datetime(sp3_eci["t_gps"],    utc=True) - _epoch).dt.total_seconds().values
    epochs_s = (pd.to_datetime(tle_df["epoch_utc"], utc=True) - _epoch).dt.total_seconds().values

    idx = np.searchsorted(epochs_s, times_s, side="right") - 1
    idx = np.clip(idx, 0, len(tle_df) - 1)

    sp3_copy = sp3_eci.copy()
    sp3_copy["_tle_idx"] = idx

    # Drop SP3 epochs whose best TLE is older than max_age_days — propagating
    # a MEO TLE 30+ days beyond its epoch gives tens-of-thousands-km errors.
    age_days = (times_s - epochs_s[idx]) / 86_400.0
    valid = np.abs(age_days) <= max_age_days
    n_skipped = int((~valid).sum())
    if n_skipped:
        log.debug("[%s] Skipping %d SP3 epochs with TLE age > %.0f days",
                  sat_label, n_skipped, max_age_days)
    sp3_copy = sp3_copy[valid]
    if sp3_copy.empty:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for tle_i, grp in sp3_copy.groupby("_tle_idx", sort=True):
        row = tle_df.iloc[int(tle_i)]
        try:
            sat = EarthSatellite(row["line1"], row["line2"], name=sat_label, ts=ts)
            t_arr = ts.from_datetimes(
                [dt.to_pydatetime()
                 for dt in pd.to_datetime(grp["t_gps"], utc=True)]
            )
            geo = sat.at(t_arr)
            pos = geo.position.km
            vel = geo.velocity.km_per_s
            chunk = pd.DataFrame({
                "t":   grp["t_gps"].values,
                "r_x": pos[0], "r_y": pos[1], "r_z": pos[2],
                "v_x": vel[0], "v_y": vel[1], "v_z": vel[2],
            })
            chunk["t"] = pd.to_datetime(chunk["t"], utc=True)
            frames.append(chunk)
        except Exception as exc:
            log.debug("[%s] SGP4 error for TLE %s: %s", sat_label, row["epoch_utc"], exc)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("t").reset_index(drop=True)


# ── RTN residuals ─────────────────────────────────────────────────────────────

def _rtn_basis(r: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    r_hat = r / np.linalg.norm(r, axis=1, keepdims=True)
    h = np.cross(r, v)
    n_hat = h / np.linalg.norm(h, axis=1, keepdims=True)
    t_hat = np.cross(n_hat, r_hat)
    return r_hat, t_hat, n_hat


def compute_residuals(sp3_eci: pd.DataFrame, tle_prop: pd.DataFrame) -> pd.DataFrame:
    """
    Merge SP3 (truth) and TLE (propagated) on 't_gps', compute RTN residuals.
    """
    sp3_eci = sp3_eci.copy()
    sp3_eci["t"] = pd.to_datetime(sp3_eci["t_gps"], utc=True)

    merged = pd.merge(
        sp3_eci[["t", "r_x", "r_y", "r_z", "v_x", "v_y", "v_z"]],
        tle_prop.rename(columns={
            "r_x": "r_x_t", "r_y": "r_y_t", "r_z": "r_z_t",
            "v_x": "v_x_t", "v_y": "v_y_t", "v_z": "v_z_t",
        }),
        on="t",
        how="inner",
    )
    if merged.empty:
        return merged

    dr = np.stack([
        merged["r_x_t"].values - merged["r_x"].values,
        merged["r_y_t"].values - merged["r_y"].values,
        merged["r_z_t"].values - merged["r_z"].values,
    ], axis=1)
    dv = np.stack([
        merged["v_x_t"].values - merged["v_x"].values,
        merged["v_y_t"].values - merged["v_y"].values,
        merged["v_z_t"].values - merged["v_z"].values,
    ], axis=1)

    merged["pos_err_km"] = np.linalg.norm(dr, axis=1)
    merged["vel_err_kms"] = np.linalg.norm(dv, axis=1)

    r = np.stack([merged["r_x"].values, merged["r_y"].values, merged["r_z"].values], axis=1)
    v = np.stack([merged["v_x"].values, merged["v_y"].values, merged["v_z"].values], axis=1)

    # COD SP3 files omit velocity records; fall back to TLE velocity for RTN basis.
    if np.isnan(v).any():
        v = np.stack([merged["v_x_t"].values, merged["v_y_t"].values,
                      merged["v_z_t"].values], axis=1)

    try:
        R, T, N = _rtn_basis(r, v)
        merged["dr_r_km"] = (dr * R).sum(axis=1)
        merged["dr_t_km"] = (dr * T).sum(axis=1)
        merged["dr_n_km"] = (dr * N).sum(axis=1)
    except Exception as exc:
        log.warning("RTN decomposition failed: %s", exc)
        merged["dr_r_km"] = merged["dr_t_km"] = merged["dr_n_km"] = np.nan

    return merged


# ── Per-satellite processing ──────────────────────────────────────────────────

def process_satellite(
    prn: str,
    norad_id: int,
    sp3_df: pd.DataFrame,
    tle_df: pd.DataFrame,
    ts,
) -> tuple[dict, pd.DataFrame | None]:
    """
    Full pipeline for one satellite: ECI convert → propagate → residuals.
    """
    sat_label = f"GALILEO-{prn}"
    sp3_sat = sp3_df[sp3_df["sat_id"] == prn].copy()
    if sp3_sat.empty:
        return {"norad_id": norad_id, "sat_name": sat_label,
                "status": "no_sp3"}, None

    # ECEF → ECI
    try:
        sp3_eci = ecef_to_eci(sp3_sat)
    except Exception as exc:
        return {"norad_id": norad_id, "sat_name": sat_label,
                "status": f"ecef_eci_error: {exc}"}, None

    if tle_df.empty:
        return {"norad_id": norad_id, "sat_name": sat_label,
                "status": "no_tle"}, None

    # TLE propagation
    try:
        tle_prop = propagate_best_tles(sp3_eci, tle_df, sat_label, ts)
    except Exception as exc:
        return {"norad_id": norad_id, "sat_name": sat_label,
                "status": f"sgp4_error: {exc}"}, None

    if tle_prop.empty:
        return {"norad_id": norad_id, "sat_name": sat_label,
                "status": "no_propagation"}, None

    # Residuals
    res = compute_residuals(sp3_eci, tle_prop)
    if res.empty:
        return {"norad_id": norad_id, "sat_name": sat_label,
                "status": "no_match"}, None

    # TLE age column — use float seconds to avoid datetime64 unit mismatch
    _ep = pd.Timestamp("1970-01-01", tz="UTC")
    tle_ep_s  = (pd.to_datetime(tle_df["epoch_utc"], utc=True) - _ep).dt.total_seconds().values
    res_t_s   = (pd.to_datetime(res["t"],            utc=True) - _ep).dt.total_seconds().values
    idx = np.searchsorted(tle_ep_s, res_t_s, side="right") - 1
    idx = np.clip(idx, 0, len(tle_df) - 1)
    used_epochs = pd.to_datetime(tle_df["epoch_utc"].iloc[idx].values, utc=True)
    res["tle_epoch"] = used_epochs.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    res["tle_age_days"] = ((res_t_s - tle_ep_s[idx]) / 86400.0).round(2)

    t_min_s = (pd.to_datetime(sp3_sat["t_gps"].min(), utc=True) - _ep).total_seconds()
    rep_tle = tle_df[tle_ep_s <= t_min_s].tail(1) if len(tle_ep_s) else tle_df.head(1)
    if rep_tle.empty:
        rep_tle = tle_df.head(1)
    tle_epoch_ts = pd.to_datetime(rep_tle["epoch_utc"].iloc[0], utc=True)
    t_start = pd.to_datetime(sp3_sat["t_gps"].min(), utc=True)
    tle_age = (t_start - tle_epoch_ts).total_seconds() / 86400.0

    res.insert(0, "sat_name", sat_label)
    res.insert(0, "norad_id", norad_id)

    summary = {
        "norad_id":        norad_id,
        "sat_name":        sat_label,
        "prn":             prn,
        "status":          "ok",
        "n_sp3_epochs":    len(sp3_sat["t_gps"].unique()),
        "n_matched":       len(res),
        "n_tles":          len(tle_df),
        "tle_age_days":    round(tle_age, 2),
        "pos_err_mean_km": round(res["pos_err_km"].mean(), 3),
        "pos_err_std_km":  round(res["pos_err_km"].std(), 3),
        "pos_err_max_km":  round(res["pos_err_km"].max(), 3),
        "vel_err_mean_kms": round(res["vel_err_kms"].mean(), 6),
        "dr_t_rms_km":     round(res["dr_t_km"].std(), 3),
        "dr_n_rms_km":     round(res["dr_n_km"].std(), 3),
    }
    return summary, res


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_comparison(
    sp3_parquet_dir: Path,
    space_db: Path,
    out_dir: Path,
    start: "datetime.date | None" = None,
    end: "datetime.date | None" = None,
    prn_filter: list[str] | None = None,
) -> None:
    """
    Load all SP3 parquets in sp3_parquet_dir, compare with TLEs, save residuals.

    Called by galileo_pipeline.py or directly.
    """
    import datetime as _dt

    sp3_parquet_dir = Path(sp3_parquet_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load all parquets
    parquets = sorted(sp3_parquet_dir.glob("galileo_sp3_*.parquet"))
    if not parquets:
        log.error("No galileo_sp3_*.parquet found in %s", sp3_parquet_dir)
        return

    log.info("Loading %d parquet file(s)…", len(parquets))
    sp3_all = pd.concat([pd.read_parquet(p) for p in parquets], ignore_index=True)
    sp3_all["t_gps"] = pd.to_datetime(sp3_all["t_gps"], utc=True)

    if start:
        sp3_all = sp3_all[sp3_all["t_gps"] >= pd.Timestamp(start, tz="UTC")]
    if end:
        sp3_all = sp3_all[sp3_all["t_gps"] <= pd.Timestamp(end, tz="UTC") + pd.Timedelta(hours=24)]

    if sp3_all.empty:
        log.error("SP3 DataFrame is empty after date filtering.")
        return

    t_start = sp3_all["t_gps"].min()
    t_end   = sp3_all["t_gps"].max()
    log.info("SP3 coverage: %s → %s  (%d PRNs, %d rows)",
             t_start, t_end, sp3_all["sat_id"].nunique(), len(sp3_all))

    # Determine which PRNs to process
    available_prns = sorted(sp3_all["sat_id"].unique())
    if prn_filter:
        prns = [p for p in prn_filter if p in available_prns]
    else:
        prns = [p for p in available_prns if p in GALILEO_PRN_NORAD]

    if not prns:
        log.error("No valid PRNs to process. Available: %s", available_prns)
        return
    log.info("Processing %d PRNs: %s", len(prns), prns)

    # Load TLEs
    norad_ids = [GALILEO_PRN_NORAD[p] for p in prns if p in GALILEO_PRN_NORAD]
    norad_ids = list(set(norad_ids))

    con = duckdb.connect(str(space_db), read_only=True)
    tle_pool = load_tles(con, norad_ids, t_start, t_end)
    con.close()
    log.info("TLE pool: %d / %d satellites have TLEs", len(tle_pool), len(norad_ids))

    ts = skyfield_load.timescale()
    summaries: list[dict] = []
    resid_frames: list[pd.DataFrame] = []

    for i, prn in enumerate(prns, 1):
        norad_id = GALILEO_PRN_NORAD.get(prn)
        if norad_id is None:
            log.warning("[%s] No NORAD mapping — skipped", prn)
            continue
        tle_df = tle_pool.get(norad_id, pd.DataFrame())
        log.info("[%d/%d] %s  NORAD=%d  TLEs=%d",
                 i, len(prns), prn, norad_id, len(tle_df))

        summary, res = process_satellite(prn, norad_id, sp3_all, tle_df, ts)
        summaries.append(summary)
        if res is not None:
            resid_frames.append(res[[c for c in _RESID_OUT_COLS if c in res.columns]])

    date_tag = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    summary_df = pd.DataFrame(summaries)
    summary_path = out_dir / f"summary_{date_tag}.csv"
    summary_df.to_csv(summary_path, index=False)
    log.info("Summary → %s", summary_path)

    if resid_frames:
        resid_df = pd.concat(resid_frames, ignore_index=True)
        resid_path = out_dir / f"residuals_{date_tag}.csv"
        resid_df.to_csv(resid_path, index=False)
        log.info("Residuals → %s (%d rows)", resid_path, len(resid_df))

        ok = summary_df[summary_df["status"] == "ok"]
        if not ok.empty:
            print("\n=== Galileo SP3 vs TLE ===")
            print(f"  衛星數: {len(ok)}")
            print(f"  平均位置誤差 (km): {ok['pos_err_mean_km'].mean():.2f}")
            print(f"  最大位置誤差 (km): {ok['pos_err_max_km'].max():.2f}")
            print(f"  Along-track RMS (km): {ok['dr_t_rms_km'].mean():.2f}")
            print(f"  Cross-track RMS (km): {ok['dr_n_rms_km'].mean():.2f}")
            print(f"\n  Summary → {summary_path}")
            print(f"  Residuals → {resid_path}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Galileo SP3 vs TLE 殘差計算",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--sp3-dir", default="data/galileo_orbits",
                   help="galileo_sp3_*.parquet 所在目錄")
    p.add_argument("--db", default="space_db.duckdb", help="TLE DuckDB 路徑")
    p.add_argument("--out-dir", default="data/galileo_comparison", help="輸出目錄")
    p.add_argument("--start", default=None, help="篩選開始日期 YYYY-MM-DD")
    p.add_argument("--end",   default=None, help="篩選結束日期 YYYY-MM-DD")
    p.add_argument("--prn", nargs="+", default=None, metavar="PRN",
                   help="只處理指定 PRN（例如 E11 E29）")
    return p


def main() -> int:
    import datetime as _dt
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    args = build_parser().parse_args()
    run_comparison(
        sp3_parquet_dir=Path(args.sp3_dir),
        space_db=Path(args.db),
        out_dir=Path(args.out_dir),
        start=_dt.date.fromisoformat(args.start) if args.start else None,
        end=_dt.date.fromisoformat(args.end)   if args.end   else None,
        prn_filter=args.prn,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
