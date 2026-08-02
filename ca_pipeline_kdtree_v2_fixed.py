# ca_pipeline_kdtree_v2_fixed.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import duckdb
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.spatial import cKDTree
from sgp4.api import Satrec, jday

EARTH_MU_KM3_S2 = 398600.4418
EARTH_RADIUS_KM = 6378.137


def isoformat_utc(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def safe_name(name: Optional[str], norad_id: Optional[int] = None) -> str:
    if isinstance(name, str) and name.strip():
        return name.strip()
    if norad_id is not None:
        return f"NORAD_{norad_id}"
    return "UNKNOWN"


def df_to_records_clean(df: pd.DataFrame) -> List[Dict[str, Any]]:
    if df is None or df.empty:
        return []
    records = []
    for row in df.to_dict(orient="records"):
        clean = {}
        for k, v in row.items():
            if isinstance(v, pd.Timestamp):
                clean[k] = isoformat_utc(v.to_pydatetime())
            elif isinstance(v, datetime):
                clean[k] = isoformat_utc(v)
            elif isinstance(v, (np.integer,)):
                clean[k] = int(v)
            elif isinstance(v, (np.floating,)):
                clean[k] = float(v)
            elif pd.isna(v):
                clean[k] = None
            else:
                clean[k] = v
        records.append(clean)
    return records


def tle_to_perigee_apogee_km(mean_motion_rev_per_day: float, eccentricity: float) -> Tuple[float, float, float]:
    n_rad_s = mean_motion_rev_per_day * 2.0 * np.pi / 86400.0
    a_km = (EARTH_MU_KM3_S2 / (n_rad_s ** 2)) ** (1.0 / 3.0)
    perigee_km = a_km * (1.0 - eccentricity) - EARTH_RADIUS_KM
    apogee_km = a_km * (1.0 + eccentricity) - EARTH_RADIUS_KM
    return perigee_km, apogee_km, a_km


def angular_diff_deg(a_deg: float, b_deg: float) -> float:
    diff = (a_deg - b_deg + 180.0) % 360.0 - 180.0
    return abs(diff)


def load_tle_raw_from_db(db_path: str, target_norad_id: int):
    conn = duckdb.connect(db_path)
    try:
        catalog_query = """
        WITH latest AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY norad_id
                ORDER BY tle_epoch DESC, load_time DESC
            ) AS rn
            FROM tle_raw
            WHERE line1 IS NOT NULL
              AND line2 IS NOT NULL
              AND mean_motion IS NOT NULL
              AND inclination_deg IS NOT NULL
              AND eccentricity IS NOT NULL
        )
        SELECT norad_id, name, line1, line2,
               tle_epoch, tle_epoch_year, tle_epoch_day,
               inclination_deg, eccentricity, mean_motion,
               raan_deg, argp_deg, mean_anomaly_deg
        FROM latest
        WHERE rn = 1
          AND norad_id != ?
        """
        catalog = conn.execute(catalog_query, [target_norad_id]).fetchall()

        target_query = """
        WITH latest AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY norad_id
                ORDER BY tle_epoch DESC, load_time DESC
            ) AS rn
            FROM tle_raw
            WHERE norad_id = ?
        )
        SELECT norad_id, name, line1, line2,
               tle_epoch, tle_epoch_year, tle_epoch_day,
               inclination_deg, eccentricity, mean_motion,
               raan_deg, argp_deg, mean_anomaly_deg
        FROM latest
        WHERE rn = 1
        """
        target_row = conn.execute(target_query, [target_norad_id]).fetchone()
        return target_row, catalog
    finally:
        conn.close()


def angular_momentum_normed(r: np.ndarray, v: np.ndarray) -> np.ndarray:
    h = np.cross(r, v)
    h_norm = np.linalg.norm(h)
    if h_norm <= 0:
        raise ValueError("invalid angular momentum norm")
    return h / h_norm


def eci_to_rtn_basis(r_eci: np.ndarray, v_eci: np.ndarray) -> np.ndarray:
    r_norm = np.linalg.norm(r_eci)
    if r_norm <= 0:
        raise ValueError("invalid position norm")
    R = r_eci / r_norm
    N = angular_momentum_normed(r_eci, v_eci)
    T = np.cross(N, R)
    t_norm = np.linalg.norm(T)
    if t_norm <= 0:
        raise ValueError("invalid transverse norm")
    T = T / t_norm
    return np.stack([R, T, N], axis=0)


def pseudo_cov_tle_leo(sigma_r_km: float = 1.0, sigma_t_km: float = 5.0, sigma_n_km: float = 3.0) -> np.ndarray:
    return np.diag([sigma_r_km ** 2, sigma_t_km ** 2, sigma_n_km ** 2])


def compute_pc_monte_carlo(r_rel_rtn: np.ndarray, C1_rtn: np.ndarray, C2_rtn: np.ndarray, Rc_km: float = 0.01, n_mc: int = 20000, rng: Optional[np.random.Generator] = None) -> float:
    if rng is None:
        rng = np.random.default_rng(42)
    C_rel = C1_rtn + C2_rtn
    C_RT = C_rel[:2, :2]
    r_RT = r_rel_rtn[:2]
    try:
        L = np.linalg.cholesky(C_RT)
    except np.linalg.LinAlgError:
        vals, vecs = np.linalg.eigh(C_RT)
        vals = np.clip(vals, 1e-10, None)
        C_RT = vecs @ np.diag(vals) @ vecs.T
        L = np.linalg.cholesky(C_RT)
    z = rng.normal(size=(2, n_mc))
    samples = (L @ z).T + r_RT
    dist = np.linalg.norm(samples, axis=1)
    return float(np.mean(dist <= Rc_km))


def risk_label_from_pc(pc: float) -> str:
    if pc >= 1e-3:
        return "HIGH"
    if pc >= 1e-5:
        return "MEDIUM"
    if pc >= 1e-7:
        return "LOW"
    return "VERY_LOW"


def build_satrec(line1: str, line2: str) -> Satrec:
    return Satrec.twoline2rv(line1, line2)


def propagate_satrec_rv(sat: Satrec, t: datetime) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6)
    err, r, v = sat.sgp4(jd, fr)
    if err != 0:
        return None, None
    return np.array(r, dtype=float), np.array(v, dtype=float)


