#!/usr/bin/env python3
"""
l3_candidate.py
===============
「候選確認式」L3：對一顆衛星的 (t, a) 序列，先由 L1/L2 類偵測器產生機動候選，
再對每個候選算 σ 正規化特徵，交給訓練好的分類器「確認或否決」。

本模組是 tasa14_l3_fusion.py（NASA/ILRS 23 星 LOSO 融合）中「單星特徵計算」段的自足版本，
供線上推論與訓練腳本共用；特徵定義、候選聯集與合併規則與原腳本逐項一致
（tests/test_l3_candidate.py 以 23 星快取特徵驗證重現性）。

候選 = detect_iter2(k=3) ∪ detect_pred(k=6, deg1) ∪ L2 四通道（CUSUM/BOCPD/SSA/MAD3σ）事件，
1 天內合併。特徵（皆 σ 正規化或域不變）：
  z_ls   位準位移 SNR       z_pe  前向預測誤差 SNR     z_step 單步 |Δa| SNR
  s_*    L2 四通道逐點分數（±1 天內最大）
  cadence_d  該星 TLE 中位更新間隔（天）
  det_it2 / det_pr  強偵測器（iter2 k=8／pred k=12）是否同意
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import statistical_detectors as sd
import tasa14_l2_compare as l2
from tasa14_compare import (MIN_GAP_HR, _shift_signal_w, adaptive_lw, detect_iter2,
                            detrend_step, robust_sigma)
from tasa14_pdf_baseline import _adaptive_w, _pred_error, detect_pred

CAND_MERGE_D = 1.0
CADENCE_SPLIT_D = 0.45                    # dense / sparse 類別界線（事前定義，同原腳本）
FEATS = ["z_ls", "z_pe", "z_step", "s_cusum", "s_bocpd", "s_ssa", "s_mad", "cadence_d",
         "det_it2", "det_pr"]
FEAT_LABELS = {
    "z_ls": ("位準位移 SNR", "レベルシフトSNR", "Level-shift SNR"),
    "z_pe": ("預測誤差 SNR", "予測誤差SNR", "Prediction-error SNR"),
    "z_step": ("單步 |Δa| SNR", "1ステップ|Δa| SNR", "Single-step |Δa| SNR"),
    "s_cusum": ("CUSUM 分數", "CUSUMスコア", "CUSUM score"),
    "s_bocpd": ("BOCPD 分數", "BOCPDスコア", "BOCPD score"),
    "s_ssa": ("SSA 分數", "SSAスコア", "SSA score"),
    "s_mad": ("MAD 3σ 分數", "MAD 3σスコア", "MAD 3σ score"),
    "cadence_d": ("更新間隔（天）", "更新間隔（日）", "Update interval (d)"),
    "det_it2": ("強偵測器 iter2 同意", "強検出器iter2一致", "Strong detector iter2 agrees"),
    "det_pr": ("強偵測器 pred 同意", "強検出器pred一致", "Strong detector pred agrees"),
}


def to_series(df: pd.DataFrame, min_gap_hr: float = MIN_GAP_HR):
    """DataFrame(epoch, sma_km) → 稀釋（≥3 h）後的 (t, a)，與 tasa14_compare.load_a 同規則。"""
    d = df.sort_values("epoch")
    d = d[d["sma_km"].notna()]
    # duckdb/pandas 2 可能回傳 datetime64[us]；後續一律以 astype("int64")/1e9 當秒數，必須先轉成 ns
    t = pd.DatetimeIndex(pd.to_datetime(d["epoch"], utc=True)).as_unit("ns")
    a = d["sma_km"].to_numpy(float)
    ts = t.astype("int64").to_numpy() / 1e9
    keep = [0]
    for i in range(1, len(ts)):
        if ts[i] - ts[keep[-1]] >= min_gap_hr * 3600:
            keep.append(i)
    keep = np.array(keep)
    return t[keep], a[keep]


# ── 逐點訊號（與 tasa14_l3_fusion 一致）──────────────────────────────────────
def signal_ls(t, a):
    n = len(a)
    tsec = t.astype("int64").to_numpy() / 1e9
    w = adaptive_lw(tsec)
    mask = np.zeros(n, bool)
    sig = _shift_signal_w(a, tsec, mask, w)
    for _ in range(2):
        s = sig[np.isfinite(sig) & ~mask]
        sdv = 1.4826 * np.median(np.abs(s - np.median(s))) if len(s) else np.nan
        if not np.isfinite(sdv) or sdv == 0:
            break
        newmask = np.zeros(n, bool)
        for j in np.where(np.abs(sig) > 8 * sdv)[0]:
            newmask[max(0, j - w):min(n, j + w)] = True
        if newmask.sum() == mask.sum():
            break
        mask = newmask
        sig = _shift_signal_w(a, tsec, mask, w)
    s = sig[np.isfinite(sig) & ~mask]
    sdv = 1.4826 * np.median(np.abs(s - np.median(s))) if len(s) else 1e-9
    return np.abs(sig) / max(sdv, 1e-9)


def signal_pe(t, a):
    tsec = t.astype("int64").to_numpy() / 1e9
    w = _adaptive_w(tsec)
    bad = np.zeros(len(a), bool)
    e = _pred_error(tsec, a, w, 1, bad)
    s = e[np.isfinite(e)]
    sdv = 1.4826 * np.median(np.abs(s - np.median(s))) if len(s) else np.nan
    if np.isfinite(sdv) and sdv > 0:
        bad = np.isfinite(e) & (np.abs(e) > 8 * sdv)
        e = _pred_error(tsec, a, w, 1, bad)
        s = e[np.isfinite(e) & ~bad]
        sdv = 1.4826 * np.median(np.abs(s - np.median(s))) if len(s) else sdv
    return np.abs(e) / max(sdv, 1e-9)


def signal_step(t, a):
    s = detrend_step(a)
    sdv = robust_sigma(s)
    z = np.full(len(a), np.nan)
    z[1:] = np.abs(s) / max(sdv, 1e-9)
    return z


def l2_scores(t, a):
    """滑動窗跑 L2，收逐點分數（重疊窗取最大）與各通道事件 epoch。"""
    n = len(a)
    sc = {c: np.full(n, np.nan) for c in l2.CHANS}
    evs = {c: [] for c in l2.CHANS}
    start = 0
    while start < n:
        seg = slice(start, min(n, start + l2.WIN))
        aw, tw = a[seg], t[seg]
        if len(aw) >= 24:
            res = sd.run_all(aw)
            for c in l2.CHANS:
                s = np.asarray(res[c]["scores"], float)
                if len(s) == len(aw):
                    idx = np.arange(seg.start, seg.start + len(aw))
                    cur = sc[c][idx]
                    sc[c][idx] = np.where(np.isnan(cur), s, np.maximum(cur, s))
                for k in res[c]["events"]:
                    if l2.EDGE <= k < len(aw) - l2.EDGE:
                        evs[c].append(tw[k])
        if start + l2.WIN >= n:
            break
        start += l2.STEP
    return sc, evs


def build_candidates(t, a, lo=None, hi=None) -> pd.DataFrame:
    """對 (t, a) 產生候選與特徵。lo/hi 限制候選時間範圍（訓練時取真值涵蓋範圍；推論時不限）。

    回傳欄位：epoch + FEATS；另附各通道是否有事件的旗標 ev_iter2/ev_pred/ev_cusum/...（動畫說明用）。
    """
    if len(a) < 60:
        return pd.DataFrame(columns=["epoch"] + FEATS)
    t = pd.DatetimeIndex(t).as_unit("ns")
    lo = t.min() if lo is None else lo
    hi = t.max() if hi is None else hi
    tsec = t.astype("int64").to_numpy() / 1e9
    gaps = np.diff(tsec) / 86400.0
    cad = float(np.median(gaps[gaps > 0]))
    z_ls, z_pe, z_st = signal_ls(t, a), signal_pe(t, a), signal_step(t, a)
    sc, evs = l2_scores(t, a)
    it2_c = list(detect_iter2(t, a, 3))
    prd_c = list(detect_pred(t, a, 6, 1, 1))
    l2_ev = {c: l2.merge_epochs(evs[c]) for c in l2.CHANS}
    cands = it2_c + prd_c
    for c in l2.CHANS:
        cands += list(l2_ev[c])
    cands = l2.merge_epochs(cands, CAND_MERGE_D)
    cands = pd.to_datetime([c for c in cands if lo <= c <= hi])
    csec = cands.astype("int64").to_numpy() / 1e9
    it2 = pd.to_datetime(detect_iter2(t, a, 8)).astype("int64").to_numpy() / 1e9
    prd = pd.to_datetime(detect_pred(t, a, 12, 1, 1)).astype("int64").to_numpy() / 1e9
    near = lambda arr, cs, d=0.75: bool(len(arr)) and bool(np.min(np.abs(arr - cs)) <= d * 86400)
    src_it2 = pd.to_datetime(it2_c).astype("int64").to_numpy() / 1e9 if len(it2_c) else np.array([])
    src_prd = pd.to_datetime(prd_c).astype("int64").to_numpy() / 1e9 if len(prd_c) else np.array([])
    src_l2 = {c: (l2_ev[c].astype("int64").to_numpy() / 1e9 if len(l2_ev[c]) else np.array([])) for c in l2.CHANS}
    rows = []
    for ce, cs in zip(cands, csec):
        m = np.abs(tsec - cs) <= 1.0 * 86400
        if not m.any():
            continue

        def mx(arr):
            v = arr[m]
            v = v[np.isfinite(v)]
            return float(v.max()) if len(v) else 0.0

        r = dict(epoch=ce, z_ls=mx(z_ls), z_pe=mx(z_pe), z_step=mx(z_st),
                 s_cusum=mx(sc["cusum"]), s_bocpd=mx(sc["bocpd"]), s_ssa=mx(sc["ssa"]),
                 s_mad=mx(sc["mad3sig"]), cadence_d=cad,
                 det_it2=int(near(it2, cs)), det_pr=int(near(prd, cs)))
        # 候選來源（哪些偵測器貢獻了這個候選；±1 天內）
        r["src_iter2"] = int(near(src_it2, cs, 1.0))
        r["src_pred"] = int(near(src_prd, cs, 1.0))
        for c in l2.CHANS:
            r["src_" + c] = int(near(src_l2[c], cs, 1.0))
        rows.append(r)
    return pd.DataFrame(rows)


def cadence_class(cadence_d: float) -> str:
    return "dense" if cadence_d < CADENCE_SPLIT_D else "sparse"
