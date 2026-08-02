#!/usr/bin/env python3
"""
statistical_detectors.py
========================
契約指定之三種具名統計變點偵測方法，作用於單顆衛星的軌道半長軸（sma/da）時間序列：

  CUSUM  — 累積和管制圖（Page 1954）：偵測序列均值的階躍變化。
  BOCPD  — 貝氏線上變點偵測（Adams & MacKay 2007）：每時刻給「變點機率」。
  SSA    — 奇異譜分析：滯後嵌入 + SVD 分離 趨勢(阻力)＋振盪(J2)＋殘差，殘差尖峰＝機動。

全部以 numpy/scipy 實作，無外部相依。每個偵測器回傳：
  scores  — 逐時刻分數（供 Layer 3 ML 當特徵）
  events  — 判定為變點/機動的索引（供 Layer 2 事件輸出）

設計依據：docs/MEME_truth_ML_tuning_design.md、期中報告 Layer 2 契約具名方法。
"""
from __future__ import annotations

import numpy as np


# ── 共用：穩健標準化 ─────────────────────────────────────────────────────────

def _robust_center_scale(y: np.ndarray) -> tuple[float, float]:
    """回傳 (中位數, 1.4826*MAD)；MAD=0 時退回標準差，仍為 0 時回 1。"""
    med = float(np.median(y))
    mad = float(np.median(np.abs(y - med))) * 1.4826
    if mad <= 1e-12:
        mad = float(np.std(y))
    return med, (mad if mad > 1e-12 else 1.0)


def _drag_detrend(y: np.ndarray) -> np.ndarray:
    """移除線性（阻力）趨勢，回傳殘差；序列 < 3 點時原樣回傳。"""
    n = len(y)
    if n < 3:
        return y - np.mean(y) if n else y
    x = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    return y - (slope * x + intercept)


# ── CUSUM ────────────────────────────────────────────────────────────────────

def cusum(y: np.ndarray, k: float = 0.5, h: float = 5.0) -> dict:
    """雙側表格式 CUSUM，作用於「增量序列」da（sma 一階差分）。

    以穩健標準化後的 z 累積，偵測均值階躍（一次性推力 → da 尖峰 → S 超過門檻）。

    Parameters
    ----------
    y : 監測序列（建議傳 da = diff(sma)）
    k : 容差（slack，標準差為單位），典型 0.5
    h : 決策門檻（標準差為單位），典型 4–6

    Returns
    -------
    dict(scores, events, s_hi, s_lo)
      scores : max(S_hi, S_lo) 逐點，越大越可能是變點
      events : 觸發警報（且重置）的索引陣列
    """
    y = np.asarray(y, float)
    n = len(y)
    if n == 0:
        return {"scores": np.array([]), "events": np.array([], int),
                "s_hi": np.array([]), "s_lo": np.array([])}

    med, scale = _robust_center_scale(y)
    z = (y - med) / scale

    s_hi = np.zeros(n)
    s_lo = np.zeros(n)
    events: list[int] = []
    hi = lo = 0.0
    for i in range(n):
        hi = max(0.0, hi + z[i] - k)
        lo = max(0.0, lo - z[i] - k)
        if hi > h or lo > h:
            events.append(i)
            hi = lo = 0.0            # 警報後重置
        s_hi[i] = hi
        s_lo[i] = lo
    scores = np.maximum(s_hi, s_lo)
    return {"scores": scores, "events": np.array(events, int),
            "s_hi": s_hi, "s_lo": s_lo}


# ── BOCPD（Adams & MacKay 2007，Gaussian UPM）─────────────────────────────────

