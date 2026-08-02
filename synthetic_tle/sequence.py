"""
sequence.py — Generate labeled TLE sequences for ML training

generate_sequence()     : propagate an orbit forward, add noise at each step
generate_training_pair(): create pre + post maneuver sequence
batch_generate()        : generate N labeled samples for the TASA dataset
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .elements import OrbitalElements
from .formatter import format_tle, tle_to_text
from .maneuver import ManeuverParams, ManeuverType, apply_maneuver
from .noise import NoiseLevel, add_tle_noise


# ─── Single sequence ─────────────────────────────────────────────────────────

def generate_sequence(
    start:       OrbitalElements,
    n_tles:      int,
    dt_days:     float = 3.0,
    noise_level: NoiseLevel = NoiseLevel.MEDIUM,
    rng:         np.random.Generator | None = None,
) -> list[OrbitalElements]:
    """
    Propagate `start` forward, generating `n_tles` elements spaced `dt_days`
    apart, each with TLE observational noise added.
    """
    if rng is None:
        rng = np.random.default_rng()

    elements = []
    current = start
    for _ in range(n_tles):
        noisy = add_tle_noise(current, noise_level, rng)
        elements.append(noisy)
        current = current.propagate(dt_days)

    return elements


# ─── Training pair ───────────────────────────────────────────────────────────

def generate_training_pair(
    initial:     OrbitalElements,
    maneuver:    ManeuverParams,
    n_before:    int   = 15,
    n_after:     int   = 15,
    dt_days:     float = 3.0,
    noise_level: NoiseLevel = NoiseLevel.MEDIUM,
    rng:         np.random.Generator | None = None,
) -> tuple[list[OrbitalElements], list[OrbitalElements]]:
    """
    Returns (pre_sequence, post_sequence).

    pre_sequence  : n_before TLEs before the maneuver (no change in orbit)
    post_sequence : n_after  TLEs after the maneuver  (new orbit parameters)

    The maneuver is applied at the propagated state at t = delta_t_days.
    """
    if rng is None:
        rng = np.random.default_rng()

    # Propagate to maneuver point (no noise)
    at_maneuver = initial.propagate(maneuver.delta_t_days)

    # Pre-sequence: propagate backward from maneuver point
    pre_start_days = -(n_before - 1) * dt_days
    pre_start = initial.propagate(maneuver.delta_t_days + pre_start_days)
    pre_seq = generate_sequence(pre_start, n_before, dt_days, noise_level, rng)

    # Apply maneuver; start post-sequence dt_days after burn so the maneuver
    # transition between pre_seq[-1] and post_seq[0] has a nonzero time gap.
    post_initial = apply_maneuver(at_maneuver, maneuver)
    post_seq = generate_sequence(post_initial.propagate(dt_days), n_after, dt_days, noise_level, rng)

    return pre_seq, post_seq


# ─── TLE text output ─────────────────────────────────────────────────────────

def seq_to_tle_text(
    seq:      list[OrbitalElements],
    sat_name: str = "SYNTH SAT",
) -> str:
    """Convert a sequence of OrbitalElements to a TLE text block."""
    tles = [format_tle(el, sat_name=sat_name, set_num=i + 1)
            for i, el in enumerate(seq)]
    return tle_to_text(tles)


# ─── Batch dataset generation ────────────────────────────────────────────────

def _random_orbit(
    rng:        np.random.Generator,
    alt_range:  tuple[float, float] = (400.0, 1200.0),
    inc_range:  tuple[float, float] = (28.0, 98.0),
    epoch_base: datetime | None     = None,
) -> OrbitalElements:
    """Sample a random near-circular LEO orbit."""
    from .elements import RE

    if epoch_base is None:
        epoch_base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    alt     = rng.uniform(*alt_range)
    sma     = RE + alt
    ecc     = rng.uniform(0.0, 0.005)        # near-circular
    inc     = rng.uniform(*inc_range)
    raan    = rng.uniform(0.0, 360.0)
    argp    = rng.uniform(0.0, 360.0)
    ma      = rng.uniform(0.0, 360.0)
    bstar   = 10 ** rng.uniform(-5, -3)     # 1e-5 to 1e-3

    return OrbitalElements(
        sma_km=sma, ecc=ecc, inc_deg=inc, raan_deg=raan,
        argp_deg=argp, ma_deg=ma, epoch=epoch_base, bstar=bstar,
    )


def batch_generate(
    n_maneuver:    int   = 25000,
    n_no_maneuver: int   = 25000,
    dv_range_m_s:  tuple[float, float] = (0.001, 50.0),
    dt_range_days: tuple[float, float] = (7.0, 54.0),
    n_before:      int   = 15,
    n_after:       int   = 15,
    dt_days:       float = 3.0,
    noise_level:   NoiseLevel = NoiseLevel.MEDIUM,
    seed:          int   = 42,
    progress_cb    = None,   # optional callback(pct: float)
) -> pd.DataFrame:
    """
    Generate a labeled training dataset of TLE sequences.

    Returns a DataFrame with one row per satellite:
      norad_id, label (0/1), maneuver_type, dv_m_s, delta_t_days,
      net_da_km, net_di_deg, pre_sma_mean, post_sma_mean,
      plus all pre/post TLE strings serialized as pipe-delimited text.
    """
    rng   = np.random.default_rng(seed)
    rows  = []
    total = n_maneuver + n_no_maneuver

    mtypes = [
        ManeuverType.PROGRADE, ManeuverType.RETROGRADE,
        ManeuverType.NORMAL,   ManeuverType.ANTINORMAL,
        ManeuverType.COMBINED,
    ]
    mweights = [0.35, 0.20, 0.15, 0.10, 0.20]

    base_epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)

    for idx in range(total):
        norad    = 90001 + idx
        is_mnvr  = idx < n_maneuver
        orbit    = _random_orbit(rng, epoch_base=base_epoch)
        orbit    = OrbitalElements(**{**asdict(orbit), "norad_id": norad})

        if is_mnvr:
            mtype  = mtypes[int(rng.choice(len(mtypes), p=mweights))]
            log_dv = rng.uniform(
                np.log10(dv_range_m_s[0]),
                np.log10(dv_range_m_s[1]),
            )
            dv       = float(10 ** log_dv)
            delta_t  = float(rng.uniform(*dt_range_days))
            params   = ManeuverParams(
                maneuver_type = mtype,
                dv_m_s        = dv,
                delta_t_days  = delta_t,
                dv_prograde_fraction = float(rng.uniform(0.5, 1.0)),
            )
            pre_seq, post_seq = generate_training_pair(
                orbit, params, n_before, n_after, dt_days, noise_level, rng
            )
            net_da  = post_seq[0].sma_km - pre_seq[-1].sma_km
            net_di  = post_seq[0].inc_deg - pre_seq[-1].inc_deg
            row = {
                "norad_id":       norad,
                "label":          1,
                "maneuver_type":  mtype.value,
                "dv_m_s":         round(dv, 6),
                "delta_t_days":   round(delta_t, 2),
                "net_da_km":      round(net_da, 4),
                "net_di_deg":     round(net_di, 6),
                "pre_sma_mean":   round(float(np.mean([e.sma_km for e in pre_seq])), 4),
                "post_sma_mean":  round(float(np.mean([e.sma_km for e in post_seq])), 4),
                "alt_km":         round(orbit.alt_km, 1),
                "inc_deg":        round(orbit.inc_deg, 4),
                "pre_tle":        seq_to_tle_text(pre_seq,  f"SYNTH-{norad}"),
                "post_tle":       seq_to_tle_text(post_seq, f"SYNTH-{norad}"),
            }
        else:
            delta_t  = float(rng.uniform(*dt_range_days))
            pre_seq  = generate_sequence(orbit, n_before, dt_days, noise_level, rng)
            mid      = orbit.propagate(delta_t)
            post_seq = generate_sequence(mid, n_after, dt_days, noise_level, rng)
            row = {
                "norad_id":       norad,
                "label":          0,
                "maneuver_type":  "none",
                "dv_m_s":         0.0,
                "delta_t_days":   round(delta_t, 2),
                "net_da_km":      round(post_seq[0].sma_km - pre_seq[-1].sma_km, 4),
                "net_di_deg":     round(post_seq[0].inc_deg - pre_seq[-1].inc_deg, 6),
                "pre_sma_mean":   round(float(np.mean([e.sma_km for e in pre_seq])), 4),
                "post_sma_mean":  round(float(np.mean([e.sma_km for e in post_seq])), 4),
                "alt_km":         round(orbit.alt_km, 1),
                "inc_deg":        round(orbit.inc_deg, 4),
                "pre_tle":        seq_to_tle_text(pre_seq,  f"SYNTH-{norad}"),
                "post_tle":       seq_to_tle_text(post_seq, f"SYNTH-{norad}"),
            }

        rows.append(row)

        if progress_cb and (idx + 1) % 500 == 0:
            progress_cb((idx + 1) / total)

    return pd.DataFrame(rows)
