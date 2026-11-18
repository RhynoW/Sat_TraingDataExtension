#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paperC_numbers.py — 期刊論文 C（docs/paper_nrlmsis_drag_validation.md）數字重現與補充分析。

逐節重算論文中可重現之數字，並補做研究缺口之分析；輸出 data/benchmark/paperC_numbers.json（分節合併寫入），
明細另存新檔（皆加 _20261118 後綴，不覆寫既有結果檔）：
  paperC_thr_insample_20261118.csv     §3.5／表 5 樣本內重算（與 drag_thr_by_alt_x30.csv 對照）
  paperC_thr_oos_bins_20261118.csv     任務 1：各方案 × 各評估法 × 各高度檔之樣本外誤報率與 90% 下限
  paperC_thr_oos_summary_20261118.csv  任務 1：各方案 × 評估法之全體摘要
  paperC_thr_oos_thresholds_20261118.csv  任務 1：各評估法訓練所得之各檔門檻（重複抽樣之中位數）
  paperC_fs7_pooled_20261118.csv       任務 2：福衛七號合併相關與 95% CI
  paperC_bias_by_f107_20261118.csv     任務 3：高活動期偏差（NRLMSIS／實測比值）依 F10.7 分組
  paperC_f107lag_20261118.csv          任務 4：F10.7 時間對齊敏感度
  paperC_fs73_20261118.csv             任務 5：FORMOSAT7-3 精密軌道與 TLE 窗
用法（Windows ARM64 / Python 3.13；資料庫一律 read_only）：
  set PYTHONIOENCODING=utf-8
  python docs/paperC_numbers.py                     # 全部
  python docs/paperC_numbers.py corr fs7 thr        # 只跑指定子命令
子命令：
  sample  §2.3 選星與補齊（425 顆、候選數、補齊衛星數與筆數、期間平均高度）
  decay   §3.1／圖 1（代表衰減率、F10.7）
  corr    §3.2／表 1、表 2
  solar   §3.3／表 3
  fs7     §3.4／表 4（逐星）
  thr     §2.8／§3.5／表 5（樣本內重算）
  oos     任務 1：門檻方案之樣本外驗證（衛星 k-fold、時間切分）
  fs7pool 任務 2：福衛七號 616 窗合併相關與 95% CI
  bias    任務 3：NRLMSIS／實測比值依 F10.7 81 日平均分組
  f107lag 任務 4：F10.7 當日 vs 前一日（福衛七號 616 窗＋270 顆中每帶 10 顆）
  fs73    任務 5：FORMOSAT7-3（NORAD 44343）精密軌道可得性與自由衰減段
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs"))
BM = ROOT / "data" / "benchmark"
OUT_JSON = BM / "paperC_numbers.json"
WORK = BM / "paperC_cache"                 # 本程式之中間快取（可刪除重算）
TAG = "20261118"
SUF = "_x30"
CACHE = BM / f"perigee_drag_cache{SUF}"
SEED = 20261118
FP_TARGET = 0.43
SPLIT = pd.Timestamp("2025-07-01", tz="UTC")
RE_KM = 6378.137
F107_GROUPS = [("<120", 0, 120), ("120–160", 120, 160), (">160", 160, 1e9)]
BANDS = [("350–550 km", 300, 575), ("600–700 km", 575, 725), ("750–850 km", 725, 875), ("900–1000 km", 875, 1025)]


def _r(x, n=4):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return x
    return round(x, n) if math.isfinite(x) else None


def _csv(df: pd.DataFrame, name: str):
    p = BM / f"{name}_{TAG}.csv"
    df.to_csv(p, index=False, encoding="utf-8-sig")
    print("  →", p.relative_to(ROOT))


def fisher_ci(r, n, z=1.959964):
    zr = np.arctanh(r)
    se = 1 / math.sqrt(n - 3)
    return float(np.tanh(zr - z * se)), float(np.tanh(zr + z * se))


def sw_daily() -> pd.DataFrame:
    """space_weather_ap.csv 之每日 F10.7 觀測值與 81 日中心平均（與 atmospheric_drag 同源）。"""
    sw = pd.read_csv(ROOT / "space_weather_ap.csv")
    d = pd.DataFrame({"date": pd.to_datetime(sw["DATE"]),
                      "f107": pd.to_numeric(sw["F10.7_OBS"], errors="coerce"),
                      "f107_81": pd.to_numeric(sw["F10.7_OBS_CENTER81"], errors="coerce")})
    return d.set_index("date").sort_index()


# ════════════════════════════════════════════════════════════════════════════
# 門檻研討（與 docs/study_drag_resid_threshold.py 同法）
# ════════════════════════════════════════════════════════════════════════════
GRID = np.round(np.concatenate([np.arange(0.03, 0.30, 0.01), np.arange(0.30, 3.01, 0.05)]), 3)


def load_transitions(all_dt: bool = False) -> pd.DataFrame:
    """全期被動衛星之逐筆轉換（與 study_drag_resid_threshold.load 相同）。all_dt=True 時保留所有轉換（供 B_eff 重新校準）。"""
    P = pd.read_csv(BM / f"perigee_drag_corr_persat{SUF}.csv")
    rows = []
    for nid in P[P.passive_all].norad_id:
        f = CACHE / f"{nid}.csv.gz"
        if not f.exists():
            continue
        r = pd.read_csv(f, usecols=["epoch", "da_km", "drag_pred_da", "drag_resid_da", "alt_km", "dt_d", "B_eff"])
        if not all_dt:
            r = r[(r.dt_d > 0) & (r.dt_d <= 3)].copy()
        r["norad_id"] = nid
        rows.append(r)
    T = pd.concat(rows, ignore_index=True)
    T["epoch"] = pd.to_datetime(T.epoch, utc=True)
    T["hbin"] = (T.alt_km / 50).round() * 50
    if not all_dt:
        T = T[T.hbin.between(300, 1000)]
    return T.reset_index(drop=True)


class FP:
    """快速誤報率：列依 (衛星, 時間) 排序；超門檻點依星 48 小時內合併為一次事件。"""

    def __init__(self, T: pd.DataFrame):
        o = np.lexsort((T.epoch.astype("int64").to_numpy(), T.norad_id.to_numpy()))
        self.T = T.iloc[o].reset_index(drop=True)
        self.sat = self.T.norad_id.to_numpy()
        self.t = self.T.epoch.astype("int64").to_numpy() / 1e9
        self.dtd = self.T.dt_d.to_numpy()
        hb = self.T.hbin.to_numpy()
        self.bin_idx = {h: np.flatnonzero(hb == h) for h in np.unique(hb)}

    def events_idx(self, i) -> int:
        """i：已依 (衛星, 時間) 排序之超門檻列索引。"""
        if len(i) == 0:
            return 0
        s, tt = self.sat[i], self.t[i]
        return int(1 + ((s[1:] != s[:-1]) | (np.diff(tt) > 48 * 3600)).sum())

    def events(self, flag: np.ndarray) -> int:
        return self.events_idx(np.flatnonzero(flag))

    def rate(self, flag, mask) -> float:
        sd = self.dtd[mask].sum()
        return self.events(flag & mask) / (sd / 1000) if sd > 0 else np.nan


def pava_decreasing(y, w):
    """加權保序迴歸（非遞增）。"""
    y, w = list(map(float, y)), list(map(float, w))
    blocks = [[y[i], w[i], 1] for i in range(len(y))]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] < blocks[i + 1][0]:             # 違反非遞增 → 合併
            a, b = blocks[i], blocks[i + 1]
            wt = a[1] + b[1]
            blocks[i] = [(a[0] * a[1] + b[0] * b[1]) / wt, wt, a[2] + b[2]]
            del blocks[i + 1]
            i = max(i - 1, 0)
        else:
            i += 1
    out = []
    for v, _, k in blocks:
        out += [v] * k
    return np.array(out)


ALL_BINS = np.arange(300.0, 1001.0, 50.0)
SD_MIN = 1000.0 / FP_TARGET          # 訓練星日少於此值之檔：零事件以外無法證明誤報率 ≤ 目標（1 件即超標）


