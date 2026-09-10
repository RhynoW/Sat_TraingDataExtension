#!/usr/bin/env python3
"""
fs7_injection_sweep_v4.py — v2 審查回應：c_drag 估計、單調性、強化推論、泛化測試
================================================================================
回應期刊 v2 審查之核心統計要求：

A. c_drag 正式估計：SNR(c)=|Δa|/√(σ²+(c·|ȧ|·Δt)²)，c 以最大概似估計，
   95% CI 以 profile likelihood（ΔLL≤1.92）給出——回答「固定常數 or 估計參數」。
B. 主係數強化推論（c 固定於 ĉ）：叢集自助 B=2000（單位＝衛星×窗），
   SNR50/β/SNR90 皆於每次重抽內直接計算；另報衛星層級（6 叢集，註記不穩）
   與「不重疊窗子集」敏感性——回應視窗重疊之疑慮。
C. 單調性檢定：分箱偵測率對 SNR_eff 之嚴格/近似單調判定 + isotonic R²。
D. 泛化測試（審查必做第 1 項）：
   D1 時間切分——2025-07-01 前之窗校準、之後之窗測試（真正的前後期獨立）；
   D2 5-fold 叢集交叉驗證——out-of-fold log loss / Brier / AUC，eff vs amp 對照。
E. 叢集結構揭露：各星窗數、窗重疊比例、每叢集試驗數。

輸出：data/benchmark/fs7_law_fit_v4.json；主控台摘要。
用法：python fs7_injection_sweep_v4.py [--boot 2000] [--seed 42]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

from fs7_injection_sweep import WIN, STRIDE, load_series
from fs7_injection_sweep_v2 import _logit_fit

SPLIT_DATE = "2025-07-01"


def snr_of(tr, c):
    return (tr["da_km"] / np.hypot(tr["sigma_km"], c * tr["adot_kmday"].abs() * tr["dt_day"])).clip(1e-2, 1e4)


def fit_ll(tr, c):
    x = np.log10(snr_of(tr, c).values)
    y = tr["hit"].values.astype(float)
    s50, beta, ll = _logit_fit(x, y)
    return s50, beta, ll


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--db", default="space_db.duckdb")
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    tr = pd.read_csv("data/benchmark/fs7_injection_trials.csv")
    # 映射各窗起始曆元（時間切分用）
    series = load_series(args.db)
    t0_map = {}
    for nid, df in series.items():
        ep = df["epoch_utc"].values
        for ws in tr.loc[tr.norad == nid, "win_start"].unique():
            t0_map[(nid, ws)] = pd.Timestamp(ep[int(ws)])
    tr["win_t0"] = [t0_map[(n, w)] for n, w in zip(tr.norad, tr.win_start)]
    tr["cluster"] = tr["norad"].astype(str) + "_" + tr["win_start"].astype(str)
    result = {}

    # ── E. 叢集結構 ─────────────────────────────────────────────────────────
    winper = tr.groupby("norad")["win_start"].nunique()
    per_cluster = tr.groupby("cluster").size()
    result["cluster_structure"] = {
        "windows_per_satellite": winper.to_dict(),
        "window_overlap_fraction": round(1 - STRIDE / WIN, 2),
        "trials_per_cluster_median": int(per_cluster.median()),
        "n_clusters": int(tr["cluster"].nunique())}
    print("E. 叢集結構：各星窗數", dict(winper), f" 窗重疊比例 {1-STRIDE/WIN:.0%}",
          f" 每叢集試驗數中位 {int(per_cluster.median())}")

    # ── A. c_drag 最大概似估計 + profile CI ─────────────────────────────────
    print("\nA. c_drag 估計（profile likelihood）…")
    cs = np.logspace(-1.3, 1.0, 47)
    lls = np.array([fit_ll(tr, c)[2] for c in cs])
    n = len(tr)
    i_hat = int(np.argmax(lls))
    c_hat = float(cs[i_hat])
    # profile 95% CI：總 LL 落差 ≤ 1.92（χ²₁/2）
    tot = lls * n
    ok = np.where(tot >= tot[i_hat] - 1.92)[0]
    c_lo, c_hi = float(cs[ok.min()]), float(cs[ok.max()])
    s50_hat, beta_hat, ll_hat = fit_ll(tr, c_hat)
    _, _, ll_c1 = fit_ll(tr, 1.0)
    result["c_drag"] = {"c_hat": round(c_hat, 2), "profile_ci95": [round(c_lo, 2), round(c_hi, 2)],
                        "ll_at_c_hat": round(ll_hat, 4), "ll_at_c1": round(ll_c1, 4),
                        "c1_inside_ci": bool(c_lo <= 1.0 <= c_hi),
                        "note": "c 為由資料以最大概似估計之共用參數（全星/全節奏/全阻力域共用一值）"}
    print(f"   ĉ_drag = {c_hat:.2f}，profile 95% CI [{c_lo:.2f}, {c_hi:.2f}]"
          f"（c=1 {'在' if result['c_drag']['c1_inside_ci'] else '不在'} CI 內）")

    # ── C. 單調性檢定 ───────────────────────────────────────────────────────
    xe = np.log10(snr_of(tr, c_hat).values)
    y = tr["hit"].values.astype(float)
    bins = pd.qcut(xe, 20, duplicates="drop")
    curve = pd.DataFrame({"b": bins, "y": y}).groupby("b", observed=True)["y"].mean().values
    diffs = np.diff(curve)
    strict = bool((diffs >= 0).all())
    approx = bool((diffs >= -0.05).all())
    # isotonic（PAVA）R²
    z = curve.copy(); w = np.ones_like(z)
    i = 0
    while i < len(z) - 1:
        if z[i] > z[i + 1]:
            znew = (w[i] * z[i] + w[i + 1] * z[i + 1]) / (w[i] + w[i + 1])
            z[i] = znew; w[i] += w[i + 1]
            z = np.delete(z, i + 1); w = np.delete(w, i + 1)
            i = max(i - 1, 0)
        else:
            i += 1
    iso = np.repeat(z, w.astype(int))[:len(curve)]
    ss_res = float(((curve - iso) ** 2).sum()); ss_tot = float(((curve - curve.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot else 1.0
    result["monotonicity"] = {"strict": strict, "approx_tol0.05": approx,
                              "isotonic_r2": round(r2, 4), "n_bins": len(curve)}
    print(f"\nC. 單調性：嚴格={strict}  近似(容差0.05)={approx}  isotonic R²={r2:.4f}")

    # ── B. 主係數：B=2000 叢集自助（SNR90 於每次重抽內計算）─────────────────
    print(f"\nB. 叢集自助 B={args.boot}（c 固定 ĉ={c_hat:.2f}）…")
    uniq = tr["cluster"].unique()
    groups = {k: np.where(tr["cluster"].values == k)[0] for k in uniq}
    xa = np.log10((tr["da_km"] / tr["sigma_km"]).clip(1e-2, 1e4).values)

    def stats_idx(idx):
        s50, beta, lle = _logit_fit(xe[idx], y[idx])
        _, _, lla = _logit_fit(xa[idx], y[idx])
        snr90 = s50 * 10 ** (np.log(9) / beta)
        return s50, beta, snr90, lle - lla
    pt = stats_idx(np.arange(n))
    boots = []
    for _ in range(args.boot):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([groups[k] for k in pick])
        boots.append(stats_idx(idx))
    b = np.array(boots)
    ci = lambda col: [round(float(np.percentile(b[:, col], q)), 3) for q in (2.5, 97.5)]
    result["law_fit_v4"] = {
        "boot_B": args.boot, "seed": args.seed, "ci_type": "percentile",
        "cluster_unit": "satellite×window (478)",
        "snr50": round(pt[0], 3), "snr50_ci95": ci(0),
        "beta": round(pt[1], 3), "beta_ci95": ci(1),
        "snr90": round(pt[2], 3), "snr90_ci95": ci(2),
        "delta_ll_per_sample": round(pt[3], 4), "delta_ll_ci95": ci(3)}
    print(f"   SNR50={pt[0]:.2f} CI{ci(0)}  β={pt[1]:.2f} CI{ci(1)}")
    print(f"   SNR90={pt[2]:.2f} CI{ci(2)}（每次重抽內計算）  ΔLL={pt[3]:.4f} CI{ci(3)}")

    # 衛星層級自助（6 叢集——依審查要求揭露，註記不穩定）
    sats = tr["norad"].unique()
    sgroups = {s: np.where(tr["norad"].values == s)[0] for s in sats}
    sboots = []
    for _ in range(args.boot):
        pick = rng.choice(sats, size=len(sats), replace=True)
        idx = np.concatenate([sgroups[s] for s in pick])
        sboots.append(stats_idx(idx))
    sb = np.array(sboots)
    result["law_fit_satellite_level"] = {
        "n_clusters": len(sats),
        "snr50_ci95": [round(float(np.percentile(sb[:, 0], q)), 3) for q in (2.5, 97.5)],
        "note": "僅 6 叢集，重抽分佈粗糙——as-requested 敏感性揭露，非主推論"}
    print(f"   衛星層級(6 叢集)SNR50 CI {result['law_fit_satellite_level']['snr50_ci95']}（敏感性）")

    # 不重疊窗子集敏感性
    sub = tr[tr["win_start"] % WIN == 0]
    s50n, betan, _ = _logit_fit(np.log10(snr_of(sub, c_hat).values), sub["hit"].values.astype(float))
    result["nonoverlap_subset"] = {"n_trials": int(len(sub)),
                                   "n_clusters": int(sub["cluster"].nunique()),
                                   "snr50": round(s50n, 3), "beta": round(betan, 3)}
    print(f"   不重疊窗子集({sub['cluster'].nunique()} 窗)：SNR50={s50n:.2f} β={betan:.2f}")

    # ── D. 泛化測試 ─────────────────────────────────────────────────────────
    print(f"\nD1. 時間切分（{SPLIT_DATE} 前校準 / 後測試）…")
    cal = tr[tr["win_t0"] < SPLIT_DATE]
    tst = tr[tr["win_t0"] >= SPLIT_DATE]

    def held_out(cal, tst):
        # 於校準集重估 c 與係數，於測試集評 log loss / Brier / AUC（eff vs amp）
        lls_c = [fit_ll(cal, c)[2] for c in cs]
        c_cal = float(cs[int(np.argmax(lls_c))])
        out = {"c_cal": round(c_cal, 2), "n_cal": int(len(cal)), "n_test": int(len(tst))}
        for tag, xfun in (("eff", lambda d: np.log10(snr_of(d, c_cal).values)),
                          ("amp", lambda d: np.log10((d["da_km"] / d["sigma_km"]).clip(1e-2, 1e4).values))):
            s50, beta, _ = _logit_fit(xfun(cal), cal["hit"].values.astype(float))
            p = 1 / (1 + np.exp(-beta * (xfun(tst) - np.log10(s50))))
            p = np.clip(p, 1e-9, 1 - 1e-9)
            yt = tst["hit"].values.astype(float)
            ll = float(np.mean(yt * np.log(p) + (1 - yt) * np.log(1 - p)))
            brier = float(np.mean((p - yt) ** 2))
            order = np.argsort(p)
            ranks = np.empty(len(p)); ranks[order] = np.arange(1, len(p) + 1)
            n1 = yt.sum(); n0 = len(yt) - n1
            auc = float((ranks[yt == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else np.nan
            out[tag] = {"held_out_logloss": round(-ll, 4), "brier": round(brier, 4),
                        "auc": round(auc, 4), "snr50_cal": round(s50, 2)}
        out["eff_better_held_out"] = bool(out["eff"]["held_out_logloss"] < out["amp"]["held_out_logloss"])
        return out
    ts = held_out(cal, tst)
    result["time_split"] = ts
    print(f"   校準 {ts['n_cal']} 筆(ĉ_cal={ts['c_cal']}) / 測試 {ts['n_test']} 筆")
    print(f"   held-out logloss: eff={ts['eff']['held_out_logloss']} vs amp={ts['amp']['held_out_logloss']}"
          f"  AUC: eff={ts['eff']['auc']} vs amp={ts['amp']['auc']}"
          f"  → {'SNR_eff 於留出期較佳 ✅' if ts['eff_better_held_out'] else '未較佳'}")

    print("\nD2. 5-fold 叢集交叉驗證…")
    folds = {k: i % 5 for i, k in enumerate(rng.permutation(uniq))}
    fold_id = tr["cluster"].map(folds).values
    oof = {"eff": np.zeros(n), "amp": np.zeros(n)}
    for f in range(5):
        m = fold_id != f
        lls_c = [fit_ll(tr[m], c)[2] for c in cs[::2]]
        c_f = float(cs[::2][int(np.argmax(lls_c))])
        for tag, xfull in (("eff", np.log10(snr_of(tr, c_f).values)), ("amp", xa)):
            s50, beta, _ = _logit_fit(xfull[m], y[m])
            oof[tag][~m] = 1 / (1 + np.exp(-beta * (xfull[~m] - np.log10(s50))))
    cv = {}
    for tag in ("eff", "amp"):
        p = np.clip(oof[tag], 1e-9, 1 - 1e-9)
        cv[tag] = {"oof_logloss": round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4),
                   "oof_brier": round(float(np.mean((p - y) ** 2)), 4)}
    result["cluster_cv5"] = cv
    print(f"   OOF logloss: eff={cv['eff']['oof_logloss']} vs amp={cv['amp']['oof_logloss']}")

    with open(Path("data/benchmark") / "fs7_law_fit_v4.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print("\n輸出：data/benchmark/fs7_law_fit_v4.json")


if __name__ == "__main__":
    main()
