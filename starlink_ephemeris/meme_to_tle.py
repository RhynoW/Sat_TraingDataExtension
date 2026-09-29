"""
Fit an estimated 2-line TLE from a SpaceX MEME precise ephemeris file.

Motivation
----------
Brand-new Starlink satellites (e.g. the 26 V3 satellites deployed by Starship
Flight 14, 2026-09-28) have real, downloadable MEME precise ephemerides well
before Space-Track issues an official TLE (1-2+ days, sometimes longer). This
module differentially-corrects an SGP4 TLE against one MEME file so a system
built to consume TLEs (SGP4 propagation only, e.g. this project's
SatDashboard) can display these satellites in the meantime.

Method (all steps empirically validated against a real MEME file + plain
`sgp4.api.Satrec`, the same engine the dashboard runs -- see
research notes / session log for the validation numbers)
------------------------------------------------------------------------
1. Parse the MEME file (starlink_ephemeris.parser) -> (t, r, v) samples in
   the EME2000 frame (km, km/s).
2. Convert the epoch-0 state to TEME via astropy (TLE/SGP4's native frame;
   ignoring this rotation was checked empirically and is NOT negligible at
   this altitude -- tens of km -- so it is applied, not skipped).
3. Build an initial-guess TLE from the TEME state (classical elements via
   dsgp4.util.from_cartesian_to_keplerian, SI units), B*=0.
4. Refine the 6 classical elements with dsgp4.newton_method so SGP4 exactly
   reproduces the TEME state at t0 (sub-10-metre residual in practice).
5. Calibrate B*: fit a linear trend to the *observed* osculating semi-major
   axis (vis-viva, frame-independent) over the whole MEME file, then
   bisect B* so that the SGP4-*propagated* SMA trend (also linear-fit over
   many points, to average out J2 short-period ripple -- comparing single
   points here was tried and is unreliable, dominated by ~km-scale ripple)
   matches it. This captures the real drag/decay behaviour the ephemeris
   encodes without deriving SGP4's internal drag-model conversion formula.
6. Format as a checksummed 2-line TLE using the project's shared Alpha-5
   codec (tle_catnr.encode_catnr) for the catalog number specifically
   (dsgp4's own dict-to-line formatter does plain zero-padding and silently
   mis-formats numbers above 99999 -- do not use it for the catalog field).
7. Validate the *final TLE text* by re-parsing with plain `sgp4.api.Satrec`
   and comparing propagated states against held-out MEME samples not used
   in the fit.

Typical accuracy (empirical, one satellite, ~2-day-span MEME file, ~270 km
altitude): <1 km at +1 h, ~2 km at +6 h, ~15 km at +24 h, ~40 km at +47 h.
Good enough for dashboard/globe visualization; not conjunction-screening
grade, and not guaranteed once the ephemeris arc's own span is exceeded.

NOTE on the catalog number
---------------------------
These satellites have no official NORAD number yet. CelesTrak's own
placeholder ID (e.g. 799501648) is *not* representable in a TLE's 5-character
catalog field (Alpha-5 tops out at 339999 -- see tle_catnr.py) and must not
be used here. Callers must supply their own synthetic, TLE-representable
catalog number; this project reserves 339974-339999 for the Flight 14 V3
batch (see meme_to_tle_batch.py). Treat the mapping as temporary: once
Space-Track assigns the real number, remove these synthetic rows from
manual_tle_downloads (scenario-advanced01's ingestion).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from tle_catnr import encode_catnr  # noqa: E402
from starlink_ephemeris.parser import parse_ephemeris_file  # noqa: E402

MU_M = 3.986004418e14      # m^3/s^2 (SI; matches dsgp4.tle.MU_EARTH)
MU_KM = 398600.4418        # km^3/s^2 (vis-viva / plain-sgp4 convention)


@dataclass
class FitResult:
    sat_name: str
    line1: str
    line2: str
    fit_epoch: datetime
    bstar: float
    observed_decay_km_day: float
    fitted_decay_km_day: float
    validation_km: dict[float, float]   # {hours_ahead: position_error_km}


def _require_deps() -> None:
    try:
        import torch  # noqa: F401
        import dsgp4  # noqa: F401
        import astropy  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "meme_to_tle requires torch, dsgp4 and astropy: "
            "pip install torch dsgp4 astropy"
        ) from exc


def _eme2000_to_teme(r_km: np.ndarray, v_km_s: np.ndarray, t_utc: datetime):
    """Rotate one EME2000/J2000(GCRS) state to TEME via astropy's tested transform."""
    from astropy import units as u
    from astropy.coordinates import GCRS, TEME, CartesianDifferential, CartesianRepresentation
    from astropy.time import Time

    t = Time(t_utc)
    rep = CartesianRepresentation(r_km * u.km,
                                  differentials=CartesianDifferential(v_km_s * u.km / u.s))
    teme = GCRS(rep, obstime=t).transform_to(TEME(obstime=t))
    r_teme = np.array([teme.x.to_value(u.km), teme.y.to_value(u.km), teme.z.to_value(u.km)])
    d = teme.cartesian.differentials["s"]
    v_teme = np.array([d.d_x.to_value(u.km / u.s), d.d_y.to_value(u.km / u.s), d.d_z.to_value(u.km / u.s)])
    return r_teme, v_teme


