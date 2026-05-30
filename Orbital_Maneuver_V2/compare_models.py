#!/usr/bin/env python3
"""
compare_models.py
==================
對同一個 Plan B 資料集，比較 4 種模型：
  1. Naive Threshold Baseline  (flag_rate > 0.05)
  2. Random Forest             (sklearn)
  3. XGBoost                   (若已安裝)
  4. LightGBM                  (已訓練的模型，直接載入)

時間泛化說明
------------
NOTE: training_samples_plan_b.csv 不含時間欄位（obs_start / date_tag 等），
每筆資料是「一顆衛星的 26 天觀測窗口聚合特徵」，
無法按時間切分做 temporal validation。
此處採用 random_split(seed=42)，與訓練時保持一致，確保 test set 不洩漏。

輸出
----
  控制台：比較表格
  Orbital_Maneuver_V2/output/model_comparison.csv
  Orbital_Maneuver_V2/output/roc_comparison.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
BASE     = Path(__file__).parent
PLAN_B   = BASE.parent / "data/maneuvers/training_samples_plan_b.csv"
MODEL    = BASE / "models_plan_b/lgbm_maneuver_v1.pkl"
FEAT_J   = BASE / "models_plan_b/feature_names.json"
THR_J    = BASE / "models_plan_b/threshold.json"
OUTPUT   = BASE / "output"

# dataset.py 所在目錄加入 sys.path
_dir = str(BASE)
if _dir not in sys.path:
    sys.path.insert(0, _dir)
from dataset import random_split, PLAN_B_FEATURE_COLS  # noqa: E402


# ── 工具函數 ──────────────────────────────────────────────────────────────────

def _youden_threshold(y_true: np.ndarray, proba: np.ndarray) -> float:
    """Youden's J = Sensitivity + Specificity - 1，找最佳閾值。"""
    fpr, tpr, thresholds = roc_curve(y_true, proba)
    j_scores = tpr - fpr
    best_idx = int(np.argmax(j_scores))
    return float(thresholds[best_idx])


def _eval(y_true: np.ndarray, proba: np.ndarray, threshold: float) -> dict:
    """計算 Precision / Recall / F1 / AUC-ROC（以指定閾值二值化）。"""
    y_pred = (proba >= threshold).astype(int)
    auc = roc_auc_score(y_true, proba) if len(np.unique(y_true)) > 1 else float("nan")
    return {
        "precision": precision_score(y_true, y_pred, zero_division=0),
        "recall":    recall_score(y_true,    y_pred, zero_division=0),
        "f1":        f1_score(y_true,         y_pred, zero_division=0),
        "auc_roc":   auc,
    }


# ── 資料載入與切分 ────────────────────────────────────────────────────────────

