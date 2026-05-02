"""
Batch downloader for daily Starlink MEME ephemeris acquisition.

URL mechanics
-------------
SpaceX hosts files at:
    https://api.starlink.com/public-files/ephemerides/
    MEME_{norad_id}_{sat_name}_{obj_id}_{status}_{gps_stop}_UNCLASSIFIED.txt

Where:
    norad_id   — NORAD catalog number (known)
    sat_name   — e.g. STARLINK-32283 (from Space-Track or file header)
    obj_id     — SpaceX-internal satellite ID, **fixed per satellite**
    gps_stop   — GPS seconds (from 1980-01-06) of the ephemeris stop time
                 Formula: int((utc_stop - datetime(1980,1,6)).total_seconds()) + 18
    status     — "Operational" | "Maneuvering" etc.

There is no public listing or per-NORAD REST endpoint.  The strategy is:

1. Seed phase  (once per satellite):
   Provide a known URL via ``seed_url_registry()``.  The downloader fetches
   the file, extracts sat_name, obj_id, and the stop time, and persists them
   in ``url_registry.csv``.

2. Daily phase  (automated):
   For each registered satellite, predict the new URL by scanning ±SCAN_RADIUS
   seconds around ``last_gps_stop + 86400`` in SCAN_STEP increments
   (~120 HEAD requests per satellite).  On first hit, download and update the
   registry.
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from .models import EphemerisMetadata
from .storage import download_ephemeris

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

EPHEMERIS_BASE = "https://api.starlink.com/public-files/ephemerides/"
GPS_EPOCH      = datetime(1980, 1, 6, tzinfo=timezone.utc)
LEAP_SECONDS   = 18                    # GPS − UTC as of 2017; update if needed

SCAN_RADIUS_S  = 3 * 3600             # ±3 hours around prediction
SCAN_STEP_S    = 60                   # step size in seconds (matches file step_size)

_MEME_FNAME_RE = re.compile(
    r"MEME_(\d+)_([\w-]+)_(\d+)_([\w]+)_(\d+)_UNCLASSIFIED\.txt",
    re.IGNORECASE,
)


# ── GPS ↔ UTC helpers ─────────────────────────────────────────────────────────

def utc_to_gps(dt_utc: datetime) -> int:
    """Convert a UTC datetime to GPS seconds (from 1980-01-06)."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return int((dt_utc - GPS_EPOCH).total_seconds()) + LEAP_SECONDS


def gps_to_utc(gps_s: int) -> datetime:
    """Convert GPS seconds (from 1980-01-06) to a UTC datetime."""
    return GPS_EPOCH + timedelta(seconds=gps_s - LEAP_SECONDS)


# ── URL helpers ───────────────────────────────────────────────────────────────

def build_meme_url(
    norad_id: int,
    sat_name: str,
    obj_id: int,
    gps_stop: int,
    status: str = "Operational",
) -> str:
    fname = (
        f"MEME_{norad_id}_{sat_name}_{obj_id}_{status}_{gps_stop}_UNCLASSIFIED.txt"
    )
    return EPHEMERIS_BASE + fname


def parse_meme_url(url: str) -> dict | None:
    """
    Extract (norad_id, sat_name, obj_id, status, gps_stop) from a MEME URL.
    Returns None if the URL doesn't match the pattern.
    """
    m = _MEME_FNAME_RE.search(url)
    if not m:
        return None
    return {
        "norad_id": int(m.group(1)),
        "sat_name": m.group(2),
        "obj_id":   int(m.group(3)),
        "status":   m.group(4),
        "gps_stop": int(m.group(5)),
    }


# ── URL Registry ──────────────────────────────────────────────────────────────

_REGISTRY_COLS = ["norad_id", "sat_name", "obj_id", "status",
                  "last_gps_stop", "last_url", "last_updated"]


def load_url_registry(registry_csv: Path) -> pd.DataFrame:
    """Load the URL registry, creating an empty one if absent."""
    if not registry_csv.exists():
        return pd.DataFrame(columns=_REGISTRY_COLS)
    df = pd.read_csv(registry_csv, dtype={"norad_id": int, "obj_id": int, "last_gps_stop": int})
    for col in _REGISTRY_COLS:
        if col not in df.columns:
            df[col] = None
    return df


def save_url_registry(df: pd.DataFrame, registry_csv: Path) -> None:
    registry_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(registry_csv, index=False)


def upsert_registry(df: pd.DataFrame, entry: dict) -> pd.DataFrame:
    """Insert or update a registry row for entry['norad_id']."""
    mask = df["norad_id"] == entry["norad_id"]
    row  = pd.DataFrame([entry])
    if mask.any():
        df = df[~mask]
    return pd.concat([df, row], ignore_index=True)


