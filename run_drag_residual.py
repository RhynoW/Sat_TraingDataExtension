#!/usr/bin/env python3
"""
run_drag_residual.py — 對全部衛星算逐 epoch NRLMSIS 阻力殘差，供 ML 特徵（as-of 併入）。

輸出 data/drag/drag_resid_{date}.csv：
  norad_id, sat_name, epoch_utc, drag_resid_da, drag_resid_absmax_7d
    drag_resid_da        — 當轉換扣除大氣阻力後的 Δa 殘差（機動訊號）
    drag_resid_absmax_7d — 過去 7 天內 |drag_resid_da| 的最大值（窗口機動強度）
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from atmospheric_drag import drag_residual, load_space_weather
from compare_tle_vs_ephemeris import load_registry


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="space_db.duckdb")
    ap.add_argument("--data-root", default="data", type=Path)
    ap.add_argument("--max-sats", type=int, default=None)
    args = ap.parse_args()

    sw = load_space_weather()
    reg = load_registry(args.data_root / "url_registry.csv")
    name_to_norad = {v: k for k, v in reg["sat_name"].items()}
    sats = list(name_to_norad.items())
    if args.max_sats:
        sats = sats[: args.max_sats]

    out_dir = args.data_root / "drag"
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(args.db, read_only=True)

    rows = []
    for k, (name, nid) in enumerate(sats):
        df = con.execute(
            "SELECT epoch_utc AS epoch, sma_km, eccentricity FROM raw_tle_archive "
            "WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc", [int(nid)]).fetchdf()
        if len(df) < 5:
            continue
        df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
        r = drag_residual(df, sw)
        if r.empty:
            continue
        r = r.sort_values("epoch").set_index("epoch")
        # 7 天滾動 |殘差| 最大
        absmax = r["drag_resid_da"].abs().rolling("7D").max()
        for ep, dr, am in zip(r.index, r["drag_resid_da"].to_numpy(), absmax.to_numpy()):
            rows.append({"norad_id": int(nid), "sat_name": name,
                         "epoch_utc": pd.Timestamp(ep).isoformat(),
                         "drag_resid_da": round(float(dr), 5),
                         "drag_resid_absmax_7d": round(float(am), 5)})
        if (k + 1) % 50 == 0:
            print(f"  ...{k+1}/{len(sats)} 顆", flush=True)
    con.close()

    if not rows:
        print("無輸出"); sys.exit(1)
    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    out = pd.DataFrame(rows)
    path = out_dir / f"drag_resid_{date_tag}.csv"
    out.to_csv(path, index=False, encoding="utf-8-sig")
    from satdet import record
    record("drag_residual", params={"max_sats": args.max_sats},
           outputs={"drag_resid": path})
    print(f"完成 → {path}  ({len(out)} 列 / {out['sat_name'].nunique()} 顆)")
    print(f"  drag_resid_absmax_7d 分布: {out['drag_resid_absmax_7d'].describe()[['50%','max']].round(3).to_dict()}")


if __name__ == "__main__":
    main()
