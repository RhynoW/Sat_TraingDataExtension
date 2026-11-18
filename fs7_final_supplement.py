#!/usr/bin/env python3
"""
fs7_final_supplement.py — 投稿前最後兩項補算（v7）
===================================================
1. held-out 校準斜率/截距之叢集自助 95% CI（測試切分、B=2,000）
2. 校準係數版 Δa₉₀ 補充表（SNR₉₀=10.57、c=0.28）與描述版（9.87、0.32）對照

輸出：data/benchmark/fs7_final_supplement.json
用法：python fs7_final_supplement.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

from fs7_injection_sweep import load_series
from fs7_injection_sweep_v2 import _logit_fit

SPLIT = "2025-07-01"
C_CAL, S50_CAL, BETA_CAL, SNR90_CAL = 0.28, 3.87, 5.04, 10.57
C_DESC, SNR90_DESC = 0.32, 9.87


def snr_of(tr, c):
    return (tr["da_km"] / np.hypot(tr["sigma_km"], c * tr["adot_kmday"].abs() * tr["dt_day"])).clip(1e-2, 1e4)


def main():
    rng = np.random.default_rng(42)
    tr = pd.read_csv("data/benchmark/fs7_injection_trials.csv")
    series = load_series("space_db.duckdb")
    t0_map = {}
    for nid, df in series.items():
        ep = df["epoch_utc"].values
        for ws in tr.loc[tr.norad == nid, "win_start"].unique():
            t0_map[(nid, ws)] = pd.Timestamp(ep[int(ws)])
    tr["win_t0"] = [t0_map[(n, w)] for n, w in zip(tr.norad, tr.win_start)]
    tr["cluster"] = tr["norad"].astype(str) + "_" + tr["win_start"].astype(str)
    tst = tr[tr["win_t0"] >= SPLIT].reset_index(drop=True)
    y = tst["hit"].values.astype(float)
    result = {}

    # ── 1. slope/intercept 叢集自助 CI ──────────────────────────────────────
    x = np.log10(snr_of(tst, C_CAL).values)
    p_raw = np.clip(1 / (1 + np.exp(-BETA_CAL * (x - np.log10(S50_CAL)))), 1e-9, 1 - 1e-9)
    lgt = np.log(p_raw / (1 - p_raw))

    def slope_int(idx):
        s50s, b, _ = _logit_fit(lgt[idx] / np.log(10), y[idx])
        slope = b / np.log(10)
        intercept = -slope * np.log(s50s)      # a in  y ~ sigmoid(a + slope·logit(p))
        return slope, intercept
    sl0, ic0 = slope_int(np.arange(len(y)))
    uniq = tst["cluster"].unique()
    groups = {k: np.where(tst["cluster"].values == k)[0] for k in uniq}
    boots = []
    for _ in range(2000):
        idx = np.concatenate([groups[k] for k in rng.choice(uniq, len(uniq), replace=True)])
        boots.append(slope_int(idx))
    b = np.array(boots)
    result["calibration_slope"] = {
        "slope": round(sl0, 2),
        "slope_ci95": [round(float(np.percentile(b[:, 0], q)), 2) for q in (2.5, 97.5)],
        "intercept": round(float(ic0), 2),
        "intercept_ci95": [round(float(np.percentile(b[:, 1], q)), 2) for q in (2.5, 97.5)],
        "method": "cluster bootstrap (satellite×window) on the test split, B=2000, "
                  "percentile; slope/intercept from logistic recalibration y ~ logit(p_raw)",
        "n_test_clusters": int(len(uniq)),
        "slope_ci_contains_1": bool(np.percentile(b[:, 0], 2.5) <= 1.0 <= np.percentile(b[:, 0], 97.5))}
    print(f"1. slope={sl0:.2f} CI{result['calibration_slope']['slope_ci95']} "
          f"intercept={ic0:.2f} CI{result['calibration_slope']['intercept_ci95']} "
          f"（CI 含 1：{result['calibration_slope']['slope_ci_contains_1']}）")

    # ── 2. Δa₉₀ 雙係數版對照表 ──────────────────────────────────────────────
    agg = pd.read_csv("data/benchmark/fs7_injection_sweep.csv")
    rows = []
    for (d, band), g in agg.groupby(["decim", "drag_band"]):
        g = g.sort_values("da_km")
        obs = g.loc[g["detect_rate"] >= 0.9, "da_km"].min()
        sig, adot, dt = g["sigma_med"].median(), g["adot_med"].median(), g["dt_med"].median()
        pred_cal = SNR90_CAL * np.hypot(sig, C_CAL * adot * dt) * 1000
        pred_desc = SNR90_DESC * np.hypot(sig, C_DESC * adot * dt) * 1000
        rows.append({"decim": int(d), "drag": band,
                     "da90_calibration_m": round(pred_cal),
                     "da90_descriptive_m": round(pred_desc),
                     "observed_floor_m": round(obs * 1000) if np.isfinite(obs) else None,
                     "rel_diff_pct": round(100 * (pred_cal - pred_desc) / pred_desc, 1)})
    result["da90_two_parameterizations"] = rows
    mx = max(abs(r["rel_diff_pct"]) for r in rows)
    print("2. Δa₉₀ 校準版 vs 描述版：最大相對差", mx, "%")
    for r in rows:
        print(f"   d={r['decim']} {r['drag']:<5} cal={r['da90_calibration_m']:4d} m  "
              f"desc={r['da90_descriptive_m']:4d} m  obs={r['observed_floor_m']}")
    result["max_rel_diff_pct"] = mx

    with open(Path("data/benchmark") / "fs7_final_supplement.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("輸出：data/benchmark/fs7_final_supplement.json")


if __name__ == "__main__":
    main()
