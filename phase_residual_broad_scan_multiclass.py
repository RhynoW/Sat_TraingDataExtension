#!/usr/bin/env python3
"""phase_residual_broad_scan_multiclass.py — 相位殘差通道之無真值廣泛掃描，
涵蓋 LEO/MEO/GEO/HEO 四種軌道類型（排除 Starlink，Starlink 另有 MEME 真值
驗證見 phase_residual_expanded_validation.py）。

**重要：本腳本不計算 Precision/Recall/F1**——本專案沒有 MEO/GEO/HEO 衛星之
獨立機動真值來源（MEME 精密星曆為 Starlink 專屬遙測，其他衛星無同等資料），
故僅能做候選發現式的描述性統計（候選率、殘差量級分布），不構成準確度驗證。
用法：python phase_residual_broad_scan_multiclass.py
輸出：data/benchmark/phase_residual_multiclass_scan_20260918.csv
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import datetime as dt

import duckdb
import numpy as np
import pandas as pd

import maneuver_strategies_july as ms
import maneuver_report_builder as rb

N_PER_CLASS = 125
SEED = 42
WINDOW_DAYS = 180

con = duckdb.connect("space_db.duckdb", read_only=True)
q = """
WITH latest AS (
  SELECT norad_id, object_name, sma_km, eccentricity, inclination_deg,
         ROW_NUMBER() OVER (PARTITION BY norad_id ORDER BY epoch_utc DESC) rn
  FROM raw_tle_archive
  WHERE sma_km IS NOT NULL AND eccentricity IS NOT NULL
    AND object_name NOT LIKE 'STARLINK%'
)
SELECT norad_id, object_name, sma_km, eccentricity, inclination_deg FROM latest WHERE rn=1
"""
pool = con.execute(q).fetchdf()
con.close()
pool["orbit_class"] = pool.apply(
    lambda r: ms.classify_orbit(float(r["sma_km"]), float(r["eccentricity"])), axis=1)
pool.loc[pool["orbit_class"] == "GEO+", "orbit_class"] = "GEO"

rng = np.random.default_rng(SEED)
sampled = []
for cls in ("LEO", "MEO", "GEO", "HEO"):
    sub = pool[pool["orbit_class"] == cls]
    n = min(N_PER_CLASS, len(sub))
    idx = rng.choice(sub.index.to_numpy(), size=n, replace=False)
    sampled.append(sub.loc[idx])
sample = pd.concat(sampled, ignore_index=True)
print(f"抽樣總數: {len(sample)}（LEO/MEO/GEO/HEO 各至多 {N_PER_CLASS} 顆，"
      f"seed={SEED}，排除 Starlink）", flush=True)
print(sample["orbit_class"].value_counts().to_string(), flush=True)

d1 = dt.date(2026, 9, 17)
d0 = d1 - dt.timedelta(days=WINDOW_DAYS)

rows = []
n_done = 0
for _, r in sample.iterrows():
    n_done += 1
    if n_done % 50 == 0:
        print(f"  進度 {n_done}/{len(sample)}", flush=True)
    nid = int(r["norad_id"])
    try:
        tle = rb.load_tle(nid, start=d0, end=d1)
    except Exception:
        continue
    if len(tle) < 10:
        continue
    pr = rb.compute_phase_residual_experimental(tle)
    rows.append(dict(norad_id=nid, object_name=r["object_name"], orbit_class=r["orbit_class"],
                     n_tle=len(tle), status=pr["status"], n_flags=pr["n_flags"],
                     max_abs_residual_km=pr["max_abs_residual_km"]))

res = pd.DataFrame(rows)
res.to_csv("data/benchmark/phase_residual_multiclass_scan_20260918.csv", index=False)

print("\n=== 無真值廣泛掃描結果（描述性統計，非準確度驗證）===", flush=True)
ok = res[res["status"] == "ok"]
print(f"有效計算: {len(ok)}/{len(res)} 顆（其餘因 TLE 不足或缺欄位跳過）", flush=True)
summary = ok.groupby("orbit_class").agg(
    n_sat=("norad_id", "size"),
    n_with_flag=("n_flags", lambda s: int((s > 0).sum())),
    flag_rate=("n_flags", lambda s: float((s > 0).mean())),
    mean_n_flags=("n_flags", "mean"),
    median_max_resid_km=("max_abs_residual_km", "median"),
)
print(summary.to_string(), flush=True)
print("\nsaved -> data/benchmark/phase_residual_multiclass_scan_20260918.csv", flush=True)
