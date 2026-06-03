from __future__ import annotations
import pandas as pd
from pathlib import Path
from utils import load_config


def load_tle_catalog(config_path: str, satellite: str) -> pd.DataFrame:
    cfg = load_config(config_path)
    tle_cfg = cfg['tle']
    source = tle_cfg.get('source_type', 'csv')

    if source == 'duckdb':
        return _load_from_duckdb(tle_cfg, satellite)
    else:
        return _load_from_csv(tle_cfg, satellite)


def _load_from_csv(tle_cfg: dict, satellite: str) -> pd.DataFrame:
    cols = tle_cfg['columns']
    df = pd.read_csv(tle_cfg['csv_path'])
    out = df[df[cols['satellite']].str.lower() == satellite.lower()].copy()
    out['epoch'] = pd.to_datetime(out[cols['epoch']], utc=True)
    out = out.sort_values('epoch')
    return out[[cols['satellite'], 'epoch', cols['line1'], cols['line2']]].rename(columns={
        cols['satellite']: 'satellite',
        cols['line1']: 'line1',
        cols['line2']: 'line2',
    })


def _load_from_duckdb(tle_cfg: dict, satellite: str) -> pd.DataFrame:
    import duckdb
    norad_map = tle_cfg.get('satellite_norad_map', {})
    norad_id = norad_map.get(satellite.lower())
    if norad_id is None:
        raise ValueError(
            f'No NORAD ID found for "{satellite}" in config tle.satellite_norad_map'
        )
    db_path = Path(tle_cfg['db_path'])
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute('''
            SELECT norad_id, object_name, epoch_utc, line1, line2
            FROM raw_tle_archive
            WHERE norad_id = ?
              AND line1 IS NOT NULL
              AND line2 IS NOT NULL
            ORDER BY epoch_utc
        ''', [int(norad_id)]).fetchdf()
    finally:
        con.close()

    if df.empty:
        raise ValueError(
            f'No TLEs found in DuckDB for {satellite} (NORAD {norad_id}). '
            f'Run the TLE download pipeline first.'
        )
    df['epoch'] = pd.to_datetime(df['epoch_utc'], utc=True)
    df['satellite'] = satellite
    return df[['satellite', 'epoch', 'line1', 'line2']].sort_values('epoch').reset_index(drop=True)


def choose_tle_for_epoch(tle_df: pd.DataFrame, epoch: pd.Timestamp) -> pd.Series:
    valid = tle_df[tle_df['epoch'] <= epoch]
    if valid.empty:
        return tle_df.iloc[0]
    return valid.iloc[-1]
