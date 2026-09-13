#!/usr/bin/env python3
"""_tasa14_l2_persat_full.py — 重跑 tasa14_l2_compare 之計算，但完整保存
每一顆衛星 × 每一個 L2 通道（cusum/bocpd/ssa/mad3sig/union/vote>=2）的逐星結果，
而非只留 vote>=2。純讀取既有函式，不改動 tasa14_l2_compare.py 本身。
"""
from __future__ import annotations
import sys
import numpy as np
import pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

from tasa14_compare import load_events, load_a, SATS
from tasa14_l2_compare import CHANS, windowed_l2, merge_epochs, fuse_vote, metrics


def main():
    events = load_events()
    variants = CHANS + ["union", "vote>=2"]
    rows = []
    print("計算中（滑動窗 L2，14 星，完整保存每一通道逐星結果）…")
    for nid, nm in SATS:
        t, a = load_a(nid)
        if t is None or len(a) < 60 or nid not in events:
            continue
        ev = events[nid]
        lo = max(t.min(), ev["ws"].min()); hi = min(t.max(), ev["we"].max())
        ev = ev[(ev["ws"] >= lo) & (ev["ws"] <= hi)].reset_index(drop=True)
        if len(ev) == 0:
            continue
        ch = windowed_l2(t, a)
        chm = {c: merge_epochs(ch[c]) for c in CHANS}
        dets = dict(chm)
        dets["union"] = merge_epochs(
            np.concatenate([chm[c].to_numpy() for c in CHANS]) if any(len(chm[c]) for c in CHANS) else [])
        dets["vote>=2"] = fuse_vote(ch)
        for v in variants:
            m = metrics(dets[v], ev, lo, hi)
            rows.append(dict(norad=nid, name=nm, method=v, **m))
        print(f"  {nm:14s} 完成", flush=True)

    df = pd.DataFrame(rows)
    out = "data/benchmark/tasa14_l2_persat_full_20260913.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}（{len(df)} 列 = 14 星 × {len(variants)} 變體）")


if __name__ == "__main__":
    main()
