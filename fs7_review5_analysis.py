#!/usr/bin/env python3
"""
fs7_review5_analysis.py — 期刊審查 R1（paper_B_submission_ReviewV1）回應所需之補充分析
====================================================================================
對應審查意見：
  M2  選擇偏差：131→96 之排除原因（前/後段覆蓋）、時序、召回之最差/最佳界限與 IPW 估計
  M4  c 之可識別性：逐降頻（cadence）擬合 c 之 profile、衍生量 c·|ȧ|·Δt（m）
  M5  注入–真實落差診斷：(a) 依 lag-1 自相關分層之注入召回與模型殘差、加入 r1 共變量之
      held-out 比較；(b) 131 件真實事件之漏報分類（覆蓋不足/低於門檻/符號不符/同區間多次點火）
  M6  90% 召回底：各網格幅度召回與叢集自助 CI；PAV 單調化後以 log10Δa 線性內插之 Δa90 與 CI
  M7  門檻判準對稱化：原 §5.4 之 TP 要求與 SP3 同號、FP 不要求 → 改以 (U) 兩側皆不看符號、
      (S) 兩側皆要求符號（偽事件之假設符號依真實事件之符號比例）重算；門檻掃描 ROC/precision
  M8  風暴期 21 件候選之逐日 Kp_max / F10.7 對齊
  m3  傾角佐證統計
  m13 執行時間

偽事件抽樣：採補充材料之 Draw C（seed 42、TLE 曆元 < 2026-08-25；docs/fs7_supplement_tables.py
S9_pseudo），n = 1,145，腳本核對其 pooled FPR（0.052 / 0.548）。原正文表之 Draw A（n = 1,131，
fs7_review3_analysis.py）依賴當時之 DB 內容，以現行 DB 已無法逐筆重現，故 R1 起正文改用 Draw C。

輸入：data/benchmark/fs7_injection_trials.csv、fs7_tle_recall_unified_20260825.csv、
      fs7_events_2025raise.csv、fs7_events_campaigns_20260825.csv、fs7_events_2024.csv、
      data/space_weather/gfz_kp_3h_2024-04_05.csv（GFZ Kp，自 kp.gfz.de 擷取）、space_db.duckdb（read_only）
輸出：data/benchmark/fs7_review5_analysis.json（摘要）
      data/benchmark/fs7_review5_event_decomposition.csv（131 件逐事件分類）
      data/benchmark/fs7_review5_threshold_sweep.csv（門檻掃描）
      data/benchmark/fs7_review5_recall_grid.csv（注入召回 × 網格幅度 × 條件，含 CI）
      docs/fig_fs7_threshold_sweep.png（+ .pdf）
用法：python fs7_review5_analysis.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd

from fs7_injection_sweep import load_series, quiet_windows, one_trial, window_stats, DA_GRID
from fs7_injection_sweep_v2 import _logit_fit
from fs7_tle_recall_unified import (SIGMA3_NEW_M, THR_OLD_M, PRE_D, POST_D, GAP_H, MIN_PRE,
                                    tle_step, wilson)
from formosat7_leoorb.satmap import SP3_TO_NORAD

BM = Path("data/benchmark")
SPLIT = "2025-07-01"
CS = np.logspace(-1.3, 1.0, 47)
C_FULL, S50_FULL, B_FULL = 0.32, 3.77, 5.25       # 全資料描述性重擬合（正文 §4.3）
C_CAL, S50_CAL, B_CAL = 0.28, 3.87, 5.04          # 校準期係數（held-out 主流程）
BINS = [0, 50, 100, 300, 1000, 3000, np.inf]
LAB = ["1-50 m", "50-100 m", "100-300 m", "300 m-1 km", "1-3 km", ">3 km"]
B_BOOT = 2000
LARGE_STEP_M = 500.0       # 「公里級」SP3 候選（不論判定）之門檻
TLE_CUTOFF = "2026-08-25"   # 與原分析相同之 TLE 曆元截止（DB 之後持續更新）
REF = np.datetime64("1970-01-01T00:00:00", "s")


def to_day(ts) -> float:
    return float((pd.Timestamp(ts).to_datetime64().astype("datetime64[s]") - REF) / np.timedelta64(1, "D"))


def snr_of(tr, c):
    return (tr["da_km"] / np.hypot(tr["sigma_km"], c * tr["adot_kmday"].abs() * tr["dt_day"])).clip(1e-2, 1e4)


def p_logit(snr, s50, beta):
    return 1.0 / (1.0 + np.exp(-beta * (np.log10(snr) - np.log10(s50))))


def logloss(y, p):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def pav(y: np.ndarray) -> np.ndarray:
    """等權 pool-adjacent-violators（非遞減）。"""
    v = list(map(float, y)); w = [1.0] * len(v); idx = [[i] for i in range(len(v))]
    i = 0
    while i < len(v) - 1:
        if v[i] > v[i + 1] + 1e-15:
            nv = (v[i] * w[i] + v[i + 1] * w[i + 1]) / (w[i] + w[i + 1])
            v[i] = nv; w[i] += w[i + 1]; idx[i] += idx[i + 1]
            del v[i + 1], w[i + 1], idx[i + 1]
            i = max(i - 1, 0)
        else:
            i += 1
    out = np.empty(len(y))
    for val, ii in zip(v, idx):
        out[ii] = val
    return out


def interp90(rec: np.ndarray, amps_m: np.ndarray, level=0.9) -> float:
    """PAV 單調化後，以 log10Δa 線性內插 recall=level 之幅度；全高於→最小網格、永不達→nan。"""
    r = pav(rec)
    if r[0] >= level:
        return float(amps_m[0])
    k = np.where(r >= level)[0]
    if not len(k):
        return float("nan")
    j = int(k[0])
    x0, x1 = np.log10(amps_m[j - 1]), np.log10(amps_m[j])
    y0, y1 = r[j - 1], r[j]
    return float(10 ** (x0 + (level - y0) * (x1 - x0) / (y1 - y0)))


def grid_floor(rec: np.ndarray, amps_m: np.ndarray, level=0.9) -> float:
    k = np.where(rec >= level)[0]
    return float(amps_m[k[0]]) if len(k) else float("nan")


def mw_auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """Mann–Whitney AUC（含平手 0.5）。"""
    allv = np.concatenate([pos, neg])
    ranks = pd.Series(allv).rank(method="average").values
    rp = ranks[:len(pos)].sum()
    return float((rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def load_tle():
    con = duckdb.connect("space_db.duckdb", read_only=True)
    tle = {}
    for sat, nid in SP3_TO_NORAD.items():
        df = con.execute("SELECT epoch_utc, sma_km FROM raw_tle_archive WHERE norad_id=? "
                         "AND epoch_utc < ? ORDER BY epoch_utc", [nid, TLE_CUTOFF]).df()
        t = df["epoch_utc"].values.astype("datetime64[s]").astype(float) / 86400.0
        tle[sat] = (t, df["sma_km"].values)
    con.close()
    return tle


# ════════════════════════════════════════════════════════════════════════════
# 真實事件：重算（含帶號 SP3 step）、排除原因、漏報分類
# ════════════════════════════════════════════════════════════════════════════
def real_events(tle, rec):
    e25 = pd.read_csv(BM / "fs7_events_2025raise.csv")
    e25 = e25[e25["verdict"] == "疑似真事件"].copy()
    e25["campaign"] = "2025-07/08"; e25["holdout"] = False
    enew = pd.read_csv(BM / "fs7_events_campaigns_20260825.csv")
    enew = enew[enew["verdict"] == "疑似真事件"].copy()
    ev = pd.concat([e25, enew], ignore_index=True)
    for c in ("t_start", "t_end"):
        ev[c] = pd.to_datetime(ev[c], utc=True, format="mixed")
    assert len(ev) == len(rec) == 131
    # 全部 SP3 候選（不論判定），供「前段趨勢窗含公里級階躍」之判定
    allc = pd.concat([pd.read_csv(BM / "fs7_events_2025raise.csv"),
                      pd.read_csv(BM / "fs7_events_campaigns_20260825.csv")], ignore_index=True)
    allc = allc[allc["step_m"].abs() >= LARGE_STEP_M]
    allc_t = {s_: np.array([to_day(x) for x in g["t_start"]]) for s_, g in allc.groupby("sp3_sat")}
    rows = []
    for i, r in ev.iterrows():
        sat = r["sp3_sat"]; t, a = tle[sat]
        t0, t1 = to_day(r["t_start"]), to_day(r["t_end"])
        step, gap, adot, ok = tle_step(t, a, t0, t1)
        assert ok == bool(rec.loc[i, "computable"])
        if ok:
            assert abs(round(step, 1) - rec.loc[i, "step_obs_m"]) < 0.06
        pre_n = int(((t >= t0 - PRE_D) & (t <= t0 - GAP_H / 24)).sum())
        post_n = int(((t >= t1 + GAP_H / 24) & (t <= t1 + POST_D)).sum())
        before = t[t < t0]; after = t[t > t1]
        # 同一評估區間（最後前段 TLE → 首筆後段 TLE）內之其他已驗證事件數
        pre_mask = (t >= t0 - PRE_D) & (t <= t0 - GAP_H / 24)
        post_mask = (t >= t1 + GAP_H / 24) & (t <= t1 + POST_D)
        if ok:
            lo_t, hi_t = t[pre_mask].max(), t[post_mask].min()
            same = ev[(ev["sp3_sat"] == sat) & (ev.index != i)]
            st = np.array([to_day(x) for x in same["t_start"]])
            n_other = int(((st > lo_t) & (st < hi_t)).sum())
            # 前段趨勢窗 [t0−PRE_D, t0) 內之其他已驗證事件（趨勢被先前點火污染）
            n_pre = int(((st >= t0 - PRE_D) & (st < t0 - 1e-6)).sum())
            lt = allc_t.get(sat, np.array([]))
            n_large_pre = int(((lt >= t0 - PRE_D) & (lt < t0 - 1e-6)).sum())
        else:
            n_other = np.nan; n_pre = np.nan; n_large_pre = np.nan
        # TLE 響應分類（後段 3 d 內各筆 TLE 對前段趨勢之殘差 / SP3 step）
        resp = "n/a"
        if ok:
            co = np.polyfit(t[pre_mask], a[pre_mask], 1)
            pm = (t >= t1 + GAP_H / 24) & (t <= t1 + POST_D)
            ratios = (a[pm] - np.polyval(co, t[pm])) * 1000.0 / float(r["step_m"])
            ratios = ratios[np.argsort(t[pm])]
            good = (ratios >= 0.5) & (ratios <= 2.0)
            if good[0]:
                resp = "immediate"
            elif good.any():
                resp = "delayed"
            elif np.all(np.abs(ratios) < 0.5):
                resp = "none"
            else:
                resp = "other"
        rows.append({
            "tle_response": resp,
            "idx": i, "sp3_sat": sat, "campaign": r["campaign"], "t_start": r["t_start"],
            "step_sp3_m": float(r["step_m"]), "amp_m": abs(float(r["step_m"])),
            "computable": ok, "step_obs_m": step if ok else np.nan,
            "gap_day": gap if ok else np.nan, "adot_kmday": adot if ok else np.nan,
            "pre_n": pre_n, "post_n": post_n,
            "h_since_last_tle": (t0 - before.max()) * 24 if len(before) else np.nan,
            "h_to_next_tle": (after.min() - t1) * 24 if len(after) else np.nan,
            "n_other_events_in_interval": n_other,
            "n_events_in_pre_window": n_pre,
            "n_large_steps_pre_window_any_verdict": n_large_pre,
            "p_pred_full": rec.loc[i, "p_pred"],
        })
    d = pd.DataFrame(rows)
    d["bin"] = pd.cut(d["amp_m"], BINS, labels=LAB)
    d["sign_ok"] = np.sign(d["step_obs_m"]) == np.sign(d["step_sp3_m"])
    d["thr3s_m"] = d["sp3_sat"].map(SIGMA3_NEW_M)
    for tag, thr in (("45", THR_OLD_M), ("3s", None)):
        th = d["thr3s_m"] if thr is None else thr
        d[f"det_S_{tag}"] = d["computable"] & (d["step_obs_m"].abs() > th) & d["sign_ok"]
        d[f"det_U_{tag}"] = d["computable"] & (d["step_obs_m"].abs() > th)
        cls = np.where(~d["computable"],
                       np.where(d["pre_n"] < MIN_PRE, np.where(d["post_n"] < 1, "excl_both", "excl_pre"),
                                "excl_post"),
                       np.where(d[f"det_S_{tag}"], "detected",
                                np.where(d["step_obs_m"].abs() > th, "sign_mismatch", "below_threshold")))
        d[f"class_{tag}"] = cls
    assert int(d["det_S_45"].sum()) == int(rec["det_old"].sum())
    assert int(d["det_S_3s"].sum()) == int(rec["det_new"].sum())
    return d


def selection_bias(d):
    out = {}
    exc = d[~d["computable"]]
    out["exclusion_reason_counts"] = {
        "pre_window_lt3_only": int((exc["pre_n"] < MIN_PRE).sum() - ((exc["pre_n"] < MIN_PRE) & (exc["post_n"] < 1)).sum()),
        "post_window_empty_only": int(((exc["post_n"] < 1) & (exc["pre_n"] >= MIN_PRE)).sum()),
        "both": int(((exc["pre_n"] < MIN_PRE) & (exc["post_n"] < 1)).sum())}
    out["excluded_pre_n_distribution"] = exc["pre_n"].value_counts().sort_index().to_dict()
    out["excluded_timing_h"] = {
        "since_last_tle_median": round(float(exc["h_since_last_tle"].median()), 1),
        "since_last_tle_iqr": [round(float(exc["h_since_last_tle"].quantile(q)), 1) for q in (.25, .75)],
        "to_next_tle_median": round(float(exc["h_to_next_tle"].median()), 1),
        "to_next_tle_iqr": [round(float(exc["h_to_next_tle"].quantile(q)), 1) for q in (.25, .75)]}
    inc = d[d["computable"]]
    out["included_timing_h"] = {
        "since_last_tle_median": round(float(inc["h_since_last_tle"].median()), 1),
        "to_next_tle_median": round(float(inc["h_to_next_tle"].median()), 1)}
    # 逐 campaign 納入機率 → IPW；以及最差（排除=漏報）/最佳（排除=命中）界限
    pinc = d.groupby("campaign")["computable"].mean()
    d["w_ipw"] = np.where(d["computable"], 1.0 / d["campaign"].map(pinc), 0.0)
    pinc_cs = d.groupby(["campaign", "sp3_sat"])["computable"].mean()
    rows = []
    for b in LAB[:5] + ["all"]:
        g = d if b == "all" else d[d["bin"] == b]
        gi = g[g["computable"]]
        r = {"bin": b, "n_verified": len(g), "n_included": len(gi)}
        for tag in ("45", "3s"):
            k = int(gi[f"det_S_{tag}"].sum())
            r[f"recall_incl_{tag}"] = round(k / len(gi), 4)
            r[f"worst_{tag}"] = round(k / len(g), 4)
            r[f"best_{tag}"] = round((k + len(g) - len(gi)) / len(g), 4)
            w = gi["w_ipw"]
            r[f"ipw_campaign_{tag}"] = round(float((w * gi[f"det_S_{tag}"]).sum() / w.sum()), 4)
        rows.append(r)
    out["recall_bounds_by_bin"] = rows
    out["ipw_note"] = ("IPW weight = 1 / P(included | campaign), inclusion probability estimated as the "
                       "campaign inclusion fraction; satellite×campaign cells contain zero-inclusion cells "
                       f"({int((pinc_cs == 0).sum())}) so a satellite×campaign IPW is not identifiable.")
    return out


def miss_decomposition(d):
    out = {}
    for tag in ("45", "3s"):
        tab = pd.crosstab(d["bin"], d[f"class_{tag}"]).reindex(LAB[:5])
        tab.loc["all"] = tab.sum()
        out[f"class_by_bin_{tag}"] = {k: {kk: int(vv) for kk, vv in v.items()}
                                      for k, v in tab.to_dict("index").items()}
    inc = d[d["computable"]].copy()
    inc["multi"] = inc["n_other_events_in_interval"] > 0
    mb = {}
    for tag in ("45", "3s"):
        g = inc.groupby("multi")[f"det_S_{tag}"].agg(["sum", "size"])
        mb[tag] = {("shared_interval" if k else "single"): {"det": int(v["sum"]), "n": int(v["size"]),
                                                            "recall": round(v["sum"] / v["size"], 3)}
                   for k, v in g.iterrows()}
    out["multi_burn"] = mb
    inc["pre_contam"] = inc["n_large_steps_pre_window_any_verdict"] > 0
    pc = {}
    for tag in ("45", "3s"):
        g = inc.groupby("pre_contam")
        pc[tag] = {("pre_window_contaminated" if k else "clean_pre_window"): {
            "n": int(len(v)), "det": int(v[f"det_S_{tag}"].sum()),
            "sign_mismatch": int((v[f"class_{tag}"] == "sign_mismatch").sum()),
            "recall": round(float(v[f"det_S_{tag}"].mean()), 3)} for k, v in g}
    out["pre_window_contamination"] = pc
    out["pre_contam_by_bin_45"] = {b: {"n": int(len(g)), "contaminated": int(g["pre_contam"].sum()),
                                       "sign_mismatch_contaminated": int(((g["class_45"] == "sign_mismatch") & g["pre_contam"]).sum()),
                                       "sign_mismatch_total": int((g["class_45"] == "sign_mismatch").sum())}
                                   for b, g in inc.groupby("bin", observed=True)}
    inc["ratio"] = inc["step_obs_m"] / inc["step_sp3_m"]
    strat = []
    for (b, cflag), g in inc.groupby(["bin", "pre_contam"], observed=True):
        strat.append({"bin": b, "pre_window": "contaminated" if cflag else "clean", "n": int(len(g)),
                      "recall_45": round(float(g["det_S_45"].mean()), 3),
                      "recall_3s": round(float(g["det_S_3s"].mean()), 3),
                      "mean_p_pred": round(float(g["p_pred_full"].mean()), 3),
                      "median_abs_adot_m_per_day": round(float(g["adot_kmday"].abs().median() * 1000), 1),
                      "median_obs_over_sp3": round(float(g["ratio"].median()), 2)})
    out["bin_by_pre_window"] = strat
    tot = {}
    for cflag, g in inc.groupby("pre_contam"):
        tot["contaminated" if cflag else "clean"] = {
            "n": int(len(g)), "recall_45": round(float(g["det_S_45"].mean()), 3),
            "recall_3s": round(float(g["det_S_3s"].mean()), 3),
            "mean_p_pred": round(float(g["p_pred_full"].mean()), 3),
            "median_abs_adot_m_per_day": round(float(g["adot_kmday"].abs().median() * 1000), 1)}
    out["pre_window_totals"] = tot
    out["tle_response_by_bin_clean"] = {b: g["tle_response"].value_counts().to_dict()
                                        for b, g in inc[~inc["pre_contam"]].groupby("bin", observed=True)}
    out["tle_response_by_bin_contaminated"] = {b: g["tle_response"].value_counts().to_dict()
                                               for b, g in inc[inc["pre_contam"]].groupby("bin", observed=True)}
    out["tle_response_def"] = ("ratio = (TLE a − pre-window linear trend)/SP3 step for each TLE in "
                               "[t_end+2h, t_end+3d]; immediate: first ratio in [0.5, 2]; delayed: a later "
                               "TLE in [0.5, 2]; none: all |ratio| < 0.5; other: remaining (e.g. > 2 or "
                               "opposite sign, typically subsequent burns).")
    cl = inc[~inc["pre_contam"] & (inc["amp_m"] >= 50)]
    out["clean_ge50m_obs_over_sp3"] = {"n": int(len(cl)),
                                       "median": round(float(cl["ratio"].median()), 2),
                                       "iqr": [round(float(cl["ratio"].quantile(q)), 2) for q in (.25, .75)]}
    out["sign_mismatch_45_pre_contaminated"] = int(
        ((inc["class_45"] == "sign_mismatch") & inc["pre_contam"]).sum())
    big = inc[inc["bin"] == "1-3 km"]
    out["bin_1_3km_misses_45"] = [
        {"sat": r.sp3_sat, "campaign": r.campaign, "t_start": str(r.t_start)[:16],
         "step_sp3_m": round(r.step_sp3_m), "step_obs_m": round(r.step_obs_m, 1),
         "gap_day": round(r.gap_day, 2), "n_other_in_interval": int(r.n_other_events_in_interval),
         "n_events_in_pre_window": int(r.n_events_in_pre_window),
         "n_large_steps_pre_window_any_verdict": int(r.n_large_steps_pre_window_any_verdict),
         "class": r.class_45}
        for r in big[~big["det_S_45"]].itertuples()]
    ratio = (inc["step_obs_m"] / inc["step_sp3_m"])
    out["obs_over_sp3_ratio_median_by_bin"] = {b: round(float(ratio[inc["bin"] == b].median()), 2)
                                              for b in LAB[:5]}
    return out


# ════════════════════════════════════════════════════════════════════════════
# 偽事件：重播 review3 RNG；對稱判準；門檻掃描
# ════════════════════════════════════════════════════════════════════════════
def pseudo_events(tle, rec):
    rng = np.random.default_rng(42)            # Draw C：同 docs/fs7_supplement_tables.py（S9_pseudo）
    ev_t = {s: [] for s in tle}
    for _, r in rec.iterrows():
        ev_t[r["sp3_sat"]].append(to_day(r["t_start"]))
    rows = []
    for sat, (t, a) in tle.items():
        evd = np.array(ev_t[sat]) if ev_t[sat] else np.array([0.0])
        cand = t[(t > t.min() + 3) & (t < t.max() - 3)]
        for tc in rng.choice(cand, size=min(200, len(cand)), replace=False):
            if np.abs(evd - tc).min() < 2.0:
                continue
            step, gap, adot, ok = tle_step(t, a, tc, tc)
            if ok:
                rows.append({"sp3_sat": sat, "t_day": float(tc), "step_m": step, "gap_day": gap})
    p = pd.DataFrame(rows)
    p["thr3s_m"] = p["sp3_sat"].map(SIGMA3_NEW_M)
    fp45 = int((p["step_m"].abs() > THR_OLD_M).sum()); fp3 = int((p["step_m"].abs() > p["thr3s_m"]).sum())
    assert len(p) == 1145 and round(fp45 / len(p), 3) == 0.052 and round(fp3 / len(p), 3) == 0.548,         (len(p), fp45, fp3)                    # 核對 fs7_supplement_tables.json S9_pseudo.pooled
    return p


def symmetric_rules(d, p):
    inc = d[d["computable"]]
    p_pos = float((inc["step_sp3_m"] > 0).mean())
    n_e, n_p = len(inc), len(p)
    out = {"p_positive_sign_real_events": round(p_pos, 3), "n_events": n_e, "n_pseudo": n_p}
    for tag, thr_e, thr_p in (("45 m", THR_OLD_M, THR_OLD_M), ("unified 3σ", inc["thr3s_m"], p["thr3s_m"])):
        tp_s = int((inc["step_obs_m"].abs().gt(thr_e) & inc["sign_ok"]).sum())
        tp_u = int(inc["step_obs_m"].abs().gt(thr_e).sum())
        fp_u = int(p["step_m"].abs().gt(thr_p).sum())
        fp_pos = int(p["step_m"].gt(thr_p).sum()); fp_neg = int((-p["step_m"]).gt(thr_p).sum())
        fpr_s = (p_pos * fp_pos + (1 - p_pos) * fp_neg) / n_p
        fp_s_eff = fpr_s * n_p
        rec_s, rec_u = tp_s / n_e, tp_u / n_e
        out[tag] = {
            "original_asymmetric": {"TP": tp_s, "FP": fp_u, "recall": round(rec_s, 3),
                                    "FPR": round(fp_u / n_p, 3)},
            "U_sign_free_both": {"TP": tp_u, "FN": n_e - tp_u, "FP": fp_u, "TN": n_p - fp_u,
                                 "recall": round(rec_u, 3), "recall_wilson": [round(x, 3) for x in wilson(tp_u, n_e)],
                                 "FPR": round(fp_u / n_p, 3), "FPR_wilson": [round(x, 3) for x in wilson(fp_u, n_p)],
                                 "precision_sample": round(tp_u / (tp_u + fp_u), 3)},
            "S_sign_constrained_both": {"TP": tp_s, "FN": n_e - tp_s, "FP_expected": round(fp_s_eff, 1),
                                        "FP_if_hyp_positive": fp_pos, "FP_if_hyp_negative": fp_neg,
                                        "recall": round(rec_s, 3),
                                        "recall_wilson": [round(x, 3) for x in wilson(tp_s, n_e)],
                                        "FPR": round(fpr_s, 3),
                                        "FPR_wilson": [round(x, 3) for x in wilson(int(round(fp_s_eff)), n_p)],
                                        "precision_sample": round(tp_s / (tp_s + fp_s_eff), 3)},
        }
    return out


def threshold_sweep(d, p, rng):
    inc = d[d["computable"]]
    p_pos = float((inc["step_sp3_m"] > 0).mean())
    se_abs = inc["step_obs_m"].abs().values
    se_sgn = (inc["step_obs_m"] * np.sign(inc["step_sp3_m"])).values      # 同號為正
    sp = p["step_m"].values
    thr = np.unique(np.round(np.logspace(0, np.log10(2000), 81), 2))
    rows = []
    for th in thr:
        rU = float((se_abs > th).mean()); rS = float((se_sgn > th).mean())
        fU = float((np.abs(sp) > th).mean())
        fS = float(p_pos * (sp > th).mean() + (1 - p_pos) * (-sp > th).mean())
        rows.append({"thr_m": th, "recall_U": rU, "FPR_U": fU, "recall_S": rS, "FPR_S": fS,
                     "precision_U_sample": rU * len(se_abs) / max(rU * len(se_abs) + fU * len(sp), 1e-9),
                     "precision_S_sample": rS * len(se_abs) / max(rS * len(se_abs) + fS * len(sp), 1e-9)})
    sw = pd.DataFrame(rows)
    sw.to_csv(BM / "fs7_review5_threshold_sweep.csv", index=False, float_format="%.5g")

    def aucs(ea, es, pp):
        aU = mw_auc(ea, np.abs(pp))
        aS = p_pos * mw_auc(es, pp) + (1 - p_pos) * mw_auc(es, -pp)
        return aU, aS
    aU, aS = aucs(se_abs, se_sgn, sp)
    # 兩樣本各自 i.i.d. 自助（偽事件按衛星分層重抽）
    bs = []
    sat_idx = {s: np.where(p["sp3_sat"].values == s)[0] for s in p["sp3_sat"].unique()}
    for _ in range(B_BOOT):
        ie = rng.integers(0, len(se_abs), len(se_abs))
        ip = np.concatenate([rng.choice(v, len(v), replace=True) for v in sat_idx.values()])
        bs.append(aucs(se_abs[ie], se_sgn[ie], sp[ip]))
    bs = np.array(bs)
    # Youden 最佳門檻（事後、僅供參考）
    jU = sw["recall_U"] - sw["FPR_U"]; jS = sw["recall_S"] - sw["FPR_S"]
    out = {"AUC_U": round(aU, 3), "AUC_U_ci": [round(float(np.percentile(bs[:, 0], q)), 3) for q in (2.5, 97.5)],
           "AUC_S": round(aS, 3), "AUC_S_ci": [round(float(np.percentile(bs[:, 1], q)), 3) for q in (2.5, 97.5)],
           "youden_U": sw.loc[jU.idxmax(), ["thr_m", "recall_U", "FPR_U"]].round(3).to_dict(),
           "youden_S": sw.loc[jS.idxmax(), ["thr_m", "recall_S", "FPR_S"]].round(3).to_dict(),
           "at_45m": sw.iloc[(sw["thr_m"] - 45).abs().argmin()].round(3).to_dict(),
           "fpr_le_0.05": {
               "U": sw[sw["FPR_U"] <= 0.05].iloc[0][["thr_m", "recall_U", "FPR_U"]].round(3).to_dict(),
               "S": sw[sw["FPR_S"] <= 0.05].iloc[0][["thr_m", "recall_S", "FPR_S"]].round(3).to_dict()},
           "fpr_le_0.01": {
               "U": sw[sw["FPR_U"] <= 0.01].iloc[0][["thr_m", "recall_U", "FPR_U"]].round(3).to_dict(),
               "S": sw[sw["FPR_S"] <= 0.01].iloc[0][["thr_m", "recall_S", "FPR_S"]].round(3).to_dict()},
           "precision_note": "sample precision uses the sample ratio 96 events : 1,145 pseudo-events "
                             "and is prevalence-dependent; it is not an operational precision."}
    return out, sw


def draw_sweep(sw, res):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(10.5, 4.2))
    ax[0].plot(sw["FPR_U"], sw["recall_U"], "-", c="#1565C0",
               label=f"sign-free both sides (AUC {res['AUC_U']:.2f})")
    ax[0].plot(sw["FPR_S"], sw["recall_S"], "-", c="#C62828",
               label=f"sign-constrained both sides (AUC {res['AUC_S']:.2f})")
    for col_r, col_f, c in (("recall_U", "FPR_U", "#1565C0"), ("recall_S", "FPR_S", "#C62828")):
        i = (sw["thr_m"] - 45).abs().idxmin()
        ax[0].plot(sw.loc[i, col_f], sw.loc[i, col_r], "o", c=c, ms=6)
    ax[0].plot([0, 1], [0, 1], ":", c="gray", lw=0.8)
    ax[0].set_xlabel("false-positive rate (pseudo-events)"); ax[0].set_ylabel("recall (96 real events)")
    ax[0].set_title("ROC; dots: 45 m threshold"); ax[0].legend(fontsize=8); ax[0].grid(alpha=.25)
    ax[1].plot(sw["thr_m"], sw["recall_S"], "-", c="#C62828", label="recall (S)")
    ax[1].plot(sw["thr_m"], sw["FPR_S"], "--", c="#C62828", label="FPR (S)")
    ax[1].plot(sw["thr_m"], sw["recall_U"], "-", c="#1565C0", label="recall (U)")
    ax[1].plot(sw["thr_m"], sw["FPR_U"], "--", c="#1565C0", label="FPR (U)")
    ax[1].axvline(45, c="gray", lw=0.8, ls=":")
    ax[1].set_xscale("log"); ax[1].set_xlabel("threshold on |post-event residual| (m)")
    ax[1].set_ylabel("rate"); ax[1].set_title("threshold sweep"); ax[1].legend(fontsize=8); ax[1].grid(alpha=.25)
    fig.tight_layout()
    fig.savefig("docs/fig_fs7_threshold_sweep.png", dpi=200)
    fig.savefig("docs/fig_fs7_threshold_sweep.pdf")
    plt.close(fig)


# ════════════════════════════════════════════════════════════════════════════
# 注入：Δa90 內插與 CI、逐 cadence c、自相關分層
# ════════════════════════════════════════════════════════════════════════════
def recall_grid(tr, rng):
    amps = np.array(DA_GRID) * 1000.0
    rows, floors = [], []
    for (dec, band), g in tr.groupby(["decim", "drag_band"], observed=True):
        H = g.pivot_table(index="cluster", columns="da_km", values="hit", aggfunc="mean")
        H = H[sorted(H.columns)].dropna()
        M = H.values
        rec = M.mean(0)
        boot = np.empty((B_BOOT, M.shape[1]))
        for b in range(B_BOOT):
            boot[b] = M[rng.integers(0, len(M), len(M))].mean(0)
        lo, hi = np.percentile(boot, [2.5, 97.5], axis=0)
        for j, a in enumerate(amps):
            rows.append({"decim": int(dec), "drag": band, "da_m": a, "n_clusters": len(M),
                         "recall": round(rec[j], 3), "ci_lo": round(lo[j], 3), "ci_hi": round(hi[j], 3)})
        f_grid = grid_floor(rec, amps); f_int = interp90(rec, amps)
        bi = np.array([interp90(x, amps) for x in boot])
        bg = np.array([grid_floor(x, amps) for x in boot])
        floors.append({"decim": int(dec), "drag": band, "grid_floor_m": f_grid,
                       "interp_da90_m": round(f_int, 1),
                       "interp_ci95_m": [round(float(np.nanpercentile(bi, 2.5)), 1),
                                         round(float(np.nanpercentile(bi, 97.5)), 1)],
                       "frac_boot_same_grid_floor": round(float(np.mean(bg == f_grid)), 3),
                       "grid_floor_boot_range_m": [float(np.nanmin(bg)), float(np.nanmax(bg))],
                       "recall_at_grid_floor": round(float(rec[list(amps).index(f_grid)]), 3),
                       "recall_one_step_below": (round(float(rec[list(amps).index(f_grid) - 1]), 3)
                                                 if list(amps).index(f_grid) > 0 else None)})
    pd.DataFrame(rows).to_csv(BM / "fs7_review5_recall_grid.csv", index=False)
    return floors


def per_cadence_c(tr):
    out = {}
    for dec, g in tr.groupby("decim"):
        lls = []
        for c in CS:
            x = np.log10(snr_of(g, c).values); y = g["hit"].values.astype(float)
            lls.append(_logit_fit(x, y)[2] * len(g))
        lls = np.array(lls); i = int(np.argmax(lls)); ok = np.where(lls >= lls[i] - 1.9208)[0]
        out[f"decim_{int(dec)}"] = {"c_hat": round(float(CS[i]), 2),
                                    "profile_ci95": [round(float(CS[ok.min()]), 2), round(float(CS[ok.max()]), 2)],
                                    "ci_touches_grid_edge": bool(ok.min() == 0 or ok.max() == len(CS) - 1)}
    return out


def drag_term_table(tr):
    rows = []
    for (dec, band), g in tr.groupby(["decim", "drag_band"], observed=True):
        sig = g["sigma_km"].median() * 1000; ad = g["adot_kmday"].abs().median() * 1000
        dt = g["dt_day"].median()
        for c, tag in ((C_FULL, "full"), (C_CAL, "cal")):
            pass
        dterm = C_FULL * ad * dt; dterm_c = C_CAL * ad * dt
        rows.append({"decim": int(dec), "drag": band, "sigma_m": round(sig, 1),
                     "drag_term_m_c032": round(dterm, 1), "drag_term_m_c028": round(dterm_c, 1),
                     "sigma_eff_m_c032": round(float(np.hypot(sig, dterm)), 1),
                     "drag_share_of_var": round(float(dterm ** 2 / (sig ** 2 + dterm ** 2)), 2)})
    return rows


def autocorr_strat(tr, series, rng):
    # 逐窗逐降頻之 lag-1 自相關（同 fs7_injection_sweep_v2.diagnose_autocorr 定義）
    r1 = {}
    for nid, df in series.items():
        t_all = df["epoch_utc"].values.astype("datetime64[s]").astype(float) / 86400.0
        a_all = df["sma_km"].values
        for (s, e) in quiet_windows(df):
            for dd in (1, 2, 4):
                t, a = t_all[s:e:dd], a_all[s:e:dd]
                if len(a) < 10:
                    continue
                slope = np.polyfit(t, a, 1)[0]
                dres = np.diff(a - slope * (t - t[0])); dres = dres - np.median(dres)
                if np.std(dres) == 0:
                    continue
                r1[(nid, s, dd)] = float(np.corrcoef(dres[:-1], dres[1:])[0, 1])
    tr = tr.copy()
    tr["r1"] = [r1.get(k, np.nan) for k in zip(tr.norad, tr.win_start, tr.decim)]
    out = {"n_trials_with_r1": int(tr["r1"].notna().sum())}
    tr = tr[tr["r1"].notna()].copy()
    tr["r1_tercile"] = tr.groupby("decim")["r1"].transform(
        lambda x: pd.qcut(x, 3, labels=["low", "mid", "high"]).astype(str))
    tr["p_full"] = p_logit(snr_of(tr, C_FULL), S50_FULL, B_FULL)
    amps = np.array(DA_GRID) * 1000.0
    rows = []
    for (dec, tt), g in tr.groupby(["decim", "r1_tercile"]):
        rec = g.groupby("da_km")["hit"].mean().reindex(DA_GRID).values
        H = g.pivot_table(index="cluster", columns="da_km", values="hit", aggfunc="mean")[DA_GRID].dropna().values
        bi = [interp90(H[rng.integers(0, len(H), len(H))].mean(0), amps) for _ in range(500)]
        rows.append({"decim": int(dec), "r1_tercile": tt, "r1_median": round(float(g["r1"].median()), 2),
                     "n_windows": int(g["cluster"].nunique()),
                     "interp_da90_m": round(interp90(rec, amps), 1),
                     "interp_ci95_m": [round(float(np.nanpercentile(bi, q)), 1) for q in (2.5, 97.5)],
                     "obs_minus_pred_recall": round(float(g["hit"].mean() - g["p_full"].mean()), 3),
                     "obs_minus_pred_recall_da_le_200m": round(float(
                         g.loc[g.da_km <= 0.2, "hit"].mean() - g.loc[g.da_km <= 0.2, "p_full"].mean()), 3)})
    out["by_cadence_r1_tercile"] = rows
    # 加入 r1 共變量：校準期擬合、測試期評估（c 固定 0.28）
    cal, tst = tr[tr["win_t0"] < SPLIT], tr[tr["win_t0"] >= SPLIT]

    def irls(X, y):
        w = np.zeros(X.shape[1])
        for _ in range(100):
            pp = 1 / (1 + np.exp(-X @ w)); W = np.clip(pp * (1 - pp), 1e-6, None)
            dw = np.linalg.solve((X * W[:, None]).T @ X, X.T @ (y - pp)); w += dw
            if np.abs(dw).max() < 1e-10:
                break
        return w
    def design(g, with_r1):
        x = np.log10(snr_of(g, C_CAL).values)
        cols = [np.ones(len(g)), x] + ([g["r1"].values] if with_r1 else [])
        return np.column_stack(cols)
    res = {}
    for tag, wr in (("snr_eff", False), ("snr_eff_plus_r1", True)):
        w = irls(design(cal, wr), cal["hit"].values.astype(float))
        pt = 1 / (1 + np.exp(-design(tst, wr) @ w))
        res[tag] = {"coef": [round(float(v), 3) for v in w],
                    "heldout_logloss": round(logloss(tst["hit"].values.astype(float), pt), 4)}
    out["heldout_r1_covariate"] = res
    out["corr_r1_logsnr_eff"] = round(float(np.corrcoef(tr["r1"], np.log10(snr_of(tr, C_FULL)))[0, 1]), 3)
    return out


# ════════════════════════════════════════════════════════════════════════════
# 風暴期、傾角、站位維持名義幅度、執行時間
# ════════════════════════════════════════════════════════════════════════════
def storm_alignment():
    """21 件風暴期候選 × GFZ 3 小時 Kp（Matzka et al. 2021；definitive，D=2）。
    本機 space_weather_daily.csv 在 2024-04/05 之 kp_max 為填補值（恆 3.67），不可用。"""
    e = pd.read_csv(BM / "fs7_events_2024.csv")
    e["t_start"] = pd.to_datetime(e["t_start"], utc=True, format="mixed")
    v = e[e["verdict"] == "疑似真事件"].copy().sort_values("t_start")
    kp = pd.read_csv("data/space_weather/gfz_kp_3h_2024-04_05.csv")
    kp["t"] = pd.to_datetime(kp["time_utc"], utc=True)
    kp = kp.set_index("t").sort_index()
    lo0 = e["t_start"].min() - pd.Timedelta("1D")
    onset = kp.loc[lo0:].index[kp.loc[lo0:, "kp"] >= 7][0]     # 樣本期內大風暴主相起點（Kp ≥ 7）
    rows = []
    for r in v.itertuples():
        slot = kp.loc[:r.t_start].iloc[-1]
        prev24 = kp.loc[r.t_start - pd.Timedelta("24h"):r.t_start]
        rows.append({"sat": r.sp3_sat, "t_start": str(r.t_start)[:16], "step_m": round(r.step_m, 1),
                     "kp_slot": float(slot["kp"]), "kp_max_prev24h": float(prev24["kp"].max()),
                     "f107_obs": float(slot["f107_obs"]),
                     "h_from_main_onset": round((r.t_start - onset).total_seconds() / 3600, 1)})
    c = pd.DataFrame(rows)
    lo, hi = e["t_start"].min(), e["t_start"].max()
    return {"sample_span": [str(lo)[:10], str(hi)[:10]], "n_candidates": int(len(v)),
            "all_negative": bool((v["step_m"] < 0).all()),
            "step_range_m": [round(float(v["step_m"].min()), 1), round(float(v["step_m"].max()), 1)],
            "main_onset_kp_ge7": str(onset)[:16], "kp_peak": float(kp["kp"].max()),
            "kp_peak_time": str(kp["kp"].idxmax())[:16],
            "n_prev24h_kp_ge5": int((c["kp_max_prev24h"] >= 5).sum()),
            "n_prev24h_kp_ge4": int((c["kp_max_prev24h"] >= 4).sum()),
            "n_after_main_onset": int((c["h_from_main_onset"] >= 0).sum()),
            "n_before_main_onset": int((c["h_from_main_onset"] < 0).sum()),
            "candidates": rows}


def inclination_stats():
    frames = []
    for f, camp in (("fs7_events_2025raise.csv", "2025-07/08"), ("fs7_events_campaigns_20260825.csv", None),
                    ("fs7_events_2024.csv", "2024 storm")):
        e = pd.read_csv(BM / f)
        if camp:
            e["campaign"] = camp
        frames.append(e)
    e = pd.concat(frames, ignore_index=True)
    di = e["di_deg"].dropna()
    s = 1.4826 * np.median(np.abs(di - np.median(di)))
    thr = 4 * s
    e["inc_corr"] = e["di_deg"].abs() > thr
    ver = e[(e["verdict"] == "疑似真事件") & (e["campaign"] != "2024 storm")]
    rej = e[e["verdict"] != "疑似真事件"]
    return {"robust_sigma_di_deg": float(f"{s:.3g}"), "threshold_4sigma_deg": float(f"{thr:.3g}"),
            "verified_131_with_inc_corroboration": int(ver["inc_corr"].sum()),
            "verified_131_n": int(len(ver)),
            "rejected_with_inc_signature": int(rej["inc_corr"].sum()), "rejected_n": int(len(rej)),
            "rejected_with_inc_signature_by_reason": rej[rej["inc_corr"]]["reason"].value_counts().to_dict()}


def station_keeping_nominal():
    mu = 3.986004418e14; a = 6928e3; v = np.sqrt(mu / a)
    return {"dv_ms": 0.01, "a_m": a, "v_ms": round(v, 1), "da_m": round(2 * a * 0.01 / v, 1),
            "note": "nominal along-track Δa = 2aΔv/v for an assumed routine ΔV of 0.01 m/s; "
                    "not an observed event"}


def heldout_auc_ci(tr, rng):
    """時間切分測試集之 trial-level AUC 與叢集（衛星×窗）自助 CI；兩模型皆用校準期係數。"""
    tst = tr[tr["win_t0"] >= SPLIT].copy()
    y = tst["hit"].values.astype(int)
    p_d = p_logit(snr_of(tst, C_CAL).values, S50_CAL, B_CAL)
    p_a = p_logit((tst["da_km"] / tst["sigma_km"]).clip(1e-2, 1e4).values, 8.74, 4.38)
    cl = tst["cluster"].values; uniq = np.unique(cl)
    gi = {k: np.where(cl == k)[0] for k in uniq}
    def auc(yy, pp):
        return mw_auc(pp[yy == 1], pp[yy == 0])
    a_d, a_a = auc(y, p_d), auc(y, p_a)
    bs = []
    for _ in range(B_BOOT):
        idx = np.concatenate([gi[k] for k in rng.choice(uniq, len(uniq), replace=True)])
        bs.append((auc(y[idx], p_d[idx]), auc(y[idx], p_a[idx])))
    bs = np.array(bs); dd = bs[:, 0] - bs[:, 1]
    q = lambda v: [round(float(np.percentile(v, 2.5)), 4), round(float(np.percentile(v, 97.5)), 4)]
    return {"unit": "trial (6,996 test-split trials; positives = injected step flagged within tolerance)",
            "ties": "averaged ranks (Mann–Whitney)", "n_clusters": int(len(uniq)),
            "drag_aware": round(a_d, 4), "drag_aware_ci": q(bs[:, 0]),
            "amplitude_only": round(a_a, 4), "amplitude_only_ci": q(bs[:, 1]),
            "delta": round(a_d - a_a, 4), "delta_ci": q(dd)}


def runtime_probe(series, rng, n=150):
    nid = 44350; df = series[nid]
    t_all = df["epoch_utc"].values.astype("datetime64[s]").astype(float) / 86400.0
    a_all = df["sma_km"].values
    s, e = quiet_windows(df)[10]
    t, a = t_all[s:e], a_all[s:e]
    t0 = time.perf_counter()
    for i in range(n):
        one_trial(t, a, DA_GRID[i % len(DA_GRID)], rng)
    dt = (time.perf_counter() - t0) / n
    return {"sec_per_trial": round(dt, 4), "est_sweep_15774_trials_min": round(dt * 15774 / 60, 1)}


def main():
    T0 = time.perf_counter()
    rng = np.random.default_rng(42)
    result = {"timing_s": {}}
    rec = pd.read_csv(BM / "fs7_tle_recall_unified_20260825.csv")
    tr = pd.read_csv(BM / "fs7_injection_trials.csv")
    tr["cluster"] = tr["norad"].astype(str) + "_" + tr["win_start"].astype(str)
    series = load_series("space_db.duckdb")
    t0_map = {}
    for nid, df in series.items():
        ep = df["epoch_utc"].values
        for ws in tr.loc[tr.norad == nid, "win_start"].unique():
            t0_map[(nid, ws)] = pd.Timestamp(ep[int(ws)])
    tr["win_t0"] = [t0_map[(n, w)] for n, w in zip(tr.norad, tr.win_start)]
    tle = load_tle()

    t = time.perf_counter()
    print("M2/M5b 真實事件重算…")
    d = real_events(tle, rec)
    d.drop(columns=["t_start"]).assign(t_start=d["t_start"].astype(str)).to_csv(
        BM / "fs7_review5_event_decomposition.csv", index=False, float_format="%.4g", encoding="utf-8-sig")
    result["selection_bias"] = selection_bias(d)
    result["miss_decomposition"] = miss_decomposition(d)
    result["timing_s"]["real_events"] = round(time.perf_counter() - t, 1)
    for r in result["selection_bias"]["recall_bounds_by_bin"]:
        print("  ", r)
    print("   排除原因:", result["selection_bias"]["exclusion_reason_counts"])
    print("   多次點火:", result["miss_decomposition"]["multi_burn"])

    t = time.perf_counter()
    print("\nM7 偽事件重播與對稱判準…")
    p = pseudo_events(tle, rec)
    result["symmetric_rules"] = symmetric_rules(d, p)
    print(json.dumps(result["symmetric_rules"], ensure_ascii=False, indent=1))
    sweep, sw = threshold_sweep(d, p, rng)
    result["threshold_sweep"] = sweep
    draw_sweep(sw, sweep)
    print("   sweep:", json.dumps(sweep, ensure_ascii=False))
    result["timing_s"]["pseudo_and_sweep"] = round(time.perf_counter() - t, 1)

    t = time.perf_counter()
    print("\nM6 Δa90 內插與 CI…")
    result["da90_interpolated"] = recall_grid(tr, rng)
    for r in result["da90_interpolated"]:
        print("  ", r)
    result["timing_s"]["recall_grid"] = round(time.perf_counter() - t, 1)

    t = time.perf_counter()
    print("\nM4 逐 cadence c 與阻力模糊項…")
    result["per_cadence_c"] = per_cadence_c(tr)
    result["drag_term_by_condition"] = drag_term_table(tr)
    print("  ", result["per_cadence_c"])
    for r in result["drag_term_by_condition"]:
        print("  ", r)
    result["timing_s"]["per_cadence_c"] = round(time.perf_counter() - t, 1)

    t = time.perf_counter()
    print("\nM5a 自相關分層…")
    result["autocorr_stratification"] = autocorr_strat(tr, series, rng)
    print(json.dumps(result["autocorr_stratification"], ensure_ascii=False, indent=1))
    result["timing_s"]["autocorr"] = round(time.perf_counter() - t, 1)

    print("\nM8 / m3 / m12 / m13 …")
    result["storm_alignment"] = storm_alignment()
    st = {k: v for k, v in result["storm_alignment"].items() if k != "candidates"}
    print("  ", st)
    result["inclination"] = inclination_stats()
    print("  ", result["inclination"])
    result["station_keeping_nominal"] = station_keeping_nominal()
    inj20 = tr[tr.da_km == 0.02].groupby(["decim", "drag_band"], observed=True)["hit"].mean().round(3)
    result["injection_recall_at_20m"] = {f"{k[0]}x_{k[1]}": float(v) for k, v in inj20.items()}
    result["heldout_auc"] = heldout_auc_ci(tr, rng)
    print("  ", result["heldout_auc"])
    result["runtime_probe"] = runtime_probe(series, np.random.default_rng(7))
    print("  ", result["runtime_probe"])
    result["timing_s"]["total"] = round(time.perf_counter() - T0, 1)

    out = BM / "fs7_review5_analysis.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8", newline="\n")
    print(f"\n輸出：{out}（總耗時 {result['timing_s']['total']} s）")


if __name__ == "__main__":
    main()
