"""補齊 TASA 指定 15 顆衛星 2024-01-01 起之歷史 TLE（Space-Track gp_history，一次性）。

下載 2024-01-01 至 2026-04-30 之 3LE（與本機已有資料重疊部分由入庫 anti-join 略過），
原始檔存 data/benchmark/tasa15_backfill/tasa15_gp_history_20240101_20260430.3le.gz，
再以每日排程之同一入庫函式 download_TLE_unified.upsert_tle_into_space_db() 寫入 space_db.duckdb
（tle_raw、raw_tle_archive、tle_table）。帳號密碼讀 .env（SPACE_TRACK_IDENTITY／SPACE_TRACK_PASSWORD），不輸出。
發射晚於 2024-01-01 者，Space-Track 只回傳發射後之 TLE。

用法：python docs/backfill_tasa15_tle.py [--no-ingest]
"""
import gzip
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
OUT = ROOT / "data/benchmark/tasa15_backfill"
RAW = OUT / "tasa15_gp_history_20240101_20260430.3le.gz"
IDS = [64199, 62190, 58651, 53056, 59711, 69018, 60548, 41634, 68831, 61871, 43081, 43797, 56193, 60507, 65316]
T0, T1 = datetime(2024, 1, 1), datetime(2026, 4, 30)


def stats(tag):
    c = duckdb.connect(str(ROOT / "space_db.duckdb"), read_only=True)
    d = c.execute(f"select norad_id, min(epoch_utc), count(*) from raw_tle_archive where norad_id in ({','.join(map(str, IDS))}) "
                  "group by 1 order by 1").fetchall()
    c.close()
    print(tag); [print("  ", r[0], str(r[1])[:10], r[2]) for r in d]
    return {r[0]: (r[1], r[2]) for r in d}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    before = stats("補齊前（norad、首筆、筆數）")
    if not RAW.exists():
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        import spacetrack.operators as op
        from spacetrack import SpaceTrackClient
        st = SpaceTrackClient(identity=os.environ["SPACE_TRACK_IDENTITY"], password=os.environ["SPACE_TRACK_PASSWORD"])
        txt = st.gp_history(norad_cat_id=IDS, epoch=op.inclusive_range(T0, T1), orderby="norad_cat_id,epoch", format="3le")
        with gzip.open(RAW, "wt", encoding="ascii") as g:
            g.write(txt)
        print("下載", txt.count("\n") // 3, "筆 →", RAW.name)
    if "--no-ingest" in sys.argv:
        return
    import download_TLE_unified as dl
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "tasa15.3le"
        f.write_text(gzip.open(RAW, "rt", encoding="ascii").read(), encoding="ascii")
        df = dl.parse_tle_file_to_tle_raw_records(f)
    print("解析", len(df), "筆")
    dl.upsert_tle_into_space_db(str(ROOT / "space_db.duckdb"), df)
    after = stats("補齊後（norad、首筆、筆數）")
    for n in IDS:
        b, a = before.get(n, (None, 0)), after.get(n, (None, 0))
        print(f"  {n}: 首筆 {str(b[0])[:10]} → {str(a[0])[:10]}，筆數 {b[1]} → {a[1]}（+{a[1] - b[1]}）")


if __name__ == "__main__":
    main()
