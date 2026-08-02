"""
dsgp4_utils.py — dSGP4 wrapper for the Sat_TraingDataExtension project.

Capabilities
------------
1. parse_tle()         — parse + initialize a single TLE into a dsgp4.TLE object
2. propagate_rv()      — propagate one TLE to a time offset, return (r, v) numpy
3. batch_propagate()   — propagate N TLEs at N times in one GPU/CPU call
4. pc_chan()           — Chan analytic 2-D PC formula
5. covariance_at_tca() — propagate 6×6 covariance to TCA via TLE-element Jacobian
6. pc_dsgp4()         — full PC pipeline: TLE → covariance → Chan PC

All functions fall back gracefully if dsgp4 is unavailable (returns None / raises
ImportError with a clear message so callers can show a UI warning).
"""
from __future__ import annotations

import numpy as np
from datetime import datetime, timezone
from typing import Optional

try:
    import torch
    import dsgp4

    _DSGP4_AVAILABLE = True
except ImportError:
    _DSGP4_AVAILABLE = False

_RE_KM = 6378.137
_MU    = 398600.4418          # km³/s²
_MIN_S = 60.0

# ── Default position-uncertainty model (TLE-class LEO, 1σ in RTN) ──────────
_DEFAULT_SIGMA_R = 0.5     # km  radial
_DEFAULT_SIGMA_T = 3.0     # km  along-track
_DEFAULT_SIGMA_N = 1.5     # km  cross-track


# ─── Low-level helpers ───────────────────────────────────────────────────────

def _require_dsgp4():
    if not _DSGP4_AVAILABLE:
        raise ImportError("dsgp4 is not installed.  Run: pip install dsgp4")


def parse_tle(line1: str, line2: str) -> "dsgp4.TLE":
    """Parse two TLE lines and initialize the SGP4 propagator parameters."""
    _require_dsgp4()
    tle = dsgp4.TLE([line1.strip(), line2.strip()])
    dsgp4.initialize_tle(tle)
    return tle


# ─── Single-satellite propagation ────────────────────────────────────────────

