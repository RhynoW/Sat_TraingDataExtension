#!/usr/bin/env python3
"""
burn_epoch_detector.py — 機動時刻（burn epoch）偵測器與 8h 分辨率量測（契約 M3）
==========================================================================
統計偵測層已提供變化點分數；本檔將其正式包裝為「burn-epoch 偵測器」：對每個 MEME 機動
episode，取窗內最大變化點分數之 TLE epoch 作為估計 burn 時刻，並以 MEME 真值量測**時刻誤差**
（達成契約「8h 分辨率機動時刻偵測」之量化驗收）。

burn 分數 = |ssa_resid_z| + |cusum_stat|（per_epoch_stats，逐 TLE epoch）。
量測：|估計 burn − 最近真值轉移| 之中位誤差、≤8h／≤24h 命中率，依嚴重度分層。

用法：python burn_epoch_detector.py
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

from satdet import TOL_NS, episodes_by_sat, input_file, record, to_ns
from satdet.common import RANK_SEV as inv, SEV_RANK as _RANK


def main():
    pe_path = input_file("data/statistical_layer/per_epoch_stats_*.csv",
                         step="statistical_layer", key="per_epoch_stats")
    pe = pd.read_csv(pe_path)
    pe.columns = [c.strip().lstrip("﻿") for c in pe.columns]
    pe["ns"] = to_ns(pe["epoch_utc"])
    pe["burn"] = pe["ssa_resid_z"].abs() + pe["cusum_stat"].abs()
    by = {int(nid): (g["ns"].to_numpy(), g["burn"].to_numpy())
          for nid, g in pe.groupby("norad_id")}

    truth_path = input_file("data/meme_truth/transitions_full_*.csv",
                            step="meme_truth", key="transitions_full")
    truth = pd.read_csv(truth_path)
    eps_by = episodes_by_sat(truth)

    errs = {s: [] for s in _RANK}; det = {s: 0 for s in _RANK}; tot = {s: 0 for s in _RANK}
    for nid, eps in eps_by.items():
        ep_ns, ep_burn = by.get(int(nid), (None, None))
        for times, rkk in eps:
            sev = inv[rkk]; tot[sev] += 1
            if ep_ns is None:
                continue
            lo, hi = times.min() - TOL_NS, times.max() + TOL_NS
            m = (ep_ns >= lo) & (ep_ns <= hi)
            if not m.any():
                continue
            burn_est = ep_ns[m][int(ep_burn[m].argmax())]     # 窗內最大分數 epoch = 估計 burn
            err_h = float(np.abs(times - burn_est).min() / 3.6e12)
            det[sev] += 1; errs[sev].append(err_h)

    print("=== Burn-epoch 時刻偵測驗收（vs MEME 真值）===")
    print(f"{'嚴重度':<8}{'episodes':>9}{'偵測':>6}{'中位誤差h':>10}{'≤8h':>8}{'≤24h':>8}")
    rows = []
    for sev in ("large", "medium", "small"):
        e = np.array(errs[sev]); n = tot[sev]; d = det[sev]
        med = float(np.median(e)) if len(e) else float("nan")
        p8 = float((e <= 8).mean()) if len(e) else 0.0
        p24 = float((e <= 24).mean()) if len(e) else 0.0
        print(f"{sev:<8}{n:>9}{d:>6}{med:>10.2f}{p8:>8.2%}{p24:>8.2%}")
        rows.append({"severity": sev, "episodes": n, "detected": d,
                     "median_err_h": round(med, 2), "within_8h": round(p8, 3),
                     "within_24h": round(p24, 3)})
    all_e = np.concatenate([np.array(errs[s]) for s in _RANK]) if any(errs.values()) else np.array([])
    if len(all_e):
        print(f"\n整體：中位時刻誤差 {np.median(all_e):.2f}h；≤8h {np.mean(all_e<=8):.1%}；"
              f"≤24h {np.mean(all_e<=24):.1%}（MEME 取樣解析度 8h → 時刻不確定度下限即 ~8h）")
    out = Path("data/benchmark/burn_epoch_timing.csv")
    pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"表 → {out}")
    record("burn_epoch_detector",
           inputs={"per_epoch_stats": pe_path, "transitions_full": truth_path},
           params={"score": "abs(ssa_resid_z)+abs(cusum_stat)", "tol_h": 24},
           outputs={"burn_epoch_timing": out})


if __name__ == "__main__":
    main()
