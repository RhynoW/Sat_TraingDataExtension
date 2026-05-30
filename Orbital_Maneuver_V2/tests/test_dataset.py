"""
test_dataset.py
===============
Unit tests for dataset.py.

所有測試使用合成 DataFrame，不依賴外部 Parquet 或 DB 檔案。
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
import pytest

from dataset import (
    FEATURE_COLS,
    LABEL_EXCLUDED,
    LABEL_MANEUVERING,
    LABEL_NOMINAL,
    TEST_END,
    TRAIN_END,
    VAL_END,
    build_dataset,
    get_class_weights,
    time_split,
)


# ─────────────────────────────────────────────────────────────────────────────
# 輔助函式
# ─────────────────────────────────────────────────────────────────────────────

def _make_feature_df(
    norad_ids: list[int],
    epochs: list[pd.Timestamp],
) -> pd.DataFrame:
    """建立含有所有 FEATURE_COLS 的合成 DataFrame（全部填 1.0）。"""
    n = len(epochs)
    assert len(norad_ids) == n
    data = {
        "norad_id":  norad_ids,
        "epoch_utc": epochs,
    }
    for col in FEATURE_COLS:
        data[col] = [1.0] * n
    return pd.DataFrame(data)


def _make_label_df(
    norad_ids: list[int],
    epochs: list[pd.Timestamp],
    labels: list[int],
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "norad_id":  norad_ids,
            "epoch_utc": epochs,
            "label":     labels,
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# build_dataset
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildDataset:

    def _make_three_row_data(self):
        """建立三行資料：label 0、1、-1 各一筆，epoch 相同以便對齊。"""
        base = pd.Timestamp("2026-01-15", tz="UTC")
        epochs = [base, base + pd.Timedelta(hours=1), base + pd.Timedelta(hours=2)]
        norad_ids = [99999, 99999, 99999]
        labels = [LABEL_NOMINAL, LABEL_MANEUVERING, LABEL_EXCLUDED]

        feat_df = _make_feature_df(norad_ids, epochs)
        lbl_df = _make_label_df(norad_ids, epochs, labels)
        return feat_df, lbl_df

    def test_excluded_rows_are_dropped(self):
        """label=-1 的行應被丟棄，不出現在結果中。"""
        feat_df, lbl_df = self._make_three_row_data()
        result = build_dataset(feat_df, lbl_df)

        assert LABEL_EXCLUDED not in result["label"].values

    def test_nominal_rows_are_kept(self):
        """label=0 的行應保留在結果中。"""
        feat_df, lbl_df = self._make_three_row_data()
        result = build_dataset(feat_df, lbl_df)

        assert LABEL_NOMINAL in result["label"].values

    def test_maneuvering_rows_are_kept(self):
        """label=1 的行應保留在結果中。"""
        feat_df, lbl_df = self._make_three_row_data()
        result = build_dataset(feat_df, lbl_df)

        assert LABEL_MANEUVERING in result["label"].values

    def test_result_row_count_excludes_excluded(self):
        """三行（0、1、-1），結果應只剩 2 行。"""
        feat_df, lbl_df = self._make_three_row_data()
        result = build_dataset(feat_df, lbl_df)

        assert len(result) == 2

    def test_nan_feature_rows_are_dropped(self):
        """含有 NaN 特徵的行應被丟棄。"""
        base = pd.Timestamp("2026-01-15", tz="UTC")
        epochs = [base, base + pd.Timedelta(hours=1)]
        norad_ids = [99999, 99999]

        feat_df = _make_feature_df(norad_ids, epochs)
        # 第一行的 sma_km 設為 NaN
        feat_df.loc[0, "sma_km"] = np.nan
        lbl_df = _make_label_df(norad_ids, epochs, [LABEL_NOMINAL, LABEL_NOMINAL])

        result = build_dataset(feat_df, lbl_df)

        assert len(result) == 1

    def test_inner_join_drops_unmatched_rows(self):
        """feature_df 與 label_df 的 (norad_id, epoch_utc) 不匹配時，該行應被丟棄。"""
        base = pd.Timestamp("2026-01-15", tz="UTC")
        feat_epochs = [base, base + pd.Timedelta(hours=1)]
        lbl_epochs  = [base]  # 只有一筆對應
        norad_ids   = [99999, 99999]

        feat_df = _make_feature_df(norad_ids, feat_epochs)
        lbl_df  = _make_label_df([99999], lbl_epochs, [LABEL_NOMINAL])

        result = build_dataset(feat_df, lbl_df)

        assert len(result) == 1


# ─────────────────────────────────────────────────────────────────────────────
# time_split
# ─────────────────────────────────────────────────────────────────────────────

class TestTimeSplit:

    def _make_split_df(self) -> pd.DataFrame:
        """
        建立橫跨 TRAIN_END / VAL_END 三段的 DataFrame：
        TRAIN_END = "2026-05-15"
        VAL_END   = "2026-05-20"
        TEST_END  = "2026-05-25"
        """
        epochs = [
            pd.Timestamp("2026-05-10", tz="UTC"),   # train
            pd.Timestamp("2026-05-14", tz="UTC"),   # train
            pd.Timestamp("2026-05-15", tz="UTC"),   # val（>= TRAIN_END）
            pd.Timestamp("2026-05-18", tz="UTC"),   # val
            pd.Timestamp("2026-05-20", tz="UTC"),   # test（>= VAL_END）
            pd.Timestamp("2026-05-23", tz="UTC"),   # test
        ]
        n = len(epochs)
        feat_df = _make_feature_df([99999] * n, epochs)
        feat_df["label"] = [LABEL_NOMINAL] * n
        return feat_df

    def test_train_split_row_count(self):
        """train split 應包含 epoch < TRAIN_END 的行（共 2 行）。"""
        df = self._make_split_df()
        train, _, _ = time_split(df)

        assert len(train) == 2

    def test_val_split_row_count(self):
        """val split 應包含 TRAIN_END <= epoch < VAL_END 的行（共 2 行）。"""
        df = self._make_split_df()
        _, val, _ = time_split(df)

        assert len(val) == 2

    def test_test_split_row_count(self):
        """test split 應包含 VAL_END <= epoch < TEST_END 的行（共 2 行）。"""
        df = self._make_split_df()
        _, _, test = time_split(df)

        assert len(test) == 2

    def test_train_max_epoch_before_train_end(self):
        """train split 的最大 epoch 應嚴格小於 TRAIN_END。"""
        df = self._make_split_df()
        train_end_ts = pd.Timestamp(TRAIN_END, tz="UTC")
        train, _, _ = time_split(df)

        assert train["epoch_utc"].max() < train_end_ts

    def test_val_min_epoch_at_or_after_train_end(self):
        """val split 的最小 epoch 應 >= TRAIN_END。"""
        df = self._make_split_df()
        train_end_ts = pd.Timestamp(TRAIN_END, tz="UTC")
        _, val, _ = time_split(df)

        assert val["epoch_utc"].min() >= train_end_ts

    def test_test_min_epoch_at_or_after_val_end(self):
        """test split 的最小 epoch 應 >= VAL_END。"""
        df = self._make_split_df()
        val_end_ts = pd.Timestamp(VAL_END, tz="UTC")
        _, _, test = time_split(df)

        assert test["epoch_utc"].min() >= val_end_ts

    def test_splits_are_non_overlapping(self):
        """三個 split 合計行數應等於原始 DataFrame 的行數（無重複）。"""
        df = self._make_split_df()
        train, val, test = time_split(df)

        assert len(train) + len(val) + len(test) == len(df)


# ─────────────────────────────────────────────────────────────────────────────
# get_class_weights
# ─────────────────────────────────────────────────────────────────────────────

class TestGetClassWeights:

    def test_minority_class_has_higher_weight(self):
        """少數類別（1）的權重應大於多數類別（0）。"""
        y = np.array([0, 0, 0, 1])
        weights = get_class_weights(y)

        assert weights[0] < weights[1]

    def test_balanced_labels_have_equal_weights(self):
        """各類別數量相同時，兩個權重應相等。"""
        y = np.array([0, 0, 1, 1])
        weights = get_class_weights(y)

        assert abs(weights[0] - weights[1]) < 1e-9

    def test_weights_dict_has_correct_keys(self):
        """回傳 dict 的 key 應包含 0 和 1。"""
        y = np.array([0, 0, 1])
        weights = get_class_weights(y)

        assert 0 in weights
        assert 1 in weights

    def test_weighted_sum_equals_n_classes(self):
        """
        balanced weight 性質：
        sum(n_i * w_i) = n_total
        等價於 sum(n_i / (n_classes * n_i)) * n_total = n_total
        即 len(classes) 個 weight 的倒數加總 = 1 / n_classes * n_classes = 1。
        """
        y = np.array([0, 0, 0, 1])
        weights = get_class_weights(y)
        n_total = len(y)
        n_classes = 2

        # w_i = n_total / (n_classes * n_i)
        # 因此 n_i * w_i = n_total / n_classes
        # sum over all classes = n_total
        weighted_sum = sum(
            int((y == cls).sum()) * weights[cls] for cls in [0, 1]
        )
        assert abs(weighted_sum - n_total) < 1e-9

    def test_single_class_zero_still_returns_weight(self):
        """y_train 只有一種類別時，應正常回傳（不拋出例外）。"""
        y = np.array([0, 0, 0])
        try:
            weights = get_class_weights(y)
            assert 0 in weights
        except Exception as exc:
            pytest.fail(f"不應拋出例外，但拋出了: {exc}")

    def test_series_input_accepted(self):
        """接受 pd.Series 輸入，結果與 numpy array 相同。"""
        y_arr = np.array([0, 0, 0, 1])
        y_ser = pd.Series([0, 0, 0, 1])

        weights_arr = get_class_weights(y_arr)
        weights_ser = get_class_weights(y_ser)

        assert abs(weights_arr[0] - weights_ser[0]) < 1e-9
        assert abs(weights_arr[1] - weights_ser[1]) < 1e-9
