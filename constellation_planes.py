#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
通用 mega-constellation RAAN 分組模組 (DuckDB 版)
"""

import duckdb                         # <<< 改用 DuckDB[web:73]
from typing import Dict, List, Optional, Any

import numpy as np
import pandas as pd

from skyfield.api import load         # 用來把 epoch_jd 轉成 datetime
ts = load.timescale()

# # ======== 對外主要介面 ========
#
# def get_plane_to_norad_balanced(
#     SHELL_NAME: str,
#     DB_PATH: str,
#     TLE_TABLE: str,
#     start_date: str,
#     end_date: str,
#     SHELL_ALT_KM: float,
#     ALT_TOL_KM: float,
#     INC_REF_DEG: float,
#     INC_TOL_DEG: float,
#     NUM_PLANES: int,
#     TARGET_PER_PLANE: Optional[int] = None,
#     FILTER_STR: Optional[str] = None,
# ) -> Dict[int, List[int]]:
#     """
#     依照指定殼層參數，從 TLE DB 中抽出該殼層衛星，並依 RAAN 分組後回傳 plane_to_norad 映射。
#     """
#     print(f"[INFO] Processing shell '{SHELL_NAME}' "
#           f"from {start_date} to {end_date} ...")
#
#     # 只用日期部分，對應 DuckDB 的 date_tag (DATE)
#     start_date_only = start_date[:10]
#     end_date_only   = end_date[:10]
#
#     df_shell = _load_shell_from_db(
#         DB_PATH=DB_PATH,
#         TLE_TABLE=TLE_TABLE,
#         start_date=start_date_only,
#         end_date=end_date_only,
#         SHELL_ALT_KM=SHELL_ALT_KM,
#         ALT_TOL_KM=ALT_TOL_KM,
#         INC_REF_DEG=INC_REF_DEG,
#         INC_TOL_DEG=INC_TOL_DEG,
#         FILTER_STR=FILTER_STR,
#     )
#
#     if df_shell.empty:
#         raise RuntimeError(
#             f"No candidates found for shell '{SHELL_NAME}' "
#             f"with given time window and filters."
#         )
#
#     df_planes = _build_planes_from_raan(df_shell, NUM_PLANES=NUM_PLANES)
#
#     if TARGET_PER_PLANE is not None:
#         df_final = _trim_to_target_per_plane(
#             df_planes,
#             TARGET_PER_PLANE=TARGET_PER_PLANE
#         )
#     else:
#         df_final = df_planes
#
#     plane_to_norad = _build_plane_to_norad_dict(df_final)
#
#     total_sats = sum(len(v) for v in plane_to_norad.values())
#     print(f"[INFO] Shell '{SHELL_NAME}' -> "
#           f"{len(plane_to_norad)} planes, total sats returned: {total_sats}")
#
#     return plane_to_norad


def get_plane_to_norad_and_name(
    SHELL_NAME: str,
    DB_PATH: str,
    TLE_TABLE: str,
    start_date: str,
    end_date: str,
    SHELL_ALT_KM: float,
    ALT_TOL_KM: float,
    INC_REF_DEG: float,
    INC_TOL_DEG: float,
    NUM_PLANES: int,
    FILTER_STR: Optional[str] = None,
    TARGET_PER_PLANE: Optional[int] = None,
) -> Dict[int, Dict[str, List[str]]]:
    """
    DuckDB 版暫時沒有 sat_name，name_list 先留空字串。
    回傳:
      { plane_id: {"norad_list":[...], "name_list":[...]}, ... }
    """
    print(f"[INFO] Processing shell '{SHELL_NAME}' "
          f"from {start_date} to {end_date} ...")

    start_date_only = start_date[:10]
    end_date_only   = end_date[:10]

    df_shell = _load_shell_from_db(
        DB_PATH=DB_PATH,
        TLE_TABLE=TLE_TABLE,
        start_date=start_date_only,
        end_date=end_date_only,
        SHELL_ALT_KM=SHELL_ALT_KM,
        ALT_TOL_KM=ALT_TOL_KM,
        INC_REF_DEG=INC_REF_DEG,
        INC_TOL_DEG=INC_TOL_DEG,
        FILTER_STR=FILTER_STR,
    )

    if df_shell.empty:
        raise RuntimeError(
            f"No candidates found for shell '{SHELL_NAME}' "
            f"with given time window and filters."
        )

    df_planes = _build_planes_from_raan(df_shell, NUM_PLANES=NUM_PLANES)

    if TARGET_PER_PLANE is not None:
        df_final = _trim_to_target_per_plane(
            df_planes,
            TARGET_PER_PLANE=TARGET_PER_PLANE
        )
    else:
        df_final = df_planes

    mapping = _build_plane_to_norad_name_dict(df_final)

    total_sats = sum(len(v["norad_list"]) for v in mapping.values())
    print(f"[INFO] Shell '{SHELL_NAME}' -> "
          f"{len(mapping)} planes, total sats returned: {total_sats}")

    return mapping, total_sats


