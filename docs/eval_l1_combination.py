#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_l1_combination.py — 以大樣本比較 L1 規則之組合方式（P2／P5／P6／其他根數／P4）。

變體（皆含「其他根數」Δi／Δe／ΔΩ 標記與 P1／P3 抑制；超過門檻之轉換不受抑制）：
  A 舊版聯集    ：門檻＝P2（舊版 P2∪P5∪P6 聯集等同 P2），P4＝標記點及其後 2 筆
  B 現行        ：門檻＝P2×P5×P6（P5 上限 1.8），P4＝標記點及其後 2 筆
  C 現行去 P4   ：門檻＝P2×P5×P6，無 P4
  D 現行 P4 累積：門檻＝P2×P5×P6，P4＝連續 3 筆轉換之淨 Δa 超過門檻時標記該 3 筆
  E P2 單獨     ：門檻＝P2，無 P4

樣本：
  meme：MEME 真值 Starlink（transitions_full_20260918，283 顆、MEME 覆蓋期間）→ 真值事件召回
  ids ：IDS 營運方點火與認證安靜期（15 顆、完整 TLE 歷史）→ 安靜期誤報、可見點火召回
  neg ：LEO 火箭箭體（名稱含 R/B，近地點 250–1200 km、離心率 < 0.02，近 365 天 TLE ≥ 60 筆）
        → 無推進物體之事件數即為誤報（可能含解體等少數真實變化）

用法：python docs/eval_l1_combination.py [meme|ids|neg|all] [neg 抽樣數，預設 300]
輸出：data/benchmark/l1_combination_<sample>.csv 與終端摘要
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SSA_RAG_URL", "http://127.0.0.1:9")
import maneuver_report_builder as rb  # noqa: E402
import maneuver_strategies_july as ms  # noqa: E402

PAD = pd.Timedelta(hours=24)
VARIANTS = {"A": ("p2", "neighbor"), "B": ("eff", "neighbor"), "C": ("eff", "none"),
            "D": ("eff", "cumulative"), "E": ("p2", "none")}
LABEL = {"A": "舊版聯集（≡P2）＋P4 鄰近", "B": "現行 P2×P5×P6＋P4 鄰近", "C": "P2×P5×P6，無 P4",
         "D": "P2×P5×P6＋P4 累積", "E": "P2 單獨，無 P4"}


def combine(tr: pd.DataFrame, orbit_class: str, thr_mode: str, p4_mode: str) -> np.ndarray:
    n = len(tr)
    if n == 0:
        return np.zeros(0, bool)
    da = tr["da_km"].to_numpy(float)
    alt = tr["alt_km"].to_numpy(float)
    bstar = tr["bstar"].to_numpy(float)
    f107 = tr["f107"].to_numpy(float)
    thr_p2 = ms.DEFAULT_P2(alt)
    if orbit_class in ("MEO", "GEO", "GEO+", "HEO"):
        thr = np.full(n, 0.05) if thr_mode == "eff" else thr_p2
    elif thr_mode == "eff":
        mult = np.where(np.isnan(f107), 1.0, ms.DEFAULT_P5(np.nan_to_num(f107, nan=ms.DEFAULT_P5.vertex)))
        mult = np.clip(mult, 1.0, ms.P5_MULT_MAX)
        fam = ms.inc_family(float(np.nanmedian(tr["inc_deg"])))
        thr = thr_p2 * mult * ms.DEFAULT_P6.get(fam, 1.0)
    else:
        thr = thr_p2
    flag = np.abs(da) > thr
    other = ((np.abs(tr["di_deg"].to_numpy(float)) > ms.THR_DI) | (np.abs(tr["de"].to_numpy(float)) > ms.THR_DE)
             | (np.abs(tr["draan_res_deg"].to_numpy(float)) > ms.THR_DRAAN))
    # P1／P3 抑制（與 apply_strategies 相同）
    sup = np.zeros(n, bool)
    for i in range(n):
        seg = da[max(0, i - 4):i + 1]
        if len(seg) >= 4 and np.mean(seg < 0.1) >= 0.85 and np.all(np.abs(seg) < 2.0) \
                and not np.isnan(bstar[i]) and bstar[i] > 0:
            sup[i] = True
    vb = bstar[~np.isnan(bstar)]
    hi = np.nanmedian(vb) + 2 * np.nanstd(vb) if len(vb) else np.inf
    sup |= (~np.isnan(bstar)) & (bstar > max(hi, 5e-4)) & (da < 0) & (np.abs(da) < 1.5)
    sup &= ~flag
    base = flag | other
    p4 = np.zeros(n, bool)
    if p4_mode == "neighbor":
        for i in range(n):
            if base[max(0, i - 2):i + 1].any():
                p4[i] = True
    elif p4_mode == "cumulative":
        for i in range(2, n):
            if abs(da[i - 2:i + 1].sum()) > thr[i] and not flag[i - 2:i + 1].any():
                p4[i - 2:i + 1] = True
    return (base | p4) & ~sup


