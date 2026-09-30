"""
Convert the raw Starlink V3 Flight-14 MEME ephemerides into a lightweight,
frame-converted position-sample table for direct interpolation -- no
SGP4/TLE fit involved.

Why this exists (see session log 2026-09-30): a differential-correction
SGP4/TLE fit (meme_to_tle.py) assumes a passive (drag-only) trajectory.
Once these satellites started their post-deployment orbit-raise burns
(observed ~36-48h after Flight 14), that assumption breaks down -- fit
validation errors grew from ~15 km to 500+ km satellite by satellite.

Instead of fitting anything, this module just re-expresses SpaceX's own
72-hour MEME samples (already precise, already forecast by SpaceX) in the
TEME frame so the dashboard's existing TEME-based `eci_to_llh_batch()`
(scenario04/physics/coords.py) can turn them into lat/lon/alt by plain
linear interpolation between the two bracketing samples. Honest labelling:
"Starlink 官方 MEME，72 小時預估" -- not a TLE, not a long-range model,
just SpaceX's own short-range forecast re-served as-is.

Output: rows (norad_id, name, t_utc, x_km, y_km, z_km) written into the
scenario-advanced01 slim DuckDB's `v3_meme_teme_samples` table. Stale once
`t_utc` runs past `now` -- re-run this after each fresh MEME download.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from starlink_ephemeris.meme_to_tle_batch import fetch_batch_roster  # noqa: E402
from starlink_ephemeris.parser import parse_ephemeris_file  # noqa: E402

CACHE_DIR = BASE_DIR / "data" / "raw" / "_v3_meme_cache"
DEFAULT_DB = BASE_DIR / "scenario-advanced01" / "DB" / "space_db_slim.duckdb"
TABLE = "v3_meme_teme_samples"


def _require_astropy() -> None:
    try:
        import astropy  # noqa: F401
    except ImportError as exc:
        raise ImportError("meme_to_teme_samples requires astropy: pip install astropy") from exc


def _eme2000_to_teme_batch(r_km: np.ndarray, v_km_s: np.ndarray, t_utc: pd.Series) -> np.ndarray:
    """Vectorised EME2000/GCRS -> TEME position conversion for one satellite's
    whole sample run. Returns (N,3) TEME km. Velocity is dropped -- only
    position is needed for lat/lon/alt display."""
    from astropy import units as u
    from astropy.coordinates import GCRS, TEME, CartesianDifferential, CartesianRepresentation
    from astropy.time import Time

    times = Time(pd.DatetimeIndex(t_utc).tz_convert("UTC").tz_localize(None).to_pydatetime())
    rep = CartesianRepresentation(
        r_km[:, 0] * u.km, r_km[:, 1] * u.km, r_km[:, 2] * u.km,
        differentials=CartesianDifferential(
            v_km_s[:, 0] * u.km / u.s, v_km_s[:, 1] * u.km / u.s, v_km_s[:, 2] * u.km / u.s),
    )
    teme = GCRS(rep, obstime=times).transform_to(TEME(obstime=times))
    return np.column_stack([
        teme.x.to_value(u.km), teme.y.to_value(u.km), teme.z.to_value(u.km),
    ])


def build_teme_samples(cache_dir: Path = CACHE_DIR) -> pd.DataFrame:
    """Parse every cached V3 MEME file and return one combined (norad_id,
    name, t_utc, x_km, y_km, z_km) DataFrame in TEME. `norad_id` here is
    this project's synthetic Alpha-5 catalog number (339974-339999), the
    same mapping meme_to_tle_batch.py uses, so the two paths line up."""
    _require_astropy()
    roster = fetch_batch_roster()
    frames: list[pd.DataFrame] = []
    for i, item in enumerate(roster):
        name = item["OBJECT_NAME"]
        placeholder = item["NORAD_CAT_ID"]
        catnr = 339974 + i
        meme_path = cache_dir / f"{placeholder}.txt"
        if not meme_path.exists():
            print(f"  [{i+1}/{len(roster)}] {name}: no cached MEME file, skipping")
            continue
        meta, df = parse_ephemeris_file(meme_path, sat_id=name)
        r = df[["r_x", "r_y", "r_z"]].to_numpy(dtype=float)
        v = df[["v_x", "v_y", "v_z"]].to_numpy(dtype=float)
        teme = _eme2000_to_teme_batch(r, v, df["t"])
        frames.append(pd.DataFrame({
            "norad_id": catnr, "name": name, "t_utc": df["t"].to_numpy(),
            "x_km": teme[:, 0], "y_km": teme[:, 1], "z_km": teme[:, 2],
        }))
        print(f"  [{i+1}/{len(roster)}] {name}: {len(df)} samples converted")
    if not frames:
        return pd.DataFrame(columns=["norad_id", "name", "t_utc", "x_km", "y_km", "z_km"])
    return pd.concat(frames, ignore_index=True)


def write_to_db(df: pd.DataFrame, db_path: Path = DEFAULT_DB) -> int:
    """Replace the `v3_meme_teme_samples` table in the slim DuckDB with `df`."""
    import duckdb
    con = duckdb.connect(str(db_path))
    try:
        con.execute(f"CREATE OR REPLACE TABLE {TABLE} AS SELECT * FROM df")
        return con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    finally:
        con.close()


def main() -> int:
    df = build_teme_samples()
    if df.empty:
        print("[teme_samples] no data converted, nothing written")
        return 1
    n = write_to_db(df)
    by_sat = df.groupby("norad_id")["t_utc"]
    print(f"[teme_samples] wrote {n} rows across {df['norad_id'].nunique()} satellites "
          f"into {DEFAULT_DB}")
    print(f"[teme_samples] sample span: {by_sat.min().min()} .. {by_sat.max().max()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
