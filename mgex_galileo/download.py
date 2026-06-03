"""
MGEX Galileo SP3 downloader.

Publicly accessible sources (no authentication required):
  COD   https://ftp.aiub.unibe.ch/CODE_MGEX/CODE/{YYYY}/
  GFZ   https://igs.gfz-potsdam.de/pub/gnss/products/mgex/{WWWW}/
  IGN   https://igs.ign.fr/pub/igs/products/mgex/{WWWW}/   (mirror)
  BKG   https://igs.bkg.bund.de/root_ftp/MGEX/products/{WWWW}/  (mirror)

NASA CDDIS (requires free Earthdata account — https://urs.earthdata.nasa.gov/):
  CDDIS https://cddis.nasa.gov/archive/gnss/products/mgex/{WWWW}/
  Configure via:  ~/.netrc  OR  env vars EARTHDATA_USER / EARTHDATA_PASS

IGS3 long-filename convention started ~2022-11-27 (GPS week 2238).
  New naming : {AC}0MGXFIN_{YYYY}{DDD}0000_01D_05M_ORB.SP3.gz  (.gz)
  Old naming : {ac}{WWWWD}.sp3.Z                                (.Z — needs unlzw3)

For .Z decompression install: pip install unlzw3
"""
from __future__ import annotations

import datetime
import gzip
import logging
import netrc
import os
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

GPS_EPOCH = datetime.date(1980, 1, 6)

# IGS renamed products to long-filename convention from this date onwards.
IGS3_CUTOFF = datetime.date(2022, 11, 27)

DEFAULT_AC_PRIORITY: list[str] = ["COD", "GFZ"]
MAX_RETRIES = 2
RETRY_DELAY_S = 3.0
# (connect_timeout, read_timeout) — short connect so dead servers fail fast.
TIMEOUT_S = (20, 300)

# NASA Earthdata host used in ~/.netrc
_EARTHDATA_HOST = "urs.earthdata.nasa.gov"
_CDDIS_BASE = "https://cddis.nasa.gov/archive/gnss/products"


def _earthdata_auth() -> tuple[str, str] | None:
    """
    Return (user, password) for NASA Earthdata CDDIS access, or None.

    Priority:
      1. .env file  EOSDIS_IDENTITY / EOSDIS_PASSWORD  (loaded from project root)
      2. Env vars   EOSDIS_IDENTITY / EOSDIS_PASSWORD  (already exported)
      3. ~/.netrc   machine urs.earthdata.nasa.gov login <u> password <p>
    """
    # Load .env from the project root (two levels above this file: mgex_galileo/download.py)
    try:
        from dotenv import load_dotenv  # type: ignore[import]
        _env_file = Path(__file__).resolve().parents[1] / ".env"
        load_dotenv(_env_file, override=False)   # don't overwrite already-set env vars
    except Exception:
        pass

    user = os.environ.get("EOSDIS_IDENTITY")
    pw   = os.environ.get("EOSDIS_PASSWORD")
    if user and pw:
        return user, pw

    try:
        nrc = netrc.netrc()
        entry = nrc.authenticators(_EARTHDATA_HOST)
        if entry:
            return entry[0], entry[2]
    except Exception:
        pass
    return None


# ── Time helpers ───────────────────────────────────────────────────────────────

def _gps_week_dow(d: datetime.date) -> tuple[int, int]:
    delta = (d - GPS_EPOCH).days
    return delta // 7, delta % 7


def _doy(d: datetime.date) -> int:
    return d.timetuple().tm_yday


# ── URL catalogue ──────────────────────────────────────────────────────────────

