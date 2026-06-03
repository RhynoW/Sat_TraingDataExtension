# conjunction_pipeline.py
#!/usr/bin/env python3
"""
Conjunction screening pipeline (Stage A/B/C) using DuckDB raw_tle_archive + SGP4.

Stage A:  從 raw_tle_archive 抽某次 TLE 下載快照，對目標星作
          |Δa| <= delta_a_km, |Δi| <= delta_i_deg, |ΔΩ_unwrapped| <= delta_raan_deg 的預篩，
          或使用橢圓軌道幾何粗篩 (rmin/rmax + e, i, RAAN)。

Stage B:  以目標 epoch 為中心 ±coarse_hours，粗時間步長 coarse_step_seconds，
          對 Stage A 候選用 SGP4 傳播，配合 cKDTree 搜尋 miss_distance < coarse_miss_threshold_km 的粗命中。

Stage C:  對每顆粗命中衛星，在 coarse_hit_time 附近做細部 TCA 搜尋（可選 grid 或 minimize_scalar），
          於 TCA 計算 RTN frame 相對位置與 pseudo-covariance，Monte Carlo 估算 Pc，
          依 Pc 給 risk_label，並寫入 DuckDB conjunction_events。
"""

import os
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import duckdb
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from scipy.optimize import minimize_scalar
from sgp4.api import Satrec, jday


# ==========================
# 基本常數
# ==========================

EARTH_MU_KM3_S2 = 398600.4418


# ==========================
# 工具函式
# ==========================

def angular_diff_deg(a_deg: float, b_deg: float) -> float:
    """
    兩個角度的最小差值，結果落在 [0, 180] deg。
    """
    diff = (a_deg - b_deg + 180.0) % 360.0 - 180.0
    return abs(diff)


def propagate_sat_rv(sat: Satrec, t: datetime) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """
    使用 SGP4 傳播，回傳 (r_eci_km, v_eci_km_s)。
    如錯誤，回傳 (None, None)。
    """
    jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6)
    err, r, v = sat.sgp4(jd, fr)
    if err != 0:
        return None, None
    return np.array(r, dtype=float), np.array(v, dtype=float)


def generate_time_grid(
    center: datetime,
    hours_before: float,
    hours_after: float,
    step_seconds: int,
) -> List[datetime]:
    """
    以 center 為中心，從 -hours_before 到 +hours_after，
    固定步長 step_seconds 產生時間序列。
    """
    start = center - timedelta(hours=hours_before)
    end = center + timedelta(hours=hours_after)
    total_seconds = int((end - start).total_seconds())
    n_steps = total_seconds // step_seconds
    return [start + timedelta(seconds=i * step_seconds) for i in range(n_steps + 1)]


def eci_to_rtn_basis(r_eci: np.ndarray, v_eci: np.ndarray) -> np.ndarray:
    """
    建立 RTN 座標系的 3x3 轉換矩陣 (rows = [u_R; u_T; u_N])。
    """
    R = r_eci / np.linalg.norm(r_eci)
    h = np.cross(r_eci, v_eci)
    N = h / np.linalg.norm(h)
    T = np.cross(N, R)
    return np.stack([R, T, N], axis=0)


def pseudo_cov_tle_leo() -> np.ndarray:
    """
    為 LEO + TLE/SGP4 提供一個粗略的 RTN pseudo-covariance (km^2)。
    可依你實際統計調整。
    """
    sigma_R = 1.0   # km
    sigma_T = 5.0   # km
    sigma_N = 3.0   # km
    return np.diag([sigma_R**2, sigma_T**2, sigma_N**2])


def compute_pc_simplified(
    r_rel_rtn: np.ndarray,
    C1_rtn: np.ndarray,
    C2_rtn: np.ndarray,
    Rc_km: float = 0.01,
    n_mc: int = 20000,
) -> float:
    """
    非嚴格、示範用 Pc：
    - C_rel = C1 + C2
    - 只考慮 RT 平面 (2D)
    - Monte Carlo 估計落在半徑 Rc 的圓形區域內的機率
    """
    C_rel = C1_rtn + C2_rtn
    C_RT = C_rel[:2, :2]
    r_RT = r_rel_rtn[:2]

    # Cholesky，必要時修正為正定
    try:
        L = np.linalg.cholesky(C_RT)
    except np.linalg.LinAlgError:
        vals, vecs = np.linalg.eigh(C_RT)
        vals = np.clip(vals, 1e-6, None)
        C_RT = vecs @ np.diag(vals) @ vecs.T
        L = np.linalg.cholesky(C_RT)

    z = np.random.normal(size=(2, n_mc))
    samples = (L @ z).T + r_RT  # 每列一個樣本
    dist = np.linalg.norm(samples, axis=1)
    pc = float(np.mean(dist <= Rc_km))
    return pc


