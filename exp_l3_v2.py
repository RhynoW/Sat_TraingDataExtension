#!/usr/bin/env python3
"""exp_l3_v2.py — L3 融合評分器 v2 實驗：目標在「修正後擂台」（只用真值涵蓋期）AUC ≥ 0.85

基準：three_layer_common_eval 之 L3（15 維、HistGB）於修正後擂台 OOF AUC 0.813。
所有比較在同一份 unit 集上進行（build_common_units，cov_by＝真值涵蓋期，與正式擂台相同）：
  ・評估：衛星分組 5 折；以 N_SEEDS 種隨機「衛星→折」分派各跑一次，報平均與標準差（避免單一分折碰巧）
  ・特徵只由 TLE 推得；B* 基準只用窗口之前的資料
特徵組：
  base15    原 15 維（5 通道 × max/mean/p90）
  +enh      加既有增強特徵（時間結構 t_*、跨通道 x_*、snr_window、da_max_m）——擂台早已算好、但 L3 從未使用
  +v2       加 v2 特徵（位準差、淨 Δa、Δi、Δe、B* 偏離；見 three_layer_common_eval.unit_row）
  all       base15 + enh + v2
另比較 HistGB 參數與 LightGBM。

輸出：data/benchmark/l3_v2_units_<日期>.parquet（unit 快取）、data/benchmark/l3_v2_results_<日期>.csv
用法：python exp_l3_v2.py [--rebuild]
"""
from __future__ import annotations

import glob
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

import three_layer_common_eval as A
from compare_tle_vs_ephemeris import load_registry
from satdet import config, episodes_by_sat, fpr_floor_threshold, load_drag_map, truth_coverage

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
TAG = date.today().strftime("%Y%m%d")
UNITS = ROOT / "data" / "benchmark" / f"l3_v2_units_{TAG}.parquet"
OUT = ROOT / "data" / "benchmark" / f"l3_v2_results_{TAG}.csv"
N_SEEDS, N_FOLDS = 5, 5

BASE = [f"f_{c}_{st}" for c in A.CH for st in ("max", "mean", "p90")]
ENH = ([f"t_{c}_{k}" for c in A.CH for k in ("peakpos", "rise", "conc")]
       + ["x_stat_minus_drag", "x_stat_over_drag", "snr_window", "da_max_m"])
V2 = ["v2_levelshift_sig", "v2_levelshift_abs", "v2_net_da_sig", "v2_di_max", "v2_de_max",
      "v2_b_dev_max", "v2_b_dev_min", "v2_b_neg_frac"]


def build_units() -> pd.DataFrame:
    truth = pd.read_csv(sorted(glob.glob("data/meme_truth/transitions_full_*.csv"))[-1])
    truth["t_to"] = pd.to_datetime(truth["t_to"], utc=True, format="ISO8601")
    eps_by = episodes_by_sat(truth)
    cov_by = truth_coverage(truth)
    reg = load_registry("data/url_registry.csv")
    sats = [(v, k) for k, v in reg["sat_name"].items()]
    U = A.build_common_units(config.SPACE_DB, sats, load_drag_map(), eps_by, cov_by, [])
    U.to_parquet(UNITS, index=False)
    return U


def folds(groups, seed):
    uniq = np.unique(groups)
    rng = np.random.default_rng(seed)
    f = dict(zip(rng.permutation(uniq), np.arange(len(uniq)) % N_FOLDS))
    return np.array([f[g] for g in groups])


def oof_auc(U, feats, make, seed):
    X = U[feats].to_numpy(float); y = U.label.to_numpy()
    fo = folds(U.norad_id.to_numpy(), seed)
    oof = np.zeros(len(y))
    for k in range(N_FOLDS):
        tr, te = fo != k, fo == k
        oof[te] = make().fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
    neg = y == 0
    thr = fpr_floor_threshold(oof[neg], 0.05)
    big = (y == 1) & (U.sev.to_numpy() == 3)
    return roc_auc_score(y, oof), float((oof[y == 1] >= thr).mean()), float((oof[big] >= thr).mean())


def main():
    U = pd.read_parquet(UNITS) if UNITS.exists() and "--rebuild" not in sys.argv else build_units()
    print(f"units {len(U)}（正 {int(U.label.sum())}、負 {int((U.label == 0).sum())}），衛星 {U.norad_id.nunique()}", flush=True)
    hgb0 = lambda: HistGradientBoostingClassifier(**A.HGB)
    hgb1 = lambda: HistGradientBoostingClassifier(max_iter=600, learning_rate=0.03, max_depth=None, max_leaf_nodes=31,
                                                  min_samples_leaf=40, l2_regularization=1.0,
                                                  class_weight="balanced", random_state=42)
    try:
        from lightgbm import LGBMClassifier
        lgb = lambda: LGBMClassifier(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=40,
                                     subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                                     class_weight="balanced", random_state=42, verbose=-1)
    except ImportError:
        lgb = None
    configs = [("base15", BASE, "HGB 原參數", hgb0),
               ("+enh", BASE + ENH, "HGB 原參數", hgb0),
               ("+v2", BASE + V2, "HGB 原參數", hgb0),
               ("all", BASE + ENH + V2, "HGB 原參數", hgb0),
               ("all", BASE + ENH + V2, "HGB 調參", hgb1)]
    if lgb:
        configs.append(("all", BASE + ENH + V2, "LightGBM", lgb))
    rows = []
    for name, feats, mname, make in configs:
        r = np.array([oof_auc(U, feats, make, s) for s in range(N_SEEDS)])
        rows.append(dict(features=name, model=mname, n_feats=len(feats), auc_mean=r[:, 0].mean(), auc_std=r[:, 0].std(),
                         recall_at_fpr05=r[:, 1].mean(), large_recall_at_fpr05=r[:, 2].mean()))
        print(f"  {name:7s} {mname:10s} ({len(feats):2d} 維) AUC {r[:, 0].mean():.3f} ± {r[:, 0].std():.3f}"
              f"｜召回@FPR≤.05 {r[:, 1].mean():.3f}｜large {r[:, 2].mean():.3f}", flush=True)
    pd.DataFrame(rows).to_csv(OUT, index=False, encoding="utf-8-sig")
    print("→", OUT)


if __name__ == "__main__":
    main()