def _candidate_urls(d: datetime.date, ac: str) -> list[tuple[str, bool]]:
    """
    Return ordered candidate (url, needs_auth) pairs for (date, AC).

    Each AC tries its primary server first, then IGN/BKG mirrors, then
    NASA CDDIS (needs_auth=True, requires Earthdata credentials).
    Tries new IGS3 names (.gz) before old 8-char names (.Z).
    """
    week, dow = _gps_week_dow(d)
    doy = _doy(d)
    year = d.year
    new = d >= IGS3_CUTOFF

    _ign   = f"https://igs.ign.fr/pub/igs/products/mgex/{week:04d}"
    _bkg   = f"https://igs.bkg.bund.de/root_ftp/MGEX/products/{week:04d}"
    _cddis = f"{_CDDIS_BASE}/{week:04d}"

    def _pub(url: str) -> tuple[str, bool]:
        return (url, False)

    def _auth(url: str) -> tuple[str, bool]:
        return (url, True)

    pairs: list[tuple[str, bool]] = []

    if ac == "COD":
        primary = f"https://ftp.aiub.unibe.ch/CODE_MGEX/CODE/{year}"
        if new:
            fname = f"COD0MGXFIN_{year}{doy:03d}0000_01D_05M_ORB.SP3.gz"
            pairs += [_pub(f"{primary}/{fname}"),
                      _pub(f"{_ign}/{fname}"),
                      _pub(f"{_bkg}/{fname}"),
                      _auth(f"{_cddis}/{fname}")]
        else:
            pairs += [_pub(f"{primary}/com{week:04d}{dow}.sp3.Z"),
                      _pub(f"{primary}/com{week:04d}{dow}.eph.Z")]

    elif ac == "GFZ":
        primary = f"https://igs.gfz-potsdam.de/pub/gnss/products/mgex/{week:04d}"
        if new:
            fin = f"GFZ0MGXFIN_{year}{doy:03d}0000_01D_05M_ORB.SP3.gz"
            rap = f"GFZ0MGXRAP_{year}{doy:03d}0000_01D_05M_ORB.SP3.gz"
            pairs += [_pub(f"{primary}/{fin}"),
                      _pub(f"{_ign}/{fin}"),
                      _pub(f"{_bkg}/{fin}"),
                      _auth(f"{_cddis}/{fin}"),
                      _pub(f"{primary}/{rap}"),
                      _pub(f"{_ign}/{rap}"),
                      _pub(f"{_bkg}/{rap}"),
                      _auth(f"{_cddis}/{rap}")]
        else:
            pairs += [_pub(f"{primary}/gbm{week:04d}{dow}.sp3.Z"),
                      _pub(f"{primary}/gbm{week:04d}{dow}.sp3.gz")]

    elif ac == "GRG":
        primary = f"https://igs.gfz-potsdam.de/pub/gnss/products/mgex/{week:04d}"
        if new:
            fname = f"GRG0MGXFIN_{year}{doy:03d}0000_01D_05M_ORB.SP3.gz"
            pairs += [_pub(f"{primary}/{fname}"),
                      _pub(f"{_ign}/{fname}"),
                      _pub(f"{_bkg}/{fname}"),
                      _auth(f"{_cddis}/{fname}")]
        else:
            pairs += [_pub(f"{primary}/grg{week:04d}{dow}.sp3.Z")]

    else:
        logger.warning("Unknown AC '%s' — no URL template defined.", ac)

    return pairs


# ── Decompression ──────────────────────────────────────────────────────────────

def _decompress(path: Path) -> Path:
    """
    Decompress a .gz or .Z file in-place and return the decompressed path.
    Returns `path` unchanged if no compression is detected.
    Raises RuntimeError for .Z when unlzw3 is not installed.
    """
    if path.suffix == ".gz":
        dest = path.with_suffix("")
        with gzip.open(path, "rb") as src, open(dest, "wb") as dst:
            dst.write(src.read())
        path.unlink()
        logger.debug("Decompressed %s → %s", path.name, dest.name)
        return dest

    if path.suffix == ".Z":
        try:
            from unlzw3 import unlzw  # type: ignore[import]
        except ImportError:
            raise RuntimeError(
                f"Cannot decompress {path.name}: install 'unlzw3'  "
                "(pip install unlzw3)"
            )
        dest = path.with_suffix("")
        dest.write_bytes(unlzw(path.read_bytes()))
        path.unlink()
        logger.debug("Decompressed (LZW) %s → %s", path.name, dest.name)
        return dest

    return path


# ── Single-URL fetch ───────────────────────────────────────────────────────────

