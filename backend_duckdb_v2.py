# backend_duckdb_v2.py  — CesiumJS-enhanced API (adds /api/orbit_czml and /api/conjunction_czml)
import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from sgp4.api import Satrec, jday
from sgp4.conveniences import sat_epoch_datetime

from conjunction_pipeline import run_pipeline
from ca_pipeline_kdtree_v2_fixed import run_ca_pipeline

R_EARTH_KM = 6378.137
F_EARTH = 1 / 298.257223563
E2 = F_EARTH * (2 - F_EARTH)

META_TABLE = "sat_n2yo_metadata"
# RAW_TABLE = "tle_raw"
RAW_TABLE = "raw_tle_archive"
TLE_TABLE = "tle_table"
RAW_ARCHIVE_TABLE = "raw_tle_archive"
DEFAULT_SPACE_DB_PATH = r"space_db.duckdb"

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("backend_duckdb")


@dataclass(frozen=True)
class Settings:
    db_path: Path
    raw_db_path: Path
    conj_db_path: Path
    host: str = "0.0.0.0"
    port: int = 5001
    debug: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        db = Path(os.getenv("DB_PATH", DEFAULT_SPACE_DB_PATH))
        return cls(
            db_path=db,
            raw_db_path=db,
            conj_db_path=db,
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "5001")),
            debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        )


settings = Settings.from_env()


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    register_error_handlers(app)
    register_routes(app)
    register_czml_routes(app)   # v2: /api/orbit_czml + /api/conjunction_czml

    @app.get("/health")
    def health() -> Any:
        return jsonify(
            {
                "status": "ok",
                "raw_db_exists": settings.raw_db_path.exists(),
                "meta_db_exists": settings.db_path.exists(),
                "conj_db_exists": settings.conj_db_path.exists(),
            }
        )

    return app


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ValueError)
    def handle_value_error(err):
        return jsonify({"error": str(err)}), 400

    @app.errorhandler(FileNotFoundError)
    def handle_not_found(err):
        return jsonify({"error": str(err)}), 404

    from werkzeug.exceptions import HTTPException

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, HTTPException):
            return err
        logger.exception("Unhandled exception")
        return jsonify({"error": "internal_server_error", "detail": str(err)}), 500

    @app.errorhandler(404)
    def handle_404(err):
        return jsonify({
            "error": "not_found",
            "detail": str(err),
            "path": request.path
        }), 404

def connect_readonly(db_path: Path) -> duckdb.DuckDBPyConnection:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    return duckdb.connect(str(db_path), read_only=True)


def parse_int_arg(name: str, default: int | None = None, minimum: int | None = None) -> int:
    raw = request.args.get(name)
    if raw is None:
        if default is None:
            raise ValueError(f"{name} is required")
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer") from exc
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def parse_float_arg(name: str, default: float | None = None, minimum: float | None = None) -> float:
    raw = request.args.get(name)
    if raw is None or raw == "":
        if default is None:
            raise ValueError(f"{name} is required")
        value = default
    else:
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be a valid number") from exc
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def get_sat_n2yo_metadata(con: duckdb.DuckDBPyConnection, norad_id: int) -> dict[str, Any] | None:
    row = con.execute(
        f"""
        SELECT
            norad_id, name_en, launch_date, launch_site, intl_code,
            perigee_km, apogee_km, inclination_deg, period_min, sma_km,
            rcs_text, source_code, website_desc_en, website_desc_ch
        FROM {META_TABLE}
        WHERE norad_id = ?
        """,
        [norad_id],
    ).fetchone()
    if row is None:
        return None
    cols = [
        "norad_id", "name_en", "launch_date", "launch_site", "intl_code",
        "perigee_km", "apogee_km", "inclination_deg", "period_min", "sma_km",
        "rcs_text", "source_code", "website_desc_en", "website_desc_ch",
    ]
    return dict(zip(cols, row))


def load_latest_tle_raw_row(norad: int) -> dict[str, Any] | None:
    with connect_readonly(settings.raw_db_path) as con:
        df = con.execute(
            f"""
            SELECT norad_id, epoch_jd, object_name, line1, line2, mean_motion
            FROM {RAW_TABLE}
            WHERE norad_id = ?
            ORDER BY epoch_jd DESC
            LIMIT 1
            """,
            [norad],
        ).df()
    if df.empty:
        return None
    return df.iloc[0].to_dict()


