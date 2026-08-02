"""tests/test_tle_catnr.py — Alpha-5 編目欄 codec 回歸。

止血目標：舊寫法 int(line[2:7]) 一遇 6 位數 NORAD（Alpha-5，如 "A0147"=100147）即
ValueError。此測試釘住 decode/encode 的傳統相容、Alpha-5 邊界與例外行為。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tle_catnr import decode_catnr, encode_catnr


# (5 字元欄, NORAD 整數)
CASES = [
    ("25544", 25544),    # 傳統 5 位數（ISS）
    ("00005", 5),        # 零填
    ("99999", 99999),    # 傳統上限
    ("A0000", 100000),   # Alpha-5 起點
    ("A0147", 100147),   # Saramago 使 SATCAT 進到的值（本次事件）
    ("E8493", 148493),
    ("Z9999", 339999),   # Alpha-5 上限
]


@pytest.mark.parametrize("field,num", CASES)
def test_decode(field, num):
    assert decode_catnr(field) == num


@pytest.mark.parametrize("field,num", CASES)
def test_encode(field, num):
    assert encode_catnr(num) == field


@pytest.mark.parametrize("field,num", CASES)
def test_round_trip(field, num):
    assert decode_catnr(encode_catnr(num)) == num
    assert encode_catnr(decode_catnr(field)) == field


def test_legacy_no_regression():
    """所有 ≤99999 仍走純數字路徑，與原 int() 完全一致。"""
    for n in (1, 42, 8493, 58573, 89494, 99999):
        assert decode_catnr(f"{n:05d}") == n


@pytest.mark.parametrize("bad", ["", "  ", "I0000", "O0000", "A00X0", "AB000"])
def test_decode_bad_raises(bad):
    with pytest.raises(ValueError):
        decode_catnr(bad)


def test_encode_out_of_range_raises():
    with pytest.raises(ValueError):
        encode_catnr(340000)   # 逾 Alpha-5，須改 GP/OMM
    with pytest.raises(ValueError):
        encode_catnr(-1)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
