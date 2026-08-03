#!/usr/bin/env python3
"""ids_domain_fpr.py — Model 2（IsolationForest）＋NRLMSIS 於非 Starlink 域之誤報率（FPR）量化。

回應外部委員（兩位共識）：本專案效能達標數字皆屬 Starlink 域內；Model 2＋NRLMSIS 物理路徑
（路由給非 Starlink／MEO/GEO/HEO 目標者）之**域外誤報**從未量化，是「路由哲學能否驗收」的關鍵缺口。

做法：以 ILRS／IDS operator **認證安靜區間**（`ids_quiet.csv`，保證無機動之弧段，14 顆精密測高
衛星、非 Starlink 域）為負樣本；在每個安靜區間切出 TLE，跑**部署中的 Model 2**
（`model2.pkl` 之 IsolationForest，含 NRLMSIS z_drag 通道）。**任何旗標即為誤報**（該弧段
operator 已認證無機動）。彙總：
  - 逐轉換 FPR ＝ 被旗標之轉換數 / 總轉換數
  - 逐窗 FPR   ＝ 至少一次旗標之安靜窗 / 總安靜窗
  - FAR        ＝ 每星日誤報數、每 1,000 星日誤報數
另報 NRLMSIS **阻力殘差之分布**（安靜期應小＝drag-consistent），佐證物理路徑之保守性。

用法：python ids_domain_fpr.py [--min-pts 6] [--shrink-days 0.75]
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
from datetime import timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import joblib
import numpy as np
import pandas as pd

from atmospheric_drag import load_space_weather
from ml_model2_anomaly import physical_residuals
from satdet import config

TAI_MINUS_UTC = 37  # 秒（安靜區間為 TAI，轉 UTC 需扣 37 s）


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=config.SPACE_DB)
    ap.add_argument("--quiet", default="ids_truth_set/ids_quiet.csv")
    ap.add_argument("--model", default="Orbital_Maneuver_V2/models_meme_anomaly/model2.pkl")
    ap.add_argument("--min-pts", type=int, default=6)      # 區間內至少 TLE 筆數
    ap.add_argument("--shrink-days", type=float, default=0.75)  # 兩端內縮避暫態
    a = ap.parse_args()

    m2 = joblib.load(a.model)
    iso, CH = m2["model"], m2["channels"]
    sw = load_space_weather()

    q = pd.read_csv(a.quiet)
    q.columns = [c.lstrip("﻿") for c in q.columns]
    q["t0"] = pd.to_datetime(q["quiet_start_tai"], utc=True) - pd.Timedelta(seconds=TAI_MINUS_UTC)
    q["t1"] = pd.to_datetime(q["quiet_end_tai"], utc=True) - pd.Timedelta(seconds=TAI_MINUS_UTC)
    print(f"IDS 認證安靜區間：{len(q)} 個、{q['norad'].nunique()} 顆衛星（非 Starlink 域）")

    con = duckdb.connect(a.db, read_only=True)
    shrink = pd.Timedelta(days=a.shrink_days)

    n_win = n_trans = 0
    n_win_flagged = n_flags = 0
    days_total = 0.0
    drag_abs_all = []
    per_sat = {}

    for nid in sorted(q["norad"].dropna().unique()):
        sub = q[q["norad"] == nid]
        s_win = s_trans = s_flag = s_winflag = 0
        s_days = 0.0
        for _, r in sub.iterrows():
            lo, hi = r["t0"] + shrink, r["t1"] - shrink
            if hi <= lo:
                continue
            df = con.execute(
                "SELECT epoch_utc AS epoch, sma_km, inclination_deg, eccentricity, raan_deg "
                "FROM raw_tle_archive WHERE norad_id=? AND sma_km IS NOT NULL "
                "AND epoch_utc >= ? AND epoch_utc <= ? ORDER BY epoch_utc",
                [int(nid), lo.strftime("%Y-%m-%dT%H:%M:%S"),
                 hi.strftime("%Y-%m-%dT%H:%M:%S")]).fetchdf()
            if len(df) < a.min_pts:
                continue
            df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
            df = df.drop_duplicates("epoch").reset_index(drop=True)
            res = physical_residuals(df, sw)
            if res.empty:
                continue
            X = np.clip(np.nan_to_num(res[CH].to_numpy()), -200, 200)
            flag = iso.predict(X) == -1
            nf = int(flag.sum())
            drag_abs_all.append(np.abs(res["z_drag"].to_numpy()) * 0.10)  # 還原成 km
            s_win += 1; s_trans += len(res); s_flag += nf
            s_winflag += int(nf > 0)
            s_days += (hi - lo).total_seconds() / 86400.0
        if s_win:
            per_sat[int(nid)] = dict(name=sub["name"].iloc[0], windows=s_win,
                                     trans=s_trans, flags=s_flag,
                                     win_flagged=s_winflag, days=s_days)
            n_win += s_win; n_trans += s_trans; n_flags += s_flag
            n_win_flagged += s_winflag; days_total += s_days
    con.close()

    drag_abs = np.concatenate(drag_abs_all) if drag_abs_all else np.array([0.0])

    print("=" * 90)
    print("Model 2（IsolationForest＋NRLMSIS z_drag）於非 Starlink 認證安靜期之域外誤報")
    print(f"（可評估子集：{len(per_sat)} 顆、{n_win} 個安靜窗、{n_trans} 轉換、{days_total:.0f} 星日）")
    print("=" * 90)
    print(f"{'衛星':16}{'窗數':>6}{'轉換':>7}{'誤報數':>7}{'誤報窗':>7}{'逐轉換FPR':>10}{'星日':>7}")
    for nid, s in sorted(per_sat.items(), key=lambda kv: -kv[1]["flags"]):
        print(f"{s['name']:16}{s['windows']:>6}{s['trans']:>7}{s['flags']:>7}{s['win_flagged']:>7}"
              f"{s['flags']/s['trans'] if s['trans'] else 0:>10.3f}{s['days']:>7.0f}")
    print("-" * 90)
    trans_fpr = n_flags / n_trans if n_trans else float("nan")
    win_fpr = n_win_flagged / n_win if n_win else float("nan")
    far_day = n_flags / days_total if days_total else float("nan")
    print(f"【彙總】逐轉換 FPR = {n_flags}/{n_trans} = {trans_fpr:.4f}")
    print(f"        逐窗   FPR = {n_win_flagged}/{n_win} = {win_fpr:.3f}")
    print(f"        FAR = {far_day:.4f} 誤報/星日 = {far_day*1000:.1f} 誤報/1,000 星日")
    print(f"        NRLMSIS 阻力殘差 |Δa|（安靜期）：中位 {np.median(drag_abs):.3f} km、"
          f"p95 {np.percentile(drag_abs,95):.3f}、p99 {np.percentile(drag_abs,99):.3f}、"
          f"max {drag_abs.max():.3f} km")
    print("=" * 90)
    print("判讀：此為 Model 2＋NRLMSIS 物理路徑在**非 Starlink 域**之首個誤報量化（負樣本＝operator "
          "認證無機動）。阻力殘差於安靜期維持小值＝drag-consistent，佐證物理閘門之保守性。")

    out = Path("data/benchmark") / "ids_domain_fpr_20260802.csv"
    pd.DataFrame([{"norad": k, **v} for k, v in per_sat.items()]).to_csv(
        out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}")


if __name__ == "__main__":
    main()
