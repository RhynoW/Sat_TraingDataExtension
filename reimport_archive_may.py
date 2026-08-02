#!/usr/bin/env python3
"""reimport_archive_may.py — 回填 tle_downloads 中 >=2026-05-01 之 6 位數 NORAD 並標檔。

背景
----
space_db.duckdb 已含 >=2026-05-01 之全部 5 位數 TLE（92 天 / 6.3M 列）；6 位數（Alpha-5，
如 "A0000"=100000）因舊 LINE1_RE=^1\\s+(\\d{5}) 在解析前被丟棄 → 現庫 0 筆。C.1 放寬正規式
後，本腳本以既有解析/upsert 管線回填該缺口，並逐日檔標記**首次引入**的新 6 位數 NORAD。

預設僅回填 6 位數（5 位數已完整、重匯為純去重）；--full 可強制全量重匯。
用法：python reimport_archive_may.py                 # 回填 6 位數 + 產對照表
      python reimport_archive_may.py --cutoff 2026-05-01 --full
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import pandas as pd

from download_TLE_unified import (
    SPACE_DB_PATH,
    init_space_db,
    parse_tle_file_to_tle_raw_records,
    upsert_tle_into_space_db,
)

ARCHIVE = r"F:/GitHub/Sat_TraingDataExtension/tle_downloads"
DATE_RE = re.compile(r"historical_daily_(\d{4})-(\d{2})-(\d{2})\.tle$")
_NAME0 = re.compile(r"^0\s+")


def _file_date(p: Path):
    m = DATE_RE.search(p.name)
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def main():
    ap = argparse.ArgumentParser(description="回填 >=cutoff 之 6 位數 NORAD 並標檔")
    ap.add_argument("--archive", default=ARCHIVE)
    ap.add_argument("--db", default=SPACE_DB_PATH)
    ap.add_argument("--cutoff", default="2026-05-01")
    ap.add_argument("--full", action="store_true",
                    help="連 5 位數全量重匯（慢，且已驗證無必要）；預設僅回填 6 位數缺口")
    args = ap.parse_args()

    cutoff = date.fromisoformat(args.cutoff)
    files = sorted(
        [p for p in Path(args.archive).glob("historical_daily_*.tle")
         if _file_date(p) and _file_date(p) >= cutoff],
        key=_file_date,
    )
    if not files:
        print(f"無 >= {cutoff} 之檔案於 {args.archive}")
        return
    print(f"檔案 {len(files)} 個（{_file_date(files[0])} ~ {_file_date(files[-1])}），"
          f"模式={'全量' if args.full else '僅6位數'}")

    init_space_db(args.db)
    con = duckdb.connect(args.db, read_only=True)
    seen = {int(r[0]) for r in con.execute(
        "SELECT DISTINCT norad_id FROM raw_tle_archive WHERE norad_id >= 100000").fetchall()}
    con.close()
    print(f"匯入前庫中 6 位數: {len(seen)} 顆\n")

    rows = []
    for p in files:
        d = _file_date(p)
        df = parse_tle_file_to_tle_raw_records(p)
        if df.empty:
            continue
        df = df.drop_duplicates(subset=["norad_id", "line1"]).reset_index(drop=True)
        six = df[df["norad_id"] >= 100000]
        ids_here = {int(x) for x in six["norad_id"]}
        new_ids = sorted(ids_here - seen)

        imp = df if args.full else six
        if len(imp):
            try:
                upsert_tle_into_space_db(args.db, imp, source_datetime_for_archive=None)
            except duckdb.IOException as e:
                print(f"  ✗ 寫入失敗（DB 被占用？關閉 app 後重試）：{e}")
                sys.exit(1)

        names = {int(r.norad_id): _NAME0.sub("", (r["name"] or "")).strip()
                 for _, r in six.iterrows()}
        seen |= set(new_ids)
        new_str = "；".join(f"{i}({names.get(i, '')})" for i in new_ids)
        rows.append({"date": d.isoformat(), "file": p.name,
                     "six_rows": len(six), "six_sats": len(ids_here),
                     "new_sats": len(new_ids), "new_ids": new_str})
        star = "★引入新" if new_ids else ""
        print(f"  {d}  6位數列={len(six):5d} 顆={len(ids_here):4d} 新={len(new_ids):4d} {star} "
              f"{new_str[:70]}")

    R = pd.DataFrame(rows)
    out = Path("data/benchmark/reimport_6digit_20260727.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    R.to_csv(out, index=False, encoding="utf-8-sig")

    con = duckdb.connect(args.db, read_only=True)
    fin = con.execute(
        "SELECT COUNT(DISTINCT norad_id) FROM raw_tle_archive WHERE norad_id >= 100000").fetchone()[0]
    con.close()

    print("\n" + "=" * 72)
    print(f"總計首次引入新 6 位數: {int(R['new_sats'].sum())} 顆")
    print(f"引入新 6 位數的檔案數: {int((R['new_sats'] > 0).sum())} / {len(R)}")
    print(f"匯入後庫中 6 位數: {fin} 顆（匯入前 {len(seen) - int(R['new_sats'].sum())}）")
    print(f"對照表 → {out}")


if __name__ == "__main__":
    main()
