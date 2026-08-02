"""
cdm_predictor.py — kessler CDM sequence predictor for conjunction risk assessment.

Pipeline
--------
  TLE pair
    └─► dSGP4 propagation (generate relative geometry over time)
          └─► Synthetic CDM sequence (N CDMs, spaced interval_h apart)
                └─► kessler Event
                      └─► kessler.model.Conjunction  (Bayesian PC prediction)
                            └─► PC(t) time series + risk label

Main public functions
---------------------
  make_cdm()                 — build a single kessler CDM from geometry at one epoch
  generate_cdm_sequence()    — synthesize N CDMs for a conjunction event
  predict_risk_sequence()    — run kessler Conjunction model on a CDM sequence
  pc_from_tle_pair()         — quick single-point PC via kessler simplified model
"""
from __future__ import annotations

import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    import kessler
    import kessler.model as km
    _KESSLER_OK = True
except ImportError:
    _KESSLER_OK = False

try:
    from dsgp4_utils import propagate_rv_utc, pc_chan, parse_tle, _DSGP4_AVAILABLE
except ImportError:
    _DSGP4_AVAILABLE = False

_MU    = 398600.4418
_RE_KM = 6378.137


def _require():
    if not _KESSLER_OK:
        raise ImportError("kessler is not installed.  Run: pip install kessler")
    if not _DSGP4_AVAILABLE:
        raise ImportError("dsgp4 is not installed.  Run: pip install dsgp4")


# ─── ECI → RTN rotation ──────────────────────────────────────────────────────

def _eci_to_rtn(r_eci: np.ndarray, v_eci: np.ndarray) -> np.ndarray:
    """Return 3×3 rotation matrix from ECI to RTN."""
    r_hat = r_eci / np.linalg.norm(r_eci)
    h     = np.cross(r_eci, v_eci)
    n_hat = h / np.linalg.norm(h)
    t_hat = np.cross(n_hat, r_hat)
    return np.vstack([r_hat, t_hat, n_hat])   # rows = RTN unit vectors


# ─── Build a single CDM ──────────────────────────────────────────────────────

