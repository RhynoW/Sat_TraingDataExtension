#!/usr/bin/env python3
"""ci_build_and_publish_slim.py — 由 CI 抓好的資料建 space_db_slim.duckdb（GitHub Actions 專用）。

前置：ci_daily_tle_update.py 已在 --ci-master 產生近期全量 raw_tle_archive
（且已把最新年度 parquet 上傳回 HF Dataset）。

輸出：scenario-advanced01/DB/space_db_slim.duckdb（與本機 update_slim_publish_hf.bat
產出格式相容），供後續呼叫既有 scenario-advanced01/tools/publish_db_to_dataset.py
原樣上傳＋重啟 Space，不需修改那支腳本。

涵蓋範圍：
  1. 近 N 天、全衛星 raw_tle_archive（來自 ci-master，已含當年/跨年資料）。
  2. 全歷史白名單：RPO 展示衛星（同 prc_maneuver/build_slim_db.py 預設白名單）
     ∪ StoryMap 故事 JSON 明列 NORAD（含 QZSS 等）∪ 使用者自訂目錄 NORAD，
     以 DuckDB httpfs 遠端讀取 HF Dataset 上『所有年度』parquet 補齊
     （不需要本機 14GB 母庫）。
  3. 其餘小型業務表（sat_n2yo_metadata 等）直接從 HF Dataset 既有檔案原樣帶入
     （這些是慢變動的參考資料，不在每日流程重算）。
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
from pathlib import Path

import duckdb
from huggingface_hub import hf_hub_download

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "scenario-advanced01"
STORIES_DIR = APP / "scenario04" / "config" / "stories"
USER_DIRS = [APP / "scenario04" / "user_defined_SaTCatalogue",
             APP / "scenario04" / "user_defined_tracking_NORAD"]

# 與 prc_maneuver/build_slim_db.py 之 SLIM_COLS_WITH_LINES 對齊
SLIM_COLS = ["norad_id", "epoch_utc", "sma_km", "eccentricity", "inclination_deg",
             "raan_deg", "argp_deg", "mean_anomaly_deg", "mean_motion", "bstar",
             "line1", "line2"]
# 與 prc_maneuver/build_slim_db.py --whitelist 預設值一致（RPO 3D 反演展示案例）
RPO_DEMO_WHITELIST = [58573, 59884, 67689, 69673, 58204, 43874]
# 慢變動小表：原樣從 Dataset 帶入，不在此腳本重算
PASSTHROUGH_TABLES = ["sat_n2yo_metadata", "training_samples",
                       "training_samples_plan_b", "conjunction_events"]


def story_json_ids() -> set[int]:
    """複製 scenario-advanced01/tools/merge_storymap_tle.py 之同名函式邏輯。"""
    ids: set[int] = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("ids", "norads") and isinstance(v, list):
                    ids.update(int(x) for x in v if str(x).isdigit())
                elif k == "norad" and str(v).isdigit():
                    ids.add(int(v))
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    if STORIES_DIR.is_dir():
        for f in STORIES_DIR.glob("*.json"):
            if f.name == "schema.json":
                continue
            try:
                walk(json.loads(f.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
    return ids


def user_defined_ids() -> set[int]:
    ids: set[int] = set()
    for d in USER_DIRS:
        for f in glob.glob(str(d / "*.csv")):
            with open(f, encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    v = (row.get("norad_id") or "").strip()
                    if v.isdigit():
                        ids.add(int(v))
    return ids


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset-repo", default="RhynoWu/starlink-maneuver-db")
    ap.add_argument("--ci-master", default="ci_work/ci_master.duckdb")
    ap.add_argument("--recent-days", type=int, default=14)
    ap.add_argument("--out", default=str(APP / "DB" / "space_db_slim.duckdb"))
    ap.add_argument("--work-dir", default="ci_work")
    args = ap.parse_args()

    ci_master = Path(args.ci_master)
    if not ci_master.exists():
        print(f"[FAIL] 找不到 {ci_master}（請先執行 ci_daily_tle_update.py）")
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    dst = duckdb.connect(str(out))
    dst.execute("INSTALL httpfs; LOAD httpfs;")
    dst.execute(f"ATTACH '{ci_master.as_posix()}' AS src (READ_ONLY);")
    col_str = ", ".join(SLIM_COLS)

    print(f"[1/4] 複製近 {args.recent_days} 天、全衛星 raw_tle_archive …")
    dst.execute(f"""
        CREATE TABLE raw_tle_archive AS
        SELECT {col_str} FROM src.raw_tle_archive
        WHERE epoch_utc >= (SELECT max(epoch_utc) FROM src.raw_tle_archive)
              - INTERVAL '{args.recent_days}' DAY
    """)
    dst.execute("DETACH src")
    n0 = dst.execute("SELECT count(*) FROM raw_tle_archive").fetchone()[0]
    print(f"      {n0:,} 列")

    whitelist = sorted(set(RPO_DEMO_WHITELIST) | story_json_ids() | user_defined_ids())
    print(f"[2/4] 全歷史白名單 {len(whitelist)} 顆（RPO 展示 + StoryMap 故事 JSON[含 QZSS] "
          f"+ 使用者目錄）→ 遠端讀取 {args.dataset_repo} 所有年度 parquet 補齊 …")
    wl_str = ",".join(str(x) for x in whitelist)
    base = f"hf://datasets/{args.dataset_repo}/raw_tle_archive/year=*/data.parquet"
    dst.execute(f"""
        INSERT INTO raw_tle_archive
        SELECT {col_str} FROM read_parquet('{base}', union_by_name=true) w
        WHERE w.norad_id IN ({wl_str})
          AND NOT EXISTS (
              SELECT 1 FROM raw_tle_archive t
              WHERE t.norad_id = w.norad_id AND t.epoch_utc = w.epoch_utc)
    """)
    n1 = dst.execute("SELECT count(*) FROM raw_tle_archive").fetchone()[0]
    print(f"      +{n1 - n0:,} 列（合計 {n1:,}）")

    print("[3/4] 帶入既有小型業務表（原樣沿用 Dataset 上次匯出結果）…")
    cache_dir = Path(args.work_dir) / "hf_cache"
    for tbl in PASSTHROUGH_TABLES:
        try:
            p = hf_hub_download(repo_id=args.dataset_repo, repo_type="dataset",
                                 filename=f"{tbl}/data.parquet", local_dir=str(cache_dir))
        except Exception as exc:  # noqa: BLE001 — 表不存在時略過，slim DB 仍可用（該功能優雅降級）
            print(f"      [skip] {tbl}: {type(exc).__name__}")
            continue
        dst.execute(f'CREATE TABLE "{tbl}" AS SELECT * FROM read_parquet(\'{Path(p).as_posix()}\')')
        n = dst.execute(f'SELECT count(*) FROM "{tbl}"').fetchone()[0]
        print(f"      {tbl}: {n:,} 列")

    print("[4/4] 建索引、CHECKPOINT …")
    try:
        dst.execute("CREATE INDEX idx_rta_norad_epoch ON raw_tle_archive(norad_id, epoch_utc);")
    except Exception as exc:  # noqa: BLE001
        print(f"      索引建立略過：{exc}")
    dst.execute("CHECKPOINT")
    dst.close()

    print(f"[OK] slim DB 完成：{out}（{out.stat().st_size / 1e6:.1f} MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
