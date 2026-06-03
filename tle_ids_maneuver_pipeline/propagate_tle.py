from __future__ import annotations
import numpy as np
import pandas as pd
from sgp4.api import Satrec, jday
from tle_db import choose_tle_for_epoch


def propagate_single_tle(line1: str, line2: str, epochs: list[pd.Timestamp]) -> pd.DataFrame:
    sat = Satrec.twoline2rv(line1, line2)
    rows = []
    for t in epochs:
        jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6)
        err, r, v = sat.sgp4(jd, fr)
        rows.append({
            'epoch': t,
            'sgp4_error': err,
            'x_km': r[0],
            'y_km': r[1],
            'z_km': r[2],
            'vx_km_s': v[0],
            'vy_km_s': v[1],
            'vz_km_s': v[2],
        })
    return pd.DataFrame(rows)


def propagate_catalog_piecewise(tle_df: pd.DataFrame, epochs: list[pd.Timestamp]) -> pd.DataFrame:
    rows = []
    for t in epochs:
        tle = choose_tle_for_epoch(tle_df, t)
        pr = propagate_single_tle(tle['line1'], tle['line2'], [t]).iloc[0].to_dict()
        pr['tle_epoch_used'] = tle['epoch']
        rows.append(pr)
    return pd.DataFrame(rows)


def eci_to_ric_basis(r_ref: np.ndarray, v_ref: np.ndarray):
    r_hat = r_ref / np.linalg.norm(r_ref)
    h = np.cross(r_ref, v_ref)
    c_hat = h / np.linalg.norm(h)
    i_hat = np.cross(c_hat, r_hat)
    return np.vstack([r_hat, i_hat, c_hat]).T
