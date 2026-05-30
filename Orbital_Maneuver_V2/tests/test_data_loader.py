"""
test_data_loader.py
===================
Unit tests for data_loader.py.

所有測試使用合成 DataFrame，不連接真實 DuckDB。
"""
from __future__ import annotations

import sys
import os

# 確保能 import 上層模組
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from data_loader import (
    MU,
    R_EARTH_KM,
    _ROLL_COLS,
    _TWO_PI,
    build_feature_matrix,
    compute_delta_features,
    compute_rolling_features,
    extract_tle_elements,
)


# ─────────────────────────────────────────────────────────────────────────────
# 輔助函式
# ─────────────────────────────────────────────────────────────────────────────

def _make_tle_df(n: int = 3, mean_motion_revday: float = 15.5) -> pd.DataFrame:
    """建立最小合成 TLE DataFrame，mean_motion 單位為 rev/day。"""
    base_time = pd.Timestamp("2025-01-01", tz="UTC")
    times = [base_time + pd.Timedelta(hours=12 * i) for i in range(n)]
    return pd.DataFrame(
        {
            "norad_id":    [99999] * n,
            "epoch_utc":   times,
            "line1":       [""] * n,
            "line2":       [""] * n,
            "mean_motion": [mean_motion_revday] * n,
            "eccentricity": [0.001] * n,
            "inclination":  [53.0] * n,
            "raan":         [10.0 + i * 0.01 for i in range(n)],
            "arg_perigee":  [0.0] * n,
            "mean_anomaly": [0.0] * n,
            "bstar":        [1e-5] * n,
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# extract_tle_elements
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractTleElements:

    def test_sma_kepler_third_law(self):
        """sma_km 應由克卜勒第三定律 a = (μ/n²)^(1/3) 計算，誤差 < 0.001 km。"""
        mm_revday = 15.5
        df = _make_tle_df(n=1, mean_motion_revday=mm_revday)
        result = extract_tle_elements(df)

        n_rad_s = mm_revday * _TWO_PI / 86_400.0
        expected_sma = (MU / n_rad_s**2) ** (1.0 / 3.0)

        assert abs(result["sma_km"].iloc[0] - expected_sma) < 1e-3

    def test_altitude_equals_sma_minus_r_earth(self):
        """altitude_km 應等於 sma_km - R_EARTH_KM。"""
        df = _make_tle_df(n=1)
        result = extract_tle_elements(df)

        assert abs(result["altitude_km"].iloc[0] - (result["sma_km"].iloc[0] - R_EARTH_KM)) < 1e-9

    def test_period_min_formula(self):
        """period_min 應等於 1440 / mean_motion（rev/day → min/rev）。"""
        mm = 14.0
        df = _make_tle_df(n=1, mean_motion_revday=mm)
        result = extract_tle_elements(df)

        expected = 1440.0 / mm
        assert abs(result["period_min"].iloc[0] - expected) < 1e-9

    def test_output_columns_present(self):
        """輸出 DataFrame 必須包含所有必要欄位。"""
        df = _make_tle_df(n=2)
        result = extract_tle_elements(df)

        required = ["norad_id", "epoch_utc", "sma_km", "altitude_km",
                    "period_min", "eccentricity", "inclination", "raan", "bstar"]
        for col in required:
            assert col in result.columns, f"缺少欄位: {col}"

    def test_empty_input_returns_empty_df_with_correct_columns(self):
        """空 DataFrame 輸入應回傳空 DataFrame，且欄位正確。"""
        empty = pd.DataFrame(columns=["norad_id", "epoch_utc", "mean_motion",
                                       "eccentricity", "inclination", "raan",
                                       "arg_perigee", "mean_anomaly", "bstar",
                                       "line1", "line2"])
        result = extract_tle_elements(empty)

        assert result.empty
        assert "sma_km" in result.columns


# ─────────────────────────────────────────────────────────────────────────────
# compute_delta_features
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeDeltaFeatures:

    def _make_elem_df(self, n: int = 4, delta_sma: float = 1.0) -> pd.DataFrame:
        """建立已含 sma_km 的合成 elem DataFrame。"""
        base_time = pd.Timestamp("2025-01-01", tz="UTC")
        times = [base_time + pd.Timedelta(hours=12 * i) for i in range(n)]
        sma_values = [7000.0 + delta_sma * i for i in range(n)]
        return pd.DataFrame(
            {
                "norad_id":    [99999] * n,
                "epoch_utc":   times,
                "sma_km":      sma_values,
                "altitude_km": [sma - R_EARTH_KM for sma in sma_values],
                "period_min":  [100.0] * n,
                "eccentricity": [0.001] * n,
                "inclination":  [53.0] * n,
                "raan":         [10.0 + 0.01 * i for i in range(n)],
                "bstar":        [1e-5] * n,
                "mean_motion":  [15.5] * n,
            }
        )

    def test_d_sma_km_is_diff_of_sma(self):
        """d_sma_km 的第二行應等於 sma_km[1] - sma_km[0]。"""
        delta = 2.5
        df = self._make_elem_df(n=3, delta_sma=delta)
        result = compute_delta_features(df)

        assert abs(result["d_sma_km"].iloc[1] - delta) < 1e-9

    def test_first_row_d_sma_is_nan(self):
        """第一行 d_sma_km 應為 NaN（diff 無前一筆）。"""
        df = self._make_elem_df(n=3)
        result = compute_delta_features(df)

        assert pd.isna(result["d_sma_km"].iloc[0])

    def test_tle_gap_hours_correct(self):
        """tle_gap_hours 第二行應等於兩個 epoch 的時間差（小時）。"""
        df = self._make_elem_df(n=3)   # 間隔 12 小時
        result = compute_delta_features(df)

        assert abs(result["tle_gap_hours"].iloc[1] - 12.0) < 1e-9

    def test_first_row_tle_gap_is_nan(self):
        """第一行 tle_gap_hours 應為 NaN。"""
        df = self._make_elem_df(n=3)
        result = compute_delta_features(df)

        assert pd.isna(result["tle_gap_hours"].iloc[0])

    def test_d_ecc_is_nan_for_first_row(self):
        """d_ecc 第一行應為 NaN。"""
        df = self._make_elem_df(n=3)
        result = compute_delta_features(df)

        assert pd.isna(result["d_ecc"].iloc[0])

    def test_empty_input_returns_empty_df(self):
        """空 DataFrame 輸入應回傳空 DataFrame，且欄位正確。"""
        empty = pd.DataFrame(columns=["norad_id", "epoch_utc", "sma_km",
                                       "altitude_km", "period_min",
                                       "eccentricity", "inclination",
                                       "raan", "bstar", "mean_motion"])
        result = compute_delta_features(empty)

        assert result.empty
        assert "d_sma_km" in result.columns


# ─────────────────────────────────────────────────────────────────────────────
# compute_rolling_features
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeRollingFeatures:

    def _make_delta_df(self, n: int = 5, interval_days: float = 1.0) -> pd.DataFrame:
        """建立已含所有 delta 特徵的合成 DataFrame，時間間隔固定。"""
        base_time = pd.Timestamp("2025-01-01", tz="UTC")
        times = [base_time + pd.Timedelta(days=interval_days * i) for i in range(n)]
        sma_values = [7000.0 + i * 0.5 for i in range(n)]
        gap_hours = [np.nan] + [interval_days * 24.0] * (n - 1)
        return pd.DataFrame(
            {
                "norad_id":    [99999] * n,
                "epoch_utc":   times,
                "sma_km":      sma_values,
                "altitude_km": [sma - R_EARTH_KM for sma in sma_values],
                "period_min":  [100.0] * n,
                "eccentricity": [0.001] * n,
                "inclination":  [53.0] * n,
                "raan":         [10.0] * n,
                "bstar":        [1e-5] * n,
                "d_sma_km":    [np.nan] + [0.5] * (n - 1),
                "d_ecc":       [np.nan] + [0.0] * (n - 1),
                "d_inc_deg":   [np.nan] + [0.0] * (n - 1),
                "tle_gap_hours": gap_hours,
                "d_raan_res_deg": [np.nan] + [0.0] * (n - 1),
                "d_sma_per_day": [np.nan] + [0.5 / (interval_days)] * (n - 1),
                "d_bstar":     [np.nan] + [0.0] * (n - 1),
            }
        )

    def test_tle_count_7d_all_within_window(self):
        """5 個間隔 1 天的資料點在最後一個 epoch（第 5 天）的 7 天視窗內，count 應為 5。"""
        df = self._make_delta_df(n=5, interval_days=1.0)
        result = compute_rolling_features(df, window_days=7.0)

        # 最後一行（第 5 個 epoch = 第 4 天之後）：前 7 天涵蓋全部 5 筆
        assert result["tle_count_7d"].iloc[-1] == 5

    def test_tle_count_7d_first_row_is_one(self):
        """第一行只有自己在視窗內，tle_count_7d 應為 1。"""
        df = self._make_delta_df(n=5, interval_days=1.0)
        result = compute_rolling_features(df, window_days=7.0)

        assert result["tle_count_7d"].iloc[0] == 1

    def test_sma_slope_direction_positive(self):
        """sma_km 單調遞增時，sma_slope_km_day 應為正值。"""
        df = self._make_delta_df(n=5, interval_days=1.0)  # sma +0.5/天
        result = compute_rolling_features(df, window_days=7.0)

        # 最後一行有足夠點數，slope 應大於 0
        assert result["sma_slope_km_day"].iloc[-1] > 0.0

    def test_sma_slope_nan_when_single_point(self):
        """只有一個點在視窗內時，sma_slope_km_day 應為 NaN。"""
        df = self._make_delta_df(n=1, interval_days=1.0)
        result = compute_rolling_features(df, window_days=7.0)

        assert pd.isna(result["sma_slope_km_day"].iloc[0])

    def test_rolling_output_columns_present(self):
        """輸出 DataFrame 應包含所有滾動特徵欄位。"""
        df = self._make_delta_df(n=5)
        result = compute_rolling_features(df, window_days=7.0)

        for col in ["sma_slope_km_day", "sma_std_km", "bstar_mean",
                    "max_gap_h", "tle_count_7d"]:
            assert col in result.columns, f"缺少欄位: {col}"

    def test_empty_input_returns_empty_df(self):
        """空 DataFrame 輸入應回傳空 DataFrame，且包含滾動欄位。"""
        empty = pd.DataFrame(columns=_ROLL_COLS)
        result = compute_rolling_features(empty, window_days=7.0)

        assert result.empty
        assert "tle_count_7d" in result.columns


# ─────────────────────────────────────────────────────────────────────────────
# build_feature_matrix  (mock load_tle_for_satellite)
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildFeatureMatrix:

    def test_empty_tle_returns_empty_with_correct_columns(self):
        """load_tle_for_satellite 回傳空 DataFrame 時，應回傳空 DataFrame 且欄位完整。"""
        empty_loader_df = pd.DataFrame(
            columns=["norad_id", "epoch_utc", "line1", "line2",
                     "mean_motion", "eccentricity", "inclination", "raan",
                     "arg_perigee", "mean_anomaly", "bstar"]
        )
        with patch("data_loader.load_tle_for_satellite", return_value=empty_loader_df):
            result = build_feature_matrix(norad_id=99999, db_path="fake.duckdb")

        assert result.empty
        for col in _ROLL_COLS:
            assert col in result.columns, f"缺少欄位: {col}"

    def test_empty_tle_row_count_is_zero(self):
        """load_tle_for_satellite 回傳空 DataFrame 時，結果行數為 0。"""
        empty_loader_df = pd.DataFrame(
            columns=["norad_id", "epoch_utc", "line1", "line2",
                     "mean_motion", "eccentricity", "inclination", "raan",
                     "arg_perigee", "mean_anomaly", "bstar"]
        )
        with patch("data_loader.load_tle_for_satellite", return_value=empty_loader_df):
            result = build_feature_matrix(norad_id=99999, db_path="fake.duckdb")

        assert len(result) == 0
