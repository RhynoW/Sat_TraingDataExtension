"""tests/test_ephemeris_type.py — SGP4-XP（Ephemeris Type=4）旗標回歸。

守門點：Type-4 TLE 的平均元素以 SGP4-XP 理論擬合，用傳統 SGP4 傳播會錯，且 line1
第 45–52 欄（n̈）被 AGOM 取代。解析層必須把 line1 第 63 欄記進 ephemeris_type，
並在整批入庫時發 warning，不能靜默混入。
"""
import os
import sys
import warnings

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from satdet.common import (EPHEMERIS_TYPE_SGP4_XP, SGP4XPWarning,
                           tle_ephemeris_type, warn_sgp4xp)
from download_TLE_unified import (parse_line1_basic, parse_omm_records,
                                  parse_tle_file_to_tle_raw_records)

_L1_TYPE0 = "1 25544U 98067A   26207.50000000  .00016717  00000-0  10270-3 0  9993"
# 同一行、第 63 欄改為 4（SGP4-XP；第 45–52 欄語意變 AGOM）
_L1_TYPE4 = _L1_TYPE0[:62] + "4" + _L1_TYPE0[63:]
_L2 = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537"


def test_column_63_parsed():
    assert tle_ephemeris_type(_L1_TYPE0) == 0
    assert tle_ephemeris_type(_L1_TYPE4) == 4
    assert tle_ephemeris_type(_L1_TYPE0[:62] + " " + _L1_TYPE0[63:]) == 0  # 空白視為 0
    assert tle_ephemeris_type(None) is None
    assert tle_ephemeris_type("1 25544U") is None  # 過短


def test_parse_line1_basic_carries_flag():
    assert parse_line1_basic(_L1_TYPE0)["ephemeris_type"] == 0
    assert parse_line1_basic(_L1_TYPE4)["ephemeris_type"] == EPHEMERIS_TYPE_SGP4_XP


def test_file_parser_carries_flag(tmp_path):
    f = tmp_path / "mix.txt"
    f.write_text(f"0 ISS\n{_L1_TYPE0}\n{_L2}\n0 ISS-XP\n{_L1_TYPE4}\n{_L2}\n", encoding="utf-8")
    df = parse_tle_file_to_tle_raw_records(f)
    assert list(df["ephemeris_type"]) == [0, 4]


def test_omm_prefers_field_then_line1():
    base = dict(NORAD_CAT_ID=25544, MEAN_MOTION=15.72, EPOCH="2026-07-26T12:00:00",
                INCLINATION=51.6, RA_OF_ASC_NODE=0, ECCENTRICITY=0.0007,
                ARG_OF_PERICENTER=0, MEAN_ANOMALY=0)
    df = parse_omm_records([
        {**base, "EPHEMERIS_TYPE": "4"},
        {**base, "TLE_LINE1": _L1_TYPE4},          # 無 EPHEMERIS_TYPE → 讀 line1
        {**base},                                   # 兩者皆無 → None
    ])
    assert list(df["ephemeris_type"].astype(object)) == [4, 4, None] or \
        (df["ephemeris_type"].tolist()[:2] == [4, 4] and df["ephemeris_type"].isna().iloc[2])


def test_warn_on_type4_not_on_type0():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert warn_sgp4xp([0, 0, None]) == 0        # 不得誤報
    with pytest.warns(SGP4XPWarning):
        assert warn_sgp4xp([0, 4, 4]) == 2
