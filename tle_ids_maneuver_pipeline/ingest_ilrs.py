from __future__ import annotations
import pandas as pd
from bs4 import BeautifulSoup
from utils import load_config, build_session, slugify, ensure_dir


def parse_ilrs_maneuver_page(html: str) -> pd.DataFrame:
    soup = BeautifulSoup(html, 'lxml')
    lines = [x.strip() for x in soup.get_text('\n').splitlines() if x.strip()]
    sats = []
    in_section = False
    for line in lines:
        if line == 'Maneuver Histories':
            in_section = True
            continue
        if in_section and line == 'Attitude Histories':
            break
        if in_section and line.startswith('- '):
            name = line[2:].strip()
            norm = slugify(name)
            sats.append({'raw_name': name, 'satellite': norm, 'source': 'ILRS maneuver page'})
    return pd.DataFrame(sats).drop_duplicates()


def fetch_ilrs_satellites(config_path: str) -> pd.DataFrame:
    cfg = load_config(config_path)
    session = build_session()
    r = session.get(cfg['ilrs']['maneuver_url'], timeout=60)
    r.raise_for_status()
    df = parse_ilrs_maneuver_page(r.text)
    out_dir = ensure_dir(cfg['project']['output_dir'])
    out = out_dir / 'ilrs_maneuver_satellites.csv'
    df.to_csv(out, index=False)
    return df


if __name__ == '__main__':
    df = fetch_ilrs_satellites('config.yaml')
    print(df)
