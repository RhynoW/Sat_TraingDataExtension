"""
formatter.py — Generate TLE strings from OrbitalElements

TLE format reference (69 chars per line, 1-indexed columns):
  Line 1: 1 NNNNNC AAAAAA   YYDDD.DDDDDDDD  s.DDDDDDDD  sXXXXXsD  sXXXXXsD E NNNNS
  Line 2: 2 NNNNN NNN.NNNN NNN.NNNN NNNNNNN NNN.NNNN NNN.NNNN NN.NNNNNNNN NNNNNNS
"""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np

from .elements import OrbitalElements

try:
    from tle_catnr import encode_catnr
except ImportError:  # 套件情境下確保 repo root 可被匯入
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    from tle_catnr import encode_catnr


# ─── Checksum ─────────────────────────────────────────────────────────────────

def _tle_checksum(line68: str) -> int:
    """TLE checksum: sum of digits + 1 per '-', mod 10."""
    total = 0
    for c in line68[:68]:
        if c.isdigit():
            total += int(c)
        elif c == "-":
            total += 1
    return total % 10


# ─── Field formatters ─────────────────────────────────────────────────────────

def _fmt_exp8(value: float) -> str:
    """
    8-char TLE exponential field: sXXXXXsD
    Represents 0.XXXXX × 10^(±D)
    Examples: 5.0e-5 → ' 50000-4', -1.23e-3 → '-12300-2'
    """
    if value == 0.0:
        return " 00000-0"

    sign = " " if value >= 0 else "-"
    v = abs(value)

    # Express as 0.XXXXX × 10^exp  (0.1 ≤ mantissa < 1.0)
    exp = int(math.floor(math.log10(v))) + 1
    mantissa = v / (10.0 ** exp)
    m_int = round(mantissa * 1e5)

    if m_int >= 100000:          # rounding overflow
        m_int //= 10
        exp += 1

    exp_sign = "+" if exp >= 0 else "-"
    return f"{sign}{m_int:05d}{exp_sign}{abs(exp)}"


def _fmt_ndot(value: float) -> str:
    """
    10-char TLE ndot field: s.DDDDDDDD
    First time derivative of mean motion / 2  [rev/day²]
    Example: 4.0e-5 → ' .00004000'
    """
    sign = " " if value >= 0 else "-"
    v    = abs(value)
    s    = f"{v:.8f}"           # e.g. "0.00004000"
    s    = s.lstrip("0") or "0"
    if not s.startswith("."):   # value ≥ 1.0 (unusual)
        s = "." + s.split(".", 1)[1][:8] if "." in s else ".00000000"
    s = (s + "0" * 9)[:9]       # ensure exactly .DDDDDDDD (9 chars)
    return sign + s              # 10 chars


def _epoch_str(epoch: datetime) -> str:
    """YYDDD.DDDDDDDD (14 chars)."""
    yr   = epoch.year % 100
    doy  = epoch.timetuple().tm_yday
    frac = (
        epoch.hour * 3600
        + epoch.minute * 60
        + epoch.second
        + epoch.microsecond / 1e6
    ) / 86400.0
    return f"{yr:02d}{doy + frac:012.8f}"


# ─── Automatic BSTAR from altitude ───────────────────────────────────────────

def _bstar_from_alt(alt_km: float, user_bstar: float | None = None) -> float:
    if user_bstar is not None:
        return user_bstar
    if alt_km < 350:
        return 5e-4
    if alt_km < 500:
        return 1e-4
    if alt_km < 800:
        return 5e-5
    return 1e-5


def _ndot_from_bstar(bstar: float, n_rev_day: float, alt_km: float) -> float:
    """Very rough ndot estimate: higher drag at lower altitudes."""
    if alt_km < 400:
        return 1e-4 * n_rev_day
    if alt_km < 600:
        return 1e-5 * n_rev_day
    return 1e-7 * n_rev_day


# ─── Main formatter ──────────────────────────────────────────────────────────

def format_tle(
    el:        OrbitalElements,
    sat_name:  str  = "SYNTH SAT",
    set_num:   int  = 1,
    rev_num:   int  = 0,
    intl_des:  str  = "26001A  ",  # synthetic international designator
) -> tuple[str, str, str]:
    """
    Return (line0, line1, line2) TLE strings (69 chars each for L1/L2).

    Parameters
    ----------
    el       : OrbitalElements to encode
    sat_name : satellite name (≤24 chars, padded)
    set_num  : element set number (1-9999)
    rev_num  : revolution number at epoch
    intl_des : international designator (8 chars)
    """
    norad  = el.norad_id
    bstar  = _bstar_from_alt(el.alt_km, el.bstar)
    n      = el.mean_motion_rev_day
    ndot1  = _ndot_from_bstar(bstar, n, el.alt_km)
    estr   = _epoch_str(el.epoch)

    # ── Line 0 ───────────────────────────────────────────────────────────
    line0 = sat_name[:24].ljust(24)

    # ── Line 1 (build 68 chars, append checksum) ─────────────────────────
    intl_des8 = (intl_des + "        ")[:8]   # pad/truncate to 8 chars
    line1_68 = (
        f"1 {encode_catnr(norad)}U "
        f"{intl_des8} "
        f"{estr} "
        f"{_fmt_ndot(ndot1)} "
        f"{_fmt_exp8(0.0)} "
        f"{_fmt_exp8(bstar)} "
        f"0 {set_num:4d}"
    )
    # Verify and trim/pad to 68 chars
    if len(line1_68) != 68:
        line1_68 = line1_68.ljust(68)[:68]
    line1 = line1_68 + str(_tle_checksum(line1_68))

    # ── Line 2 ───────────────────────────────────────────────────────────
    # Eccentricity: 7 digits, no decimal point (implied 0.XXXXXXX)
    ecc_str = f"{el.ecc:.7f}"[2:]   # "0.XXXXXXX"[2:] → "XXXXXXX"
    if len(ecc_str) != 7:
        ecc_str = ecc_str.ljust(7, "0")[:7]

    line2_68 = (
        f"2 {encode_catnr(norad)} "
        f"{el.inc_deg:8.4f} "
        f"{el.raan_deg:8.4f} "
        f"{ecc_str} "
        f"{el.argp_deg:8.4f} "
        f"{el.ma_deg:8.4f} "
        f"{n:11.8f}"
        f"{rev_num:5d}"
    )
    if len(line2_68) != 68:
        line2_68 = line2_68.ljust(68)[:68]
    line2 = line2_68 + str(_tle_checksum(line2_68))

    return line0, line1, line2


def tle_to_text(
    tles: list[tuple[str, str, str]],
    header: str = "",
) -> str:
    """Join multiple (line0, line1, line2) tuples into a TLE text block."""
    lines = []
    if header:
        lines.append(f"# {header}")
    for l0, l1, l2 in tles:
        lines.extend([l0, l1, l2])
    return "\n".join(lines)
