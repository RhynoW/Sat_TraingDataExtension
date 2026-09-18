#!/usr/bin/env python3
"""phase_residual_storm_dose_response.py — 用 6 顆 COSMIC2 衛星（NORAD 44343,
44349,44350,44351,44353,44358，TLE 全歷史涵蓋 2024-01-01～），對多場強度不同
之磁暴（含原始 2026-04-18 事件）與各自的平靜對照週重新掃描相位殘差通道，
檢驗「候選觸發是否隨磁暴強度呈劑量效應」。

無獨立機動真值，樣本量小（每場磁暴僅 6 顆衛星），統計檢定力有限；
本腳本之目的是初步描述性檢驗，不宣稱最終結論。
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import datetime as dt

import pandas as pd
import numpy as np

import maneuver_report_builder as rb

COSMIC2 = [44349, 44351, 44343, 44350, 44358, 44353]

# (storm_name, storm_center_date, storm_window_start, storm_window_end,
#  calm_window_start, calm_window_end, max_kp, min_dst)
# 磁暴中心日與強度取自 _omni_daily_2024_2026.csv（OMNI2 實測，非估計）；
# 平靜對照週為鄰近（±2~5週）、經同一份逐日彙整表確認 |Dst|<20 且 Kp<3 之
# 7 天區間。
STORMS = [
    # (名稱, 磁暴週start, 磁暴週end, 平靜對照週start, 平靜對照週end, 磁暴期maxKp, 磁暴期minDst)
    # 平靜對照週經 _omni_daily_2024_2026.csv 逐日 OMNI2 實測資料程式化搜尋，
    # 選同一顆衛星附近 ±60 天內 max(Kp) 最小之 7 天窗口（非手動猜測）。
    ("2024-05-11 Gannon(G5)", "2024-05-08", "2024-05-14", "2024-07-01", "2024-07-07", 9.00, -406.0),
    ("2024-10-11(G4)",        "2024-10-08", "2024-10-14", "2024-11-16", "2024-11-22", 8.70, -333.0),
    ("2025-01-01(G3)",        "2024-12-29", "2025-01-04", "2024-11-17", "2024-11-23", 8.00, -212.0),
    ("2026-01-20(G3)",        "2026-01-17", "2026-01-23", "2026-02-25", "2026-03-03", 8.70, -236.0),
    ("2025-04-16(G3)",        "2025-04-13", "2025-04-19", "2025-05-19", "2025-05-25", 7.70, -138.0),
    ("2026-07-04(G2)",        "2026-07-01", "2026-07-07", "2026-09-02", "2026-09-08", 7.33, -150.0),
    ("2026-04-18(G1-2,原案例)", "2026-04-15", "2026-04-21", "2026-06-17", "2026-06-23", 5.33, -95.0),
]

rows = []
for name, s0, s1, c0, c1, max_kp, min_dst in STORMS:
    s0d, s1d = dt.date.fromisoformat(s0), dt.date.fromisoformat(s1)
    c0d, c1d = dt.date.fromisoformat(c0), dt.date.fromisoformat(c1)
    s_lo, s_hi = pd.Timestamp(s0, tz="UTC"), pd.Timestamp(s1, tz="UTC")
    c_lo, c_hi = pd.Timestamp(c0, tz="UTC"), pd.Timestamp(c1, tz="UTC")

    storm_hits, calm_hits = 0, 0
    n_valid = 0
    for nid in COSMIC2:
        try:
            tle_s = rb.load_tle(nid, start=s0d - dt.timedelta(days=10), end=s1d + dt.timedelta(days=3))
            tle_c = rb.load_tle(nid, start=c0d - dt.timedelta(days=10), end=c1d + dt.timedelta(days=3))
        except Exception as e:
            print(f"  [skip {name} nid={nid}] {e}", flush=True)
            continue
        if len(tle_s) < 10 or len(tle_c) < 10:
            print(f"  [skip {name} nid={nid}] insufficient TLE (s={len(tle_s)}, c={len(tle_c)})", flush=True)
            continue
        n_valid += 1
        pr_s = rb.compute_phase_residual_experimental(tle_s)
        pr_c = rb.compute_phase_residual_experimental(tle_c)
        if pr_s["status"] == "ok" and any(s_lo <= e <= s_hi for e in pr_s["flagged_epochs"]):
            storm_hits += 1
        if pr_c["status"] == "ok" and any(c_lo <= e <= c_hi for e in pr_c["flagged_epochs"]):
            calm_hits += 1

    rows.append(dict(storm=name, max_kp=max_kp, min_dst=min_dst, n_valid_sat=n_valid,
                     storm_hits=storm_hits, calm_hits=calm_hits,
                     storm_hit_rate=storm_hits / n_valid if n_valid else np.nan,
                     calm_hit_rate=calm_hits / n_valid if n_valid else np.nan))
    print(f"{name}: n={n_valid}, storm_hits={storm_hits}/{n_valid}, calm_hits={calm_hits}/{n_valid}", flush=True)

res = pd.DataFrame(rows)
res.to_csv("data/benchmark/phase_residual_storm_dose_response_20260918.csv", index=False)
print("\n=== 全部磁暴彙總（COSMIC2 6 星，descriptive）===", flush=True)
print(res.to_string(index=False), flush=True)

valid = res.dropna(subset=["storm_hit_rate"])
if len(valid) >= 4:
    from scipy import stats
    rho_kp, p_kp = stats.spearmanr(valid["max_kp"], valid["storm_hit_rate"])
    rho_dst, p_dst = stats.spearmanr(-valid["min_dst"], valid["storm_hit_rate"])  # -Dst 越大代表磁暴越強
    print(f"\nSpearman(Kp強度, 磁暴週觸發率): rho={rho_kp:.3f}, p={p_kp:.3f}", flush=True)
    print(f"Spearman(-Dst強度, 磁暴週觸發率): rho={rho_dst:.3f}, p={p_dst:.3f}", flush=True)
print("\nsaved -> data/benchmark/phase_residual_storm_dose_response_20260918.csv", flush=True)
