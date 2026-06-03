"""
SP3-c / SP3-d parser — multi-GNSS precise orbits.

Supported constellations (SP3 prefix → constellation):
  'E' — Galileo      'G' — GPS
  'C' — BeiDou (BDS) 'R' — GLONASS
  'J' — QZSS

Format reference:
  https://files.igs.org/pub/data/format/sp3d.pdf

Column layout (0-indexed Python slices):
  Record type   : line[0]          ('P' position, 'V' velocity)
  SV identifier : line[1:4]        e.g. 'E01', 'G12'
  X / VX        : line[4:18]       km  / dm s⁻¹
  Y / VY        : line[18:32]
  Z / VZ        : line[32:46]
  Clock/rate    : line[46:60]      µs  / 10⁻⁴ µs s⁻¹

Time system note
----------------
SP3 files use GPS time (no leap seconds).  As of 2024, GPS − UTC = 18 s.
We store epochs as pandas.Timestamp(tz='UTC') where the *numeric values*
represent GPS time, not UTC.  To convert to true UTC subtract 18 s (or use
the leap-second table for historical dates).  The column is named 't_gps'
to make this explicit.
"""
from __future__ import annotations

import gzip
import logging
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, IO

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_EPOCH_RE = re.compile(
    r"^\*\s+(\d{4})\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)"
)

# AC code inferred from filename
_AC_FROM_PREFIX = {
    "COD": "COD", "COM": "COD",
    "GFZ": "GFZ", "GBM": "GFZ",
    "GRG": "GRG", "ESA": "ESA",
    "IAC": "IAC", "SHA": "SHA",
    "TUG": "TUG", "WHU": "WHU",
}

_RESULT_COLS = [
    "sat_id", "t_gps", "x_m", "y_m", "z_m",
    "v_x_mps", "v_y_mps", "v_z_mps",
    "ac", "file_epoch_start", "file_epoch_end",
]


# ── File helpers ───────────────────────────────────────────────────────────────

@contextmanager
def _open_sp3(path: Path) -> Generator[IO[str], None, None]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="ascii", errors="replace") as fh:
            yield fh
    else:
        with open(path, "r", encoding="ascii", errors="replace") as fh:
            yield fh


def _infer_ac(path: Path) -> str:
    prefix = path.name[:3].upper()
    return _AC_FROM_PREFIX.get(prefix, "UNKN")


def _parse_epoch(line: str) -> pd.Timestamp | None:
    m = _EPOCH_RE.match(line)
    if not m:
        return None
    yr, mo, dy, hr, mi = [int(m.group(i)) for i in range(1, 6)]
    sec_f = float(m.group(6))
    sec_i = int(sec_f)
    ns = int(round((sec_f - sec_i) * 1e9))
    return pd.Timestamp(yr, mo, dy, hr, mi, sec_i, nanosecond=ns, tz="UTC")


# ── Main parser ────────────────────────────────────────────────────────────────