def get_plane_config_from_norad_and_name(
    SHELL_NAME: str,
    DB_PATH: str,
    TLE_TABLE: str,
    start_date: str,
    end_date: str,
    SHELL_ALT_KM: float,
    ALT_TOL_KM: float,
    INC_REF_DEG: float,
    INC_TOL_DEG: float,
    NUM_PLANES: int,
    FILTER_STR: str | None = None,
    TARGET_PER_PLANE: int | None = None,
) -> Dict[str, List[int]]:
    """
    依照 plane_config 的格式輸出:
      {
        "plane_00": [47352, 47357, ...],
        "plane_01": [...],
        ...
      }
    """
    mapping = get_plane_to_norad_and_name(
        SHELL_NAME=SHELL_NAME,
        DB_PATH=DB_PATH,
        TLE_TABLE=TLE_TABLE,
        start_date=start_date,
        end_date=end_date,
        SHELL_ALT_KM=SHELL_ALT_KM,
        ALT_TOL_KM=ALT_TOL_KM,
        INC_REF_DEG=INC_REF_DEG,
        INC_TOL_DEG=INC_TOL_DEG,
        NUM_PLANES=NUM_PLANES,
        FILTER_STR=FILTER_STR,
        TARGET_PER_PLANE=TARGET_PER_PLANE,
    )

    plane_config: Dict[str, List[int]] = {}
    for pid, v in mapping.items():
        key = f"plane_{pid:02d}"
        norad_list = [int(n) for n in v["norad_list"]]
        plane_config[key] = norad_list

    return plane_config

# ======== 內部工具函式 ========

def _load_shell_from_db(
    DB_PATH: str,
    TLE_TABLE: str,
    start_date: str,   # 'YYYY-MM-DD'
    end_date: str,     # 'YYYY-MM-DD'
    SHELL_ALT_KM: float,
    ALT_TOL_KM: float,
    INC_REF_DEG: float,
    INC_TOL_DEG: float,
    FILTER_STR: Optional[str],
) -> pd.DataFrame:
    """
    從 DuckDB 讀取符合「指定高度與傾角」的殼層衛星。
    使用:
      - date_tag (DATE) 做時間範圍
      - sma_km, inclination_deg, raan_deg
      - epoch_jd 轉成 epoch datetime 給後續排序使用
    目前暫不做 sat_name filter（因為 schema 尚無名稱欄位）。
    """
    conn = duckdb.connect(DB_PATH, read_only=True)

    a_ref = 6378.0 + SHELL_ALT_KM

    q = f"""
    SELECT
        t.norad_id,
        t.epoch_jd,
        t.date_tag,
        t.sma_km,
        t.inclination_deg,
        t.raan_deg
    FROM {TLE_TABLE} AS t
    WHERE t.date_tag BETWEEN ? AND ?
    AND t.sma_km BETWEEN ? AND ?
    AND t.inclination_deg BETWEEN ? AND ?    ORDER BY t.norad_id, t.epoch_jd;
    """

    params = (
        start_date, end_date,
        a_ref - ALT_TOL_KM, a_ref + ALT_TOL_KM,
        INC_REF_DEG - INC_TOL_DEG, INC_REF_DEG + INC_TOL_DEG,
    )

    df = pd.read_sql_query(q, conn, params=params)
    conn.close()
    print("$$$"*50)

    print("RAW SQL:", q)
    print("PARAMS:", params)

    # 如果全部都是簡單型別，可以粗暴組一份 debug 用的字串
    debug_sql = q
    for p in params:
        if isinstance(p, str):
            v = f"'{p}'"
        else:
            v = str(p)
        debug_sql = debug_sql.replace("?", v, 1)

    print("DEBUG SQL:\n", debug_sql)

    print(params)
    print(df)

    if df.empty:
        print("[WARN] _load_shell_from_db: query result is empty.")
        return df

    # epoch_jd (UTC JD) -> datetime，用 Skyfield 轉一次
    # 注意：這裡假設 epoch_jd 是 UTC JD
    t_sf = ts.ut1_jd(df["epoch_jd"].to_numpy())
    df["epoch"] = pd.to_datetime(t_sf.utc_datetime())  # 給後續排序用

    # 每顆衛星在時間窗內取「最新一筆」TLE
    df = (
        df.sort_values(["norad_id", "epoch"])
          .groupby("norad_id")
          .tail(1)
          .reset_index(drop=True)
    )

    print(f"[INFO] Shell candidates (unique NORAD): {df['norad_id'].nunique()}")
    return df


