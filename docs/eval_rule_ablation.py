#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_rule_ablation.py — L1／L2 規則逐條消融（ablation），找出無作用或效益極低之規則。

基準：R7 採用之 L1（P2×P5×P6 有效門檻＋其他根數＋P4，扣 P1／P3 抑制）。
L1 消融：逐一移除 P1、P3、P4、P5、P6、Δi、Δe、ΔΩ，量測召回與誤報之變化。
L2：對每顆衛星計算四種統計方法（CUSUM／BOCPD／SSA／MAD3σ）之觸發時點，統計
    (a) 基準 L1 事件中「≥2 種方法」輔助通道成立之件數，以及各方法為關鍵票（移除後不足 2 種）之件數；
    (b) 各方法單獨之觸發率（火箭箭體為誤報率）。

樣本同 eval_l1_combination.py：meme（283 顆 Starlink）、ids（15 顆，安靜期與可見點火）、neg（300 顆 LEO 火箭箭體）。
用法：python docs/eval_rule_ablation.py [meme|ids|neg|all]
輸出：data/benchmark/rule_ablation_<sample>.csv 與終端摘要
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs"))
os.environ.setdefault("SSA_RAG_URL", "http://127.0.0.1:9")
import maneuver_report_builder as rb  # noqa: E402
import maneuver_strategies_july as ms  # noqa: E402
import eval_l1_combination as ec  # noqa: E402

PAD = pd.Timedelta(hours=24)
DROPS = ["base", "P1", "P3", "P4", "P5", "P6", "di", "de", "draan"]
L2CH = ["cusum", "bocpd", "ssa", "mad3sig"]


def combine(tr, oc, drop):
    n = len(tr)
    if n == 0:
        return np.zeros(0, bool)
    da = tr["da_km"].to_numpy(float)
    alt = tr["alt_km"].to_numpy(float)
    bstar = tr["bstar"].to_numpy(float)
    f107 = tr["f107"].to_numpy(float)
    thr_p2 = ms.DEFAULT_P2(alt)
    if oc in ("MEO", "GEO", "GEO+", "HEO"):
        thr = np.full(n, 0.05) if "P6" not in drop else thr_p2
    else:
        mult = 1.0
        if "P5" not in drop:
            mult = np.clip(np.where(np.isnan(f107), 1.0, ms.DEFAULT_P5(np.nan_to_num(f107, nan=70.0))), 1.0, ms.P5_MULT_MAX)
        p6 = 1.0 if "P6" in drop else ms.DEFAULT_P6.get(ms.inc_family(float(np.nanmedian(tr["inc_deg"]))), 1.0)
        thr = thr_p2 * mult * p6
    flag = np.abs(da) > thr
    other = np.zeros(n, bool)
    if "di" not in drop:
        other |= np.abs(tr["di_deg"].to_numpy(float)) > ms.THR_DI
    if "de" not in drop:
        other |= np.abs(tr["de"].to_numpy(float)) > ms.THR_DE
    if "draan" not in drop:
        other |= np.abs(tr["draan_res_deg"].to_numpy(float)) > ms.THR_DRAAN
    sup = np.zeros(n, bool)
    if "P1" not in drop:
        for i in range(n):
            seg = da[max(0, i - 4):i + 1]
            if len(seg) >= 4 and np.mean(seg < 0.1) >= 0.85 and np.all(np.abs(seg) < 2.0) \
                    and not np.isnan(bstar[i]) and bstar[i] > 0:
                sup[i] = True
    if "P3" not in drop:
        vb = bstar[~np.isnan(bstar)]
        hi = np.nanmedian(vb) + 2 * np.nanstd(vb) if len(vb) else np.inf
        sup |= (~np.isnan(bstar)) & (bstar > max(hi, 5e-4)) & (da < 0) & (np.abs(da) < 1.5)
    sup &= ~flag
    base = flag | other
    p4 = np.zeros(n, bool)
    if "P4" not in drop:
        for i in range(n):
            if base[max(0, i - 2):i + 1].any():
                p4[i] = True
    return (base | p4) & ~sup


def l2_times(df):
    raw = rb.compute_l2(df)
    out = {}
    for ch in L2CH:
        idx = np.asarray(raw.get(ch, {}).get("events", []), int)
        idx = idx[(idx >= 0) & (idx < len(df))]
        ep = pd.to_datetime(df["epoch"].iloc[idx], utc=True).dt.tz_convert(None)
        out[ch] = ep.to_numpy(dtype="datetime64[ns]") if len(idx) else np.array([], "datetime64[ns]")
    return out


def l2_votes(ev, l2t):
    """回傳每件事件之觸發方法集合。"""
    res = []
    for e in ev:
        lo, hi = np.datetime64((e["t_start"] - PAD).tz_convert(None)), np.datetime64((e["t_end"] + PAD).tz_convert(None))
        res.append({ch for ch, t in l2t.items() if len(t) and ((t >= lo) & (t <= hi)).any()})
    return res


def l2_stats(row, ev, l2t, days):
    votes = l2_votes(ev, l2t)
    row["l2_ev_ok"] = sum(len(v) >= 2 for v in votes)
    for ch in L2CH:
        row[f"l2_piv_{ch}"] = sum(len(v) == 2 and ch in v for v in votes)
        row[f"l2_in_{ch}"] = sum(ch in v for v in votes)
        row[f"l2_rate_{ch}"] = len(l2t[ch])
    row["days"] = days


