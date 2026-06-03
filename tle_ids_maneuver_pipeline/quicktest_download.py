#!/usr/bin/env python3
"""
quicktest_download.py
─────────────────────
Quick sanity check: list available SP3 files for jason-3 at CDDIS
without downloading.  Useful to verify credentials & directory layout.
"""
from download_ids import build_auth_session, get_credentials, list_cddis_directory, \
                         select_files_for_window, CDDIS_BASE, ANALYSIS_CENTER
from utils import load_config
from datetime import datetime, timezone

cfg = load_config('config.yaml')
user, pw = get_credentials(cfg)
session  = build_auth_session(user, pw)

satellite = 'jason-3'
sat_code  = cfg['ids']['satellite_code_map'][satellite]
ac        = ANALYSIS_CENTER
dir_url   = f'{CDDIS_BASE}/{ac}/{sat_code}/'

print(f'Listing: {dir_url}')
files = list_cddis_directory(session, dir_url)
print(f'Total files listed: {len(files)}')

start = datetime(2024, 1, 1, tzinfo=timezone.utc)
end   = datetime(2024, 3, 31, tzinfo=timezone.utc)
sel   = select_files_for_window(files, sat_code, start, end, ac)
print(f'Files covering 2024-01-01 – 2024-03-31: {len(sel)}')
for m in sel:
    print(f"  {m['fname']}")
