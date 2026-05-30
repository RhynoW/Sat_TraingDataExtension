"""evaluate.py — compute detection metrics for maneuver classifier."""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    f1_score,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)

logger = logging.getLogger(__name__)


def compute_metrics(
    y_true: np.ndarray | pd.Series,
    y_proba: np.ndarray | pd.Series,
    threshold: float = 0.5,
) -> dict:
    """Return dict: precision, recall, f1, auc_roc, avg_precision.

    Parameters
    ----------
    y_true:
        Ground-truth binary labels (0 = nominal, 1 = maneuvering).
    y_proba:
        Predicted probabilities for class 1.
    threshold:
        Decision threshold for converting probabilities to predictions.

    Returns
    -------
    dict with keys: precision, recall, f1, auc_roc, avg_precision,
                    n_pos, n_neg, threshold.
    """
    y_true = np.asarray(y_true, dtype=int)
    y_proba = np.asarray(y_proba, dtype=float)
    y_pred = (y_proba >= threshold).astype(int)

    report = classification_report(y_true, y_pred, output_dict=True, zero_division=0)
    has_both_classes = len(np.unique(y_true)) > 1

    metrics = {
        "precision": report.get("1", {}).get("precision", 0.0),
        "recall": report.get("1", {}).get("recall", 0.0),
        "f1": report.get("1", {}).get("f1-score", 0.0),
        "auc_roc": roc_auc_score(y_true, y_proba) if has_both_classes else float("nan"),
        "pr_auc": (
            average_precision_score(y_true, y_proba) if has_both_classes else float("nan")
        ),
        "n_pos": int(y_true.sum()),
        "n_neg": int((1 - y_true).sum()),
        "threshold": threshold,
    }

    logger.debug(
        "compute_metrics: threshold=%.3f  n_pos=%d  n_neg=%d  f1=%.4f  auc=%.4f",
        threshold,
        metrics["n_pos"],
        metrics["n_neg"],
        metrics["f1"],
        metrics["auc_roc"] if not np.isnan(metrics["auc_roc"]) else -1,
    )
    return metrics


def find_optimal_threshold(
    y_true: np.ndarray | pd.Series,
    y_proba: np.ndarray | pd.Series,
) -> float:
    """Youden's J statistic: argmax(TPR - FPR)."""
    y_true = np.asarray(y_true, dtype=int)
    y_proba = np.asarray(y_proba, dtype=float)

    fpr, tpr, thresholds = roc_curve(y_true, y_proba)
    j = tpr - fpr
    optimal_idx = int(np.argmax(j))
    optimal_threshold = float(thresholds[optimal_idx])

    logger.info(
        "Optimal threshold (Youden J): %.4f  TPR=%.4f  FPR=%.4f",
        optimal_threshold,
        tpr[optimal_idx],
        fpr[optimal_idx],
    )
    return optimal_threshold


def find_optimal_threshold_fbeta(
    y_true: np.ndarray | pd.Series,
    y_proba: np.ndarray | pd.Series,
    beta: float = 0.5,
) -> float:
    """F-beta optimal threshold via the precision-recall curve.

    Maximises F_beta = (1+β²)·P·R / (β²·P + R) over all candidate thresholds.
    beta < 1 favours Precision; beta > 1 favours Recall.
    Default beta=0.5 prioritises Precision over Recall, which is more useful
    when false-alarm cost is high (imbalanced operational setting).
    """
    y_true = np.asarray(y_true, dtype=int)
    y_proba = np.asarray(y_proba, dtype=float)

    precision, recall, thresholds = precision_recall_curve(y_true, y_proba)
    # precision_recall_curve returns arrays of length n+1; thresholds has length n.
    # precision[:-1] and recall[:-1] align with thresholds.
    p = precision[:-1]
    r = recall[:-1]

    b2 = beta ** 2
    denom = b2 * p + r
    with np.errstate(divide="ignore", invalid="ignore"):
        fbeta = np.where(denom > 0, (1 + b2) * p * r / denom, 0.0)

    optimal_idx = int(np.argmax(fbeta))
    optimal_threshold = float(thresholds[optimal_idx])

    logger.info(
        "Optimal threshold (F-beta=%.1f): %.4f  Precision=%.4f  Recall=%.4f  Fbeta=%.4f",
        beta,
        optimal_threshold,
        float(p[optimal_idx]),
        float(r[optimal_idx]),
        float(fbeta[optimal_idx]),
    )
    return optimal_threshold


def compute_lead_time(
    y_true_series: pd.Series,
    y_proba_series: pd.Series,
    timestamps: pd.Series,
    threshold: float = 0.5,
) -> float:
    """Mean hours between model alert and first true-positive label onset.

    y_true_series, y_proba_series, timestamps must be aligned pd.Series
    sorted by time.

    Parameters
    ----------
    y_true_series:
        Ground-truth binary labels aligned with timestamps.
    y_proba_series:
        Predicted probabilities aligned with timestamps.
    timestamps:
        Datetime series (pd.Timestamp) aligned with the above.
    threshold:
        Decision threshold for alert.

    Returns
    -------
    Mean lead time in hours. NaN if no true positives detected.
    """
    # Reset indices so alignment is consistent
    y_true = y_true_series.reset_index(drop=True)
    y_proba = y_proba_series.reset_index(drop=True)
    ts = pd.Series(pd.to_datetime(timestamps.values), name="timestamp")

    # Find transitions 0→1 in y_true (maneuver onset)
    onsets = ts[y_true.diff() == 1]
    leads: list[float] = []

    for onset_t in onsets:
        mask = (ts <= onset_t) & (y_proba >= threshold)
        if mask.any():
            alert_t = ts[mask].min()
            lead_hours = (onset_t - alert_t).total_seconds() / 3600.0
            leads.append(lead_hours)

    result = float(np.mean(leads)) if leads else float("nan")
    logger.info(
        "compute_lead_time: %d onsets found, %d detected, mean lead=%.2f h",
        len(onsets),
        len(leads),
        result if not np.isnan(result) else -1,
    )
    return result