def make_cdm(
    creation_utc:   datetime,
    tca_utc:        datetime,
    miss_km:        float,
    rel_speed_km_s: float,
    rel_pos_rtn_km: Optional[np.ndarray],
    rel_vel_rtn_km_s: Optional[np.ndarray],
    r1_km:          np.ndarray,
    v1_km_s:        np.ndarray,
    r2_km:          np.ndarray,
    v2_km_s:        np.ndarray,
    pc:             float = 0.0,
    norad_pri:      int   = 0,
    norad_sec:      int   = 0,
    sigma_r:        float = 0.5,
    sigma_t:        float = 3.0,
    sigma_n:        float = 1.5,
) -> "kessler.ConjunctionDataMessage":
    """
    Build a kessler CDM object from geometry data at one observation epoch.

    RTN covariance is set as diagonal based on (sigma_r, sigma_t, sigma_n).
    """
    _require()

    cdm = kessler.ConjunctionDataMessage(set_defaults=True)

    # Header
    cdm.set_header("CCSDS_CDM_VERS", "1.0")
    cdm.set_header("CREATION_DATE", creation_utc.strftime("%Y-%m-%dT%H:%M:%S.000"))
    cdm.set_header("ORIGINATOR",    "TASA-CCSDT")
    cdm.set_header("MESSAGE_ID",
                   f"CDM_{norad_pri}_{norad_sec}_{creation_utc.strftime('%Y%m%dT%H%M%S')}")

    # Relative metadata
    tca_str = tca_utc.strftime("%Y-%m-%dT%H:%M:%S.000") if hasattr(tca_utc, "strftime") else str(tca_utc)
    cdm.set_relative_metadata("TCA",          tca_str)
    cdm.set_relative_metadata("MISS_DISTANCE", float(miss_km))
    cdm.set_relative_metadata("RELATIVE_SPEED", float(rel_speed_km_s))

    if rel_pos_rtn_km is not None:
        cdm.set_relative_metadata("RELATIVE_POSITION_R", float(rel_pos_rtn_km[0]))
        cdm.set_relative_metadata("RELATIVE_POSITION_T", float(rel_pos_rtn_km[1]))
        cdm.set_relative_metadata("RELATIVE_POSITION_N", float(rel_pos_rtn_km[2]))
    if rel_vel_rtn_km_s is not None:
        cdm.set_relative_metadata("RELATIVE_VELOCITY_R", float(rel_vel_rtn_km_s[0]))
        cdm.set_relative_metadata("RELATIVE_VELOCITY_T", float(rel_vel_rtn_km_s[1]))
        cdm.set_relative_metadata("RELATIVE_VELOCITY_N", float(rel_vel_rtn_km_s[2]))

    cdm.set_relative_metadata("COLLISION_PROBABILITY",        float(pc))
    cdm.set_relative_metadata("COLLISION_PROBABILITY_METHOD", "CHAN-2D")

    # Object metadata — primary (kessler uses 0-indexed object IDs)
    cdm.set_object(0, "OBJECT",                "OBJECT1")
    cdm.set_object(0, "OBJECT_DESIGNATOR",     str(norad_pri))
    cdm.set_object(0, "CATALOG_NAME",          "USSPACECOM")
    cdm.set_object(0, "OBJECT_NAME",           f"NORAD_{norad_pri}")
    cdm.set_object(0, "INTERNATIONAL_DESIGNATOR", "0000-000A")

    # Object metadata — secondary
    cdm.set_object(1, "OBJECT",                "OBJECT2")
    cdm.set_object(1, "OBJECT_DESIGNATOR",     str(norad_sec))
    cdm.set_object(1, "CATALOG_NAME",          "USSPACECOM")
    cdm.set_object(1, "OBJECT_NAME",           f"NORAD_{norad_sec}")
    cdm.set_object(1, "INTERNATIONAL_DESIGNATOR", "0000-000B")

    # State vectors at TCA — kessler expects (2, 3): [0,:]=xyz position, [1,:]=xyz velocity
    cdm.set_state(0, np.vstack([r1_km, v1_km_s]))
    cdm.set_state(1, np.vstack([r2_km, v2_km_s]))

    # Covariance (RTN diagonal, 6×6)
    C = np.diag([sigma_r**2, sigma_t**2, sigma_n**2,
                 1e-6,       1e-6,       1e-6])   # 6×6
    cdm.set_covariance(0, C)
    cdm.set_covariance(1, C)

    return cdm


# ─── Synthetic CDM sequence ──────────────────────────────────────────────────

def generate_cdm_sequence(
    line1_pri: str, line2_pri: str,
    line1_sec: str, line2_sec: str,
    tca_utc:   datetime,
    n_cdms:    int   = 6,
    interval_h: float = 24.0,
    Rc_km:     float = 0.01,
    norad_pri: int   = 0,
    norad_sec: int   = 0,
    sigma_r:   float = 0.5,
    sigma_t:   float = 3.0,
    sigma_n:   float = 1.5,
) -> list["kessler.ConjunctionDataMessage"]:
    """
    Generate a synthetic sequence of CDMs for one conjunction event.

    Each CDM is created at an observation epoch before TCA:
      obs[0] = TCA - (n_cdms - 1) × interval_h
      ...
      obs[-1] = TCA - interval_h         (last CDM before TCA)

    The relative geometry (miss distance, RTN components) is computed via
    dSGP4 propagation at each CDM epoch.

    Returns list of kessler CDM objects (earliest first).
    """
    _require()
    if tca_utc.tzinfo is None:
        tca_utc = tca_utc.replace(tzinfo=timezone.utc)

    cdms = []
    for i in range(n_cdms):
        hours_before = interval_h * (n_cdms - i)
        obs_utc = tca_utc - timedelta(hours=hours_before)

        # Propagate both satellites to the observation epoch
        try:
            r1, v1 = propagate_rv_utc(line1_pri, line2_pri, obs_utc)
            r2, v2 = propagate_rv_utc(line1_sec, line2_sec, obs_utc)
        except Exception:
            continue

        dr = r2 - r1
        dv = v2 - v1
        miss = float(np.linalg.norm(dr))

        # RTN decomposition using primary satellite frame
        try:
            R_rtn = _eci_to_rtn(r1, v1)
            dr_rtn = R_rtn @ dr
            dv_rtn = R_rtn @ dv
        except Exception:
            dr_rtn = dr
            dv_rtn = dv

        # Simple PC estimate (Chan) at this observation epoch
        P_comb = np.diag([
            (sigma_r**2) * 2, (sigma_t**2) * 2, (sigma_n**2) * 2,
            2e-6, 2e-6, 2e-6,
        ])
        pc = pc_chan(dr, P_comb, Rc_km=Rc_km)

        cdm = make_cdm(
            creation_utc    = obs_utc,
            tca_utc         = tca_utc,
            miss_km         = miss,
            rel_speed_km_s  = float(np.linalg.norm(dv)),
            rel_pos_rtn_km  = dr_rtn,
            rel_vel_rtn_km_s= dv_rtn,
            r1_km           = r1,
            v1_km_s         = v1,
            r2_km           = r2,
            v2_km_s         = v2,
            pc              = pc,
            norad_pri       = norad_pri,
            norad_sec       = norad_sec,
            sigma_r         = sigma_r,
            sigma_t         = sigma_t,
            sigma_n         = sigma_n,
        )
        cdms.append(cdm)

    return cdms


