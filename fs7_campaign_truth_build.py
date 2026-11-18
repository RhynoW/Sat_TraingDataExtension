#!/usr/bin/env python3
"""
fs7_campaign_truth_build.py — 四段新 campaign 的 SP3 事件真值建置
==================================================================
期刊審查核心第 2 項：對 2024-07、2024-11/12、2025-05、2026-01 四段新下載之
leoOrb SP3 跑既有事件驗證管線（formosat7_leoorb.detect：SP3 偵測 + 四項一致性
檢查），產出已驗證事件與幅度分箱，補 300 m–1 km 樣本空洞。

2026-01 段標記 holdout=True（保留為從未參與校準之測試段）。

輸出：
  data/benchmark/fs7_events_campaigns_20260825.csv   逐事件（含 verdict/campaign）
  主控台：各段候選→通過統計 + 全期幅度分箱表
用法：python fs7_campaign_truth_build.py
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd

from formosat7_leoorb import archive, detect
from formosat7_leoorb.download import DEFAULT_CACHE_DIR, day_tag

CAMPAIGNS = [
    ("2024-07",    date(2024, 7, 8),  date(2024, 8, 1),  False),
    ("2024-11/12", date(2024, 11, 18), date(2024, 12, 13), False),
    ("2025-05",    date(2025, 5, 1),  date(2025, 5, 25), False),
    ("2026-01",    date(2026, 1, 13), date(2026, 2, 3),  True),   # holdout
]


def day_range(d0: date, d1: date):
    d = d0
    while d <= d1:
        yield d
        d += timedelta(days=1)


def main():
    all_ev = []
    for name, d0, d1, holdout in CAMPAIGNS:
        paths = []
        for d in day_range(d0, d1):
            p = DEFAULT_CACHE_DIR / f"leoOrb_{day_tag(d)}.tar.gz"
            if p.exists():
                paths.append(p)
        print(f"\n=== {name}（{d0} ~ {d1}，{len(paths)} 個每日包）===")
        if not paths:
            print("  無資料，跳過")
            continue
        df = pd.concat([archive.load_leoorb_tar(p) for p in paths], ignore_index=True)
        print(f"  弧段資料 {len(df):,} epoch 列")
        series = detect.build_series(df)
        print(f"  連續序列：{len(series)} 星")
        ev = detect.detect_events(series)
        ev = detect.verify(ev)
        if ev.empty:
            print("  無候選事件")
            continue
        ev["campaign"] = name
        ev["holdout"] = holdout
        n_ok = int((ev["verdict"] == "疑似真事件").sum())
        print(f"  候選 {len(ev)} 段 → 通過四項一致性檢查 {n_ok} 段")
        all_ev.append(ev)

    if not all_ev:
        print("全部無事件")
        return
    ev = pd.concat(all_ev, ignore_index=True)
    out = Path("data/benchmark/fs7_events_campaigns_20260825.csv")
    ev.to_csv(out, index=False, encoding="utf-8-sig")

    ok = ev[ev["verdict"] == "疑似真事件"].copy()
    ok["amp_m"] = ok["step_m"].abs()
    bins = [0, 50, 100, 300, 1000, 3000, np.inf]
    labels = ["1–50 m", "50–100 m", "100–300 m", "300 m–1 km", "1–3 km", ">3 km"]
    ok["bin"] = pd.cut(ok["amp_m"], bins, labels=labels)
    print("\n===== 四段合計：已驗證事件幅度分箱 =====")
    tab = ok.groupby(["bin", "campaign"], observed=True).size().unstack(fill_value=0)
    tab["合計"] = tab.sum(axis=1)
    print(tab.to_string())
    print(f"\n【300 m–1 km 補樣】新增 {int((ok['bin']=='300 m–1 km').sum())} 事件"
          f"（原僅 3）；其中 holdout(2026-01)佔 "
          f"{int(((ok['bin']=='300 m–1 km') & ok['holdout']).sum())}")
    print(f"輸出：{out}")


if __name__ == "__main__":
    main()
