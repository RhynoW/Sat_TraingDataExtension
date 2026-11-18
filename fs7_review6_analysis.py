#!/usr/bin/env python3
"""
fs7_review6_analysis.py — 期刊審查 R2（paper_B_submission_ReviewV2）回應所需之補充分析
====================================================================================
對應審查意見：
  M1  「無 TLE 響應」之判定敏感性（比值門檻 0.3/0.5/0.7 × 觀察窗 3/5/7 d）、真實事件結果類別
      之叢集自助 CI（叢集＝衛星×campaign）、按衛星/campaign 之樣本數、與 |ȧ|、後段 TLE 數之關係
  M2  以 E1 特徵建立之簡單 logistic（leave-one-campaign-out）與 D1 描述性機率之比較
  M3  前段窗口污染之來源拆分：僅共模剔除之點火 / 僅已驗證點火 / 兩者；E1 召回、殘差、延遲
  M4  只用研討會版未使用之 85 件事件（非 2025-07/08）重算召回、FPR 與門檻掃描 AUC
  M5  rule S 假設符號比例 p₊ ∈ {0, 0.5, 0.521, 1} 之 FPR 與 AUC 敏感性
  M7  1× 之 c 擴大網格（上限 100）
  M8  替代拖曳代理：c·|ȧ|·Δt^p，p ∈ {0, 0.5, 1, 2}，校準期擬合 → 測試期 held-out
  m9  D1 之 CUSUM（κ, h）與 MAD 倍數敏感性：重播同一注入（同 seed、同窗、同注入位置）

輸入：同 fs7_review5_analysis.py；space_db.duckdb（read_only，TLE 曆元 < 2026-08-25）
輸出：data/benchmark/fs7_review6_analysis.json
      data/benchmark/fs7_review6_detector_sensitivity.csv（m9 逐條件 Δa90 與誤報）
用法：python fs7_review6_analysis.py
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

from fs7_injection_sweep import (DA_GRID, DECIM, WIN, STRIDE, MIN_PTS, TOL, quiet_windows,
                                 window_stats, FS7_NORADS)
from fs7_injection_sweep_v2 import _logit_fit
from fs7_tle_recall_unified import SIGMA3_NEW_M, THR_OLD_M, PRE_D, POST_D, GAP_H, MIN_PRE, wilson
from fs7_review5_analysis import (BM, SPLIT, LAB, LARGE_STEP_M, TLE_CUTOFF, to_day, snr_of, p_logit,
                                  logloss, interp90, mw_auc, load_tle, real_events, pseudo_events,
                                  C_CAL, S50_CAL, B_CAL)
from statistical_detectors import cusum, mad3sigma

B_BOOT = 2000


# ════════════════════════════════════════════════════════════════════════════
# 真實事件：逐 TLE 響應比值（供 M1 敏感性）與污染來源（M3）
# ════════════════════════════════════════════════════════════════════════════
def load_events():
    e25 = pd.read_csv(BM / "fs7_events_2025raise.csv")
    e25 = e25[e25["verdict"] == "疑似真事件"].copy()
    e25["campaign"] = "2025-07/08"
    enew = pd.read_csv(BM / "fs7_events_campaigns_20260825.csv")
    enew = enew[enew["verdict"] == "疑似真事件"].copy()
    ev = pd.concat([e25, enew], ignore_index=True)
    for c in ("t_start", "t_end"):
        ev[c] = pd.to_datetime(ev[c], utc=True, format="mixed")
    allc = pd.concat([pd.read_csv(BM / "fs7_events_2025raise.csv"),
                      pd.read_csv(BM / "fs7_events_campaigns_20260825.csv")], ignore_index=True)
    allc["t_start"] = pd.to_datetime(allc["t_start"], utc=True, format="mixed")
    allc = allc[allc["step_m"].abs() >= LARGE_STEP_M].copy()
    allc["verified"] = allc["verdict"] == "疑似真事件"
    allc["common_mode"] = allc["reason"].astype(str).str.contains("共模")
    return ev, allc


def response_ratios(tle, ev, d, max_days=7.0):
    """對每件可評估事件回傳後段 [t_end+2h, t_end+max_days] 各 TLE 之 (Δt_day, ratio)。"""
    out = {}
    for i, r in ev.iterrows():
        if not d.loc[i, "computable"]:
            continue
        t, a = tle[r["sp3_sat"]]
        t0, t1 = to_day(r["t_start"]), to_day(r["t_end"])
        pre = (t >= t0 - PRE_D) & (t <= t0 - GAP_H / 24)
        co = np.polyfit(t[pre], a[pre], 1)
        pm = (t >= t1 + GAP_H / 24) & (t <= t1 + max_days)
        tt = t[pm]; o = np.argsort(tt)
        out[i] = (tt[o] - t1, ((a[pm] - np.polyval(co, t[pm])) * 1000.0 / float(r["step_m"]))[o])
    return out


def classify(dts, ratios, cut, win):
    m = dts <= win
    rr = ratios[m]
    if not len(rr):
        return "n/a"
    lo, hi = cut, 1.0 / cut
    good = (rr >= lo) & (rr <= hi)
    if good[0]:
        return "immediate"
    if good.any():
        return "delayed"
    if np.all(np.abs(rr) < cut):
        return "none"
    return "other"


def cluster_boot_props(df, col, classes, rng, cluster="cluster"):
    cl = df[cluster].values; uniq = np.unique(cl)
    gi = {k: np.where(cl == k)[0] for k in uniq}
    vals = df[col].values
    pt = {c: float(np.mean(vals == c)) for c in classes}
    bs = {c: [] for c in classes}
    for _ in range(B_BOOT):
        idx = np.concatenate([gi[k] for k in rng.choice(uniq, len(uniq), replace=True)])
        v = vals[idx]
        for c in classes:
            bs[c].append(np.mean(v == c))
    return {c: {"n": int(np.sum(vals == c)), "prop": round(pt[c], 3),
                "ci95": [round(float(np.percentile(bs[c], 2.5)), 3), round(float(np.percentile(bs[c], 97.5)), 3)]}
            for c in classes}


def m1_analysis(d, ev, rr, rng):
    out = {}
    d = d.copy()
    d["cluster"] = d["sp3_sat"] + "|" + d["campaign"]
    # (a) 全 131 件之結果類別（45 m、rule S），叢集自助 CI
    classes = ["excl_pre", "excl_post", "detected", "below_threshold", "sign_mismatch"]
    out["n_clusters_sat_campaign"] = int(d["cluster"].nunique())
    out["outcome_classes_131_45m"] = cluster_boot_props(d, "class_45", classes, rng)
    # (b) 可評估 96 件：TLE 響應類別（預設定義）× 污染，CI
    inc = d[d["computable"]].copy()
    inc["contam"] = inc["n_large_steps_pre_window_any_verdict"] > 0
    cl50 = inc[(~inc["contam"]) & (inc["amp_m"] >= 50) & (inc["amp_m"] < 300)]
    out["clean_50_300m_response_default"] = cluster_boot_props(
        cl50, "tle_response", ["immediate", "delayed", "none", "other"], rng)
    out["clean_50_300m_n"] = int(len(cl50))
    out["clean_50_300m_by_satellite"] = cl50.groupby("sp3_sat")["tle_response"].value_counts().unstack(fill_value=0).to_dict("index")
    out["clean_50_300m_by_campaign"] = cl50.groupby("campaign")["tle_response"].value_counts().unstack(fill_value=0).to_dict("index")
    # (c) 判定敏感性：比值門檻 × 觀察窗
    sens = []
    for cut in (0.3, 0.5, 0.7):
        for win in (3.0, 5.0, 7.0):
            cls = {i: classify(*rr[i], cut, win) for i in cl50.index}
            vc = pd.Series(cls).value_counts()
            big = inc[(~inc["contam"]) & (inc["amp_m"] >= 300)]
            clsb = pd.Series({i: classify(*rr[i], cut, win) for i in big.index}).value_counts()
            sens.append({"ratio_cut": cut, "window_d": win,
                         "clean_50_300_none": int(vc.get("none", 0)),
                         "clean_50_300_delayed": int(vc.get("delayed", 0)),
                         "clean_50_300_immediate": int(vc.get("immediate", 0)),
                         "clean_50_300_other": int(vc.get("other", 0)),
                         "clean_ge300_immediate": int(clsb.get("immediate", 0)),
                         "clean_ge300_n": int(len(big))})
    out["response_sensitivity"] = sens
    # (d) 「無響應」與 |ȧ|、後段 TLE 數、gap 之關係（clean 50–300 m）
    cl50 = cl50.copy()
    cl50["n_post_3d"] = [int((rr[i][0] <= 3.0).sum()) for i in cl50.index]
    g = cl50.groupby(cl50["tle_response"] == "none")
    out["none_vs_other_covariates"] = {
        ("none" if k else "not_none"): {"n": int(len(v)),
                                         "median_abs_adot_m_day": round(float(v["adot_kmday"].abs().median() * 1000), 1),
                                         "median_n_post_tle_3d": float(v["n_post_3d"].median()),
                                         "median_gap_day": round(float(v["gap_day"].median()), 2),
                                         "median_amp_m": round(float(v["amp_m"].median()), 1),
                                         "frac_negative_step": round(float((v["step_sp3_m"] < 0).mean()), 2)}
        for k, v in g}
    # (e) 未偵測（45 m）是否由門檻造成：clean 50–300 m 中 |residual| 之最大可能（在 3 d 內任一 TLE）
    mx = [float(np.max(np.abs(rr[i][1][rr[i][0] <= 3.0] * d.loc[i, "step_sp3_m"]))) for i in cl50.index]
    out["clean_50_300_max_abs_residual_3d_m"] = {"median": round(float(np.median(mx)), 1),
                                                 "n_below_45m": int(np.sum(np.array(mx) < 45))}
    return out


def m3_analysis(d, ev, allc):
    inc = d[d["computable"]].copy()
    src = []
    for i in inc.index:
        r = ev.loc[i]; t0 = r["t_start"]
        g = allc[(allc["sp3_sat"] == r["sp3_sat"]) & (allc["t_start"] >= t0 - pd.Timedelta(days=PRE_D))
                 & (allc["t_start"] < t0)]
        if not len(g):
            src.append("clean")
        elif g["verified"].all():
            src.append("verified_only")
        elif (~g["verified"]).all():
            src.append("rejected_only")
        else:
            src.append("both")
        inc.loc[i, "n_rej_cm"] = int((~g["verified"] & g["common_mode"]).sum())
    inc["src"] = src
    inc["ratio"] = inc["step_obs_m"] / inc["step_sp3_m"]
    inc["post_delay_h"] = inc["h_to_next_tle"]
    out = {"n_with_common_mode_rejected_burn_in_prewindow": int((inc["n_rej_cm"] > 0).sum())}
    rows = []
    for s_, g in inc.groupby("src"):
        rows.append({"source": s_, "n": int(len(g)),
                     "recall_45_S": round(float(g["det_S_45"].mean()), 3),
                     "recall_45_U": round(float(g["det_U_45"].mean()), 3),
                     "wrong_sign": int((g["class_45"] == "sign_mismatch").sum()),
                     "median_abs_residual_m": round(float(g["step_obs_m"].abs().median()), 1),
                     "median_ratio": round(float(g["ratio"].median()), 2),
                     "median_abs_adot_m_day": round(float(g["adot_kmday"].abs().median() * 1000), 1),
                     "median_delay_first_post_tle_h": round(float(g["post_delay_h"].median()), 1),
                     "median_amp_m": round(float(g["amp_m"].median()), 1)})
    out["by_source"] = rows
    cm = inc[inc["n_rej_cm"] > 0]
    out["common_mode_contaminated"] = {"n": int(len(cm)), "recall_45_S": round(float(cm["det_S_45"].mean()), 3),
                                       "wrong_sign": int((cm["class_45"] == "sign_mismatch").sum()),
                                       "by_bin": cm["bin"].value_counts().reindex(LAB[:5]).fillna(0).astype(int).to_dict()}
    return out


def m4_independent(d, p, rng):
    inc = d[d["computable"]]
    sub = inc[inc["campaign"] != "2025-07/08"]
    p_pos = float((inc["step_sp3_m"] > 0).mean())
    sp = p["step_m"].values
    res = {"n_events_85_subset_evaluable": int(len(sub)), "n_events_46_subset_evaluable": int(len(inc) - len(sub))}
    for tag, g in (("independent_85", sub), ("conference_46", inc[inc["campaign"] == "2025-07/08"]), ("all_96", inc)):
        r = {}
        for thr_name, thr in (("45m", THR_OLD_M),):
            tpS = int(((g["step_obs_m"].abs() > thr) & g["sign_ok"]).sum())
            tpU = int((g["step_obs_m"].abs() > thr).sum())
            r[f"recall_S_{thr_name}"] = round(tpS / len(g), 3)
            r[f"recall_S_{thr_name}_wilson"] = [round(x, 3) for x in wilson(tpS, len(g))]
            r[f"recall_U_{thr_name}"] = round(tpU / len(g), 3)
        r["recall_S_by_bin"] = {b: {"n": int(len(x)), "recall": round(float(x["det_S_45"].mean()), 3)}
                                for b, x in g.groupby("bin", observed=True)}
        ea = g["step_obs_m"].abs().values
        es = (g["step_obs_m"] * np.sign(g["step_sp3_m"])).values
        r["AUC_U"] = round(mw_auc(ea, np.abs(sp)), 3)
        r["AUC_S"] = round(p_pos * mw_auc(es, sp) + (1 - p_pos) * mw_auc(es, -sp), 3)
        res[tag] = r
    # 獨立子集之門檻掃描：45 m 與 Youden
    ea = sub["step_obs_m"].abs().values
    thr = np.unique(np.round(np.logspace(0, np.log10(2000), 81), 2))
    j = [(np.mean(ea > t) - np.mean(np.abs(sp) > t), t) for t in thr]
    best = max(j)
    res["independent_85_youden_U"] = {"thr_m": float(best[1]), "J": round(best[0], 3)}
    res["FPR_45m_U"] = round(float(np.mean(np.abs(sp) > THR_OLD_M)), 3)
    return res


def m5_sign_sensitivity(d, p):
    inc = d[d["computable"]]
    sp = p["step_m"].values
    es = (inc["step_obs_m"] * np.sign(inc["step_sp3_m"])).values
    out = []
    for pp in (0.0, 0.5, float((inc["step_sp3_m"] > 0).mean()), 1.0):
        row = {"p_positive": round(pp, 3)}
        for nm, thr in (("45m", THR_OLD_M), ("3s", None)):
            th = p["thr3s_m"].values if thr is None else thr
            row[f"FPR_S_{nm}"] = round(float(pp * np.mean(sp > th) + (1 - pp) * np.mean(-sp > th)), 3)
        row["AUC_S"] = round(pp * mw_auc(es, sp) + (1 - pp) * mw_auc(es, -sp), 3)
        out.append(row)
    return {"rows": out, "pseudo_step_median_m": round(float(np.median(sp)), 2),
            "frac_pseudo_positive": round(float(np.mean(sp > 0)), 3)}


def m2_e1_logistic(d):
    """E1 偵測（45 m、rule S）之簡單 logistic；leave-one-campaign-out。"""
    inc = d[d["computable"]].copy()
    inc["contam"] = (inc["n_large_steps_pre_window_any_verdict"] > 0).astype(float)
    inc["x_amp"] = np.log10(inc["amp_m"].clip(1))
    y = inc["det_S_45"].astype(float).values

    def irls(X, yy, ridge=1e-3):
        w = np.zeros(X.shape[1])
        for _ in range(200):
            pp = 1 / (1 + np.exp(-np.clip(X @ w, -30, 30))); W = np.clip(pp * (1 - pp), 1e-6, None)
            H = (X * W[:, None]).T @ X + ridge * np.eye(X.shape[1])
            dw = np.linalg.solve(H, X.T @ (yy - pp) - ridge * w); w += dw
            if np.abs(dw).max() < 1e-9:
                break
        return w
    feats = {"log_amp": ["x_amp"], "log_amp_plus_contam": ["x_amp", "contam"]}
    res = {}
    for name, cols in feats.items():
        pred = np.zeros(len(inc))
        for camp in inc["campaign"].unique():
            tr_ = inc["campaign"] != camp
            X = np.column_stack([np.ones(tr_.sum())] + [inc.loc[tr_, c].values for c in cols])
            w = irls(X, y[tr_.values])
            Xt = np.column_stack([np.ones((~tr_).sum())] + [inc.loc[~tr_, c].values for c in cols])
            pred[(~tr_).values] = 1 / (1 + np.exp(-Xt @ w))
        res[name] = {"loco_logloss": round(logloss(y, pred), 3), "loco_brier": round(float(np.mean((pred - y) ** 2)), 3),
                     "loco_auc": round(mw_auc(pred[y == 1], pred[y == 0]), 3)}
    pD1 = inc["p_pred_full"].values
    res["D1_descriptive_probability"] = {"logloss": round(logloss(y, pD1), 3),
                                         "brier": round(float(np.mean((pD1 - y) ** 2)), 3),
                                         "auc": round(mw_auc(pD1[y == 1], pD1[y == 0]), 3)}
    pr = np.full(len(y), y.mean())
    res["base_rate"] = {"logloss": round(logloss(y, pr), 3), "brier": round(float(np.mean((pr - y) ** 2)), 3)}
    res["note"] = "LOCO = leave-one-campaign-out (5 folds); D1 probability uses fixed descriptive-refit coefficients (no refit)."
    return res


# ════════════════════════════════════════════════════════════════════════════
# 注入：M7 擴大網格、M8 替代拖曳代理
# ════════════════════════════════════════════════════════════════════════════
def snr_nc(g, c, pw=1.0):
    """不截斷之 SNR_eff（避免 clip(1e-2) 在大 c 時形成人為平台）。"""
    return (g["da_km"] / np.hypot(g["sigma_km"], c * g["adot_kmday"].abs() * g["dt_day"] ** pw)).values


def snr_drag_only(g, pw=1.0):
    return (g["da_km"] / (g["adot_kmday"].abs() * g["dt_day"] ** pw)).values


def m7_wide_grid(tr):
    cs = np.logspace(-1.3, 2.0, 67)
    out = {"note": "unclipped SNR; c→∞ limit = drag-only model Δa/(|ȧ|Δt) with σ_TLE dropped"}
    for dec, g in list(tr.groupby("decim")) + [("all", tr)]:
        y = g["hit"].values.astype(float)
        lls = np.array([_logit_fit(np.log10(snr_nc(g, c)), y)[2] * len(g) for c in cs])
        ll_inf = _logit_fit(np.log10(snr_drag_only(g)), y)[2] * len(g)
        i = int(np.argmax(lls)); ok = np.where(lls >= lls[i] - 1.9208)[0]
        ll032 = lls[int(np.argmin(np.abs(cs - 0.32)))]
        out[f"decim_{dec}"] = {"c_hat": round(float(cs[i]), 2),
                               "ci95": [round(float(cs[ok.min()]), 2),
                                        "inf" if ok.max() == len(cs) - 1 else round(float(cs[ok.max()]), 2)],
                               "ll_at_c_hat": round(float(lls[i]), 1), "ll_at_c032": round(float(ll032), 1),
                               "ll_drag_only_limit": round(float(ll_inf), 1),
                               "interior_max": bool(lls[i] - ll_inf > 1.9208 and i < len(cs) - 1)}
    # 截斷假象之示範（全資料）
    y = tr["hit"].values.astype(float)
    demo = []
    for c in (0.32, 10, 20, 50, 100):
        sn = snr_nc(tr, c)
        demo.append({"c": c, "frac_below_1e-2": round(float(np.mean(sn < 1e-2)), 3),
                     "ll_unclipped": round(_logit_fit(np.log10(sn), y)[2] * len(tr), 1),
                     "ll_clipped_1e-2": round(_logit_fit(np.log10(np.clip(sn, 1e-2, 1e4)), y)[2] * len(tr), 1)})
    out["clip_artifact_demo"] = demo
    return out


def m8_drag_proxies(tr):
    cal, tst = tr[tr["win_t0"] < SPLIT], tr[tr["win_t0"] >= SPLIT]
    cs = np.logspace(-3, 3, 97)
    yc = cal["hit"].values.astype(float); yt = tst["hit"].values.astype(float)
    out = []
    for pw in (0.0, 0.5, 1.0, 2.0):
        ll = np.array([_logit_fit(np.log10(snr_nc(cal, c, pw)), yc)[2] for c in cs])
        ll_inf = _logit_fit(np.log10(snr_drag_only(cal, pw)), yc)[2]
        i = int(np.argmax(ll))
        if ll_inf >= ll[i]:
            s50, beta, _ = _logit_fit(np.log10(snr_drag_only(cal, pw)), yc)
            pt = p_logit(snr_drag_only(tst, pw), s50, beta); c_rep = "inf (drag-only)"
        else:
            c_hat = float(cs[i])
            s50, beta, _ = _logit_fit(np.log10(snr_nc(cal, c_hat, pw)), yc)
            pt = p_logit(snr_nc(tst, c_hat, pw), s50, beta); c_rep = round(c_hat, 3)
        out.append({"proxy": f"c·|ȧ|·Δt^{pw:g}", "exponent": pw, "c_hat_cal": c_rep,
                    "cal_mean_ll": round(float(max(ll[i], ll_inf)), 5),
                    "heldout_logloss": round(logloss(yt, pt), 4),
                    "heldout_auc": round(mw_auc(pt[yt == 1], pt[yt == 0]), 4)})
    for nm, fn in (("drag-only Δa/(|ȧ|Δt)", lambda g: snr_drag_only(g, 1.0)),
                   ("none (Δa/σ)", lambda g: (g["da_km"] / g["sigma_km"]).values)):
        s50, beta, _ = _logit_fit(np.log10(fn(cal)), yc)
        pt = p_logit(fn(tst), s50, beta)
        out.append({"proxy": nm, "exponent": None, "heldout_logloss": round(logloss(yt, pt), 4),
                    "heldout_auc": round(mw_auc(pt[yt == 1], pt[yt == 0]), 4)})
    return out


def m8_da90_compare(tr):
    """全資料擬合 Δt^1 與 Δt^0.5 兩形式之模型隱含 Δa90，與內插經驗值（review5）比較。"""
    r5 = json.loads((BM / "fs7_review5_analysis.json").read_text(encoding="utf-8"))
    emp = {(r["decim"], r["drag"]): r["interp_da90_m"] for r in r5["da90_interpolated"]}
    y = tr["hit"].values.astype(float)
    cs = np.logspace(-2, 2, 81)
    out = {}
    for pw in (1.0, 0.5):
        ll = [_logit_fit(np.log10(snr_nc(tr, c, pw)), y)[2] for c in cs]
        c_hat = float(cs[int(np.argmax(ll))])
        s50, beta, _ = _logit_fit(np.log10(snr_nc(tr, c_hat, pw)), y)
        snr90 = s50 * 10 ** (np.log(9) / beta)
        rows = []
        for (dd, band), g in tr.groupby(["decim", "drag_band"], observed=True):
            sig, ad, dt = g["sigma_km"].median(), g["adot_kmday"].abs().median(), g["dt_day"].median()
            pred = snr90 * np.hypot(sig, c_hat * ad * dt ** pw) * 1000
            rows.append({"cond": f"{int(dd)}x_{band}", "model_da90_m": round(float(pred)),
                         "interp_da90_m": emp[(int(dd), band)],
                         "ratio_interp_over_model": round(float(emp[(int(dd), band)] / pred), 2)})
        rr = np.array([r["ratio_interp_over_model"] for r in rows])
        out[f"dt_pow_{pw:g}"] = {"c_hat": round(c_hat, 3), "snr90": round(float(snr90), 2), "rows": rows,
                                 "max_abs_log_ratio": round(float(np.max(np.abs(np.log(rr)))), 3),
                                 "ratio_range": [float(rr.min()), float(rr.max())]}
    return out


# ════════════════════════════════════════════════════════════════════════════
# m9：D1 參數敏感性（同 seed 重播注入位置）
# ════════════════════════════════════════════════════════════════════════════
def load_series_cut():
    con = duckdb.connect("space_db.duckdb", read_only=True)
    out = {}
    for nid in FS7_NORADS:
        df = con.execute("SELECT epoch_utc, sma_km FROM raw_tle_archive WHERE norad_id=? AND sma_km IS NOT NULL "
                         "AND epoch_utc < ? ORDER BY epoch_utc", [nid, TLE_CUTOFF]).df()
        out[nid] = df.drop_duplicates("epoch_utc").reset_index(drop=True)
    con.close()
    return out


def d1_flags(sma, kappa, h, zmad):
    da = np.diff(sma, prepend=sma[0])
    f = set(mad3sigma(da, z_thresh=zmad)["events"].tolist()) | set(cusum(da, k=kappa, h=h)["events"].tolist())
    return np.array(sorted(f), int)


def m9_detector_sensitivity(series, base_trials):
    settings = [("baseline", 0.5, 5.0, 3.0), ("h=4", 0.5, 4.0, 3.0), ("h=6", 0.5, 6.0, 3.0),
                ("kappa=0.25", 0.25, 5.0, 3.0), ("kappa=1.0", 1.0, 5.0, 3.0), ("MAD 4σ", 0.5, 5.0, 4.0)]
    # 先固定注入位置：重播 fs7_injection_sweep 之 RNG 序列（每 trial 一次 integers）
    rng = np.random.default_rng(42)
    plan = []
    for nid, df in series.items():
        t_all = df["epoch_utc"].values.astype("datetime64[s]").astype(float) / 86400.0
        a_all = df["sma_km"].values
        for (s, e) in quiet_windows(df):
            for dd in DECIM:
                t, a = t_all[s:e:dd], a_all[s:e:dd]
                if len(a) < MIN_PTS:
                    continue
                sigma, adot, dtm = window_stats(t, a)
                if sigma <= 0:
                    continue
                for da_km in DA_GRID:
                    inj = int(rng.integers(len(a) // 3, 2 * len(a) // 3))
                    plan.append((nid, s, dd, da_km, inj, t, a))
    assert len(plan) == len(base_trials), (len(plan), len(base_trials))
    rows, summ = [], []
    bt = base_trials.reset_index(drop=True)
    for name, kappa, h, zmad in settings:
        hits = np.empty(len(plan), int); ctrl = {}
        for k, (nid, s, dd, da_km, inj, t, a) in enumerate(plan):
            x = a.copy(); x[inj:] += da_km
            fl = d1_flags(x, kappa, h, zmad)
            hits[k] = int(len(fl) > 0 and np.abs(fl - inj).min() <= TOL)
            key = (nid, s, dd)
            if key not in ctrl:
                fc = d1_flags(a, kappa, h, zmad)
                ctrl[key] = (len(fc), float(t[-1] - t[0]))
        if name == "baseline":
            agree = float(np.mean(hits == bt["hit"].values))
        tr = bt[["norad", "win_start", "decim", "da_km", "drag_band"]].copy(); tr["hit"] = hits
        tr["cluster"] = tr["norad"].astype(str) + "_" + tr["win_start"].astype(str)
        amps = np.array(DA_GRID) * 1000
        for (dd, band), g in tr.groupby(["decim", "drag_band"], observed=True):
            rec = g.groupby("da_km")["hit"].mean().reindex(DA_GRID).values
            keys = [(n, w, dd) for n, w in g[["norad", "win_start"]].drop_duplicates().itertuples(index=False)]
            nfl = sum(ctrl[k][0] for k in keys); span = sum(ctrl[k][1] for k in keys)
            rows.append({"setting": name, "decim": int(dd), "drag": band,
                         "interp_da90_m": round(interp90(rec, amps), 1),
                         "far_flags_per_30d": round(30 * nfl / span, 2),
                         "ctrl_window_any_flag": round(float(np.mean([ctrl[k][0] > 0 for k in keys])), 3)})
        sub = pd.DataFrame([r for r in rows if r["setting"] == name])
        summ.append({"setting": name, "kappa": kappa, "h": h, "mad_z": zmad,
                     "da90_range_m": [float(sub["interp_da90_m"].min()), float(sub["interp_da90_m"].max())],
                     "far_pooled_flags_per_30d": round(float(sub["far_flags_per_30d"].mean()), 2)})
    df = pd.DataFrame(rows)
    df.to_csv(BM / "fs7_review6_detector_sensitivity.csv", index=False)
    base = df[df.setting == "baseline"].set_index(["decim", "drag"])["interp_da90_m"]
    from scipy.stats import spearmanr
    for s_ in summ:
        cur = df[df.setting == s_["setting"]].set_index(["decim", "drag"])["interp_da90_m"].reindex(base.index)
        s_["spearman_da90_vs_baseline"] = round(float(spearmanr(base.values, cur.values).correlation), 3)
        s_["max_rel_change_da90"] = round(float(np.max(np.abs(cur.values / base.values - 1))), 3)
    return {"baseline_hit_agreement_with_published_trials": round(agree, 4), "settings": summ}


def main():
    T0 = time.perf_counter()
    rng = np.random.default_rng(42)
    res = {"timing_s": {}}
    rec = pd.read_csv(BM / "fs7_tle_recall_unified_20260825.csv")
    tle = load_tle()
    d = real_events(tle, rec)
    ev, allc = load_events()
    rr = response_ratios(tle, ev, d)

    print("M1 …"); res["M1"] = m1_analysis(d, ev, rr, rng)
    print(json.dumps({k: v for k, v in res["M1"].items() if k != "response_sensitivity"}, ensure_ascii=False, default=str)[:3000])
    for r in res["M1"]["response_sensitivity"]:
        print("  ", r)
    print("M3 …"); res["M3"] = m3_analysis(d, ev, allc); print(json.dumps(res["M3"], ensure_ascii=False, default=str))
    p = pseudo_events(tle, rec)
    print("M4 …"); res["M4"] = m4_independent(d, p, rng); print(json.dumps(res["M4"], ensure_ascii=False, default=str))
    print("M5 …"); res["M5"] = m5_sign_sensitivity(d, p); print(res["M5"])
    print("M2 …"); res["M2"] = m2_e1_logistic(d); print(res["M2"])

    tr = pd.read_csv(BM / "fs7_injection_trials.csv")
    series = load_series_cut()
    t0_map = {}
    for nid, df in series.items():
        ep = df["epoch_utc"].values
        for ws in tr.loc[tr.norad == nid, "win_start"].unique():
            t0_map[(nid, ws)] = pd.Timestamp(ep[int(ws)])
    tr["win_t0"] = [t0_map[(n, w)] for n, w in zip(tr.norad, tr.win_start)]
    print("M7 …"); res["M7"] = m7_wide_grid(tr); print(res["M7"])
    print("M8 …"); res["M8"] = m8_drag_proxies(tr)
    for r in res["M8"]:
        print("  ", r)
    res["M8_da90"] = m8_da90_compare(tr)
    for k, v in res["M8_da90"].items():
        print("  ", k, v["c_hat"], v["snr90"], v["ratio_range"], [ (r["cond"], r["model_da90_m"], r["interp_da90_m"]) for r in v["rows"]])
    t = time.perf_counter()
    print("m9 …"); res["m9"] = m9_detector_sensitivity(series, tr)
    res["timing_s"]["m9"] = round(time.perf_counter() - t, 1)
    print(json.dumps(res["m9"], ensure_ascii=False, indent=1))
    res["timing_s"]["total"] = round(time.perf_counter() - T0, 1)
    out = BM / "fs7_review6_analysis.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8", newline="\n")
    print(f"輸出：{out}（{res['timing_s']['total']} s）")


if __name__ == "__main__":
    main()
