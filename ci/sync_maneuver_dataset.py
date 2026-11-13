#!/usr/bin/env python3
"""sync_maneuver_dataset.py — 以本機總庫增量更新 starlink-maneuver-db 之年度 TLE parquet。

背景：GitHub Actions 每日排程已於 2026-09-17 移除（雲端憑證 401），而 ci_daily_tle_update.py
需另外向 Space-Track 重抓一次。本機每日 download_tle_unified.bat 已把最新 TLE 寫入
space_db.duckdb，本腳本直接取用它，不再重抓：
  1. 下載 Dataset 上今年（跨年時含去年）的 raw_tle_archive/year=YYYY/data.parquet。
  2. 自本機 space_db.duckdb 取出近 --lookback-days 天（預設 30）的列，以 norad_id+epoch_utc
     反向比對，只保留 Dataset 尚無者。
     （2026-11-13 修正：原本只取「epoch 晚於 Dataset MAX(epoch)」的列；Space-Track 常晚一兩天才
       發布某 epoch 的 TLE，這些晚到的 TLE epoch 早於 MAX 而被永久略過——10/27–11/11 漏 31,456 筆。）
  3. 依年度併入原檔、重寫並上傳覆蓋；最後重啟 maneuver-detection-i18n Space（清 httpfs／快取）。

用法：
    python ci/sync_maneuver_dataset.py               # 正式執行
    python ci/sync_maneuver_dataset.py --dry-run     # 只統計新增列數，不上傳
    python ci/sync_maneuver_dataset.py --lookback-days 90   # 回補較長期間

前置需求：已 `hf auth login`（或設 HF_TOKEN）；space_db.duckdb 未被其他程序以寫入模式開啟。
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
from huggingface_hub import HfApi, hf_hub_download

REPO_ROOT = Path(__file__).resolve().parents[1]

RAW_TABLE_COLS = [
    "norad_id", "object_name", "line1", "line2", "epoch_jd", "epoch_utc",
    "downloaded_at_utc", "sma_km", "eccentricity", "inclination_deg", "raan_deg",
    "argp_deg", "mean_anomaly_deg", "mean_motion", "energy", "rmin_km", "rmax_km", "bstar",
]  # 與 ci_daily_tle_update.py 一致；Dataset 年度檔另帶 year 分割欄

# 舊版 RhynoWu/maneuver-detection 已 PAUSED，重啟會把它喚醒，故只重啟 i18n 版
SPACES = ["RhynoWu/maneuver-detection-i18n"]


def year_path(year: int) -> str:
    return f"raw_tle_archive/year={year}/data.parquet"


def fetch_year(repo: str, year: int, cache: Path) -> Path | None:
    try:
        return Path(hf_hub_download(repo_id=repo, repo_type="dataset",
                                    filename=year_path(year), local_dir=str(cache)))
    except Exception as exc:  # noqa: BLE001 — 新年度尚無檔案屬正常
        print(f"      year={year} 尚無資料（{type(exc).__name__}）")
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset-repo", default="RhynoWu/starlink-maneuver-db")
    ap.add_argument("--db", default=str(REPO_ROOT / "space_db.duckdb"))
    ap.add_argument("--work-dir", default=str(Path(tempfile.gettempdir()) / "sync_maneuver_dataset"),
                    help="暫存目錄（預設系統暫存區，避免 2.4 GB 檔案落在 repo 內）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--lookback-days", type=int, default=30,
                    help="回頭比對的天數：此期間內本機有、Dataset 沒有的 TLE 一律補上（含晚發布者）")
    ap.add_argument("--keep-work", action="store_true", help="保留下載與輸出檔（預設完成後刪除，約 2.4 GB）")
    args = ap.parse_args()

    if not Path(args.db).exists():
        print(f"[FAIL] 找不到本機總庫：{args.db}")
        return 1
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    this_year = datetime.now(timezone.utc).year

    print(f"[1/4] 下載 Dataset 年度檔（{this_year - 1}、{this_year}）…")
    files = {yr: fetch_year(args.dataset_repo, yr, work / "dl") for yr in (this_year - 1, this_year)}
    files = {yr: p for yr, p in files.items() if p}
    if not files:
        print("[FAIL] Dataset 上找不到任何近兩年的年度檔，請改用 export_to_hf_parquet.py 全量匯出")
        return 1

    con = duckdb.connect()
    src = ", ".join(f"'{p.as_posix()}'" for p in files.values())
    ds_max = con.execute(f"SELECT max(epoch_utc) FROM read_parquet([{src}], union_by_name=true)").fetchone()[0]
    print(f"      Dataset 最新 epoch：{ds_max}")

    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.lookback_days)).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[2/4] 自本機總庫取出 {cutoff} 之後、Dataset 尚無的 TLE …")
    con.execute(f"ATTACH '{Path(args.db).as_posix()}' AS m (READ_ONLY)")
    cols = ", ".join(RAW_TABLE_COLS)
    # 先複製再去重：對 ATTACH 表直接用 QUALIFY 會觸發 DuckDB 內部錯誤（inequal types INTEGER != TIMESTAMP）
    con.execute(f"CREATE TABLE raw AS SELECT {cols} FROM m.raw_tle_archive WHERE epoch_utc > TIMESTAMP '{cutoff}'")
    con.execute("CREATE TABLE dedup AS SELECT * FROM raw "
                "QUALIFY ROW_NUMBER() OVER (PARTITION BY norad_id, epoch_utc ORDER BY downloaded_at_utc DESC) = 1")
    con.execute("DROP TABLE raw")
    con.execute(f"CREATE TABLE have AS SELECT DISTINCT norad_id, epoch_utc FROM read_parquet([{src}], union_by_name=true) "
                f"WHERE epoch_utc > TIMESTAMP '{cutoff}'")
    # 容許 ±1 秒：Dataset 部分列來自其他來源，epoch 微秒位數與本機不同（同一 TLE），
    # 精確比對會把約 22 萬筆同一 TLE 誤判為缺漏而重複寫入（2026-11-13 dry-run 實測）
    con.execute("CREATE TABLE new AS SELECT d.* FROM dedup d ANTI JOIN have h "
                "ON d.norad_id = h.norad_id "
                "AND h.epoch_utc BETWEEN d.epoch_utc - INTERVAL 1 SECOND AND d.epoch_utc + INTERVAL 1 SECOND")
    con.execute("DROP TABLE dedup; DROP TABLE have")
    stats = con.execute("SELECT CAST(year(epoch_utc) AS INT) yr, count(*), min(epoch_utc), max(epoch_utc) "
                        "FROM new GROUP BY 1 ORDER BY 1").fetchall()
    if not stats:
        print("[OK] 本機總庫沒有 Dataset 尚無的 TLE，略過上傳")
        return 0
    late = con.execute(f"SELECT count(*) FROM new WHERE epoch_utc <= TIMESTAMP '{ds_max}'").fetchone()[0]
    print(f"      其中 epoch 早於 Dataset 最新值（晚發布、舊規則會漏掉）者：{late:,} 列")
    for yr, n, lo, hi in stats:
        print(f"      year={yr}: 新增 {n:,} 列（{lo} ~ {hi}）")
    if args.dry_run:
        print("[OK] dry-run，未上傳")
        return 0

    print("[3/4] 併入年度檔並上傳 …")
    api = HfApi()
    for yr, n, _, hi in stats:
        out = work / "out" / f"year={yr}" / "data.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        base = files.get(yr)
        old = (f"SELECT {cols} FROM read_parquet('{base.as_posix()}') UNION ALL " if base else "")
        con.execute(f"""
            COPY (SELECT *, CAST({yr} AS BIGINT) AS year FROM ({old}SELECT * FROM new WHERE year(epoch_utc) = {yr})
                  ORDER BY norad_id, epoch_utc)
            TO '{out.as_posix()}' (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 9, ROW_GROUP_SIZE 122880)
        """)
        total = con.execute(f"SELECT count(*) FROM read_parquet('{out.as_posix()}')").fetchone()[0]
        print(f"      year={yr}: 共 {total:,} 列（{out.stat().st_size / 1e6:,.0f} MB），上傳中 …")
        api.upload_file(path_or_fileobj=str(out), path_in_repo=year_path(yr),
                        repo_id=args.dataset_repo, repo_type="dataset",
                        commit_message=f"data: raw_tle_archive year={yr} 增量 {n:,} 筆（至 {str(hi)[:16]}）")
    con.close()

    print("[4/4] 重啟 Space …")
    for space in SPACES:
        try:
            api.restart_space(space)
            print(f"      已重啟 {space}")
        except Exception as exc:  # noqa: BLE001 — 非致命，容器下次重啟自然拿到新資料
            print(f"      [warn] 重啟 {space} 失敗（非致命）：{exc}")

    if not args.keep_work:
        shutil.rmtree(work, ignore_errors=True)
    print("[OK] starlink-maneuver-db 已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
