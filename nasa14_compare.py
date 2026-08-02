#!/usr/bin/env python3
"""nasa14_compare.py — 本專案 σ 正規化(SNR)變點偵測 vs PDF Poly/LOWESS,於 NASA/ILRS 14 星標竿。

真值：ids_truth_set/ids_truth.csv(修正版,14 星),collapse burns→機動事件(unique win_start)。
方法：a(t) 去趨勢後之相鄰步階 s，以「相對各星自身雜訊 σ 的 SNR 門檻」k·σ 判定機動——
      即雜訊底論文主張的高度相依 σ 正規化;另跑固定絕對門檻基線作對照。
評估：逐星 TP/FP/FN → Precision/Recall/F1，彙總平均(14 星)與最高;窗配對容差 ±1.5 天。
用法：python nasa14_compare.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import duckdb

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DB = "space_db.duckdb"
TRUTH = "ids_truth_set/ids_truth.csv"
RE = 6378.137
TOL_D = 1.5          # 窗配對容差(天)
MERGE_D = 1.0        # 相鄰旗標合併(天)
ROLL = 21            # Δa 去趨勢滾動中位窗
MIN_GAP_HR = 3.0     # TLE 稀釋

SATS = [(22076,"TOPEX/Poseidon"),(26997,"Jason-1"),(27386,"Envisat"),(33105,"Jason-2"),
        (36508,"CryoSat-2"),(37781,"HY-2A"),(39086,"SARAL"),(41240,"Jason-3"),
        (41335,"Sentinel-3A"),(43437,"Sentinel-3B"),(46469,"HY-2C"),(46984,"Sentinel-6A"),
        (48621,"HY-2D"),(54754,"SWOT")]


def tai2utc(ts):
    t = pd.to_datetime(ts, utc=True)
    off = np.where(t.dt.year <= 2016, 36, 37)
    return t - pd.to_timedelta(off, unit="s")


def load_events():
    d = pd.read_csv(TRUTH)
    d = d.dropna(subset=["norad"])
    d["norad"] = d["norad"].astype(int)
    d["ws"] = tai2utc(d["win_start_tai"]); d["we"] = tai2utc(d["win_end_tai"])
    ev = (d.groupby(["norad", "win_start_tai"])
            .agg(ws=("ws", "first"), we=("we", "first")).reset_index())
    return {n: g[["ws", "we"]].sort_values("ws").reset_index(drop=True)
            for n, g in ev.groupby("norad")}


def load_a(nid):
    con = duckdb.connect(DB, read_only=True)
    r = con.execute("SELECT epoch_utc, sma_km FROM raw_tle_archive "
                    "WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc", [nid]).fetchall()
    con.close()
    if not r: return None, None
    t = pd.to_datetime([x[0] for x in r], utc=True)
    a = np.array([float(x[1]) for x in r])
    ts = t.astype("int64").to_numpy() / 1e9
    keep = [0]
    for i in range(1, len(ts)):
        if ts[i] - ts[keep[-1]] >= MIN_GAP_HR * 3600:
            keep.append(i)
    return t[keep], a[np.array(keep)]


def detrend_step(a):
    """相鄰差分去趨勢：s[i] = Δa[i] − rolling_median(Δa)。回傳 s（與 a[1:] 對齊）。"""
    da = np.diff(a)
    s = pd.Series(da)
    base = s.rolling(ROLL, center=True, min_periods=5).median()
    return (s - base).to_numpy()


def robust_sigma(s):
    x = s[np.isfinite(s)]
    return 1.4826 * np.median(np.abs(x - np.median(x))) if len(x) else np.nan


def detect(t, a, thr_abs):
    """回傳偵測時刻(合併後)。thr_abs 為 |s| 的絕對門檻(km)。"""
    s = detrend_step(a)
    te = t[1:]                      # step 對應到後一點
    flag = np.abs(s) > thr_abs
    idx = np.where(flag & np.isfinite(s))[0]
    if len(idx) == 0: return []
    # 合併 MERGE_D 天內的連續旗標為單一偵測(取最大 |s| 的時刻)
    tsec = te.astype("int64").to_numpy() / 1e9
    dets, grp = [], [idx[0]]
    for j in idx[1:]:
        if tsec[j] - tsec[grp[-1]] <= MERGE_D * 86400:
            grp.append(j)
        else:
            best = grp[int(np.argmax(np.abs(s[grp])))]
            dets.append(te[best]); grp = [j]
    best = grp[int(np.argmax(np.abs(s[grp])))]
    dets.append(te[best])
    return pd.to_datetime(dets)


LW = 6   # 前後位準窗(點)


def _shift_signal(a, tsec, mask):
    """前後中位「持續性位準位移」訊號(去阻力斜率);單點離群不會造成持續位移 → 抑 FP。"""
    n = len(a)
    da = np.diff(a); dt = np.diff(tsec)
    good = (~mask[1:]) & (~mask[:-1]) & (dt > 0)
    sl = float(np.median(da[good] / dt[good])) if good.sum() > 10 else \
         float(np.median(da / np.where(dt > 0, dt, 1)))
    s = pd.Series(a)
    mb = s.rolling(LW, min_periods=3).median().shift(1).to_numpy()          # 前段中位 a[i-LW..i-1]
    ma = s[::-1].rolling(LW, min_periods=3).median().to_numpy()[::-1]       # 後段中位 a[i..i+LW-1]
    tb = pd.Series(tsec).rolling(LW, min_periods=3).median().shift(1).to_numpy()
    ta = pd.Series(tsec[::-1]).rolling(LW, min_periods=3).median().to_numpy()[::-1]
    return (ma - mb) - sl * (ta - tb)                                       # 去阻力後之位準位移(km)


def detect_iter(t, a, k, n_iter=3):
    """迭代 + 位準位移偵測:每輪偵測→遮罩→重估 σ 與阻力斜率→再偵測。回傳偵測時刻。"""
    n = len(a)
    tsec = t.astype("int64").to_numpy() / 1e9
    mask = np.zeros(n, bool)
    sig = _shift_signal(a, tsec, mask)
    for _ in range(n_iter):
        s = sig[np.isfinite(sig) & ~mask]
        sd = 1.4826 * np.median(np.abs(s - np.median(s))) if len(s) else np.nan
        if not np.isfinite(sd) or sd == 0:
            break
        newmask = np.zeros(n, bool)
        for j in np.where(np.abs(sig) > k * sd)[0]:
            newmask[max(0, j - LW):min(n, j + LW)] = True
        if newmask.sum() == mask.sum():
            mask = newmask; break
        mask = newmask
        sig = _shift_signal(a, tsec, mask)
    # 最終:以非極大抑制取每個位移峰為單一偵測
    s = sig[np.isfinite(sig)]
    sd = 1.4826 * np.median(np.abs(s - np.median(s))) if len(s) else np.nan
    if not np.isfinite(sd) or sd == 0:
        return pd.to_datetime([])
    cand = np.where(np.abs(sig) > k * sd)[0]
    used = np.zeros(n, bool); dets = []
    for j in sorted(cand, key=lambda x: -abs(sig[x])):
        if used[max(0, j - LW):min(n, j + LW)].any():
            continue
        used[max(0, j - LW):min(n, j + LW)] = True
        dets.append(t[j])
    return pd.to_datetime(sorted(dets))


def evaluate(nid, events, detfn):
    t, a = load_a(nid)
    if t is None or len(a) < 30 or nid not in events:
        return None
    ev = events[nid]
    # 評估重疊區間：TLE 與真值皆有
    lo = max(t.min(), ev["ws"].min()); hi = min(t.max(), ev["we"].max())
    ev = ev[(ev["ws"] >= lo) & (ev["ws"] <= hi)].reset_index(drop=True)
    if len(ev) == 0: return None
    dets = detfn(t, a)
    dets = pd.to_datetime([d for d in dets if lo <= d <= hi])
    tol = pd.Timedelta(days=TOL_D)
    # TP/FN：逐真值事件是否被任一偵測命中
    det_used = np.zeros(len(dets), bool)
    tp = 0
    for _, e in ev.iterrows():
        w0, w1 = e["ws"] - tol, e["we"] + tol
        hit = [i for i, d in enumerate(dets) if w0 <= d <= w1 and not det_used[i]]
        if hit:
            det_used[hit[0]] = True; tp += 1
    fn = len(ev) - tp
    fp = int((~det_used).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return dict(norad=nid, n_ev=len(ev), n_det=len(dets), tp=tp, fp=fp, fn=fn,
                precision=prec, recall=rec, f1=f1)


def run_mode(events, mode, param):
    """mode='snr' 單趟 σ 正規化;mode='abs' 固定門檻(km);mode='iter' 迭代位準位移(k=param)。"""
    rows = []
    for nid, nm in SATS:
        if mode == "iter":
            detfn = lambda t, a, k=param: detect_iter(t, a, k)
        elif mode == "snr":
            t0, a0 = load_a(nid)
            if t0 is None: continue
            thr = param * robust_sigma(detrend_step(a0))
            detfn = lambda t, a, thr=thr: detect(t, a, thr)
        else:
            detfn = lambda t, a, thr=param: detect(t, a, thr)
        r = evaluate(nid, events, detfn)
        if r: rows.append({**r, "name": nm})
    return pd.DataFrame(rows)


def main():
    events = load_events()
    print("=" * 78)
    print("本專案 σ 正規化(SNR)偵測 vs 固定門檻，NASA/ILRS 14 星標竿")
    print("=" * 78)

    # ── 單趟 σ 正規化基線 ──
    print("【單趟 σ 正規化(相鄰步階)】")
    for k in [4, 6, 8]:
        df = run_mode(events, "snr", k)
        print(f"  k={k}: 平均 F1={df['f1'].mean():.3f} (P={df['precision'].mean():.2f} "
              f"R={df['recall'].mean():.2f}) | 最高 F1={df['f1'].max():.3f}")

    # ── 固定絕對門檻基線 ──
    print("【固定絕對門檻(對照)】")
    for thr in [0.05, 0.1]:
        df = run_mode(events, "abs", thr)
        print(f"  |s|>{thr*1000:.0f} m: 平均 F1={df['f1'].mean():.3f} "
              f"(P={df['precision'].mean():.2f} R={df['recall'].mean():.2f}) | 最高 F1={df['f1'].max():.3f}")

    # ── 迭代 + 位準位移(本次新增,對標 PDF 迭代法) ──
    print("【迭代 + 位準位移(σ 正規化)】← 本次新增")
    best = None
    for k in [3, 4, 5, 6]:
        df = run_mode(events, "iter", k)
        avg_f1 = df["f1"].mean()
        print(f"  k={k}: 平均 F1={avg_f1:.3f} (P={df['precision'].mean():.2f} "
              f"R={df['recall'].mean():.2f}) | 最高 F1={df['f1'].max():.3f}")
        if best is None or avg_f1 > best[1]:
            best = (k, avg_f1, df)

    k, avg_f1, df = best
    print("=" * 78)
    print(f"★ 最佳(迭代+位準位移) 全域 k={k}：平均 F1={avg_f1:.3f}、最高 F1={df['f1'].max():.3f}")
    print(f"  對照 PDF 最佳(LOWESS ΔSMA/Δt 迭代)：平均 F1=0.52、最高 F1=0.92\n")

    df = df.sort_values("f1", ascending=False)
    print(f"{'衛星':14}{'事件':>5}{'偵測':>5}{'TP':>4}{'FP':>4}{'FN':>5}"
          f"{'P':>6}{'R':>6}{'F1':>6}")
    for _, r in df.iterrows():
        print(f"{r['name']:14}{r.n_ev:>5}{r.n_det:>5}{r.tp:>4}{r.fp:>4}{r.fn:>5}"
              f"{r.precision:>6.2f}{r.recall:>6.2f}{r.f1:>6.2f}")

    out = Path("data/benchmark/nasa14_compare_iter_20260801.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.assign(global_k=k, method="iter+levelshift").to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}")


if __name__ == "__main__":
    main()
