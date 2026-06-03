from __future__ import annotations

"""
download_ids.py
───────────────
Downloads IDS precise orbit products (SP3 format) from NASA CDDIS for satellites
listed on the ILRS maneuver page.

CDDIS directory layout  (from NASA Earthdata description):
  https://cddis.nasa.gov/archive/doris/products/orbits/ssa/{sss}/
  File: ssasssVV.bXXDDD.eYYEEE.dgs.sp3.LLL.Z

Authentication: NASA Earthdata login via ~/.netrc  OR  env vars
  EARTHDATA_USERNAME / EARTHDATA_PASSWORD

References
  https://www.earthdata.nasa.gov/data/space-geodesy-techniques/doris/
          international-doris-service-orbit-product
  https://cddis.nasa.gov/Data_and_Derived_Products/CDDIS_Archive_Access.html
"""

import ftplib
import gzip
import logging
import netrc
import os
import re
import shutil
import struct
import subprocess
import time
import zlib
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Optional
from urllib import request as urllib_request
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from utils import load_config, ensure_dir, get_env_credential

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)s  %(message)s')

EARTHDATA_HOST = 'urs.earthdata.nasa.gov'
CDDIS_BASE     = 'https://cddis.nasa.gov/archive/doris/products/orbits'
ANALYSIS_CENTER = 'ssa'


# ──────────────────────────────────────────────
# Authentication helpers
# ──────────────────────────────────────────────

def _read_netrc() -> tuple[str, str] | tuple[None, None]:
    """Read Earthdata credentials from ~/.netrc (or ~/_netrc on Windows)."""
    candidates = [Path.home() / '.netrc', Path.home() / '_netrc']
    for c in candidates:
        if c.exists():
            try:
                n = netrc.netrc(str(c))
                auth = n.authenticators(EARTHDATA_HOST)
                if auth:
                    return auth[0], auth[2]
            except netrc.NetrcParseError:
                pass
    return None, None


def get_credentials(config: dict) -> tuple[str, str]:
    """Resolve Earthdata credentials:  netrc > env vars > config file."""
    user, pw = _read_netrc()
    if user:
        log.info('Using credentials from ~/.netrc')
        return user, pw
    ids_auth = config.get('ids', {}).get('auth', {})
    user = get_env_credential(ids_auth.get('username_env')) or ''
    pw   = get_env_credential(ids_auth.get('password_env')) or ''
    if user:
        log.info('Using credentials from environment variables.')
        return user, pw
    raise RuntimeError(
        'No Earthdata credentials found.\n'
        '  Option A: create ~/.netrc with:\n'
        '            machine urs.earthdata.nasa.gov\n'
        '            login   <YOUR_USERNAME>\n'
        '            password <YOUR_PASSWORD>\n'
        '  Option B: set EARTHDATA_USERNAME / EARTHDATA_PASSWORD env vars.'
    )


def _acquire_earthdata_token(username: str, password: str) -> str | None:
    """
    Obtain a URS Bearer token for CDDIS access.
    CDDIS honours 'Authorization: Bearer <token>' and skips the OAuth redirect,
    which allows programmatic directory listing and file download to work correctly.
    """
    import base64
    b64 = base64.b64encode(f'{username}:{password}'.encode()).decode()
    headers = {'Authorization': f'Basic {b64}'}
    # List existing tokens first (avoids creating duplicates)
    try:
        r = requests.get(
            'https://urs.earthdata.nasa.gov/api/users/tokens',
            headers=headers, timeout=20,
        )
        if r.status_code == 200:
            tokens = r.json()
            if tokens:
                tok = tokens[0].get('access_token')
                if tok:
                    log.info('Reusing existing Earthdata token.')
                    return tok
    except Exception as e:
        log.debug('Token list failed: %s', e)
    # Generate a fresh token
    try:
        r = requests.post(
            'https://urs.earthdata.nasa.gov/api/users/token',
            headers=headers, timeout=20,
        )
        if r.status_code == 200:
            tok = r.json().get('access_token')
            if tok:
                log.info('Generated new Earthdata token.')
                return tok
        log.warning('Token generation returned %s: %s', r.status_code, r.text[:200])
    except Exception as e:
        log.warning('Token generation failed: %s', e)
    return None


