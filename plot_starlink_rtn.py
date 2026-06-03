#!/usr/bin/env python3
"""
Plot RTN + RSS time-series for a single satellite from compare_tle_vs_ephemeris residuals.

Usage
-----
python plot_starlink_rtn.py \
  --residuals data/comparison/residuals_2026-05-02.csv \
  --sat-name STARLINK-35364

or

python plot_starlink_rtn.py \
  --residuals data/comparison/residuals_2026-05-02.csv \
  --norad-id 65840
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Plot RTN + RSS for one satellite.")
    p.add_argument(
        "--residuals",
        type=Path,
        required=True,
        help="Residual CSV from compare_tle_vs_ephemeris.py",
    )
    p.add_argument(
        "--sat-name",
        type=str,
        default=None,
        help="sat_name (MEME / SpaceX-internal name), e.g. STARLINK-35364",
    )
    p.add_argument(
        "--norad-id",
        type=int,
        default=None,
        help="Alternative: select by NORAD ID instead of sat_name.",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output PNG path (default: derived from residuals path + sat_name).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    df = pd.read_csv(args.residuals)

    # normalize time column
    if "t" not in df.columns:
        raise SystemExit("Residual CSV must contain column 't' (UTC timestamp).")
    df["t"] = pd.to_datetime(df["t"], utc=True)

    # choose satellite
    if args.sat_name is None and args.norad_id is None:
        raise SystemExit("Please provide --sat-name or --norad-id.")

    if args.sat_name is not None:
        sub = df[df["sat_name"] == args.sat_name].copy()
        label = args.sat_name
    else:
        sub = df[df["norad_id"] == args.norad_id].copy()
        label = f"NORAD-{args.norad_id}"

    if sub.empty:
        raise SystemExit(f"No rows found for {label} in {args.residuals}.")

    # sanity check for RTN columns
    for col in ("dr_r_km", "dr_t_km", "dr_n_km", "pos_err_km"):
        if col not in sub.columns:
            raise SystemExit(
                f"Residual CSV missing column '{col}'. "
                "Did you add RTN to compute_residuals()?"
            )

    sub = sub.sort_values("t").reset_index(drop=True)

    t = sub["t"]
    dr_r = sub["dr_r_km"]
    dr_t = sub["dr_t_km"]
    dr_n = sub["dr_n_km"]
    rss = sub["pos_err_km"]

    # relative time for X 軸 (hours from start)
    t0 = t.iloc[0]
    hours = (t - t0).dt.total_seconds() / 3600.0

    plt.style.use("seaborn-v0_8-whitegrid") if "seaborn-v0_8-whitegrid" in plt.style.available else None

    fig, axes = plt.subplots(4, 1, figsize=(12, 10), sharex=True)
    fig.suptitle(f"TLE vs MEME — RTN & RSS for {label}", fontsize=13)

    # R
    ax = axes[0]
    ax.plot(hours, dr_r, color="tab:blue", linewidth=1.0)
    ax.set_ylabel("R (km)")
    ax.set_title("Radial residual")

    # T
    ax = axes[1]
    ax.plot(hours, dr_t, color="tab:orange", linewidth=1.0)
    ax.set_ylabel("T (km)")
    ax.set_title("Along-track residual")

    # N
    ax = axes[2]
    ax.plot(hours, dr_n, color="tab:green", linewidth=1.0)
    ax.set_ylabel("N (km)")
    ax.set_title("Cross-track residual")

    # RSS
    ax = axes[3]
    ax.plot(hours, rss, color="k", linewidth=1.2)
    ax.set_ylabel("RSS (km)")
    ax.set_xlabel(f"Hours from {t0.isoformat()}")
    ax.set_title("3D position error norm")

    for ax in axes:
        ax.grid(True, alpha=0.4)

    fig.tight_layout(rect=[0, 0.02, 1, 0.96])

    if args.out is None:
        stem = args.residuals.stem
        safe_label = label.replace(" ", "_")
        out = args.residuals.parent / f"timeseries_rtn_{safe_label}.png"
    else:
        out = args.out

    fig.savefig(out, dpi=150, bbox_inches="tight")
    print("Saved:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())