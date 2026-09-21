#!/usr/bin/env python3
"""
three_layer_candidate_eval.py
=============================
「候選確認式」L3 與 L1／L2 在同一批衛星、同一套事件級指標（tasa14_l2_compare.metrics：
容差 1.5 天、一對一貪婪配對）上的並排比較。三個評估集：

  A. 非 Starlink 23 星（NASA/ILRS 認證機動窗；L3 為逐星留一 LOSO，θ 於訓練星選定）
  B. Starlink 283 顆（MEME medium+ 轉移；L3 為衛星分組 5 折 OOF）
  C. 福衛七號 6 顆（精密星曆推估之「疑似真事件」弱真值；L3 為部署模型，全程未參與訓練與選門檻）

方法（每顆衛星各算一組偵測 epoch，再與真值比）：
  L1        P1–P6 combined 旗標之轉換 epoch（maneuver_strategies_july，含 2026-09-21 步階護欄）
  L2 各通道  CUSUM／BOCPD／SSA／MAD 3σ 之事件（取自候選之來源旗標）；L2 聯集＝任一通道
  候選全接受 iter2 ∪ pred ∪ L2 之全部候選（＝L3 的輸入，未經確認）→ 顯示 L3「確認」步驟的增益
  L3        對候選逐一確認（機率 ≥ θ）

輸出：data/benchmark/three_layer_candidate_eval_<date>.csv（彙總）、…_persat_<date>.csv（逐星）
用法：python three_layer_candidate_eval.py
"""
from __future__ import annotations

import glob
import sys
from datetime import datetime, timezone

import duckdb
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import l3_candidate as C
import maneuver_strategies_july as ms
import tasa14_l2_compare as l2
from tasa14_compare import load_a
from tasa23_ext_arena import load_events_ext2

STAMP = datetime.now(timezone.utc).strftime("%Y%m%d")
HGB = dict(max_iter=250, learning_rate=0.08, random_state=42)
CH_SRC = {"CUSUM": "src_cusum", "BOCPD": "src_bocpd", "SSA": "src_ssa", "MAD3σ": "src_mad3sig"}


def _f107():
    try:
        f = pd.read_csv("f107_cache.csv")
        f["epoch"] = pd.to_datetime(f["epoch"]).dt.strftime("%Y-%m-%d")
        return dict(zip(f["epoch"], f["f107"]))
    except Exception:
        return {}


F107 = _f107()
_CON = None


def l1_dets(nid):
    """P1–P6 combined 旗標之轉換 epoch（同 3 h 稀釋序列），1 天內合併。"""
    global _CON
    if _CON is None:
        _CON = duckdb.connect("space_db.duckdb", read_only=True)
    df = _CON.execute("SELECT epoch_utc AS epoch, sma_km, inclination_deg, eccentricity, raan_deg, bstar "
                      "FROM raw_tle_archive WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc", [int(nid)]).fetchdf()
    if len(df) < 20:
        return pd.DatetimeIndex([], tz="UTC")
    df["epoch"] = pd.DatetimeIndex(pd.to_datetime(df["epoch"], utc=True)).as_unit("ns")
    ts = df["epoch"].astype("int64").to_numpy() / 1e9
    keep = [0]
    for i in range(1, len(ts)):
        if ts[i] - ts[keep[-1]] >= 3.0 * 3600:
            keep.append(i)
    df = df.iloc[keep].reset_index(drop=True)
    tr = ms.build_transitions(df, F107 or None)
    if tr.empty:
        return pd.DatetimeIndex([], tz="UTC")
    orbit = ms.classify_orbit(float(df.sma_km.iloc[-1]), float(df.eccentricity.iloc[-1]), float(df.inclination_deg.iloc[-1]))
    comb = np.asarray(ms.apply_strategies(tr, orbit)["combined"], bool)
    return l2.merge_epochs(list(pd.to_datetime(tr["epoch"], utc=True)[comb]), C.CAND_MERGE_D)


def merged(sub, mask=None):
    e = sub["epoch"] if mask is None else sub.loc[mask, "epoch"]
    return l2.merge_epochs(list(e), C.CAND_MERGE_D)


def score_set(dets_by_method, ev, lo, hi):
    ev = ev[(ev["ws"] >= lo) & (ev["ws"] <= hi)].reset_index(drop=True)
    return {m: l2.metrics(d, ev, lo, hi) for m, d in dets_by_method.items()}


def methods_for(sub, nid, proba, theta):
    d = {"L1 規則 P1–P6": l1_dets(nid)}
    for lab, col in CH_SRC.items():
        d[f"L2 {lab}"] = merged(sub, sub[col] == 1)
    d["L2 聯集（任一通道）"] = merged(sub, (sub[list(CH_SRC.values())].sum(axis=1) > 0))
    d["候選全接受（無 L3）"] = merged(sub)
    d["L3 候選確認"] = merged(sub, proba >= theta)
    return d


def summarize(rows, family):
    df = pd.DataFrame(rows)
    g = df.groupby("method").agg(n_sats=("norad", "nunique"), precision=("precision", "mean"),
                                 recall=("recall", "mean"), f1=("f1", "mean")).reset_index()
    g.insert(0, "family", family)
    return df.assign(family=family), g


