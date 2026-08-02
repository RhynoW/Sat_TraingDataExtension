#!/usr/bin/env python3
"""
fusion_channel_importance.py — 旁敲側擊融合評分器：它如何選擇/加權五通道？
============================================================================
對真正的融合評分器（HistGradientBoosting，GroupKFold OOF）跑四種互補探測，
量化五通道（cusum/bocpd/ssa/mad3sig/drag）× (max/mean/p90) 的貢獻與加權邏輯：

  (A) 排列重要度：打亂某特徵→AUC 掉多少（模型有多依賴它）。fold 內在測試集上算，無洩漏。
  (B) 消融 ΔAUC ：把某通道 3 特徵整個拿掉重訓→AUC 損失（該通道的不可替代性）。
  (C) 單通道 only：只用某通道 3 特徵訓練→其單獨判別力上限。
  (D) 原始關聯　：每通道 max 分數與標籤之點二列相關（模型學習前的生訊號強度）。

輸出：data/benchmark/fusion_channel_importance_{date}.csv、主控台彙整表。
用法：python fusion_channel_importance.py [--max-sats N]
"""
from __future__ import annotations

import argparse
import glob
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold
from sklearn.metrics import roc_auc_score
from sklearn.inspection import permutation_importance

from compare_tle_vs_ephemeris import load_registry
from satdet import config, episodes_by_sat, load_drag_map
from three_layer_common_eval import build_common_units, CH, HGB

STATS = ("max", "mean", "p90")
FEATS = [f"f_{c}_{s}" for c in CH for s in STATS]
CH_ZH = {"cusum": "CUSUM", "bocpd": "BOCPD", "ssa": "SSA",
         "mad3sig": "3σ-MAD", "drag": "NRLMSIS阻力殘差"}


def oof_auc(X, y, groups, feat_idx):
    """對指定特徵子集跑 GroupKFold OOF，回傳 AUC。"""
    oof = np.zeros(len(y))
    Xs = X[:, feat_idx]
    for tr, te in GroupKFold(5).split(Xs, y, groups):
        oof[te] = HistGradientBoostingClassifier(**HGB).fit(
            Xs[tr], y[tr]).predict_proba(Xs[te])[:, 1]
    return roc_auc_score(y, oof), oof


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=config.SPACE_DB)
    ap.add_argument("--max-sats", type=int, default=None)
    args = ap.parse_args()

    tp = sorted(glob.glob("data/meme_truth/transitions_full_*.csv"))[-1]
    truth = pd.read_csv(tp)
    truth["t_to"] = pd.to_datetime(truth["t_to"], utc=True, format="ISO8601")
    eps_by = episodes_by_sat(truth)
    reg = load_registry("data/url_registry.csv")
    n2n = {v: k for k, v in reg["sat_name"].items()}
    sats = list(n2n.items())[: args.max_sats] if args.max_sats else list(n2n.items())

    print(f"建共同 unit 集：{len(sats)} 顆 Starlink …", flush=True)
    U = build_common_units(args.db, sats, load_drag_map(), eps_by)
    y = U["label"].to_numpy(); groups = U["norad_id"].to_numpy()
    X = U[FEATS].to_numpy()
    all_idx = list(range(len(FEATS)))

    auc_full, _ = oof_auc(X, y, groups, all_idx)
    print(f"  full 15-feature 融合器 OOF AUC = {auc_full:.4f}"
          f"（{int((y==1).sum())} 正 / {int((y==0).sum())} 負 unit）\n")

    # ── (A) 排列重要度（fold 內測試集，AUC 分數，n_repeats=10）──
    perm = {f: [] for f in FEATS}
    for tr, te in GroupKFold(5).split(X, y, groups):
        m = HistGradientBoostingClassifier(**HGB).fit(X[tr], y[tr])
        r = permutation_importance(m, X[te], y[te], scoring="roc_auc",
                                   n_repeats=10, random_state=0)
        for j, f in enumerate(FEATS):
            perm[f].append(r.importances_mean[j])
    perm_feat = {f: float(np.mean(v)) for f, v in perm.items()}
    perm_ch = {c: sum(perm_feat[f"f_{c}_{s}"] for s in STATS) for c in CH}

    # ── (B) 消融：拿掉某通道 3 特徵重訓 ──
    abl = {}
    for c in CH:
        keep = [i for i, f in enumerate(FEATS) if not f.startswith(f"f_{c}_")]
        a, _ = oof_auc(X, y, groups, keep)
        abl[c] = auc_full - a

    # ── (C) 單通道 only ──
    solo = {}
    for c in CH:
        idx = [i for i, f in enumerate(FEATS) if f.startswith(f"f_{c}_")]
        a, _ = oof_auc(X, y, groups, idx)
        solo[c] = a

    # ── (D) 原始關聯：通道 max 分數 vs 標籤（點二列相關）──
    raw = {}
    for c in CH:
        s = U[f"f_{c}_max"].to_numpy()
        raw[c] = float(np.corrcoef(s, y)[0, 1])

    # ── 彙整表（依排列重要度排序）──
    order = sorted(CH, key=lambda c: perm_ch[c], reverse=True)
    print("=" * 84)
    print("融合評分器如何加權五通道（依排列重要度排序；full AUC "
          f"{auc_full:.3f}）")
    print("=" * 84)
    print(f"  {'通道':<16}{'排列重要度':>12}{'消融ΔAUC':>12}{'單通道AUC':>12}{'生訊號r':>10}")
    print("  " + "-" * 78)
    for c in order:
        print(f"  {CH_ZH[c]:<16}{perm_ch[c]:>12.4f}{abl[c]:>12.4f}"
              f"{solo[c]:>12.3f}{raw[c]:>10.3f}")
    print("=" * 84)

    # 最依賴的「特徵」（非通道）Top-6
    top = sorted(perm_feat.items(), key=lambda kv: kv[1], reverse=True)[:6]
    print("  最受依賴的單一特徵 Top-6（通道×統計量）：")
    for f, v in top:
        c, s = f[2:].rsplit("_", 1)
        print(f"    {CH_ZH.get(c, c):<14} · {s:<4} 排列重要度 {v:.4f}")
    print("\n  判讀：排列重要度＝打亂該通道分數後 AUC 的平均下降；消融ΔAUC＝整通道移除的損失；")
    print("        單通道AUC＝只用它能到多少；生訊號r＝模型學習前，該通道 max 與標籤的相關。")

    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    outp = Path("data/benchmark") / f"fusion_channel_importance_{date}.csv"
    outp.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"channel": CH_ZH[c], "perm_importance": perm_ch[c],
                   "ablation_delta_auc": abl[c], "solo_auc": solo[c],
                   "raw_corr": raw[c]} for c in order]).to_csv(
        outp, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {outp}")


if __name__ == "__main__":
    main()
