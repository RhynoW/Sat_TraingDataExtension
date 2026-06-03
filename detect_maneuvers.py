#!/usr/bin/env python3
"""
Detect potential orbital maneuvers from Starlink MEME ephemeris data.

Algorithm
---------
For each satellite directory under data/raw/{sat_name}/, extract the first
state vector of every .txt file.  Each such vector (r, v) in EME2000 is the
orbital state when SpaceX regenerated the ephemeris (~every 8 hours).  Any
burn between two consecutive regeneration epochs shifts the orbital elements
in a way that cannot be explained by natural perturbations alone.

Validated indicators (between consecutive snapshot epochs t_k -> t_{k+1}):
  da_km        km   semi-major axis change (in-plane altitude burn)
  di_deg       deg  inclination change (out-of-plane burn)
  de                eccentricity change (orbit shaping)
  draan_res_deg deg RAAN residual after J2 secular drift correction
  dv_est_ms    m/s  estimated delta-V from da (Hohmann approximation)

Note on argument of perigee (omega):
  All Starlink satellites have e < 0.005 (near-circular), making omega
  ill-conditioned.  We use the argument of latitude u = omega + nu instead.

Validation results (from 284 real satellites, 1966 transitions):
  J2 RAAN correction: residual std = 0.021 deg on quiet transitions (100%
  within 0.1 deg) -- confirms correction is accurate.
  All satellites have e < 0.005, confirming omega is unreliable.

Inclination families detected:
  53-deg shell  226 sats   (main Starlink LEO constellation)
  mid-inc        28 sats   (53-85 deg, Gen2 and transitions)
  SSO            31 sats   (97-deg, polar Starlink)

Usage
-----
  python detect_maneuvers.py
  python detect_maneuvers.py --data-root data --out-dir data/maneuvers
  python detect_maneuvers.py --no-plot
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ── physical constants ────────────────────────────────────────────────────────
MU  = 398_600.4418    # km3/s2  WGS84 Earth GM
R_E = 6_378.137       # km      WGS84 equatorial radius
J2  = 1.082_63e-3     # J2 zonal harmonic

# ── maneuver flag thresholds ──────────────────────────────────────────────────
THR_DA_SM  = 1.0      # km   small maneuver
THR_DA_MD  = 5.0      # km   medium maneuver
THR_DA_LG  = 10.0     # km   large maneuver (orbit-raising / deorbit)
THR_DI     = 0.02     # deg  inclination change threshold
THR_DE     = 0.001    # -    eccentricity change threshold
THR_DRAAN  = 0.1      # deg  J2-corrected RAAN residual (validated noise floor ~0.021 deg)

# ── satellites to exclude (test / dummy data) ────────────────────────────────
_EXCLUDE = {"STARLINK-DEMO"}

# ── logger ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("maneuver")

# ── compiled regex for first data line of MEME file ──────────────────────────
_FLOAT = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
_DATA_FULL_RE = re.compile(
    r"^(\d{4})(\d{3})(\d{2})(\d{2})(\d{2}\.\d+)"
    r"\s+(" + _FLOAT + r")"
    r"\s+(" + _FLOAT + r")"
    r"\s+(" + _FLOAT + r")"
    r"\s+(" + _FLOAT + r")"
    r"\s+(" + _FLOAT + r")"
    r"\s+(" + _FLOAT + r")"
)


# ── fast first-state extractor ────────────────────────────────────────────────

def extract_first_state(path: Path) -> dict | None:
    """
    Read only the first data line of a MEME file.
    Returns dict with keys: t, r_x, r_y, r_z, v_x, v_y, v_z or None.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _DATA_FULL_RE.match(line.strip())
                if m:
                    yr, doy, hh, mm = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                    ss_f = float(m.group(5))
                    ss_i = int(ss_f)
                    us   = round((ss_f - ss_i) * 1_000_000)
                    t = (
                        pd.Timestamp(yr, 1, 1, tzinfo=timezone.utc)
                        + pd.Timedelta(days=doy - 1)
                        + pd.Timedelta(hours=hh, minutes=mm, seconds=ss_i, microseconds=us)
                    )
                    return {
                        "t":   t,
                        "r_x": float(m.group(6)),  "r_y": float(m.group(7)),  "r_z": float(m.group(8)),
                        "v_x": float(m.group(9)),  "v_y": float(m.group(10)), "v_z": float(m.group(11)),
                    }
    except Exception as exc:
        log.warning("Cannot read %s: %s", path.name, exc)
    return None


