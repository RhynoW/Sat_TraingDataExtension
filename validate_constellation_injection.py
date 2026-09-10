#!/usr/bin/env python3
"""
validate_constellation_injection.py — 注入式合成真值測試：非 Starlink 星系的「零異常」是真安靜還是看不到？

背景：`constellation_anomaly.py` 對 OneWeb／千帆等非 Starlink 星系做批量機動掃描，目前回報
「零異常」，但沒有真值可核對這是「真的安靜」還是「系統對非 Starlink 域本來就不敏感」
（StoryMap 案例十二⑤）。

方法：不依賴外部真值，而是把「已知真實發生過的機動量級」疊加到「真實的非 Starlink 衛星 TLE 雜訊背景」上——
  - 疊加量級：一組涵蓋小型站台保持到大型軌道調整的真實量級 [0.5, 1, 2, 3, 5, 10] km
    （2km 為 `constellation_anomaly.DA_MANEUVER_KM` 現行判定門檻，5.9km 為案例十三實測抓到的
    真實 Starlink 推力弧半長軸階躍量級，其餘為中介值，用以描出偵測門檻曲線而非單一二元結果）。
  - 疊加方式：對真實 OneWeb／千帆衛星，任選一個中段 epoch 當作機動時刻，
    其後所有 TLE 快照的 sma_km 一律加上該量級（模擬瞬時燃燒後半長軸永久位移），
    其餘欄位、其餘衛星、原始雜訊完全不動。
  - 判定：重跑 `constellation_anomaly.py` 同一套逐星 |Δa| 步階邏輯，
    檢查注入的那一步是否超過現行 2km 判定門檻（即會不會被①現有邏輯標記為顯著機動）。
  - 對多顆真實衛星重複，統計「在此量級下，多少比例的真實背景雜訊仍會被正確標記」，
    畫出量級 vs 偵測率的曲線，取代含糊的「零異常」。

用法：
  python validate_constellation_injection.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from constellation_anomaly import CONSTELLATIONS, DA_MANEUVER_KM, load_constellation

DB_PATH = "space_db.duckdb"
OUT_CSV = "data/benchmark/constellation_injection_validation_20260910.csv"
CONSTELLATIONS_TO_TEST = ["OneWeb", "Qianfan"]
INJECT_MAGNITUDES_KM = [0.5, 1.0, 2.0, 3.0, 5.0, 10.0]
N_SATS_PER_TEST = 20


def inject_and_check(df_sat: pd.DataFrame, mag_km: float) -> bool:
    """對單顆衛星的真實 TLE 序列，於中段注入一次 Δa=mag_km 的永久階躍，回傳是否被 |Δa|>門檻 抓到。"""
    d = df_sat.sort_values("epoch").reset_index(drop=True)
    if len(d) < 6:
        return False
    mid = len(d) // 2
    sma = d["sma_km"].to_numpy(float).copy()
    sma[mid:] += mag_km   # 模擬瞬時燃燒後半長軸永久位移
    da = np.diff(sma)
    return bool(np.abs(da[mid - 1]) > DA_MANEUVER_KM)


def main() -> None:
    rows = []
    for cname in CONSTELLATIONS_TO_TEST:
        pat = CONSTELLATIONS[cname]
        df = load_constellation(DB_PATH, pat, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-09-10"))
        if df.empty:
            print(f"{cname}: 無資料，略過")
            continue
        counts = df.groupby("norad_id").size()
        eligible = counts[counts >= 15].index.to_numpy()
        rng = np.random.default_rng(42)
        picked = rng.choice(eligible, size=min(N_SATS_PER_TEST, len(eligible)), replace=False)
        for mag in INJECT_MAGNITUDES_KM:
            n_detect = 0
            for nid in picked:
                sub = df[df["norad_id"] == nid][["epoch", "sma_km"]]
                if inject_and_check(sub, mag):
                    n_detect += 1
            rows.append({"constellation": cname, "n_sats_tested": len(picked),
                        "inject_mag_km": mag, "n_detected": n_detect,
                        "detect_rate": n_detect / len(picked)})
        print(f"{cname}: 測試 {len(picked)} 顆真實衛星")

    r = pd.DataFrame(rows)
    r.to_csv(OUT_CSV, index=False)
    print(r.to_string(index=False))
    print(f"\n輸出 → {OUT_CSV}")


if __name__ == "__main__":
    main()