def parse_sp3_gnss(sp3_path: Path, constellation: str = "E") -> pd.DataFrame:
    """
    Parse one SP3 file and return epochs for the requested constellation.

    Parameters
    ----------
    sp3_path      : Path to an SP3 or SP3.gz file.
    constellation : Single-character SP3 prefix: 'E'=Galileo, 'C'=BDS,
                    'G'=GPS, 'R'=GLONASS, 'J'=QZSS.  Default 'E'.

    Returns
    -------
    DataFrame with columns:
        sat_id          — e.g. 'C19', 'E11'
        t_gps           — GPS time as pd.Timestamp(tz='UTC')
        x_m, y_m, z_m  — ECEF position in metres
        v_x_mps, ...   — ECEF velocity in m s⁻¹  (NaN when absent)
        ac              — analysis centre, e.g. 'COD', 'GFZ'
        file_epoch_start, file_epoch_end  — coverage window
    """
    sp3_path = Path(sp3_path)
    prefix = constellation[0].upper()
    ac = _infer_ac(sp3_path)

    pos_rows: list[dict] = []
    vel_map: dict[tuple[pd.Timestamp, str], tuple[float, float, float]] = {}

    current_t: pd.Timestamp | None = None
    file_start: pd.Timestamp | None = None
    file_end: pd.Timestamp | None = None

    with _open_sp3(sp3_path) as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line:
                continue

            first = line[0]

            # ── Epoch header ────────────────────────────────────────────────
            if first == "*":
                t = _parse_epoch(line)
                if t is not None:
                    current_t = t
                    if file_start is None:
                        file_start = t
                    file_end = t
                continue

            # ── Position record ─────────────────────────────────────────────
            if first == "P" and len(line) > 3 and line[1] == prefix:
                if current_t is None:
                    continue
                sat_id = line[1:4].strip()
                try:
                    x_km = float(line[4:18])
                    y_km = float(line[18:32])
                    z_km = float(line[32:46])
                except ValueError:
                    continue
                if abs(x_km) > 999_000 or abs(y_km) > 999_000 or abs(z_km) > 999_000:
                    continue
                pos_rows.append({
                    "sat_id": sat_id,
                    "t_gps": current_t,
                    "x_m": x_km * 1_000.0,
                    "y_m": y_km * 1_000.0,
                    "z_m": z_km * 1_000.0,
                })
                continue

            # ── Velocity record ─────────────────────────────────────────────
            if first == "V" and len(line) > 3 and line[1] == prefix:
                if current_t is None:
                    continue
                sat_id = line[1:4].strip()
                try:
                    vx_dms = float(line[4:18])
                    vy_dms = float(line[18:32])
                    vz_dms = float(line[32:46])
                except ValueError:
                    continue
                if abs(vx_dms) > 999_000:
                    continue
                vel_map[(current_t, sat_id)] = (
                    vx_dms * 0.1, vy_dms * 0.1, vz_dms * 0.1,
                )
                continue

            if line.startswith("EOF"):
                break

    if not pos_rows:
        logger.warning("No %s records in %s", prefix, sp3_path.name)
        return pd.DataFrame(columns=_RESULT_COLS)

    df = pd.DataFrame(pos_rows)

    if vel_map:
        vx_vals = np.full(len(df), np.nan)
        vy_vals = np.full(len(df), np.nan)
        vz_vals = np.full(len(df), np.nan)
        for i, row in enumerate(df.itertuples(index=False)):
            v = vel_map.get((row.t_gps, row.sat_id))
            if v:
                vx_vals[i], vy_vals[i], vz_vals[i] = v
        df["v_x_mps"] = vx_vals
        df["v_y_mps"] = vy_vals
        df["v_z_mps"] = vz_vals
    else:
        df["v_x_mps"] = np.nan
        df["v_y_mps"] = np.nan
        df["v_z_mps"] = np.nan

    df["ac"] = ac
    df["file_epoch_start"] = file_start
    df["file_epoch_end"] = file_end

    return df[_RESULT_COLS].reset_index(drop=True)


def parse_sp3_galileo(sp3_path: Path) -> pd.DataFrame:
    """Backward-compatible alias for parse_sp3_gnss(path, constellation='E')."""
    return parse_sp3_gnss(sp3_path, constellation="E")


# ── Optional: ECEF → ECI conversion ───────────────────────────────────────────

def ecef_to_eci_galileo(
    df_ecef: pd.DataFrame,
    method: str = "astropy",
) -> pd.DataFrame:
    """
    Rotate ECEF (ITRF) positions/velocities to ECI (GCRS/J2000).

    Adds columns r_x, r_y, r_z (m) and v_x, v_y, v_z (m s⁻¹) in GCRS.

    Parameters
    ----------
    df_ecef : DataFrame from parse_sp3_galileo.
    method  : 'astropy' (default, high-precision) or 'approx' (fast, ~arcsec).

    Notes
    -----
    The t_gps column holds GPS time stored as UTC timestamps.  This function
    corrects for the 18-second GPS−UTC offset when constructing the rotation.
    """
    df = df_ecef.copy()

    if method == "astropy":
        return _ecef_to_eci_astropy(df)
    elif method == "approx":
        return _ecef_to_eci_approx(df)
    else:
        raise ValueError(f"Unknown method '{method}'. Use 'astropy' or 'approx'.")


_GPS_LEAP = 18  # GPS − UTC in seconds (update if leap seconds are added)