def eci_to_llh(r_eci_km: np.ndarray, t_utc: datetime) -> tuple[float, float, float]:
    x, y, z = r_eci_km
    jd, fr = jday(
        t_utc.year, t_utc.month, t_utc.day,
        t_utc.hour, t_utc.minute, t_utc.second + t_utc.microsecond * 1e-6,
    )
    T = ((jd - 2451545.0) + fr) / 36525.0
    gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0 + fr) + 0.000387933 * T**2
    gmst_rad = np.deg2rad(gmst % 360.0)

    x_ecef = np.cos(gmst_rad) * x + np.sin(gmst_rad) * y
    y_ecef = -np.sin(gmst_rad) * x + np.cos(gmst_rad) * y
    z_ecef = z

    lon = np.arctan2(y_ecef, x_ecef)
    r = np.sqrt(x_ecef**2 + y_ecef**2)
    lat = np.arctan2(z_ecef, r * (1 - E2))
    alt = 0.0
    for _ in range(5):
        sin_lat = np.sin(lat)
        N = R_EARTH_KM / np.sqrt(1 - E2 * sin_lat**2)
        cos_lat = np.cos(lat)
        # Guard against division by zero at the poles (|lat| ≈ 90°, cos → 0)
        if abs(cos_lat) > 1e-9:
            alt = r / cos_lat - N
        else:
            alt = abs(z_ecef) / (1.0 - E2) - N
        lat = np.arctan2(z_ecef, r * (1 - E2 * (N / (N + alt))))
    return float(np.rad2deg(lat)), float(np.rad2deg(lon)), float(alt)


def propagate_orbit(row: dict[str, Any], num_pts: int = 300, span_hours: int = 48) -> list[dict[str, Any]]:
    sat = Satrec.twoline2rv(row["line1"], row["line2"])
    epoch_dt = sat_epoch_datetime(sat).replace(tzinfo=timezone.utc)

    # Batch JD arrays: epoch_jd + fractional-day offsets avoids per-point jday() calls
    epoch_jd, epoch_fr = jday(
        epoch_dt.year, epoch_dt.month, epoch_dt.day,
        epoch_dt.hour, epoch_dt.minute,
        epoch_dt.second + epoch_dt.microsecond * 1e-6,
    )
    times_min = np.linspace(0.0, span_hours * 60.0, num_pts)
    jds = np.full(num_pts, epoch_jd)
    frs = epoch_fr + times_min / 1440.0   # minutes → fractional days

    errs, r_ecis, _ = sat.sgp4_array(jds, frs)   # vectorised SGP4: shape (N,) and (N, 3)

    positions = []
    for i, (err, r_eci) in enumerate(zip(errs, r_ecis)):
        if err != 0:
            continue
        t = epoch_dt + timedelta(minutes=float(times_min[i]))
        lat, lon, alt_km = eci_to_llh(r_eci, t)
        positions.append({"time": t.isoformat(), "lat": lat, "lon": lon, "alt_km": alt_km})
    return positions


# ==========================================
# CesiumJS CZML helpers  (new in v2)
# Skill references:
#   cesiumjs-spatial-math  → eci_to_ecef_m, INERTIAL frame positions
#   cesiumjs-time-properties → forwardExtrapolationType=HOLD, LAGRANGE sampling
#   cesiumjs-entities       → entity description HTML for InfoBox on click
#   cesiumjs-interaction    → structured description so selectedEntity shows rich data
#   cesiumjs-core-utilities → Resource.fetchJson() loads /api/orbit_czml & /api/conjunction_czml
# ==========================================

_RISK_RGBA: dict[str, list[int]] = {
    "HIGH":    [255,  40,  40, 255],
    "MEDIUM":  [255, 160,   0, 255],
    "LOW":     [255, 240,   0, 200],
    "UNKNOWN": [160, 160, 160, 200],
}


def _rgba_to_hex(rgba: list[int]) -> str:
    return f"{rgba[0]:02X}{rgba[1]:02X}{rgba[2]:02X}"


def eci_to_ecef_m(r_eci_km: np.ndarray, t_utc: datetime) -> np.ndarray:
    """ECI (km) → ECEF (m) via GMST rotation.  Used for static TCA markers in CZML."""
    jd, fr = jday(
        t_utc.year, t_utc.month, t_utc.day,
        t_utc.hour, t_utc.minute, t_utc.second + t_utc.microsecond * 1e-6,
    )
    gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0 + fr)
    gmst_rad = np.deg2rad(gmst % 360.0)
    cg, sg = np.cos(gmst_rad), np.sin(gmst_rad)
    return np.array([
        ( cg * r_eci_km[0] + sg * r_eci_km[1]) * 1000.0,
        (-sg * r_eci_km[0] + cg * r_eci_km[1]) * 1000.0,
        r_eci_km[2] * 1000.0,
    ])


def propagate_to_time(row: dict, t_utc: datetime) -> np.ndarray | None:
    """Propagate a satellite to a specific UTC time via SGP4. Returns ECI pos (km) or None."""
    sat = Satrec.twoline2rv(row["line1"], row["line2"])
    jd, fr = jday(
        t_utc.year, t_utc.month, t_utc.day,
        t_utc.hour, t_utc.minute, t_utc.second + t_utc.microsecond * 1e-6,
    )
    err, r_eci, _ = sat.sgp4(jd, fr)
    if err != 0:
        return None
    return np.array(r_eci)


