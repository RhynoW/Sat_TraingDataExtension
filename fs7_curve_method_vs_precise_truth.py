#!/usr/bin/env python3
"""fs7_curve_method_vs_precise_truth.py — 用福衛七號(FORMOSAT-7)之精密星曆
(leoOrb SP3)推估之機動候選事件為真值，比較 TLE 版 Polynomial Fit 重現版、
LOWESS 重現版、本專案規則式方法（iter2 k=8）三者之偵測表現。

**真值來源與誠實聲明**：真值並非官方機動公告（福衛七號非 DORIS/ILRS 衛星，
無此類官方紀錄），而是 `formosat7_leoorb/detect.py` 既有之四項獨立證據判定法
（持久性、弧段一致性、共模檢查、傾角通道，見該模組 docstring），對
`data/formosat7_leoorb/` 之 leoOrb SP3 精密軌道逐日弧段做偵測後，通過全部
四項驗證者判定為「疑似真事件」（見 `fs7_campaign_truth_build.py` 產出之
`data/benchmark/fs7_events_campaigns_20260825.csv`）。此為本專案自建之最佳
可得替代真值，非外部機構發布之正式真值。

**已知的先天限制（誠實記錄）**：福衛七號之候選機動事件量級多為數十公尺
（peak_m 常在 20-250 公尺等級），遠小於本專案其餘 23 星標竿之典型機動量級
（多為公里等級）；TLE 本身之半長軸雜訊底通常已達百公尺至公里等級，故本次
比較預期 TLE 版方法之召回率可能明顯偏低——這是 TLE 資料本身之物理解析度
限制，而非偵測演算法或程式邏輯問題，如實記錄而非隱藏。

用法：python fs7_curve_method_vs_precise_truth.py
輸出：data/benchmark/fs7_curve_method_vs_precise_truth_20260914.csv
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

from tasa14_compare import load_a, evaluate, TOL_D, MERGE_D
from tasa14_pdf_baseline import detect_pred, detect_pdf
from formosat7_leoorb.satmap import SP3_TO_NORAD, SP3_TO_NAME

K_ITER2 = 8


def detect_iter2_local(t, a, k=K_ITER2):
    """本專案規則式基準線（同 master_block1 之 iter2(k=8)）；就地實作避免
    額外相依 tasa14_l3_fusion.py 之 sys.argv 側載機制。"""
    from tasa14_compare import detect_iter
    return detect_iter(t, a, k)


def load_truth_events() -> dict:
    """讀取 fs7_events_campaigns_20260825.csv，篩選 verdict=疑似真事件，
    以 t_start/t_end 為事件視窗，轉為 {norad: DataFrame[ws,we]}。"""
    p = Path("data/benchmark/fs7_events_campaigns_20260825.csv")
    df = pd.read_csv(p)
    df["t_start"] = pd.to_datetime(df["t_start"], utc=True)
    df["t_end"] = pd.to_datetime(df["t_end"], utc=True)
    df = df[df["verdict"].str.contains("真")]
    df["norad"] = df["sp3_sat"].map(SP3_TO_NORAD)
    events = {}
    for nid, g in df.groupby("norad"):
        events[int(nid)] = g[["t_start", "t_end"]].rename(
            columns={"t_start": "ws", "t_end": "we"}).sort_values("ws").reset_index(drop=True)
    return events


def main():
    events = load_truth_events()
    rows = []
    for sp3_id, nid in SP3_TO_NORAD.items():
        nm = SP3_TO_NAME[sp3_id]
        if nid not in events:
            print(f"[{nm}] 無驗證通過之真值事件，跳過", flush=True)
            continue
        t, a = load_a(nid)
        if t is None or len(a) < 30:
            print(f"[{nm}] TLE 資料不足，跳過", flush=True)
            continue
        r_poly = evaluate(nid, events, lambda t_, a_: detect_pred(t_, a_, 50, 1, 1))
        r_low = evaluate(nid, events, lambda t_, a_: detect_pdf(t_, a_, 20, "resid", 1))
        r_ours = evaluate(nid, events, lambda t_, a_: detect_iter2_local(t_, a_))
        for method, r in [("polynomial", r_poly), ("lowess", r_low), ("iter2_k8", r_ours)]:
            if r:
                rows.append(dict(norad=nid, name=nm, method=method, n_ev=r["n_ev"],
                                  tp=r["tp"], fp=r["fp"], fn=r["fn"],
                                  precision=r["precision"], recall=r["recall"], f1=r["f1"]))
        print(f"[{nm}] n_ev={r_poly['n_ev'] if r_poly else '?'} "
              f"poly F1={r_poly['f1']:.3f} low F1={r_low['f1']:.3f} "
              f"ours F1={r_ours['f1']:.3f}" if r_poly and r_low and r_ours else f"[{nm}] 部分方法無結果",
              flush=True)

    df = pd.DataFrame(rows)
    out = Path("data/benchmark/fs7_curve_method_vs_precise_truth_20260914.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}（{len(df)} 列）")
    if len(df):
        print(df.groupby("method")[["precision", "recall", "f1"]].mean())


if __name__ == "__main__":
    main()