def prep(nid, d0=None, d1=None):
    df = rb.load_tle(int(nid)).sort_values("epoch", kind="stable").reset_index(drop=True)
    if d0 is not None:
        df = df[(df["epoch"] >= d0) & (df["epoch"] <= d1)].reset_index(drop=True)
    df = df[~((df["epoch"].shift(-1) - df["epoch"]).dt.total_seconds() < 1.0)].reset_index(drop=True)
    if len(df) < 20:
        return None
    oc = ms.classify_orbit(float(df["sma_km"].iloc[0]), float(df["eccentricity"].iloc[0]),
                           float(df["inclination_deg"].iloc[0]))
    tr = ms.build_transitions(df, F107)
    return df, tr, oc


def events_for(df, tr, comb):
    return rb.build_candidate_events(df, tr, comb, {}, None, None, None)


def run_meme():
    T = pd.read_csv(ROOT / "data/meme_truth/transitions_full_20260918.csv", parse_dates=["t_from", "t_to"])
    rows = []
    for k, (nid, g) in enumerate(T.groupby("norad_id"), 1):
        w0, w1 = g["t_from"].min(), g["t_to"].max()
        eps = []
        for _, x in g[g["label_meme"] == 1].sort_values("t_from").iterrows():
            if eps and x["t_from"] - eps[-1][1] <= pd.Timedelta(hours=48):
                eps[-1][1] = max(eps[-1][1], x["t_to"]); eps[-1][2] = max(eps[-1][2], abs(x["da_km"]))
            else:
                eps.append([x["t_from"], x["t_to"], abs(x["da_km"])])
        p = prep(nid, w0, w1)
        if p is None:
            continue
        df, tr, oc = p
        days = (df["epoch"].iloc[-1] - df["epoch"].iloc[0]).total_seconds() / 86400
        row = {"norad": int(nid), "days": days, "n_ep": len(eps), "n_ep_large": sum(e[2] >= 10 for e in eps)}
        for v, (tm, pm) in VARIANTS.items():
            c = combine(tr, oc, tm, pm)
            ev = events_for(df, tr, c)
            cov = [any(x["t_start"] - PAD <= e[1] and e[0] <= x["t_end"] + PAD for x in ev) for e in eps]
            row[f"{v}_pts"] = int(c.sum()); row[f"{v}_ev"] = len(ev); row[f"{v}_cov"] = sum(cov)
            row[f"{v}_cov_large"] = sum(cv for cv, e in zip(cov, eps) if e[2] >= 10)
        rows.append(row)
        if k % 50 == 0:
            print("meme", k, flush=True)
    return pd.DataFrame(rows)


def run_ids():
    tru = pd.read_csv("ids_truth_set/ids_truth.csv")
    qui = pd.read_csv("ids_truth_set/ids_quiet.csv")
    for c in ("win_start_tai", "win_end_tai"):
        tru[c] = pd.to_datetime(tru[c], utc=True)
    for c in ("quiet_start_tai", "quiet_end_tai"):
        qui[c] = pd.to_datetime(qui[c], utc=True)
    rows = []
    for nid in sorted(qui["norad"].dropna().unique()):
        q, t = qui[qui["norad"] == nid], tru[tru["norad"] == nid]
        p = prep(nid)
        if p is None:
            continue
        df, tr, oc = p
        qs = [(a + PAD, b - PAD) for a, b in zip(q["quiet_start_tai"], q["quiet_end_tai"]) if b - a > 2 * PAD]
        qd = sum((b - a).total_seconds() for a, b in qs) / 86400
        w = t.groupby(["win_start_tai", "win_end_tai"]).agg(vis=("tle_visible_50", "max")).reset_index()
        vis = w[w["vis"] == 1]
        row = {"norad": int(nid), "name": q["name"].iloc[0], "quiet_days": qd, "burn_vis": len(vis)}
        for v, (tm, pm) in VARIANTS.items():
            c = combine(tr, oc, tm, pm)
            ev = events_for(df, tr, c)
            row[f"{v}_ev"] = len(ev)
            row[f"{v}_fp"] = sum(any(a <= e["t_end"] and e["t_start"] <= b for a, b in qs) for e in ev)
            row[f"{v}_det"] = sum(any(e["t_start"] <= r["win_end_tai"] + PAD and r["win_start_tai"] - PAD <= e["t_end"]
                                      for e in ev) for _, r in vis.iterrows())
        rows.append(row)
        print("ids", nid, flush=True)
    return pd.DataFrame(rows)


