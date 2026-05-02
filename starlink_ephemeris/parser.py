"""
Parse Starlink Modified ITC (MEME) ephemeris files.

Format summary (Starlink Spaceflight Safety / trajectories docs):
  - Optional CCSDS-style header block with KEY = VALUE pairs.
  - Data lines:  yyyyDOYhhmmss.sss  x  y  z  vx  vy  vz
      where DOY is 3-digit day-of-year, positions in km, velocities in km/s.
  - Each data line is followed by 3 covariance lines (21 values total, ignored).

The parser identifies data lines by the timestamp regex and skips everything
else, so it tolerates varying header styles without needing to enumerate them.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .models import EphemerisMetadata

# ------------------------------------------------------------------
# Compiled patterns
# ------------------------------------------------------------------

# Matches a full state-vector line:
#   group 1-5: timestamp components  (year, DOY, HH, MM, SS.sss)
#   groups 6-11: r_x r_y r_z v_x v_y v_z
_FLOAT = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
_DATA_LINE_RE = re.compile(
    r"^(\d{4})(\d{3})(\d{2})(\d{2})(\d{2}\.\d+)"   # timestamp
    r"(?:\s+(" + _FLOAT + r"))"                     # r_x
    r"(?:\s+(" + _FLOAT + r"))"                     # r_y
    r"(?:\s+(" + _FLOAT + r"))"                     # r_z
    r"(?:\s+(" + _FLOAT + r"))"                     # v_x
    r"(?:\s+(" + _FLOAT + r"))"                     # v_y
    r"(?:\s+(" + _FLOAT + r"))"                     # v_z
)

# CCSDS-style header: KEY = VALUE
_KV_EQ_RE = re.compile(r"^\s*([\w_]+)\s*=\s*(.+)")
# MEME-style header: key:value  (e.g. "ephemeris_start:2026-05-01 21:37:42 UTC")
_KV_COLON_RE = re.compile(r"^\s*([\w_]+)\s*:\s*(.+)")

# MEME keyword aliases → canonical name used internally
_MEME_KEY_MAP = {
    "EPHEMERIS_START": "START_TIME",
    "EPHEMERIS_STOP":  "STOP_TIME",
    "CREATED":         "CREATION_DATE",
    "OBJECT_NAME":     "OBJECT_NAME",   # pass-through
}

# Lines that are not key:value pairs in the MEME header (e.g. frame name)
_IGNORE_HEADER_WORDS = {"UVW", "EME2000", "ITRF", "GCRS", "DATA_START", "DATA_STOP",
                         "META_START", "META_STOP"}


# ------------------------------------------------------------------
# Timestamp helpers
# ------------------------------------------------------------------

def _itc_timestamp_to_dt(year: str, doy: str, hh: str, mm: str, ss_frac: str) -> datetime:
    """Convert Modified ITC timestamp components to a UTC-aware datetime."""
    ss = float(ss_frac)
    s_int = int(ss)
    microseconds = round((ss - s_int) * 1_000_000)
    base = datetime(int(year), 1, 1, tzinfo=timezone.utc) + timedelta(days=int(doy) - 1)
    return base.replace(hour=int(hh), minute=int(mm), second=s_int, microsecond=microseconds)


def _parse_ccsds_datetime(s: str) -> datetime | None:
    """
    Parse datetime strings to a UTC-aware datetime.

    Handles:
      - CCSDS DOY: yyyy-DOYThh:mm:ss.sss
      - ISO-8601:  yyyy-mm-ddThh:mm:ss[.f]
      - MEME plain: yyyy-mm-dd hh:mm:ss UTC
    """
    s = s.strip()
    # Strip trailing " UTC" or "+00:00"
    for suffix in (" UTC", "+00:00", "Z"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()

    # yyyy-DOYThh:mm:ss.sss
    m = re.match(r"^(\d{4})-(\d{3})T(\d{2}):(\d{2}):(\d{2})\.(\d+)$", s)
    if m:
        yr, doy, hh, mn, ss, frac = m.groups()
        us = int(frac.ljust(6, "0")[:6])
        base = datetime(int(yr), 1, 1, tzinfo=timezone.utc) + timedelta(days=int(doy) - 1)
        return base.replace(hour=int(hh), minute=int(mn), second=int(ss), microsecond=us)

    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def parse_ephemeris_file(
    path: Path,
    sat_id: str,
    source_url: str = "",
    download_time: datetime | None = None,
) -> tuple[EphemerisMetadata, pd.DataFrame]:
    """
    Parse a Modified ITC Starlink ephemeris file.

    Returns
    -------
    (EphemerisMetadata, DataFrame)
        DataFrame columns: t, r_x, r_y, r_z, v_x, v_y, v_z
        All timestamps are UTC-aware.
    """
    raw_bytes = path.read_bytes()
    checksum = hashlib.sha256(raw_bytes).hexdigest()
    text = raw_bytes.decode("utf-8", errors="replace")

    if download_time is None:
        download_time = datetime.now(tz=timezone.utc)

    header_kv: dict[str, str] = {}
    records: list[dict] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Skip known stand-alone frame/block tokens
        if stripped.upper() in _IGNORE_HEADER_WORDS:
            continue

        # Try data line first (most common branch once we're in the data block)
        m = _DATA_LINE_RE.match(stripped)
        if m:
            t = _itc_timestamp_to_dt(*m.group(1, 2, 3, 4, 5))
            records.append({
                "t":   t,
                "r_x": float(m.group(6)),
                "r_y": float(m.group(7)),
                "r_z": float(m.group(8)),
                "v_x": float(m.group(9)),
                "v_y": float(m.group(10)),
                "v_z": float(m.group(11)),
            })
            continue

        # MEME format: ephemeris_start:2026-05-01 21:37:42 UTC [ephemeris_stop:... step_size:...]
        # A single MEME header line can pack multiple key:value pairs separated by spaces
        # e.g. "ephemeris_start:... ephemeris_stop:... step_size:60"
        for token in re.split(r"\s+(?=[a-zA-Z_]\w*:)", stripped):
            kv_c = _KV_COLON_RE.match(token)
            if kv_c:
                raw_key = kv_c.group(1).upper()
                canonical = _MEME_KEY_MAP.get(raw_key, raw_key)
                header_kv[canonical] = kv_c.group(2).strip()
                continue
            # CCSDS: KEY = VALUE
            kv_eq = _KV_EQ_RE.match(token)
            if kv_eq:
                header_kv[kv_eq.group(1).upper()] = kv_eq.group(2).strip()

    # Build the DataFrame
    if records:
        df = pd.DataFrame(records)
        df["t"] = pd.to_datetime(df["t"], utc=True)
        df.sort_values("t", inplace=True)
        df.reset_index(drop=True, inplace=True)
    else:
        df = pd.DataFrame(columns=["t", "r_x", "r_y", "r_z", "v_x", "v_y", "v_z"])

    # Resolve file_start / file_end from header keywords, fall back to data range
    file_start: datetime
    file_end: datetime

    if records:
        data_start = df["t"].min().to_pydatetime()
        data_end   = df["t"].max().to_pydatetime()
    else:
        now = datetime.now(tz=timezone.utc)
        data_start = data_end = now

    file_start = _parse_ccsds_datetime(header_kv["START_TIME"]) \
        if "START_TIME" in header_kv else data_start
    file_end   = _parse_ccsds_datetime(header_kv["STOP_TIME"]) \
        if "STOP_TIME" in header_kv else data_end

    # Satellite ID: prefer OBJECT_NAME from header, fall back to caller-supplied value
    effective_sat_id = header_kv.get("OBJECT_NAME", sat_id)

    metadata = EphemerisMetadata(
        sat_id=effective_sat_id,
        file_start=file_start,
        file_end=file_end,
        download_time=download_time,
        source_url=source_url,
        checksum=checksum,
    )
    return metadata, df
