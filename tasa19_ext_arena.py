#!/usr/bin/env python3
"""tasa19_ext_arena.py — (b) 擴充擂台:14 星 + SPOT-2/3/4/5 + Sentinel-6B = 19 星。

對 5 顆新星計算:本法 iter2(k=8,參數凍結不重調)、曲線法全域最佳(組態凍結:
pred deg1 iter1 k=50)、曲線法逐星 oracle(與原 14 星同一 104 組態網格)。
再與原 14 星結果合併,做 n=19 之配對檢定(vs oracle 與 vs 全域,雙尾 Wilcoxon)。
真值:ids_truth.csv + ids_truth_ext.csv(SPOT/S6B 為 window-only)。
用法:python tasa19_ext_arena.py [--skip-oracle](先跑快的部分)
輸出:data/benchmark/tasa19_ext_20260804.csv
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

EXT_SATS = [(20436, "SPOT-2"), (22823, "SPOT-3"), (25260, "SPOT-4"),
            (27421, "SPOT-5"), (66514, "Sentinel-6B")]
LAUNCH_EXT = {20436: 1990, 22823: 1993, 25260: 1998, 27421: 2002, 66514: 2025}
LAUNCH14 = {22076: 1992, 26997: 2001, 27386: 2002, 33105: 2008, 36508: 2010,
            37781: 2011, 39086: 2013, 41240: 2016, 41335: 2016, 43437: 2018,
            46469: 2020, 46984: 2020, 48621: 2021, 54754: 2022}
K_OURS = 8
GLOBAL_CFG = dict(k=50, deg=1, n_iter=1)      # 曲線法全域最佳(凍結)
KS = [3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30]
KS_PRED = KS + [40, 50, 60, 80]


def load_events_ext():
    ev14 = tc.load_events()
    d = pd.read_csv("ids_truth_set/ids_truth_ext.csv")
    d["ws"] = tai2utc(d["win_start_tai"]); d["we"] = tai2utc(d["win_end_tai"])
    for nid, g in d.groupby("norad"):
        ev14[int(nid)] = g[["ws", "we"]].sort_values("ws").reset_index(drop=True)
    return ev14


def main():
    skip_oracle = "--skip-oracle" in sys.argv
    events = load_events_ext()
    rows = []
    print("== 新 5 星:本法 iter2(k=8,凍結)與曲線法全域(凍結) ==")
    for nid, nm in EXT_SATS:
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
        print("== 新 5 星:曲線法逐星 oracle(104 組態,與原 14 星同網格)==")
        for nid, nm in EXT_SATS:
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
    p = Path("data/benchmark/tasa19_ext_20260804.csv")
    out.to_csv(p, index=False, encoding="utf-8-sig")
    print(f"→ {p}")

    # ── n=19 合併檢定 ──
    if skip_oracle:
        return
    it14 = pd.read_csv("data/benchmark/tasa14_iter2_20260804.csv").set_index("norad")["f1"]
    gl14 = pd.read_csv("data/benchmark/tasa14_pdf_baseline_20260803.csv").set_index("norad")["f1"]
    or14 = pd.read_csv("data/benchmark/tasa14_pdf_oracle_20260803.csv").set_index("norad")["f1"]
    ext = out.pivot_table(index="norad", columns="method", values="f1")
    mine = pd.concat([it14, ext["iter2"]])
    glob = pd.concat([gl14, ext["pdf_global"]])
    orac = pd.concat([or14, ext["pdf_oracle"]])
    LAUNCH = {**LAUNCH14, **LAUNCH_EXT}
    print("\n== n=19 擴充擂台配對檢定(iter2,雙尾 Wilcoxon)==")
    for lab, ids in [("全 19 星", list(mine.index)),
                     ("發射年 ≥ 2010", [n for n in mine.index if LAUNCH[n] >= 2010])]:
        for opp_lab, opp in [("oracle", orac), ("全域(同待遇)", glob)]:
            a_, b_ = mine.loc[ids], opp.loc[ids]
            w, pv = stats.wilcoxon(a_, b_)
            print(f"  {lab:10s} vs {opp_lab:10s} n={len(ids)}  {a_.mean():.3f} vs {b_.mean():.3f}"
                  f"  勝/負={int((a_>b_).sum())}/{int((a_<b_).sum())}  p={pv:.4f}")


if __name__ == "__main__":
    main()