def risk_label_from_pc(pc: float) -> str:
    """
    簡化版風險等級：High / Medium / Low / Very Low。
    門檻可依你之後標定調整。
    """
    if pc >= 1e-3:
        return "HIGH"
    if pc >= 1e-5:
        return "MEDIUM"
    if pc >= 1e-7:
        return "LOW"
    return "VERY_LOW"


# ==========================
# Stage A – 從 raw_tle_archive 做幾何預篩 (舊版 Δa/Δi/ΔΩ)
# ==========================

def load_stageA_candidates(
    db_path: str,
    target_norad: int,
    delta_a_km: float = 20.0,
    delta_i_deg: float = 1.0,
    delta_raan_deg: float = 15.0,
    snapshot_date: Optional[str] = None,  # 'YYYY-MM-DD'，None 則取最近一次 epoch_utc
) -> Tuple[pd.DataFrame, datetime]:
    """
    Stage A (舊版):
    snapshot 的定義 = TLE epoch 所在日期 (CAST(epoch_utc AS DATE))。

    流程：
    1) 先找目標星在該 snapshot 日期的最新一筆 epoch_utc 作為目標 TLE
       - 若 snapshot_date 為 None，則用目標星所有 TLE 中最新一筆
       - 若指定 snapshot_date，但該日目標星沒有 TLE，則退回目標星全體最新一筆
    2) 以「目標 TLE 的日期」為 snapshot_date，抓出 raw_tle_archive 中
       同一天所有衛星的 TLE
    3) 在此 snapshot 內對目標星作 |Δa|, |Δi|, unwrap ΔΩ 預篩
    4) 回傳候選 DataFrame 與目標 epoch_utc（作為 Stage B 中心時間）
    """
    con = duckdb.connect(db_path)

    # 先找目標星的代表 TLE
    if snapshot_date is not None:
        df_target = con.execute(
            """
            SELECT
                norad_id,
                object_name,
                line1,
                line2,
                epoch_utc,
                sma_km,
                inclination_deg,
                raan_deg,
                eccentricity,
                mean_motion
            FROM raw_tle_archive
            WHERE norad_id = ?
              AND CAST(epoch_utc AS DATE) = CAST(? AS DATE)
            ORDER BY epoch_utc DESC
            LIMIT 1
            """,
            [target_norad, snapshot_date],
        ).df()
        if df_target.empty:
            df_target = con.execute(
                """
                SELECT
                    norad_id,
                    object_name,
                    line1,
                    line2,
                    epoch_utc,
                    sma_km,
                    inclination_deg,
                    raan_deg,
                    eccentricity,
                    mean_motion
                FROM raw_tle_archive
                WHERE norad_id = ?
                ORDER BY epoch_utc DESC
                LIMIT 1
                """,
                [target_norad],
            ).df()
    else:
        df_target = con.execute(
            """
            SELECT
                norad_id,
                object_name,
                line1,
                line2,
                epoch_utc,
                sma_km,
                inclination_deg,
                raan_deg,
                eccentricity,
                mean_motion
            FROM raw_tle_archive
            WHERE norad_id = ?
            ORDER BY epoch_utc DESC
            LIMIT 1
            """,
            [target_norad],
        ).df()

    if df_target.empty:
        con.close()
        raise ValueError(f"raw_tle_archive 找不到 NORAD {target_norad} 在任何日期的 TLE")

    target = df_target.iloc[0]
    epoch_center = target["epoch_utc"]
    if epoch_center.tzinfo is None:
        epoch_center = epoch_center.replace(tzinfo=timezone.utc)
    snapshot_day = epoch_center.date().isoformat()

    # 以目標星 epoch 所在日期為 snapshot，抓出同一天所有 TLE
    df = con.execute(
        """
        SELECT
            norad_id,
            object_name,
            line1,
            line2,
            epoch_utc,
            sma_km,
            inclination_deg,
            raan_deg,
            eccentricity,
            mean_motion
        FROM raw_tle_archive
        WHERE CAST(epoch_utc AS DATE) = CAST(? AS DATE)
        """,
        [snapshot_day],
    ).df()
    con.close()

    if df.empty:
        raise ValueError(f"raw_tle_archive 在 {snapshot_day} 當天沒有任何 TLE 記錄")

    # 取得目標星（理論上一定存在，但再檢查一次）
    df_target_day = df[df["norad_id"] == target_norad]
    if df_target_day.empty:
        raise ValueError(f"NORAD {target_norad} 不在 {snapshot_day} 這個 snapshot 中")

    target = df_target_day.iloc[0]
    sma0 = target["sma_km"]
    inc0 = target["inclination_deg"]
    raan0 = target["raan_deg"]

    def _raan_diff(raan: float) -> float:
        return angular_diff_deg(raan, raan0)

    df["delta_a_km"] = (df["sma_km"] - sma0).abs()
    df["delta_i_deg"] = (df["inclination_deg"] - inc0).abs()
    df["delta_raan_deg"] = df["raan_deg"].apply(_raan_diff)

    mask = (
        (df["norad_id"] != target_norad) &
        (df["delta_a_km"] <= delta_a_km) &
        (df["delta_i_deg"] <= delta_i_deg) &
        (df["delta_raan_deg"] <= delta_raan_deg)
    )

    df_out = df[mask].sort_values(
        ["delta_a_km", "delta_i_deg", "delta_raan_deg"]
    ).reset_index(drop=True)

    return df_out, epoch_center

