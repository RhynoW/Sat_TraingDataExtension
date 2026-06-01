#!/usr/bin/env python3
"""
detect_prc_maneuvers.py
-----------------------
偵測中國 LEO 衛星軌道機動事件，支援兩種資料來源：

  --data-source duckdb  (預設)
      從 space_db.duckdb 的 raw_tle_archive 讀取 TLE。
      可搭配 --download 從 Space-Track 補下載缺失資料。

  --data-source parquet
      從月份 parquet 檔案讀取 TLE，無需 DuckDB。
      適用於 Streamlit Cloud / GitHub 部署環境。
      需指定 --parquet-dir（預設 data/tle_parquet/prc）。

演算法（與 compare_tle_vs_ephemeris.py TLE detector 相同）：
  - 比較連續 TLE epoch 之間的 Keplerian element 跳變
  - J2 RAAN 漂移修正後計算 draan_res
  - composite score = max(|da|/1.0, |di|/0.02, |de|/0.001, |draan_res|/0.1)
  - score > 1.0 → 標記為機動

Usage:
  python detect_prc_maneuvers.py --start 2025-01-01 --end 2025-12-31 --download
  python detect_prc_maneuvers.py --start 2025-01-01 --end 2025-12-31 \\
      --data-source parquet --parquet-dir data/tle_parquet/prc
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ── 路徑設定 ─────────────────────────────────────────────────────────────────
REPO_ROOT      = Path(__file__).resolve().parent.parent   # prc_maneuver/../
DB_PATH        = str(REPO_ROOT / "space_db.duckdb")
ANNO_XLSX      = REPO_ROOT / "leo_annotator" / "output" / "annotations_leo_full_with_source中國衛星.xlsx"
OUT_DIR        = Path(__file__).resolve().parent / "output"  # prc_maneuver/output/

# ── 物理常數 ──────────────────────────────────────────────────────────────────
MU  = 398_600.4418    # km³/s²
R_E = 6_378.137       # km
J2  = 1.082_63e-3

# ── 偵測閾值（與 detect_maneuvers.py / compare_tle_vs_ephemeris.py 相同） ───
THR_DA    = 1.0    # km
THR_DI    = 0.02   # deg
THR_DE    = 0.001
THR_DRAAN = 0.1    # deg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("prc_detect")


# ─────────────────────────────────────────────────────────────────────────────
# 軌道力學輔助函式
# ─────────────────────────────────────────────────────────────────────────────

def j2_raan_drift(a: float, e: float, i_deg: float, dt_s: float) -> float:
    """J2 世俗 RAAN 漂移（度），用於從 draan_raw 中扣除自然漂移。"""
    i = math.radians(i_deg)
    n = math.sqrt(MU / a**3)
    p = a * (1.0 - e**2)
    rate = math.degrees(-1.5 * n * J2 * (R_E / p)**2 * math.cos(i))
    return rate * dt_s


def ang_diff(a1: float, a2: float) -> float:
    """有號角度差 (a2−a1)，包裹至 (−180, +180]。"""
    d = (a2 - a1) % 360.0
    return d - 360.0 if d > 180.0 else d


def maneuver_score(da: float, di: float, de: float, draan_res: float) -> float:
    """Max-of-ratios composite score；> 1.0 表示至少一個閾值被超過。"""
    return max(
        abs(da)       / THR_DA,
        abs(di)       / THR_DI,
        abs(de)       / THR_DE,
        abs(draan_res)/ THR_DRAAN,
    )


def da_severity(da_km: float) -> str:
    a = abs(da_km)
    if a < 1.0:  return "none"
    if a < 5.0:  return "small"
    if a < 10.0: return "medium"
    return "large"


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1：Space-Track TLE 補下載
# ─────────────────────────────────────────────────────────────────────────────

def _parse_3le_text(txt: str, norad_ids_set: set[int]) -> pd.DataFrame:
    """
    解析 Space-Track 3le 格式文字，回傳適合寫入 raw_tle_archive 的 DataFrame。
    欄位：norad_id, object_name, line1, line2,
          epoch_jd, epoch_utc, downloaded_at_utc,
          sma_km, eccentricity, inclination_deg, raan_deg,
          argp_deg, mean_anomaly_deg, mean_motion, energy,
          rmin_km, rmax_km, bstar
    """
    lines = [ln.rstrip() for ln in txt.splitlines()]
    records = []
    i = 0
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC

    while i < len(lines):
        ln = lines[i].strip()
        # 嘗試偵測 3-line 格式：name / line1 / line2
        if (not ln.startswith("1") and not ln.startswith("2") and ln
                and i + 2 < len(lines)
                and lines[i+1].strip().startswith("1")
                and lines[i+2].strip().startswith("2")):
            name  = ln
            line1 = lines[i+1].strip()
            line2 = lines[i+2].strip()
            i += 3
        elif (ln.startswith("1") and i + 1 < len(lines)
              and lines[i+1].strip().startswith("2")):
            name  = None
            line1 = ln
            line2 = lines[i+1].strip()
            i += 2
        else:
            i += 1
            continue

        try:
            norad1 = int(line1[2:7])
            norad2 = int(line2[2:7])
        except Exception:
            continue
        if norad1 != norad2 or norad1 not in norad_ids_set:
            continue

        try:
            # 解析 epoch
            yr_s  = line1[18:20]
            yr    = (2000 + int(yr_s)) if int(yr_s) < 57 else (1900 + int(yr_s))
            doyf  = float(line1[20:32])
            day   = int(doyf)
            frac  = doyf - day
            ep_dt = (datetime(yr, 1, 1, tzinfo=timezone.utc)
                     + timedelta(days=day - 1 + frac))
            ep_naive = ep_dt.replace(tzinfo=None)
            epoch_ns = int(ep_naive.timestamp() * 1e9)
            epoch_jd = epoch_ns / 8.64e13 + 2440587.5

            # 軌道根數
            inc    = float(line2[8:16])
            raan   = float(line2[17:25])
            ecc    = float("0." + line2[26:33].strip())
            argp   = float(line2[34:42])
            ma     = float(line2[43:51])
            mm     = float(line2[52:63])   # rev/day

            # 幾何量
            n_rad_s = mm * 2.0 * math.pi / 86400.0
            sma     = (MU / n_rad_s**2) ** (1.0/3.0)
            energy  = -MU / (2.0 * sma)
            rmin    = sma * (1.0 - ecc)
            rmax    = sma * (1.0 + ecc)

            # bstar
            bstar_s = line1[53:61].strip()
            bstar   = None
            m = re.match(r"([+-]?\d{5})([+-]\d)", bstar_s.replace(" ", ""))
            if m:
                bstar = float(m.group(1)) * 1e-5 * (10.0 ** int(m.group(2)))

            records.append({
                "norad_id":          norad1,
                "object_name":       name,
                "line1":             line1,
                "line2":             line2,
                "epoch_jd":          epoch_jd,
                "epoch_utc":         ep_naive,
                "downloaded_at_utc": now_utc,
                "sma_km":            sma,
                "eccentricity":      ecc,
                "inclination_deg":   inc,
                "raan_deg":          raan,
                "argp_deg":          argp,
                "mean_anomaly_deg":  ma,
                "mean_motion":       mm,
                "energy":            energy,
                "rmin_km":           rmin,
                "rmax_km":           rmax,
                "bstar":             bstar,
            })
        except Exception as exc:
            log.debug("略過解析失敗的 TLE 行: %s", exc)

    return pd.DataFrame(records)


def _upsert_to_archive(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """將 df 寫入 raw_tle_archive（以 line1 去重）。回傳插入筆數。"""
    if df.empty:
        return 0
    df = df.drop_duplicates(subset=["norad_id", "line1"]).reset_index(drop=True)
    con.register("_new_tles", df)
    con.execute("""
        INSERT INTO raw_tle_archive
        SELECT src.*
        FROM _new_tles src
        WHERE NOT EXISTS (
            SELECT 1 FROM raw_tle_archive a
            WHERE a.norad_id = src.norad_id
              AND a.line1    = src.line1
        )
    """)
    con.unregister("_new_tles")
    return len(df)


def download_tles(
    norad_ids: list[int],
    dl_start: datetime,
    dl_end: datetime,
    batch_size: int = 150,
    chunk_days: int = 90,
) -> None:
    """
    從 Space-Track 下載指定時間範圍的中國衛星 TLE。
    以 batch_size 個 NORAD ID × chunk_days 天為一組，寫入 raw_tle_archive。
    """
    import spacetrack.operators as op
    from spacetrack import SpaceTrackClient

    identity = os.getenv("SPACE_TRACK_IDENTITY")
    password = os.getenv("SPACE_TRACK_PASSWORD")
    if not identity or not password:
        log.error("未設定 SPACE_TRACK_IDENTITY / SPACE_TRACK_PASSWORD 環境變數")
        sys.exit(1)

    st_client = SpaceTrackClient(identity=identity, password=password)
    norad_set  = set(norad_ids)
    id_batches = [norad_ids[i:i+batch_size] for i in range(0, len(norad_ids), batch_size)]

    # 將時間範圍切成 chunk_days 天的小段
    time_chunks: list[tuple[datetime, datetime]] = []
    cur = dl_start
    while cur < dl_end:
        nxt = min(cur + timedelta(days=chunk_days), dl_end)
        time_chunks.append((cur, nxt))
        cur = nxt + timedelta(seconds=1)

    total_batches = len(id_batches) * len(time_chunks)
    log.info("下載計畫：%d ID批 × %d 時間段 = %d 次 API 請求",
             len(id_batches), len(time_chunks), total_batches)

    con = duckdb.connect(DB_PATH, read_only=False)
    con.execute("SET preserve_insertion_order = false;")

    total_inserted = 0
    req_num = 0
    for tc_start, tc_end in time_chunks:
        drange = op.inclusive_range(tc_start, tc_end)
        log.info("--- 時間段 %s ~ %s ---",
                 tc_start.strftime("%Y-%m-%d"), tc_end.strftime("%Y-%m-%d"))
        for k, batch in enumerate(id_batches, 1):
            req_num += 1
            log.info("[%d/%d] ID批 %d/%d，%d 顆衛星 …",
                     req_num, total_batches, k, len(id_batches), len(batch))
            try:
                txt = st_client.gp_history(
                    norad_cat_id=batch,
                    epoch=drange,
                    orderby="NORAD_CAT_ID,EPOCH",
                    format="3le",
                    emptyresult="show",
                )
            except Exception as exc:
                log.error("  請求 %d 失敗: %s，等待 20s 後繼續", req_num, exc)
                time.sleep(20)
                continue

            df = _parse_3le_text(txt, norad_set)
            if df.empty:
                log.info("  無資料")
            else:
                _upsert_to_archive(con, df)
                total_inserted += len(df)
                log.info("  解析 %d 筆 TLE", len(df))

            if req_num < total_batches:
                time.sleep(8)

    con.close()
    log.info("下載完成，共寫入約 %d 筆 TLE", total_inserted)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2：TLE-based 機動偵測
# ─────────────────────────────────────────────────────────────────────────────

def detect_one_satellite(
    norad_id: int,
    sat_name: str,
    tle_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    對一顆衛星執行 TLE-based 機動偵測。
    tle_df 已按 epoch_utc 排序，欄位：epoch_utc, sma_km, eccentricity,
    inclination_deg, raan_deg。
    """
    if len(tle_df) < 2:
        return pd.DataFrame()

    rows = []
    snaps = tle_df[["epoch_utc", "sma_km", "eccentricity",
                     "inclination_deg", "raan_deg"]].to_dict("records")

    for k in range(len(snaps) - 1):
        s1, s2 = snaps[k], snaps[k+1]

        t1 = pd.Timestamp(s1["epoch_utc"]).tz_localize("UTC") if pd.Timestamp(s1["epoch_utc"]).tzinfo is None else pd.Timestamp(s1["epoch_utc"]).tz_convert("UTC")
        t2 = pd.Timestamp(s2["epoch_utc"]).tz_localize("UTC") if pd.Timestamp(s2["epoch_utc"]).tzinfo is None else pd.Timestamp(s2["epoch_utc"]).tz_convert("UTC")
        dt_s = (t2 - t1).total_seconds()
        if dt_s <= 0:
            continue

        a1, e1, i1, r1 = s1["sma_km"], s1["eccentricity"], s1["inclination_deg"], s1["raan_deg"]
        a2, e2, i2, r2 = s2["sma_km"], s2["eccentricity"], s2["inclination_deg"], s2["raan_deg"]

        a_ref = 0.5 * (a1 + a2)
        e_ref = 0.5 * (e1 + e2)
        i_ref = 0.5 * (i1 + i2)

        da        = a2 - a1
        de        = e2 - e1
        di        = i2 - i1
        draan_raw = ang_diff(r1, r2)
        draan_res = draan_raw - j2_raan_drift(a_ref, e_ref, i_ref, dt_s)
        score     = maneuver_score(da, di, de, draan_res)
        flagged   = score > 1.0

        # 組合 flag_reason 字串
        reasons = []
        sev = da_severity(da)
        if sev != "none":                  reasons.append(f"da={da:+.2f}km[{sev}]")
        if abs(di) > THR_DI:               reasons.append(f"di={di:+.4f}deg")
        if abs(de) > THR_DE:               reasons.append(f"de={de:+.5f}")
        if abs(draan_res) > THR_DRAAN:     reasons.append(f"dOmega_res={draan_res:+.3f}deg")

        rows.append({
            "norad_id":       norad_id,
            "sat_name":       sat_name,
            "t_from":         t1,
            "t_to":           t2,
            "dt_h":           round(dt_s / 3600.0, 2),
            "a_km":           round(a1, 3),
            "alt_km":         round(a1 - R_E, 2),
            "e":              round(e1, 6),
            "i_deg":          round(i1, 4),
            "raan_deg":       round(r1, 4),
            "da_km":          round(da, 4),
            "de":             round(de, 6),
            "di_deg":         round(di, 5),
            "draan_raw_deg":  round(draan_raw, 4),
            "draan_res_deg":  round(draan_res, 4),
            "da_severity":    sev,
            "score":          round(score, 4),
            "flagged":        flagged,
            "flag_reason":    " | ".join(reasons) if reasons else "",
        })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Parquet 資料來源
