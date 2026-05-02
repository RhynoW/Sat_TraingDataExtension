#!/usr/bin/env python3
"""
download_SP_and_RIC_unified.py

用途：
1) 從本地暫存目錄載入 SpaceX 公開提供的 Starlink CCSDS OEM 檔案
2) 解析高精度 ephemeris state vectors，寫入 space_db.duckdb 的 sp_ephem_raw
3) 讀取既有 TLE（raw_tle_archive），使用 SGP4 傳播到 SP epoch
4) 將 TLE propagated TEME state 與 OEM state 轉到共同座標系（Astropy GCRS）
5) 計算 RIC 殘差，寫入 tle_sp_ric_residuals

資料來源更新：
- Starlink/SpaceX trajectory 支援 CCSDS OEM KVN 格式，且 REF_FRAME 支援 ITRF 與 EME2000。[web:74][web:77]
- Space-Track 已自 2025-07-28 起不再託管 SpaceX ephemerides，應改從 SpaceX 直接下載。[web:75]

注意：
- sgp4 輸出為 TEME frame。[web:13]
- 比較座標系在本程式實作上使用 Astropy GCRS。[web:65]
- 若 OEM 原始 frame 是 ITRF/ITRS，會先轉到 GCRS。
- 若 OEM 原始 frame 是 EME2000，第一版先視為 GCRS-like inertial frame 近似處理；
  若之後需要研究級嚴格比對，可再換成更嚴格的 EME2000/J2000/GCRS 轉換流程。[web:74][web:84]
"""

import os
import re
import shutil
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional

import duckdb
import pandas as pd
import numpy as np
from dotenv import load_dotenv

from sgp4.api import Satrec, jday

from astropy import units as u
from astropy.time import Time
from astropy.coordinates import (
    TEME,
    ITRS,
    GCRS,
    CartesianRepresentation,
    CartesianDifferential,
)
from astropy.utils import iers


# ==========================
# 常數與環境變數
# ==========================

load_dotenv()

SPACE_DB_PATH = os.getenv("SPACE_DB_PATH", "./space_db.duckdb")

SP_EPHEM_TEMP_PATH = os.getenv("SP_EPHEM_TEMP_PATH", "./sp_ephem_downloads_temp")
SP_EPHEM_PATH = os.getenv("SP_EPHEM_PATH", "./sp_ephem_downloads")

STARLINK_NORAD_IDS = os.getenv("STARLINK_NORAD_IDS", "")
FRAME_COMPARE = os.getenv("FRAME_COMPARE", "GCRS")
SP_DEFAULT_FRAME = os.getenv("SP_DEFAULT_FRAME", "ITRF")

# 如需用檔名 / OBJECT_NAME 對應 NORAD，可在 .env 放 CSV 對應表路徑
STARLINK_OEM_MAP_CSV = os.getenv("STARLINK_OEM_MAP_CSV", "")

# Astropy / IERS 設定
iers.conf.auto_max_age = None
iers.conf.auto_download = True

# 允許的 OEM 參考座標系
SUPPORTED_OEM_FRAMES = {"ITRF", "ITRS", "ECEF", "EME2000", "GCRS", "GCRF"}


# ==========================
# DB 初始化
# ==========================

