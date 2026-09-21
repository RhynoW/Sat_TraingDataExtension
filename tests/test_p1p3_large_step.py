"""P1/P3 抑制規則不得擋掉本身已超過 P2 高度門檻的步階（回歸：福衛五號 2026-04-14 −519 m 降軌）。"""
import numpy as np
import pandas as pd

import maneuver_strategies_july as ms


def _series(step_m=None, n=60, step_at=30, alt_km=723.0):
    t0 = pd.Timestamp("2026-04-01", tz="UTC")
    a = ms.R_E + alt_km - 0.0003 * np.arange(n)          # 每 12 h 緩降 0.3 m（阻力衰減）
    if step_m is not None:
        a[step_at:] += step_m / 1000.0
    # 升交點赤經依 J2 進動（否則 draan 殘差會單獨觸發旗標，與本測試無關）
    raan = np.zeros(n)
    raan[0] = 10.0
    for i in range(1, n):
        raan[i] = (raan[i - 1] + ms._j2_raan_deg(a[i - 1], 0.0001, 98.3, 12 * 3600.0)) % 360.0
    return pd.DataFrame({
        "epoch": [t0 + pd.Timedelta(hours=12 * i) for i in range(n)],
        "sma_km": a, "inclination_deg": 98.3, "eccentricity": 0.0001,
        "raan_deg": raan, "bstar": 5e-5})


def _run(df):
    tr = ms.build_transitions(df)
    return tr, ms.apply_strategies(tr, ms.classify_orbit(float(df.sma_km.iloc[-1]), 0.0001, 98.3))


def test_pure_decay_is_not_flagged():
    _, S = _run(_series())
    assert not S["combined"].any()


def test_large_downward_step_survives_suppressors():
    tr, S = _run(_series(step_m=-519.0))
    k = int(np.argmax(np.abs(tr["da_km"].to_numpy())))
    assert abs(tr["da_km"].iloc[k]) * 1000 > 400            # 超過 ≥700 km 帶 P2 門檻 400 m
    assert S["per_strategy"]["P2"][k]
    assert not S["per_strategy"]["P1_suppress"][k]
    assert not S["per_strategy"]["P3_suppress"][k]
    assert S["combined"][k], "−519 m 降軌不應被 P1/P3 當成大氣衰減擋掉"


def test_large_upward_step_still_flagged():
    tr, S = _run(_series(step_m=+519.0))
    k = int(np.argmax(np.abs(tr["da_km"].to_numpy())))
    assert S["combined"][k]
