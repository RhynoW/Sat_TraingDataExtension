#!/usr/bin/env python3
"""lit_tier2_reproductions.py — 案例十一 Tier2「可行但需更多設計」4 篇文獻方法之
重現實作，與本專案完全相同驗證基準（tasa14_compare.evaluate）在 23 星標竿上比較。

實作方法（皆為本專案依論文方法精神重現之簡化版，非原始程式碼；每項皆誠實
標註簡化之處）：
  7. Holzinger, Scheeres & Alfriend, 2012（控制距離度量）：原文為完整最優控制
     理論+協方差傳播框架（僅摘要層級可查證，無法精確重現）。本專案簡化為
     「Δv 代理控制成本，除以觀測間隔平方根做不確定度正規化」——核心差異化
     設計是門檻依「距離上次觀測多久」動態調整（擴散不確定度假設 ~√dt），
     而非其餘方法之經驗MAD正規化。
  8. San-Juan et al., 2017（Hybrid SGP4/HTLE）：從該衛星自身之逐TLE SGP4
     自洽殘差歷史，擬合「誤差隨外推時間成長」之冪次模型(log-log線性)作為
     「捆綁誤差模型」，再用此模型正規化新殘差後才套門檐——直接實作論文
     「為TLE配一份誤差成長模型」之核心概念。
  9. Isolation Forest 獨立標竿測試：本專案既有 ml_model2_anomaly.py 已採用
     此工具但從未單獨（不搭配融合）跑過標準P/R/F1評測，此處補做公平的
     單一方法對照點。
  10. PatchTST「預測—殘差」簡化代理：受限於單顆衛星僅數千點資料量不足以
      訓練真正Transformer，改用「用前 patch_len 點預測下一點」之 Ridge
      迴歸（在全序列上一次性訓練，近似patch化＋預測殘差之精神），非深度
      學習版本，已誠實標註為簡化代理。

用法：python lit_tier2_reproductions.py [--quick]
輸出：data/benchmark/lit_tier2_persat_20260913.csv
"""
from __future__ import annotations
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import duckdb

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
warnings.filterwarnings("ignore")

from tasa14_compare import load_a, evaluate, TOL_D, MERGE_D, DB
from tasa23_ext_arena import ALL_SATS23, load_events_ext2
from mpt_maneuver_reconstruct import dv_from_da

MU_KM = 398600.4418


def _merge_and_pick(t, tsec, idx, score):
    if len(idx) == 0:
        return pd.to_datetime([])
    dets, grp = [], [idx[0]]
    for j in idx[1:]:
        if tsec[j] - tsec[grp[-1]] <= MERGE_D * 86400:
            grp.append(j)
        else:
            best = grp[int(np.argmax(np.abs(score[grp])))]
            dets.append(t[best]); grp = [j]
    best = grp[int(np.argmax(np.abs(score[grp])))]
    dets.append(t[best])
    return pd.to_datetime(sorted(dets))


# ═══════════════ 7. Holzinger et al. 2012（控制距離代理）═══════════════

def detect_holzinger2012(t, a, k=6.0):
    tsec = t.astype("int64").to_numpy() / 1e9
    da = np.diff(a, prepend=a[0])
    dt = np.diff(tsec, prepend=tsec[1] - tsec[0] if len(tsec) > 1 else 1.0)
    dt_days = np.maximum(dt, 60.0) / 86400.0
    dv = dv_from_da(da, a)                       # Δv 代理（m/s），控制成本正比於此
    control_dist = dv / np.sqrt(dt_days)          # 除以 √dt：擴散不確定度正規化
    med = np.median(control_dist)
    mad = 1.4826 * np.median(np.abs(control_dist - med))
    if not np.isfinite(mad) or mad == 0:
        return pd.to_datetime([])
    idx = np.where(np.abs(control_dist - med) > k * mad)[0]
    return _merge_and_pick(t, tsec, idx, control_dist - med)


# ═══════════════ 8. San-Juan et al. 2017（Hybrid SGP4／HTLE誤差模型）═══════════════