def fit_schemes(F: FP, tr: np.ndarray, resid_col: str = "drag_resid_da", n_min: float = 3000.0) -> dict:
    """在訓練列（布林遮罩 tr）上決定各方案之門檻；回傳 {方案: Series(hbin → thr)}（涵蓋 300–1000 km 全部 15 檔）與 C 式係數。

    B：論文定義（各檔格點最小門檻使誤報率 ≤ 目標）；訓練集缺該檔時以 C 式於檔位中心之值代入。
    C：論文定義（轉換數 ≥ n_min 之檔，log10 B 對高度線性擬合；下限 0.03 km）。
    D（改良一）：B 之單調（非遞增）上包絡——僅用訓練星日 ≥ SD_MIN 之檔，每檔取「該檔及以上各檔 B 之最大值」；
       資料不足之檔取 max(C 式值, 上方最近之 D 值)。無自由參數。
    E（改良二）：B 之加權保序迴歸（log10、非遞增、權重＝訓練轉換數，同樣只用資料足夠之檔）；資料不足檔同 D 之處理。
    """
    T = F.T
    absr = T[resid_col].abs().to_numpy()
    thrB, ntr, sdd = {}, {}, {}
    for h, ib in F.bin_idx.items():
        ib = ib[tr[ib]]
        if len(ib) == 0:
            continue
        ntr[h] = len(ib)
        a, sd = absr[ib], F.dtd[ib].sum() / 1000
        sdd[h] = sd * 1000
        thrB[h] = next((g for g in GRID if F.events_idx(ib[a > g]) / sd <= FP_TARGET), GRID[-1])
    B0 = pd.Series(thrB).sort_index()
    N = pd.Series(ntr).reindex(ALL_BINS).fillna(0)
    SD = pd.Series(sdd).reindex(ALL_BINS).fillna(0)
    fitm = N[N >= n_min].index
    b_, a_ = np.polyfit(fitm.to_numpy(float), np.log10(B0[fitm].to_numpy(float)), 1)
    Cc = pd.Series(np.maximum(10 ** (a_ + b_ * ALL_BINS), 0.03), index=ALL_BINS)
    B = B0.reindex(ALL_BINS)
    B = B.fillna(Cc)
    suff = SD >= SD_MIN
    Bs = B0[suff.reindex(B0.index).fillna(False).to_numpy()]

    def fill_insufficient(S):
        out = {}
        for h in ALL_BINS[::-1]:                              # 由高而低，保證非遞增
            above = [out[x] for x in out if x > h]
            ref = min(above) if above else 0.03
            out[h] = S[h] if h in S.index else max(Cc[h], ref)
            out[h] = max(out[h], ref)                         # 單調約束
        return pd.Series(out).sort_index()

    D = fill_insufficient(pd.Series({h: Bs[Bs.index >= h].max() for h in Bs.index}))
    E0 = pd.Series(10 ** pava_decreasing(np.log10(Bs.to_numpy(float)), N[Bs.index].to_numpy(float)), index=Bs.index).clip(lower=0.03)
    E = fill_insufficient(E0)
    return {"B": B, "D": D, "E": E, "C_ab": (a_, b_), "n_train": N, "sd_train": SD, "B_raw": B0}


def thr_rows(F: FP, sch: dict, scheme: str) -> np.ndarray:
    T = F.T
    if scheme == "A":
        return np.full(len(T), 0.30)
    if scheme == "C":
        a_, b_ = sch["C_ab"]
        return np.maximum(10 ** (a_ + b_ * T.alt_km.to_numpy()), 0.03)
    return T.hbin.map(sch[scheme]).to_numpy(float)


def min90(resid, thr, rng, n_max=3000):
    """注入：隨機抽至多 3,000 筆，殘差加上隨機正負號之步階 s（0.02–3.0 km），回傳超門檻比例達 90% 之最小 s。"""
    if len(resid) == 0:
        return np.nan
    idx = rng.choice(len(resid), size=min(len(resid), n_max), replace=False)
    rr, tt = resid[idx], thr[idx]
    sign = rng.choice([-1, 1], size=len(idx))
    for sz in np.arange(0.02, 3.01, 0.01):
        if (np.abs(rr + sign * sz) > tt).mean() >= 0.9:
            return round(float(sz), 2)
    return np.nan


SCHEMES = ["A", "B", "C", "D", "E"]


def evaluate(F: FP, te: np.ndarray, thr: dict, resid_col="drag_resid_da"):
    """測試列 te 上各方案之各檔誤報率與全體誤報率。"""
    T = F.T
    absr = T[resid_col].abs().to_numpy()
    hb = T.hbin.to_numpy()
    out = []
    for s in SCHEMES:
        flag = absr > thr[s]
        for h in sorted(np.unique(hb[te])):
            m = te & (hb == h)
            out.append({"scheme": s, "hbin": h, "events": F.events(flag & m), "sat_days": F.dtd[m].sum(),
                        "n_trans": int(m.sum())})
        out.append({"scheme": s, "hbin": -1, "events": F.events(flag & te), "sat_days": F.dtd[te].sum(), "n_trans": int(te.sum())})
    return pd.DataFrame(out)


def _bin_table(F, ev_df, inj, label):
    """事件表 → 每方案每檔誤報率（含全體列 hbin = −1）＋ 90% 下限。"""
    g = ev_df.groupby(["scheme", "hbin"], as_index=False)[["events", "sat_days", "n_trans"]].sum()
    g["fp_per_ksd"] = g.events / (g.sat_days / 1000)
    g["meets_target"] = g.fp_per_ksd <= FP_TARGET + 1e-9
    g["eval"] = label
    if inj is not None:
        g = g.merge(inj, on=["scheme", "hbin"], how="left")
    return g


def _inject_all(F, te, thr, rng, resid_col="drag_resid_da"):
    T = F.T
    rr = T[resid_col].to_numpy()
    out = []
    for h, ib in F.bin_idx.items():
        ib = ib[te[ib]]
        for s in SCHEMES:
            out.append({"scheme": s, "hbin": h, "min90_km": min90(rr[ib], thr[s][ib], rng)})
    return pd.DataFrame(out)


def sec_thr():
    """§2.8／§3.5／表 5：樣本內重算（全部資料決定門檻、全部資料評估）。"""
    T = load_transitions()
    F = FP(T)
    allm = np.ones(len(F.T), bool)
    sch = fit_schemes(F, allm)
    thr = {s: thr_rows(F, sch, s) for s in SCHEMES}
    ev = evaluate(F, allm, thr)
    rng = np.random.default_rng(SEED)
    tab = _bin_table(F, ev, _inject_all(F, allm, thr, rng), "in-sample")
    absr = F.T.drag_resid_da.abs()
    extra = F.T.groupby("hbin").agg(n_sat=("norad_id", "nunique"), n_trans=("dt_d", "size"),
                                    pred_med_km=("drag_pred_da", lambda s: s.abs().median()),
                                    p99_km=("drag_resid_da", lambda s: s.abs().quantile(0.99)))
    thrC_med = pd.Series(thr["C"], index=F.T.index).groupby(F.T.hbin).median().rename("thrC_med_km")
    W = tab[tab.hbin > 0].pivot_table(index="hbin", columns="scheme", values="fp_per_ksd")
    W.columns = [f"fp_{c}" for c in W.columns]
    M = tab[tab.hbin > 0].pivot_table(index="hbin", columns="scheme", values="min90_km")
    M.columns = [f"min90_{c}" for c in M.columns]
    out = pd.concat([extra, W, M, thrC_med, sch["B"].rename("thrB_km"), sch["D"].rename("thrD_km"),
                     sch["E"].rename("thrE_km")], axis=1)
    out.index.name = "hbin"
    out = out.reset_index()
    _csv(out.round(4), "paperC_thr_insample")
    a_, b_ = sch["C_ab"]
    zA = (absr > 0.30).to_numpy()
    lo, hi = (F.T.hbin <= 450).to_numpy(), (F.T.hbin >= 600).to_numpy()
    O = pd.read_csv(BM / "drag_thr_by_alt_x30.csv").set_index("hbin")      # 論文表 5 之來源
    o = out.set_index("hbin")
    cmp = {c: bool(np.allclose(O[c].to_numpy(float), o[k].to_numpy(float), atol=6e-4, equal_nan=True))
           for c, k in [("thrB_km", "thrB_km"), ("fp_A_per_ksd", "fp_A"), ("fp_B_per_ksd", "fp_B"), ("fp_C_per_ksd", "fp_C"),
                        ("thrC_med_km", "thrC_med_km"), ("p99_km", "p99_km"), ("pred_med_km", "pred_med_km"),
                        ("n_sat", "n_sat"), ("n_trans", "n_trans")]}
    # 90% 下限：原程式之亂數序列不同（RNG 消耗順序不同），以差異量呈現
    d90 = {lab: _r(np.nanmax(np.abs(O[f"min90_{lab}_km"].to_numpy(float) - o[f"min90_{lab}"].to_numpy(float))), 3) for lab in "ABC"}
    allr = lambda s: _r(tab[(tab.scheme == s) & (tab.hbin == -1)].fp_per_ksd.iloc[0])  # noqa: E731
    res = dict(
        n_trans=len(F.T), n_sat=int(F.T.norad_id.nunique()), sat_days=_r(F.dtd.sum(), 1),
        fp_A_all=_r(F.rate(zA, allm)), fp_A_300_450=_r(F.rate(zA, lo)), fp_A_600_1000=_r(F.rate(zA, hi)),
        fp_B_all=allr("B"), fp_C_all=allr("C"), fp_D_all=allr("D"), fp_E_all=allr("E"),
        C_a=_r(a_, 4), C_b_per_1000km=_r(b_ * 1000, 4),
        C_thr_at={h: _r(max(10 ** (a_ + b_ * h), 0.03), 3) for h in (300, 500, 700, 1000)},
        match_drag_thr_by_alt_x30=cmp, min90_maxabs_diff_vs_csv=d90,
        bins=out.round(4).to_dict(orient="records"),
        p99_600_1000_range_m=[_r(o.loc[600:1000, "p99_km"].min() * 1000, 1), _r(o.loc[600:1000, "p99_km"].max() * 1000, 1)],
        fp_C_bins_above_target=[float(h) for h in o.index if o.loc[h, "fp_C"] > FP_TARGET],
        fp_C_bins_above_A=[float(h) for h in o.index if o.loc[h, "fp_C"] > o.loc[h, "fp_A"] + 1e-9],
        csv_min90_C_700_1000=[_r(O.loc[700:1000, "min90_C_km"].min(), 2), _r(O.loc[700:1000, "min90_C_km"].max(), 2)],
        csv_min90_A_700_1000=[_r(O.loc[700:1000, "min90_A_km"].min(), 2), _r(O.loc[700:1000, "min90_A_km"].max(), 2)],
        csv_min90_C_300_400=[_r(O.loc[300:400, "min90_C_km"].min(), 2), _r(O.loc[300:400, "min90_C_km"].max(), 2)],
    )
    # 誤報事件之衛星集中度（樣本內）：各方案各檔之事件數、涉及衛星數、前三名衛星
    P = pd.read_csv(BM / f"perigee_drag_corr_persat{SUF}.csv").set_index("norad_id")
    conc = []
    for s in SCHEMES:
        for h, ib in F.bin_idx.items():
            fl = ib[absr.to_numpy()[ib] > thr[s][ib]]
            if len(fl) == 0:
                conc.append({"scheme": s, "hbin": h, "events": 0, "n_sat_events": 0, "top1_share": np.nan, "top3": ""})
                continue
            sat, tt = F.sat[fl], F.t[fl]
            new = np.r_[True, (sat[1:] != sat[:-1]) | (np.diff(tt) > 48 * 3600)]
            ev = pd.Series(sat[new]).value_counts()
            conc.append({"scheme": s, "hbin": h, "events": int(ev.sum()), "n_sat_events": len(ev),
                         "top1_share": ev.iloc[0] / ev.sum(),
                         "top3": "; ".join(f"{P.object_name.get(k, k)} ({k}) ×{v}" for k, v in ev.head(3).items())})
    CC = pd.DataFrame(conc)
    _csv(CC.round(3), "paperC_thr_event_sats")
    res["event_concentration"] = CC[CC.scheme.isin(["C", "D"]) & (CC.events > 0)].round(3).to_dict(orient="records")
    print(json.dumps({k: v for k, v in res.items() if k not in ("bins", "event_concentration")}, ensure_ascii=False, indent=1))
    print(out.round(3).to_string(index=False))
    print(CC[CC.scheme.isin(["C", "D"]) & (CC.events > 0)].to_string(index=False))
    return res


