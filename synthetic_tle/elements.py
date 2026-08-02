"""
elements.py — OrbitalElements dataclass with J2 propagation
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np

MU  = 398600.4418   # km³/s²
RE  = 6378.137      # km
J2  = 1.08262668e-3


@dataclass
class OrbitalElements:
    """Classical Keplerian orbital elements (osculating)."""
    sma_km:    float       # Semi-major axis [km]
    ecc:       float       # Eccentricity [0, 1)
    inc_deg:   float       # Inclination [deg]
    raan_deg:  float       # Right Ascension of Ascending Node [deg]
    argp_deg:  float       # Argument of perigee [deg]
    ma_deg:    float       # Mean anomaly [deg]
    epoch:     datetime    # Epoch (UTC-aware or naive)
    bstar:     float = 1e-4  # BSTAR drag term [1/RE]
    norad_id:  int   = 99999

    # ── derived properties ──────────────────────────────────────────────────

    @property
    def alt_km(self) -> float:
        return self.sma_km - RE

    @property
    def mean_motion_rad_s(self) -> float:
        return np.sqrt(MU / self.sma_km**3)

    @property
    def mean_motion_rev_day(self) -> float:
        return self.mean_motion_rad_s * 86400.0 / (2.0 * np.pi)

    @property
    def circ_velocity_km_s(self) -> float:
        """Circular orbit speed at SMA (e≈0 approximation)."""
        return np.sqrt(MU / self.sma_km)

    @property
    def orbital_period_s(self) -> float:
        return 2.0 * np.pi / self.mean_motion_rad_s

    # ── J2 propagation ──────────────────────────────────────────────────────

    def propagate(self, days: float) -> "OrbitalElements":
        """
        Propagate forward by `days` using J2-perturbed Keplerian motion.
        Updates RAAN, argp, mean anomaly; SMA, ecc, inc unchanged.
        """
        n      = self.mean_motion_rad_s                # rad/s
        p      = self.sma_km * (1.0 - self.ecc**2)    # semi-latus rectum [km]
        i_rad  = np.radians(self.inc_deg)
        dt_s   = days * 86400.0

        # Secular J2 rates [rad/s]
        coeff  = -1.5 * n * J2 * (RE / p) ** 2
        d_raan = coeff * np.cos(i_rad)
        d_argp = -coeff * (2.5 * np.sin(i_rad)**2 - 2.0)   # = 0.75nJ2(RE/p)²(5cos²i-1)
        d_ma   = n  # Keplerian mean motion (J2 correction ~ 1e-3 × n, omitted)

        new_raan = (self.raan_deg + np.degrees(d_raan * dt_s)) % 360.0
        new_argp = (self.argp_deg + np.degrees(d_argp * dt_s)) % 360.0
        new_ma   = (self.ma_deg   + np.degrees(d_ma   * dt_s)) % 360.0

        return OrbitalElements(
            sma_km   = self.sma_km,
            ecc      = self.ecc,
            inc_deg  = self.inc_deg,
            raan_deg = new_raan,
            argp_deg = new_argp,
            ma_deg   = new_ma,
            epoch    = self.epoch + timedelta(days=days),
            bstar    = self.bstar,
            norad_id = self.norad_id,
        )

    # ── convenience ─────────────────────────────────────────────────────────

    def summary(self) -> dict:
        return {
            "sma_km":  round(self.sma_km, 4),
            "alt_km":  round(self.alt_km, 4),
            "ecc":     round(self.ecc, 7),
            "inc_deg": round(self.inc_deg, 4),
            "raan_deg": round(self.raan_deg, 4),
            "argp_deg": round(self.argp_deg, 4),
            "ma_deg":  round(self.ma_deg, 4),
            "n_rev_day": round(self.mean_motion_rev_day, 8),
            "bstar":   self.bstar,
            "epoch":   self.epoch.isoformat(),
        }