def seed_url_registry(
    url: str,
    registry_csv: Path,
    data_root: Path,
    timeout: int = 60,
) -> dict:
    """
    Download the file at `url`, parse the MEME filename and file header to
    extract sat_name, obj_id, and gps_stop, then persist to the URL registry.

    Call this once per satellite to bootstrap daily auto-download.
    Returns the registry entry dict.
    """
    parsed = parse_meme_url(url)
    if parsed is None:
        raise ValueError(f"URL does not match MEME filename pattern: {url}")

    _, local_path = download_ephemeris(url, data_root, timeout=timeout)

    # gps_stop may differ slightly; re-derive from the file's actual stop time
    from .parser import parse_ephemeris_file
    meta2, _ = parse_ephemeris_file(local_path, sat_id=parsed["sat_name"], source_url=url)
    gps_stop = utc_to_gps(meta2.file_end)

    entry = {
        "norad_id":    parsed["norad_id"],
        "sat_name":    parsed["sat_name"],
        "obj_id":      parsed["obj_id"],
        "status":      parsed["status"],
        "last_gps_stop": gps_stop,
        "last_url":    url,
        "last_updated": datetime.now(tz=timezone.utc).isoformat(),
    }

    df = load_url_registry(registry_csv)
    df = upsert_registry(df, entry)
    save_url_registry(df, registry_csv)
    print(f"[registry] Seeded NORAD {parsed['norad_id']}  obj_id={parsed['obj_id']}")
    return entry


# ── Manifest-based bulk seeding ───────────────────────────────────────────────

MANIFEST_URL = "https://api.starlink.com/public-files/ephemerides/MANIFEST.txt"


def fetch_manifest(timeout: int = 30) -> list[str]:
    """Download MANIFEST.txt and return a list of MEME filenames."""
    r = requests.get(MANIFEST_URL, timeout=timeout)
    r.raise_for_status()
    return [line.strip() for line in r.text.splitlines() if line.strip()]


def seed_from_manifest(
    catalog_csv: Path,
    registry_csv: Path,
    timeout: int = 30,
) -> dict[int, dict]:
    """
    Download MANIFEST.txt, cross-reference with the catalog, and populate the
    URL registry for every matched satellite — without downloading ephemeris files.

    Returns a dict mapping norad_id → registry entry for every seeded satellite.
    Already-registered satellites are skipped unless the manifest has a newer
    gps_stop value.
    """
    print("[manifest] Fetching manifest …")
    filenames = fetch_manifest(timeout=timeout)
    print(f"[manifest] {len(filenames)} entries in manifest.")

    # Build norad_id → best (highest gps_stop) parsed entry from manifest
    manifest_map: dict[int, dict] = {}
    for fname in filenames:
        parsed = parse_meme_url(EPHEMERIS_BASE + fname)
        if parsed is None:
            continue
        nid = parsed["norad_id"]
        if nid not in manifest_map or parsed["gps_stop"] > manifest_map[nid]["gps_stop"]:
            manifest_map[nid] = parsed

    catalog = load_catalog(catalog_csv)
    catalog_ids = set(int(r["norad_id"]) for _, r in catalog.iterrows())

    matches = catalog_ids & set(manifest_map.keys())
    print(f"[manifest] {len(matches)} catalog satellites found in manifest "
          f"(of {len(catalog_ids)} in catalog).")

    df_reg = load_url_registry(registry_csv)
    existing = {int(r["norad_id"]): int(r["last_gps_stop"])
                for _, r in df_reg.iterrows()}

    seeded: dict[int, dict] = {}
    now_iso = datetime.now(tz=timezone.utc).isoformat()

    for nid in sorted(matches):
        p = manifest_map[nid]
        # Skip if already registered with an equal or newer gps_stop
        if nid in existing and existing[nid] >= p["gps_stop"]:
            continue
        entry = {
            "norad_id":      nid,
            "sat_name":      p["sat_name"],
            "obj_id":        p["obj_id"],
            "status":        p["status"],
            "last_gps_stop": p["gps_stop"],
            "last_url":      EPHEMERIS_BASE + f"MEME_{nid}_{p['sat_name']}_{p['obj_id']}_{p['status']}_{p['gps_stop']}_UNCLASSIFIED.txt",
            "last_updated":  now_iso,
        }
        df_reg = upsert_registry(df_reg, entry)
        seeded[nid] = entry

    if seeded:
        save_url_registry(df_reg, registry_csv)
        print(f"[manifest] Seeded/updated {len(seeded)} registry entries → {registry_csv}")
    else:
        print("[manifest] No new entries to add.")

    unmatched = catalog_ids - set(manifest_map.keys())
    if unmatched:
        print(f"[manifest] {len(unmatched)} catalog satellites NOT in manifest: "
              f"{sorted(unmatched)[:10]}{'…' if len(unmatched) > 10 else ''}")

    return seeded


