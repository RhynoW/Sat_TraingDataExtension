#!/usr/bin/env python3
"""phase_residual_storm_lag_analysis.py — 驗證 2026-04-18 磁暴是否也對 Starlink
產生相位殘差候選異常，並比較觸發時間與軌道傾角族群（可作為緯度暴露程度之
代理）的關係。無獨立機動真值，屬描述性／相關性分析，非準確度驗證。

背景：docs/相位殘差通道_新增偵測管道實作與驗證_20260913.md §十三 已發現
FS7/COSMIC-2 7 顆衛星於磁暴期間同步觸發候選異常，並與
F:\\GitHub\\SpaceWeather 之 OMNI2/CelesTrak 資料確認同期確有一次中度地磁暴
（Dst -95nT, 04-18 00:00~08:00 UTC 主降相）。
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

import maneuver_report_builder as rb

N_PER_FAMILY = 40
SEED = 42
STORM_ONSET = pd.Timestamp("2026-04-17 18:00:00", tz="UTC")  # 鞘區密度開始增強（近似）
STORM_DST_MIN = pd.Timestamp("2026-04-18 07:30:00", tz="UTC")  # Dst主降相最低點（近似）

con = duckdb.connect("space_db.duckdb", read_only=True)
q = """
WITH latest AS (
  SELECT norad_id, object_name, sma_km, inclination_deg,
         ROW_NUMBER() OVER (PARTITION BY norad_id ORDER BY epoch_utc DESC) rn
  FROM raw_tle_archive
  WHERE object_name ILIKE '%STARLINK%' AND sma_km IS NOT NULL AND inclination_deg IS NOT NULL
)
SELECT norad_id, object_name, sma_km, inclination_deg FROM latest WHERE rn=1
"""
pool = con.execute(q).fetchdf()
con.close()
pool["inc_bucket"] = pool["inclination_deg"].round(0).astype(int)

rng = np.random.default_rng(SEED)
sampled = []
for bucket in (43, 53, 70, 97):
    sub = pool[pool["inc_bucket"] == bucket]
    n = min(N_PER_FAMILY, len(sub))
    idx = rng.choice(sub.index.to_numpy(), size=n, replace=False)
    sampled.append(sub.loc[idx])
sample = pd.concat(sampled, ignore_index=True)
print(f"抽樣總數: {len(sample)}（傾角族群 43/53/70/97 各至多 {N_PER_FAMILY} 顆，seed={SEED}）", flush=True)
print(sample["inc_bucket"].value_counts().sort_index().to_string(), flush=True)

d0 = dt.date(2026, 4, 5)
d1 = dt.date(2026, 4, 28)
storm_lo = pd.Timestamp("2026-04-15", tz="UTC")
storm_hi = pd.Timestamp("2026-04-21", tz="UTC")

rows = []
n_done = 0
for _, r in sample.iterrows():
    n_done += 1
    if n_done % 40 == 0:
        print(f"  進度 {n_done}/{len(sample)}", flush=True)
    nid = int(r["norad_id"])
    try:
        tle = rb.load_tle(nid, start=d0, end=d1)
    except Exception:
        continue
    if len(tle) < 10:
        continue
    pr = rb.compute_phase_residual_experimental(tle)
    if pr["status"] != "ok":
        continue
    storm_flags = [e for e in pr["flagged_epochs"] if storm_lo <= e <= storm_hi]
    rows.append(dict(
        norad_id=nid, object_name=r["object_name"], inc_bucket=r["inc_bucket"],
        sma_km=r["sma_km"], n_tle=len(tle), n_flags_total=pr["n_flags"],
        n_flags_in_storm_window=len(storm_flags),
        first_storm_flag=min(storm_flags) if storm_flags else pd.NaT,
    ))

res = pd.DataFrame(rows)
res["lag_h_vs_onset"] = (res["first_storm_flag"] - STORM_ONSET).dt.total_seconds() / 3600.0
res["lag_h_vs_dstmin"] = (res["first_storm_flag"] - STORM_DST_MIN).dt.total_seconds() / 3600.0
res.to_csv("data/benchmark/phase_residual_storm_lag_starlink_20260918.csv", index=False)

print("\n=== Starlink 磁暴窗口內候選觸發統計（無真值，描述性）===", flush=True)
print(f"總樣本: {len(res)}", flush=True)
hit = res[res["n_flags_in_storm_window"] > 0]
print(f"磁暴窗口內（04-15~04-21）至少 1 次候選: {len(hit)}/{len(res)} "
      f"（{len(hit)/len(res)*100:.1f}%）", flush=True)
print("\n依傾角族群分層：", flush=True)
summary = res.groupby("inc_bucket").agg(
    n_sat=("norad_id", "size"),
    n_hit=("n_flags_in_storm_window", lambda s: int((s > 0).sum())),
    hit_rate=("n_flags_in_storm_window", lambda s: float((s > 0).mean())),
    mean_lag_vs_onset_h=("lag_h_vs_onset", "mean"),
    median_lag_vs_onset_h=("lag_h_vs_onset", "median"),
)
print(summary.to_string(), flush=True)
if len(hit) >= 3:
    from scipy import stats
    corr = stats.spearmanr(hit["inc_bucket"], hit["lag_h_vs_onset"])
    print(f"\nSpearman 相關（傾角 vs 距磁暴起始之延遲時數）: rho={corr.statistic:.3f}, p={corr.pvalue:.3f}", flush=True)
print("\nsaved -> data/benchmark/phase_residual_storm_lag_starlink_20260918.csv", flush=True)
