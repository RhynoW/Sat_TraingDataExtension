#!/usr/bin/env python3
"""
Build ML training dataset: MEME ground-truth labels × TLE orbital features.

Plan A — Binary classification
  Ground Truth : data/maneuvers/transitions_2026-05-02.csv
                 label = 1  if da_severity in {small, medium, large}
                 label = 0  if da_severity == none
  Features     : TLE orbital element time-series, [-7d, 0] window around t_from
  Outputs      : data/maneuvers/training_samples_meme_gt.csv
                 training_samples table in space_db.duckdb

Feature groups
--------------
  current-state  alt_km, inc_deg, ecc, inc_family_enc
  delta-Nd       da / di / de / draan_res at 1-day, 3-day, 7-day look-back
  rate-Nd        per-hour rate of the above
  rolling-7d     std / max|da| / mean|da| of all TLE deltas in window
  dv-estimate    dv_intrack_ms, dv_crosstrack_ms from 1-day changes
  solar          f107 index at t_from
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

# ── paths ─────────────────────────────────────────────────────────────────────
BASE       = Path(__file__).parent
DB_PATH    = BASE / "space_db.duckdb"
TRANS_CSV  = BASE / "data/maneuvers/transitions_2026-05-02.csv"
REG_CSV    = BASE / "data/url_registry.csv"
F107_CSV   = BASE / "f107_cache.csv"
OUT_CSV    = BASE / "data/maneuvers/training_samples_meme_gt.csv"
MODEL_VER  = "v1.0-meme-gt-plan-a"

# ── Plan B paths ──────────────────────────────────────────────────────────────
VAL_CSV    = BASE / "leo_annotator/output/validation_full.csv"
ANN_CSV    = BASE / "leo_annotator/output/annotations_leo_full.csv"
BEH_CSV    = BASE / "leo_annotator/output/maneuver_behavior_classified.csv"
OUT_CSV_B  = BASE / "data/maneuvers/training_samples_plan_b.csv"
OUT_PQ     = BASE / "data/maneuvers/training_dataset_final.parquet"
MODEL_VER_B = "v1.0-tle-annotation-plan-b"

DATE_START_B = "2026-05-01"
DATE_END_B   = "2026-05-27"
OBS_DAYS_B   = 26.0

# 偵測閾值（與 validate_annotations.py 一致）
THR_DI    = 0.02
THR_DE    = 0.001
THR_DRAAN = 0.1

# ── physical constants ────────────────────────────────────────────────────────
MU  = 398_600.4418   # km³/s²
R_E = 6_378.137      # km
J2  = 1.082_63e-3

WINDOW_DAYS   = 7    # look-back window for TLE features
LOOKBACKS     = [1, 3, 7]   # day offsets for delta features
MAX_GAP_FRAC  = 0.6  # max allowed gap as fraction of lookback before skip

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("build_dataset")


# ── orbital helpers (same constants as detect_maneuvers.py) ──────────────────

def j2_raan_rate_deg_per_s(a: float, e: float, i_deg: float) -> float:
    """Secular J2 RAAN precession rate in deg/s."""
    i = np.radians(i_deg)
    n = np.sqrt(MU / a**3)
    p = a * (1 - e**2)
    return np.degrees(-1.5 * n * J2 * (R_E / p)**2 * np.cos(i))


def angle_diff(a1: float, a2: float) -> float:
    """Signed difference (a2 - a1) wrapped to (-180, +180]."""
    d = (a2 - a1) % 360.0
    return d - 360.0 if d > 180.0 else d


def dv_from_da(a: float, da: float) -> float:
    """Hohmann ΔV (m/s) from semi-major axis change da (km)."""
    return abs(0.5 * np.sqrt(MU / a) / a * da) * 1000.0


def inc_family_encode(i_deg: float) -> int:
    if i_deg < 45:  return 0   # 43-deg shell
    if i_deg < 55:  return 1   # 53-deg shell
    if i_deg < 85:  return 2   # 70-deg shell
    return 3                   # SSO ~97-deg


# ── feature extraction ────────────────────────────────────────────────────────

def closest_row(sat_tle: pd.DataFrame, target_t: pd.Timestamp,
                max_gap_s: float) -> pd.Series | None:
    """Return TLE row closest to target_t within max_gap_s seconds."""
    if sat_tle.empty:
        return None
    deltas = (sat_tle["date_tag"] - target_t).abs()
    idx    = deltas.idxmin()
    if deltas[idx].total_seconds() > max_gap_s:
        return None
    return sat_tle.loc[idx]


def j2_integrated_raan(sat_window: pd.DataFrame) -> float:
    """
    Compute cumulative J2 RAAN drift (deg) over sorted TLE window.
    Uses trapezoidal integration of per-epoch J2 rate × Δt.
    """
    if len(sat_window) < 2:
        return 0.0
    total = 0.0
    rows = sat_window.sort_values("date_tag").reset_index(drop=True)
    for k in range(len(rows) - 1):
        r1, r2 = rows.iloc[k], rows.iloc[k + 1]
        a_mid = 0.5 * (r1["sma_km"] + r2["sma_km"])
        e_mid = 0.5 * (r1["eccentricity"] + r2["eccentricity"])
        i_mid = 0.5 * (r1["inclination_deg"] + r2["inclination_deg"])
        dt_s  = (r2["date_tag"] - r1["date_tag"]).total_seconds()
        rate  = j2_raan_rate_deg_per_s(a_mid, e_mid, i_mid)
        total += rate * dt_s
    return total


def compute_features(sat_tle: pd.DataFrame, t_from: pd.Timestamp,
                     f107_val: float) -> dict | None:
    """
    Extract feature vector from TLE window for one MEME transition.

    Parameters
    ----------
    sat_tle  : all TLE rows for the satellite in [t_from - 7d, t_from + 1d]
    t_from   : start epoch of the MEME transition
    f107_val : F10.7 solar flux index on t_from date (NaN if unavailable)
    """
    if sat_tle.empty:
        return None

    sat_tle = sat_tle.sort_values("date_tag").reset_index(drop=True)

    # ── current state (closest TLE to t_from) ─────────────────────────────
    cur = closest_row(sat_tle, t_from, max_gap_s=WINDOW_DAYS * 86400 * 0.5)
    if cur is None:
        return None

    a0   = cur["sma_km"]
    i0   = cur["inclination_deg"]
    e0   = cur["eccentricity"]
    r0   = cur["raan_deg"]
    alt0 = a0 - R_E

    feats: dict = {
        "alt_km":           round(alt0, 2),
        "inc_deg":          round(i0, 4),
        "ecc":              round(e0, 6),
        "inc_family_enc":   inc_family_encode(i0),
        "f107":             round(f107_val, 1) if not np.isnan(f107_val) else np.nan,
    }

    # ── delta features at each look-back ──────────────────────────────────
    window_7d = sat_tle[sat_tle["date_tag"] <= t_from].copy()

    da_series: list[float] = []
    prev_t = prev_sma = None
    for _, row in window_7d.iterrows():
        if prev_sma is not None:
            da_series.append(row["sma_km"] - prev_sma)
        prev_t, prev_sma = row["date_tag"], row["sma_km"]

    for lb in LOOKBACKS:
        target_t  = t_from - pd.Timedelta(days=lb)
        max_gap_s = lb * 86400 * MAX_GAP_FRAC
        past      = closest_row(window_7d, target_t, max_gap_s)

        if past is None:
            for key in (f"da_{lb}d_km", f"di_{lb}d_deg", f"de_{lb}d",
                        f"draan_res_{lb}d_deg",
                        f"da_rate_{lb}d_km_h", f"di_rate_{lb}d_deg_h",
                        f"draan_res_rate_{lb}d_deg_h"):
                feats[key] = np.nan
            continue

        dt_s  = (t_from - past["date_tag"]).total_seconds()
        dt_h  = dt_s / 3600.0

        # SMA change
        da = a0 - past["sma_km"]

        # Inclination change
        di = i0 - past["inclination_deg"]

        # Eccentricity change
        de = e0 - past["eccentricity"]

        # J2-corrected RAAN residual over [past → t_from] window
        sub_window = window_7d[window_7d["date_tag"] >= past["date_tag"]]
        j2_raan    = j2_integrated_raan(sub_window)
        draan_raw  = angle_diff(past["raan_deg"], r0)
        draan_res  = draan_raw - j2_raan

        feats[f"da_{lb}d_km"]            = round(da, 4)
        feats[f"di_{lb}d_deg"]           = round(di, 5)
        feats[f"de_{lb}d"]               = round(de, 6)
        feats[f"draan_res_{lb}d_deg"]    = round(draan_res, 4)
        feats[f"da_rate_{lb}d_km_h"]     = round(da / dt_h, 5) if dt_h > 0 else np.nan
        feats[f"di_rate_{lb}d_deg_h"]    = round(di / dt_h, 6) if dt_h > 0 else np.nan
        feats[f"draan_res_rate_{lb}d_deg_h"] = round(draan_res / dt_h, 6) if dt_h > 0 else np.nan

    # ── rolling 7-day statistics ───────────────────────────────────────────
    if da_series:
        da_arr = np.array(da_series)
        feats["da_std_7d"]      = round(float(np.std(da_arr)), 4)
        feats["da_abs_max_7d"]  = round(float(np.max(np.abs(da_arr))), 4)
        feats["da_abs_mean_7d"] = round(float(np.mean(np.abs(da_arr))), 4)
    else:
        feats["da_std_7d"]      = np.nan
        feats["da_abs_max_7d"]  = np.nan
        feats["da_abs_mean_7d"] = np.nan

    feats["n_tle_7d"] = len(window_7d)

    # ── ΔV estimates from 1-day look-back ────────────────────────────────
    da_1d = feats.get("da_1d_km", np.nan)
    di_1d = feats.get("di_1d_deg", np.nan)
    draan_res_1d = feats.get("draan_res_1d_deg", np.nan)

    if not np.isnan(da_1d):
        feats["dv_intrack_1d_ms"] = round(dv_from_da(a0, da_1d), 3)
    else:
        feats["dv_intrack_1d_ms"] = np.nan

    if not (np.isnan(di_1d) or np.isnan(draan_res_1d)):
        v_c = np.sqrt(MU / a0)
        di_r  = np.radians(abs(di_1d))
        dO_r  = np.radians(abs(draan_res_1d))
        i_r   = np.radians(i0)
        feats["dv_crosstrack_1d_ms"] = round(v_c * np.sqrt(di_r**2 + (np.sin(i_r) * dO_r)**2) * 1000.0, 3)
    else:
        feats["dv_crosstrack_1d_ms"] = np.nan

    return feats


# ── Plan B helpers ───────────────────────────────────────────────────────────

def adaptive_thr_da(sma_km: float) -> float:
    """P2：高度自適應 Δa 閾值（< 400 km → 2.0；> 600 km → 0.5；其餘 1.0）"""
    alt = sma_km - R_E
    if alt < 400:
        return 2.0
    elif alt > 600:
        return 0.5
    return 1.0


def extract_features_plan_b(sat_tle: pd.DataFrame) -> dict | None:
    """
    26 天觀測窗口的 per-satellite 特徵向量。

    特徵群組：
      orbit_state   — 觀測期起始軌道元素
      bstar         — B* 統計（阻力係數）
      da_aggregate  — 26 天 Δa 聚合統計
      monotone      — 單調衰減指標（P1）
      flagging      — 旗標率與次數
      multiwindow   — 4 × 7 天子窗口旗標數
      tle_coverage  — TLE 密度與缺口
    """
    if len(sat_tle) < 3:
        return None

    sat_tle = sat_tle.sort_values("date_tag").reset_index(drop=True)
    first   = sat_tle.iloc[0]
    a0      = float(first["sma_km"])
    i0      = float(first["inclination_deg"])
    e0      = float(first["eccentricity"])

    # ── bstar ──────────────────────────────────────────────────────────────
    if "bstar" in sat_tle.columns and sat_tle["bstar"].notna().any():
        bv         = sat_tle["bstar"].dropna()
        bstar_mean = float(bv.mean())
        bstar_std  = float(bv.std()) if len(bv) > 1 else 0.0
    else:
        bstar_mean = bstar_std = np.nan

    # ── TLE coverage ───────────────────────────────────────────────────────
    gaps_h = [(sat_tle.iloc[i]["date_tag"] - sat_tle.iloc[i-1]["date_tag"]).total_seconds() / 3600
              for i in range(1, len(sat_tle))]
    mean_gap_h = float(np.mean(gaps_h)) if gaps_h else np.nan
    max_gap_h  = float(np.max(gaps_h))  if gaps_h else np.nan

    # ── per-pair deltas ────────────────────────────────────────────────────
    da_list = di_list = de_list = draan_list = thr_list = []
    da_list, di_list, de_list, draan_list, thr_list = [], [], [], [], []

    for i in range(1, len(sat_tle)):
        prev = sat_tle.iloc[i - 1]
        curr = sat_tle.iloc[i]
        dt_s = (curr["date_tag"] - prev["date_tag"]).total_seconds()
        if dt_s <= 0 or dt_s > 86400 * 7:
            continue
        da        = float(curr["sma_km"]) - float(prev["sma_km"])
        di        = float(curr["inclination_deg"]) - float(prev["inclination_deg"])
        de        = float(curr["eccentricity"])     - float(prev["eccentricity"])
        draan_raw = angle_diff(float(prev["raan_deg"]), float(curr["raan_deg"]))
        raan_j2   = j2_raan_rate_deg_per_s(
            float(prev["sma_km"]), float(prev["eccentricity"]), float(prev["inclination_deg"])
        ) * dt_s
        draan_res = draan_raw - raan_j2
        thr_da    = adaptive_thr_da(float(prev["sma_km"]))
        da_list.append(da);    di_list.append(di)
        de_list.append(de);    draan_list.append(draan_res)
        thr_list.append(thr_da)

    if not da_list:
        return None

    da_arr    = np.array(da_list)
    di_arr    = np.array(di_list)
    de_arr    = np.array(de_list)
    draan_arr = np.array(draan_list)
    thr_arr   = np.array(thr_list)

    # ── flagging ───────────────────────────────────────────────────────────
    flagged   = (
        (np.abs(da_arr) > thr_arr)    |
        (np.abs(di_arr) > THR_DI)     |
        (np.abs(de_arr) > THR_DE)     |
        (np.abs(draan_arr) > THR_DRAAN)
    )
    n_trans   = len(da_arr)
    n_flagged = int(flagged.sum())
    flag_rate = n_flagged / n_trans if n_trans > 0 else 0.0

    # ── monotone decay ─────────────────────────────────────────────────────
    net_da     = float(da_arr.sum())
    total_drop = -net_da if net_da < 0 else 0.0
    neg_streak = cur = 0
    for v in da_arr:
        if v < -0.3:
            cur += 1
            neg_streak = max(neg_streak, cur)
        else:
            cur = 0

    bstar_boost   = (not np.isnan(bstar_mean)) and bstar_mean > 0.0005 and a0 < R_E + 450
    s_thr = 3 if bstar_boost else 5
    d_thr = 3.0 if bstar_boost else 5.0
    n_thr = -2.0 if bstar_boost else -3.0
    monotone_decay = int(neg_streak >= s_thr and total_drop > d_thr and net_da < n_thr)

    # ── multi-window (4 × 7d) ─────────────────────────────────────────────
    t_start = sat_tle["date_tag"].min()
    n_win_flagged = 0
    for w in range(4):
        w0     = t_start + pd.Timedelta(days=w * 7)
        w1     = w0 + pd.Timedelta(days=7)
        w_data = sat_tle[(sat_tle["date_tag"] >= w0) & (sat_tle["date_tag"] < w1)]
        if len(w_data) < 3:
            continue
        for j in range(1, len(w_data)):
            p2 = w_data.iloc[j - 1]; c2 = w_data.iloc[j]
            dt2 = (c2["date_tag"] - p2["date_tag"]).total_seconds()
            if dt2 <= 0 or dt2 > 86400 * 7:
                continue
            if abs(float(c2["sma_km"]) - float(p2["sma_km"])) > adaptive_thr_da(float(p2["sma_km"])):
                n_win_flagged += 1
                break

    return {
        # orbit state
        "alt_km":            round(a0 - R_E, 2),
        "inc_deg":           round(i0, 4),
        "ecc":               round(e0, 6),
        "inc_family_enc":    inc_family_encode(i0),
        # bstar
        "bstar_mean":        round(bstar_mean, 7) if not np.isnan(bstar_mean) else np.nan,
        "bstar_std":         round(bstar_std, 8)  if not np.isnan(bstar_std)  else np.nan,
        # 26-day da aggregate
        "net_da_km":         round(net_da, 3),
        "max_da_km":         round(float(np.max(np.abs(da_arr))), 3),
        "da_std":            round(float(np.std(da_arr)), 4),
        "da_abs_mean":       round(float(np.mean(np.abs(da_arr))), 4),
        "max_di_deg":        round(float(np.max(np.abs(di_arr))), 5),
        "max_draan_res_deg": round(float(np.max(np.abs(draan_arr))), 4),
        # monotone decay (P1)
        "neg_streak":        neg_streak,
        "total_drop_km":     round(total_drop, 3),
        "monotone_decay":    monotone_decay,
        # flagging
        "n_transitions":     n_trans,
        "n_flagged":         n_flagged,
        "flag_rate":         round(flag_rate, 4),
        "burn_freq_per_day": round(n_flagged / OBS_DAYS_B, 4),
        # multi-window
        "n_windows_flagged": n_win_flagged,
        # TLE coverage
        "n_tle":             len(sat_tle),
        "mean_tle_gap_h":    round(mean_gap_h, 2) if not np.isnan(mean_gap_h) else np.nan,
        "max_tle_gap_h":     round(max_gap_h,  2) if not np.isnan(max_gap_h)  else np.nan,
        # ΔV estimate from net da
        "dv_net_ms":         round(dv_from_da(a0, net_da), 3),
    }


def run_plan_b() -> pd.DataFrame:
    """
    Plan B：TLE 標註驅動的訓練資料集。
    來源：validation_full.csv（Precision 97.8% 標籤）
          annotations_leo_full.csv（推進類別）
          maneuver_behavior_classified.csv（10 種行為標籤）
    輸出：data/maneuvers/training_samples_plan_b.csv
    """
    log.info("=== Plan B: TLE-annotation dataset ===")

    # ── labels ────────────────────────────────────────────────────────────
    val = pd.read_csv(VAL_CSV)
    val["norad_id"] = val["norad_id"].astype(str).str.strip()

    ann = pd.read_csv(ANN_CSV, dtype=str, encoding="utf-8-sig")
    ann["norad_id"] = ann["norad_id"].astype(str).str.strip()

    beh = pd.read_csv(BEH_CSV, dtype=str)
    beh["norad_id"] = beh["norad_id"].astype(str).str.strip()

    merged = (
        val
        .merge(ann[["norad_id", "propulsion_class", "mass_kg"]], on="norad_id", how="left",
               suffixes=("", "_ann"))
        .merge(beh[["norad_id", "behavior", "monotone_decay"]], on="norad_id", how="left")
    )
    merged = merged[merged["tle_status"] == "ok"].reset_index(drop=True)
    log.info("  有效衛星: %d 顆（tle_status=ok）", len(merged))

    # ── bulk TLE load ──────────────────────────────────────────────────────
    norad_ints = ", ".join(str(int(n)) for n in merged["norad_id"])
    conn = duckdb.connect(str(DB_PATH), read_only=True)

    # bstar 欄位可能不存在於舊版 DB，動態偵測
    try:
        tbl_cols  = conn.execute("DESCRIBE tle_table").df()["column_name"].str.lower().tolist()
        bstar_sel = ", bstar" if "bstar" in tbl_cols else ", NULL::DOUBLE AS bstar"
    except Exception:
        bstar_sel = ", NULL::DOUBLE AS bstar"
    log.info("  bstar: %s", "available" if "bstar" in bstar_sel[:8] else "unavailable (NULL)")

    tle_all = conn.execute(f"""
        SELECT norad_id, date_tag, sma_km, eccentricity, inclination_deg,
               raan_deg{bstar_sel}
        FROM tle_table
        WHERE norad_id IN ({norad_ints})
          AND date_tag BETWEEN TIMESTAMP '{DATE_START_B}'
                           AND TIMESTAMP '{DATE_END_B} 23:59:59'
        ORDER BY norad_id, date_tag
    """).df()
    conn.close()
    tle_all["date_tag"] = pd.to_datetime(tle_all["date_tag"])
    tle_grouped = {str(nid): grp.reset_index(drop=True)
                   for nid, grp in tle_all.groupby("norad_id")}
    log.info("  TLE 總筆數: %d  衛星數: %d", len(tle_all), len(tle_grouped))

    # ── feature extraction loop ────────────────────────────────────────────
    records, skipped = [], 0
    for _, row in merged.iterrows():
        norad   = str(row["norad_id"])
        sat_tle = tle_grouped.get(norad, pd.DataFrame())
        feats   = extract_features_plan_b(sat_tle)
        if feats is None:
            skipped += 1
            continue

        lbl_bin = int(str(row.get("maneuver_detected",     "False")).lower() == "true")
        lbl_mw  = int(str(row.get("multi_window_detected", "False")).lower() == "true")
        prop    = str(row.get("propulsion_class", "")) if pd.notna(row.get("propulsion_class")) else ""
        beh_lbl = str(row.get("behavior", ""))         if pd.notna(row.get("behavior"))         else ""

        records.append({
            "norad_id":         norad,
            "sat_name":         str(row.get("sat_name", "")),
            "propulsion_class": prop,
            "mass_kg":          row.get("mass_kg", np.nan),
            "label_binary":     lbl_bin,
            "label_mw":         lbl_mw,
            "behavior":         beh_lbl,
            "label_source":     "tle_annotation_v1",
            "model_version":    MODEL_VER_B,
            **feats,
        })

    df_b = pd.DataFrame(records)
    log.info("  提取完成: %d 樣本  略過（TLE 不足）: %d", len(df_b), skipped)

    # ── CSV ────────────────────────────────────────────────────────────────
    OUT_CSV_B.parent.mkdir(parents=True, exist_ok=True)
    df_b.to_csv(OUT_CSV_B, index=False)
    log.info("Plan B CSV → %s  (%d rows × %d cols)", OUT_CSV_B, len(df_b), df_b.shape[1])

    # ── DuckDB ────────────────────────────────────────────────────────────
    conn = duckdb.connect(str(DB_PATH))
    conn.execute("CREATE TABLE IF NOT EXISTS training_samples_plan_b AS SELECT * FROM df_b WHERE 1=0")
    conn.execute("DELETE FROM training_samples_plan_b WHERE model_version = ?", [MODEL_VER_B])
    conn.register("df_b", df_b)
    conn.execute("INSERT INTO training_samples_plan_b SELECT * FROM df_b")
    conn.unregister("df_b")
    conn.close()
    log.info("Plan B → DuckDB training_samples_plan_b  (%d 筆)", len(df_b))

    return df_b


def _print_plan_b_summary(df: pd.DataFrame) -> None:
    feat_cols = [c for c in df.columns
                 if c not in ("norad_id", "sat_name", "propulsion_class", "mass_kg",
                               "label_binary", "label_mw", "behavior",
                               "label_source", "model_version")]
    print()
    print("=" * 60)
    print(f"  Training Dataset Summary — Plan B  ({MODEL_VER_B})")
    print("=" * 60)
    print(f"  Total samples      : {len(df)}")
    print(f"  Features per sample: {len(feat_cols)}")
    print()
    print("  label_binary distribution:")
    for v, cnt in df["label_binary"].value_counts().sort_index().items():
        print(f"    {v}: {cnt:>6}  ({cnt/len(df)*100:.1f}%)")
    print()
    print("  label_mw (incl. multi-window) distribution:")
    for v, cnt in df["label_mw"].value_counts().sort_index().items():
        print(f"    {v}: {cnt:>6}  ({cnt/len(df)*100:.1f}%)")
    print()
    print("  propulsion_class distribution (top 6):")
    for v, cnt in df["propulsion_class"].value_counts().head(6).items():
        print(f"    {str(v):<18}: {cnt:>6}")
    print()
    print("  behavior distribution (labeled satellites):")
    beh_cnt = df[df["behavior"] != ""]["behavior"].value_counts()
    for v, cnt in beh_cnt.head(10).items():
        print(f"    {str(v):<22}: {cnt:>5}")
    print()
    nan_rate = df[feat_cols].isna().mean()
    high_nan = nan_rate[nan_rate > 0.05]
    if not high_nan.empty:
        print("  Features with >5% NaN:")
        for f, r in high_nan.items():
            print(f"    {f}: {r*100:.1f}%")
    else:
        print("  No features with >5% NaN")
    print()
    print(f"  Output CSV  : {OUT_CSV_B}")
    print("=" * 60)


def merge_and_save_final(df_b: pd.DataFrame) -> None:
    """
    將 Plan A（MEME GT）與 Plan B（TLE 標註）合併，輸出 Parquet。
    共同欄位：norad_id, label_binary, label_source, model_version,
              alt_km, inc_deg, ecc, inc_family_enc
    Plan A 特有欄位填 NaN；Plan B 特有欄位填 NaN。
    """
    # Plan A from CSV
    if OUT_CSV.exists():
        df_a = pd.read_csv(OUT_CSV)
        df_a["plan"] = "A"
    else:
        log.warning("Plan A CSV 不存在，跳過合併")
        df_b["plan"] = "B"
        df_b.to_parquet(OUT_PQ, index=False)
        log.info("Final Parquet (B only) → %s  (%d rows)", OUT_PQ, len(df_b))
        return

    df_b_copy = df_b.copy()
    df_b_copy["plan"] = "B"

    # norad_id 統一為 Int64（nullable integer）避免 str/int 混型
    for df in (df_a, df_b_copy):
        df["norad_id"] = pd.to_numeric(df["norad_id"], errors="coerce").astype("Int64")

    combined = pd.concat([df_a, df_b_copy], ignore_index=True, sort=False)
    combined.to_parquet(OUT_PQ, index=False)

    log.info("Final Parquet → %s", OUT_PQ)
    log.info("  Plan A: %d rows  Plan B: %d rows  Total: %d rows",
             len(df_a), len(df_b_copy), len(combined))
    log.info("  欄位數: %d  (A+B union)", combined.shape[1])

    # 標籤分布
    log.info("  label_binary distribution:\n%s",
             combined.groupby(["plan", "label_binary"]).size().to_string())


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Build ML training dataset")
    parser.add_argument("--plan", choices=["a", "b", "all"], default="b",
                        help="a=MEME-GT only  b=TLE-annotation only  all=both+merge (default: b)")
    args = parser.parse_args()

    df_b: pd.DataFrame | None = None
    if args.plan in ("b", "all"):
        df_b = run_plan_b()
        _print_plan_b_summary(df_b)
        if args.plan == "b":
            return

    log.info("=== Plan A: MEME ground-truth ===")
    log.info("Loading MEME ground-truth transitions …")
    trans = pd.read_csv(TRANS_CSV)
    trans["t_from"] = pd.to_datetime(trans["t_from"], utc=True)
    trans["t_to"]   = pd.to_datetime(trans["t_to"],   utc=True)

    reg = pd.read_csv(REG_CSV)[["norad_id", "sat_name"]].drop_duplicates("sat_name")
    trans = trans.merge(reg, on="sat_name", how="left")

    n_missing = trans["norad_id"].isna().sum()
    if n_missing:
        log.warning("  %d transitions have no NORAD ID — will be skipped", n_missing)

    trans = trans.dropna(subset=["norad_id"])
    trans["norad_id"] = trans["norad_id"].astype(int)

    # Binary label
    trans["label_binary"]   = (trans["da_severity"] != "none").astype(int)
    trans["label_severity"] = trans["da_severity"]

    log.info("  %d transitions for %d satellites", len(trans), trans["sat_name"].nunique())
    log.info("  label_binary: 1=%d  0=%d",
             trans["label_binary"].sum(), (trans["label_binary"] == 0).sum())

    # ── bulk TLE load ──────────────────────────────────────────────────────
    log.info("Loading TLE data from DuckDB …")
    norad_list = trans["norad_id"].unique().tolist()
    n_str      = ",".join(str(n) for n in norad_list)

    t_min = (trans["t_from"].min() - pd.Timedelta(days=WINDOW_DAYS + 1)).strftime("%Y-%m-%d %H:%M:%S")
    t_max = (trans["t_from"].max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    tle_all = conn.execute(f"""
        SELECT norad_id, date_tag, sma_km, eccentricity, inclination_deg,
               raan_deg, argp_deg, mean_anomaly_deg
        FROM tle_table
        WHERE norad_id IN ({n_str})
          AND date_tag BETWEEN TIMESTAMP '{t_min}' AND TIMESTAMP '{t_max}'
        ORDER BY norad_id, date_tag
    """).df()
    conn.close()

    tle_all["date_tag"] = pd.to_datetime(tle_all["date_tag"], utc=True)
    log.info("  Loaded %d TLE rows for %d satellites", len(tle_all), tle_all["norad_id"].nunique())

    # ── F10.7 ─────────────────────────────────────────────────────────────
    f107_map: dict[str, float] = {}
    if F107_CSV.exists():
        f107_df = pd.read_csv(F107_CSV)
        f107_df["epoch"] = pd.to_datetime(f107_df["epoch"]).dt.normalize()
        f107_map = dict(zip(f107_df["epoch"].dt.strftime("%Y-%m-%d"), f107_df["f107"]))
        log.info("  F10.7 loaded: %d entries", len(f107_map))
    else:
        log.warning("  f107_cache.csv not found — f107 feature will be NaN")

    # ── feature extraction loop ────────────────────────────────────────────
    log.info("Extracting features for %d transitions …", len(trans))
    records = []
    skipped = 0

    tle_grouped = {nid: grp.reset_index(drop=True)
                   for nid, grp in tle_all.groupby("norad_id")}

    for _, row in trans.iterrows():
        norad   = int(row["norad_id"])
        t_from  = row["t_from"]

        sat_tle = tle_grouped.get(norad, pd.DataFrame())
        # Restrict to [t_from - 7d, t_from + 1d]
        if not sat_tle.empty:
            mask    = (sat_tle["date_tag"] >= t_from - pd.Timedelta(days=WINDOW_DAYS)) & \
                      (sat_tle["date_tag"] <= t_from + pd.Timedelta(days=1))
            sat_win = sat_tle[mask]
        else:
            sat_win = sat_tle

        date_key = t_from.strftime("%Y-%m-%d")
        f107_val = float(f107_map.get(date_key, np.nan))

        feats = compute_features(sat_win, t_from, f107_val)
        if feats is None:
            skipped += 1
            continue

        records.append({
            "norad_id":           norad,
            "sat_name":           row["sat_name"],
            "center_epoch":       t_from.isoformat(),
            "window_start":       (t_from - pd.Timedelta(days=WINDOW_DAYS)).isoformat(),
            "window_end":         t_from.isoformat(),
            "label_binary":       int(row["label_binary"]),
            "label_severity":     row["label_severity"],
            "label_maneuver_class": row["maneuver_class"],
            "inc_family":         row["inc_family"],
            "da_km_meme":         round(row["da_km"], 4),
            "label_source":       "meme_ephemeris",
            "model_version":      MODEL_VER,
            **feats,
        })

    log.info("  Extracted: %d samples  Skipped (no TLE): %d", len(records), skipped)

    if not records:
        log.error("No samples extracted. Check TLE coverage.")
        return

    df_out = pd.DataFrame(records)

    # ── save CSV ───────────────────────────────────────────────────────────
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(OUT_CSV, index=False)
    log.info("CSV -> %s  (%d rows, %d features)", OUT_CSV, len(df_out), df_out.shape[1])

    # ── write to DuckDB training_samples table ────────────────────────────
    log.info("Writing to DuckDB training_samples …")
    feat_cols = [c for c in df_out.columns
                 if c not in ("norad_id", "sat_name", "center_epoch",
                               "window_start", "window_end",
                               "label_binary", "label_severity",
                               "label_maneuver_class", "inc_family",
                               "da_km_meme", "label_source", "model_version")]

    conn = duckdb.connect(str(DB_PATH))
    conn.execute("DELETE FROM training_samples WHERE model_version = ?", [MODEL_VER])

    insert_rows = []
    for _, r in df_out.iterrows():
        feat_dict = {c: (None if (isinstance(r[c], float) and np.isnan(r[c])) else r[c])
                     for c in feat_cols}
        insert_rows.append((
            int(r["norad_id"]),
            r["center_epoch"],
            r["window_start"],
            r["window_end"],
            json.dumps(feat_dict),
            f"binary:{r['label_binary']}|severity:{r['label_severity']}|class:{r['label_maneuver_class']}",
            r["label_source"],
            r["model_version"],
        ))

    conn.executemany("""
        INSERT INTO training_samples
            (norad_id, center_epoch, window_start, window_end,
             features_json, label, label_source, model_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, insert_rows)
    conn.close()
    log.info("DuckDB: %d rows inserted into training_samples", len(insert_rows))

    # ── summary ───────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print(f"  Training Dataset Summary — Plan A  ({MODEL_VER})")
    print("=" * 60)
    print(f"  Total samples      : {len(df_out)}")
    print(f"  Skipped (no TLE)   : {skipped}")
    print(f"  Features per sample: {len(feat_cols)}")
    print()
    print("  Label distribution (binary):")
    for v, cnt in df_out["label_binary"].value_counts().sort_index().items():
        print(f"    {v}: {cnt}  ({cnt/len(df_out)*100:.1f}%)")
    print()
    print("  Label distribution (da_severity):")
    for v, cnt in df_out["label_severity"].value_counts().items():
        print(f"    {v:8s}: {cnt}")
    print()
    nan_rate = df_out[feat_cols].isna().mean()
    high_nan = nan_rate[nan_rate > 0.05]
    if not high_nan.empty:
        print("  Features with >5% NaN:")
        for f, r in high_nan.items():
            print(f"    {f}: {r*100:.1f}%")
    else:
        print("  No features with >5% NaN")
    print()
    print(f"  Output CSV  : {OUT_CSV}")
    print("=" * 60)

    if args.plan == "all" and df_b is not None:
        merge_and_save_final(df_b)


if __name__ == "__main__":
    main()