def bocpd(y: np.ndarray, hazard_lambda: float = 100.0,
          mu0: float | None = None, kappa0: float = 1.0,
          alpha0: float = 1.0, beta0: float | None = None) -> dict:
    """貝氏線上變點偵測，Normal-Gamma 共軛（未知均值/變異）觀測模型。

    回傳每時刻「變點機率」P(run_length=0)，作為機率式機動旗標。

    Parameters
    ----------
    y             : 監測序列（建議傳 drag-detrended sma 或 da）
    hazard_lambda : 常數風險率 H = 1/λ；λ 越大越保守（預期段落越長）
    mu0,kappa0,alpha0,beta0 : Normal-Gamma 先驗超參數（beta0 預設由資料變異估）

    Returns
    -------
    dict(scores, events, cp_prob)
      scores  = cp_prob = P(r_t=0)
      events  = cp_prob 局部極大且 > 0.5 的索引
    """
    y = np.asarray(y, float)
    n = len(y)
    if n == 0:
        return {"scores": np.array([]), "events": np.array([], int),
                "cp_prob": np.array([])}

    med, scale = _robust_center_scale(y)
    if mu0 is None:
        mu0 = med
    if beta0 is None:
        beta0 = max(scale ** 2, 1e-6)

    H = 1.0 / hazard_lambda
    # 每個 run-length 的後驗超參數（隨時間成長）
    mu = np.array([mu0])
    kappa = np.array([kappa0])
    alpha = np.array([alpha0])
    beta = np.array([beta0])

    from scipy.special import gammaln

    R = np.array([1.0])              # P(r_0 = 0) = 1
    cp_prob = np.zeros(n)            # P(r_t = 0)（標準指標，可能在劇烈階躍退化為 H）
    short_prob = np.zeros(n)         # P(r_t < 3)（穩健指標：變點後 run-length 必短）
    rl_map = np.zeros(n, int)        # MAP run-length（重置 → 變點）
    _SHORT = 3

    for t in range(n):
        x = y[t]
        # Student-t 預測機率（Normal-Gamma 邊際）
        df = 2.0 * alpha
        scale_t = np.sqrt(beta * (kappa + 1.0) / (alpha * kappa))
        z = (x - mu) / scale_t
        log_pred = (gammaln((df + 1.0) / 2.0) - gammaln(df / 2.0)
                    - 0.5 * np.log(df * np.pi) - np.log(scale_t)
                    - (df + 1.0) / 2.0 * np.log1p(z * z / df))
        pred = np.exp(log_pred)

        growth = R * pred * (1.0 - H)     # run-length 成長
        cp = np.sum(R * pred * H)          # 發生變點（r→0）
        new_R = np.concatenate([[cp], growth])
        new_R /= new_R.sum() + 1e-300
        R = new_R
        cp_prob[t] = R[0]
        short_prob[t] = R[:min(_SHORT, len(R))].sum()
        rl_map[t] = int(np.argmax(R))

        # 更新後驗（先把 r=0 的先驗接在前面）
        mu_new = np.concatenate([[mu0], (kappa * mu + x) / (kappa + 1.0)])
        kappa_new = np.concatenate([[kappa0], kappa + 1.0])
        alpha_new = np.concatenate([[alpha0], alpha + 0.5])
        beta_new = np.concatenate([[beta0],
                                   beta + (kappa * (x - mu) ** 2) / (2.0 * (kappa + 1.0))])
        mu, kappa, alpha, beta = mu_new, kappa_new, alpha_new, beta_new

    # 事件：MAP run-length 重置（穩定段落被打斷）或 short_prob 局部尖峰
    # （後者對「近連續機動」的忙碌序列較敏感，不需先有長穩定段）。
    events: list[int] = []
    for i in range(1, n):
        reset = rl_map[i - 1] > 3 and rl_map[i] <= 1
        lo = short_prob[i - 1]
        hi = short_prob[i + 1] if i < n - 1 else 0.0
        peak = short_prob[i] > 0.4 and short_prob[i] >= lo and short_prob[i] >= hi
        if reset or peak:
            events.append(i)
    return {"scores": short_prob, "events": np.array(events, int),
            "cp_prob": cp_prob, "short_prob": short_prob, "rl_map": rl_map}


# ── SSA（Singular Spectrum Analysis）─────────────────────────────────────────

