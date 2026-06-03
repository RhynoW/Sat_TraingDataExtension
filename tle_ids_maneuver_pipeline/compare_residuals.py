from __future__ import annotations
import numpy as np
import pandas as pd
from astropy.coordinates import TEME, ITRS, CartesianRepresentation, CartesianDifferential
from astropy.time import Time
import astropy.units as u

from utils import load_config, parse_dt, daterange, ensure_dir
from tle_db import load_tle_catalog
from propagate_tle import propagate_catalog_piecewise, eci_to_ric_basis


def teme_to_itrs(
    x_km: float, y_km: float, z_km: float,
    vx_km_s: float, vy_km_s: float, vz_km_s: float,
    epoch: pd.Timestamp,
) -> tuple[np.ndarray, np.ndarray]:
    """Convert SGP4 TEME position/velocity to ITRS (Earth-fixed, matches SP3 ITRF)."""
    t = Time(epoch.to_pydatetime(), scale='utc')
    teme_pos = CartesianRepresentation(x_km * u.km, y_km * u.km, z_km * u.km)
    teme_vel = CartesianDifferential(vx_km_s * u.km / u.s, vy_km_s * u.km / u.s, vz_km_s * u.km / u.s)
    teme_coord = TEME(teme_pos.with_differentials(teme_vel), obstime=t)
    itrs_coord = teme_coord.transform_to(ITRS(obstime=t))
    pos = itrs_coord.cartesian.xyz.to(u.km).value
    vel = itrs_coord.cartesian.differentials['s'].d_xyz.to(u.km / u.s).value
    return pos, vel


def compute_residuals(tle_states: pd.DataFrame, ids_states: pd.DataFrame) -> pd.DataFrame:
    df = tle_states.merge(ids_states, on='epoch', suffixes=('_tle', '_ids'))
    rows = []
    for _, row in df.iterrows():
        # Convert SGP4 TEME → ITRS to match SP3 ITRF frame
        r_itrs, v_itrs = teme_to_itrs(
            row['x_km_tle'], row['y_km_tle'], row['z_km_tle'],
            row.get('vx_km_s_tle', 0.0), row.get('vy_km_s_tle', 0.0), row.get('vz_km_s_tle', 0.0),
            row['epoch'],
        )
        r_ids = np.array([row['x_km_ids'], row['y_km_ids'], row['z_km_ids']])
        # IDS velocities are in dm/s → convert to km/s
        if {'vx_dm_s', 'vy_dm_s', 'vz_dm_s'}.issubset(df.columns):
            v_ids = np.array([row['vx_dm_s'], row['vy_dm_s'], row['vz_dm_s']]) / 10.0
        else:
            v_ids = v_itrs

        dr = r_itrs - r_ids
        basis = eci_to_ric_basis(r_ids, v_ids)
        ric = basis.T @ dr
        rows.append({
            'epoch':             row['epoch'],
            'dr_km':             float(np.linalg.norm(dr)),
            'radial_km':         float(ric[0]),
            'in_track_km':       float(ric[1]),
            'cross_track_km':    float(ric[2]),
            'tle_epoch_used':    row['tle_epoch_used'],
            'sgp4_error':        row['sgp4_error'],
        })
    out = pd.DataFrame(rows).sort_values('epoch')
    out['dr_diff_km'] = out['dr_km'].diff()
    return out


def build_epoch_grid(config_path: str) -> list[pd.Timestamp]:
    cfg = load_config(config_path)
    start = pd.Timestamp(parse_dt(cfg['analysis']['start']))
    end = pd.Timestamp(parse_dt(cfg['analysis']['end']))
    step = int(cfg['analysis']['step_seconds'])
    return [pd.Timestamp(t) for t in daterange(start.to_pydatetime(), end.to_pydatetime(), step)]


def run_compare(config_path: str, satellite: str, ids_states: pd.DataFrame) -> pd.DataFrame:
    cfg = load_config(config_path)
    tle_df = load_tle_catalog(config_path, satellite)
    epochs = sorted(set(pd.to_datetime(ids_states['epoch'], utc=True)))
    tle_states = propagate_catalog_piecewise(tle_df, epochs)
    residuals = compute_residuals(tle_states, ids_states)
    out_dir = ensure_dir(f"{cfg['project']['output_dir']}/residuals/{satellite}")
    residuals.to_csv(out_dir / 'residuals.csv', index=False)
    return residuals
