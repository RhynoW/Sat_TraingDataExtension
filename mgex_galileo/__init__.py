"""
mgex_galileo — IGS-MGEX Galileo precise ephemeris (SP3) pipeline.

Responsibilities:
  download  — fetch SP3 files from CODE/GFZ/GRG MGEX servers
  sp3_parser — parse SP3 files into Galileo-only DataFrames
  index     — DuckDB-backed file catalogue with time-range queries
  cli       — command-line entry point
"""
from .download import download_galileo_sp3
from .sp3_parser import parse_sp3_gnss, parse_sp3_galileo
from .index import build_sp3_index, query_sp3_files_for_interval

__all__ = [
    "download_galileo_sp3",
    "parse_sp3_gnss",
    "parse_sp3_galileo",
    "build_sp3_index",
    "query_sp3_files_for_interval",
]