# ── URL discovery via time scan ───────────────────────────────────────────────

def _head_ok(url: str, timeout: int = 10) -> bool:
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        return r.status_code == 200
    except Exception:
        return False


def scan_for_new_url(
    norad_id: int,
    sat_name: str,
    obj_id: int,
    last_gps_stop: int,
    status: str = "Operational",
    radius_s: int = SCAN_RADIUS_S,
    step_s: int = SCAN_STEP_S,
    head_timeout: int = 8,
    inter_delay_s: float = 0.05,
) -> str | None:
    """
    Scan a time window to find the current day's ephemeris URL.

    Searches GPS stop times in [last_gps_stop + 86400 - radius_s,
                                last_gps_stop + 86400 + radius_s]
    in `step_s` increments.  Returns the first 200-OK URL, or None.
    """
    centre  = last_gps_stop + 86400
    lo, hi  = centre - radius_s, centre + radius_s
    n_steps = (hi - lo) // step_s + 1

    logger.debug(
        "Scanning %d steps for NORAD %d  centre=%s",
        n_steps, norad_id, gps_to_utc(centre).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    # Scan outward from the centre for faster hits
    offsets = sorted(range(-radius_s, radius_s + 1, step_s), key=abs)

    for off in offsets:
        gps_try = centre + off
        url     = build_meme_url(norad_id, sat_name, obj_id, gps_try, status)
        if _head_ok(url, timeout=head_timeout):
            logger.info("Found URL for NORAD %d  gps_stop=%d", norad_id, gps_try)
            return url
        if inter_delay_s:
            time.sleep(inter_delay_s)
    return None


# ── Catalog helpers ───────────────────────────────────────────────────────────

def load_catalog(csv_path: Path) -> pd.DataFrame:
    """Load and deduplicate the satellite catalog CSV."""
    df = pd.read_csv(csv_path, dtype={"norad_id": int})
    required = {"norad_id", "mission_batch", "launch_date", "sat_count"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Catalog missing columns: {missing}")
    before = len(df)
    df = df.drop_duplicates(subset="norad_id", keep="first").reset_index(drop=True)
    if len(df) < before:
        logger.info("Dropped %d duplicate NORAD IDs.", before - len(df))
    return df


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class DownloadResult:
    norad_id: int
    mission_batch: str
    status: str                          # "ok" | "skip" | "no_registry" | "no_url" | "error"
    sat_id: str = ""
    local_path: str = ""
    error: str = ""
    run_date: date = field(default_factory=lambda: datetime.now(tz=timezone.utc).date())


# ── Core batch download ───────────────────────────────────────────────────────

def _download_one_registered(
    reg_row: pd.Series,
    mission_batch: str,
    data_root: Path,
    download_timeout: int,
    scan_radius_s: int,
    scan_step_s: int,
    inter_delay_s: float,
    manifest_url: str | None = None,
) -> tuple[DownloadResult, dict | None]:
    """
    For a satellite that has a registry entry: resolve today's URL and download.

    URL resolution priority:
      1. manifest_url  — passed in from a fresh MANIFEST.txt fetch (preferred)
      2. last_url      — the previously known URL (still served for ~24 h)
      3. time-scan     — ±scan_radius_s around last_gps_stop+86400 (slow fallback)

    Returns (DownloadResult, updated_registry_entry_or_None).
    """
    norad_id   = int(reg_row["norad_id"])
    sat_name   = str(reg_row["sat_name"])
    obj_id     = int(reg_row["obj_id"])
    status     = str(reg_row.get("status", "Operational"))
    last_stop  = int(reg_row["last_gps_stop"])

    url: str | None = None

    if manifest_url:
        # Manifest always reflects currently-served files — use it directly.
        url = manifest_url
    else:
        last_url = str(reg_row.get("last_url", ""))
        if last_url and _head_ok(last_url, timeout=8):
            url = last_url
        else:
            url = scan_for_new_url(
                norad_id, sat_name, obj_id, last_stop,
                status=status,
                radius_s=scan_radius_s, step_s=scan_step_s,
                inter_delay_s=inter_delay_s,
            )

    if url is None:
        return (
            DownloadResult(norad_id=norad_id, mission_batch=mission_batch,
                           status="no_url"),
            None,
        )

    try:
        meta, path = download_ephemeris(url, data_root, timeout=download_timeout)
        gps_stop_new = utc_to_gps(meta.file_end)
        updated = {
            "norad_id": norad_id, "sat_name": sat_name,
            "obj_id": obj_id, "status": status,
            "last_gps_stop": gps_stop_new,
            "last_url": url,
            "last_updated": datetime.now(tz=timezone.utc).isoformat(),
        }
        return (
            DownloadResult(norad_id=norad_id, mission_batch=mission_batch,
                           status="ok", sat_id=meta.sat_id, local_path=str(path)),
            updated,
        )
    except Exception as exc:
        return (
            DownloadResult(norad_id=norad_id, mission_batch=mission_batch,
                           status="error", error=str(exc)),
            None,
        )


def run_daily_batch(
    catalog_csv: Path,
    data_root: Path,
    registry_csv: Path | None = None,
    download_timeout: int = 60,
    max_workers: int = 4,
    inter_request_delay_s: float = 0.05,
    scan_radius_s: int = SCAN_RADIUS_S,
    scan_step_s: int = SCAN_STEP_S,
) -> pd.DataFrame:
    """
    Download the latest ephemeris for every satellite in the catalog that has
    a URL registry entry.

    Satellites without a registry entry are marked ``no_registry`` — seed them
    first with ``seed_url_registry(url, registry_csv, data_root)``.

    Returns a tidy DataFrame with one row per satellite.
    """
    if registry_csv is None:
        registry_csv = data_root / "url_registry.csv"

    catalog  = load_catalog(catalog_csv)
    registry = load_url_registry(registry_csv)
    reg_map  = {int(r["norad_id"]): r for _, r in registry.iterrows()}

    total = len(catalog)
    n_reg = sum(1 for nid in catalog["norad_id"] if int(nid) in reg_map)
    print(f"[batch] {total} satellites in catalog, {n_reg} in registry, "
          f"{total - n_reg} need seeding.")

    results: list[DownloadResult] = []
    registry_updates: list[dict] = []

    # Fetch live manifest once → {norad_id: url} for currently-served files
    print("[batch] Fetching live manifest for current URLs …")
    live_manifest: dict[int, str] = {}
    try:
        for fname in fetch_manifest():
            p = parse_meme_url(EPHEMERIS_BASE + fname)
            if p and p["norad_id"] < 200_000:
                nid = p["norad_id"]
                gps = p["gps_stop"]
                # keep the entry with the highest gps_stop (most recent file)
                existing_url = live_manifest.get(nid)
                if existing_url is None:
                    live_manifest[nid] = EPHEMERIS_BASE + fname
                else:
                    existing_gps = int(existing_url.split("_")[-2])
                    if gps > existing_gps:
                        live_manifest[nid] = EPHEMERIS_BASE + fname
        print(f"[batch] Manifest has {len(live_manifest)} active satellites.")
    except Exception as exc:
        logger.warning("Manifest fetch failed (%s) — falling back to scan.", exc)

    # Satellites with no registry entry → immediate no_registry
    unregistered = [(int(r["norad_id"]), str(r["mission_batch"]))
                    for _, r in catalog.iterrows() if int(r["norad_id"]) not in reg_map]
    for nid, batch in unregistered:
        results.append(DownloadResult(norad_id=nid, mission_batch=batch,
                                      status="no_registry"))

    # Registered satellites → parallel download
    registered_rows = [(reg_map[int(r["norad_id"])], str(r["mission_batch"]))
                       for _, r in catalog.iterrows() if int(r["norad_id"]) in reg_map]

    print(f"[batch] Processing {len(registered_rows)} registered satellites …")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _download_one_registered,
                reg_row, batch, data_root, download_timeout,
                scan_radius_s, scan_step_s, inter_request_delay_s,
                live_manifest.get(int(reg_row["norad_id"])),
            ): int(reg_row["norad_id"])
            for reg_row, batch in registered_rows
        }
        done = 0
        for fut in as_completed(futures):
            res, upd = fut.result()
            results.append(res)
            if upd:
                registry_updates.append(upd)
            done += 1
            tag = {"ok": "✓", "skip": "→", "no_url": "?", "error": "✗"}.get(res.status, "-")
            print(f"  [{done}/{len(registered_rows)}] NORAD {res.norad_id:6d}"
                  f"  {res.status:10s}  {tag}  {res.sat_id or res.error[:60]}")

    # Persist registry updates
    if registry_updates:
        df_reg = load_url_registry(registry_csv)
        for upd in registry_updates:
            df_reg = upsert_registry(df_reg, upd)
        save_url_registry(df_reg, registry_csv)
        print(f"[registry] Updated {len(registry_updates)} entries → {registry_csv}")

    df = pd.DataFrame([vars(r) for r in results])
    df["run_date"] = pd.to_datetime(df["run_date"])

    ok  = (df["status"] == "ok").sum()
    skp = (df["status"] == "skip").sum()
    nu  = (df["status"] == "no_url").sum()
    nr  = (df["status"] == "no_registry").sum()
    err = (df["status"] == "error").sum()
    print(f"\n[batch] ok={ok}  skip={skp}  no_url={nu}  no_registry={nr}  error={err}")
    return df
