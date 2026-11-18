#!/usr/bin/env python3
"""
fs7_supplement_tables.py — derived tables for the Supplementary Material of
"An Empirical Sensitivity Model for Maneuver Detection from Public Two-Line
Elements" (docs/paper_fs7_supplement_EN.md).

Every number produced here is computed from the released derived tables in
data/benchmark/ and, where a trial-level quantity is required, from the TLE
history in space_db.duckdb opened read-only and truncated at TLE_CUTOFF (the
cutoff that reproduces the 478 quiet windows of fs7_injection_trials.csv
exactly). Nothing is hand-entered.

Sections (keys of the output JSON):
  S2_selection        included (96) vs excluded (35) events          [CSV only]
  S3_sp3_checks       per-check rejection counts of SP3 candidates   [CSV only]
  S4_profile          profile likelihood of c and joint-surface 95% region [CSV only]
  S5_variants         c-parameterization variants on common test events [CSV + DB epochs]
  S7_metrics          FAR / delay / precision stratification (exact
                      re-run of fs7_injection_sweep_v3 trials, verified
                      against fs7_injection_metrics.csv)                [DB]
  S8_calibration      reliability bins raw vs Platt; recalibrated slope CI [CSV + DB epochs]
  S9_pseudo           pseudo-event per-period / cadence summaries (redraw)
                      and real-event first-post-TLE delay              [DB]

Output: data/benchmark/fs7_supplement_tables.json
Usage (from repository root):  python docs/fs7_supplement_tables.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

from fs7_injection_sweep import (DA_GRID, DECIM, MIN_PTS, WIN, _detect_idx,
                                 load_series, quiet_windows, window_stats)
from fs7_injection_sweep_v2 import _logit_fit
from fs7_tle_recall_unified import SIGMA3_NEW_M, THR_OLD_M, tle_step, wilson
from formosat7_leoorb.satmap import SP3_TO_NORAD, NORAD_TO_SP3

BENCH = ROOT / "data" / "benchmark"
DB = str(ROOT / "space_db.duckdb")
TLE_CUTOFF = "2026-08-25"          # reproduces the 478 windows of fs7_injection_trials.csv
SPLIT = "2025-07-01"
STORM = ("2024-05-08", "2024-05-20")
CS = np.logspace(-1.3, 1.0, 47)
TOL_STEP, TOL_DAY, FRAG_SPAN = 2, 1.0, 5
MERGE_GAP = TOL_STEP               # flags <= 2 samples apart form one event
BINS = [0, 50, 100, 300, 1000, 3000, np.inf]
LABELS = ["1-50 m", "50-100 m", "100-300 m", "300 m-1 km", "1-3 km", ">3 km"]
REASON = {"persist": "暫態未留永久階躍", "arc": "弧段間解不一致", "common": "多星共模"}


def r3(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), 3)


def snr_of(tr, c):
    return (tr["da_km"] / np.hypot(tr["sigma_km"], c * tr["adot_kmday"].abs() * tr["dt_day"])).clip(1e-2, 1e4)


def fit_at(tr, c):
    return _logit_fit(np.log10(snr_of(tr, c).values), tr["hit"].values.astype(float))


def metrics(p, y):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    brier = float(np.mean((p - y) ** 2))
    order = np.argsort(p)
    ranks = np.empty(len(p)); ranks[order] = np.arange(1, len(p) + 1)
    n1 = y.sum(); n0 = len(y) - n1
    auc = float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))
    return ll, brier, auc


def slope_intercept(p, y):
    """Logistic recalibration y ~ sigmoid(a + b·logit(p)); returns (b, a)."""
    p = np.clip(p, 1e-9, 1 - 1e-9)
    lgt = np.log(p / (1 - p))
    s50s, w1, _ = _logit_fit(lgt / np.log(10), y)
    b = w1 / np.log(10)
    return b, -b * np.log(s50s)


def merge_events(idx: np.ndarray) -> list[np.ndarray]:
    if len(idx) == 0:
        return []
    idx = np.sort(idx)
    cuts = np.where(np.diff(idx) > MERGE_GAP)[0] + 1
    return np.split(idx, cuts)


def load_series_cut():
    s = load_series(DB)
    return {k: d[d["epoch_utc"] < pd.Timestamp(TLE_CUTOFF)].reset_index(drop=True) for k, d in s.items()}


def trials_with_epochs(series):
    tr = pd.read_csv(BENCH / "fs7_injection_trials.csv")
    t0 = {}
    for nid, df in series.items():
        ep = df["epoch_utc"].values
        for ws in tr.loc[tr.norad == nid, "win_start"].unique():
            t0[(nid, ws)] = pd.Timestamp(ep[int(ws)])
    tr["win_t0"] = [t0[(n, w)] for n, w in zip(tr.norad, tr.win_start)]
    tr["cluster"] = tr["norad"].astype(str) + "_" + tr["win_start"].astype(str)
    return tr


# ───────────────────────────── S2 selection ──────────────────────────────
def s2_selection():
    rec = pd.read_csv(BENCH / "fs7_tle_recall_unified_20260825.csv")
    rec["bin"] = pd.cut(rec["amp_m"], BINS, labels=LABELS)
    out = {}
    for dim in ("bin", "campaign", "sp3_sat"):
        g = rec.groupby(dim, observed=True)["computable"]
        out[dim] = {str(k): {"n": int(len(v)), "included": int(v.sum()),
                             "excluded": int((~v).sum()),
                             "exclusion_rate": r3(1 - v.mean())} for k, v in g}
    inc, exc = rec[rec.computable]["amp_m"], rec[~rec.computable]["amp_m"]
    q = lambda s: [r3(s.quantile(0.25)), r3(s.median()), r3(s.quantile(0.75))]
    mw = stats.mannwhitneyu(inc, exc, alternative="two-sided")
    ct = {}
    for dim in ("bin", "campaign", "sp3_sat"):
        tab = pd.crosstab(rec[dim], rec["computable"])
        chi2, p, dof, _ = stats.chi2_contingency(tab)
        ct[dim] = {"chi2": r3(chi2), "dof": int(dof), "p": r3(p)}
    out["amplitude_m_q25_med_q75"] = {"included": q(inc), "excluded": q(exc),
                                      "mannwhitney_p": r3(mw.pvalue)}
    out["chi2_independence"] = ct
    out["holdout"] = {str(k): {"n": int(len(v)), "included": int(v.sum())}
                      for k, v in rec.groupby("holdout")["computable"]}
    return out


# ───────────────────────────── S3 SP3 checks ─────────────────────────────
def s3_sp3_checks():
    sets = {
        "2024 storm interval": pd.read_csv(BENCH / "fs7_events_2024.csv"),
        "2025-07/08": pd.read_csv(BENCH / "fs7_events_2025raise.csv"),
    }
    camp = pd.read_csv(BENCH / "fs7_events_campaigns_20260825.csv")
    for c in ("2024-07", "2024-11/12", "2025-05", "2026-01"):
        sets[c] = camp[camp["campaign"] == c]
    rows = {}
    allc = []
    for name, ev in sets.items():
        ev = ev.copy()
        reason = ev["reason"].fillna("")
        f = {k: reason.str.contains(v) for k, v in REASON.items()}
        ok = ev["verdict"] == "疑似真事件"
        n_fail = sum(f[k].astype(int) for k in f)
        row = {"candidates": int(len(ev)), "verified": int(ok.sum())}
        for k in f:
            row[f"fail_{k}"] = int(f[k].sum())
            row[f"sole_{k}"] = int((f[k] & (n_fail == 1)).sum())
        row["multi_fail"] = int((n_fail >= 2).sum())
        row["single_arc_candidates"] = int((ev["n_arcs_med"] <= 1).sum())
        big_cm = f["common"] & ~f["persist"] & ~f["arc"] & (ev["step_m"].abs() >= 1000)
        row["common_only_step_ge_1km"] = int(big_cm.sum())
        rows[name] = row
        ev["set"] = name
        allc.append(ev)
    a = pd.concat(allc, ignore_index=True)
    ok = a["verdict"] == "疑似真事件"
    di = a["di_deg"].abs()
    inc = {"verified_abs_di_deg_med": r3(di[ok].median()),
           "verified_abs_di_deg_p95": r3(di[ok].quantile(0.95)),
           "rejected_abs_di_deg_med": r3(di[~ok].median()),
           "verified_abs_di_gt_0.005deg": int((di[ok] > 0.005).sum())}
    return {"per_set": rows, "inclination": inc}


# ───────────────────────────── S4 profile / joint ────────────────────────
def ll_beta_profile(x, y, s50):
    lo, hi = 0.5, 20.0
    def ll(b):
        p = np.clip(1 / (1 + np.exp(-b * (x - np.log10(s50)))), 1e-12, 1 - 1e-12)
        return float(np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    for _ in range(40):
        m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
        if ll(m1) < ll(m2):
            lo = m1
        else:
            hi = m2
    return ll((lo + hi) / 2)


def s4_profile():
    tr = pd.read_csv(BENCH / "fs7_injection_trials.csv")
    n = len(tr)
    prof = [fit_at(tr, c) for c in CS]
    lls = np.array([p[2] for p in prof]) * n
    ih = int(np.argmax(lls))
    rel = lls - lls[ih]
    pick = [0.1, 0.2, 0.25, 0.28, 0.32, 0.4, 0.5, 0.7, 1.0, 2.0]
    table = []
    for c in pick:
        j = int(np.argmin(np.abs(CS - c)))
        table.append({"c_grid": r3(CS[j]), "rel_loglik": round(float(rel[j]), 2),
                      "snr50": round(prof[j][0], 2), "beta": round(prof[j][1], 2)})
    # joint surface (same grid as fs7_review4_analysis.py)
    y = tr["hit"].values.astype(float)
    c_grid = np.logspace(-0.9, 0.4, 26)
    s_grid = np.logspace(-0.2, 1.0, 26)
    LL = np.empty((len(s_grid), len(c_grid)))
    for j, c in enumerate(c_grid):
        x = np.log10(snr_of(tr, c).values)
        for i, s50 in enumerate(s_grid):
            LL[i, j] = ll_beta_profile(x, y, s50) * n
    LLr = LL - LL.max()
    inside = LLr >= -1.92
    ii, jj = np.where(inside)
    imax = np.unravel_index(LL.argmax(), LL.shape)
    return {"profile_table": table, "c_hat_grid": r3(CS[ih]),
            "joint_max": {"c": r3(c_grid[imax[1]]), "snr50": r3(s_grid[imax[0]])},
            "joint_95_region_grid_extent": {
                "c": [r3(c_grid[jj.min()]), r3(c_grid[jj.max()])],
                "snr50": [r3(s_grid[ii.min()]), r3(s_grid[ii.max()])],
                "n_grid_cells": int(inside.sum())},
            "grid": {"c": "logspace(-0.9, 0.4, 26)", "snr50": "logspace(-0.2, 1.0, 26)"}}


# ───────────────────────────── S5 variants ───────────────────────────────
def s5_variants(tr):
    cal, tst = tr[tr["win_t0"] < SPLIT], tr[tr["win_t0"] >= SPLIT].reset_index(drop=True)
    c_cal = float(CS[int(np.argmax([fit_at(cal, c)[2] for c in CS]))])
    yt = tst["hit"].values.astype(float)
    variants = {"c=1": 1.0, "c=0.32": 0.32, "c_cal": c_cal}
    out, P, X = {"c_cal": r3(c_cal), "n_test": int(len(tst))}, {}, {}
    for tag, c in variants.items():
        s50, beta, _ = fit_at(cal, c)
        x = snr_of(tst, c).values
        p = 1 / (1 + np.exp(-beta * (np.log10(x) - np.log10(s50))))
        ll, br, auc = metrics(p, yt)
        out[tag] = {"c": r3(c), "snr50": round(s50, 2), "beta": round(beta, 2),
                    "snr90": round(s50 * 10 ** (np.log(9) / beta), 2),
                    "held_out_logloss": round(ll, 4), "brier": round(br, 4), "auc": round(auc, 4)}
        P[tag], X[tag] = p, x
    pairs = {}
    for a, b in (("c=1", "c_cal"), ("c=0.32", "c_cal"), ("c=1", "c=0.32")):
        d = np.abs(P[a] - P[b])
        pairs[f"{a} vs {b}"] = {"mean_abs_dp": round(float(d.mean()), 4),
                                "p99_abs_dp": round(float(np.quantile(d, 0.99)), 4),
                                "max_abs_dp": round(float(d.max()), 4),
                                "pearson_r_p": round(float(np.corrcoef(P[a], P[b])[0, 1]), 4),
                                "median_snr_ratio": r3(np.median(X[a] / X[b])),
                                "snr50_ratio": r3(out[a]["snr50"] / out[b]["snr50"])}
    out["pairs"] = pairs
    tst = tst.copy()
    tst["drag_band"] = tst["drag_band"].astype(str)
    cond = []
    for (d, band), g in tst.groupby(["decim", "drag_band"]):
        idx = g.index.values
        row = {"decim": int(d), "drag": band, "n": int(len(idx)),
               "obs_rate": r3(yt[idx].mean())}
        for tag in variants:
            row[f"med_snr_{tag}"] = round(float(np.median(X[tag][idx])), 2)
            row[f"mean_p_{tag}"] = r3(P[tag][idx].mean())
        cond.append(row)
    out["by_condition"] = sorted(cond, key=lambda r: (r["decim"], ["low", "mid", "high"].index(r["drag"])))
    return out


# ───────────────────────────── S7 metrics ────────────────────────────────
def s7_metrics(series):
    """Exact replica of fs7_injection_sweep_v3.run_trials (same RNG order),
    additionally keeping flag indices for event-level accounting."""
    rng = np.random.default_rng(42)
    tr_rows, ctl_rows = [], []
    for nid, df in series.items():
        t_all = df["epoch_utc"].values.astype("datetime64[s]").astype(float) / 86400.0
        a_all = df["sma_km"].values
        for (s, e) in quiet_windows(df):
            for d in DECIM:
                t, a = t_all[s:e:d], a_all[s:e:d]
                n = len(a)
                if n < MIN_PTS:
                    continue
                sigma, adot, dtm = window_stats(t, a)
                if sigma <= 0:
                    continue
                span = float(t[-1] - t[0])
                key = dict(norad=nid, win_start=s, decim=d, adot_kmday=round(adot, 5), span_day=span)
                flags0 = _detect_idx(a)
                rng.integers(n // 3, 2 * n // 3)                 # pinj (keeps RNG order)
                ctl_rows.append({**key, "n_flags": len(flags0),
                                 "n_events": len(merge_events(flags0)),
                                 "far_flag_30d": len(flags0) / max(span, 1e-6) * 30.0,
                                 "far_event_30d": len(merge_events(flags0)) / max(span, 1e-6) * 30.0})
                for da_km in DA_GRID:
                    inj = int(rng.integers(n // 3, 2 * n // 3))
                    x = a.copy(); x[inj:] += da_km
                    flags = _detect_idx(x)
                    near = flags[np.abs(flags - inj) <= TOL_STEP]
                    fp = flags[flags < inj - TOL_STEP]
                    after = flags[flags >= inj]
                    delay = float(t[int(after.min())] - t[inj]) if len(after) else np.nan
                    evs = merge_events(flags)
                    tp_ev = sum(1 for g in evs if np.any(np.abs(g - inj) <= TOL_STEP))
                    fp_ev = sum(1 for g in evs if g.max() < inj - TOL_STEP)
                    tr_rows.append({**key, "da_km": da_km, "hit_step": int(len(near) > 0),
                                    "n_fp": int(len(fp)), "n_tp_flags": int(len(near)),
                                    "tp_ev": int(min(tp_ev, 1)), "fp_ev": int(fp_ev),
                                    "delay_day": delay,
                                    "delay_samples": int(after.min() - inj) if len(after) else -1})
    tr, ctl = pd.DataFrame(tr_rows), pd.DataFrame(ctl_rows)
    tr["drag_band"] = pd.qcut(tr["adot_kmday"].abs(), 3, labels=["low", "mid", "high"])
    ctl["drag_band"] = pd.qcut(ctl["adot_kmday"].abs(), 3, labels=["low", "mid", "high"])
    # verification against the released metrics table
    ref = pd.read_csv(BENCH / "fs7_injection_metrics.csv")
    agg = tr.groupby(["da_km", "decim", "drag_band"], observed=True).agg(
        tp=("hit_step", "sum"), fp=("n_fp", "sum")).reset_index()
    m = agg.merge(ref, on=["da_km", "decim", "drag_band"], suffixes=("", "_ref"))
    assert len(m) == 99 and (m.tp == m.tp_ref).all() and (m.fp == m.fp_ref).all(), "replica mismatch"

    out = {"n_trials": int(len(tr)), "n_control_windows": int(len(ctl)),
           "replica_verified_against_fs7_injection_metrics_csv": True}

    def far_block(g):
        return {"n_windows": int(len(g)),
                "flag_med": r3(g["far_flag_30d"].median()),
                "flag_q25_q75": [r3(g["far_flag_30d"].quantile(.25)), r3(g["far_flag_30d"].quantile(.75))],
                "flag_mean": r3(g["far_flag_30d"].mean()),
                "event_med": r3(g["far_event_30d"].median()),
                "event_mean": r3(g["far_event_30d"].mean()),
                "frac_windows_no_flag": r3((g["n_flags"] == 0).mean())}
    out["far_pooled"] = far_block(ctl)
    out["far_by_cadence"] = {f"{d}x": far_block(g) for d, g in ctl.groupby("decim")}
    out["far_by_drag"] = {str(b): far_block(g) for b, g in ctl.groupby("drag_band", observed=True)}
    out["far_by_satellite"] = {f"{NORAD_TO_SP3[n]} ({n})": far_block(g) for n, g in ctl.groupby("norad")}
    out["far_by_cadence_drag"] = {f"{d}x-{b}": far_block(g)
                                  for (d, b), g in ctl.groupby(["decim", "drag_band"], observed=True)}

    big = tr[tr["da_km"] >= 0.05]
    dl = {}
    for d, g in big.groupby("decim"):
        has = g["delay_day"].notna()
        dd = g.loc[has, "delay_day"]
        dl[f"{d}x"] = {"n_trials": int(len(g)), "frac_with_post_flag": r3(has.mean()),
                       "median_day": r3(dd.median()),
                       "iqr_day": [r3(dd.quantile(.25)), r3(dd.quantile(.75))],
                       "p90_day": r3(dd.quantile(.9)),
                       "first_tle_frac_of_trials": r3((g["delay_samples"] == 0).mean()),
                       "first_tle_frac_of_flagged": r3((g.loc[has, "delay_samples"] == 0).mean())}
    out["delay_da_ge_50m"] = dl
    dl2 = {}
    for (d, da), g in tr.groupby(["decim", "da_km"]):
        has = g["delay_day"].notna()
        dl2[f"{d}x-{int(round(da*1000))}m"] = {
            "first_tle_frac": r3((g["delay_samples"] == 0).mean()),
            "median_day": r3(g.loc[has, "delay_day"].median()) if has.any() else None}
    out["delay_by_cadence_amp"] = dl2

    def prec(g):
        tp, fpf = g["hit_step"].sum(), g["n_fp"].sum()
        tpf = g["n_tp_flags"].sum()
        tpe, fpe = g["tp_ev"].sum(), g["fp_ev"].sum()
        return {"n": int(len(g)),
                "flag_level_main_text": r3(tp / max(tp + fpf, 1)),
                "flag_level_all_flags": r3(tpf / max(tpf + fpf, 1)),
                "event_level": r3(tpe / max(tpe + fpe, 1))}
    det = tr[tr["da_km"] >= 0.2]
    out["precision_da_ge_200m"] = {"pooled": prec(det),
                                   **{f"{d}x": prec(g) for d, g in det.groupby("decim")}}
    out["precision_by_cadence_drag_da_ge_200m"] = {
        f"{d}x-{b}": prec(g) for (d, b), g in det.groupby(["decim", "drag_band"], observed=True)}
    out["precision_by_amp_pooled"] = {f"{int(round(da*1000))}m": prec(g) for da, g in tr.groupby("da_km")}
    fr = {}
    for d, g in ref.groupby("decim"):
        w = lambda s: r3((s["frag_rate"] * s["n"]).sum() / s["n"].sum())
        fr[f"{d}x"] = {"all_amplitudes": w(g), "da_ge_200m": w(g[g["da_km"] >= 0.2])}
    out["fragmentation_by_cadence"] = fr     # n-weighted from fs7_injection_metrics.csv
    return out


# ───────────────────────────── S8 calibration ────────────────────────────
def s8_calibration(tr):
    rng = np.random.default_rng(42)                     # same RNG order as fs7_review4_analysis.py
    tr = tr.copy()
    tr["block"] = tr["norad"].astype(str) + "_" + (tr["win_start"] // (WIN * 5)).astype(str)
    rng.permutation(tr["block"].unique())               # blocked-CV fold assignment (consumed)
    cal, tst = tr[tr["win_t0"] < SPLIT], tr[tr["win_t0"] >= SPLIT].reset_index(drop=True)
    y_cal, y_tst = cal["hit"].values.astype(float), tst["hit"].values.astype(float)
    c_cal = float(CS[int(np.argmax([fit_at(cal, c)[2] for c in CS]))])
    s50, beta, _ = _logit_fit(np.log10(snr_of(cal, c_cal).values), y_cal)
    calb = cal.reset_index(drop=True)
    kf = rng.permutation(len(calb)) % 5
    xc = np.log10(snr_of(calb, c_cal).values)
    oof = np.zeros(len(calb))
    for f in range(5):
        m = kf != f
        s5f, bf, _ = _logit_fit(xc[m], y_cal[m])
        oof[~m] = 1 / (1 + np.exp(-bf * (xc[~m] - np.log10(s5f))))
    oofc = np.clip(oof, 1e-9, 1 - 1e-9)
    s50p, bp, _ = _logit_fit(np.log(oofc / (1 - oofc)) / np.log(10), y_cal)
    a_pl, b_pl = -bp * np.log10(s50p), bp / np.log(10)
    x_t = np.log10(snr_of(tst, c_cal).values)
    p_raw = np.clip(1 / (1 + np.exp(-beta * (x_t - np.log10(s50)))), 1e-9, 1 - 1e-9)
    p_rec = 1 / (1 + np.exp(-(a_pl + b_pl * np.log(p_raw / (1 - p_raw)))))
    out = {"c_cal": r3(c_cal), "platt": {"a": r3(a_pl), "b": r3(b_pl)}, "n_test": int(len(tst))}
    uniq = tst["cluster"].unique()
    groups = {k: np.where(tst["cluster"].values == k)[0] for k in uniq}
    rng_b = np.random.default_rng(42)
    for tag, p in (("raw", p_raw), ("recalibrated", p_rec)):
        ll, br, auc = metrics(p, y_tst)
        b0, a0 = slope_intercept(p, y_tst)
        boots = []
        for _ in range(2000):
            idx = np.concatenate([groups[k] for k in rng_b.choice(uniq, len(uniq), replace=True)])
            boots.append(slope_intercept(p[idx], y_tst[idx]))
        bb = np.array(boots)
        dec = pd.qcut(p, 10, duplicates="drop")
        bins = pd.DataFrame({"b": dec, "p": p, "y": y_tst}).groupby("b", observed=True).agg(
            p_mean=("p", "mean"), y_rate=("y", "mean"), n=("y", "size")).reset_index(drop=True)
        out[tag] = {"logloss": round(ll, 4), "brier": round(br, 4), "auc": round(auc, 4),
                    "slope": round(b0, 2),
                    "slope_ci95": [round(float(np.percentile(bb[:, 0], q)), 2) for q in (2.5, 97.5)],
                    "intercept": round(a0, 2),
                    "intercept_ci95": [round(float(np.percentile(bb[:, 1], q)), 2) for q in (2.5, 97.5)],
                    "bins": [{"p_mean": r3(r.p_mean), "y_rate": r3(r.y_rate), "n": int(r.n)}
                             for r in bins.itertuples()]}
    return out


# ───────────────────────────── S9 pseudo-events ──────────────────────────
def s9_pseudo():
    con = duckdb.connect(DB, read_only=True)
    rec = pd.read_csv(BENCH / "fs7_tle_recall_unified_20260825.csv")
    ref = np.datetime64("1970-01-01T00:00:00", "s")
    tod = lambda ts: float((pd.Timestamp(ts).to_datetime64().astype("datetime64[s]") - ref) / np.timedelta64(1, "D"))
    ev_t = {s: [] for s in SP3_TO_NORAD}
    for _, r in rec.iterrows():
        ev_t[r["sp3_sat"]].append(tod(r["t_start"]))
    st0, st1 = tod(STORM[0]), tod(STORM[1])
    tle = {}
    for sat, nid in SP3_TO_NORAD.items():
        df = con.execute("SELECT epoch_utc, sma_km FROM raw_tle_archive WHERE norad_id=? "
                         "AND epoch_utc < ? ORDER BY epoch_utc", [nid, TLE_CUTOFF]).df()
        tle[sat] = (df["epoch_utc"].values.astype("datetime64[s]").astype(float) / 86400.0,
                    df["sma_km"].values)
    rng = np.random.default_rng(42)
    rows = []
    for sat, (t, a) in tle.items():
        evd = np.array(ev_t[sat])
        cand = t[(t > t.min() + 3) & (t < t.max() - 3)]
        for tc in rng.choice(cand, size=min(200, len(cand)), replace=False):
            if np.abs(evd - tc).min() < 2.0:
                continue
            step_m, gap, adot, ok = tle_step(t, a, tc, tc)
            if not ok:
                continue
            rows.append({"sat": sat, "tc": tc, "gap_day": gap,
                         "fp45": int(abs(step_m) > THR_OLD_M),
                         "fp3s": int(abs(step_m) > SIGMA3_NEW_M[sat]),
                         "storm": bool(st0 <= tc <= st1)})
    ps = pd.DataFrame(rows)
    ps["date"] = pd.to_datetime(ps["tc"] * 86400, unit="s")
    ps["period"] = ps["date"].dt.year.astype(str) + "-H" + np.where(ps["date"].dt.month <= 6, "1", "2")

    def blk(g):
        k45, k3, n = int(g.fp45.sum()), int(g.fp3s.sum()), int(len(g))
        return {"n": n, "fpr_45m": r3(k45 / n), "fpr_45m_ci": [r3(x) for x in wilson(k45, n)],
                "fpr_3sig": r3(k3 / n), "fpr_3sig_ci": [r3(x) for x in wilson(k3, n)]}
    out = {"draw": f"seed 42, TLE history < {TLE_CUTOFF}", "pooled": blk(ps),
           "storm_excluded": blk(ps[~ps.storm]), "n_in_storm": int(ps.storm.sum()),
           "per_satellite": {s: blk(g) for s, g in ps.groupby("sat")},
           "per_period": {p: blk(g) for p, g in ps.groupby("period")}}
    out["satellite_weighted"] = {
        "fpr_45m": r3(np.mean([v["fpr_45m"] for v in out["per_satellite"].values()])),
        "fpr_3sig": r3(np.mean([v["fpr_3sig"] for v in out["per_satellite"].values()]))}
    real_gap = rec.loc[rec.computable, "gap_day"].astype(float)
    pg = ps["gap_day"]
    qs = (0.1, 0.25, 0.5, 0.75, 0.9)
    ks = stats.ks_2samp(pg, real_gap)
    out["cadence_match"] = {
        "pseudo_gap_day_quantiles": {str(q): r3(pg.quantile(q)) for q in qs},
        "real_gap_day_quantiles": {str(q): r3(real_gap.quantile(q)) for q in qs},
        "n_pseudo": int(len(pg)), "n_real": int(len(real_gap)),
        "ks_stat": r3(ks.statistic), "ks_p": r3(ks.pvalue)}
    # real-event delay: first post-event TLE used by the detector relative to t_end
    evs = pd.concat([pd.read_csv(BENCH / "fs7_events_2025raise.csv"),
                     pd.read_csv(BENCH / "fs7_events_campaigns_20260825.csv")], ignore_index=True)
    evs = evs[evs["verdict"] == "疑似真事件"]
    evs["key"] = evs["sp3_sat"] + "|" + pd.to_datetime(evs["t_start"], utc=True, format="mixed").astype(str)
    tend = dict(zip(evs["key"], evs["t_end"]))
    comp = rec[rec.computable].copy()
    comp["key"] = comp["sp3_sat"] + "|" + pd.to_datetime(comp["t_start"], utc=True, format="mixed").astype(str)
    delays = []
    for _, r in comp.iterrows():
        t, _a = tle[r["sp3_sat"]]
        te = tod(tend[r["key"]])
        post = t[(t >= te + 2 / 24) & (t <= te + 3.0)]
        delays.append({"campaign": r["campaign"], "delay_day": float(post.min() - te)})
    dd = pd.DataFrame(delays)
    blkd = lambda s: {"n": int(len(s)), "median_day": r3(s.median()),
                      "iqr_day": [r3(s.quantile(.25)), r3(s.quantile(.75))]}
    out["real_event_first_post_tle_delay"] = {"pooled": blkd(dd.delay_day),
        **{c: blkd(g.delay_day) for c, g in dd.groupby("campaign")}}
    # closely spaced verified events (same satellite)
    allv = rec.copy()
    allv["t"] = pd.to_datetime(allv["t_start"], utc=True, format="mixed")
    sep = []
    for s, g in allv.sort_values("t").groupby("sp3_sat"):
        sep += list(g["t"].diff().dt.total_seconds().dropna() / 86400.0)
    sep = np.array(sep)
    out["closely_spaced"] = {"n_pairs": int(len(sep)),
                             "lt_1h": int((sep < 1 / 24).sum()),
                             "lt_6h": int((sep < 0.25).sum()),
                             "lt_1d": int((sep < 1).sum()),
                             "lt_3d": int((sep < 3).sum())}
    return out


def main():
    res = {"tle_cutoff": TLE_CUTOFF}
    print("S2 selection …"); res["S2_selection"] = s2_selection()
    print("S3 SP3 checks …"); res["S3_sp3_checks"] = s3_sp3_checks()
    print("S4 profile / joint …"); res["S4_profile"] = s4_profile()
    series = load_series_cut()
    tr = trials_with_epochs(series)
    tr["drag_band"] = pd.qcut(tr["adot_kmday"].abs(), 3, labels=["low", "mid", "high"])
    print("S5 variants …"); res["S5_variants"] = s5_variants(tr)
    print("S7 metrics (trial replica) …"); res["S7_metrics"] = s7_metrics(series)
    print("S8 calibration …"); res["S8_calibration"] = s8_calibration(tr)
    print("S9 pseudo-events …"); res["S9_pseudo"] = s9_pseudo()
    out = BENCH / "fs7_supplement_tables.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(f"output: {out}")


if __name__ == "__main__":
    main()