# ==========================
# Stage A – 橢圓軌道幾何預篩 (使用 rmin/rmax + e, i, RAAN)
# ==========================

def load_stageA_candidates_elliptic(
    db_path: str,
    target_norad: int,
    snapshot_date: Optional[str] = None,  # 'YYYY-MM-DD'，None 則取最近一次 epoch_utc
    radial_buffer_km: float = 50.0,
    max_delta_ecc: float = 0.3,
    max_delta_inc_deg: float = 5.0,
    max_delta_raan_deg: float = 30.0,
) -> Tuple[pd.DataFrame, datetime]:
    """
    Stage A (改良版，考慮橢圓軌道幾何)：
    snapshot 的定義 = TLE epoch 所在日期 (CAST(epoch_utc AS DATE))。

    流程：
    1) 先找目標星在該 snapshot 日期的最新一筆 epoch_utc 作為目標 TLE
       - 若 snapshot_date 為 None，則用目標星所有 TLE 中最新一筆
       - 若指定 snapshot_date，但該日目標星沒有 TLE，則退回目標星全體最新一筆
    2) 以「目標 TLE 的日期」為 snapshot_date，抓出 raw_tle_archive 中
       同一天所有衛星的幾何欄位
    3) 依 radial overlap + |Δecc| + |Δinc| + |ΔRAAN| 做 Stage A 預篩
    4) 回傳候選 DataFrame 與目標 epoch_utc（作為 Stage B 的中心時間）
    """
    con = duckdb.connect(db_path)

    # 先找目標星的代表 TLE（目標中心 epoch）
    if snapshot_date is not None:
        df_target = con.execute(
            """
            SELECT
                norad_id,
                object_name,
                line1,
                line2,
                epoch_utc,
                sma_km,
                rmin_km,
                rmax_km,
                eccentricity,
                inclination_deg,
                raan_deg,
                argp_deg,
                mean_anomaly_deg
            FROM raw_tle_archive
            WHERE norad_id = ?
              AND CAST(epoch_utc AS DATE) = CAST(? AS DATE)
            ORDER BY epoch_utc DESC
            LIMIT 1
            """,
            [target_norad, snapshot_date],
        ).df()
        # 若該日沒有 TLE，就退回用該星最新一筆
        if df_target.empty:
            df_target = con.execute(
                """
                SELECT
                    norad_id,
                    object_name,
                    line1,
                    line2,
                    epoch_utc,
                    sma_km,
                    rmin_km,
                    rmax_km,
                    eccentricity,
                    inclination_deg,
                    raan_deg,
                    argp_deg,
                    mean_anomaly_deg
                FROM raw_tle_archive
                WHERE norad_id = ?
                ORDER BY epoch_utc DESC
                LIMIT 1
                """,
                [target_norad],
            ).df()
    else:
        # 未指定日期，直接用目標星最新 TLE
        df_target = con.execute(
            """
            SELECT
                norad_id,
                object_name,
                line1,
                line2,
                epoch_utc,
                sma_km,
                rmin_km,
                rmax_km,
                eccentricity,
                inclination_deg,
                raan_deg,
                argp_deg,
                mean_anomaly_deg
            FROM raw_tle_archive
            WHERE norad_id = ?
            ORDER BY epoch_utc DESC
            LIMIT 1
            """,
            [target_norad],
        ).df()

    if df_target.empty:
        con.close()
        raise ValueError(f"raw_tle_archive 找不到 NORAD {target_norad} 在任何日期的 TLE")

    tgt = df_target.iloc[0]
    epoch_center = tgt["epoch_utc"]
    if epoch_center.tzinfo is None:
        epoch_center = epoch_center.replace(tzinfo=timezone.utc)
    snapshot_day = epoch_center.date().isoformat()

    # 以目標星 epoch 所在日期為 snapshot，抓出同一天所有幾何欄位
    df = con.execute(
        """
        SELECT
            norad_id,
            object_name,
            line1,
            line2,
            epoch_utc,
            sma_km,
            rmin_km,
            rmax_km,
            eccentricity,
            inclination_deg,
            raan_deg,
            argp_deg,
            mean_anomaly_deg
        FROM raw_tle_archive
        WHERE CAST(epoch_utc AS DATE) = CAST(? AS DATE)
        """,
        [snapshot_day],
    ).df()
    con.close()

    if df.empty:
        raise ValueError(f"raw_tle_archive 在 {snapshot_day} 當天沒有任何 TLE 記錄")

    # 再從當天這批裡找目標星（理論上一定存在，但保險起見再檢查一次）
    df_target_day = df[df["norad_id"] == target_norad]
    if df_target_day.empty:
        raise ValueError(f"NORAD {target_norad} 不在 {snapshot_day} 這個 snapshot 中")

    tgt = df_target_day.iloc[0]
    rmin0 = tgt["rmin_km"]
    rmax0 = tgt["rmax_km"]
    ecc0  = tgt["eccentricity"]
    inc0  = tgt["inclination_deg"]
    raan0 = tgt["raan_deg"]

    def _raan_delta(raan: float) -> float:
        return angular_diff_deg(raan, raan0)

    # radial overlap：NOT (rmax0 + buf < rmin_s OR rmax_s + buf < rmin0)
    df["radial_overlap"] = ~(
        ((rmax0 + radial_buffer_km) < df["rmin_km"]) |
        ((df["rmax_km"] + radial_buffer_km) < rmin0)
    )

    df["delta_ecc"] = (df["eccentricity"] - ecc0).abs()
    df["delta_inc_deg"] = (df["inclination_deg"] - inc0).abs()
    df["delta_raan_deg"] = df["raan_deg"].apply(_raan_delta)

    mask = (
        (df["norad_id"] != target_norad) &
        (df["radial_overlap"]) &
        (df["delta_ecc"] <= max_delta_ecc) &
        (df["delta_inc_deg"] <= max_delta_inc_deg) &
        (df["delta_raan_deg"] <= max_delta_raan_deg)
    )

    df_out = df[mask].sort_values(
        ["radial_overlap", "delta_ecc", "delta_inc_deg", "delta_raan_deg"]
    ).reset_index(drop=True)

    return df_out, epoch_center

