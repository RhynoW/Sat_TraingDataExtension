"""
test_labeler.py
===============
Unit tests for labeler.py.

所有測試使用合成 DataFrame，不載入真實殘差 CSV。
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
import pytest

from labeler import (
    LABEL_EXCLUDED,
    LABEL_MANEUVERING,
    LABEL_NOMINAL,
    assign_labels,
    detect_meme_events,
    detect_mode_a,
)


# ─────────────────────────────────────────────────────────────────────────────
# 輔助函式
# ─────────────────────────────────────────────────────────────────────────────

def _make_res_df(
    norad_id: int,
    times: list[pd.Timestamp],
    pos_errs: list[float],
    valid: bool = True,
) -> pd.DataFrame:
    """建立最小合成殘差 DataFrame。"""
    return pd.DataFrame(
        {
            "norad_id":         [norad_id] * len(times),
            "t":                times,
            "pos_err_km":       pos_errs,
            "valid_for_training": [valid] * len(times),
        }
    )


def _make_v_shape_res(
    norad_id: int = 12345,
    peak_value: float = 200.0,
    low_value: float = 5.0,
) -> pd.DataFrame:
    """
    建立 V 形 pos_err_km 殘差：低→高→低。
    確保：peak > _PEAK_THRESHOLD_KM (50 km)，恢復後 < _RECOVERY_THRESHOLD_KM (20 km)。
    """
    base = pd.Timestamp("2025-06-01T12:00:00", tz="UTC")
    times = [base + pd.Timedelta(hours=h) for h in [0, 6, 12, 18, 24]]
    # 低 → 高 → 最高 → 下降 → 低（恢復）
    pos_errs = [low_value, 60.0, peak_value, 80.0, low_value]
    return _make_res_df(norad_id, times, pos_errs, valid=True)


# ─────────────────────────────────────────────────────────────────────────────
# detect_meme_events
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectMemeEvents:

    def test_v_shape_detects_one_event(self):
        """V 形殘差應偵測到恰好一個機動事件。"""
        res_df = _make_v_shape_res()
        events = detect_meme_events(res_df)

        assert len(events) == 1

    def test_v_shape_event_peak_is_maximum(self):
        """偵測到的事件 peak_pos_err_km 應為輸入序列的最大值。"""
        peak_value = 200.0
        res_df = _make_v_shape_res(peak_value=peak_value)
        events = detect_meme_events(res_df)

        assert abs(events["peak_pos_err_km"].iloc[0] - peak_value) < 1e-9

    def test_v_shape_event_has_correct_norad_id(self):
        """偵測到的事件 norad_id 應與輸入一致。"""
        norad_id = 55555
        res_df = _make_v_shape_res(norad_id=norad_id)
        events = detect_meme_events(res_df)

        assert int(events["norad_id"].iloc[0]) == norad_id

    def test_event_columns_present(self):
        """回傳 DataFrame 必須包含所有必要欄位。"""
        res_df = _make_v_shape_res()
        events = detect_meme_events(res_df)

        for col in ["norad_id", "event_peak_t", "event_start_t",
                    "event_end_t", "peak_pos_err_km"]:
            assert col in events.columns, f"缺少欄位: {col}"

    def test_all_below_threshold_returns_empty(self):
        """所有 pos_err_km 低於閾值時，應回傳空 DataFrame。"""
        base = pd.Timestamp("2025-06-01", tz="UTC")
        times = [base + pd.Timedelta(hours=h) for h in range(5)]
        res_df = _make_res_df(12345, times, [1.0, 2.0, 3.0, 2.0, 1.0])
        events = detect_meme_events(res_df)

        assert events.empty

    def test_empty_input_returns_empty_df(self):
        """空 DataFrame 輸入應回傳空 DataFrame，且無例外拋出。"""
        empty = pd.DataFrame(columns=["norad_id", "t", "pos_err_km", "valid_for_training"])
        events = detect_meme_events(empty)

        assert events.empty
        assert "norad_id" in events.columns

    def test_empty_input_no_exception(self):
        """空 DataFrame 輸入不應拋出任何例外。"""
        empty = pd.DataFrame(columns=["norad_id", "t", "pos_err_km", "valid_for_training"])
        try:
            detect_meme_events(empty)
        except Exception as exc:
            pytest.fail(f"不應拋出例外，但拋出了: {exc}")

    def test_single_row_returns_empty(self):
        """只有一行資料（< 3 行）時，應回傳空 DataFrame。"""
        base = pd.Timestamp("2025-06-01", tz="UTC")
        res_df = _make_res_df(12345, [base], [300.0])
        events = detect_meme_events(res_df)

        assert events.empty


# ─────────────────────────────────────────────────────────────────────────────
# detect_mode_a
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectModeA:

    def _make_monotone_high_res(
        self,
        norad_id: int = 12345,
        n: int = 6,
        start_val: float = 600.0,
        step: float = 50.0,
    ) -> pd.DataFrame:
        """
        建立 pos_err > MODE_A_POS_THRESHOLD (500 km) 且單調遞增的殘差序列。
        """
        base = pd.Timestamp("2025-06-10T00:00:00", tz="UTC")
        times = [base + pd.Timedelta(hours=12 * i) for i in range(n)]
        pos_errs = [start_val + step * i for i in range(n)]
        return _make_res_df(norad_id, times, pos_errs)

    def test_monotone_above_threshold_detects_one_window(self):
        """單調遞增且 > 500 km 的序列應偵測到一個 Mode A 視窗。"""
        res_df = self._make_monotone_high_res()
        windows = detect_mode_a(res_df)

        assert len(windows) == 1

    def test_mode_a_columns_present(self):
        """回傳 DataFrame 必須包含所有必要欄位。"""
        res_df = self._make_monotone_high_res()
        windows = detect_mode_a(res_df)

        for col in ["norad_id", "window_start_t", "window_end_t"]:
            assert col in windows.columns, f"缺少欄位: {col}"

    def test_all_below_threshold_returns_empty(self):
        """所有 pos_err_km < 500 km 時，不應偵測到任何 Mode A 視窗。"""
        base = pd.Timestamp("2025-06-01", tz="UTC")
        times = [base + pd.Timedelta(hours=h) for h in range(5)]
        res_df = _make_res_df(12345, times, [100.0] * 5)
        windows = detect_mode_a(res_df)

        assert windows.empty

    def test_descending_does_not_trigger_mode_a(self):
        """
        pos_err > 500 km 但單調遞減（< 80% 遞增）時，
        不應觸發 Mode A（monotone_frac < MODE_A_MONOTONE_FRAC）。
        """
        base = pd.Timestamp("2025-06-01", tz="UTC")
        times = [base + pd.Timedelta(hours=12 * i) for i in range(6)]
        # 單調遞減：diffs 全部 < 0，monotone_frac = 0
        pos_errs = [1000.0 - 50.0 * i for i in range(6)]
        res_df = _make_res_df(12345, times, pos_errs)
        windows = detect_mode_a(res_df)

        assert windows.empty

    def test_empty_input_returns_empty_df(self):
        """空 DataFrame 輸入應回傳空 DataFrame。"""
        empty = pd.DataFrame(columns=["norad_id", "t", "pos_err_km", "valid_for_training"])
        windows = detect_mode_a(empty)

        assert windows.empty


# ─────────────────────────────────────────────────────────────────────────────
# assign_labels
# ─────────────────────────────────────────────────────────────────────────────

class TestAssignLabels:

    def _make_tle_epochs(
        self,
        norad_id: int,
        times: list[pd.Timestamp],
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "norad_id":   [norad_id] * len(times),
                "epoch_utc":  times,
            }
        )

    def test_label_column_added(self):
        """assign_labels 應在 tle_epochs_df 中加入 label 欄位。"""
        norad_id = 12345
        peak_time = pd.Timestamp("2025-06-01T12:00:00", tz="UTC")

        # 構造一個觸發 MEME event 的殘差
        res_df = _make_v_shape_res(norad_id=norad_id)

        # TLE epoch 就在 peak 附近（< 24 h）
        tle_times = [peak_time + pd.Timedelta(hours=2)]
        tle_df = self._make_tle_epochs(norad_id, tle_times)

        result = assign_labels(tle_df, res_df)

        assert "label" in result.columns

    def test_maneuvering_epoch_labeled_one(self):
        """
        與機動 peak 相距 2 小時的 TLE epoch（< MEME_EVENT_WINDOW_H=24h），
        應被標記為 LABEL_MANEUVERING = 1。
        """
        norad_id = 12345
        # V 形殘差的 peak 落在 base + 12h
        base = pd.Timestamp("2025-06-01T12:00:00", tz="UTC")
        times = [base + pd.Timedelta(hours=h) for h in [0, 6, 12, 18, 24]]
        pos_errs = [5.0, 60.0, 200.0, 80.0, 5.0]
        res_df = _make_res_df(norad_id, times, pos_errs)

        peak_t = base + pd.Timedelta(hours=12)  # index=2
        tle_epoch = peak_t + pd.Timedelta(hours=2)  # 與 peak 差 2h < 24h
        tle_df = self._make_tle_epochs(norad_id, [tle_epoch])

        result = assign_labels(tle_df, res_df)

        assert result["label"].iloc[0] == LABEL_MANEUVERING

    def test_nominal_epoch_labeled_zero(self):
        """
        遠離任何機動事件且 valid_for_training=True 的 epoch，
        應被標記為 LABEL_NOMINAL = 0。
        """
        norad_id = 77777
        base = pd.Timestamp("2025-01-01", tz="UTC")
        # 全程低殘差，valid_for_training=True
        times = [base + pd.Timedelta(hours=h) for h in range(0, 36, 6)]
        pos_errs = [2.0] * len(times)
        res_df = _make_res_df(norad_id, times, pos_errs, valid=True)

        # TLE epoch 落在殘差覆蓋的中間
        tle_epoch = base + pd.Timedelta(hours=12)
        tle_df = self._make_tle_epochs(norad_id, [tle_epoch])

        result = assign_labels(tle_df, res_df)

        assert result["label"].iloc[0] == LABEL_NOMINAL

    def test_empty_tle_epochs_returns_empty_with_label_col(self):
        """空 tle_epochs_df 應回傳空 DataFrame 且包含 label 欄位。"""
        tle_df = pd.DataFrame(columns=["norad_id", "epoch_utc"])
        res_df = _make_v_shape_res()

        result = assign_labels(tle_df, res_df)

        assert result.empty
        assert "label" in result.columns

    def test_empty_res_df_leads_to_excluded(self):
        """
        沒有殘差資料時，所有 TLE epoch 應被標記為 LABEL_EXCLUDED（無法確認）。
        """
        norad_id = 11111
        base = pd.Timestamp("2025-01-01", tz="UTC")
        tle_df = self._make_tle_epochs(norad_id, [base])
        res_df = pd.DataFrame(columns=["norad_id", "t", "pos_err_km", "valid_for_training"])

        result = assign_labels(tle_df, res_df)

        assert result["label"].iloc[0] == LABEL_EXCLUDED
