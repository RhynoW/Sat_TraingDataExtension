#!/usr/bin/env python3
"""phase_residual_starlink_dose_response.py — 回應 §十四 建議之後續步驟(a)：
用 Starlink 大樣本，對 COSMIC2 劑量效應檢驗中所測的磁暴，重新檢驗是否也
呈現「只對原始最弱磁暴敏感」之同一模式。

資料限制（2026-09-18 查證，執行前已誠實告知使用者）：本地 space_db.duckdb
之 Starlink TLE 為滾動窗口，目前僅涵蓋 2026-04-29～2026-09-17。§十四 所測
6 場額外磁暴中，僅 **2026-07-04（G2, Kp=7.33, Dst=-150nT）** 落在此範圍內；
其餘 5 場（2024-2025 年，含 Gannon G5）與原始 2026-04-18 事件本身，Starlink
端現皆已無 TLE 資料可查（原始 04-18 事件之 Starlink 結果見 §十三之二，
基於當時仍可查得之較舊資料，非本腳本重跑）。

沿用 §十三之一／十三之二 完全相同之 140 顆 Starlink 衛星清單
（data/benchmark/phase_residual_storm_lag_starlink_20260918.csv 之 norad_id），
確保與先前結果之衛星母體一致、可直接比較觸發率。
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import datetime as dt

import numpy as np
import pandas as pd

import maneuver_report_builder as rb

SAT_LIST_CSV = "data/benchmark/phase_residual_storm_lag_starlink_20260918.csv"

# (storm_name, storm_week_start, storm_week_end, calm_week_start, calm_week_end, max_kp, min_dst)
# 磁暴週/平靜週定義與 §十四（COSMIC2 劑量效應檢驗）完全相同，取自
# phase_residual_storm_dose_response.py 之 STORMS 清單，僅挑選目前 Starlink
# TLE 資料庫仍可查得之磁暴。
STORM = ("2026-07-04(G2)", "2026-07-01", "2026-07-07", "2026-09-02", "2026-09-08", 7.33, -150.0)


def main():
    sat_df = pd.read_csv(SAT_LIST_CSV)
    norad_ids = sat_df["norad_id"].astype(int).tolist()
    print(f"沿用 §十三之一 相同之 {len(norad_ids)} 顆 Starlink 衛星清單（{SAT_LIST_CSV}）", flush=True)

    name, s0, s1, c0, c1, max_kp, min_dst = STORM
    s0d, s1d = dt.date.fromisoformat(s0), dt.date.fromisoformat(s1)
    c0d, c1d = dt.date.fromisoformat(c0), dt.date.fromisoformat(c1)
    s_lo, s_hi = pd.Timestamp(s0, tz="UTC"), pd.Timestamp(s1, tz="UTC")
    c_lo, c_hi = pd.Timestamp(c0, tz="UTC"), pd.Timestamp(c1, tz="UTC")

    storm_hits, calm_hits, n_valid = 0, 0, 0
    n_skip = 0
    rows = []
    for i, nid in enumerate(norad_ids):
        try:
            tle_s = rb.load_tle(nid, start=s0d - dt.timedelta(days=10), end=s1d + dt.timedelta(days=3))
            tle_c = rb.load_tle(nid, start=c0d - dt.timedelta(days=10), end=c1d + dt.timedelta(days=3))
        except Exception as e:
            n_skip += 1
            continue
        if len(tle_s) < 10 or len(tle_c) < 10:
            n_skip += 1
            continue
        n_valid += 1
        pr_s = rb.compute_phase_residual_experimental(tle_s)
        pr_c = rb.compute_phase_residual_experimental(tle_c)
        hit_s = pr_s["status"] == "ok" and any(s_lo <= e <= s_hi for e in pr_s["flagged_epochs"])
        hit_c = pr_c["status"] == "ok" and any(c_lo <= e <= c_hi for e in pr_c["flagged_epochs"])
        storm_hits += int(hit_s)
        calm_hits += int(hit_c)
        rows.append(dict(norad_id=nid, storm_hit=hit_s, calm_hit=hit_c))
        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(norad_ids)}] storm_hits={storm_hits} calm_hits={calm_hits} skipped={n_skip}", flush=True)

    print(f"\n有效衛星: {n_valid}/{len(norad_ids)}（跳過 {n_skip}，無足夠 TLE）", flush=True)
    print(f"{name}: 磁暴週觸發 {storm_hits}/{n_valid} ({storm_hits/n_valid*100:.1f}%)  "
          f"平靜週觸發 {calm_hits}/{n_valid} ({calm_hits/n_valid*100:.1f}%)", flush=True)

    df = pd.DataFrame(rows)
    out_csv = "data/benchmark/phase_residual_starlink_0704_dose_response_20260918.csv"
    df.to_csv(out_csv, index=False)

    from scipy.stats import chi2_contingency
    table = [[storm_hits, n_valid - storm_hits], [calm_hits, n_valid - calm_hits]]
    chi2, p, _, _ = chi2_contingency(table)
    print(f"\n卡方檢定: chi2={chi2:.2f}, p={p:.3e}", flush=True)

    print("\n=== 對照：先前已知結果 ===", flush=True)
    print("2026-04-18(原始, Kp=5.33, Dst=-95): Starlink 磁暴週 75.0%(105/140) vs 平靜週 6.4%(9/140), p=6.9e-31", flush=True)
    print("2026-04-18(原始): COSMIC2 磁暴週 6/6 vs 平靜週 0/6", flush=True)
    print("其餘6場磁暴(含Gannon G5): COSMIC2 磁暴週 0/6 (全數)", flush=True)
    print(f"{name}: Starlink 磁暴週 {storm_hits}/{n_valid} vs 平靜週 {calm_hits}/{n_valid}, p={p:.3e}", flush=True)

    print(f"\nsaved -> {out_csv}")


if __name__ == "__main__":
    main()