# ── orbital mechanics ─────────────────────────────────────────────────────────

def state_to_elements(rx: float, ry: float, rz: float,
                      vx: float, vy: float, vz: float) -> dict:
    """
    Convert EME2000 state vector (km, km/s) to Keplerian elements.

    Returns: a (km), e, i (deg), raan (deg), u (deg = omega+nu, argument of
    latitude -- preferred over omega for near-circular orbits).

    Note: omega is omitted because e < 0.005 for all Starlink satellites,
    making omega ill-conditioned.
    """
    r = np.array([rx, ry, rz])
    v = np.array([vx, vy, vz])
    r_mag = np.linalg.norm(r)
    v_mag = np.linalg.norm(v)

    eps   = v_mag**2 / 2 - MU / r_mag
    a     = -MU / (2 * eps)

    h     = np.cross(r, v)
    h_mag = np.linalg.norm(h)
    i_rad = np.arccos(np.clip(h[2] / h_mag, -1, 1))

    K = np.array([0.0, 0.0, 1.0])
    N = np.cross(K, h)
    N_mag = np.linalg.norm(N)

    if N_mag < 1e-10:
        raan_rad = 0.0
    else:
        raan_rad = np.arccos(np.clip(N[0] / N_mag, -1, 1))
        if N[1] < 0:
            raan_rad = 2 * np.pi - raan_rad

    e_vec = np.cross(v, h) / MU - r / r_mag
    e     = np.linalg.norm(e_vec)

    # Argument of perigee (omega) -- needed only to compute u = omega + nu
    if N_mag < 1e-10 or e < 1e-12:
        omega_rad = 0.0
    else:
        omega_rad = np.arccos(np.clip(np.dot(N, e_vec) / (N_mag * e), -1, 1))
        if e_vec[2] < 0:
            omega_rad = 2 * np.pi - omega_rad

    r_dot_v = np.dot(r, v)
    if e < 1e-12:
        nu_rad = 0.0
    else:
        nu_rad = np.arccos(np.clip(np.dot(e_vec, r) / (e * r_mag), -1, 1))
        if r_dot_v < 0:
            nu_rad = 2 * np.pi - nu_rad

    # Argument of latitude u = omega + nu (well-defined even for e -> 0)
    u_rad = (omega_rad + nu_rad) % (2 * np.pi)

    return {
        "a":    a,
        "e":    e,
        "i":    np.degrees(i_rad),
        "raan": np.degrees(raan_rad),
        "u":    np.degrees(u_rad),
    }


def j2_raan_rate_deg_per_s(a: float, e: float, i_deg: float) -> float:
    """Secular J2 RAAN precession rate (deg/s)."""
    i = np.radians(i_deg)
    n = np.sqrt(MU / a**3)
    p = a * (1 - e**2)
    return np.degrees(-1.5 * n * J2 * (R_E / p)**2 * np.cos(i))


def dv_from_da(a: float, da: float) -> float:
    """
    Estimate |delta-V| (m/s) from a semi-major axis change da (km).
    Hohmann small-burn approximation for circular orbit: dV = (v_c/2a)|da|.
    NOTE: summing over multiple transitions overestimates total mission dV
    because oscillating phasing burns partially cancel.
    """
    return abs(0.5 * np.sqrt(MU / a) / a * da) * 1000  # m/s


def angle_diff(a1: float, a2: float) -> float:
    """Signed difference a2 - a1 wrapped to (-180, +180]."""
    d = (a2 - a1) % 360
    return d - 360 if d > 180 else d


def inc_family(i_deg: float) -> str:
    """Classify inclination into Starlink shell family."""
    if i_deg < 55:
        return "53deg"
    if i_deg < 85:
        return "mid-inc"
    return "SSO"


def da_severity(da_km: float) -> str:
    """Label maneuver magnitude."""
    a = abs(da_km)
    if a < THR_DA_SM:
        return "none"
    if a < THR_DA_MD:
        return "small"
    if a < THR_DA_LG:
        return "medium"
    return "large"


# ── per-satellite analysis ────────────────────────────────────────────────────

