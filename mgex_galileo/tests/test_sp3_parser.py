"""
Unit tests for mgex_galileo.sp3_parser.

Run with:
    python -m pytest mgex_galileo/tests/ -v
or:
    python mgex_galileo/tests/test_sp3_parser.py
"""
from __future__ import annotations

import gzip
import math
import sys
import tempfile
from pathlib import Path

# Allow running directly without installing the package
_PKG_ROOT = Path(__file__).resolve().parents[2]
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from mgex_galileo.sp3_parser import parse_sp3_galileo

SAMPLE_SP3 = Path(__file__).parent / "sample_galileo.sp3"


# ── helpers ────────────────────────────────────────────────────────────────────

def _assert_close(a: float, b: float, tol: float = 1.0, label: str = "") -> None:
    assert abs(a - b) <= tol, f"{label}: {a} vs {b} (tol={tol})"


# ── tests ──────────────────────────────────────────────────────────────────────

def test_basic_parse() -> None:
    df = parse_sp3_galileo(SAMPLE_SP3)
    assert not df.empty, "DataFrame should not be empty"

    expected_cols = {
        "sat_id", "t_gps", "x_m", "y_m", "z_m",
        "v_x_mps", "v_y_mps", "v_z_mps", "ac",
        "file_epoch_start", "file_epoch_end",
    }
    assert expected_cols.issubset(df.columns), f"Missing columns: {expected_cols - set(df.columns)}"


def test_galileo_only() -> None:
    df = parse_sp3_galileo(SAMPLE_SP3)
    # All sat_ids must start with 'E'
    bad = df[~df["sat_id"].str.startswith("E")]
    assert bad.empty, f"Non-Galileo rows found: {bad['sat_id'].unique()}"


def test_satellite_count() -> None:
    df = parse_sp3_galileo(SAMPLE_SP3)
    sat_ids = df["sat_id"].unique()
    # Sample file has E01, E02, E11, E12, E30
    assert len(sat_ids) == 5, f"Expected 5 satellites, got {len(sat_ids)}: {sorted(sat_ids)}"
    assert "E01" in sat_ids
    assert "E30" in sat_ids


def test_epoch_count() -> None:
    df = parse_sp3_galileo(SAMPLE_SP3)
    epochs = df["t_gps"].nunique()
    # Sample file has 3 epochs
    assert epochs == 3, f"Expected 3 epochs, got {epochs}"


def test_position_units() -> None:
    df = parse_sp3_galileo(SAMPLE_SP3)
    e01 = df[df["sat_id"] == "E01"].iloc[0]

    # SP3 stores in km; parser must convert to metres
    # E01 first epoch: x=4873.408524 km → 4_873_408.524 m
    _assert_close(e01["x_m"], 4_873_408.524, tol=0.1, label="E01 x_m")
    _assert_close(e01["y_m"], 23_434_834.842, tol=0.1, label="E01 y_m")
    _assert_close(e01["z_m"], -10_481_940.600, tol=0.1, label="E01 z_m")


def test_velocity_units() -> None:
    df = parse_sp3_galileo(SAMPLE_SP3)
    e01 = df[(df["sat_id"] == "E01") & (df["t_gps"] == df["t_gps"].min())].iloc[0]

    # SP3 velocity in dm/s; parser must convert to m/s (*0.1)
    # VE01: 3847.534500 dm/s → 384.7534500 m/s
    assert not math.isnan(e01["v_x_mps"]), "v_x_mps should not be NaN for E01 epoch 0"
    _assert_close(e01["v_x_mps"], 384.75345, tol=0.0001, label="E01 v_x_mps")


def test_missing_velocity_is_nan() -> None:
    df = parse_sp3_galileo(SAMPLE_SP3)
    # Epochs 2 and 3 have no V records → velocities should be NaN
    later = df[df["t_gps"] > df["t_gps"].min()]
    assert later["v_x_mps"].isna().all(), (
        "Later epochs (no V records) should have NaN velocities"
    )


def test_epoch_timestamps() -> None:
    df = parse_sp3_galileo(SAMPLE_SP3)
    import pandas as pd

    t0 = pd.Timestamp("2023-01-01 00:00:00", tz="UTC")
    t1 = pd.Timestamp("2023-01-01 00:15:00", tz="UTC")
    t2 = pd.Timestamp("2023-01-01 00:30:00", tz="UTC")

    actual_epochs = sorted(df["t_gps"].unique())
    assert actual_epochs[0] == t0, f"First epoch mismatch: {actual_epochs[0]}"
    assert actual_epochs[1] == t1
    assert actual_epochs[2] == t2


def test_coverage_window() -> None:
    df = parse_sp3_galileo(SAMPLE_SP3)
    import pandas as pd

    assert df["file_epoch_start"].iloc[0] == pd.Timestamp("2023-01-01 00:00:00", tz="UTC")
    assert df["file_epoch_end"].iloc[0] == pd.Timestamp("2023-01-01 00:30:00", tz="UTC")


def test_ac_inferred_from_filename() -> None:
    df = parse_sp3_galileo(SAMPLE_SP3)
    # sample_galileo.sp3 doesn't match any AC prefix → UNKN
    assert df["ac"].iloc[0] == "UNKN"


def test_gfz_ac_inference() -> None:
    from mgex_galileo.sp3_parser import _infer_ac

    assert _infer_ac(Path("GFZ0MGXRAP_2023001.SP3")) == "GFZ"
    assert _infer_ac(Path("COD0MGXFIN_2023001.SP3")) == "COD"
    assert _infer_ac(Path("gbm22421.sp3")) == "GFZ"
    assert _infer_ac(Path("com20201.sp3")) == "COD"


def test_gz_file() -> None:
    """Parser should transparently handle .gz-compressed SP3 files."""
    with tempfile.NamedTemporaryFile(suffix=".sp3.gz", delete=False) as tmp:
        gz_path = Path(tmp.name)

    try:
        with gzip.open(gz_path, "wt", encoding="ascii") as out:
            out.write(SAMPLE_SP3.read_text(encoding="ascii"))

        df = parse_sp3_galileo(gz_path)
        assert not df.empty
        assert df["sat_id"].nunique() == 5
    finally:
        gz_path.unlink(missing_ok=True)


def test_meo_orbit_sanity() -> None:
    """Galileo orbit radius should be ~29,600 km (MEO)."""
    import numpy as np

    df = parse_sp3_galileo(SAMPLE_SP3)
    radii_km = np.sqrt(df["x_m"]**2 + df["y_m"]**2 + df["z_m"]**2) / 1000.0

    mean_r = radii_km.mean()
    # Galileo MEO: ~29,600 km; our synthetic positions may differ, so just
    # check they're in a plausible MEO range (20,000–35,000 km)
    assert 20_000 < mean_r < 35_000, (
        f"Mean orbit radius {mean_r:.0f} km is outside plausible MEO range"
    )


# ── standalone runner ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_basic_parse,
        test_galileo_only,
        test_satellite_count,
        test_epoch_count,
        test_position_units,
        test_velocity_units,
        test_missing_velocity_is_nan,
        test_epoch_timestamps,
        test_coverage_window,
        test_ac_inferred_from_filename,
        test_gfz_ac_inference,
        test_gz_file,
        test_meo_orbit_sanity,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {t.__name__}  →  {exc}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
