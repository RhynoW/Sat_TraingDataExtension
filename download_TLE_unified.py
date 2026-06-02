# download_TLE_unified.py

#!/usr/bin/env python3
"""
Unified TLE downloader/loader for space_db.duckdb.

支援兩種模式：
1) mode=spacetrack: 直接從 Space-Track gp_history 下載 TLE，寫入
   - tle_raw
   - raw_tle_archive
   - tle_table

2) mode=local_files: 從暫存目錄 DAILY_TLE_TEMP_PATH 讀 historical_daily_*.tle，
   解析後寫入同一顆 space_db.duckdb 的上述三張表，並搬移到 DAILY_TLE_PATH。
"""

import os
import re
import shutil
import subprocess
import time
import math
from pathlib import Path
from datetime import datetime, timedelta, date, timezone
from sys import exception
from typing import Optional

import duckdb
import pandas as pd
from dotenv import load_dotenv
import dotenv
from skyfield.api import EarthSatellite, load as load_skyfield
from spacetrack import SpaceTrackClient
import spacetrack.operators as op

# ==========================
# 常數與環境變數
# ==========================

load_dotenv()

MU_EARTH = 398600.4418  # km^3/s^2

SPACE_DB_PATH = os.getenv("SPACE_DB_PATH",  r"./space_db.duckdb")

DAILY_TLE_TEMP_PATH = os.getenv("DAILY_TLE_TEMP_PATH", "./tle_downloads_temp")
DAILY_TLE_PATH = os.getenv("DAILY_TLE_PATH", "./tle_downloads")

SPACE_TRACK_IDENTITY = os.getenv("SPACE_TRACK_IDENTITY")
SPACE_TRACK_PASSWORD = os.getenv("SPACE_TRACK_PASSWORD")

# 舊版 tle_raw 解析用 regex
TLE_NAME_RE = re.compile(r"^[^12].*")       # 非 1/2 開頭 → 可能是名稱行
LINE1_RE = re.compile(r"^1\s+(\d{5})")
LINE2_RE = re.compile(r"^2\s+(\d{5})")


# ==========================
# DB 初始化
# ==========================