# ─────────────────────────────────────────────────────────────────────────────

def load_tle_from_parquet(
    norad_ids: list[int],
    t_start: pd.Timestamp,
    t_end: pd.Timestamp,
    parquet_dir: Path,
) -> pd.DataFrame:
    """
    依日期範圍自動選取月份 parquet 檔，載入後過濾 NORAD ID 與時間區間。
    parquet 檔命名格式：{parquet_dir}/YYYY_MM.parquet
    """
    lb = t_start - pd.Timedelta(days=2)  # 2 天 look-back
    # 產生需要的月份列表
    months: list[tuple[int, int]] = []
    cur = pd.Timestamp(lb.year, lb.month, 1, tz="UTC")
    end_mo = pd.Timestamp(t_end.year, t_end.month, 1, tz="UTC")
    while cur <= end_mo:
        months.append((cur.year, cur.month))
        cur += pd.DateOffset(months=1)

    norad_set = set(norad_ids)
    dfs: list[pd.DataFrame] = []
    missing: list[str] = []

    for yr, mo in months:
        fpath = parquet_dir / f"{yr:04d}_{mo:02d}.parquet"
        if not fpath.exists():
            missing.append(fpath.name)
            continue
        df = pd.read_parquet(fpath)
        # 過濾衛星
        if "norad_id" in df.columns:
            df = df[df["norad_id"].isin(norad_set)]
        if not df.empty:
            dfs.append(df)

    if missing:
        log.warning("找不到 %d 個月份 parquet: %s", len(missing), ", ".join(missing))

    if not dfs:
        return pd.DataFrame()

    df_all = pd.concat(dfs, ignore_index=True)
    # 確保 epoch_utc 是 UTC-aware datetime
    df_all["epoch_utc"] = pd.to_datetime(df_all["epoch_utc"], utc=True)
    # 時間過濾
    df_all = df_all[
        (df_all["epoch_utc"] >= lb) &
        (df_all["epoch_utc"] <= t_end)
    ].sort_values(["norad_id", "epoch_utc"]).reset_index(drop=True)

    return df_all


