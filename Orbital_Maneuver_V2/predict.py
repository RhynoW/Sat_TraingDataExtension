"""predict.py — CLI inference: score a satellite's TLE history with the trained model.

Usage
-----
    python predict.py --norad NORAD_ID
                      [--db DB_PATH]
                      [--model MODEL_PKL]
                      [--start START_UTC]
                      [--end END_UTC]

The script:
1. Loads the saved LightGBMClassifier (joblib) and companion feature_names.json.
2. Builds the feature matrix for the requested satellite via data_loader.
3. Scores every epoch; prints an alert table to stdout.
4. Saves a CSV with all feature columns + predicted probability.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb
import joblib
import numpy as np
import pandas as pd

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────
_DEFAULT_DB           = "../space_db.duckdb"
_DEFAULT_MODEL_PKL    = "./models/lgbm_maneuver_v1.pkl"
_DEFAULT_MODEL_PLAN_B = "./models_plan_b/lgbm_maneuver_v1.pkl"
_ALERT_THRESHOLD      = 0.5

# Plan B 物理常數（與 build_training_dataset.py 一致）
_MU      = 398_600.4418
_R_E     = 6_378.137
_J2      = 1.082_63e-3
_THR_DI    = 0.02
_THR_DE    = 0.001
_THR_DRAAN = 0.1
_OBS_DAYS  = 26.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run maneuver inference on a satellite using TLE-derived features."
    )
    parser.add_argument(
        "--norad",
        required=True,
        type=int,
        metavar="NORAD_ID",
        help="NORAD catalog ID of the target satellite.",
    )
    parser.add_argument(
        "--db",
        default=_DEFAULT_DB,
        help=f"Path to DuckDB database (default: {_DEFAULT_DB})",
    )
    parser.add_argument(
        "--model",
        default=_DEFAULT_MODEL_PKL,
        help=f"Path to saved model .pkl (default: {_DEFAULT_MODEL_PKL})",
    )
    parser.add_argument(
        "--start",
        default=None,
        metavar="START_UTC",
        help="Start datetime in ISO-8601 format, e.g. 2026-05-01T00:00:00 (optional).",
    )
    parser.add_argument(
        "--end",
        default=None,
        metavar="END_UTC",
        help="End datetime in ISO-8601 format, e.g. 2026-05-25T00:00:00 (optional).",
    )

    thresh_group = parser.add_mutually_exclusive_group()
    thresh_group.add_argument(
        "--threshold",
        type=float,
        default=None,
        metavar="FLOAT",
        help=(
            "Override decision threshold (e.g. 0.35). "
            "Mutually exclusive with --auto-threshold."
        ),
    )
    thresh_group.add_argument(
        "--auto-threshold",
        action="store_true",
        default=False,
        help=(
            "Force-read decision threshold from models/threshold.json. "
            "Exits with error if the file does not exist. "
            "Mutually exclusive with --threshold."
        ),
    )

    parser.add_argument(
        "--plan-b",
        action="store_true",
        default=False,
        help=(
            "Use Plan B model (26-day window aggregate features). "
            "Automatically sets --model to models_plan_b/lgbm_maneuver_v1.pkl "
            "if --model is not also specified."
        ),
    )
    return parser.parse_args(argv)


def _resolve_threshold(args: argparse.Namespace, model_path: Path) -> float:
    """Determine the decision threshold from CLI args or threshold.json.

    Priority
    --------
    1. ``--threshold FLOAT``  → use that value directly.
    2. ``--auto-threshold``   → read ``<model_dir>/threshold.json``; exit if missing.
    3. Neither flag           → try ``<model_dir>/threshold.json``; fall back to 0.5.
    """
    threshold_json = model_path.parent / "threshold.json"

    if args.threshold is not None:
        return float(args.threshold)

    if args.auto_threshold:
        if not threshold_json.exists():
            logger.error(
                "--auto-threshold requested but threshold.json not found: %s",
                threshold_json,
            )
            sys.exit(1)
        with open(threshold_json, encoding="utf-8") as fh:
            data = json.load(fh)
        return float(data["threshold"])

    # Neither flag: best-effort read, fallback to _ALERT_THRESHOLD
    if threshold_json.exists():
        with open(threshold_json, encoding="utf-8") as fh:
            data = json.load(fh)
        return float(data["threshold"])

    logger.info("No threshold.json found; using default threshold 0.5")
    return _ALERT_THRESHOLD


def _load_model_and_features(
    model_path: Path,
) -> tuple[object, list[str]]:
    """Load the serialised LightGBM model and its feature name list.

    Parameters
    ----------
    model_path:
        Path to the ``lgbm_maneuver_v1.pkl`` file produced by train.py.

    Returns
    -------
    (model, feature_cols) tuple.
    """
    if not model_path.exists():
        logger.error("Model file not found: %s", model_path)
        sys.exit(1)

    model = joblib.load(model_path)
    logger.info("Model loaded ← %s", model_path)

    feature_names_path = model_path.parent / "feature_names.json"
    if not feature_names_path.exists():
        logger.error("feature_names.json not found next to model: %s", feature_names_path)
        sys.exit(1)

    with open(feature_names_path, encoding="utf-8") as fh:
        feature_cols: list[str] = json.load(fh)
    logger.info("Feature names loaded: %d columns", len(feature_cols))

    return model, feature_cols


def _load_data_loader():
    try:
        import data_loader  # type: ignore[import]
        return data_loader
    except ImportError as exc:
        logger.error("Cannot import data_loader: %s", exc)
        sys.exit(1)


def _adaptive_thr_da(sma_km: float) -> float:
    alt = sma_km - _R_E
    if alt < 400:  return 2.0
    if alt > 600:  return 0.5
    return 1.0


def _j2_raan_rate(sma: float, ecc: float, inc_deg: float) -> float:
    i = np.radians(inc_deg)
    n = np.sqrt(_MU / sma ** 3)
    p = sma * (1 - ecc ** 2)
    return np.degrees(-1.5 * n * _J2 * (_R_E / p) ** 2 * np.cos(i))


def _angle_diff(a: float, b: float) -> float:
    d = (b - a) % 360.0
    return d - 360.0 if d > 180.0 else d


def _inc_family(i: float) -> int:
    if i < 45: return 0
    if i < 55: return 1
    if i < 85: return 2
    return 3


def _build_plan_b_features(
    norad_id: int,
    db_path: str,
    start_utc: str | None,
    end_utc: str | None,
) -> pd.DataFrame | None:
    """
    26 天窗口聚合特徵提取（Plan B 模型用）。
    回傳 1 列 DataFrame；TLE < 3 筆時回傳 None。
    """
    # 日期範圍
    end_dt   = pd.Timestamp(end_utc)   if end_utc   else pd.Timestamp.utcnow().normalize()
    start_dt = pd.Timestamp(start_utc) if start_utc else end_dt - pd.Timedelta(days=_OBS_DAYS)
    s_str = start_dt.strftime("%Y-%m-%d")
    e_str = end_dt.strftime("%Y-%m-%d 23:59:59")

    # 查詢 TLE
    con = duckdb.connect(db_path, read_only=True)
    try:
        cols      = con.execute("DESCRIBE tle_table").df()["column_name"].str.lower().tolist()
        bstar_sel = ", bstar" if "bstar" in cols else ", NULL::DOUBLE AS bstar"
        tle = con.execute(f"""
            SELECT date_tag, sma_km, eccentricity, inclination_deg, raan_deg{bstar_sel}
            FROM tle_table
            WHERE norad_id = {norad_id}
              AND date_tag BETWEEN TIMESTAMP '{s_str}' AND TIMESTAMP '{e_str}'
            ORDER BY date_tag
        """).df()
    finally:
        con.close()

    if len(tle) < 3:
        logger.warning("NORAD %d: 僅 %d 筆 TLE（需 ≥ 3）", norad_id, len(tle))
        return None

    tle["date_tag"] = pd.to_datetime(tle["date_tag"])
    tle = tle.sort_values("date_tag").reset_index(drop=True)
    first = tle.iloc[0]
    a0, i0, e0 = float(first["sma_km"]), float(first["inclination_deg"]), float(first["eccentricity"])

    # bstar 統計
    bv = tle["bstar"].dropna() if "bstar" in tle.columns else pd.Series([], dtype=float)
    bstar_mean = float(bv.mean()) if len(bv) else np.nan
    bstar_std  = float(bv.std())  if len(bv) > 1 else np.nan

    # TLE 覆蓋
    gaps = [(tle.iloc[i]["date_tag"] - tle.iloc[i-1]["date_tag"]).total_seconds() / 3600
            for i in range(1, len(tle))]

    # per-pair 差分
    da_l, di_l, de_l, dr_l, th_l = [], [], [], [], []
    for i in range(1, len(tle)):
        p, c = tle.iloc[i-1], tle.iloc[i]
        dt_s = (c["date_tag"] - p["date_tag"]).total_seconds()
        if dt_s <= 0 or dt_s > 86400 * 7:
            continue
        da  = float(c["sma_km"]) - float(p["sma_km"])
        di  = float(c["inclination_deg"]) - float(p["inclination_deg"])
        de  = float(c["eccentricity"]) - float(p["eccentricity"])
        drr = _angle_diff(float(p["raan_deg"]), float(c["raan_deg"]))
        drr -= _j2_raan_rate(float(p["sma_km"]), float(p["eccentricity"]), float(p["inclination_deg"])) * dt_s
        da_l.append(da); di_l.append(di); de_l.append(de); dr_l.append(drr)
        th_l.append(_adaptive_thr_da(float(p["sma_km"])))

    if not da_l:
        return None

    da_a, di_a, de_a, dr_a, th_a = (np.array(x) for x in (da_l, di_l, de_l, dr_l, th_l))
    flagged = (np.abs(da_a) > th_a) | (np.abs(di_a) > _THR_DI) | \
              (np.abs(de_a) > _THR_DE) | (np.abs(dr_a) > _THR_DRAAN)

    net_da     = float(da_a.sum())
    total_drop = -net_da if net_da < 0 else 0.0
    neg_streak = cur = 0
    for v in da_a:
        cur = (cur + 1) if v < -0.3 else 0
        neg_streak = max(neg_streak, cur)

    bstar_boost = (not np.isnan(bstar_mean)) and bstar_mean > 0.0005 and a0 < _R_E + 450
    s_thr, d_thr, n_thr = (3, 3.0, -2.0) if bstar_boost else (5, 5.0, -3.0)
    mono = int(neg_streak >= s_thr and total_drop > d_thr and net_da < n_thr)

    n_tr, n_fl = len(da_a), int(flagged.sum())

    # 4 × 7d 窗口
    t0 = tle["date_tag"].min()
    n_win = 0
    for w in range(4):
        w0 = t0 + pd.Timedelta(days=w*7); w1 = w0 + pd.Timedelta(days=7)
        wd = tle[(tle["date_tag"] >= w0) & (tle["date_tag"] < w1)]
        if len(wd) < 3: continue
        for j in range(1, len(wd)):
            pp, cc = wd.iloc[j-1], wd.iloc[j]
            dt2 = (cc["date_tag"] - pp["date_tag"]).total_seconds()
            if dt2 > 0 and dt2 <= 86400*7 and \
               abs(float(cc["sma_km"]) - float(pp["sma_km"])) > _adaptive_thr_da(float(pp["sma_km"])):
                n_win += 1; break

    dv_net = abs(0.5 * np.sqrt(_MU / a0) / a0 * net_da) * 1000.0

    return pd.DataFrame([{
        "alt_km":            round(a0 - _R_E, 2),
        "inc_deg":           round(i0, 4),
        "ecc":               round(e0, 6),
        "inc_family_enc":    _inc_family(i0),
        "bstar_mean":        round(bstar_mean, 7) if not np.isnan(bstar_mean) else np.nan,
        "bstar_std":         round(bstar_std, 8)  if not np.isnan(bstar_std)  else np.nan,
        "net_da_km":         round(net_da, 3),
        "max_da_km":         round(float(np.max(np.abs(da_a))), 3),
        "da_std":            round(float(np.std(da_a)), 4),
        "da_abs_mean":       round(float(np.mean(np.abs(da_a))), 4),
        "max_di_deg":        round(float(np.max(np.abs(di_a))), 5),
        "max_draan_res_deg": round(float(np.max(np.abs(dr_a))), 4),
        "neg_streak":        neg_streak,
        "total_drop_km":     round(total_drop, 3),
        "monotone_decay":    mono,
        "n_transitions":     n_tr,
        "n_flagged":         n_fl,
        "flag_rate":         round(n_fl / n_tr, 4) if n_tr else 0.0,
        "burn_freq_per_day": round(n_fl / _OBS_DAYS, 4),
        "n_windows_flagged": n_win,
        "n_tle":             len(tle),
        "mean_tle_gap_h":    round(float(np.mean(gaps)), 2) if gaps else np.nan,
        "max_tle_gap_h":     round(float(np.max(gaps)), 2)  if gaps else np.nan,
        "dv_net_ms":         round(dv_net, 3),
        # metadata
        "_window_start":     start_dt.isoformat(),
        "_window_end":       end_dt.isoformat(),
        "_n_tle_raw":        len(tle),
    }])


def _print_plan_b_result(
    feat_row: pd.DataFrame,
    feature_cols: list[str],
    proba: float,
    threshold: float,
    norad_id: int,
) -> None:
    """Plan B 推論結果：單一 26 天窗口的摘要輸出。"""
    r = feat_row.iloc[0]
    alert = proba >= threshold
    sep = "=" * 66

    print()
    print(sep)
    print(f"  Plan B 機動推論  —  NORAD {norad_id}")
    print(f"  觀測窗口  : {r.get('_window_start','')[:10]} ～ {r.get('_window_end','')[:10]}  ({_OBS_DAYS:.0f} 天)")
    print(sep)

    # 特徵摘要
    display = [
        ("alt_km",           "軌道高度 (km)"),
        ("inc_deg",          "傾角 (°)"),
        ("ecc",              "離心率"),
        ("net_da_km",        "26d 累積 Δa (km)"),
        ("max_da_km",        "最大單次 |Δa| (km)"),
        ("n_flagged",        "旗標轉移次數"),
        ("flag_rate",        "旗標率"),
        ("neg_streak",       "最長連續下降序列"),
        ("monotone_decay",   "單調衰減旗標"),
        ("n_windows_flagged","7d 子窗口旗標數 (/ 4)"),
        ("bstar_mean",       "B* 均值"),
    ]
    print()
    for col, label in display:
        val = r.get(col, np.nan)
        if isinstance(val, float) and np.isnan(val):
            print(f"  {label:<28}  N/A")
        else:
            print(f"  {label:<28}  {val}")

    print()
    print("  " + "-" * 62)
    alert_str = "  *** 偵測到機動 ***" if alert else ""
    print(f"  p_maneuver   = {proba:.6f}  (threshold = {threshold:.4f}){alert_str}")
    print(sep)
    print()


def _print_alert_table(
    df: pd.DataFrame,
    proba: np.ndarray,
    threshold: float = _ALERT_THRESHOLD,
) -> None:
    """Print the epoch-level alert table to stdout.

    Columns shown: epoch_utc | sma_km | d_sma_km | tle_gap_hours | p_maneuver | alert

    Parameters
    ----------
    df:
        Feature DataFrame aligned with ``proba``.
    proba:
        Predicted probabilities for class 1 (maneuvering).
    threshold:
        Probability threshold above which an alert is raised.
    """
    col_epoch    = "epoch_utc"
    col_sma      = "sma_km"
    col_d_sma    = "d_sma_km"
    col_gap      = "tle_gap_hours"

    header = (
        f"{'epoch_utc':<24}  {'sma_km':>10}  {'d_sma_km':>10}  "
        f"{'tle_gap_h':>10}  {'p_maneuver':>12}  {'alert'}"
    )
    print()
    print("=" * len(header))
    print(header)
    print("-" * len(header))

    for i, (idx, row) in enumerate(df.iterrows()):
        p = float(proba[i])
        alert_str = "!! MANEUVER" if p > threshold else ""
        epoch_str = str(row.get(col_epoch, ""))[:23]
        sma_val   = f"{row.get(col_sma, float('nan')):.3f}"   if col_sma   in row.index else "       N/A"
        d_sma_val = f"{row.get(col_d_sma, float('nan')):.4f}" if col_d_sma in row.index else "       N/A"
        gap_val   = f"{row.get(col_gap, float('nan')):.2f}"   if col_gap   in row.index else "       N/A"
        print(
            f"{epoch_str:<24}  {sma_val:>10}  {d_sma_val:>10}  "
            f"{gap_val:>10}  {p:>12.6f}  {alert_str}"
        )

    print("=" * len(header))
    n_alerts = int((proba > threshold).sum())
    print(f"\n{len(df)} epochs scored  |  {n_alerts} alert(s) above threshold {threshold}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    """Load model, score TLE-derived features, print alerts, save CSV."""
    args = _parse_args(argv)

    # --plan-b 自動選擇對應模型路徑（若使用者未明確指定 --model）
    if args.plan_b and args.model == _DEFAULT_MODEL_PKL:
        args.model = _DEFAULT_MODEL_PLAN_B

    model_path = Path(args.model)
    model, feature_cols = _load_model_and_features(model_path)

    threshold = _resolve_threshold(args, model_path)
    logger.info("Decision threshold: %.4f", threshold)

    # ── Plan B 模式：26 天窗口聚合特徵推論 ───────────────────────────────────
    if args.plan_b:
        feat_row = _build_plan_b_features(
            norad_id  = args.norad,
            db_path   = args.db,
            start_utc = args.start,
            end_utc   = args.end,
        )
        if feat_row is None:
            logger.error("Plan B 特徵提取失敗（TLE 不足或資料庫查詢錯誤）")
            sys.exit(1)

        present  = [c for c in feature_cols if c in feat_row.columns]
        X        = feat_row[present]
        proba    = float(model.predict_proba(X)[:, 1][0])

        _print_plan_b_result(feat_row, feature_cols, proba, threshold, args.norad)

        # 儲存 CSV
        today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        out_path  = Path(f"predictions_planb_{args.norad}_{today_str}.csv")
        out_df = feat_row.copy()
        out_df["p_maneuver"] = proba
        out_df["alert"]      = int(proba >= threshold)
        out_df.to_csv(out_path, index=False)
        print(f"Predictions saved → {out_path.resolve()}")
        return

    # ── 1. Build feature matrix ───────────────────────────────────────────────
    data_loader = _load_data_loader()

    kwargs: dict = {"norad_id": args.norad, "db_path": args.db}
    if args.start:
        kwargs["start_utc"] = args.start
    if args.end:
        kwargs["end_utc"] = args.end

    logger.info("Building feature matrix for NORAD %d …", args.norad)
    try:
        feat_df = data_loader.build_feature_matrix(**kwargs)
    except Exception as exc:
        logger.error("Feature build failed for NORAD %d: %s", args.norad, exc)
        sys.exit(1)

    if len(feat_df) == 0:
        logger.error("No feature rows returned for NORAD %d — nothing to score.", args.norad)
        sys.exit(1)

    # Drop rows with NaN in any feature column
    present_features = [c for c in feature_cols if c in feat_df.columns]
    missing_features = [c for c in feature_cols if c not in feat_df.columns]
    if missing_features:
        logger.warning(
            "Feature columns absent in data (will be excluded from scoring): %s",
            missing_features,
        )

    score_df = feat_df.dropna(subset=present_features).copy()
    logger.info("Scoring %d rows (dropped %d NaN rows)", len(score_df), len(feat_df) - len(score_df))

    if len(score_df) == 0:
        logger.error("All rows have NaN features — cannot score.")
        sys.exit(1)

    # ── 2. Score ──────────────────────────────────────────────────────────────
    X = score_df[present_features]
    proba: np.ndarray = model.predict_proba(X)[:, 1]
    logger.info(
        "Scoring done: min=%.4f  max=%.4f  mean=%.4f  alerts=%d",
        float(proba.min()),
        float(proba.max()),
        float(proba.mean()),
        int((proba > threshold).sum()),
    )

    # ── 3. Print alert table ──────────────────────────────────────────────────
    _print_alert_table(score_df, proba, threshold=threshold)

    # ── 4. Save CSV ───────────────────────────────────────────────────────────
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    out_csv_name = f"predictions_{args.norad}_{today_str}.csv"
    out_csv_path = Path(out_csv_name)

    output_df = score_df.copy()
    output_df["p_maneuver"] = proba
    output_df["alert"] = (proba > threshold).astype(int)

    output_df.to_csv(out_csv_path, index=False)
    print(f"Predictions saved → {out_csv_path.resolve()}")
    logger.info("CSV saved → %s  (%d rows)", out_csv_path, len(output_df))


if __name__ == "__main__":
    main()