def _recal_factor(T_all: pd.DataFrame, train_mask_fn) -> pd.Series:
    """以訓練期轉換重新校準逐星 B_eff（中位數，與 atmospheric_drag.drag_residual 同法），回傳 {norad: B_train/B_eff}。"""
    fac = {}
    for nid, g in T_all.groupby("norad_id"):
        m = (train_mask_fn(g) & (g.drag_pred_da < 0) & np.isfinite(g.da_km)).to_numpy()
        ratio = (g.da_km[m] * g.B_eff[m] / g.drag_pred_da[m])        # = −Δa / s
        ratio = ratio[ratio > 0]
        fac[nid] = float(ratio.median() / g.B_eff.iloc[0]) if len(ratio) else np.nan
    return pd.Series(fac)


def sec_oos():
    """任務 1：門檻方案之樣本外驗證（衛星分組 k-fold、時間切分）。"""
    T = load_transitions()
    F = FP(T)
    n = len(F.T)
    P = pd.read_csv(BM / f"perigee_drag_corr_persat{SUF}.csv").set_index("norad_id")
    sats = np.array(sorted(F.T.norad_id.unique()))
    sat_bin = P.bin.reindex(sats).to_numpy()
    tabs, thr_log = [], []
    R = int(os.environ.get("OOS_REPEATS", 20))
    R_INJ = int(os.environ.get("OOS_INJ_REPEATS", 5))

    def log_thr(label, rep, fold, sch):
        thr_log.append(pd.DataFrame({"eval": label, "rep": rep, "fold": fold, "hbin": sch["B"].index,
                                     "thrB": sch["B"].values, "thrD": sch["D"].values, "thrE": sch["E"].values,
                                     "sd_train": sch["sd_train"].values, "C_a": sch["C_ab"][0], "C_b": sch["C_ab"][1]}))

    def run_cv(k, label):
        rng_split = np.random.default_rng(SEED)
        rng_inj = np.random.default_rng(SEED + k)
        for rep in range(R):
            fold = {}
            for b in np.unique(sat_bin):                     # 依選星檔分層，檔內隨機分 k 組
                ids = rng_split.permutation(sats[sat_bin == b])
                off = rng_split.integers(k)
                for j, nid in enumerate(ids):
                    fold[nid] = (j + off) % k
            f_row = F.T.norad_id.map(fold).to_numpy()
            thr = {s: np.full(n, np.nan) for s in SCHEMES}
            for j in range(k):
                tr, te = f_row != j, f_row == j
                sch = fit_schemes(F, tr, n_min=3000 * tr.mean())
                for s in SCHEMES:
                    thr[s][te] = thr_rows(F, sch, s)[te]
                log_thr(label, rep, j, sch)
            allm = np.ones(n, bool)
            inj = _inject_all(F, allm, thr, rng_inj) if rep < R_INJ else None
            t_ = _bin_table(F, evaluate(F, allm, thr), inj, label)
            t_["rep"] = rep
            tabs.append(t_)
            print(f"  {label} rep {rep} 完成", flush=True)

    run_cv(5, "sat-5fold")
    run_cv(2, "sat-2fold")

    # 時間切分（兩個方向）× 殘差版本（B_eff 全期校準／以訓練期重新校準）
    Tall = load_transitions(all_dt=True)
    rng_inj = np.random.default_rng(SEED + 7)
    recal = {}
    for direction in ("early→late", "late→early"):
        tr = (F.T.epoch < SPLIT).to_numpy() if direction == "early→late" else (F.T.epoch >= SPLIT).to_numpy()
        te = ~tr
        fn = (lambda g: g.epoch < SPLIT) if direction == "early→late" else (lambda g: g.epoch >= SPLIT)
        fac = _recal_factor(Tall, fn)
        recal[direction] = dict(median=_r(np.nanmedian(fac), 4), p10=_r(np.nanpercentile(fac, 10), 4),
                                p90=_r(np.nanpercentile(fac, 90), 4), n=int(np.isfinite(fac).sum()))
        F.T["resid_recal"] = F.T.da_km - F.T.drag_pred_da * F.T.norad_id.map(fac).to_numpy()
        for col, lab in (("drag_resid_da", "orig"), ("resid_recal", "recal")):
            ok = np.isfinite(F.T[col].to_numpy())
            sch = fit_schemes(F, tr & ok, resid_col=col, n_min=3000 * tr.mean())
            thr = {s: thr_rows(F, sch, s) for s in SCHEMES}
            label = f"time {direction} ({'B_eff full' if lab == 'orig' else 'B_eff train'})"
            t_ = _bin_table(F, evaluate(F, te & ok, thr, resid_col=col),
                            _inject_all(F, te & ok, thr, rng_inj, resid_col=col), label)
            ev_tr = _bin_table(F, evaluate(F, tr & ok, thr, resid_col=col), None, label)
            t_ = t_.merge(ev_tr[["scheme", "hbin", "fp_per_ksd"]].rename(columns={"fp_per_ksd": "fp_train"}),
                          on=["scheme", "hbin"], how="left")
            t_["rep"] = 0
            tabs.append(t_)
            log_thr(label, 0, 0, sch)
            print(f"  {label} 完成", flush=True)

    Tb = pd.concat(tabs, ignore_index=True)
    TL = pd.concat(thr_log, ignore_index=True)
    agg = Tb.groupby(["eval", "scheme", "hbin"]).agg(
        fp_med=("fp_per_ksd", "median"), fp_p05=("fp_per_ksd", lambda s: s.quantile(0.05)),
        fp_p95=("fp_per_ksd", lambda s: s.quantile(0.95)), share_meet=("meets_target", "mean"),
        min90_med=("min90_km", "median"), sat_days=("sat_days", "median"), n_trans=("n_trans", "median"),
        fp_train=("fp_train", "median"), n_rep=("rep", "nunique")).reset_index()
    _csv(agg.round(4), "paperC_thr_oos_bins")
    thr_med = TL.groupby(["eval", "hbin"])[["thrB", "thrD", "thrE", "sd_train"]].median().reset_index()
    ca = TL.groupby("eval")[["C_a", "C_b"]].median().reset_index()
    thr_med = thr_med.merge(ca, on="eval")
    thr_med["thrC_center"] = np.maximum(10 ** (thr_med.C_a + thr_med.C_b * thr_med.hbin), 0.03)
    _csv(thr_med.round(4), "paperC_thr_oos_thresholds")
    agg = agg.merge(thr_med[["eval", "hbin", "sd_train"]], on=["eval", "hbin"], how="left")
    agg["evaluable"] = (agg.sd_train >= SD_MIN) & (agg.sat_days >= SD_MIN)
    _csv(agg.round(4), "paperC_thr_oos_bins")
    rows = []
    for (e, s), g in agg.groupby(["eval", "scheme"]):
        gb = g[g.hbin > 0].sort_values("hbin")
        ge = gb[gb.evaluable]
        allr = g[g.hbin == -1].iloc[0]
        rows.append({"eval": e, "scheme": s, "fp_all_med": allr.fp_med, "fp_all_p05": allr.fp_p05, "fp_all_p95": allr.fp_p95,
                     "share_rep_all_meet": allr.share_meet,
                     "n_bins_fail": int((gb.fp_med > FP_TARGET).sum()),
                     "bins_fail": "/".join(str(int(h)) for h in gb[gb.fp_med > FP_TARGET].hbin),
                     "fp_max_bin": gb.fp_med.max(),
                     "n_bins_evaluable": len(ge), "n_bins_fail_evaluable": int((ge.fp_med > FP_TARGET).sum()),
                     "bins_fail_evaluable": "/".join(str(int(h)) for h in ge[ge.fp_med > FP_TARGET].hbin),
                     "fp_max_bin_evaluable": ge.fp_med.max(),
                     "min90_700_1000": "/".join(f"{v:.2f}" if np.isfinite(v) else "—" for v in gb[gb.hbin >= 700].min90_med),
                     "min90_300_400": "/".join(f"{v:.2f}" if np.isfinite(v) else "—" for v in gb[gb.hbin <= 400].min90_med)})
    S = pd.DataFrame(rows)
    _csv(S.round(4), "paperC_thr_oos_summary")
    print(S.round(3).to_string(index=False))
    piv = agg[agg.hbin > 0].pivot_table(index="hbin", columns=["eval", "scheme"], values="fp_med")
    return dict(repeats=R, inj_repeats=R_INJ, split=str(SPLIT.date()), target=FP_TARGET, recal_B_factor=recal,
                summary=S.round(4).to_dict(orient="records"),
                fp_med_by_bin={f"{e}|{s}": {str(int(h)): _r(v, 3) for h, v in piv[(e, s)].items()} for e, s in piv.columns},
                min90_by_bin={f"{e}|{s}": {str(int(r.hbin)): _r(r.min90_med, 2) for r in g.itertuples()}
                              for (e, s), g in agg[agg.hbin > 0].groupby(["eval", "scheme"])})


