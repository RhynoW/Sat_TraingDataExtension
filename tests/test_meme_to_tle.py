# -*- coding: utf-8 -*-
"""tests/test_meme_to_tle.py — regression coverage for starlink_ephemeris/meme_to_tle.py
(differential-correction TLE fit from a MEME precise ephemeris). Uses an offline
fixture (a real, previously-downloaded MEME file for STARLINK-40083, Starship
Flight 14) so this runs without network access; skips cleanly if torch/dsgp4/
astropy aren't installed (meme_to_tle's own optional-dependency contract).

Regression baseline (2026-09-29, session that built this module): fitting this
exact fixture gave B*=4.408e-04 and a held-out validation error of 41.0 km at
+47 h (the worst checkpoint). This test uses a looser bound (150 km) so it
doesn't flake on minor, harmless numerical differences (solver iteration
counts, library versions) while still catching a real regression (e.g. the
EME2000->TEME rotation being dropped, which was empirically ~40x worse).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("torch")
pytest.importorskip("dsgp4")
pytest.importorskip("astropy")

from starlink_ephemeris.meme_to_tle import fit_tle_from_meme  # noqa: E402
from tle_catnr import decode_catnr, encode_catnr  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "meme_starlink_40083_sample.txt"


def test_reserved_v3_catalog_block_roundtrips_through_alpha5():
    # 339974-339999: the block this project reserves for the Flight 14 V3 batch.
    for n in (339974, 339999, 339986):
        assert decode_catnr(encode_catnr(n)) == n
    with pytest.raises(ValueError):
        encode_catnr(340000)  # one past Alpha-5's ceiling


def test_fit_tle_from_meme_end_to_end():
    result = fit_tle_from_meme(
        FIXTURE, sat_name="STARLINK-40083", catalog_number=339974,
        intl_designator="26225A",
    )
    assert result.line1.startswith("1 Z9974U 26225A")
    assert result.line2.startswith("2 Z9974")
    assert len(result.line1) == 69 and len(result.line2) == 69

    # Re-parse with the plain sgp4 engine (the one the dashboard actually runs)
    # to confirm the text itself -- not just the in-memory dsgp4 object -- is valid.
    from sgp4.api import Satrec

    sat = Satrec.twoline2rv(result.line1, result.line2)
    err_code, r, v = sat.sgp4(sat.jdsatepoch, sat.jdsatepochF)
    assert err_code == 0
    assert 6600 < (sum(x * x for x in r) ** 0.5) < 6700   # sane LEO radius, km

    # This satellite is real and decaying (drag-dominated at ~270 km); a
    # meaningful nonzero B* should have been calibrated, not left at 0.
    assert 1e-5 < result.bstar < 1e-2
    assert result.observed_decay_km_day < -0.5   # genuine secular decay, not noise

    assert result.validation_km, "expected at least one held-out validation point"
    assert max(result.validation_km.values()) < 150.0
