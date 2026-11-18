#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paperA_reviewV1_analysis.py — 論文 A 投稿前審查（Review V1）P0／P1 重算。

對應審查條目：
  est    §2.1–2.3  估計量：未置中 vs 置中 MAD、原始差分 vs 去趨勢差分、相鄰相關 ρ1、
                   依實際時間間隔之半變異（lag dependence）、TLE 間隔分布、以弧段為單位之 bootstrap CI
  far    §2.5      靜默弧段虛擬事件窗：實際步階判定量（後括號中位 − 前括號中位）之零假設分布、
                   3σ_res 門檻之實測誤報率、經驗門檻（p99／p99.7）
  det    §2.4      Jason-3：只用 SMA 之偵測、真值非零窗與真值為零窗分開；經驗門檻下重算；閏秒依 epoch
  xtrack §3.1–3.3  SWOT／CryoSat-2：以點火時刻之緯度幅角 u、Δi 與 ΔΩ 反演法向 Δv；Δi／ΔΩ 步階之
                   靜默弧段雜訊；沿軌 Δv 逐星斜率／截距／偏差／MAE／RMSE 與 bootstrap CI
  alt    §4.1      高度模型：參數 bootstrap CI（以衛星為單位）、排除族群敏感度、常數／分族群／高度模型比較

TLE 半長軸定義：raw_tle_archive.sma_km = (μ/n²)^(1/3)，n 為 TLE（Kozai）平均運動、μ = 398600.4418 km³ s⁻²
（已逐筆驗證）；即「由 TLE 平均運動經 Kepler 關係得之 SMA proxy」，非 SGP4 內部 Brouwer 平均 SMA、亦非密切 SMA。

TAI→UTC：依 epoch 查閏秒表（原程式一律減 37 s；2017 年以前資料差 1–5 s，對 0.3–3 d 括號與 0.75 d 緩衝無實質影響）。

用法：set PYTHONIOENCODING=utf-8
      python docs/paperA_reviewV1_analysis.py              # 全部
      python docs/paperA_reviewV1_analysis.py est far      # 指定子命令
輸出：data/benchmark/paperA_reviewV1.json（分節合併）＋ data/benchmark/paperA_rv1_*.csv
資料庫一律 read_only；不覆寫既有結果檔。
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
DB = ROOT / "space_db.duckdb"
BENCH = ROOT / "data" / "benchmark"
OUT_JSON = BENCH / "paperA_reviewV1.json"
QUIET = ROOT / "ids_truth_set" / "ids_quiet.csv"
TRUTH = ROOT / "ids_truth_set" / "ids_truth.csv"
MU = 398600.4418
RE = 6378.137
RNG = np.random.default_rng(20261118)
NBOOT = 2000

TARGETS = [
    (36508, "CryoSat-2", "CRYO2"), (27386, "Envisat", "ENVI1"), (37781, "HY-2A", "HY-2A"),
    (46469, "HY-2C", "HY-2C"), (48621, "HY-2D", "HY-2D"), (26997, "Jason-1", "JASO1"),
    (33105, "Jason-2", "JASO2"), (41240, "Jason-3", "JASO3"), (39086, "SARAL", "SARAL"),
    (41335, "Sentinel-3A", "SEN3A"), (43437, "Sentinel-3B", "SEN3B"), (46984, "Sentinel-6A", "SEN6A"),
    (54754, "SWOT", "SWOT1"),
]
GAP_H, BUFFER_D, MIN_PTS, MIN_SPAN_D = 3.0, 0.75, 12, 3.0
BR_IN_D, BR_OUT_D, MIN_SIDE = 0.3, 3.0, 3
K = 3.0
LAG_BINS_H = [3, 6, 12, 24, 48, 96, 192]

# 閏秒表（TAI−UTC，s），涵蓋 1999 起之資料
LEAPS = [(dt.datetime(1999, 1, 1), 32), (dt.datetime(2006, 1, 1), 33), (dt.datetime(2009, 1, 1), 34),
         (dt.datetime(2012, 7, 1), 35), (dt.datetime(2015, 7, 1), 36), (dt.datetime(2017, 1, 1), 37)]


def tai_minus_utc(t: dt.datetime) -> int:
    v = 32
    for d0, s in LEAPS:
        if t >= d0:
            v = s
    return v


def tai2ep(s: str) -> float:
    """TAI 字串 → 與 TLE 時間一致之 epoch 秒（naive .timestamp()，與 ids_* 腳本相同慣例）。"""
    t = dt.datetime.fromisoformat(s)
    return t.timestamp() - tai_minus_utc(t)


def utc2ep(s: str) -> float:
    return dt.datetime.fromisoformat(s).timestamp()


def _r(x, n=3):
    if x is None:
        return None
    try:
        x = float(x)
    except Exception:
        return x
    return round(x, n) if math.isfinite(x) else None


def save(sec, obj):
    allj = json.loads(OUT_JSON.read_text(encoding="utf-8")) if OUT_JSON.exists() else {}
    allj[sec] = obj
    allj["_meta"] = dict(script="docs/paperA_reviewV1_analysis.py",
                         run_utc=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                         db="space_db.duckdb（read_only）", nboot=NBOOT, seed=20261118)
    OUT_JSON.write_text(json.dumps(allj, ensure_ascii=False, indent=1), encoding="utf-8")


_CON = None


def con():
    global _CON
    if _CON is None:
        _CON = duckdb.connect(str(DB), read_only=True)
    return _CON


def load(nid, cols="sma_km"):
    rows = con().execute(f"SELECT epoch_utc, {cols} FROM raw_tle_archive WHERE norad_id=? "
                         f"AND sma_km IS NOT NULL ORDER BY epoch_utc", [int(nid)]).fetchall()
    t = np.array([r[0].timestamp() for r in rows])
    vals = [np.array([r[k] for r in rows]) for k in range(1, len(rows[0]))] if rows else []
    return t, vals


def thin(t, *ys, gap_h=GAP_H):
    keep = [0]
    g = gap_h * 3600.0
    for i in range(1, len(t)):
        if t[i] - t[keep[-1]] >= g:
            keep.append(i)
    keep = np.array(keep)
    return (t[keep],) + tuple(y[keep] for y in ys)


def quiets(ids_id):
    out = []
    for r in csv.DictReader(open(QUIET, encoding="utf-8-sig")):
        if r["ids_id"] == ids_id:
            out.append((tai2ep(r["quiet_start_tai"]), tai2ep(r["quiet_end_tai"])))
    return out


def mad_c(x):
    x = np.asarray(x, float)
    return 1.4826 * float(np.median(np.abs(x - np.median(x))))


def mad0(x):
    return 1.4826 * float(np.median(np.abs(np.asarray(x, float))))


# ═══════════════════════════════════════════════════════════════════════════════
# est：估計量、相關性、lag、bootstrap
# ═══════════════════════════════════════════════════════════════════════════════
def arc_pieces(t, a, qs):
    """回傳每弧段 (tt, aa, resid)；與表 1 相同之緩衝、門檻與多項式階數規則。"""
    out = []
    for s, e in qs:
        s += BUFFER_D * 86400
        e -= BUFFER_D * 86400
        if e <= s:
            continue
        m = (t >= s) & (t <= e)
        if m.sum() < MIN_PTS:
            continue
        tt, aa = t[m], a[m]
        span = (tt[-1] - tt[0]) / 86400.0
        if span < MIN_SPAN_D:
            continue
        deg = 1 if span < 10 else (2 if span < 40 else 3)
        deg = min(deg, len(aa) - 2)
        x = (tt - tt[0]) / 86400.0
        c = np.polyfit(x, aa, max(deg, 1))
        out.append((tt, aa, aa - np.polyval(c, x)))
    return out


def stats_from_pieces(P):
    res = np.concatenate([p[2] for p in P])
    draw = np.concatenate([np.diff(p[1]) for p in P])
    dres = np.concatenate([np.diff(p[2]) for p in P])
    return dict(
        s_res_old=mad0(res) * 1e3, s_res_c=mad_c(res) * 1e3,
        s_diff_old=mad0(draw) / math.sqrt(2) * 1e3, s_diff_rawc=mad_c(draw) / math.sqrt(2) * 1e3,
        s_diff_dt=mad_c(dres) / math.sqrt(2) * 1e3)


