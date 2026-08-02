"""
maneuver.py — Impulsive maneuver models (ΔV physics)

支援機動類型
-----------
PROGRADE    順行衝量：增加 SMA（升軌）
RETROGRADE  逆行衝量：降低 SMA（降軌）
NORMAL      法向衝量：增加傾角
ANTINORMAL  反法向：降低傾角
HOHMANN     兩段式 Hohmann 轉移（prograde 在近地點 + 遠地點）
COMBINED    指定 prograde + normal 分量的複合機動
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Optional

import numpy as np

from .elements import MU, OrbitalElements


class ManeuverType(str, Enum):
    PROGRADE   = "prograde"
    RETROGRADE = "retrograde"
    NORMAL     = "normal"
    ANTINORMAL = "antinormal"
    HOHMANN    = "hohmann"
    COMBINED   = "combined"


@dataclass
class ManeuverParams:
    """Parameters for a single impulsive maneuver."""
    maneuver_type:  ManeuverType
    dv_m_s:         float       # Total ΔV magnitude [m/s]
    delta_t_days:   float       # Time after initial epoch when burn occurs
    # For COMBINED only:
    dv_prograde_fraction: float = 1.0   # fraction [0,1] in prograde direction
    # Target SMA for HOHMANN (optional; if None, inferred from dv)
    target_sma_km: Optional[float] = None

    @property
    def dv_km_s(self) -> float:
        return self.dv_m_s / 1000.0


# ─── Physics ─────────────────────────────────────────────────────────────────

def _vis_viva_sma(r_km: float, v_km_s: float) -> float:
    """Semi-major axis from vis-viva equation: a = 1/(2/r - v²/GM)."""
    return 1.0 / (2.0 / r_km - v_km_s**2 / MU)


def _ecc_from_periapsis(r_p: float, a: float) -> float:
    """Eccentricity given periapsis radius and SMA: e = 1 - r_p/a."""
    return max(0.0, abs(1.0 - r_p / a))


def apply_maneuver(
    elements: OrbitalElements,
    params:   ManeuverParams,
) -> OrbitalElements:
    """
    Apply an impulsive maneuver and return post-maneuver elements.

    Assumes the burn occurs at the point on the orbit defined by the
    current mean anomaly (approximately at the current position).
    For near-circular orbits this gives accurate results.
    """
    a  = elements.sma_km
    e  = elements.ecc
    i  = elements.inc_deg
    ra = elements.raan_deg
    ap = elements.argp_deg
    M  = elements.ma_deg

    v_c    = elements.circ_velocity_km_s   # circular orbit speed [km/s]
    dv     = params.dv_km_s                # [km/s]
    mtype  = params.maneuver_type

    # ── Prograde / Retrograde ─────────────────────────────────────────────
    if mtype in (ManeuverType.PROGRADE, ManeuverType.HOHMANN):
        v_new = v_c + dv
        a_new = _vis_viva_sma(a, v_new)
        # Burn point is periapsis of new transfer orbit
        e_new = _ecc_from_periapsis(a, a_new)
        i_new, ra_new = i, ra

    elif mtype == ManeuverType.RETROGRADE:
        v_new = max(v_c - dv, 0.01)   # floor to avoid negative speed
        a_new = _vis_viva_sma(a, v_new)
        e_new = _ecc_from_periapsis(a_new, a)  # burn point is now apoapsis
        i_new, ra_new = i, ra

    # ── Normal / Anti-normal ──────────────────────────────────────────────
    elif mtype == ManeuverType.NORMAL:
        # Out-of-plane ΔV rotates the orbit plane
        # Δi = arctan(ΔV / v_in_plane) ≈ ΔV/v_c for small burns
        di = np.degrees(np.arctan2(dv, v_c))
        a_new, e_new = a, e
        i_new = min(180.0, i + di)
        ra_new = ra

    elif mtype == ManeuverType.ANTINORMAL:
        di = np.degrees(np.arctan2(dv, v_c))
        a_new, e_new = a, e
        i_new = max(0.0, i - di)
        ra_new = ra

    # ── Combined (prograde + normal components) ───────────────────────────
    elif mtype == ManeuverType.COMBINED:
        frac_pro = np.clip(params.dv_prograde_fraction, 0.0, 1.0)
        dv_pro   = dv * frac_pro
        dv_nor   = dv * np.sqrt(1.0 - frac_pro**2)

        v_new = v_c + dv_pro
        a_new = _vis_viva_sma(a, np.sqrt(v_new**2 + dv_nor**2))
        e_new = _ecc_from_periapsis(a, a_new)

        di    = np.degrees(np.arctan2(dv_nor, v_c))
        i_new = min(180.0, max(0.0, i + di))
        ra_new = ra

    else:
        raise ValueError(f"Unknown maneuver type: {mtype}")

    # Circular orbit assumption: reset argp (undefined for e→0),
    # keep mean anomaly at burn point.
    # Epoch stays at the burn time (caller is responsible for propagating
    # elements to the maneuver epoch before calling this function).
    ap_new = ap if e_new > 0.001 else 0.0
    epoch_new = elements.epoch

    return OrbitalElements(
        sma_km   = a_new,
        ecc      = round(e_new, 7),
        inc_deg  = round(i_new, 6),
        raan_deg = round(ra_new % 360.0, 6),
        argp_deg = round(ap_new % 360.0, 6),
        ma_deg   = round(M % 360.0, 6),
        epoch    = epoch_new,
        bstar    = elements.bstar,
        norad_id = elements.norad_id,
    )


def delta_a_km(pre: OrbitalElements, post: OrbitalElements) -> float:
    """Net SMA change [km]."""
    return post.sma_km - pre.sma_km


def delta_i_deg(pre: OrbitalElements, post: OrbitalElements) -> float:
    """Net inclination change [deg]."""
    return post.inc_deg - pre.inc_deg
