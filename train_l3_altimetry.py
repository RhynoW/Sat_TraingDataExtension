#!/usr/bin/env python3
"""
train_l3_altimetry.py
=====================
訓練「候選確認式」L3（非 Starlink 族群）：NASA/ILRS 23 顆低軌衛星（14 顆 IDS 測高衛星 +
SPOT-2/3/4/5、Sentinel-6B、GRACE-A/B、GRACE-FO-C/D），以操作方認證的機動窗為真值。

流程：
  1. 以 l3_candidate.build_candidates 對 23 星（目前資料庫）產生候選＋10 個 σ 正規化特徵＋各偵測器
     來源旗標，標籤＝候選落在操作方認證機動窗 ±1.5 天內；快取為 data/benchmark/l3_altimetry_features_<date>.csv
     （邏輯與 tasa14_l3_fusion 逐項一致，見 tests/test_l3_candidate.py；2026-08-04 快取見 tasa23_fusion_features_*）
  2. 逐星留一（LOSO）：被評星完全不進訓練；決策門檻 θ 依 cadence 類別（dense/sparse）
     於「訓練星」上以平均 F1 網格搜尋，故被評星之 θ 無測試洩漏 → 誠實逐星 P/R/F1
  3. 部署用模型：全 23 星訓練；θ 依各類別以 LOSO 的 OOF 機率選定
  4. 福衛七號之弱真值（85 個疑似真事件）不參與訓練與選門檻，另作樣本外測試（見評估腳本）

輸出：models_fusion/l3_altimetry.pkl、data/benchmark/l3_altimetry_loso_<date>.csv
用法：python train_l3_altimetry.py
"""
from __future__ import annotations

import glob
import sys
from datetime import datetime, timezone
from pathlib import Path
from functools import lru_cache

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import l3_candidate as C
import tasa14_l2_compare as l2
from tasa14_compare import load_a
from tasa23_ext_arena import ALL_SATS23, load_events_ext2

STAMP = datetime.now(timezone.utc).strftime("%Y%m%d")
TOL_D = 1.5
OUT_MODEL = "models_fusion/l3_altimetry.pkl"
THETA_GRID = np.arange(0.10, 0.91, 0.05)
HGB = dict(max_iter=250, learning_rate=0.08, random_state=42)


@lru_cache(maxsize=None)
def _series(nid):
    return load_a(nid)


def star_f1(nid, dets, events):
    t, _ = _series(nid)
    ev = events[nid]
    lo = max(t.min(), ev["ws"].min())
    hi = min(t.max(), ev["we"].max())
    ev = ev[(ev["ws"] >= lo) & (ev["ws"] <= hi)].reset_index(drop=True)
    return l2.metrics(dets, ev, lo, hi)


def accepted(sub, proba, theta):
    return l2.merge_epochs(list(sub.loc[proba >= theta, "epoch"]), C.CAND_MERGE_D)


def pick_theta(df, sats, proba_of, events):
    """在 sats 上以平均 F1 網格搜尋 θ；proba_of[n] 為該星候選的機率。"""
    best_th, best = 0.5, -1.0
    for th in THETA_GRID:
        m = float(np.mean([star_f1(n, accepted(df[df.norad == n], proba_of[n], th), events)["f1"] for n in sats]))
        if m > best:
            best, best_th = m, float(th)
    return best_th, best


