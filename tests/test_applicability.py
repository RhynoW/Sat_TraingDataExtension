# -*- coding: utf-8 -*-
"""tests/test_applicability.py — 步驟 4「不適用要明說」與「沒有真值≠安靜」之回歸測試

  1. truth_coverage()：須以完整真值表計算（含 none／small 轉移），涵蓋時段＝最早 t_from 到最晚 t_to
  2. coverage_mask()：沒有真值（cov=None）時全為 False——不可被當成安靜負樣本
  3. assess()：訓練族群外之傾角／高度／入軌天數要列出原因並判為 out_of_domain；族群內判為 applicable

用法：pytest tests/test_applicability.py -v
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from satdet import coverage_mask, to_ns, truth_coverage
from applicability import assess

DOMAIN = {"inc_families_deg": [[52.6, 53.7, 10]], "alt_range_km": [324.0, 588.0], "min_age_days": 4.0}


def test_truth_coverage_uses_all_severities():
    truth = pd.DataFrame({
        "norad_id": [1, 1, 2],
        "t_from": ["2026-05-01", "2026-06-01", "2026-07-01"],
        "t_to": ["2026-05-02", "2026-06-02", "2026-07-02"],
        "da_severity": ["none", "small", "medium"],
    })
    cov = truth_coverage(truth)
    assert set(cov) == {1, 2}          # 只有 none／small 的衛星 1 也必須有涵蓋時段
    lo, hi = cov[1]
    assert lo == to_ns(pd.Series(["2026-05-01"]))[0]
    assert hi == to_ns(pd.Series(["2026-06-02"]))[0]


def test_coverage_mask_no_truth_is_never_quiet():
    ep = to_ns(pd.Series(pd.date_range("2026-05-01", periods=10, freq="D")))
    assert not coverage_mask(ep, None).any()
    cov = (int(ep[2]), int(ep[5]))
    m = coverage_mask(ep, cov)
    assert m.tolist() == [False, False, True, True, True, True, False, False, False, False]


def _tle(inc, alt, days=10):
    t = pd.date_range("2026-10-01", periods=days * 3, freq="8h", tz="UTC")
    return pd.DataFrame({"epoch": t, "sma_km": np.full(len(t), 6378.137 + alt), "inclination_deg": np.full(len(t), inc)})


def test_assess_out_of_domain_reasons():
    a = assess(_tle(30.5, 300.0), t_first=pd.Timestamp("2026-10-01", tz="UTC"), domain=DOMAIN, use_regime=False)
    assert (a.status == "out_of_domain").all()
    r = a.reasons.iloc[-1]
    assert "傾角 30.5°" in r and "高度 300 km" in r
    assert "入軌" in a.reasons.iloc[0]       # 首筆入軌未滿 4 天


def test_assess_in_domain_applicable():
    a = assess(_tle(53.0, 480.0), t_first=pd.Timestamp("2026-01-01", tz="UTC"), domain=DOMAIN, use_regime=False)
    assert (a.status == "applicable").all()
    assert (a.reasons == "").all()
