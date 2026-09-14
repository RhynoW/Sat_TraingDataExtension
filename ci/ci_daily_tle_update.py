#!/usr/bin/env python3
"""ci_daily_tle_update.py — GitHub Actions 每日 TLE 增量更新（雲端無狀態版）。

背景：本機的 download_TLE_unified.py 靠本機 .env 的 LAST_TLE_DATE 記住抓取進度，
且母庫 space_db.duckdb（14GB）只存在本機，兩者都無法搬進 GitHub Actions 這種
「每次全新環境、用完即丟」的執行環境。

本腳本改用「HF Dataset 上的年度 Parquet」取代兩者：
  1. 只下載「今年」（跨年時也下載「去年」）的 raw_tle_archive/year=YYYY/data.parquet，
     從中直接讀出 MAX(epoch_utc) 當作續傳起點（免持久化狀態）。
  2. 用 Secrets（SPACE_TRACK_IDENTITY / SPACE_TRACK_PASSWORD）呼叫
     download_TLE_unified.py 既有、已測試過的抓取函式，寫入一個乾淨的臨時小型 DuckDB
     （而不是本機 14GB 母庫）。
  3. 去重後依年份重新切檔，只把有變動的年度檔上傳覆蓋回 HF Dataset。

用法（CI 內執行；本機也可手動跑做測試）：
    python ci/ci_daily_tle_update.py --dataset-repo RhynoWu/starlink-maneuver-db

前置需求：環境變數 SPACE_TRACK_IDENTITY, SPACE_TRACK_PASSWORD, HF_TOKEN。
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
from huggingface_hub import HfApi, hf_hub_download

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from download_TLE_unified import (  # noqa: E402
    SPACE_TRACK_IDENTITY,
    SPACE_TRACK_PASSWORD,
    download_historical_from_spacetrack,
    download_historical_omm_from_spacetrack,
    init_space_db,
)

RAW_TABLE_COLS = [
    "norad_id", "object_name", "line1", "line2", "epoch_jd", "epoch_utc",
    "downloaded_at_utc", "sma_km", "eccentricity", "inclination_deg", "raan_deg",
    "argp_deg", "mean_anomaly_deg", "mean_motion", "energy", "rmin_km", "rmax_km", "bstar",
]  # 須與 init_space_db 之 raw_tle_archive DDL 完全一致；用具名 SELECT 而非 SELECT *，
   # 因 Dataset 上的年度分割檔（export_to_hf_parquet.py 產出）多帶一個 year 分割欄，
   # 位置對應的 SELECT * 會導致欄位數不符（19 vs 18）而 INSERT 失敗


def year_path(year: int) -> str:
    return f"raw_tle_archive/year={year}/data.parquet"


def try_fetch_year_parquet(repo: str, year: int, cache_dir: Path) -> str | None:
    try:
        return hf_hub_download(repo_id=repo, repo_type="dataset",
                                filename=year_path(year), local_dir=str(cache_dir))
    except Exception as exc:  # noqa: BLE001 — 檔案不存在（新年度/首次執行）屬正常情形
        print(f"[ci] year={year} 尚無資料（{type(exc).__name__}），視為空白年度")
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset-repo", default="RhynoWu/starlink-maneuver-db")
    ap.add_argument("--work-dir", default="ci_work")
    ap.add_argument("--source-format", choices=["3le", "omm"], default="3le")
    ap.add_argument("--min-start-date", default="2026-01-01",
                     help="Dataset 完全空白時的起始抓取日期")
    ap.add_argument("--restart-maneuver-space", action="store_true", default=True,
                     help="上傳後重啟 maneuver-detection Space（清掉 httpfs/快取狀態）")
    args = ap.parse_args()

    if not SPACE_TRACK_IDENTITY or not SPACE_TRACK_PASSWORD:
        print("[FAIL] SPACE_TRACK_IDENTITY / SPACE_TRACK_PASSWORD 環境變數未設定")
        return 1

    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    ci_db = work / "ci_master.duckdb"
    if ci_db.exists():
        ci_db.unlink()

    print(f"[1/5] 初始化臨時 DB：{ci_db}")
    init_space_db(str(ci_db))

    today = datetime.now(timezone.utc).date()
    this_year = today.year

    print(f"[2/5] 下載既有年度 parquet（{this_year - 1}、{this_year}）以取得續傳起點 …")
    con = duckdb.connect(str(ci_db))
    n_imported = 0
    for yr in (this_year - 1, this_year):
        p = try_fetch_year_parquet(args.dataset_repo, yr, work / "hf_cache")
        if p:
            cols = ", ".join(RAW_TABLE_COLS)
            con.execute(f"INSERT INTO raw_tle_archive SELECT {cols} FROM read_parquet('{Path(p).as_posix()}')")
            n = con.execute("SELECT count(*) FROM raw_tle_archive").fetchone()[0]
            print(f"      年度 {yr} 匯入後累計 {n:,} 列")
            n_imported += 1
    row = con.execute("SELECT max(epoch_utc) FROM raw_tle_archive").fetchone()
    last_epoch = row[0] if row else None
    con.close()

    if last_epoch is not None:
        last_date = last_epoch.date() if hasattr(last_epoch, "date") else date.fromisoformat(str(last_epoch)[:10])
        start_date = last_date + timedelta(days=1)
        print(f"      續傳起點：{start_date}（來源最新資料日 {last_date}）")
    else:
        start_date = datetime.strptime(args.min_start_date, "%Y-%m-%d").date()
        print(f"      Dataset 無既有資料，改用預設起始日：{start_date}")

    target_end = today - timedelta(days=1)  # Space-Track 通常 T-1 才有完整資料

    if start_date > target_end:
        print(f"[3/5] 已是最新（{start_date} > {target_end}），略過抓取")
    else:
        print(f"[3/5] 抓取 {start_date} 至 {target_end} …")
        from skyfield.api import load as load_skyfield
        ts = load_skyfield.timescale()
        downloader = (download_historical_omm_from_spacetrack
                      if args.source_format == "omm"
                      else download_historical_from_spacetrack)
        download_dir = work / "tle_downloads"
        cur = start_date
        while cur <= target_end:
            nxt = cur + timedelta(days=1)
            try:
                downloader(str(ci_db), str(download_dir), cur.strftime("%Y-%m-%d"),
                           nxt.strftime("%Y-%m-%d"), ts, SPACE_TRACK_IDENTITY, SPACE_TRACK_PASSWORD)
            except Exception as exc:  # noqa: BLE001 — 單日失敗不中斷整批，留待下次補
                print(f"      [warn] {cur} 抓取失敗：{exc}")
            cur = nxt

    print("[4/5] 去重（保險，避免任何重疊區間造成重複列）並依年度重新切檔 …")
    con = duckdb.connect(str(ci_db))
    con.execute("""
        CREATE OR REPLACE TABLE raw_tle_archive AS
        SELECT * FROM raw_tle_archive
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY norad_id, epoch_utc ORDER BY downloaded_at_utc DESC
        ) = 1
    """)
    years = [r[0] for r in con.execute(
        "SELECT DISTINCT CAST(year(epoch_utc) AS INT) FROM raw_tle_archive ORDER BY 1").fetchall()]
    print(f"      涵蓋年度：{years}")

    out_dir = work / "hf_export"
    api = HfApi()
    for yr in years:
        ypath = out_dir / f"year={yr}" / "data.parquet"
        ypath.parent.mkdir(parents=True, exist_ok=True)
        con.execute(f"""
            COPY (SELECT * FROM raw_tle_archive WHERE year(epoch_utc) = {yr}
                  ORDER BY norad_id, epoch_utc)
            TO '{ypath.as_posix()}'
            (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 9, ROW_GROUP_SIZE 122880)
        """)
        n = con.execute(f"SELECT count(*) FROM read_parquet('{ypath.as_posix()}')").fetchone()[0]
        print(f"      year={yr}: {n:,} 列 → {ypath}（{ypath.stat().st_size/1e6:.1f} MB）")
        api.upload_file(path_or_fileobj=str(ypath), path_in_repo=year_path(yr),
                         repo_id=args.dataset_repo, repo_type="dataset",
                         commit_message=f"ci: daily update raw_tle_archive year={yr}")
        print(f"      已上傳 → {args.dataset_repo}/{year_path(yr)}")
    con.close()

    print(f"[5/5] 保留臨時 DB 供下一步（build slim）使用：{ci_db}")
    if args.restart_maneuver_space:
        try:
            api.restart_space("RhynoWu/maneuver-detection")
            print("      已重啟 maneuver-detection Space")
        except Exception as exc:  # noqa: BLE001 — 非致命，容器下次自然會拿到新資料
            print(f"      [warn] 重啟 maneuver-detection Space 失敗（非致命）：{exc}")

    print("[OK] 每日 TLE 更新完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