# ════════════════════════════════════════════════════════════════════════════
# 既有數字之核對（§2.3、§3.1–3.4）
# ════════════════════════════════════════════════════════════════════════════
def sec_sample():
    import gzip
    sel = pd.read_csv(BM / f"perigee_bin_selection{SUF}.csv")
    P = pd.read_csv(BM / f"perigee_drag_corr_persat{SUF}.csv")
    ids, n_lines = set(), 0
    for f in sorted((BM / "perigee_backfill").glob("batch_*.tle.gz")):
        for ln in gzip.open(f, "rt", encoding="ascii"):
            if ln.startswith("1 "):
                ids.add(int(ln[2:7]))
                n_lines += 1
    need = (BM / "perigee_backfill" / "ids.txt")
    n_need = len(need.read_text().split()) if need.exists() else None
    per_bin = sel.groupby("bin").size()
    res = dict(n_selected=len(sel), n_bins=int(per_bin.size), per_bin={str(int(k)): int(v) for k, v in per_bin.items()},
               tol_km_counts={str(k): int(v) for k, v in sel.tol_km.value_counts().sort_index().items()},
               ecc_max=_r(sel.e.max(), 5), backfill_sats_in_files=len(ids), backfill_ids_txt=n_need, backfill_tle=n_lines,
               n_first_tle_2024_01=int((P.first_tle < "2024-02-01").sum()),
               alt_mean_range=[_r(P.alt_mean.min(), 1), _r(P.alt_mean.max(), 1)],
               n_passive=int(P.passive_all.sum()), n_raised=int((~P.passive_all).sum()),
               n_persat=len(P), max_family_per_bin=int(sel.assign(f=sel.object_name.str.split(r"[ \-]").str[0])
                                                       .groupby(["bin", "f"]).size().max()))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return res


def sec_decay():
    D = pd.read_csv(BM / "nrlmsis_decay_expect.csv", parse_dates=["date"])
    last7 = D[D.date >= D.date.max() - pd.Timedelta(days=6)]
    i81 = D.f107_81.idxmax()
    res = dict(period=[str(D.date.min().date()), str(D.date.max().date())],
               median_m_per_day={c.split("km")[0]: _r(D[c].median(), 3) for c in D.columns if c.endswith("m_per_day")},
               last7_window=[str(last7.date.min().date()), str(last7.date.max().date())],
               last7_400km_median=_r(last7["400km_m_per_day"].median(), 1), last7_400km_mean=_r(last7["400km_m_per_day"].mean(), 1),
               f107_81_last=_r(D.f107_81.iloc[-1], 1), f107_81_last7_mean=_r(last7.f107_81.mean(), 1),
               f107_81_median=_r(D.f107_81.median(), 1), f107_81_max=_r(D.f107_81.max(), 1), f107_81_max_date=str(D.date[i81].date()),
               orders_300_vs_1000=_r(np.log10(D["300km_m_per_day"].median() / D["1000km_m_per_day"].median()), 2))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return res


def sec_corr():
    G = pd.read_csv(BM / f"perigee_drag_corr_global{SUF}.csv", index_col=0)["value"]
    B = pd.read_csv(BM / f"perigee_drag_corr_bins{SUF}.csv")
    P = pd.read_csv(BM / f"perigee_drag_corr_persat{SUF}.csv")
    A = pd.read_csv(BM / f"perigee_drag_corr_windows{SUF}.csv.gz")
    pos = (A.obs_decay > 0) & (A.nrl_decay > 0)
    # 由逐窗與逐星檔重算（驗證 global CSV）
    rec = {"n_win": len(A), "n_win_pos": int(pos.sum()), "n_sat": int(A.norad_id.nunique()),
           "r_log": pearsonr(np.log10(A.obs_decay[pos]), np.log10(A.nrl_decay[pos]))[0],
           "rho_alt_obs": spearmanr(P.alt_mean, np.log10(P.obs_decay_med.clip(lower=1e-3)))[0],
           "rho_alt_nrl": spearmanr(P.alt_mean, np.log10(P.nrl_decay_med.clip(lower=1e-3)))[0],
           "r_persat_med_all": P.r_pearson.median(), "r_persat_med_passive": P[P.passive_all].r_pearson.median(),
           "r_persat_med_raised": P[~P.passive_all].r_pearson.median(),
           "share_r_gt05_passive": (P[P.passive_all].r_pearson > 0.5).mean(),
           "rho_alt_resrms": spearmanr(P.alt_mean, P.res_rms)[0], "rho_alt_resrel": spearmanr(P.alt_mean, P.res_rel)[0],
           "rho_nrl_absres": spearmanr(A.nrl_decay, A.res_rate.abs())[0],
           "n_passive": int(P.passive_all.sum()), "n_raised": int((~P.passive_all).sum())}
    rec = {k: _r(v, 4) for k, v in rec.items()}
    # 表 2 欄位定義核對：衰減率中位數＝該檔全部 7 日窗之中位數（非逐星中位數之中位數）
    pm = P.groupby("bin").agg(obs_persat_med=("obs_decay_med", "median"), nrl_persat_med=("nrl_decay_med", "median"))
    T2 = B[["bin", "n_sat", "n_passive", "obs_decay_med", "nrl_decay_med", "persat_r_median_passive", "res_rel_med"]].merge(
        pm, left_on="bin", right_index=True)
    passive_bins_300_850 = T2[T2.bin <= 850].persat_r_median_passive
    res = dict(global_csv={k: _r(v, 4) for k, v in G.items()}, recomputed=rec,
               table2=T2.round(4).to_dict(orient="records"),
               passive_r_min_300_850=_r(passive_bins_300_850.min(), 3),
               bin300_obs_med=_r(B.loc[B.bin == 300, "obs_decay_med"].iloc[0], 2),
               bin1000_obs_med=_r(B.loc[B.bin == 1000, "obs_decay_med"].iloc[0], 3))
    print(json.dumps({k: v for k, v in res.items() if k != "table2"}, ensure_ascii=False, indent=1))
    print(T2.round(3).to_string(index=False))
    return res


def _solar_load():
    A = pd.read_csv(BM / f"perigee_drag_corr_windows{SUF}.csv.gz", parse_dates=["w"])
    P = pd.read_csv(BM / f"perigee_drag_corr_persat{SUF}.csv")
    keep = P[P.passive_all & (P.first_tle < "2024-02-01")]
    A = A[A.norad_id.isin(keep.norad_id)].copy()
    norm = A.groupby("norad_id").nrl_decay.transform("median")
    A["obs_n"], A["nrl_n"] = A.obs_decay / norm, A.nrl_decay / norm
    return A, keep


