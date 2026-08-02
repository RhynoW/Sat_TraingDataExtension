#!/usr/bin/env python3
"""
check_earliest_tle.py — 向 Space-Track 查某 NORAD 的「最早可取得 TLE」。
需先設定環境變數 SPACE_TRACK_IDENTITY / SPACE_TRACK_PASSWORD。

用法：  python check_earliest_tle.py 66666
"""
import os
import sys

from spacetrack import SpaceTrackClient


def main(norad: int) -> None:
    ident = os.getenv("SPACE_TRACK_IDENTITY")
    pw = os.getenv("SPACE_TRACK_PASSWORD")
    if not ident or not pw:
        print("請先設定 SPACE_TRACK_IDENTITY / SPACE_TRACK_PASSWORD 環境變數")
        sys.exit(1)

    st = SpaceTrackClient(identity=ident, password=pw)

    # 最早一筆歷史 GP（依 epoch 升冪，取 1 筆）
    earliest = st.gp_history(norad_cat_id=norad, orderby="epoch asc", limit=1,
                             format="tle")
    # 最新一筆
    latest = st.gp_history(norad_cat_id=norad, orderby="epoch desc", limit=1,
                           format="tle")
    # 總筆數（metadata）
    print(f"=== NORAD {norad} — Space-Track gp_history ===")
    print("最早可取得 TLE：\n" + (earliest or "(無資料)"))
    print("\n最新 TLE：\n" + (latest or "(無資料)"))


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 66666
    main(n)
