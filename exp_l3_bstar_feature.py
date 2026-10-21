#!/usr/bin/env python3
"""exp_l3_bstar_feature.py — 實驗：「B* 相對該衛星自身基準的偏離」能否提升 L3 Starlink 候選確認模型？

源起：案例三十（bstar_thrust_analysis.py）發現推進星系之 B* 會吸收推力（單筆 B* 判斷降軌 AUC 0.913），
而 L3 候選模型之 10 個特徵（l3_candidate.FEATS）皆不含 B*／ndot。

A/B 設計（與 train_l3_starlink.py 完全同流程，僅特徵集不同；不覆蓋正式模型）：
  資料：train_l3_starlink 之候選快取（data/benchmark/starlink_candidate_features_*.csv，標籤＝MEME medium+ 機動 ±1.5 天）
  新特徵（候選時刻 ±1 天窗口內，基準＝該星「窗口之前 30 天」之中位數／MAD，僅用過去資料）：
    b_dev_max / b_dev_min   B* 偏離之最大／最小值（MAD 單位）
    b_neg_frac              窗口內負 B* 比例
    nd_dev_absmax           |ndot| 偏離之最大值（MAD 單位）（僅 +ndot 組）
  三組：base（10 特徵）、+bstar（13）、+bstar+ndot（14）
  評估：衛星分組 5 折（5 種隨機分折）→ OOF；θ 於 OOF 以平均逐星 F1 選定（同正式流程）；
        另報 OOF ROC-AUC／PR-AUC；逐星 F1 成對 Wilcoxon（base vs 新組，取 5 次分折之平均）。

輸出：data/benchmark/exp_l3_bstar_{features,summary,persat}_<日期>.csv
用法：python exp_l3_bstar_feature.py
"""
from __future__ import annotations

import glob
import sys
from datetime import date

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import wilcoxon
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

import l3_candidate as C
import train_l3_starlink as T
from satdet import config

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TAG = date.today().strftime("%Y%m%d")
OUT = {k: f"data/benchmark/exp_l3_bstar_{k}_{TAG}.csv" for k in ("features", "summary", "persat")}
WIN = pd.Timedelta(days=1)
BASE_WIN = pd.Timedelta(days=30)
MAD_FLOOR = {"bstar": 1e-5, "ndot": 1e-6}
N_SPLITS, SEEDS = 5, (0, 1, 2, 3, 4)
B_FEATS = ["b_dev_max", "b_dev_min", "b_neg_frac"]
ARMS = {"base": C.FEATS, "+bstar": C.FEATS + B_FEATS, "+bstar+ndot": C.FEATS + B_FEATS + ["nd_dev_absmax"]}


def _robust(x: np.ndarray, floor: float) -> tuple[float, float]:
    med = float(np.median(x))
    return med, max(1.4826 * float(np.median(np.abs(x - med))), floor)