def _decompressed_name(compressed_name: str) -> str:
    for ext in (".gz", ".Z"):
        if compressed_name.endswith(ext):
            return compressed_name[: -len(ext)]
    return compressed_name


# Hosts that timed out in the current session — skip without retrying.
_dead_hosts: set[str] = set()
# CDDIS session (reused across calls to avoid re-authenticating per file)
_cddis_session: "requests.Session | None" = None


def _host_of(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).netloc


class _EarthdataSession(requests.Session):
    """
    requests.Session that re-applies basic auth when the server redirects to
    urs.earthdata.nasa.gov (which is cross-domain, so the default session
    strips Authorization headers on that hop).
    """

    def __init__(self, username: str, password: str) -> None:
        super().__init__()
        self._ed_creds = (username, password)
        self.auth = self._ed_creds

    def rebuild_auth(self, prepared_request, response):
        super().rebuild_auth(prepared_request, response)
        # If auth was stripped because the redirect went to earthdata, restore it.
        if (prepared_request.headers.get("Authorization") is None
                and "urs.earthdata.nasa.gov" in prepared_request.url):
            from requests.auth import HTTPBasicAuth
            HTTPBasicAuth(*self._ed_creds)(prepared_request)


def _get_cddis_session() -> "requests.Session | None":
    """
    Build (or reuse) a session authenticated against NASA Earthdata / CDDIS.

    CDDIS redirects to urs.earthdata.nasa.gov for OAuth.  _EarthdataSession
    re-injects basic-auth credentials on that cross-domain hop so the OAuth
    token is granted and a CDDIS cookie is stored for subsequent requests.
    Returns None if no credentials are configured.
    """
    global _cddis_session
    if _cddis_session is not None:
        return _cddis_session

    creds = _earthdata_auth()
    if creds is None:
        return None

    user, pw = creds
    session = _EarthdataSession(user, pw)

    # Warm the session: follow the full auth redirect chain on a small CDDIS page.
    try:
        r = session.get(
            "https://cddis.nasa.gov/archive/gnss/products/mgex/",
            timeout=TIMEOUT_S,
            allow_redirects=True,
        )
        if "earthdata" in r.url.lower() or r.status_code in (401, 403):
            logger.warning(
                "CDDIS Earthdata authentication failed — check EOSDIS_IDENTITY/EOSDIS_PASSWORD."
            )
            return None
        logger.info("CDDIS Earthdata session established (user=%s)", user)
    except Exception as exc:
        logger.warning("CDDIS session warm-up failed: %s", exc)
        return None

    _cddis_session = session
    return session


def _fetch_url(
    url: str,
    out_dir: Path,
    retries: int = MAX_RETRIES,
    needs_auth: bool = False,
) -> Path | None:
    """
    Download `url` into `out_dir`, decompress if needed.

    Returns the local path on success, None on 404/timeout/repeated failure.
    Skips download if the decompressed file already exists — checked BEFORE
    any dead-host or network logic so re-runs are instant for cached files.
    needs_auth=True uses the CDDIS Earthdata session.
    """
    fname = url.split("/")[-1]
    final_name = _decompressed_name(fname)
    final_path = out_dir / final_name

    if final_path.exists():
        logger.info("Already cached: %s", final_path.name)
        return final_path

    host = _host_of(url)
    if host in _dead_hosts:
        logger.debug("Skipping dead host %s: %s", host, url)
        return None

    if needs_auth:
        session = _get_cddis_session()
        if session is None:
            logger.debug(
                "CDDIS skipped (no Earthdata credentials). "
                "Set EOSDIS_IDENTITY/EOSDIS_PASSWORD in .env or ~/.netrc"
            )
            return None
    else:
        session = None   # use plain requests

    compressed_path = out_dir / fname
    out_dir.mkdir(parents=True, exist_ok=True)

    connect_errors = 0
    for attempt in range(1, retries + 1):
        try:
            logger.debug("GET %s (attempt %d/%d)", url, attempt, retries)
            getter = session.get if session else requests.get
            r = getter(url, timeout=TIMEOUT_S, stream=True)
            if r.status_code == 404:
                logger.debug("404: %s", url)
                return None
            # Detect CDDIS auth redirect disguised as 200
            if needs_auth and "earthdata" in r.url.lower():
                logger.warning("CDDIS redirected to Earthdata login — credentials may be wrong.")
                return None
            r.raise_for_status()

            with open(compressed_path, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)

            try:
                return _decompress(compressed_path)
            except RuntimeError as exc:
                logger.warning("%s", exc)
                compressed_path.unlink(missing_ok=True)
                return None

        except requests.HTTPError:
            return None
        except Exception as exc:
            connect_errors += 1
            logger.warning(
                "Attempt %d/%d failed for %s: %s", attempt, retries, url, exc
            )
            compressed_path.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(RETRY_DELAY_S)

    # If every attempt was a connection/timeout error, mark the host as dead
    # so we don't waste time on it for the remaining 100+ days.
    if connect_errors == retries:
        logger.warning("Host %s unreachable — skipping for this session.", host)
        _dead_hosts.add(host)

    return None


