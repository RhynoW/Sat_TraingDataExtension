#!/usr/bin/env python3
"""j2_sensitivity_analysis.py — 回應論文一限制#7：比較「不做 J2 修正」／
「現行一階 J2 解析式修正」／「SGP4 傳播殘差」三種 ΔRAAN 殘差計算法。

抽樣自 E1 母體（leo_annotator/output/validation_full_p1only.csv，30 天窗口、
tle_status=ok 之 14,019 顆衛星），隨機抽樣 N_SAMPLE 顆（受 dsgp4 逐筆傳播
運算量限制，未跑滿全母體，於報告中明確揭露此抽樣限制）。

三種 ΔRAAN 殘差定義（皆針對同一組連續 TLE 對）：
  (a) raw       = angle_diff(prev_raan, curr_raan)                     — 完全不修正
  (b) j2        = raw - j2_raan_rate_deg_per_s(prev) * dt              — 現行方法
  (c) sgp4      = angle_diff(sgp4_predicted_raan, curr_raan)           — 傳播前一筆 TLE
                  至下一筆 TLE 之 epoch，取其預測 RAAN 與下一筆 TLE 之實際 RAAN 相減

比較：三法之旗標觸發數（|殘差|>THR_DRAAN）、(b)(c) 相關係數與均方差、
0°/360° 跨越邊界之 unwrap 正確性檢查。
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd
import duckdb

import dsgp4_utils as dg
from detect_maneuvers import angle_diff, j2_raan_rate_deg_per_s, state_to_elements, THR_DRAAN

DB_PATH = r"C:\STK_Python\CCIT_Orbit_Maneuvers\GCP_Version\space_db.duckdb"
DATE_START, DATE_END = "2026-05-01", "2026-05-30"
N_SAMPLE = 300
SEED = 42

def main():
    pop = pd.read_csv("leo_annotator/output/validation_full_p1only.csv", dtype={"norad_id": str})
    pop = pop[pop["tle_status"] == "ok"]
    rng = np.random.default_rng(SEED)
    sample_ids = rng.choice(pop["norad_id"].values, size=min(N_SAMPLE, len(pop)), replace=False)
    print(f"母體 {len(pop)} 顆（E1 全量），抽樣 {len(sample_ids)} 顆（seed={SEED}）")

    con = duckdb.connect(DB_PATH, read_only=True)
    norad_sql = ", ".join(sample_ids)
    tle = con.execute(f"""
        SELECT CAST(norad_id AS VARCHAR) AS norad_id, epoch_utc, line1, line2,
               sma_km, eccentricity, inclination_deg, raan_deg
        FROM raw_tle_archive
        WHERE norad_id IN ({norad_sql})
          AND epoch_utc BETWEEN TIMESTAMP '{DATE_START}' AND TIMESTAMP '{DATE_END} 23:59:59'
        ORDER BY norad_id, epoch_utc
    """).df()
    con.close()
    tle["epoch_utc"] = pd.to_datetime(tle["epoch_utc"])
    print(f"查得 {len(tle)} 筆 TLE，涵蓋 {tle['norad_id'].nunique()} 顆衛星有資料")

    rows = []
    n_sgp4_fail = 0
    for nid, g in tle.groupby("norad_id"):
        g = g.sort_values("epoch_utc").reset_index(drop=True)
        for i in range(1, len(g)):
            prev, curr = g.iloc[i - 1], g.iloc[i]
            dt_s = (curr["epoch_utc"] - prev["epoch_utc"]).total_seconds()
            if dt_s <= 0 or dt_s > 86400 * 7:
                continue

            raw = angle_diff(prev["raan_deg"], curr["raan_deg"])
            j2_rate = j2_raan_rate_deg_per_s(prev["sma_km"], prev["eccentricity"], prev["inclination_deg"])
            res_j2 = raw - j2_rate * dt_s

            try:
                r, v = dg.propagate_rv_utc(prev["line1"], prev["line2"], curr["epoch_utc"].to_pydatetime())
                elems = state_to_elements(*r, *v)
                res_sgp4 = angle_diff(elems["raan"], curr["raan_deg"])
            except Exception:
                n_sgp4_fail += 1
                continue

            rows.append(dict(
                norad_id=nid, dt_h=dt_s / 3600.0,
                raan_raw=raw, raan_j2=res_j2, raan_sgp4=res_sgp4,
                flag_raw=abs(raw) > THR_DRAAN,
                flag_j2=abs(res_j2) > THR_DRAAN,
                flag_sgp4=abs(res_sgp4) > THR_DRAAN,
            ))

    df = pd.DataFrame(rows)
    df.to_csv("data/benchmark/j2_sensitivity_transitions_20260918.csv", index=False)
    print(f"\n共 {len(df)} 筆有效轉換（SGP4 傳播失敗跳過 {n_sgp4_fail} 筆）")

    n = len(df)
    print("\n=== 三法觸發旗標數（同一組轉換） ===")
    print(f"  raw（不修正）  : {int(df['flag_raw'].sum())} / {n}  ({df['flag_raw'].mean()*100:.2f}%)")
    print(f"  J2 解析式修正  : {int(df['flag_j2'].sum())} / {n}  ({df['flag_j2'].mean()*100:.2f}%)")
    print(f"  SGP4 傳播殘差  : {int(df['flag_sgp4'].sum())} / {n}  ({df['flag_sgp4'].mean()*100:.2f}%)")

    from scipy import stats
    rho, p = stats.pearsonr(df["raan_j2"], df["raan_sgp4"])
    rmse = float(np.sqrt(np.mean((df["raan_j2"] - df["raan_sgp4"]) ** 2)))
    print(f"\nJ2 vs SGP4 殘差相關係數: r={rho:.4f} (p={p:.2e})，RMSE={rmse:.4f} deg")
    print(f"J2 殘差標準差: {df['raan_j2'].std():.4f} deg | SGP4 殘差標準差: {df['raan_sgp4'].std():.4f} deg")

    agree_j2_sgp4 = (df["flag_j2"] == df["flag_sgp4"]).mean()
    both_flag = (df["flag_j2"] & df["flag_sgp4"]).sum()
    only_j2   = (df["flag_j2"] & ~df["flag_sgp4"]).sum()
    only_sgp4 = (~df["flag_j2"] & df["flag_sgp4"]).sum()
    print(f"\nJ2 與 SGP4 旗標一致率: {agree_j2_sgp4*100:.2f}%  "
          f"（兩者皆觸發 {both_flag}，僅 J2 觸發 {only_j2}，僅 SGP4 觸發 {only_sgp4}）")

    # 0/360 unwrap 邊界檢查：raan_deg 接近 0 或 360 附近的轉換
    near_wrap = tle_near_wrap_check(tle)
    print(f"\nRAAN 接近 0°/360° 邊界（<2° 或 >358°）之 TLE 筆數: {near_wrap}")

    print(f"\nsaved -> data/benchmark/j2_sensitivity_transitions_20260918.csv")


def tle_near_wrap_check(tle: pd.DataFrame) -> int:
    return int(((tle["raan_deg"] < 2.0) | (tle["raan_deg"] > 358.0)).sum())


if __name__ == "__main__":
    main()
