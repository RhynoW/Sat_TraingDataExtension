#!/usr/bin/env python3
"""
train_l3_starlink.py
====================
訓練「候選確認式」L3（Starlink 族群）：與 train_l3_altimetry.py 同一套候選產生與 10 個 σ 正規化特徵
（l3_candidate.py），真值改用 MEME 精密星曆的 medium+ 機動轉移（data/meme_truth）。

標籤：候選落在任一 MEME medium+ 轉移 ±1.5 天內 → 1（與非 Starlink 版的配對容差 TOL_D=1.5 天一致）。
評估：衛星分組 GroupKFold(5) → OOF 機率；決策門檻 θ 於 OOF 上以平均 F1 選定（事件級 P/R/F1，
同 tasa14_l2_compare.metrics）。Starlink 更新頻率相近，僅一個 θ。

輸出：models_fusion/l3_starlink.pkl、data/benchmark/starlink_candidate_features_<date>.csv、
      data/benchmark/l3_starlink_oof_<date>.csv
用法：python train_l3_starlink.py [--rebuild]
"""
from __future__ import annotations

import glob
import sys
from datetime import datetime, timezone
from pathlib import Path

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
import tasa14_l2_compare as l2
from compare_tle_vs_ephemeris import load_registry
from satdet import config, episodes_by_sat

STAMP = datetime.now(timezone.utc).strftime("%Y%m%d")
FEAT_CSV = Path(f"data/benchmark/starlink_candidate_features_{STAMP}.csv")
OUT_MODEL = "models_fusion/l3_starlink.pkl"
TOL = pd.Timedelta(days=1.5)
THETA_GRID = np.arange(0.10, 0.91, 0.05)
HGB = dict(max_iter=250, learning_rate=0.08, random_state=42)


def build(rebuild=False):
    old = sorted(glob.glob("data/benchmark/starlink_candidate_features_*.csv"))
    if old and not rebuild:
        d = pd.read_csv(old[-1])
        d["epoch"] = pd.to_datetime(d["epoch"], utc=True, format="mixed")
        print(f"載入快取 {old[-1]}", flush=True)
        return d
    tp = sorted(glob.glob("data/meme_truth/transitions_full_*.csv"))[-1]
    truth = pd.read_csv(tp)
    truth["t_to"] = pd.to_datetime(truth["t_to"], utc=True, format="ISO8601")
    eps_by = episodes_by_sat(truth)
    reg = load_registry("data/url_registry.csv")
    n2n = {v: k for k, v in reg["sat_name"].items()}
    con = duckdb.connect(config.SPACE_DB, read_only=True)
    rows = []
    for i, (name, nid) in enumerate(n2n.items()):
        df = con.execute("SELECT epoch_utc AS epoch, sma_km FROM raw_tle_archive "
                         "WHERE norad_id=? AND sma_km IS NOT NULL ORDER BY epoch_utc", [int(nid)]).fetchdf()
        if len(df) < 60:
            continue
        t, a = C.to_series(df)
        if len(a) < 60:
            continue
        d = C.build_candidates(t, a)
        if d.empty:
            continue
        ev_t = np.concatenate([tt for tt, _ in eps_by.get(int(nid), [])]) if eps_by.get(int(nid)) else np.array([], dtype="int64")
        ev = pd.to_datetime(ev_t, utc=True) if len(ev_t) else pd.DatetimeIndex([], tz="UTC")
        cn = d["epoch"].astype("int64").to_numpy()
        en = ev.as_unit("ns").astype("int64").to_numpy() if len(ev) else np.array([], dtype="int64")
        d["label"] = [int(len(en) > 0 and np.min(np.abs(en - c)) <= TOL.value) for c in cn]
        d["norad"], d["name"] = int(nid), name
        d["t_first"], d["t_last"] = t.min(), t.max()
        rows.append(d)
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(n2n)} 顆，累計候選 {sum(len(r) for r in rows)}", flush=True)
    con.close()
    out = pd.concat(rows, ignore_index=True)
    out.to_csv(FEAT_CSV, index=False, encoding="utf-8-sig")
    print(f"→ {FEAT_CSV}（{len(out)} 候選、{out.norad.nunique()} 顆、正例率 {out.label.mean():.2f}）", flush=True)
    return out