# ── A. 非 Starlink 23 星（LOSO）──────────────────────────────────────────────
def eval_altimetry():
    feat = sorted(glob.glob("data/benchmark/l3_altimetry_features_*.csv"))[-1]
    loso = pd.read_csv(sorted(glob.glob("data/benchmark/l3_altimetry_loso_*.csv"))[-1]).set_index("norad")
    df = pd.read_csv(feat)
    df["epoch"] = pd.to_datetime(df["epoch"], utc=True, format="mixed")
    events = load_events_ext2()
    rows = []
    for n in sorted(df.norad.unique()):
        tr = df[df.norad != n]
        te = df[df.norad == n]
        clf = HistGradientBoostingClassifier(**HGB).fit(tr[C.FEATS], tr["label"])
        proba = clf.predict_proba(te[C.FEATS])[:, 1]
        t, _ = load_a(int(n))
        ev = events[int(n)]
        lo, hi = max(t.min(), ev["ws"].min()), min(t.max(), ev["we"].max())
        res = score_set(methods_for(te, int(n), proba, float(loso.loc[n, "theta"])), ev, lo, hi)
        for m, r in res.items():
            rows.append(dict(norad=int(n), name=te["name"].iloc[0], method=m, **r))
        print(f"  A {te['name'].iloc[0]:14s} L3 F1={res['L3 候選確認']['f1']:.3f}  L1={res['L1 規則 P1–P6']['f1']:.3f}  全接受={res['候選全接受（無 L3）']['f1']:.3f}", flush=True)
    return summarize(rows, "非Starlink 23星（NASA/ILRS，LOSO）")


# ── B. Starlink（OOF）──────────────────────────────────────────────────────────
def eval_starlink():
    import train_l3_starlink as TS
    feat = sorted(glob.glob("data/benchmark/starlink_candidate_features_*.csv"))[-1]
    df = pd.read_csv(feat)
    df["epoch"] = pd.to_datetime(df["epoch"], utc=True, format="mixed")
    events = TS.sat_events(df)
    M = joblib.load("models_fusion/l3_starlink.pkl")
    theta = float(M["theta"]["dense"])
    d = df[df.norad.map(lambda n: len(events[int(n)]) > 0)].reset_index(drop=True)
    oof = np.zeros(len(d))
    for tr, te in GroupKFold(5).split(d, d.label, d.norad):
        oof[te] = HistGradientBoostingClassifier(**HGB).fit(d.iloc[tr][C.FEATS], d.iloc[tr]["label"]).predict_proba(d.iloc[te][C.FEATS])[:, 1]
    d["oof"] = oof
    rows = []
    for k, (n, g) in enumerate(d.groupby("norad")):
        lo = pd.to_datetime(g["t_first"].iloc[0], utc=True)
        hi = pd.to_datetime(g["t_last"].iloc[0], utc=True)
        res = score_set(methods_for(g, int(n), g["oof"].to_numpy(), theta), events[int(n)], lo, hi)
        for m, r in res.items():
            rows.append(dict(norad=int(n), name=g["name"].iloc[0], method=m, **r))
        if (k + 1) % 50 == 0:
            print(f"  B {k + 1} 顆", flush=True)
    return summarize(rows, "Starlink 283顆（MEME，OOF）")


# ── C. 福衛七號（樣本外，弱真值）───────────────────────────────────────────────
def eval_fs7():
    from formosat7_leoorb.satmap import SP3_TO_NAME, SP3_TO_NORAD
    from fs7_curve_method_vs_precise_truth import load_truth_events
    M = joblib.load("models_fusion/l3_altimetry.pkl")
    events = load_truth_events()
    rows = []
    for sp3, nid in SP3_TO_NORAD.items():
        if nid not in events:
            continue
        t, a = load_a(nid)
        if t is None or len(a) < 60:
            continue
        d = C.build_candidates(t, a)
        if d.empty:
            continue
        cls = C.cadence_class(float(d.cadence_d.iloc[0]))
        proba = M["clf"].predict_proba(d[C.FEATS])[:, 1]
        res = score_set(methods_for(d, nid, proba, float(M["theta"][cls])), events[nid], t.min(), t.max())
        for m, r in res.items():
            rows.append(dict(norad=nid, name=SP3_TO_NAME[sp3], method=m, **r))
        print(f"  C {SP3_TO_NAME[sp3]:10s} [{cls}] L3 F1={res['L3 候選確認']['f1']:.3f}  L1={res['L1 規則 P1–P6']['f1']:.3f}  全接受={res['候選全接受（無 L3）']['f1']:.3f}", flush=True)
    return summarize(rows, "福衛七號 6顆（精密星曆弱真值，樣本外）")


def main():
    pers, sums = [], []
    for fn in (eval_altimetry, eval_starlink, eval_fs7):
        p, s = fn()
        pers.append(p)
        sums.append(s)
        print("\n" + s.round(3).to_string(index=False) + "\n", flush=True)
    per = pd.concat(pers, ignore_index=True)
    summ = pd.concat(sums, ignore_index=True)
    per.to_csv(f"data/benchmark/three_layer_candidate_eval_persat_{STAMP}.csv", index=False, encoding="utf-8-sig")
    summ.to_csv(f"data/benchmark/three_layer_candidate_eval_{STAMP}.csv", index=False, encoding="utf-8-sig")
    print(f"→ data/benchmark/three_layer_candidate_eval_{STAMP}.csv")


if __name__ == "__main__":
    main()