def build_features(events, rebuild=False):
    old = sorted(glob.glob("data/benchmark/l3_altimetry_features_*.csv"))
    if old and not rebuild:
        d = pd.read_csv(old[-1])
        d["epoch"] = pd.to_datetime(d["epoch"], utc=True, format="mixed")
        print(f"載入快取 {old[-1]}", flush=True)
        return d
    tol = pd.Timedelta(days=TOL_D)
    rows = []
    for nid, nm in ALL_SATS23:
        t, a = _series(nid)
        if t is None or len(a) < 60 or nid not in events:
            continue
        ev = events[nid]
        lo, hi = max(t.min(), ev["ws"].min()), min(t.max(), ev["we"].max())
        evw = ev[(ev["ws"] >= lo) & (ev["ws"] <= hi)].reset_index(drop=True)
        if len(evw) == 0:
            continue
        d = C.build_candidates(t, a, lo, hi)
        if d.empty:
            continue
        d["label"] = [int(any((e["ws"] - tol <= ce <= e["we"] + tol) for _, e in evw.iterrows())) for ce in d["epoch"]]
        d["norad"], d["name"] = nid, nm
        rows.append(d)
        print(f"  {nm:14s} 候選 {len(d):4d} 正例率 {d.label.mean():.2f}", flush=True)
    out = pd.concat(rows, ignore_index=True)
    out.to_csv(f"data/benchmark/l3_altimetry_features_{STAMP}.csv", index=False, encoding="utf-8-sig")
    return out


def main():
    events = load_events_ext2()
    df = build_features(events, "--rebuild" in sys.argv)
    sats = sorted(set(df.norad) & set(events))
    cad = df.groupby("norad")["cadence_d"].first().to_dict()
    cls = {n: C.cadence_class(cad[n]) for n in sats}
    names = df.groupby("norad")["name"].first().to_dict()
    print(f"{len(sats)} 顆、{len(df)} 候選、正例率 {df.label.mean():.2f}", flush=True)

    rows, oof = [], {}
    for held in sats:
        tr = df[(df.norad != held) & df.norad.isin(sats)]
        te = df[df.norad == held]
        clf = HistGradientBoostingClassifier(**HGB).fit(tr[C.FEATS], tr["label"])
        tr_sats = [n for n in sats if n != held and cls[n] == cls[held]]
        if len(tr_sats) < 2:
            tr_sats = [n for n in sats if n != held]
        pr = {n: clf.predict_proba(df[df.norad == n][C.FEATS])[:, 1] for n in tr_sats}
        th, _ = pick_theta(df, tr_sats, pr, events)
        proba = clf.predict_proba(te[C.FEATS])[:, 1]
        oof[held] = proba
        met = star_f1(held, accepted(te, proba, th), events)
        rows.append(dict(norad=held, name=names[held], cls=cls[held], theta=th, **met))
        print(f"  {names[held]:14s} [{cls[held]:6s} θ={th:.2f}] P={met['precision']:.2f} R={met['recall']:.2f} F1={met['f1']:.3f}", flush=True)
    out = pd.DataFrame(rows).sort_values("f1", ascending=False)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    csv = f"data/benchmark/l3_altimetry_loso_{stamp}.csv"
    out.to_csv(csv, index=False, encoding="utf-8-sig")
    print(f"\nLOSO（{len(out)} 星）平均 F1={out.f1.mean():.3f}  P={out.precision.mean():.3f}  R={out.recall.mean():.3f}  → {csv}", flush=True)

    # 部署用：全星訓練；θ 依類別由 LOSO 的 OOF 機率選定
    theta = {}
    for c in ("dense", "sparse"):
        cs = [n for n in sats if cls[n] == c]
        theta[c], f1c = pick_theta(df, cs, oof, events)
        print(f"  部署 θ[{c}] = {theta[c]:.2f}（{len(cs)} 星 OOF 平均 F1 {f1c:.3f}）", flush=True)
    clf = HistGradientBoostingClassifier(**HGB).fit(df[df.norad.isin(sats)][C.FEATS], df[df.norad.isin(sats)]["label"])
    joblib.dump({
        "clf": clf, "feats": C.FEATS, "theta": theta, "cadence_split_d": C.CADENCE_SPLIT_D,
        "family": "leo_altimetry", "n_sats": len(sats), "n_candidates": int(len(df)),
        "sats": {int(n): names[n] for n in sats},
        "loso": {"f1": float(out.f1.mean()), "precision": float(out.precision.mean()),
                 "recall": float(out.recall.mean()), "n": int(len(out))},
        "trained_on": stamp,
    }, OUT_MODEL)
    print("saved →", OUT_MODEL)


if __name__ == "__main__":
    main()
