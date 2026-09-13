#!/usr/bin/env python3
"""_tasa14_asof20250501_persat.py — 將分析時間凍結在 2025-05-01（對齊 TASA
《TASA方法於NASA機動資料庫偵測結果_20260731.pdf》之資料快照日），重跑本專案
方法（固定門檻/單趟SNR/迭代+位準位移）之逐星 P/R/F1，供與該 PDF 之聚合數字
做同一時間切面比較。真值與 TLE 皆截止於 cutoff，不使用 cutoff 之後的任何資料。
"""
from __future__ import annotations
import sys
import numpy as np
import pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

from tasa14_compare import (load_events, load_a, SATS, detect, detect_iter,
                             detrend_step, robust_sigma, TOL_D)

CUTOFF = pd.Timestamp("2025-05-01", tz="UTC")


def load_a_cut(nid):
    t, a = load_a(nid)
    if t is None:
        return None, None
    mask = np.asarray(t <= CUTOFF)
    return t[mask], a[mask]


def load_events_cut():
    events = load_events()
    return {nid: ev[ev["ws"] <= CUTOFF].reset_index(drop=True) for nid, ev in events.items()}


def evaluate_cut(nid, events, detfn):
    t, a = load_a_cut(nid)
    if t is None or len(a) < 30 or nid not in events:
        return None
    ev = events[nid]
    lo = max(t.min(), ev["ws"].min()); hi = min(t.max(), ev["we"].max())
    ev = ev[(ev["ws"] >= lo) & (ev["ws"] <= hi)].reset_index(drop=True)
    if len(ev) == 0:
        return None
    dets = detfn(t, a)
    dets = pd.to_datetime([d for d in dets if lo <= d <= hi])
    tol = pd.Timedelta(days=float(TOL_D))
    used = np.zeros(len(dets), bool); tp = 0
    for _, e in ev.iterrows():
        w0, w1 = e["ws"] - tol, e["we"] + tol
        hit = [i for i, d in enumerate(dets) if w0 <= d <= w1 and not used[i]]
        if hit:
            used[hit[0]] = True; tp += 1
    fn = len(ev) - tp
    fp = int((~used).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return dict(norad=nid, n_ev=len(ev), n_det=len(dets), tp=tp, fp=fp, fn=fn,
                precision=prec, recall=rec, f1=f1)


def main():
    events = load_events_cut()
    rows = []
    for nid, nm in SATS:
        t0, a0 = load_a_cut(nid)
        if t0 is None:
            continue
        thr_snr = 6 * robust_sigma(detrend_step(a0))

        r_fixed = evaluate_cut(nid, events, lambda t, a: detect(t, a, 0.05))
        r_snr = evaluate_cut(nid, events, lambda t, a, thr=thr_snr: detect(t, a, thr))
        r_iter = evaluate_cut(nid, events, lambda t, a: detect_iter(t, a, 6))

        for method, r in [("固定門檻50m", r_fixed), ("單趟SNR(k=6)", r_snr),
                          ("迭代+位準位移(k=6,headline)", r_iter)]:
            if r:
                r = dict(r); r.pop("norad", None)
                rows.append(dict(norad=nid, name=nm, method=method, **r))
        n_ev = r_iter["n_ev"] if r_iter else (r_snr["n_ev"] if r_snr else None)
        print(f"  {nm:14s} n_ev(截至0501)={n_ev}", flush=True)

    df = pd.DataFrame(rows)
    out = "data/benchmark/tasa14_asof20250501_persat_20260914.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}（{len(df)} 列）")

    headline = df[df.method == "迭代+位準位移(k=6,headline)"]
    print(f"\n【headline，截至2025-05-01，n={len(headline)}】")
    print(f"平均 Precision={headline.precision.mean():.3f}  "
          f"平均 Recall={headline.recall.mean():.3f}  平均 F1={headline.f1.mean():.3f}")


if __name__ == "__main__":
    main()
