#!/usr/bin/env python3
"""tasa23_ext_arena.py — 路線一擴充擂台:19 星 + GRACE-A/B + GRACE-FO-C/D = 23 星。

真值:ids_truth_ext2.csv(SOE MANV,operator 認證;window-only)。
4 顆新星全部參數凍結 hold-out(本法 iter2 k=8;曲線法全域 pred deg1 k=50;
曲線法逐星 oracle 與原 14 星同一 104 組態網格)。
合併 n=23 之配對檢定(vs oracle 與 vs 全域,雙尾 Wilcoxon)。
用法:python tasa23_ext_arena.py [--skip-oracle]
輸出:data/benchmark/tasa23_ext_20260804.csv
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

import tasa14_compare as tc
from tasa14_compare import load_a, detect_iter2, tai2utc, evaluate
from tasa14_pdf_baseline import detect_pred, detect_pdf
from tasa19_ext_arena import (load_events_ext, EXT_SATS, LAUNCH_EXT, LAUNCH14,
                              K_OURS, GLOBAL_CFG, KS, KS_PRED)

EXT_SATS2 = [(27391, "GRACE-A"), (27392, "GRACE-B"),
             (43476, "GRACE-FO-C"), (43477, "GRACE-FO-D")]
LAUNCH_EXT2 = {27391: 2002, 27392: 2002, 43476: 2018, 43477: 2018}
ALL_SATS23 = list(tc.SATS) + list(EXT_SATS) + list(EXT_SATS2)


def load_events_ext2():
    ev = load_events_ext()
    d = pd.read_csv("ids_truth_set/ids_truth_ext2.csv")
    d["ws"] = tai2utc(d["win_start_tai"]); d["we"] = tai2utc(d["win_end_tai"])
    for nid, g in d.groupby("norad"):
        ev[int(nid)] = g[["ws", "we"]].sort_values("ws").reset_index(drop=True)
    return ev


def main():
    skip_oracle = "--skip-oracle" in sys.argv
    events = load_events_ext2()
    rows = []
    print("== 新 4 星(GRACE 族):本法 iter2(k=8,凍結)與曲線法全域(凍結) ==")
    for nid, nm in EXT_SATS2:
        r1 = evaluate(nid, events, lambda t, a: detect_iter2(t, a, K_OURS))
        r2 = evaluate(nid, events, lambda t, a: detect_pred(t, a, GLOBAL_CFG["k"],
                                                            GLOBAL_CFG["deg"], GLOBAL_CFG["n_iter"]))
        if r1 is None:
            print(f"  {nm:12s} 無可評估重疊(TLE/真值)"); continue
        rows.append(dict(norad=nid, name=nm, method="iter2", **{k: r1[k] for k in
                    ("n_ev", "tp", "fp", "fn", "precision", "recall", "f1")}))
        rows.append(dict(norad=nid, name=nm, method="pdf_global", **{k: r2[k] for k in
                    ("n_ev", "tp", "fp", "fn", "precision", "recall", "f1")}))
        print(f"  {nm:12s} 事件={r1['n_ev']:4d} | iter2 F1={r1['f1']:.3f}"
              f"(P={r1['precision']:.2f} R={r1['recall']:.2f})"
              f" | 曲線全域 F1={r2['f1']:.3f}", flush=True)

    if not skip_oracle:
        print("== 新 4 星:曲線法逐星 oracle(104 組態,與原網格相同)==")
        for nid, nm in EXT_SATS2:
            best = None
            for deg in [1, 2]:
                for ni in [1, 3]:
                    for k in KS_PRED:
                        r = evaluate(nid, events, lambda t, a, k=k, d=deg, n=ni: detect_pred(t, a, k, d, n))
                        if r and (best is None or r["f1"] > best[0]):
                            best = (r["f1"], f"pred_{deg}_iter{ni}/k={k}", r)
            for ch in ["resid", "rate"]:
                for ni in [1, 3]:
                    for k in KS:
                        r = evaluate(nid, events, lambda t, a, k=k, c=ch, n=ni: detect_pdf(t, a, k, c, n))
                        if r and (best is None or r["f1"] > best[0]):
                            best = (r["f1"], f"lowess_{ch}_iter{ni}/k={k}", r)
            if best is None:
                continue
            f1, cfg, r = best
            rows.append(dict(norad=nid, name=nm, method="pdf_oracle", cfg=cfg,
                             **{k: r[k] for k in ("n_ev", "tp", "fp", "fn", "precision", "recall", "f1")}))
            print(f"  {nm:12s} oracle F1={f1:.3f} [{cfg}]", flush=True)

    out = pd.DataFrame(rows)
    p = Path("data/benchmark/tasa23_ext_20260804.csv")
    out.to_csv(p, index=False, encoding="utf-8-sig")
    print(f"→ {p}")

    if skip_oracle:
        return
    it14 = pd.read_csv("data/benchmark/tasa14_iter2_20260804.csv").set_index("norad")["f1"]
    gl14 = pd.read_csv("data/benchmark/tasa14_pdf_baseline_20260803.csv").set_index("norad")["f1"]
    or14 = pd.read_csv("data/benchmark/tasa14_pdf_oracle_20260803.csv").set_index("norad")["f1"]
    e19 = pd.read_csv("data/benchmark/tasa19_ext_20260804.csv") \
            .pivot_table(index="norad", columns="method", values="f1")
    e23 = out.pivot_table(index="norad", columns="method", values="f1")
    mine = pd.concat([it14, e19["iter2"], e23["iter2"]])
    glob = pd.concat([gl14, e19["pdf_global"], e23["pdf_global"]])
    orac = pd.concat([or14, e19["pdf_oracle"], e23["pdf_oracle"]])
    LAUNCH = {**LAUNCH14, **LAUNCH_EXT, **LAUNCH_EXT2}
    print("\n== n=23 擴充擂台配對檢定(iter2,雙尾 Wilcoxon)==")
    for lab, ids in [("全 23 星", list(mine.index)),
                     ("發射年 ≥ 2010", [n for n in mine.index if LAUNCH[n] >= 2010])]:
        for opp_lab, opp in [("oracle", orac), ("全域(同待遇)", glob)]:
            a_, b_ = mine.loc[ids], opp.loc[ids]
            w, pv = stats.wilcoxon(a_, b_)
            print(f"  {lab:10s} vs {opp_lab:10s} n={len(ids)}  {a_.mean():.3f} vs {b_.mean():.3f}"
                  f"  勝/負={int((a_>b_).sum())}/{int((a_<b_).sum())}  p={pv:.4f}")


if __name__ == "__main__":
    main()
