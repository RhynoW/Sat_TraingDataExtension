#!/usr/bin/env python3
"""
fs7_repro_minimal.py — 審稿用最小重現流程（不需 Space-Track 帳號、不需 DB）
=========================================================================
只讀審稿資料包內之衍生表，重現並核對正文主要數值：
  Table 3   時間切分 held-out log loss / AUC（drag-aware c=0.28 vs amplitude-only）
  Table 4a  內插 90% 注入召回幅度（點估計；CI 需 B=2,000 自助，見 fs7_review5_analysis.py）
  Table 4   真實事件分箱召回（45 m 與 unified 3σ）
  Table 5   45 m rule U 之 recall（需偽事件逐筆殘差：見 fs7_review5_threshold_sweep.csv）
輸入：data/benchmark/fs7_injection_trials_with_t0.csv（試驗表 + 窗起點曆元；不含原始 TLE）
      data/benchmark/fs7_tle_recall_unified_20260825.csv
      data/benchmark/fs7_review5_threshold_sweep.csv
用法：python fs7_repro_minimal.py      （全部核對通過時 exit 0）
相依：numpy、pandas（無其他）
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

BM = Path(__file__).resolve().parent / "data/benchmark"
SPLIT = "2025-07-01"
C_CAL = 10 ** -0.55        # 校準期 ĉ：logspace(-1.3, 1.0, 47) 之網格值 0.2818（正文四捨五入為 0.28）
GRID = [0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 0.75, 1.00, 1.50, 2.00]
FAIL = []


def check(name, got, exp, tol):
    ok = abs(got - exp) <= tol
    print(f"  {'OK ' if ok else 'BAD'} {name}: {got:.4f} (expected {exp}, tol {tol})")
    if not ok:
        FAIL.append(name)


def logit_fit(x, y):
    X = np.column_stack([np.ones_like(x), x]); w = np.zeros(2)
    for _ in range(100):
        p = 1 / (1 + np.exp(-X @ w)); W = np.clip(p * (1 - p), 1e-6, None)
        dw = np.linalg.solve((X * W[:, None]).T @ X, X.T @ (y - p)); w += dw
        if np.abs(dw).max() < 1e-10:
            break
    return 10 ** (-w[0] / w[1]), w[1]


def auc(pos, neg):
    r = pd.Series(np.concatenate([pos, neg])).rank().values
    return (r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def pav(y):
    v, w, idx = list(y), [1.0] * len(y), [[i] for i in range(len(y))]
    i = 0
    while i < len(v) - 1:
        if v[i] > v[i + 1] + 1e-15:
            v[i] = (v[i] * w[i] + v[i + 1] * w[i + 1]) / (w[i] + w[i + 1]); w[i] += w[i + 1]; idx[i] += idx[i + 1]
            del v[i + 1], w[i + 1], idx[i + 1]; i = max(i - 1, 0)
        else:
            i += 1
    out = np.empty(len(y))
    for val, ii in zip(v, idx):
        out[ii] = val
    return out


def interp90(rec, amps):
    r = pav(rec)
    if r[0] >= 0.9:
        return amps[0]
    j = int(np.where(r >= 0.9)[0][0])
    x0, x1 = np.log10(amps[j - 1]), np.log10(amps[j])
    return 10 ** (x0 + (0.9 - r[j - 1]) * (x1 - x0) / (r[j] - r[j - 1]))


def main():
    tr = pd.read_csv(BM / "fs7_injection_trials_with_t0.csv", parse_dates=["win_t0"])
    print(f"trials: {len(tr)}")
    cal, tst = tr[tr["win_t0"] < SPLIT], tr[tr["win_t0"] >= SPLIT]
    y = tst["hit"].values.astype(float)

    def snr(g, c):
        return (g["da_km"] / np.hypot(g["sigma_km"], c * g["adot_kmday"].abs() * g["dt_day"])).clip(1e-2, 1e4).values
    print("Table 3 (temporal hold-out)")
    s50, b = logit_fit(np.log10(snr(cal, C_CAL)), cal["hit"].values.astype(float))
    p = np.clip(1 / (1 + np.exp(-b * (np.log10(snr(tst, C_CAL)) - np.log10(s50)))), 1e-9, 1 - 1e-9)
    check("drag-aware SNR50 (cal)", s50, 3.87, 0.01); check("drag-aware beta (cal)", b, 5.04, 0.01)
    check("drag-aware held-out log loss", -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)), 0.1237, 0.0005)
    check("drag-aware held-out AUC", auc(p[y == 1], p[y == 0]), 0.9773, 0.0005)
    xa = lambda g: np.log10((g["da_km"] / g["sigma_km"]).clip(1e-2, 1e4).values)
    s50a, ba = logit_fit(xa(cal), cal["hit"].values.astype(float))
    pa = np.clip(1 / (1 + np.exp(-ba * (xa(tst) - np.log10(s50a)))), 1e-9, 1 - 1e-9)
    check("amplitude-only held-out log loss", -np.mean(y * np.log(pa) + (1 - y) * np.log(1 - pa)), 0.1413, 0.0005)

    print("Table 4a (interpolated Δa90, point estimates)")
    exp = {(1, "low"): 40.7, (1, "mid"): 91.0, (1, "high"): 156.5, (2, "low"): 47.0, (2, "mid"): 98.4,
           (2, "high"): 209.9, (4, "low"): 98.8, (4, "mid"): 200.0, (4, "high"): 476.3}
    amps = np.array(GRID) * 1000
    for (d, band), e in exp.items():
        g = tr[(tr.decim == d) & (tr.drag_band == band)]
        rec = g.groupby("da_km")["hit"].mean().reindex(GRID).values
        check(f"Δa90 {d}x·{band} (m)", interp90(rec, amps), e, 0.15)

    print("Table 4 (real-event recall, evaluable events)")
    rr = pd.read_csv(BM / "fs7_tle_recall_unified_20260825.csv")
    rr = rr[rr["computable"]]
    rr["bin"] = pd.cut(rr["amp_m"], [0, 50, 100, 300, 1000, 3000], labels=["1-50", "50-100", "100-300", "300-1k", "1-3k"])
    e45 = {"1-50": 0.11, "50-100": 0.31, "100-300": 0.50, "300-1k": 0.62, "1-3k": 0.82}
    e3s = {"1-50": 0.19, "50-100": 0.50, "100-300": 0.61, "300-1k": 0.62, "1-3k": 0.82}
    for bname, g in rr.groupby("bin", observed=True):
        check(f"recall 45 m {bname}", g["det_old"].mean(), e45[bname], 0.006)
        check(f"recall 3σ {bname}", g["det_new"].mean(), e3s[bname], 0.006)
    check("evaluable events", len(rr), 96, 0)

    print("Table 5 (rule U at 45 m, from the threshold sweep)")
    sw = pd.read_csv(BM / "fs7_review5_threshold_sweep.csv")
    r = sw.iloc[(sw["thr_m"] - 45).abs().argmin()]
    check("recall U @45 m", r["recall_U"], 0.552, 0.001); check("FPR U @45 m", r["FPR_U"], 0.052, 0.001)
    check("FPR S @45 m", r["FPR_S"], 0.026, 0.001)

    print("\nALL CHECKS PASSED" if not FAIL else f"\n{len(FAIL)} CHECK(S) FAILED: {FAIL}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