def sec_solar():
    A, keep = _solar_load()
    rows, ext = [], {}
    for lab, lo, hi in BANDS:
        ids = keep[(keep.bin >= lo) & (keep.bin < hi)].norad_id
        g = A[A.norad_id.isin(ids)].groupby("w")
        S = pd.DataFrame({"obs": g.obs_n.median(), "nrl": g.nrl_n.median(), "n": g.size()})
        S = S[S.n >= max(2, len(ids) // 2)]
        rows.append({"band": lab, "n_sat": len(ids), "n_week": len(S), "r_series": pearsonr(S.obs, S.nrl)[0],
                     "r_log": pearsonr(np.log10(S.obs.clip(lower=1e-3)), np.log10(S.nrl))[0],
                     "persat_r_median": keep[keep.norad_id.isin(ids)].r_pearson.median()})
        idx = S.index.tz_localize(None) if S.index.tz is not None else S.index
        S.index = idx
        hi_ = S.loc["2024-08-01":"2024-12-31"]
        lo_ = S.loc["2025-05-01":"2025-09-30"]
        ext[lab] = dict(obs_max_2024H2=_r(hi_.obs.max(), 2), obs_max_week=str(hi_.obs.idxmax().date()),
                        nrl_max_2024H2=_r(hi_.nrl.max(), 2), obs_min_2025mid=_r(lo_.obs.min(), 2),
                        obs_min_week=str(lo_.obs.idxmin().date()), nrl_min_2025mid=_r(lo_.nrl.min(), 2),
                        obs_last=_r(S.obs.iloc[-1], 2), obs_first=_r(S.obs.iloc[0], 2))
    R = pd.DataFrame(rows)
    O = pd.read_csv(BM / f"nrlmsis_solar_tracking_bands{SUF}.csv")
    res = dict(n_sat_total=int(R.n_sat.sum()), bands=R.round(4).to_dict(orient="records"),
               matches_csv=bool(np.allclose(R[["r_series", "r_log", "persat_r_median"]].to_numpy(float),
                                            O[["r_band_median_series", "r_log", "persat_r_median"]].to_numpy(float), atol=6e-4)),
               extremes=ext)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return res


def _fs7_windows():
    W = pd.read_csv(BM / "fs7_precise_decay_windows.csv", parse_dates=["w"])
    sw = sw_daily()
    ctr = (W.w + pd.Timedelta(days=3)).dt.normalize()
    W["f107_81"] = sw.f107_81.reindex(ctr.to_numpy()).to_numpy()
    return W


def sec_fs7():
    W = _fs7_windows()
    C = pd.read_csv(BM / "fs7_precise_nrlmsis_corr.csv")
    rows = []
    for name, g in W.groupby("name"):
        b = g.dropna(subset=["tle"])
        rows.append({"sat": name, "n_win": len(g), "n_win_tle": len(b), "r_precise_nrl": pearsonr(g.decay, g.nrl)[0],
                     "rho_precise_nrl": spearmanr(g.decay, g.nrl)[0], "r_tle_nrl": pearsonr(b.tle, b.nrl)[0],
                     "r_tle_precise": pearsonr(b.tle, b.decay)[0],
                     "rms_precise_minus_nrl": np.sqrt(((g.decay - g.nrl) ** 2).mean()),
                     "rms_tle_minus_precise": np.sqrt(((b.tle - b.decay) ** 2).mean()), "decay_med": g.decay.median(),
                     "B": float(np.median(g.decay[g.decay > 0] / g["shape"][g.decay > 0])),
                     "alt_min": g.alt.min(), "alt_max": g.alt.max()})
    R = pd.DataFrame(rows)
    cols = ["r_precise_nrl", "rho_precise_nrl", "r_tle_nrl", "r_tle_precise", "rms_precise_minus_nrl", "rms_tle_minus_precise", "decay_med"]
    Cm = C.set_index("sat").loc[R.sat]
    match = {c: bool(np.allclose(R[c].to_numpy(float), Cm[c].to_numpy(float), atol=6e-4)) for c in cols}
    match["B"] = bool(np.allclose(R.B.to_numpy(), Cm.B_m2_per_kg.to_numpy(), atol=6e-5))
    res = dict(n_win_total=len(W), per_sat=R.round(4).to_dict(orient="records"), matches_corr_csv=match,
               ranges={c: [_r(R[c].min(), 4), _r(R[c].max(), 4)] for c in cols + ["B"]},
               alt_range=[_r(W.alt.min(), 1), _r(W.alt.max(), 1)],
               mean_of_persat={c: _r(R[c].mean(), 4) for c in ["r_precise_nrl", "r_tle_nrl", "r_tle_precise"]},
               last_window_by_sat={n: str(g.w.max().date()) for n, g in W.groupby("name")})
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return res


# ════════════════════════════════════════════════════════════════════════════
# 任務 2：福衛七號合併相關
# ════════════════════════════════════════════════════════════════════════════
def _boot_r_weeks(df, x, y, n_boot=5000, seed=SEED):
    """以「週」為群集重抽（同週五星一起抽），回傳 Pearson r 之 2.5／97.5 百分位。"""
    rng = np.random.default_rng(seed)
    wk = df.w.to_numpy()
    uw = np.unique(wk)
    groups = [np.flatnonzero(wk == u) for u in uw]
    X, Y = df[x].to_numpy(), df[y].to_numpy()
    rs = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(len(uw), size=len(uw))
        i = np.concatenate([groups[k] for k in pick])
        rs[b] = np.corrcoef(X[i], Y[i])[0, 1]
    return float(np.percentile(rs, 2.5)), float(np.percentile(rs, 97.5))


def sec_fs7pool():
    W = _fs7_windows()
    rows = []
    for lab, x, y, d in (("precise vs NRLMSIS", "decay", "nrl", W),
                         ("TLE vs NRLMSIS", "tle", "nrl", W.dropna(subset=["tle"])),
                         ("TLE vs precise", "tle", "decay", W.dropna(subset=["tle"]))):
        r = pearsonr(d[x], d[y])[0]
        f_lo, f_hi = fisher_ci(r, len(d))
        b_lo, b_hi = _boot_r_weeks(d, x, y)
        rows.append({"pair": lab, "n_win": len(d), "n_week": d.w.nunique(), "r_pooled": r, "fisher_lo": f_lo, "fisher_hi": f_hi,
                     "boot_week_lo": b_lo, "boot_week_hi": b_hi, "rho_pooled": spearmanr(d[x], d[y])[0]})
    R = pd.DataFrame(rows)
    _csv(R.round(4), "paperC_fs7_pooled")
    print(R.round(4).to_string(index=False))
    return dict(rows=R.round(4).to_dict(orient="records"),
                note="Fisher z 假設各窗獨立（偏窄）；週群集 bootstrap 以同一週之所有衛星一起重抽，5000 次")


# ════════════════════════════════════════════════════════════════════════════
# 任務 3：高活動期偏差
# ════════════════════════════════════════════════════════════════════════════
def _grp(f):
    for lab, lo, hi in F107_GROUPS:
        if lo <= f < hi:
            return lab
    return None


def _boot_median(v, clusters, n_boot=5000, seed=SEED, stat=np.median):
    rng = np.random.default_rng(seed)
    uc = np.unique(clusters)
    groups = [np.flatnonzero(clusters == u) for u in uc]
    out = np.empty(n_boot)
    for b in range(n_boot):
        i = np.concatenate([groups[k] for k in rng.integers(len(uc), size=len(uc))])
        out[b] = stat(v[i])
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def _persat_group_ratio(A, col_n="nrl_decay", col_o="obs_decay", min_win=5):
    """逐星於各 F10.7 組之 Σ預期／Σ實測（窗數 ≥ min_win 且 Σ實測 > 0）。"""
    g = A.groupby(["norad_id", "grp"]).agg(n=(col_o, "size"), so=(col_o, "sum"), sn=(col_n, "sum")).reset_index()
    g = g[(g.n >= min_win) & (g.so > 0)]
    g["ratio"] = g.sn / g.so
    return g


def sec_bias():
    rows = []
    # ── 福衛七號（精密軌道）：逐窗比值 NRLMSIS／精密
    W = _fs7_windows()
    W["grp"] = W.f107_81.map(_grp)
    W["ratio"] = W.nrl / W.decay
    for lab, _, _ in F107_GROUPS + [("all", 0, 0)]:
        d = W if lab == "all" else W[W.grp == lab]
        d = d[d.decay > 0]
        lo, hi = _boot_median(d.ratio.to_numpy(), d.w.to_numpy())
        ros = d.groupby("name").apply(lambda g: g.nrl.sum() / g.decay.sum())
        rows.append({"dataset": "FS7 precise (5 sats)", "band": "538–585 km", "f107_81_group": lab, "n_win": len(d),
                     "n_sat": d.name.nunique(), "n_week": d.w.nunique(), "ratio_median": d.ratio.median(), "ci_lo": lo, "ci_hi": hi,
                     "ci_method": "週群集 bootstrap（逐窗比值中位數）", "ratio_sum": d.nrl.sum() / d.decay.sum(),
                     "persat_sum_ratio_range": f"{ros.min():.3f}–{ros.max():.3f}",
                     "nrl_med_m_day": d.nrl.median(), "obs_med_m_day": d.decay.median(), "f107_81_med": d.f107_81.median()})
    # TLE 版（同窗，福衛七號 TLE）
    Wt = W.dropna(subset=["tle"])
    Wt = Wt[Wt.tle > 0]
    for lab, _, _ in F107_GROUPS:
        d = Wt[Wt.grp == lab]
        r_ = (d.nrl / d.tle).to_numpy()
        lo, hi = _boot_median(r_, d.w.to_numpy())
        rows.append({"dataset": "FS7 TLE (same windows)", "band": "538–585 km", "f107_81_group": lab, "n_win": len(d),
                     "n_sat": d.name.nunique(), "n_week": d.w.nunique(), "ratio_median": np.median(r_), "ci_lo": lo, "ci_hi": hi,
                     "ci_method": "週群集 bootstrap（逐窗比值中位數）", "ratio_sum": d.nrl.sum() / d.tle.sum(),
                     "nrl_med_m_day": d.nrl.median(), "obs_med_m_day": d.tle.median(), "f107_81_med": d.f107_81.median()})
    # 五星中位數週序列（取代「145 vs 120 m／日」之圖讀值）
    g = W.groupby("w")
    S = pd.DataFrame({"p": g.decay.median(), "nrl": g.nrl.median(), "n": g.size(), "f81": g.f107_81.first()})
    S = S[S.n >= 2]
    S.index = S.index.tz_localize(None) if S.index.tz is not None else S.index
    hiS = S.loc["2024-09-01":"2024-12-31"]
    wk_max = hiS.nrl.idxmax()
    fs7_hi = dict(period="2024-09-01–2024-12-31（五星中位數週序列，n ≥ 2）", n_week=len(hiS),
                  nrl_mean=_r(hiS.nrl.mean(), 1), precise_mean=_r(hiS.p.mean(), 1),
                  ratio_of_means=_r(hiS.nrl.mean() / hiS.p.mean(), 3),
                  nrl_max_week=str(wk_max.date()), nrl_at_max=_r(hiS.nrl.max(), 1), precise_at_max=_r(hiS.loc[wk_max, "p"], 1),
                  max_diff_week=str((hiS.nrl - hiS.p).idxmax().date()), max_diff_nrl=_r(hiS.loc[(hiS.nrl - hiS.p).idxmax(), "nrl"], 1),
                  max_diff_precise=_r(hiS.loc[(hiS.nrl - hiS.p).idxmax(), "p"], 1))
    lowS = S.loc["2025-07-01":]
    fs7_lo = dict(period="2025-07-01 以後", n_week=len(lowS), nrl_mean=_r(lowS.nrl.mean(), 1), precise_mean=_r(lowS.p.mean(), 1),
                  ratio_of_means=_r(lowS.nrl.mean() / lowS.p.mean(), 3))
    rho_f = spearmanr(W.f107_81, np.log(W.ratio.where(W.ratio > 0)), nan_policy="omit")[0]

    # ── 270 顆全期被動衛星：逐星各組 Σ預期／Σ實測，再取衛星中位數；bootstrap 以衛星重抽
    A, keep = _solar_load()
    sw = sw_daily()
    A["f107_81"] = sw.f107_81.reindex((A.w.dt.tz_localize(None) + pd.Timedelta(days=3)).dt.normalize().to_numpy()).to_numpy()
    A["grp"] = A.f107_81.map(_grp)
    bandof = {}
    for lab, lo, hi in BANDS:
        for nid in keep[(keep.bin >= lo) & (keep.bin < hi)].norad_id:
            bandof[nid] = lab
    A["band"] = A.norad_id.map(bandof)
    persat = _persat_group_ratio(A)
    persat["band"] = persat.norad_id.map(bandof)
    for band in [b[0] for b in BANDS] + ["all 270"]:
        for lab, _, _ in F107_GROUPS:
            d = persat[(persat.grp == lab) & ((persat.band == band) | (band == "all 270"))]
            if len(d) < 3:
                continue
            lo, hi = _boot_median(d.ratio.to_numpy(), d.norad_id.to_numpy())
            dw = A[(A.grp == lab) & ((A.band == band) | (band == "all 270"))]
            rows.append({"dataset": "270 passive (TLE)", "band": band, "f107_81_group": lab, "n_win": len(dw),
                         "n_sat": len(d), "n_week": dw.w.nunique(), "ratio_median": d.ratio.median(), "ci_lo": lo, "ci_hi": hi,
                         "ci_method": "衛星 bootstrap（逐星 Σ預期／Σ實測之中位數）", "ratio_sum": dw.nrl_decay.sum() / dw.obs_decay.sum(),
                         "nrl_med_m_day": dw.nrl_decay.median(), "obs_med_m_day": dw.obs_decay.median(),
                         "f107_81_med": dw.f107_81.median()})
    # 高／低活動比值之比（>160 ÷ <120）逐星計算後取中位數：直接量化「偏差是否隨活動上升」
    pv = persat.pivot_table(index="norad_id", columns="grp", values="ratio")
    hl = (pv[">160"] / pv["<120"]).dropna()
    hl_band = {}
    for band in [b[0] for b in BANDS]:
        v = hl[hl.index.map(bandof) == band]
        lo, hi = _boot_median(v.to_numpy(), v.index.to_numpy())
        hl_band[band] = dict(n_sat=len(v), median=_r(v.median(), 3), ci=[_r(lo, 3), _r(hi, 3)],
                             share_gt1=_r((v > 1).mean(), 3))
    lo, hi = _boot_median(hl.to_numpy(), hl.index.to_numpy())
    hl_band["all"] = dict(n_sat=len(hl), median=_r(hl.median(), 3), ci=[_r(lo, 3), _r(hi, 3)], share_gt1=_r((hl > 1).mean(), 3))
    fs = W[W.decay > 0].groupby("name").apply(lambda g: (g[g.grp == ">160"].nrl.sum() / g[g.grp == ">160"].decay.sum()) /
                                               (g[g.grp == "<120"].nrl.sum() / g[g.grp == "<120"].decay.sum()))
    R = pd.DataFrame(rows)
    _csv(R.round(4), "paperC_bias_by_f107")
    print(R.round(3).to_string(index=False))
    res = dict(groups=[g[0] for g in F107_GROUPS], rows=R.round(4).to_dict(orient="records"),
               fs7_weekly_high=fs7_hi, fs7_weekly_low=fs7_lo, fs7_spearman_f107_vs_logratio=_r(rho_f, 3),
               high_over_low_ratio_270=hl_band, fs7_high_over_low_persat={k: _r(v, 3) for k, v in fs.items()})
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, ensure_ascii=False, indent=1))
    return res


