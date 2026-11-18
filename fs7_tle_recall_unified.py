#!/usr/bin/env python3
"""
fs7_tle_recall_unified.py — TLE 側召回統一重比對（雙門檻 + FPR 控制 + 定律預測）
================================================================================
期刊 §5.3 收尾：對全部已驗證 SP3 事件（2025-07/08 原 46 件 + 四段新 campaign
85 件）以**同一份程式碼**跑 TLE 側偵測，比較兩種門檻：

  舊門檻：45 m（研討會版沿用之 3σ，估計法相依之保守值）
  新門檻：統一估計器之逐星 3σ（3.9–6.2 m，campaign 前安靜段）

偵測判準（承研討會版）：事件時窗前後之 TLE 半長軸階躍——前段 TLE 線性去趨勢
（吸收局部阻力），後段首筆之殘差 step_obs；|step_obs| > thr 且與 SP3 step 同號。

FPR 控制：逐星於安靜期抽 200 個偽事件時刻，同一判準量測誤報率（雙門檻）。
定律驗證：以 v4 係數（c=0.32、SNR50=3.77、β=5.25）算每事件之預測偵測機率，
分箱比較「定律預測召回 vs 實測召回」。

輸出：data/benchmark/fs7_tle_recall_unified_20260825.csv（逐事件）
      主控台：分箱召回表（雙門檻、Wilson 95% CI）、FPR、預測對照
用法：python fs7_tle_recall_unified.py
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd

from formosat7_leoorb.satmap import SP3_TO_NORAD

# 統一估計器之逐星 3σ（m）——campaign 前安靜段（2025-06-01~07-10）
SIGMA3_NEW_M = {"L76": 5.9, "L77": 4.2, "L78": 3.9, "L79": 4.0, "L80": 4.7, "L81": 6.2}
THR_OLD_M = 45.0
PRE_D, POST_D, GAP_H = 3.0, 3.0, 2.0
MIN_PRE = 3
# v4 定律係數（c 固定 ĉ）
C_DRAG, SNR50, BETA = 0.32, 3.77, 5.25
N_FP = 200

BINS = [0, 50, 100, 300, 1000, 3000, np.inf]
LABELS = ["1-50 m", "50-100 m", "100-300 m", "300 m-1 km", "1-3 km", ">3 km"]


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def tle_step(tt, aa, t_ev0, t_ev1):
    """回傳 (step_obs_m, gap_day, adot_kmday, ok)。tt 為天（float）、aa 為 km。"""
    pre = (tt >= t_ev0 - PRE_D) & (tt <= t_ev0 - GAP_H / 24)
    post = (tt >= t_ev1 + GAP_H / 24) & (tt <= t_ev1 + POST_D)
    if pre.sum() < MIN_PRE or post.sum() < 1:
        return np.nan, np.nan, np.nan, False
    tp, ap = tt[pre], aa[pre]
    coef = np.polyfit(tp, ap, 1)
    i_post = np.argsort(tt[post])[:2]                      # 後段最早 1–2 筆
    t_po, a_po = tt[post][i_post], aa[post][i_post]
    resid = a_po - np.polyval(coef, t_po)
    step_m = float(np.median(resid)) * 1000.0
    gap = float(t_po[0] - tp[-1])
    return step_m, gap, float(coef[0]), True


def main():
    con = duckdb.connect("space_db.duckdb", read_only=True)
    tle = {}
    for sat, nid in SP3_TO_NORAD.items():
        df = con.execute("SELECT epoch_utc, sma_km FROM raw_tle_archive "
                         "WHERE norad_id=? ORDER BY epoch_utc", [nid]).df()
        t = df["epoch_utc"].values.astype("datetime64[s]").astype(float) / 86400.0
        tle[sat] = (t, df["sma_km"].values)

    # ── 事件集：2025 原集 + 新四段（皆取通過驗證者）─────────────────────────
    e25 = pd.read_csv("data/benchmark/fs7_events_2025raise.csv")
    e25 = e25[e25["verdict"] == "疑似真事件"].copy()
    e25["campaign"] = "2025-07/08"; e25["holdout"] = False
    enew = pd.read_csv("data/benchmark/fs7_events_campaigns_20260825.csv")
    enew = enew[enew["verdict"] == "疑似真事件"].copy()
    ev = pd.concat([e25, enew], ignore_index=True)
    for c in ("t_start", "t_end"):
        ev[c] = pd.to_datetime(ev[c], utc=True, format="mixed")

    ref = np.datetime64("1970-01-01T00:00:00", "s")
    rows = []
    for _, r in ev.iterrows():
        sat = r["sp3_sat"]
        t, a = tle[sat]
        t0 = (r["t_start"].to_datetime64().astype("datetime64[s]") - ref) / np.timedelta64(1, "D")
        t1 = (r["t_end"].to_datetime64().astype("datetime64[s]") - ref) / np.timedelta64(1, "D")
        step_m, gap, adot, ok = tle_step(t, a, float(t0), float(t1))
        amp = abs(r["step_m"])
        sig_m = SIGMA3_NEW_M[sat] / 3.0
        snr = (amp / 1000.0) / np.hypot(sig_m / 1000.0, C_DRAG * abs(adot) * gap) if ok else np.nan
        rows.append({
            "sp3_sat": sat, "campaign": r["campaign"], "holdout": bool(r["holdout"]),
            "t_start": r["t_start"], "amp_m": amp, "computable": ok,
            "step_obs_m": round(step_m, 1) if ok else np.nan,
            "gap_day": round(gap, 2) if ok else np.nan,
            "adot_kmday": round(adot, 5) if ok else np.nan,
            "det_old": bool(ok and abs(step_m) > THR_OLD_M and np.sign(step_m) == np.sign(r["step_m"])),
            "det_new": bool(ok and abs(step_m) > SIGMA3_NEW_M[sat] and np.sign(step_m) == np.sign(r["step_m"])),
            "snr_eff_pred": round(float(snr), 2) if ok and np.isfinite(snr) else np.nan,
            "p_pred": round(float(1 / (1 + np.exp(-BETA * (np.log10(max(snr, 1e-3)) - np.log10(SNR50))))), 3)
                      if ok and np.isfinite(snr) else np.nan,
        })
    res = pd.DataFrame(rows)
    res.to_csv("data/benchmark/fs7_tle_recall_unified_20260825.csv",
               index=False, encoding="utf-8-sig")

    comp = res[res["computable"]].copy()
    comp["bin"] = pd.cut(comp["amp_m"], BINS, labels=LABELS)
    print(f"事件總數 {len(res)}（原 46 + 新 {len(enew)}），可比對 {len(comp)} 件"
          f"（其餘 TLE 前後段不足）\n")
    print("===== 分箱召回：舊門檻 45 m vs 統一新門檻 3.9-6.2 m =====")
    print(f"{'分箱':<12}{'n':>4}{'舊召回':>9}{'新召回':>9}{'新95%CI':>18}{'定律預測':>10}")
    for b in LABELS:
        g = comp[comp["bin"] == b]
        if not len(g):
            continue
        n = len(g)
        r_old, r_new = g["det_old"].mean(), g["det_new"].mean()
        lo, hi = wilson(int(g["det_new"].sum()), n)
        pp = g["p_pred"].mean()
        print(f"{b:<12}{n:>4}{r_old:>9.2f}{r_new:>9.2f}{f'[{lo:.2f},{hi:.2f}]':>18}{pp:>10.2f}")

    # ── FPR 控制：安靜期偽事件 ───────────────────────────────────────────────
    rng = np.random.default_rng(42)
    ev_days = {s: [] for s in tle}
    for _, r in ev.iterrows():
        d0 = (r["t_start"].to_datetime64().astype("datetime64[s]") - ref) / np.timedelta64(1, "D")
        ev_days[r["sp3_sat"]].append(float(d0))
    fp_old = fp_new = n_fp = 0
    for sat, (t, a) in tle.items():
        evd = np.array(ev_days[sat]) if ev_days[sat] else np.array([0.0])
        cand = t[(t > t.min() + PRE_D) & (t < t.max() - POST_D)]
        picks = rng.choice(cand, size=min(N_FP, len(cand)), replace=False)
        for tc in picks:
            if np.abs(evd - tc).min() < 2.0:               # 避開真事件 ±2 天
                continue
            step_m, gap, adot, ok = tle_step(t, a, tc, tc)
            if not ok:
                continue
            n_fp += 1
            fp_old += int(abs(step_m) > THR_OLD_M)
            fp_new += int(abs(step_m) > SIGMA3_NEW_M[sat])
    print(f"\n===== FPR（安靜期偽事件 n={n_fp}）=====")
    print(f"舊門檻 45 m：{fp_old/n_fp:.3f}   新門檻 3.9-6.2 m：{fp_new/n_fp:.3f}")
    print("\n輸出：data/benchmark/fs7_tle_recall_unified_20260825.csv")


if __name__ == "__main__":
    main()
