#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paperA_numbers.py — 期刊論文 A（docs/paper_tle_sma_noise_floor.md）數字重現程式。

逐節重算論文中所有可重現之數字，輸出 data/benchmark/paperA_numbers.json（分節合併寫入），
並另存明細 CSV（不覆寫任何既有結果檔）：
  data/benchmark/paperA_ids_sigma_recalc_20261118.csv     表 1 重算
  data/benchmark/paperA_sensitivity_20261118.csv          §2.2 敏感度（3×3×3 全格點）
  data/benchmark/paperA_fs_events_20261118.csv            福衛五號／七號 >50 m 事件
  data/benchmark/paperA_jason3_det_recalc_20261118.csv    §3.1 Jason-3 逐事件重算
  data/benchmark/paperA_dv_recalc_20261118.csv            §5.5 ΔV 逐事件重算

用法（Windows ARM64 / Python 3.13；資料庫一律 read_only）：
  set PYTHONIOENCODING=utf-8
  python docs/paperA_numbers.py                 # 全部（約 1–2 分鐘）
  python docs/paperA_numbers.py ids sens        # 只跑指定子命令
子命令：ids（表 1）、sens（§2.2 敏感度）、det（§3.1）、dv（§5.5）、fs（§5.1–5.3 福衛）、
        starlink（§3.2 MEME 真值與檢核一／二、自我差分）、fit（§3.2 擬合／NRLMSIS 標高／外推）

固定期間（寫死以利重現；資料庫為滾動視窗，日後重跑之 DB 依賴數字可能漂移）：
  福衛五號／七號「近一年」：epoch ∈ [2025-11-17 00:00, 2026-11-18 00:00) UTC（截至 2026-11-17 之一年）
  福衛三號「近 30 天」：     epoch ∈ [2026-10-18 00:00, 2026-11-18 00:00) UTC
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ids_truth_set"))
sys.path.insert(0, str(ROOT / "docs"))

DB = ROOT / "space_db.duckdb"
BENCH = ROOT / "data" / "benchmark"
OUT_JSON = BENCH / "paperA_numbers.json"
TAG = "20261118"
RE = 6378.137
MU = 398600.4418

FS_YEAR = ("2025-11-17", "2026-11-18")
FS3_30D = ("2026-10-18", "2026-11-18")


def _con():
    return duckdb.connect(str(DB), read_only=True)


def _r(x, n=3):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return None
    return round(float(x), n)


def thin(t, a, gap_h):
    """與 ids_sigma_calibrate.load_tle 相同之去重／稀釋：保留相鄰間隔 ≥ gap_h 之點。"""
    if len(t) == 0:
        return t, a
    keep = [0]
    g = gap_h * 3600.0
    for i in range(1, len(t)):
        if (t[i] - t[keep[-1]]) >= g:
            keep.append(i)
    return t[keep], a[keep]


def load_raw(nid, t0=None, t1=None, con=None):
    own = con is None
    con = con or _con()
    q = ("SELECT epoch_utc, sma_km FROM raw_tle_archive WHERE norad_id=? AND sma_km IS NOT NULL")
    args = [int(nid)]
    if t0:
        q += " AND epoch_utc>=?"; args.append(t0)
    if t1:
        q += " AND epoch_utc<?"; args.append(t1)
    rows = con.execute(q + " ORDER BY epoch_utc", args).fetchall()
    if own:
        con.close()
    # 與 ids_* 腳本一致：naive datetime 之 .timestamp()（本機時區）；認證安靜期亦以同法轉換，
    # 故相對對齊不變。轉回字串時以 fromtimestamp()（本機）逆轉，即得原 UTC 時刻。
    t = np.array([r[0].timestamp() for r in rows])
    a = np.array([float(r[1]) for r in rows])
    return t, a


# ═══════════════════════════════════════════════════════════════════════════════
# §2.2 估計量（參數化版之 ids_sigma_calibrate.robust_sigma）
# ═══════════════════════════════════════════════════════════════════════════════
def sigma_quiet(t_raw, a_raw, quiets, gap_h=3.0, buffer_d=0.75, deg_off=0,
                min_pts=12, min_span_d=3.0):
    """回傳 dict（σ_res、σ_diff 單位 m）。gap_h／buffer_d／deg_off=0 時與原程式相同。
    deg_off：多項式階數規則（<10 d:1、<40 d:2、否則 3）整體 ±1；下限 1（與原程式 max(deg,1) 一致）。"""
    t, a = thin(t_raw, a_raw, gap_h)
    diffs, resids, npts, nint = [], [], 0, 0
    for (s, e) in quiets:
        s += buffer_d * 86400; e -= buffer_d * 86400
        if e <= s:
            continue
        m = (t >= s) & (t <= e)
        if m.sum() < min_pts:
            continue
        tt, aa = t[m], a[m]
        span = (tt[-1] - tt[0]) / 86400.0
        if span < min_span_d:
            continue
        nint += 1; npts += len(aa)
        deg = (1 if span < 10 else (2 if span < 40 else 3)) + deg_off
        deg = min(deg, len(aa) - 2)
        x = (tt - tt[0]) / 86400.0
        c = np.polyfit(x, aa, max(deg, 1))
        resids.extend((aa - np.polyval(c, x)).tolist())
        diffs.extend(np.diff(aa).tolist())
    if nint == 0:
        return None
    return dict(n_int=nint, n_pts=npts,
                sigma_res_m=1.4826 * float(np.median(np.abs(resids))) * 1000.0,
                sigma_diff_m=1.4826 * float(np.median(np.abs(diffs))) / math.sqrt(2.0) * 1000.0,
                alt_km=float(np.median(a)) - RE)


def _ids_inputs():
    import ids_sigma_calibrate as isc
    con = _con()
    data = {}
    for nid, name in isc.TARGETS:
        t, a = load_raw(nid, con=con)
        data[nid] = (name, t, a, isc.load_quiet(isc.NORAD2IDS[nid]))
    con.close()
    return data


