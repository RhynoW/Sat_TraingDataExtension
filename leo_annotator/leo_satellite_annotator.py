#!/usr/bin/env python3
"""
leo_satellite_annotator.py
==========================
LEO 衛星「質量與推進系統標註表」雛形程式

資料來源優先順序：
  1. CelesTrak SATCAT API  → 軌道高度、COSPAR ID
  2. UCS Satellite Database (本地 Excel) → 質量、任務類型
  3. Nanosats Database (網頁) → CubeSat 質量、推進描述
  4. KeepTrack (網頁) → 質量、推進型號
  5. N2YO (網頁) → 軌道高度備援

用法：
  # 從 CSV 批次處理
  python leo_satellite_annotator.py --input sample_input.csv --ucs UCS_Satellite_Database.xlsx --output annotations.csv

  # 單顆衛星
  python leo_satellite_annotator.py --norad 25544 --ucs UCS_Satellite_Database.xlsx

  # 互動模式（無任何 --input / --norad）
  python leo_satellite_annotator.py --ucs UCS_Satellite_Database.xlsx
"""

import os
import re
import sys
import time
import argparse
import logging
from pathlib import Path

import requests
import pandas as pd
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────────────────────────
# 0. Schema
# ─────────────────────────────────────────────────────────────────────────────
SCHEMA = [
    "norad_id", "cospar_id", "sat_name", "orbit_band",
    "mass_kg", "mass_class", "platform_class", "propulsion_class",
    "propulsion_description", "mission_type",
    "mass_source", "propulsion_source",
    "mass_confidence", "propulsion_confidence",
    "mass_note", "propulsion_note",
]

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

# ─────────────────────────────────────────────────────────────────────────────
# 1. Classification helpers
# ─────────────────────────────────────────────────────────────────────────────

def classify_orbit_band(alt_km: float | None) -> str:
    """Map mean altitude (km) to orbit_band label."""
    if alt_km is None:
        return ""
    if 300 <= alt_km <= 450:
        return "LEO_300_450"
    elif 450 < alt_km <= 800:
        return "LEO_450_800"
    elif 800 < alt_km <= 1000:
        return "LEO_800_1000"
    else:
        return "OUT_OF_RANGE"


def classify_mass(mass_kg: float | None) -> str:
    """Map mass in kg to discrete mass_class label."""
    if mass_kg is None:
        return ""
    if mass_kg < 10:
        return "<10kg"
    elif mass_kg < 50:
        return "10_50kg"
    elif mass_kg < 200:
        return "50_200kg"
    elif mass_kg < 1000:
        return "200_1000kg"
    else:
        return ">1000kg"


def classify_platform(mass_kg: float | None) -> str:
    """Map mass to platform_class; returns 'Unknown' if mass unknown."""
    if mass_kg is None:
        return "Unknown"
    if mass_kg < 50:
        return "Cube/Nano"
    elif mass_kg < 200:
        return "Micro"
    else:
        return "Small/Medium"


def classify_propulsion(text: str) -> tuple[str, str]:
    """
    Return (propulsion_class, propulsion_description) from free text.
    Priority: Electric_EP > Chemical > Micro/ColdGas > Hybrid/Other > None
    """
    t = (text or "").lower()
    if not t.strip():
        return "None", "No propulsion reported"

    ep_kw = [
        "hall thruster", "hall-effect", "hall effect",
        "ion engine", "gridded ion", "electric propulsion",
        "electrospray", "field emission", "rf ion", "ep thruster",
        "xenon", "krypton propellant",
    ]
    chem_kw = [
        "monopropellant", "bipropellant", "hydrazine", "hpgp",
        "solid motor", "solid rocket", "green propellant",
        "butane thruster", "propane thruster",
    ]
    micro_kw = [
        "cold gas", "cold-gas", "pulsed plasma", "ppt",
        "microjet", "resistojet", "micro propulsion", "mems thruster",
        "vacco", "bgm", "enpulsion nano",
    ]
    generic_kw = ["thruster", "propulsion", "engine", "maneuver"]

    if any(k in t for k in ep_kw):
        return "Electric_EP", text.strip()
    if any(k in t for k in chem_kw):
        return "Chemical", text.strip()
    if any(k in t for k in micro_kw):
        return "Micro/ColdGas", text.strip()
    if any(k in t for k in generic_kw):
        return "Hybrid/Other", f"Propulsion mentioned but type unclear: {text.strip()}"
    return "None", "No propulsion reported"