def _assign_plane_by_raan(raan_deg: float, NUM_PLANES: int) -> int:
    r = float(np.mod(raan_deg, 360.0))
    bin_width = 360.0 / NUM_PLANES
    idx = int(r // bin_width)
    if idx == NUM_PLANES:
        idx = NUM_PLANES - 1
    return idx


def _build_planes_from_raan(df_shell: pd.DataFrame,
                            NUM_PLANES: int) -> pd.DataFrame:
    if df_shell.empty:
        raise ValueError("_build_planes_from_raan: df_shell is empty.")

    df = df_shell.copy()
    df["plane_idx"] = df["raan_deg"].apply(
        _assign_plane_by_raan,
        NUM_PLANES=NUM_PLANES
    )

    plane_stats = (
        df.groupby("plane_idx")["raan_deg"]
          .median()
          .reset_index()
          .rename(columns={"raan_deg": "raan_med"})
          .sort_values("raan_med")
          .reset_index(drop=True)
    )
    plane_stats["plane_id"] = plane_stats.index

    df = df.merge(
        plane_stats[["plane_idx", "plane_id", "raan_med"]],
        on="plane_idx",
        how="left"
    )

    plane_counts = (
        df.groupby("plane_id")["norad_id"]
          .nunique()
          .reset_index(name="sat_count")
          .sort_values("plane_id")
    )
    print("\n[INFO] Plane sat_count (before balancing):")
    print(plane_counts.to_string(index=False))

    return df


def _trim_to_target_per_plane(df_in: pd.DataFrame,
                              TARGET_PER_PLANE: int) -> pd.DataFrame:
    rows = []
    for pid, g in df_in.groupby("plane_id"):
        r_med = g["raan_med"].iloc[0]
        r_diff = np.abs(np.mod(g["raan_deg"] - r_med + 180.0, 360.0) - 180.0)
        g = g.assign(raan_diff=r_diff)

        g = g.sort_values("raan_diff")
        if len(g) > TARGET_PER_PLANE:
            g = g.head(TARGET_PER_PLANE)

        rows.append(g)

    df_out = pd.concat(rows, ignore_index=True)

    plane_counts = (
        df_out.groupby("plane_id")["norad_id"]
              .nunique()
              .reset_index(name="sat_count")
              .sort_values("plane_id")
    )
    print("\n[INFO] Plane sat_count (balanced):")
    print(plane_counts.to_string(index=False))

    return df_out


def _build_plane_to_norad_dict(df_in: pd.DataFrame) -> Dict[int, List[int]]:
    plane_to_norad = (
        df_in.groupby("plane_id")["norad_id"]
             .apply(lambda s: [str(int(x)) for x in sorted(s.unique())])
             .to_dict()
    )

    plane_to_norad = {
        int(pid): [int(x) for x in norads]
        for pid, norads in plane_to_norad.items()
    }

    return plane_to_norad


def _build_plane_to_norad_name_dict(df_in: pd.DataFrame) -> Dict[int, Dict[str, List[str]]]:
    """
    目前 DuckDB 版沒有 sat_name，先用空字串佔位。
    若未來加入名稱欄位，可在這裡改為實際 sat_name。
    """
    out: Dict[int, Dict[str, List[str]]] = {}

    for pid, grp in df_in.groupby("plane_id"):
        grp_sorted = grp.sort_values("norad_id")
        norads = [str(int(x)) for x in grp_sorted["norad_id"].unique()]
        # 暫時沒有 sat_name，全部給空字串
        names = ["" for _ in norads]
        out[int(pid)] = {
            "norad_list": norads,
            "name_list": names,
        }

    return out
