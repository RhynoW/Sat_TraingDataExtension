"""tests/test_sixdigit_ingest.py — 6 位數 NORAD 匯入回歸（C.1 正規式 + C.2 OMM）。

守門兩個真正的阻斷點：
  C.1 parse_tle_file_to_tle_raw_records 的 LINE1_RE/LINE2_RE 曾要求編目欄 5 位數字，
      Alpha-5 行（"1 A0000U…"=100000）會在解析前被丟棄。
  C.2 parse_omm_records 以 OMM NORAD_CAT_ID 整數欄讀入，連逾 Alpha-5（>339999，官方
      已不發 TLE）之物件亦可入庫。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from download_TLE_unified import parse_tle_file_to_tle_raw_records, parse_omm_records

# 真實格式：SARAMAGO=A0000(100000) 與傳統 VANGUARD=00005 各一組 3LE
_SARAMAGO = (
    "0 SARAMAGO\n"
    "1 A0000U 26067CY  26206.89652557  .00009402  00000-0  43149-3 0  9993\n"
    "2 A0000  97.4594 164.9741 0006254 220.0061 140.0714 15.20618096 17586\n"
)
_VANGUARD = (
    "0 VANGUARD 1\n"
    "1 00005U 58002B   26207.00122857  .00000332  00000-0  41766-3 0  9997\n"
    "2 00005  34.2489 194.5521 1836675 313.4847  32.6675 10.86020778447508\n"
)


def test_parser_accepts_alpha5(tmp_path):
    """C.1：Alpha-5 6 位數不再被 LINE1_RE/LINE2_RE 丟棄。"""
    f = tmp_path / "mini.tle"
    f.write_text(_SARAMAGO + _VANGUARD, encoding="utf-8")
    df = parse_tle_file_to_tle_raw_records(f)
    ids = set(df["norad_id"])
    assert 100000 in ids, "6 位數 SARAMAGO(100000) 應被解析"
    assert 5 in ids, "傳統 5 位數不得回歸失效"


def test_parser_classic_only_unchanged(tmp_path):
    """僅傳統 5 位數時行為與原本一致。"""
    f = tmp_path / "classic.tle"
    f.write_text(_VANGUARD, encoding="utf-8")
    df = parse_tle_file_to_tle_raw_records(f)
    assert list(df["norad_id"]) == [5]


_OMM = [
    {"OBJECT_NAME": "ISS (ZARYA)", "OBJECT_ID": "1998-067A",
     "EPOCH": "2026-07-27T05:03:21.680640", "MEAN_MOTION": 15.5, "ECCENTRICITY": 0.0004,
     "INCLINATION": 51.6, "RA_OF_ASC_NODE": 100.0, "ARG_OF_PERICENTER": 50.0,
     "MEAN_ANOMALY": 10.0, "BSTAR": 3.2e-4, "CLASSIFICATION_TYPE": "U",
     "NORAD_CAT_ID": 25544, "ELEMENT_SET_NO": 999, "REV_AT_EPOCH": 48,
     "TLE_LINE1": "1 25544U ...", "TLE_LINE2": "2 25544  ..."},
    {"OBJECT_NAME": "SARAMAGO", "OBJECT_ID": "2026-067CY",
     "EPOCH": "2026-07-25T21:30:59.809248", "MEAN_MOTION": 15.206, "ECCENTRICITY": 0.0006254,
     "INCLINATION": 97.4594, "RA_OF_ASC_NODE": 164.97, "ARG_OF_PERICENTER": 220.0,
     "MEAN_ANOMALY": 140.07, "BSTAR": 4.3e-4, "CLASSIFICATION_TYPE": "U",
     "NORAD_CAT_ID": 100000, "ELEMENT_SET_NO": 999, "REV_AT_EPOCH": 1758,
     "TLE_LINE1": "1 A0000U ...", "TLE_LINE2": "2 A0000  ..."},
    {"OBJECT_NAME": "FUTURE-OBJ", "OBJECT_ID": "2027-001A",
     "EPOCH": "2027-01-01T00:00:00", "MEAN_MOTION": 14.0, "ECCENTRICITY": 0.001,
     "INCLINATION": 53.0, "RA_OF_ASC_NODE": 0.0, "ARG_OF_PERICENTER": 0.0,
     "MEAN_ANOMALY": 0.0, "BSTAR": 1e-4, "CLASSIFICATION_TYPE": "U",
     "NORAD_CAT_ID": 350000, "ELEMENT_SET_NO": 1, "REV_AT_EPOCH": 1},  # 逾 Alpha-5，無 TLE
]


def test_omm_reads_integer_catnr():
    """C.2：OMM 以整數 NORAD_CAT_ID 讀入，含 6 位數與逾 Alpha-5。"""
    df = parse_omm_records(_OMM, source_file="unit.omm.json")
    assert list(df["norad_id"]) == [25544, 100000, 350000]
    # 逾 Alpha-5 無 TLE 表示，line1 為空但仍成功入 df（治本不依賴 TLE 格式）
    assert df.loc[df.norad_id == 350000, "line1"].isna().all()
    # 軌道欄位正確映射
    row = df.loc[df.norad_id == 100000].iloc[0]
    assert abs(row["inclination_deg"] - 97.4594) < 1e-6
    assert abs(row["mean_motion"] - 15.206) < 1e-6


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
