#!/usr/bin/env python3
"""
fs7_review7_analysis.py — 期刊終審（paper_fs7_sensitivity_model_Review_Final）回應所需之小型補充分析
================================================================================================
  M1  無 TLE 響應事件之 SP3 重疊弧查核（同一 SP3 來源之內部一致性，非獨立驗證）
  M2  大候選以外（large-candidate-free）窗口事件之共變量：後段 TLE 數、與任一 SP3 候選之最近間距、
      ±3 d 候選密度；小振幅分箱召回之 Wilson CI
  M4  rule S 之正/負假設符號個別 FP/TN/FPR；符號混合期望之自助 CI（真實事件與偽事件分別重抽）
  m4  不屬污染窗口之 wrong-sign 事件逐件明細
  M5  √Δt 形式之全資料 SNR50、β、SNR90（與線性形式並列）
輸入：同 fs7_review5/6；space_db.duckdb（read_only，TLE 曆元 < 2026-08-25）
輸出：data/benchmark/fs7_review7_analysis.json
用法：python fs7_review7_analysis.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
except Exception:
    pass

import numpy as np
import pandas as pd

from fs7_injection_sweep_v2 import _logit_fit
from fs7_tle_recall_unified import THR_OLD_M, PRE_D, wilson
from fs7_review5_analysis import BM, LAB, load_tle, real_events, pseudo_events, to_day
from fs7_review6_analysis import load_events, response_ratios, snr_nc

B_BOOT = 2000


def all_candidates():
    a = pd.concat([pd.read_csv(BM / "fs7_events_2025raise.csv"),
                   pd.read_csv(BM / "fs7_events_campaigns_20260825.csv")], ignore_index=True)
    a["t_start"] = pd.to_datetime(a["t_start"], utc=True, format="mixed")
    return a


def m1_m2(d, ev, rr):
    allc = all_candidates()
    inc = d[d["computable"]].copy()
    inc["lcf"] = inc["n_large_steps_pre_window_any_verdict"] == 0
    rows = []
    for i in inc.index:
        r = ev.loc[i]; t0 = r["t_start"]
        same = allc[(allc["sp3_sat"] == r["sp3_sat"]) & (allc["t_start"] != t0)]
        dtd = (same["t_start"] - t0).dt.total_seconds().abs() / 86400
        rows.append({"idx": i, "n_arcs_med": float(r["n_arcs_med"]), "arc_spread_m": float(r["arc_spread_m"]),
                     "persist_ratio": float(r["persist_ratio"]),
                     "nearest_any_candidate_d": float(dtd.min()) if len(dtd) else np.nan,
                     "n_candidates_pm3d": int((dtd <= 3).sum()),
                     "n_post_tle_3d": int((rr[i][0] <= 3.0).sum())})
    x = pd.DataFrame(rows).set_index("idx")
    inc = inc.join(x)
    out = {}
    # M2：大候選以外窗口 vs 污染窗口之共變量
    cov = {}
    for k, g in inc.groupby("lcf"):
        cov["large_candidate_free" if k else "contaminated"] = {
            "n": int(len(g)),
            "median_post_tle_3d": float(g["n_post_tle_3d"].median()),
            "median_gap_day": round(float(g["gap_day"].median()), 2),
            "median_nearest_any_candidate_d": round(float(g["nearest_any_candidate_d"].median()), 2),
            "median_candidates_pm3d": float(g["n_candidates_pm3d"].median()),
            "frac_with_any_candidate_within_1d": round(float((g["nearest_any_candidate_d"] <= 1).mean()), 2)}
    out["M2_covariates"] = cov
    lcf = inc[inc["lcf"]]
    out["M2_recall_wilson_lcf"] = {}
    for b, g in lcf.groupby("bin", observed=True):
        k = int(g["det_S_45"].sum()); n = len(g)
        out["M2_recall_wilson_lcf"][b] = {"k": k, "n": n, "recall": round(k / n, 3),
                                         "wilson95": [round(v, 3) for v in wilson(k, n)]}
    # M1：無響應事件之 SP3 重疊弧
    c50 = lcf[(lcf["amp_m"] >= 50) & (lcf["amp_m"] < 300)]
    none = c50[c50["tle_response"] == "none"]; resp = c50[c50["tle_response"] != "none"]
    def arcs(g):
        return {"n": int(len(g)), "multi_arc_n": int((g["n_arcs_med"] >= 2).sum()),
                "median_n_arcs": float(g["n_arcs_med"].median()),
                "median_arc_spread_m": round(float(g["arc_spread_m"].median()), 1),
                "max_arc_spread_m": round(float(g["arc_spread_m"].max()), 1),
                "median_persist_ratio": round(float(g["persist_ratio"].median()), 2),
                "median_amp_m": round(float(g["amp_m"].median()), 1)}
    out["M1_overlap_arcs"] = {"no_response": arcs(none), "responding": arcs(resp),
                              "no_response_multi_arc_events": [
                                  {"sat": r.sp3_sat, "campaign": r.campaign, "t_start": str(r.t_start)[:16],
                                   "step_sp3_m": round(r.step_sp3_m), "n_arcs_med": r.n_arcs_med,
                                   "arc_spread_m": round(r.arc_spread_m, 1)}
                                  for r in none[none["n_arcs_med"] >= 2].itertuples()]}
    # m4：非污染之 wrong-sign
    ws = inc[(inc["class_45"] == "sign_mismatch") & inc["lcf"]]
    out["m4_uncontaminated_wrong_sign"] = [
        {"sat": r.sp3_sat, "campaign": r.campaign, "t_start": str(r.t_start)[:16], "bin": r.bin,
         "step_sp3_m": round(r.step_sp3_m, 1), "step_obs_m": round(r.step_obs_m, 1), "gap_day": round(r.gap_day, 2),
         "abs_adot_m_day": round(abs(r.adot_kmday) * 1000, 1), "verified_events_in_prewindow": int(r.n_events_in_pre_window),
         "other_events_in_interval": int(r.n_other_events_in_interval), "candidates_pm3d": int(r.n_candidates_pm3d),
         "nearest_any_candidate_d": round(r.nearest_any_candidate_d, 2), "n_arcs_med": r.n_arcs_med,
         "tle_response": r.tle_response}
        for r in ws.itertuples()]
    return out


def m4_sign(d, p, rng):
    inc = d[d["computable"]]
    sp = p["step_m"].values; n_p = len(sp)
    p_pos = float((inc["step_sp3_m"] > 0).mean())
    out = {"p_positive": round(p_pos, 3), "n_pseudo": n_p}
    sat_idx = [np.where(p["sp3_sat"].values == s)[0] for s in p["sp3_sat"].unique()]
    for nm, thr_e, thr_p in (("45m", THR_OLD_M, THR_OLD_M), ("3s", inc["thr3s_m"].values, p["thr3s_m"].values)):
        fpp = int((sp > thr_p).sum()); fpn = int((-sp > thr_p).sum())
        rec = {}
        for sgn, fp in (("positive", fpp), ("negative", fpn)):
            rec[sgn] = {"FP": fp, "TN": n_p - fp, "FPR": round(fp / n_p, 4),
                        "FPR_wilson": [round(v, 4) for v in wilson(fp, n_p)]}
        # 真實事件之 recall 依其自身 SP3 符號分組
        e_abs = inc["step_obs_m"].abs().values; ok = inc["sign_ok"].values
        th_e = thr_e if np.ndim(thr_e) else np.full(len(inc), thr_e)
        det = (e_abs > th_e) & ok
        pos = (inc["step_sp3_m"] > 0).values
        rec["recall_positive_events"] = {"n": int(pos.sum()), "recall": round(float(det[pos].mean()), 3)}
        rec["recall_negative_events"] = {"n": int((~pos).sum()), "recall": round(float(det[~pos].mean()), 3)}
        exp_fpr = p_pos * fpp / n_p + (1 - p_pos) * fpn / n_p
        bs = []
        thp = thr_p if np.ndim(thr_p) else np.full(n_p, thr_p)
        for _ in range(B_BOOT):
            ie = rng.integers(0, len(inc), len(inc))
            pp = float(pos[ie].mean())
            ip = np.concatenate([rng.choice(v, len(v), replace=True) for v in sat_idx])
            bs.append(pp * np.mean(sp[ip] > thp[ip]) + (1 - pp) * np.mean(-sp[ip] > thp[ip]))
        rec["expected_FPR"] = round(exp_fpr, 4)
        rec["expected_FPR_bootstrap_ci95"] = [round(float(np.percentile(bs, q)), 4) for q in (2.5, 97.5)]
        rec["expected_FP"] = round(exp_fpr * n_p, 1)
        out[nm] = rec
    out["note"] = ("Expected FPR = p₊·FPR(+) + (1−p₊)·FPR(−). CI: percentile bootstrap (B = 2,000) resampling real "
                   "events (for p₊) and pseudo-events within satellite; replaces the Wilson interval on the rounded "
                   "expected count used in R1/R2.")
    return out


def m5_sqrt(tr):
    y = tr["hit"].values.astype(float)
    cs = np.logspace(-2, 2, 81)
    out = {}
    for pw in (1.0, 0.5):
        ll = [_logit_fit(np.log10(snr_nc(tr, c, pw)), y)[2] for c in cs]
        c_hat = float(cs[int(np.argmax(ll))])
        s50, beta, mll = _logit_fit(np.log10(snr_nc(tr, c_hat, pw)), y)
        out[f"dt_pow_{pw:g}"] = {"c_hat": round(c_hat, 3), "snr50": round(s50, 2), "beta": round(beta, 2),
                                 "snr90": round(s50 * 10 ** (np.log(9) / beta), 2),
                                 "mean_ll": round(mll, 5)}
    out["note"] = ("Full-data fits, unclipped SNR. Under the √Δt form the ambiguity term is c·|ȧ|·√Δt with Δt in days, "
                   "so c carries units of m/day^0.5 per (m/day) and is not comparable with the linear-form c.")
    return out


def main():
    rng = np.random.default_rng(42)
    rec = pd.read_csv(BM / "fs7_tle_recall_unified_20260825.csv")
    tle = load_tle()
    d = real_events(tle, rec)
    ev, _ = load_events()
    rr = response_ratios(tle, ev, d)
    res = {}
    res.update(m1_m2(d, ev, rr))
    p = pseudo_events(tle, rec)
    res["M4_sign"] = m4_sign(d, p, rng)
    tr = pd.read_csv(BM / "fs7_injection_trials.csv")
    res["M5_sqrt_params"] = m5_sqrt(tr)
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    out = BM / "fs7_review7_analysis.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8", newline="\n")
    print(f"輸出：{out}")


if __name__ == "__main__":
    main()
