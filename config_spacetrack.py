from dotenv import load_dotenv
import os
import datetime as dt
import pandas as pd
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

SPACE_TRACK_USER = os.getenv("SPACE_TRACK_IDENTITY")
SPACE_TRACK_PASS = os.getenv("SPACE_TRACK_PASSWORD")

def make_st_client():
    st = SpaceTrackClient(identity=SPACE_TRACK_USER,
                          password=SPACE_TRACK_PASS)
    return st


def download_starlink_tle_history(norad_id: int,
                                  start_dt: dt.datetime,
                                  end_dt: dt.datetime,
                                  out_tle_path: str = None):
    st = make_st_client()

    # 格式化日期字串以確保 API 相容性
    date_str = f"{start_dt.strftime('%Y-%m-%d')}--{end_dt.strftime('%Y-%m-%d')}"

    try:
        # 使用 format='tle' 下載，這會回傳 Line 1, Line 2 的組合
        tle_txt = st.gp(
            norad_cat_id=norad_id,
            epoch=date_str,
            orderby='EPOCH ASC',
            format='tle'
        )
    except Exception as e:
        print(f"Error fetching NORAD {norad_id}: {e}")
        return []

    lines = [l.strip() for l in tle_txt.splitlines() if l.strip()]

    # 更加安全的配對邏輯：檢查首字元是否為 1 和 2
    tle_pairs = []
    for i in range(0, len(lines) - 1):
        if lines[i].startswith('1') and lines[i + 1].startswith('2'):
            # 檢查兩行是否屬於同一顆衛星（NORAD ID 檢查）
            if lines[i][2:7] == lines[i + 1][2:7]:
                tle_pairs.append((lines[i], lines[i + 1]))

    # 去除重複項 (以 Line 1 作為唯一標識，因為它包含完整的 Epoch)
    seen_lines = set()
    unique_pairs = []
    for p in tle_pairs:
        if p[0] not in seen_lines:
            unique_pairs.append(p)
            seen_lines.add(p[0])

    if out_tle_path and unique_pairs:
        with open(out_tle_path, "w", encoding="utf-8") as f:
            for l1, l2 in unique_pairs:
                f.write(f"{l1}\n{l2}\n")

    return unique_pairs



def download_starlink_tle_history_old(norad_id: int,
                                  start_dt: dt.datetime,
                                  end_dt: dt.datetime,
                                  out_tle_path: str = None):
    """
    從 Space-Track 下載某顆 Starlink 衛星在時間區間內的 TLE 歷史（GP）。
    以 TLE 格式字串輸出，同時回傳 list[(L1, L2)]。
    """
    st = make_st_client()
    drange = op.inclusive_range(start_dt, end_dt)

    # class=gp / gp_history，使用 format='tle' 直接拿 TLE 文字。[web:37][web:13]
    tle_txt = st.gp(
        norad_cat_id=norad_id,
        epoch=drange,
        orderby='EPOCH',
        format='tle'
    )

    lines = [l for l in tle_txt.splitlines() if l.strip()]
    tle_pairs = [(lines[i], lines[i+1]) for i in range(0, len(lines), 2)]

    if out_tle_path:
        with open(out_tle_path, "w", encoding="utf-8") as f:
            for l1, l2 in tle_pairs:
                f.write(l1.strip() + "\n")
                f.write(l2.strip() + "\n")

    return tle_pairs

if __name__ == "__main__":
    # 範例：某顆 Starlink，請換成你要分析的 NORAD
    norad_id = 44714
    center = dt.datetime(2026, 4, 1, tzinfo=dt.timezone.utc)
    start_dt = center - dt.timedelta(days=5)
    end_dt   = center + dt.timedelta(days=5)

    tle_pairs = download_starlink_tle_history(
        norad_id,
        start_dt,
        end_dt,
        out_tle_path=f"starlink_{norad_id}_tle_5d.txt"
    )
    print(f"TLE count for {norad_id}:", len(tle_pairs))