def compute_target_orbit_extremes_from_tle(mean_motion: float, eccentricity: float) -> Tuple[float, float]:
    peri_km, apo_km, _ = tle_to_perigee_apogee_km(mean_motion, eccentricity)
    return peri_km, apo_km


def pre_filter_candidates(target_row, catalog, padding_km: float, t_inc: float, t_perigee_km: float, t_apogee_km: float, max_delta_inc_deg: Optional[float] = None, max_delta_raan_deg: Optional[float] = None, debug: bool = False, debug_logs: Optional[List[str]] = None):
    candidates = []
    target_raan = target_row[10] if len(target_row) > 10 else None
    for i, row in enumerate(catalog):
        norad, name, l1, l2, tle_epoch, tle_epoch_year, tle_epoch_day, inc, ecc, mm, raan_deg, argp_deg, mean_anomaly_deg = row
        if mm is None or ecc is None:
            continue
        try:
            peri_km, apo_km, _ = tle_to_perigee_apogee_km(mm, ecc)
        except Exception:
            continue
        overlap = not (apo_km < t_perigee_km - padding_km or peri_km > t_apogee_km + padding_km)
        if not overlap:
            continue
        if max_delta_inc_deg is not None and abs(inc - t_inc) > max_delta_inc_deg:
            continue
        if max_delta_raan_deg is not None and target_raan is not None and raan_deg is not None:
            if angular_diff_deg(raan_deg, target_raan) > max_delta_raan_deg:
                continue
        if debug and i < 10 and debug_logs is not None:
            debug_logs.append(f"[DEBUG] {norad:>6} {safe_name(name, norad)[:24]:24s} peri={peri_km:8.1f} apo={apo_km:8.1f} t_peri={t_perigee_km:8.1f} t_apo={t_apogee_km:8.1f} overlap={overlap}")
        candidates.append((norad, safe_name(name, norad), l1, l2))
    return candidates