# 論文表 1 原值（m／km）
PAPER_T1 = {
    "Sentinel-3A": (803, 137, 11821, 0.2, 0.2), "Jason-3": (1338, 58, 7876, 0.3, 0.1),
    "SWOT": (893, 47, 2642, 0.3, 0.3), "Sentinel-3B": (803, 113, 5313, 0.4, 0.3),
    "Jason-2": (1311, 54, 5688, 0.4, 0.1), "Sentinel-6A": (1338, 22, 3786, 0.4, 0.1),
    "HY-2D": (952, 44, 5323, 0.7, 0.2), "HY-2C": (952, 46, 6249, 0.8, 0.2),
    "Jason-1": (1325, 67, 4451, 0.8, 0.2), "CryoSat-2": (719, 200, 9851, 1.0, 0.3),
    "SARAL": (785, 47, 8994, 1.5, 0.2), "Envisat": (766, 140, 9431, 1.5, 0.5),
    "HY-2A": (968, 56, 8449, 2.1, 1.2),
}

PAPER_T1_RATIO = {"Sentinel-3A": 0.005, "Jason-3": 0.006, "SWOT": 0.006, "Sentinel-3B": 0.007,
                  "Jason-2": 0.008, "Sentinel-6A": 0.009, "HY-2D": 0.014, "HY-2C": 0.015,
                  "Jason-1": 0.015, "CryoSat-2": 0.019, "SARAL": 0.029, "Envisat": 0.029, "HY-2A": 0.042}


def sec_ids():
    data = _ids_inputs()
    calib = pd.read_csv(ROOT / "ids_truth_set" / "ids_sigma_calibration.csv")
    rows = []
    for nid, (name, t, a, q) in data.items():
        r = sigma_quiet(t, a, q)
        c = calib[calib["norad"] == nid].iloc[0]
        p = PAPER_T1[name]
        rows.append(dict(
            name=name, norad=nid, alt_km=r["alt_km"], n_int=r["n_int"], n_pts=r["n_pts"],
            sigma_res_m=r["sigma_res_m"], sigma_diff_m=r["sigma_diff_m"],
            csv_sigma_res_m=c["sigma_resid_km"] * 1000, csv_sigma_diff_m=c["sigma_diff_km"] * 1000,
            csv_n_int=int(c["n_int"]), csv_n_pts=int(c["n_pts"]), csv_alt_km=c["alt_km"],
            paper_alt_km=p[0], paper_n_int=p[1], paper_n_pts=p[2],
            paper_sigma_res_m=p[3], paper_sigma_diff_m=p[4],
            ratio_res_to_50m=r["sigma_res_m"] / 50.0))
    D = pd.DataFrame(rows).sort_values("sigma_diff_m")
    D.to_csv(BENCH / f"paperA_ids_sigma_recalc_{TAG}.csv", index=False, encoding="utf-8-sig")
    out = dict(
        note="ids_sigma_calibrate.py 之估計量（3 h 稀釋、內縮 0.75 d、≥12 點、≥3 d、多項式 1/2/3 階）以現行 DB 重跑",
        per_sat={r["name"]: {k: (_r(v, 4) if isinstance(v, float) else v) for k, v in r.items()}
                 for r in D.to_dict("records")},
        median_sigma_diff_m=_r(D["sigma_diff_m"].median(), 3),
        median_sigma_res_m=_r(D["sigma_res_m"].median(), 3),
        csv_median_sigma_diff_m=_r(D["csv_sigma_diff_m"].median(), 3),
        alt_range_km=[_r(D["alt_km"].min(), 1), _r(D["alt_km"].max(), 1)],
        n_int_range=[int(D["n_int"].min()), int(D["n_int"].max())],
        sigma_diff_range_m=[_r(D["sigma_diff_m"].min(), 3), _r(D["sigma_diff_m"].max(), 3)],
        max_abs_diff_vs_csv_m=dict(
            sigma_res=_r((D["sigma_res_m"] - D["csv_sigma_res_m"]).abs().max(), 5),
            sigma_diff=_r((D["sigma_diff_m"] - D["csv_sigma_diff_m"]).abs().max(), 5)),
        all_counts_equal_csv=bool(((D["n_int"] == D["csv_n_int"]) & (D["n_pts"] == D["csv_n_pts"])).all()),
        csv_rounded_equal_paper=dict(
            sigma_res=bool(((D["csv_sigma_res_m"] + 1e-9).round(1) == D["paper_sigma_res_m"]).all()),
            sigma_diff=bool(((D["csv_sigma_diff_m"] + 1e-9).round(1) == D["paper_sigma_diff_m"]).all()),
            alt=bool((D["csv_alt_km"].round(0) == D["paper_alt_km"]).all()),
            n_int=bool((D["csv_n_int"] == D["paper_n_int"]).all()),
            n_pts=bool((D["csv_n_pts"] == D["paper_n_pts"]).all()),
            ratio=bool(((D["csv_sigma_res_m"] / 50).round(3) == pd.Series(
                [PAPER_T1_RATIO[n] for n in D["name"]], index=D.index)).all())),
        csv_median_sigma_res_m=_r(D["csv_sigma_res_m"].median(), 3),
        rounded_1dp_equal_paper=dict(
            sigma_res=bool((D["sigma_res_m"].round(1) == D["paper_sigma_res_m"]).all()),
            sigma_diff=bool((D["sigma_diff_m"].round(1) == D["paper_sigma_diff_m"]).all()),
            alt=bool((D["alt_km"].round(0) == D["paper_alt_km"]).all())),
    )
    print(D[["name", "alt_km", "n_int", "n_pts", "sigma_res_m", "sigma_diff_m",
             "paper_sigma_res_m", "paper_sigma_diff_m"]].round(3).to_string(index=False))
    print("13 顆 σ_diff 中位 =", out["median_sigma_diff_m"], "m")
    return out


