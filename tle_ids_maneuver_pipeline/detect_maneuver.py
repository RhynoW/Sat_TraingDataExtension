from __future__ import annotations
import numpy as np
import pandas as pd
from utils import load_config, ensure_dir


def rolling_zscore(x: pd.Series, window: int) -> pd.Series:
    mu = x.rolling(window, min_periods=max(3, window // 2)).mean()
    sd = x.rolling(window, min_periods=max(3, window // 2)).std()
    return (x - mu) / sd.replace(0, np.nan)


def detect_candidates(residuals: pd.DataFrame, config_path: str) -> pd.DataFrame:
    cfg = load_config(config_path)
    thr = cfg['analysis']['thresholds']
    window = int(cfg['analysis']['rolling_window_points'])
    df = residuals.copy().sort_values('epoch')
    df['abs_radial'] = df['radial_km'].abs()
    df['abs_in_track'] = df['in_track_km'].abs()
    df['abs_cross_track'] = df['cross_track_km'].abs()
    df['z_dr'] = rolling_zscore(df['dr_km'], window).abs()
    df['z_djump'] = rolling_zscore(df['dr_diff_km'].fillna(0), window).abs()
    df['candidate'] = (
        (df['abs_radial'] > thr['radial_km']) |
        (df['abs_in_track'] > thr['in_track_km']) |
        (df['abs_cross_track'] > thr['cross_track_km']) |
        (df['z_dr'] > 3.0) |
        (df['z_djump'] > 3.0)
    )
    cand = df[df['candidate']].copy()
    min_sep = pd.Timedelta(hours=cfg['analysis']['min_candidate_separation_hours'])
    clusters = []
    last_t = None
    cid = -1
    for t in pd.to_datetime(cand['epoch'], utc=True):
        if last_t is None or t - last_t > min_sep:
            cid += 1
        clusters.append(cid)
        last_t = t
    cand['cluster_id'] = clusters
    summary = cand.groupby('cluster_id').agg(
        start_epoch=('epoch', 'min'),
        end_epoch=('epoch', 'max'),
        peak_dr_km=('dr_km', 'max'),
        peak_abs_in_track_km=('abs_in_track', 'max'),
        peak_abs_radial_km=('abs_radial', 'max'),
        peak_abs_cross_track_km=('abs_cross_track', 'max'),
        n_points=('epoch', 'count'),
    ).reset_index(drop=True)
    return summary


def save_candidates(candidates: pd.DataFrame, output_dir: str, satellite: str):
    out_dir = ensure_dir(f'{output_dir}/candidates/{satellite}')
    candidates.to_csv(out_dir / 'maneuver_candidates.csv', index=False)
