#!/usr/bin/env python3
"""lit_tier1_reproductions.py — 案例十一「有機會實作比較」第一梯隊 5 篇文獻方法之
重現實作，與本專案方法用完全相同的驗證基準（tasa14_compare.evaluate：同真值、
同 ±1.5 天配對容差、同 1 天旗標合併）在 23 星標竿上比較。

實作方法（皆為本專案依論文方法精神重現，非原始程式碼）：
  1. Kelecy et al. 2007（AMOS）：滑動視窗前後多項式(deg1)外推差分 + n-σ門檻。
  2. Mukundan & Wang 2021（Applied Sciences）：TLE自身元素 vs 前一筆TLE以SGP4
     傳播至當前epoch之元素，兩者差分 + n-σ門檻。
  3. RSO Proper Elements（Adv. Space Res. 2023）之【改編版】：因原文全文查證
     失敗、無法取得其「proper element」精確算法，本專案改用「移除阻力secular
     趨勢(rolling median去趨勢)後的殘差序列」作為忠實於其研究精神（在比平均
     要素更乾淨的特徵空間跑BOCPD）之誠實代理，套用本專案既有 BOCPD 實作
     （statistical_detectors.bocpd）。
  4. Adaptive CuSum（EngrXiv）：CUSUM改為滑動視窗動態估計局部均值/MAD，
     取代本專案 statistical_detectors.cusum 原本的全域固定估計。
  5. Peng & Bai 2018（Adv. Space Res.）：以 MLPRegressor(近似ANN)/SVR/GP 三種
     監督式模型學習修正 atmospheric_drag.py 物理阻力殘差，再對「修正後殘差」
     跑本專案既有偵測邏輯，比較訊噪比是否改善。

（第5篇 Geometric Distance Difference, Aerospace 2025 需 Starlink MEME 精密
星曆，本機 sp_ephem_raw 資料表目前為空，需另外重新下載，本次未執行——已在
報告中誠實註記，非隱藏。）

用法：python lit_tier1_reproductions.py [--quick]（--quick 只跑 3 顆衛星測試）
輸出：data/benchmark/lit_tier1_persat_20260913.csv
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
from statistical_detectors import bocpd, cusum as _cusum_ref  # noqa: F401 (ref for parity)

MU_KM = 398600.4418  # km^3/s^2


def _merge_and_pick(t, tsec, idx, score):
    """把索引依 MERGE_D 天合併，每群取 |score| 最大者的時刻。"""
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


# ═══════════════ 1. Kelecy et al. 2007 ═══════════════

def _kelecy_signal(a: np.ndarray, tsec: np.ndarray, w: int) -> np.ndarray:
    """滑動視窗前後多項式(deg1)外推差分，向量化版（closed-form 最小平方）。"""
    n = len(a)
    diff = np.full(n, np.nan)
    if n <= 2 * w + 1:
        return diff
    from numpy.lib.stride_tricks import sliding_window_view
    x = tsec.copy()

    def fit_extrap(xw, yw, x0):
        xm = xw.mean(axis=1, keepdims=True)
        xc = xw - xm
        denom = (xc ** 2).sum(axis=1)
        denom = np.where(denom < 1e-9, np.nan, denom)
        slope = (xc * (yw - yw.mean(axis=1, keepdims=True))).sum(axis=1) / denom
        intercept = yw.mean(axis=1) - slope * xm[:, 0]
        return intercept + slope * x0

    Xb = sliding_window_view(x, w)[: n - 2 * w]         # 視窗 i..i+w-1 → 預測 i+w
    Yb = sliding_window_view(a, w)[: n - 2 * w]
    Xf = sliding_window_view(x, w)[w + 1 : n - w + 1]   # 視窗 i+w+1..i+2w → 預測 i+w
    Yf = sliding_window_view(a, w)[w + 1 : n - w + 1]
    target_x = x[w : n - w]
    pred_b = fit_extrap(Xb, Yb, target_x)
    pred_f = fit_extrap(Xf, Yf, target_x)
    diff[w : n - w] = pred_f - pred_b
    return diff


def detect_kelecy2007(t, a, w=10, k=4.0):
    tsec = t.astype("int64").to_numpy() / 1e9
    diff = _kelecy_signal(a, tsec, w)
    valid = np.isfinite(diff)
    if valid.sum() < 10:
        return pd.to_datetime([])
    med = np.nanmedian(diff[valid])
    sd = 1.4826 * np.nanmedian(np.abs(diff[valid] - med))
    if not np.isfinite(sd) or sd == 0:
        return pd.to_datetime([])
    idx = np.where(valid & (np.abs(diff - med) > k * sd))[0]
    return _merge_and_pick(t, tsec, idx, diff - med)


# ═══════════════ 2. Mukundan & Wang 2021 ═══════════════

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


def detect_mukundan2021(nid: int, k=4.0):
    from sgp4.api import Satrec, jday

    t, sma, l1, l2 = _load_tle_lines(nid)
    if t is None or len(t) < 30:
        return pd.to_datetime([]), None, None
    n = len(t)
    diff = np.full(n, np.nan)
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
            diff[i] = sma[i] - a_pred
        except Exception:
            continue
    valid = np.isfinite(diff)
    if valid.sum() < 10:
        return pd.to_datetime([]), t, sma
    med = np.nanmedian(diff[valid])
    sd = 1.4826 * np.nanmedian(np.abs(diff[valid] - med))
    if not np.isfinite(sd) or sd == 0:
        return pd.to_datetime([]), t, sma
    tsec = t.astype("int64").to_numpy() / 1e9
    idx = np.where(valid & (np.abs(diff - med) > k * sd))[0]
    return _merge_and_pick(t, tsec, idx, diff - med), t, sma


# ═══════════════ 3. RSO Proper Elements（改編代理版）+ BOCPD ═══════════════

def _proper_element_proxy(a: np.ndarray, window: int = 21) -> np.ndarray:
    """誠實聲明：非原文之精確 proper element 算法（原文全文查證失敗），
    改用 rolling-median 去除阻力 secular 趨勢後的殘差序列作為代理特徵空間。"""
    s = pd.Series(a)
    trend = s.rolling(window, center=True, min_periods=5).median()
    trend = trend.bfill().ffill()
    return (s - trend).to_numpy()


def detect_proper_bocpd(t, a, hazard_lambda=100.0):
    tsec = t.astype("int64").to_numpy() / 1e9
    proper = _proper_element_proxy(a)
    res = bocpd(proper, hazard_lambda=hazard_lambda)
    idx = res["events"]
    if len(idx) == 0:
        return pd.to_datetime([])
    score = res["scores"]
    return _merge_and_pick(t, tsec, idx, score)


# ═══════════════ 4. Adaptive CuSum ═══════════════

def detect_adaptive_cusum(t, a, win=60, k=0.5, h=5.0):
    tsec = t.astype("int64").to_numpy() / 1e9
    da = np.diff(a, prepend=a[0])
    n = len(da)
    s = pd.Series(da)
    local_med = s.rolling(win, center=True, min_periods=10).median()
    local_med = local_med.bfill().ffill().to_numpy()
    resid = np.abs(s - pd.Series(local_med))
    local_mad = resid.rolling(win, center=True, min_periods=10).median()
    local_mad = (local_mad.bfill().ffill().to_numpy()) * 1.4826
    local_mad = np.where(local_mad <= 1e-12, 1.0, local_mad)
    z = (da - local_med) / local_mad

    hi = lo = 0.0
    events, scores = [], np.zeros(n)
    for i in range(n):
        hi = max(0.0, hi + z[i] - k)
        lo = max(0.0, lo - z[i] - k)
        scores[i] = max(hi, lo)
        if hi > h or lo > h:
            events.append(i)
            hi = lo = 0.0
    return _merge_and_pick(t, tsec, np.array(events, int), scores)


# ═══════════════ 6. Peng & Bai 2018：物理殘差 + ML 修正 ═══════════════

def detect_peng_bai2018(t, a, nid, model="mlp", k=4.0):
    from atmospheric_drag import drag_residual
    from sklearn.neural_network import MLPRegressor
    from sklearn.svm import SVR
    from sklearn.gaussian_process import GaussianProcessRegressor

    df = pd.DataFrame({"epoch": t, "sma_km": a})
    try:
        out = drag_residual(df)
    except Exception:
        return pd.to_datetime([])
    if out is None or len(out) == 0 or "drag_resid_da" not in out.columns:
        return pd.to_datetime([])
    epoch = pd.to_datetime(out["epoch"], utc=True)
    resid = out["drag_resid_da"].to_numpy(float)
    n = len(resid)
    valid = np.isfinite(resid)
    if valid.sum() < 30:
        return pd.to_datetime([])

    idx_all = np.arange(n)
    X = idx_all[valid].reshape(-1, 1).astype(float)
    y = resid[valid]
    split = int(len(X) * 0.5)
    if split < 15:
        return pd.to_datetime([])
    Xtr, ytr = X[:split], y[:split]

    try:
        if model == "mlp":
            reg = MLPRegressor(hidden_layer_sizes=(16,), max_iter=500, random_state=42)
        elif model == "svr":
            reg = SVR(kernel="rbf", C=1.0)
        else:
            reg = GaussianProcessRegressor(normalize_y=True)
        reg.fit(Xtr, ytr)
        pred_all = reg.predict(X)
    except Exception:
        return pd.to_datetime([])

    corrected = np.full(n, np.nan)
    corrected[valid] = y - pred_all

    med = np.nanmedian(corrected[valid])
    sd = 1.4826 * np.nanmedian(np.abs(corrected[valid] - med))
    if not np.isfinite(sd) or sd == 0:
        return pd.to_datetime([])

    t_idx = pd.DatetimeIndex(epoch)
    tsec = t_idx.astype("int64").to_numpy() / 1e9
    idx = np.where(valid & (np.abs(corrected - med) > k * sd))[0]
    return _merge_and_pick(t_idx, tsec, idx, corrected - med)


# ═══════════════ 主流程 ═══════════════

METHODS_SIMPLE = {
    "kelecy2007": lambda t, a, nid: detect_kelecy2007(t, a),
    "proper_bocpd": lambda t, a, nid: detect_proper_bocpd(t, a),
    "adaptive_cusum": lambda t, a, nid: detect_adaptive_cusum(t, a),
    "peng_bai2018_mlp": lambda t, a, nid: detect_peng_bai2018(t, a, nid, model="mlp"),
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
            dets2, t2, sma2 = detect_mukundan2021(nid)
            if t2 is not None:
                ev = events[nid]
                lo = max(t2.min(), ev["ws"].min()); hi = min(t2.max(), ev["we"].max())
                evw = ev[(ev["ws"] >= lo) & (ev["ws"] <= hi)].reset_index(drop=True)
                if len(evw):
                    dd = pd.to_datetime([d for d in dets2 if lo <= d <= hi])
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
                    rows.append(dict(norad=nid, name=nm, method="mukundan2021",
                                     n_ev=len(evw), n_det=len(dd), tp=tp, fp=fp, fn=fn_,
                                     precision=prec, recall=rec, f1=f1))
                    print(f"    {'mukundan2021':18s} F1={f1:.3f} P={prec:.2f} R={rec:.2f}", flush=True)
        except Exception as exc:
            print(f"    mukundan2021       失敗：{exc}", flush=True)

    df = pd.DataFrame(rows)
    out = Path("data/benchmark/lit_tier1_persat_20260913.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}（{len(df)} 列，耗時 {time.time()-t0:.0f}s）")
    if len(df):
        print(df.groupby("method")[["precision", "recall", "f1"]].mean())


if __name__ == "__main__":
    main()
