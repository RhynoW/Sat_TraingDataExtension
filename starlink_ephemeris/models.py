"""Data models for the Starlink ephemeris pipeline."""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EphemerisMetadata:
    """Metadata for one downloaded/stored ephemeris file version."""

    sat_id: str
    file_start: datetime     # UTC, timezone-aware
    file_end: datetime       # UTC, timezone-aware
    download_time: datetime  # UTC, timezone-aware
    source_url: str
    checksum: str            # SHA-256 hex digest of the raw file bytes


@dataclass
class EphemerisSample:
    """Single state-vector sample from an ephemeris file."""

    sat_id: str
    file_start: datetime  # Foreign key back to EphemerisMetadata.file_start
    t: datetime           # UTC, timezone-aware
    r_x: float            # km  (EME2000 / MEME frame)
    r_y: float            # km
    r_z: float            # km
    v_x: float            # km/s
    v_y: float            # km/s
    v_z: float            # km/s


@dataclass
class DailyManeuverIndicator:
    """Divergence indicator between two successive ephemeris versions."""

    sat_id: str
    day_index: int            # Position of the *newer* file in the sorted list
    file_start_old: datetime  # UTC, timezone-aware
    file_start_new: datetime  # UTC, timezone-aware
    divergence_km: float      # Max |Δr| over the comparison window
    is_candidate_maneuver: bool = field(default=False)
