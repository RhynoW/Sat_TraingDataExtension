"""候選確認式 L3（l3_candidate.py）回歸測試。"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import l3_candidate as C

ROOT = Path(__file__).resolve().parents[1]


def _synthetic(step_m=None, n=700, step_at=400, noise_m=0.4, seed=0):
    """8 h 更新的 ~723 km 低軌：緩降 + 公尺級雜訊，可選一個 step_m 公尺的階躍。"""
    rng = np.random.default_rng(seed)
    t = pd.date_range("2025-01-01", periods=n, freq="8h", tz="UTC")
    a = 7101.0 - 0.0004 * np.arange(n) + rng.normal(0, noise_m / 1000.0, n)
    if step_m is not None:
        a[step_at:] += step_m / 1000.0
    return t, a


def test_to_series_handles_microsecond_epochs():
    """回歸：duckdb 回傳 datetime64[us]，astype('int64')/1e9 曾使 3 h 稀釋把序列砍到只剩幾十點。"""
    t, a = _synthetic()
    df = pd.DataFrame({"epoch": pd.DatetimeIndex(t).as_unit("us"), "sma_km": a})
    tt, aa = C.to_series(df)
    assert len(aa) == len(a)
    assert str(tt.dtype).startswith("datetime64[ns")


def test_signals_match_original_implementation():
    orig = pytest.importorskip("tasa14_l3_fusion")
    t, a = _synthetic(step_m=-519.0)
    t = pd.DatetimeIndex(t).as_unit("ns")
    assert np.allclose(C.signal_ls(t, a), orig.signal_ls(t, a), equal_nan=True)
    assert np.allclose(C.signal_pe(t, a), orig.signal_pe(t, a), equal_nan=True)
    assert np.allclose(C.signal_step(t, a), orig.signal_step(t, a), equal_nan=True)


def test_large_step_yields_high_snr_candidate():
    t, a = _synthetic(step_m=-519.0)
    c = C.build_candidates(pd.DatetimeIndex(t).as_unit("ns"), a)
    assert len(c) > 0
    near = c[(c["epoch"] - t[400]).abs() <= pd.Timedelta(days=1.5)]
    assert len(near) > 0 and near["z_step"].max() > 100, "−519 m 階躍（雜訊 ~0.4 m）的單步 SNR 應遠大於 100"


@pytest.mark.skipif(not (ROOT / "models_fusion" / "l3_altimetry.pkl").exists(), reason="模型檔不存在")
def test_altimetry_model_confirms_large_downward_step():
    """福衛五號 2026-04-14 −519 m 降軌情境：非 Starlink 模型應確認此階躍，且不確認純衰減段。"""
    import joblib
    M = joblib.load(ROOT / "models_fusion" / "l3_altimetry.pkl")
    t, a = _synthetic(step_m=-519.0)
    c = C.build_candidates(pd.DatetimeIndex(t).as_unit("ns"), a)
    theta = M["theta"][C.cadence_class(float(c["cadence_d"].iloc[0]))]
    p = M["clf"].predict_proba(c[M["feats"]])[:, 1]
    near = (c["epoch"] - t[400]).abs() <= pd.Timedelta(days=1.5)
    assert (p[near.to_numpy()] >= theta).any(), "L3 應確認 −519 m 降軌"
    far = ((c["epoch"] - t[400]).abs() > pd.Timedelta(days=15)).to_numpy()
    assert (p[far] >= theta).mean() < 0.5, "純衰減段的多數候選不應被確認"
