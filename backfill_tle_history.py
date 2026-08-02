#!/usr/bin/env python3
"""
backfill_tle_history.py — 從 Space-Track 補下載某 NORAD 的完整 TLE 歷史進 space_db.duckdb。

重用 download_TLE_unified.py 的解析/寫入管線（tle_raw / raw_tle_archive / tle_table，
含去重），確保 schema 一致。

需先設定環境變數 SPACE_TRACK_IDENTITY / SPACE_TRACK_PASSWORD。

用法：
  python backfill_tle_history.py 66666                 # 全歷史
  python backfill_tle_history.py 66666 --since 2025-12-01
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb
from spacetrack import SpaceTrackClient
import spacetrack.operators as op

from download_TLE_unified import (
    init_space_db,
    parse_tle_file_to_tle_raw_records,
    parse_omm_records,
    upsert_tle_into_space_db,
    backfill_bstar_from_tle_raw,
)

DB_PATH = os.getenv("SPACE_DB_PATH", "./space_db.duckdb")


def _norad_epoch_span(db_path: str, norad: int) -> tuple:
    con = duckdb.connect(db_path, read_only=True)
    try:
        r = con.execute(
            "SELECT COUNT(*), MIN(epoch_utc), MAX(epoch_utc) "
            "FROM raw_tle_archive WHERE norad_id=?", [norad]).fetchone()
    finally:
        con.close()
    return r


def main() -> None:
    ap = argparse.ArgumentParser(description="補下載 NORAD 完整 TLE 歷史")
    ap.add_argument("norad", type=int)
    ap.add_argument("--since", default=None, help="起始日期 YYYY-MM-DD（預設全歷史）")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--format", choices=["3le", "omm"], default="3le",
                    help="取回格式：3le（Alpha-5 相容）或 omm（治本：GP/OMM JSON，直接讀 NORAD_CAT_ID）")
    args = ap.parse_args()

    ident = os.getenv("SPACE_TRACK_IDENTITY")
    pw = os.getenv("SPACE_TRACK_PASSWORD")
    if not ident or not pw:
        print("請先設定 SPACE_TRACK_IDENTITY / SPACE_TRACK_PASSWORD 環境變數")
        sys.exit(1)

    norad = args.norad

    # ── 補下載前現況 ─────────────────────────────────────────────────────────
    before = _norad_epoch_span(args.db, norad)
    print(f"[補下載前] NORAD {norad}: rows={before[0]}  epoch {before[1]} ~ {before[2]}")

    # ── 向 Space-Track 取 gp_history（3le 或 OMM/JSON）─────────────────────────
    st = SpaceTrackClient(identity=ident, password=pw)
    kwargs = dict(norad_cat_id=norad, orderby="epoch asc", format=args.format)
    if args.since:
        kwargs["epoch"] = op.greater_than(args.since)
    print(f"[Space-Track] 查詢 gp_history（{args.format}）{kwargs.get('epoch', '(全歷史)')} …")
    text = st.gp_history(**kwargs)
    if not text or not text.strip():
        print("Space-Track 無回傳資料。")
        sys.exit(1)

    init_space_db(args.db)
    tmp = None
    if args.format == "omm":
        omm_list = json.loads(text)
        print(f"[Space-Track] 取得 {len(omm_list)} 筆 OMM。")
        df = parse_omm_records(omm_list, source_file=f"backfill_{norad}_omm")
    else:
        n_sets = text.count("\n1 ")  # 概略計 TLE 筆數
        print(f"[Space-Track] 取得約 {n_sets} 筆 TLE。")
        tmp = Path(tempfile.gettempdir()) / f"backfill_{norad}_{datetime.now():%Y%m%d%H%M%S}.tle"
        tmp.write_text(text, encoding="utf-8")
        df = parse_tle_file_to_tle_raw_records(tmp)
    if df.empty:
        print("解析結果為空，未寫入。")
        sys.exit(1)
    print(f"[解析] {len(df)} 筆記錄，epoch {df['tle_epoch'].min()} ~ {df['tle_epoch'].max()}")

    try:
        upsert_tle_into_space_db(
            args.db, df, source_datetime_for_archive=datetime.now(timezone.utc))
        backfill_bstar_from_tle_raw(args.db)
    except duckdb.IOException as e:
        print(f"\n寫入失敗（資料庫可能被 app 佔用）：{e}")
        print("→ 請先關閉 maneuver_app_2026August.py / 其他佔用 space_db.duckdb 的程式再重試。")
        sys.exit(1)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)

    # ── 補下載後現況 ─────────────────────────────────────────────────────────
    after = _norad_epoch_span(args.db, norad)
    print(f"\n[補下載後] NORAD {norad}: rows={after[0]}  epoch {after[1]} ~ {after[2]}")
    print(f"新增 {after[0] - before[0]} 筆；最早 epoch {before[1]} → {after[1]}")


if __name__ == "__main__":
    main()