def load_tle_from_duckdb(
    norad_id_name: list[tuple[int, str]],
    t_start: pd.Timestamp,
    t_end: pd.Timestamp,
    db_path: str,
) -> pd.DataFrame:
    """從 DuckDB raw_tle_archive 讀取 TLE 資料。"""
    con = duckdb.connect(db_path, read_only=True)
    id_str = ",".join(str(n) for n, _ in norad_id_name)
    lb = (t_start - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    ue = t_end.strftime("%Y-%m-%d %H:%M:%S")
    df = con.execute(f"""
        SELECT norad_id, epoch_utc,
               sma_km, eccentricity, inclination_deg, raan_deg
        FROM raw_tle_archive
        WHERE norad_id IN ({id_str})
          AND epoch_utc >= '{lb}'
          AND epoch_utc <= '{ue}'
        ORDER BY norad_id, epoch_utc
    """).fetchdf()
    con.close()
    df["epoch_utc"] = pd.to_datetime(df["epoch_utc"], utc=True)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2：TLE-based 機動偵測
# ─────────────────────────────────────────────────────────────────────────────

def run_detection(
    norad_id_name: list[tuple[int, str]],
    t_start: pd.Timestamp,
    t_end: pd.Timestamp,
    data_source: str = "duckdb",
    parquet_dir: Path | None = None,
    db_path: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    對所有衛星執行偵測，回傳 (all_transitions, flagged_events)。
    data_source: 'duckdb' 或 'parquet'
    """
    if data_source == "parquet":
        if parquet_dir is None:
            log.error("--data-source parquet 需指定 --parquet-dir")
            return pd.DataFrame(), pd.DataFrame()
        log.info("從 parquet 讀取 TLE（%s）…", parquet_dir)
        norad_ids = [n for n, _ in norad_id_name]
        df_all = load_tle_from_parquet(norad_ids, t_start, t_end, parquet_dir)
        log.info("parquet 讀取完成：%d 筆 TLE，%d 顆衛星",
                 len(df_all), df_all["norad_id"].nunique() if not df_all.empty else 0)
    else:
        _db = db_path or DB_PATH
        log.info("從 DuckDB 讀取 raw_tle_archive（%s）…", Path(_db).name)
        df_all = load_tle_from_duckdb(norad_id_name, t_start, t_end, _db)
        log.info("DuckDB 讀取完成：%d 筆 TLE，涵蓋 %d 顆衛星",
                 len(df_all), df_all["norad_id"].nunique())

    name_map = dict(norad_id_name)
    all_trans: list[pd.DataFrame] = []

    for norad_id, grp in df_all.groupby("norad_id"):
        sat_name = name_map.get(int(norad_id), f"NORAD-{norad_id}")
        grp_sorted = grp.sort_values("epoch_utc").reset_index(drop=True)
        df_t = detect_one_satellite(int(norad_id), sat_name, grp_sorted)
        if not df_t.empty:
            all_trans.append(df_t)

    if not all_trans:
        return pd.DataFrame(), pd.DataFrame()

    transitions = pd.concat(all_trans, ignore_index=True)
    # 只保留 t_from 在目標區間內的 transition
    tf = pd.to_datetime(transitions["t_from"], utc=True)
    transitions = transitions[(tf >= t_start) & (tf <= t_end)].reset_index(drop=True)

    flagged = transitions[transitions["flagged"]].copy()
    flagged = flagged.sort_values("score", ascending=False).reset_index(drop=True)

    return transitions, flagged


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3：統計與輸出
# ─────────────────────────────────────────────────────────────────────────────

def print_summary(
    trans: pd.DataFrame,
    flagged: pd.DataFrame,
    t_start: pd.Timestamp,
    t_end: pd.Timestamp,
) -> None:
    n_sats  = trans["norad_id"].nunique()
    n_trans = len(trans)
    n_flag  = len(flagged)

    sev_cnt = trans["da_severity"].value_counts()
    ds = t_start.strftime("%Y-%m-%d")
    de = t_end.strftime("%Y-%m-%d")
    print(f"\n{'='*65}")
    print(f"  中國 LEO 衛星機動偵測  {ds} ~ {de}")
    print(f"{'='*65}")
    print(f"  分析衛星數      : {n_sats}")
    print(f"  總 transition 數 : {n_trans}  (~{n_trans/max(n_sats,1):.1f}/衛星)")
    print(f"  標記機動事件數  : {n_flag}  ({100*n_flag/max(n_trans,1):.1f}%)")
    print(f"\n  da 嚴重度分布：")
    for sev in ("large", "medium", "small", "none"):
        c = sev_cnt.get(sev, 0)
        print(f"    {sev:8s} : {c:5d} ({100*c/max(n_trans,1):.1f}%)")

    if n_flag:
        print(f"\n  Top-20 機動事件（按 score 排序）：")
        cols = ["sat_name","norad_id","t_from","t_to","da_km","di_deg","score","flag_reason"]
        print(flagged.head(20)[cols].to_string(index=False))


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="中國 LEO 衛星機動偵測 (TLE-based)")
    # 時間範圍
    ap.add_argument("--start",          default="2026-01-01",
                    help="偵測起始日期 YYYY-MM-DD（預設 2026-01-01）")
    ap.add_argument("--end",            default="2026-05-31",
                    help="偵測結束日期 YYYY-MM-DD（預設 2026-05-31）")
    # 資料來源
    ap.add_argument("--data-source",    choices=["duckdb", "parquet"], default="duckdb",
                    help="TLE 資料來源（預設 duckdb）")
    ap.add_argument("--parquet-dir",    default=None,
                    help="parquet 月份檔目錄（--data-source parquet 時使用；"
                         "預設 data/tle_parquet/prc）")
    ap.add_argument("--db",             default=None,
                    help="DuckDB 路徑（預設 space_db.duckdb；可指定 space_db_slim.duckdb）")
    # 下載選項（僅 duckdb 模式有效）
    ap.add_argument("--download",       action="store_true",
                    help="從 Space-Track 下載缺失 TLE（需帳號，僅 duckdb 模式）")
    ap.add_argument("--batch-size",     type=int, default=150,
                    help="每次 Space-Track 查詢的 NORAD ID 數量（預設 150）")
    ap.add_argument("--dl-chunk-days",  type=int, default=90,
                    help="下載時每段時間區間天數（預設 90）")
    ap.add_argument("--skip-detect",    action="store_true",
                    help="只下載，不執行偵測")
    ap.add_argument("--out-suffix",     default="",
                    help="輸出 CSV 檔名後綴（預設為起始年份）")
    args = ap.parse_args()

    t_start = pd.Timestamp(args.start + " 00:00:00", tz="UTC")
    t_end   = pd.Timestamp(args.end   + " 23:59:59", tz="UTC")
    suffix  = args.out_suffix or f"{args.start[:4]}"

    # 資料來源設定
    data_source = args.data_source
    parquet_dir: Path | None = None
    db_path: str = args.db or DB_PATH

    if data_source == "parquet":
        parquet_dir = Path(args.parquet_dir) if args.parquet_dir else (
            REPO_ROOT / "data" / "tle_parquet" / "prc"
        )
        if not parquet_dir.exists():
            log.error("parquet 目錄不存在: %s", parquet_dir)
            return 1
        log.info("資料來源: parquet（%s）", parquet_dir)
    else:
        log.info("資料來源: DuckDB（%s）", Path(db_path).name)

    # 讀取中國衛星清單
    log.info("讀取中國衛星清單 …")
    ann = pd.read_excel(ANNO_XLSX)
    prc = ann[ann["source_code"].str.contains("China|PRC", case=False, na=False)]
    norad_id_name = list(zip(prc["norad_id"].astype(int), prc["sat_name"].fillna("")))
    log.info("中國衛星數：%d", len(norad_id_name))

    # Phase 1：補下載（僅 duckdb 模式）
    if args.download:
        if data_source == "parquet":
            log.warning("--download 在 parquet 模式下無效，略過")
        else:
            dl_start_dt = datetime(t_start.year, t_start.month, t_start.day, tzinfo=timezone.utc)
            dl_end_dt   = datetime(t_end.year,   t_end.month,   t_end.day,   tzinfo=timezone.utc)
            log.info("=== Phase 1：下載 %s ~ %s TLE ===",
                     dl_start_dt.strftime("%Y-%m-%d"), dl_end_dt.strftime("%Y-%m-%d"))
            norad_ids = [n for n, _ in norad_id_name]
            download_tles(
                norad_ids,
                dl_start=dl_start_dt,
                dl_end=dl_end_dt,
                batch_size=args.batch_size,
                chunk_days=args.dl_chunk_days,
            )
    else:
        log.info("（略過下載）")

    if args.skip_detect:
        log.info("--skip-detect 旗標設定，結束。")
        return 0

    # Phase 2：偵測
    log.info("=== Phase 2：執行 TLE-based 機動偵測（%s ~ %s）===",
             t_start.strftime("%Y-%m-%d"), t_end.strftime("%Y-%m-%d"))
    transitions, flagged = run_detection(
        norad_id_name, t_start, t_end,
        data_source=data_source,
        parquet_dir=parquet_dir,
        db_path=db_path,
    )

    if transitions.empty:
        log.error("偵測結果為空，請確認 DB 資料是否完整。")
        return 1

    # Phase 3：輸出 CSV
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    trans_path = OUT_DIR / f"prc_maneuver_transitions_{suffix}.csv"
    flag_path  = OUT_DIR / f"prc_maneuver_flagged_{suffix}.csv"

    transitions.to_csv(trans_path, index=False, encoding="utf-8-sig")
    flagged.to_csv(flag_path, index=False, encoding="utf-8-sig")

    log.info("Transitions CSV → %s  (%d 列)", trans_path, len(transitions))
    log.info("Flagged CSV     → %s  (%d 列)", flag_path, len(flagged))

    print_summary(transitions, flagged, t_start, t_end)
    return 0


if __name__ == "__main__":
    sys.exit(main())