def add_bstar_features(d: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect(config.SPACE_DB, read_only=True)
    out = []
    for nid, g in d.groupby("norad"):
        tle = con.execute("SELECT epoch_utc, bstar, try_cast(trim(substr(line1, 34, 10)) AS DOUBLE) AS ndot "
                          "FROM raw_tle_archive WHERE norad_id = ? ORDER BY epoch_utc", [int(nid)]).fetchdf()
        tle["t"] = pd.to_datetime(tle.epoch_utc, utc=True)
        tle = tle.drop_duplicates("t").dropna(subset=["bstar"])
        # duckdb 可能回傳 µs 單位；一律轉 ns 整數再比較
        tt = tle.t.dt.as_unit("ns").astype("int64").to_numpy()
        g = g.copy()
        feats = {k: [] for k in B_FEATS + ["nd_dev_absmax"]}
        for ep in g.epoch.dt.as_unit("ns"):
            e0, w_ns, b_ns = ep.value, WIN.value, BASE_WIN.value
            w = (tt >= e0 - w_ns) & (tt <= e0 + w_ns)
            b = (tt >= e0 - w_ns - b_ns) & (tt < e0 - w_ns)
            if w.sum() == 0 or b.sum() < 5:
                for k in feats:
                    feats[k].append(np.nan)
                continue
            bw, bb = tle.bstar.to_numpy()[w], tle.bstar.to_numpy()[b]
            med, mad = _robust(bb, MAD_FLOOR["bstar"])
            z = (bw - med) / mad
            feats["b_dev_max"].append(float(z.max()))
            feats["b_dev_min"].append(float(z.min()))
            feats["b_neg_frac"].append(float((bw < 0).mean()))
            nw, nb = tle.ndot.to_numpy()[w], tle.ndot.to_numpy()[b]
            nmed, nmad = _robust(nb, MAD_FLOOR["ndot"])
            feats["nd_dev_absmax"].append(float(np.abs((nw - nmed) / nmad).max()))
        for k, v in feats.items():
            g[k] = v
        out.append(g)
    con.close()
    return pd.concat(out, ignore_index=True)


def group_folds(norads: np.ndarray, seed: int) -> np.ndarray:
    uniq = np.unique(norads)
    rng = np.random.default_rng(seed)
    fold_of = dict(zip(rng.permutation(uniq), np.arange(len(uniq)) % N_SPLITS))
    return np.array([fold_of[n] for n in norads])


def run_arm(d, feats, folds, events, rng):
    oof = np.zeros(len(d))
    for k in range(N_SPLITS):
        tr, te = folds != k, folds == k
        clf = HistGradientBoostingClassifier(**T.HGB).fit(d.loc[tr, feats], d.loc[tr, "label"])
        oof[te] = clf.predict_proba(d.loc[te, feats])[:, 1]
    d = d.assign(oof=oof)
    best_th, best = 0.5, -1.0
    for th in T.THETA_GRID:
        f = np.mean([T.star_f1(g, g["oof"].to_numpy(), th, events[int(n)], rng.loc[n, "lo"], rng.loc[n, "hi"])["f1"]
                     for n, g in d.groupby("norad")])
        if f > best:
            best, best_th = float(f), float(th)
    per = pd.DataFrame([dict(norad=int(n), **T.star_f1(g, g["oof"].to_numpy(), best_th, events[int(n)],
                                                       rng.loc[n, "lo"], rng.loc[n, "hi"]))
                        for n, g in d.groupby("norad")])
    return dict(theta=best_th, f1=per.f1.mean(), precision=per.precision.mean(), recall=per.recall.mean(),
                auc=roc_auc_score(d.label, oof), ap=average_precision_score(d.label, oof)), per


def main() -> int:
    src = sorted(glob.glob("data/benchmark/starlink_candidate_features_*.csv"))[-1]
    df = pd.read_csv(src)
    df["epoch"] = pd.to_datetime(df["epoch"], utc=True, format="mixed")
    print(f"候選快取：{src}（{len(df)} 候選、{df.norad.nunique()} 顆）", flush=True)
    events = T.sat_events(df)
    rng = df.groupby("norad").agg(lo=("t_first", "first"), hi=("t_last", "first"))
    rng["lo"] = pd.to_datetime(rng["lo"], utc=True, format="mixed")
    rng["hi"] = pd.to_datetime(rng["hi"], utc=True, format="mixed")
    sats = [n for n in df.norad.unique() if len(events[int(n)]) > 0]
    d = df[df.norad.isin(sats)].reset_index(drop=True)
    d = add_bstar_features(d)
    d.to_csv(OUT["features"], index=False, encoding="utf-8-sig")
    print(f"{len(sats)} 顆、{len(d)} 候選、正例率 {d.label.mean():.3f}；B* 特徵缺值率 {d.b_dev_max.isna().mean():.3f}", flush=True)

    rows, per_all = [], []
    for seed in SEEDS:
        folds = group_folds(d.norad.to_numpy(), seed)
        for arm, feats in ARMS.items():
            m, per = run_arm(d, feats, folds, events, rng)
            rows.append(dict(seed=seed, arm=arm, **m))
            per_all.append(per.assign(seed=seed, arm=arm))
            print(f"  seed={seed} {arm:12s} F1={m['f1']:.3f} P={m['precision']:.3f} R={m['recall']:.3f} "
                  f"AUC={m['auc']:.3f} AP={m['ap']:.3f} θ={m['theta']:.2f}", flush=True)
    summ = pd.DataFrame(rows)
    per_all = pd.concat(per_all, ignore_index=True)
    summ.to_csv(OUT["summary"], index=False, encoding="utf-8-sig")
    per_all.to_csv(OUT["persat"], index=False, encoding="utf-8-sig")

    print("\n五次分折平均：")
    print(summ.groupby("arm")[["f1", "precision", "recall", "auc", "ap"]].agg(["mean", "std"]).round(3).to_string())
    pm = per_all.groupby(["arm", "norad"]).f1.mean().unstack(0)
    for arm in ("+bstar", "+bstar+ndot"):
        diff = pm[arm] - pm["base"]
        p = wilcoxon(pm[arm], pm["base"]).pvalue if (diff != 0).any() else 1.0
        print(f"逐星 F1 {arm} vs base：平均差 {diff.mean():+.4f}，勝/平/負 {(diff > 0).sum()}/{(diff == 0).sum()}/"
              f"{(diff < 0).sum()}，Wilcoxon p={p:.4g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