def classify_pattern(da_vals: np.ndarray) -> str:
    """
    Classify the da pattern across a satellite's transitions.

    stable   -- |da| consistently small (no significant maneuvers)
    phasing  -- da alternates sign >=65% of the time (Hohmann slot-keeping)
    raising  -- net altitude gain > THR_DA_MD, mostly positive da burns
    lowering -- net altitude loss > THR_DA_MD, mostly negative da burns
    mixed    -- active but pattern doesn't fit the above categories
    """
    n = len(da_vals)
    if n < 2:
        return "unknown"
    abs_mean = np.abs(da_vals).mean()
    if abs_mean < THR_DA_SM:
        return "stable"
    sign_changes = sum(1 for i in range(n - 1)
                       if np.sign(da_vals[i]) != np.sign(da_vals[i + 1]))
    net = da_vals.sum()
    frac_pos = (da_vals > 0).sum() / n
    if sign_changes >= (n - 1) * 0.65:       # >=65% of transitions flip sign
        return "phasing"
    if net > THR_DA_MD and frac_pos > 0.65:
        return "raising"
    if net < -THR_DA_MD and frac_pos < 0.35:
        return "lowering"
    return "mixed"


def analyze_satellite(sat_name: str, sat_dir: Path) -> pd.DataFrame:
    """
    For one satellite, extract first-state snapshots and compute inter-epoch
    deltas.  Returns a DataFrame of transitions; empty if < 2 valid snapshots.
    """
    txt_files = sorted(
        [p for p in sat_dir.glob("*.txt") if not p.name.startswith("_")],
        key=lambda p: p.name,
    )
    if len(txt_files) < 2:
        return pd.DataFrame()

    snapshots = []
    for f in txt_files:
        s = extract_first_state(f)
        if s is not None:
            elems = state_to_elements(s["r_x"], s["r_y"], s["r_z"],
                                      s["v_x"], s["v_y"], s["v_z"])
            snapshots.append({**s, **elems})

    if len(snapshots) < 2:
        return pd.DataFrame()

    da_arr = np.array([snapshots[k+1]["a"] - snapshots[k]["a"]
                       for k in range(len(snapshots) - 1)])
    pattern = classify_pattern(da_arr)

    rows = []
    for k in range(len(snapshots) - 1):
        s1, s2 = snapshots[k], snapshots[k + 1]
        dt_s = (s2["t"] - s1["t"]).total_seconds()
        dt_h = dt_s / 3600.0

        a_ref = 0.5 * (s1["a"] + s2["a"])
        e_ref = 0.5 * (s1["e"] + s2["e"])
        i_ref = 0.5 * (s1["i"] + s2["i"])

        j2_raan_deg = j2_raan_rate_deg_per_s(a_ref, e_ref, i_ref) * dt_s

        da        = s2["a"]    - s1["a"]
        de        = s2["e"]    - s1["e"]
        di        = s2["i"]    - s1["i"]
        draan_raw = angle_diff(s1["raan"], s2["raan"])
        draan_res = draan_raw - j2_raan_deg
        du        = angle_diff(s1["u"],    s2["u"])
        dv_est    = dv_from_da(s1["a"], da)

        # Flagging (RAAN residual threshold raised to validated noise floor)
        flags = []
        sev = da_severity(da)
        if sev != "none":                 flags.append(f"da={da:+.2f}km[{sev}]")
        if abs(di) > THR_DI:              flags.append(f"di={di:+.4f}deg")
        if abs(de) > THR_DE:              flags.append(f"de={de:+.5f}")
        if abs(draan_res) > THR_DRAAN:    flags.append(f"dOmega_res={draan_res:+.3f}deg")

        rows.append({
            "sat_name":       sat_name,
            "inc_family":     inc_family(s1["i"]),
            "maneuver_class": pattern,
            "t_from":         s1["t"],
            "t_to":           s2["t"],
            "dt_h":           round(dt_h, 2),
            # orbital state at t_from
            "a_km":           round(s1["a"], 3),
            "alt_km":         round(s1["a"] - R_E, 2),
            "e":              round(s1["e"], 6),
            "i_deg":          round(s1["i"], 4),
            "raan_deg":       round(s1["raan"], 4),
            "u_deg":          round(s1["u"], 4),
            # deltas
            "da_km":          round(da, 4),
            "de":             round(de, 6),
            "di_deg":         round(di, 5),
            "draan_raw_deg":  round(draan_raw, 4),
            "draan_j2_deg":   round(j2_raan_deg, 4),
            "draan_res_deg":  round(draan_res, 4),
            "du_deg":         round(du, 4),
            "da_severity":    sev,
            "dv_est_ms":      round(dv_est, 3),
            "flagged":        len(flags) > 0,
            "flag_reason":    " | ".join(flags) if flags else "",
        })

    return pd.DataFrame(rows)


