"""formosat7_leoorb 與 sp3_core 的回歸測試（不需網路）。

重點放在「弄錯不會報錯」的那幾項：時制、單位、框架、epoch 秒偏移。
"""

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from formosat7_leoorb import archive, download, merge, satmap  # noqa: E402
from sp3_core import _time_system_from_header, parse_sp3_lines  # noqa: E402


# ── %c 表頭時制判讀 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("line,expected", [
    # leoOrb：檔案型別欄空白 —— split()[3] 會取到 'ccc'，固定欄位才對
    ("%c    cc GPS ccc cccc cccc cccc cccc", "GPS"),
    # 標準 SP3-c：型別欄有填
    ("%c M  cc GPS ccc cccc cccc cccc cccc", "GPS"),
    ("%c M  cc TAI ccc cccc cccc cccc cccc", "TAI"),
    ("%c M  cc UTC ccc cccc cccc cccc cccc", "UTC"),
])
def test_time_system_from_header(line, expected):
    assert _time_system_from_header(line) == expected


def test_leoorb_header_defeats_split_based_parsing():
    """守住這個回歸：leoOrb 表頭用 split()[3] 會靜默判錯（=128 km 沿跡誤差）。"""
    line = "%c    cc GPS ccc cccc cccc cccc cccc"
    assert line.split()[3] == "ccc"          # 錯誤做法確實會踩雷
    assert _time_system_from_header(line) == "GPS"


# ── 時制換算 ──────────────────────────────────────────────────────────────

#: SP3 是固定欄寬格式：記錄型別 1 字元、衛星代號 3 字元，
#: 其後 X/Y/Z（或 VX/VY/VZ）各佔 14 字元。夾具必須照這個排，否則欄位會錯位。
_P_POS_KM = (2806.907, 6363.434, 0.008)
_V_DM_S = (-58674.0, 25881.0, 30800.0)


def _fixed(tag: str, values) -> str:
    return tag + "".join("%14.7f" % v for v in values) + "%14.6f" % 999999.999999


def _lines(time_system: str) -> list:
    return [
        "#cV2026  8 16 21 54  0.00000000       1       IGS08 FIT UCAR",
        "## 2432  78840.00000000    60.00000000 61268 0.9124999999985",
        "+    1   L76  0  0  0  0  0  0  0  0  0  0  0  0  0  0  0  0  0",
        "%c    cc " + time_system + " ccc cccc cccc cccc cccc",
        "*  2026  8 16 21 54  0.00000000",
        _fixed("PL76", _P_POS_KM),
        _fixed("VL76", _V_DM_S),
    ]


@pytest.mark.parametrize("ts,expect_second", [
    ("GPS", 42),   # 21:54:00 GPS - 18 s -> 21:53:42 UTC
    ("TAI", 23),   # 21:54:00 TAI - 37 s -> 21:53:23 UTC
    ("UTC", 0),    # 不修正
])
def test_epoch_time_system_conversion(ts, expect_second):
    df = parse_sp3_lines(_lines(ts))
    assert len(df) == 1
    assert df["epoch"].iloc[0].second == expect_second


def test_velocity_stays_in_dm_s():
    """解析器不代為換算單位，欄名即單位。dm/s -> km/s 是除以 10000。"""
    df = parse_sp3_lines(_lines("GPS"))
    assert df["vx_dm_s"].iloc[0] == pytest.approx(-58674.0)
    km_s = archive.add_velocity_km_s(df)["vx_km_s"].iloc[0]
    assert km_s == pytest.approx(-5.8674)


# ── 框架：地固 vs 慣性 ────────────────────────────────────────────────────

def test_inertial_velocity_matches_circular_speed():
    """漏掉 omega x r 的話 |v| 約 7.11，補上後才約 7.57 = sqrt(mu/r)。"""
    df = parse_sp3_lines(_lines("GPS"))
    d = archive.add_inertial_velocity(df)
    r = np.linalg.norm(d[["x_km", "y_km", "z_km"]].to_numpy(float)[0])
    v_ecef = np.linalg.norm(d[["vx_km_s", "vy_km_s", "vz_km_s"]].to_numpy(float)[0])
    v_eci = np.linalg.norm(d[["vx_eci_km_s", "vy_eci_km_s", "vz_eci_km_s"]].to_numpy(float)[0])
    v_circ = np.sqrt(archive.MU_EARTH_KM3_S2 / r)

    # 夾具取的是來源文件表格裡**四捨五入後的顯示值**，導出的速度因此是
    # 7.1141 / 7.5745；文件用全精度原始值算出的是 7.1117 / 7.5730。
    # 差異來自夾具輸入精度，不是換算邏輯。
    assert v_ecef == pytest.approx(7.1141, abs=1e-3)
    assert v_eci == pytest.approx(7.5745, abs=1e-3)
    # 慣性速度應貼近圓軌速度（0.1% 內），地固速度則明顯偏低
    assert abs(v_eci - v_circ) / v_circ < 1e-3
    assert abs(v_ecef - v_circ) / v_circ > 0.05


# ── 檔名與星號對照 ────────────────────────────────────────────────────────

def test_parse_arc_filename():
    m = archive.parse_arc_filename("leoOrb_2026.229.001.01_0001.0001_sp3")
    assert m["year"] == 2026 and m["doy"] == 229
    assert m["sat_index"] == "001" and m["arc_index"] == "01"
    assert archive.parse_arc_filename("not_a_leoorb_file.txt") is None


def test_satmap():
    assert satmap.norad_for_sp3("L76") == 44349
    assert satmap.sp3_for_arc_index("005") == "L80"
    assert satmap.norad_for_sp3("ZZZ") is None
    # 六個對照都已用實資料位置比對驗證（L78 於 2024.121-125）
    assert all(satmap.is_verified(s) for s in satmap.SP3_TO_NORAD)
    assert satmap.UNCONFIRMED_SP3 == frozenset()
    assert not satmap.is_verified("ZZZ")


# ── 日期標籤 ──────────────────────────────────────────────────────────────

def test_day_tag_roundtrip():
    assert download.day_tag(date(2026, 8, 17)) == "2026.229"
    assert download.parse_day_tag("2026.229") == date(2026, 8, 17)
    assert download.day_tag(date(2019, 10, 1)) == download.EARLIEST_DAY_TAG
    with pytest.raises(ValueError):
        download.parse_day_tag("2026-229")


def test_day_url():
    assert download.day_url("2026.229").endswith(
        "/daily_tar/2026.229/leoOrb_2026.229.tar.gz")


# ── 抽稀：epoch 不落在整分上 ──────────────────────────────────────────────

def test_resample_handles_non_round_second_offset():
    """epoch 是 HH:MM:42（GPS-18 s）。直接對 Unix 秒取模會全部落空。"""
    ep = pd.date_range("2026-08-16 00:00:42", periods=60, freq="60s", tz="UTC")
    m = pd.DataFrame({"sp3_sat": "L76", "epoch": ep})
    out = merge.resample(m, step_minutes=5)
    assert len(out) == 12
    assert (out["epoch"].dt.second == 42).all()
    deltas = out["epoch"].diff().dropna().dt.total_seconds().unique()
    assert list(deltas) == [300.0]
