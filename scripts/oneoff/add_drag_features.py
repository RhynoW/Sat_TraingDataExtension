#!/usr/bin/env python3
"""
add_drag_features.py — 把 NRLMSIS 阻力殘差特徵 as-of 併入 Plan A 訓練列，寫回 parquet。
冪等：重跑覆寫這兩欄。依賴 run_drag_residual.py 的輸出。
"""
from __future__ import annotations

import glob
import sys

import pandas as pd

DRAG = ["drag_resid_da", "drag_resid_absmax_7d"]
PARQUET = "data/maneuvers/training_dataset_final.parquet"


def main() -> None:
    g = sorted(glob.glob("data/drag/drag_resid_*.csv"))
    if not g:
        print("找不到 drag_resid_*.csv，請先跑 run_drag_residual.py"); sys.exit(1)

    df = pd.read_parquet(PARQUET)
    st = pd.read_csv(g[-1])
    st["epoch_utc"] = pd.to_datetime(st["epoch_utc"], utc=True, format="ISO8601")
    st = st.sort_values("epoch_utc")

    df = df.drop(columns=[c for c in DRAG if c in df.columns])
    is_a = df["plan"] == "A"
    a = df[is_a].copy()
    a["_ce"] = pd.to_datetime(a["center_epoch"], utc=True, format="ISO8601")
    a = a.sort_values("_ce")

    merged = pd.merge_asof(
        a, st[["sat_name", "epoch_utc"] + DRAG], by="sat_name",
        left_on="_ce", right_on="epoch_utc", direction="backward",
    ).drop(columns=["_ce", "epoch_utc"])

    out = pd.concat([merged, df[~is_a]], ignore_index=True, sort=False)
    out.to_parquet(PARQUET, index=False)
    cov = {c: int(merged[c].notna().sum()) for c in DRAG}
    print(f"併入完成 → {PARQUET}")
    print(f"  Plan A rows={len(merged)}  drag 非空={cov}  總欄數={out.shape[1]}")


if __name__ == "__main__":
    main()