def init_sp_ric_tables(db_path: str) -> None:
    con = duckdb.connect(database=db_path, read_only=False)

    con.execute("""
        CREATE TABLE IF NOT EXISTS sp_ephem_raw (
            norad_id          INTEGER NOT NULL,
            epoch_utc         TIMESTAMP NOT NULL,
            frame             VARCHAR NOT NULL,
            x_km              DOUBLE NOT NULL,
            y_km              DOUBLE NOT NULL,
            z_km              DOUBLE NOT NULL,
            vx_km_s           DOUBLE NOT NULL,
            vy_km_s           DOUBLE NOT NULL,
            vz_km_s           DOUBLE NOT NULL,
            object_name       VARCHAR,
            object_id         VARCHAR,
            source_file       VARCHAR,
            downloaded_at_utc TIMESTAMP NOT NULL,
            PRIMARY KEY (norad_id, epoch_utc, frame)
        );
    """)

    # 舊 DB 補欄位
    alter_sqls = [
        "ALTER TABLE sp_ephem_raw ADD COLUMN object_id VARCHAR;",
    ]
    for sql in alter_sqls:
        try:
            con.execute(sql)
        except Exception:
            pass

    con.execute("""
        CREATE TABLE IF NOT EXISTS tle_sp_ric_residuals (
            norad_id          INTEGER NOT NULL,
            epoch_utc         TIMESTAMP NOT NULL,
            tle_source_epoch  TIMESTAMP NOT NULL,
            frame             VARCHAR NOT NULL,
            dr_km             DOUBLE NOT NULL,
            di_km             DOUBLE NOT NULL,
            dc_km             DOUBLE NOT NULL,
            dpos_km           DOUBLE NOT NULL,
            dvr_km_s          DOUBLE,
            dvi_km_s          DOUBLE,
            dvc_km_s          DOUBLE,
            tle_line1         VARCHAR,
            tle_line2         VARCHAR,
            created_at_utc    TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (norad_id, epoch_utc, tle_source_epoch)
        );
    """)

    try:
        con.execute("CREATE INDEX idx_sp_ephem_norad_epoch ON sp_ephem_raw(norad_id, epoch_utc);")
    except Exception:
        pass

    try:
        con.execute("CREATE INDEX idx_ric_norad_epoch ON tle_sp_ric_residuals(norad_id, epoch_utc);")
    except Exception:
        pass

    con.close()


# ==========================
# 工具函式
# ==========================

def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def parse_env_norad_ids(raw: str) -> list[int]:
    if not raw.strip():
        return []
    ids = []
    for token in raw.split(","):
        token = token.strip()
        if token:
            ids.append(int(token))
    return sorted(set(ids))


def datetime_to_jday(dt_utc: datetime) -> tuple[float, float]:
    if dt_utc.tzinfo is not None:
        dt_utc = dt_utc.astimezone(timezone.utc).replace(tzinfo=None)

    return jday(
        dt_utc.year, dt_utc.month, dt_utc.day,
        dt_utc.hour, dt_utc.minute,
        dt_utc.second + dt_utc.microsecond * 1e-6
    )


def load_oem_mapping_csv(map_csv_path: str) -> dict[str, int]:
    """
    可選：
    讀取一張對應表，把 OBJECT_NAME / OBJECT_ID / source_file 對應到 NORAD ID。
    欄位名稱可接受：
      - norad_id
      - object_name
      - object_id
      - source_file
    """
    mapping = {}

    if not map_csv_path:
        return mapping

    fp = Path(map_csv_path)
    if not fp.exists():
        raise FileNotFoundError(f"STARLINK_OEM_MAP_CSV 不存在: {fp}")

    df = pd.read_csv(fp)

    required = {"norad_id"}
    if not required.issubset(df.columns):
        raise ValueError("OEM mapping CSV 至少需要 norad_id 欄位")

    for _, row in df.iterrows():
        norad = int(row["norad_id"])

        for key_col in ["object_name", "object_id", "source_file"]:
            if key_col in df.columns and pd.notna(row.get(key_col)):
                key = str(row[key_col]).strip().upper()
                if key:
                    mapping[key] = norad

    return mapping


def infer_norad_from_text(text: str) -> Optional[int]:
    m = re.search(r"\b(\d{5})\b", text)
    if m:
        return int(m.group(1))
    return None


def infer_norad_from_oem(
    source_file: str,
    object_name: Optional[str],
    object_id: Optional[str],
    mapping: Optional[dict[str, int]] = None,
) -> int:
    """
    第一版策略：
    1) 先查使用者提供的 mapping CSV
    2) 再從 source_file / object_name / object_id 中硬抓 5 位數 NORAD
    若仍抓不到就報錯，避免寫入錯誤衛星。
    """
    mapping = mapping or {}

    candidates = []
    if source_file:
        candidates.append(source_file)
    if object_name:
        candidates.append(object_name)
    if object_id:
        candidates.append(object_id)

    for item in candidates:
        key = str(item).strip().upper()
        if key in mapping:
            return mapping[key]

    for item in candidates:
        norad = infer_norad_from_text(str(item))
        if norad is not None:
            return norad

    raise ValueError(
        f"無法從 OEM 檔/metadata 推定 NORAD ID。"
        f" source_file={source_file}, object_name={object_name}, object_id={object_id}。"
        f"建議提供 STARLINK_OEM_MAP_CSV 對應表。"
    )


