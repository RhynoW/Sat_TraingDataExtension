"""train.py — CLI to train a LightGBM maneuver classifier from TLE data.

Usage
-----
    python train.py [--db DB_PATH] [--residuals GLOB] [--out-dir DIR]
                    [--norad-ids N [N ...]]

The script:
1. Builds per-satellite feature matrices via data_loader.build_feature_matrix().
2. Loads orbit-determination residuals and assigns binary labels via labeler.
3. Merges, splits by time, and trains LightGBMClassifier with early stopping.
4. Evaluates on val and test splits, prints a summary table, and saves the
   model + feature list.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

# Local modules (same package)
import dataset as ds
import evaluate

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────
_DEFAULT_DB         = "../space_db.duckdb"
_DEFAULT_RESIDUALS  = "../data/comparison/residuals_*.csv"
_DEFAULT_OUT_DIR    = "./models"


# ── Helpers ───────────────────────────────────────────────────────────────────

_DEFAULT_PARQUET = "../data/maneuvers/training_dataset_final.parquet"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train LightGBM maneuver classifier on TLE-derived features."
    )
    parser.add_argument(
        "--db",
        default=_DEFAULT_DB,
        help=f"Path to DuckDB database (default: {_DEFAULT_DB})",
    )
    parser.add_argument(
        "--residuals",
        default=_DEFAULT_RESIDUALS,
        help=f"Glob pattern for residual CSV files (default: {_DEFAULT_RESIDUALS})",
    )
    parser.add_argument(
        "--out-dir",
        default=_DEFAULT_OUT_DIR,
        help=f"Output directory for model + artifacts (default: {_DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--norad-ids",
        nargs="+",
        type=int,
        metavar="N",
        default=None,
        help="Restrict training to these NORAD IDs (default: all available)",
    )
    parser.add_argument(
        "--parquet",
        default=None,
        metavar="PATH",
        help=(
            "Load training data directly from Parquet (Plan B / combined). "
            "Bypasses DuckDB + MEME residuals pipeline. "
            f"(default: {_DEFAULT_PARQUET})"
        ),
    )
    parser.add_argument(
        "--plan",
        choices=["A", "B", "all"],
        default="B",
        help="Filter Parquet to plan A, B, or all rows (only used with --parquet, default: B)",
    )
    return parser.parse_args(argv)


def _load_data_loader():
    """Import data_loader lazily so missing dep gives a clear error."""
    try:
        import data_loader  # type: ignore[import]
        return data_loader
    except ImportError as exc:
        logger.error("Cannot import data_loader: %s", exc)
        sys.exit(1)


def _load_labeler():
    """Import labeler lazily so missing dep gives a clear error."""
    try:
        import labeler  # type: ignore[import]
        return labeler
    except ImportError as exc:
        logger.error("Cannot import labeler: %s", exc)
        sys.exit(1)


def _build_combined_df(
    norad_ids: list[int] | None,
    db_path: str,
    residuals_glob: str,
) -> pd.DataFrame:
    """Build feature + label DataFrame for all requested satellites.

    Parameters
    ----------
    norad_ids:
        List of NORAD IDs to process, or None for all available.
    db_path:
        Path to the DuckDB database.
    residuals_glob:
        Glob pattern pointing to residual CSV files.

    Returns
    -------
    Merged DataFrame ready for ``dataset.time_split()``.
    """
    data_loader = _load_data_loader()
    labeler_mod = _load_labeler()

    # Load residuals once (covers all satellites)
    residuals_df = labeler_mod.load_residuals(residuals_glob)

    # Resolve which NORAD IDs to process
    if norad_ids is None:
        all_db_ids = set(data_loader.list_norad_ids(db_path))
        res_ids = set(residuals_df["norad_id"].dropna().astype(int).unique())
        norad_ids = sorted(all_db_ids & res_ids)
        logger.info(
            "No --norad-ids given; auto-selected %d satellites (TLE ∩ MEME residuals)",
            len(norad_ids),
        )
    else:
        logger.info("Processing %d specified NORAD IDs", len(norad_ids))

    feature_frames: list[pd.DataFrame] = []
    label_frames: list[pd.DataFrame] = []

    for norad_id in norad_ids:
        logger.info("Building features for NORAD %d …", norad_id)
        try:
            feat_df = data_loader.build_feature_matrix(norad_id, db_path)
        except Exception as exc:
            logger.warning("Skipping NORAD %d — feature build failed: %s", norad_id, exc)
            continue

        # Filter residuals to this satellite only to avoid O(n_sats × n_residuals)
        sat_residuals = residuals_df[residuals_df["norad_id"] == norad_id]
        label_df = labeler_mod.assign_labels(feat_df, sat_residuals)

        feature_frames.append(feat_df)
        label_frames.append(label_df)

    if not feature_frames:
        logger.error("No feature data produced — aborting.")
        sys.exit(1)

    all_features = pd.concat(feature_frames, ignore_index=True)
    all_labels   = pd.concat(label_frames,   ignore_index=True)

    merged = ds.build_dataset(all_features, all_labels)
    return merged


def _print_summary(
    results: list[dict],
) -> None:
    """Print a formatted evaluation summary table to stdout."""
    header = (
        f"{'Split':<12}  {'Threshold':>10}  {'N':>8}  "
        f"{'Precision':>10}  {'Recall':>8}  {'F1':>8}  {'AUC-ROC':>9}  {'PR-AUC':>8}"
    )
    print()
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for r in results:
        auc_str = f"{r['auc_roc']:.4f}" if not np.isnan(r["auc_roc"]) else "    N/A "
        pr_str  = f"{r['pr_auc']:.4f}"  if not np.isnan(r["pr_auc"])  else "   N/A "
        thr_str = f"{r.get('threshold', 0.5):.4f}"
        print(
            f"{r['split']:<12}  {thr_str:>10}  {r['n_samples']:>8d}  "
            f"{r['precision']:>10.4f}  {r['recall']:>8.4f}  "
            f"{r['f1']:>8.4f}  {auc_str:>9}  {pr_str:>8}"
        )
    print("=" * len(header))
    print()


def _build_from_parquet(
    parquet_path: str,
    plan_filter: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    """Load Plan B (or combined) Parquet and return (train, val, test, feature_cols).

    Parameters
    ----------
    parquet_path : str
        Path to training_dataset_final.parquet.
    plan_filter : str
        "A", "B", or "all" — filter ``plan`` column in Parquet.

    Returns
    -------
    (train_df, val_df, test_df, feature_cols)
        Splits ready for LightGBM. ``feature_cols`` lists the columns used.
    """
    path = Path(parquet_path)
    if not path.exists():
        logger.error("Parquet not found: %s", path)
        sys.exit(1)

    df = pd.read_parquet(path, engine="pyarrow")
    logger.info("Loaded Parquet: %d rows × %d cols  from %s", len(df), df.shape[1], path)

    # ── plan filter ────────────────────────────────────────────────────────
    if "plan" in df.columns and plan_filter != "all":
        df = df[df["plan"] == plan_filter].copy().reset_index(drop=True)
        logger.info("After plan=%s filter: %d rows", plan_filter, len(df))

    # ── label column ──────────────────────────────────────────────────────
    if "label" not in df.columns:
        if "label_binary" in df.columns:
            df = df.rename(columns={"label_binary": "label"})
        else:
            logger.error("No 'label' or 'label_binary' column in Parquet")
            sys.exit(1)

    df["label"] = df["label"].astype(int)
    logger.info("label distribution: %s", df["label"].value_counts().to_dict())

    # ── feature selection ─────────────────────────────────────────────────
    # Use PLAN_B_FEATURE_COLS when plan B; fall back to union of available cols
    if plan_filter in ("B", "all"):
        candidate_cols = ds.PLAN_B_FEATURE_COLS
    else:
        candidate_cols = ds.FEATURE_COLS

    present  = [c for c in candidate_cols if c in df.columns]
    missing  = [c for c in candidate_cols if c not in df.columns]
    if missing:
        logger.warning("Feature columns not in Parquet (skipped): %s", missing)

    # Drop columns that are 100% NaN (e.g. bstar_mean/std when DB lacks bstar)
    all_nan = [c for c in present if df[c].isna().all()]
    if all_nan:
        logger.warning("Dropping 100%% NaN feature columns: %s", all_nan)
        present = [c for c in present if c not in all_nan]

    # Drop rows with any remaining NaN feature
    before_nan = len(df)
    df = df.dropna(subset=present).reset_index(drop=True)
    logger.info(
        "Dropped %d NaN-feature rows → %d remaining  |  features=%d",
        before_nan - len(df), len(df), len(present),
    )

    # ── split ─────────────────────────────────────────────────────────────
    # Plan B has no epoch_utc → use satellite-level stratified random split
    if "epoch_utc" in df.columns and plan_filter == "A":
        train_df, val_df, test_df = ds.time_split(df)
    else:
        train_df, val_df, test_df = ds.random_split(df)

    return train_df, val_df, test_df, present


# ── Entry point ───────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    """Train LightGBM classifier and save model artifacts."""
    args = _parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Output directory: %s", out_dir.resolve())

    # ── 1. Build / load feature+label dataset ───────────────────────────────
    parquet_path = args.parquet or _DEFAULT_PARQUET
    if Path(parquet_path).exists():
        # Parquet 模式（Plan B / combined）
        train_df, val_df, test_df, present_features = _build_from_parquet(
            parquet_path, plan_filter=args.plan
        )
    else:
        # 原始 DuckDB + MEME 殘差模式（Plan A）
        logger.info("Parquet not found at %s — falling back to DuckDB/MEME mode", parquet_path)
        merged_df = _build_combined_df(
            norad_ids=args.norad_ids,
            db_path=args.db,
            residuals_glob=args.residuals,
        )
        train_df, val_df, test_df = ds.time_split(merged_df)
        present_features = [c for c in ds.FEATURE_COLS if c in train_df.columns]
        missing_features = [c for c in ds.FEATURE_COLS if c not in train_df.columns]
        if missing_features:
            logger.warning("Missing feature columns (will be skipped): %s", missing_features)

    # ── 2. Validate split sizes ──────────────────────────────────────────────
    if len(train_df) == 0:
        logger.error("Training split is empty.")
        sys.exit(1)

    X_train = train_df[present_features]
    y_train = train_df["label"].values.astype(int)

    X_val = val_df[present_features]   if len(val_df)  > 0 else pd.DataFrame(columns=present_features)
    y_val = val_df["label"].values.astype(int) if len(val_df) > 0 else np.array([], dtype=int)

    X_test = test_df[present_features]    if len(test_df)  > 0 else pd.DataFrame(columns=present_features)
    y_test = test_df["label"].values.astype(int) if len(test_df) > 0 else np.array([], dtype=int)

    # ── 3. Train LightGBM ────────────────────────────────────────────────────
    logger.info(
        "Training LightGBM: X_train=%s  positives=%d",
        X_train.shape,
        int(y_train.sum()),
    )

    model = lgb.LGBMClassifier(
        n_estimators=1000,
        learning_rate=0.05,
        num_leaves=15,
        min_child_samples=10,
        reg_lambda=1.0,
        class_weight="balanced",    # N_neg/N_pos ≈ 14.4; lowering scale_pos_weight causes premature early stopping
        random_state=42,
        n_jobs=-1,
    )

    eval_set = [(X_val, y_val)] if len(X_val) > 0 else []  # type: ignore[arg-type]
    callbacks = [lgb.early_stopping(50), lgb.log_evaluation(100)]

    model.fit(
        X_train,
        y_train,
        eval_set=eval_set if eval_set else None,
        callbacks=callbacks if eval_set else [lgb.log_evaluation(100)],
    )
    logger.info("Training complete. Best iteration: %s", model.best_iteration_)

    # ── 4. Evaluate ──────────────────────────────────────────────────────────

    # Find optimal threshold via F-beta (β=0.5, prioritises Precision) on val split.
    # Requires val to be non-empty and contain at least one positive sample.
    best_threshold: float = 0.5
    if len(y_val) > 0 and int(y_val.sum()) > 0:
        proba_val = model.predict_proba(X_val)[:, 1]
        best_threshold = evaluate.find_optimal_threshold_fbeta(y_val, proba_val, beta=0.5)
        logger.info(
            "Optimal threshold (F-beta=0.5) on val split: %.4f", best_threshold
        )
    else:
        logger.warning(
            "Val split empty or has no positives — falling back to threshold=0.5"
        )

    results: list[dict] = []

    for split_name, X_s, y_s in [
        ("train", X_train, y_train),
        ("val",   X_val,   y_val),
        ("test",  X_test,  y_test),
    ]:
        if len(y_s) == 0:
            logger.warning("Split '%s' is empty — skipping evaluation.", split_name)
            continue
        proba = model.predict_proba(X_s)[:, 1]

        # Row 1 — default threshold 0.5
        metrics_default = evaluate.compute_metrics(y_s, proba, threshold=0.5)
        results.append(
            {
                "split":     split_name,
                "n_samples": len(y_s),
                **metrics_default,
            }
        )

        # Row 2 — optimal threshold (skip duplicate row when best_threshold == 0.5)
        if abs(best_threshold - 0.5) > 1e-6:
            metrics_opt = evaluate.compute_metrics(
                y_s, proba, threshold=best_threshold
            )
            results.append(
                {
                    "split":     f"{split_name}@opt",
                    "n_samples": len(y_s),
                    **metrics_opt,
                }
            )

    # ── 5. Save model + feature names + threshold ────────────────────────────
    model_path = out_dir / "lgbm_maneuver_v1.pkl"
    joblib.dump(model, model_path)
    logger.info("Model saved → %s", model_path)

    feature_names_path = out_dir / "feature_names.json"
    with open(feature_names_path, "w", encoding="utf-8") as fh:
        json.dump(present_features, fh, indent=2)
    logger.info("Feature names saved → %s", feature_names_path)

    threshold_path = out_dir / "threshold.json"
    with open(threshold_path, "w", encoding="utf-8") as fh:
        json.dump({"threshold": float(best_threshold), "method": "f_beta_0.5"}, fh, indent=2)
    logger.info("Threshold saved → %s  (%.4f)", threshold_path, best_threshold)

    # ── 6. Print summary ─────────────────────────────────────────────────────
    _print_summary(results)


if __name__ == "__main__":
    main()