def sec_est():
    rows, lagrows, boot_med = [], [], {k: [] for k in ("s_res_c", "s_diff_old", "s_diff_dt")}
    per_boot = {}
    for nid, name, iid in TARGETS:
        t, (a,) = load(nid)
        t, a = thin(t, a)
        P = arc_pieces(t, a, quiets(iid))
        st = stats_from_pieces(P)
        # 相鄰相關：Pearson（弧內相鄰殘差對）與穩健版 ρ1 = 1 − (s_Δ/√2)² / s_res²
        x0 = np.concatenate([p[2][:-1] for p in P]); x1 = np.concatenate([p[2][1:] for p in P])
        rho_p = float(np.corrcoef(x0, x1)[0, 1])
        rho_rob = 1.0 - (st["s_diff_dt"] / st["s_res_c"]) ** 2
        # 秩相關（對離群穩健）
        from scipy.stats import spearmanr
        rho_s = float(spearmanr(x0, x1)[0])
        dts = np.concatenate([np.diff(p[0]) for p in P]) / 3600.0
        # 依實際時間間隔之半變異：s(τ) = 1.4826·MAD(r_j − r_i)/√2，比值 s(τ)/s_res
        lag = {}
        for lo, hi in zip(LAG_BINS_H[:-1], LAG_BINS_H[1:]):
            dd = []
            for tt, _, rr in P:
                T = (tt[None, :] - tt[:, None]) / 3600.0
                R = rr[None, :] - rr[:, None]
                m = (T >= lo) & (T < hi)
                dd.append(R[m])
            dd = np.concatenate(dd)
            if len(dd) >= 20:
                sv = mad_c(dd) / math.sqrt(2) * 1e3
                lag[f"{lo}-{hi}h"] = dict(n=int(len(dd)), s_m=_r(sv), ratio=_r(sv / st["s_res_c"]))
                lagrows.append(dict(sat=name, lag_bin=f"{lo}-{hi}h", n=len(dd), s_m=sv,
                                    ratio=sv / st["s_res_c"]))
        # bootstrap：以弧段為單位重抽
        B = {k: [] for k in ("s_res_c", "s_diff_old", "s_diff_dt", "rho_rob")}
        n = len(P)
        for _ in range(NBOOT):
            idx = RNG.integers(0, n, n)
            sb = stats_from_pieces([P[i] for i in idx])
            for k in ("s_res_c", "s_diff_old", "s_diff_dt"):
                B[k].append(sb[k])
            B["rho_rob"].append(1 - (sb["s_diff_dt"] / sb["s_res_c"]) ** 2)
        per_boot[name] = B
        ci = {k: [_r(np.percentile(v, 2.5)), _r(np.percentile(v, 97.5))] for k, v in B.items()}
        alt = float(np.median(a)) - RE
        rows.append(dict(sat=name, norad=nid, alt_km=alt, n_arc=n, n_pts=int(sum(len(p[0]) for p in P)),
                         dt_med_h=float(np.median(dts)), dt_p10_h=float(np.percentile(dts, 10)),
                         dt_p90_h=float(np.percentile(dts, 90)),
                         **st, rho1_pearson=rho_p, rho1_spearman=rho_s, rho1_robust=rho_rob,
                         ci_s_res_c=ci["s_res_c"], ci_s_diff_old=ci["s_diff_old"],
                         ci_s_diff_dt=ci["s_diff_dt"], ci_rho_rob=ci["rho_rob"], lag=lag))
        print(f"{name:12s} {alt:6.0f} km  arcs={n:3d}  Δt中位={np.median(dts):4.1f} h  "
              f"σres舊={st['s_res_old']:.3f} 置中={st['s_res_c']:.3f}  σdiff舊={st['s_diff_old']:.3f} "
              f"去趨勢={st['s_diff_dt']:.3f}  ρ1(P)={rho_p:.2f} ρ1(S)={rho_s:.2f} ρ1(穩健)={rho_rob:.2f}")
    D = pd.DataFrame(rows)
    D.drop(columns=["lag"]).to_csv(BENCH / "paperA_rv1_estimators.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(lagrows).to_csv(BENCH / "paperA_rv1_lag.csv", index=False, encoding="utf-8-sig")
    # 13 顆中位之 bootstrap（各星獨立以弧段重抽後取中位）
    med_ci = {}
    for k in ("s_res_c", "s_diff_old", "s_diff_dt", "rho_rob"):
        M = np.median(np.array([per_boot[n][k] for n in per_boot]), axis=0)
        med_ci[k] = [_r(np.percentile(M, 2.5)), _r(np.percentile(M, 97.5))]
    lag_med = (pd.DataFrame(lagrows).groupby("lag_bin", sort=False)["ratio"].median().round(3).to_dict())
    snap = con().execute("SELECT count(*), max(epoch_utc), max(downloaded_at_utc) FROM raw_tle_archive WHERE norad_id IN ("
                         + ",".join(str(x[0]) for x in TARGETS) + ")").fetchone()
    out = dict(
        snapshot=dict(rows_13sat=int(snap[0]), max_epoch_utc=str(snap[1]), max_downloaded_at_utc=str(snap[2]),
                      db_mtime_utc=dt.datetime.fromtimestamp(DB.stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds")),
        sma_definition="sma_km = (μ/n²)^(1/3)，n 為 TLE Kozai 平均運動，μ = 398600.4418（逐筆驗證）",
        n_sat=len(D),
        median=dict(s_res_old=_r(D.s_res_old.median()), s_res_c=_r(D.s_res_c.median()),
                    s_diff_old=_r(D.s_diff_old.median()), s_diff_rawc=_r(D.s_diff_rawc.median()),
                    s_diff_dt=_r(D.s_diff_dt.median()), rho1_pearson=_r(D.rho1_pearson.median()),
                    rho1_spearman=_r(D.rho1_spearman.median()), rho1_robust=_r(D.rho1_robust.median()),
                    dt_med_h=_r(D.dt_med_h.median(), 2)),
        median_ci95=med_ci,
        range=dict(s_res_c=[_r(D.s_res_c.min()), _r(D.s_res_c.max())],
                   s_diff_dt=[_r(D.s_diff_dt.min()), _r(D.s_diff_dt.max())],
                   rho1_robust=[_r(D.rho1_robust.min()), _r(D.rho1_robust.max())],
                   rho1_pearson=[_r(D.rho1_pearson.min()), _r(D.rho1_pearson.max())]),
        max_abs_diff_old_vs_detrended_m=_r((D.s_diff_old - D.s_diff_dt).abs().max(), 4),
        max_abs_diff_res_old_vs_centered_m=_r((D.s_res_old - D.s_res_c).abs().max(), 4),
        lag_ratio_median_over_sats=lag_med,
        per_sat={r["sat"]: {k: (_r(v) if isinstance(v, float) else v) for k, v in r.items() if k != "sat"}
                 for r in rows},
    )
    print(json.dumps({k: out[k] for k in ("median", "median_ci95", "range", "lag_ratio_median_over_sats",
                                           "max_abs_diff_old_vs_detrended_m",
                                           "max_abs_diff_res_old_vs_centered_m")}, ensure_ascii=False, indent=1))
    save("est", out)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# far：虛擬事件窗（實際步階判定量之零假設分布）
# ═══════════════════════════════════════════════════════════════════════════════
def step_stat(t, y, s_ep, e_ep):
    pre = (t >= s_ep - BR_OUT_D * 86400) & (t <= s_ep - BR_IN_D * 86400)
    post = (t >= e_ep + BR_IN_D * 86400) & (t <= e_ep + BR_OUT_D * 86400)
    if pre.sum() < MIN_SIDE or post.sum() < MIN_SIDE:
        return None
    return float(np.median(y[post]) - np.median(y[pre]))


def pseudo_steps(t, y, qs, win_h=2.5, stride_h=12.0, fn=step_stat):
    """在每個靜默弧段（扣 0.75 d 緩衝）內放長度 win_h 之虛擬窗，其兩側括號須完全落在弧段內。"""
    out = []
    for k, (s, e) in enumerate(qs):
        s += BUFFER_D * 86400
        e -= BUFFER_D * 86400
        c = s + BR_OUT_D * 86400
        while c + win_h * 3600 + BR_OUT_D * 86400 <= e:
            v = fn(t, y, c, c + win_h * 3600)
            if v is not None:
                out.append((k, c, v))
            c += stride_h * 3600
    return out


def sec_far():
    est = json.loads(OUT_JSON.read_text(encoding="utf-8"))["est"]["per_sat"] if OUT_JSON.exists() else {}
    t1 = pd.read_csv(ROOT / "ids_truth_set" / "ids_sigma_calibration.csv").set_index("norad")
    rows, allrec = [], []
    for nid, name, iid in TARGETS:
        t, (a,) = load(nid)                 # 與偵測器相同：未稀釋
        qs = quiets(iid)
        ps = pseudo_steps(t, a, qs)
        if len(ps) < 10:
            print(f"{name:12s} 虛擬窗不足（{len(ps)}）")
            rows.append(dict(sat=name, n_pseudo=len(ps)))
            continue
        arc = np.array([p[0] for p in ps]); v = np.array([p[2] for p in ps]) * 1e3   # m
        av = np.abs(v)
        sig_res = float(est[name]["s_res_c"])          # 本次快照、置中 σ_res（與表 1 新版一致）
        thr = K * sig_res
        far = float((av >= thr).mean())
        # 非重疊子集（相鄰虛擬窗間隔 ≥ 7 d）
        cs = np.array([p[1] for p in ps]); keep = []
        for i in range(len(cs)):
            if not keep or cs[i] - cs[keep[-1]] >= 7 * 86400 or arc[i] != arc[keep[-1]]:
                keep.append(i)
        far_no = float((av[keep] >= thr).mean())
        # bootstrap（以弧段為單位）
        ua = np.unique(arc); grp = {u: np.where(arc == u)[0] for u in ua}
        fb, q99b, q997b = [], [], []
        for _ in range(NBOOT):
            pick = RNG.choice(ua, len(ua))
            idx = np.concatenate([grp[u] for u in pick])
            fb.append((av[idx] >= thr).mean()); q99b.append(np.percentile(av[idx], 99))
            q997b.append(np.percentile(av[idx], 99.7))
        s_step = mad_c(v)
        rec = dict(sat=name, norad=nid, n_pseudo=len(v), n_arc_used=len(ua), n_nonoverlap=len(keep),
                   sigma_res_m=sig_res, thr_3sres_m=thr,
                   step_median_signed_m=float(np.median(v)), step_scale_mad_m=s_step,
                   ratio_step_scale_to_sres=s_step / sig_res,
                   q95_m=float(np.percentile(av, 95)), q99_m=float(np.percentile(av, 99)),
                   q997_m=float(np.percentile(av, 99.7)), max_m=float(av.max()),
                   far_3sres=far, far_3sres_ci=[float(np.percentile(fb, 2.5)), float(np.percentile(fb, 97.5))],
                   far_3sres_nonoverlap=far_no,
                   q99_ci=[float(np.percentile(q99b, 2.5)), float(np.percentile(q99b, 97.5))],
                   q997_ci=[float(np.percentile(q997b, 2.5)), float(np.percentile(q997b, 97.5))])
        rows.append(rec)
        allrec += [dict(sat=name, arc=int(k), t=c, step_m=x * 1e3) for k, c, x in ps]
        print(f"{name:12s} n={len(v):5d} 弧={len(ua):3d}  3σres={thr:5.2f} m  誤報率={far:.3f} "
              f"[{rec['far_3sres_ci'][0]:.3f},{rec['far_3sres_ci'][1]:.3f}] 非重疊={far_no:.3f}  "
              f"步階尺度={s_step:.2f} m（/σres={s_step / sig_res:.2f}）  p99={rec['q99_m']:.2f} p99.7={rec['q997_m']:.2f}")
    D = pd.DataFrame(rows)
    D.to_csv(BENCH / "paperA_rv1_pseudo_far.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(allrec).to_csv(BENCH / "paperA_rv1_pseudo_steps.csv", index=False, encoding="utf-8-sig")
    Dv = D.dropna(subset=["far_3sres"])
    out = dict(
        design=dict(window_h=2.5, stride_h=12, bracket_d=[BR_IN_D, BR_OUT_D], min_side=MIN_SIDE,
                    buffer_d=BUFFER_D, data="未稀釋 TLE（與 ids_detection_curve 偵測器相同）",
                    statistic="median(SMA, post bracket) − median(SMA, pre bracket)",
                    threshold="3 × σ_res（本次 est 置中 σ_res）"),
        n_sat=int(len(Dv)), n_pseudo_total=int(Dv.n_pseudo.sum()),
        far_3sres_median=_r(Dv.far_3sres.median()), far_3sres_range=[_r(Dv.far_3sres.min()), _r(Dv.far_3sres.max())],
        ratio_step_scale_to_sres_median=_r(Dv.ratio_step_scale_to_sres.median()),
        ratio_step_scale_to_sres_range=[_r(Dv.ratio_step_scale_to_sres.min()), _r(Dv.ratio_step_scale_to_sres.max())],
        per_sat={r["sat"]: {k: (_r(v, 4) if isinstance(v, float) else
                                ([_r(x, 4) for x in v] if isinstance(v, list) else v))
                            for k, v in r.items() if k != "sat"} for r in rows},
    )
    print(json.dumps({k: v for k, v in out.items() if k != "per_sat"}, ensure_ascii=False, indent=1))
    save("far", out)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# det：Jason-3（SMA-only）
# ═══════════════════════════════════════════════════════════════════════════════
def sec_det():
    allj = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    far = allj["far"]["per_sat"]["Jason-3"]
    df = pd.read_csv(TRUTH)
    j = df[df["norad"] == 41240]
    W = j.groupby(["win_start_tai", "win_end_tai"], as_index=False).agg(
        da_net_km=("da_km", "sum"), dv_along=("dv_along", "sum"), dv_cross_abs=("dv_cross", lambda x: x.abs().sum()),
        n_burns=("burn_idx", "size"))
    t, (a,) = load(41240)
    sres = far["sigma_res_m"]
    thr = {"3sres": K * sres, "p99": far["q99_m"], "p997": far["q997_m"], "max_null": far["max_m"]}
    recs = []
    for _, r in W.iterrows():
        st = step_stat(t, a, tai2ep(r["win_start_tai"]), tai2ep(r["win_end_tai"]))
        if st is None:
            continue
        rec = dict(win_start_tai=r["win_start_tai"], n_burns=int(r["n_burns"]),
                   da_true_m=abs(r["da_net_km"]) * 1e3, dv_cross_abs=r["dv_cross_abs"],
                   da_obs_m=st * 1e3, abs_obs_m=abs(st) * 1e3)
        for k, v in thr.items():
            rec[f"det_{k}"] = int(abs(st) * 1e3 >= v)
        recs.append(rec)
    D = pd.DataFrame(recs)
    D.to_csv(BENCH / "paperA_rv1_jason3_det.csv", index=False, encoding="utf-8-sig")
    nz = D[D.da_true_m > 0]; z = D[D.da_true_m == 0]
    old = pd.read_csv(ROOT / "ids_truth_set" / "ids_detection_curve_jason3.csv")
    out = dict(
        detector="SMA-only：|median(post) − median(pre)| ≥ 門檻；括號 [0.3, 3] d；每側 ≥3 筆；未稀釋 TLE；只在已知機動窗評估（非連續盲測）",
        n_windows=int(len(D)), n_nonzero_truth=int(len(nz)), n_zero_truth=int(len(z)),
        thresholds_m={k: _r(v) for k, v in thr.items()},
        detected_nonzero={k: int(nz[f"det_{k}"].sum()) for k in thr},
        detected_zero_truth={k: int(z[f"det_{k}"].sum()) for k in thr},
        zero_truth_windows=z[["win_start_tai", "dv_cross_abs", "da_obs_m"]].round(4).to_dict("records"),
        missed_nonzero_3sres=nz[nz.det_3sres == 0][["win_start_tai", "da_true_m", "da_obs_m"]].round(3).to_dict("records"),
        r_obs_vs_truth_nonzero=_r(np.corrcoef(nz.da_true_m, nz.abs_obs_m)[0, 1]),
        max_abs_obs_change_vs_old_csv_m=_r((D.sort_values("win_start_tai").abs_obs_m.values -
                                            old.sort_values("win_start_tai").da_obs_m.values).__abs__().max(), 4)
        if len(old) == len(D) else "筆數不同",
        nonzero_truth_range_m=[_r(nz.da_true_m.min()), _r(nz.da_true_m.max())],
        n_nonzero_between_thresholds=int(((nz.da_true_m >= thr["3sres"]) & (nz.da_true_m < 150)).sum()),
        n_nonzero_between_detected=int((((nz.da_true_m >= thr["3sres"]) & (nz.da_true_m < 150)) & (nz.det_3sres == 1)).sum()),
    )
    for k in thr:
        sub = nz[nz.da_true_m >= thr[k]]
        out.setdefault("detected_nonzero_truth_above_thr", {})[k] = [int(sub[f"det_{k}"].sum()), int(len(sub))]
    print(json.dumps(out, ensure_ascii=False, indent=1))
    save("det", out)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# xtrack：法向 Δv（u、Δi、ΔΩ）與沿軌逐星統計
# ═══════════════════════════════════════════════════════════════════════════════
def lin_step(t, y, s_ep, e_ep):
    """括號內各自線性擬合，於窗中點外插之差；用於 Δi／ΔΩ（扣除背景節點進動）。"""
    pre = (t >= s_ep - BR_OUT_D * 86400) & (t <= s_ep - BR_IN_D * 86400)
    post = (t >= e_ep + BR_IN_D * 86400) & (t <= e_ep + BR_OUT_D * 86400)
    if pre.sum() < MIN_SIDE or post.sum() < MIN_SIDE:
        return None
    tm = 0.5 * (s_ep + e_ep)
    cp = np.polyfit((t[pre] - tm) / 86400, y[pre], 1)
    cq = np.polyfit((t[post] - tm) / 86400, y[post], 1)
    return float(cq[1] - cp[1])


def arg_lat(line1, line2, ep_utc):
    from sgp4.api import Satrec, jday
    s = Satrec.twoline2rv(line1, line2)
    d = dt.datetime.fromtimestamp(ep_utc)
    jd, fr = jday(d.year, d.month, d.day, d.hour, d.minute, d.second + d.microsecond * 1e-6)
    e, r, v = s.sgp4(jd, fr)
    if e != 0:
        return None
    r = np.array(r); v = np.array(v)
    h = np.cross(r, v); hn = h / np.linalg.norm(h)
    node = np.cross([0, 0, 1.0], hn); node /= np.linalg.norm(node)
    u = math.atan2(np.dot(r, np.cross(hn, node)), np.dot(r, node))
    return u, math.acos(hn[2]), float(np.linalg.norm(v))


def boot_reg(x, y, nb=NBOOT):
    x = np.asarray(x); y = np.asarray(y); n = len(x)
    rs, sl = [], []
    for _ in range(nb):
        i = RNG.integers(0, n, n)
        if np.std(x[i]) == 0 or np.std(y[i]) == 0:
            continue
        rs.append(np.corrcoef(x[i], y[i])[0, 1]); sl.append(np.polyfit(x[i], y[i], 1)[0])
    return [float(np.percentile(rs, 2.5)), float(np.percentile(rs, 97.5))], \
        [float(np.percentile(sl, 2.5)), float(np.percentile(sl, 97.5))]


def reg_stats(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    if len(x) < 3:
        return dict(n=int(len(x)))
    sl, ic = np.polyfit(x, y, 1)
    err = y - x
    r = float(np.corrcoef(x, y)[0, 1])
    rci, slci = boot_reg(x, y)
    return dict(n=int(len(x)), r=_r(r), r_ci=[_r(v) for v in rci], slope=_r(sl), slope_ci=[_r(v) for v in slci],
                intercept_mm_s=_r(ic * 1e3, 2), bias_median_mm_s=_r(np.median(err) * 1e3, 2),
                mae_median_mm_s=_r(np.median(np.abs(err)) * 1e3, 2), rmse_mm_s=_r(np.sqrt(np.mean(err ** 2)) * 1e3, 2),
                truth_median_abs_mm_s=_r(np.median(np.abs(x)) * 1e3, 2))


def sec_xtrack():
    df = pd.read_csv(TRUTH)
    recs, noise = [], {}
    for nid, name, iid in [(54754, "SWOT", "SWOT1"), (36508, "CryoSat-2", "CRYO2")]:
        rows = con().execute("SELECT epoch_utc, sma_km, inclination_deg, raan_deg, line1, line2 FROM raw_tle_archive "
                             "WHERE norad_id=? ORDER BY epoch_utc", [nid]).fetchall()
        t = np.array([r[0].timestamp() for r in rows]); a = np.array([r[1] for r in rows])
        inc = np.array([r[2] for r in rows]); om = np.degrees(np.unwrap(np.radians([r[3] for r in rows])))
        L1 = [r[4] for r in rows]; L2 = [r[5] for r in rows]
        # 靜默弧段之 Δi／sin i·ΔΩ 步階雜訊（線性擬合括號估計量）
        qs = quiets(iid)
        si = math.sin(math.radians(float(np.median(inc))))
        pi_ = np.array([p[2] for p in pseudo_steps(t, inc, qs, fn=lin_step)])
        po_ = np.array([p[2] for p in pseudo_steps(t, om, qs, fn=lin_step)])
        pa_ = np.array([p[2] for p in pseudo_steps(t, a, qs)])
        vbar = math.sqrt(MU / float(np.median(a)))
        noise[name] = dict(n_pseudo=int(len(pi_)), s_di_mdeg=_r(mad_c(pi_) * 1e3, 4),
                           s_sinidOm_mdeg=_r(mad_c(po_) * si * 1e3, 4),
                           dvN_equiv_from_di_mm_s=_r(vbar * math.radians(mad_c(pi_)) * 1e6, 2),
                           dvN_equiv_from_dOm_mm_s=_r(vbar * math.radians(mad_c(po_) * si) * 1e6, 2),
                           s_da_step_m=_r(mad_c(pa_) * 1e3, 3),
                           dvT_equiv_mm_s=_r(math.sqrt(MU / float(np.median(a)) ** 3) * mad_c(pa_) / 2 * 1e6, 3),
                           tle_inclination_quantum_mdeg=0.1)
        s = df[df["norad"] == nid]
        wins = s.groupby(["win_start_tai", "win_end_tai"], as_index=False).size()
        wl = [(tai2ep(x), tai2ep(y)) for x, y in zip(wins.win_start_tai, wins.win_end_tai)]
        for (ws, we), g in s.groupby(["win_start_tai", "win_end_tai"]):
            s_ep, e_ep = tai2ep(ws), tai2ep(we)
            da = step_stat(t, a, s_ep, e_ep); di_med = step_stat(t, inc, s_ep, e_ep)
            di = lin_step(t, inc, s_ep, e_ep); dO = lin_step(t, om, s_ep, e_ep)
            if None in (da, di, dO, di_med):
                continue
            lo, hi = s_ep - BR_OUT_D * 86400, e_ep + BR_OUT_D * 86400
            neigh = sum(1 for (x, y) in wl if not (abs(x - s_ep) < 60 and abs(y - e_ep) < 60) and not (y < lo or x > hi))
            k0 = int(np.searchsorted(t, s_ep)) - 1
            if k0 < 0:
                continue
            di_pred = dO_pred = 0.0
            us = []
            for _, b in g.iterrows():
                ul = arg_lat(L1[k0], L2[k0], utc2ep(b["epoch_utc"]))
                if ul is None:
                    continue
                u, ii, vv = ul
                us.append(u)
                di_pred += math.cos(u) * b["dv_cross"] / (vv * 1e3)
                dO_pred += math.sin(u) * b["dv_cross"] / (vv * 1e3 * math.sin(ii))
            if not us:
                continue
            a_med = float(np.median(a[max(0, k0 - 20):k0 + 1]))
            v = math.sqrt(MU / a_med); n = math.sqrt(MU / a_med ** 3)
            ii = math.radians(float(inc[k0]))
            dvc = g["dv_cross"].values
            cross_one_sign = bool((np.abs(dvc) > 0).any() and (np.all(dvc >= 0) or np.all(dvc <= 0)))
            # 法向 Δv 最小平方反演（單一 u 時精確）：Δv_N = v·(cos u·Δi + sin u·sin i·ΔΩ)
            w = np.abs(dvc) if np.abs(dvc).sum() > 0 else np.ones(len(dvc))
            ubar = math.atan2(float(np.sum(w * np.sin(us))), float(np.sum(w * np.cos(us)))) if len(us) == len(w) else us[0]
            dvN_rec = v * (math.cos(ubar) * math.radians(di) + math.sin(ubar) * math.sin(ii) * math.radians(dO)) * 1e3
            recs.append(dict(
                sat=name, win_start_tai=ws, n_burns=len(g), clean=int(neigh == 0),
                u_deg=math.degrees(ubar), cross_one_sign=cross_one_sign,
                dv_along_truth=g["dv_along"].sum(), dv_along_rec=n * da / 2 * 1e3,
                dv_cross_truth=float(dvc.sum()), dv_cross_abs_truth=float(np.abs(dvc).sum()),
                dv_cross_rec_old=v * math.radians(di_med) * 1e3, dv_cross_rec_new=dvN_rec,
                di_obs_mdeg=di * 1e3, di_pred_mdeg=math.degrees(di_pred) * 1e3,
                dOm_sini_obs_mdeg=dO * math.sin(ii) * 1e3, dOm_sini_pred_mdeg=math.degrees(dO_pred) * math.sin(ii) * 1e3))
    D = pd.DataFrame(recs)
    D.to_csv(BENCH / "paperA_rv1_dv_vector.csv", index=False, encoding="utf-8-sig")
    out = dict(noise_quiet=noise, n_windows=int(len(D)), n_clean=int(D.clean.sum()),
               clean_rule="括號 [s−3 d, e+3 d] 內無其他 IDS 記錄之機動窗（只依日誌時刻，不依反演結果）",
               along={}, cross={}, elements={})
    for scope, dd in (("all", D), ("clean", D[D.clean == 1])):
        m = dd[dd.dv_along_truth.abs() > 1e-6]
        out["along"][scope] = dict(pooled=reg_stats(m.dv_along_truth, m.dv_along_rec),
                                   **{s_: reg_stats(m[m.sat == s_].dv_along_truth, m[m.sat == s_].dv_along_rec)
                                      for s_ in ("SWOT", "CryoSat-2")})
        c = dd[dd.dv_cross_abs_truth > 1e-6]
        c1 = c[c.cross_one_sign]
        out["cross"][scope] = dict(
            n_with_cross=int(len(c)), n_one_sign=int(len(c1)),
            old_vdi_median=reg_stats(c1.dv_cross_truth, c1.dv_cross_rec_old),
            new_u_di_dOm=reg_stats(c1.dv_cross_truth, c1.dv_cross_rec_new),
            **{f"new_{s_}": reg_stats(c1[c1.sat == s_].dv_cross_truth, c1[c1.sat == s_].dv_cross_rec_new)
               for s_ in ("SWOT", "CryoSat-2")})
        out["elements"][scope] = dict(
            di_obs_vs_pred=reg_stats(c.di_pred_mdeg / 1e3, c.di_obs_mdeg / 1e3),
            dOm_sini_obs_vs_pred=reg_stats(c.dOm_sini_pred_mdeg / 1e3, c.dOm_sini_obs_mdeg / 1e3),
            median_abs_di_pred_mdeg=_r(c.di_pred_mdeg.abs().median(), 3),
            median_abs_dOm_sini_pred_mdeg=_r(c.dOm_sini_pred_mdeg.abs().median(), 3),
            frac_pred_above_2sigma_noise=dict(
                di=_r(np.mean(np.abs(c.di_pred_mdeg) > 2 * np.mean([noise[s_]["s_di_mdeg"] for s_ in noise])), 3),
                dOm=_r(np.mean(np.abs(c.dOm_sini_pred_mdeg) > 2 * np.mean([noise[s_]["s_sinidOm_mdeg"] for s_ in noise])), 3)))
    out["u_deg_distribution"] = dict(abs_sin_u_median=_r(np.median(np.abs(np.sin(np.radians(D.u_deg))))),
                                     frac_near_node_abs_cos_gt_0p9=_r(np.mean(np.abs(np.cos(np.radians(D.u_deg))) > 0.9)))
    print(json.dumps(out, ensure_ascii=False, indent=1))
    save("xtrack", out)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# alt：高度模型不確定度與敏感度
# ═══════════════════════════════════════════════════════════════════════════════
def sigma_th(h, p):
    s0, A, H = p
    return np.sqrt(s0 ** 2 + (A * np.exp(-(h - 400.0) / H)) ** 2)


def fit_alt(h, s):
    from scipy.optimize import least_squares

    def resid(p):
        return np.log10(sigma_th(h, np.abs(p))) - np.log10(s)
    f = least_squares(resid, x0=[0.05, 10.0, 120.0], loss="soft_l1")
    p = np.abs(f.x)
    rr = resid(f.x)
    r2 = 1 - np.sum(rr ** 2) / np.sum((np.log10(s) - np.log10(s).mean()) ** 2)
    return p, r2, rr


def sec_alt():
    d = pd.read_csv(BENCH / "tle_noise_floor_map.csv").dropna(subset=["sigma_m"]).copy()
    d["sigma_m"] = d["sigma_m"].clip(lower=0.02)
    h, s = d.alt_km.values, d.sigma_m.values
    p, r2, rr = fit_alt(h, s)
    B = []
    for _ in range(NBOOT):
        i = RNG.integers(0, len(d), len(d))
        try:
            pb, _, _ = fit_alt(h[i], s[i])
            B.append(pb)
        except Exception:
            pass
    B = np.array(B)
    ci = {k: [_r(np.percentile(B[:, j], 2.5), 3), _r(np.percentile(B[:, j], 97.5), 3)]
          for j, k in enumerate(("sigma0_m", "A_m", "H_km"))}
    s800 = sigma_th(800.0, B.T)
    groups = {}
    for g in d.group.unique():
        m = d.group != g
        pg, r2g, _ = fit_alt(h[m], s[m])
        groups[f"drop: {g}"] = dict(n=int(m.sum()), sigma0_m=_r(pg[0], 3), A_m=_r(pg[1], 2), H_km=_r(pg[2], 1),
                                    R2_log=_r(r2g), s800_m=_r(sigma_th(800.0, pg), 3))
    # 模型比較（log10 空間，高斯似然之 AIC）
    ls = np.log10(s)
    n = len(ls)

    def aic(rss, k):
        return n * math.log(rss / n) + 2 * k
    rss_const = float(np.sum((ls - ls.mean()) ** 2))
    gm = d.groupby("group")["sigma_m"].transform(lambda x: np.log10(x).mean())
    rss_group = float(np.sum((ls - gm.values) ** 2))
    rss_alt = float(np.sum(rr ** 2))
    out = dict(
        input="data/benchmark/tle_noise_floor_map.csv（56 顆有效；滑動窗自我一致估計量：40-TLE 窗、排除 >0.3 km 步階、線性去趨勢；與靜默弧段估計量不同）",
        groups=d.group.value_counts().to_dict(), alt_range_km=[_r(h.min(), 0), _r(h.max(), 0)],
        fit=dict(sigma0_m=_r(p[0], 4), A_m=_r(p[1], 2), H_km=_r(p[2], 2), R2_log=_r(r2, 4)),
        ci95_bootstrap_by_satellite=ci, n_boot_ok=int(len(B)),
        s800_m=_r(sigma_th(800.0, p), 3), s800_ci95=[_r(np.percentile(s800, 2.5), 3), _r(np.percentile(s800, 97.5), 3)],
        leave_group_out=groups,
        model_comparison_log10=dict(
            constant=dict(k=1, rss=_r(rss_const, 3), aic=_r(aic(rss_const, 1), 1)),
            per_group_mean=dict(k=int(d.group.nunique()), rss=_r(rss_group, 3), aic=_r(aic(rss_group, d.group.nunique()), 1)),
            altitude_model=dict(k=3, rss=_r(rss_alt, 3), aic=_r(aic(rss_alt, 3), 1))),
    )
    print(json.dumps(out, ensure_ascii=False, indent=1))
    save("alt", out)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# sens：新估計量之 3×3×3 處理參數敏感度
# ═══════════════════════════════════════════════════════════════════════════════
def sec_sens():
    global BUFFER_D
    raw = {}
    for nid, name, iid in TARGETS:
        t, (a,) = load(nid)
        raw[name] = (t, a, quiets(iid))
    rows = []
    b0 = BUFFER_D
    for g in (1.5, 3.0, 6.0):
        for b in (0.5, 0.75, 1.0):
            for doff in (-1, 0, 1):
                BUFFER_D = b
                vals = []
                for name, (t, a, qs) in raw.items():
                    tt, aa = thin(t, a, gap_h=g)
                    P = []
                    for s_, e_ in qs:
                        s_ += b * 86400; e_ -= b * 86400
                        m = (tt >= s_) & (tt <= e_)
                        if e_ <= s_ or m.sum() < MIN_PTS:
                            continue
                        x_, y_ = tt[m], aa[m]
                        span = (x_[-1] - x_[0]) / 86400
                        if span < MIN_SPAN_D:
                            continue
                        deg = max(1, min((1 if span < 10 else (2 if span < 40 else 3)) + doff, len(y_) - 2))
                        xx = (x_ - x_[0]) / 86400
                        P.append((x_, y_, y_ - np.polyval(np.polyfit(xx, y_, deg), xx)))
                    if P:
                        st = stats_from_pieces(P)
                        vals.append((name, st["s_res_c"], st["s_diff_dt"], 1 - (st["s_diff_dt"] / st["s_res_c"]) ** 2))
                V = pd.DataFrame(vals, columns=["sat", "s_res_c", "s_diff_dt", "rho"])
                rows.append(dict(gap_h=g, buffer_d=b, deg_off=doff, med_s_res_c=V.s_res_c.median(),
                                 med_s_diff_dt=V.s_diff_dt.median(), med_rho=V.rho.median(), n=len(V)))
    BUFFER_D = b0
    D = pd.DataFrame(rows)
    D.to_csv(BENCH / "paperA_rv1_sensitivity.csv", index=False, encoding="utf-8-sig")
    out = dict(grid="thinning 1.5/3/6 h × trimming 0.5/0.75/1.0 d × degree rule −1/0/+1",
               med_s_res_c_range=[_r(D.med_s_res_c.min()), _r(D.med_s_res_c.max())],
               med_s_diff_dt_range=[_r(D.med_s_diff_dt.min()), _r(D.med_s_diff_dt.max())],
               med_rho_range=[_r(D.med_rho.min()), _r(D.med_rho.max())],
               by_gap={str(g): dict(s_res_c=_r(D[D.gap_h == g].med_s_res_c.median()),
                                    s_diff_dt=_r(D[D.gap_h == g].med_s_diff_dt.median()),
                                    rho=_r(D[D.gap_h == g].med_rho.median())) for g in (1.5, 3.0, 6.0)},
               by_deg={str(d): dict(s_res_c=_r(D[D.deg_off == d].med_s_res_c.median()),
                                    s_diff_dt=_r(D[D.deg_off == d].med_s_diff_dt.median())) for d in (-1, 0, 1)})
    print(json.dumps(out, ensure_ascii=False, indent=1))
    save("sens", out)
    return out


SECTIONS = dict(est=sec_est, far=sec_far, det=sec_det, xtrack=sec_xtrack, alt=sec_alt)



# ═══════════════════════════════════════════════════════════════════════════════
# far2：去漂移步階判定量（兩側括號各自線性擬合、於窗中點外插相減）之零假設分布與 Jason-3 偵測
# ═══════════════════════════════════════════════════════════════════════════════
def sec_far2():
    est = json.loads(OUT_JSON.read_text(encoding="utf-8"))["est"]["per_sat"]
    rows = []
    for nid, name, iid in TARGETS:
        t, (a,) = load(nid)
        ps = pseudo_steps(t, a, quiets(iid), fn=lin_step)
        arc = np.array([p[0] for p in ps]); v = np.array([p[2] for p in ps]) * 1e3
        av = np.abs(v)
        sres = float(est[name]["s_res_c"])
        ua = np.unique(arc); grp = {u: np.where(arc == u)[0] for u in ua}
        q99b, q997b = [], []
        for _ in range(NBOOT):
            idx = np.concatenate([grp[u] for u in RNG.choice(ua, len(ua))])
            q99b.append(np.percentile(av[idx], 99)); q997b.append(np.percentile(av[idx], 99.7))
        rec = dict(sat=name, n_pseudo=len(v), step_median_signed_m=float(np.median(v)), step_scale_mad_m=mad_c(v),
                   ratio_scale_to_sres=mad_c(v) / sres, far_3sres=float((av >= 3 * sres).mean()),
                   q99_m=float(np.percentile(av, 99)), q997_m=float(np.percentile(av, 99.7)),
                   q99_ci=[float(np.percentile(q99b, 2.5)), float(np.percentile(q99b, 97.5))],
                   q997_ci=[float(np.percentile(q997b, 2.5)), float(np.percentile(q997b, 97.5))])
        rows.append(rec)
        print(f"{name:12s} 中位(帶號)={rec['step_median_signed_m']:+.3f}  尺度={rec['step_scale_mad_m']:.2f}"
              f"（/σres={rec['ratio_scale_to_sres']:.2f}）  3σres誤報={rec['far_3sres']:.3f}  p99={rec['q99_m']:.2f}  p99.7={rec['q997_m']:.2f}")
    D = pd.DataFrame(rows)
    D.to_csv(BENCH / "paperA_rv1_pseudo_far_lin.csv", index=False, encoding="utf-8-sig")
    # Jason-3 偵測（去漂移判定量）
    J = D.set_index("sat").loc["Jason-3"]
    df = pd.read_csv(TRUTH); j = df[df.norad == 41240]
    W = j.groupby(["win_start_tai", "win_end_tai"], as_index=False).agg(da_net_km=("da_km", "sum"))
    t, (a,) = load(41240)
    recs = []
    for _, r in W.iterrows():
        st = lin_step(t, a, tai2ep(r.win_start_tai), tai2ep(r.win_end_tai))
        if st is not None:
            recs.append(dict(win_start_tai=r.win_start_tai, da_true_m=abs(r.da_net_km) * 1e3, abs_obs_m=abs(st) * 1e3))
    E = pd.DataFrame(recs); nz = E[E.da_true_m > 0]
    det = {}
    for k, thr in (("p99", J.q99_m), ("p997", J.q997_m)):
        det[k] = dict(thr_m=_r(thr), detected_nonzero=[int((nz.abs_obs_m >= thr).sum()), int(len(nz))],
                      detected_truth_above_thr=[int(((nz.abs_obs_m >= thr) & (nz.da_true_m >= thr)).sum()),
                                                int((nz.da_true_m >= thr).sum())],
                      zero_truth_flagged=int(((E.da_true_m == 0) & (E.abs_obs_m >= thr)).sum()))
    E.to_csv(BENCH / "paperA_rv1_jason3_det_lin.csv", index=False, encoding="utf-8-sig")
    out = dict(statistic="兩側括號 [0.3, 3] d 各自線性擬合、於窗中點外插相減（去漂移）",
               median_abs_signed_median_m=_r(D.step_median_signed_m.abs().median()),
               ratio_scale_to_sres_median=_r(D.ratio_scale_to_sres.median()),
               far_3sres_median=_r(D.far_3sres.median()),
               per_sat={r["sat"]: {k: (_r(v, 4) if isinstance(v, float) else ([_r(x, 4) for x in v] if isinstance(v, list) else v))
                                   for k, v in r.items() if k != "sat"} for r in rows},
               jason3=det, r_obs_vs_truth_nonzero=_r(np.corrcoef(nz.da_true_m, nz.abs_obs_m)[0, 1]))
    print(json.dumps({k: v for k, v in out.items() if k != "per_sat"}, ensure_ascii=False, indent=1))
    save("far2", out)
    return out


SECTIONS["far2"] = sec_far2
SECTIONS["sens"] = sec_sens


# ═══════════════════════════════════════════════════════════════════════════════
# fs3：福衛三號（無推進）以新估計量重算（2026-10-18 至 2026-11-17 之 30 天視為單一弧段，與表 1 同規則）
# ═══════════════════════════════════════════════════════════════════════════════
def sec_fs3():
    t0, t1_ = dt.datetime(2026, 10, 18).timestamp(), dt.datetime(2026, 11, 18).timestamp()
    rows = []
    for nid, nm in [(29047, "FORMOSAT-3A"), (29048, "FORMOSAT-3B"), (29049, "FORMOSAT-3C"),
                    (29050, "FORMOSAT-3D"), (29051, "FORMOSAT-3E"), (29052, "FORMOSAT-3F"),
                    (42920, "FORMOSAT-5"), (44349, "FORMOSAT-7-1"), (44351, "FORMOSAT-7-2"), (44343, "FORMOSAT-7-3"),
                    (44350, "FORMOSAT-7-4"), (44358, "FORMOSAT-7-5"), (44353, "FORMOSAT-7-6")]:
        t, (a,) = load(nid)
        m = (t >= t0) & (t < t1_)
        t, a = thin(t[m], a[m])
        x = (t - t[0]) / 86400
        span = x[-1]
        deg = 1 if span < 10 else (2 if span < 40 else 3)
        r = a - np.polyval(np.polyfit(x, a, deg), x)
        st = stats_from_pieces([(t, a, r)])
        x0, x1 = r[:-1], r[1:]
        from scipy.stats import spearmanr
        rows.append(dict(sat=nm, alt_km=_r(float(np.median(a)) - RE, 1), n=int(len(a)),
                         s_res_c=_r(st["s_res_c"]), s_diff_dt=_r(st["s_diff_dt"]), s_diff_old=_r(st["s_diff_old"]),
                         rho1_robust=_r(1 - (st["s_diff_dt"] / st["s_res_c"]) ** 2), rho1_spearman=_r(spearmanr(x0, x1)[0])))
        print(rows[-1])
    D = pd.DataFrame(rows)
    f7 = D[D.sat.str.startswith("FORMOSAT-7")]
    D = D[D.sat.str.startswith("FORMOSAT-3")]; hi = D[D.alt_km > 750]
    out = dict(period="2026-10-18 – 2026-11-17（30 天視為單一弧段；福衛五號／七號此期間無 >50 m 步階時方具意義）", per_sat=rows,
               fs7=dict(alt_km=[_r(f7.alt_km.min(), 0), _r(f7.alt_km.max(), 0)],
                        s_res_c=[_r(f7.s_res_c.min()), _r(f7.s_res_c.max())],
                        s_diff_dt=[_r(f7.s_diff_dt.min()), _r(f7.s_diff_dt.max())],
                        s_diff_old=[_r(f7.s_diff_old.min()), _r(f7.s_diff_old.max())]),
               five_high=dict(alt_km=[_r(hi.alt_km.min(), 0), _r(hi.alt_km.max(), 0)],
                              s_res_c=[_r(hi.s_res_c.min()), _r(hi.s_res_c.max())],
                              s_diff_dt=[_r(hi.s_diff_dt.min()), _r(hi.s_diff_dt.max())],
                              s_res_c_median=_r(hi.s_res_c.median()), s_diff_dt_median=_r(hi.s_diff_dt.median())))
    print(json.dumps(out["five_high"], ensure_ascii=False))
    save("fs3", out)
    return out


SECTIONS["fs3"] = sec_fs3


# ═══════════════════════════════════════════════════════════════════════════════
# rv2：第二輪審查（Review V2）補測
#   counts   lag bin 之弧段／配對／衛星數；逐弧段 MAD 中位（等權弧段）對照；衛星層 bootstrap
#   holdout  以弧段分組之 5 折交叉驗證與時間切分（前半弧段校準、後半驗證）之樣本外 exceedance
#   dur      虛擬窗長 0／2.5／12／24 h 與隨機起點之敏感度；真實窗長分布
#   nonov    非重疊子樣本（相鄰虛擬窗之完整括號支撐不重疊）逐星 FAP 與 CI
#   normal   單次點火窗之法向 Δv；多次點火窗之營運方預測平面變化向量對 TLE 觀測；法向估計器零假設分位數
#   influ    SWOT 逐窗剔除之 r／斜率影響；Jason-3 檢出比例 Clopper–Pearson CI
#   aic      高度模型以高斯似然（普通最小平方）重估之 AIC
# ═══════════════════════════════════════════════════════════════════════════════
def _cp(k, n, a=0.05):
    from scipy.stats import beta
    lo = beta.ppf(a / 2, k, n - k + 1) if k > 0 else 0.0
    hi = beta.ppf(1 - a / 2, k + 1, n - k) if k < n else 1.0
    return [_r(lo), _r(hi)]


def rv2_counts():
    rows, per_arc = [], []
    for nid, name, iid in TARGETS:
        t, (a,) = load(nid)
        t, a = thin(t, a)
        P = arc_pieces(t, a, quiets(iid))
        for lo, hi in zip(LAG_BINS_H[:-1], LAG_BINS_H[1:]):
            narc = npair = 0
            for tt, _, rr in P:
                T = (tt[None, :] - tt[:, None]) / 3600.0
                m = int(((T >= lo) & (T < hi)).sum())
                if m:
                    narc += 1
                    npair += m
            rows.append(dict(sat=name, lag_bin=f"{lo}-{hi}h", n_arc=narc, n_pair=npair))
        arc_res = [mad_c(p[2]) * 1e3 for p in P]
        arc_dif = [mad_c(np.diff(p[2])) / math.sqrt(2) * 1e3 for p in P if len(p[2]) > 3]
        per_arc.append(dict(sat=name, arcmed_s_res=float(np.median(arc_res)), arcmed_s_diff=float(np.median(arc_dif))))
    C = pd.DataFrame(rows)
    agg = C.groupby("lag_bin", sort=False).agg(n_sat=("n_arc", lambda x: int((x > 0).sum())),
                                               n_arc=("n_arc", "sum"), n_pair=("n_pair", "sum")).reset_index()
    C.to_csv(BENCH / "paperA_rv2_lag_counts.csv", index=False, encoding="utf-8-sig")
    A = pd.DataFrame(per_arc)
    est = json.loads(OUT_JSON.read_text(encoding="utf-8"))["est"]["per_sat"]
    sres = np.array([est[n]["s_res_c"] for n in A.sat])
    sdif = np.array([est[n]["s_diff_dt"] for n in A.sat])
    bs_r, bs_d = [], []
    for _ in range(NBOOT):
        i = RNG.integers(0, len(sres), len(sres))
        bs_r.append(np.median(sres[i]))
        bs_d.append(np.median(sdif[i]))
    return dict(lag_counts=agg.to_dict("records"),
                arc_equal_weight=dict(median_over_sats_s_res=_r(A.arcmed_s_res.median()),
                                      median_over_sats_s_diff=_r(A.arcmed_s_diff.median()),
                                      per_sat={r.sat: [_r(r.arcmed_s_res), _r(r.arcmed_s_diff)] for r in A.itertuples()}),
                satellite_bootstrap_ci=dict(s_res_c=[_r(np.percentile(bs_r, 2.5)), _r(np.percentile(bs_r, 97.5))],
                                            s_diff_dt=[_r(np.percentile(bs_d, 2.5)), _r(np.percentile(bs_d, 97.5))]))


def rv2_holdout():
    PS = pd.read_csv(BENCH / "paperA_rv1_pseudo_steps.csv")
    out = {}
    for name, g in PS.groupby("sat"):
        v = g.step_m.abs().values
        arc = g.arc.values
        ua = np.unique(arc)
        folds = np.array_split(RNG.permutation(ua), 5)
        ex99 = ex997 = n_te = 0
        for f in folds:
            te = np.isin(arc, f)
            if te.sum() == 0 or (~te).sum() < 100:
                continue
            q99 = np.percentile(v[~te], 99)
            q997 = np.percentile(v[~te], 99.7)
            ex99 += int((v[te] >= q99).sum())
            ex997 += int((v[te] >= q997).sum())
            n_te += int(te.sum())
        order = g.groupby("arc").t.min().sort_values().index.values
        cal = np.isin(arc, order[:len(order) // 2])
        val = ~cal
        q99t = np.percentile(v[cal], 99)
        va = np.unique(arc[val])
        grp = {u: np.where(arc == u)[0] for u in va}
        eb = []
        for _ in range(NBOOT):
            idx = np.concatenate([grp[u] for u in RNG.choice(va, len(va))])
            eb.append((v[idx] >= q99t).mean())
        out[name] = dict(cv5_exceed_q99=_r(ex99 / n_te, 4), cv5_exceed_q997=_r(ex997 / n_te, 4), n_test=n_te,
                         temporal_q99_cal_m=_r(q99t, 2), temporal_exceed_val=_r(float((v[val] >= q99t).mean()), 4),
                         temporal_exceed_val_ci=[_r(np.percentile(eb, 2.5), 4), _r(np.percentile(eb, 97.5), 4)],
                         n_cal=int(cal.sum()), n_val=int(val.sum()), n_arc_cal=int(len(order) // 2),
                         n_arc_val=int(len(order) - len(order) // 2))
    V = pd.DataFrame(out).T
    c99 = V.cv5_exceed_q99.astype(float)
    tv = V.temporal_exceed_val.astype(float)
    return dict(per_sat=out, cv5_q99_median=_r(c99.median(), 4), cv5_q99_range=[_r(c99.min(), 4), _r(c99.max(), 4)],
                cv5_q997_median=_r(V.cv5_exceed_q997.astype(float).median(), 4),
                temporal_median=_r(tv.median(), 4), temporal_range=[_r(tv.min(), 4), _r(tv.max(), 4)])


def rv2_dur():
    df = pd.read_csv(TRUTH)
    wd = {}
    for nid, name in ((41240, "Jason-3"), (54754, "SWOT"), (36508, "CryoSat-2")):
        w = df[df.norad == nid].drop_duplicates(["win_start_tai", "win_end_tai"])
        h = (pd.to_datetime(w.win_end_tai) - pd.to_datetime(w.win_start_tai)).dt.total_seconds() / 3600
        wd[name] = dict(n=int(len(h)), p10=_r(h.quantile(.1), 2), median=_r(h.median(), 2),
                        p90=_r(h.quantile(.9), 2), max=_r(h.max(), 2))
    res = {}
    for nid, name, iid in [x for x in TARGETS if x[1] in ("Jason-3", "SWOT", "CryoSat-2", "Sentinel-6A", "Jason-2")]:
        t, (a,) = load(nid)
        qs = quiets(iid)
        rr, vv = {}, {}
        for wh in (0.0, 2.5, 12.0, 24.0):
            v = np.abs(np.array([p[2] for p in pseudo_steps(t, a, qs, win_h=wh)])) * 1e3
            vv[wh] = v
            rr[f"{wh:g}h"] = dict(n=int(len(v)), q99_m=_r(np.percentile(v, 99), 2), median_m=_r(np.median(v), 3))
        base = np.percentile(vv[2.5], 99)
        for wh in vv:
            rr[f"{wh:g}h"]["exceed_at_q99_2p5h"] = _r(float((vv[wh] >= base).mean()), 4)
        offs = []
        for _ in range(5):
            o = RNG.uniform(0, 12) * 3600
            v = np.abs(np.array([p[2] for p in pseudo_steps(t, a, [(s_ + o, e_) for s_, e_ in qs])])) * 1e3
            offs.append(np.percentile(v, 99))
        rr["random_offset_q99_range_m"] = [_r(min(offs), 2), _r(max(offs), 2)]
        res[name] = rr
    return dict(window_duration_h=wd, sensitivity=res)


def rv2_nonov():
    PS = pd.read_csv(BENCH / "paperA_rv1_pseudo_steps.csv")
    far = json.loads(OUT_JSON.read_text(encoding="utf-8"))["far"]["per_sat"]
    sup = (2.5 / 24 + 2 * BR_OUT_D) * 86400
    out = {}
    for name, g in PS.groupby("sat"):
        g = g.sort_values("t")
        keep, last = [], {}
        for i, r in enumerate(g.itertuples()):
            if r.arc not in last or r.t - last[r.arc] >= sup:
                keep.append(i)
                last[r.arc] = r.t
        h = g.iloc[keep]
        v = h.step_m.abs().values
        arc = h.arc.values
        thr3 = far[name]["thr_3sres_m"]
        q99 = far[name]["q99_m"]
        ua = np.unique(arc)
        grp = {u: np.where(arc == u)[0] for u in ua}
        fb, fq = [], []
        for _ in range(NBOOT):
            idx = np.concatenate([grp[u] for u in RNG.choice(ua, len(ua))])
            fb.append((v[idx] >= thr3).mean())
            fq.append((v[idx] >= q99).mean())
        out[name] = dict(n=int(len(v)), n_arc=int(len(ua)), fap_3sres=_r((v >= thr3).mean(), 4),
                         fap_3sres_ci=[_r(np.percentile(fb, 2.5), 4), _r(np.percentile(fb, 97.5), 4)],
                         fap_q99=_r((v >= q99).mean(), 4),
                         fap_q99_ci=[_r(np.percentile(fq, 2.5), 4), _r(np.percentile(fq, 97.5), 4)])
    return dict(support_d=_r(sup / 86400, 3), per_sat=out)


def rv2_normal():
    df = pd.read_csv(TRUTH)
    recs, nullq = [], {}
    for nid, name, iid in [(54754, "SWOT", "SWOT1"), (36508, "CryoSat-2", "CRYO2")]:
        rows = con().execute("SELECT epoch_utc, inclination_deg, raan_deg, sma_km, line1, line2 FROM raw_tle_archive "
                             "WHERE norad_id=? ORDER BY epoch_utc", [nid]).fetchall()
        t = np.array([r[0].timestamp() for r in rows])
        inc = np.array([r[1] for r in rows])
        om = np.degrees(np.unwrap(np.radians([r[2] for r in rows])))
        a = np.array([r[3] for r in rows])
        L1 = [r[4] for r in rows]
        L2 = [r[5] for r in rows]
        si = math.sin(math.radians(float(np.median(inc))))
        vbar = math.sqrt(MU / float(np.median(a)))
        PI = pseudo_steps(t, inc, quiets(iid), fn=lin_step)
        PO = {(k, c): x for k, c, x in pseudo_steps(t, om, quiets(iid), fn=lin_step)}
        pairs = [(x, PO[(k, c)] * si) for k, c, x in PI if (k, c) in PO]
        di_ = np.abs([p[0] for p in pairs])
        do_ = np.abs([p[1] for p in pairs])
        tot = np.hypot(di_, do_)
        nullq[name] = dict(n=int(len(pairs)), q99_di_mdeg=_r(np.percentile(di_, 99) * 1e3, 3),
                           q99_sinidOm_mdeg=_r(np.percentile(do_, 99) * 1e3, 3),
                           q99_planechange_dvN_mm_s=_r(vbar * math.radians(np.percentile(tot, 99)) * 1e6, 1),
                           median_planechange_dvN_mm_s=_r(vbar * math.radians(np.median(tot)) * 1e6, 2))
        for (ws, we), g in df[df.norad == nid].groupby(["win_start_tai", "win_end_tai"]):
            s_ep, e_ep = tai2ep(ws), tai2ep(we)
            di = lin_step(t, inc, s_ep, e_ep)
            dO = lin_step(t, om, s_ep, e_ep)
            k0 = int(np.searchsorted(t, s_ep)) - 1
            if di is None or dO is None or k0 < 0:
                continue
            ii = math.radians(float(inc[k0]))
            pi_ref = po_ref = 0.0
            us, ok = [], True
            for _, b in g.iterrows():
                ul = arg_lat(L1[k0], L2[k0], utc2ep(b["epoch_utc"]))
                if ul is None:
                    ok = False
                    break
                u, _, vv = ul
                us.append(u)
                pi_ref += math.cos(u) * b["dv_cross"] / (vv * 1e3)
                po_ref += math.sin(u) * b["dv_cross"] / (vv * 1e3)
            if not ok:
                continue
            v = math.sqrt(MU / float(a[k0]))
            single = len(g) == 1
            dvN_single = (v * (math.cos(us[0]) * math.radians(di) + math.sin(us[0]) * math.sin(ii) * math.radians(dO)) * 1e3
                          if single else np.nan)
            recs.append(dict(sat=name, win_start_tai=ws, n_burns=len(g), single=single,
                             dvN_truth=float(g.dv_cross.sum()), dvN_abs_truth=float(g.dv_cross.abs().sum()),
                             dvN_rec_single=dvN_single,
                             ref_di_mdeg=math.degrees(pi_ref) * 1e3, ref_sinidOm_mdeg=math.degrees(po_ref) * 1e3,
                             obs_di_mdeg=di * 1e3, obs_sinidOm_mdeg=dO * math.sin(ii) * 1e3))
    D = pd.DataFrame(recs)
    D.to_csv(BENCH / "paperA_rv2_normal.csv", index=False, encoding="utf-8-sig")
    s1 = D[D.single & (D.dvN_abs_truth > 0)]
    m = D[~D.single & (D.dvN_abs_truth > 0)]
    ref_mag = np.hypot(D.ref_di_mdeg, D.ref_sinidOm_mdeg)
    return dict(null_quantiles=nullq, n_single=int(len(s1)), n_multi=int(len(m)),
                single_dvN=reg_stats(s1.dvN_truth, s1.dvN_rec_single),
                single_truth_abs_median_mm_s=_r(s1.dvN_abs_truth.median() * 1e3, 3),
                multi_di_obs_vs_ref=reg_stats(m.ref_di_mdeg / 1e3, m.obs_di_mdeg / 1e3),
                multi_sinidOm_obs_vs_ref=reg_stats(m.ref_sinidOm_mdeg / 1e3, m.obs_sinidOm_mdeg / 1e3),
                ref_planechange_max_mdeg=_r(ref_mag.max(), 4), ref_planechange_median_mdeg=_r(ref_mag.median(), 5),
                ref_di_max_mdeg=_r(D.ref_di_mdeg.abs().max(), 4), ref_sinidOm_max_mdeg=_r(D.ref_sinidOm_mdeg.abs().max(), 4),
                tle_field_quantum_mdeg=dict(inclination=0.1, raan=0.1,
                                            sini_raan_SWOT=_r(0.1 * math.sin(math.radians(77.6)), 4),
                                            sini_raan_CryoSat2=_r(0.1 * math.sin(math.radians(92.0)), 4)))


def rv2_influ():
    D = pd.read_csv(BENCH / "paperA_rv1_dv_vector.csv")
    s = D[(D.sat == "SWOT") & (D.clean == 1) & (D.dv_along_truth.abs() > 1e-6)].reset_index(drop=True)
    x = s.dv_along_truth.values
    y = s.dv_along_rec.values
    full = dict(r=_r(np.corrcoef(x, y)[0, 1]), slope=_r(np.polyfit(x, y, 1)[0]))
    loo = []
    for i in range(len(s)):
        m = np.arange(len(s)) != i
        loo.append((i, np.corrcoef(x[m], y[m])[0, 1], np.polyfit(x[m], y[m], 1)[0]))
    L = pd.DataFrame(loo, columns=["i", "r", "slope"])
    k = int(L.r.idxmax())
    w = s.iloc[k]
    det = json.loads(OUT_JSON.read_text(encoding="utf-8"))["det"]
    return dict(swot_full=full, swot_loo_r_range=[_r(L.r.min()), _r(L.r.max())],
                swot_loo_slope_range=[_r(L.slope.min()), _r(L.slope.max())],
                swot_most_influential=dict(win_start_tai=w.win_start_tai, n_burns=int(w.n_burns),
                                           truth_mm_s=_r(w.dv_along_truth * 1e3, 2), rec_mm_s=_r(w.dv_along_rec * 1e3, 2),
                                           r_without=_r(L.r[k]), slope_without=_r(L.slope[k])),
                bootstrap_unit="logged window（每窗一筆；同窗多次點火已合併）",
                jason3_cp95={k_: _cp(v_, det["n_nonzero_truth"]) for k_, v_ in det["detected_nonzero"].items()})


def rv2_aic():
    from scipy.optimize import least_squares
    d = pd.read_csv(BENCH / "tle_noise_floor_map.csv").dropna(subset=["sigma_m"]).copy()
    d["sigma_m"] = d.sigma_m.clip(lower=0.02)
    h, ls = d.alt_km.values, np.log10(d.sigma_m.values)
    n = len(ls)
    f = least_squares(lambda p: np.log10(sigma_th(h, np.abs(p))) - ls, x0=[0.05, 10.0, 120.0])
    p = np.abs(f.x)
    rss = float(np.sum(f.fun ** 2))
    gm = d.groupby("group").sigma_m.transform(lambda x: np.log10(x).mean()).values
    rss_g = float(np.sum((ls - gm) ** 2))
    rss_c = float(np.sum((ls - ls.mean()) ** 2))
    kg = d.group.nunique()

    def aic(r, k):
        return n * math.log(r / n) + 2 * (k + 1)
    return dict(likelihood="log10 σ 之獨立高斯誤差、共同變異數；參數以普通最小平方（最大概似）重估；k 含變異數",
                ols_fit=dict(sigma0_m=_r(p[0], 4), A_m=_r(p[1], 2), H_km=_r(p[2], 1)),
                aic=dict(constant=_r(aic(rss_c, 1), 1), per_group=_r(aic(rss_g, kg), 1), altitude=_r(aic(rss, 3), 1)),
                k=dict(constant=2, per_group=kg + 1, altitude=4),
                satellites=d[["group", "norad", "alt_km", "inc_deg", "sigma_m", "n_tle"]].round(3).to_dict("records"))


def sec_rv2():
    prev = json.loads(OUT_JSON.read_text(encoding="utf-8")).get("rv2", {})
    only = [x for x in sys.argv[2:]] or ["counts", "holdout", "dur", "nonov", "normal", "influ", "aic"]
    fns = dict(counts=rv2_counts, holdout=rv2_holdout, dur=rv2_dur, nonov=rv2_nonov,
               normal=rv2_normal, influ=rv2_influ, aic=rv2_aic)
    for k in only:
        prev[k] = fns[k]()
        print(f"── {k}")
        print(json.dumps({kk: vv for kk, vv in prev[k].items() if kk != "satellites"}, ensure_ascii=False, default=str)[:3000])
    save("rv2", prev)
    return prev


SECTIONS["rv2"] = sec_rv2


# ═══════════════════════════════════════════════════════════════════════════════
# rv3：第三輪審查（Review V3）補算
#   temporal  時間切分之切點日期、期間、弧段／窗數、超越次數；巢狀 bootstrap（校準弧段重抽並重估 q99）
#   cvfold    5 折交叉驗證逐折 q99、超越次數與窗數
#   gap       福衛七號群集：前後 10 天斜率、樣本數、斜率標準誤、僅用空檔前之殘差；資料庫全體物件數
#   dur33     Jason-3 窗長 3.3 h 之 q99
#   alt       高度改以 RE = 6378.137 km 重擬合；0.02 m 下限之敏感度與受影響筆數
# ═══════════════════════════════════════════════════════════════════════════════
def rv3_temporal():
    PS = pd.read_csv(BENCH / "paperA_rv1_pseudo_steps.csv")
    out = {}
    for name, g in PS.groupby("sat"):
        v = g.step_m.abs().values
        arc = g.arc.values
        start = g.groupby("arc").t.min().sort_values()
        order = start.index.values
        half = len(order) // 2
        cal_arcs, val_arcs = order[:half], order[half:]
        cal = np.isin(arc, cal_arcs)
        val = ~cal
        q = np.percentile(v[cal], 99)
        k = int((v[val] >= q).sum())
        gc = {u: np.where(arc == u)[0] for u in cal_arcs}
        gv = {u: np.where(arc == u)[0] for u in val_arcs}
        nest = []
        for _ in range(NBOOT):
            ic = np.concatenate([gc[u] for u in RNG.choice(cal_arcs, len(cal_arcs))])
            iv = np.concatenate([gv[u] for u in RNG.choice(val_arcs, len(val_arcs))])
            nest.append((v[iv] >= np.percentile(v[ic], 99)).mean())
        f = lambda x: dt.datetime.fromtimestamp(x).strftime("%Y-%m-%d")
        tcal_end = g[cal].t.max()
        tval_start = g[val].t.min()
        out[name] = dict(cut_date=f(tval_start), cal_period=[f(g[cal].t.min()), f(tcal_end)],
                         val_period=[f(tval_start), f(g[val].t.max())],
                         n_arc_cal=int(half), n_arc_val=int(len(order) - half),
                         n_win_cal=int(cal.sum()), n_win_val=int(val.sum()), q99_cal_m=_r(q, 2),
                         exceed_count=k, exceed_rate=_r(k / int(val.sum()), 4),
                         nested_ci=[_r(np.percentile(nest, 2.5), 4), _r(np.percentile(nest, 97.5), 4)],
                         n_val_arcs_with_exceed=int(len({a_ for a_ in arc[val][v[val] >= q]})))
    return out


def rv3_cvfold():
    PS = pd.read_csv(BENCH / "paperA_rv1_pseudo_steps.csv")
    rng = np.random.default_rng(20261118)
    out = {}
    for name, g in PS.groupby("sat"):
        v = g.step_m.abs().values
        arc = g.arc.values
        folds = np.array_split(rng.permutation(np.unique(arc)), 5)
        rows = []
        for f_ in folds:
            te = np.isin(arc, f_)
            q = np.percentile(v[~te], 99)
            rows.append(dict(n_arc=int(len(f_)), n_win=int(te.sum()), q99_m=_r(q, 2), exceed=int((v[te] >= q).sum())))
        K = sum(r["exceed"] for r in rows)
        N = sum(r["n_win"] for r in rows)
        out[name] = dict(folds=rows, exceed=K, n=N, rate=_r(K / N, 4))
    return out


def rv3_gap():
    rows = []
    for n, nm in [(44349, "7-1"), (44351, "7-2"), (44343, "7-3"), (44350, "7-4"), (44358, "7-5"), (44353, "7-6")]:
        r = con().execute("select epoch_utc, sma_km from raw_tle_archive where norad_id=? and epoch_utc>='2025-11-01' "
                          "and epoch_utc<'2026-11-18' order by 1", [n]).fetchdf().drop_duplicates("epoch_utc").reset_index(drop=True)
        t = (r.epoch_utc - r.epoch_utc[0]).dt.total_seconds().values / 86400
        a = r.sma_km.values * 1000
        for lab, a0, b0 in [("Jan", "2025-12-30", "2026-01-03"), ("Mar/Apr", "2026-03-30", "2026-04-03"),
                            ("Apr", "2026-04-15", "2026-04-20"), ("Jun", "2026-06-03", "2026-06-08")]:
            w = r[(r.epoch_utc >= a0) & (r.epoch_utc < b0)].index
            d = np.diff(a)
            k = w[np.argmin(d[w - 1])]
            gap = t[k] - t[k - 1]
            mp = (t >= t[k - 1] - 10) & (t <= t[k - 1])
            mq = (t >= t[k]) & (t <= t[k] + 10)

            def fit(m):
                x, y = t[m], a[m]
                c_, cov = np.polyfit(x, y, 1, cov=True)
                return c_[0], math.sqrt(cov[0, 0]), int(m.sum())
            rp, sp, npre = fit(mp)
            rq, sq, npost = fit(mq)
            raw = d[k - 1]
            rows.append(dict(sat=nm, event=lab, before=str(r.epoch_utc[k - 1])[:16], after=str(r.epoch_utc[k])[:16],
                             gap_d=round(gap, 2), raw_m=round(raw, 1), rate_pre=round(rp, 1), se_pre=round(sp, 1), n_pre=npre,
                             rate_post=round(rq, 1), se_post=round(sq, 1), n_post=npost,
                             resid_prepost=round(raw - 0.5 * (rp + rq) * gap, 1), resid_preonly=round(raw - rp * gap, 1)))
    D = pd.DataFrame(rows)
    D.to_csv(BENCH / "paperA_rv3_fs7_gap.csv", index=False, encoding="utf-8-sig")
    med = D.groupby("event", sort=False).agg(raw_abs=("raw_m", lambda x: x.abs().median()),
                                             res_abs=("resid_prepost", lambda x: x.abs().median()),
                                             res_pre_abs=("resid_preonly", lambda x: x.abs().median()))
    cnt = {}
    for a0, b0, lab in [("2026-04-12", "2026-04-17", "Apr gap"), ("2026-04-01", "2026-04-06", "reference 5 d"),
                        ("2026-03-30", "2026-03-31", "Mar gap 1 d"), ("2025-12-31", "2026-01-01", "Jan gap 1 d"),
                        ("2026-05-20", "2026-05-21", "reference 1 d")]:
        cnt[lab] = int(con().execute("select count(distinct norad_id) from raw_tle_archive where epoch_utc>=? and epoch_utc<?",
                                     [a0, b0]).fetchone()[0])
    return dict(rows=D.to_dict("records"), cluster_median_abs=med.round(1).reset_index().to_dict("records"),
                archive_objects_with_tles=cnt,
                post_gap_download="FORMOSAT-7-1 之 2026-04-18 元素集於 2026-05-02 15:47 UTC 回補下載")


def rv3_dur33():
    t, (a,) = load(41240)
    out = {}
    for wh in (2.5, 3.3):
        v = np.abs([p[2] for p in pseudo_steps(t, a, quiets("JASO3"), win_h=wh)]) * 1e3
        out[f"{wh}h"] = _r(np.percentile(v, 99), 3)
    return out


def rv3_alt():
    d0 = pd.read_csv(BENCH / "tle_noise_floor_map.csv").dropna(subset=["sigma_m"]).copy()
    d0["alt_km"] = d0.alt_km - (RE - 6371.0)            # 原 CSV 高度以 6371 km 計 → 改以 6378.137 km
    res = {}
    for floor in (0.02, 0.01, 0.005):
        d = d0.copy()
        n_aff = int((d.sigma_m < floor).sum())
        d["sigma_m"] = d.sigma_m.clip(lower=floor)
        h, s = d.alt_km.values, d.sigma_m.values
        p, r2, rr = fit_alt(h, s)
        B = []
        for _ in range(NBOOT if floor == 0.02 else 500):
            i = RNG.integers(0, len(d), len(d))
            B.append(fit_alt(h[i], s[i])[0])
        B = np.array(B)
        ci = {k: [_r(np.percentile(B[:, j], 2.5), 3), _r(np.percentile(B[:, j], 97.5), 3)]
              for j, k in enumerate(("sigma0_m", "A_m", "H_km"))}
        s800 = sigma_th(800.0, B.T)
        res[str(floor)] = dict(n_affected=n_aff, fit=dict(sigma0_m=_r(p[0], 4), A_m=_r(p[1], 2), H_km=_r(p[2], 2), R2_log=_r(r2, 4)),
                               ci95=ci, s800_m=_r(sigma_th(800.0, p), 3),
                               s800_ci=[_r(np.percentile(s800, 2.5), 3), _r(np.percentile(s800, 97.5), 3)])
    d = d0.copy()
    d["sigma_m"] = d.sigma_m.clip(lower=0.02)
    h, s = d.alt_km.values, d.sigma_m.values
    groups = {}
    for g_ in d.group.unique():
        m = d.group != g_
        pg, r2g, _ = fit_alt(h[m], s[m])
        groups[g_] = dict(H_km=_r(pg[2], 1), A_m=_r(pg[1], 2), s800_m=_r(sigma_th(800.0, pg), 3))
    from scipy.optimize import least_squares
    ls = np.log10(s)
    n = len(ls)
    f = least_squares(lambda q: np.log10(sigma_th(h, np.abs(q))) - ls, x0=[0.05, 10.0, 120.0])
    rss = float(np.sum(f.fun ** 2))
    gm = d.groupby("group").sigma_m.transform(lambda x: np.log10(x).mean()).values
    aic = lambda r_, k: n * math.log(r_ / n) + 2 * (k + 1)
    return dict(reference_radius_km=RE, alt_range_km=[_r(h.min(), 0), _r(h.max(), 0)], by_floor=res,
                leave_group_out=groups,
                aic=dict(constant=_r(aic(float(np.sum((ls - ls.mean()) ** 2)), 1), 1),
                         per_group=_r(aic(float(np.sum((ls - gm) ** 2)), d.group.nunique()), 1),
                         altitude=_r(aic(rss, 3), 1), ols_H_km=_r(np.abs(f.x)[2], 1)),
                satellites=d[["group", "norad", "alt_km", "inc_deg", "sigma_m", "n_tle"]].round(3).to_dict("records"))


def sec_rv3():
    prev = json.loads(OUT_JSON.read_text(encoding="utf-8")).get("rv3", {})
    only = sys.argv[2:] or ["temporal", "cvfold", "gap", "dur33", "alt"]
    fns = dict(temporal=rv3_temporal, cvfold=rv3_cvfold, gap=rv3_gap, dur33=rv3_dur33, alt=rv3_alt)
    for k in only:
        prev[k] = fns[k]()
        print(f"── {k}")
        print(json.dumps({kk: vv for kk, vv in (prev[k].items() if isinstance(prev[k], dict) else [])
                          if kk not in ("satellites", "rows")}, ensure_ascii=False, default=str)[:3500])
    save("rv3", prev)
    return prev


SECTIONS["rv3"] = sec_rv3


if __name__ == "__main__":
    args = sys.argv[1:] or [k for k in SECTIONS if k not in ("rv2", "rv3")]
    if args[0] in ("rv2", "rv3"):
        args = [args[0]]
    for a_ in args:
        print(f"\n══════ {a_} ══════")
        SECTIONS[a_]()