def run(sample):
    rows = []
    if sample == "meme":
        T = pd.read_csv(ROOT / "data/meme_truth/transitions_full_20260918.csv", parse_dates=["t_from", "t_to"])
        items = []
        for nid, g in T.groupby("norad_id"):
            eps = []
            for _, x in g[g["label_meme"] == 1].sort_values("t_from").iterrows():
                if eps and x["t_from"] - eps[-1][1] <= pd.Timedelta(hours=48):
                    eps[-1][1] = max(eps[-1][1], x["t_to"])
                else:
                    eps.append([x["t_from"], x["t_to"]])
            items.append((nid, g["t_from"].min(), g["t_to"].max(), eps))
    elif sample == "ids":
        tru = pd.read_csv("ids_truth_set/ids_truth.csv")
        qui = pd.read_csv("ids_truth_set/ids_quiet.csv")
        for c in ("win_start_tai", "win_end_tai"):
            tru[c] = pd.to_datetime(tru[c], utc=True)
        for c in ("quiet_start_tai", "quiet_end_tai"):
            qui[c] = pd.to_datetime(qui[c], utc=True)
        items = [(nid, None, None, None) for nid in sorted(qui["norad"].dropna().unique())]
    else:
        R0 = pd.read_csv(ROOT / "data/benchmark/l1_combination_neg.csv")   # 沿用相同 300 顆
        end = pd.Timestamp("2026-11-14", tz="UTC")
        items = [(nid, end - pd.Timedelta(days=365), end, None) for nid in R0["norad"]]
    for k, (nid, w0, w1, eps) in enumerate(items, 1):
        p = ec.prep(nid, w0, w1)
        if p is None:
            continue
        df, tr, oc = p
        days = (df["epoch"].iloc[-1] - df["epoch"].iloc[0]).total_seconds() / 86400
        row = {"norad": int(nid)}
        if sample == "ids":
            q = qui[qui["norad"] == nid]; t = tru[tru["norad"] == nid]
            qs = [(a + PAD, b - PAD) for a, b in zip(q["quiet_start_tai"], q["quiet_end_tai"]) if b - a > 2 * PAD]
            row["quiet_days"] = sum((b - a).total_seconds() for a, b in qs) / 86400
            w = t.groupby(["win_start_tai", "win_end_tai"]).agg(vis=("tle_visible_50", "max")).reset_index()
            vis = w[w["vis"] == 1]; row["burn_vis"] = len(vis)
        if sample == "meme":
            row["n_ep"] = len(eps)
        for d in DROPS:
            c = combine(tr, oc, set() if d == "base" else {d})
            ev = ec.events_for(df, tr, c)
            row[f"{d}_pts"] = int(c.sum()); row[f"{d}_ev"] = len(ev)
            if sample == "meme":
                row[f"{d}_cov"] = sum(any(x["t_start"] - PAD <= e[1] and e[0] <= x["t_end"] + PAD for x in ev) for e in eps)
            elif sample == "ids":
                row[f"{d}_fp"] = sum(any(a <= e["t_end"] and e["t_start"] <= b for a, b in qs) for e in ev)
                row[f"{d}_det"] = sum(any(e["t_start"] <= r["win_end_tai"] + PAD and r["win_start_tai"] - PAD <= e["t_end"]
                                          for e in ev) for _, r in vis.iterrows())
            if d == "base":
                l2_stats(row, ev, l2_times(df), days)
        rows.append(row)
        if k % 50 == 0:
            print(sample, k, flush=True)
    return pd.DataFrame(rows)


def summary(sample, R):
    print(f"\n=== {sample}（{len(R)} 顆）===")
    for d in DROPS:
        if sample == "meme":
            extra = f"召回 {R[d+'_cov'].sum()/R['n_ep'].sum():.3f}"
        elif sample == "ids":
            extra = f"安靜期誤報 {R[d+'_fp'].sum()}（每千 {R[d+'_fp'].sum()/R['quiet_days'].sum()*1000:.2f}）、可見點火 {R[d+'_det'].sum()}/{R['burn_vis'].sum()}"
        else:
            extra = f"每千星日事件 {R[d+'_ev'].sum()/R['days'].sum()*1000:.2f}"
        print(f"  {'移除 '+d if d!='base' else '基準'}：候選點 {R[d+'_pts'].sum()}、事件 {R[d+'_ev'].sum()}、{extra}")
    print(f"  L2：基準事件中 ≥2 方法成立 {R['l2_ev_ok'].sum()} 件；"
          + "、".join(f"{c} 關鍵票 {R['l2_piv_'+c].sum()}／出現 {R['l2_in_'+c].sum()}／觸發 {R['l2_rate_'+c].sum()/R['days'].sum()*1000:.1f} 次每千星日"
                     for c in L2CH))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    for s in ("meme", "ids", "neg"):
        if which in (s, "all"):
            R = run(s)
            R.to_csv(ROOT / f"data/benchmark/rule_ablation_{s}.csv", index=False, encoding="utf-8-sig")
            summary(s, R)
