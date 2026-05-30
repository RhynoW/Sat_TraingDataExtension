"""integration_test.py — End-to-end pipeline integration test.

Runs in sequence:
  Step 1 — Unit tests (pytest tests/)
  Step 2 — Mini training  (16 NORAD IDs → models_itest/)
  Step 3 — Artifact checks (pkl / feature_names.json / threshold.json)
  Step 4 — predict: auto-read threshold.json (default behavior) × 8 satellites
  Step 5 — predict: --auto-threshold × 8 satellites
  Step 6 — predict: --threshold 0.30  (manual override) × 8 satellites
  Step 7 — CSV output check × 8 satellites
  Step 8 — Summary

Usage
-----
    python integration_test.py

The test uses a separate output directory (models_itest/) so the production
model in models/ is never overwritten.  Temporary prediction CSVs are written
to the working directory and removed at the end.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────
# 16 satellites with events spread across train / val / test periods.
_TRAIN_NORAD_IDS = [
    68075, 65878, 68076, 68262, 68079, 56105, 64479, 60104,
    64718, 60315, 64030, 58388, 64475, 64706, 64716, 64037,
]

# 8 satellites to run prediction on (subset of training set)
_PREDICT_NORAD_IDS = [64479, 56105, 68075, 65878, 68076, 68262, 68079, 60104]

_ITEST_OUT_DIR   = "models_itest"
_DB_PATH         = "../space_db.duckdb"
_RESIDUALS_GLOB  = "../data/comparison/residuals_*.csv"

# ── ANSI colours (disabled on Windows if TERM not set) ────────────────────────
_IS_WIN = sys.platform == "win32"
_GREEN  = "" if _IS_WIN else "\033[32m"
_RED    = "" if _IS_WIN else "\033[31m"
_YELLOW = "" if _IS_WIN else "\033[33m"
_BOLD   = "" if _IS_WIN else "\033[1m"
_RESET  = "" if _IS_WIN else "\033[0m"

Results: list[dict] = []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(label: str, cmd: list[str], *, cwd: str | None = None) -> bool:
    """Run *cmd* as subprocess, print result, append to Results. Returns True on success."""
    t0 = time.time()
    print(f"\n{_BOLD}[{label}]{_RESET}  {' '.join(cmd)}")
    print("-" * 72)

    proc = subprocess.run(cmd, cwd=cwd, capture_output=False)
    elapsed = time.time() - t0
    ok = proc.returncode == 0

    status = f"{_GREEN}PASS{_RESET}" if ok else f"{_RED}FAIL{_RESET}"
    print(f"\n  → {status}  (exit={proc.returncode}  {elapsed:.1f}s)")
    Results.append({"step": label, "ok": ok, "elapsed": elapsed, "cmd": " ".join(cmd)})
    return ok


def _check(label: str, condition: bool, detail: str = "") -> bool:
    """Record a boolean assertion. Returns True on success."""
    ok = bool(condition)
    status = f"{_GREEN}PASS{_RESET}" if ok else f"{_RED}FAIL{_RESET}"
    print(f"  {status}  {label}" + (f" — {detail}" if detail else ""))
    Results.append({"step": label, "ok": ok, "elapsed": 0.0, "cmd": ""})
    return ok


def _print_summary() -> int:
    """Print summary table. Returns 0 if all passed, 1 otherwise."""
    total   = len(Results)
    passed  = sum(1 for r in Results if r["ok"])
    failed  = total - passed

    print()
    print("=" * 72)
    print(f"{_BOLD}INTEGRATION TEST SUMMARY{_RESET}")
    print("-" * 72)
    for r in Results:
        icon = f"{_GREEN}PASS{_RESET}" if r["ok"] else f"{_RED}FAIL{_RESET}"
        t    = f"{r['elapsed']:.1f}s" if r["elapsed"] > 0 else "    "
        print(f"  {icon}  {t:>6}  {r['step']}")
    print("-" * 72)
    colour = _GREEN if failed == 0 else _RED
    print(f"  {colour}{passed}/{total} passed{_RESET}  ({failed} failed)")
    print("=" * 72)
    print()
    return 0 if failed == 0 else 1


def _run_predict_and_rename(
    label: str,
    norad: int,
    pkl_path: Path,
    target: Path,
    *,
    extra_args: list[str] | None = None,
) -> bool:
    """Run predict.py for *norad*, rename the output CSV to *target*.

    predict.py always writes predictions_{norad}_{YYYYMMDD}.csv.  We delete
    that file first so that a pre-existing stale copy is never mistaken for a
    fresh result.  Returns True when *target* exists after the run.
    """
    today_str = date.today().strftime("%Y%m%d")
    src_csv = Path(f"predictions_{norad}_{today_str}.csv")
    if src_csv.exists():
        src_csv.unlink()

    cmd = [
        sys.executable, "predict.py",
        "--norad", str(norad),
        "--db",    _DB_PATH,
        "--model", str(pkl_path),
    ]
    if extra_args:
        cmd.extend(extra_args)
    ok = _run(label, cmd)

    if src_csv.exists():
        src_csv.rename(target)
    return ok and target.exists()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    here = Path(__file__).parent
    os.chdir(here)

    itest_dir = Path(_ITEST_OUT_DIR)

    print(f"\n{_BOLD}{'=' * 72}{_RESET}")
    print(f"{_BOLD}  Orbital_Maneuver_V2  —  Integration Test{_RESET}")
    print(f"{_BOLD}{'=' * 72}{_RESET}")
    print(f"  Train satellites : {len(_TRAIN_NORAD_IDS)} IDs")
    print(f"  Predict satellites: {len(_PREDICT_NORAD_IDS)} IDs")

    # ── Step 1: Unit tests ────────────────────────────────────────────────────
    print(f"\n{_BOLD}STEP 1 — Unit tests{_RESET}")
    _run("pytest", [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"])

    # ── Step 2: Mini training ─────────────────────────────────────────────────
    print(f"\n{_BOLD}STEP 2 — Mini training ({len(_TRAIN_NORAD_IDS)} satellites){_RESET}")
    norad_args = [str(n) for n in _TRAIN_NORAD_IDS]
    _run(
        "train.py",
        [
            sys.executable, "train.py",
            "--norad-ids", *norad_args,
            "--db",        _DB_PATH,
            "--residuals", _RESIDUALS_GLOB,
            "--out-dir",   _ITEST_OUT_DIR,
        ],
    )

    # ── Step 3: Artifact checks ───────────────────────────────────────────────
    print(f"\n{_BOLD}STEP 3 — Artifact checks{_RESET}")
    pkl_path    = itest_dir / "lgbm_maneuver_v1.pkl"
    feat_path   = itest_dir / "feature_names.json"
    thresh_path = itest_dir / "threshold.json"

    _check("models_itest/lgbm_maneuver_v1.pkl exists", pkl_path.exists())
    _check("models_itest/feature_names.json exists",   feat_path.exists())
    _check("models_itest/threshold.json exists",       thresh_path.exists())

    if thresh_path.exists():
        with open(thresh_path, encoding="utf-8") as fh:
            td = json.load(fh)
        _check(
            "threshold.json has 'threshold' key",
            "threshold" in td,
            str(td),
        )
        _check(
            "threshold value in (0, 1)",
            0.0 < float(td.get("threshold", -1)) < 1.0,
            f"value={td.get('threshold')}",
        )
        _check(
            "threshold.json method == 'f_beta_0.5'",
            td.get("method") == "f_beta_0.5",
            f"method={td.get('method')}",
        )

    if feat_path.exists():
        with open(feat_path, encoding="utf-8") as fh:
            feats = json.load(fh)
        _check(
            "feature_names.json is non-empty list",
            isinstance(feats, list) and len(feats) > 0,
            f"{len(feats)} features",
        )

    # Track all CSV paths created across all predict steps
    all_csv_default: dict[int, Path] = {}
    all_csv_auto:    dict[int, Path] = {}
    all_csv_manual:  dict[int, Path] = {}

    # ── Step 4: predict — default (auto-reads threshold.json) ─────────────────
    print(f"\n{_BOLD}STEP 4 — predict: default threshold × {len(_PREDICT_NORAD_IDS)} satellites{_RESET}")
    for norad in _PREDICT_NORAD_IDS:
        target = Path(f"predictions_{norad}_itest_default.csv")
        _run_predict_and_rename(f"predict:default:{norad}", norad, pkl_path, target)
        all_csv_default[norad] = target
        _check(
            f"[{norad}] predictions CSV created (default)",
            target.exists(),
            str(target),
        )

    # ── Step 5: predict — --auto-threshold ────────────────────────────────────
    print(f"\n{_BOLD}STEP 5 — predict: --auto-threshold × {len(_PREDICT_NORAD_IDS)} satellites{_RESET}")
    for norad in _PREDICT_NORAD_IDS:
        target = Path(f"predictions_{norad}_itest_auto.csv")
        _run_predict_and_rename(
            f"predict:--auto-threshold:{norad}", norad, pkl_path, target,
            extra_args=["--auto-threshold"],
        )
        all_csv_auto[norad] = target
        _check(
            f"[{norad}] predictions CSV created (auto-threshold)",
            target.exists(),
        )

    # ── Step 6: predict — --threshold 0.30 ────────────────────────────────────
    print(f"\n{_BOLD}STEP 6 — predict: --threshold 0.30 × {len(_PREDICT_NORAD_IDS)} satellites{_RESET}")
    for norad in _PREDICT_NORAD_IDS:
        target = Path(f"predictions_{norad}_itest_t030.csv")
        _run_predict_and_rename(
            f"predict:--threshold 0.30:{norad}", norad, pkl_path, target,
            extra_args=["--threshold", "0.30"],
        )
        all_csv_manual[norad] = target
        _check(
            f"[{norad}] predictions CSV created (threshold=0.30)",
            target.exists(),
        )

    # ── Step 7: CSV content checks ────────────────────────────────────────────
    print(f"\n{_BOLD}STEP 7 — CSV content checks × {len(_PREDICT_NORAD_IDS)} satellites{_RESET}")
    import pandas as pd

    for norad in _PREDICT_NORAD_IDS:
        for csv_path, variant in [
            (all_csv_default.get(norad), "default"),
            (all_csv_auto.get(norad),    "auto-threshold"),
            (all_csv_manual.get(norad),  "threshold=0.30"),
        ]:
            tag = f"[{norad}] {variant}"
            if csv_path is None or not csv_path.exists():
                _check(f"{tag}: CSV readable", False, "file missing")
                continue
            try:
                df = pd.read_csv(csv_path)
                _check(f"{tag}: has 'p_maneuver' column",  "p_maneuver" in df.columns)
                _check(f"{tag}: has 'alert' column",       "alert" in df.columns)
                _check(f"{tag}: rows > 0",                 len(df) > 0, f"{len(df)} rows")
                _check(f"{tag}: p_maneuver in [0, 1]",
                       df["p_maneuver"].between(0.0, 1.0).all())
            except Exception as exc:
                _check(f"{tag}: CSV readable", False, str(exc))

    # ── Cleanup ───────────────────────────────────────────────────────────────
    print(f"\n{_BOLD}Cleaning up temporary files …{_RESET}")
    all_csvs = (
        list(all_csv_default.values())
        + list(all_csv_auto.values())
        + list(all_csv_manual.values())
    )
    for f in all_csvs:
        if f and f.exists():
            f.unlink()
            print(f"  removed {f}")
    import shutil
    if itest_dir.exists():
        shutil.rmtree(itest_dir)
        print(f"  removed {itest_dir}/")

    return _print_summary()


if __name__ == "__main__":
    sys.exit(main())