def generate_time_grid(center: datetime, hours_before: float, hours_after: float, step_seconds: int) -> List[datetime]:
    start = center - timedelta(hours=hours_before)
    end = center + timedelta(hours=hours_after)
    total_seconds = int((end - start).total_seconds())
    n_steps = total_seconds // step_seconds
    return [start + timedelta(seconds=i * step_seconds) for i in range(n_steps + 1)]


def stage_b_kdtree_scan_satrec(target_sat: Satrec, secondary_map: Dict[int, Tuple[str, Satrec]], center_time: datetime, hours_before: float, hours_after: float, step_seconds: int, miss_threshold_km: float) -> pd.DataFrame:
    times = generate_time_grid(center_time, hours_before, hours_after, step_seconds)
    sec_ids = list(secondary_map.keys())
    records: List[dict] = []
    for t in times:
        r_t, _ = propagate_satrec_rv(target_sat, t)
        if r_t is None:
            continue
        pts = []
        valid_ids = []
        valid_names = []
        for nid in sec_ids:
            _, sec_sat = secondary_map[nid]
            r_s, _ = propagate_satrec_rv(sec_sat, t)
            if r_s is None:
                continue
            pts.append(r_s)
            valid_ids.append(nid)
            valid_names.append(secondary_map[nid][0])
        if not pts:
            continue
        pts = np.vstack(pts)
        idxs = cKDTree(pts).query_ball_point(r_t, r=miss_threshold_km)
        for idx in idxs:
            records.append({
                "secondary_norad": int(valid_ids[idx]),
                "secondary_name": valid_names[idx],
                "coarse_hit_time_utc": t,
                "coarse_miss_km": float(np.linalg.norm(pts[idx] - r_t)),
            })
    if not records:
        return pd.DataFrame(columns=["secondary_norad", "secondary_name", "coarse_hit_time_utc", "coarse_miss_km"])
    df = pd.DataFrame(records)
    return df.sort_values(["secondary_norad", "coarse_miss_km", "coarse_hit_time_utc"]).drop_duplicates(subset=["secondary_norad"]).reset_index(drop=True)


def build_relative_timeseries(target_sat: Satrec, secondary_sat: Satrec, center_time: datetime, hours_before: float, hours_after: float, step_seconds: int) -> List[Dict[str, Any]]:
    series: List[Dict[str, Any]] = []
    for t in generate_time_grid(center_time, hours_before, hours_after, step_seconds):
        r1, v1 = propagate_satrec_rv(target_sat, t)
        r2, v2 = propagate_satrec_rv(secondary_sat, t)
        if r1 is None or v1 is None or r2 is None or v2 is None:
            continue
        dr = r2 - r1
        dv = v2 - v1
        series.append({
            "time_utc": isoformat_utc(t),
            "relative_distance_km": round(float(np.linalg.norm(dr)), 6),
            "relative_speed_km_s": round(float(np.linalg.norm(dv)), 6),
        })
    return series


