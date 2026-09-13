#!/usr/bin/env python3
"""phase_residual_detector.py — 新增偵測通道，回應案例十一⑤發現之「本專案全部
現有通道皆作用於半長軸(sma)，對相位調整(phasing)機動structurally看不到」問題。

原理：從TLE本身之mean_anomaly_deg + mean_motion（不需MEME，23星標竿全部適用），
以「前一筆TLE之平均運動外推平均近點角」預測下一筆TLE理應之M，與其實際值相減
（wrap至±180°，再乘以a換算成沿軌弧長km）——此「相位殘差」訊號對「軌道週期
暫時改變、事後恢復但累積相位偏移未消失」之機動（phasing）敏感，而sma本身
（此類機動事後幾乎不變）對此結構性看不到。

用法：python phase_residual_detector.py [--quick]
輸出：data/benchmark/phase_residual_persat_20260913.csv
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import duckdb

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

from tasa14_compare import evaluate, TOL_D, MERGE_D, DB
from tasa23_ext_arena import ALL_SATS23, load_events_ext2


def load_a_m_n(nid: int):
    """讀取 sma_km + 緯度幅角 u=(argp+M) + mean_motion(rev/day)，同 load_a() 之
    3小時稀釋規則。

    **重要修正（2026-09-13 廣泛掃描時發現）**：原始版本直接用 TLE 之
    `mean_anomaly_deg` 追蹤沿軌位置，但對近圓軌道（e→0，Starlink/Kuiper/
    OneWeb 絕大多數皆屬此類）而言，近點角 M 與近地點幅角 argp 個別皆是
    數值上退化（ill-defined）的量——近地點位置在圓軌道上無意義，微小定軌
    雜訊即可讓 M 在數十度內劇烈跳動，但兩者之和「緯度幅角 u=argp+M」（衛星
    相對於升交點的實際角位置）才是穩定、有物理意義的量。改用 u 取代原始 M，
    避免對圓軌道衛星產生大量假警報。"""
    for i in range(6):
        try:
            con = duckdb.connect(DB, read_only=True); break
        except duckdb.IOException:
            if i == 5: raise
            time.sleep(2.0 * (i + 1))
    r = con.execute(
        "SELECT epoch_utc, sma_km, mean_anomaly_deg, argp_deg, mean_motion FROM raw_tle_archive "
        "WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc", [nid]).fetchall()
    con.close()
    if not r:
        return None
    t = pd.to_datetime([x[0] for x in r], utc=True)
    a = np.array([float(x[1]) for x in r])
    u = np.array([(float(x[2]) + float(x[3])) % 360.0 for x in r])
    n = np.array([float(x[4]) for x in r])
    ts = t.astype("int64").to_numpy() / 1e9
    keep = [0]
    for i in range(1, len(ts)):
        if ts[i] - ts[keep[-1]] >= 3.0 * 3600:
            keep.append(i)
    keep = np.array(keep)
    return dict(t=t[keep], a=a[keep], M=u[keep], n=n[keep])


def phase_residual_km(d: dict) -> np.ndarray:
    """相位殘差訊號（km，沿軌弧長）。residual[i] = wrap180(u[i] - predicted u[i])
    * (pi/180) * a[i]，predicted以第i-1筆之平均運動外推。d["M"] 實際存放的是
    緯度幅角 u=argp+M（見 load_a_m_n 說明），非原始平均近點角。"""
    t, a, M, n = d["t"], d["a"], d["M"], d["n"]
    tsec = t.astype("int64").to_numpy() / 1e9
    n_pts = len(a)
    resid = np.full(n_pts, np.nan)
    for i in range(1, n_pts):
        dt_days = (tsec[i] - tsec[i - 1]) / 86400.0
        predicted_orbits = n[i - 1] * dt_days
        predicted_M = (M[i - 1] + predicted_orbits * 360.0) % 360.0
        diff_deg = (M[i] - predicted_M + 180.0) % 360.0 - 180.0   # wrap to [-180,180)
        resid[i] = np.radians(diff_deg) * a[i]
    return resid


def detect_phase_residual(d: dict, k=6.0, n_iter=3):
    t = d["t"]
    tsec = t.astype("int64").to_numpy() / 1e9
    resid = phase_residual_km(d)
    n_pts = len(resid)
    mask = np.zeros(n_pts, bool)
    for _ in range(n_iter):
        s = resid[np.isfinite(resid) & ~mask]
        if len(s) < 10:
            break
        med = np.median(s); mad = 1.4826 * np.median(np.abs(s - med))
        if not np.isfinite(mad) or mad == 0:
            break
        newmask = np.isfinite(resid) & (np.abs(resid - med) > k * mad)
        if newmask.sum() == mask.sum():
            mask = newmask; break
        mask = newmask
    s = resid[np.isfinite(resid)]
    med = np.median(s); mad = 1.4826 * np.median(np.abs(s - med))
    if not np.isfinite(mad) or mad == 0:
        return pd.to_datetime([])
    idx = np.where(np.isfinite(resid) & (np.abs(resid - med) > k * mad))[0]
    if len(idx) == 0:
        return pd.to_datetime([])
    dets, grp = [], [idx[0]]
    for j in idx[1:]:
        if tsec[j] - tsec[grp[-1]] <= MERGE_D * 86400:
            grp.append(j)
        else:
            best = grp[int(np.argmax(np.abs(resid[grp] - med)))]
            dets.append(t[best]); grp = [j]
    best = grp[int(np.argmax(np.abs(resid[grp] - med)))]
    dets.append(t[best])
    return pd.to_datetime(sorted(dets))


def main():
    quick = "--quick" in sys.argv
    events = load_events_ext2()
    sats = ALL_SATS23[:3] if quick else ALL_SATS23

    rows = []
    t0 = time.time()
    for nid, nm in sats:
        d = load_a_m_n(nid)
        if d is None or len(d["a"]) < 60 or nid not in events:
            print(f"  {nm:14s} 跳過（資料不足）", flush=True)
            continue
        dets = detect_phase_residual(d)
        r = evaluate(nid, events, lambda t_, a_, dd=dets: dd)
        if r:
            rows.append(dict(norad=nid, name=nm, method="phase_residual", **{
                k: v for k, v in r.items() if k != "norad"}))
            print(f"[{nm}] F1={r['f1']:.3f} P={r['precision']:.2f} R={r['recall']:.2f} "
                  f"({time.time()-t0:.0f}s)", flush=True)

    df = pd.DataFrame(rows)
    out = Path("data/benchmark/phase_residual_persat_20260913.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}（{len(df)} 列，耗時 {time.time()-t0:.0f}s）")
    if len(df):
        print(f"平均 F1={df['f1'].mean():.3f} P={df['precision'].mean():.3f} R={df['recall'].mean():.3f}")


if __name__ == "__main__":
    main()
