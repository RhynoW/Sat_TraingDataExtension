#!/usr/bin/env python3
"""lit_geometric_distance_demo.py — 案例十一 Tier1 第 6 篇（Geometric Distance
Difference, Aerospace 2025）之補做實作：以本專案既有 Starlink MEME 精密星曆
（作為論文「精密解」之代理）與 SGP4 傳播 TLE 之幾何距離差分，偵測機動。

資料現況（誠實記錄）：本機 sp_ephem_raw 資料表與任何本地快取皆無 MEME 原始檔，
但 data/url_registry.csv 中存有近期（含今日）由既有排程更新之有效下載連結，
本腳本即時連線下載 3 顆目前活躍 Starlink 衛星之 MEME（涵蓋未來72小時預報窗），
與其近期 TLE 做 SGP4 傳播比對。

**方法論限制（誠實記錄，非隱藏）**：MEME 僅提供「未來72小時預報」而非歷史檔案，
故此次示範窗口內（下載當下起算72小時）沒有任何機動已經發生、也沒有可比對的
歷史真值——本腳本能且僅能：(1) 證明方法可實際運作、(2) 輸出真實的幾何距離
殘差時序供檢視、(3) 若窗口內剛好有偵測觸發便如實報告，但**無法產出 P/R/F1**，
因為沒有真值可核對。若要做到與其餘 5 篇一致的量化比較，需要連續多天／數週
持續收集 MEME+TLE 建立自己的歷史檔案庫，非本次時間範圍內可完成。

用法：python lit_geometric_distance_demo.py
輸出：data/benchmark/lit_geometric_distance_demo_20260913.csv（逐衛星 pos_err_km 時序）
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import requests

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from starlink_ephemeris.parser import parse_ephemeris_file
from compare_tle_vs_ephemeris import propagate_with_best_tles, compute_residuals
from skyfield.api import load as skyfield_load

DB = "space_db.duckdb"
N_SATS = 3
DOWNLOAD_DIR = Path("data/_lit_geodist_tmp")


def pick_fresh_satellites(n=N_SATS):
    df = pd.read_csv("data/url_registry.csv")
    df["last_updated"] = pd.to_datetime(df["last_updated"], utc=True)
    df = df.sort_values("last_updated", ascending=False)
    return df.head(n)[["norad_id", "sat_name", "last_url"]].to_dict("records")


def download_meme(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return True
    except Exception as exc:
        print(f"  下載失敗：{exc}")
        return False


def load_recent_tles(nid: int, since_days=10) -> pd.DataFrame:
    con = duckdb.connect(DB, read_only=True)
    df = con.execute(
        f"SELECT norad_id, line1, line2, epoch_utc FROM raw_tle_archive "
        f"WHERE norad_id=? AND line1 IS NOT NULL "
        f"AND epoch_utc >= now() - INTERVAL '{int(since_days)} DAY' ORDER BY epoch_utc",
        [nid]).fetchdf()
    con.close()
    df["epoch_utc"] = pd.to_datetime(df["epoch_utc"], utc=True)
    return df


def detect_change(pos_err: np.ndarray, k=6.0):
    """對幾何距離殘差跑穩健 z-score 異常偵測（與本專案其餘方法一致風格）。"""
    med = np.nanmedian(pos_err)
    sd = 1.4826 * np.nanmedian(np.abs(pos_err - med))
    if not np.isfinite(sd) or sd == 0:
        return np.array([], int)
    return np.where(np.abs(pos_err - med) > k * sd)[0]


def main():
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ts = skyfield_load.timescale()
    sats = pick_fresh_satellites()
    print(f"挑選 {len(sats)} 顆目前活躍衛星：{[s['sat_name'] for s in sats]}")

    all_rows = []
    for s in sats:
        nid, name, url = s["norad_id"], s["sat_name"], s["last_url"]
        print(f"\n[{name}] NORAD {nid}")
        dest = DOWNLOAD_DIR / f"MEME_{nid}.txt"
        t0 = time.time()
        if not download_meme(url, dest):
            continue
        print(f"  下載完成 ({time.time()-t0:.1f}s, {dest.stat().st_size} bytes)")

        try:
            meta, meme_df = parse_ephemeris_file(dest, sat_id=name)
        except Exception as exc:
            print(f"  解析失敗：{exc}"); continue
        print(f"  MEME 點數：{len(meme_df)}，{meme_df['t'].min()} ~ {meme_df['t'].max()}")

        tle_df = load_recent_tles(nid)
        if tle_df.empty:
            print("  無近期 TLE，跳過"); continue
        print(f"  近期 TLE 筆數：{len(tle_df)}")

        try:
            prop_df = propagate_with_best_tles(meme_df, tle_df.rename(columns={"norad_id": "norad_id"}), name, ts)
        except Exception as exc:
            print(f"  SGP4傳播失敗：{exc}"); continue
        if prop_df.empty:
            print("  傳播結果為空，跳過"); continue

        res = compute_residuals(meme_df, prop_df)
        if res.empty:
            print("  殘差計算結果為空（時間戳可能未對齊），跳過"); continue

        idx = detect_change(res["pos_err_km"].to_numpy())
        print(f"  幾何距離殘差：均值={res['pos_err_km'].mean():.3f}km "
              f"中位數={res['pos_err_km'].median():.3f}km "
              f"最大={res['pos_err_km'].max():.3f}km")
        print(f"  觸發異常點數：{len(idx)}"
              + (f"，首個時刻：{res['t'].iloc[idx[0]]}" if len(idx) else "（此72小時窗內無異常，符合大多數衛星短期內不機動的預期）"))

        res["norad_id"] = nid; res["sat_name"] = name
        all_rows.append(res[["t", "norad_id", "sat_name", "pos_err_km", "dr_r_km", "dr_t_km", "dr_n_km"]])

    if all_rows:
        out = pd.concat(all_rows, ignore_index=True)
        p = Path("data/benchmark/lit_geometric_distance_demo_20260913.csv")
        out.to_csv(p, index=False, encoding="utf-8-sig")
        print(f"\n輸出 → {p}（{len(out)} 列）")
    else:
        print("\n無成功結果可輸出。")


if __name__ == "__main__":
    main()