def refine_tca_with_pc_minimize(target_sat: Satrec, secondary_sat: Satrec, coarse_time: datetime, coarse_window_minutes: float = 10.0, Rc_km: float = 0.01, n_mc: int = 20000, sigma_r_km: float = 1.0, sigma_t_km: float = 5.0, sigma_n_km: float = 3.0) -> Tuple[Optional[datetime], Optional[float], Optional[float], Optional[float], Optional[np.ndarray]]:
    span_seconds = int(coarse_window_minutes * 60)
    t0 = coarse_time
    def d2_of_dt(dt_seconds: float) -> float:
        t = t0 + timedelta(seconds=float(dt_seconds))
        r1, _ = propagate_satrec_rv(target_sat, t)
        r2, _ = propagate_satrec_rv(secondary_sat, t)
        if r1 is None or r2 is None:
            return 1e30
        dr = r2 - r1
        return float(np.dot(dr, dr))
    res = minimize_scalar(d2_of_dt, bounds=(-span_seconds, span_seconds), method="bounded", options={"xatol": 0.1})
    if not res.success:
        return None, None, None, None, None
    tca = t0 + timedelta(seconds=float(res.x))
    r1, v1 = propagate_satrec_rv(target_sat, tca)
    r2, v2 = propagate_satrec_rv(secondary_sat, tca)
    if r1 is None or r2 is None or v1 is None or v2 is None:
        return None, None, None, None, None
    dr = r2 - r1
    dv = v2 - v1
    miss_km = float(np.linalg.norm(dr))
    rel_vel_km_s = float(np.linalg.norm(dv))
    try:
        r_rel_rtn = eci_to_rtn_basis(r1, v1) @ dr
    except Exception:
        return None, None, None, None, None
    C1 = pseudo_cov_tle_leo(sigma_r_km=sigma_r_km, sigma_t_km=sigma_t_km, sigma_n_km=sigma_n_km)
    C2 = pseudo_cov_tle_leo(sigma_r_km=sigma_r_km, sigma_t_km=sigma_t_km, sigma_n_km=sigma_n_km)
    pc = compute_pc_monte_carlo(r_rel_rtn=r_rel_rtn, C1_rtn=C1, C2_rtn=C2, Rc_km=Rc_km, n_mc=n_mc)
    return tca, miss_km, rel_vel_km_s, pc, r_rel_rtn


