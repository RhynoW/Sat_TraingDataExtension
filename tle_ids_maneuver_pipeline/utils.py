from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone, timedelta
import os
import re
import yaml
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def load_config(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_dt(x: str) -> datetime:
    x = x.replace('Z', '+00:00')
    return datetime.fromisoformat(x).astimezone(timezone.utc)


def daterange(start: datetime, end: datetime, step_seconds: int):
    t = start
    step = timedelta(seconds=step_seconds)
    while t <= end:
        yield t
        t += step


def slugify(name: str) -> str:
    s = name.strip().lower()
    s = s.replace('_', '-')
    s = re.sub(r'\s+', '-', s)
    s = re.sub(r'[^a-z0-9\-]+', '', s)
    s = re.sub(r'-+', '-', s).strip('-')
    aliases = {
        'topexposeidon': 'topex-poseidon',
        'topex-poseidonids': 'topex-poseidon',
        'cryosat-2ids': 'cryosat-2',
        'envisatids': 'envisat',
        'hy-2aids': 'hy-2a',
        'hy-2cids': 'hy-2c',
        'hy-2dids': 'hy-2d',
        'jason-1ids': 'jason-1',
        'jason-2ids': 'jason-2',
        'jason-3ids': 'jason-3',
        'saralids': 'saral',
        'sentinel-3aids': 'sentinel-3a',
        'sentinel-3bids': 'sentinel-3b',
        'sentinel-6aids': 'sentinel-6a',
        'swotids': 'swot',
    }
    return aliases.get(s, s)


def build_session(username: str | None = None, password: str | None = None) -> requests.Session:
    session = requests.Session()
    retry = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    session.headers.update({'User-Agent': 'tle-ids-maneuver-pipeline/0.1'})
    if username and password:
        session.auth = (username, password)
    return session


def get_env_credential(name: str | None) -> str | None:
    if not name:
        return None
    return os.environ.get(name)