def build_auth_session(username: str, password: str) -> requests.Session:
    """
    Build a requests.Session authenticated for CDDIS access.
    Uses a URS Bearer token (preferred — avoids OAuth redirect that strips auth
    on cross-domain requests) with a Basic-auth fallback.
    """
    session = requests.Session()
    retry = Retry(total=5, backoff_factor=2,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET", "HEAD"])
    session.mount('https://', HTTPAdapter(max_retries=retry))
    session.headers.update({'User-Agent': 'tle-ids-maneuver-pipeline/0.2'})

    token = _acquire_earthdata_token(username, password)
    if token:
        session.headers['Authorization'] = f'Bearer {token}'
    else:
        # Fallback: basic auth sent on initial request only.
        # May still fail for CDDIS if OAuth redirect occurs.
        log.warning('Could not acquire Bearer token; falling back to Basic auth.')
        session.auth = (username, password)
    return session


def get_with_auth(session: requests.Session, url: str, timeout: int = 120) -> requests.Response:
    """
    GET with automatic follow of Earthdata auth redirects.
    CDDIS may redirect to EDL SSO then back; requests handles cookies automatically.
    """
    r = session.get(url, timeout=timeout, allow_redirects=True)
    if r.status_code == 401:
        raise PermissionError(
            f'HTTP 401 Unauthorized for {url}\n'
            'Check your Earthdata credentials or app authorisation at:\n'
            'https://urs.earthdata.nasa.gov/profile'
        )
    r.raise_for_status()
    return r


# ──────────────────────────────────────────────
# Directory listing & file selection
# ──────────────────────────────────────────────

def list_cddis_directory(session: requests.Session, url: str) -> list[str]:
    """Return list of filenames in a CDDIS HTTPS directory listing."""
    if not url.endswith('/'):
        url += '/'
    r = get_with_auth(session, url)
    # Guard: if we got redirected to an auth page, the response URL won't be
    # the CDDIS directory we asked for.
    if r.url and 'urs.earthdata.nasa.gov' in r.url:
        raise PermissionError(
            f'CDDIS redirected to URS login page — Bearer token auth failed.\n'
            f'Check credentials or re-generate the token at https://urs.earthdata.nasa.gov/profile'
        )
    hrefs = re.findall(r'href="([^"]+)"', r.text)
    # Keep only relative filenames (not absolute URLs, not query strings, not parent links)
    files = [
        h.rstrip('/')
        for h in hrefs
        if h and not h.startswith('http') and not h.startswith('?')
        and not h.startswith('/') and h != '../'
    ]
    return files


def list_ftp_directory(host: str, remote_path: str, port: int = 21,
                       user: str = 'anonymous', password: str = 'anonymous@') -> list[str]:
    """List basenames of files in an FTP directory using passive mode."""
    with ftplib.FTP() as ftp:
        ftp.connect(host, port, timeout=30)
        ftp.login(user, password)
        ftp.set_pasv(True)
        try:
            names = ftp.nlst(remote_path)
        except ftplib.error_perm as e:
            if '550' in str(e):   # No such directory
                return []
            raise
    return [n.split('/')[-1] for n in names if n.split('/')[-1]]


def download_ftp_file(host: str, remote_path: str, dest_path: Path,
                      port: int = 21, user: str = 'anonymous',
                      password: str = 'anonymous@', force: bool = False) -> Path:
    """
    Download a single file from FTP to dest_path.
    Decompresses .Z files automatically (reuses decompress_Z).
    Returns path to the (decompressed) file.
    """
    dest_path = Path(dest_path)
    sp3_path  = Path(str(dest_path)[:-2]) if str(dest_path).endswith('.Z') else dest_path
    if sp3_path.exists() and not force:
        log.info('  Already cached: %s', sp3_path.name)
        return sp3_path
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    log.info('  FTP download: ftp://%s%s', host, remote_path)
    with ftplib.FTP() as ftp:
        ftp.connect(host, port, timeout=120)
        ftp.login(user, password)
        ftp.set_pasv(True)
        with open(dest_path, 'wb') as fh:
            ftp.retrbinary(f'RETR {remote_path}', fh.write)
    log.info('  Saved %s  (%.1f KB)', dest_path.name, dest_path.stat().st_size / 1024)
    if str(dest_path).endswith('.Z'):
        sp3_path = decompress_Z(dest_path)
        dest_path.unlink(missing_ok=True)
        log.info('  Decompressed -> %s', sp3_path.name)
    return sp3_path


def parse_sp3_filename(fname: str) -> dict | None:
    """
    Parse CDDIS IDS SP3 filename:
      ssasssVV.bXXDDD.eYYEEE.dgs.sp3.LLL.Z
    Returns dict with keys: ac, sat, version, begin_year, begin_doy,
                             end_year, end_doy, data_type, sp3_version, rep, fname
    """
    pat = re.compile(
        r'^(?P<ac>[a-z]{3})(?P<sat>[a-z0-9]{3})(?P<ver>\d{2})'
        r'\.b(?P<by>\d{2})(?P<bd>\d{3})'
        r'\.e(?P<ey>\d{2})(?P<ed>\d{3})'
        r'\.(?P<dtype>[dgs_]{3})'
        r'\.sp3'
        r'(?:\.(?P<rep>\d{3}))?'
        r'(?:\.Z)?$',
        re.IGNORECASE,
    )
    m = pat.match(fname.strip())
    if not m:
        return None
    g = m.groupdict()
    return {
        'ac': g['ac'],
        'sat': g['sat'],
        'version': int(g['ver']),
        'begin_year': 2000 + int(g['by']),
        'begin_doy':  int(g['bd']),
        'end_year':   2000 + int(g['ey']),
        'end_doy':    int(g['ed']),
        'data_type':  g['dtype'],
        'rep':        int(g['rep']) if g['rep'] else 1,
        'fname':      fname.strip(),
    }


def doy_to_date(year: int, doy: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1)


def select_files_for_window(
    all_files: list[str],
    sat_code: str,
    start: datetime,
    end: datetime,
    ac: str = ANALYSIS_CENTER,
) -> list[dict]:
    """
    Filter parsed SP3 filenames that overlap [start, end] for a given satellite.
    Prefer highest version number; among ties prefer highest rep number.
    """
    parsed = [p for f in all_files if (p := parse_sp3_filename(f)) is not None]
    parsed = [p for p in parsed
              if p['ac'] == ac and p['sat'].lower() == sat_code.lower()]
    results = []
    for p in parsed:
        f_start = doy_to_date(p['begin_year'], p['begin_doy'])
        f_end   = doy_to_date(p['end_year'],   p['end_doy'])
        if f_start <= end and f_end >= start:
            results.append(p)
    # deduplicate: keep highest version then highest rep
    best = {}
    for p in results:
        key = (p['begin_year'], p['begin_doy'], p['end_year'], p['end_doy'])
        if key not in best:
            best[key] = p
        else:
            prev = best[key]
            if (p['version'], p['rep']) > (prev['version'], prev['rep']):
                best[key] = p
    return sorted(best.values(), key=lambda x: (x['begin_year'], x['begin_doy']))


# ──────────────────────────────────────────────
# Download & decompress
# ──────────────────────────────────────────────

def decompress_Z(src: Path) -> Path:
    """
    Decompress a UNIX .Z (LZW) or .gz compressed file.
    Tries unlzw3 (LZW), then gzip, then system uncompress.
    """
    dst = src.with_suffix('')
    if dst.exists():
        return dst
    raw = src.read_bytes()
    # LZW: magic bytes 0x1f 0x9d
    if raw[:2] == b'\x1f\x9d':
        try:
            import unlzw3
            dst.write_bytes(unlzw3.unlzw(raw))
            return dst
        except Exception as e:
            log.debug('unlzw3 failed: %s', e)
    # gzip: magic bytes 0x1f 0x8b
    try:
        import io
        with gzip.open(io.BytesIO(raw), 'rb') as gz_f:
            dst.write_bytes(gz_f.read())
        return dst
    except Exception:
        pass
    # system uncompress / 7z fallback
    for cmd in [['uncompress', '-f', str(src)], ['7z', 'e', '-y', str(src), f'-o{src.parent}']]:
        try:
            subprocess.run(cmd, check=True, timeout=60, capture_output=True)
            if dst.exists():
                return dst
        except Exception:
            pass
    raise RuntimeError(
        f'Cannot decompress {src}. '
        f'Run: pip install unlzw3'
    )


def download_sp3_file(
    session: requests.Session,
    url: str,
    dest_path: Path,
    force: bool = False,
) -> Path:
    """
    Download a single SP3 file.  Decompresses .Z files automatically.
    Returns path to the (decompressed) SP3 file.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path = dest_path if not str(dest_path).endswith('.Z') else dest_path
    sp3_path  = raw_path.with_suffix('') if str(raw_path).endswith('.Z') else raw_path

    if sp3_path.exists() and not force:
        log.info(f'  Already cached: {sp3_path.name}')
        return sp3_path

    log.info(f'  Downloading: {url}')
    r = get_with_auth(session, url)
    raw_path.write_bytes(r.content)
    log.info(f'  Saved {raw_path.name}  ({raw_path.stat().st_size / 1024:.1f} KB)')

    if str(raw_path).endswith('.Z'):
        sp3_path = decompress_Z(raw_path)
        raw_path.unlink(missing_ok=True)
        log.info(f'  Decompressed -> {sp3_path.name}')
    return sp3_path


# ──────────────────────────────────────────────
# SP3 parser
# ──────────────────────────────────────────────

_TAI_MINUS_UTC_S = 37  # leap seconds: TAI − UTC as of 2017-01-01 (current as of 2026)
_TAI_CORRECTION  = pd.Timedelta(seconds=_TAI_MINUS_UTC_S)


def parse_sp3_positions(path: str | Path) -> pd.DataFrame:
    """
    Parse SP3c/d file into a DataFrame with columns:
      epoch, sp3_sat, x_km, y_km, z_km, vx_dm_s, vy_dm_s, vz_dm_s, clk_us
    Position unit in SP3: km.  Velocity unit: dm/s.
    IDS ssa products use TAI time system (header %c record); epochs are
    converted to UTC by subtracting the TAI−UTC offset (37 s since 2017).
    """
    records = []
    opener = gzip.open if str(path).endswith('.gz') else open
    current_epoch = None
    time_system = 'UTC'  # default; overridden by %c header line
    with opener(path, 'rt', encoding='utf-8', errors='ignore') as fh:
        for line in fh:
            # Detect time system from %c header record (field at columns 9-11)
            if line.startswith('%c') and time_system == 'UTC':
                parts = line.split()
                if len(parts) >= 4:
                    time_system = parts[3].upper()
            if line.startswith('*'):
                parts = line.split()
                y, mo, d, H, M = map(int, parts[1:6])
                sec = float(parts[6])
                s_int = int(sec)
                us = int(round((sec - s_int) * 1e6))
                current_epoch = pd.Timestamp(
                    year=y, month=mo, day=d, hour=H, minute=M,
                    second=s_int, microsecond=us, tz='UTC'
                )
                # Convert TAI epoch tags to UTC
                if time_system == 'TAI':
                    current_epoch -= _TAI_CORRECTION
            elif line.startswith('P') and current_epoch is not None:
                sat_id  = line[1:4].strip()
                # Extended precision: f14.7 columns at 4,18,32,46
                x   = float(line[4:18])
                y_  = float(line[18:32])
                z   = float(line[32:46])
                clk_str = line[46:60].strip()
                clk = float(clk_str) if clk_str and clk_str not in ('999999.999999', '999999.9999999') else None
                records.append({
                    'epoch': current_epoch,
                    'sp3_sat': sat_id,
                    'x_km': x, 'y_km': y_, 'z_km': z,
                    'clk_us': clk,
                })
            elif line.startswith('V') and records and current_epoch is not None:
                # Velocity record (optional in SP3)
                records[-1]['vx_dm_s'] = float(line[4:18])
                records[-1]['vy_dm_s'] = float(line[18:32])
                records[-1]['vz_dm_s'] = float(line[32:46])
    df = pd.DataFrame(records)
    for col in ('vx_dm_s', 'vy_dm_s', 'vz_dm_s', 'clk_us'):
        if col not in df.columns:
            df[col] = float('nan')
    return df


# ──────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────

def download_ids_products(
    config_path: str,
    satellite: str,
    start: str | None = None,
    end: str   | None = None,
    force: bool = False,
) -> list[Path]:
    """
    Download all IDS orbit SP3 files for *satellite* covering [start, end].

    Parameters
    ----------
    config_path : str
        Path to config.yaml.
    satellite : str
        Normalised satellite name matching config satellite_code_map key
        (e.g. 'jason-3', 'sentinel-3a', 'cryosat-2').
    start, end : ISO 8601 strings (UTC).  Defaults to config analysis window.
    force : bool
        Re-download even if cached.

    Returns
    -------
    List of paths to downloaded (decompressed) SP3 files.
    """
    cfg = load_config(config_path)
    ids_cfg = cfg['ids']
    ac = ids_cfg.get('analysis_center', ANALYSIS_CENTER)
    sat_code = ids_cfg['satellite_code_map'].get(satellite)
    if not sat_code:
        raise ValueError(f'No satellite code mapping for "{satellite}" in config.yaml')

    start_str = start or cfg['analysis']['start']
    end_str   = end   or cfg['analysis']['end']
    start_dt  = datetime.fromisoformat(start_str.replace('Z', '+00:00')).astimezone(timezone.utc)
    end_dt    = datetime.fromisoformat(end_str.replace('Z', '+00:00')).astimezone(timezone.utc)

    out_dir = ensure_dir(Path(cfg['project']['output_dir']) / 'ids' / satellite)
    username, password = get_credentials(cfg)
    session = build_auth_session(username, password)

    ftp_mirrors = ids_cfg.get('ftp_mirrors', [])

    # 1. List directory — try FTP mirrors first, fall back to CDDIS HTTPS
    all_files: list[str] = []
    active_ftp: tuple | None = None   # (host, port, base_remote_path)

    for mirror in ftp_mirrors:
        parsed = urlparse(mirror)
        host   = parsed.hostname or ''
        port   = parsed.port or 21
        base   = parsed.path.rstrip('/')
        remote = f'{base}/{sat_code}'
        try:
            log.info('Trying FTP mirror: ftp://%s%s/', host, remote)
            names = list_ftp_directory(host, remote, port)
            if names:
                all_files = names
                active_ftp = (host, port, base)
                log.info('FTP listing OK: %d files from %s', len(names), host)
                break
            log.warning('FTP mirror %s returned no files for %s', host, sat_code)
        except Exception as e:
            log.warning('FTP mirror %s failed: %s', host, e)

    if not all_files:
        dir_url = f'{CDDIS_BASE}/{ac}/{sat_code}/'
        log.info('FTP unavailable; listing CDDIS HTTPS: %s', dir_url)
        try:
            all_files = list_cddis_directory(session, dir_url)
        except Exception as e:
            log.error('Cannot list directory %s: %s', dir_url, e)
            raise
    else:
        dir_url = None  # not used when FTP succeeded

    # 2. Select files that overlap the requested window
    selected = select_files_for_window(all_files, sat_code, start_dt, end_dt, ac)
    if not selected:
        log.warning('No SP3 files found for %s (%s) in window %s – %s',
                    satellite, sat_code, start_dt.date(), end_dt.date())
        log.warning('Available files (%d total): %s...', len(all_files), all_files[:5])
        return []

    log.info('Found %d SP3 file(s) to download for %s', len(selected), satellite)

    # 3. Download — prefer FTP, fall back to HTTPS per file
    downloaded = []
    for meta in selected:
        fname    = meta['fname']
        dest     = out_dir / fname
        sp3_path = None

        if active_ftp:
            ftp_host, ftp_port, ftp_base = active_ftp
            remote_file = f'{ftp_base}/{sat_code}/{fname}'
            try:
                sp3_path = download_ftp_file(
                    ftp_host, remote_file, dest, port=ftp_port, force=force
                )
            except Exception as e:
                log.warning('FTP download failed for %s: %s — falling back to HTTPS', fname, e)

        if sp3_path is None:
            https_url = f'{CDDIS_BASE}/{ac}/{sat_code}/{fname}'
            sp3_path = download_sp3_file(session, https_url, dest, force=force)

        downloaded.append(sp3_path)
        time.sleep(0.3)

    # 4. Save manifest
    manifest = pd.DataFrame([{
        'satellite': satellite,
        'sat_code': sat_code,
        'fname': m['fname'],
        'begin': doy_to_date(m['begin_year'], m['begin_doy']).isoformat(),
        'end':   doy_to_date(m['end_year'],   m['end_doy']).isoformat(),
        'version': m['version'],
        'rep': m['rep'],
        'local_path': str(out_dir / m['fname'].replace('.Z', '')),
    } for m in selected])
    manifest.to_csv(out_dir / 'download_manifest.csv', index=False)
    log.info(f'Manifest saved to {out_dir / "download_manifest.csv"}')

    return downloaded


def load_ids_states(sp3_paths: list[Path], sat_code: str) -> pd.DataFrame:
    """
    Parse one or more SP3 files and return a time-sorted DataFrame
    with columns: epoch, x_km, y_km, z_km, vx_dm_s, vy_dm_s, vz_dm_s.

    IDS SP3 files use internal satellite IDs (e.g. 'L76' for SWOT) that differ
    from the directory code ('swo').  Since every file was already fetched from
    the correct satellite's directory, we accept whichever sp3_sat appears in
    the file rather than filtering by the directory code.
    """
    frames = []
    for p in sp3_paths:
        df = parse_sp3_positions(p)
        if df.empty:
            continue
        # Each IDS single-satellite SP3 file contains exactly one sp3_sat value.
        # Accept it directly; do not filter by directory sat_code.
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True).drop_duplicates('epoch').sort_values('epoch')
    return out.reset_index(drop=True)


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────
if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--config',    required=True,  help='path to config.yaml')
    ap.add_argument('--satellite', required=True,  help='e.g. jason-3')
    ap.add_argument('--start',     default=None,   help='ISO8601 UTC start')
    ap.add_argument('--end',       default=None,   help='ISO8601 UTC end')
    ap.add_argument('--force',     action='store_true', help='force re-download')
    args = ap.parse_args()
    paths = download_ids_products(
        args.config, args.satellite,
        start=args.start, end=args.end, force=args.force,
    )
    for p in paths:
        print(p)