def _load_tle_lines(nid: int):
    for i in range(6):
        try:
            con = duckdb.connect(DB, read_only=True); break
        except duckdb.IOException:
            if i == 5: raise
            time.sleep(2.0 * (i + 1))
    r = con.execute(
        "SELECT epoch_utc, sma_km, line1, line2 FROM raw_tle_archive "
        "WHERE norad_id=? AND sma_km IS NOT NULL AND line1 IS NOT NULL "
        "ORDER BY epoch_utc", [nid]).fetchall()
    con.close()
    if not r:
        return None, None, None, None
    t = pd.to_datetime([x[0] for x in r], utc=True)
    sma = np.array([float(x[1]) for x in r])
    l1 = [x[2] for x in r]; l2 = [x[3] for x in r]
    ts = t.astype("int64").to_numpy() / 1e9
    keep = [0]
    for i in range(1, len(ts)):
        if ts[i] - ts[keep[-1]] >= 3.0 * 3600:
            keep.append(i)
    keep = np.array(keep)
    return t[keep], sma[keep], [l1[i] for i in keep], [l2[i] for i in keep]


def _sgp4_self_consistency(nid: int):
    """對每一對相鄰TLE，用前一筆SGP4傳播至後一筆epoch，回傳
    (dt_days[], resid[]=後筆sma自值-傳播值, t[], sma[])。"""
    from sgp4.api import Satrec, jday
    t, sma, l1, l2 = _load_tle_lines(nid)
    if t is None or len(t) < 20:
        return None
    n = len(t)
    dt_days = np.full(n, np.nan)
    resid = np.full(n, np.nan)
    for i in range(1, n):
        try:
            sat = Satrec.twoline2rv(l1[i - 1], l2[i - 1])
            dt_ = t[i].to_pydatetime()
            jd, fr = jday(dt_.year, dt_.month, dt_.day, dt_.hour, dt_.minute,
                          dt_.second + dt_.microsecond / 1e6)
            e, r, v = sat.sgp4(jd, fr)
            if e != 0:
                continue
            rm = float(np.linalg.norm(r)); vm = float(np.linalg.norm(v))
            energy = vm ** 2 / 2.0 - MU_KM / rm
            a_pred = -MU_KM / (2.0 * energy)
            resid[i] = sma[i] - a_pred
            dt_days[i] = (t[i] - t[i - 1]).total_seconds() / 86400.0
        except Exception:
            continue
    return dict(t=t, sma=sma, dt_days=dt_days, resid=resid)


def detect_sanjuan2017(nid: int, k=4.0):
    info = _sgp4_self_consistency(nid)
    if info is None:
        return pd.to_datetime([]), None
    t, dt_days, resid = info["t"], info["dt_days"], info["resid"]
    valid = np.isfinite(dt_days) & np.isfinite(resid) & (dt_days > 0) & (np.abs(resid) > 1e-9)
    if valid.sum() < 15:
        return pd.to_datetime([]), t
    logdt = np.log(dt_days[valid])
    logerr = np.log(np.abs(resid[valid]))
    slope, intercept = np.polyfit(logdt, logerr, 1)          # 「捆綁誤差模型」：|err| ~ exp(b)*dt^slope
    pred_scale = np.exp(intercept) * np.power(np.maximum(dt_days, 1e-3), slope)
    normalized = np.where(np.isfinite(resid), resid / np.maximum(pred_scale, 1e-9), np.nan)
    nv = normalized[np.isfinite(normalized)]
    med = np.median(nv); mad = 1.4826 * np.median(np.abs(nv - med))
    if not np.isfinite(mad) or mad == 0:
        return pd.to_datetime([]), t
    tsec = t.astype("int64").to_numpy() / 1e9
    idx = np.where(np.isfinite(normalized) & (np.abs(normalized - med) > k * mad))[0]
    return _merge_and_pick(t, tsec, idx, np.nan_to_num(normalized - med)), t


# ═══════════════ 9. Isolation Forest 獨立標竿 ═══════════════

def detect_isolation_forest(t, a, contamination=0.08):
    from sklearn.ensemble import IsolationForest
    tsec = t.astype("int64").to_numpy() / 1e9
    da = np.diff(a, prepend=a[0])
    dt_h = np.diff(tsec, prepend=tsec[1] - tsec[0] if len(tsec) > 1 else 3600.0) / 3600.0
    X = np.column_stack([da, da / np.maximum(dt_h, 0.1)])
    if len(X) < 30:
        return pd.to_datetime([])
    clf = IsolationForest(n_estimators=200, contamination=contamination, random_state=42)
    pred = clf.fit_predict(X)
    score = -clf.score_samples(X)                # 越大越異常
    idx = np.where(pred == -1)[0]
    return _merge_and_pick(t, tsec, idx, score)