def _ecef_to_eci_astropy(df: pd.DataFrame) -> pd.DataFrame:
    try:
        from astropy.coordinates import ITRS, GCRS, CartesianRepresentation
        from astropy.coordinates import CartesianDifferential
        from astropy import units as u
        from astropy.time import Time
    except ImportError:
        raise ImportError(
            "astropy is required for high-precision ECEF→ECI. "
            "Run: pip install astropy"
        )

    # GPS time → true UTC (subtract leap seconds)
    utc_times = df["t_gps"] - pd.Timedelta(seconds=_GPS_LEAP)
    ap_times = Time(utc_times.values, format="datetime64", scale="utc")

    xyz_m = df[["x_m", "y_m", "z_m"]].values
    has_vel = not df["v_x_mps"].isna().all()

    rx = np.empty(len(df))
    ry = np.empty(len(df))
    rz = np.empty(len(df))
    vx = np.full(len(df), np.nan)
    vy = np.full(len(df), np.nan)
    vz = np.full(len(df), np.nan)

    for i, (t, row) in enumerate(zip(ap_times, df.itertuples(index=False))):
        if has_vel and not np.isnan(row.v_x_mps):
            itrs = ITRS(
                CartesianRepresentation(
                    row.x_m * u.m, row.y_m * u.m, row.z_m * u.m,
                    differentials=CartesianDifferential(
                        row.v_x_mps * u.m / u.s,
                        row.v_y_mps * u.m / u.s,
                        row.v_z_mps * u.m / u.s,
                    ),
                ),
                obstime=t,
            )
            gcrs = itrs.transform_to(GCRS(obstime=t))
            c = gcrs.cartesian
            rx[i] = c.x.to(u.m).value
            ry[i] = c.y.to(u.m).value
            rz[i] = c.z.to(u.m).value
            d = c.differentials["s"]
            vx[i] = d.d_x.to(u.m / u.s).value
            vy[i] = d.d_y.to(u.m / u.s).value
            vz[i] = d.d_z.to(u.m / u.s).value
        else:
            itrs = ITRS(
                CartesianRepresentation(
                    row.x_m * u.m, row.y_m * u.m, row.z_m * u.m
                ),
                obstime=t,
            )
            gcrs = itrs.transform_to(GCRS(obstime=t))
            c = gcrs.cartesian
            rx[i] = c.x.to(u.m).value
            ry[i] = c.y.to(u.m).value
            rz[i] = c.z.to(u.m).value

    df["r_x"] = rx
    df["r_y"] = ry
    df["r_z"] = rz
    df["v_x"] = vx
    df["v_y"] = vy
    df["v_z"] = vz
    return df


def _ecef_to_eci_approx(df: pd.DataFrame) -> pd.DataFrame:
    """
    Approximate ECEF → ECI via Earth rotation angle (GMST).
    Accuracy ~arcsecond; suitable for residual analysis but not precise geodesy.
    """
    utc_ts = df["t_gps"] - pd.Timedelta(seconds=_GPS_LEAP)
    # Julian Date (UT1 ≈ UTC here)
    J2000_OFFSET = 2_451_545.0
    jd = utc_ts.astype("int64") / 1e9 / 86400.0 + 2_440_587.5
    T = (jd - J2000_OFFSET) / 36525.0

    # Greenwich Mean Sidereal Time (degrees)
    gmst_deg = (280.46061837 + 360.98564736629 * (jd - J2000_OFFSET)
                + 0.000387933 * T**2 - T**3 / 38710000.0) % 360.0
    theta = np.deg2rad(gmst_deg)

    ct, st = np.cos(theta), np.sin(theta)
    x = df["x_m"].values
    y = df["y_m"].values
    z = df["z_m"].values

    df["r_x"] = ct * x - st * y
    df["r_y"] = st * x + ct * y
    df["r_z"] = z.copy()

    if not df["v_x_mps"].isna().all():
        omega = 7.292115e-5  # Earth rotation rate rad/s
        vx = df["v_x_mps"].values
        vy = df["v_y_mps"].values
        vz = df["v_z_mps"].values
        df["v_x"] = ct * vx - st * vy - omega * (st * x + ct * y)
        df["v_y"] = st * vx + ct * vy + omega * (ct * x - st * y)
        df["v_z"] = vz.copy()
    else:
        df["v_x"] = np.nan
        df["v_y"] = np.nan
        df["v_z"] = np.nan

    return df
