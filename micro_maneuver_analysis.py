#!/usr/bin/env python3
"""
micro_maneuver_analysis.py — 微型機動偵測可行性分析（契約 M4）
=============================================================
以合成注入驗證（synthetic_injection_test.py）得到的 Δa 偵測下限為基礎，換算為 ΔV 下限，
並對比 TLE 星曆 vs MEME 精密星曆的偵測能力，回答「多小的機動仍可偵測」。

物理換算（近圓軌道、沿軌脈衝）：
  Δa ≈ (2/n)·Δv  →  Δv ≈ Δa·n/2，  n = √(μ/a³)（平均運動, rad/s）

結論用於：解釋表 8 情境② small recall 未達標；界定需 MEME 才可偵測的微型機動範圍。
用法：python micro_maneuver_analysis.py
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

MU = 398_600.4418
ALT_A = {"LEO_low(<450)": 6778.0, "LEO(450-700)": 6928.0, "LEO_high(>700)": 7178.0}
MEME_POS_SIGMA_M = 5.0      # MEME 位置精度 ~公尺級（取 5 m）
TLE_SNR_FLOOR = 4.0         # 注入驗證所得：偵測需 SNR≈4–6.7；取保守 4×


def dv_from_da(da_km: float, a_km: float) -> float:
    """Δa(km) → Δv(m/s)，近圓沿軌脈衝。"""
    n = np.sqrt(MU / a_km ** 3)           # rad/s
    return da_km * n / 2.0 * 1000.0       # km/s→m/s


def main():
    fp = Path("data/benchmark/injection_floors.csv")
    if fp.exists():
        floors = pd.read_csv(fp)
    else:
        print("找不到 injection_floors.csv，請先跑 synthetic_injection_test.py"); return

    rows = []
    for _, r in floors.iterrows():
        band = r["noise_band"]; a = ALT_A.get(band, 6928.0); sigma = r["sigma_km"]
        for lvl, col in [("50%", "da50_km"), ("90%", "da90_km")]:
            da = r.get(col)
            if pd.isna(da):
                continue
            rows.append({"noise_band": band, "a_km": a, "sigma_km": sigma,
                         "detect_level": lvl, "da_floor_km": da,
                         "dv_floor_ms": round(dv_from_da(float(da), a), 4)})
    tle = pd.DataFrame(rows)

    # MEME 偵測下限：位置σ~5m → Δa 可辨 ~ 幾倍σ（保守 4×5m=20m=2e-2 km）
    meme_da_km = TLE_SNR_FLOOR * MEME_POS_SIGMA_M / 1000.0   # m→km（20 m = 0.02 km）
    print("=== TLE 星曆：Δa / ΔV 偵測下限（合成注入驗證換算）===")
    print(tle.to_string(index=False))
    print(f"\n=== MEME 精密星曆：偵測下限（位置σ≈{MEME_POS_SIGMA_M}m）===")
    for band, a in ALT_A.items():
        dvm = dv_from_da(meme_da_km, a)
        print(f"  {band:16} Δa≈{meme_da_km*1e3:.3f}m  ΔV≈{dvm*1e3:.3f} mm/s")

    # 綜合結論表
    best_tle_dv = tle[tle["detect_level"] == "50%"]["dv_floor_ms"].min()
    worst_tle_dv = tle[tle["detect_level"] == "90%"]["dv_floor_ms"].max()
    meme_dv_ms = dv_from_da(meme_da_km, 6928.0)      # m/s
    print("\n=== 微型機動可行性結論 ===")
    print(f"  TLE 偵測下限：ΔV ≈ {best_tle_dv:.2f}–{worst_tle_dv:.2f} m/s（依高度/雜訊）")
    print(f"  MEME 偵測下限：ΔV ≈ {meme_dv_ms*1e3:.1f} mm/s = {meme_dv_ms:.4f} m/s"
          f"（較 TLE 靈敏約 {best_tle_dv/meme_dv_ms:.0f}–{worst_tle_dv/meme_dv_ms:.0f} 倍）")
    print(f"  → 微型機動（ΔV < ~{best_tle_dv:.1f} m/s）需 MEME 精密星曆方可偵測；")
    print(f"    此即表 8 情境② small 嚴重度 recall 未達標之物理根因（小機動落於 TLE 雜訊底下）。")

    out = Path("data/benchmark/micro_maneuver_feasibility.csv")
    tle.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n表 → {out}")


if __name__ == "__main__":
    main()