def ssa(y: np.ndarray, window: int | None = None, n_components: int = 3,
        z_thresh: float = 3.0) -> dict:
    """奇異譜分析重構殘差偵測。

    對 sma 序列做滯後嵌入 → SVD → 取前 n_components 重構「平滑正常成分」
    （趨勢/阻力 + J2 振盪），殘差 = 原序列 − 重構；機動造成的階躍落入殘差尖峰。

    Parameters
    ----------
    y            : 監測序列（建議傳 sma 本身）
    window       : 嵌入視窗 L（預設 min(24, n//3)）
    n_components : 重構所用主成分數（趨勢+振盪，典型 2–5）
    z_thresh     : 殘差穩健 z 分數門檻，超過即標為機動

    Returns
    -------
    dict(scores, events, residual, recon)
      scores   = |殘差| 的穩健 z 分數
      events   = z > z_thresh 的索引
    """
    y = np.asarray(y, float)
    n = len(y)
    if n < 6:
        return {"scores": np.zeros(n), "events": np.array([], int),
                "residual": np.zeros(n), "recon": y.copy()}

    L = window or min(24, max(2, n // 3))
    L = min(L, n - 1)
    K = n - L + 1

    # 軌跡矩陣（Hankel）
    X = np.column_stack([y[i:i + L] for i in range(K)])   # L × K
    U, S, Vt = np.linalg.svd(X, full_matrices=False)
    r = min(n_components, len(S))
    X_recon = (U[:, :r] * S[:r]) @ Vt[:r, :]

    # 對角平均（Hankelization）還原 1D
    recon = np.zeros(n)
    counts = np.zeros(n)
    for i in range(L):
        for j in range(K):
            recon[i + j] += X_recon[i, j]
            counts[i + j] += 1.0
    recon /= np.maximum(counts, 1.0)

    residual = y - recon
    med, scale = _robust_center_scale(residual)
    scores = np.abs(residual - med) / scale
    events = np.where(scores > z_thresh)[0]
    return {"scores": scores, "events": events, "residual": residual, "recon": recon}


# ── 基準：3σ MAD（現行統計層替代方案）────────────────────────────────────────

def mad3sigma(y: np.ndarray, z_thresh: float = 3.0) -> dict:
    """3σ MAD 尖峰偵測（對 da 增量序列）——作為現行統計層替代方案之對照基準。

    穩健 z = |da − median| / (1.4826·MAD)；z > 門檻即標為異常。
    """
    y = np.asarray(y, float)
    n = len(y)
    if n == 0:
        return {"scores": np.array([]), "events": np.array([], int)}
    med, scale = _robust_center_scale(y)
    scores = np.abs(y - med) / scale
    events = np.where(scores > z_thresh)[0]
    return {"scores": scores, "events": events}


# ── 便利：對 sma 序列一次跑三法 ───────────────────────────────────────────────

def run_all(sma: np.ndarray) -> dict:
    """對 sma 序列跑三法，回傳統一結構。

    CUSUM/BOCPD 作用於 drag-detrended 殘差的增量/殘差；SSA 作用於原 sma。
    回傳每法的 scores（逐點）與 events（索引）。長度與輸入 sma 對齊
    （CUSUM 的 da 少一點，已於此補齊為與 sma 同長）。
    """
    sma = np.asarray(sma, float)
    n = len(sma)
    detr = _drag_detrend(sma)
    da = np.diff(sma, prepend=sma[0]) if n else sma      # 與 sma 同長

    cu = cusum(da)
    bo = bocpd(detr)
    ss = ssa(sma)
    md = mad3sigma(da)
    return {
        "cusum":  {"scores": cu["scores"], "events": cu["events"]},
        "bocpd":  {"scores": bo["scores"], "events": bo["events"]},
        "ssa":    {"scores": ss["scores"], "events": ss["events"]},
        "mad3sig": {"scores": md["scores"], "events": md["events"]},
    }
