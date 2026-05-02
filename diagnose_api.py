"""
Diagnostic v3: find the per-NORAD-ID ephemeris URL pattern.

Known facts from earlier runs:
  - GCS bucket listing → 403 VPC-blocked (dead end)
  - api.starlink.com/public-files/ephemerides/<full-filename> → 200 (works)
  - File format: keyword:value header + yyyyDOYhhmmss.sss data lines

Now testing: can we reach the file with ONLY the NORAD ID?
"""
import re, json
from datetime import datetime, timedelta

import requests

BASE     = "https://api.starlink.com/public-files/ephemerides/"
TIMEOUT  = 20
NORAD    = 62425   # known-working satellite
MEME_RE  = re.compile(r'MEME_\d+_[\w-]+_\d+_\w+_\d+_UNCLASSIFIED\.txt')


def probe(label: str, url: str, method: str = "GET") -> requests.Response | None:
    print(f"\n{'='*68}")
    print(f"  [{method}] {label}")
    print(f"  {url}")
    print('='*68)
    try:
        fn = requests.get if method == "GET" else requests.head
        r = fn(url, timeout=TIMEOUT, allow_redirects=True)
        ct = r.headers.get('Content-Type', '?')
        print(f"  HTTP {r.status_code}  |  {ct}  |  {len(r.content)} bytes")
        if r.status_code == 200:
            hits = MEME_RE.findall(r.text)
            if hits:
                print(f"  MEME hits: {len(hits)}  first={hits[0]}")
            else:
                print(f"  Body[:400]: {r.text[:400]}")
        else:
            print(f"  Body[:200]: {r.text[:200]}")
        return r
    except Exception as exc:
        print(f"  ERROR: {exc}")
        return None


def gps_seconds_to_utc(gps_s: int) -> str:
    """Convert GPS seconds (from Jan 6 1980) to UTC string."""
    gps_epoch = datetime(1980, 1, 6)
    dt = gps_epoch + timedelta(seconds=gps_s)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC (GPS, no leap-sec correction)")


if __name__ == "__main__":
    print(f"\n=== ID interpretation ===")
    print(f"1461965880 as GPS seconds → {gps_seconds_to_utc(1461965880)}")
    print(f"1212137    → probably an internal SpaceX object sequence ID")

    # ── A: per-NORAD REST-style patterns ──────────────────────────────────────
    for path in [
        f"{NORAD}",
        f"{NORAD}/",
        f"{NORAD}/latest",
        f"latest/{NORAD}",
        f"?norad_id={NORAD}",
        f"?noradId={NORAD}",
        f"?sat={NORAD}",
    ]:
        probe(f"per-NORAD pattern: {path}", BASE + path, "HEAD")

    # ── B: Space Safety portal API ────────────────────────────────────────────
    for url in [
        "https://api.starlink.com/public-files/satellites",
        "https://api.starlink.com/public-files/catalog",
        "https://api.starlink.com/public-files/ephemerides/index.json",
        "https://api.starlink.com/public-files/ephemerides/manifest.json",
        "https://www.space-safety.starlink.com/",
        "https://api.space-safety.starlink.com/satellites",
        "https://api.space-safety.starlink.com/ephemerides",
    ]:
        probe(url.split("/")[-1] or url.split("/")[-2], url, "HEAD")

    # ── C: Confirm known-working URL still live ───────────────────────────────
    r = probe(
        "known-working MEME file (full GET)",
        BASE + "MEME_62425_STARLINK-32283_1212137_Operational_1461965880_UNCLASSIFIED.txt"
    )
    if r and r.status_code == 200:
        lines = r.text.splitlines()[:8]
        print("\n  First 8 lines of file:")
        for ln in lines:
            print(f"    {ln}")
