#!/usr/bin/env python3
"""backfill_tasa14.py — 回補 NASA/ILRS 14 顆標竿衛星之 TLE 歷史至 space_db.duckdb。

每星依其 ILRS 機動起始年設 --since，向 Space-Track gp_history 取 3LE（Alpha-5 相容），
以既有解析/upsert 管線寫入 raw_tle_archive（idempotent anti-join）；末尾一次性補 bstar。
憑證由 .env 經 dotenv 載入。用法：python backfill_tasa14.py
"""
from __future__ import annotations
import os, sys, time, tempfile
from datetime import datetime, timezone
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

from dotenv import load_dotenv
load_dotenv()

import duckdb
from spacetrack import SpaceTrackClient
import spacetrack.operators as op

from download_TLE_unified import (
    init_space_db, parse_tle_file_to_tle_raw_records,
    upsert_tle_into_space_db, backfill_bstar_from_tle_raw,
)

DB = os.getenv("SPACE_DB_PATH", "space_db.duckdb")

# (NORAD, 名稱, since)  —— since 取 ILRS 機動起始年前緣
SATS = [
    (22076, "TOPEX/Poseidon", "1992-01-01"),
    (26997, "Jason-1",        "2001-01-01"),
    (27386, "Envisat",        "2002-01-01"),
    (33105, "Jason-2",        "2008-01-01"),
    (36508, "CryoSat-2",      "2010-01-01"),
    (37781, "HY-2A",          "2011-01-01"),
    (39086, "SARAL",          "2013-01-01"),
    (41240, "Jason-3",        "2016-01-01"),
    (41335, "Sentinel-3A",    "2016-01-01"),
    (43437, "Sentinel-3B",    "2018-01-01"),
    (46469, "HY-2C",          "2020-01-01"),
    (46984, "Sentinel-6A",    "2020-01-01"),
    (48621, "HY-2D",          "2021-01-01"),
    (54754, "SWOT",           "2023-01-01"),
]


def span(nid):
    con = duckdb.connect(DB, read_only=True)
    r = con.execute("SELECT COUNT(*), MIN(epoch_utc), MAX(epoch_utc) "
                    "FROM raw_tle_archive WHERE norad_id=?", [nid]).fetchone()
    con.close()
    return r


def main():
    ident = os.getenv("SPACE_TRACK_IDENTITY"); pw = os.getenv("SPACE_TRACK_PASSWORD")
    if not ident or not pw:
        print("缺 Space-Track 憑證"); sys.exit(1)
    st = SpaceTrackClient(identity=ident, password=pw)
    init_space_db(DB)

    print(f"{'NORAD':7}{'名稱':16}{'since':>11}{'前筆數':>8}{'後筆數':>8}{'新增':>7}  最早→最晚")
    for nid, nm, since in SATS:
        b = span(nid)
        try:
            text = st.gp_history(norad_cat_id=nid, orderby="epoch asc",
                                 format="3le", epoch=op.greater_than(since))
        except Exception as e:
            print(f"{nid:<7}{nm:16}  Space-Track 查詢失敗: {e}"); continue
        if not text or not text.strip():
            print(f"{nid:<7}{nm:16}  無回傳"); continue
        tmp = Path(tempfile.gettempdir()) / f"bf_{nid}.tle"
        tmp.write_text(text, encoding="utf-8")
        try:
            df = parse_tle_file_to_tle_raw_records(tmp)
            if not df.empty:
                upsert_tle_into_space_db(DB, df, source_datetime_for_archive=datetime.now(timezone.utc))
        except duckdb.IOException as e:
            print(f"{nid:<7}{nm:16}  DB 寫入失敗（被占用？）: {e}"); sys.exit(1)
        finally:
            tmp.unlink(missing_ok=True)
        a = span(nid)
        print(f"{nid:<7}{nm:16}{since:>11}{b[0]:>8}{a[0]:>8}{a[0]-b[0]:>7}  "
              f"{str(a[1])[:10]}→{str(a[2])[:10]}")
        time.sleep(4)  # Space-Track 禮貌性間隔

    print("\n補 bstar（全表一次）…")
    try:
        backfill_bstar_from_tle_raw(DB)
    except Exception as e:
        print(f"bstar 補值略過: {e}")
    print("完成。")


if __name__ == "__main__":
    main()
