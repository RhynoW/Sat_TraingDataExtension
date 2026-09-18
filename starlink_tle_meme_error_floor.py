#!/usr/bin/env python3
"""starlink_tle_meme_error_floor.py — 用現有 ~4.5 個月 Starlink MEME 精密星曆
（2026-05-02～09-17，284 顆衛星全量），直接量測 TLE 半長軸誤差底是否隨時間
（太陽/地磁活動）變化，取代先前「TLE 自我差分」法之間接推論。

方法：對每顆衛星，取其 MEME 精密星曆序列（真值），用「該時刻之前最近一筆
TLE」以 SGP4 傳播至同一時刻（`propagate_with_best_tles`，與論文一/報表
API 實際運作方式一致：永遠用最近的過去 TLE 外推當下狀態），將兩者狀態
向量分別轉為半長軸，取殘差 a_TLE - a_MEME。此殘差直接就是「TLE 相對於
獨立真值的誤差」，不依賴「安靜期」假設或去趨勢/排除跳動等前處理選擇，
理論上優於自我差分法。

全量 284 顆衛星、MEME 降採樣至每日一筆（兼顧涵蓋整個 4.5 個月與運算量）。
除依「TLE 外推時長」分層外，另依「日曆週」分層統計，並交叉比對
F:\\GitHub\\SpaceWeather 之 OMNI2 F10.7／Kp／Dst 週平均，檢驗誤差底是否
隨太陽/地磁活動而系統性變化（而非僅隨資料庫滾動視窗漂移）。
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from skyfield.api import load as skyfield_load

from compare_tle_vs_ephemeris import (
    find_all_ephemeris_files, load_all_meme, query_tles_in_range,
    propagate_with_best_tles, _eci_to_elements,
)

DATA_RAW = Path("data/raw")
REGISTRY_CSV = Path("data/url_registry.csv")
DB_PATH = "space_db.duckdb"
N_SAMPLE = 284
SEED = 42
RESAMPLE_HOURS = 24
SWX_GLOB = r"F:\GitHub\SpaceWeather\data\swx_parquet\**\*.parquet"


def main():
    reg = pd.read_csv(REGISTRY_CSV, usecols=["norad_id", "sat_name"]).drop_duplicates("sat_name")
    sat_dirs = sorted(p for p in DATA_RAW.iterdir() if p.is_dir() and p.name.upper().startswith("STARLINK"))
    print(f"MEME 資料共 {len(sat_dirs)} 顆 Starlink 衛星目錄", flush=True)

    rng = np.random.default_rng(SEED)
    pick = rng.choice(len(sat_dirs), size=min(N_SAMPLE, len(sat_dirs)), replace=False)
    sample_dirs = [sat_dirs[i] for i in pick]
    print(f"抽樣 {len(sample_dirs)} 顆（seed={SEED}）", flush=True)

    ts = skyfield_load.timescale()
    con = duckdb.connect(DB_PATH, read_only=True)

    rows = []
    n_ok, n_skip = 0, 0
    for i, sat_dir in enumerate(sample_dirs):
        sat_name = sat_dir.name
        m = reg[reg["sat_name"] == sat_name]
        if m.empty:
            n_skip += 1
            continue
        norad_id = int(m.iloc[0]["norad_id"])

        files = find_all_ephemeris_files(sat_dir)
        if not files:
            n_skip += 1
            continue
        meme = load_all_meme(sat_name, files)
        if meme.empty or len(meme) < 10:
            n_skip += 1
            continue

        # 降採樣：每 RESAMPLE_HOURS 小時取最近一筆，兼顧涵蓋全時段與運算量
        meme = meme.sort_values("t").reset_index(drop=True)
        meme["_bucket"] = meme["t"].dt.floor(f"{RESAMPLE_HOURS}h")
        meme = meme.groupby("_bucket", as_index=False).first().drop(columns="_bucket")

        t_start, t_end = meme["t"].min(), meme["t"].max()
        tle_df = con.execute(
            "SELECT norad_id, line1, line2, epoch_utc, object_name AS space_track_name "
            "FROM raw_tle_archive WHERE norad_id=? ORDER BY epoch_utc",
            [norad_id],
        ).fetchdf()
        if tle_df.empty:
            n_skip += 1
            continue
        tle_df["epoch_utc"] = pd.to_datetime(tle_df["epoch_utc"], utc=True)
        tle_df = tle_df[(tle_df["epoch_utc"] >= t_start - pd.Timedelta(days=3)) &
                         (tle_df["epoch_utc"] <= t_end)].reset_index(drop=True)
        if tle_df.empty:
            n_skip += 1
            continue

        try:
            prop = propagate_with_best_tles(meme, tle_df, sat_name, ts)
        except Exception as e:
            n_skip += 1
            continue
        if prop.empty:
            n_skip += 1
            continue

        merged = pd.merge(
            meme.rename(columns={c: f"{c}_m" for c in ["r_x","r_y","r_z","v_x","v_y","v_z"]}),
            prop.rename(columns={c: f"{c}_t" for c in ["r_x","r_y","r_z","v_x","v_y","v_z"]}),
            on="t", how="inner",
        )
        if merged.empty:
            n_skip += 1
            continue

        # 找每筆 MEME 時刻所用之 TLE epoch，算出「外推時長」
        tle_epochs = tle_df["epoch_utc"].values
        idx = np.searchsorted(tle_epochs, merged["t"].values, side="right") - 1
        idx = np.clip(idx, 0, len(tle_df) - 1)
        prop_age_h = (merged["t"].values - tle_epochs[idx]) / np.timedelta64(1, "h")

        for j, r in merged.iterrows():
            el_m = _eci_to_elements(r["r_x_m"], r["r_y_m"], r["r_z_m"], r["v_x_m"], r["v_y_m"], r["v_z_m"])
            el_t = _eci_to_elements(r["r_x_t"], r["r_y_t"], r["r_z_t"], r["v_x_t"], r["v_y_t"], r["v_z_t"])
            rows.append(dict(
                sat_name=sat_name, norad_id=norad_id, t=r["t"],
                a_meme_km=el_m["a"], a_tle_km=el_t["a"],
                da_km=el_t["a"] - el_m["a"], prop_age_h=float(prop_age_h[j]),
            ))
        n_ok += 1
        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(sample_dirs)}] 已處理 {n_ok} 顆有效、{n_skip} 顆跳過、累積 {len(rows)} 筆殘差", flush=True)

    con.close()
    print(f"\n有效衛星: {n_ok}/{len(sample_dirs)}（跳過 {n_skip}）， 總殘差筆數: {len(rows)}", flush=True)

    df = pd.DataFrame(rows)
    out_csv = "data/benchmark/starlink_tle_meme_error_floor_20260918.csv"
    df.to_csv(out_csv, index=False)

    da_m = df["da_km"].to_numpy() * 1000.0
    sigma_mad = float(np.median(np.abs(da_m - np.median(da_m))) * 1.4826)
    print(f"\n=== 全體（不分外推時長）===", flush=True)
    print(f"殘差筆數={len(da_m)}  中位|da|={np.median(np.abs(da_m)):.2f} m  "
          f"MAD-sigma={sigma_mad:.2f} m  std={np.std(da_m):.2f} m  "
          f"P90={np.percentile(np.abs(da_m),90):.2f} m", flush=True)

    print(f"\n=== 依 TLE 外推時長分層 ===", flush=True)
    bins = [0, 6, 24, 48, 72, 1e9]
    labels = ["0-6h", "6-24h", "24-48h", "48-72h", ">72h"]
    df["age_bucket"] = pd.cut(df["prop_age_h"], bins=bins, labels=labels)
    for lb in labels:
        sub = df[df["age_bucket"] == lb]
        if len(sub) < 5:
            continue
        da_sub = sub["da_km"].to_numpy() * 1000.0
        sig = float(np.median(np.abs(da_sub - np.median(da_sub))) * 1.4826)
        print(f"  外推 {lb:>7}: n={len(sub):>6}  中位|da|={np.median(np.abs(da_sub)):>6.2f} m  "
              f"MAD-sigma={sig:>6.2f} m", flush=True)

    # ── 時間因素檢驗：僅用「新鮮」外推（<24h）之殘差依日曆週分層，
    #    避免外推時長差異混淆真正的時間（太陽/地磁活動）趨勢 ──
    print(f"\n=== 時間因素檢驗（僅用外推<24h之新鮮殘差，依日曆週分層）===", flush=True)
    fresh = df[df["prop_age_h"] < 24].copy()
    fresh["week"] = pd.to_datetime(fresh["t"]).dt.tz_localize(None).dt.to_period("W").dt.start_time
    weekly = []
    for wk, sub in fresh.groupby("week"):
        if len(sub) < 20:
            continue
        da_sub = sub["da_km"].to_numpy() * 1000.0
        sig = float(np.median(np.abs(da_sub - np.median(da_sub))) * 1.4826)
        weekly.append(dict(week=wk, n=len(sub), median_abs_da_m=float(np.median(np.abs(da_sub))),
                           mad_sigma_m=sig))
    weekly_df = pd.DataFrame(weekly).sort_values("week")
    weekly_csv = "data/benchmark/starlink_tle_meme_error_floor_weekly_20260918.csv"
    weekly_df.to_csv(weekly_csv, index=False)
    print(weekly_df.to_string(index=False), flush=True)

    if len(weekly_df) >= 4:
        from scipy.stats import spearmanr
        rho, p = spearmanr(np.arange(len(weekly_df)), weekly_df["mad_sigma_m"])
        print(f"\n週序 vs MAD-sigma 之 Spearman 相關: rho={rho:.3f}, p={p:.3f}"
              f"（顯著且為正代表隨時間系統性上升，顯著且為負代表下降，不顯著代表無單調時間趨勢）",
              flush=True)

    # ── 與 SpaceWeather OMNI2 F10.7/Kp/Dst 週平均交叉比對 ──
    try:
        swx = duckdb.connect().execute(f"""
            SELECT date_trunc('week', valid_time) AS week, param_code, avg(value) AS v
            FROM read_parquet('{SWX_GLOB}', hive_partitioning=1)
            WHERE param_code IN ('F107_OBS','KP_3H','DST')
            GROUP BY 1, 2
        """).df()
        swx["week"] = pd.to_datetime(swx["week"]).dt.tz_localize(None)
        swx_wide = swx.pivot(index="week", columns="param_code", values="v").reset_index()
        merged_sw = pd.merge(weekly_df, swx_wide, on="week", how="left")
        merged_sw.to_csv("data/benchmark/starlink_tle_meme_error_floor_weekly_swx_20260918.csv", index=False)
        print(f"\n=== 與 F10.7／Kp／Dst 週平均合併（存檔供後續比對，非本次結論）===", flush=True)
        print(merged_sw.to_string(index=False), flush=True)
        for col in ("F107_OBS", "KP_3H", "DST"):
            if col in merged_sw.columns and merged_sw[col].notna().sum() >= 4:
                from scipy.stats import spearmanr as _sp
                r, p = _sp(merged_sw[col], merged_sw["mad_sigma_m"], nan_policy="omit")
                print(f"  {col} vs MAD-sigma: rho={r:.3f}, p={p:.3f}", flush=True)
    except Exception as e:
        print(f"\n[跳過 SpaceWeather 交叉比對] {e}", flush=True)

    print(f"\nsaved -> {out_csv}")
    print(f"saved -> {weekly_csv}")


if __name__ == "__main__":
    main()
