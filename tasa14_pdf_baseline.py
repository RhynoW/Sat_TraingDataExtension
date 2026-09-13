#!/usr/bin/env python3
"""tasa14_pdf_baseline.py — 曲線擬合基準法之本地重實作(同擂台版)。

背景:報告先前引用之「PDF LOWESS 迭代 平均 F1=0.52、最高 0.92」為早期重實作
參考值,其腳本未保留、不可重現。本檔依文獻(李泽越等,國防科技大學學報 2024,
doi:10.11887/j.cn.202404005)之方法精神——LOWESS 平滑、預報(擬合)誤差、
自適應門檻、迭代精修——重新實作,並在與 tasa14_compare.py **完全相同的評估
口徑**(同真值、同 ±1.5 天窗容差、同貪婪一對一配對、同 1 天旗標合併)下跑
14 星,使兩法可公平同台比較(回應委員「同子集重算對照法」之要求)。

方法(重實作,非原碼):
  主族「前向預測誤差」(faithful,v2):對每一點 i,以其前 w 點擬合多項式
  (deg 1/2)外推至 t_i,誤差 e_i = a_i − pred_i——與原文獻「軌道預報誤差
  擬合法」同構(預測只用機動前資料,步階無法被平滑吸收)。窗寬 w 依 TLE
  頻率自適應(文獻圖 6 經驗關係之近似 w = clip(round(16 − 3.2·f), 6, 20))。
  自適應門檻 |e| > k·1.4826·MAD;迭代=將旗標點自後續擬合窗剔除+重估 MAD。
  對照族「LOWESS 對稱平滑殘差」(v1)保留於網格——健全性檢查(§4.5)顯示
  小窗對稱平滑會吸收步階,故其分數僅列為家族內對照,不作曲線法上限。
  兩族 × 參數網格之逐星最佳(oracle)作為曲線法之優待上界。
用法:python tasa14_pdf_baseline.py
輸出:data/benchmark/tasa14_pdf_baseline_20260803.csv(全域最佳逐星 P/R/F1)
     data/benchmark/tasa14_pdf_oracle_20260803.csv(逐星 oracle 優待)
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from statsmodels.nonparametric.smoothers_lowess import lowess as sm_lowess

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

from tasa14_compare import load_a, load_events, evaluate, SATS, MERGE_D

N_ITER = 3


def _adaptive_w(tsec):
    """文獻圖 6 經驗關係之近似:TLE 頻率 f(個/天)→ 窗寬 w(點)。"""
    span_d = (tsec[-1] - tsec[0]) / 86400.0
    f = len(tsec) / max(span_d, 1.0)
    return int(np.clip(round(16 - 3.2 * f), 6, 20))


def _fit_curve(tsec, a, mask, frac):
    """於未遮罩點擬合 LOWESS,回傳全點位之曲線值(遮罩區內插)。"""
    g = ~mask
    if g.sum() < 10:
        g = np.ones(len(a), bool)
    sm = sm_lowess(a[g], tsec[g], frac=frac, it=1, return_sorted=False)
    return np.interp(tsec, tsec[g], sm)


def detect_pdf(t, a, k, channel="resid", n_iter=N_ITER):
    """LOWESS 曲線法偵測。channel='resid'(ΔSMA)或 'rate'(ΔSMA/Δt)。"""
    n = len(a)
    tsec = t.astype("int64").to_numpy() / 1e9
    w = _adaptive_w(tsec)
    frac = min(1.0, max(w / n, 5.0 / n))
    mask = np.zeros(n, bool)
    sig = np.full(n, np.nan)
    sd = np.nan
    for _ in range(max(1, n_iter)):
        curve = _fit_curve(tsec, a, mask, frac)
        r = a - curve
        if channel == "rate":
            dt_d = np.diff(tsec) / 86400.0
            sig = np.concatenate([[np.nan], np.diff(r) / np.where(dt_d > 0, dt_d, np.nan)])
        else:
            sig = r.copy()
        s = sig[np.isfinite(sig) & ~mask]
        new_sd = 1.4826 * np.median(np.abs(s - np.median(s))) if len(s) else np.nan
        if np.isfinite(new_sd) and new_sd > 0:
            sd = new_sd
        elif not np.isfinite(sd) or sd == 0:
            return pd.to_datetime([])
        newmask = np.zeros(n, bool)
        for j in np.where(np.isfinite(sig) & (np.abs(sig) > k * sd))[0]:
            newmask[max(0, j - w):min(n, j + w)] = True
        # 遮罩爆炸保護:未遮罩樣本不足以穩健估 MAD 時,停止迭代沿用前輪
        if newmask.mean() > 0.5:
            break
        if newmask.sum() == mask.sum():
            mask = newmask
            break
        mask = newmask
    # 最終偵測:旗標點合併 MERGE_D 天,取 |sig| 最大時刻(與 tasa14_compare.detect 同)
    idx = np.where(np.isfinite(sig) & (np.abs(sig) > k * sd))[0]
    if len(idx) == 0:
        return pd.to_datetime([])
    dets, grp = [], [idx[0]]
    for j in idx[1:]:
        if tsec[j] - tsec[grp[-1]] <= MERGE_D * 86400:
            grp.append(j)
        else:
            dets.append(t[grp[int(np.argmax(np.abs(sig[grp])))]]); grp = [j]
    dets.append(t[grp[int(np.argmax(np.abs(sig[grp])))]])
    return pd.to_datetime(sorted(dets))


def run_pdf(events, k, channel="resid", n_iter=N_ITER):
    rows = []
    for nid, nm in SATS:
        detfn = lambda t, a, k=k, ch=channel, ni=n_iter: detect_pdf(t, a, k, ch, ni)
        r = evaluate(nid, events, detfn)
        if r:
            rows.append({**r, "name": nm})
    return pd.DataFrame(rows)


# ────────────────── v2 主族:前向預測誤差(faithful) ──────────────────

def _pred_error(tsec, a, w, deg, bad):
    """滑動窗前向預測誤差:e[i] = a[i] − poly(前 w 點,deg).extrap(t[i])。
    bad=True 之點(已判為事件)不參與擬合窗(nan-aware);窗內有效點 <max(4,w/2)
    時 e=NaN。向量化 normal equations,O(n·w)。"""
    from numpy.lib.stride_tricks import sliding_window_view
    n = len(a)
    e = np.full(n, np.nan)
    if n <= w + 1:
        return e
    x = tsec / 86400.0
    y = np.where(bad, np.nan, a)
    Yw = sliding_window_view(y, w)[:-1]          # 視窗 i:y[i..i+w-1] → 預測 i+w
    Xw = sliding_window_view(x, w)[:-1]
    valid = np.isfinite(Yw)
    cnt = valid.sum(axis=1)
    Xm = np.where(valid, Xw, np.nan)
    xm = np.nanmean(Xm, axis=1)
    Xc = np.where(valid, Xw - xm[:, None], 0.0)
    Yv = np.where(valid, Yw, 0.0)
    tx = x[w:] - xm
    S0 = cnt.astype(float)
    S1 = Xc.sum(1); S2 = (Xc**2).sum(1)
    Sy = Yv.sum(1); Sxy = (Xc * Yv).sum(1)
    eps = 1e-12
    if deg == 1:
        den = S0 * S2 - S1**2
        b = (S0 * Sxy - S1 * Sy) / np.where(np.abs(den) < eps, np.nan, den)
        c = (Sy - b * S1) / np.maximum(S0, 1)
        pred = c + b * tx
    else:
        S3 = (Xc**3).sum(1); S4 = (Xc**4).sum(1)
        Sx2y = ((Xc**2) * Yv).sum(1)
        A = np.stack([np.stack([S0, S1, S2], -1),
                      np.stack([S1, S2, S3], -1),
                      np.stack([S2, S3, S4], -1)], -2)
        A = A + np.eye(3) * 1e-9
        rhs = np.stack([Sy, Sxy, Sx2y], -1)
        try:
            sol = np.linalg.solve(A, rhs[..., None])[..., 0]
        except np.linalg.LinAlgError:
            sol = np.full((len(S0), 3), np.nan)
        pred = sol[:, 0] + sol[:, 1] * tx + sol[:, 2] * tx**2
    e[w:] = a[w:] - pred
    e[w:][cnt < max(4, w // 2)] = np.nan
    return e


def detect_pred(t, a, k, deg=1, n_iter=N_ITER):
    """前向預測誤差偵測(v2 主族)。迭代:旗標點剔除出擬合窗+重估 MAD。"""
    n = len(a)
    tsec = t.astype("int64").to_numpy() / 1e9
    w = _adaptive_w(tsec)
    bad = np.zeros(n, bool)
    sd = np.nan
    e = np.full(n, np.nan)
    for _ in range(max(1, n_iter)):
        e = _pred_error(tsec, a, w, deg, bad)
        s = e[np.isfinite(e) & ~bad]
        new_sd = 1.4826 * np.median(np.abs(s - np.median(s))) if len(s) else np.nan
        if np.isfinite(new_sd) and new_sd > 0:
            sd = new_sd
        elif not np.isfinite(sd) or sd == 0:
            return pd.to_datetime([])
        newbad = np.isfinite(e) & (np.abs(e) > k * sd)
        if newbad.mean() > 0.5 or newbad.sum() == bad.sum():
            bad = newbad if newbad.mean() <= 0.5 else bad
            break
        bad = newbad
    idx = np.where(np.isfinite(e) & (np.abs(e) > k * sd))[0]
    if len(idx) == 0:
        return pd.to_datetime([])
    dets, grp = [], [idx[0]]
    for j in idx[1:]:
        if tsec[j] - tsec[grp[-1]] <= MERGE_D * 86400:
            grp.append(j)
        else:
            dets.append(t[grp[int(np.argmax(np.abs(e[grp])))]]); grp = [j]
    dets.append(t[grp[int(np.argmax(np.abs(e[grp])))]])
    return pd.to_datetime(sorted(dets))


def run_pred(events, k, deg=1, n_iter=N_ITER):
    rows = []
    for nid, nm in SATS:
        detfn = lambda t, a, k=k, dg=deg, ni=n_iter: detect_pred(t, a, k, dg, ni)
        r = evaluate(nid, events, detfn)
        if r:
            rows.append({**r, "name": nm})
    return pd.DataFrame(rows)


def main():
    events = load_events()
    print("=" * 78)
    print("曲線擬合基準法重實作 v2(前向預測誤差為主族)— NASA/ILRS 14 星,同擂台")
    print("=" * 78)
    KS = [3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30]
    KS_PRED = KS + [40, 50, 60, 80]      # pred 族誤差幅度大,峰值 k 較高
    grid = {}                      # (family, p1, n_iter, k) → df
    best = None
    # 主族:前向預測誤差(deg=1/2)
    for deg in [1, 2]:
        for n_iter, tag in [(1, "單趟"), (N_ITER, "迭代")]:
            for k in KS_PRED:
                df = run_pred(events, k, deg, n_iter)
                grid[("pred", deg, n_iter, k)] = df
                m = df["f1"].mean()
                print(f"  預測誤差 deg{deg} {tag} k={k:2d}: 平均 F1={m:.3f} "
                      f"(P={df['precision'].mean():.2f} R={df['recall'].mean():.2f}) "
                      f"| 最高 F1={df['f1'].max():.3f}", flush=True)
                if best is None or m > best[0]:
                    best = (m, ("pred", deg, n_iter, k), df)
    # 對照族:LOWESS 對稱平滑殘差(v1;§4.5 已證會吸收步階,僅列家族內對照)
    for channel in ["resid", "rate"]:
        for n_iter, tag in [(1, "單趟"), (N_ITER, "迭代")]:
            for k in KS:
                df = run_pdf(events, k, channel, n_iter)
                grid[("lowess", channel, n_iter, k)] = df
                m = df["f1"].mean()
                print(f"  LOWESS {channel:5s} {tag} k={k:2d}: 平均 F1={m:.3f} "
                      f"| 最高 F1={df['f1'].max():.3f}", flush=True)
                if best is None or m > best[0]:
                    best = (m, ("lowess", channel, n_iter, k), df)
    m, cfg, df = best
    fam, p1, n_iter, k = cfg
    print("=" * 78)
    print(f"★ 全域最佳組態:{fam}/{p1} iter{n_iter} k={k} → 平均 F1={m:.3f}、最高 F1={df['f1'].max():.3f}")

    # ── 逐星最佳組態(oracle 優待):兩族全網格取每星 F1 最高 ──
    all_rows = []
    for (f_, p_, ni, kk), d in grid.items():
        all_rows.append(d.assign(family=f_, param=str(p_), n_iter=ni, global_k=kk,
                                 method=f"{f_}_{p_}_iter{ni}"))
    big = pd.concat(all_rows, ignore_index=True)
    oracle = big.loc[big.groupby("norad")["f1"].idxmax()].reset_index(drop=True)
    print(f"◆ 逐星最佳組態(oracle 優待):平均 F1={oracle['f1'].mean():.3f}"
          f"(P={oracle['precision'].mean():.2f} R={oracle['recall'].mean():.2f})"
          f"、最高 F1={oracle['f1'].max():.3f}")
    oracle = oracle.sort_values("f1", ascending=False)
    print(f"{'衛星':14}{'組態':22}{'事件':>5}{'TP':>4}{'FP':>5}{'P':>6}{'R':>6}{'F1':>6}")
    for _, r in oracle.iterrows():
        print(f"{r['name']:14}{r['method']+'/k='+str(r['global_k']):22}{r.n_ev:>5}"
              f"{r.tp:>4}{r.fp:>5}{r.precision:>6.2f}{r.recall:>6.2f}{r.f1:>6.2f}")

    out = Path("data/benchmark/tasa14_pdf_baseline_20260803.csv")
    df.assign(family=fam, param=str(p1), n_iter=n_iter, global_k=k,
              method=f"{fam}_{p1}_iter{n_iter}").to_csv(out, index=False, encoding="utf-8-sig")
    out2 = Path("data/benchmark/tasa14_pdf_oracle_20260803.csv")
    oracle.to_csv(out2, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}(全域最佳)、{out2}(逐星 oracle 優待)")


if __name__ == "__main__":
    main()