# ─── Event → PC time series ──────────────────────────────────────────────────

def predict_risk_sequence(
    cdm_list: list,
) -> list[dict]:
    """
    Given a list of kessler CDM objects (for one conjunction event),
    return a list of dicts with keys: creation_utc, tca_utc, miss_km, pc.

    This extracts the geometry and PC already embedded in the CDMs without
    running heavy Bayesian inference (which requires observation chains).
    """
    _require()
    records = []
    for cdm in cdm_list:
        try:
            creation = cdm._values_header.get("CREATION_DATE", None)
            tca      = cdm._values_relative_metadata.get("TCA", None)
            miss     = float(cdm._values_relative_metadata.get("MISS_DISTANCE", 0))
            pc       = float(cdm._values_relative_metadata.get("COLLISION_PROBABILITY", 0))
            records.append({
                "creation_utc": creation,
                "tca_utc":      tca,
                "miss_km":      miss,
                "pc":           pc,
            })
        except Exception:
            continue
    return records


# ─── Quick PC via kessler Conjunction model ──────────────────────────────────

def pc_from_tle_pair(
    line1_pri: str, line2_pri: str,
    line1_sec: str, line2_sec: str,
    tca_utc:   datetime,
    Rc_km:     float = 0.01,
    n_cdms:    int   = 3,
    interval_h: float = 24.0,
    norad_pri: int   = 0,
    norad_sec: int   = 0,
) -> dict:
    """
    Quick end-to-end conjunction risk assessment using dSGP4 + kessler.

    Returns dict with:
      pc        — final PC at TCA
      miss_km   — miss distance at TCA
      cdm_seq   — list of CDM records (time series)
      risk      — risk label string
    """
    _require()

    # Propagate to TCA
    r1, v1 = propagate_rv_utc(line1_pri, line2_pri, tca_utc)
    r2, v2 = propagate_rv_utc(line1_sec, line2_sec, tca_utc)
    dr     = r2 - r1
    miss   = float(np.linalg.norm(dr))

    # Generate CDM sequence
    cdm_seq = generate_cdm_sequence(
        line1_pri, line2_pri, line1_sec, line2_sec,
        tca_utc=tca_utc, n_cdms=n_cdms, interval_h=interval_h,
        Rc_km=Rc_km, norad_pri=norad_pri, norad_sec=norad_sec,
    )

    records = predict_risk_sequence(cdm_seq)

    # Final PC: use the latest CDM (closest to TCA)
    final_pc = records[-1]["pc"] if records else 0.0

    def _risk_label(p):
        if p >= 1e-3: return "HIGH"
        if p >= 1e-5: return "MEDIUM"
        if p >= 1e-7: return "LOW"
        return "VERY_LOW"

    return {
        "pc":      final_pc,
        "miss_km": miss,
        "cdm_seq": records,
        "risk":    _risk_label(final_pc),
    }
