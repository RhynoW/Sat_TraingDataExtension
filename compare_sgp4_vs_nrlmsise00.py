#!/usr/bin/env python3
"""compare_sgp4_vs_nrlmsise00.py — 直接比較 SGP4（簡化解析阻力）與 J2+NRLMSISE-00
（完整數值大氣密度）兩種力模式，對 MEME 真值的貼合程度，取代僅用 F10.7 做間接
代理指標的相關性分析（見案例二十五 §5 之誠實更正與委員建議）。

方法：對每顆衛星，取一筆較早的 TLE 為起點：
  1. 用起點後第 1 天之 MEME 真值校準 BC（`calibrate_bc`）。
  2. 分別用 SGP4（原生）與 Cowell+NRLMSISE-00（用校準之 BC）傳播至後續數天的
     MEME 觀測時刻。
  3. 兩者對 MEME 之殘差（|a_pred - a_meme|）逐點比較：何者更貼近真值？
     此為委員提出問題之直接量化答案，而非僅相關係數之間接推論。

抽樣少量衛星、橫跨不同 F10.7 條件（低/中/高活動週各挑代表），驗證架構並取得
初步結果；此為概念驗證規模，非全量 284 顆衛星之完整研究（見腳本結尾之誠實
限制說明）。
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import time

import duckdb
import numpy as np
import pandas as pd
from skyfield.api import load as skyfield_load

import nrlmsise00_propagator as prop
from compare_tle_vs_ephemeris import find_all_ephemeris_files, load_all_meme, _eci_to_elements

DB_PATH = "space_db.duckdb"
CALIB_DAYS = 1.0
EVAL_DAYS = 5.0   # 校準後再往前看幾天（涵蓋 F10.7 可能變化之時間尺度）

# 2026-09-19：n=3、n=14 之小樣本結果互相矛盾（n=3 時 SGP4 穩贏 2.3 倍；
# n=14 時勝率拉近至 43%，且 Cowell+NRLMSISE-00 在 SGP4 誤差最大的離群案例
# 上反而更穩健）——樣本數不足以下定論，擴大至 n=100（既有 283 顆 MEME
# 衛星中隨機抽樣，seed=777，見 data/benchmark/_compare_100sats_list_20260919.csv）。
CASES_CSV = "data/benchmark/_compare_100sats_list_20260919.csv"


def main():
    ts = skyfield_load.timescale()
    con = duckdb.connect(DB_PATH, read_only=True)
    rows = []

    CASES = pd.read_csv(CASES_CSV).to_dict("records")
    print(f"載入 {len(CASES)} 顆衛星清單（{CASES_CSV}）", flush=True)

    for case in CASES:
        norad_id, sat_name = case["norad_id"], case["sat_name"]
        print(f"\n=== NORAD {norad_id} ({sat_name}) ===", flush=True)

        sat_dir_candidates = [p for p in __import__("pathlib").Path("data/raw").glob(f"{sat_name}*") if p.is_dir()]
        if not sat_dir_candidates:
            print(f"  [跳過] 找不到 MEME 目錄", flush=True)
            continue
        files = find_all_ephemeris_files(sat_dir_candidates[0])
        meme = load_all_meme(sat_name, files)
        if meme.empty:
            print(f"  [跳過] MEME 資料為空", flush=True)
            continue
        meme = meme.sort_values("t").reset_index(drop=True)

        tle_df = con.execute(
            "SELECT line1, line2, epoch_utc FROM raw_tle_archive WHERE norad_id=? ORDER BY epoch_utc",
            [norad_id],
        ).fetchdf()
        tle_df["epoch_utc"] = pd.to_datetime(tle_df["epoch_utc"], utc=True)
        if tle_df.empty:
            print(f"  [跳過] 查無 TLE", flush=True)
            continue

        # 選一筆 TLE 曆元，之後至少有 CALIB_DAYS+EVAL_DAYS 天的 MEME 涵蓋
        meme_t = meme["t"]
        usable = tle_df[tle_df["epoch_utc"] <= meme_t.max() - pd.Timedelta(days=CALIB_DAYS + EVAL_DAYS)]
        usable = usable[usable["epoch_utc"] >= meme_t.min()]
        if usable.empty:
            print(f"  [跳過] 找不到合適之起點 TLE", flush=True)
            continue
        tle_row = usable.iloc[len(usable) // 3]  # 取前段一筆，非最後一筆，確保後面有足夠評估窗口
        line1, line2, epoch = tle_row["line1"], tle_row["line2"], tle_row["epoch_utc"]
        print(f"  起點 TLE 曆元: {epoch}", flush=True)

        # 校準窗口：曆元後第 0～CALIB_DAYS 天內所有 MEME 觀測，做多點最小平方擬合
        # （取代單點匹配——單點易被局部真實擾動帶偏，見上一輪結果之誠實檢討）
        t1 = epoch + pd.Timedelta(days=CALIB_DAYS)
        calib_window = meme[(meme_t > epoch) & (meme_t <= t1)].iloc[::5].reset_index(drop=True)
        if len(calib_window) < 5:
            print(f"  [跳過] 校準窗口內 MEME 點數不足（{len(calib_window)}）", flush=True)
            continue
        calib_smas = [
            _eci_to_elements(r["r_x"], r["r_y"], r["r_z"], r["v_x"], r["v_y"], r["v_z"])["a"]
            for _, r in calib_window.iterrows()
        ]
        t1_actual = calib_window["t"].iloc[-1]

        print(f"  校準窗口：{calib_window['t'].iloc[0]} ～ {t1_actual}"
              f"（{len(calib_window)} 個 MEME 觀測點，多點最小平方擬合）", flush=True)
        t0 = time.time()
        bc = prop.calibrate_bc_multipoint(
            line1, line2, ts,
            calib_times_utc=calib_window["t"].tolist(), target_sma_km=calib_smas,
        )
        print(f"  校準 BC = {bc:.4e} km^2/kg = {bc*1e6:.4f} m^2/kg （耗時 {time.time()-t0:.1f}s）", flush=True)

        # 評估窗口：t1 之後到 t1+EVAL_DAYS 天。
        # 2026-09-19 修正（關鍵）：先前直接比較「瞬時（osculating）sma」在稀疏、
        # 未對齊軌道相位的取樣點上，結果逐日衰減率正負交替、呈鋸齒狀——這正是
        # 案例十三已發現過的陷阱（瞬時 sma 受 J2 短週期擾動污染，須以多軌道
        #週期平均之「平均根數」比較，而非瞬時值）。改為：每天取密集取樣點
        # （約每 15 分鐘一筆，涵蓋該日全部軌道週期），對 MEME／SGP4／Cowell
        # 三者各自在該日內取平均 sma 再比較，把 J2 短週期雜訊平均掉，讓真正的
        # 長期（秒差）衰減趨勢差異浮現。
        eval_window = meme[(meme_t > t1_actual) & (meme_t <= t1_actual + pd.Timedelta(days=EVAL_DAYS))]
        if eval_window.empty:
            print(f"  [跳過] 評估窗口內無 MEME 資料", flush=True)
            continue
        dense_times = pd.date_range(t1_actual, t1_actual + pd.Timedelta(days=EVAL_DAYS),
                                    freq="15min", inclusive="right")
        print(f"  評估：{len(eval_window)} 筆 MEME 原始點、{len(dense_times)} 個密集取樣時刻"
              f"（每日平均，消除 J2 短週期雜訊）", flush=True)

        t0 = time.time()
        cowell_df = prop.propagate_cowell(line1, line2, dense_times.tolist(), bc, ts=ts)
        print(f"  Cowell+NRLMSISE-00 傳播耗時 {time.time()-t0:.1f}s", flush=True)
        if cowell_df.empty:
            print(f"  [跳過] Cowell 傳播失敗", flush=True)
            continue
        cowell_df["sma_sgp4_km"] = [prop.sgp4_sma_km(line1, line2, t, ts) for t in cowell_df["t"]]
        cowell_df["day"] = ((cowell_df["t"] - t1_actual).dt.total_seconds() / 86400.0).apply(np.floor)

        meme_eval = eval_window.copy()
        meme_eval["sma_meme_km"] = [
            _eci_to_elements(r["r_x"], r["r_y"], r["r_z"], r["v_x"], r["v_y"], r["v_z"])["a"]
            for _, r in meme_eval.iterrows()
        ]
        meme_eval["day"] = ((meme_eval["t"] - t1_actual).dt.total_seconds() / 86400.0).apply(np.floor)

        for day, cg in cowell_df.groupby("day"):
            mg = meme_eval[meme_eval["day"] == day]
            if mg.empty or len(cg) < 10:
                continue
            sma_meme_mean = mg["sma_meme_km"].mean()
            sma_sgp4_mean = cg["sma_sgp4_km"].mean()
            sma_cowell_mean = cg["a_cowell_km"].mean()
            rows.append(dict(
                norad_id=norad_id, day=int(day),
                sma_meme_km=sma_meme_mean, sma_sgp4_km=sma_sgp4_mean, sma_cowell_km=sma_cowell_mean,
                err_sgp4_m=abs(sma_sgp4_mean - sma_meme_mean) * 1000,
                err_cowell_m=abs(sma_cowell_mean - sma_meme_mean) * 1000,
                days_since_calib=float(day),
                n_meme=len(mg), n_dense=len(cg),
            ))

    con.close()
    if not rows:
        print("\n無有效結果。", flush=True)
        return

    df = pd.DataFrame(rows)
    df.to_csv("data/benchmark/compare_sgp4_vs_nrlmsise00_20260919.csv", index=False)

    print("\n" + "=" * 70, flush=True)
    print("=== SGP4 vs Cowell+NRLMSISE-00 對 MEME 真值之殘差比較 ===", flush=True)
    print("=" * 70, flush=True)
    print(df.groupby("norad_id")[["err_sgp4_m", "err_cowell_m"]].median().round(1).to_string(), flush=True)
    print(f"\n全體中位誤差：SGP4={df['err_sgp4_m'].median():.1f} m  "
          f"Cowell+NRLMSISE-00={df['err_cowell_m'].median():.1f} m", flush=True)
    win_rate = (df["err_cowell_m"] < df["err_sgp4_m"]).mean()
    print(f"Cowell+NRLMSISE-00 誤差較小之比例：{win_rate*100:.1f}%（{len(df)} 個評估點）", flush=True)

    print("\n=== 依『距校準第幾天』分層（每日平均值比較，檢驗誤差是否隨天數擴大）===", flush=True)
    print(df.groupby("day")[["err_sgp4_m", "err_cowell_m", "n_meme", "n_dense"]].median().round(1).to_string(), flush=True)

    print(f"\nsaved -> data/benchmark/compare_sgp4_vs_nrlmsise00_20260919.csv")
    print(f"\n【樣本規模說明】本次為 n={len(CASES)} 顆衛星、單一 5 天窗口（2026-06 中旬）；"
          "n=3 與 n=14 之前導結果互相矛盾，顯示小樣本下之勝負比例並不穩定。"
          "本次規模仍侷限於單一觀測窗口／單一時期之太陽活動條件，若要如案例"
          "二十五之規模（284 顆、4.5 個月、涵蓋多種太陽活動條件）系統性回答"
          "「NRLMSISE-00 是否在特定條件下較穩健」，需再擴大時間跨度，非本次範圍。")


if __name__ == "__main__":
    main()
