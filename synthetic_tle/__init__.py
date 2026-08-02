"""synthetic_tle — TLE synthetic data generator for orbital maneuver detection."""

from .elements  import OrbitalElements, MU, RE, J2
from .maneuver  import ManeuverParams, ManeuverType, apply_maneuver
from .formatter import format_tle, tle_to_text
from .noise     import NoiseLevel, add_tle_noise, get_sigma
from .sequence  import (
    generate_sequence,
    generate_training_pair,
    seq_to_tle_text,
    batch_generate,
)

__all__ = [
    "OrbitalElements", "MU", "RE", "J2",
    "ManeuverParams", "ManeuverType", "apply_maneuver",
    "format_tle", "tle_to_text",
    "NoiseLevel", "add_tle_noise", "get_sigma",
    "generate_sequence", "generate_training_pair",
    "seq_to_tle_text", "batch_generate",
]