def run_neg(n_sats):
    import duckdb
    con = duckdb.connect(rb.DB_PATH, read_only=True)
    meta = con.execute("SELECT norad_id, name_en, perigee_km, apogee_km FROM sat_n2yo_metadata "
                       "WHERE name_en LIKE '%R/B%' AND perigee_km BETWEEN 250 AND 1200 AND apogee_km < 1500").df()
    con.close()
    rng = np.random.default_rng(20261115)
    ids = list(meta["norad_id"].sample(frac=1.0, random_state=20261115))
    end = pd.Timestamp("2026-11-14", tz="UTC")
    rows = []
    for nid in ids:
        if len(rows) >= n_sats:
            break
        try:
            p = prep(nid, end - pd.Timedelta(days=365), end)
        except Exception:
            continue
        if p is None or len(p[0]) < 60:
            continue
        df, tr, oc = p
        if float(df["eccentricity"].median()) >= 0.02:
            continue
        days = (df["epoch"].iloc[-1] - df["epoch"].iloc[0]).total_seconds() / 86400
        row = {"norad": int(nid), "days": days, "alt": float(df["sma_km"].median() - 6378.137)}
        for v, (tm, pm) in VARIANTS.items():
            c = combine(tr, oc, tm, pm)
            row[f"{v}_pts"] = int(c.sum()); row[f"{v}_ev"] = len(events_for(df, tr, c))
        rows.append(row)
        if len(rows) % 50 == 0:
            print("neg", len(rows), flush=True)
    return pd.DataFrame(rows)


def summary(name, R):
    print(f"\n=== {name} ===")
    if name == "meme":
        sd, ne, nl = R["days"].sum(), R["n_ep"].sum(), R["n_ep_large"].sum()
        print(f"{len(R)} 顆、{sd:.0f} 星日；真值事件 {ne}（large {nl}）")
        for v in VARIANTS:
            print(f"  {v} {LABEL[v]}：事件 {R[v+'_ev'].sum()}（每千星日 {R[v+'_ev'].sum()/sd*1000:.1f}）、候選點 {R[v+'_pts'].sum()}；"
                  f"召回 {R[v+'_cov'].sum()/ne:.3f}、large 召回 {R[v+'_cov_large'].sum()/max(nl,1):.3f}")
    elif name == "ids":
        qd, bv = R["quiet_days"].sum(), R["burn_vis"].sum()
        print(f"{len(R)} 顆、安靜期 {qd:.0f} 星日、可見點火 {bv}")
        for v in VARIANTS:
            print(f"  {v} {LABEL[v]}：事件 {R[v+'_ev'].sum()}；安靜期誤報 {R[v+'_fp'].sum()}（每千 {R[v+'_fp'].sum()/qd*1000:.2f}）；"
                  f"可見點火召回 {R[v+'_det'].sum()}/{bv}")
    else:
        sd = R["days"].sum()
        print(f"{len(R)} 顆 LEO 火箭箭體、{sd:.0f} 星日（無推進，事件即誤報）")
        for v in VARIANTS:
            print(f"  {v} {LABEL[v]}：事件 {R[v+'_ev'].sum()}（每千星日 {R[v+'_ev'].sum()/sd*1000:.2f}）、候選點 {R[v+'_pts'].sum()}；"
                  f"有事件之箭體 {(R[v+'_ev']>0).sum()} 顆")


F107 = rb.load_f107()

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    nneg = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    out = ROOT / "data/benchmark"
    for name, fn in (("meme", run_meme), ("ids", run_ids), ("neg", lambda: run_neg(nneg))):
        if which in (name, "all"):
            R = fn()
            R.to_csv(out / f"l1_combination_{name}.csv", index=False, encoding="utf-8-sig")
            summary(name, R)
