"""dataset.py — Combine TLE features + maneuver labels, time-split, handle class imbalance."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Shared constants ──────────────────────────────────────────────────────────
TRAIN_END = "2026-05-15"
VAL_END   = "2026-05-20"
TEST_END  = "2026-05-25"

LABEL_NOMINAL     = 0
LABEL_MANEUVERING = 1
LABEL_EXCLUDED    = -1

FEATURE_COLS: list[str] = [
    "sma_km",
    "eccentricity",
    "inclination",
    "bstar",
    "d_sma_km",
    "d_ecc",
    "d_inc_deg",
    "d_raan_res_deg",
    "tle_gap_hours",
    "d_sma_per_day",
    "d_bstar",
    "sma_slope_km_day",
    "sma_std_km",
    "bstar_mean",
    "max_gap_h",
    "tle_count_7d",
]

# Plan B: 26-day window aggregate features (per-satellite, bstar_mean/std excluded — 100% NaN in local DB)
PLAN_B_FEATURE_COLS: list[str] = [
    "alt_km",
    "inc_deg",
    "ecc",
    "inc_family_enc",
    "net_da_km",
    "max_da_km",
    "da_std",
    "da_abs_mean",
    "max_di_deg",
    "max_draan_res_deg",
    "neg_streak",
    "total_drop_km",
    "monotone_decay",
    "n_transitions",
    "n_flagged",
    "flag_rate",
    "burn_freq_per_day",
    "n_windows_flagged",
    "n_tle",
    "mean_tle_gap_h",
    "max_tle_gap_h",
    "dv_net_ms",
]


# ── Public API ────────────────────────────────────────────────────────────────

def build_dataset(feature_df: pd.DataFrame, label_df: pd.DataFrame) -> pd.DataFrame:
    """Merge features and labels; drop excluded rows and NaN feature rows.

    Parameters
    ----------
    feature_df:
        DataFrame with at least columns ``norad_id``, ``epoch_utc``, and all
        ``FEATURE_COLS``.
    label_df:
        DataFrame with at least columns ``norad_id``, ``epoch_utc``, ``label``
        (values: LABEL_NOMINAL, LABEL_MANEUVERING, LABEL_EXCLUDED).

    Returns
    -------
    Merged DataFrame, inner-joined on [norad_id, epoch_utc], with excluded and
    NaN-feature rows removed.
    """
    logger.info(
        "build_dataset: feature_df=%d rows, label_df=%d rows",
        len(feature_df),
        len(label_df),
    )

    # Ensure epoch_utc is tz-aware UTC in both frames for consistent join
    feature_df = feature_df.copy()
    label_df = label_df.copy()
    feature_df["epoch_utc"] = pd.to_datetime(feature_df["epoch_utc"], utc=True)
    label_df["epoch_utc"] = pd.to_datetime(label_df["epoch_utc"], utc=True)

    merged = feature_df.merge(
        label_df[["norad_id", "epoch_utc", "label"]],
        on=["norad_id", "epoch_utc"],
        how="inner",
    )
    logger.info("After inner join: %d rows", len(merged))

    # Drop LABEL_EXCLUDED rows
    before_excl = len(merged)
    merged = merged[merged["label"] != LABEL_EXCLUDED].copy()
    logger.info(
        "Dropped %d LABEL_EXCLUDED rows → %d remaining",
        before_excl - len(merged),
        len(merged),
    )

    # Drop rows where any feature column is NaN (rolling-window warm-up)
    present_features = [c for c in FEATURE_COLS if c in merged.columns]
    missing_features = [c for c in FEATURE_COLS if c not in merged.columns]
    if missing_features:
        logger.warning("Feature columns not present in data: %s", missing_features)

    before_nan = len(merged)
    merged = merged.dropna(subset=present_features)
    logger.info(
        "Dropped %d rows with NaN features → %d remaining",
        before_nan - len(merged),
        len(merged),
    )

    logger.info(
        "build_dataset done: %d rows  |  class distribution: %s",
        len(merged),
        merged["label"].value_counts().to_dict(),
    )
    return merged.reset_index(drop=True)


def time_split(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split DataFrame into train / val / test by epoch_utc.

    Boundaries (non-overlapping, contiguous):
        train : epoch_utc < TRAIN_END
        val   : TRAIN_END <= epoch_utc < VAL_END
        test  : VAL_END   <= epoch_utc < TEST_END

    Parameters
    ----------
    df:
        Merged dataset from ``build_dataset()``, must contain ``epoch_utc``.

    Returns
    -------
    (train_df, val_df, test_df) tuple.
    """
    df = df.copy()
    df["epoch_utc"] = pd.to_datetime(df["epoch_utc"], utc=True)

    train_end = pd.Timestamp(TRAIN_END, tz="UTC")
    val_end   = pd.Timestamp(VAL_END,   tz="UTC")
    test_end  = pd.Timestamp(TEST_END,  tz="UTC")

    train = df[df["epoch_utc"] < train_end].copy()
    val   = df[(df["epoch_utc"] >= train_end) & (df["epoch_utc"] < val_end)].copy()
    test  = df[(df["epoch_utc"] >= val_end)   & (df["epoch_utc"] < test_end)].copy()

    for split_name, split_df in [("train", train), ("val", val), ("test", test)]:
        dist = split_df["label"].value_counts().to_dict() if len(split_df) > 0 else {}
        logger.info(
            "time_split [%s]: %d rows  |  class distribution: %s",
            split_name,
            len(split_df),
            dist,
        )

    return train, val, test