def run_ca_pipeline(db_path: str, target_norad_id: int, time_start: datetime, time_span_hours: float = 24.0, coarse_dt_sec: int = 300, miss_threshold_km: float = 50.0, prefilter_padding_km: float = 300.0, rcs1_km: float = 0.01, rcs2_km: float = 0.01, max_delta_inc_deg: Optional[float] = None, max_delta_raan_deg: Optional[float] = None, top_n: int = 100, debug: bool = False, coarse_hours_before: Optional[float] = None, coarse_hours_after: Optional[float] = None, fine_window_minutes: float = 10.0, Rc_km: float = 0.01, n_mc: int = 20000, sigma_r_km: float = 1.0, sigma_t_km: float = 5.0, sigma_n_km: float = 3.0, chart_dt_sec: int = 300) -> Dict[str, Any]:
    debug_logs: List[str] = []
    t0 = time.perf_counter()
    if time_start.tzinfo is None:
        time_start = time_start.replace(tzinfo=timezone.utc)
    if coarse_hours_before is None:
        coarse_hours_before = time_span_hours / 2.0
    if coarse_hours_after is None:
        coarse_hours_after = time_span_hours / 2.0
    target_row, catalog = load_tle_raw_from_db(db_path, target_norad_id)
    if target_row is None:
        raise ValueError(f"tle_raw 找不到 NORAD {target_norad_id} 的 TLE")
    target_name = safe_name(target_row[1], target_row[0])
    t_inc = target_row[7]
    t_ecc = target_row[8]
    t_mm = target_row[9]
    t_perigee_km, t_apogee_km = compute_target_orbit_extremes_from_tle(t_mm, t_ecc)
    debug_logs.append(f"[DEBUG] Target {target_name} ({target_row[0]})")
    debug_logs.append(f"[DEBUG] inc={t_inc:.3f} deg, perigee={t_perigee_km:.1f} km, apogee={t_apogee_km:.1f} km")
    debug_logs.append(f"[DEBUG] catalog size={len(catalog)}")
    candidates = pre_filter_candidates(target_row, catalog, prefilter_padding_km, t_inc, t_perigee_km, t_apogee_km, max_delta_inc_deg, max_delta_raan_deg, debug, debug_logs)
    debug_logs.append(f"[DEBUG] prefilter candidates={len(candidates)} / {len(catalog)}")
    if not candidates:
        elapsed_sec = time.perf_counter() - t0
        return {
            "status": "ok",
            "input": {"db_path": db_path, "target_norad_id": target_norad_id, "time_start_utc": isoformat_utc(time_start), "time_span_hours": time_span_hours, "chart_dt_sec": chart_dt_sec},
            "summary": {"target_name": target_name, "target_norad_id": int(target_norad_id), "catalog_size": int(len(catalog)), "prefilter_candidate_count": 0, "coarse_hit_count": 0, "event_count": 0, "target_perigee_km": round(t_perigee_km, 6), "target_apogee_km": round(t_apogee_km, 6)},
            "events": [], "debug": debug_logs if debug else [], "timing": {"elapsed_sec": round(elapsed_sec, 6)}
        }
    target_sat = build_satrec(target_row[2], target_row[3])
    secondary_map: Dict[int, Tuple[str, Satrec]] = {}
    for norad, name, l1, l2 in candidates:
        try:
            secondary_map[int(norad)] = (name, build_satrec(l1, l2))
        except Exception as e:
            debug_logs.append(f"[WARN] failed to build Satrec for {norad}: {repr(e)}")
    coarse_hits_df = stage_b_kdtree_scan_satrec(target_sat, secondary_map, time_start, coarse_hours_before, coarse_hours_after, coarse_dt_sec, miss_threshold_km)
    debug_logs.append(f"[DEBUG] coarse hits={len(coarse_hits_df)}")
    results: List[dict] = []
    for row in coarse_hits_df.itertuples(index=False):
        sec_id = int(row.secondary_norad)
        sec_name, sec_sat = secondary_map.get(sec_id, (row.secondary_name, None))
        if sec_sat is None:
            continue
        tca, miss_km, rel_vel_km_s, pc, r_rel_rtn = refine_tca_with_pc_minimize(target_sat, sec_sat, row.coarse_hit_time_utc, fine_window_minutes, Rc_km, n_mc, sigma_r_km, sigma_t_km, sigma_n_km)
        if tca is None:
            debug_logs.append(f"[WARN] Stage C failed for {sec_id}")
            continue
        rel_series = build_relative_timeseries(target_sat, sec_sat, time_start, coarse_hours_before, coarse_hours_after, chart_dt_sec)
        results.append({
            "secondary_norad": sec_id,
            "secondary_name": sec_name,
            "coarse_hit_time_utc": isoformat_utc(row.coarse_hit_time_utc),
            "tca_utc": isoformat_utc(tca),
            "coarse_miss_km": round(float(row.coarse_miss_km), 6),
            "miss_distance_km": round(float(miss_km), 6),
            "rel_velocity_km_s": round(float(rel_vel_km_s), 6),
            "pc": round(float(pc), 12),
            "risk_label": risk_label_from_pc(pc),
            "r_rel_r_km": round(float(r_rel_rtn[0]), 6),
            "r_rel_t_km": round(float(r_rel_rtn[1]), 6),
            "r_rel_n_km": round(float(r_rel_rtn[2]), 6),
            "relative_series": rel_series,
        })
    results.sort(key=lambda x: (x["miss_distance_km"], -x["pc"]))
    if top_n is not None and top_n > 0:
        results = results[:top_n]
    elapsed_sec = time.perf_counter() - t0
    return {
        "status": "ok",
        "input": {
            "db_path": db_path, "target_norad_id": target_norad_id, "time_start_utc": isoformat_utc(time_start), "time_span_hours": time_span_hours,
            "coarse_dt_sec": coarse_dt_sec, "miss_threshold_km": miss_threshold_km, "prefilter_padding_km": prefilter_padding_km,
            "rcs1_km": rcs1_km, "rcs2_km": rcs2_km, "max_delta_inc_deg": max_delta_inc_deg, "max_delta_raan_deg": max_delta_raan_deg,
            "top_n": top_n, "coarse_hours_before": coarse_hours_before, "coarse_hours_after": coarse_hours_after, "fine_window_minutes": fine_window_minutes,
            "Rc_km": Rc_km, "n_mc": n_mc, "sigma_r_km": sigma_r_km, "sigma_t_km": sigma_t_km, "sigma_n_km": sigma_n_km, "chart_dt_sec": chart_dt_sec,
        },
        "summary": {
            "target_name": target_name, "target_norad_id": int(target_norad_id), "catalog_size": int(len(catalog)), "prefilter_candidate_count": int(len(candidates)),
            "coarse_hit_count": int(len(coarse_hits_df)), "event_count": int(len(results)), "target_perigee_km": round(t_perigee_km, 6), "target_apogee_km": round(t_apogee_km, 6),
        },
        "events": results,
        "debug": debug_logs if debug else [],
        "timing": {"elapsed_sec": round(elapsed_sec, 6)},
    }


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Close approach pipeline using DuckDB tle_raw + Satrec + KD-tree Stage B + RTN Monte Carlo Stage C")
    parser.add_argument("--db-path", default=os.getenv("SPACE_DB_PATH", "./space_db.duckdb"))
    parser.add_argument("--target-norad-id", type=int, required=True)
    parser.add_argument("--time-start", default=None)
    parser.add_argument("--time-span-hours", type=float, default=24.0)
    parser.add_argument("--coarse-hours-before", type=float, default=12)
    parser.add_argument("--coarse-hours-after", type=float, default=12)
    parser.add_argument("--coarse-dt-sec", type=int, default=300)
    parser.add_argument("--miss-threshold-km", type=float, default=50.0)
    parser.add_argument("--prefilter-padding-km", type=float, default=300.0)
    parser.add_argument("--rcs1-km", type=float, default=0.01)
    parser.add_argument("--rcs2-km", type=float, default=0.01)
    parser.add_argument("--max-delta-inc-deg", type=float, default=5.0)
    parser.add_argument("--max-delta-raan-deg", type=float, default=30.0)
    parser.add_argument("--top-n", type=int, default=100)
    parser.add_argument("--fine-window-minutes", type=float, default=10.0)
    parser.add_argument("--Rc-km", type=float, default=0.01)
    parser.add_argument("--n-mc", type=int, default=20000)
    parser.add_argument("--sigma-r-km", type=float, default=1.0)
    parser.add_argument("--sigma-t-km", type=float, default=5.0)
    parser.add_argument("--sigma-n-km", type=float, default=3.0)
    parser.add_argument("--chart-dt-sec", type=int, default=300)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--pretty-json", action="store_true")
    parser.add_argument("--output-json-path", default=None)
    parser.add_argument("--export-csv", default=None)
    return parser


