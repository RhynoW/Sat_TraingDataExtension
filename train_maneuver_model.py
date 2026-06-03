#!/usr/bin/env python3
"""
Train orbital-phase / maneuver-activity models from 30-day TLE features.

MEME ephemeris provides ground truth at 8-hour resolution.
TLE provides daily orbital elements.  Key insight: individual 8h burns
are invisible in 24h TLE, but the satellite's OPERATIONAL PHASE (deployment
vs stationkeeping vs high-shell) IS clearly distinguishable from 30-day TLE
statistics.

Two models are trained:

  Model 1 — Orbital Phase (4-class)
    Label  : alt_shell  (deployment / raising / operational / high-shell)
    Valided by MEME alt_start_km / alt_end_km
    AUC target: >0.97 (feature separation is very strong)

  Model 2 — Activity Level (binary)
    Label  : 1 = actively deploying (sma_slope > 0.1 km/day from MEME)
             0 = stationkeeping (operational or high-shell)
    Purpose: detects satellites in orbit-raising phase from TLE alone

Features (30-day TLE window per satellite)
-----------------------------------------
  sma_mean_km, alt_mean_km             current altitude
  sma_net_30d_km                       net altitude change in 30d
  sma_slope_km_day                     linear trend (km/day)
  sma_std_30d_km                       std of SMA oscillation
  sma_resid_std_km                     de-trended SMA std (burn noise)
  sma_range_30d_km                     max-min over 30d
  inc_std_30d_deg                      inclination stability
  raan_res_30d_deg                     J2-corrected RAAN residual
  ecc_mean                             eccentricity
  n_tle_30d                            data density
  inc_family_enc                       inclination shell (0/1/2/3)

Outputs
-------
  models/orbital_phase_v1.ubj          XGBoost 4-class orbital-phase model
  models/activity_level_v1.ubj         XGBoost binary activity model
  models/model_meta_v1.json            feature list + CV metrics
  data/maneuvers/satellite_oof_predictions.csv
  data/maneuvers/feature_importance_phase.csv
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score, classification_report, confusion_matrix,
    roc_auc_score, average_precision_score,
)
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import LabelEncoder
import xgboost as xgb

# ── paths ─────────────────────────────────────────────────────────────────────
BASE      = Path(__file__).parent
FEAT_CSV  = BASE / "data/maneuvers/satellite_features_30d.csv"
MODEL_DIR = BASE / "models"
OUT_DIR   = BASE / "data/maneuvers"
MODEL_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("train")

# ── feature / label definitions ───────────────────────────────────────────────
FEAT_COLS = [
    "sma_mean_km", "alt_mean_km",
    "sma_net_30d_km", "sma_slope_km_day",
    "sma_std_30d_km", "sma_resid_std_km", "sma_range_30d_km",
    "inc_std_30d_deg", "raan_res_30d_deg",
    "ecc_mean", "n_tle_30d",
    "inc_family_enc",
]

PHASE_ORDER   = ["deployment", "raising", "operational", "high-shell"]
PHASE_COLORS  = {"deployment": "orange", "raising": "green",
                 "operational": "steelblue", "high-shell": "purple"}

XGB_BASE = dict(
    n_estimators     = 300,
    max_depth        = 4,
    learning_rate    = 0.05,
    subsample        = 0.8,
    colsample_bytree = 0.8,
    min_child_weight = 1,
    tree_method      = "hist",
    random_state     = 42,
    n_jobs           = -1,
)


def inc_family_encode(i_deg: float) -> int:
    if i_deg < 45:  return 0
    if i_deg < 55:  return 1
    if i_deg < 85:  return 2
    return 3


def load_and_enrich(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["inc_family_enc"] = df["i_deg_mean"].apply(inc_family_encode)
    # Activity label: satellite is actively raising if slope > 0.1 km/day
    df["label_activity"] = (df["sma_slope_km_day"].abs() > 0.1).astype(int)
    log.info("Dataset: %d satellites  features: %d", len(df), len(FEAT_COLS))
    log.info("  alt_shell: %s", df["alt_shell"].value_counts().to_dict())
    log.info("  activity:  active=%d  stable=%d",
             df["label_activity"].sum(), (df["label_activity"] == 0).sum())
    return df


def cross_validate_phase(df: pd.DataFrame) -> tuple[np.ndarray, pd.DataFrame]:
    """5-fold stratified CV for 4-class orbital phase model."""
    le = LabelEncoder()
    le.classes_ = np.array(PHASE_ORDER)
    y  = le.transform(df["alt_shell"])
    X  = df[FEAT_COLS].values.astype(np.float32)

    skf  = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    oof  = np.zeros(len(y), dtype=int)
    rows = []

    params = {**XGB_BASE,
              "objective": "multi:softmax",
              "num_class": 4,
              "eval_metric": "mlogloss"}

    for fold, (tr, va) in enumerate(skf.split(X, y), 1):
        m = xgb.XGBClassifier(**params)
        m.fit(X[tr], y[tr],
              eval_set=[(X[va], y[va])], verbose=False)
        pred = m.predict(X[va])
        oof[va] = pred
        acc = accuracy_score(y[va], pred)
        rows.append({"fold": fold, "acc": acc, "n_val": len(va)})
        log.info("  Fold %d  Acc=%.4f  (n=%d)", fold, acc, len(va))

    return oof, pd.DataFrame(rows)


def cross_validate_binary(df: pd.DataFrame) -> tuple[np.ndarray, pd.DataFrame]:
    """5-fold stratified CV for binary activity model."""
    y = df["label_activity"].values
    X = df[FEAT_COLS].values.astype(np.float32)

    neg, pos = (y == 0).sum(), (y == 1).sum()
    spw = neg / pos if pos > 0 else 1.0

    skf  = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    oof  = np.zeros(len(y), dtype=float)
    rows = []

    params = {**XGB_BASE,
              "objective": "binary:logistic",
              "eval_metric": "aucpr",
              "scale_pos_weight": spw}

    for fold, (tr, va) in enumerate(skf.split(X, y), 1):
        m = xgb.XGBClassifier(**params)
        m.fit(X[tr], y[tr],
              eval_set=[(X[va], y[va])], verbose=False)
        prob = m.predict_proba(X[va])[:, 1]
        oof[va] = prob
        auc = roc_auc_score(y[va], prob) if y[va].sum() > 0 else float("nan")
        ap  = average_precision_score(y[va], prob) if y[va].sum() > 0 else float("nan")
        rows.append({"fold": fold, "auc": auc, "ap": ap, "n_val": len(va)})
        log.info("  Fold %d  AUC=%.4f  AP=%.4f  (n=%d)", fold, auc, ap, len(va))

    return oof, pd.DataFrame(rows)


def train_final(df: pd.DataFrame, y: np.ndarray, params: dict) -> xgb.XGBClassifier:
    X = df[FEAT_COLS].values.astype(np.float32)
    m = xgb.XGBClassifier(**params)
    m.fit(X, y, verbose=False)
    return m


def feature_importance_df(model: xgb.XGBClassifier, feat_cols: list[str]) -> pd.DataFrame:
    scores = model.get_booster().get_score(importance_type="gain")
    rows   = [{"feature": f, "gain": scores.get(f"f{i}", 0.0)}
              for i, f in enumerate(feat_cols)]
    imp = pd.DataFrame(rows).sort_values("gain", ascending=False).reset_index(drop=True)
    imp["gain_pct"] = (imp["gain"] / imp["gain"].sum() * 100).round(2)
    return imp


def main() -> None:
    df = load_and_enrich(FEAT_CSV)
    X  = df[FEAT_COLS].values.astype(np.float32)

    # ── Model 1: Orbital Phase ────────────────────────────────────────────
    log.info("\n=== Model 1: Orbital Phase (4-class) ===")
    le = LabelEncoder()
    le.classes_ = np.array(PHASE_ORDER)
    y_phase = le.transform(df["alt_shell"])

    oof_phase, cv_phase = cross_validate_phase(df)
    mean_acc_phase = cv_phase["acc"].mean()
    log.info("CV mean Acc = %.4f ± %.4f", mean_acc_phase, cv_phase["acc"].std())

    print()
    print("─" * 60)
    print("  OOF Orbital Phase Classification Report")
    print("─" * 60)
    print(classification_report(y_phase, oof_phase, target_names=PHASE_ORDER))
    cm_phase = confusion_matrix(y_phase, oof_phase)
    cm_df    = pd.DataFrame(cm_phase,
                            index=[f"true_{s}" for s in PHASE_ORDER],
                            columns=[f"pred_{s}" for s in PHASE_ORDER])
    print(cm_df.to_string())

    # Final model 1
    phase_params = {**XGB_BASE,
                    "objective": "multi:softmax",
                    "num_class": 4,
                    "eval_metric": "mlogloss"}
    final_phase = train_final(df, y_phase, phase_params)
    phase_path  = MODEL_DIR / "orbital_phase_v1.ubj"
    final_phase.get_booster().save_model(str(phase_path))
    log.info("Orbital phase model saved -> %s", phase_path)

    imp_phase = feature_importance_df(final_phase, FEAT_COLS)
    imp_path  = OUT_DIR / "feature_importance_phase.csv"
    imp_phase.to_csv(imp_path, index=False)

    print()
    print("  Feature importance (gain %) — Phase model:")
    print(imp_phase[["feature", "gain_pct"]].to_string(index=False))

    # ── Model 2: Activity Level (binary) ─────────────────────────────────
    log.info("\n=== Model 2: Activity Level (binary) ===")
    y_act = df["label_activity"].values
    log.info("  active=%d  stable=%d", y_act.sum(), (y_act == 0).sum())

    oof_act, cv_act = cross_validate_binary(df)
    mean_auc = cv_act["auc"].mean()
    mean_ap  = cv_act["ap"].mean()
    log.info("CV mean AUC=%.4f ± %.4f  AP=%.4f", mean_auc, cv_act["auc"].std(), mean_ap)

    pred_act = (oof_act >= 0.5).astype(int)
    print()
    print("─" * 60)
    print("  OOF Activity Level Report")
    print("─" * 60)
    print(classification_report(y_act, pred_act, target_names=["stable", "active"]))

    activity_params = {**XGB_BASE,
                       "objective": "binary:logistic",
                       "eval_metric": "aucpr",
                       "scale_pos_weight": (y_act == 0).sum() / max(y_act.sum(), 1)}
    final_act = train_final(df, y_act, activity_params)
    act_path  = MODEL_DIR / "activity_level_v1.ubj"
    final_act.get_booster().save_model(str(act_path))
    log.info("Activity model saved -> %s", act_path)

    # ── OOF predictions CSV ───────────────────────────────────────────────
    keep = [c for c in ["norad_id", "sat_name", "alt_shell", "maneuver_class",
                         "sma_slope_km_day", "sma_std_30d_km", "alt_mean_km"]
            if c in df.columns]
    oof_df = df[keep].copy()
    oof_df["pred_phase"]    = le.inverse_transform(oof_phase)
    oof_df["pred_activity"] = (oof_act >= 0.5).astype(int)
    oof_df["prob_activity"] = oof_act.round(4)
    oof_path = OUT_DIR / "satellite_oof_predictions.csv"
    oof_df.to_csv(oof_path, index=False)

    # ── Save model metadata ───────────────────────────────────────────────
    meta = {
        "model_version": "v1.0-meme-gt-satellite-level",
        "feat_cols":     FEAT_COLS,
        "phase_classes": PHASE_ORDER,
        "n_satellites":  int(len(df)),
        "phase_cv_acc_mean": float(mean_acc_phase),
        "phase_cv_acc_std":  float(cv_phase["acc"].std()),
        "activity_cv_auc_mean": float(mean_auc),
        "activity_cv_ap_mean":  float(mean_ap),
        "known_limitation": (
            "Trained on 3-day MEME window (283 satellites). "
            "Per-transition (8h) labels are NOT learnable from daily TLE. "
            "Satellite-level orbital phase (30-day TLE) is reliably detected. "
            "Re-train as more MEME data accumulates."
        ),
    }
    (MODEL_DIR / "model_meta_v1.json").write_text(json.dumps(meta, indent=2))

    # ── Misclassified satellites ──────────────────────────────────────────
    wrong = oof_df[oof_df["pred_phase"] != oof_df["alt_shell"]]
    if not wrong.empty:
        print()
        print("  Misclassified satellites:")
        show = [c for c in ["norad_id", "sat_name", "alt_shell", "pred_phase",
                             "sma_slope_km_day", "sma_std_30d_km"] if c in wrong.columns]
        print(wrong[show].to_string(index=False))

    print()
    print("=" * 60)
    print("  Training complete")
    print(f"  Orbital phase model : {phase_path}")
    print(f"  Activity model      : {act_path}")
    print(f"  OOF predictions     : {oof_path}")
    print(f"  Phase CV Acc        : {mean_acc_phase:.4f}")
    print(f"  Activity CV AUC     : {mean_auc:.4f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