def to_satrec_map(df: pd.DataFrame) -> Dict[int, Satrec]:
    """
    把 DataFrame 中的 (norad_id, line1, line2) 轉為 Satrec dict。
    """
    out: Dict[int, Satrec] = {}
    for row in df.itertuples(index=False):
        try:
            out[int(row.norad_id)] = Satrec.twoline2rv(row.line1, row.line2)
        except Exception:
            continue
    return out


# ==========================
# Stage B – 粗時間網格 + KD-tree 掃描
# ==========================

def stage_b_kdtree_scan(
    target_sat: Satrec,
    secondary_map: Dict[int, Satrec],
    center_time: datetime,
    hours_before: float = 12.0,
    hours_after: float = 12.0,
    step_seconds: int = 300,
    miss_threshold_km: float = 50.0,
) -> pd.DataFrame:
    """
    Stage B:
    - 以 center_time 為中心 ±hours，固定 step_seconds 傳播 target / secondaries
    - 每個時間點對 secondaries 建 cKDTree
    - 找出距 target 小於 miss_threshold_km 的粗命中
    - 對每個 secondary 保留一筆「最小 miss distance」記錄
    """
    times = generate_time_grid(
        center=center_time,
        hours_before=hours_before,
        hours_after=hours_after,
        step_seconds=step_seconds,
    )
    sec_ids = list(secondary_map.keys())
    records: List[dict] = []

    for t in times:
        r_t, v_t = propagate_sat_rv(target_sat, t)
        if r_t is None:
            continue

        pts = []
        valid_ids = []
        for nid in sec_ids:
            r_s, v_s = propagate_sat_rv(secondary_map[nid], t)
            if r_s is None:
                continue
            pts.append(r_s)
            valid_ids.append(nid)

        if not pts:
            continue

        pts = np.vstack(pts)
        tree = cKDTree(pts)
        idxs = tree.query_ball_point(r_t, r=miss_threshold_km)

        for idx in idxs:
            d = float(np.linalg.norm(pts[idx] - r_t))
            records.append(
                {
                    "t_utc": t,
                    "secondary_norad": int(valid_ids[idx]),
                    "miss_distance_km": d,
                }
            )

    if not records:
        return pd.DataFrame(
            columns=["secondary_norad", "t_utc", "miss_distance_km"]
        )

    df = pd.DataFrame(records)
    df = (
        df.sort_values(["secondary_norad", "miss_distance_km", "t_utc"])
          .drop_duplicates("secondary_norad")
          .reset_index(drop=True)
    )
    return df


