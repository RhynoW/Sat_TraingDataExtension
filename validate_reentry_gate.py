#!/usr/bin/env python3
"""
validate_reentry_gate.py — 擴大樣本驗證 atmospheric_drag.is_reentry_decay() 的再入判定準確度。

背景：`is_reentry_decay()` 原本只用 4 個手選案例（FORMOSAT-3A、機動 Starlink、ISS、Van Allen A）
做邏輯正確性檢查，樣本太小，只能算「煙霧測試」而非統計驗證（見 StoryMap 案例十二）。

方法：不依賴外部真值標籤，直接用 TLE 本身的物理事實建立客觀真值——
  - **真陽性（確認再入）**：近地點高度曾跌破 120km、且此後 >14 天再無任何 TLE
    （追蹤徹底中止 = 已燒毀）。
  - **真陰性（確認安靜）**：ISS、天宮核心艙，加上隨機抽樣的長期追蹤 Starlink
    （近地點全程 >300km，靠站位保持維持）。
對每顆衛星的完整 TLE 歷史跑 `is_reentry_decay()`，統計 recall／specificity。

用法：
  python validate_reentry_gate.py
"""
from __future__ import annotations

import math

import duckdb
import pandas as pd

from atmospheric_drag import is_reentry_decay

DB_PATH = "space_db.duckdb"
OUT_CSV = "data/benchmark/reentry_gate_validation_20260910.csv"

# 確認再入：近地點<120km、此後 >14 天無 TLE（tracking 徹底中止）。
# 排除 NORAD 68538（單筆 TLE 擬合異常，-5750km「近地點」為資料瑕疵非物理事實）。
CONFIRMED_REENTRIES = [
    (26411, "CLUSTER II-FM6"), (38752, "RBSP A / Van Allen A"), (62805, "unnamed"),
    (40750, "unnamed"), (39266, "CUSAT 1"), (64543, "W-SERIES 4"), (66143, "CZ-5 R/B"),
    (59347, "FALCON 9 R/B"), (67247, "CZ-3B R/B"), (59707, "CZ-3B R/B"), (37398, "MERIDIAN 4"),
    (66310, "LVM3 R/B"), (20965, "USA 67 R/B(2)"), (69571, "CZ-3B R/B"), (26410, "CLUSTER II-FM7"),
    (37399, "SL-26 R/B"),
]


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z ** 2 / n
    center = p + z ** 2 / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2))
    return (center - half) / denom, (center + half) / denom


def eval_case(con, norad: int, name: str, expected: bool) -> dict | None:
    df = con.execute(
        "SELECT epoch_utc AS epoch, sma_km, eccentricity, line1, line2 "
        "FROM raw_tle_archive WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc",
        [int(norad)]).fetchdf()
    if len(df) < 5:
        return None
    df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
    pred = is_reentry_decay(df)
    return {"norad_id": norad, "name": name, "n": len(df), "expected": expected,
            "predicted": pred, "correct": pred == expected}


def main() -> None:
    con = duckdb.connect(DB_PATH, read_only=True)

    quiet_ids = [(25544, "ISS (ZARYA)"), (48274, "TIANHE / Tiangong core")]
    sample = con.execute("""
        SELECT norad_id, ANY_VALUE(object_name) sat_name
        FROM raw_tle_archive
        WHERE UPPER(object_name) LIKE '%STARLINK%' AND sma_km IS NOT NULL AND eccentricity IS NOT NULL
        GROUP BY norad_id
        HAVING COUNT(*) >= 30 AND MIN(sma_km*(1-eccentricity)-6378.137) > 300
        ORDER BY RANDOM() LIMIT 40
    """).fetchdf()
    quiet_ids += list(zip(sample["norad_id"], sample["sat_name"]))

    rows = [eval_case(con, nid, name, True) for nid, name in CONFIRMED_REENTRIES]
    rows += [eval_case(con, nid, name, False) for nid, name in quiet_ids]
    con.close()

    r = pd.DataFrame([x for x in rows if x is not None])
    r.to_csv(OUT_CSV, index=False)

    n_re, n_qt = (r.expected).sum(), (~r.expected).sum()
    tp = ((r.expected) & (r.predicted)).sum()
    tn = ((~r.expected) & (~r.predicted)).sum()
    fp, fn = n_qt - tn, n_re - tp
    rec_lo, rec_hi = wilson_ci(tp, n_re)
    spec_lo, spec_hi = wilson_ci(tn, n_qt)

    print(f"評估總數：{len(r)}（確認再入 {n_re} 顆／確認安靜 {n_qt} 顆）")
    print(f"再入 recall = {tp}/{n_re} = {tp/n_re:.3f}  Wilson 95% CI [{rec_lo:.3f}, {rec_hi:.3f}]")
    print(f"安靜 specificity = {tn}/{n_qt} = {tn/n_qt:.3f}  Wilson 95% CI [{spec_lo:.3f}, {spec_hi:.3f}]")
    print(f"FN={fn}  FP={fp}")
    if (~r.correct).any():
        print("\n誤判案例：")
        print(r[~r.correct].to_string(index=False))
    print(f"\n輸出 → {OUT_CSV}")


if __name__ == "__main__":
    main()