# ════════════════════════════════════════════════════════════════════════════
# 任務 4：F10.7 時間對齊敏感度
# ════════════════════════════════════════════════════════════════════════════
def _density_lag(epochs, alt_km, lat, lon, lag_days):
    """與 atmospheric_drag.density 相同，但 F10.7 日值取 epoch − lag_days 之值（81 日平均與 ap 不變）。"""
    import pymsis
    import atmospheric_drag as ad
    sw = ad.load_space_weather()
    epochs = pd.DatetimeIndex(pd.to_datetime(epochs, utc=True))
    dates = np.array([e.to_pydatetime().replace(tzinfo=None) for e in epochs])
    _, fa, a = ad._sw_arrays(epochs, sw)
    f, _, _ = ad._sw_arrays(epochs - pd.Timedelta(days=lag_days), sw)
    ap7 = ad._ap7_array(epochs, a)
    ap = ap7 if ap7 is not None else np.tile(a[:, None], (1, 7))
    r = pymsis.calculate(dates, np.asarray(lon, float), np.asarray(lat, float), np.asarray(alt_km, float), f, fa, ap,
                         version=ad.MSIS_VERSION, options=ad._storm_options() if (ad.STORM_AP_MODE and ap7 is not None) else None)
    return np.asarray(r)[..., 0].ravel()


def _fs7_shape(dates, alt_km, lag):
    """與 gen_fig_fs7_precise_nrlmsis.nrl_shape 相同之取樣，F10.7 落後 lag 日。"""
    LATS, LONS, HRS = np.arange(-24, 25, 8), np.array([0.0, 180.0]), np.arange(0, 24, 3)
    k = len(LATS) * len(LONS) * len(HRS)
    t = pd.DatetimeIndex([pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=int(h)) for d in dates for h in HRS for _ in LATS for _ in LONS])
    la = np.tile(np.repeat(LATS, len(LONS)), len(dates) * len(HRS)).astype(float)
    lo = np.tile(LONS, len(dates) * len(HRS) * len(LATS))
    rho = _density_lag(t, np.repeat(alt_km, k), la, lo, lag).reshape(len(dates), k).mean(1)
    a_m = (np.asarray(alt_km) + RE_KM) * 1e3
    return rho * np.sqrt(3.986004418e14 * a_m) * 86400.0


def _patch_orbit_avg(lag):
    """把 atmospheric_drag.orbit_avg_density_hourly 之 F10.7 落後日數改為 lag（原程式為 1 日）。"""
    import inspect
    import atmospheric_drag as ad
    if not hasattr(ad, "_orig_src_oadh"):
        ad._orig_src_oadh = inspect.getsource(ad.orbit_avg_density_hourly)
    old = "_sw_arrays(hs - pd.Timedelta(days=1), sw)"
    assert old in ad._orig_src_oadh
    src = ad._orig_src_oadh.replace(old, "_sw_arrays(hs - pd.Timedelta(days=_F107_LAG), sw)")
    exec(compile(src, "<patched orbit_avg_density_hourly>", "exec"), ad.__dict__)
    ad._F107_LAG = lag


def _lag_one(args):
    nid, lag = args
    out = WORK / "f107lag" / f"{nid}_lag{lag}.csv.gz"
    if out.exists():
        return nid, lag, "cached"
    os.chdir(ROOT)
    os.environ["TAG"] = "x30"
    import duckdb
    import atmospheric_drag as ad
    import analyze_perigee_drag_corr as apc
    _patch_orbit_avg(lag)
    sw = ad.load_space_weather()
    c = duckdb.connect(str(ROOT / "space_db.duckdb"), read_only=True)
    df = c.execute("select epoch_utc epoch, sma_km, eccentricity, line1, line2 from raw_tle_archive "
                   "where norad_id=? and epoch_utc>=? and epoch_utc<'2026-11-16' and sma_km is not null order by 1",
                   [int(nid), apc.T0]).df()
    c.close()
    df["epoch"] = pd.to_datetime(df.epoch, utc=True)
    df = pd.concat([apc.backfill_rows(nid), df], ignore_index=True)
    df["epoch"] = pd.to_datetime(df.epoch, utc=True)
    df = df.sort_values("epoch")
    df = df[df.epoch.diff().dt.total_seconds().fillna(1e9).abs() > 60]
    r = ad.drag_residual(df, sw)
    ep = pd.to_datetime(df.epoch, utc=True).sort_values()
    r["dt_d"] = ep.diff().dt.total_seconds().to_numpy()[1:] / 86400
    r["B_eff"] = r.attrs.get("B_eff")
    out.parent.mkdir(parents=True, exist_ok=True)
    r.to_csv(out, index=False, compression="gzip")
    return nid, lag, len(r)


