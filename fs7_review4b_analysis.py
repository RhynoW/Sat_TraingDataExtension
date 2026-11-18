#!/usr/bin/env python3
"""
fs7_review4b_analysis.py — 第四輪稿件審查補算（v8）
====================================================
1. corr(log c, log SNR50) 之 B 收斂檢查（B=200 vs B=500，叢集自助）
2. amplitude-only 模型於同一 temporal test split 之校準斜率/截距＋叢集自助 CI
3. pseudo-event 分層：各星 evaluable 數、逐星 FPR、satellite-weighted FPR、
   排除 2024-05 磁暴區間之敏感性
4. 混淆表之 Wilson 95% CI（recall 與 FPR）

輸出：data/benchmark/fs7_review4b_analysis.json
用法：python fs7_review4b_analysis.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd

from fs7_injection_sweep import load_series
from fs7_injection_sweep_v2 import _logit_fit
from fs7_tle_recall_unified import SIGMA3_NEW_M, THR_OLD_M, tle_step, wilson
from formosat7_leoorb.satmap import SP3_TO_NORAD

SPLIT = "2025-07-01"
STORM = ("2024-05-08", "2024-05-20")
CS = np.logspace(-1.3, 1.0, 24)


def snr_of(tr, c):
    return (tr["da_km"] / np.hypot(tr["sigma_km"], c * tr["adot_kmday"].abs() * tr["dt_day"])).clip(1e-2, 1e4)


def fit_at(tr, c):
    return _logit_fit(np.log10(snr_of(tr, c).values), tr["hit"].values.astype(float))


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
    result = {}

    # ── 1. corr 收斂檢查 ────────────────────────────────────────────────────
    print("1. corr(log c, log SNR50) B=200 vs B=500 …")
    uniq = tr["cluster"].unique()
    groups = {k: np.where(tr["cluster"].values == k)[0] for k in uniq}

    def joint_boot(B):
        pts = []
        for _ in range(B):
            idx = np.concatenate([groups[k] for k in rng.choice(uniq, len(uniq), replace=True)])
            sub = tr.iloc[idx]
            lls = [fit_at(sub, c)[2] for c in CS]
            cb = float(CS[int(np.argmax(lls))])
            s50b, _, _ = fit_at(sub, cb)
            pts.append((cb, s50b))
        p = np.array(pts)
        return float(np.corrcoef(np.log(p[:, 0]), np.log(p[:, 1]))[0, 1])
    c200 = joint_boot(200)
    c500 = joint_boot(500)
    result["corr_convergence"] = {"B200": round(c200, 3), "B500": round(c500, 3),
        "note": "Pearson on (log c, log SNR50) across full-data cluster-bootstrap "
                "replicates; grid c>0 (24 log-spaced points)"}
    print(f"   B=200: {c200:.3f}   B=500: {c500:.3f}")

    # ── 2. amplitude-only 校準斜率/截距 + CI（同 temporal test split）────────
    print("\n2. amplitude-only slope/intercept on test split …")
    cal, tst = tr[tr["win_t0"] < SPLIT], tr[tr["win_t0"] >= SPLIT].reset_index(drop=True)
    y = tst["hit"].values.astype(float)
    xa_cal = np.log10((cal["da_km"] / cal["sigma_km"]).clip(1e-2, 1e4).values)
    s50a, ba, _ = _logit_fit(xa_cal, cal["hit"].values.astype(float))
    xa_t = np.log10((tst["da_km"] / tst["sigma_km"]).clip(1e-2, 1e4).values)
    p_amp = np.clip(1 / (1 + np.exp(-ba * (xa_t - np.log10(s50a)))), 1e-9, 1 - 1e-9)
    lgt = np.log(p_amp / (1 - p_amp))

    def slope_int(idx):
        s50s, b, _ = _logit_fit(lgt[idx] / np.log(10), y[idx])
        slope = b / np.log(10)
        return slope, -slope * np.log(s50s)
    sl0, ic0 = slope_int(np.arange(len(y)))
    uniq_t = tst["cluster"].unique()
    gt = {k: np.where(tst["cluster"].values == k)[0] for k in uniq_t}
    boots = [slope_int(np.concatenate([gt[k] for k in rng.choice(uniq_t, len(uniq_t), replace=True)]))
             for _ in range(2000)]
    b = np.array(boots)
    result["amp_calibration"] = {
        "slope": round(sl0, 2),
        "slope_ci95": [round(float(np.percentile(b[:, 0], q)), 2) for q in (2.5, 97.5)],
        "intercept": round(float(ic0), 2),
        "intercept_ci95": [round(float(np.percentile(b[:, 1], q)), 2) for q in (2.5, 97.5)]}
    print(f"   amp slope={sl0:.2f} CI{result['amp_calibration']['slope_ci95']} "
          f"intercept={ic0:.2f} CI{result['amp_calibration']['intercept_ci95']}")

    # ── 3. pseudo-event 分層 ────────────────────────────────────────────────
    print("\n3. pseudo-event 分層與磁暴敏感性 …")
    con = duckdb.connect("space_db.duckdb", read_only=True)
    rec = pd.read_csv("data/benchmark/fs7_tle_recall_unified_20260825.csv")
    ref = np.datetime64("1970-01-01T00:00:00", "s")
    ev_t = {s: [] for s in SP3_TO_NORAD}
    for _, r in rec.iterrows():
        d0 = (pd.Timestamp(r["t_start"]).to_datetime64().astype("datetime64[s]") - ref) / np.timedelta64(1, "D")
        ev_t[r["sp3_sat"]].append(float(d0))
    storm0 = (np.datetime64(STORM[0] + "T00:00:00", "s") - ref) / np.timedelta64(1, "D")
    storm1 = (np.datetime64(STORM[1] + "T00:00:00", "s") - ref) / np.timedelta64(1, "D")
    rng2 = np.random.default_rng(42)
    per_sat, pooled = {}, {"n": 0, "fp_old": 0, "fp_new": 0,
                           "n_ns": 0, "fp_old_ns": 0, "fp_new_ns": 0}
    for sat, nid in SP3_TO_NORAD.items():
        df = con.execute("SELECT epoch_utc, sma_km FROM raw_tle_archive WHERE norad_id=? "
                         "ORDER BY epoch_utc", [nid]).df()
        t = df["epoch_utc"].values.astype("datetime64[s]").astype(float) / 86400.0
        a = df["sma_km"].values
        evd = np.array(ev_t[sat]) if ev_t[sat] else np.array([0.0])
        cand = t[(t > t.min() + 3) & (t < t.max() - 3)]
        n = fo = fn = n_ns = fo_ns = fn_ns = 0
        for tc in rng2.choice(cand, size=min(200, len(cand)), replace=False):
            if np.abs(evd - tc).min() < 2.0:
                continue
            step_m, gap, adot, ok = tle_step(t, a, tc, tc)
            if not ok:
                continue
            in_storm = storm0 <= tc <= storm1
            hit_o = int(abs(step_m) > THR_OLD_M)
            hit_n = int(abs(step_m) > SIGMA3_NEW_M[sat])
            n += 1; fo += hit_o; fn += hit_n
            if not in_storm:
                n_ns += 1; fo_ns += hit_o; fn_ns += hit_n
        per_sat[sat] = {"n_evaluable": n, "fpr_45m": round(fo / n, 3),
                        "fpr_3sig": round(fn / n, 3)}
        for k, v in (("n", n), ("fp_old", fo), ("fp_new", fn),
                     ("n_ns", n_ns), ("fp_old_ns", fo_ns), ("fp_new_ns", fn_ns)):
            pooled[k] += v
    sw_old = float(np.mean([v["fpr_45m"] for v in per_sat.values()]))
    sw_new = float(np.mean([v["fpr_3sig"] for v in per_sat.values()]))
    result["pseudo_event_stratified"] = {
        "per_satellite": per_sat,
        "pooled_fpr": {"45m": round(pooled["fp_old"] / pooled["n"], 3),
                       "3sig": round(pooled["fp_new"] / pooled["n"], 3)},
        "satellite_weighted_fpr": {"45m": round(sw_old, 3), "3sig": round(sw_new, 3)},
        "storm_excluded_fpr": {"45m": round(pooled["fp_old_ns"] / pooled["n_ns"], 3),
                               "3sig": round(pooled["fp_new_ns"] / pooled["n_ns"], 3),
                               "n": pooled["n_ns"]}}
    print(f"   pooled 45m={result['pseudo_event_stratified']['pooled_fpr']['45m']} "
          f"sat-weighted={sw_old:.3f}  storm-excl={result['pseudo_event_stratified']['storm_excluded_fpr']['45m']}")
    print(f"   pooled 3σ={result['pseudo_event_stratified']['pooled_fpr']['3sig']} "
          f"sat-weighted={sw_new:.3f}  storm-excl={result['pseudo_event_stratified']['storm_excluded_fpr']['3sig']}")
    print("   各星 evaluable:", {k: v["n_evaluable"] for k, v in per_sat.items()})

    # ── 4. Wilson CI ────────────────────────────────────────────────────────
    result["wilson_ci"] = {
        "recall_45m_37_96": [round(x, 3) for x in wilson(37, 96)],
        "recall_3sig_45_96": [round(x, 3) for x in wilson(45, 96)],
        "fpr_45m_64_1131": [round(x, 3) for x in wilson(64, 1131)],
        "fpr_3sig_617_1131": [round(x, 3) for x in wilson(617, 1131)]}
    print("\n4. Wilson CI:", result["wilson_ci"])

    with open(Path("data/benchmark") / "fs7_review4b_analysis.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("輸出：data/benchmark/fs7_review4b_analysis.json")


if __name__ == "__main__":
    main()
