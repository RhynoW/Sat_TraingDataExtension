"""
starlink_ephemeris
==================
Prototype pipeline for downloading, parsing, and analysing Starlink
Modified ITC (MEME) ephemeris files to detect orbital maneuvers.

Public API
----------
Models:
    EphemerisMetadata, EphemerisSample, DailyManeuverIndicator

Parsing / storage:
    parse_ephemeris_file, download_ephemeris, download_batch, load_all_ephemerides

Analysis:
    interpolate_state, compute_state_divergence_indicator,
    compute_daily_indicators, flag_maneuver_candidates

High-level:
    analyze_satellite_maneuvers
"""
from .models import DailyManeuverIndicator, EphemerisMetadata, EphemerisSample
from .parser import parse_ephemeris_file
from .storage import (
    download_batch,
    download_ephemeris,
    extract_sat_id_from_url,
    load_all_ephemerides,
    local_path_for,
)
from .analysis import (
    compute_daily_indicators,
    compute_state_divergence_indicator,
    flag_maneuver_candidates,
    interpolate_state,
)
from .pipeline import analyze_satellite_maneuvers
from .downloader import (
    DownloadResult,
    build_meme_url,
    fetch_manifest,
    gps_to_utc,
    load_catalog,
    parse_meme_url,
    run_daily_batch,
    scan_for_new_url,
    seed_from_manifest,
    seed_url_registry,
    utc_to_gps,
)

__all__ = [
    # models
    "EphemerisMetadata",
    "EphemerisSample",
    "DailyManeuverIndicator",
    # parser
    "parse_ephemeris_file",
    # storage
    "extract_sat_id_from_url",
    "local_path_for",
    "download_ephemeris",
    "download_batch",
    "load_all_ephemerides",
    # analysis
    "interpolate_state",
    "compute_state_divergence_indicator",
    "compute_daily_indicators",
    "flag_maneuver_candidates",
    # pipeline
    "analyze_satellite_maneuvers",
    # downloader
    "DownloadResult",
    "build_meme_url",
    "fetch_manifest",
    "gps_to_utc",
    "load_catalog",
    "parse_meme_url",
    "run_daily_batch",
    "scan_for_new_url",
    "seed_from_manifest",
    "seed_url_registry",
    "utc_to_gps",
]
