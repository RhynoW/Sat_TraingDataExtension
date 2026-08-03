#!/usr/bin/env python3
"""ops_simulation.py — 值勤流程模擬：候選漏斗、告警負荷與人工覆核工時（回應委員意見）。

委員（第一位建議6、第二位誤警負荷）：期末應以固定窗口模擬值班流程，量化候選數、升級數、
人工核判時間、真正例／漏失、平均告警延遲，並以「每星日／每 1,000 星日」表示 FAR。

做法：以擂台之逐 unit 三層預測（`three_layer_perunit_*.csv`：l1/l2/l3_pred + label + sev +
l3_score）與各衛星 TLE 觀測跨度（星日），推算部署於 N 顆星系之日／週值勤負荷：
  - **候選漏斗**：L1 廣掃候選 → L2 統計確認 → L3 融合最終告警（每 1,000 星日）
  - **告警負荷**：每星日／每 1,000 星日之告警數、精確率、TP／FP
  - **人工覆核工時**：告警數 × 每則覆核分鐘；高信心（l3_score≥0.9）自動升級、其餘批次審
  - **延遲**：引用融合器實測中位延遲（0.1–0.5 h，見 §11／表 2）

用法：python ops_simulation.py [--fleet 284] [--review-min 5] [--horizon-days 7]
"""
from __future__ import annotations
import argparse
import glob
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd
from satdet import config


def sat_days(db, norads):
    """各衛星 TLE 觀測跨度（首末 epoch 差）之總和＝總星日。"""
    con = duckdb.connect(db, read_only=True)
    tot = 0.0
    for nid in norads:
        r = con.execute("SELECT min(epoch_utc), max(epoch_utc) FROM raw_tle_archive "
                        "WHERE norad_id=? AND sma_km IS NOT NULL", [int(nid)]).fetchone()
        if r and r[0] and r[1]:
            tot += (pd.Timestamp(r[1]) - pd.Timestamp(r[0])).total_seconds() / 86400.0
    con.close()
    return tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--perunit", default=sorted(glob.glob(
        "data/benchmark/three_layer_perunit_*.csv"))[-1])
    ap.add_argument("--db", default=config.SPACE_DB)
    ap.add_argument("--fleet", type=int, default=284, help="部署星系規模（顆）")
    ap.add_argument("--review-min", type=float, default=5.0, help="每則告警人工覆核分鐘")
    ap.add_argument("--horizon-days", type=int, default=7)
    ap.add_argument("--escalate", type=float, default=0.90, help="高信心自動升級門檻")
    a = ap.parse_args()

    d = pd.read_csv(a.perunit)
    d.columns = [c.lstrip("﻿") for c in d.columns]
    norads = sorted(d["norad_id"].unique())
    sd = sat_days(a.db, norads)
    n_sats = len(norads)

    y = d["label"].to_numpy(int)
    for layer in ("l1", "l2", "l3"):
        d[layer] = d[f"{layer}_pred"].to_numpy(int)

    # 逐層告警（正確 unit 級）與 TP/FP
    def counts(pred):
        tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
        fn = int(((pred == 0) & (y == 1)).sum())
        return tp, fp, fn
    l1 = counts(d["l1"].to_numpy()); l2 = counts(d["l2"].to_numpy()); l3 = counts(d["l3"].to_numpy())

    per1k = lambda n: n / sd * 1000.0            # 每 1,000 星日
    scale = a.fleet * a.horizon_days              # 目標窗之星日
    fleet_rate = lambda n: n / sd * scale         # 投影到 fleet × horizon

    print("=" * 82)
    print(f"值勤流程模擬｜資料基準：{n_sats} 顆、{sd:,.0f} 星日（逐 unit 三層預測）")
    print(f"部署情境：{a.fleet} 顆星系 × {a.horizon_days} 天窗＝{scale:,} 星日；覆核 {a.review_min:.0f} min/告警")
    print("=" * 82)

    print("\n【候選漏斗｜每 1,000 星日】(寬鬆告警 → 精緻鑑別 → 最終告警)")
    print(f"  L1 廣掃候選 ：{per1k(l1[0]+l1[1]):6.1f}（TP {per1k(l1[0]):.1f} + FP {per1k(l1[1]):.1f}）")
    print(f"  L2 統計確認 ：{per1k(l2[0]+l2[1]):6.1f}（TP {per1k(l2[0]):.1f} + FP {per1k(l2[1]):.1f}）")
    print(f"  L3 最終告警 ：{per1k(l3[0]+l3[1]):6.1f}（TP {per1k(l3[0]):.1f} + FP {per1k(l3[1]):.1f}）")

    tp, fp, fn = l3
    alerts = tp + fp
    prec = tp / alerts if alerts else float("nan")
    esc = int(((d["l3"].to_numpy() == 1) & (d["l3_score"].to_numpy() >= a.escalate)).sum())
    print(f"\n【L3 告警負荷】精確率 {prec:.3f}｜FAR(FP) {per1k(fp):.1f}/1,000 星日 = {fp/sd:.4f}/星日")
    print(f"  高信心自動升級（l3_score≥{a.escalate}）佔 {esc}/{alerts}＝{esc/alerts:.0%}（優先人工）")

    print(f"\n【{a.fleet} 顆 × {a.horizon_days} 天值勤窗投影】")
    A = fleet_rate(alerts); T = fleet_rate(tp); F = fleet_rate(fp)
    daily = A / a.horizon_days
    review_h = A * a.review_min / 60.0
    print(f"  預期最終告警 ：{A:.1f} 則（TP {T:.1f}、FP {F:.1f}）；平均每日 {daily:.1f} 則")
    print(f"  人工覆核工時 ：{review_h:.1f} 人時／{a.horizon_days} 天（每則 {a.review_min:.0f} min）"
          f"＝每日 {review_h/a.horizon_days:.1f} 人時")
    print(f"  漏失（FN）    ：{fleet_rate(fn):.1f} 則（多為 small／貼近雜訊底，見 §10.7）")
    print(f"  平均告警延遲 ：中位 0.1–0.5 h（融合器實測，§11／表 2），遠優於契約 24h")
    print("=" * 82)
    print("判讀：三層漏斗把 L1 廣掃逐級收斂為可負荷之 L3 告警；高信心自動升級使值勤員優先審少量"
          "關鍵告警，其餘批次處理。FAR 與工時以每 1,000 星日／人時計，可直接對映營運排班。")

    out = Path("data/benchmark") / "ops_simulation_20260802.csv"
    pd.DataFrame([
        dict(layer="L1", tp_per1k=per1k(l1[0]), fp_per1k=per1k(l1[1])),
        dict(layer="L2", tp_per1k=per1k(l2[0]), fp_per1k=per1k(l2[1])),
        dict(layer="L3", tp_per1k=per1k(l3[0]), fp_per1k=per1k(l3[1])),
    ]).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}")


if __name__ == "__main__":
    main()
