#!/usr/bin/env python3
"""tasa14_l2_compare.py — L2 統計變點層(CUSUM/BOCPD/SSA/3σ-MAD)+ 無監督融合,於 NASA/ILRS 14 星。

L2 偵測器為窗級設計(BOCPD 為 O(n²)),故以滑動窗跑 statistical_detectors.run_all,
收集各通道事件→合併→配對 ILRS 真值。另加無監督融合:union(任一)、vote≥2(至少兩通道)。
L3(HistGB 融合)為 Starlink 訓練之跨域模型,依報告規約僅作一致性驗證、不列數字,故以
無監督融合替代作「星系級融合」對照。用法：python tasa14_l2_compare.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

import statistical_detectors as sd
from tasa14_compare import load_events, load_a, SATS, TOL_D, MERGE_D

WIN, STEP, EDGE = 150, 100, 4       # 滑動窗點數 / 步長 / 邊緣裁切
CHANS = ["cusum", "bocpd", "ssa", "mad3sig"]


def windowed_l2(t, a):
    """滑動窗跑 L2 四通道，回傳 {channel: [epoch,...]}（未合併）。"""
    n = len(a)
    out = {c: [] for c in CHANS}
    start = 0
    while start < n:
        seg = slice(start, min(n, start + WIN))
        aw = a[seg]; tw = t[seg]
        if len(aw) >= 24:
            res = sd.run_all(aw)
            for c in CHANS:
                for idx in res[c]["events"]:
                    if EDGE <= idx < len(aw) - EDGE:
                        out[c].append(tw[idx])
        if start + WIN >= n:
            break
        start += STEP
    return out


def windowed_l2_iter(t, a):
    """④ 迭代化 L2:每通道先跑一趟,將自身事件 ±1 天之點自序列剔除後重跑
    (統計量不再被事件污染;事件本身在接縫處仍可被偵測)。回傳第二趟事件。"""
    ch1 = windowed_l2(t, a)
    tsec = t.astype("int64").to_numpy() / 1e9
    out = {}
    for c in CHANS:
        ev1 = merge_epochs(ch1[c])
        if not len(ev1):
            out[c] = []
            continue
        esec = ev1.astype("int64").to_numpy() / 1e9
        mask = np.zeros(len(a), bool)
        for e in esec:
            mask |= np.abs(tsec - e) <= 1.0 * 86400
        keep = ~mask
        if keep.sum() < 60:
            out[c] = list(ev1)
            continue
        ch2 = windowed_l2(t[keep], a[keep])
        out[c] = ch2[c]
    return out


def merge_epochs(epochs, merge_d=MERGE_D):
    if not len(epochs): return pd.to_datetime([])
    e = pd.to_datetime(sorted(pd.to_datetime(epochs)))
    sec = e.astype("int64").to_numpy() / 1e9
    keep = [e[0]]; last = sec[0]
    for i in range(1, len(e)):
        if sec[i] - last > merge_d * 86400:
            keep.append(e[i]); last = sec[i]
    return pd.to_datetime(keep)


def fuse_vote(chan_epochs, min_ch=2, merge_d=MERGE_D):
    """至少 min_ch 個通道在 merge_d 窗內都有事件 → 融合偵測。"""
    allev = []
    for c in CHANS:
        for e in merge_epochs(chan_epochs[c]):
            allev.append((pd.Timestamp(e), c))
    allev.sort()
    if not allev: return pd.to_datetime([])
    dets, i = [], 0
    used = [False] * len(allev)
    for i, (e0, c0) in enumerate(allev):
        if used[i]: continue
        grp_ch = {c0}; grp_t = [e0]; used[i] = True
        for j in range(i + 1, len(allev)):
            if used[j]: continue
            if (allev[j][0] - e0).total_seconds() <= merge_d * 86400:
                grp_ch.add(allev[j][1]); grp_t.append(allev[j][0]); used[j] = True
            else:
                break
        if len(grp_ch) >= min_ch:
            dets.append(grp_t[len(grp_t) // 2])
    return merge_epochs(dets)


def metrics(dets, ev, lo, hi):
    dets = pd.to_datetime([d for d in dets if lo <= d <= hi])
    tol = pd.Timedelta(days=float(TOL_D))
    used = np.zeros(len(dets), bool); tp = 0
    for _, e in ev.iterrows():
        w0, w1 = e["ws"] - tol, e["we"] + tol
        hit = [i for i, d in enumerate(dets) if w0 <= d <= w1 and not used[i]]
        if hit: used[hit[0]] = True; tp += 1
    fn = len(ev) - tp; fp = int((~used).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return dict(n_ev=len(ev), n_det=len(dets), tp=tp, fp=fp, fn=fn, precision=p, recall=r, f1=f1)


def main():
    events = load_events()
    variants = CHANS + ["union", "vote>=2"]
    agg = {v: [] for v in variants}
    per_sat = []

    print("計算中(滑動窗 L2，14 星)…")
    for nid, nm in SATS:
        t, a = load_a(nid)
        if t is None or len(a) < 60 or nid not in events:
            continue
        ev = events[nid]
        lo = max(t.min(), ev["ws"].min()); hi = min(t.max(), ev["we"].max())
        ev = ev[(ev["ws"] >= lo) & (ev["ws"] <= hi)].reset_index(drop=True)
        if len(ev) == 0: continue
        ch = windowed_l2(t, a)
        chm = {c: merge_epochs(ch[c]) for c in CHANS}
        dets = dict(chm)
        dets["union"] = merge_epochs(np.concatenate([chm[c].to_numpy() for c in CHANS]) if any(len(chm[c]) for c in CHANS) else [])
        dets["vote>=2"] = fuse_vote(ch)
        row = {"norad": nid, "name": nm}
        for v in variants:
            m = metrics(dets[v], ev, lo, hi)
            agg[v].append(m)
            if v == "vote>=2":
                row.update(m)
        per_sat.append(row)

    print("\n" + "=" * 72)
    print("L2 統計層 + 無監督融合，NASA/ILRS 14 星（平均 F1/P/R、最高 F1）")
    print("=" * 72)
    print(f"{'方法':12}{'平均F1':>9}{'平均P':>8}{'平均R':>8}{'最高F1':>9}")
    summary = []
    for v in variants:
        f1 = np.array([m["f1"] for m in agg[v]])
        p_ = np.array([m["precision"] for m in agg[v]])
        r_ = np.array([m["recall"] for m in agg[v]])
        print(f"{v:12}{f1.mean():>9.3f}{p_.mean():>8.3f}{r_.mean():>8.3f}{f1.max():>9.3f}")
        summary.append(dict(method=v, mean_f1=f1.mean(), mean_p=p_.mean(),
                            mean_r=r_.mean(), max_f1=f1.max()))
    pd.DataFrame(summary).to_csv("data/benchmark/tasa14_l2_summary_20260803.csv",
                                 index=False, encoding="utf-8-sig")
    print("-" * 72)
    print(f"{'(對照) 迭代+位準位移':22}{0.458:>9.3f}{0.767:>9.3f}")

    df = pd.DataFrame(per_sat).sort_values("f1", ascending=False)
    print("\n【最佳融合 vote>=2 逐星】")
    print(f"{'衛星':14}{'事件':>5}{'偵測':>5}{'TP':>4}{'FP':>4}{'FN':>5}{'P':>6}{'R':>6}{'F1':>6}")
    for _, r in df.iterrows():
        print(f"{r['name']:14}{r.n_ev:>5}{r.n_det:>5}{r.tp:>4}{r.fp:>4}{r.fn:>5}"
              f"{r.precision:>6.2f}{r.recall:>6.2f}{r.f1:>6.2f}")

    out = Path("data/benchmark/tasa14_l2_compare_20260801.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}")


if __name__ == "__main__":
    main()
