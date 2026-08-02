#!/usr/bin/env python3
"""
thrust_arc_catalog.py — 規模化推力弧型錄：逐分鐘 MEME 才有的「時間結構」
========================================================================
承 P1 負面結果之結論——時間結構在 8h TLE 被抹平、無助於偵測；但在**逐分鐘 MEME
檔**上，一次機動是有豐富形態的推力弧。本腳本自 data/raw 的逐分鐘 MEME 檔，規模化
萃取每次「機動作業（campaign）」的形態特徵，並據以分型（連續電推 vs 脈衝式），
展示 8h TLE 看不到、唯高解析度可得的資訊。

每個 campaign 之形態特徵（由 burn_arc_profiler 之弧剖面聚合而得）：
  dur_h        作業總時長（電推長達數小時–數日，脈衝式短）
  n_arcs       逐軌微點火段數（電推 phasing 動輒數十–數百；脈衝式個位數）
  peak_da_km   最強單步半長軸變化
  dv_ms        換算 ΔV（(Δa/2)·n）
  seg_per_h    微點火節奏（n_arcs / dur_h）

輸出：data/benchmark/thrust_arc_catalog_{date}.csv、主控台統計＋分型。
用法：python thrust_arc_catalog.py [--max-sats N] [--max-files M]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

from burn_arc_profiler import (RAW_DIR, parse_ephemeris_file, osculating_sma,
                               profile_arcs, merge_file_arcs)


def catalog_sat(sat: str, max_files: int | None):
    d = RAW_DIR / sat
    files = sorted(d.glob("*.txt"))
    if max_files:
        files = files[:max_files]
    per_file = {}
    for f in files:
        try:
            _, df = parse_ephemeris_file(f, sat)
            arcs = profile_arcs(osculating_sma(df))
            if not arcs.empty:
                per_file[f.name] = arcs
        except Exception:
            continue
    camps = merge_file_arcs(per_file)
    if camps.empty:
        return camps
    camps["sat"] = sat
    camps["dur_h"] = ((camps["t_end"] - camps["t_start"]).dt.total_seconds() / 3600).round(2)
    camps["peak_da_km"] = camps["peak_da"].abs().round(3)
    a_ref = 6928.0  # ~550 km Starlink；僅供 ΔV 量級換算
    n = np.sqrt(398600.4418 / a_ref ** 3)
    camps["dv_ms"] = (camps["peak_da_km"] / 2 * n * 1000).round(4)
    camps["seg_per_h"] = (camps["n_arcs"] / camps["dur_h"].clip(lower=0.1)).round(2)
    return camps[["sat", "t_start", "t_end", "dur_h", "n_arcs",
                  "peak_da_km", "dv_ms", "seg_per_h"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-sats", type=int, default=25)
    ap.add_argument("--max-files", type=int, default=None)
    args = ap.parse_args()

    sats = sorted(p.name for p in RAW_DIR.iterdir() if p.is_dir())[: args.max_sats]
    print(f"掃描 {len(sats)} 顆星之逐分鐘 MEME 檔（推力弧剖面）…", flush=True)

    all_camps = []
    for k, sat in enumerate(sats, 1):
        c = catalog_sat(sat, args.max_files)
        if not c.empty:
            all_camps.append(c)
        if k % 5 == 0:
            done = sum(len(x) for x in all_camps)
            print(f"  {k}/{len(sats)} 顆 … 累計 {done} 個機動作業", flush=True)

    if not all_camps:
        print("無機動作業偵出"); return
    cat = pd.concat(all_camps, ignore_index=True)
    nsat = cat["sat"].nunique()

    print("\n" + "=" * 74)
    print(f"推力弧型錄：{nsat} 顆星、{len(cat)} 個機動作業（逐分鐘 MEME）")
    print("=" * 74)

    def q(col):
        v = cat[col]
        return f"中位 {v.median():.2f}｜IQR {v.quantile(.25):.2f}–{v.quantile(.75):.2f}｜max {v.max():.2f}"
    print(f"  作業時長 dur_h    : {q('dur_h')}")
    print(f"  微點火段數 n_arcs : {q('n_arcs')}")
    print(f"  峰值單步 peak_da_km: {q('peak_da_km')}")
    print(f"  ΔV(m/s)          : {q('dv_ms')}")
    print(f"  微點火節奏 seg_per_h: {q('seg_per_h')}")

    # ── 形態分型（規則式；電推連續 vs 脈衝式 vs 短微調）──
    def typ(r):
        if r["n_arcs"] >= 5 and r["dur_h"] >= 3:
            return "連續電推 phasing（多段長弧）"
        if r["peak_da_km"] >= 2.0 and r["dur_h"] < 3:
            return "脈衝式變軌（短、單步大）"
        return "短微調/站位保持"
    cat["morph"] = cat.apply(typ, axis=1)
    print("\n  機動作業形態分型（規則式）：")
    for m, g in cat.groupby("morph"):
        print(f"    {m:<26} {len(g):>5} 個（{100*len(g)/len(cat):>4.1f}%）"
              f"｜中位 dur {g['dur_h'].median():.1f}h、段數 {g['n_arcs'].median():.0f}、"
              f"ΔV {g['dv_ms'].median():.3f}")

    print("\n  判讀：這五個形態特徵在 8h TLE 上完全不可得（一次機動只剩單一階躍）；")
    print("        逐分鐘 MEME 揭露電推「逐軌分段點火」的微結構，可支援機動『型態』分類。")

    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    outp = Path("data/benchmark") / f"thrust_arc_catalog_{date}.csv"
    outp.parent.mkdir(parents=True, exist_ok=True)
    cat.to_csv(outp, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {outp}")


if __name__ == "__main__":
    main()