def sec_sens():
    from scipy.stats import spearmanr
    data = _ids_inputs()
    gaps, bufs, degs = (1.5, 3.0, 6.0), (0.5, 0.75, 1.0), (-1, 0, 1)
    rows = []
    for g in gaps:
        for b in bufs:
            for k in degs:
                for nid, (name, t, a, q) in data.items():
                    r = sigma_quiet(t, a, q, gap_h=g, buffer_d=b, deg_off=k)
                    rows.append(dict(gap_h=g, buffer_d=b, deg_off=k, name=name, norad=nid,
                                     alt_km=r["alt_km"], n_int=r["n_int"], n_pts=r["n_pts"],
                                     sigma_res_m=r["sigma_res_m"], sigma_diff_m=r["sigma_diff_m"]))
    S = pd.DataFrame(rows)
    S.to_csv(BENCH / f"paperA_sensitivity_{TAG}.csv", index=False, encoding="utf-8-sig")
    base = S[(S.gap_h == 3.0) & (S.buffer_d == 0.75) & (S.deg_off == 0)].set_index("name")

    def summ(sub):
        sub = sub.set_index("name")
        rr = sub["sigma_res_m"] / base["sigma_res_m"]
        rd = sub["sigma_diff_m"] / base["sigma_diff_m"]
        rho_d = spearmanr(sub["alt_km"], sub["sigma_diff_m"])[0]
        return dict(
            median_sigma_res_m=_r(sub["sigma_res_m"].median()),
            median_sigma_diff_m=_r(sub["sigma_diff_m"].median()),
            max_sigma_res_m=_r(sub["sigma_res_m"].max()), max_sigma_diff_m=_r(sub["sigma_diff_m"].max()),
            n_sat_sigma_diff_lt_1m=int((sub["sigma_diff_m"] < 1).sum()),
            ratio_res_vs_base=[_r(rr.min()), _r(rr.max())],
            ratio_diff_vs_base=[_r(rd.min()), _r(rd.max())],
            spearman_alt_sigma_diff=_r(rho_d),
            per_sat={n: [_r(sub.loc[n, "sigma_res_m"]), _r(sub.loc[n, "sigma_diff_m"])] for n in sub.index})

    oat = {}
    for lab, (g, b, k) in {
        "baseline(3h,0.75d,±0)": (3.0, 0.75, 0),
        "gap=1.5h": (1.5, 0.75, 0), "gap=6h": (6.0, 0.75, 0),
        "buffer=0.5d": (3.0, 0.5, 0), "buffer=1.0d": (3.0, 1.0, 0),
        "deg-1": (3.0, 0.75, -1), "deg+1": (3.0, 0.75, 1),
    }.items():
        oat[lab] = summ(S[(S.gap_h == g) & (S.buffer_d == b) & (S.deg_off == k)])
    grid = []
    for (g, b, k), sub in S.groupby(["gap_h", "buffer_d", "deg_off"]):
        s = summ(sub); s.pop("per_sat")
        grid.append(dict(gap_h=g, buffer_d=b, deg_off=int(k), **s))
    G = pd.DataFrame(grid)
    out = dict(
        note="ids_sigma_calibrate 流程之 3×3×3 全格點：稀釋 1.5/3/6 h × 內縮 0.5/0.75/1.0 d × 階數規則 −1/0/+1（下限 1 階）",
        one_at_a_time=oat,
        grid_summary=dict(
            median_sigma_diff_m_range=[_r(G.median_sigma_diff_m.min()), _r(G.median_sigma_diff_m.max())],
            median_sigma_res_m_range=[_r(G.median_sigma_res_m.min()), _r(G.median_sigma_res_m.max())],
            max_sigma_diff_m_over_grid=_r(G.max_sigma_diff_m.max()),
            max_sigma_res_m_over_grid=_r(G.max_sigma_res_m.max()),
            min_n_sat_sigma_diff_lt_1m=int(G.n_sat_sigma_diff_lt_1m.min()),
            ratio_diff_vs_base_range=[_r(min(x[0] for x in G.ratio_diff_vs_base)),
                                      _r(max(x[1] for x in G.ratio_diff_vs_base))],
            ratio_res_vs_base_range=[_r(min(x[0] for x in G.ratio_res_vs_base)),
                                     _r(max(x[1] for x in G.ratio_res_vs_base))],
            spearman_alt_sigma_diff_range=[_r(G.spearman_alt_sigma_diff.min()),
                                           _r(G.spearman_alt_sigma_diff.max())]),
        grid=G.to_dict("records"))
    for k, v in oat.items():
        print(f"{k:24s} 中位 σ_res={v['median_sigma_res_m']:.3f} σ_diff={v['median_sigma_diff_m']:.3f}"
              f"  最大 σ_diff={v['max_sigma_diff_m']:.3f}  σ_res 比值 {v['ratio_res_vs_base']}"
              f"  σ_diff 比值 {v['ratio_diff_vs_base']}")
    print("全格點：", out["grid_summary"])
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# §3.1 Jason-3 偵測曲線
# ═══════════════════════════════════════════════════════════════════════════════
def _det_csv_stats(old, sig_res):
    nz = old[old["da_true_m"] > 0]
    ms = old[old["detected"] == 0]
    return dict(file="ids_truth_set/ids_detection_curve_jason3.csv（2026-08-11 凍結）",
                n=int(len(old)), n_detected=int(old["detected"].sum()), p_det=_r(old["detected"].mean(), 4),
                r=_r(np.corrcoef(old["da_true_m"], old["da_obs_m"])[0, 1]),
                missed_da_true_m=[_r(x, 2) for x in ms["da_true_m"]],
                n_true_zero=int((old["da_true_m"] == 0).sum()),
                da_true_nonzero_range_m=[_r(nz["da_true_m"].min(), 2), _r(nz["da_true_m"].max(), 1)],
                da_over_sigma_nonzero_range=[_r(nz["da_true_m"].min() / (sig_res * 1000), 1),
                                             _r(nz["da_true_m"].max() / (sig_res * 1000), 0)],
                da_obs_max_m=_r(old["da_obs_m"].max(), 0))