def random_split(
    df: pd.DataFrame,
    train_frac: float = 0.70,
    val_frac:   float = 0.15,
    seed:       int   = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Satellite-level stratified random split for Plan B (no epoch_utc).

    Splits on unique ``norad_id`` so the same satellite never spans splits,
    preserving the label ratio in each split.

    Returns
    -------
    (train_df, val_df, test_df)  — test_frac = 1 − train_frac − val_frac
    """
    rng        = np.random.default_rng(seed)
    label_col  = "label" if "label" in df.columns else "label_binary"

    # Unique satellite-label pairs for stratification
    sat_labels = df.groupby("norad_id")[label_col].max().reset_index()
    sat_labels = sat_labels.sample(frac=1, random_state=seed).reset_index(drop=True)

    pos = sat_labels[sat_labels[label_col] == 1]["norad_id"].tolist()
    neg = sat_labels[sat_labels[label_col] == 0]["norad_id"].tolist()

    def _split_ids(ids: list) -> tuple[list, list, list]:
        n     = len(ids)
        n_tr  = max(1, round(n * train_frac))
        n_val = max(1, round(n * val_frac))
        return ids[:n_tr], ids[n_tr:n_tr + n_val], ids[n_tr + n_val:]

    pos_tr, pos_val, pos_te = _split_ids(pos)
    neg_tr, neg_val, neg_te = _split_ids(neg)

    def _select(ids: list) -> pd.DataFrame:
        return df[df["norad_id"].isin(ids)].copy().reset_index(drop=True)

    train = _select(pos_tr + neg_tr)
    val   = _select(pos_val + neg_val)
    test  = _select(pos_te + neg_te)

    for name, split in [("train", train), ("val", val), ("test", test)]:
        dist = split[label_col].value_counts().to_dict() if len(split) > 0 else {}
        logger.info("random_split [%s]: %d rows  |  %s", name, len(split), dist)

    return train, val, test


def get_class_weights(y_train: np.ndarray | pd.Series) -> dict[int, float]:
    """Compute balanced class weights for LightGBM.

    Formula: w_i = n_total / (n_classes * n_i)

    Parameters
    ----------
    y_train:
        1-D array-like of integer labels (0, 1) for the training split.

    Returns
    -------
    dict ``{0: w0, 1: w1}`` suitable for ``class_weight`` parameter.
    """
    y = np.asarray(y_train, dtype=int)
    classes = np.unique(y)
    n_total = len(y)
    n_classes = len(classes)
    weights: dict[int, float] = {}

    for cls in classes:
        n_i = int((y == cls).sum())
        weights[int(cls)] = float(n_total) / (n_classes * n_i)

    logger.info("Class weights: %s", weights)
    return weights


def save_dataset(df: pd.DataFrame, path: str | Path) -> None:
    """Save DataFrame to Parquet (pyarrow engine), preserving dtypes.

    Parameters
    ----------
    df:
        DataFrame to persist.
    path:
        Destination file path (.parquet recommended).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, engine="pyarrow", index=False)
    logger.info("Dataset saved → %s  (%d rows)", path, len(df))


def load_dataset(path: str | Path) -> pd.DataFrame:
    """Load DataFrame from Parquet (pyarrow engine).

    Parameters
    ----------
    path:
        Source file path (.parquet).

    Returns
    -------
    DataFrame with dtypes preserved (including datetime columns).
    """
    path = Path(path)
    df = pd.read_parquet(path, engine="pyarrow")
    logger.info("Dataset loaded ← %s  (%d rows)", path, len(df))
    return df