# ==========================
# Stage C – 細時間 TCA + RTN covariance + Pc
# 1. 原始 grid 掃描版本 (Old Stage C)
# 2. minimize_scalar 版本 (New Stage C)
# ==========================

def search_best_distance_around_time(
    target_sat: Satrec,
    secondary_sat: Satrec,
    center_time: datetime,
    span_seconds: int = 300,
    step_seconds: int = 1,
) -> Tuple[
    Optional[datetime], Optional[float],
    Optional[np.ndarray], Optional[np.ndarray],
    Optional[np.ndarray], Optional[np.ndarray],
]:
    """
    Old Stage C:
    以 center_time 為中心，在 ±span_seconds 內，以 step_seconds 掃描，
    回傳最小距離時刻與當時兩星的 r/v。
    """
    best_t = None
    best_d = None
    best_r1 = best_v1 = None
    best_r2 = best_v2 = None

    for dt_sec in range(-span_seconds, span_seconds + 1, step_seconds):
        t = center_time + timedelta(seconds=dt_sec)
        r1, v1 = propagate_sat_rv(target_sat, t)
        r2, v2 = propagate_sat_rv(secondary_sat, t)
        if r1 is None or r2 is None:
            continue
        d = float(np.linalg.norm(r2 - r1))
        if best_d is None or d < best_d:
            best_d = d
            best_t = t
            best_r1, best_v1 = r1, v1
            best_r2, best_v2 = r2, v2

    return best_t, best_d, best_r1, best_v1, best_r2, best_v2


def search_best_distance_around_time_minimize(
    target_sat: Satrec,
    secondary_sat: Satrec,
    center_time: datetime,
    span_seconds: int = 300,
) -> Tuple[
    Optional[datetime], Optional[float],
    Optional[np.ndarray], Optional[np.ndarray],
    Optional[np.ndarray], Optional[np.ndarray],
]:
    """
    New Stage C:
    以 center_time 為中心，在 ±span_seconds 內，
    利用 scipy.optimize.minimize_scalar 對 d^2(t) 做一維有界最小化，
    尋找 TCA 時刻與當時兩星的 r/v。
    """
    t0 = center_time

    def d2_of_dt(dt: float) -> float:
        t = t0 + timedelta(seconds=float(dt))
        r1, v1 = propagate_sat_rv(target_sat, t)
        r2, v2 = propagate_sat_rv(secondary_sat, t)
        if r1 is None or r2 is None:
            return 1e18
        dr = r2 - r1
        return float(np.dot(dr, dr))  # km^2

    res = minimize_scalar(
        d2_of_dt,
        bounds=(-span_seconds, span_seconds),
        method="bounded",
        options={"xatol": 0.1},  # ~0.1 秒級精度
    )

    if not res.success:
        return None, None, None, None, None, None

    dt_opt = float(res.x)
    best_t = t0 + timedelta(seconds=dt_opt)

    r1, v1 = propagate_sat_rv(target_sat, best_t)
    r2, v2 = propagate_sat_rv(secondary_sat, best_t)
    if r1 is None or r2 is None:
        return None, None, None, None, None, None

    best_d = float(np.linalg.norm(r2 - r1))
    return best_t, best_d, r1, v1, r2, v2


def refine_tca_with_pc_grid(
    target_sat: Satrec,
    secondary_sat: Satrec,
    coarse_time: datetime,
    coarse_window_minutes: float = 5.0,
    fine_step_seconds: int = 1,
    Rc_km: float = 0.01,
    n_mc: int = 20000,
) -> Tuple[Optional[datetime], Optional[float], Optional[float]]:
    """
    Old Stage C:
    - 以 Stage B 給的 coarse_time 為中心，在 ±coarse_window_minutes 內、
      以 fine_step_seconds 掃描真正 TCA。
    - 找到最小 miss distance 後，於該 TCA 計算 RTN 相對位置與 Pc。
    """
    span_seconds = int(coarse_window_minutes * 60)

    best_t, best_d, best_r1, best_v1, best_r2, best_v2 = search_best_distance_around_time(
        target_sat=target_sat,
        secondary_sat=secondary_sat,
        center_time=coarse_time,
        span_seconds=span_seconds,
        step_seconds=fine_step_seconds,
    )

    if best_t is None or best_r1 is None or best_r2 is None:
        return None, None, None

    r_rel = best_r2 - best_r1
    B = eci_to_rtn_basis(best_r1, best_v1)
    r_rel_rtn = B @ r_rel

    C1 = pseudo_cov_tle_leo()
    C2 = pseudo_cov_tle_leo()
    pc = compute_pc_simplified(
        r_rel_rtn=r_rel_rtn,
        C1_rtn=C1,
        C2_rtn=C2,
        Rc_km=Rc_km,
        n_mc=n_mc,
    )

    return best_t, best_d, pc


