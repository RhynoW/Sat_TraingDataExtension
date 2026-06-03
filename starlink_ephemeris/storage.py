"""
Download and store Starlink ephemeris files locally.

Directory layout:
    data_root/
        raw/
            {sat_id}/
                {file_start_iso}.txt   # e.g. 2024-01-01T12-00-00Z.txt
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

from .models import EphemerisMetadata
from .parser import parse_ephemeris_file

logger = logging.getLogger(__name__)

# MEME_<norad_id>_<sat_name>_...  →  captures sat_name
_MEME_FILENAME_RE = re.compile(r"MEME_\d+_([A-Za-z0-9-]+)_")


# ------------------------------------------------------------------
# Path helpers
# ------------------------------------------------------------------

def extract_sat_id_from_url(url: str) -> str:
    """
    Infer satellite ID from the Starlink ephemeris URL filename.

    Example URL tail: MEME_62425_STARLINK-32283_..._UNCLASSIFIED.txt
    Returns: "STARLINK-32283"
    """
    filename = url.rstrip("/").split("/")[-1]
    m = _MEME_FILENAME_RE.search(filename)
    return m.group(1) if m else Path(filename).stem


def local_path_for(data_root: Path, sat_id: str, file_start: datetime) -> Path:
    """
    Canonical storage path for one ephemeris version.

    Uses hyphens in the time part so the filename is valid on all platforms.
    Example: data_root/raw/STARLINK-32283/2024-01-01T12-00-00Z.txt
    """
    ts = file_start.strftime("%Y-%m-%dT%H-%M-%SZ")
    return data_root / "raw" / sat_id / f"{ts}.txt"


# ------------------------------------------------------------------
# Download
# ------------------------------------------------------------------

def download_ephemeris(
    url: str,
    data_root: Path,
    timeout: int = 60,
) -> tuple[EphemerisMetadata, Path]:
    """
    Download an ephemeris file and save it under data_root/raw/{sat_id}/.

    Skips the write if a file with an identical SHA-256 already exists at
    the target path (idempotent re-runs).

    Returns
    -------
    (EphemerisMetadata, local_path)

    Raises
    ------
    requests.HTTPError  on non-2xx responses.
    """
    sat_id = extract_sat_id_from_url(url)
    download_time = datetime.now(tz=timezone.utc)

    print(f"[download] {url}")
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    raw_bytes = response.content

    # Stage under a temp name so we can parse to learn file_start before naming
    stage_dir = data_root / "raw" / sat_id
    stage_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = stage_dir / "_tmp_download.txt"

    try:
        tmp_path.write_bytes(raw_bytes)
        metadata, _ = parse_ephemeris_file(
            tmp_path, sat_id=sat_id, source_url=url, download_time=download_time
        )

        final_path = local_path_for(data_root, metadata.sat_id, metadata.file_start)
        final_path.parent.mkdir(parents=True, exist_ok=True)

        # Idempotency check: skip if identical content already stored
        if final_path.exists():
            existing_checksum = hashlib.sha256(final_path.read_bytes()).hexdigest()
            if existing_checksum == metadata.checksum:
                logger.info("Identical file already at %s — skipping.", final_path)
                print(f"  [skip] identical content already at {final_path}")
                tmp_path.unlink(missing_ok=True)
                return metadata, final_path

        tmp_path.replace(final_path)
        print(f"  [saved] {final_path}")
        return metadata, final_path

    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def download_batch(
    urls: list[str],
    data_root: Path,
    timeout: int = 60,
) -> list[tuple[EphemerisMetadata, Path]]:
    """Download multiple ephemeris URLs, collecting (metadata, path) pairs."""
    results: list[tuple[EphemerisMetadata, Path]] = []
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] ", end="")
        try:
            results.append(download_ephemeris(url, data_root, timeout=timeout))
        except Exception as exc:
            logger.error("Failed to download %s: %s", url, exc)
            print(f"  [error] {exc}")
    return results


# ------------------------------------------------------------------
# Load
# ------------------------------------------------------------------

def load_all_ephemerides(
    sat_id: str,
    data_root: Path,
) -> list[tuple[EphemerisMetadata, "pd.DataFrame"]]:
    """
    Parse every stored .txt file for `sat_id` and return a list of
    (EphemerisMetadata, DataFrame) pairs sorted by file_start ascending.

    Files that fail to parse are logged and skipped.
    """
    import pandas as pd  # local import keeps module-level imports minimal

    sat_dir = data_root / "raw" / sat_id
    if not sat_dir.exists():
        logger.warning("No data directory found: %s", sat_dir)
        return []

    txt_files = [p for p in sat_dir.glob("*.txt") if not p.name.startswith("_")]
    if not txt_files:
        logger.warning("No .txt files in %s", sat_dir)
        return []

    results: list[tuple[EphemerisMetadata, pd.DataFrame]] = []
    for path in sorted(txt_files):
        try:
            meta, df = parse_ephemeris_file(path, sat_id=sat_id)
            results.append((meta, df))
        except Exception as exc:
            logger.warning("Skipping %s — parse error: %s", path.name, exc)

    results.sort(key=lambda pair: pair[0].file_start)
    print(f"[load] {len(results)} ephemeris versions for {sat_id}")
    return results
