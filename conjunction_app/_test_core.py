# -*- coding: utf-8 -*-
"""
Quick test of non-Streamlit core functions in app.py.
Run:  python conjunction_app/_test_core.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from datetime import datetime, timezone
from sgp4.api import Satrec, jday

R_EARTH_KM = 6378.137
F_EARTH    = 1 / 298.257223563
E2         = F_EARTH * (2 - F_EARTH)
MU_KM3_S2  = 398600.4418


def _gmst_rad(jd, fr):
    T    = ((jd - 2451545.0) + fr) / 36525.0
    gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0 + fr) + 0.000387933 * T**2
    return float(np.deg2rad(gmst % 360.0))


def eci_to_llh(r_eci, t_utc):
    x, y, z = r_eci
    jd_, fr_ = jday(t_utc.year, t_utc.month, t_utc.day,
                    t_utc.hour, t_utc.minute,
                    t_utc.second + t_utc.microsecond * 1e-6)
    g  = _gmst_rad(jd_, fr_)
    xe =  np.cos(g)*x + np.sin(g)*y
    ye = -np.sin(g)*x + np.cos(g)*y
    ze = z
    lon = np.arctan2(ye, xe)
    r   = np.sqrt(xe**2 + ye**2)
    lat = np.arctan2(ze, r*(1-E2))
    alt = 0.0
    for _ in range(5):
        sl  = np.sin(lat); N = R_EARTH_KM/np.sqrt(1-E2*sl**2); cl = np.cos(lat)
        alt = r/cl - N if abs(cl) > 1e-9 else abs(ze)/(1-E2) - N
        lat = np.arctan2(ze, r*(1-E2*(N/(N+alt))))
    return float(np.rad2deg(lat)), float(np.rad2deg(lon)), float(alt)


def observer_ecef(lat_deg, lon_deg, alt_km=0.0):
    lat = np.deg2rad(lat_deg); lon = np.deg2rad(lon_deg)
    sl, cl = np.sin(lat), np.cos(lat)
    N = R_EARTH_KM / np.sqrt(1 - E2*sl**2)
    return np.array([(N+alt_km)*cl*np.cos(lon), (N+alt_km)*cl*np.sin(lon), (N*(1-E2)+alt_km)*sl])


REPO = Path(__file__).resolve().parent.parent
errors = []

# ---------- Test 1: coordinate conversion ----------
print("=== Test 1: eci_to_llh / observer_ecef ===")
try:
    r = np.array([6700., 0., 0.])
    t = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    lat, lon, alt = eci_to_llh(r, t)
    assert abs(alt - (6700 - R_EARTH_KM)) < 20, f"alt={alt}"
    print(f"  eci_to_llh: lat={lat:.2f} lon={lon:.2f} alt={alt:.1f} km  PASS")

    obs = observer_ecef(25.033, 121.565)
    assert abs(np.linalg.norm(obs) - R_EARTH_KM) < 50
    print(f"  observer_ecef: |r|={np.linalg.norm(obs):.1f} km  PASS")
except AssertionError as e:
    print(f"  FAIL: {e}"); errors.append("Test1")

# ---------- Test 2: sat_background dropdown ----------
print("\n=== Test 2: sat_background dropdown labels ===")
try:
    bg_p = REPO / "data" / "tle_parquet" / "sat_background.parquet"
    assert bg_p.exists(), "sat_background.parquet not found"
    bg   = pd.read_parquet(bg_p)
    bg_s = bg.sort_values(["constellation", "sat_name"]).reset_index(drop=True)
    labels = [
        f"{row['constellation']}  >  {row['sat_name']}  (NORAD {int(row['norad_id'])})"
        for _, row in bg_s.iterrows()
    ]
    norads = bg_s["norad_id"].astype(int).tolist()
    assert len(labels) == len(norads) == len(bg_s)
    print(f"  {len(bg)} sats loaded, {len(bg_s['constellation'].unique())} constellations")
    for lbl in labels[:5]:
        print(f"    {lbl}")
    print("  PASS")
except AssertionError as e:
    print(f"  FAIL: {e}"); errors.append("Test2")

# ---------- Test 3: SGP4 propagation ----------
print("\n=== Test 3: SGP4 propagation ===")
try:
    L1 = "1 25544U 98067A   25150.50000000  .00016717  00000-0  10270-3 0  9993"
    L2 = "2 25544  51.6400 208.9163 0006703  86.6816 273.5244 15.49294477 12345"
    sat = Satrec.twoline2rv(L1, L2)
    jd0, fr0 = jday(2025, 5, 30, 0, 0, 0)
    errs, r_ecis, _ = sat.sgp4_array(np.full(10, jd0), fr0 + np.arange(10)/1440.0)
    assert np.all(errs == 0), f"SGP4 errors: {errs}"
    alts = []
    for i, r_eci in enumerate(r_ecis):
        t = datetime(2025, 5, 30, 0, i, 0, tzinfo=timezone.utc)
        _, _, alt = eci_to_llh(r_eci, t)
        alts.append(alt)
    assert 200 < min(alts) < 2000
    print(f"  10 steps OK, alt {min(alts):.0f}-{max(alts):.0f} km  PASS")
except AssertionError as e:
    print(f"  FAIL: {e}"); errors.append("Test3")

# ---------- Test 4: parquet inventory ----------
print("\n=== Test 4: parquet inventory ===")
for fname in ["sat_metadata.parquet", "sat_background.parquet",
              "latest30day_tle.parquet", "conjunction_events.parquet"]:
    p = REPO / "data" / "tle_parquet" / fname
    if p.exists():
        df = pd.read_parquet(p)
        extra = ""
        if "line1" in df.columns:
            extra = f", has line1/line2"
        print(f"  {fname}: {len(df)} rows{extra}  PASS")
    else:
        print(f"  {fname}: NOT FOUND (run build_slim_db.py --latest30day)")

# ---------- Summary ----------
print()
if errors:
    print(f"FAILED: {errors}")
    sys.exit(1)
else:
    print("All core tests passed.")
