#!/usr/bin/env python3
"""bootstrap_ci.py — 主指標之 bootstrap 95% 信賴區間（回應外部委員意見）。

委員意見（第一、二位共識）：
  - 小樣本分層指標（small n=11）須附信賴區間，勿以點值定論。
  - 主指標（large 召回、AUC）亦應列 CI；bootstrap 之重抽樣單位須為**衛星或 episode**，
    而非高度相關的相鄰 TLE epoch（否則 CI 假性過窄）。

做法：對 `three_layer_perunit_*.csv`（GroupKFold OOF、無洩漏之逐 unit L3 分數）以
**衛星（norad_id）為重抽樣單位**做分層 bootstrap（B=2000），計算：
  (a) ROC-AUC；(b) 各嚴重度（large/medium/small）於 FPR≤0.05 操作點之召回率。
FPR≤0.05 門檻於每次 bootstrap 內、以該次負 unit 之 l3_score 95 百分位重新估計（誠實）。
輸出點估計 + 2.5/97.5 百分位 CI。

用法：python bootstrap_ci.py [--csv <perunit.csv>] [-B 2000] [--seed 42]
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

try:
    from satdet.common import RANK_SEV  # {1:'small',2:'medium',3:'large'} 之類
except Exception:
    RANK_SEV = None


def wilson_ci(k: int, n: int, z: float = 1.96):
    """二項比例之 Wilson 95% CI（供小樣本點估計對照）。"""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def recall_at_fpr(score, label, sev, sev_target, fpr_budget=0.05):
    """在 FPR≤fpr_budget 門檻下，sev_target 類正 unit 之召回率。"""
    neg = score[label == 0]
    if len(neg) == 0:
        return float("nan")
    thr = np.quantile(neg, 1.0 - fpr_budget)  # 負 unit 之 (1-FPR) 分位＝門檻
    m = (label == 1) & (sev == sev_target)
    if m.sum() == 0:
        return float("nan")
    return float((score[m] >= thr).mean())


def point_and_ci(csv_path: str, B: int, seed: int):
    d = pd.read_csv(csv_path)
    d.columns = [c.lstrip("﻿") for c in d.columns]
    score = d["l3_score"].to_numpy(float)
    label = d["label"].to_numpy(int)
    sev = d["sev"].to_numpy(int)
    nid = d["norad_id"].to_numpy()

    # 嚴重度碼 → 名稱
    sev_codes = sorted(set(sev[label == 1].tolist()))
    if RANK_SEV and all(c in RANK_SEV for c in sev_codes):
        name = {c: RANK_SEV[c] for c in sev_codes}
    else:  # fallback：假設 1<2<3 = small<medium<large
        fb = {1: "small", 2: "medium", 3: "large"}
        name = {c: fb.get(c, f"sev{c}") for c in sev_codes}
    targets = {name[c]: c for c in sev_codes}

    def metrics(idx):
        s, l, v = score[idx], label[idx], sev[idx]
        out = {}
        if len(set(l)) == 2:
            out["AUC"] = roc_auc_score(l, s)
        else:
            out["AUC"] = float("nan")
        for nm, code in targets.items():
            out[f"recall_{nm}"] = recall_at_fpr(s, l, v, code)
        # 整體召回（所有正 unit）
        neg = s[l == 0]
        thr = np.quantile(neg, 0.95) if len(neg) else np.inf
        pos = (l == 1)
        out["recall_all"] = float((s[pos] >= thr).mean()) if pos.sum() else float("nan")
        return out

    # 點估計（全樣本）
    point = metrics(np.arange(len(d)))

    # 各類正 unit 之 n（供 Wilson 對照）
    n_by = {nm: int(((label == 1) & (sev == code)).sum()) for nm, code in targets.items()}

    # 以衛星為單位之 bootstrap
    sats = np.array(sorted(set(nid.tolist())))
    sat_rows = {s: np.where(nid == s)[0] for s in sats}
    rng = np.random.default_rng(seed)
    keys = list(point.keys())
    boot = {k: [] for k in keys}
    for _ in range(B):
        pick = rng.choice(sats, size=len(sats), replace=True)
        idx = np.concatenate([sat_rows[s] for s in pick])
        m = metrics(idx)
        for k in keys:
            boot[k].append(m[k])

    print("=" * 78)
    print(f"主指標 bootstrap 95% CI（重抽樣單位＝衛星，B={B}；來源 {Path(csv_path).name}）")
    print(f"正 unit={int((label==1).sum())}、負 unit={int((label==0).sum())}、衛星={len(sats)}")
    print("=" * 78)
    print(f"{'指標':16}{'點估計':>10}{'2.5%':>10}{'97.5%':>10}   備註")
    for k in keys:
        arr = np.array([x for x in boot[k] if np.isfinite(x)])
        lo, hi = (np.percentile(arr, 2.5), np.percentile(arr, 97.5)) if len(arr) else (np.nan, np.nan)
        note = ""
        for nm, code in targets.items():
            if k == f"recall_{nm}":
                n = n_by[nm]
                kk = int(round(point[k] * n)) if np.isfinite(point[k]) else 0
                wlo, whi = wilson_ci(kk, n)
                note = f"n={n}（{kk}/{n}）Wilson[{wlo:.3f},{whi:.3f}]"
        print(f"{k:16}{point[k]:>10.3f}{lo:>10.3f}{hi:>10.3f}   {note}")
    print("=" * 78)
    print("判讀：large／AUC 之 CI 窄→穩健；small 之 bootstrap 與 Wilson CI 皆極寬（n 小），"
          "故『6/11 可回收、4/11 物理極限』屬區間性推估、不宜以點值定論。")

    # 存 CSV（可重現）
    rows = []
    for k in keys:
        arr = np.array([x for x in boot[k] if np.isfinite(x)])
        lo, hi = (np.percentile(arr, 2.5), np.percentile(arr, 97.5)) if len(arr) else (np.nan, np.nan)
        rows.append(dict(metric=k, point=point[k], ci_lo=lo, ci_hi=hi))
    out = Path("data/benchmark") / "bootstrap_ci_20260802.csv"
    pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n輸出 → {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/benchmark/three_layer_perunit_20260721.csv")
    ap.add_argument("-B", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    point_and_ci(a.csv, a.B, a.seed)


if __name__ == "__main__":
    main()