def load_and_split():
    """讀取 Plan B CSV，用 random_split(seed=42) 切分。"""
    if not PLAN_B.exists():
        print(f"[ERROR] Plan B CSV not found: {PLAN_B}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(PLAN_B)
    label_col = "label" if "label" in df.columns else "label_binary"
    print(f"  資料集: {len(df)} 行 × {len(df.columns)} 欄  "
          f"(正={int((df[label_col]==1).sum())}  負={int((df[label_col]==0).sum())})")

    train_df, val_df, test_df = random_split(df, seed=42)
    print(f"  Train: {len(train_df)}  Val: {len(val_df)}  Test: {len(test_df)}\n")
    return train_df, val_df, test_df, label_col


def _get_X_y(df: pd.DataFrame, feature_cols: list[str], label_col: str):
    """從 DataFrame 取出 X (填補缺欄) 和 y。"""
    for c in feature_cols:
        if c not in df.columns:
            df[c] = np.nan
    X = df[feature_cols].values.astype(float)
    y = df[label_col].values.astype(int)
    return X, y


# ── 各模型評估 ────────────────────────────────────────────────────────────────

def eval_naive(train_df, val_df, test_df, feature_cols, label_col) -> dict:
    """Naive: flag_rate > 0.05 作為 binary 預測（不需訓練）。"""
    print("  [1/4] Naive Threshold Baseline (flag_rate > 0.05)…")

    if "flag_rate" not in test_df.columns:
        print("    [WARN] flag_rate 欄位不存在，跳過 Naive baseline。")
        return {}

    y_test  = test_df[label_col].values.astype(int)
    y_pred  = (test_df["flag_rate"].fillna(0).values > 0.05).astype(int)
    # 沒有連續機率，使用 flag_rate 本身作為 score 計算 AUC
    scores  = test_df["flag_rate"].fillna(0).values
    auc_val = roc_auc_score(y_test, scores) if len(np.unique(y_test)) > 1 else float("nan")

    return {
        "model":     "Naive (flag_rate>0.05)",
        "precision": precision_score(y_test, y_pred, zero_division=0),
        "recall":    recall_score(y_test,    y_pred, zero_division=0),
        "f1":        f1_score(y_test,         y_pred, zero_division=0),
        "auc_roc":   auc_val,
        "threshold": "flag_rate>0.05",
        "proba":     scores,
        "y_true":    y_test,
    }


def eval_rf(train_df, val_df, test_df, feature_cols, label_col) -> dict:
    """Random Forest (sklearn)，Youden 閾值。"""
    from sklearn.ensemble import RandomForestClassifier

    print("  [2/4] Random Forest (n_estimators=300)…")

    X_train, y_train = _get_X_y(train_df, feature_cols, label_col)
    X_val,   y_val   = _get_X_y(val_df,   feature_cols, label_col)
    X_test,  y_test  = _get_X_y(test_df,  feature_cols, label_col)

    rf = RandomForestClassifier(
        n_estimators=300,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    rf.fit(X_train, y_train)

    # 在 val split 找最佳 Youden 閾值
    val_proba = rf.predict_proba(X_val)[:, 1]
    thr = _youden_threshold(y_val, val_proba)

    test_proba = rf.predict_proba(X_test)[:, 1]
    m = _eval(y_test, test_proba, thr)

    return {
        "model":     "Random Forest",
        **m,
        "threshold": thr,
        "proba":     test_proba,
        "y_true":    y_test,
    }


def eval_xgb(train_df, val_df, test_df, feature_cols, label_col) -> dict | None:
    """XGBoost（若已安裝），Youden 閾值。"""
    try:
        import xgboost as xgb
    except ImportError:
        print("  [3/4] XGBoost 未安裝，跳過。")
        return None

    print("  [3/4] XGBoost (n_estimators=300)…")

    X_train, y_train = _get_X_y(train_df, feature_cols, label_col)
    X_val,   y_val   = _get_X_y(val_df,   feature_cols, label_col)
    X_test,  y_test  = _get_X_y(test_df,  feature_cols, label_col)

    # neg/pos ratio 用 train split 計算
    n_pos = int(y_train.sum())
    n_neg = int((y_train == 0).sum())
    spw   = n_neg / n_pos if n_pos > 0 else 1.0

    xgb_model = xgb.XGBClassifier(
        n_estimators=300,
        scale_pos_weight=spw,
        random_state=42,
        eval_metric="logloss",
        verbosity=0,
    )
    xgb_model.fit(X_train, y_train)

    val_proba  = xgb_model.predict_proba(X_val)[:, 1]
    thr        = _youden_threshold(y_val, val_proba)
    test_proba = xgb_model.predict_proba(X_test)[:, 1]
    m          = _eval(y_test, test_proba, thr)

    return {
        "model":     "XGBoost",
        **m,
        "threshold": thr,
        "proba":     test_proba,
        "y_true":    y_test,
    }


def eval_lgbm(test_df, feature_cols, label_col) -> dict:
    """LightGBM：直接載入已訓練模型，使用 threshold=0.9180。"""
    print("  [4/4] LightGBM (已訓練模型，threshold=0.9180)…")

    if not MODEL.exists():
        print(f"  [WARN] 模型未找到: {MODEL}")
        return {}

    model = joblib.load(MODEL)
    with open(THR_J, encoding="utf-8") as f:
        thr = float(json.load(f)["threshold"])

    X_test, y_test = _get_X_y(test_df, feature_cols, label_col)
    proba = model.predict_proba(X_test)[:, 1]
    m     = _eval(y_test, proba, thr)

    return {
        "model":     "LightGBM (ours)",
        **m,
        "threshold": thr,
        "proba":     proba,
        "y_true":    y_test,
    }


# ── 輸出：表格 + CSV + ROC 圖 ─────────────────────────────────────────────────

def print_table(results: list[dict]) -> None:
    """控制台印出比較表格。"""
    hdr = f"  {'模型':<28}  {'Precision':>10}  {'Recall':>8}  {'F1':>8}  {'AUC-ROC':>9}  {'閾值':>12}"
    print("=" * 82)
    print("  多模型比較（Plan B test split，random_split seed=42）")
    print("=" * 82)
    print(hdr)
    print("  " + "-" * 78)
    for r in results:
        if not r:
            continue
        thr_str = r["threshold"] if isinstance(r["threshold"], str) else f"{r['threshold']:.4f}"
        print(
            f"  {r['model']:<28}  "
            f"{r['precision']:>9.1%}  "
            f"{r['recall']:>8.1%}  "
            f"{r['f1']:>8.1%}  "
            f"{r['auc_roc']:>9.4f}  "
            f"{thr_str:>12}"
        )
    print()


def save_csv(results: list[dict]) -> None:
    """儲存 model_comparison.csv。"""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in results:
        if not r:
            continue
        rows.append({
            "model":     r["model"],
            "precision": round(r["precision"] * 100, 2),
            "recall":    round(r["recall"]    * 100, 2),
            "f1":        round(r["f1"]        * 100, 2),
            "auc_roc":   round(r["auc_roc"],         4),
            "threshold": r["threshold"],
        })
    out = OUTPUT / "model_comparison.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"  [OK] CSV 已儲存 → {out}")


def save_roc(results: list[dict]) -> None:
    """儲存 ROC 曲線比較圖。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  [WARN] matplotlib 未安裝，跳過 ROC 圖。")
        return

    COLORS = ["#e74c3c", "#2980b9", "#27ae60", "#8e44ad", "#e67e22"]
    fig, ax = plt.subplots(figsize=(8, 7))

    # 對角線（random baseline）
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="Random (AUC=0.50)")

    for i, r in enumerate(results):
        if not r or np.isnan(r.get("auc_roc", float("nan"))):
            continue
        y_true = r["y_true"]
        proba  = r["proba"]
        # Naive 可能沒有連續機率（flag_rate），仍可畫 ROC
        fpr, tpr, _ = roc_curve(y_true, proba)
        color = COLORS[i % len(COLORS)]
        ax.plot(fpr, tpr, lw=2, color=color,
                label=f"{r['model']}  (AUC={r['auc_roc']:.4f})")

    ax.set_xlabel("False Positive Rate", fontsize=12)
    ax.set_ylabel("True Positive Rate",  fontsize=12)
    ax.set_title("ROC Curve Comparison — Plan B Models\n(test split, random_split seed=42)", fontsize=11)
    ax.legend(loc="lower right", fontsize=9)
    ax.set_xlim([-0.01, 1.01])
    ax.set_ylim([-0.01, 1.01])
    ax.grid(True, alpha=0.3)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    out = OUTPUT / "roc_comparison.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [OK] ROC 圖已儲存 → {out}")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n" + "=" * 82)
    print("  compare_models.py — Plan B 多模型比較")
    print("=" * 82 + "\n")

    # 1. 載入特徵欄位
    with open(FEAT_J, encoding="utf-8") as f:
        feature_cols: list[str] = json.load(f)
    print(f"  特徵數: {len(feature_cols)}\n")

    # 2. 讀取並切分資料
    train_df, val_df, test_df, label_col = load_and_split()

    # 3. 各模型評估
    results: list[dict] = []

    naive_r = eval_naive(train_df, val_df, test_df, feature_cols, label_col)
    results.append(naive_r)

    rf_r = eval_rf(train_df, val_df, test_df, feature_cols, label_col)
    results.append(rf_r)

    xgb_r = eval_xgb(train_df, val_df, test_df, feature_cols, label_col)
    if xgb_r:
        results.append(xgb_r)

    lgbm_r = eval_lgbm(test_df, feature_cols, label_col)
    results.append(lgbm_r)

    print()

    # 4. 輸出
    print_table(results)
    save_csv(results)
    save_roc(results)

    print("\n  NOTE (Temporal Validation): training_samples_plan_b.csv 不含時間欄位，")
    print("  無法做 temporal validation。每筆是 26 天窗口聚合特徵，")
    print("  已改用 random_split(seed=42) 確保與訓練時 test set 一致。\n")


if __name__ == "__main__":
    main()