# ==========================
# OEM 檔案解析 / 寫入
# ==========================

def parse_sp_ephemeris_file(
    file_path: Path,
    default_frame: str = "ITRF",
    mapping: Optional[dict[str, int]] = None,
) -> pd.DataFrame:
    """
    解析 SpaceX Starlink CCSDS OEM (KVN) 檔案。

    依 CCSDS OEM 與 Starlink docs：
    - 檔頭通常以 CCSDS_OEM_VERS 開頭
    - metadata 包含 OBJECT_NAME / OBJECT_ID / REF_FRAME / TIME_SYSTEM
    - 資料段為 Epoch X Y Z VX VY VZ
    """

    lines = [ln.strip() for ln in file_path.open("r", encoding="utf-8", errors="ignore") if ln.strip()]

    if not any(line.startswith("CCSDS_OEM_VERS") for line in lines[:20]):
        raise ValueError(f"不是 CCSDS OEM KVN 檔案: {file_path}")

    meta = {}
    in_meta = False
    records = []

    for line in lines:
        if line.startswith("COMMENT"):
            continue

        if line == "META_START":
            in_meta = True
            continue
        if line == "META_STOP":
            in_meta = False
            continue

        if in_meta and "=" in line:
            k, v = [x.strip() for x in line.split("=", 1)]
            meta[k.upper()] = v
            continue

        # OEM data line: Epoch X Y Z VX VY VZ [可選 AX AY AZ]
        parts = line.split()
        if len(parts) >= 7 and "T" in parts[0]:
            epoch_utc = pd.to_datetime(parts[0], utc=True).to_pydatetime()

            records.append({
                "epoch_utc": epoch_utc,
                "x_km": float(parts[1]),
                "y_km": float(parts[2]),
                "z_km": float(parts[3]),
                "vx_km_s": float(parts[4]),
                "vy_km_s": float(parts[5]),
                "vz_km_s": float(parts[6]),
            })

    if not records:
        raise ValueError(f"OEM 檔內沒有 ephemeris data records: {file_path}")

    object_name = meta.get("OBJECT_NAME")
    object_id = meta.get("OBJECT_ID")
    ref_frame = meta.get("REF_FRAME", default_frame).upper()
    time_system = meta.get("TIME_SYSTEM", "UTC").upper()

    if ref_frame not in SUPPORTED_OEM_FRAMES:
        raise ValueError(f"目前不支援的 OEM REF_FRAME={ref_frame}, file={file_path}")

    if time_system != "UTC":
        # 第一版：先限制 UTC，避免 time scale 混用
        raise ValueError(f"目前僅支援 TIME_SYSTEM=UTC, got {time_system}, file={file_path}")

    norad_id = infer_norad_from_oem(
        source_file=file_path.name,
        object_name=object_name,
        object_id=object_id,
        mapping=mapping,
    )

    df = pd.DataFrame(records)
    df["norad_id"] = norad_id
    df["frame"] = "ITRF" if ref_frame in ("ITRF", "ITRS", "ECEF") else ref_frame
    df["object_name"] = object_name
    df["object_id"] = object_id
    df["source_file"] = file_path.name

    return df


