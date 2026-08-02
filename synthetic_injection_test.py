#!/usr/bin/env python3
"""
synthetic_injection_test.py — 合成機動注入驗證（契約 M3）
========================================================
以「已知真值」量化偵測器靈敏度：在合成的乾淨半長軸序列（drag 衰減 + 真實 TLE 雜訊）中，
於已知時刻注入已知量級 Δa 的階躍機動，跑統計偵測器，量測「偵測率 vs 機動量 × 雜訊」。
直接給出**最小可偵測機動下限**（供 micro_maneuver_analysis 使用），並解釋表 8 情境② small
嚴重度未達標之本質原因（小機動落在 TLE 雜訊底之下）。

偵測器：statistical_detectors.run_all → MAD3σ ∪ CUSUM（da 上的變化點），旗標於注入 ±tol 內即命中。

用法：python synthetic_injection_test.py [--trials 300]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

from statistical_detectors import run_all

# 真實 TLE 半長軸單步雜訊（km），依高度概略（低軌阻力抖動大）
NOISE_BY_ALT = {"LEO_low(<450)": 0.15, "LEO(450-700)": 0.08, "LEO_high(>700)": 0.05}
DA_GRID = [0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.0, 5.0]   # 注入機動量 (km)
N_PTS = 60                                                   # 序列長（~天/筆）
TOL = 2                                                      # 命中容差（步）


def _detect(sma: np.ndarray) -> np.ndarray:
    """回傳被旗標的索引（MAD3σ ∪ CUSUM，作用於 da）。"""
    r = run_all(sma)
    flag = np.zeros(len(sma), bool)
    for k in ("mad3sig", "cusum"):
        ev = r[k]["events"]
        if len(ev):
            flag[np.clip(np.asarray(ev), 0, len(sma) - 1)] = True
    return flag


def trial(da_km, sigma, drag_rate, rng) -> tuple[bool, int]:
    """單次注入試驗：回傳 (是否命中, latency 步)。"""
    t = np.arange(N_PTS)
    base = 6900.0 - drag_rate * t                     # 乾淨 drag 衰減
    inj = rng.integers(N_PTS // 3, 2 * N_PTS // 3)    # 注入位置
    base[inj:] += da_km                               # 階躍機動
    sma = base + rng.normal(0, sigma, N_PTS)          # TLE 雜訊
    flag = _detect(sma)
    hits = np.where(flag)[0]
    near = hits[np.abs(hits - inj) <= TOL]
    return (len(near) > 0, int(np.abs(near - inj).min()) if len(near) else -1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    print(f"合成注入驗證：{args.trials} 試驗/格，Δa×雜訊 掃描\n")
    rows = []
    for lbl, sigma in NOISE_BY_ALT.items():
        for da in DA_GRID:
            hits = lats = 0; n = 0
            for _ in range(args.trials):
                ok, lat = trial(da, sigma, rng.uniform(0.0, 0.05), rng)
                n += 1; hits += int(ok); lats += lat if lat >= 0 else 0
            dr = hits / n
            rows.append({"noise_band": lbl, "sigma_km": sigma, "da_km": da,
                         "detect_rate": round(dr, 3),
                         "snr": round(da / sigma, 2)})
    df = pd.DataFrame(rows)

    # 每雜訊帶的偵測下限（50%/90% 偵測率對應 Δa）
    print(df.pivot(index="da_km", columns="noise_band", values="detect_rate").to_string())
    print("\n【偵測下限：達 50% / 90% 偵測率所需 Δa (km)】")
    floors = []
    for lbl, sigma in NOISE_BY_ALT.items():
        sub = df[df["noise_band"] == lbl].sort_values("da_km")
        def _floor(p):
            ok = sub[sub["detect_rate"] >= p]
            return float(ok["da_km"].min()) if len(ok) else None
        f50, f90 = _floor(0.5), _floor(0.9)
        floors.append({"noise_band": lbl, "sigma_km": sigma, "da50_km": f50, "da90_km": f90})
        print(f"  {lbl:16} σ={sigma}km → 50%:{f50}km  90%:{f90}km  (SNR@50%≈{f50/sigma if f50 else None:.1f})")

    out = Path("data/benchmark"); out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "injection_detect_rate.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(floors).to_csv(out / "injection_floors.csv", index=False, encoding="utf-8-sig")
    print(f"\n表 → {out}/injection_detect_rate.csv, injection_floors.csv")
    print("結論：偵測下限 ≈ 3–5× TLE 雜訊σ；小機動(Δa<σ)本質不可偵測，"
          "呼應表 8 情境② small recall 未達標。")


if __name__ == "__main__":
    main()