def sec_det():
    import ids_detection_curve as idc
    df = pd.read_csv(idc.TRUTH)
    j = df[df["norad"] == idc.NORAD_J3].drop_duplicates(
        subset=["win_start_tai", "win_end_tai"]).reset_index(drop=True)
    calib = pd.read_csv(idc.CALIB)
    c = calib[calib["norad"] == idc.NORAD_J3].iloc[0]
    sig_res, sig_diff = float(c["sigma_resid_km"]), float(c["sigma_diff_km"])
    t, a = idc.load_tle(idc.NORAD_J3)
    recs = []
    for _, r in j.iterrows():
        s_ep, e_ep = idc._to_epoch(r["win_start_tai"]), idc._to_epoch(r["win_end_tai"])
        st = idc.observed_step(t, a, s_ep, e_ep)
        if st is None:
            continue
        recs.append(dict(win_start_tai=r["win_start_tai"], da_true_m=abs(float(r["da_km"])) * 1000,
                         da_obs_m=abs(st) * 1000))
    D = pd.DataFrame(recs)
    D["det_sigma_res"] = (D["da_obs_m"] >= 3 * sig_res * 1000).astype(int)
    D["det_sigma_diff"] = (D["da_obs_m"] >= 3 * sig_diff * 1000).astype(int)
    D.to_csv(BENCH / f"paperA_jason3_det_recalc_{TAG}.csv", index=False, encoding="utf-8-sig")
    old = pd.read_csv(idc.OUT)
    nz = D[D["da_true_m"] > 0]
    miss = D[D["det_sigma_res"] == 0]
    out = dict(
        sigma_used_by_program="sigma_resid_km（σ_res）",
        sigma_res_m=_r(sig_res * 1000), sigma_diff_m=_r(sig_diff * 1000),
        thr_3sigma_res_m=_r(3 * sig_res * 1000), thr_3sigma_diff_m=_r(3 * sig_diff * 1000),
        n_windows_truth=int(len(j)), n_events=int(len(D)),
        n_detected=int(D["det_sigma_res"].sum()), p_det=_r(D["det_sigma_res"].mean(), 4),
        n_detected_if_sigma_diff=int(D["det_sigma_diff"].sum()),
        missed=[dict(win_start_tai=m.win_start_tai, da_true_m=_r(m.da_true_m, 2),
                     da_obs_m=_r(m.da_obs_m, 3)) for m in miss.itertuples()],
        r_obs_true=_r(np.corrcoef(D["da_true_m"], D["da_obs_m"])[0, 1]),
        n_true_zero=int((D["da_true_m"] == 0).sum()),
        da_true_nonzero_range_m=[_r(nz["da_true_m"].min(), 2), _r(nz["da_true_m"].max(), 1)],
        da_over_sigma_res_nonzero_range=[_r(nz["da_true_m"].min() / (sig_res * 1000), 1),
                                         _r(nz["da_true_m"].max() / (sig_res * 1000), 0)],
        existing_csv=_det_csv_stats(old, sig_res),
    )
    # 多 burn 窗：ids_detection_curve 以 drop_duplicates 只取「第一個 burn」之 da 為真值；
    # 改以窗內加總（與 ids_dv_vector_validate 一致）重算，供參考
    wsum = df[df["norad"] == idc.NORAD_J3].groupby("win_start_tai")["da_km"].agg(["sum", "size"])
    Dw = D.merge(wsum, left_on="win_start_tai", right_index=True)
    Dw["da_true_sum_m"] = Dw["sum"].abs() * 1000
    out["multi_burn_windows"] = dict(
        n_windows_with_ge2_burns=int((Dw["size"] >= 2).sum()),
        r_obs_vs_truth_first_burn=out["r_obs_true"],
        r_obs_vs_truth_window_sum=_r(np.corrcoef(Dw["da_true_sum_m"], Dw["da_obs_m"])[0, 1]),
        median_ratio_obs_over_first_burn_ge2=_r((Dw["da_obs_m"] / Dw["da_true_m"])[(Dw["size"] >= 2) & (Dw["da_true_m"] > 1)].median()),
        median_ratio_obs_over_sum_ge2=_r((Dw["da_obs_m"] / Dw["da_true_sum_m"])[(Dw["size"] >= 2) & (Dw["da_true_sum_m"] > 1)].median()))
    oldw = old.merge(wsum, left_on="win_start_tai", right_index=True)
    out["existing_csv"]["r_obs_vs_truth_window_sum"] = _r(np.corrcoef(oldw["sum"].abs() * 1000, oldw["da_obs_m"])[0, 1])
    out["existing_csv"]["da_true_window_sum_nonzero_range_m"] = [
        _r((oldw["sum"].abs() * 1000)[oldw["sum"] != 0].min(), 2), _r((oldw["sum"].abs() * 1000).max(), 1)]
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# §5.5 ΔV 向量
# ═══════════════════════════════════════════════════════════════════════════════
def sec_dv():
    import ids_dv_vector_validate as dv
    df = pd.read_csv(dv.TRUTH)
    recs = []
    for nid, name in dv.TARGETS:
        t, a, inc = dv.load_tle(nid)
        s = df[df["norad"] == nid]
        agg = s.groupby(["win_start_tai", "win_end_tai"], as_index=False).agg(
            dv_along=("dv_along", "sum"), dv_cross=("dv_cross", "sum"), n_burns=("burn_idx", "size"))
        wins = [(dv._ep(a0), dv._ep(b0)) for a0, b0 in zip(agg["win_start_tai"], agg["win_end_tai"])]
        for _, r in agg.iterrows():
            s_ep, e_ep = dv._ep(r["win_start_tai"]), dv._ep(r["win_end_tai"])
            da_obs, a_med = dv.step(t, a, s_ep, e_ep)
            di_obs, _ = dv.step(t, inc, s_ep, e_ep)
            if da_obs is None or di_obs is None:
                continue
            lo, hi = s_ep - dv.BR_OUT_D * 86400, e_ep + dv.BR_OUT_D * 86400
            neigh = sum(1 for (ws, we) in wins
                        if not (abs(ws - s_ep) < 60 and abs(we - e_ep) < 60) and not (we < lo or ws > hi))
            n = math.sqrt(MU / a_med ** 3); v = math.sqrt(MU / a_med)
            recs.append(dict(sat=name, win_start_tai=r["win_start_tai"], clean=int(neigh == 0),
                             dv_along_truth=r["dv_along"], dv_along_rec=n * da_obs / 2 * 1000,
                             dv_cross_truth=r["dv_cross"], dv_cross_rec=v * math.radians(di_obs) * 1000))
    D = pd.DataFrame(recs)
    D.to_csv(BENCH / f"paperA_dv_recalc_{TAG}.csv", index=False, encoding="utf-8-sig")

    def rep(d, ct, cr):
        m = d[[ct, cr]].dropna(); m = m[m[ct].abs() > 1e-6]
        err = (m[cr] - m[ct]).abs()
        return dict(n=int(len(m)), r=_r(np.corrcoef(m[ct], m[cr])[0, 1]),
                    median_abs_err_mm_s=_r(err.median() * 1000, 2),
                    median_abs_truth_mm_s=_r(m[ct].abs().median() * 1000, 2))
    Dc = D[D.clean == 1]
    out = dict(n_events_total=int(len(D)), n_clean=int(len(Dc)),
               along_all=rep(D, "dv_along_truth", "dv_along_rec"),
               along_clean=rep(Dc, "dv_along_truth", "dv_along_rec"),
               cross_all=rep(D, "dv_cross_truth", "dv_cross_rec"),
               along_clean_by_sat={s: rep(Dc[Dc.sat == s], "dv_along_truth", "dv_along_rec")
                                   for s in ("CryoSat-2", "SWOT")},
               along_all_by_sat={s: rep(D[D.sat == s], "dv_along_truth", "dv_along_rec")
                                 for s in ("CryoSat-2", "SWOT")})
    V = pd.read_csv(ROOT / "ids_truth_set" / "ids_dv_vector_validate.csv")
    Vc = V[V.clean == 1]
    out["existing_csv"] = dict(
        file="ids_truth_set/ids_dv_vector_validate.csv（2026-08-11 凍結）",
        n_events_total=int(len(V)), n_clean=int(len(Vc)),
        along_all=rep(V, "dv_along_truth", "dv_along_rec"),
        along_clean=rep(Vc, "dv_along_truth", "dv_along_rec"),
        cross_all=rep(V, "dv_cross_truth", "dv_cross_rec"),
        along_clean_by_sat={s: rep(Vc[Vc.sat == s], "dv_along_truth", "dv_along_rec") for s in ("CryoSat-2", "SWOT")})
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# §5 福衛系列
# ═══════════════════════════════════════════════════════════════════════════════
FS7 = {44349: "FORMOSAT-7-1 (A)", 44351: "FORMOSAT-7-2 (B)", 44343: "FORMOSAT-7-3 (C)",
       44350: "FORMOSAT-7-4 (D)", 44358: "FORMOSAT-7-5 (E)", 44353: "FORMOSAT-7-6 (F)"}