def parse_time_start(s: Optional[str]) -> datetime:
    if not s:
        return now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    try:
        result = run_ca_pipeline(db_path=args.db_path, target_norad_id=args.target_norad_id, time_start=parse_time_start(args.time_start), time_span_hours=args.time_span_hours, coarse_dt_sec=args.coarse_dt_sec, miss_threshold_km=args.miss_threshold_km, prefilter_padding_km=args.prefilter_padding_km, rcs1_km=args.rcs1_km, rcs2_km=args.rcs2_km, max_delta_inc_deg=args.max_delta_inc_deg, max_delta_raan_deg=args.max_delta_raan_deg, top_n=args.top_n, debug=args.debug, coarse_hours_before=args.coarse_hours_before, coarse_hours_after=args.coarse_hours_after, fine_window_minutes=args.fine_window_minutes, Rc_km=args.Rc_km, n_mc=args.n_mc, sigma_r_km=args.sigma_r_km, sigma_t_km=args.sigma_t_km, sigma_n_km=args.sigma_n_km, chart_dt_sec=args.chart_dt_sec)
        if args.export_csv and result["events"]:
            pd.DataFrame(result["events"]).to_csv(args.export_csv, index=False)
        if args.output_json_path:
            with open(args.output_json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2 if args.pretty_json else None)
        print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty_json else None))
    except Exception as e:
        err = {"status": "error", "error": {"type": type(e).__name__, "message": str(e), "traceback": traceback.format_exc()}}
        if args.output_json_path:
            with open(args.output_json_path, "w", encoding="utf-8") as f:
                json.dump(err, f, ensure_ascii=False, indent=2)
        print(json.dumps(err, ensure_ascii=False, indent=2))
        raise SystemExit(1)

if __name__ == "__main__":
    main()
