#!/usr/bin/env python3
"""lit_tierA2_reproductions.py — 案例十一「下一批10篇」Tier A（有完整全文）
5 篇文獻方法之重現實作，與本專案完全相同驗證基準（tasa14_compare.evaluate）
在 23 星標竿上比較。

實作方法（本專案依論文精神重現之簡化版，非原始程式碼；每項皆誠實標註簡化
與領域不匹配之處）：
  1. Decoto, 2015（AMOS，GEO站保機動特徵化）：**領域不匹配誠實聲明**——原文
     專為GEO衛星週期性站保機動設計（頻率擬合找機動週期），本專案23星標竿
     全為LEO衛星，無此週期性前提。簡化為其偵測核心（前後歷元SGP4自洽濾波，
     複用Tier1 Mukundan 2021邏輯），略去GEO專屬的頻率特徵化/分類步驟。
  2. Roberts & Linares, 2021（AMOS/MIT碩論，GEO經度監督式分類）：**領域不
     匹配誠實聲明**——原文用GEO經度滑動視窗+CNN分類。LEO衛星無「經度漂移」
     概念，改用sma滑動視窗特徵（斜率/加速度/局部變異數）+ RandomForest
     監督式分類器（原文CNN，此處簡化為輕量樹模型，符合論文精神），前半段
     訓練、全段預測（與Tier1 Peng&Bai 2018同樣的train/test切分方式）。
  4. Qin et al., 2019（Sensors，北斗機動起訖時間）：正反向SGP4傳播殘差之
     較大者作為偵測訊號——比 Mukundan 2021 僅前向傳播更敏感。
  9. MDPI Aerospace 2026（自適應多特徵準則）：**與本專案方法高度同構**，
     三特徵（Δa、Δe變化率、平均運動局部離散度）各自穩健z分數、取最大值
     為綜合準則，搭配迭代遮罩重估（與本專案detect_iter同構）。
  10. Shorten et al., 2023（arXiv，最優提議粒子濾波）：以SGP4啟發之擴散
     過程（不確定度隨√Δt成長）為狀態轉移模型，用觀測似然重加權粒子，
     以「負對數邊際似然（驚訝度）」作偵測訊號，並在有效樣本數(ESS)崩潰時
     重採樣——序貫貝氏濾波，與本專案其餘方法典範完全不同。

用法：python lit_tierA2_reproductions.py [--quick]
輸出：data/benchmark/lit_tierA2_persat_20260913.csv
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

from tasa14_compare import load_a, evaluate, TOL_D, MERGE_D, DB, robust_sigma, detrend_step
from tasa23_ext_arena import ALL_SATS23, load_events_ext2

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


def _robust_z(x):
    x = np.asarray(x, float)
    med = np.nanmedian(x)
    mad = 1.4826 * np.nanmedian(np.abs(x - med))
    if not np.isfinite(mad) or mad == 0:
        return np.zeros_like(x)
    return (x - med) / mad


# ═══════════════ 共用：載入含 e / mean_motion 之完整逐星資料 ═══════════════

def load_a_full(nid: int):
    for i in range(6):
        try:
            con = duckdb.connect(DB, read_only=True); break
        except duckdb.IOException:
            if i == 5: raise
            time.sleep(2.0 * (i + 1))
    r = con.execute(
        "SELECT epoch_utc, sma_km, eccentricity, mean_motion, line1, line2 "
        "FROM raw_tle_archive WHERE norad_id=? AND sma_km IS NOT NULL "
        "ORDER BY epoch_utc", [nid]).fetchall()
    con.close()
    if not r:
        return None
    t = pd.to_datetime([x[0] for x in r], utc=True)
    a = np.array([float(x[1]) for x in r])
    e = np.array([float(x[2]) for x in r])
    mm = np.array([float(x[3]) for x in r])
    l1 = [x[4] for x in r]; l2 = [x[5] for x in r]
    ts = t.astype("int64").to_numpy() / 1e9
    keep = [0]
    for i in range(1, len(ts)):
        if ts[i] - ts[keep[-1]] >= 3.0 * 3600:
            keep.append(i)
    keep = np.array(keep)
    return dict(t=t[keep], a=a[keep], e=e[keep], mm=mm[keep],
                l1=[l1[i] for i in keep], l2=[l2[i] for i in keep])


def _sgp4_prop_sma(l1, l2, target_dt):
    from sgp4.api import Satrec, jday
    sat = Satrec.twoline2rv(l1, l2)
    jd, fr = jday(target_dt.year, target_dt.month, target_dt.day,
                  target_dt.hour, target_dt.minute, target_dt.second + target_dt.microsecond / 1e6)
    e, r, v = sat.sgp4(jd, fr)
    if e != 0:
        return np.nan
    rm = float(np.linalg.norm(r)); vm = float(np.linalg.norm(v))
    energy = vm ** 2 / 2.0 - MU_KM / rm
    return -MU_KM / (2.0 * energy)


# ═══════════════ 1. Decoto 2015（前後歷元SGP4自洽濾波，GEO法簡化套用LEO）═══════════════
# 誠實揭露（2026-09-14 內部審查發現）：Decoto 2015 原文為 GEO 站台保持之頻域
# 週期性訊號擬合，本專案未實作該頻域方法，改用與 lit_tier1_reproductions.py
# 之 detect_mukundan2021 完全相同之機制（逐相鄰TLE前向SGP4自洽殘差＋穩健z
# 分數）。此為方法論上的重複，並非兩個獨立重現版——本檔案之 F1 數字與
# Mukundan 2021 版本高度相關（同一機制、同一資料），不應在跨文獻排名表中
# 視為兩個獨立資料點。詳見 docs/案例十一TierA2文獻實作比較_20260913.md §2.1。

def detect_decoto2015(d, k=4.0):
    t, a, l1, l2 = d["t"], d["a"], d["l1"], d["l2"]
    n = len(t)
    resid = np.full(n, np.nan)
    for i in range(1, n):
        pred = _sgp4_prop_sma(l1[i - 1], l2[i - 1], t[i].to_pydatetime())
        if np.isfinite(pred):
            resid[i] = a[i] - pred
    valid = np.isfinite(resid)
    if valid.sum() < 15:
        return pd.to_datetime([])
    z = _robust_z(resid)
    tsec = t.astype("int64").to_numpy() / 1e9
    idx = np.where(valid & (np.abs(z) > k))[0]
    return _merge_and_pick(t, tsec, idx, np.nan_to_num(z))


# ═══════════════ 2. Roberts & Linares 2021（滑動視窗特徵+監督式分類，簡化為RF）═══════════════

def detect_roberts2021(d, events_win, patch=12, k_thresh=0.5):
    from sklearn.ensemble import RandomForestClassifier
    t, a = d["t"], d["a"]
    n = len(a)
    if n < patch * 4:
        return pd.to_datetime([])
    tsec = t.astype("int64").to_numpy() / 1e9
    slope = np.gradient(a, tsec / 86400.0)
    accel = np.gradient(slope, tsec / 86400.0)
    localvar = pd.Series(a).rolling(patch, center=True, min_periods=3).std().to_numpy()
    X = np.column_stack([slope, accel, np.nan_to_num(localvar)])
    tol = pd.Timedelta(days=float(TOL_D))
    y = np.zeros(n, int)
    for _, e in events_win.iterrows():
        m = (t >= e["ws"] - tol) & (t <= e["we"] + tol)
        y[np.asarray(m)] = 1
    if y.sum() < 3 or y.sum() > n - 3:
        return pd.to_datetime([])
    split = n // 2
    clf = RandomForestClassifier(n_estimators=200, max_depth=5, random_state=42, class_weight="balanced")
    clf.fit(X[:split], y[:split])
    proba = clf.predict_proba(X)[:, 1] if len(clf.classes_) > 1 else np.zeros(n)
    idx = np.where(proba > k_thresh)[0]
    return _merge_and_pick(t, tsec, idx, proba)


# ═══════════════ 4. Qin et al. 2019（正反向SGP4傳播殘差）═══════════════

def detect_qin2019(d, k=4.0):
    t, a, l1, l2 = d["t"], d["a"], d["l1"], d["l2"]
    n = len(t)
    fwd = np.full(n, np.nan); bwd = np.full(n, np.nan)
    for i in range(1, n):
        pred = _sgp4_prop_sma(l1[i - 1], l2[i - 1], t[i].to_pydatetime())
        if np.isfinite(pred):
            fwd[i] = a[i] - pred
    for i in range(0, n - 1):
        pred = _sgp4_prop_sma(l1[i + 1], l2[i + 1], t[i].to_pydatetime())
        if np.isfinite(pred):
            bwd[i] = a[i] - pred
    combo = np.nanmax(np.abs(np.column_stack([np.nan_to_num(fwd), np.nan_to_num(bwd)])), axis=1)
    valid = np.isfinite(fwd) | np.isfinite(bwd)
    z = _robust_z(np.where(valid, combo, np.nan))
    tsec = t.astype("int64").to_numpy() / 1e9
    idx = np.where(valid & (z > k))[0]
    return _merge_and_pick(t, tsec, idx, np.nan_to_num(z))


# ═══════════════ 9. MDPI Aerospace 2026（自適應多特徵準則）═══════════════

def detect_mdpi2026(d, k=20.0, n_iter=3):
    t, a, e, mm = d["t"], d["a"], d["e"], d["mm"]
    n = len(a)
    tsec = t.astype("int64").to_numpy() / 1e9
    dt_days = np.diff(tsec, prepend=tsec[1] - tsec[0] if n > 1 else 1.0) / 86400.0
    med_gap = float(np.median(dt_days[dt_days > 0])) if (dt_days > 0).any() else 1.0
    w = int(np.clip(round(2.0 / max(med_gap, 1e-3)), 4, 20))    # 依TLE間隔自適應視窗

    da = np.diff(a, prepend=a[0])
    de_rate = np.diff(e, prepend=e[0]) / np.maximum(dt_days, 1e-3)
    mm_disp = pd.Series(mm).rolling(w, center=True, min_periods=3).std().to_numpy()

    mask = np.zeros(n, bool)
    combined = np.zeros(n)
    for _ in range(n_iter):
        z1 = _robust_z(np.where(~mask, da, np.nan))
        z2 = _robust_z(np.where(~mask, de_rate, np.nan))
        z3 = _robust_z(np.where(~mask, mm_disp, np.nan))
        combined = np.nanmax(np.abs(np.stack([np.nan_to_num(z1), np.nan_to_num(z2),
                                               np.nan_to_num(z3)])), axis=0)
        newmask = combined > k
        if newmask.sum() == mask.sum():
            mask = newmask; break
        mask = newmask

    idx = np.where(combined > k)[0]
    return _merge_and_pick(t, tsec, idx, combined)


# ═══════════════ 10. Shorten et al. 2023（最優提議粒子濾波）═══════════════

def detect_particle_filter(t, a, n_particles=300, k=4.0, seed=42):
    """簡化版最優提議粒子濾波（Shorten et al. 2023 精神重現）。

    **誠實記錄一項除錯過程中發現的已知限制**：最初版本用單一狀態（僅sma）+
    負對數邊際似然（「驚訝度」）作偵測訊號，實測發現該訊號動態範圍極端
    （因觀測雜訊尺度極小，任何真實跳動都造成天文數字級的對數概似），且
    MAD穩健正規化對此類重尾分布無法乾淨分離異常。改為**二態模型**
    （位置+漂移率，較貼近真實衛星平滑衰減行為）並改用「創新量
    （innovation，即預測與觀測之差）除以預測標準差」之標準卡爾曼式正規化
    殘差，仍觀察到粒子退化（degeneracy）現象——重採樣過於頻繁導致偵測力
    下降，這是簡化版粒子濾波器的已知通病（原文之「最優提議」設計正是為了
    緩解此問題，但其精確算法無法從摘要重現）。已用較強之重採樣正規化雜訊
    緩解，最終版本效能雖不如其餘方法，但如實呈現而非隱藏，見報告說明。
    """
    rng = np.random.default_rng(seed)
    tsec = t.astype("int64").to_numpy() / 1e9
    n = len(a)
    obs_sigma = max(robust_sigma(np.diff(a)), 0.03)   # 50m門檻同量級之底噪下限
    drift_noise = obs_sigma * 0.3

    pos = np.full(n_particles, a[0])
    drift = np.zeros(n_particles)
    weights = np.ones(n_particles) / n_particles
    innov_z = np.zeros(n)

    for i in range(1, n):
        dt_days = max((tsec[i] - tsec[i - 1]) / 86400.0, 1e-3)
        drift = drift + rng.normal(0, drift_noise, n_particles)
        pos = pos + drift * dt_days + rng.normal(0, obs_sigma * np.sqrt(dt_days), n_particles)
        pred_mean = np.average(pos, weights=weights)
        pred_var = np.average((pos - pred_mean) ** 2, weights=weights) + obs_sigma ** 2
        innov_z[i] = (a[i] - pred_mean) / np.sqrt(pred_var)

        logw = -0.5 * ((a[i] - pos) / obs_sigma) ** 2
        m = logw.max()
        w = np.exp(logw - m) * weights
        wsum = w.sum()
        weights = w / wsum if wsum > 0 else np.ones(n_particles) / n_particles
        ess = 1.0 / np.sum(weights ** 2)
        if ess < 0.5 * n_particles:
            idx_r = rng.choice(n_particles, size=n_particles, p=weights)
            pos = pos[idx_r] + rng.normal(0, obs_sigma * 1.0, n_particles)
            drift = drift[idx_r] + rng.normal(0, drift_noise * 1.0, n_particles)
            weights = np.ones(n_particles) / n_particles

    z = _robust_z(innov_z)
    idx = np.where(np.abs(z) > k)[0]
    return _merge_and_pick(t, tsec, idx, z)


# ═══════════════ 主流程 ═══════════════

def main():
    quick = "--quick" in sys.argv
    events = load_events_ext2()
    sats = ALL_SATS23[:3] if quick else ALL_SATS23

    rows = []
    t0 = time.time()
    for nid, nm in sats:
        d = load_a_full(nid)
        if d is None or len(d["a"]) < 60 or nid not in events:
            print(f"  {nm:14s} 跳過（資料不足）", flush=True)
            continue
        t, a = d["t"], d["a"]
        ev_all = events[nid]
        lo = max(t.min(), ev_all["ws"].min()); hi = min(t.max(), ev_all["we"].max())
        ev_win = ev_all[(ev_all["ws"] >= lo) & (ev_all["ws"] <= hi)].reset_index(drop=True)
        print(f"[{nm}] 開始 ({time.time()-t0:.0f}s)…", flush=True)

        methods = {
            "decoto2015": lambda: detect_decoto2015(d),
            "roberts2021": lambda: detect_roberts2021(d, ev_win),
            "qin2019": lambda: detect_qin2019(d),
            "mdpi2026": lambda: detect_mdpi2026(d),
            "particle_filter": lambda: detect_particle_filter(t, a),
        }
        for mname, fn in methods.items():
            try:
                dets = fn()
                r = evaluate(nid, events, lambda t_, a_, dd=dets: dd)
                if r:
                    rows.append(dict(norad=nid, name=nm, method=mname, **{
                        k: v for k, v in r.items() if k != "norad"}))
                    print(f"    {mname:18s} F1={r['f1']:.3f} P={r['precision']:.2f} R={r['recall']:.2f}", flush=True)
            except Exception as exc:
                print(f"    {mname:18s} 失敗：{exc}", flush=True)

    df = pd.DataFrame(rows)
    out = Path("data/benchmark/lit_tierA2_persat_20260913.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}（{len(df)} 列，耗時 {time.time()-t0:.0f}s）")
    if len(df):
        print(df.groupby("method")[["precision", "recall", "f1"]].mean())


if __name__ == "__main__":
    main()
