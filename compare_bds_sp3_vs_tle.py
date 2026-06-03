#!/usr/bin/env python3
"""
Compare BeiDou SP3 precise ephemeris vs TLE-propagated positions.

Satellite types in COD MGEX SP3:
  MEO  (C19–C49, ~21,500 km) — SGP4 good to ~30-day TLE age
  IGSO (C38–C40, ~35,800 km) — SGP4 near resonance; age limit = 15 days

PRN→NORAD mapping derived 2026-04-01 by SP3 position matching.
Update the table if PRN reassignments occur.

Usage
-----
  python compare_bds_sp3_vs_tle.py
  python compare_bds_sp3_vs_tle.py --prn C19 C26 --no-plot
  python compare_bds_sp3_vs_tle.py --start 2026-04-01 --end 2026-04-30
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

log = logging.getLogger("bds_compare")

# ── PRN → NORAD mapping (verified 2026-04-01 by SP3 position matching) ───────
BDS_PRN_NORAD: dict[str, int] = {
    "C19": 43001,  # BEIDOU 3M1
    "C20": 43002,  # BEIDOU 3M2
    "C21": 43208,  # BEIDOU 3M6
    "C22": 43207,  # BEIDOU 3M5
    "C23": 43581,  # BEIDOU 3M9
    "C24": 43582,  # BEIDOU 3M10
    "C25": 43603,  # BEIDOU 3M12
    "C26": 43602,  # BEIDOU 3M11
    "C27": 43107,  # BEIDOU 3M3
    "C28": 43108,  # BEIDOU 3M4
    "C29": 43245,  # BEIDOU 3M7
    "C30": 43246,  # BEIDOU 3M8
    "C32": 43622,  # BEIDOU 3M13
    "C33": 43623,  # BEIDOU 3M14
    "C34": 43648,  # BEIDOU 3M16
    "C35": 43647,  # BEIDOU 3M15
    "C36": 43706,  # BEIDOU 3M17
    "C37": 43707,  # BEIDOU 3M18
    "C38": 44204,  # BEIDOU 3 IGSO-1  (~35,800 km, 15-day age limit)
    "C39": 44337,  # BEIDOU 3 IGSO-2  (~35,800 km, 15-day age limit)
    "C40": 44709,  # BEIDOU 3 IGSO-3  (~35,800 km, 15-day age limit)
    "C41": 44864,  # BEIDOU 3M19
    "C42": 44865,  # BEIDOU 3M20
    "C43": 44794,  # BEIDOU 3M22
    "C44": 44793,  # BEIDOU 3M21
    "C45": 44543,  # BEIDOU 3M24
    "C47": 61186,  # BEIDOU 3M25
    "C48": 58655,  # BEIDOU 3 M26
    "C49": 61187,  # BEIDOU 3M27
}

# IGSO PRNs: reduced TLE age limit because SGP4 breaks down near GEO resonance
_IGSO_PRNS = {"C38", "C39", "C40"}
MAX_TLE_AGE_MEO  = 30   # days
MAX_TLE_AGE_IGSO = 15   # days — tighter for near-resonance orbits

GPS_LEAP_S  = 18
EARTH_OMEGA = 7.292115e-5  # rad s⁻¹

_RESID_OUT_COLS = [
    "norad_id", "sat_name", "t",
    "dr_r_km", "dr_t_km", "dr_n_km",
    "pos_err_km", "vel_err_kms",
    "tle_epoch", "tle_age_days",
    "orbit_type",
]


# ── ECEF → ECI ────────────────────────────────────────────────────────────────

def ecef_to_eci(df: pd.DataFrame) -> pd.DataFrame:
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


# ── TLE loading ───────────────────────────────────────────────────────────────

def load_tles(con: duckdb.DuckDBPyConnection,
              norad_ids: list[int],
              t_start: pd.Timestamp,
              t_end: pd.Timestamp,
              pre_days: float = 3.0) -> dict[int, pd.DataFrame]:
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


# ── TLE propagation ───────────────────────────────────────────────────────────

def propagate_best_tles(sp3_eci: pd.DataFrame, tle_df: pd.DataFrame,
                        sat_label: str, ts,
                        max_age_days: float = MAX_TLE_AGE_MEO) -> pd.DataFrame:
    if tle_df.empty:
        return pd.DataFrame()

    _ep = pd.Timestamp("1970-01-01", tz="UTC")
    times_s  = (pd.to_datetime(sp3_eci["t_gps"],    utc=True) - _ep).dt.total_seconds().values
    epochs_s = (pd.to_datetime(tle_df["epoch_utc"], utc=True) - _ep).dt.total_seconds().values

    idx = np.searchsorted(epochs_s, times_s, side="right") - 1
    idx = np.clip(idx, 0, len(tle_df) - 1)

    age_days = (times_s - epochs_s[idx]) / 86_400.0
    valid = np.abs(age_days) <= max_age_days
    n_skip = int((~valid).sum())
    if n_skip:
        log.debug("[%s] Skipping %d epochs with TLE age > %.0f days",
                  sat_label, n_skip, max_age_days)

    sp3_copy = sp3_eci.copy()
    sp3_copy["_tle_idx"] = idx
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
            log.debug("[%s] SGP4 error: %s", sat_label, exc)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("t").reset_index(drop=True)


# ── RTN residuals ─────────────────────────────────────────────────────────────

def _rtn_basis(r: np.ndarray, v: np.ndarray):
    r_hat = r / np.linalg.norm(r, axis=1, keepdims=True)
    h = np.cross(r, v)
    n_hat = h / np.linalg.norm(h, axis=1, keepdims=True)
    t_hat = np.cross(n_hat, r_hat)
    return r_hat, t_hat, n_hat


def compute_residuals(sp3_eci: pd.DataFrame, tle_prop: pd.DataFrame) -> pd.DataFrame:
    sp3_eci = sp3_eci.copy()
    sp3_eci["t"] = pd.to_datetime(sp3_eci["t_gps"], utc=True)

    merged = pd.merge(
        sp3_eci[["t", "r_x", "r_y", "r_z", "v_x", "v_y", "v_z"]],
        tle_prop.rename(columns={
            "r_x": "r_x_t", "r_y": "r_y_t", "r_z": "r_z_t",
            "v_x": "v_x_t", "v_y": "v_y_t", "v_z": "v_z_t",
        }),
        on="t", how="inner",
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

    merged["pos_err_km"]  = np.linalg.norm(dr, axis=1)
    merged["vel_err_kms"] = np.linalg.norm(dv, axis=1)

    r = np.stack([merged["r_x"].values, merged["r_y"].values, merged["r_z"].values], axis=1)
    v = np.stack([merged["v_x"].values, merged["v_y"].values, merged["v_z"].values], axis=1)
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

def process_satellite(prn: str, norad_id: int, sp3_df: pd.DataFrame,
                      tle_df: pd.DataFrame, ts) -> tuple[dict, pd.DataFrame | None]:
    orbit_type = "IGSO" if prn in _IGSO_PRNS else "MEO"
    max_age = MAX_TLE_AGE_IGSO if orbit_type == "IGSO" else MAX_TLE_AGE_MEO
    sat_label = f"BDS-{prn}"

    sp3_sat = sp3_df[sp3_df["sat_id"] == prn].copy()
    if sp3_sat.empty:
        return {"norad_id": norad_id, "sat_name": sat_label,
                "orbit_type": orbit_type, "status": "no_sp3"}, None

    try:
        sp3_eci = ecef_to_eci(sp3_sat)
    except Exception as exc:
        return {"norad_id": norad_id, "sat_name": sat_label,
                "orbit_type": orbit_type, "status": f"ecef_eci_error: {exc}"}, None

    if tle_df.empty:
        return {"norad_id": norad_id, "sat_name": sat_label,
                "orbit_type": orbit_type, "status": "no_tle"}, None

    try:
        tle_prop = propagate_best_tles(sp3_eci, tle_df, sat_label, ts,
                                       max_age_days=max_age)
    except Exception as exc:
        return {"norad_id": norad_id, "sat_name": sat_label,
                "orbit_type": orbit_type, "status": f"sgp4_error: {exc}"}, None

    if tle_prop.empty:
        return {"norad_id": norad_id, "sat_name": sat_label,
                "orbit_type": orbit_type, "status": "no_propagation"}, None

    res = compute_residuals(sp3_eci, tle_prop)
    if res.empty:
        return {"norad_id": norad_id, "sat_name": sat_label,
                "orbit_type": orbit_type, "status": "no_match"}, None

    # TLE age column
    _ep = pd.Timestamp("1970-01-01", tz="UTC")
    tle_ep_s  = (pd.to_datetime(tle_df["epoch_utc"], utc=True) - _ep).dt.total_seconds().values
    res_t_s   = (pd.to_datetime(res["t"],            utc=True) - _ep).dt.total_seconds().values
    idx = np.searchsorted(tle_ep_s, res_t_s, side="right") - 1
    idx = np.clip(idx, 0, len(tle_df) - 1)
    used_epochs = pd.to_datetime(tle_df["epoch_utc"].iloc[idx].values, utc=True)
    res["tle_epoch"]    = used_epochs.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    res["tle_age_days"] = ((res_t_s - tle_ep_s[idx]) / 86400.0).round(2)
    res["orbit_type"]   = orbit_type

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
        "orbit_type":      orbit_type,
        "status":          "ok",
        "n_sp3_epochs":    len(sp3_sat["t_gps"].unique()),
        "n_matched":       len(res),
        "n_tles":          len(tle_df),
        "tle_age_days":    round(tle_age, 2),
        "pos_err_mean_km": round(res["pos_err_km"].mean(), 3),
        "pos_err_std_km":  round(res["pos_err_km"].std(), 3),
        "pos_err_max_km":  round(res["pos_err_km"].max(), 3),
        "vel_err_mean_kms": round(res["vel_err_kms"].mean(), 6),
        "dr_r_rms_km":     round(res["dr_r_km"].std(), 3),
        "dr_t_rms_km":     round(res["dr_t_km"].std(), 3),
        "dr_n_rms_km":     round(res["dr_n_km"].std(), 3),
    }
    return summary, res[[c for c in _RESID_OUT_COLS if c in res.columns]]


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_comparison(sp3_parquet_dir: Path, space_db: Path, out_dir: Path,
                   start=None, end=None,
                   prn_filter: list[str] | None = None) -> None:
    import datetime as _dt

    sp3_parquet_dir = Path(sp3_parquet_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    parquets = sorted(sp3_parquet_dir.glob("bds_sp3_*.parquet"))
    if not parquets:
        log.error("No bds_sp3_*.parquet found in %s", sp3_parquet_dir)
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
    log.info("BDS SP3 coverage: %s → %s  (%d PRNs, %d rows)",
             t_start, t_end, sp3_all["sat_id"].nunique(), len(sp3_all))

    available_prns = sorted(sp3_all["sat_id"].unique())
    prns = ([p for p in prn_filter if p in available_prns]
            if prn_filter
            else [p for p in available_prns if p in BDS_PRN_NORAD])

    if not prns:
        log.error("No valid PRNs. Available: %s", available_prns)
        return
    log.info("Processing %d PRNs: %s", len(prns), prns)

    norad_ids = list({BDS_PRN_NORAD[p] for p in prns if p in BDS_PRN_NORAD})
    con = duckdb.connect(str(space_db), read_only=True)
    tle_pool = load_tles(con, norad_ids, t_start, t_end)
    con.close()
    log.info("TLE pool: %d / %d satellites have TLEs", len(tle_pool), len(norad_ids))

    ts = skyfield_load.timescale()
    summaries: list[dict] = []
    resid_frames: list[pd.DataFrame] = []

    for i, prn in enumerate(prns, 1):
        norad_id = BDS_PRN_NORAD.get(prn)
        if norad_id is None:
            log.warning("[%s] No NORAD mapping — skipped", prn)
            continue
        tle_df = tle_pool.get(norad_id, pd.DataFrame())
        orbit_type = "IGSO" if prn in _IGSO_PRNS else "MEO"
        log.info("[%d/%d] %s  NORAD=%d  TLEs=%d  type=%s",
                 i, len(prns), prn, norad_id, len(tle_df), orbit_type)

        summary, res = process_satellite(prn, norad_id, sp3_all, tle_df, ts)
        summaries.append(summary)
        if res is not None:
            resid_frames.append(res)

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
            meo_ok  = ok[ok["orbit_type"] == "MEO"]
            igso_ok = ok[ok["orbit_type"] == "IGSO"]
            print("\n=== BeiDou SP3 vs TLE ===")
            if not meo_ok.empty:
                print(f"  MEO  衛星數: {len(meo_ok)}")
                print(f"  MEO  平均位置誤差: {meo_ok['pos_err_mean_km'].mean():.2f} km")
                print(f"  MEO  Along-track RMS: {meo_ok['dr_t_rms_km'].mean():.2f} km")
                print(f"  MEO  Cross-track RMS: {meo_ok['dr_n_rms_km'].mean():.2f} km")
            if not igso_ok.empty:
                print(f"  IGSO 衛星數: {len(igso_ok)}")
                print(f"  IGSO 平均位置誤差: {igso_ok['pos_err_mean_km'].mean():.2f} km")
            print(f"\n  Summary  → {summary_path}")
            print(f"  Residuals → {resid_path}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="BeiDou SP3 vs TLE 殘差計算",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--sp3-dir", default="data/bds_orbits")
    p.add_argument("--db",      default="space_db.duckdb")
    p.add_argument("--out-dir", default="data/bds_comparison")
    p.add_argument("--start",   default=None, help="YYYY-MM-DD")
    p.add_argument("--end",     default=None, help="YYYY-MM-DD")
    p.add_argument("--prn",     nargs="+", default=None, metavar="PRN")
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