FS3 = {29047: "FORMOSAT-3A", 29048: "FORMOSAT-3B", 29049: "FORMOSAT-3C",
       29050: "FORMOSAT-3D", 29051: "FORMOSAT-3E", 29052: "FORMOSAT-3F"}
WRONG_FS7 = [43010, 43011, 43012, 43013, 43014, 43015]


def _adj_stats(t, a):
    """相鄰 |Δa|（m）統計；t 已排序且去除重複 epoch。"""
    d = np.diff(a) * 1000.0
    x = np.abs(d)
    return dict(n_pairs=int(len(x)), median_m=_r(np.median(x), 2), p90_m=_r(np.percentile(x, 90), 2),
                p99_m=_r(np.percentile(x, 99), 2), max_m=_r(x.max(), 1), n_gt50=int((x > 50).sum())), d


def _dedup(t, a):
    _, idx = np.unique(t, return_index=True)
    return t[idx], a[idx]


def sec_fs():
    con = _con()
    out = dict(period_year_utc=list(FS_YEAR), period_fs3_30d_utc=list(FS3_30D),
               note_stats="相鄰 |Δa|：primary＝僅去除重複 epoch；另附 3 h 稀釋版（與 §2.2 一致）")
    # 43010–43015 身分
    meta = duckdb.connect().execute(
        "SELECT norad_id, name_en, launch_date, intl_code FROM read_parquet(?) WHERE norad_id IN "
        "(43010,43011,43012,43013,43014,43015) ORDER BY 1",
        [str(ROOT / "data" / "tle_parquet" / "sat_metadata.parquet")]).fetchall()
    ident = {}
    for nid, nm, ld, ic in meta:
        t, a = load_raw(nid, *FS_YEAR, con=con)
        ident[str(nid)] = dict(name=nm, launch=str(ld), intl=ic,
                               alt_median_year_km=_r(np.median(a) - RE, 1) if len(a) else None,
                               n_tle_year=int(len(a)))
    out["norad_43010_43015_identity"] = ident
    # 43010（FENGYUN 3D）之統計：檢查論文 §5.3 原值是否源自誤植
    t, a = _dedup(*load_raw(43010, *FS_YEAR, con=con))
    out["fengyun3d_43010_year_stats"] = _adj_stats(t, a)[0]

    # 表 2：2024-01-01 起至 2026-11-17 之高度中位（RE=6378.137 km）
    t2 = {}
    for nid in [29047, 29048, 29049, 29050, 29051, 29052, 42920] + list(FS7):
        _, a = load_raw(nid, "2024-01-01", FS_YEAR[1], con=con)
        t2[str(nid)] = _r(np.median(a) - RE, 1)
    out["table2_alt_median_2024_2026_km"] = t2

    ev_rows = []

    def sat_block(nid, name, period):
        t, a = _dedup(*load_raw(nid, *period, con=con))
        st, d = _adj_stats(t, a)
        t3, a3 = thin(t, a, 3.0)
        st3, _ = _adj_stats(t3, a3)
        alt = a - RE
        amed = float(np.median(a))
        v = math.sqrt(MU / amed)
        evs = []
        for i in np.where(np.abs(d) > 50)[0]:
            dvm = v / (2 * amed) * abs(d[i]) / 1000.0 * 1000.0   # m/s（式 6：Δv=(v/2a)Δa）
            e = dict(norad=nid, sat=name,
                     epoch_before=dt.datetime.fromtimestamp(t[i]).strftime("%Y-%m-%d %H:%M:%S"),
                     epoch_after=dt.datetime.fromtimestamp(t[i + 1]).strftime("%Y-%m-%d %H:%M:%S"),
                     da_m=_r(d[i], 1), dv_m_s=_r(dvm, 3))
            evs.append(e); ev_rows.append(e)
        return dict(name=name, n_tle_unique=int(len(t)), alt_median_km=_r(np.median(alt), 1),
                    alt_min_km=_r(alt.min(), 1), alt_max_km=_r(alt.max(), 1),
                    a_median_km=_r(amed, 2), v_km_s=_r(v, 4),
                    adjacent_dedup=st, adjacent_thin3h=st3, events_gt50m=evs)

    out["FS5"] = sat_block(42920, "FORMOSAT-5", FS_YEAR)
    f5 = out["FS5"]
    # 式 (6) 以論文數值（a≈7101 km、v≈7.49 km/s、Δa 0.798 km）與重算值各算一次
    out["FS5_eq6"] = dict(paper_inputs=_r(7.49 / (2 * 7101) * 0.798 * 1000, 4),
                          recomputed=_r(f5["v_km_s"] / (2 * f5["a_median_km"]) * f5["adjacent_dedup"]["max_m"] / 1000 * 1000, 4),
                          snr_max_over_1m=_r(f5["adjacent_dedup"]["max_m"] / 1.0, 0))
    out["FS7"] = {str(n): sat_block(n, nm, FS_YEAR) for n, nm in FS7.items()}
    # FS7 合併
    alls = [out["FS7"][str(n)] for n in FS7]
    out["FS7_summary"] = dict(
        alt_median_range_km=[min(s["alt_median_km"] for s in alls), max(s["alt_median_km"] for s in alls)],
        alt_minmax_year_km=[min(s["alt_min_km"] for s in alls), max(s["alt_max_km"] for s in alls)],
        median_m_range=[min(s["adjacent_dedup"]["median_m"] for s in alls), max(s["adjacent_dedup"]["median_m"] for s in alls)],
        p99_m_range=[min(s["adjacent_dedup"]["p99_m"] for s in alls), max(s["adjacent_dedup"]["p99_m"] for s in alls)],
        n_gt50_range=[min(s["adjacent_dedup"]["n_gt50"] for s in alls), max(s["adjacent_dedup"]["n_gt50"] for s in alls)])
    # FS3：近 30 天，§2.2 同一估計量（3 h 稀釋、多項式依跨度、式 1/2；無機動故不內縮）
    fs3 = {}
    for nid, nm in FS3.items():
        t, a = load_raw(nid, *FS3_30D, con=con)
        r = sigma_quiet(t, a, [(t[0], t[-1])], gap_h=3.0, buffer_d=0.0)
        r_buf = sigma_quiet(t, a, [(t[0], t[-1])], gap_h=3.0, buffer_d=0.75)
        tt, aa = thin(t, a, 3.0)
        fs3[nm] = dict(norad=nid, alt_median_km=_r(r["alt_km"], 1), n_pts=r["n_pts"],
                       span_d=_r((tt[-1] - tt[0]) / 86400, 2),
                       sigma_res_m=_r(r["sigma_res_m"], 3), sigma_diff_m=_r(r["sigma_diff_m"], 3),
                       sigma_res_m_buffer075=_r(r_buf["sigma_res_m"], 3),
                       sigma_diff_m_buffer075=_r(r_buf["sigma_diff_m"], 3))
    sd = [v["sigma_diff_m"] for v in fs3.values()]
    sr = [v["sigma_res_m"] for v in fs3.values()]
    al = [v["alt_median_km"] for v in fs3.values()]
    out["FS3"] = dict(per_sat=fs3, sigma_diff_range_m=[min(sd), max(sd)], sigma_res_range_m=[min(sr), max(sr)],
                      alt_range_km=[min(al), max(al)],
                      fig1_representative=dict(alt_km=_r(np.median(al), 1), sigma_diff_m=_r(np.median(sd), 3),
                                               rule="六星 σ_diff 中位數、高度中位數"))
    con.close()
    pd.DataFrame(ev_rows).to_csv(BENCH / f"paperA_fs_events_{TAG}.csv", index=False, encoding="utf-8-sig")
    print(json.dumps({k: out[k] for k in ("FS5", "FS5_eq6", "FS7_summary", "FS3")}, ensure_ascii=False, indent=1)[:6000])
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# §3.2 Starlink
# ═══════════════════════════════════════════════════════════════════════════════
def sec_starlink():
    from scipy.stats import spearmanr
    d = pd.read_csv(BENCH / "starlink_tle_meme_error_floor_20260918.csv", parse_dates=["t"])
    d["ada_m"] = d["da_km"].abs() * 1000.0
    x = d["ada_m"]
    bins = [0, 6, 12, 24, 48, 72, 1e9]
    labs = ["0-6h", "6-12h", "12-24h", "24-48h", "48-72h", ">72h"]
    d["age"] = pd.cut(d["prop_age_h"], bins, labels=labs)
    by_age = {k: dict(n=int(len(g)), median_m=_r(g["ada_m"].median(), 1))
              for k, g in d.groupby("age", observed=True)}
    alt = d["a_meme_km"] - RE
    sat_alt = d.groupby("sat_name")["a_meme_km"].median() - RE
    out = dict(
        source="data/benchmark/starlink_tle_meme_error_floor_20260918.csv（starlink_tle_meme_error_floor.py 產出）",
        n_sats=int(d["sat_name"].nunique()), n_rows=int(len(d)),
        t_range=[str(d["t"].min()), str(d["t"].max())],
        abs_da_median_m=_r(x.median(), 1), abs_da_p90_m=_r(np.percentile(x, 90), 1),
        abs_da_q25_m=_r(x.quantile(0.25), 1), abs_da_q75_m=_r(x.quantile(0.75), 1),
        by_prop_age=by_age,
        alt_km_point_p05_p50_p95=[_r(alt.quantile(q), 1) for q in (0.05, 0.5, 0.95)],
        alt_km_point_min_max=[_r(alt.min(), 1), _r(alt.max(), 1)],
        alt_km_persat_median_min_max=[_r(sat_alt.min(), 1), _r(sat_alt.max(), 1)],
        alt_km_persat_median_p05_p95=[_r(sat_alt.quantile(0.05), 1), _r(sat_alt.quantile(0.95), 1)],
    )
    # 週彙總（外推 <24 h、依日曆週；MAD-σ）× F10.7 週平均：讀既有 weekly_swx CSV（SpaceWeather 原始檔在 F:）
    w = pd.read_csv(BENCH / "starlink_tle_meme_error_floor_weekly_swx_20260918.csv")
    rw = spearmanr(w["F107_OBS"], w["mad_sigma_m"], nan_policy="omit")
    out["weekly_spearman_F107_vs_madsigma"] = dict(n_weeks=int(len(w)), rho=_r(rw[0]), p=_r(rw[1], 4))
    rw2 = spearmanr(w["F107_OBS"], w["median_abs_da_m"], nan_policy="omit")
    out["weekly_spearman_F107_vs_median_abs_da"] = dict(rho=_r(rw2[0]), p=_r(rw2[1], 4))
    p = pd.read_csv(BENCH / "starlink_tle_meme_error_vs_deltaf107_20260919.csv")
    out["pointwise_spearman"] = dict(
        n=int(len(p)),
        abs_da_vs_F107_at_epoch=_r(spearmanr(p["f107_meme_epoch"], p["abs_da_m"])[0]),
        abs_da_vs_deltaF107=_r(spearmanr(p["delta_f107"], p["abs_da_m"])[0]))
    # 檢核一／二：機動濾除（重建互動查核）
    d = d.sort_values(["sat_name", "t"]).reset_index(drop=True)
    g = d.groupby("sat_name")
    net = (g["a_meme_km"].last() - g["a_meme_km"].first()).abs()
    d["dt_d"] = g["t"].diff().dt.total_seconds() / 86400.0
    d["rate_prev"] = g["a_meme_km"].diff().abs() * 1000.0 / d["dt_d"]
    d["rate_next"] = d.groupby("sat_name")["rate_prev"].shift(-1)
    hold = net[net < 10.0].index
    H = d[d["sat_name"].isin(hold)]
    chk = dict(rule="維持星＝MEME 真值 a 首末淨變化 <10 km；取樣點保留條件＝與前後相鄰取樣之真值 |Δa|/Δt 皆 < 門檻（m/day）",
               n_hold_sats=int(len(hold)), n_hold_rows=int(len(H)),
               hold_median_before_m=_r(H["ada_m"].median(), 1),
               true_rate_median_m_per_day_hold=_r(H["rate_prev"].median(), 0),
               true_rate_median_m_per_day_all=_r(d["rate_prev"].median(), 0),
               thresholds={})
    for thr in (2000, 1000, 500):
        mh = (H["rate_prev"] < thr) & (H["rate_next"] < thr)
        ma = (d["rate_prev"] < thr) & (d["rate_next"] < thr)
        chk["thresholds"][str(thr)] = dict(
            hold_n_kept=int(mh.sum()), hold_frac_kept=_r(mh.mean(), 4), hold_median_m=_r(H[mh]["ada_m"].median(), 1),
            all_n_kept=int(ma.sum()), all_median_m=_r(d[ma]["ada_m"].median(), 1))
    chk["all_median_before_m"] = _r(d["ada_m"].median(), 1)
    chk["drop_pct_hold_2000"] = _r(100 * (1 - chk["thresholds"]["2000"]["hold_median_m"] / chk["hold_median_before_m"]), 1)
    a_med = float(d["a_meme_km"].median())
    J2 = 1.08262668e-3
    chk["J2_short_period_amp_km_at_median_a"] = dict(a_km=_r(a_med, 1), amp_km=_r(a_med * J2 * (RE / a_med) ** 2, 2))
    out["check1_check2"] = chk

    # 自我差分估計：tle_noise_floor_map.csv（fs7_noise_floor_map.py，2026-09-18 產出）
    m = pd.read_csv(BENCH / "tle_noise_floor_map.csv")
    sl = m[m["group"] == "Starlink sample (train domain)"]
    out["selfdiff_30_starlink_csv"] = dict(
        file="data/benchmark/tle_noise_floor_map.csv（檔案時間 2026-09-18）",
        n_rows=int(len(sl)), n_valid=int(sl["sigma_m"].notna().sum()),
        median_sigma_m=_r(sl["sigma_m"].median(), 2),
        note="2026-08-25 之 6.1 m 版本 CSV 已被覆寫、未入 git，無法重現；DB 為滾動視窗，現重跑會得不同值")
    # 以現行 DB 重算（僅示範漂移；不覆寫 CSV）
    import fs7_noise_floor_map as nfm
    con = _con()
    now = con.execute("SELECT norad_id FROM raw_tle_archive WHERE object_name ILIKE '%STARLINK%' "
                      "GROUP BY norad_id HAVING COUNT(*)>300 AND MAX(epoch_utc)>'2026-07-01' "
                      "ORDER BY hash(norad_id) LIMIT 30").df()["norad_id"].tolist()
    sigs = []
    for nid in now:
        q = con.execute("SELECT epoch_utc, sma_km FROM raw_tle_archive WHERE norad_id=? AND sma_km IS NOT NULL "
                        "ORDER BY epoch_utc", [int(nid)]).df()
        tt = q["epoch_utc"].values.astype("datetime64[s]").astype(float) / 86400.0
        sigs.append(nfm.sigma_nominal(tt, q["sma_km"].values))
    out["selfdiff_30_starlink_rerun_now"] = dict(
        n_valid=int(np.isfinite(sigs).sum()), median_sigma_m=_r(np.nanmedian(sigs), 2),
        overlap_with_csv_norads=int(len(set(now) & set(sl["norad"]))),
        note="同一腳本邏輯、現行 DB（截至 2026-11-17）；僅示範滾動視窗漂移")
    # STARLINK-3005（48881）：案例三方法 vs §3.2 方法，以現行 DB 重算
    q = con.execute("SELECT epoch_utc, sma_km FROM raw_tle_archive WHERE norad_id=48881 ORDER BY epoch_utc").df()
    con.close()
    q["epoch_utc"] = pd.to_datetime(q["epoch_utc"], utc=True)
    tt = q["epoch_utc"].values.astype("datetime64[s]").astype(float)
    t3, a3 = thin(tt, q["sma_km"].values, 3.0)
    cut = t3[-1] - 60 * 86400
    a60 = a3[t3 >= cut]
    da = np.diff(a60)
    case3 = 1.4826 * float(np.median(np.abs(da - np.median(da)))) * 1000
    tday = tt / 86400.0
    a_all = q["sma_km"].values
    nwin, nclean = 0, 0
    for s0 in range(0, len(a_all) - nfm.WIN, nfm.WIN):
        nwin += 1
        if np.abs(np.diff(a_all[s0:s0 + nfm.WIN])).max() <= nfm.STEP_MAX_KM:
            nclean += 1
    out["starlink3005_rerun_now"] = dict(
        db_span=[str(q["epoch_utc"].min()), str(q["epoch_utc"].max())], n_tle=int(len(q)),
        case3_60d_mad_sigma_m=_r(case3, 2), case3_n_diffs=int(len(da)),
        case3_n_absdiff_gt_300m=int((np.abs(da) > 0.3).sum()), case3_max_absdiff_m=_r(np.abs(da).max() * 1000, 0),
        sec32_method_sigma_m=_r(nfm.sigma_nominal(tday, a_all), 2), sec32_n_windows=nwin, sec32_n_clean_windows=nclean,
        note="論文 11.6 m（9/160 筆 >0.3 km、最大 564 m）與 3.12 m（534 筆、5 個乾淨窗）為 2026-09-18 之 DB 狀態，DB 已滾動，無法逐位重現")
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str)[:7000])
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# §3.2 擬合／NRLMSIS
# ═══════════════════════════════════════════════════════════════════════════════
def sec_fit():
    from scipy.optimize import least_squares
    from fs7_noise_floor_map_v2 import sigma_th
    from gen_fig_sigma_drag_altitude import msis_rho
    d = pd.read_csv(BENCH / "tle_noise_floor_map.csv").dropna(subset=["sigma_m"])
    d["sigma_m"] = d["sigma_m"].clip(lower=0.02)
    h, s = d["alt_km"].values, d["sigma_m"].values

    def resid(p):
        return np.log10(sigma_th(h, np.abs(p))) - np.log10(s)
    f = least_squares(resid, x0=[0.05, 10.0, 120.0], loss="soft_l1")
    s0, A, H = np.abs(f.x)
    r2 = 1 - np.sum(resid(f.x) ** 2) / np.sum((np.log10(s) - np.log10(s).mean()) ** 2)
    bands = {}
    for h0, h1 in [(350, 550), (400, 550), (450, 550)]:
        bands[f"{h0}-{h1}"] = _r((h1 - h0) / float(np.log(msis_rho(h0)[0] / msis_rho(h1)[0])), 2)
    # 太陽活動敏感度（同日期／位置，F10.7=70/220）
    bands_f = {}
    for f107 in (70.0, 220.0):
        bands_f[str(int(f107))] = {f"{h0}-{h1}": _r((h1 - h0) / float(np.log(
            msis_rho(h0, f107=f107)[0] / msis_rho(h1, f107=f107)[0])), 2)
            for h0, h1 in [(350, 550), (400, 550), (450, 550)]}
    import pymsis
    from datetime import datetime as _dtm

    def _rho20(hk):
        return float(np.asarray(pymsis.calculate(_dtm(2026, 3, 21, 12), 0.0, 0.0, np.array([float(hk)]),
                                                 150.0, 150.0, [[10.0] * 7], version=2.0))[..., 0].ravel()[0])
    bands20 = {f"{h0}-{h1}": _r((h1 - h0) / math.log(_rho20(h0) / _rho20(h1)), 2)
               for h0, h1 in [(350, 550), (400, 550), (450, 550)]}
    out = dict(
        input="data/benchmark/tle_noise_floor_map.csv（fs7_noise_floor_map.py 2026-09-18 產出；高度以 RE=6371 km 計）",
        n_points_fit=int(len(d)),
        fit=dict(sigma0_m=_r(s0, 4), A_m=_r(A, 2), H_km=_r(H, 2), R2_log=_r(r2, 4)),
        fit_0825=dict(sigma0_m=0.04, A_m=25, H_km=79, R2_log=0.87,
                      status="無法重現（2026-08-25 版 CSV 已被覆寫、未入 git）"),
        extrap_800km_m=_r(sigma_th(800.0, (s0, A, H)), 3),
        extrap_800km_with_0825_params_m=_r(sigma_th(800.0, (0.04, 25.0, 79.0)), 3),
        msis=dict(conditions="pymsis（NRLMSIS 2.0）、2026-03-21 12:00 UTC、lat 0°、lon 0°、F10.7=F10.7a=150 sfu、Ap=10（docs/gen_fig_sigma_drag_altitude.msis_rho 預設）",
                  pymsis_version=getattr(pymsis, "__version__", "?"),
                  note_version="msis_rho() 未指定 version → pymsis 預設 2.1；另以 version=2.0 明確重算（scale_height_km_v2_0）",
                  scale_height_km=bands, scale_height_km_v2_0=bands20,
                  scale_height_km_other_f107=bands_f),
    )
    hs = list(bands.values())
    out["H_fit_vs_msis_rel_diff"] = dict(
        rel_to_fit=[_r((H - x) / H, 3) for x in hs], rel_to_msis=[_r((H - x) / x, 3) for x in hs])
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


SECTIONS = dict(ids=sec_ids, sens=sec_sens, det=sec_det, dv=sec_dv, fs=sec_fs,
                starlink=sec_starlink, fit=sec_fit)


def main():
    want = [a for a in sys.argv[1:] if a in SECTIONS] or list(SECTIONS)
    res = json.loads(OUT_JSON.read_text(encoding="utf-8")) if OUT_JSON.exists() else {}
    for k in want:
        print(f"\n════ {k} ════")
        t0 = dt.datetime.now()
        res[k] = SECTIONS[k]()
        res.setdefault("_meta", {})[k] = dict(run_at=dt.datetime.now().isoformat(timespec="seconds"),
                                              seconds=round((dt.datetime.now() - t0).total_seconds(), 1))
    OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\n→ {OUT_JSON}")


if __name__ == "__main__":
    main()