def sec_f107lag():
    rows, summ = [], {}
    # ── (a) 福衛七號 616 窗：精密實測不變，NRLMSIS 形狀項以當日（原）與前一日 F10.7 重算
    W = _fs7_windows()
    sw = sw_daily()
    W["grp"] = W.f107_81.map(_grp)
    for lag in (0, 1):
        parts = []
        for name, g in W.groupby("name"):
            g = g.copy()
            g["shape_l"] = _fs7_shape((g.w.dt.tz_localize(None) + pd.Timedelta(days=3)).dt.date, g.alt.to_numpy(), lag)
            pos = g.decay > 0
            Bc = float(np.median(g.decay[pos] / g.shape_l[pos]))
            g["nrl_l"] = Bc * g.shape_l
            parts.append(g)
            rows.append({"dataset": "FS7 precise", "sat": name, "lag_days": lag, "n_win": len(g),
                         "r": pearsonr(g.decay, g.nrl_l)[0], "B": Bc,
                         "shape_maxreldiff_vs_csv": float(np.max(np.abs(g.shape_l / g["shape"] - 1))) if lag == 0 else np.nan})
        G = pd.concat(parts)
        G = G[G.decay > 0]
        rat = {lab: float(np.median(G[G.grp == lab].nrl_l / G[G.grp == lab].decay)) for lab, _, _ in F107_GROUPS}
        summ[f"fs7_lag{lag}"] = dict(r_pooled=_r(pearsonr(G.decay, G.nrl_l)[0], 4),
                                     r_persat=[_r(x["r"], 4) for x in rows if x["dataset"] == "FS7 precise" and x["lag_days"] == lag],
                                     ratio_median_by_group={k: _r(v, 4) for k, v in rat.items()},
                                     high_over_low=_r(rat[">160"] / rat["<120"], 4))
    # ── (b) 270 顆中每高度帶 10 顆（固定種子）：TLE 路徑重跑 drag_residual，F10.7 落後 0 日 vs 1 日（現行程式＝1 日）
    A, keep = _solar_load()
    rng = np.random.default_rng(SEED)
    pick = []
    for lab, lo, hi in BANDS:
        ids = sorted(keep[(keep.bin >= lo) & (keep.bin < hi)].norad_id)
        pick += [(lab, int(x)) for x in rng.choice(ids, size=min(10, len(ids)), replace=False)]
    from concurrent.futures import ProcessPoolExecutor
    jobs = [(nid, lag) for _, nid in pick for lag in (0, 1)]
    with ProcessPoolExecutor(max_workers=int(os.environ.get("NPROC", 8))) as ex:
        for nid, lag, st in ex.map(_lag_one, jobs):
            print(" ", nid, lag, st, flush=True)
    os.environ["TAG"] = "x30"
    import analyze_perigee_drag_corr as apc
    W81 = sw.f107_81
    per = []
    for band, nid in pick:
        res_l = {}
        for lag in (0, 1):
            r = pd.read_csv(WORK / "f107lag" / f"{nid}_lag{lag}.csv.gz")
            Wd = apc.windows(nid, r)
            Wd["f107_81"] = W81.reindex((pd.to_datetime(Wd.w).dt.tz_localize(None) + pd.Timedelta(days=3)).dt.normalize().to_numpy()).to_numpy()
            Wd["grp"] = Wd.f107_81.map(_grp)
            res_l[lag] = Wd
        m = res_l[0].merge(res_l[1], on="w", suffixes=("_0", "_1"))
        ok = (m.nrl_decay_0 > 0) & (m.nrl_decay_1 > 0)
        rec = {"band": band, "norad_id": nid, "n_win": int(ok.sum()),
               "r_lag0": pearsonr(m.obs_decay_0[ok], m.nrl_decay_0[ok])[0], "r_lag1": pearsonr(m.obs_decay_1[ok], m.nrl_decay_1[ok])[0],
               "B_ratio_lag0_over_lag1": float(pd.read_csv(WORK / "f107lag" / f"{nid}_lag0.csv.gz", usecols=["B_eff"]).B_eff.iloc[0] /
                                               pd.read_csv(WORK / "f107lag" / f"{nid}_lag1.csv.gz", usecols=["B_eff"]).B_eff.iloc[0]),
               "nrl_rel_change_med": float(np.median(m.nrl_decay_0[ok] / m.nrl_decay_1[ok] - 1)),
               "nrl_rel_change_p95abs": float(np.percentile(np.abs(m.nrl_decay_0[ok] / m.nrl_decay_1[ok] - 1), 95))}
        for lag in (0, 1):
            g = m[ok]
            for lab, _, _ in F107_GROUPS:
                gg = g[g[f"grp_{lag}"] == lab]
                rec[f"ratio_{lab}_lag{lag}"] = gg[f"nrl_decay_{lag}"].sum() / gg[f"obs_decay_{lag}"].sum() if len(gg) >= 5 and gg[f"obs_decay_{lag}"].sum() > 0 else np.nan
        # 與既有快取（現行 1 日落後）之一致性
        cw = A[A.norad_id == nid][["w", "nrl_decay"]].copy()
        cw["w"] = pd.to_datetime(cw.w, utc=True)
        r1 = res_l[1][["w", "nrl_decay"]].copy()
        r1["w"] = pd.to_datetime(r1.w, utc=True)
        mm = cw.merge(r1, on="w", suffixes=("_cache", "_re"))
        rec["cache_reldiff_med"] = float(np.median(np.abs(mm.nrl_decay_re / mm.nrl_decay_cache - 1))) if len(mm) else np.nan
        per.append(rec)
    Pq = pd.DataFrame(per)
    for lab, _, _ in F107_GROUPS:
        Pq[f"dratio_{lab}"] = Pq[f"ratio_{lab}_lag0"] - Pq[f"ratio_{lab}_lag1"]
    Pq["dr"] = Pq.r_lag0 - Pq.r_lag1
    Pq["hl_lag0"] = Pq["ratio_>160_lag0"] / Pq["ratio_<120_lag0"]
    Pq["hl_lag1"] = Pq["ratio_>160_lag1"] / Pq["ratio_<120_lag1"]
    by_band = Pq.groupby("band").agg(n=("norad_id", "size"), r_lag0_med=("r_lag0", "median"), r_lag1_med=("r_lag1", "median"),
                                     dr_med=("dr", "median"), dr_min=("dr", "min"), dr_max=("dr", "max"),
                                     hl_lag0_med=("hl_lag0", "median"), hl_lag1_med=("hl_lag1", "median"),
                                     nrl_rel_change_med=("nrl_rel_change_med", "median"))
    out = pd.concat([pd.DataFrame(rows), Pq.assign(dataset="TLE subset (10 per band)")], ignore_index=True)
    _csv(out.round(5), "paperC_f107lag")
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    print(by_band.round(4).to_string())
    res = dict(fs7=summ, tle_subset_by_band=by_band.round(4).reset_index().to_dict(orient="records"),
               tle_subset_all=dict(n=len(Pq), r_lag0_med=_r(Pq.r_lag0.median(), 4), r_lag1_med=_r(Pq.r_lag1.median(), 4),
                                   dr_med=_r(Pq.dr.median(), 4), dr_absmax=_r(Pq.dr.abs().max(), 4),
                                   hl_lag0_med=_r(Pq.hl_lag0.median(), 4), hl_lag1_med=_r(Pq.hl_lag1.median(), 4),
                                   cache_reldiff_med=_r(Pq.cache_reldiff_med.median(), 5)),
               picked=[nid for _, nid in pick],
               note="atmospheric_drag.orbit_avg_density_hourly（近圓軌道 TLE 路徑）原本即使用前一日 F10.7；"
                    "density()（福衛七號、圖 1、單點法）使用當日值。")
    print(json.dumps({k: v for k, v in res.items() if k != "picked"}, ensure_ascii=False, indent=1))
    return res


# ════════════════════════════════════════════════════════════════════════════
# 任務 5：FORMOSAT7-3（L78／NORAD 44343）
# ════════════════════════════════════════════════════════════════════════════
def _l78_day(tar):
    """只解析 tar 內 L78（序號 003）之弧段 → 與 gen_fig_fs7_precise_nrlmsis.day_mean 相同之日中位半長軸。"""
    out = WORK / "fs73_daily" / Path(tar).name.replace(".tar.gz", ".csv")
    if out.exists():
        return
    import tarfile
    sys.path.insert(0, str(ROOT))
    from sp3_core import parse_sp3_lines
    from formosat7_leoorb.archive import parse_arc_filename
    from formosat7_leoorb.detect import build_series
    frames = []
    try:
        with tarfile.open(tar) as tf:
            for m in tf.getmembers():
                meta = parse_arc_filename(m.name)
                if not m.isfile() or meta is None or meta["sat_index"] != "003":
                    continue
                df = parse_sp3_lines(tf.extractfile(m).read().decode("ascii", "replace").splitlines())
                if df.empty:
                    continue
                df["arc_id"] = meta["arc_id"]
                frames.append(df)
    except Exception as e:                                   # 壞檔略過
        print("skip", tar, e)
    rows = []
    if frames:
        ser = build_series(pd.concat(frames, ignore_index=True))
        for sat, s in ser.items():
            a = s.a_km
            per = int(round(2 * np.pi * np.sqrt(a.median() ** 3 / 398600.4418) / 60))
            sm = a.rolling(per, center=True, min_periods=int(per * 0.9)).mean().dropna()
            for d, g in sm.groupby(sm.index.floor("D")):
                if len(g) >= 18 * 60:
                    rows.append({"date": d.date(), "sp3_sat": sat, "a_km": g.median(), "n_min": len(g), "n_arcs": len(frames)})
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["date", "sp3_sat", "a_km", "n_min", "n_arcs"]).to_csv(out, index=False)