def build_orbit_czml(
    norad_id: int,
    row: dict,
    meta: dict | None,
    num_pts: int = 300,
    span_hours: int = 48,
) -> list:
    """
    Build a CZML packet list for a satellite's orbit animation.

    Positions are in the INERTIAL (ECI) reference frame — CesiumJS rotates
    Earth beneath the satellite automatically.  forwardExtrapolationType=HOLD
    keeps the satellite visible at the clock edges instead of vanishing.

    Frontend usage:
        const czml = await Cesium.Resource.fetchJson({url: '/api/orbit_czml?norad_id=49336'});
        viewer.dataSources.add(Cesium.CzmlDataSource.load(czml));
    """
    sat_obj = Satrec.twoline2rv(row["line1"], row["line2"])
    epoch_dt = sat_epoch_datetime(sat_obj).replace(tzinfo=timezone.utc)

    epoch_jd, epoch_fr = jday(
        epoch_dt.year, epoch_dt.month, epoch_dt.day,
        epoch_dt.hour, epoch_dt.minute,
        epoch_dt.second + epoch_dt.microsecond * 1e-6,
    )
    times_min = np.linspace(0.0, span_hours * 60.0, num_pts)
    jds = np.full(num_pts, epoch_jd)
    frs = epoch_fr + times_min / 1440.0

    errs, r_ecis, _ = sat_obj.sgp4_array(jds, frs)

    # Flat [t_seconds, x_m, y_m, z_m, ...] for CZML cartesian array
    inert_pts: list[float] = []
    for k, (err, r_eci) in enumerate(zip(errs, r_ecis)):
        if err != 0:
            continue
        t_s = float(times_min[k]) * 60.0
        inert_pts.extend([
            round(t_s, 1),
            round(float(r_eci[0]) * 1000.0, 1),
            round(float(r_eci[1]) * 1000.0, 1),
            round(float(r_eci[2]) * 1000.0, 1),
        ])

    epoch_iso = epoch_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso   = (epoch_dt + timedelta(hours=span_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build InfoBox HTML (cesiumjs-interaction: entity.description shown on click)
    name_en    = meta.get("name_en")         if meta else None
    launch_str = meta.get("launch_date")     if meta else None
    intl_code  = meta.get("intl_code")       if meta else None
    perigee    = meta.get("perigee_km")      if meta else None
    apogee     = meta.get("apogee_km")       if meta else None
    inc_deg    = meta.get("inclination_deg") if meta else None
    period_min = meta.get("period_min")      if meta else None
    desc_en    = meta.get("website_desc_en") if meta else None

    display_name = name_en or f"NORAD {norad_id}"
    rows_html: list[str] = [
        f"<tr><td>NORAD</td><td><b>{norad_id}</b></td></tr>",
        f"<tr><td>Name</td><td><b>{display_name}</b></td></tr>",
    ]
    if intl_code:
        rows_html.append(f"<tr><td>Intl. Code</td><td>{intl_code}</td></tr>")
    if launch_str:
        rows_html.append(f"<tr><td>Launch</td><td>{launch_str}</td></tr>")
    if perigee is not None and apogee is not None:
        rows_html.append(
            f"<tr><td>Perigee / Apogee</td><td>{float(perigee):.0f} / {float(apogee):.0f} km</td></tr>"
        )
    if inc_deg is not None:
        rows_html.append(f"<tr><td>Inclination</td><td>{float(inc_deg):.2f}°</td></tr>")
    if period_min is not None:
        rows_html.append(f"<tr><td>Period</td><td>{float(period_min):.1f} min</td></tr>")
    if desc_en:
        snippet = (desc_en[:200] + "…") if len(desc_en) > 200 else desc_en
        rows_html.append(f"<tr><td colspan='2'><i>{snippet}</i></td></tr>")

    desc_html = (
        "<table style='color:#ddd;font-family:sans-serif;font-size:13px;border-collapse:collapse'>"
        + "".join(rows_html)
        + "</table>"
    )

    return [
        {
            "id": "document",
            "name": display_name,
            "version": "1.0",
            "clock": {
                "interval":    f"{epoch_iso}/{end_iso}",
                "currentTime": epoch_iso,
                "multiplier":  60,
                "range":       "LOOP_STOP",
                "step":        "SYSTEM_CLOCK_MULTIPLIER",
            },
        },
        {
            "id":           f"sat/{norad_id}",
            "name":         display_name,
            "description":  desc_html,
            "availability": f"{epoch_iso}/{end_iso}",
            "position": {
                "epoch":                    epoch_iso,
                "referenceFrame":           "INERTIAL",
                "interpolationAlgorithm":   "LAGRANGE",
                "interpolationDegree":      5,
                "forwardExtrapolationType": "HOLD",
                "backwardExtrapolationType":"HOLD",
                "cartesian":                inert_pts,
            },
            "point": {
                "color":        {"rgba": [0, 200, 255, 255]},
                "pixelSize":    12,
                "outlineColor": {"rgba": [0, 80, 120, 255]},
                "outlineWidth": 2,
            },
            "path": {
                "material":   {"solidColor": {"color": {"rgba": [0, 200, 255, 180]}}},
                "width":      2.5,
                "leadTime":   3600,
                "trailTime":  3600,
                "resolution": 60,
            },
            "label": {
                "text":         display_name,
                "font":         "11pt Lucida Console",
                "fillColor":    {"rgba": [255, 255, 255, 220]},
                "outlineColor": {"rgba": [0, 0, 0, 255]},
                "outlineWidth": 2,
                "style":        "FILL_AND_OUTLINE",
                "pixelOffset":  {"cartesian2": [14, 0]},
            },
        },
    ]


def build_conjunction_czml(events: list[dict]) -> list:
    """
    Build a CZML packet list for conjunction TCA markers.

    For each event produces:
      • Primary satellite point at TCA (ECEF, larger marker)
      • Secondary satellite point at TCA (ECEF, smaller marker)
      • A polyline between the two positions (miss-vector geometry)
    All entities carry an InfoBox HTML description (cesiumjs-interaction skill).

    Colours: red=HIGH, orange=MEDIUM, yellow=LOW, grey=UNKNOWN.

    Frontend usage:
        const czml = await Cesium.Resource.fetchJson({url: '/api/conjunction_czml?norad=...'});
        viewer.dataSources.add(Cesium.CzmlDataSource.load(czml));
    """
    czml: list = [{"id": "document", "name": "Conjunction Events", "version": "1.0"}]

    for i, ev in enumerate(events):
        primary_norad   = int(ev["primary_norad"])
        secondary_norad = int(ev["secondary_norad"])
        tca_str  = str(ev.get("tca_utc", ""))
        miss_km  = float(ev.get("miss_distance_km", 0.0))
        pc       = float(ev.get("pc", 0.0))
        risk     = str(ev.get("risk_label", "UNKNOWN")).upper()
        rgba     = _RISK_RGBA.get(risk, _RISK_RGBA["UNKNOWN"])

        try:
            tca_dt = datetime.fromisoformat(tca_str.replace("Z", "+00:00"))
            if tca_dt.tzinfo is None:
                tca_dt = tca_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            logger.warning("conjunction_czml: cannot parse tca_utc=%s for event %d", tca_str, i)
            continue

        positions: dict[str, np.ndarray] = {}

        for norad, role, px_size in [
            (primary_norad,   "Primary",   20),
            (secondary_norad, "Secondary", 14),
        ]:
            tle_row = load_latest_tle_raw_row(norad)
            if tle_row is None:
                logger.warning("conjunction_czml: no TLE for NORAD %s", norad)
                continue
            r_eci = propagate_to_time(tle_row, tca_dt)
            if r_eci is None:
                logger.warning("conjunction_czml: SGP4 error for NORAD %s at TCA", norad)
                continue
            ecef_m = eci_to_ecef_m(r_eci, tca_dt)
            positions[role] = ecef_m

            desc_html = (
                "<table style='color:#ddd;font-size:13px;border-collapse:collapse'>"
                f"<tr><td>Role</td><td><b>{role}</b></td></tr>"
                f"<tr><td>NORAD</td><td><b>{norad}</b></td></tr>"
                f"<tr><td>TCA</td><td><b>{tca_dt.strftime('%Y-%m-%d %H:%M:%S')} UTC</b></td></tr>"
                f"<tr><td>Miss Distance</td><td><b>{miss_km:.3f} km</b></td></tr>"
                f"<tr><td>Pc</td><td><b>{pc:.2e}</b></td></tr>"
                f"<tr><td>Risk</td><td><b>"
                f"<span style='color:#{_rgba_to_hex(rgba)}'>{risk}</span></b></td></tr>"
                "</table>"
            )
            prefix = "★" if role == "Primary" else "◆"
            czml.append({
                "id":          f"conjunction/{i}/{role.lower()}/{norad}",
                "name":        f"{prefix} NORAD {norad} ({risk})",
                "description": desc_html,
                "position":    {
                    "cartesian": [
                        round(float(ecef_m[0]), 1),
                        round(float(ecef_m[1]), 1),
                        round(float(ecef_m[2]), 1),
                    ]
                },
                "point": {
                    "color":        {"rgba": rgba},
                    "pixelSize":    px_size,
                    "outlineColor": {"rgba": [255, 255, 255, 255]},
                    "outlineWidth": 2,
                },
                "label": {
                    "text":         f"{prefix} NORAD {norad}",
                    "font":         "11pt sans-serif",
                    "fillColor":    {"rgba": rgba},
                    "outlineColor": {"rgba": [0, 0, 0, 255]},
                    "outlineWidth": 2,
                    "style":        "FILL_AND_OUTLINE",
                    "pixelOffset":  {"cartesian2": [0, -26]},
                },
            })

        # Miss-vector polyline between TCA positions (cesiumjs-spatial-math: ECEF chord)
        if "Primary" in positions and "Secondary" in positions:
            p, s = positions["Primary"], positions["Secondary"]
            czml.append({
                "id":   f"conjunction/{i}/miss-line",
                "name": f"Miss vector: {miss_km:.3f} km ({risk})",
                "polyline": {
                    "positions": {"cartesian": [
                        round(float(p[0]), 1), round(float(p[1]), 1), round(float(p[2]), 1),
                        round(float(s[0]), 1), round(float(s[1]), 1), round(float(s[2]), 1),
                    ]},
                    "material": {"solidColor": {"color": {"rgba": rgba}}},
                    "width":    2.0,
                    "arcType":  "NONE",
                },
            })

    return czml


def resolve_snapshot_date(
    db_path: Path,
    target_norad: int,
    snapshot_date: str | None,
    max_lookback_days: int = 7,
) -> tuple[str | None, bool, dict[str, Any]]:
    info: dict[str, Any] = {
        "raw_tle_archive_checked": False,
        "raw_tle_archive_found": False,
        "tle_raw_checked": False,       # kept for API backward-compat
        "tle_raw_found_any": False,
        "tle_raw_found_on_window": False,
    }
    if snapshot_date is None:
        return None, False, info
    try:
        target_dt = date.fromisoformat(snapshot_date)
    except ValueError as exc:
        raise ValueError(f"snapshot_date must be YYYY-MM-DD, got: {snapshot_date}") from exc

    # Single connection for all checks — RAW_TABLE == RAW_ARCHIVE_TABLE == "raw_tle_archive"
    with connect_readonly(db_path) as con:
        info["raw_tle_archive_checked"] = True
        info["tle_raw_checked"] = True

        total_count = con.execute(
            f"SELECT COUNT(*) FROM {RAW_ARCHIVE_TABLE} WHERE norad_id = ?",
            [target_norad],
        ).fetchone()[0]
        info["raw_tle_archive_found"] = total_count > 0
        info["tle_raw_found_any"] = total_count > 0   # same table

        # Walk backwards up to max_lookback_days to find a TLE dated on that day
        for i in range(max_lookback_days + 1):
            check_str = (target_dt - timedelta(days=i)).isoformat()
            count = con.execute(
                f"""
                SELECT COUNT(*)
                FROM {RAW_ARCHIVE_TABLE}
                WHERE norad_id = ?
                  AND CAST(epoch_utc AS DATE) = ?
                """,
                [target_norad, check_str],
            ).fetchone()[0]
            if count > 0:
                return check_str, (i > 0), info

        # No TLE found anywhere in the lookback window
        window_count = con.execute(
            f"""
            SELECT COUNT(*)
            FROM {RAW_ARCHIVE_TABLE}
            WHERE norad_id = ?
              AND CAST(epoch_utc AS DATE) BETWEEN ? AND ?
            """,
            [target_norad,
             (target_dt - timedelta(days=max_lookback_days)).isoformat(),
             target_dt.isoformat()],
        ).fetchone()[0]
        info["tle_raw_found_on_window"] = window_count > 0

    return None, True, info


_STATIC_ROOT = Path(__file__).resolve().parent


def register_routes(app: Flask) -> None:
    @app.get("/")
    def index():
        p = _STATIC_ROOT / "index.html"
        if not p.is_file():
            return jsonify({"error": f"index.html not found in {_STATIC_ROOT}"}), 404
        return send_from_directory(str(_STATIC_ROOT), "index.html")

    @app.get("/<path:filename>")
    def static_files(filename: str):
        p = (_STATIC_ROOT / filename).resolve()
        if not p.is_file() or not str(p).startswith(str(_STATIC_ROOT)):
            return jsonify({"error": f"{filename} not found"}), 404
        return send_from_directory(str(_STATIC_ROOT), filename)

    @app.get("/api/norads")
    def list_norads():
        with connect_readonly(settings.raw_db_path) as con:
            df = con.execute(f"SELECT DISTINCT norad_id FROM {RAW_TABLE} ORDER BY norad_id").df()
        return jsonify(df["norad_id"].astype(int).tolist())

    @app.get("/api/orbit")
    def get_orbit():
        norad_id = parse_int_arg("norad_id", minimum=1)
        num_pts   = min(parse_int_arg("num_points", default=300, minimum=2), 2000)
        span_hours = min(parse_int_arg("span_hours", default=48, minimum=1), 240)
        row = load_latest_tle_raw_row(norad_id)
        if row is None:
            return jsonify({"error": f"no TLE for NORAD {norad_id}"}), 404
        positions = propagate_orbit(row, num_pts=num_pts, span_hours=span_hours)

        meta = None
        if settings.db_path.exists():
            with connect_readonly(settings.db_path) as con:
                meta = get_sat_n2yo_metadata(con, norad_id)

        name_en = meta.get("name_en") if meta else None
        launch_dt = meta.get("launch_date") if meta else None
        launch_site = meta.get("launch_site") if meta else None
        intl_code = meta.get("intl_code") if meta else None
        perigee_km = meta.get("perigee_km") if meta else None
        apogee_km = meta.get("apogee_km") if meta else None
        inclination = meta.get("inclination_deg") if meta else None
        period_min = meta.get("period_min") if meta else None
        sma_km = meta.get("sma_km") if meta else None
        rcs_text = meta.get("rcs_text") if meta else None
        source_code = meta.get("source_code") if meta else None
        desc_en = meta.get("website_desc_en") if meta else None
        desc_ch = meta.get("website_desc_ch") if meta else None
        launch_str = launch_dt if isinstance(launch_dt, str) else (launch_dt.strftime("%Y-%m-%d") if launch_dt else None)

        meta_text = f"NORAD {norad_id}\n(no sat_n2yo_metadata record)"
        if meta is not None:
            display_name = name_en or f"NORAD {norad_id}"
            meta_lines = [
                f"{display_name} (NORAD {norad_id}, SRC={source_code or 'N/A'})",
                f"Launch: {launch_str or 'N/A'} @ {launch_site or 'N/A'}",
            ]
            if desc_en:
                meta_lines.append((desc_en[:250] + "...") if len(desc_en) > 250 else desc_en)
            if desc_ch:
                meta_lines.append((desc_ch[:250] + "...") if len(desc_ch) > 250 else desc_ch)
            meta_text = "\n".join(meta_lines)

        return jsonify(
            {
                "norad_id": norad_id,
                "name": row.get("name") or "",
                "tle_epoch": str(row["epoch_jd"]),
                "positions_lla": positions,
                "name_en": name_en,
                "launch_date": launch_str,
                "launch_site": launch_site,
                "intl_code": intl_code,
                "perigee_km": perigee_km,
                "apogee_km": apogee_km,
                "inclination_deg": inclination,
                "period_min": period_min,
                "sma_km": sma_km,
                "rcs_text": rcs_text,
                "source_code": source_code,
                "website_desc_en": desc_en,
                "website_desc_ch": desc_ch,
                "meta_text": meta_text,
            }
        )

    @app.get("/api/conjunction")
    def api_conjunction():
        target_norad = parse_int_arg("norad", minimum=1)
        snapshot_date = request.args.get("snapshot_date") or None
        delta_a_km = parse_float_arg("delta_a_km", default=20.0, minimum=0.0)
        delta_i_deg = parse_float_arg("delta_i_deg", default=1.0, minimum=0.0)
        delta_raan_deg = parse_float_arg("delta_raan_deg", default=15.0, minimum=0.0)
        coarse_hours_before = parse_float_arg("coarse_hours_before", default=0.0, minimum=0.0)
        coarse_hours_after = parse_float_arg("coarse_hours_after", default=72.0, minimum=0.0)
        coarse_step_seconds = parse_int_arg("coarse_step_seconds", default=600, minimum=1)
        fine_window_minutes = parse_float_arg("fine_window_minutes", default=10.0, minimum=0.0)
        fine_step_seconds = parse_int_arg("fine_step_seconds", default=1, minimum=1)
        Rc_km = parse_float_arg("Rc_km", default=0.01, minimum=0.0)
        n_mc = parse_int_arg("n_mc", default=2000, minimum=1)

        resolved_date, was_fallback, snapshot_info = resolve_snapshot_date(
            db_path=settings.conj_db_path,
            target_norad=target_norad,
            snapshot_date=snapshot_date,
            max_lookback_days=7,
        )
        logger.info(
            "conjunction request norad=%s snapshot_date=%s resolved_date=%s was_fallback=%s snapshot_info=%s",
            target_norad, snapshot_date, resolved_date, was_fallback, snapshot_info
        )
        try:
            df = run_pipeline(
                db_path=str(settings.conj_db_path),
                target_norad=target_norad,
                snapshot_date=resolved_date,
                delta_a_km=delta_a_km,
                delta_i_deg=delta_i_deg,
                delta_raan_deg=delta_raan_deg,
                coarse_hours_before=coarse_hours_before,
                coarse_hours_after=coarse_hours_after,
                coarse_step_seconds=coarse_step_seconds,
                fine_window_minutes=fine_window_minutes,
                fine_step_seconds=fine_step_seconds,
                Rc_km=Rc_km,
                n_mc=n_mc,
            )

            events = []
            if not df.empty:
                events = [
                    {
                        "primary_norad": int(row.primary_norad),
                        "secondary_norad": int(row.secondary_norad),
                        "coarse_hit_time_utc": row.coarse_hit_time_utc.isoformat(),
                        "tca_utc": row.tca_utc.isoformat(),
                        "miss_distance_km": float(row.miss_distance_km),
                        "pc": float(row.pc),
                        "risk_label": row.risk_label,
                    }
                    for row in df.itertuples(index=False)
                ]

            return jsonify(
                {
                    "norad": target_norad,
                    "snapshot_date_requested": snapshot_date,
                    "snapshot_date_used": resolved_date,
                    "was_date_fallback": was_fallback,
                    "snapshot_info": snapshot_info,
                    "events": events,
                }
            )
        except Exception as e:
            logger.exception("run_pipeline failed for norad=%s", target_norad)
            return jsonify({
                "status": "error",
                "norad": target_norad,
                "snapshot_date_requested": snapshot_date,
                "error": {"type": type(e).__name__, "message": str(e)},
            }), 500

    @app.get("/api/conjunction_v2")
    def api_conjunction_v2():
        target_norad = parse_int_arg("norad", minimum=1)
        time_start_date = request.args.get("time_start_date") or None
        time_span_hours = parse_float_arg("time_span_hours", default=24.0, minimum=0.0)
        coarse_hours_before = parse_float_arg("coarse_hours_before", default=12.0, minimum=0.0)
        coarse_hours_after = parse_float_arg("coarse_hours_after", default=12.0, minimum=0.0)
        coarse_dt_sec = parse_int_arg("coarse_dt_sec", default=300, minimum=1)
        miss_threshold_km = parse_float_arg("miss_threshold_km", default=50.0, minimum=0.0)
        prefilter_padding_km = parse_float_arg("prefilter_padding_km", default=300.0, minimum=0.0)
        max_delta_inc_deg = parse_float_arg("max_delta_inc_deg", default=5.0, minimum=0.0)
        max_delta_raan_deg = parse_float_arg("max_delta_raan_deg", default=30.0, minimum=0.0)
        top_n = parse_int_arg("top_n", default=50, minimum=1)
        fine_window_minutes = parse_float_arg("fine_window_minutes", default=10.0, minimum=0.0)
        Rc_km = parse_float_arg("Rc_km", default=0.01, minimum=0.0)
        n_mc = parse_int_arg("n_mc", default=20000, minimum=1)
        sigma_r_km = parse_float_arg("sigma_r_km", default=1.0, minimum=0.0)
        sigma_t_km = parse_float_arg("sigma_t_km", default=5.0, minimum=0.0)
        sigma_n_km = parse_float_arg("sigma_n_km", default=3.0, minimum=0.0)
        chart_dt_sec = parse_int_arg("chart_dt_sec", default=300, minimum=1)
        debug = request.args.get("debug", "false").lower() in ("1", "true", "yes", "on")

        try:
            if time_start_date:
                dt = datetime.fromisoformat(time_start_date)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                time_start = dt.astimezone(timezone.utc)
                if "T" not in time_start_date:
                    time_start = time_start.replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                time_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

            result = run_ca_pipeline(
                db_path=str(settings.conj_db_path),
                target_norad_id=target_norad,
                time_start=time_start,
                time_span_hours=time_span_hours,
                coarse_dt_sec=coarse_dt_sec,
                miss_threshold_km=miss_threshold_km,
                prefilter_padding_km=prefilter_padding_km,
                max_delta_inc_deg=max_delta_inc_deg,
                max_delta_raan_deg=max_delta_raan_deg,
                top_n=top_n,
                debug=debug,
                coarse_hours_before=coarse_hours_before,
                coarse_hours_after=coarse_hours_after,
                fine_window_minutes=fine_window_minutes,
                Rc_km=Rc_km,
                n_mc=n_mc,
                sigma_r_km=sigma_r_km,
                sigma_t_km=sigma_t_km,
                sigma_n_km=sigma_n_km,
                chart_dt_sec=chart_dt_sec,
            )
            if result.get("status") != "ok":
                return jsonify(result), 500
            return jsonify(
                {
                    "norad": target_norad,
                    "time_start_requested": time_start_date,
                    "time_start_used": result.get("input", {}).get("time_start_utc"),
                    "summary": result.get("summary", {}),
                    "events": result.get("events", []),
                    "debug": result.get("debug", []),
                    "timing": result.get("timing", {}),
                }
            )
        except Exception as e:
            logger.exception("conjunction_v2 failed for norad=%s", target_norad)
            return jsonify(
                {
                    "status": "error",
                    "norad": target_norad,
                    "time_start_requested": time_start_date,
                    "error": {"type": type(e).__name__, "message": str(e)},
                }
            ), 500


def register_czml_routes(app: Flask) -> None:
    """
    Register the two CesiumJS-optimised CZML endpoints (new in v2).

    GET /api/orbit_czml
        ?norad_id=<int>
        &num_points=<int, default 300, max 2000>
        &span_hours=<int, default 48, max 240>
        → CZML JSON array  (load with CzmlDataSource.load())

    GET /api/conjunction_czml
        ?norad=<int>
        &time_start_date=<YYYY-MM-DD, optional>
        &time_span_hours=<float, default 24>
        &miss_threshold_km=<float, default 50>
        &max_events=<int, default 20, max 100>
        → CZML JSON array with TCA markers + miss-vector polylines
    """

    @app.get("/api/orbit_czml")
    def get_orbit_czml():
        """
        Returns a CZML document for a satellite's animated orbit.

        Frontend snippet (cesiumjs-core-utilities Resource pattern):
            const czml = await Cesium.Resource.fetchJson({
                url: '/api/orbit_czml',
                queryParameters: { norad_id: 49336 }
            });
            viewer.dataSources.add(Cesium.CzmlDataSource.load(czml));
        """
        norad_id   = parse_int_arg("norad_id", minimum=1)
        num_pts    = min(parse_int_arg("num_points",  default=300, minimum=2), 2000)
        span_hours = min(parse_int_arg("span_hours",  default=48,  minimum=1), 240)

        row = load_latest_tle_raw_row(norad_id)
        if row is None:
            return jsonify({"error": f"no TLE for NORAD {norad_id}"}), 404

        meta = None
        if settings.db_path.exists():
            with connect_readonly(settings.db_path) as con:
                meta = get_sat_n2yo_metadata(con, norad_id)

        czml_packets = build_orbit_czml(norad_id, row, meta, num_pts=num_pts, span_hours=span_hours)
        return app.response_class(
            json.dumps(czml_packets, separators=(",", ":")),
            mimetype="application/json",
        )

    @app.get("/api/conjunction_czml")
    def api_conjunction_czml():
        """
        Runs the CA pipeline and returns a CZML document with TCA markers.

        Each conjunction event renders as:
          • Primary satellite point (larger, risk-coloured)
          • Secondary satellite point (smaller, same colour)
          • Polyline between them (miss-vector geometry)
        Entity descriptions provide InfoBox data on click (cesiumjs-interaction skill).

        Frontend snippet:
            const czml = await Cesium.Resource.fetchJson({
                url: '/api/conjunction_czml',
                queryParameters: { norad: 49336, time_span_hours: 24 }
            });
            viewer.dataSources.add(Cesium.CzmlDataSource.load(czml));
        """
        target_norad      = parse_int_arg("norad", minimum=1)
        time_start_date   = request.args.get("time_start_date") or None
        time_span_hours   = parse_float_arg("time_span_hours",   default=24.0,  minimum=0.0)
        miss_threshold_km = parse_float_arg("miss_threshold_km", default=50.0,  minimum=0.0)
        max_events        = min(parse_int_arg("max_events",       default=20,    minimum=1), 100)

        try:
            if time_start_date:
                dt = datetime.fromisoformat(time_start_date)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                time_start = dt.astimezone(timezone.utc)
                if "T" not in time_start_date:
                    time_start = time_start.replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                time_start = datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )

            result = run_ca_pipeline(
                db_path=str(settings.conj_db_path),
                target_norad_id=target_norad,
                time_start=time_start,
                time_span_hours=time_span_hours,
                miss_threshold_km=miss_threshold_km,
            )
            if result.get("status") != "ok":
                return jsonify({"error": "pipeline failed", "detail": result}), 500

            events = result.get("events", [])[:max_events]
            czml_packets = build_conjunction_czml(events)
            return app.response_class(
                json.dumps(czml_packets, separators=(",", ":")),
                mimetype="application/json",
            )

        except Exception as e:
            logger.exception("conjunction_czml failed for norad=%s", target_norad)
            return jsonify({
                "status": "error",
                "norad": target_norad,
                "error": {"type": type(e).__name__, "message": str(e)},
            }), 500


app = create_app()

if __name__ == "__main__":
    app.run(host=settings.host, port=settings.port, debug=settings.debug)
