#!/usr/bin/env python3
"""migrate_raw_tle_archive_to_yearly.py — 一次性遷移腳本（本機手動執行一次）。

目的：把 HF Dataset（預設 RhynoWu/starlink-maneuver-db）現有的單一大檔
raw_tle_archive/data.parquet 依年份拆成 raw_tle_archive/year=YYYY/data.parquet，
建立「每日 GitHub Actions 自動更新」所需的資料結構。之後 ci/ci_daily_tle_update.py
才能只抓、只傳「今年」那一小份年度檔，不必碰整包舊資料。

用法（本機執行一次，需要已 `hf auth login` 且對該 Dataset 有寫入權限）：
    python ci/migrate_raw_tle_archive_to_yearly.py
    python ci/migrate_raw_tle_archive_to_yearly.py --dry-run   # 先看會切出哪些年度檔，不上傳

安全性：只會新增 raw_tle_archive/year=YYYY/data.parquet，不會刪除或覆蓋舊的
raw_tle_archive/data.parquet（原檔保留作為備援，可在確認新結構運作正常後再手動清理）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
from huggingface_hub import HfApi, hf_hub_download


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset-repo", default="RhynoWu/starlink-maneuver-db")
    ap.add_argument("--work-dir", default="ci_work/migrate")
    ap.add_argument("--dry-run", action="store_true", help="只切檔，不上傳")
    args = ap.parse_args()

    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)

    print(f"下載現有 {args.dataset_repo}:raw_tle_archive/data.parquet（約 1.7GB，請耐心等候）…")
    src_path = hf_hub_download(repo_id=args.dataset_repo, repo_type="dataset",
                                filename="raw_tle_archive/data.parquet", local_dir=str(work))
    src = Path(src_path).as_posix()

    con = duckdb.connect()
    years = [r[0] for r in con.execute(
        f"SELECT DISTINCT CAST(year(epoch_utc) AS INT) AS y FROM read_parquet('{src}') ORDER BY y"
    ).fetchall()]
    total_before = con.execute(f"SELECT count(*) FROM read_parquet('{src}')").fetchone()[0]
    print(f"偵測到年度：{years}（原檔總列數 {total_before:,}）")

    out_dir = work / "hf_export"
    api = HfApi()
    total_after = 0
    for yr in years:
        ypath = out_dir / f"year={yr}" / "data.parquet"
        ypath.parent.mkdir(parents=True, exist_ok=True)
        con.execute(f"""
            COPY (SELECT * FROM read_parquet('{src}')
                  WHERE year(epoch_utc) = {yr} ORDER BY norad_id, epoch_utc)
            TO '{ypath.as_posix()}'
            (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 9, ROW_GROUP_SIZE 122880)
        """)
        n = con.execute(f"SELECT count(*) FROM read_parquet('{ypath.as_posix()}')").fetchone()[0]
        total_after += n
        print(f"  year={yr}: {n:,} 列 → {ypath}（{ypath.stat().st_size / 1e6:.1f} MB）")
        if not args.dry_run:
            api.upload_file(
                path_or_fileobj=str(ypath),
                path_in_repo=f"raw_tle_archive/year={yr}/data.parquet",
                repo_id=args.dataset_repo, repo_type="dataset",
                commit_message=f"migrate: split raw_tle_archive into year={yr}",
            )
            print("    已上傳")

    print(f"\n總列數比對：原檔 {total_before:,} vs 拆檔後合計 {total_after:,}"
          f"{'（一致，OK）' if total_before == total_after else '  ⚠️ 不一致，請勿刪除舊檔，先排查原因！'}")

    if args.dry_run:
        print("[dry-run] 未上傳。確認上面切出的年度與列數無誤後，移除 --dry-run 重跑即可上傳。")
        return 0

    print("\n遷移完成。舊的 raw_tle_archive/data.parquet 目前仍保留在 Dataset 中作為備援，"
          "建議先確認 ci/ci_build_and_publish_slim.py 與兩個 Space 都運作正常一段時間後，"
          "再手動用 huggingface_hub 的 delete_file 清掉舊檔（非必要，留著對 Dataset 空間影響不大）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