def upsert_sp_ephem_into_db(
    db_path: str,
    df_sp: pd.DataFrame,
    downloaded_at_utc: Optional[datetime] = None,
) -> None:
    if df_sp.empty:
        return

    df = df_sp.copy()
    ts = downloaded_at_utc or datetime.now(timezone.utc)
    ts_naive = pd.Timestamp(ts).tz_convert("UTC").tz_localize(None) if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts)

    df["downloaded_at_utc"] = ts_naive
    df["epoch_utc"] = pd.to_datetime(df["epoch_utc"], utc=True).dt.tz_convert("UTC").dt.tz_localize(None)

    con = duckdb.connect(database=db_path, read_only=False)
    try:
        con.register("df_sp", df)
        con.execute("""
            INSERT INTO sp_ephem_raw AS t BY NAME
            SELECT
                norad_id,
                epoch_utc,
                frame,
                x_km,
                y_km,
                z_km,
                vx_km_s,
                vy_km_s,
                vz_km_s,
                object_name,
                object_id,
                source_file,
                downloaded_at_utc
            FROM df_sp
            ON CONFLICT (norad_id, epoch_utc, frame) DO NOTHING
        """)
        con.unregister("df_sp")
    finally:
        con.close()


# ==========================
# TLE 讀取與傳播
# ==========================

def get_candidate_tle_for_epoch(
    con: duckdb.DuckDBPyConnection,
    norad_id: int,
    epoch_utc: datetime,
) -> Optional[dict]:
    epoch_naive = pd.Timestamp(epoch_utc).tz_convert("UTC").tz_localize(None) if pd.Timestamp(epoch_utc).tzinfo else pd.Timestamp(epoch_utc)

    q1 = con.execute("""
        SELECT
            norad_id,
            object_name,
            line1,
            line2,
            epoch_utc
        FROM raw_tle_archive
        WHERE norad_id = ?
          AND epoch_utc <= ?
        ORDER BY epoch_utc DESC
        LIMIT 1
    """, [norad_id, epoch_naive]).fetchdf()

    if not q1.empty:
        return q1.iloc[0].to_dict()

    q2 = con.execute("""
        SELECT
            norad_id,
            object_name,
            line1,
            line2,
            epoch_utc
        FROM raw_tle_archive
        WHERE norad_id = ?
        ORDER BY ABS(epoch_utc - ?)
        LIMIT 1
    """, [norad_id, epoch_naive]).fetchdf()

    if q2.empty:
        return None

    return q2.iloc[0].to_dict()


def propagate_tle_to_teme(line1: str, line2: str, epoch_utc: datetime) -> tuple[np.ndarray, np.ndarray]:
    sat = Satrec.twoline2rv(line1, line2)
    jd, fr = datetime_to_jday(epoch_utc)
    err, r, v = sat.sgp4(jd, fr)
    if err != 0:
        raise RuntimeError(f"SGP4 propagation error code={err}")
    return np.array(r, dtype=float), np.array(v, dtype=float)


# ==========================
# Astropy frame transforms
# ==========================

def _ensure_time_astropy(epoch_utc: datetime) -> Time:
    if epoch_utc.tzinfo is None:
        epoch_utc = epoch_utc.replace(tzinfo=timezone.utc)
    else:
        epoch_utc = epoch_utc.astimezone(timezone.utc)
    return Time(epoch_utc, scale="utc")


def _build_cartrep_with_velocity(
    r_km: np.ndarray,
    v_km_s: np.ndarray,
) -> CartesianRepresentation:
    return CartesianRepresentation(
        x=r_km[0] * u.km,
        y=r_km[1] * u.km,
        z=r_km[2] * u.km,
        differentials=CartesianDifferential(
            d_x=v_km_s[0] * (u.km / u.s),
            d_y=v_km_s[1] * (u.km / u.s),
            d_z=v_km_s[2] * (u.km / u.s),
        )
    )


