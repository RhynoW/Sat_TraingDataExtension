"""
noise.py — TLE observation noise model (calibrated from real TLE uncertainty)

Noise levels are calibrated from empirical TLE vs MEME residuals:
  - LOW   ≈ high-quality satellites (GPS, GNSS), σ_sma ≈ 0.05 km
  - MEDIUM ≈ typical LEO (Starlink 550 km), σ_sma ≈ 0.2 km
  - HIGH  ≈ dense atmosphere / lower orbit (ISS 400 km), σ_sma ≈ 0.5 km
"""
from __future__ import annotations

from dataclasses import replace
from enum import Enum

import numpy as np

from .elements import OrbitalElements


class NoiseLevel(str, Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


# σ table keyed by (noise_level, alt_bin)
# alt_bin: "sub400" | "400-600" | "600plus"
_SIGMA: dict[str, dict[str, dict[str, float]]] = {
    "sub400": {
        "low":    {"sma": 0.15, "ecc": 3e-5, "inc": 0.003, "raan": 0.04, "argp": 0.05, "ma": 0.08},
        "medium": {"sma": 0.40, "ecc": 8e-5, "inc": 0.006, "raan": 0.08, "argp": 0.12, "ma": 0.18},
        "high":   {"sma": 0.80, "ecc": 2e-4, "inc": 0.012, "raan": 0.15, "argp": 0.25, "ma": 0.35},
    },
    "400-600": {
        "low":    {"sma": 0.05, "ecc": 1e-5, "inc": 0.001, "raan": 0.01, "argp": 0.02, "ma": 0.03},
        "medium": {"sma": 0.15, "ecc": 3e-5, "inc": 0.002, "raan": 0.03, "argp": 0.05, "ma": 0.08},
        "high":   {"sma": 0.35, "ecc": 8e-5, "inc": 0.005, "raan": 0.07, "argp": 0.12, "ma": 0.18},
    },
    "600plus": {
        "low":    {"sma": 0.03, "ecc": 5e-6, "inc": 0.0005, "raan": 0.005, "argp": 0.01, "ma": 0.015},
        "medium": {"sma": 0.08, "ecc": 1.5e-5,"inc": 0.001, "raan": 0.015, "argp": 0.03, "ma": 0.04},
        "high":   {"sma": 0.20, "ecc": 4e-5,  "inc": 0.003, "raan": 0.04,  "argp": 0.08, "ma": 0.12},
    },
}


def _alt_bin(alt_km: float) -> str:
    if alt_km < 400:
        return "sub400"
    if alt_km < 600:
        return "400-600"
    return "600plus"


def get_sigma(alt_km: float, level: NoiseLevel) -> dict[str, float]:
    """Return per-element noise std-dev for a given altitude and noise level."""
    return _SIGMA[_alt_bin(alt_km)][level.value]


def add_tle_noise(
    el:    OrbitalElements,
    level: NoiseLevel = NoiseLevel.MEDIUM,
    rng:   np.random.Generator | None = None,
) -> OrbitalElements:
    """
    Return a copy of `el` with Gaussian observational noise added to all
    orbital elements to simulate TLE uncertainty.
    """
    if rng is None:
        rng = np.random.default_rng()

    sigma = get_sigma(el.alt_km, level)

    return OrbitalElements(
        sma_km   = el.sma_km   + rng.normal(0, sigma["sma"]),
        ecc      = max(0.0, el.ecc + rng.normal(0, sigma["ecc"])),
        inc_deg  = np.clip(el.inc_deg + rng.normal(0, sigma["inc"]), 0, 180),
        raan_deg = (el.raan_deg + rng.normal(0, sigma["raan"])) % 360,
        argp_deg = (el.argp_deg + rng.normal(0, sigma["argp"])) % 360,
        ma_deg   = (el.ma_deg   + rng.normal(0, sigma["ma"]))   % 360,
        epoch    = el.epoch,
        bstar    = el.bstar,
        norad_id = el.norad_id,
    )