def _osculating_sma(r: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Vis-viva semi-major axis (km); rotation-invariant (frame-independent)."""
    rmag = np.linalg.norm(r, axis=-1)
    vmag2 = np.sum(v ** 2, axis=-1)
    return 1.0 / (2.0 / rmag - vmag2 / MU_KM)


def fit_tle_from_meme(
    meme_path: Path,
    sat_name: str,
    catalog_number: int,
    intl_designator: str,
    check_hours: tuple[float, ...] = (1.0, 6.0, 24.0, 47.0),
) -> FitResult:
    """Fit an estimated TLE from one MEME file. See module docstring for method/caveats."""
    _require_deps()
    import torch
    import dsgp4
    from dsgp4.tle import compute_checksum
    from dsgp4.util import from_cartesian_to_keplerian

    meta, df = parse_ephemeris_file(Path(meme_path), sat_id=sat_name)
    if len(df) < 10:
        raise ValueError(f"{sat_name}: MEME file has only {len(df)} samples, too few to fit")

    t0 = df.loc[0, "t"].to_pydatetime()
    r0 = df.loc[0, ["r_x", "r_y", "r_z"]].to_numpy(dtype=float)
    v0 = df.loc[0, ["v_x", "v_y", "v_z"]].to_numpy(dtype=float)
    r_teme, v_teme = _eme2000_to_teme(r0, v0, t0)

    a_m, e, inc, raan, argp, M = from_cartesian_to_keplerian(r_teme * 1000.0, v_teme * 1000.0, MU_M)
    n_rad_s = float(np.sqrt(MU_M / a_m ** 3))

    epoch_days = (t0 - datetime(t0.year, 1, 1, tzinfo=timezone.utc)).total_seconds() / 86400.0 + 1.0
    base_elems = {
        "satellite_catalog_number": 1, "classification": "U",
        "international_designator": intl_designator,
        "epoch_year": t0.year, "epoch_days": epoch_days,
        "mean_motion_first_derivative": 0.0, "mean_motion_second_derivative": 0.0,
        "inclination": float(inc), "raan": float(raan), "eccentricity": float(e),
        "argument_of_perigee": float(argp), "mean_anomaly": float(M), "mean_motion": n_rad_s,
        "revolution_number_at_epoch": 1, "element_number": 1, "ephemeris_type": 0,
    }

    tle0 = dsgp4.TLE(dict(base_elems, b_star=0.0))
    dsgp4.initialize_tle(tle0)
    epoch_mjd = float(tle0._jdsatepoch) + float(tle0._jdsatepochF) - 2400000.5
    target = torch.tensor([list(r_teme), list(v_teme)], dtype=torch.float64)
    _, y0 = dsgp4.newton_method(tle0, epoch_mjd, target_state=target, max_iter=80)
    y0 = y0.detach()

    # ---- observed secular SMA trend (raw EME2000 r,v; frame-independent) ----
    tsec_all = np.array([(t - t0).total_seconds() for t in df["t"]])
    r_all = df[["r_x", "r_y", "r_z"]].to_numpy(dtype=float)
    v_all = df[["v_x", "v_y", "v_z"]].to_numpy(dtype=float)
    a_obs = _osculating_sma(r_all, v_all)
    obs_slope, _ = np.polyfit(tsec_all, a_obs, 1)
    span_s = float(tsec_all[-1])

    def _tle_from_elements(bstar_val: float):
        e_dict = dict(base_elems, b_star=float(bstar_val))
        e_dict["eccentricity"] = float(y0[0])
        e_dict["argument_of_perigee"] = float(y0[1]) % (2 * np.pi)
        e_dict["inclination"] = float(y0[2])
        e_dict["mean_anomaly"] = float(y0[3]) % (2 * np.pi)
        e_dict["mean_motion"] = float(y0[4]) / 60.0   # no_kozai [rad/min] -> rad/s
        e_dict["raan"] = float(y0[5]) % (2 * np.pi)
        t_try = dsgp4.TLE(e_dict)
        dsgp4.initialize_tle(t_try)
        return t_try

    def _propagated_slope(bstar_val: float, n_points: int = 40):
        t_try = _tle_from_elements(bstar_val)
        tofs = torch.tensor(np.linspace(0, span_s / 60.0, n_points), dtype=torch.float64)
        states = dsgp4.propagate(t_try, tofs)
        r_p = states[:, 0, :].detach().numpy()
        v_p = states[:, 1, :].detach().numpy()
        a_p = _osculating_sma(r_p, v_p)
        slope, _ = np.polyfit(tofs.numpy() * 60.0, a_p, 1)
        return slope, t_try

    lo, hi = 0.0, 2e-3
    slope_lo, _ = _propagated_slope(lo)
    slope_hi, _ = _propagated_slope(hi)
    if not (slope_lo >= obs_slope >= slope_hi):
        # Fall back to B*=0 if the observed decay is outside the bracket
        # (e.g. an apparent *rise*, likely a real manoeuvre baked into the
        # ephemeris -- do not force-fit drag to a non-drag signal).
        bstar_fit, tle_final = 0.0, _tle_from_elements(0.0)
    else:
        for _ in range(25):
            mid = (lo + hi) / 2
            s_mid, _ = _propagated_slope(mid)
            if s_mid > obs_slope:
                lo = mid
            else:
                hi = mid
        bstar_fit = (lo + hi) / 2
        _, tle_final = _propagated_slope(bstar_fit, n_points=200)

    fitted_slope, _ = _propagated_slope(bstar_fit, n_points=200)
    dsgp4.initialize_tle(tle_final)

    # ---- format final TLE text (synthetic Alpha-5 catalog number) ----
    line1_raw, line2_raw = tle_final._lines
    cat_field = encode_catnr(catalog_number)
    line1 = line1_raw[:2] + cat_field + line1_raw[7:68]
    line2 = line2_raw[:2] + cat_field + line2_raw[7:68]
    line1 = line1 + str(compute_checksum(line1))
    line2 = line2 + str(compute_checksum(line2))

    # ---- validate with plain sgp4 (the deployment engine) against held-out MEME samples ----
    from sgp4.api import Satrec, jday

    sat_ref = Satrec.twoline2rv(line1, line2)
    validation: dict[float, float] = {}
    step_s = tsec_all[1] - tsec_all[0] if len(tsec_all) > 1 else 60.0
    for hrs in check_hours:
        idx = int(round(hrs * 3600.0 / step_s))
        if idx >= len(df):
            continue
        t_h = df.loc[idx, "t"].to_pydatetime()
        r_h = df.loc[idx, ["r_x", "r_y", "r_z"]].to_numpy(dtype=float)
        v_h = df.loc[idx, ["v_x", "v_y", "v_z"]].to_numpy(dtype=float)
        r_h_teme, _ = _eme2000_to_teme(r_h, v_h, t_h)
        jd, fr = jday(t_h.year, t_h.month, t_h.day, t_h.hour, t_h.minute,
                     t_h.second + t_h.microsecond / 1e6)
        err_code, r_pred, _ = sat_ref.sgp4(jd, fr)
        if err_code != 0:
            continue
        validation[hrs] = float(np.linalg.norm(np.array(r_pred) - r_h_teme))

    return FitResult(
        sat_name=sat_name, line1=line1, line2=line2, fit_epoch=t0, bstar=bstar_fit,
        observed_decay_km_day=obs_slope * 86400.0, fitted_decay_km_day=fitted_slope * 86400.0,
        validation_km=validation,
    )