# ═══════════════ 10. PatchTST「預測—殘差」簡化代理 ═══════════════

def detect_patchtst_proxy(t, a, patch_len=16, k=5.0):
    from sklearn.linear_model import Ridge
    n = len(a)
    if n < patch_len + 30:
        return pd.to_datetime([])
    X = np.stack([a[i:i + patch_len] for i in range(n - patch_len)])
    y = a[patch_len:]
    reg = Ridge(alpha=1.0)
    reg.fit(X, y)
    pred = reg.predict(X)
    resid = np.full(n, np.nan)
    resid[patch_len:] = y - pred
    valid = np.isfinite(resid)
    med = np.median(resid[valid]); mad = 1.4826 * np.median(np.abs(resid[valid] - med))
    if not np.isfinite(mad) or mad == 0:
        return pd.to_datetime([])
    tsec = t.astype("int64").to_numpy() / 1e9
    idx = np.where(valid & (np.abs(resid - med) > k * mad))[0]
    return _merge_and_pick(t, tsec, idx, np.nan_to_num(resid - med))


# ═══════════════ 主流程 ═══════════════

METHODS_SIMPLE = {
    "holzinger2012": lambda t, a, nid: detect_holzinger2012(t, a),
    "isolation_forest": lambda t, a, nid: detect_isolation_forest(t, a),
    "patchtst_proxy": lambda t, a, nid: detect_patchtst_proxy(t, a),
}


def main():
    quick = "--quick" in sys.argv
    events = load_events_ext2()
    sats = ALL_SATS23[:3] if quick else ALL_SATS23

    rows = []
    t0 = time.time()
    for nid, nm in sats:
        t, a = load_a(nid)
        if t is None or len(a) < 60 or nid not in events:
            print(f"  {nm:14s} 跳過（資料不足）", flush=True)
            continue
        print(f"[{nm}] 開始 ({time.time()-t0:.0f}s)…", flush=True)

        for mname, fn in METHODS_SIMPLE.items():
            try:
                dets = fn(t, a, nid)
                r = evaluate(nid, events, lambda t_, a_, d=dets: d)
                if r:
                    rows.append(dict(norad=nid, name=nm, method=mname, **{
                        k: v for k, v in r.items() if k != "norad"}))
                    print(f"    {mname:18s} F1={r['f1']:.3f} P={r['precision']:.2f} R={r['recall']:.2f}", flush=True)
            except Exception as exc:
                print(f"    {mname:18s} 失敗：{exc}", flush=True)

        try:
            dets, t_full = detect_sanjuan2017(nid)
            if t_full is not None:
                ev = events[nid]
                lo = max(t_full.min(), ev["ws"].min()); hi = min(t_full.max(), ev["we"].max())
                evw = ev[(ev["ws"] >= lo) & (ev["ws"] <= hi)].reset_index(drop=True)
                if len(evw):
                    dd = pd.to_datetime([d for d in dets if lo <= d <= hi])
                    tol = pd.Timedelta(days=float(TOL_D))
                    used = np.zeros(len(dd), bool); tp = 0
                    for _, e in evw.iterrows():
                        w0, w1 = e["ws"] - tol, e["we"] + tol
                        hit = [i for i, d in enumerate(dd) if w0 <= d <= w1 and not used[i]]
                        if hit: used[hit[0]] = True; tp += 1
                    fn_ = len(evw) - tp; fp = int((~used).sum())
                    prec = tp / (tp + fp) if tp + fp else 0.0
                    rec = tp / (tp + fn_) if tp + fn_ else 0.0
                    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
                    rows.append(dict(norad=nid, name=nm, method="sanjuan2017",
                                     n_ev=len(evw), n_det=len(dd), tp=tp, fp=fp, fn=fn_,
                                     precision=prec, recall=rec, f1=f1))
                    print(f"    {'sanjuan2017':18s} F1={f1:.3f} P={prec:.2f} R={rec:.2f}", flush=True)
        except Exception as exc:
            print(f"    sanjuan2017        失敗：{exc}", flush=True)

    df = pd.DataFrame(rows)
    out = Path("data/benchmark/lit_tier2_persat_20260913.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}（{len(df)} 列，耗時 {time.time()-t0:.0f}s）")
    if len(df):
        print(df.groupby("method")[["precision", "recall", "f1"]].mean())


if __name__ == "__main__":
    main()