# ── plotting ──────────────────────────────────────────────────────────────────

def plot_results(trans: pd.DataFrame, out_dir: Path, date_tag: str) -> None:
    try:
        plt.style.use("seaborn-v0_8-whitegrid")
    except OSError:
        pass

    plots_dir = out_dir / "plots"
    plots_dir.mkdir(exist_ok=True)

    fam_colors = {"53deg": "steelblue", "mid-inc": "darkorange", "SSO": "mediumpurple"}
    cls_colors = {"raising": "tab:green", "lowering": "tab:red",
                  "phasing": "tab:purple", "mixed": "tab:gray", "stable": "tab:blue"}

    # ── Fig 1: da and di distributions by inclination family ─────────────────
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f"Maneuver Indicator Distributions  ({date_tag})", fontsize=13)

    for ax, col, label, thr, unit in [
        (axes[0, 0], "da_km",       "da (km)",              THR_DA_SM, "km"),
        (axes[0, 1], "di_deg",      "di (deg)",             THR_DI,    "deg"),
        (axes[1, 0], "draan_res_deg","dOmega residual (deg)",THR_DRAAN, "deg"),
        (axes[1, 1], "dv_est_ms",   "dV estimate (m/s)",    None,      "m/s"),
    ]:
        for fam, col_color in fam_colors.items():
            sub = trans[trans["inc_family"] == fam][col]
            if col == "dv_est_ms":
                sub = sub[sub < 20]
            ax.hist(sub, bins=60, color=col_color, alpha=0.55,
                    edgecolor="none", label=fam)
        if thr is not None:
            ax.axvline( thr, color="tomato", linestyle="--", linewidth=1.0)
            ax.axvline(-thr, color="tomato", linestyle="--", linewidth=1.0)
        ax.set_xlabel(label)
        ax.set_ylabel("Count")
        ax.set_title(label)
        ax.legend(fontsize=8)

    fig.tight_layout()
    p = plots_dir / f"maneuver_distributions_{date_tag}.png"
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Distributions -> %s", p)

    # ── Fig 2: Altitude trajectories by maneuver class ───────────────────────
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle(f"Altitude Trajectories by Maneuver Class  ({date_tag})", fontsize=13)
    class_order = [
        ("raising",  "Orbit-Raising"),
        ("lowering", "Orbit-Lowering"),
        ("phasing",  "Phasing"),
        ("mixed",    "Mixed / Complex"),
    ]
    for ax, (cls, title) in zip(axes.flat, class_order):
        sats = trans[trans["maneuver_class"] == cls]["sat_name"].unique()
        alpha = 0.70 if len(sats) <= 20 else 0.20
        lw    = 1.3  if len(sats) <= 20 else 0.5
        for sat in sats:
            sub = trans[trans["sat_name"] == sat].sort_values("t_from")
            ax.plot(sub["t_from"], sub["alt_km"],
                    color=cls_colors[cls], linewidth=lw, alpha=alpha)
        ax.set_title(f"{title}  (n={len(sats)})", fontsize=11)
        ax.set_ylabel("Altitude (km)")
        ax.set_xlabel("UTC")
        ax.tick_params(axis="x", labelrotation=20)
        for alt_ref in (350, 400, 450, 500, 550):
            ax.axhline(alt_ref, color="k", linestyle=":", linewidth=0.4, alpha=0.4)
            ax.text(trans["t_from"].min(), alt_ref + 2,
                    f"{alt_ref} km", fontsize=6, alpha=0.5)

    fig.tight_layout()
    p = plots_dir / f"class_altitude_trajectories_{date_tag}.png"
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Altitude trajectories -> %s", p)

    # ── Fig 3: da scatter over time, colored by severity ─────────────────────
    sev_colors = {"none": "lightgray", "small": "steelblue",
                  "medium": "darkorange", "large": "tomato"}
    fig, ax = plt.subplots(figsize=(15, 5))
    for sev, color in sev_colors.items():
        sub = trans[trans["da_severity"] == sev]
        ax.scatter(sub["t_from"], sub["da_km"],
                   s=5 if sev == "none" else 20,
                   alpha=0.3 if sev == "none" else 0.6,
                   color=color, linewidths=0, label=sev)
    for thr in (THR_DA_SM, THR_DA_MD, THR_DA_LG,
                -THR_DA_SM, -THR_DA_MD, -THR_DA_LG):
        ax.axhline(thr, color="k", linestyle=":", linewidth=0.5, alpha=0.5)
    ax.set_xlabel("UTC")
    ax.set_ylabel("da (km)")
    ax.set_title(f"Semi-Major Axis Change Over Time  ({date_tag})")
    ax.legend(title="Severity", fontsize=9)
    ax.tick_params(axis="x", labelrotation=20)
    fig.tight_layout()
    p = plots_dir / f"da_severity_timeseries_{date_tag}.png"
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("da severity time-series -> %s", p)

    # ── Fig 4: da vs di scatter, colored by maneuver class ───────────────────
    fig, ax = plt.subplots(figsize=(10, 7))
    for cls, color in cls_colors.items():
        sub = trans[trans["maneuver_class"] == cls]
        ax.scatter(sub["da_km"], sub["di_deg"], s=10, alpha=0.4,
                   color=color, linewidths=0, label=cls)
    for thr in (THR_DA_SM, -THR_DA_SM):
        ax.axvline(thr, color="k", linestyle=":", linewidth=0.7)
    for thr in (THR_DI, -THR_DI):
        ax.axhline(thr, color="k", linestyle=":", linewidth=0.7)
    ax.set_xlabel("da (km)")
    ax.set_ylabel("di (deg)")
    ax.set_title(f"da vs di by Maneuver Class  ({date_tag})")
    ax.legend(fontsize=9)
    fig.tight_layout()
    p = plots_dir / f"da_vs_di_{date_tag}.png"
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("da vs di -> %s", p)