def refine_tca_with_pc_minimize(
    target_sat: Satrec,
    secondary_sat: Satrec,
    coarse_time: datetime,
    coarse_window_minutes: float = 5.0,
    Rc_km: float = 0.01,
    n_mc: int = 20000,
) -> Tuple[Optional[datetime], Optional[float], Optional[float]]:
    """
    New Stage C:
    - 以 Stage B 給的 coarse_time 為中心，在 ±coarse_window_minutes 內，
      用 minimize_scalar 在連續時間上尋找 TCA。
    - 在該 TCA 計算 RTN 相對位置與 Pc。
    """
    span_seconds = int(coarse_window_minutes * 60)

    best_t, best_d, best_r1, best_v1, best_r2, best_v2 = search_best_distance_around_time_minimize(
        target_sat=target_sat,
        secondary_sat=secondary_sat,
        center_time=coarse_time,
        span_seconds=span_seconds,
    )

    if best_t is None or best_r1 is None or best_r2 is None:
        return None, None, None

    r_rel = best_r2 - best_r1
    B = eci_to_rtn_basis(best_r1, best_v1)
    r_rel_rtn = B @ r_rel

    C1 = pseudo_cov_tle_leo()
    C2 = pseudo_cov_tle_leo()
    pc = compute_pc_simplified(
        r_rel_rtn=r_rel_rtn,
        C1_rtn=C1,
        C2_rtn=C2,
        Rc_km=Rc_km,
        n_mc=n_mc,
    )

    return best_t, best_d, pc


# ==========================
# Pipeline 主流程
# ==========================

