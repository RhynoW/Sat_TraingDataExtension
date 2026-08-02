#!/usr/bin/env python3
"""
fusion_p1_features.py — P1 特徵改進實驗：多樣性與時間結構是否提升融合器？
============================================================================
依「以可解釋性反推改進」之結論，於融合器加入 P1 特徵並量測增益：
  (i)   時間結構：每通道之峰值位置 t_peakpos、最大上升步 t_rise、峰值集中度 t_conc
  (ii)  跨通道交互：x_stat_minus_drag、x_stat_over_drag（統計證據 vs 物理阻力）
  (iii) 窗內物理 SNR：snr_window（最大 Δa 公尺 / 該星雜訊 σ）

比較 baseline（15 維 max/mean/p90 × 5 通道）vs enhanced（15 ＋ 18 = 33 維），
同一 GroupKFold(5) OOF、同一操作點 FPR≤0.05，報 AUC 與分層召回之變化；
並以排列重要度列出最有貢獻的 P1 特徵。

輸出：data/benchmark/fusion_p1_features_{date}.csv、主控台對照。
用法：python fusion_p1_features.py [--max-sats N]
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
from satdet import config, episodes_by_sat, load_drag_map, fpr_floor_threshold
from satdet.common import SEV_RANK
from three_layer_common_eval import build_common_units, eval_scores, CH, STAT_CH, HGB

BASE = [f"f_{c}_{s}" for c in CH for s in ("max", "mean", "p90")]           # 15
P1_TIME = [f"t_{c}_{s}" for c in CH for s in ("peakpos", "rise", "conc")]   # 15
P1_X = ["x_stat_minus_drag", "x_stat_over_drag", "snr_window"]              # 3
P1 = P1_TIME + P1_X
ENH = BASE + P1


def oof(U, feats, y, groups):
    X = U[feats].to_numpy()
    o = np.zeros(len(y))
    for tr, te in GroupKFold(5).split(X, y, groups):
        o[te] = HistGradientBoostingClassifier(**HGB).fit(
            X[tr], y[tr]).predict_proba(X[te])[:, 1]
    return o


def summarize(o, y, sev, neg, tag):
    thr = fpr_floor_threshold(o[neg], 0.05)
    m = eval_scores(o, y, sev, thr)
    auc = roc_auc_score(y, o)
    print(f"  {tag:<26}{auc:>8.4f}{m['recall']:>9.3f}{m['fpr']:>8.3f}"
          f"{m['rec_large']:>8.3f}{m['rec_medium']:>9.3f}{m['rec_small']:>8.3f}")
    return {"tag": tag, "auc": auc, "recall": m["recall"], "fpr": m["fpr"],
            "rec_large": m["rec_large"], "rec_medium": m["rec_medium"],
            "rec_small": m["rec_small"]}


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
    y = U["label"].to_numpy(); sev = U["sev"].to_numpy(); groups = U["norad_id"].to_numpy()
    neg = y == 0
    print(f"  unit {len(U)}（正 {int((y==1).sum())} / 負 {int(neg.sum())}）｜"
          f"baseline {len(BASE)} 維 → enhanced {len(ENH)} 維（＋{len(P1)} P1 特徵）\n")

    o_base = oof(U, BASE, y, groups)
    o_enh = oof(U, ENH, y, groups)
    o_p1 = oof(U, P1, y, groups)   # 只用 P1 特徵，看其單獨判別力

    print("=" * 78)
    print("P1 特徵改進實驗（GroupKFold OOF，操作點 FPR≤0.05）")
    print("=" * 78)
    print(f"  {'特徵組':<26}{'AUC':>8}{'召回':>9}{'FPR':>8}{'large':>8}{'medium':>9}{'small':>8}")
    print("  " + "-" * 72)
    r_base = summarize(o_base, y, sev, neg, "baseline（15 維）")
    r_enh = summarize(o_enh, y, sev, neg, "enhanced（33 維，＋P1）")
    r_p1 = summarize(o_p1, y, sev, neg, "P1-only（18 維）")
    print("=" * 78)
    dauc = r_enh["auc"] - r_base["auc"]
    dlarge = r_enh["rec_large"] - r_base["rec_large"]
    dmed = r_enh["rec_medium"] - r_base["rec_medium"]
    dsmall = r_enh["rec_small"] - r_base["rec_small"]
    print(f"  增益 Δ：AUC {dauc:+.4f}｜large 召回 {dlarge:+.3f}｜"
          f"medium {dmed:+.3f}｜small {dsmall:+.3f}")
    print("  （註：HGB 多執行緒有 ±0.005 AUC 微抖動，ΔAUC 應以量級與方向判讀）")

    # ── 排列重要度：enhanced 模型中，哪些 P1 特徵最有貢獻 ──
    print("\n  enhanced 模型中最有貢獻的 P1 特徵（排列重要度 Top-8）：")
    Xe = U[ENH].to_numpy()
    imp = {f: [] for f in ENH}
    for tr, te in GroupKFold(5).split(Xe, y, groups):
        mm = HistGradientBoostingClassifier(**HGB).fit(Xe[tr], y[tr])
        rr = permutation_importance(mm, Xe[te], y[te], scoring="roc_auc",
                                    n_repeats=8, random_state=0)
        for k, f in enumerate(ENH):
            imp[f].append(rr.importances_mean[k])
    impm = {f: float(np.mean(v)) for f, v in imp.items()}
    p1_rank = sorted([(f, impm[f]) for f in P1], key=lambda kv: kv[1], reverse=True)[:8]
    for f, v in p1_rank:
        print(f"    {f:<22} 排列重要度 {v:.4f}")

    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    outp = Path("data/benchmark") / f"fusion_p1_features_{date}.csv"
    outp.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([r_base, r_enh, r_p1]).to_csv(outp, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {outp}")


if __name__ == "__main__":
    main()
