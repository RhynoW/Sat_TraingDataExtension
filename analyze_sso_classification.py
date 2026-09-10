#!/usr/bin/env python3
"""
analyze_sso_classification.py — 太陽同步軌道（SSO）缺口的嚴謹改進方案。

背景：StoryMap 案例十二「尚待測試的缺口」原本只能誠實列出「從未把太陽同步單獨設為一條
測試分層」，因為①用傾角當 SSO 判準只是代理指標、不夠嚴謹（高傾角不等於嚴格太陽同步），
②怕重新收集資料曠日費時。

改進：不需要新收案例——本專案既有的兩批已驗證資料裡本來就藏著太陽同步軌道樣本：
  1. **嚴謹分類**：直接對真實 TLE 的 RAAN（升交點赤經）時序做線性回歸，算出真實的
     節線進動速率（deg/day），跟太陽同步軌道的理論目標值 360°/365.2422 ≈ 0.9856°/day 比較——
     這是比「傾角是否接近 96-99°」更嚴謹的判準（例：CryoSat-2 傾角 92° 看似像 SSO，
     但實際進動速率只有 0.24°/day，明確不是 SSO；而 SARAL 傾角 98.5°、進動速率 0.985°/day，
     幾乎完美吻合，是嚴格 SSO）。
  2. **重用既有結果**：技術報告 `docs/report_tasa_ilrs_benchmark.md` 之「23星逐星總表」
     （`tasa23_l3_stack_q23_20260804.csv`，L3 融合模型、LOSO 交叉驗證）已經對案例四的
     23 顆外部真值衛星逐一算出召回率——只是從未依 SSO/非SSO 分類重新切一刀來看。
     本腳本把①的嚴謹分類套用到②的既有結果上，直接算出兩組的召回率對照，不需要任何新訓練或新真值。

用法：
  python analyze_sso_classification.py
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

DB_PATH = "space_db.duckdb"
L3_RESULTS_CSV = "data/benchmark/tasa23_l3_stack_q23_20260804.csv"
OUT_CSV = "data/benchmark/sso_classification_validation_20260910.csv"

SOLAR_RATE_DEG_DAY = 360.0 / 365.2422   # 太陽同步軌道之理論節線進動目標值 ≈ 0.9856°/day
SSO_TOLERANCE = 0.05                     # 判定為「嚴格太陽同步」之容許誤差（deg/day）

# 案例四 23 顆外部真值衛星（名稱依 raw_tle_archive 實際命名）
BENCHMARK_23 = [
    (36508, "CRYOSAT 2"), (43437, "SENTINEL 3B"), (41335, "SENTINEL 3A"),
    (66514, "SENTINEL-6B"), (54754, "SWOT"), (33105, "JASON 2"), (41240, "JASON 3"),
    (48621, "HAIYANG 2D"), (46469, "HAIYANG 2C"), (27421, "SPOT 5"), (43476, "GRACE-FO 1"),
    (20436, "SPOT 2"), (46984, "SENTINEL-6A"), (39086, "SARAL"), (25260, "SPOT 4"),
    (22823, "SPOT 3"), (43477, "GRACE-FO 2"), (27391, "GRACE 1"), (26997, "JASON"),
    (27386, "ENVISAT"), (22076, "TOPEX/POSEIDON"), (37781, "HAIYANG 2A"), (27392, "GRACE 2"),
]


def raan_precession_rate(con, norad: int) -> tuple[float, float, int] | None:
    """回傳 (真實節線進動速率 deg/day, 平均傾角, 樣本數)；樣本不足回傳 None。"""
    df = con.execute(
        "SELECT epoch_utc, inclination_deg, raan_deg FROM raw_tle_archive "
        "WHERE norad_id=? AND raan_deg IS NOT NULL ORDER BY epoch_utc", [int(norad)]).fetchdf()
    if len(df) < 20:
        return None
    t = pd.to_datetime(df["epoch_utc"], utc=True)
    days = (t - t.iloc[0]).dt.total_seconds().to_numpy() / 86400.0
    raan_unwrapped = np.degrees(np.unwrap(np.radians(df["raan_deg"].to_numpy(float))))
    slope, _ = np.polyfit(days, raan_unwrapped, 1)
    return float(slope), float(df["inclination_deg"].mean()), len(df)


def main() -> None:
    con = duckdb.connect(DB_PATH, read_only=True)
    rows = []
    for nid, name in BENCHMARK_23:
        r = raan_precession_rate(con, nid)
        if r is None:
            print(f"NORAD {nid} ({name})：樣本不足，略過")
            continue
        rate, inc, n = r
        is_sso = abs(rate - SOLAR_RATE_DEG_DAY) < SSO_TOLERANCE
        rows.append({"norad_id": nid, "name": name, "n_tle": n, "inc_mean_deg": round(inc, 2),
                     "raan_rate_deg_day": round(rate, 4),
                     "diff_from_solar_rate": round(rate - SOLAR_RATE_DEG_DAY, 4),
                     "is_sso": is_sso})
    con.close()
    cls = pd.DataFrame(rows)

    l3 = pd.read_csv(L3_RESULTS_CSV)[["norad", "n_ev", "tp", "fn", "recall"]].rename(columns={"norad": "norad_id"})
    merged = cls.merge(l3, on="norad_id", how="left")
    merged.to_csv(OUT_CSV, index=False)

    print(merged.sort_values("raan_rate_deg_day", ascending=False).to_string(index=False))

    sso = merged[merged["is_sso"]]
    non_sso = merged[~merged["is_sso"]]
    print(f"\n嚴格 SSO（|進動速率-{SOLAR_RATE_DEG_DAY:.4f}|<{SSO_TOLERANCE}）："
          f"{len(sso)} 顆，共 {int(sso['n_ev'].sum())} 個事件，"
          f"加權召回率 = {sso['tp'].sum()/sso['n_ev'].sum():.3f}")
    print(f"非 SSO：{len(non_sso)} 顆，共 {int(non_sso['n_ev'].sum())} 個事件，"
          f"加權召回率 = {non_sso['tp'].sum()/non_sso['n_ev'].sum():.3f}")
    print(f"\n輸出 → {OUT_CSV}")


if __name__ == "__main__":
    main()
