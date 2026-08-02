#!/usr/bin/env python3
"""
add_stat_features.py
====================
把統計偵測層的逐 epoch 統計量（cusum_stat / bocpd_cp_prob / ssa_resid_z）
以 as-of 方式（每顆衛星取 center_epoch 之前最近的 TLE 統計）併入 Plan A 訓練列，
寫回 training_dataset_final.parquet。冪等：重跑會覆寫這三欄。

依據：Phase 2（statistical_detectors 三統計量作為 ML 特徵）。
"""
from __future__ import annotations

import glob
import sys

import pandas as pd

STAT = ["cusum_stat", "bocpd_cp_prob", "ssa_resid_z"]
PARQUET = "data/maneuvers/training_dataset_final.parquet"


def main() -> None:
    stat_glob = sorted(glob.glob("data/statistical_layer/per_epoch_stats_*.csv"))
    if not stat_glob:
        print("找不到 per_epoch_stats_*.csv，請先跑 run_statistical_layer.py")
        sys.exit(1)

    df = pd.read_parquet(PARQUET)
    st = pd.read_csv(stat_glob[-1])
    st["epoch_utc"] = pd.to_datetime(st["epoch_utc"], utc=True, format="ISO8601")
    st = st.sort_values("epoch_utc")

    # 先移除舊的三欄（冪等）
    df = df.drop(columns=[c for c in STAT if c in df.columns])

    is_a = df["plan"] == "A"
    a = df[is_a].copy()
    a["_ce"] = pd.to_datetime(a["center_epoch"], utc=True, format="ISO8601")
    a = a.sort_values("_ce")

    merged = pd.merge_asof(
        a, st[["sat_name", "epoch_utc"] + STAT], by="sat_name",
        left_on="_ce", right_on="epoch_utc", direction="backward",
    ).drop(columns=["_ce", "epoch_utc"])

    # 併回（Plan B 這三欄為 NaN）
    out = pd.concat([merged, df[~is_a]], ignore_index=True, sort=False)
    out.to_parquet(PARQUET, index=False)

    cov = {c: int(merged[c].notna().sum()) for c in STAT}
    print(f"併入完成 → {PARQUET}")
    print(f"  Plan A rows={len(merged)}  三統計量非空覆蓋={cov}")
    print(f"  總列數={len(out)}  總欄數={out.shape[1]}")


if __name__ == "__main__":
    main()