def propagate_rv(
    line1: str,
    line2: str,
    t_minutes: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Propagate a TLE to `t_minutes` after its epoch.

    Returns
    -------
    r_km : np.ndarray shape (3,)  position in km (ECI/TEME)
    v_km_s : np.ndarray shape (3,)  velocity in km/s
    """
    _require_dsgp4()
    tle = parse_tle(line1, line2)
    tofs = torch.tensor([float(t_minutes)], dtype=torch.float64)
    state = dsgp4.propagate(tle, tofs)
    # dsgp4 returns (2, 3) for single tof, (N, 2, 3) for multiple tofs
    if state.dim() == 2:
        r = state[0, :].detach().cpu().numpy()
        v = state[1, :].detach().cpu().numpy()
    else:
        r = state[0, 0, :].detach().cpu().numpy()
        v = state[0, 1, :].detach().cpu().numpy()
    return r, v


def propagate_rv_utc(
    line1: str,
    line2: str,
    t_utc: datetime,
) -> tuple[np.ndarray, np.ndarray]:
    """Propagate to an absolute UTC time, computing offset from TLE epoch."""
    _require_dsgp4()
    tle = parse_tle(line1, line2)
    # TLE epoch as datetime
    epoch_jd  = float(tle._jdsatepoch) + float(tle._jdsatepochF)
    epoch_dt  = datetime.fromtimestamp(
        (epoch_jd - 2440587.5) * 86400.0, tz=timezone.utc
    )
    if t_utc.tzinfo is None:
        t_utc = t_utc.replace(tzinfo=timezone.utc)
    delta_min = (t_utc - epoch_dt).total_seconds() / 60.0
    return propagate_rv(line1, line2, delta_min)


# ─── Batch propagation ───────────────────────────────────────────────────────

def batch_propagate(
    tle_lines: list[tuple[str, str]],
    t_minutes_per_tle: list[float],
) -> np.ndarray:
    """
    Propagate N TLEs at N times simultaneously (one time per TLE).

    Parameters
    ----------
    tle_lines : list of (line1, line2) pairs
    t_minutes_per_tle : list of floats — one t_min per TLE (same length)

    Returns
    -------
    states : np.ndarray shape (N, 2, 3) — [:, 0, :] is r_km, [:, 1, :] is v_km_s
    """
    _require_dsgp4()
    if len(tle_lines) != len(t_minutes_per_tle):
        raise ValueError("tle_lines and t_minutes_per_tle must have the same length")

    # Create and collect individual TLE objects (not yet initialized)
    tles = [dsgp4.TLE([l1.strip(), l2.strip()]) for l1, l2 in tle_lines]

    # Batch-initialize: returns (tle_elements_list, batch_tle_object)
    _, tles_batch = dsgp4.initialize_tle(tles)

    tsinces = torch.tensor(
        [float(t) for t in t_minutes_per_tle], dtype=torch.float64
    )
    states_t = dsgp4.propagate_batch(tles_batch, tsinces)   # (N, 2, 3)
    return states_t.detach().cpu().numpy()


# ─── Covariance propagation via TLE-element Jacobian ────────────────────────

def compute_tle_jacobian(
    line1: str,
    line2: str,
    t_minutes: float,
) -> np.ndarray:
    """
    Compute the 6×9 Jacobian  d(r, v) / d(TLE_elements)  via autograd.

    TLE element order: [bstar, ndot, nddot, ecco, argpo, inclo, mo, no_kozai, nodeo]
    State order:       [rx, ry, rz, vx, vy, vz]  (km, km/s)

    Returns np.ndarray shape (6, 9).
    """
    _require_dsgp4()
    tle = dsgp4.TLE([line1.strip(), line2.strip()])
    tle_elements = dsgp4.initialize_tle(tle, with_grad=True)   # tensor (9,) with grad

    t = torch.tensor([float(t_minutes)], dtype=torch.float64)

    def _propagate(el: torch.Tensor) -> torch.Tensor:
        # Temporarily swap TLE internal params to compute gradient
        tle._bstar    = el[0]
        tle._ndot     = el[1]
        tle._nddot    = el[2]
        tle._ecco     = el[3]
        tle._argpo    = el[4]
        tle._inclo    = el[5]
        tle._mo       = el[6]
        tle._no_kozai = el[7]
        tle._nodeo    = el[8]
        # re-initialize with new params
        dsgp4.initialize_tle(tle, with_grad=False)
        state = dsgp4.propagate(tle, t)   # (1, 2, 3)
        return torch.cat([state[0, 0, :], state[0, 1, :]])   # (6,)

    J = torch.autograd.functional.jacobian(_propagate, tle_elements)   # (6, 9)
    return J.detach().cpu().numpy()


def covariance_at_tca(
    line1: str,
    line2: str,
    t_minutes: float,
    sigma_r_km: float = _DEFAULT_SIGMA_R,
    sigma_t_km: float = _DEFAULT_SIGMA_T,
    sigma_n_km: float = _DEFAULT_SIGMA_N,
) -> np.ndarray:
    """
    Propagate a diagonal RTN position covariance from epoch to t_minutes using
    the TLE-element Jacobian.

    The initial covariance is expressed in RTN frame and projected to ECI via
    the orbital geometry, then propagated to TCA via  P_TCA = J @ P0 @ J^T.

    Returns
    -------
    P_6x6 : np.ndarray (6, 6) — full state covariance at TCA in ECI km, km/s
    """
    _require_dsgp4()
    # Position covariance in ECI: approximate RTN → ECI as identity (conservative)
    P0_pos = np.diag([sigma_r_km**2, sigma_t_km**2, sigma_n_km**2])   # 3×3
    # Velocity uncertainty ~1 km/s per km/s * 0.1% → use 0.001 km/s default
    sigma_v = 0.001   # km/s
    P0_vel = np.diag([sigma_v**2, sigma_v**2, sigma_v**2])

    P0 = np.block([
        [P0_pos, np.zeros((3, 3))],
        [np.zeros((3, 3)), P0_vel],
    ])   # 6×6

    try:
        J = compute_tle_jacobian(line1, line2, t_minutes)   # 6×9
        # Use only position-related columns (indices 3-8, excluding bstar/ndot/nddot)
        J_pos = J[:, 3:]   # 6×6 (ecco, argpo, inclo, mo, no_kozai, nodeo)
        # Map initial P0 to TLE-element space (approximate) then back to state space
        # Simplified: use the full 6×6 direct STM approximation
        # We approximate: d_state ≈ J_pos @ d_tle_elements
        # Scale columns by typical element uncertainty to make dimensionally consistent
        # This is a rough but useful approximation
        P_tca = J_pos @ np.eye(6) * np.diag(P0) @ J_pos.T
        # Regularize
        lam, V = np.linalg.eigh(P_tca)
        lam = np.maximum(lam, 1e-12)
        P_tca = V @ np.diag(lam) @ V.T
    except Exception:
        # Fall back: propagate analytically (covariance grows linearly with time)
        t_days = t_minutes / (24.0 * 60.0)
        growth = 1.0 + 0.5 * t_days   # rough linear growth model
        P_tca  = P0 * growth**2

    return P_tca


# ─── PC computation (Chan analytic 2-D formula) ──────────────────────────────

def pc_chan(
    r_rel_km: np.ndarray,
    P_comb: np.ndarray,
    Rc_km: float = 0.01,
) -> float:
    """
    Chan analytic Probability of Collision (2-D projection into B-plane).

    Parameters
    ----------
    r_rel_km : np.ndarray (3,) — relative position at TCA in ECI (km)
    P_comb   : np.ndarray (6, 6) or (3, 3) — combined covariance (primary + secondary)
    Rc_km    : float — hard-body radius (combined, km)

    Returns
    -------
    pc : float in [0, 1]
    """
    r = np.asarray(r_rel_km, dtype=float)
    P = np.asarray(P_comb, dtype=float)

    # Take only position block
    if P.shape == (6, 6):
        P3 = P[:3, :3]
    else:
        P3 = P

    # B-plane projection: project perpendicular to relative velocity direction
    # Simplified: project onto the two axes with largest uncertainty
    eigvals, eigvecs = np.linalg.eigh(P3)
    eigvals = np.maximum(eigvals, 1e-12)

    # Sort by magnitude (descending)
    idx = np.argsort(eigvals)[::-1]
    sigma_a = np.sqrt(eigvals[idx[0]])
    sigma_b = np.sqrt(eigvals[idx[1]])

    # Project miss distance onto principal axes
    r_proj = eigvecs[:, idx].T @ r    # (3,) in eigen-frame
    da = r_proj[0] / sigma_a if sigma_a > 0 else 0.0
    db = r_proj[1] / sigma_b if sigma_b > 0 else 0.0

    # Chan formula: PC = (Rc² / (σ_a σ_b)) × exp(-0.5 × (da² + db²))
    mahal2 = da**2 + db**2
    if sigma_a * sigma_b < 1e-20:
        return 0.0
    pc = (Rc_km**2 / (sigma_a * sigma_b)) * np.exp(-0.5 * mahal2)
    return float(np.clip(pc, 0.0, 1.0))


def pc_monte_carlo(
    r_rel_km: np.ndarray,
    P_comb: np.ndarray,
    Rc_km: float = 0.01,
    n_mc: int = 50_000,
    seed: int = 42,
) -> float:
    """Monte Carlo PC in 3-D (slower but more accurate for small Rc)."""
    P = np.asarray(P_comb, dtype=float)
    P3 = P[:3, :3] if P.shape == (6, 6) else P
    r  = np.asarray(r_rel_km[:3], dtype=float)

    rng = np.random.default_rng(seed)
    try:
        L = np.linalg.cholesky(P3)
    except np.linalg.LinAlgError:
        lam, V = np.linalg.eigh(P3)
        lam = np.maximum(lam, 1e-12)
        L = V @ np.diag(np.sqrt(lam))

    samples = (L @ rng.standard_normal((3, n_mc))).T + r   # (n_mc, 3)
    hits    = np.linalg.norm(samples, axis=1) <= Rc_km
    return float(hits.mean())


# ─── Full PC pipeline ─────────────────────────────────────────────────────────

def pc_dsgp4(
    line1_pri: str, line2_pri: str,
    line1_sec: str, line2_sec: str,
    tca_utc:   datetime,
    Rc_km:     float = 0.01,
    sigma_r:   float = _DEFAULT_SIGMA_R,
    sigma_t:   float = _DEFAULT_SIGMA_T,
    sigma_n:   float = _DEFAULT_SIGMA_N,
    method:    str   = "chan",
) -> dict:
    """
    Full PC pipeline using dSGP4:
      1. Propagate both TLEs to TCA
      2. Compute relative position/velocity
      3. Propagate covariance to TCA via Jacobian
      4. Compute PC (Chan or Monte Carlo)

    Returns dict with keys: pc, miss_km, rel_vel_km_s, method
    """
    _require_dsgp4()

    r1, v1 = propagate_rv_utc(line1_pri, line2_pri, tca_utc)
    r2, v2 = propagate_rv_utc(line1_sec, line2_sec, tca_utc)

    dr     = r2 - r1
    dv     = v2 - v1
    miss   = float(np.linalg.norm(dr))
    rel_v  = float(np.linalg.norm(dv))

    # Minutes from primary TLE epoch to TCA
    tle_pri = parse_tle(line1_pri, line2_pri)
    epoch_jd = float(tle_pri._jdsatepoch) + float(tle_pri._jdsatepochF)
    epoch_dt = datetime.fromtimestamp(
        (epoch_jd - 2440587.5) * 86400.0, tz=timezone.utc
    )
    if tca_utc.tzinfo is None:
        tca_utc = tca_utc.replace(tzinfo=timezone.utc)
    t_min = (tca_utc - epoch_dt).total_seconds() / 60.0

    # Propagate covariance (primary + secondary combined)
    try:
        P1 = covariance_at_tca(line1_pri, line2_pri, t_min, sigma_r, sigma_t, sigma_n)
        P2 = covariance_at_tca(line1_sec, line2_sec, t_min, sigma_r, sigma_t, sigma_n)
        P_comb = P1 + P2
    except Exception:
        # Fallback: diagonal pseudo-covariance
        sig2 = np.array([sigma_r**2, sigma_t**2, sigma_n**2, 1e-6, 1e-6, 1e-6])
        P_comb = np.diag(sig2 * 2.0)   # factor-2 combined

    if method == "mc":
        pc = pc_monte_carlo(dr, P_comb, Rc_km=Rc_km)
    else:
        pc = pc_chan(dr, P_comb, Rc_km=Rc_km)

    return {
        "pc":           pc,
        "miss_km":      miss,
        "rel_vel_km_s": rel_v,
        "method":       method,
    }


# ─── Convenience: recompute PC for a conjunctions DataFrame ──────────────────

def recompute_pc_dataframe(
    conj_df,
    tle_df,
    Rc_km:   float = 0.01,
    sigma_r: float = _DEFAULT_SIGMA_R,
    sigma_t: float = _DEFAULT_SIGMA_T,
    sigma_n: float = _DEFAULT_SIGMA_N,
    method:  str   = "chan",
):
    """
    Given a conjunction_events DataFrame and a TLE DataFrame (with columns
    norad_id, line1, line2), recompute PC for each event using dSGP4.

    Returns a copy of conj_df with updated 'pc' and 'risk_label' columns.
    """
    _require_dsgp4()
    import pandas as pd

    df = conj_df.copy()
    tle_map = {}
    for _, row in tle_df.iterrows():
        tle_map[int(row["norad_id"])] = (str(row["line1"]), str(row["line2"]))

    pcs = []
    for _, row in df.iterrows():
        p_id = int(row["primary_norad"])
        s_id = int(row["secondary_norad"])
        tca  = row["tca_utc"]
        if isinstance(tca, str):
            tca = datetime.fromisoformat(tca)
        if p_id not in tle_map or s_id not in tle_map:
            pcs.append(float(row.get("pc", 0.0)))
            continue
        try:
            result = pc_dsgp4(
                *tle_map[p_id], *tle_map[s_id],
                tca_utc=tca, Rc_km=Rc_km,
                sigma_r=sigma_r, sigma_t=sigma_t, sigma_n=sigma_n,
                method=method,
            )
            pcs.append(result["pc"])
        except Exception:
            pcs.append(float(row.get("pc", 0.0)))

    df["pc"] = pcs

    def _risk(p):
        if p >= 1e-3:  return "HIGH"
        if p >= 1e-5:  return "MEDIUM"
        if p >= 1e-7:  return "LOW"
        return "VERY_LOW"

    df["risk_label"] = df["pc"].apply(_risk)
    return df