def teme_to_gcrf_state(
    epoch_utc: datetime,
    r_teme_km: np.ndarray,
    v_teme_km_s: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    t = _ensure_time_astropy(epoch_utc)
    rep = _build_cartrep_with_velocity(r_teme_km, v_teme_km_s)

    teme_coord = TEME(rep, obstime=t)
    gcrs_coord = teme_coord.transform_to(GCRS(obstime=t))

    r_gcrs_km = np.array([
        gcrs_coord.cartesian.x.to_value(u.km),
        gcrs_coord.cartesian.y.to_value(u.km),
        gcrs_coord.cartesian.z.to_value(u.km),
    ], dtype=float)

    v_gcrs_km_s = np.array([
        gcrs_coord.cartesian.differentials["s"].d_x.to_value(u.km / u.s),
        gcrs_coord.cartesian.differentials["s"].d_y.to_value(u.km / u.s),
        gcrs_coord.cartesian.differentials["s"].d_z.to_value(u.km / u.s),
    ], dtype=float)

    return r_gcrs_km, v_gcrs_km_s


def itrf_to_gcrf_state(
    epoch_utc: datetime,
    r_itrf_km: np.ndarray,
    v_itrf_km_s: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    t = _ensure_time_astropy(epoch_utc)
    rep = _build_cartrep_with_velocity(r_itrf_km, v_itrf_km_s)

    itrs_coord = ITRS(rep, obstime=t)
    gcrs_coord = itrs_coord.transform_to(GCRS(obstime=t))

    r_gcrs_km = np.array([
        gcrs_coord.cartesian.x.to_value(u.km),
        gcrs_coord.cartesian.y.to_value(u.km),
        gcrs_coord.cartesian.z.to_value(u.km),
    ], dtype=float)

    v_gcrs_km_s = np.array([
        gcrs_coord.cartesian.differentials["s"].d_x.to_value(u.km / u.s),
        gcrs_coord.cartesian.differentials["s"].d_y.to_value(u.km / u.s),
        gcrs_coord.cartesian.differentials["s"].d_z.to_value(u.km / u.s),
    ], dtype=float)

    return r_gcrs_km, v_gcrs_km_s


def eme2000_to_gcrf_state(
    epoch_utc: datetime,
    r_eme2000_km: np.ndarray,
    v_eme2000_km_s: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    第一版近似：
    將 EME2000 視為 GCRS-like inertial frame，直接回傳。
    若後續要研究級嚴格比較，可再替換成更精細的 EME2000/J2000/GCRS 轉換。
    """
    return r_eme2000_km, v_eme2000_km_s


def normalize_sp_state_to_compare_frame(
    epoch_utc: datetime,
    frame: str,
    r_km: np.ndarray,
    v_km_s: np.ndarray,
    compare_frame: str = "GCRS",
) -> tuple[np.ndarray, np.ndarray]:
    frame = frame.upper()
    compare_frame = compare_frame.upper()

    if compare_frame not in ("GCRS", "GCRF"):
        raise NotImplementedError(f"目前只支援 compare_frame=GCRS/GCRF, got {compare_frame}")

    if frame in ("GCRS", "GCRF"):
        return r_km, v_km_s

    if frame in ("ITRF", "ITRS", "ECEF"):
        return itrf_to_gcrf_state(epoch_utc, r_km, v_km_s)

    if frame == "EME2000":
        return eme2000_to_gcrf_state(epoch_utc, r_km, v_km_s)

    raise NotImplementedError(f"尚未支援 OEM frame 轉換: {frame} -> {compare_frame}")


# ==========================
# RIC 殘差
# ==========================

def build_ric_basis(r_ref_km: np.ndarray, v_ref_km_s: np.ndarray) -> np.ndarray:
    r_norm = np.linalg.norm(r_ref_km)
    if r_norm == 0.0:
        raise ValueError("Reference position norm is zero")

    r_hat = r_ref_km / r_norm

    h_vec = np.cross(r_ref_km, v_ref_km_s)
    h_norm = np.linalg.norm(h_vec)
    if h_norm == 0.0:
        raise ValueError("Reference angular momentum norm is zero")

    c_hat = h_vec / h_norm
    i_hat = np.cross(c_hat, r_hat)

    return np.vstack([r_hat, i_hat, c_hat])


def compute_ric_residual(
    r_ref_km: np.ndarray,
    v_ref_km_s: np.ndarray,
    r_test_km: np.ndarray,
    v_test_km_s: np.ndarray,
) -> dict:
    ric_basis = build_ric_basis(r_ref_km, v_ref_km_s)

    delta_r = r_test_km - r_ref_km
    delta_v = v_test_km_s - v_ref_km_s

    dric = ric_basis @ delta_r
    dvric = ric_basis @ delta_v

    return {
        "dr_km": float(dric[0]),
        "di_km": float(dric[1]),
        "dc_km": float(dric[2]),
        "dpos_km": float(np.linalg.norm(delta_r)),
        "dvr_km_s": float(dvric[0]),
        "dvi_km_s": float(dvric[1]),
        "dvc_km_s": float(dvric[2]),
    }


# ==========================
# RIC 計算主流程
# ==========================

def compute_ric_for_norad(
    db_path: str,
    norad_id: int,
    start_utc: Optional[datetime] = None,
    end_utc: Optional[datetime] = None,
    compare_frame: str = "GCRS",
) -> int:
    con = duckdb.connect(database=db_path, read_only=False)

    try:
        sql = """
            SELECT
                norad_id,
                epoch_utc,
                frame,
                x_km, y_km, z_km,
                vx_km_s, vy_km_s, vz_km_s
            FROM sp_ephem_raw
            WHERE norad_id = ?
        """
        params = [norad_id]

        if start_utc is not None:
            sql += " AND epoch_utc >= ?"
            params.append(pd.Timestamp(start_utc).tz_convert("UTC").tz_localize(None) if pd.Timestamp(start_utc).tzinfo else pd.Timestamp(start_utc))

        if end_utc is not None:
            sql += " AND epoch_utc <= ?"
            params.append(pd.Timestamp(end_utc).tz_convert("UTC").tz_localize(None) if pd.Timestamp(end_utc).tzinfo else pd.Timestamp(end_utc))

        sql += " ORDER BY epoch_utc"

        df_sp = con.execute(sql, params).fetchdf()
        if df_sp.empty:
            print(f"無 OEM/SP 資料可計算 RIC, norad_id={norad_id}")
            return 0

        results = []

        for _, row in df_sp.iterrows():
            epoch_utc = pd.Timestamp(row["epoch_utc"]).to_pydatetime().replace(tzinfo=timezone.utc)

            sp_r = np.array([row["x_km"], row["y_km"], row["z_km"]], dtype=float)
            sp_v = np.array([row["vx_km_s"], row["vy_km_s"], row["vz_km_s"]], dtype=float)
            sp_frame = str(row["frame"]).upper()

            tle = get_candidate_tle_for_epoch(con, norad_id, epoch_utc)
            if tle is None:
                continue

            tle_epoch = pd.Timestamp(tle["epoch_utc"]).to_pydatetime()
            tle_line1 = tle["line1"]
            tle_line2 = tle["line2"]

            try:
                # TLE -> TEME
                r_teme, v_teme = propagate_tle_to_teme(tle_line1, tle_line2, epoch_utc)

                # TEME -> GCRS
                r_tle_cmp, v_tle_cmp = teme_to_gcrf_state(epoch_utc, r_teme, v_teme)

                # OEM frame -> GCRS
                r_sp_cmp, v_sp_cmp = normalize_sp_state_to_compare_frame(
                    epoch_utc, sp_frame, sp_r, sp_v, compare_frame=compare_frame
                )

                # RIC (SP/OEM 為 reference)
                ric = compute_ric_residual(
                    r_ref_km=r_sp_cmp,
                    v_ref_km_s=v_sp_cmp,
                    r_test_km=r_tle_cmp,
                    v_test_km_s=v_tle_cmp,
                )
            except Exception as e:
                print(f"[WARN] norad={norad_id}, epoch={epoch_utc}, RIC 計算失敗: {e}")
                continue

            results.append({
                "norad_id": norad_id,
                "epoch_utc": epoch_utc.replace(tzinfo=None),
                "tle_source_epoch": pd.Timestamp(tle_epoch).to_pydatetime().replace(tzinfo=None),
                "frame": "GCRS",
                "dr_km": ric["dr_km"],
                "di_km": ric["di_km"],
                "dc_km": ric["dc_km"],
                "dpos_km": ric["dpos_km"],
                "dvr_km_s": ric["dvr_km_s"],
                "dvi_km_s": ric["dvi_km_s"],
                "dvc_km_s": ric["dvc_km_s"],
                "tle_line1": tle_line1,
                "tle_line2": tle_line2,
            })

        if not results:
            return 0

        df_out = pd.DataFrame(results)
        con.register("df_ric", df_out)
        con.execute("""
            INSERT INTO tle_sp_ric_residuals AS t BY NAME
            SELECT
                norad_id,
                epoch_utc,
                tle_source_epoch,
                frame,
                dr_km,
                di_km,
                dc_km,
                dpos_km,
                dvr_km_s,
                dvi_km_s,
                dvc_km_s,
                tle_line1,
                tle_line2
            FROM df_ric
            ON CONFLICT (norad_id, epoch_utc, tle_source_epoch) DO NOTHING
        """)
        con.unregister("df_ric")

        return len(df_out)

    finally:
        con.close()


# ==========================
# 模式：從本地暫存載入 OEM 檔
# ==========================

def run_local_sp_files_mode():
    temp_base = ensure_dir(SP_EPHEM_TEMP_PATH)
    final_base = ensure_dir(SP_EPHEM_PATH)

    init_sp_ric_tables(SPACE_DB_PATH)

    mapping = load_oem_mapping_csv(STARLINK_OEM_MAP_CSV)

    files = sorted(temp_base.glob("*"))
    files = [fp for fp in files if fp.is_file()]

    if not files:
        print(f"在暫存目錄 {temp_base} 沒有找到 OEM 檔案")
        return

    for fp in files:
        print(f"處理 OEM 暫存檔案: {fp}")
        try:
            df_sp = parse_sp_ephemeris_file(
                fp,
                default_frame=SP_DEFAULT_FRAME,
                mapping=mapping,
            )

            if df_sp.empty:
                print("  OEM 解析結果為空，略過。")
            else:
                df_sp = df_sp.drop_duplicates(subset=["norad_id", "epoch_utc", "frame"]).reset_index(drop=True)
                upsert_sp_ephem_into_db(SPACE_DB_PATH, df_sp, downloaded_at_utc=datetime.now(timezone.utc))
                print(f"  已寫入 {len(df_sp)} 筆 OEM ephemeris")

            dest = final_base / fp.name
            if dest.exists():
                dest.unlink()
            shutil.move(str(fp), dest)
            print(f"  已搬移到正式資料夾: {dest}")

        except Exception as e:
            print(f"  處理失敗: {fp}, error={e}")

    print(f"完成 OEM 載入，space_db 位於: {SPACE_DB_PATH}")


# ==========================
# 模式：計算 RIC
# ==========================

def run_compute_ric_mode():
    init_sp_ric_tables(SPACE_DB_PATH)

    norad_ids = parse_env_norad_ids(STARLINK_NORAD_IDS)
    if not norad_ids:
        raise RuntimeError("請先在 .env 設定 STARLINK_NORAD_IDS，例如 44713,44714")

    total = 0
    for norad_id in norad_ids:
        try:
            n = compute_ric_for_norad(
                db_path=SPACE_DB_PATH,
                norad_id=norad_id,
                start_utc=None,
                end_utc=None,
                compare_frame=FRAME_COMPARE,
            )
            total += n
            print(f"norad_id={norad_id}, 新增 RIC 筆數={n}")
        except Exception as e:
            print(f"norad_id={norad_id}, 計算失敗: {e}")

    print(f"完成 RIC 計算, 總新增筆數={total}")


# ==========================
# 模式：all
# ==========================

def run_all_mode():
    run_local_sp_files_mode()
    run_compute_ric_mode()


# ==========================
# CLI
# ==========================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Load SpaceX Starlink CCSDS OEM ephemeris and compute TLE-OEM RIC residuals"
    )
    parser.add_argument(
        "--mode",
        choices=["local_sp_files", "compute_ric", "all"],
        default="local_sp_files",
        help=(
            "local_sp_files: 從暫存目錄載入 OEM 檔; "
            "compute_ric: 計算 RIC 殘差; "
            "all: local_sp_files + compute_ric"
        ),
    )

    args = parser.parse_args()

    if args.mode == "local_sp_files":
        run_local_sp_files_mode()
    elif args.mode == "compute_ric":
        run_compute_ric_mode()
    else:
        run_all_mode()


if __name__ == "__main__":
    main()