def sec_fs73():
    import tarfile
    from concurrent.futures import ProcessPoolExecutor
    os.chdir(ROOT)
    import gen_fig_fs7_precise_nrlmsis as g7
    LEO = ROOT / "data" / "formosat7_leoorb"
    tars = sorted(LEO.glob("leoOrb_*.tar.gz"))
    # 1) 可得性：每日 tar 內 L78 弧段數（快取）
    avf = WORK / "fs73_availability.csv"
    if avf.exists():
        AV = pd.read_csv(avf, parse_dates=["date"])
    else:
        recs = []
        for t in tars:
            y, d = t.name[7:11], t.name[12:15]
            with tarfile.open(t) as tf:
                n = sum(1 for m in tf.getnames() if Path(m).name.split(".")[2:3] == ["003"])   # leoOrb_YYYY.DDD.sss.aa_…：以 "." 分割之第 3 段為衛星序號
            recs.append({"date": pd.Timestamp(f"{y}-01-01") + pd.Timedelta(days=int(d) - 1), "n_arcs_L78": n})
        AV = pd.DataFrame(recs)
        WORK.mkdir(exist_ok=True)
        AV.to_csv(avf, index=False)
    have = AV[AV.n_arcs_L78 > 0]
    # 2) TLE 機動史
    import duckdb
    c = duckdb.connect(str(ROOT / "space_db.duckdb"), read_only=True)
    t = c.execute("select epoch_utc e, sma_km a from raw_tle_archive where norad_id=44343 and epoch_utc>='2024-01-01' "
                  "and epoch_utc<'2026-11-18' order by 1").df()
    c.close()
    t["e"] = pd.to_datetime(t.e)
    t["da_m"] = t.a.diff() * 1000
    raises = t[t.da_m > 200]
    last_raise = raises.e.max()
    free_start = (last_raise + pd.Timedelta(days=3)).normalize()
    # 3) 精密軌道日序列（只 L78 弧段）
    todo = [str(x) for x in tars if (AV.set_index("date").n_arcs_L78.get(
        pd.Timestamp(f"{x.name[7:11]}-01-01") + pd.Timedelta(days=int(x.name[12:15]) - 1), 0) > 0)]
    with ProcessPoolExecutor(max_workers=int(os.environ.get("NPROC", 8))) as ex:
        list(ex.map(_l78_day, todo, chunksize=4))
    files = [f for f in (WORK / "fs73_daily").glob("*.csv") if f.stat().st_size > 40]
    daily = pd.concat([pd.read_csv(f, parse_dates=["date"]) for f in files]).groupby("date").a_km.median().sort_index()
    D = daily.to_frame()
    Wp = g7.windows_from_daily(D)
    Wp["shape"] = g7.nrl_shape(Wp.w.dt.date + pd.Timedelta(days=3), Wp.alt.to_numpy())
    pos = Wp.decay > 0
    Bp = float(np.median(Wp.decay[pos] / Wp["shape"][pos]))
    Wp["nrl"] = Bp * Wp["shape"]
    Tt = g7.windows_from_daily(g7.tle_daily(44343))
    Wp = Wp.merge(Tt[["w", "decay"]].rename(columns={"decay": "tle"}), on="w", how="left")
    Wp["segment"] = np.where(Wp.w >= free_start, "free decay", "pre-2025-05 (maneuver windows excluded)")
    both = Wp.dropna(subset=["tle"])
    sw = sw_daily()
    Wp["f107_81"] = sw.f107_81.reindex((Wp.w + pd.Timedelta(days=3)).dt.normalize().to_numpy()).to_numpy()
    Wp["grp"] = Wp.f107_81.map(_grp)
    # 4) TLE 自由衰減段（leoOrb 已停止）：TLE 7 日窗 vs NRLMSIS（以 TLE 日均高度計算，B 於本段校準）
    Tf = Tt[Tt.w >= free_start].copy().reset_index(drop=True)
    Tf["shape"] = g7.nrl_shape(Tf.w.dt.date + pd.Timedelta(days=3), Tf.alt.to_numpy())
    pos = Tf.decay > 0
    Bt = float(np.median(Tf.decay[pos] / Tf["shape"][pos]))
    Tf["nrl"] = Bt * Tf["shape"]
    Tf["f107_81"] = sw.f107_81.reindex((Tf.w + pd.Timedelta(days=3)).dt.normalize().to_numpy()).to_numpy()
    Tf["grp"] = Tf.f107_81.map(_grp)
    # 對照：其他五星於同一期間之 TLE 窗（與既有 fs7_precise_decay_windows 同 B）
    W5 = _fs7_windows()
    W5f = W5[(W5.w >= free_start)].dropna(subset=["tle"])
    out = pd.concat([Wp.assign(source="leoOrb precise"), Tf.rename(columns={"decay": "tle_decay"}).assign(source="TLE free decay")],
                    ignore_index=True)
    _csv(out.round(5), "paperC_fs73")
    rat_t = {lab: _r(np.median((g.nrl / g.tle_decay if "tle_decay" in g else g.nrl / g.decay)), 4)
             for lab, g in Tf.rename(columns={"decay": "tle_decay"}).groupby("grp")}
    res = dict(
        leoorb_days_with_L78=int(len(have)), leoorb_first=str(have.date.min().date()), leoorb_last=str(have.date.max().date()),
        leoorb_days_2025_with_L78=int((have.date >= "2025-01-01").sum()),
        leoorb_gap_2025=dict(n_days_missing_2025_01_to_05_27=int(((AV.date >= "2025-01-01") & (AV.date <= "2025-05-27") & (AV.n_arcs_L78 == 0)).sum())),
        tle_raises=[dict(epoch=str(r.e), da_m=_r(r.da_m, 0)) for r in raises.itertuples()],
        last_raise=str(last_raise), free_decay_start=str(free_start.date()),
        precise_daily_days=int(len(D)), precise_last_day=str(D.index.max().date()),
        precise_windows=int(len(Wp)), precise_windows_free=int((Wp.segment == "free decay").sum()),
        precise_B=_r(Bp, 5), r_precise_nrl=_r(pearsonr(Wp.decay, Wp.nrl)[0], 4) if len(Wp) > 3 else None,
        r_tle_precise=_r(pearsonr(both.tle, both.decay)[0], 4) if len(both) > 3 else None,
        r_tle_nrl_precisewin=_r(pearsonr(both.tle, both.nrl)[0], 4) if len(both) > 3 else None,
        rms_tle_minus_precise=_r(np.sqrt(((both.tle - both.decay) ** 2).mean()), 2) if len(both) else None,
        rms_precise_minus_nrl=_r(np.sqrt(((Wp.decay - Wp.nrl) ** 2).mean()), 2),
        precise_alt_range=[_r(Wp.alt.min(), 1), _r(Wp.alt.max(), 1)],
        precise_ratio_median_by_group={k: _r(np.median(g.nrl / g.decay), 4) for k, g in Wp[Wp.decay > 0].groupby("grp")},
        precise_n_by_group={k: int(len(g)) for k, g in Wp.groupby("grp")},
        tle_free=dict(n_win=len(Tf), period=[str(Tf.w.min().date()), str(Tf.w.max().date())], B=_r(Bt, 5),
                      r_tle_nrl=_r(pearsonr(Tf.decay, Tf.nrl)[0], 4), rho=_r(spearmanr(Tf.decay, Tf.nrl)[0], 4),
                      rms_tle_minus_nrl=_r(np.sqrt(((Tf.decay - Tf.nrl) ** 2).mean()), 2),
                      decay_med=_r(Tf.decay.median(), 2), alt_range=[_r(Tf.alt.min(), 1), _r(Tf.alt.max(), 1)],
                      ratio_median_by_group=rat_t, n_by_group={k: int(len(g)) for k, g in Tf.groupby("grp")}),
        other5_tle_same_period=dict(n_win=len(W5f), r_tle_nrl=_r(pearsonr(W5f.tle, W5f.nrl)[0], 4) if len(W5f) > 3 else None,
                                    r_persat={n: _r(pearsonr(g.tle, g.nrl)[0], 4) for n, g in W5f.groupby("name") if len(g) > 3}))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return res


SECTIONS = dict(sample=sec_sample, decay=sec_decay, corr=sec_corr, solar=sec_solar, fs7=sec_fs7, thr=sec_thr, oos=sec_oos,
                fs7pool=sec_fs7pool, bias=sec_bias, f107lag=sec_f107lag, fs73=sec_fs73)


def main():
    want = [a for a in sys.argv[1:] if a in SECTIONS] or list(SECTIONS)
    res = json.loads(OUT_JSON.read_text(encoding="utf-8")) if OUT_JSON.exists() else {}
    for k in want:
        print(f"\n════ {k} ════", flush=True)
        t0 = dt.datetime.now()
        res[k] = SECTIONS[k]()
        res.setdefault("_meta", {})[k] = dict(run_at=dt.datetime.now().isoformat(timespec="seconds"),
                                              seconds=round((dt.datetime.now() - t0).total_seconds(), 1))
        OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\n→ {OUT_JSON}")


if __name__ == "__main__":
    main()
