#!/usr/bin/env python3
"""
fs7_review3_analysis.py — v3 審查投稿前必辦之技術核查（v5 分析）
================================================================
1. c_drag profile likelihood 曲線 + 可辨識性（c×SNR50 聯合自助相關、逐阻力域 c）
2. 參數化轉換表：c=1 / c=0.32(MLE) / 校準期自由擬合——SNR50/β/SNR90/held-out logloss
3. Δa90 統一單位回算：逐條件 預測 vs 實測 90% 門檻
4. 校準圖（時間切分測試集 reliability diagram + calibration slope/intercept）
5. 事件納入(96) vs 排除(35) 偏差分析
6. 混淆矩陣（45 m 與統一 3σ 門檻；FPR 單位明確定義）

輸出：data/benchmark/fs7_review3_analysis.json（摘要值；若重跑結果與既有檔不同，不覆寫，
        改寫入 fs7_review3_analysis_rerun.json 並列出差異）
      data/benchmark/fs7_review3_profile_grid.csv   c 之 profile likelihood 曲線網格
                                                    （c, ll_total, rel_ll, snr50, beta；47 點）
      data/benchmark/fs7_review3_joint_boot.csv     B=200 叢集自助之 (ĉ_b, SNR50_b)（corr −0.98 之來源）
  圖改由 docs/gen_fig_fs7_model_supplement.py 讀上述 CSV 繪製（Fig. S1 之 fig_fs7_profile_likelihood）。
輸入：data/benchmark/fs7_injection_trials.csv、fs7_tle_recall_unified_20260825.csv、
      space_db.duckdb（read_only；取窗起點曆元與 pseudo-event 之 TLE）
用法：python fs7_review3_analysis.py
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

from fs7_injection_sweep import load_series
from fs7_injection_sweep_v2 import _logit_fit
from fs7_tle_recall_unified import SIGMA3_NEW_M, THR_OLD_M, tle_step
from formosat7_leoorb.satmap import SP3_TO_NORAD

SPLIT = "2025-07-01"
CS = np.logspace(-1.3, 1.0, 47)


def snr_of(tr, c):
    return (tr["da_km"] / np.hypot(tr["sigma_km"], c * tr["adot_kmday"].abs() * tr["dt_day"])).clip(1e-2, 1e4)


def fit_at(tr, c):
    x = np.log10(snr_of(tr, c).values)
    y = tr["hit"].values.astype(float)
    return _logit_fit(x, y)          # (snr50, beta, meanLL)


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
    tr["drag_band"] = pd.qcut(tr["adot_kmday"].abs(), 3, labels=["low", "mid", "high"])
    n = len(tr)
    result = {}

    # ── 1. profile likelihood + 可辨識性 ────────────────────────────────────
    print("1. profile likelihood 與可辨識性…")
    prof = [fit_at(tr, c) for c in CS]
    lls = np.array([p[2] for p in prof]) * n
    i_hat = int(np.argmax(lls))
    c_hat = float(CS[i_hat])
    ok = np.where(lls >= lls[i_hat] - 1.92)[0]
    prof_curve = [{"c": round(float(c), 3), "rel_ll": round(float(l - lls[i_hat]), 2),
                   "snr50": round(p[0], 2)} for c, l, p in zip(CS, lls, prof)]
    pd.DataFrame({"c": CS, "ll_total": lls, "rel_ll": lls - lls[i_hat],
                  "snr50": [p[0] for p in prof], "beta": [p[1] for p in prof]}).to_csv(
        "data/benchmark/fs7_review3_profile_grid.csv", index=False, float_format="%.6g")
    # 聯合自助（B=200、逐重抽重估 c 與 SNR50）→ 相關係數
    uniq = tr["cluster"].unique()
    groups = {k: np.where(tr["cluster"].values == k)[0] for k in uniq}
    cs_coarse = CS[::2]
    joint = []
    for _ in range(200):
        idx = np.concatenate([groups[k] for k in rng.choice(uniq, len(uniq), replace=True)])
        sub = tr.iloc[idx]
        ll_c = [fit_at(sub, c)[2] for c in cs_coarse]
        cb = float(cs_coarse[int(np.argmax(ll_c))])
        s50b, _, _ = fit_at(sub, cb)
        joint.append((cb, s50b))
    joint = np.array(joint)
    pd.DataFrame({"c_boot": joint[:, 0], "snr50_boot": joint[:, 1]}).to_csv(
        "data/benchmark/fs7_review3_joint_boot.csv", index=False, float_format="%.6g")
    corr = float(np.corrcoef(np.log(joint[:, 0]), np.log(joint[:, 1]))[0, 1])
    band_c = {}
    for b in ("low", "mid", "high"):
        sub = tr[tr["drag_band"] == b]
        ll_c = [fit_at(sub, c)[2] for c in CS]
        band_c[b] = round(float(CS[int(np.argmax(ll_c))]), 2)
    result["identifiability"] = {
        "c_hat": round(c_hat, 2),
        "profile_ci95": [round(float(CS[ok.min()]), 2), round(float(CS[ok.max()]), 2)],
        "joint_boot_corr_logc_logsnr50": round(corr, 2),
        "per_drag_band_c": band_c,
        "wording": "jointly calibrated" if abs(corr) > 0.5 else "separately identifiable"}
    print(f"   ĉ={c_hat:.2f}  corr(log c, log SNR50)={corr:.2f} → "
          f"{result['identifiability']['wording']}；逐阻力域 c={band_c}")

    # ── 2. 參數化轉換表（含 held-out logloss）───────────────────────────────
    print("\n2. 參數化轉換表…")
    cal, tst = tr[tr["win_t0"] < SPLIT], tr[tr["win_t0"] >= SPLIT]
    ll_cal = [fit_at(cal, c)[2] for c in CS]
    c_free = float(CS[int(np.argmax(ll_cal))])
    rows = []
    for tag, c in (("c=1 (v2 隱含)", 1.0), ("c=0.32 (全資料 MLE)", 0.32),
                   ("free fit on cal (c=%.2f)" % c_free, c_free), ("no-drag (Δa/σ)", 0.0)):
        s50, beta, _ = fit_at(cal, c) if c > 0 else _logit_fit(
            np.log10((cal["da_km"] / cal["sigma_km"]).clip(1e-2, 1e4).values),
            cal["hit"].values.astype(float))
        x_t = (np.log10(snr_of(tst, c).values) if c > 0 else
               np.log10((tst["da_km"] / tst["sigma_km"]).clip(1e-2, 1e4).values))
        p = np.clip(1 / (1 + np.exp(-beta * (x_t - np.log10(s50)))), 1e-9, 1 - 1e-9)
        yt = tst["hit"].values.astype(float)
        ll = float(-np.mean(yt * np.log(p) + (1 - yt) * np.log(1 - p)))
        snr90 = s50 * 10 ** (np.log(9) / beta)
        rows.append({"model": tag, "snr50": round(s50, 2), "beta": round(beta, 2),
                     "snr90": round(snr90, 2), "held_out_logloss": round(ll, 4)})
        print(f"   {tag:<28} SNR50={s50:6.2f} β={beta:.2f} SNR90={snr90:6.2f} "
              f"held-out LL={ll:.4f}")
    result["parameterization_table"] = rows

    # ── 3. Δa90 統一單位回算 ────────────────────────────────────────────────
    print("\n3. Δa90 回算（預測 vs 實測 90% 門檻）…")
    s50_h, beta_h, _ = fit_at(tr, c_hat)
    snr90_h = s50_h * 10 ** (np.log(9) / beta_h)
    agg = pd.read_csv("data/benchmark/fs7_injection_sweep.csv")
    rows3 = []
    for (d, b), g in agg.groupby(["decim", "drag_band"]):
        g = g.sort_values("da_km")
        obs = g.loc[g["detect_rate"] >= 0.9, "da_km"].min()
        sig, adot, dt = g["sigma_med"].median(), g["adot_med"].median(), g["dt_med"].median()
        pred = snr90_h * np.hypot(sig, c_hat * adot * dt)
        rows3.append({"decim": int(d), "drag": b, "sigma_m": round(sig * 1000, 1),
                      "adot_mday": round(adot * 1000, 1), "dt_day": round(dt, 2),
                      "pred_da90_m": round(pred * 1000), "obs_da90_m":
                      round(obs * 1000) if np.isfinite(obs) else None})
        print(f"   d={d} {b:<5} σ={sig*1000:5.1f}m |ȧ|={adot*1000:5.1f}m/d Δt={dt:.2f}d"
              f" → 預測 {pred*1000:4.0f} m / 實測 {obs*1000:4.0f} m")
    result["da90_backcalc"] = rows3

    # ── 4. 校準圖資料（時間切分測試集）──────────────────────────────────────
    print("\n4. 校準（reliability）…")
    s50c, betac, _ = fit_at(cal, c_free)
    p_t = np.clip(1 / (1 + np.exp(-betac * (np.log10(snr_of(tst, c_free).values)
                                            - np.log10(s50c)))), 1e-6, 1 - 1e-6)
    yt = tst["hit"].values.astype(float)
    dec = pd.qcut(p_t, 10, duplicates="drop")
    calib = pd.DataFrame({"bin": dec, "p": p_t, "y": yt}).groupby("bin", observed=True).agg(
        p_mean=("p", "mean"), y_rate=("y", "mean"), n=("y", "size")).reset_index(drop=True)
    logit_p = np.log(p_t / (1 - p_t))
    cs50, cbeta, _ = _logit_fit(logit_p / np.log(10), yt)   # slope/intercept 轉換
    slope = cbeta / np.log(10) * np.log(10)                  # β on logit_p
    result["calibration"] = {
        "bins": calib.round(3).to_dict("records"),
        "slope": round(float(cbeta), 2),
        "note": "slope≈1 表示機率校準良好（以 logit(p) 為單一特徵之再校準斜率）"}
    print(f"   calibration slope ≈ {cbeta:.2f}（理想=1）")

    # ── 5. 納入 vs 排除偏差 ─────────────────────────────────────────────────
    print("\n5. 事件納入(96) vs 排除(35) 偏差…")
    rec = pd.read_csv("data/benchmark/fs7_tle_recall_unified_20260825.csv")
    BINS = [0, 50, 100, 300, 1000, 3000, np.inf]
    LAB = ["1-50", "50-100", "100-300", "300-1k", "1-3k", ">3k"]
    rec["bin"] = pd.cut(rec["amp_m"], BINS, labels=LAB)
    cmp_rows = {}
    for dim in ("bin", "campaign", "sp3_sat"):
        t1 = rec.groupby([dim, "computable"], observed=True).size().unstack(fill_value=0)
        t1.columns = ["excluded", "included"] if 0 in [int(c) for c in [False]] else t1.columns
        cmp_rows[dim] = t1.to_dict()
    excl_rate_bin = rec.groupby("bin", observed=True)["computable"].apply(lambda x: 1 - x.mean())
    excl_rate_cam = rec.groupby("campaign", observed=True)["computable"].apply(lambda x: 1 - x.mean())
    result["selection_bias"] = {
        "exclusion_rate_by_bin": excl_rate_bin.round(2).to_dict(),
        "exclusion_rate_by_campaign": excl_rate_cam.round(2).to_dict(),
        "verdict": "排除率若隨幅度/期間系統性變化→正文標 potential selection bias"}
    print("   排除率（按幅度）:", dict(excl_rate_bin.round(2)))
    print("   排除率（按期間）:", dict(excl_rate_cam.round(2)))

    # ── 6. 混淆矩陣（event-level TP/FN + pseudo-event TN/FP）────────────────
    print("\n6. 混淆矩陣（單位：pseudo-event＝安靜期隨機時刻以同一前後段估計器評估一次）…")
    import duckdb
    con = duckdb.connect("space_db.duckdb", read_only=True)
    tle = {}
    for sat, nid in SP3_TO_NORAD.items():
        df = con.execute("SELECT epoch_utc, sma_km FROM raw_tle_archive WHERE norad_id=? "
                         "ORDER BY epoch_utc", [nid]).df()
        t = df["epoch_utc"].values.astype("datetime64[s]").astype(float) / 86400.0
        tle[sat] = (t, df["sma_km"].values)
    comp = rec[rec["computable"]]
    conf = {}
    fp = {"old": 0, "new": 0}; n_pseudo = 0
    ev_t = {s: [] for s in tle}
    ref = np.datetime64("1970-01-01T00:00:00", "s")
    for _, r in rec.iterrows():
        d0 = (pd.Timestamp(r["t_start"]).to_datetime64().astype("datetime64[s]") - ref) / np.timedelta64(1, "D")
        ev_t[r["sp3_sat"]].append(float(d0))
    for sat, (t, a) in tle.items():
        evd = np.array(ev_t[sat]) if ev_t[sat] else np.array([0.0])
        cand = t[(t > t.min() + 3) & (t < t.max() - 3)]
        for tc in rng.choice(cand, size=min(200, len(cand)), replace=False):
            if np.abs(evd - tc).min() < 2.0:
                continue
            step_m, gap, adot, okk = tle_step(t, a, tc, tc)
            if not okk:
                continue
            n_pseudo += 1
            fp["old"] += int(abs(step_m) > THR_OLD_M)
            fp["new"] += int(abs(step_m) > SIGMA3_NEW_M[sat])
    for tag, col in (("thr_45m", "det_old"), ("thr_unified3sig", "det_new")):
        tp = int(comp[col].sum()); fn = len(comp) - tp
        fpv = fp["old"] if tag == "thr_45m" else fp["new"]
        tn = n_pseudo - fpv
        conf[tag] = {"TP": tp, "FN": fn, "FP": fpv, "TN": tn,
                     "recall": round(tp / len(comp), 3),
                     "FPR_per_pseudo_event": round(fpv / n_pseudo, 3),
                     "precision_vs_pseudo": round(tp / (tp + fpv), 3) if tp + fpv else None}
        print(f"   {tag}: TP={tp} FN={fn} FP={fpv} TN={tn} "
              f"recall={tp/len(comp):.2f} FPR={fpv/n_pseudo:.3f}")
    result["confusion"] = {"unit": "event-level TP/FN（96 件）；FP/TN 以 pseudo-event"
                                   f"（n={n_pseudo}）計，FPR=FP/(FP+TN)", **conf}

    write_json_guarded(result, Path("data/benchmark") / "fs7_review3_analysis.json")
    print("\n網格：data/benchmark/fs7_review3_profile_grid.csv, fs7_review3_joint_boot.csv")
    print("圖：python docs/gen_fig_fs7_model_supplement.py")


def _diff(a, b, path=""):
    """列出兩個 json 物件之差異（路徑: 舊 → 新）。"""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            out += _diff(a.get(k, "<缺>"), b.get(k, "<缺>"), f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for k, (x, y) in enumerate(zip(a, b)):
            out += _diff(x, y, f"{path}[{k}]")
    elif a != b:
        out.append(f"{path}: {a!r} → {b!r}")
    return out


def write_json_guarded(result: dict, path: Path) -> None:
    """既有摘要 json 不覆寫：重跑結果相同則不動檔；不同則另存 <stem>_rerun.json 並列差異。"""
    new = json.loads(json.dumps(result, ensure_ascii=False, default=str))
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        d = _diff(old, new)
        if not d:
            print(f"\n摘要值與既有 {path.name} 一致（檔案未改動）")
            return
        alt = path.with_name(path.stem + "_rerun.json")
        alt.write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        print(f"\n[差異] 重跑摘要與既有 {path.name} 不同，已另存 {alt.name}（原檔未動）：")
        for x in d:
            print("   ", x)
        return
    path.write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(f"\n輸出：{path}")


if __name__ == "__main__":
    main()
