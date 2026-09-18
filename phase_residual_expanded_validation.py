#!/usr/bin/env python3
"""擴大相位殘差通道驗證樣本：從23星標竿擴大到283顆Starlink（用新重建的
MEME真值 transitions_full_20260918.csv 之 phasing 標籤當事件真值），
與 maneuver_report_builder.compute_phase_residual_experimental() 之
偵測結果比對，計算真實 macro P/R/F1（沿用 tasa14_compare.evaluate() 之
配對容差 TOL_D=1.5 天邏輯）。"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as pd
import numpy as np

import maneuver_report_builder as rb

TOL_D = 1.5   # 天，沿用 tasa14_compare.TOL_D
EVENT_MERGE_D = 3.0  # 天，合併鄰近 phasing 轉換為單一事件（與偵測器合併窗一致）

df = pd.read_csv("data/meme_truth/transitions_full_20260918.csv")
df["t_from"] = pd.to_datetime(df["t_from"], utc=True)
df["t_to"] = pd.to_datetime(df["t_to"], utc=True)

phasing = df[df["poserr_confirmed"] == True].copy()
print(f"poserr_confirmed 轉換總數: {len(phasing)}，涉及 {phasing['norad_id'].nunique()} 顆衛星", flush=True)

# 合併同衛星鄰近 confirmed 轉換為單一事件（ws=最早t_from, we=最晚t_to）
events_by_sat = {}
for nid, g in phasing.groupby("norad_id"):
    g = g.sort_values("t_from").reset_index(drop=True)
    evs = []
    cur_ws, cur_we = g.loc[0, "t_from"], g.loc[0, "t_to"]
    for i in range(1, len(g)):
        if (g.loc[i, "t_from"] - cur_we).total_seconds() <= EVENT_MERGE_D * 86400:
            cur_we = max(cur_we, g.loc[i, "t_to"])
        else:
            evs.append((cur_ws, cur_we))
            cur_ws, cur_we = g.loc[i, "t_from"], g.loc[i, "t_to"]
    evs.append((cur_ws, cur_we))
    events_by_sat[int(nid)] = pd.DataFrame(evs, columns=["ws", "we"])

n_events_total = sum(len(v) for v in events_by_sat.values())
print(f"合併後 phasing 事件總數: {n_events_total}（{len(events_by_sat)} 顆衛星）", flush=True)

import datetime as _dt
d0 = _dt.date(2026, 5, 2)
d1 = _dt.date(2026, 9, 17)

results = []
n_done = 0
for nid, ev in events_by_sat.items():
    n_done += 1
    if n_done % 40 == 0:
        print(f"  進度 {n_done}/{len(events_by_sat)}", flush=True)
    try:
        tle = rb.load_tle(nid, start=d0, end=d1)
    except Exception as e:
        if n_done <= 3:
            print(f"  [skip {nid}] load_tle error: {e}", flush=True)
        continue
    if len(tle) < 10:
        continue
    pr = rb.compute_phase_residual_experimental(tle)
    if pr["status"] != "ok":
        continue
    dets = pd.to_datetime(pr["flagged_epochs"])
    tol = pd.Timedelta(days=TOL_D)
    det_used = np.zeros(len(dets), bool)
    tp = 0
    for _, e in ev.iterrows():
        w0, w1 = e["ws"] - tol, e["we"] + tol
        hit = [i for i, d in enumerate(dets) if w0 <= d <= w1 and not det_used[i]]
        if hit:
            det_used[hit[0]] = True
            tp += 1
    fn = len(ev) - tp
    fp = int((~det_used).sum())
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    results.append(dict(norad=nid, n_ev=len(ev), n_det=len(dets), tp=tp, fp=fp, fn=fn,
                        precision=prec, recall=rec, f1=f1))

res_df = pd.DataFrame(results)
res_df.to_csv("data/benchmark/phase_residual_expanded_283_20260918.csv", index=False)

print("\n=== 擴大樣本結果（n =", len(res_df), "顆衛星, 相較原23星標竿）===", flush=True)
if res_df.empty:
    print("無有效結果（所有衛星皆被跳過），請檢查 load_tle/compute_phase_residual_experimental 狀態", flush=True)
    raise SystemExit(0)
print("macro Precision:", res_df["precision"].mean(), flush=True)
print("macro Recall   :", res_df["recall"].mean(), flush=True)
print("macro F1       :", res_df["f1"].mean(), flush=True)
tp_sum, fp_sum, fn_sum = res_df["tp"].sum(), res_df["fp"].sum(), res_df["fn"].sum()
p_pool = tp_sum / (tp_sum + fp_sum) if (tp_sum + fp_sum) else 0.0
r_pool = tp_sum / (tp_sum + fn_sum) if (tp_sum + fn_sum) else 0.0
f1_pool = 2 * p_pool * r_pool / (p_pool + r_pool) if (p_pool + r_pool) else 0.0
print(f"pooled Precision={p_pool:.4f} Recall={r_pool:.4f} F1={f1_pool:.4f}", flush=True)
print("saved -> data/benchmark/phase_residual_expanded_283_20260918.csv", flush=True)