def sat_events(df):
    """每顆衛星的真值事件表（ws=we=MEME 轉移時刻；同 1 天內合併）。"""
    tp = sorted(glob.glob("data/meme_truth/transitions_full_*.csv"))[-1]
    truth = pd.read_csv(tp)
    truth["t_to"] = pd.to_datetime(truth["t_to"], utc=True, format="ISO8601")
    eps_by = episodes_by_sat(truth)
    out = {}
    for nid in df.norad.unique():
        tt = eps_by.get(int(nid), [])
        ts = pd.to_datetime(np.concatenate([x for x, _ in tt]), utc=True) if tt else pd.DatetimeIndex([], tz="UTC")
        ts = l2.merge_epochs(list(ts), 1.0)
        out[int(nid)] = pd.DataFrame({"ws": ts, "we": ts})
    return out


def star_f1(sub, proba, theta, ev, lo, hi):
    dets = l2.merge_epochs(list(sub.loc[proba >= theta, "epoch"]), C.CAND_MERGE_D)
    return l2.metrics(dets, ev[(ev["ws"] >= lo) & (ev["ws"] <= hi)].reset_index(drop=True), lo, hi)


def main():
    df = build("--rebuild" in sys.argv)
    events = sat_events(df)
    rng = df.groupby("norad").agg(lo=("t_first", "first"), hi=("t_last", "first"))
    rng["lo"] = pd.to_datetime(rng["lo"], utc=True, format="mixed")
    rng["hi"] = pd.to_datetime(rng["hi"], utc=True, format="mixed")
    sats = [n for n in df.norad.unique() if len(events[int(n)]) > 0]
    d = df[df.norad.isin(sats)].reset_index(drop=True)
    print(f"{len(sats)} 顆（有真值事件）、{len(d)} 候選、正例率 {d.label.mean():.2f}", flush=True)

    oof = np.zeros(len(d))
    for tr, te in GroupKFold(5).split(d, d.label, d.norad):
        oof[te] = HistGradientBoostingClassifier(**HGB).fit(d.iloc[tr][C.FEATS], d.iloc[tr]["label"]).predict_proba(d.iloc[te][C.FEATS])[:, 1]
    d["oof"] = oof
    best_th, best = 0.5, -1.0
    for th in THETA_GRID:
        f = np.mean([star_f1(g, g["oof"].to_numpy(), th, events[int(n)], rng.loc[n, "lo"], rng.loc[n, "hi"])["f1"]
                     for n, g in d.groupby("norad")])
        if f > best:
            best, best_th = float(f), float(th)
    per = [dict(norad=int(n), **star_f1(g, g["oof"].to_numpy(), best_th, events[int(n)], rng.loc[n, "lo"], rng.loc[n, "hi"]))
           for n, g in d.groupby("norad")]
    per = pd.DataFrame(per)
    per.to_csv(f"data/benchmark/l3_starlink_oof_{STAMP}.csv", index=False)
    print(f"OOF（{len(per)} 顆）θ={best_th:.2f}：平均 F1={per.f1.mean():.3f} P={per.precision.mean():.3f} R={per.recall.mean():.3f}", flush=True)
    clf = HistGradientBoostingClassifier(**HGB).fit(d[C.FEATS], d["label"])
    joblib.dump({"clf": clf, "feats": C.FEATS, "theta": {"dense": best_th, "sparse": best_th},
                 "cadence_split_d": C.CADENCE_SPLIT_D, "family": "starlink", "n_sats": len(sats),
                 "n_candidates": int(len(d)),
                 "loso": {"f1": float(per.f1.mean()), "precision": float(per.precision.mean()),
                          "recall": float(per.recall.mean()), "n": int(len(per))},
                 "trained_on": STAMP}, OUT_MODEL)
    print("saved →", OUT_MODEL)


if __name__ == "__main__":
    main()