# ── Per-day download ───────────────────────────────────────────────────────────

def _download_day(d: datetime.date, out_dir: Path, acs: list[str]) -> Path | None:
    """Try each AC in priority order for one calendar day."""
    for ac in acs:
        for url, needs_auth in _candidate_urls(d, ac):
            local = _fetch_url(url, out_dir, needs_auth=needs_auth)
            if local is not None:
                logger.info("[%s] %s ← %s", d, local.name, ac)
                return local
    return None


# ── Public API ─────────────────────────────────────────────────────────────────

def download_galileo_sp3(
    start_date: datetime.date,
    end_date: datetime.date,
    out_dir: Path,
    ac_priority: list[str] | None = None,
    use_gnss_lib_py: bool = False,
) -> list[Path]:
    """
    Download MGEX SP3 files covering [start_date, end_date] (inclusive).

    Parameters
    ----------
    start_date, end_date : UTC date range (both inclusive).
    out_dir : Directory for downloaded SP3 files (created if absent).
    ac_priority : AC preference order, e.g. ["COD", "GFZ", "GRG"].
                  Defaults to ["COD", "GFZ"].
    use_gnss_lib_py : Delegate to gnss_lib_py.ephemeris_downloader when True.

    Returns
    -------
    List of local SP3 file paths (downloaded now or already cached).
    Missing days are logged as warnings but do not raise.
    """
    out_dir = Path(out_dir)
    acs = ac_priority or DEFAULT_AC_PRIORITY

    if use_gnss_lib_py:
        return _download_via_gnss_lib_py(start_date, end_date, out_dir, acs)

    found: list[Path] = []
    day = start_date
    while day <= end_date:
        result = _download_day(day, out_dir, acs)
        if result:
            found.append(result)
            print(f"  [ok] {day}  {result.name}")
        else:
            logger.warning("No SP3 found for %s (ACs: %s)", day, acs)
            print(f"  [miss] {day}  (no file from {acs})")
        day += datetime.timedelta(days=1)

    return found


def _download_via_gnss_lib_py(
    start_date: datetime.date,
    end_date: datetime.date,
    out_dir: Path,
    acs: list[str],
) -> list[Path]:
    try:
        from gnss_lib_py.utils.ephemeris_downloader import load_ephemeris  # type: ignore[import]
    except ImportError:
        raise ImportError(
            "gnss_lib_py is not installed — run: pip install gnss_lib_py"
        )

    GPS_EPOCH_DT = datetime.datetime(1980, 1, 6, tzinfo=datetime.timezone.utc)

    def to_gps_ms(d: datetime.date) -> float:
        dt = datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc)
        return (dt - GPS_EPOCH_DT).total_seconds() * 1000.0

    paths: list[Path] = []
    try:
        result = load_ephemeris(
            file_type="sp3",
            gps_millis_start=to_gps_ms(start_date),
            gps_millis_end=to_gps_ms(end_date) + 86_400_000,
            constellation="galileo",
            download_directory=str(out_dir),
        )
        if result is not None:
            for p in result:
                paths.append(Path(p))
    except Exception as exc:
        logger.error("gnss_lib_py download failed: %s", exc)

    return paths