# ── main ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Detect orbital maneuvers from Starlink MEME ephemeris.")
    p.add_argument("--data-root", type=Path, default=Path("data"))
    p.add_argument("--out-dir",   type=Path, default=None)
    p.add_argument("--no-plot",   action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    raw_root = args.data_root / "raw"
    out_dir  = args.out_dir or (args.data_root / "maneuvers")
    out_dir.mkdir(parents=True, exist_ok=True)

    if not raw_root.is_dir():
        log.error("data/raw not found: %s", raw_root)
        return 1

    sat_dirs = sorted(d for d in raw_root.iterdir()
                      if d.is_dir() and d.name not in _EXCLUDE)
    excluded = len([d for d in raw_root.iterdir()
                    if d.is_dir() and d.name in _EXCLUDE])
    log.info("Processing %d satellite directories (%d excluded).",
             len(sat_dirs), excluded)

    all_trans: list[pd.DataFrame] = []
    for sat_dir in sat_dirs:
        df = analyze_satellite(sat_dir.name, sat_dir)
        if not df.empty:
            all_trans.append(df)

    if not all_trans:
        log.error("No transitions found.")
        return 1

    trans   = pd.concat(all_trans, ignore_index=True)
    flagged = trans[trans["flagged"]].copy()
    date_tag = trans["t_from"].dt.strftime("%Y-%m-%d").iloc[0]

    # ── save CSVs ─────────────────────────────────────────────────────────────
    trans_path = out_dir / f"transitions_{date_tag}.csv"
    trans.to_csv(trans_path, index=False)
    log.info("Transitions -> %s  (%d rows)", trans_path, len(trans))

    flag_path = out_dir / f"flagged_maneuvers_{date_tag}.csv"
    (flagged.sort_values("dv_est_ms", ascending=False)
             .to_csv(flag_path, index=False))
    log.info("Flagged -> %s  (%d events)", flag_path, len(flagged))

    # ── per-satellite summary ─────────────────────────────────────────────────
    sat_summary = (
        trans.groupby(["sat_name", "inc_family", "maneuver_class"])
        .agg(
            n_trans      = ("da_km", "count"),
            alt_start_km = ("alt_km", "first"),
            alt_end_km   = ("alt_km", "last"),
            net_da_km    = ("da_km", "sum"),
            abs_da_mean  = ("da_km", lambda x: x.abs().mean()),
            abs_da_max   = ("da_km", lambda x: x.abs().max()),
            max_di_deg   = ("di_deg", lambda x: x.abs().max()),
            dv_total_ms  = ("dv_est_ms", "sum"),
            n_large      = ("da_severity", lambda x: (x == "large").sum()),
            n_medium     = ("da_severity", lambda x: (x == "medium").sum()),
        )
        .reset_index()
        .sort_values("abs_da_mean", ascending=False)
    )
    sat_summary_path = out_dir / f"satellite_summary_{date_tag}.csv"
    sat_summary.to_csv(sat_summary_path, index=False)
    log.info("Satellite summary -> %s  (%d rows)", sat_summary_path, len(sat_summary))

    # ── console report ────────────────────────────────────────────────────────
    n_sats    = trans["sat_name"].nunique()
    n_trans   = len(trans)
    n_flagged = len(flagged)

    sev_counts = trans["da_severity"].value_counts()
    cls_counts = sat_summary["maneuver_class"].value_counts()

    print(f"\n{'='*65}")
    print(f"  Orbital Maneuver Detection -- {date_tag}")
    print(f"  (STARLINK-DEMO excluded as test data)")
    print(f"{'='*65}")
    print(f"  Satellites analysed  : {n_sats}")
    print(f"  Total transitions    : {n_trans}  (~{n_trans/n_sats:.1f} per satellite)")
    print(f"  Flagged transitions  : {n_flagged}  ({100*n_flagged/n_trans:.1f}%)")

    print(f"\n  da severity breakdown:")
    for sev in ("large", "medium", "small", "none"):
        cnt = sev_counts.get(sev, 0)
        pct = 100 * cnt / n_trans
        print(f"    {sev:8s} : {cnt:4d} ({pct:.1f}%)")

    print(f"\n  Inclination families:")
    for fam, cnt in trans.groupby("inc_family")["sat_name"].nunique().items():
        print(f"    {fam:10s} : {cnt} satellites")

    print(f"\n  Maneuver class (per satellite):")
    for cls in ("raising", "lowering", "phasing", "mixed", "stable"):
        cnt = cls_counts.get(cls, 0)
        print(f"    {cls:10s} : {cnt} satellites")

    print(f"\n  da distribution (all transitions):")
    da = trans["da_km"]
    print(f"    median : {da.median():+.4f} km")
    print(f"    std    : {da.std():.4f} km")
    print(f"    P1/P99 : {da.quantile(0.01):+.2f} / {da.quantile(0.99):+.2f} km")

    print(f"\n  di distribution (all transitions):")
    di = trans["di_deg"]
    print(f"    std    : {di.std()*1000:.2f} milli-deg")
    print(f"    |di| > {THR_DI} deg : {(di.abs()>THR_DI).sum()} transitions")

    print(f"\n  J2 RAAN residual (all transitions):")
    dr = trans["draan_res_deg"]
    print(f"    std    : {dr.std()*1000:.2f} milli-deg")
    print(f"    P99    : {dr.abs().quantile(0.99):.4f} deg")

    if n_flagged:
        print(f"\n  Top-20 by |da| (large maneuvers):")
        cols = ["sat_name","maneuver_class","t_from","t_to","da_km","dv_est_ms","di_deg","da_severity"]
        print(
            flagged[flagged["da_severity"].isin(["large","medium"])]
            .sort_values("da_km", key=abs, ascending=False)
            .head(20)[cols]
            .to_string(index=False)
        )

        print(f"\n  Satellites with largest inclination changes:")
        print(
            sat_summary[sat_summary["max_di_deg"] > THR_DI]
            [["sat_name","maneuver_class","alt_start_km","alt_end_km","max_di_deg","dv_total_ms"]]
            .sort_values("max_di_deg", ascending=False)
            .head(10)
            .to_string(index=False)
        )

    print(f"\n  Output directory: {out_dir}")

    if not args.no_plot:
        plot_results(trans, out_dir, date_tag)

    return 0


if __name__ == "__main__":
    sys.exit(main())
