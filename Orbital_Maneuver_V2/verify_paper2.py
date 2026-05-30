#!/usr/bin/env python3
"""verify_paper2.py — 獨立驗證論文二所有核心數字"""
import io, sys, json, joblib
import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
sys.path.insert(0, "..")

from dataset import random_split, PLAN_B_FEATURE_COLS
from sklearn.metrics import roc_auc_score, precision_score, recall_score, f1_score

# ── 1. 資料切分驗證 ─────────────────────────────────────────────────────────
print("=" * 60)
print("1. 資料切分驗證")
print("=" * 60)

# 必須從 Parquet 讀取，與 train.py 路徑一致（norad_id 為 Int64，排序相同）
df_pq = pd.read_parquet("../data/maneuvers/training_dataset_final.parquet")
df    = df_pq[df_pq["plan"] == "B"].copy()
df    = df.rename(columns={"label_binary": "label"})
label_col = "label"

train_df, val_df, test_df = random_split(df, seed=42)
tr_ids = set(train_df["norad_id"])
va_ids = set(val_df["norad_id"])
te_ids = set(test_df["norad_id"])

print(f"全資料    : {len(df)} 行  pos={int((df[label_col]==1).sum())} neg={int((df[label_col]==0).sum())}")
print(f"train     : {len(train_df)} 行  pos={int((train_df[label_col]==1).sum())}")
print(f"val       : {len(val_df)} 行  pos={int((val_df[label_col]==1).sum())}")
print(f"test      : {len(test_df)} 行  pos={int((test_df[label_col]==1).sum())} neg={int((test_df[label_col]==0).sum())}")
print()

leak_tv = len(tr_ids & va_ids)
leak_tt = len(tr_ids & te_ids)
leak_vt = len(va_ids & te_ids)
print(f"train∩val  : {leak_tv}  (應=0)  {'PASS' if leak_tv==0 else 'FAIL'}")
print(f"train∩test : {leak_tt}  (應=0)  {'PASS' if leak_tt==0 else 'FAIL'}")
print(f"val∩test   : {leak_vt}  (應=0)  {'PASS' if leak_vt==0 else 'FAIL'}")

# ── 2. 特徵一致性 ────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("2. 特徵欄位一致性")
print("=" * 60)

with open("models_plan_b/feature_names.json", encoding="utf-8") as f:
    saved_feats = json.load(f)

diff = set(saved_feats) ^ set(PLAN_B_FEATURE_COLS)
print(f"feature_names.json  : {len(saved_feats)} 個特徵")
print(f"PLAN_B_FEATURE_COLS : {len(PLAN_B_FEATURE_COLS)} 個特徵")
print(f"差集（應為空）: {diff if diff else '(空) PASS'}")

# ── 3. LightGBM 指標重算 ─────────────────────────────────────────────────────
print()
print("=" * 60)
print("3. LightGBM 指標重算")
print("=" * 60)

model = joblib.load("models_plan_b/lgbm_maneuver_v1.pkl")
X_test = test_df[[c for c in saved_feats if c in test_df.columns]].copy()
for c in saved_feats:
    if c not in X_test.columns:
        X_test[c] = np.nan
X_test = X_test[saved_feats]
y = test_df[label_col].values.astype(int)
proba = model.predict_proba(X_test)[:, 1]

thr = 0.9180
pred = (proba >= thr).astype(int)

prec_val = precision_score(y, pred)
rec_val  = recall_score(y, pred)
f1_val   = f1_score(y, pred)
auc_val  = roc_auc_score(y, proba)

tp = int(((y==1)&(pred==1)).sum())
fp = int(((y==0)&(pred==1)).sum())
fn = int(((y==1)&(pred==0)).sum())
tn = int(((y==0)&(pred==0)).sum())

CLAIMED = {"Precision": 0.859, "Recall": 0.762, "F1": 0.808, "AUC-ROC": 0.9934}
ACTUAL  = {"Precision": prec_val, "Recall": rec_val, "F1": f1_val, "AUC-ROC": auc_val}

print(f"{'指標':<12} {'聲稱':>8}  {'實際':>8}  {'差值':>8}  {'判定'}")
print("-" * 55)
for k in CLAIMED:
    diff_v = ACTUAL[k] - CLAIMED[k]
    status = "PASS" if abs(diff_v) < 0.001 else "FAIL"
    print(f"{k:<12} {CLAIMED[k]:>8.4f}  {ACTUAL[k]:>8.4f}  {diff_v:>+8.4f}  {status}")
print()
print(f"混淆矩陣: TP={tp} FP={fp} FN={fn} TN={tn}")

# ── 4. SHAP Top-5 重算 ───────────────────────────────────────────────────────
print()
print("=" * 60)
print("4. SHAP Top-5 重算")
print("=" * 60)

