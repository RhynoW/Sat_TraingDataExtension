#!/usr/bin/env python3
"""
validate_heo_drag_residual.py — 量化「NRLMSIS 阻力殘差模型在 HEO 非末期再入段不適用」這件事。

背景：StoryMap 案例十二⑥目前只用文字定性宣稱「HEO 遠地點階段以第三體攝動為主、非大氣阻力，
硬套阻力模型會得出不合理結果」，沒有實際數字佐證。本腳本直接對真實 HEO 衛星（Cluster II、
Van Allen Probes）跑 `atmospheric_drag.drag_residual()`，並與已知在 LEO 圓軌上驗證良好的
`drag_resid_da` 雜訊地板（案例十二②：<0.2km 視為正常）比較量級，把「不適用」變成有數字的「差了幾倍」。

方法：
  - 只用「非末期再入段」：以近地點高度 > PERIGEE_FLOOR_KM 為界，排除末期俯衝再入的那一段
    （避免把 is_reentry_decay() 本來就該抓到的劇烈非線性衰減，誤算成「阻力模型的一般失效量級」）。
  - 對比組：ISS（LEO 圓軌、站台保持）在同一函式下的殘差量級，作為「模型設計目標範圍」的參照。

用法：
  python validate_heo_drag_residual.py
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from atmospheric_drag import drag_residual, load_space_weather

DB_PATH = "space_db.duckdb"
OUT_CSV = "data/benchmark/heo_drag_residual_validation_20260910.csv"
PERIGEE_FLOOR_KM = 1000.0   # 近地點高於此視為「正常運行段」，排除末期俯衝再入

# (norad_id, 名稱, 軌道類型) — HEO 案例取尚未進入末期俯衝、或已排除俯衝段之正常運行歷史；
# LEO 對照組取站台保持衛星（模型原始設計目標）。
CASES = [
    (26464, "CLUSTER II-FM8", "HEO"),
    (26410, "CLUSTER II-FM7", "HEO"),
    (25544, "ISS (ZARYA)", "LEO 對照組"),
]
# 註：Van Allen A/B（38752/38753）在本地封存的 TLE 歷史窗內，近地點全程已 <250km，
# 代表這兩份封存資料本身就落在末期俯衝階段，找不到「非末期正常運行段」可用，故不納入本表。


def eval_case(con, norad: int, name: str, kind: str) -> dict | None:
    df = con.execute(
        "SELECT epoch_utc AS epoch, sma_km, eccentricity, line1, line2 "
        "FROM raw_tle_archive WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc",
        [int(norad)]).fetchdf()
    if len(df) < 10:
        return None
    df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
    e = df["eccentricity"].to_numpy(float)
    rp_alt = df["sma_km"].to_numpy(float) * (1 - e) - 6378.137
    if kind == "HEO":
        df = df[rp_alt > PERIGEE_FLOOR_KM].reset_index(drop=True)
    if len(df) < 10:
        return None
    sw = load_space_weather()
    resid = drag_residual(df, sw)
    if resid.empty:
        return None
    r = resid["drag_resid_da"].to_numpy(float)
    return {
        "norad_id": norad, "name": name, "kind": kind, "n_epochs_used": len(df),
        "resid_median_abs_km": float(np.median(np.abs(r))),
        "resid_std_km": float(np.std(r)),
        "resid_p95_abs_km": float(np.percentile(np.abs(r), 95)),
        "resid_max_abs_km": float(np.max(np.abs(r))),
    }


def main() -> None:
    con = duckdb.connect(DB_PATH, read_only=True)
    rows = [eval_case(con, nid, name, kind) for nid, name, kind in CASES]
    con.close()
    r = pd.DataFrame([x for x in rows if x is not None])
    r.to_csv(OUT_CSV, index=False)

    print(r.to_string(index=False))
    leo = r[r["kind"] == "LEO 對照組"]
    heo = r[r["kind"] == "HEO"]
    if not leo.empty and not heo.empty:
        leo_med = leo["resid_median_abs_km"].iloc[0]
        ratio = heo["resid_median_abs_km"] / leo_med
        print(f"\nLEO 對照組（ISS）殘差中位數 = {leo_med:.4f} km")
        for _, row in heo.iterrows():
            print(f"  {row['name']}: 殘差中位數 = {row['resid_median_abs_km']:.3f} km "
                  f"（約 ISS 的 {row['resid_median_abs_km']/leo_med:.0f} 倍）")
    print(f"\n輸出 → {OUT_CSV}")


if __name__ == "__main__":
    main()