def run_pipeline(
    db_path: str,
    target_norad: int = 66666,
    snapshot_date: Optional[str] = None,
    delta_a_km: float = 20.0,
    delta_i_deg: float = 1.0,
    delta_raan_deg: float = 15.0,
    coarse_hours_before: float = 12.0,
    coarse_hours_after: float = 96.0,
    coarse_step_seconds: int = 300,
    coarse_miss_threshold_km: float = 50.0,
    fine_window_minutes: float = 10.0,
    fine_step_seconds: int = 1,
    Rc_km: float = 0.01,
    n_mc: int = 20000,
    export_csv_path: Optional[str] = None,
    # 新增：橢圓幾何粗篩參數
    radial_buffer_km: float = 50.0,
    max_delta_ecc: float = 0.3,
    max_delta_inc_deg: float = 5.0,
    max_delta_raan_deg: float = 30.0,
    use_elliptic_stageA: bool = True,
    center_time_override: Optional[datetime] = None,
    # 新增：Stage C 模式 ('grid', 'minimize', 'benchmark')
    stage_c_mode: str = "minimize",
) -> pd.DataFrame:
    """
    串起 Stage A/B/C，並將結果寫入 DuckDB conjunction_events 表。
    stage_c_mode:
        - 'grid'      : 使用舊版逐秒掃描 Stage C
        - 'minimize'  : 使用新版 minimize_scalar Stage C
        - 'benchmark' : 兩者都跑並列印時間與結果差異，寫入 DB 時採用新版結果
    """
    if use_elliptic_stageA:
        # Stage A：橢圓軌道幾何粗篩
        df_candidates, epoch_center = load_stageA_candidates_elliptic(
            db_path=db_path,
            target_norad=target_norad,
            snapshot_date=snapshot_date,
            radial_buffer_km=radial_buffer_km,
            max_delta_ecc=max_delta_ecc,
            max_delta_inc_deg=max_delta_inc_deg,
            max_delta_raan_deg=max_delta_raan_deg,
        )
    else:
        # Stage A：舊版 Δa/Δi/ΔΩ 粗篩
        df_candidates, epoch_center = load_stageA_candidates(
            db_path=db_path,
            target_norad=target_norad,
            delta_a_km=delta_a_km,
            delta_i_deg=delta_i_deg,
            delta_raan_deg=delta_raan_deg,
            snapshot_date=snapshot_date,
        )

    if df_candidates.empty:
        print("Stage A 無候選衛星。")
        return df_candidates
    # 若指定了外部中心時間，就用它
    center_time = center_time_override or epoch_center

    # 建 Satrec
    con = duckdb.connect(db_path)
    row = con.execute(
        """
        SELECT line1, line2
        FROM raw_tle_archive
        WHERE norad_id = ?
        ORDER BY epoch_utc DESC
        LIMIT 1
        """,
        [target_norad],
    ).fetchone()
    con.close()
    if row is None:
        raise ValueError(f"raw_tle_archive 找不到 NORAD {target_norad} 的 TLE")

    line1_t, line2_t = row
    target_sat = Satrec.twoline2rv(line1_t, line2_t)

    secondary_map = to_satrec_map(df_candidates)

    # Stage B：粗時間網格 + KD-tree
    coarse_hits = stage_b_kdtree_scan(
        target_sat=target_sat,
        secondary_map=secondary_map,
        center_time=center_time,
        hours_before=coarse_hours_before,
        hours_after=coarse_hours_after,
        step_seconds=coarse_step_seconds,
        miss_threshold_km=coarse_miss_threshold_km,
    )

    if coarse_hits.empty:
        print("Stage B 無粗命中候選。")
        return coarse_hits

    # Stage C：TCA + Pc
    results: List[dict] = []
    for row in coarse_hits.itertuples(index=False):
        sec_id = int(row.secondary_norad)
        sec_sat = secondary_map.get(sec_id)
        if sec_sat is None:
            continue

        # 這裡用 row.t_utc 當 coarse_time
        coarse_time = row.t_utc

        if stage_c_mode == "grid":
            tca, miss, pc = refine_tca_with_pc_grid(
                target_sat=target_sat,
                secondary_sat=sec_sat,
                coarse_time=coarse_time,
                coarse_window_minutes=fine_window_minutes,
                fine_step_seconds=fine_step_seconds,
                Rc_km=Rc_km,
                n_mc=n_mc,
            )

        elif stage_c_mode == "minimize":
            tca, miss, pc = refine_tca_with_pc_minimize(
                target_sat=target_sat,
                secondary_sat=sec_sat,
                coarse_time=coarse_time,
                coarse_window_minutes=fine_window_minutes,
                Rc_km=Rc_km,
                n_mc=n_mc,
            )

        elif stage_c_mode == "benchmark":
            # 跑舊版
            t0 = time.perf_counter()
            tca_grid, miss_grid, pc_grid = refine_tca_with_pc_grid(
                target_sat=target_sat,
                secondary_sat=sec_sat,
                coarse_time=coarse_time,
                coarse_window_minutes=fine_window_minutes,
                fine_step_seconds=fine_step_seconds,
                Rc_km=Rc_km,
                n_mc=n_mc,
            )
            t1 = time.perf_counter()

            # 跑新版
            t2 = time.perf_counter()
            tca_new, miss_new, pc_new = refine_tca_with_pc_minimize(
                target_sat=target_sat,
                secondary_sat=sec_sat,
                coarse_time=coarse_time,
                coarse_window_minutes=fine_window_minutes,
                Rc_km=Rc_km,
                n_mc=n_mc,
            )
            t3 = time.perf_counter()

            # 簡單列印 benchmark（若任一失敗就標示）
            if (tca_grid is not None) and (tca_new is not None):
                dt_tca = (tca_new - tca_grid).total_seconds()
                print(
                    f"[StageC benchmark] secondary {sec_id}: "
                    f"grid miss={miss_grid:.3f} km, new miss={miss_new:.3f} km, "
                    f"Δtca={dt_tca:.3f} s, "
                    f"grid={1e3*(t1-t0):.1f} ms, new={1e3*(t3-t2):.1f} ms"
                )
            else:
                print(
                    f"[StageC benchmark] secondary {sec_id}: "
                    f"grid_ok={tca_grid is not None}, new_ok={tca_new is not None}, "
                    f"grid={1e3*(t1-t0):.1f} ms, new={1e3*(t3-t2):.1f} ms"
                )

            # 寫入 DB 時採用新版結果（若新版失敗就退回舊版）
            if tca_new is not None and miss_new is not None and pc_new is not None:
                tca, miss, pc = tca_new, miss_new, pc_new
            else:
                tca, miss, pc = tca_grid, miss_grid, pc_grid

        else:
            raise ValueError(f"未知的 stage_c_mode: {stage_c_mode}")

        if tca is None or miss is None or pc is None:
            continue

        results.append(
            {
                "primary_norad": target_norad,
                "secondary_norad": sec_id,
                "coarse_hit_time_utc": coarse_time,
                "tca_utc": tca,
                "miss_distance_km": miss,
                "pc": pc,
                "risk_label": risk_label_from_pc(pc),
            }
        )

    if not results:
        print("Stage C 無有效 TCA 結果。")
        return pd.DataFrame(
            columns=[
                "primary_norad",
                "secondary_norad",
                "coarse_hit_time_utc",
                "tca_utc",
                "miss_distance_km",
                "pc",
                "risk_label",
            ]
        )

    out = pd.DataFrame(results).sort_values("miss_distance_km").reset_index(drop=True)

    # 寫入 DuckDB conjunction_events
    con = duckdb.connect(db_path)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS conjunction_events (
            primary_norad        INTEGER,
            secondary_norad      INTEGER,
            coarse_hit_time_utc  TIMESTAMP,
            tca_utc              TIMESTAMP,
            miss_distance_km     DOUBLE,
            pc                   DOUBLE,
            risk_label           VARCHAR
        );
        """
    )
    con.register("df_out", out)
    con.execute("INSERT INTO conjunction_events SELECT * FROM df_out")
    con.close()

    if export_csv_path:
        out.to_csv(export_csv_path, index=False)

    return out


# ==========================
# CLI 入口
# ==========================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Conjunction screening with DuckDB raw_tle_archive (Stage A/B/C)"
    )
    parser.add_argument("--db-path", default=os.getenv("CONJECTIONDB_PATH", "./conjection_database.duckdb"))
    parser.add_argument("--target-norad", type=int, default=66666)
    parser.add_argument("--snapshot-date", default=None, help="YYYY-MM-DD，預設使用最新下載快照")

    # 舊版 Δa/Δi/ΔΩ
    parser.add_argument("--delta-a-km", type=float, default=20.0)
    parser.add_argument("--delta-i-deg", type=float, default=1.0)
    parser.add_argument("--delta-raan-deg", type=float, default=15.0)

    # 新版橢圓幾何粗篩參數
    parser.add_argument("--radial-buffer-km", type=float, default=50.0,
                        help="radial overlap buffer (km) for Stage A elliptic filter")
    parser.add_argument("--max-delta-ecc", type=float, default=0.3,
                        help="max |Δecc| for Stage A elliptic filter")
    parser.add_argument("--max-delta-inc-deg", type=float, default=5.0,
                        help="max |Δinc| (deg) for Stage A elliptic filter")
    parser.add_argument("--max-delta-raan-deg", type=float, default=30.0,
                        help="max |ΔRAAN| (deg) for Stage A elliptic filter")
    parser.add_argument("--no-elliptic-stageA", action="store_true",
                        help="use old Δa/Δi/ΔΩ Stage A instead of elliptic filter")

    parser.add_argument("--coarse-hours-before", type=float, default=12.0)
    parser.add_argument("--coarse-hours-after", type=float, default=12.0)
    parser.add_argument("--coarse-step-seconds", type=int, default=300)
    parser.add_argument("--coarse-miss-threshold-km", type=float, default=50.0)

    parser.add_argument("--fine-window-minutes", type=float, default=10.0)
    parser.add_argument("--fine-step-seconds", type=int, default=1)

    parser.add_argument("--Rc-km", type=float, default=0.01)
    parser.add_argument("--n-mc", type=int, default=20000)

    parser.add_argument("--export-csv", default="conjunction_results.csv")

    # 新增：Stage C 模式
    parser.add_argument(
        "--stage-c-mode",
        choices=["grid", "minimize", "benchmark"],
        default="minimize",
        help="Stage C search method: grid (old), minimize (new), benchmark (run both)",
    )

    args = parser.parse_args()

    out = run_pipeline(
        db_path=args.db_path,
        target_norad=args.target_norad,
        snapshot_date=args.snapshot_date,
        delta_a_km=args.delta_a_km,
        delta_i_deg=args.delta_i_deg,
        delta_raan_deg=args.delta_raan_deg,
        coarse_hours_before=args.coarse_hours_before,
        coarse_hours_after=args.coarse_hours_after,
        coarse_step_seconds=args.coarse_step_seconds,
        coarse_miss_threshold_km=args.coarse_miss_threshold_km,
        fine_window_minutes=args.fine_window_minutes,
        fine_step_seconds=args.fine_step_seconds,
        Rc_km=args.Rc_km,
        n_mc=args.n_mc,
        export_csv_path=args.export_csv,
        radial_buffer_km=args.radial_buffer_km,
        max_delta_ecc=args.max_delta_ecc,
        max_delta_inc_deg=args.max_delta_inc_deg,
        max_delta_raan_deg=args.max_delta_raan_deg,
        use_elliptic_stageA=(not args.no_elliptic_stageA),
        stage_c_mode=args.stage_c_mode,
    )

    if out.empty:
        print("No conjunction candidates found.")
    else:
        print(out.head(20).to_string(index=False))


if __name__ == "__main__":
    main()