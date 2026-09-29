"""
Batch driver: fit estimated TLEs for the Starship Flight 14 Starlink V3 batch
(26 satellites, international designators 2026-225A..2026-225AB) from their
MEME precise ephemerides, and write a single manual_tle_downloads-ready file.

See starlink_ephemeris/meme_to_tle.py for the method and its caveats -- this
is a single-epoch differential-correction fit with a decay-trend-calibrated
B*, good for dashboard/globe visualization, not conjunction-screening grade.

Usage
-----
    python -m starlink_ephemeris.meme_to_tle_batch [--out PATH] [--dry-run]

Output
------
Writes a 3-line-format .tle file (name / line1 / line2 per satellite) to
--out (default: scenario-advanced01/manual_tle_downloads/starlink_v3_flight14_meme_fit.tle).
Also prints a per-satellite validation summary (position error vs held-out
MEME samples) so a bad fit is visible immediately, not silently shipped.

Catalog numbers 339974-339999 are reserved by this project for this batch
(see generate_catalog.py's Flight14-V3 comment) -- SYNTHETIC, not official,
not CelesTrak's own placeholder IDs (those don't fit a TLE's 5-char field;
see meme_to_tle.py's module docstring). Remove the output file once
Space-Track assigns real NORAD numbers for these satellites.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from starlink_ephemeris.meme_to_tle import fit_tle_from_meme  # noqa: E402

SUPPLEMENTAL_URL = "https://celestrak.org/NORAD/elements/supplemental/sup-gp.php"
INTDES_PREFIX = "2026-225"          # Starship Flight 14
SYNTH_CATNR_START = 339974          # reserved block start (26 slots to 339999)
DEFAULT_OUT = (BASE_DIR / "scenario-advanced01" / "manual_tle_downloads"
              / "starlink_v3_flight14_meme_fit.tle")


def _piece_sort_key(object_id: str) -> tuple[int, str]:
    """COSPAR launch-piece order: A..Z (len 1) before AA..AZ (len 2), etc."""
    piece = object_id.rpartition("-")[2]
    return (len(piece), piece)


def fetch_batch_roster() -> list[dict]:
    """Live CelesTrak supplemental roster for this launch, in COSPAR piece order."""
    r = requests.get(SUPPLEMENTAL_URL, params={"INTDES": INTDES_PREFIX, "FORMAT": "json"},
                     timeout=30, headers={"User-Agent": "SatDashboard/1.0"})
    r.raise_for_status()
    items = r.json()
    items.sort(key=lambda o: _piece_sort_key(o["OBJECT_ID"]))
    return items


def download_meme(url: str, dest: Path, timeout: int = 60, retries: int = 3) -> None:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            dest.write_bytes(r.content)
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--cache-dir", type=Path, default=BASE_DIR / "data" / "raw" / "_v3_meme_cache")
    ap.add_argument("--dry-run", action="store_true", help="Fit and print, but do not write --out")
    args = ap.parse_args()

    roster = fetch_batch_roster()
    print(f"[batch] {len(roster)} satellites in {INTDES_PREFIX} roster (CelesTrak supplemental).")
    if len(roster) != 26:
        print(f"[batch] WARNING: expected 26, got {len(roster)} -- roster may have changed "
              f"(re-catalogued, or a new object appeared). Continuing with what's available.")

    args.cache_dir.mkdir(parents=True, exist_ok=True)

    lines_out: list[str] = []
    summary_rows: list[tuple] = []
    for i, item in enumerate(roster):
        name = item["OBJECT_NAME"]
        oid = item["OBJECT_ID"]
        placeholder_norad = item["NORAD_CAT_ID"]
        catnr = SYNTH_CATNR_START + i
        intl_designator = oid.replace("2026-", "26", 1)   # '2026-225A' -> '26225A'

        # Resolve the current MEME URL via the live manifest (fetched once, cached).
        from starlink_ephemeris.downloader import fetch_manifest, parse_meme_url, EPHEMERIS_BASE
        if not hasattr(main, "_manifest_cache"):
            print("[batch] Fetching MANIFEST.txt for current MEME URLs …")
            filenames = fetch_manifest()
            m: dict[int, dict] = {}
            for fn in filenames:
                p = parse_meme_url(EPHEMERIS_BASE + fn)
                if p and (m.get(p["norad_id"], {}).get("gps_stop", -1) < p["gps_stop"]):
                    m[p["norad_id"]] = p
            main._manifest_cache = m  # type: ignore[attr-defined]
        m = main._manifest_cache  # type: ignore[attr-defined]
        p = m.get(placeholder_norad)
        if p is None:
            print(f"  [{i+1}/{len(roster)}] {name}: NOT in current manifest, skipping")
            summary_rows.append((name, oid, catnr, "no_manifest_entry", None, None, {}))
            continue
        real_url = (EPHEMERIS_BASE + f"MEME_{placeholder_norad}_{p['sat_name']}_{p['obj_id']}_"
                   f"{p['status']}_{p['gps_stop']}_UNCLASSIFIED.txt")

        cache_path = args.cache_dir / f"{placeholder_norad}.txt"
        time.sleep(0.3)
        try:
            download_meme(real_url, cache_path)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i+1}/{len(roster)}] {name}: download failed ({exc}), skipping")
            summary_rows.append((name, oid, catnr, "download_failed", None, None, {}))
            continue

        try:
            result = fit_tle_from_meme(cache_path, sat_name=name, catalog_number=catnr,
                                       intl_designator=intl_designator)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i+1}/{len(roster)}] {name}: fit failed ({exc}), skipping")
            summary_rows.append((name, oid, catnr, "fit_failed", None, None, {}))
            continue

        lines_out.append(f"0 {name}")
        lines_out.append(result.line1)
        lines_out.append(result.line2)
        max_err = max(result.validation_km.values()) if result.validation_km else None
        summary_rows.append((name, oid, catnr, "ok", result.bstar, max_err, result.validation_km))
        print(f"  [{i+1:2d}/{len(roster)}] {name:16s} cat={catnr}  B*={result.bstar:.4e}  "
              f"max_val_err={max_err:.1f} km" if max_err is not None else
              f"  [{i+1:2d}/{len(roster)}] {name:16s} cat={catnr}  B*={result.bstar:.4e}  (no validation points)")

    print("\n--- Summary ---")
    ok = sum(1 for r in summary_rows if r[3] == "ok")
    print(f"fitted OK: {ok}/{len(roster)}")
    for row in summary_rows:
        if row[3] != "ok":
            print(f"  FAILED: {row[0]} ({row[1]}) -> {row[3]}")
    if ok:
        worst = max((r[5] for r in summary_rows if r[3] == "ok" and r[5] is not None), default=None)
        print(f"worst max-validation-error across batch: {worst:.1f} km" if worst is not None else "")

    if args.dry_run:
        print("\n[dry-run] not writing output file.")
        return 0 if ok == len(roster) else 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# ESTIMATED TLEs, NOT OFFICIAL -- fitted from SpaceX MEME precise ephemeris via\n"
        f"# SGP4 differential correction (starlink_ephemeris/meme_to_tle.py). Catalog numbers\n"
        f"# 339974-339999 are SYNTHETIC, reserved by this project for the Starship Flight 14\n"
        f"# Starlink V3 batch (intl designators {INTDES_PREFIX}A-{INTDES_PREFIX}AB) -- they are\n"
        f"# NOT official Space-Track/CelesTrak numbers and NOT the same as CelesTrak's own\n"
        f"# placeholder IDs (799501648-799501673, which don't fit a TLE's 5-char field).\n"
        f"# Remove this file once Space-Track assigns real NORAD numbers for these satellites.\n"
        f"# Validation (position error vs held-out MEME samples, km): see batch run log.\n"
    )
    args.out.write_text(header + "\n".join(lines_out) + "\n", encoding="utf-8")
    print(f"\n[batch] wrote {ok} satellites -> {args.out}")
    return 0 if ok == len(roster) else 1


if __name__ == "__main__":
    sys.exit(main())
