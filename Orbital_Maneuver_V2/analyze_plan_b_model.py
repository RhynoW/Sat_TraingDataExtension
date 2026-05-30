#!/usr/bin/env python3
"""
analyze_plan_b_model.py
========================
Task 1: Plan B LightGBM 特徵重要性（gain-based，排序顯示）
Task 2: Plan A MEME GT Starlink 外部驗證
        — 用 Plan B features 對 283 顆 Starlink 衛星重新推論，
          與 MEME 地面真值比較（衛星層級 binary 標籤）
Task 3: SHAP 分析
        — TreeExplainer + beeswarm / bar chart，儲存 PNG
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (auc, f1_score, precision_recall_curve,
                              precision_score, recall_score, roc_auc_score)

BASE   = Path(__file__).parent
PLAN_A = BASE.parent / "data/maneuvers/training_samples_meme_gt.csv"
PLAN_B = BASE.parent / "data/maneuvers/training_samples_plan_b.csv"
MODEL  = BASE / "models_plan_b/lgbm_maneuver_v1.pkl"
FEAT_J = BASE / "models_plan_b/feature_names.json"
THR_J  = BASE / "models_plan_b/threshold.json"
OUTPUT = BASE / "output"


# ── 工具 ─────────────────────────────────────────────────────────────────────

def _bar(val: float, total: float, width: int = 35) -> str:
    n = max(0, round(val / total * width))
    return "#" * n + "." * (width - n)


def _metrics(y_true, proba, threshold) -> dict:
    y_pred = (proba >= threshold).astype(int)
    return {
        "precision": precision_score(y_true, y_pred, zero_division=0),
        "recall":    recall_score(y_true,    y_pred, zero_division=0),
        "f1":        f1_score(y_true,         y_pred, zero_division=0),
        "auc_roc":   roc_auc_score(y_true, proba) if len(np.unique(y_true)) > 1 else np.nan,
        "pr_auc":    auc(*precision_recall_curve(y_true, proba)[:2][::-1]),
    }


# ── Task 1：特徵重要性 ───────────────────────────────────────────────────────

def feature_importance(model, feature_cols: list[str]) -> None:
    imp  = model.feature_importances_
    total = float(imp.sum()) or 1.0
    fi   = sorted(zip(feature_cols, imp), key=lambda x: -x[1])

    print("=" * 72)
    print("  1.  FEATURE IMPORTANCE  (Plan B LightGBM, gain-based)")
    print("=" * 72)
    print(f"  {'Rank':<4}  {'Feature':<22}  {'Gain':>8}  {'%':>6}  {'Bar'}")
    print("  " + "-" * 68)
    for rank, (name, g) in enumerate(fi, 1):
        pct = g / total * 100
        print(f"  {rank:<4}  {name:<22}  {g:>8.0f}  {pct:>5.1f}%  {_bar(g, total)}")
    print()

    # 前 5 特徵合計貢獻
    top5 = sum(g for _, g in fi[:5])
    print(f"  Top-5 features account for {top5/total*100:.1f}% of total gain")
    print()


# ── Task 2：外部驗證（Plan A Starlink） ──────────────────────────────────────

def external_validation(model, feature_cols: list[str], threshold: float) -> None:
    print("=" * 72)
    print("  2.  EXTERNAL VALIDATION — Plan A MEME GT Starlink 衛星")
    print("=" * 72)

    if not PLAN_A.exists():
        print(f"  [WARN] Plan A CSV not found: {PLAN_A}")
        return
    if not PLAN_B.exists():
        print(f"  [WARN] Plan B CSV not found: {PLAN_B}")
        return

    plan_a = pd.read_csv(PLAN_A)
    plan_b = pd.read_csv(PLAN_B)

    plan_a["norad_id"] = pd.to_numeric(plan_a["norad_id"], errors="coerce").astype("Int64")
    plan_b["norad_id"] = pd.to_numeric(plan_b["norad_id"], errors="coerce").astype("Int64")

    # Plan A 彙整到衛星層級：任一轉移 label=1 → 衛星層級=1
    plan_a_sat = (
        plan_a
        .groupby("norad_id")["label_binary"]
        .max()
        .reset_index()
        .rename(columns={"label_binary": "gt_label"})
    )
    a_pos = int((plan_a_sat["gt_label"] == 1).sum())
    a_neg = int((plan_a_sat["gt_label"] == 0).sum())
    print(f"\n  Plan A 衛星數      : {len(plan_a_sat):>5}  （正例={a_pos}  負例={a_neg}）")

    # Plan B 篩到 Plan A 衛星
    a_norads     = set(plan_a_sat["norad_id"].dropna().unique())
    b_starlink   = plan_b[plan_b["norad_id"].isin(a_norads)].copy()
    not_in_b     = a_norads - set(b_starlink["norad_id"].unique())
    print(f"  Plan B 涵蓋 Plan A : {len(b_starlink):>5} 行  （未涵蓋 {len(not_in_b)} 顆）")

    if len(b_starlink) == 0:
        print("  [WARN] Plan B 無 Plan A 衛星資料，無法驗證。")
        return

    merged = b_starlink.merge(plan_a_sat, on="norad_id", how="inner")
    print(f"  合併後樣本         : {len(merged):>5}\n")

    # 特徵對齊：缺欄補 NaN（不補 0，讓模型以訓練時的 NaN 行為處理）
    missing_feats = [c for c in feature_cols if c not in merged.columns]
    if missing_feats:
        print(f"  [INFO] 缺少特徵欄位（補 NaN）: {missing_feats}")
        for c in missing_feats:
            merged[c] = np.nan

    X      = merged[feature_cols]
    proba  = model.predict_proba(X)[:, 1]
    y_true = merged["gt_label"].values.astype(int)

    # 在多個閾值下評估
    print(f"  {'Threshold':>10}  {'Precision':>10}  {'Recall':>8}  {'F1':>8}  {'AUC-ROC':>9}  {'PR-AUC':>8}")
    print("  " + "-" * 62)
    for thr in [0.50, threshold]:
        m = _metrics(y_true, proba, thr)
        thr_lbl = f"{thr:.4f}" + (" ← opt" if abs(thr - threshold) < 1e-6 else "")
        print(
            f"  {thr_lbl:>10}  {m['precision']:>10.1%}  {m['recall']:>8.1%}  "
            f"{m['f1']:>8.1%}  {m['auc_roc']:>9.4f}  {m['pr_auc']:>8.4f}"
        )
    print()

    # 混淆矩陣
    y_pred = (proba >= threshold).astype(int)
    tp = int(((y_true == 1) & (y_pred == 1)).sum())
    fn = int(((y_true == 1) & (y_pred == 0)).sum())
    fp = int(((y_true == 0) & (y_pred == 1)).sum())
    tn = int(((y_true == 0) & (y_pred == 0)).sum())
    print(f"  混淆矩陣（閾值 {threshold:.4f}）")
    print(f"    TP={tp:>4}  FN={fn:>4}   → Recall  = {tp/(tp+fn) if tp+fn else 0:.1%}")
    print(f"    FP={fp:>4}  TN={tn:>4}   → Precision= {tp/(tp+fp) if tp+fp else 0:.1%}")
    print()

    # 誤分類明細（前 20 筆）
    merged["p_maneuver"] = proba
    merged["predicted"]  = y_pred
    wrong = merged[y_pred != y_true].sort_values("p_maneuver", ascending=False)
    if not wrong.empty:
        print(f"  誤分類衛星 ({len(wrong)} 顆，前 20 筆)：")
        print(f"  {'NORAD':>7}  {'GT':>3}  {'Pred':>4}  {'p':>8}  behavior")
        print("  " + "-" * 55)
        for _, r in wrong.head(20).iterrows():
            print(
                f"  {int(r['norad_id']):>7}  {int(r['gt_label']):>3}  "
                f"{int(r['predicted']):>4}  {r['p_maneuver']:>8.4f}  "
                f"{str(r.get('behavior', ''))}"
            )
    else:
        print("  ✅ 全部分類正確！")
    print()


# ── Task 3：SHAP 分析 ────────────────────────────────────────────────────────

def shap_analysis(model, feature_cols: list[str]) -> None:
    """Task 3: SHAP summary analysis — 文字摘要 + bar chart + beeswarm PNG"""
    print("=" * 72)
    print("  3.  SHAP ANALYSIS  (Plan B LightGBM — test split)")
    print("=" * 72)

    try:
        import shap
    except ImportError:
        print("  [WARN] shap 未安裝。請執行：pip install shap")
        return

    if not PLAN_B.exists():
        print(f"  [WARN] Plan B CSV not found: {PLAN_B}")
        return

    # ── 讀取資料並用相同 seed=42 切分，取 test split ──────────────────────────
    # 需要把 dataset.py 的 random_split 加入路徑搜尋
    import sys as _sys
    _dir = str(Path(__file__).parent)
    if _dir not in _sys.path:
        _sys.path.insert(0, _dir)
    from dataset import random_split

    df = pd.read_csv(PLAN_B)
    label_col = "label" if "label" in df.columns else "label_binary"

    _, _, test_df = random_split(df, seed=42)
    print(f"\n  Test split: {len(test_df)} 行  "
          f"（正例={int((test_df[label_col]==1).sum())}  "
          f"負例={int((test_df[label_col]==0).sum())}）")

    # 對齊特徵欄位（缺欄補 NaN）
    missing = [c for c in feature_cols if c not in test_df.columns]
    if missing:
        print(f"  [INFO] 缺少特徵欄位（補 NaN）: {missing}")
        for c in missing:
            test_df[c] = np.nan

    X_test = test_df[feature_cols].values  # numpy array 加速 SHAP

    # ── 計算 SHAP values ────────────────────────────────────────────────────
    print("\n  計算 SHAP values（TreeExplainer）…")
    explainer   = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_test)

    # LightGBM binary: shap_values 可能是 list[2] 或單一 2D array
    if isinstance(shap_values, list):
        sv = shap_values[1]   # class=1 的 SHAP
    else:
        sv = shap_values      # 已經是 (n_samples, n_features)

    mean_abs = np.abs(sv).mean(axis=0)   # shape: (n_features,)

    # ── 文字版 SHAP summary（按 mean|SHAP| 排序）─────────────────────────────
    order = np.argsort(-mean_abs)        # 降序
    total = float(mean_abs.sum()) or 1.0
    print(f"\n  {'Rank':<4}  {'Feature':<22}  {'mean|SHAP|':>12}  {'%':>6}  {'Bar'}")
    print("  " + "-" * 70)
    for i, idx in enumerate(order):
        name = feature_cols[idx]
        val  = mean_abs[idx]
        pct  = val / total * 100
        print(f"  {i+1:<4}  {name:<22}  {val:>12.5f}  {pct:>5.1f}%  {_bar(val, mean_abs[order[0]])}")
    print()

    # ── 儲存圖片 ────────────────────────────────────────────────────────────
    OUTPUT.mkdir(parents=True, exist_ok=True)

    try:
        import matplotlib
        matplotlib.use("Agg")          # 非互動模式，必須在 import pyplot 之前
        import matplotlib.pyplot as plt

        # ── Bar chart（橫向，mean |SHAP value|） ────────────────────────────
        sorted_idx  = order[::-1]      # 由小到大，讓最大的顯示在最上面
        sorted_vals = mean_abs[sorted_idx]
        sorted_names = [feature_cols[i] for i in sorted_idx]

        fig, ax = plt.subplots(figsize=(9, 7))
        colors = plt.cm.RdYlGn(np.linspace(0.2, 0.9, len(sorted_vals)))[::-1]
        bars = ax.barh(range(len(sorted_vals)), sorted_vals, color=colors)
        ax.set_yticks(range(len(sorted_vals)))
        ax.set_yticklabels(sorted_names, fontsize=9)
        ax.set_xlabel("mean |SHAP value|", fontsize=11)
        ax.set_title("SHAP Feature Importance — Plan B LightGBM\n(mean absolute SHAP value, test split)", fontsize=11)
        ax.invert_yaxis()  # 最重要的在最上面
        plt.tight_layout()
        bar_path = OUTPUT / "shap_summary_bar.png"
        fig.savefig(bar_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"  [OK] SHAP bar chart 已儲存 → {bar_path}")

        # ── Beeswarm plot ────────────────────────────────────────────────────
        X_test_df = pd.DataFrame(X_test, columns=feature_cols)
        shap_exp  = shap.Explanation(
            values         = sv,
            base_values    = explainer.expected_value if not isinstance(explainer.expected_value, list)
                             else explainer.expected_value[1],
            data           = X_test_df.values,
            feature_names  = feature_cols,
        )
        fig2, ax2 = plt.subplots(figsize=(10, 7))
        shap.plots.beeswarm(shap_exp, max_display=22, show=False)
        bee_path = OUTPUT / "shap_beeswarm.png"
        plt.savefig(bee_path, dpi=150, bbox_inches="tight")
        plt.close("all")
        print(f"  [OK] SHAP beeswarm 已儲存 → {bee_path}")

    except Exception as e:
        print(f"  [WARN] 圖片儲存失敗：{e}")

    # 前 10 名摘要
    print(f"\n  Top-10 SHAP features:")
    for i, idx in enumerate(order[:10]):
        print(f"    {i+1:>2}. {feature_cols[idx]:<22}  mean|SHAP|={mean_abs[idx]:.5f}")
    print()


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not MODEL.exists():
        print(f"[ERROR] 模型未找到: {MODEL}", file=sys.stderr)
        sys.exit(1)

    model = joblib.load(MODEL)
    with open(FEAT_J, encoding="utf-8") as f:
        feature_cols: list[str] = json.load(f)
    with open(THR_J, encoding="utf-8") as f:
        threshold = float(json.load(f)["threshold"])

    print(f"\n  Model  : {MODEL}")
    print(f"  Features: {len(feature_cols)}  |  Threshold: {threshold:.4f}\n")

    feature_importance(model, feature_cols)
    external_validation(model, feature_cols, threshold)
    shap_analysis(model, feature_cols)


if __name__ == "__main__":
    main()