def map_mission_type(purpose: str) -> str:
    """Map UCS 'Purpose' free text to mission_type label."""
    p = (purpose or "").lower()
    if any(x in p for x in ["communication", "telecom", "relay", "iot", "broadband", "connectivity"]):
        return "COMM"
    if any(x in p for x in ["earth observation", "remote sensing", "imaging", "eo", "surveillance"]):
        return "EO"
    if any(x in p for x in ["technology", "demo", "experiment", "test", "demonstration"]):
        return "TechDemo"
    if any(x in p for x in ["science", "research", "astronomy", "space science"]):
        return "Science"
    if any(x in p for x in ["navigation", "gps", "gnss", "positioning", "timing"]):
        return "Nav"
    return "Other"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Source: CelesTrak SATCAT API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_celestrak(norad_id: str | int) -> dict:
    """
    Query CelesTrak SATCAT JSON API.
    Returns dict with keys: cospar_id, sat_name, apogee_km, perigee_km,
                             mean_alt_km, orbit_band, rcs_size, period_min, inclination
    """
    url = f"https://celestrak.org/satcat/records.php?CATNR={norad_id}&FORMAT=JSON"
    try:
        r = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        if not data:
            logging.warning(f"CelesTrak: no record for NORAD {norad_id}")
            return {}
        rec = data[0]
        apogee  = rec.get("APOGEE")
        perigee = rec.get("PERIGEE")
        mean_alt = None
        if apogee is not None and perigee is not None:
            mean_alt = round((float(apogee) + float(perigee)) / 2, 1)
        return {
            "cospar_id":   rec.get("INTLDES", "").strip(),
            "sat_name":    rec.get("OBJECT_NAME", "").strip(),
            "apogee_km":   apogee,
            "perigee_km":  perigee,
            "mean_alt_km": mean_alt,
            "orbit_band":  classify_orbit_band(mean_alt),
            "rcs_size":    rec.get("RCS_SIZE", ""),
            "period_min":  rec.get("PERIOD"),
            "inclination": rec.get("INCLINATION"),
        }
    except Exception as e:
        logging.warning(f"CelesTrak error (NORAD {norad_id}): {e}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Source: UCS Satellite Database (local Excel)
# ─────────────────────────────────────────────────────────────────────────────

_ucs_df: pd.DataFrame | None = None

# Known UCS column names (as of 2024 edition)
UCS_COL_NORAD   = "NORAD Number"
UCS_COL_COSPAR  = "COSPAR Number"
UCS_COL_NAME    = "Name of Satellite, Alternate Names"
UCS_COL_MASS    = "Launch Mass (kg.)"
UCS_COL_DRY     = "Dry Mass (kg.)"
UCS_COL_PURPOSE = "Purpose"


def load_ucs(filepath: str) -> None:
    global _ucs_df
    p = Path(filepath)
    if not p.exists():
        logging.warning(f"UCS file not found: {filepath}. Skipping UCS lookups.")
        return
    try:
        _ucs_df = pd.read_excel(filepath, header=0, dtype=str)
        # Normalize column names (strip whitespace)
        _ucs_df.columns = [c.strip() for c in _ucs_df.columns]
        logging.info(f"UCS Database loaded: {len(_ucs_df)} rows, columns: {list(_ucs_df.columns[:6])}...")
    except Exception as e:
        logging.error(f"Failed to load UCS database: {e}")


def _ucs_find_column(keywords: list[str]) -> str | None:
    """Find a UCS column whose name contains any of the keywords (case-insensitive)."""
    if _ucs_df is None:
        return None
    for col in _ucs_df.columns:
        if any(kw.lower() in col.lower() for kw in keywords):
            return col
    return None


def lookup_ucs(norad_id: str | int, sat_name: str = "") -> dict:
    """
    Match a satellite in the local UCS DataFrame by NORAD ID, then by name.
    Returns dict with keys: mass_kg, mass_source, mass_confidence, mass_note,
                             mission_type, cospar_id (if found)
    """
    if _ucs_df is None:
        return {}

    norad_col   = _ucs_find_column(["NORAD"])
    name_col    = _ucs_find_column(["Name of Satellite"])
    mass_col    = _ucs_find_column(["Launch Mass"])
    dry_col     = _ucs_find_column(["Dry Mass"])
    purpose_col = _ucs_find_column(["Purpose"])
    cospar_col  = _ucs_find_column(["COSPAR"])

    row = None

    # Try NORAD match
    if norad_col:
        matches = _ucs_df[
            _ucs_df[norad_col].str.strip().str.lower() == str(norad_id).strip().lower()
        ]
        if not matches.empty:
            row = matches.iloc[0]

    # Fallback: name substring match
    if row is None and sat_name and name_col:
        name_clean = sat_name.strip().upper()
        matches = _ucs_df[
            _ucs_df[name_col].str.upper().str.contains(name_clean, na=False, regex=False)
        ]
        if not matches.empty:
            row = matches.iloc[0]

    if row is None:
        return {}

    result = {}

    # Mass
    mass_val = None
    if mass_col:
        raw = str(row.get(mass_col, "")).strip()
        m = re.search(r"[\d,.]+", raw.replace(",", ""))
        if m:
            try:
                mass_val = float(m.group().replace(",", ""))
            except ValueError:
                pass

    dry_val = None
    if dry_col:
        raw = str(row.get(dry_col, "")).strip()
        m = re.search(r"[\d,.]+", raw.replace(",", ""))
        if m:
            try:
                dry_val = float(m.group().replace(",", ""))
            except ValueError:
                pass

    if mass_val is not None:
        result["mass_kg"] = mass_val
        result["mass_source"] = "UCS"
        result["mass_confidence"] = "High"
        note = f"UCS launch mass: {mass_val} kg"
        if dry_val is not None:
            note += f"; dry mass: {dry_val} kg"
        result["mass_note"] = note
    elif dry_val is not None:
        result["mass_kg"] = dry_val
        result["mass_source"] = "UCS"
        result["mass_confidence"] = "Medium"
        result["mass_note"] = f"UCS dry mass only: {dry_val} kg (launch mass missing)"

    # Mission type
    if purpose_col:
        purpose = str(row.get(purpose_col, "")).strip()
        result["mission_type"] = map_mission_type(purpose)

    # COSPAR (may supplement CelesTrak)
    if cospar_col:
        result["cospar_id"] = str(row.get(cospar_col, "")).strip()

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 4. Source: Nanosats Database (web scrape)
# ─────────────────────────────────────────────────────────────────────────────

def _nanosats_slug(name: str) -> str:
    """Convert satellite name to Nanosats URL slug."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


def scrape_nanosats(sat_name: str) -> dict:
    """
    Attempt to scrape nanosats.eu individual satellite page.
    Falls back to empty dict on failure.
    """
    slug = _nanosats_slug(sat_name)
    url = f"https://www.nanosats.eu/sat/{slug}"
    try:
        r = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
        if r.status_code != 200:
            logging.info(f"Nanosats: HTTP {r.status_code} for '{sat_name}' ({url})")
            return {}
        soup = BeautifulSoup(r.text, "html.parser")
        result = {}
        notes = []

        # Parse detail table rows
        for tr in soup.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            label = cells[0].get_text(strip=True).lower()
            value = cells[1].get_text(strip=True)

            if not value or value in ("-", "N/A", "Unknown"):
                continue

            if any(kw in label for kw in ["mass", "weight"]):
                m = re.search(r"([\d.]+)\s*kg", value, re.IGNORECASE)
                if not m:
                    m = re.search(r"[\d.]+", value)
                if m:
                    try:
                        result["mass_kg"] = float(m.group(1) if m.lastindex else m.group())
                        result["mass_source"] = "NanosatDB"
                        result["mass_confidence"] = "Medium"
                        result["mass_note"] = f"NanosatDB: {value}"
                    except ValueError:
                        pass

            if "propulsion" in label or "thruster" in label:
                result["propulsion_raw"] = value
                notes.append(f"NanosatDB propulsion: {value}")

        if notes:
            result["propulsion_note_extra"] = "; ".join(notes)

        return result
    except Exception as e:
        logging.warning(f"Nanosats scrape error for '{sat_name}': {e}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# 5. Source: KeepTrack (web scrape, replaces Gunter's)
# ─────────────────────────────────────────────────────────────────────────────

# Motor values that indicate attitude control only, not propulsion
_AOCS_ONLY = {"aocs", "rcs", "unknown", "n/a", "none", ""}


def scrape_keeptrack(norad_id: str | int) -> dict:
    """
    Scrape keeptrack.space/satellite/{norad_id} for mass, propulsion, purpose.
    Page structure: consecutive <p> tags in label/value pairs.
    Returns dict with: mass_kg, mass_source, mass_confidence, mass_note,
                       propulsion_raw, propulsion_source, propulsion_confidence
    """
    url = f"https://keeptrack.space/satellite/{norad_id}"
    try:
        r = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
        if r.status_code != 200:
            logging.info(f"KeepTrack: HTTP {r.status_code} for NORAD {norad_id}")
            return {}
        soup = BeautifulSoup(r.text, "html.parser")

        # Build label→value map from consecutive <p> pairs
        paras = [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]
        kv: dict[str, str] = {}
        for i in range(len(paras) - 1):
            kv[paras[i].lower()] = paras[i + 1]

        result: dict = {}

        # Mass — prefer launch mass, fall back to dry mass
        for label in ("launch mass", "dry mass"):
            raw = kv.get(label, "").strip()
            if raw and raw.lower() not in ("unknown", "n/a", "calculating..."):
                m = re.search(r"[\d.]+", raw.replace(",", ""))
                if m:
                    try:
                        result["mass_kg"]         = float(m.group())
                        result["mass_source"]     = "KeepTrack"
                        result["mass_confidence"] = "Medium"
                        result["mass_note"]       = f"KeepTrack {label}: {raw} kg"
                        break
                    except ValueError:
                        pass

        # Propulsion — Motor field (skip AOCS-only entries)
        motor = kv.get("motor", "").strip()
        if motor.lower() not in _AOCS_ONLY:
            result["propulsion_raw"]        = motor
            result["propulsion_source"]     = "KeepTrack"
            result["propulsion_confidence"] = "Medium"

        return result
    except Exception as e:
        logging.warning(f"KeepTrack scrape error (NORAD {norad_id}): {e}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# 6. Source: N2YO (web scrape, orbit fallback)
# ─────────────────────────────────────────────────────────────────────────────

def scrape_n2yo(norad_id: str | int) -> dict:
    """
    Scrape n2yo.com for apogee/perigee as a fallback orbit source.
    Also tries n2yo.org URL pattern per user specification.
    """
    urls = [
        f"https://www.n2yo.com/satellite/?s={norad_id}",
        f"https://www.n2yo.org/satellite/?s={norad_id}",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            text = soup.get_text(" ", strip=True)

            apo = re.search(r"Apogee[:\s]+([\d,]+)\s*km", text, re.IGNORECASE)
            per = re.search(r"Perigee[:\s]+([\d,]+)\s*km", text, re.IGNORECASE)
            if apo and per:
                apogee  = float(apo.group(1).replace(",", ""))
                perigee = float(per.group(1).replace(",", ""))
                mean_alt = round((apogee + perigee) / 2, 1)
                return {
                    "apogee_km":   apogee,
                    "perigee_km":  perigee,
                    "mean_alt_km": mean_alt,
                    "orbit_band":  classify_orbit_band(mean_alt),
                    "orbit_source": "N2YO",
                }
        except Exception as e:
            logging.warning(f"N2YO scrape error (NORAD {norad_id}, {url}): {e}")
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# 7. Main annotation logic
# ─────────────────────────────────────────────────────────────────────────────

def annotate_satellite(
    norad_id: str | int,
    cospar_hint: str = "",
    name_hint: str = "",
    alt_hint: float | None = None,
    request_delay: float = 1.5,
    skip_celestrak: bool = False,
) -> dict:
    """
    Collect data from all sources and merge into a single annotation record.
    When skip_celestrak=True and hints are provided, CelesTrak is bypassed
    (useful when orbit data is already known from an external catalog).
    """
    rec = {f: "" for f in SCHEMA}
    rec["norad_id"] = str(norad_id).strip()

    # ── Step 1: CelesTrak (orbit + name) ────────────────────────────────────
    if skip_celestrak and (cospar_hint or name_hint or alt_hint is not None):
        logging.info(f"  [CelesTrak] NORAD {norad_id} — skipped (pre-filled from catalog)")
        rec["cospar_id"]  = cospar_hint
        rec["sat_name"]   = name_hint
        rec["orbit_band"] = classify_orbit_band(alt_hint)
    else:
        logging.info(f"  [CelesTrak] NORAD {norad_id}")
        ct = fetch_celestrak(norad_id)
        time.sleep(request_delay)
        rec["cospar_id"]  = ct.get("cospar_id") or cospar_hint
        rec["sat_name"]   = ct.get("sat_name")  or name_hint
        rec["orbit_band"] = ct.get("orbit_band", "")
        if not rec["orbit_band"] and alt_hint is not None:
            rec["orbit_band"] = classify_orbit_band(alt_hint)

    sat_name = rec["sat_name"]

    # ── Step 2: UCS Database (local) ────────────────────────────────────────
    logging.info(f"  [UCS] '{sat_name}'")
    ucs = lookup_ucs(norad_id, sat_name)

    if ucs.get("mass_kg") is not None:
        rec["mass_kg"]          = ucs["mass_kg"]
        rec["mass_source"]      = ucs.get("mass_source", "UCS")
        rec["mass_confidence"]  = ucs.get("mass_confidence", "High")
        rec["mass_note"]        = ucs.get("mass_note", "")

    if ucs.get("mission_type"):
        rec["mission_type"] = ucs["mission_type"]

    if ucs.get("cospar_id") and not rec["cospar_id"]:
        rec["cospar_id"] = ucs["cospar_id"]

    # ── Step 3: Nanosats DB ──────────────────────────────────────────────────
    if sat_name:
        logging.info(f"  [Nanosats] '{sat_name}'")
        nano = scrape_nanosats(sat_name)
        time.sleep(request_delay)

        # Fill mass if UCS didn't provide it
        if not rec["mass_kg"] and nano.get("mass_kg") is not None:
            rec["mass_kg"]         = nano["mass_kg"]
            rec["mass_source"]     = nano.get("mass_source", "NanosatDB")
            rec["mass_confidence"] = nano.get("mass_confidence", "Medium")
            rec["mass_note"]       = nano.get("mass_note", "")

        # Propulsion from Nanosats
        if nano.get("propulsion_raw"):
            pclass, pdesc = classify_propulsion(nano["propulsion_raw"])
            rec["propulsion_class"]       = pclass
            rec["propulsion_description"] = pdesc
            rec["propulsion_source"]      = "NanosatDB"
            rec["propulsion_confidence"]  = "Medium"
            rec["propulsion_note"]        = nano.get("propulsion_note_extra", nano["propulsion_raw"])

    # ── Step 4: KeepTrack ────────────────────────────────────────────────────
    logging.info(f"  [KeepTrack] NORAD {norad_id}")
    kt = scrape_keeptrack(norad_id)
    time.sleep(request_delay)

    if not rec["mass_kg"] and kt.get("mass_kg") is not None:
        rec["mass_kg"]         = kt["mass_kg"]
        rec["mass_source"]     = kt.get("mass_source", "KeepTrack")
        rec["mass_confidence"] = kt.get("mass_confidence", "Medium")
        rec["mass_note"]       = kt.get("mass_note", "")

    if not rec["propulsion_class"] and kt.get("propulsion_raw"):
        pclass, pdesc = classify_propulsion(kt["propulsion_raw"])
        rec["propulsion_class"]       = pclass
        rec["propulsion_description"] = pdesc
        rec["propulsion_source"]      = kt.get("propulsion_source", "KeepTrack")
        rec["propulsion_confidence"]  = kt.get("propulsion_confidence", "Medium")
        rec["propulsion_note"]        = f"KeepTrack motor: {kt['propulsion_raw']}"

    # ── Step 5: N2YO (orbit fallback) ───────────────────────────────────────
    if not rec["orbit_band"]:
        logging.info(f"  [N2YO] NORAD {norad_id} (orbit fallback)")
        n2 = scrape_n2yo(norad_id)
        time.sleep(request_delay)
        if n2.get("orbit_band"):
            rec["orbit_band"] = n2["orbit_band"]

    # ── Step 6: Derived classifications ─────────────────────────────────────
    mass_val = None
    if rec["mass_kg"] != "":
        try:
            mass_val = float(rec["mass_kg"])
        except (ValueError, TypeError):
            pass

    rec["mass_class"]     = classify_mass(mass_val)
    rec["platform_class"] = classify_platform(mass_val)

    # ── Step 7: Defaults for missing fields ─────────────────────────────────
    if not rec["propulsion_class"]:
        rec["propulsion_class"]       = "None"
        rec["propulsion_description"] = "No propulsion reported"
        rec["propulsion_source"]      = ""
        rec["propulsion_confidence"]  = "Low"
        rec["propulsion_note"]        = "No propulsion info found across queried sources"

    if not rec["mission_type"]:
        rec["mission_type"] = "Other"

    if not rec["mass_kg"]:
        if not rec["mass_note"]:
            rec["mass_note"] = "No mass data found in UCS, Nanosats, or KeepTrack"
        rec["mass_confidence"] = "Low"

    return rec


# ─────────────────────────────────────────────────────────────────────────────
# 8. CLI
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="LEO Satellite Mass & Propulsion Annotator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--input",  "-i", metavar="CSV",
                   help="Input CSV with columns: NORAD_ID[,COSPAR_ID,NAME,MEAN_ALT_KM]")
    p.add_argument("--norad",  "-n", metavar="ID",
                   help="Single NORAD ID to annotate")
    p.add_argument("--ucs",    "-u", metavar="XLSX",
                   help="Path to UCS Satellite Database Excel file")
    p.add_argument("--output", "-o", metavar="CSV",
                   default="leo_annotations.csv",
                   help="Output CSV path (default: leo_annotations.csv)")
    p.add_argument("--delay",  "-d", type=float, default=1.5,
                   help="Seconds to wait between HTTP requests (default: 1.5)")
    p.add_argument("--no-celestrak", action="store_true",
                   help="Skip CelesTrak queries and use COSPAR_ID/NAME/MEAN_ALT_KM "
                        "from the input CSV directly (faster when orbit data is pre-filled)")
    p.add_argument("--resume", "-r", action="store_true",
                   help="Skip NORADs already in the output CSV and append new rows")
    p.add_argument("--verbose","-v", action="store_true",
                   help="Enable DEBUG logging")
    return p


def load_input_csv(filepath: str) -> list[dict]:
    """
    Load satellite list from CSV.
    Expected columns (case-insensitive): NORAD_ID, [COSPAR_ID], [NAME], [MEAN_ALT_KM]
    """
    df = pd.read_csv(filepath, dtype=str)
    df.columns = [c.strip().upper() for c in df.columns]

    col_map = {
        "norad_id":   next((c for c in df.columns if "NORAD" in c), df.columns[0]),
        "cospar_id":  next((c for c in df.columns if "COSPAR" in c), None),
        "name":       next((c for c in df.columns if "NAME" in c), None),
        "alt_km":     next((c for c in df.columns if "ALT" in c or "MEAN" in c), None),
    }

    satellites = []
    for _, row in df.iterrows():
        def get(col_key):
            col = col_map.get(col_key)
            if col and col in row.index:
                val = str(row[col]).strip()
                return val if val not in ("", "nan", "NaN") else ""
            return ""

        alt_raw = get("alt_km")
        try:
            alt_km = float(alt_raw) if alt_raw else None
        except ValueError:
            alt_km = None

        satellites.append({
            "norad_id":  get("norad_id"),
            "cospar_id": get("cospar_id"),
            "name":      get("name"),
            "alt_km":    alt_km,
        })
    return satellites


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        encoding="utf-8",
    )

    # Load UCS database if provided
    if args.ucs:
        load_ucs(args.ucs)
    else:
        logging.info("No --ucs file specified; UCS lookups will be skipped.")

    # Collect satellite list
    satellites: list[dict] = []

    if args.input:
        satellites = load_input_csv(args.input)
        logging.info(f"Loaded {len(satellites)} satellite(s) from {args.input}")

    elif args.norad:
        satellites = [{
            "norad_id": args.norad.strip(),
            "cospar_id": "",
            "name": "",
            "alt_km": None,
        }]

    else:
        # Interactive mode
        print("\n=== LEO Satellite Annotator — Interactive Mode ===")
        print("Enter NORAD ID(s) separated by commas (e.g.  25544, 48274, 44057):")
        raw = input("NORAD ID(s) > ").strip()
        if not raw:
            print("No input provided. Exiting.")
            sys.exit(0)
        for nid in raw.split(","):
            nid = nid.strip()
            if nid:
                satellites.append({"norad_id": nid, "cospar_id": "", "name": "", "alt_km": None})

    if not satellites:
        logging.error("No satellites to process. Exiting.")
        sys.exit(1)

    # Resume: load already-processed NORAD IDs from existing output
    done_norads: set[str] = set()
    out_path = Path(args.output)
    write_header = True
    if args.resume and out_path.exists() and out_path.stat().st_size > 0:
        try:
            existing = pd.read_csv(args.output, dtype=str, encoding="utf-8-sig")
            done_norads = set(existing["norad_id"].astype(str).str.strip())
            write_header = False
            logging.info(f"[RESUME] {len(done_norads)} 筆已完成，繼續未處理部分")
        except Exception as e:
            logging.warning(f"[RESUME] 讀取現有輸出失敗，重新開始：{e}")
            write_header = True

    out_path.parent.mkdir(parents=True, exist_ok=True)
    open_mode = "a" if (args.resume and not write_header) else "w"
    out_file = open(args.output, open_mode, newline="", encoding="utf-8-sig")
    csv_writer = None  # initialised after first row

    # Process each satellite — write each row immediately
    total = len(satellites)
    done_count = 0
    for i, sat in enumerate(satellites, 1):
        nid = str(sat["norad_id"]).strip()

        if nid in done_norads:
            logging.info(f"[{i}/{total}] NORAD {nid} 已完成，略過")
            done_count += 1
            continue

        logging.info(f"[{i}/{total}] Annotating NORAD {nid} ...")
        try:
            row = annotate_satellite(
                norad_id       = nid,
                cospar_hint    = sat.get("cospar_id", ""),
                name_hint      = sat.get("name", ""),
                alt_hint       = sat.get("alt_km"),
                request_delay  = args.delay,
                skip_celestrak = args.no_celestrak,
            )
        except Exception as e:
            logging.error(f"  Failed for NORAD {nid}: {e}")
            row = {f: "" for f in SCHEMA}
            row["norad_id"] = nid
            row["mass_note"] = f"Error during annotation: {e}"

        # Initialise CSV writer on first new row
        import csv as _csv
        if csv_writer is None:
            csv_writer = _csv.DictWriter(
                out_file, fieldnames=SCHEMA, extrasaction="ignore",
                lineterminator="\n",
            )
            if write_header:
                csv_writer.writeheader()
        csv_writer.writerow(row)
        out_file.flush()
        done_count += 1

    out_file.close()

    msg = f"[DONE] Annotation complete: {done_count} satellite(s) -> {args.output}"
    logging.info(msg)


if __name__ == "__main__":
    main()
