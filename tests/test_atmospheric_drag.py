# -*- coding: utf-8 -*-
"""tests/test_atmospheric_drag.py — atmospheric_drag 兩個 2026-09-29 修正的回歸測試。

  1. pymsis 開關 9：3 小時 ap(7) 必須真正影響密度（STORM_AP_MODE=True），
     關閉時退回只讀日均 Ap 的舊行為。
  2. drag_residual 的 dt 與 datetime 解析度無關：[us] 與 [ns] 輸入得到相同 B_eff 與殘差。

用法：pytest tests/test_atmospheric_drag.py -v
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("pymsis")
import atmospheric_drag as AD  # noqa: E402

SW = {"2024-05-10": (180.0, 170.0, 100.0), "2024-05-11": (180.0, 170.0, 150.0)}


def _density_with_ap(monkeypatch, ap3h: float, storm: bool) -> float:
    """固定日均 Ap，只改 3 小時 ap，看密度是否跟著變。"""
    monkeypatch.setattr(AD, "_ap7_array", lambda epochs, daily: np.array([[daily[0]] + [ap3h] * 6]))
    return float(AD.density(pd.to_datetime(["2024-05-11T00:00Z"]), [400.0], SW, storm_ap=storm)[0])


def test_3h_ap_takes_effect_in_storm_mode(monkeypatch):
    lo, hi = _density_with_ap(monkeypatch, 10.0, True), _density_with_ap(monkeypatch, 400.0, True)
    assert hi > 1.5 * lo


def test_legacy_mode_ignores_3h_ap(monkeypatch):
    lo, hi = _density_with_ap(monkeypatch, 10.0, False), _density_with_ap(monkeypatch, 400.0, False)
    assert hi == pytest.approx(lo, rel=1e-12)


def _decay_track(unit: str) -> pd.DataFrame:
    t = pd.Series(pd.date_range("2024-05-10", periods=12, freq="8h", tz="UTC")).astype(f"datetime64[{unit}, UTC]")
    a = 6378.137 + 420.0 - 0.02 * np.arange(12)
    return pd.DataFrame({"epoch": t, "sma_km": a, "eccentricity": 0.0005})


def test_dt_independent_of_datetime_resolution():
    r_us = AD.drag_residual(_decay_track("us"), SW)
    r_ns = AD.drag_residual(_decay_track("ns"), SW)
    assert r_us.attrs["B_eff"] == pytest.approx(r_ns.attrs["B_eff"], rel=1e-9)
    np.testing.assert_allclose(r_us["drag_resid_da"], r_ns["drag_resid_da"], rtol=1e-9, atol=1e-12)