def init_space_db(db_path: str) -> None:
    """
    在 unified space_db.duckdb 中初始化 TLE 相關表:
      - tle_raw
      - raw_tle_archive
      - tle_table
    若已存在則跳過，並嘗試補上 rmin_km / rmax_km 欄位與索引。
    """
    con = duckdb.connect(database=db_path, read_only=False)

    # 1) tle_raw: 原來 tle_raw.duckdb 的 schema
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS tle_raw (
            norad_id            INTEGER     NOT NULL,
            tle_epoch           TIMESTAMP   NOT NULL,
            tle_epoch_year      INTEGER     NOT NULL,
            tle_epoch_day       DOUBLE      NOT NULL,
            name                VARCHAR,
            line1               VARCHAR     NOT NULL,
            line2               VARCHAR     NOT NULL,
            classification      VARCHAR,
            intl_designator     VARCHAR,
            mean_motion         DOUBLE,
            inclination_deg     DOUBLE,
            raan_deg            DOUBLE,
            eccentricity        DOUBLE,
            argp_deg            DOUBLE,
            mean_anomaly_deg    DOUBLE,
            rev_number          INTEGER,
            bstar               DOUBLE,
            element_number      INTEGER,
            source_file         VARCHAR,
            load_time           TIMESTAMP DEFAULT current_timestamp,
            UNIQUE (norad_id, line1)
        );
        """
    )

    # 2) 主幾何表：tle_table
    con.execute("""
        CREATE TABLE IF NOT EXISTS tle_table (
            norad_id         INTEGER NOT NULL,
            epoch_jd         DOUBLE  NOT NULL,
            date_tag         TIMESTAMP NOT NULL,
            sma_km           DOUBLE  NOT NULL,
            eccentricity     DOUBLE  NOT NULL,
            inclination_deg  DOUBLE  NOT NULL,
            raan_deg         DOUBLE  NOT NULL,
            argp_deg         DOUBLE  NOT NULL,
            mean_anomaly_deg DOUBLE  NOT NULL,
            mean_motion      DOUBLE  NOT NULL,
            energy           DOUBLE  NOT NULL,
            rmin_km          DOUBLE,
            rmax_km          DOUBLE,
            bstar            DOUBLE,
            UNIQUE (norad_id, date_tag)
        );
    """)

    # 3) 原始 TLE 歷史快照表：raw_tle_archive
    con.execute("""
        CREATE TABLE IF NOT EXISTS raw_tle_archive (
            norad_id          INTEGER NOT NULL,
            object_name       VARCHAR,
            line1             VARCHAR NOT NULL,
            line2             VARCHAR NOT NULL,
            epoch_jd          DOUBLE  NOT NULL,
            epoch_utc         TIMESTAMP NOT NULL,
            downloaded_at_utc TIMESTAMP NOT NULL,
            sma_km            DOUBLE  NOT NULL,
            eccentricity      DOUBLE  NOT NULL,
            inclination_deg   DOUBLE  NOT NULL,
            raan_deg          DOUBLE  NOT NULL,
            argp_deg          DOUBLE  NOT NULL,
            mean_anomaly_deg  DOUBLE  NOT NULL,
            mean_motion       DOUBLE  NOT NULL,
            energy            DOUBLE  NOT NULL,
            rmin_km           DOUBLE,
            rmax_km           DOUBLE,
            bstar             DOUBLE
        );
    """)

    # 4) 嘗試補上缺少的欄位（舊版 DB 沒有時用；欄位已存在會拋例外，catch 即可）
    alter_sqls = [
        "ALTER TABLE tle_table ADD COLUMN rmin_km DOUBLE;",
        "ALTER TABLE tle_table ADD COLUMN rmax_km DOUBLE;",
        "ALTER TABLE tle_table ADD COLUMN bstar    DOUBLE;",
        "ALTER TABLE raw_tle_archive ADD COLUMN rmin_km DOUBLE;",
        "ALTER TABLE raw_tle_archive ADD COLUMN rmax_km DOUBLE;",
        "ALTER TABLE raw_tle_archive ADD COLUMN bstar    DOUBLE;",
    ]
    for sql in alter_sqls:
        try:
            con.execute(sql)
        except Exception:
            pass

    # 5) 索引
    try:
        con.execute("CREATE INDEX idx_tle_norad_date ON tle_table(norad_id, date_tag);")
    except Exception:
        pass

    try:
        con.execute("CREATE INDEX idx_raw_norad_epoch ON raw_tle_archive(norad_id, epoch_utc);")
    except Exception:
        pass

    con.close()

    # 6) 回填 bstar：把 tle_raw 中已有的 bstar 補進 tle_table / raw_tle_archive
    backfill_bstar_from_tle_raw(db_path)


def backfill_bstar_from_tle_raw(db_path: str) -> None:
    """
    從 tle_raw（source of truth）將 bstar 回填至 tle_table 與 raw_tle_archive。
    只更新 bstar IS NULL 且 tle_raw 有非 NULL 值的列，冪等可重複執行。

    時間戳對齊說明：
      tle_raw.tle_epoch  — UTC（parse_tle_epoch 以 timezone.utc 解析）
      tle_table.date_tag — 舊批次資料以 CST（UTC+8）存入，因此比 tle_raw 早 8 小時
                           新批次（download_TLE_unified.py）以 UTC 存入（兩者並存）
      對齊策略：同時嘗試精確 UTC 匹配，以及 date_tag + 8h = tle_epoch（舊 CST 資料）
    """
    con = duckdb.connect(database=db_path, read_only=False)
    try:
        # tle_table：兩種對齊方式：UTC 精確匹配 + CST 偏移匹配
        con.execute("""
            UPDATE tle_table t
            SET    bstar = r.bstar
            FROM   tle_raw r
            WHERE  t.norad_id = r.norad_id
              AND  (
                    t.date_tag                          = r.tle_epoch
                 OR t.date_tag + INTERVAL '8' HOUR = r.tle_epoch
              )
              AND  t.bstar    IS NULL
              AND  r.bstar    IS NOT NULL
        """)

        # raw_tle_archive：以 (norad_id, line1) 對齊（最精確，無時區問題）
        con.execute("""
            UPDATE raw_tle_archive a
            SET    bstar = r.bstar
            FROM   tle_raw r
            WHERE  a.norad_id = r.norad_id
              AND  a.line1    = r.line1
              AND  a.bstar   IS NULL
              AND  r.bstar   IS NOT NULL
        """)

        n1 = con.execute("SELECT COUNT(*) FROM tle_table WHERE bstar IS NOT NULL").fetchone()[0]
        n2 = con.execute("SELECT COUNT(*) FROM raw_tle_archive WHERE bstar IS NOT NULL").fetchone()[0]
        print(f"[backfill_bstar] tle_table bstar 有值: {n1:,} 列  |  raw_tle_archive bstar 有值: {n2:,} 列")
    finally:
        con.close()


# ==========================
# 幾何計算
# ==========================

def sma_from_no_kozai_rad_per_min(no_kozai_rad_per_min: float) -> float:
    n_rad_s = no_kozai_rad_per_min / 60.0
    return (MU_EARTH / (n_rad_s ** 2)) ** (1.0 / 3.0)


def radial_range_from_a_e(sma_km: float, ecc: float) -> tuple[float, float]:
    """
    根據半長軸 a 與偏心率 e，計算地心徑向範圍：
        rmin = a(1-e)
        rmax = a(1+e)
    """
    rmin_km = sma_km * (1.0 - ecc)
    rmax_km = sma_km * (1.0 + ecc)
    return rmin_km, rmax_km


# ==========================
# 解析 TLE（沿用 tle_database7 版本）
# ==========================

def parse_tle_epoch(line1: str) -> tuple[int, float, datetime]:
    year_str = line1[18:20]
    day_str = line1[20:32]

    yy = int(year_str)
    year4 = 1900 + yy if yy >= 57 else 2000 + yy  # Sputnik 1957 分界
    day_of_year = float(day_str)

    dt0 = datetime(year4, 1, 1, tzinfo=timezone.utc)
    dt = dt0 + timedelta(days=day_of_year - 1.0)

    return year4, day_of_year, dt


def parse_line1_basic(line1: str) -> dict:
    classification = line1[7].strip() or None
    intl_designator = (line1[9:17]).strip() or None

    bstar_s = line1[53:61].strip()
    bstar = None
    if bstar_s and bstar_s not in ["0", "00000-0"]:
        m = re.match(r"([ +-]?\d{5})([ +-]\d)", bstar_s.replace(" ", ""))
        if m:
            mant = float(m.group(1)) * 1e-5
            expo = int(m.group(2))
            bstar = mant * (10.0 ** expo)

    elem_num_s = line1[64:68].strip()
    element_number = int(elem_num_s) if elem_num_s else None

    return {
        "classification": classification,
        "intl_designator": intl_designator,
        "bstar": bstar,
        "element_number": element_number,
    }


def parse_line2_orbit(line2: str) -> dict:
    inc_deg = float(line2[8:16])
    raan_deg = float(line2[17:25])
    ecc_str = line2[26:33].strip()
    ecc = float(f"0.{ecc_str}") if ecc_str else 0.0
    argp_deg = float(line2[34:42])
    ma_deg = float(line2[43:51])
    mm = float(line2[52:63])
    rev_str = line2[63:68].strip()
    rev = int(rev_str) if rev_str else None

    return {
        "inclination_deg": inc_deg,
        "raan_deg": raan_deg,
        "eccentricity": ecc,
        "argp_deg": argp_deg,
        "mean_anomaly_deg": ma_deg,
        "mean_motion": mm,
        "rev_number": rev,
    }


def parse_tle_file_to_tle_raw_records(file_path: Path) -> pd.DataFrame:
    """
    自動判斷 3 行 TLE（名稱 + line1 + line2）或 2 行 TLE（line1 + line2），
    並回傳適合寫入 space_db.tle_raw 的 DataFrame。
    """
    lines = [ln.rstrip("\n") for ln in file_path.open("r", encoding="utf-8", errors="ignore")]
    records = []

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()

        # case A: name + line1 + line2
        if (
            TLE_NAME_RE.match(line)
            and i + 2 < n
            and LINE1_RE.match(lines[i + 1])
            and LINE2_RE.match(lines[i + 2])
        ):
            name = line.strip()
            line1 = lines[i + 1].rstrip()
            line2 = lines[i + 2].rstrip()
            i += 3

        # case B: line1 + line2
        elif (
            LINE1_RE.match(line)
            and i + 1 < n
            and LINE2_RE.match(lines[i + 1])
        ):
            name = None
            line1 = line
            line2 = lines[i + 1].rstrip()
            i += 2

        else:
            i += 1
            continue

        norad1 = int(line1[2:7])
        norad2 = int(line2[2:7])
        if norad1 != norad2:
            continue

        epoch_year, epoch_day, epoch_dt = parse_tle_epoch(line1)
        line1_info = parse_line1_basic(line1)
        line2_info = parse_line2_orbit(line2)

        rec = {
            "norad_id": norad1,
            "tle_epoch": epoch_dt,
            "tle_epoch_year": epoch_year,
            "tle_epoch_day": epoch_day,
            "name": name,
            "line1": line1,
            "line2": line2,
            "source_file": file_path.name,
        }
        rec.update(line1_info)
        rec.update(line2_info)
        records.append(rec)

    return pd.DataFrame(records)


# ==========================
# 寫入 space_db 的統一函式
# ==========================

def upsert_tle_into_space_db(
    db_path: str,
    df_tle_raw: pd.DataFrame,
    source_datetime_for_archive: Optional[datetime] = None,
) -> None:
    """
    給一個已經依 tle_raw schema 解析好的 DataFrame，
    在 unified space_db.duckdb 中：
      - 寫入 tle_raw
      - 轉幾何後寫入 raw_tle_archive / tle_table
    """
    print(">>> upsert_tle_into_space_db version: anti-join v4, date", datetime.now())
    if df_tle_raw.empty:
        return

    # Space-Track occasionally returns two TLEs for the same satellite with
    # identical epoch but different elements (different line1).
    # idx_tle_raw_norad_epoch is a UNIQUE index on (norad_id, tle_epoch), which
    # ON CONFLICT (norad_id, line1) DO NOTHING does not cover.
    # Deduplicate here so the batch itself is epoch-unique before hitting the DB.
    df_tle_raw = (
        df_tle_raw
        .drop_duplicates(subset=["norad_id", "tle_epoch"], keep="first")
        .reset_index(drop=True)
    )

    df_geo = df_tle_raw.copy()

    # ---- 時間欄位統一 ----
    df_geo["tle_epoch"] = pd.to_datetime(df_geo["tle_epoch"], utc=True)
    df_geo["epoch_utc"] = df_geo["tle_epoch"]
    df_geo["epoch_utc_naive"] = df_geo["epoch_utc"].dt.tz_convert("UTC").dt.tz_localize(None)

    downloaded_at_utc = source_datetime_for_archive or datetime.now(timezone.utc)
    downloaded_at_utc_naive = pd.Timestamp(downloaded_at_utc).tz_convert("UTC").tz_localize(None)
    df_geo["downloaded_at_utc"] = downloaded_at_utc_naive

    # 用 int64 ns 計算 Julian Date，避免 Series.view() deprecated warning
    epoch_ns = df_geo["epoch_utc_naive"].to_numpy(dtype="datetime64[ns]").astype("int64")
    df_geo["epoch_jd"] = epoch_ns / 8.64e13 + 2440587.5

    # ---- 幾何欄位 ----
    sma_list = []
    rmin_list = []
    rmax_list = []
    energy_list = []

    for _, row in df_geo.iterrows():
        mm = float(row["mean_motion"])  # rev/day
        no_kozai_rad_per_min = (2.0 * math.pi * mm) / 1440.0
        sma_km = sma_from_no_kozai_rad_per_min(no_kozai_rad_per_min)
        sma_list.append(sma_km)

        ecc = float(row["eccentricity"])
        rmin_km, rmax_km = radial_range_from_a_e(sma_km, ecc)
        rmin_list.append(rmin_km)
        rmax_list.append(rmax_km)

        energy_list.append(-MU_EARTH / (2.0 * sma_km))

    df_geo["sma_km"] = sma_list
    df_geo["rmin_km"] = rmin_list
    df_geo["rmax_km"] = rmax_list
    df_geo["energy"] = energy_list

    # ---- 組成 raw_tle_archive dataframe ----
    df_raw_arch = df_geo[
        [
            "norad_id",
            "name",
            "line1",
            "line2",
            "epoch_jd",
            "epoch_utc_naive",
            "downloaded_at_utc",
            "sma_km",
            "eccentricity",
            "inclination_deg",
            "raan_deg",
            "argp_deg",
            "mean_anomaly_deg",
            "mean_motion",
            "energy",
            "rmin_km",
            "rmax_km",
            "bstar",
        ]
    ].rename(columns={
        "name": "object_name",
        "epoch_utc_naive": "epoch_utc",
    })

    # ---- 組成 tle_table dataframe ----
    df_tle_table = df_geo[
        [
            "norad_id",
            "epoch_jd",
            "epoch_utc_naive",
            "sma_km",
            "eccentricity",
            "inclination_deg",
            "raan_deg",
            "argp_deg",
            "mean_anomaly_deg",
            "mean_motion",
            "energy",
            "rmin_km",
            "rmax_km",
            "bstar",
        ]
    ].rename(columns={"epoch_utc_naive": "date_tag"})

    # Space-Track occasionally returns two TLEs for the same satellite with
    # different elements (different line1) but identical epoch timestamps.
    # Both survive the tle_raw insert (unique on norad_id, line1) but collapse
    # to the same (norad_id, date_tag) in tle_table.  ON CONFLICT DO NOTHING
    # only deconflicts against existing rows, not within the incoming batch,
    # so deduplicate here before inserting.
    df_tle_table = (
        df_tle_table
        .drop_duplicates(subset=["norad_id", "date_tag"], keep="first")
        .reset_index(drop=True)
    )

    con = duckdb.connect(database=db_path, read_only=False)
    con.execute("SET preserve_insertion_order = false;")

    try:
        # ==========================
        # 1) 寫入 tle_raw（anti-join，避免 INSERT OR IGNORE binder 問題）
        # ==========================
        con.register("df_raw", df_tle_raw)

        # NOT EXISTS guards two distinct unique constraints on tle_raw:
        #   UNIQUE(norad_id, line1)                — exact-duplicate TLE
        #   UNIQUE INDEX idx_tle_raw_norad_epoch   — same epoch, updated elements
        # ON CONFLICT (norad_id, line1) only covered the first one, leaving
        # cross-file same-epoch-different-line1 rows to hit the epoch index.
        con.execute("""
            INSERT INTO tle_raw (
                norad_id, tle_epoch, tle_epoch_year, tle_epoch_day,
                name, line1, line2, classification, intl_designator,
                mean_motion, inclination_deg, raan_deg, eccentricity,
                argp_deg, mean_anomaly_deg, rev_number, bstar,
                element_number, source_file
            )
            SELECT
                src.norad_id,
                src.tle_epoch,
                src.tle_epoch_year,
                src.tle_epoch_day,
                src.name,
                src.line1,
                src.line2,
                src.classification,
                src.intl_designator,
                src.mean_motion,
                src.inclination_deg,
                src.raan_deg,
                src.eccentricity,
                src.argp_deg,
                src.mean_anomaly_deg,
                src.rev_number,
                src.bstar,
                src.element_number,
                src.source_file
            FROM df_raw src
            WHERE NOT EXISTS (
                SELECT 1 FROM tle_raw t
                WHERE t.norad_id = src.norad_id
                  AND (t.line1 = src.line1 OR t.tle_epoch = src.tle_epoch)
            )
        """)

        # Back-fill name for pre-existing rows that were inserted without it
        # (e.g. previously downloaded with format='tle' instead of '3le').
        # Starlink sat names in Space-Track (e.g. "STARLINK-1008") differ from
        # both the NORAD ID and the SpaceX API name — only norad_id is reliable
        # for cross-referencing; this UPDATE merely populates the display label.
        con.register("df_raw_names", df_tle_raw[["norad_id", "line1", "name"]].dropna(subset=["name"]))
        con.execute("""
            UPDATE tle_raw
            SET name = src.name
            FROM df_raw_names src
            WHERE tle_raw.norad_id = src.norad_id
              AND tle_raw.line1    = src.line1
              AND tle_raw.name IS NULL
        """)
        con.unregister("df_raw_names")
        con.unregister("df_raw")

        # ==========================
        # 2) 寫入 raw_tle_archive
        # ==========================
        con.register("df_arch", df_raw_arch)
        con.execute(
            """
            INSERT INTO raw_tle_archive
            SELECT
                norad_id,
                object_name,
                line1,
                line2,
                epoch_jd,
                epoch_utc,
                downloaded_at_utc,
                sma_km,
                eccentricity,
                inclination_deg,
                raan_deg,
                argp_deg,
                mean_anomaly_deg,
                mean_motion,
                energy,
                rmin_km,
                rmax_km,
                bstar
            FROM df_arch
            """
        )

        # Back-fill object_name for pre-existing archive rows inserted without a name
        con.register("df_arch_names", df_raw_arch[["norad_id", "line1", "object_name"]].dropna(subset=["object_name"]))
        con.execute("""
            UPDATE raw_tle_archive
            SET object_name = src.object_name
            FROM df_arch_names src
            WHERE raw_tle_archive.norad_id    = src.norad_id
              AND raw_tle_archive.line1       = src.line1
              AND raw_tle_archive.object_name IS NULL
        """)
        con.unregister("df_arch_names")
        con.unregister("df_arch")

        # ==========================
        # 3) 寫入 tle_table（anti-join）
        # ==========================
        con.register("df_tle_table", df_tle_table)

        # tle_table has no UNIQUE constraint (only a non-unique index), so
        # ON CONFLICT is a no-op there.  Use an explicit NOT EXISTS anti-join
        # to skip rows already present.  Python-level drop_duplicates above
        # already ensures the batch itself has no (norad_id, date_tag) dups.
        con.execute("""
            INSERT INTO tle_table
            SELECT
                src.norad_id,
                src.epoch_jd,
                src.date_tag,
                src.sma_km,
                src.eccentricity,
                src.inclination_deg,
                src.raan_deg,
                src.argp_deg,
                src.mean_anomaly_deg,
                src.mean_motion,
                src.energy,
                src.rmin_km,
                src.rmax_km,
                src.bstar
            FROM df_tle_table src
            WHERE NOT EXISTS (
                SELECT 1 FROM tle_table t
                WHERE t.norad_id = src.norad_id
                  AND t.date_tag = src.date_tag
            )
        """)

        con.unregister("df_tle_table")

    finally:
        con.close()

# ==========================
# 模式 1：Space-Track gp_history 下載
# ==========================

def read_last_tle_date(fmt: str = "%Y-%m-%d") -> Optional[date]:
    val = os.getenv("LAST_TLE_DATE")
    if not val:
        return None
    try:
        return datetime.strptime(val, fmt).date()
    except ValueError:
        return None


def write_last_tle_date(d: date, fmt: str = "%Y-%m-%d") -> None:
    dotenv.set_key(
        str('./.env'),
        "LAST_TLE_DATE",
        d.strftime(fmt)
    )


def download_historical_from_spacetrack(
    db_path: str,
    download_dir: str,
    date_start_str: str,
    date_end_str: str,
    ts,
    identity: str,
    password: str,
) -> str:
    filename = f"historical_daily_{date_start_str}.tle"
    filepath = os.path.join(download_dir, filename)

    d_start = datetime.strptime(date_start_str, '%Y-%m-%d')
    d_end = datetime.strptime(date_end_str, '%Y-%m-%d')

    st = SpaceTrackClient(identity=identity, password=password)
    drange = op.inclusive_range(d_start, d_end)

    if os.path.isfile(filepath):
        print(f"檔案存在 {filepath}，取消下載")
    else:
        start = time.perf_counter()
        time.sleep(10)  # 避免太密集呼叫
        # format='3le' returns the name line (line 0) so Space-Track's official
        # STARLINK-XXXX label is stored.  Note: Space-Track's STARLINK number is
        # its own sequential assignment — it does NOT equal the NORAD catalog ID
        # or the SpaceX-internal name embedded in MEME ephemeris URLs.
        tle_text = st.gp_history(
            creation_date=drange,
            orderby='NORAD_CAT_ID,EPOCH',
            format='3le',
            emptyresult='show'
        )
        os.makedirs(download_dir, exist_ok=True)
        with open(filepath, 'w', encoding='ascii') as f:
            f.write(tle_text)
        end = time.perf_counter()
        print(
            f"{d_start} 至 {d_end} TLE 歷史資料下載並存檔：{filepath}, "
            f"執行時間: {end - start:.2f} 秒"
        )

    # 解析並寫入 space_db
    start = time.perf_counter()
    df_raw = parse_tle_file_to_tle_raw_records(Path(filepath))
    upsert_tle_into_space_db(db_path, df_raw, source_datetime_for_archive=None)
    end = time.perf_counter()
    print(f"{filepath} 寫入 space_db 時間: {end - start:.2f} 秒")

    return filepath


def run_spacetrack_mode():
    if not SPACE_TRACK_IDENTITY or not SPACE_TRACK_PASSWORD:
        raise RuntimeError("Space-Track 帳號或密碼環境變數未設定")

    ts = load_skyfield.timescale()
    download_dir = Path(DAILY_TLE_PATH)
    download_dir.mkdir(parents=True, exist_ok=True)

    init_space_db(SPACE_DB_PATH)

    fmt = "%Y-%m-%d"
    today = date.today()
    target_end = today - timedelta(days=1)

    last_tle_date = read_last_tle_date(fmt)
    if last_tle_date is None:
        current_date = date(2026, 1, 1)
    else:
        current_date = last_tle_date + timedelta(days=1)

    while current_date <= target_end:
        next_day = current_date + timedelta(days=1)
        try:
            filepath = download_historical_from_spacetrack(
                SPACE_DB_PATH,
                str(download_dir),
                current_date.strftime(fmt),
                next_day.strftime(fmt),
                ts,
                SPACE_TRACK_IDENTITY,
                SPACE_TRACK_PASSWORD,
            )

        except Exception as e:
            print(f"{e} TLE下載失敗，日期 {current_date.strftime(fmt)}")

        write_last_tle_date(current_date, fmt)
        print(f"更新 LAST_TLE_DATE = {current_date.strftime(fmt)}")
        current_date = next_day


# ==========================
# 模式 2：從暫存目錄載入 local TLE 檔
# ==========================

def run_local_files_mode():
    """
    模式 2：
    從 DAILY_TLE_TEMP_PATH 讀 historical_daily_*.tle，
    解析後寫入 space_db 的 tle_raw / raw_tle_archive / tle_table，
    並搬移到 DAILY_TLE_PATH。
    """
    temp_base = Path(DAILY_TLE_TEMP_PATH)
    final_base = Path(DAILY_TLE_PATH)

    temp_base.mkdir(parents=True, exist_ok=True)
    final_base.mkdir(parents=True, exist_ok=True)

    files = sorted(temp_base.glob("historical_daily_*.tle"))
    if not files:
        print(f"在暫存目錄 {temp_base} 沒有找到 historical_daily_*.tle 檔案")
        return

    init_space_db(SPACE_DB_PATH)

    for fp in files:
        print(f"處理暫存檔案: {fp}")
        df = parse_tle_file_to_tle_raw_records(fp)
        if df.empty:
            print("  解析結果為空，略過。")
            dest = final_base / fp.name
            shutil.move(str(fp), dest)
            continue

        # df 內去重：同檔案完全相同 TLE（同 norad_id + line1）只保留一筆
        df = df.drop_duplicates(subset=["norad_id", "line1"]).reset_index(drop=True)

        # 寫入 unified space_db
        upsert_tle_into_space_db(SPACE_DB_PATH, df, source_datetime_for_archive=None)
        print(f"  已寫入 {len(df)} 筆 TLE 至 space_db")

        # 搬移到正式資料夾
        dest = final_base / fp.name
        if dest.exists():
            dest.unlink()
        shutil.move(str(fp), dest)
        print(f"  已搬移到正式資料夾: {dest}")

    print(f"完成載入與搬移，space_db 位於: {SPACE_DB_PATH}")


# ==========================
# 下游重建（slim DB / parquet）
# ==========================

def rebuild_downstream(parquet: bool) -> None:
    """
    TLE 寫入 space_db.duckdb 完成後，呼叫 prc_maneuver/build_slim_db.py
    重建 space_db_slim.duckdb 與/或月份 parquet，並匯出 latest30day_tle.parquet。

    旗標邏輯：
      parquet=False  → build_slim_db.py --slim-only
      parquet=True   → build_slim_db.py --parquet-src slim --latest30day
                       （先建 slim → 月份 parquet → latest30day parquet）
    """
    build_script = Path(__file__).resolve().parent / "prc_maneuver" / "build_slim_db.py"
    if not build_script.exists():
        print(f"[rebuild] 找不到 build_slim_db.py：{build_script}", flush=True)
        return

    import sys as _sys
    cmd = [_sys.executable, str(build_script)]
    if parquet:
        # 先建 slim，再從 slim 匯出月份 parquet，最後匯出 latest30day（從原始 DB）
        cmd += ["--parquet-src", "slim", "--latest30day"]
    else:
        cmd.append("--slim-only")

    print(f"[rebuild] 執行：{' '.join(cmd)}", flush=True)
    t0 = time.perf_counter()
    result = subprocess.run(cmd, text=True)
    elapsed = time.perf_counter() - t0
    if result.returncode != 0:
        print(f"[rebuild] ❌ build_slim_db.py 失敗（exit {result.returncode}，{elapsed:.0f} s）",
              flush=True)
    else:
        print(f"[rebuild] ✅ 完成（{elapsed:.0f} s）", flush=True)


# ==========================
# CLI 入口
# ==========================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Unified TLE downloader/loader for space_db.duckdb")
    parser.add_argument(
        "--mode",
        choices=["spacetrack", "local_files"],
        default="spacetrack",
        help="spacetrack: 從 Space-Track gp_history 下載; local_files: 從暫存目錄載入 historical_daily_*.tle",
    )
    parser.add_argument(
        "--rebuild-slim",
        action="store_true",
        help="TLE 寫入完成後重建 space_db_slim.duckdb（呼叫 prc_maneuver/build_slim_db.py --slim-only）",
    )
    parser.add_argument(
        "--rebuild-parquet",
        action="store_true",
        help="TLE 寫入完成後重建 slim DB 並匯出月份 parquet（隱含 --rebuild-slim）",
    )

    args = parser.parse_args()

    if args.mode == "spacetrack":
        run_spacetrack_mode()
    else:
        run_local_files_mode()

    if args.rebuild_slim or args.rebuild_parquet:
        rebuild_downstream(parquet=args.rebuild_parquet)


if __name__ == "__main__":
    main()
    # python download_TLE_unified.py --mode local_files # 從下載的TLE寫進DB
    # python download_TLE_unified.py --mode spacetrack # 長期跑排程

    # #DBever CLI執行
    # -- tle_raw: 不允許(norad_id, line1)    重複
    # CREATE UNIQUE INDEX tle_raw_uq_norad_line1
    # ON tle_raw(norad_id, line1);
    #
    # -- tle_table: 不允許(norad_id, date_tag) 重複
    # CREATE UNIQUE INDEX tle_table_uq_norad_date
    # ON tle_table(norad_id, date_tag);