try:
    import shap
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_test)
    if isinstance(shap_values, list):
        sv = shap_values[1]
    else:
        sv = shap_values
    mean_abs = np.abs(sv).mean(axis=0)
    total = float(mean_abs.sum())
    order = np.argsort(-mean_abs)
    CLAIMED_SHAP = {
        "n_flagged": 40.7, "flag_rate": 19.4, "da_std": 8.0,
        "alt_km": 6.3, "mean_tle_gap_h": 3.5
    }
    print(f"{'Rank':<4}  {'特徵':<22}  {'mean|SHAP|':>12}  {'%':>7}  {'聲稱%':>7}  {'判定'}")
    print("-" * 72)
    for i, idx in enumerate(order[:10]):
        name = saved_feats[idx]
        pct  = mean_abs[idx] / total * 100
        claimed = CLAIMED_SHAP.get(name)
        if claimed is not None:
            diff_s = pct - claimed
            status = "PASS" if abs(diff_s) < 1.0 else "CHECK"
            print(f"{i+1:<4}  {name:<22}  {mean_abs[idx]:>12.5f}  {pct:>6.1f}%  {claimed:>6.1f}%  {status}")
        else:
            print(f"{i+1:<4}  {name:<22}  {mean_abs[idx]:>12.5f}  {pct:>6.1f}%  {'N/A':>7}")
except ImportError:
    print("  [SKIP] shap 未安裝")

# ── 5. 多模型比較 ─────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("5. 多模型比較重算（RF + XGB + LightGBM）")
print("=" * 60)

def youden_thr(y_true, proba_v):
    P = y_true.sum(); N = len(y_true)-P
    if P==0 or N==0: return 0.5
    best_j, best_t = -np.inf, 0.5
    for t in np.unique(proba_v):
        p = (proba_v>=t).astype(int)
        tp_t=int(((p==1)&(y_true==1)).sum()); fp_t=int(((p==1)&(y_true==0)).sum())
        j = tp_t/P - fp_t/N
        if j > best_j: best_j, best_t = j, float(t)
    return best_t

X_tr  = train_df[PLAN_B_FEATURE_COLS].fillna(0).values
y_tr  = train_df[label_col].values.astype(int)
X_val = val_df[PLAN_B_FEATURE_COLS].fillna(0).values
y_val = val_df[label_col].values.astype(int)
X_te  = test_df[PLAN_B_FEATURE_COLS].fillna(0).values

results = []

# Naive
flag_te = test_df["flag_rate"].fillna(0).values
m_naive_pred = (flag_te >= 0.05).astype(int)
results.append({
    "模型": "Naive (flag_rate>0.05)",
    "Precision": precision_score(y, m_naive_pred),
    "Recall": recall_score(y, m_naive_pred),
    "F1": f1_score(y, m_naive_pred),
    "AUC-ROC": roc_auc_score(y, flag_te),
})

# Random Forest
from sklearn.ensemble import RandomForestClassifier
rf = RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=42, n_jobs=-1)
rf.fit(X_tr, y_tr)
rf_p_val = rf.predict_proba(X_val)[:, 1]
rf_thr   = youden_thr(y_val, rf_p_val)
rf_p_te  = rf.predict_proba(X_te)[:, 1]
rf_pred  = (rf_p_te >= rf_thr).astype(int)
results.append({
    "模型": "Random Forest",
    "Precision": precision_score(y, rf_pred),
    "Recall": recall_score(y, rf_pred),
    "F1": f1_score(y, rf_pred),
    "AUC-ROC": roc_auc_score(y, rf_p_te),
})

# XGBoost
try:
    import xgboost as xgb
    scale_pw = (y_tr==0).sum() / max((y_tr==1).sum(), 1)
    xm = xgb.XGBClassifier(n_estimators=300, scale_pos_weight=scale_pw,
                            random_state=42, eval_metric="logloss", verbosity=0)
    xm.fit(X_tr, y_tr)
    xb_p_val = xm.predict_proba(X_val)[:, 1]
    xb_thr   = youden_thr(y_val, xb_p_val)
    xb_p_te  = xm.predict_proba(X_te)[:, 1]
    xb_pred  = (xb_p_te >= xb_thr).astype(int)
    results.append({
        "模型": "XGBoost",
        "Precision": precision_score(y, xb_pred),
        "Recall": recall_score(y, xb_pred),
        "F1": f1_score(y, xb_pred),
        "AUC-ROC": roc_auc_score(y, xb_p_te),
    })
except ImportError:
    print("  [SKIP] xgboost 未安裝")

# LightGBM
results.append({
    "模型": "LightGBM (ours)",
    "Precision": prec_val,
    "Recall": rec_val,
    "F1": f1_val,
    "AUC-ROC": auc_val,
})

CLAIMED_MODELS = {
    "Naive (flag_rate>0.05)": (0.670, 0.351, 0.461, 0.9766),
    "Random Forest":          (0.735, 0.976, 0.839, 0.9921),
    "XGBoost":                (0.709, 0.988, 0.826, 0.9930),
    "LightGBM (ours)":        (0.859, 0.762, 0.808, 0.9934),
}

print(f"{'模型':<28} {'Prec':>7} {'Rec':>7} {'F1':>7} {'AUC':>8}  {'判定'}")
print("-" * 72)
for r in results:
    c = CLAIMED_MODELS.get(r["模型"])
    if c:
        diffs = [abs(r["Precision"]-c[0]), abs(r["Recall"]-c[1]),
                 abs(r["F1"]-c[2]), abs(r["AUC-ROC"]-c[3])]
        status = "PASS" if all(d < 0.01 for d in diffs) else "CHECK"
    else:
        status = "N/A"
    print(f"{r['模型']:<28} {r['Precision']:>6.1%} {r['Recall']:>6.1%} "
          f"{r['F1']:>6.1%} {r['AUC-ROC']:>7.4f}  {status}")

print()
print("[DONE] 驗證完成")
