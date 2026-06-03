"""
DuckDB-backed SP3 file index.

Schema (table: sp3_index)
    file_path          TEXT PRIMARY KEY
    ac                 TEXT
    start_time         TIMESTAMPTZ
    end_time           TIMESTAMPTZ
    has_galileo        BOOLEAN
    n_galileo_epochs   INTEGER
    creation_time      TIMESTAMPTZ
"""
from __future__ import annotations

import gzip
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS sp3_index (
    file_path          TEXT PRIMARY KEY,
    ac                 TEXT,
    start_time         TIMESTAMPTZ,
    end_time           TIMESTAMPTZ,
    has_galileo        BOOLEAN,
    n_galileo_epochs   INTEGER,
    creation_time      TIMESTAMPTZ
);
"""

_EPOCH_RE = re.compile(
    r"^\*\s+(\d{4})\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)"
)


# ── Fast header scan (no full parse needed for indexing) ──────────────────────

def _open_sp3_text(path: Path):
    return (
        gzip.open(path, "rt", encoding="ascii", errors="replace")
        if path.suffix == ".gz"
        else open(path, "r", encoding="ascii", errors="replace")
    )


def _quick_meta(sp3_path: Path) -> dict:
    """
    Scan an SP3 file to extract index metadata without building a DataFrame.
    Only reads `*` epoch lines and `P` record types — fast even for large files.
    """
    from .sp3_parser import _infer_ac  # local import avoids circular dependency

    ac = _infer_ac(sp3_path)
    start_time: pd.Timestamp | None = None
    end_time: pd.Timestamp | None = None
    n_galileo = 0
    has_galileo = False

    with _open_sp3_text(sp3_path) as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line:
                continue

            if line[0] == "*":
                m = _EPOCH_RE.match(line)
                if m:
                    yr, mo, dy, hr, mi = [int(m.group(i)) for i in range(1, 6)]
                    sec_f = float(m.group(6))
                    sec_i = int(sec_f)
                    ns = int(round((sec_f - sec_i) * 1e9))
                    t = pd.Timestamp(yr, mo, dy, hr, mi, sec_i, nanosecond=ns, tz="UTC")
                    if start_time is None:
                        start_time = t
                    end_time = t

            elif len(line) > 3 and line[0] == "P" and line[1] == "E":
                has_galileo = True
                n_galileo += 1

            elif line.startswith("EOF"):
                break

    return {
        "file_path": str(sp3_path.resolve()),
        "ac": ac,
        "start_time": start_time,
        "end_time": end_time,
        "has_galileo": has_galileo,
        "n_galileo_epochs": n_galileo,
        "creation_time": datetime.now(tz=timezone.utc),
    }


# ── Public API ─────────────────────────────────────────────────────────────────

def build_sp3_index(
    sp3_files: list[Path],
    index_db: Path,
) -> None:
    """
    Build or update the SP3 index in `index_db` for the given file list.

    Existing entries (matched by file_path) are replaced so re-running is safe.

    Parameters
    ----------
    sp3_files : Paths to SP3 or SP3.gz files to index.
    index_db  : DuckDB database file (created if absent).
    """
    index_db = Path(index_db)
    index_db.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(index_db))
    con.execute(_DDL)

    processed = 0
    for sp3 in sp3_files:
        sp3 = Path(sp3)
        if not sp3.exists():
            logger.warning("File not found, skipping: %s", sp3)
            continue
        try:
            meta = _quick_meta(sp3)
        except Exception as exc:
            logger.warning("Failed to scan %s: %s", sp3.name, exc)
            continue

        con.execute(
            """
            INSERT OR REPLACE INTO sp3_index
                (file_path, ac, start_time, end_time,
                 has_galileo, n_galileo_epochs, creation_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                meta["file_path"],
                meta["ac"],
                meta["start_time"],
                meta["end_time"],
                meta["has_galileo"],
                meta["n_galileo_epochs"],
                meta["creation_time"],
            ],
        )
        processed += 1
        logger.debug(
            "Indexed %s (%d Galileo epochs)",
            sp3.name,
            meta["n_galileo_epochs"],
        )

    con.close()
    print(f"[index] {processed}/{len(sp3_files)} files indexed → {index_db}")


def query_sp3_files_for_interval(
    index_db: Path,
    start_time: pd.Timestamp,
    end_time: pd.Timestamp,
    require_galileo: bool = True,
) -> list[Path]:
    """
    Return SP3 files whose coverage overlaps [start_time, end_time].

    Parameters
    ----------
    index_db       : DuckDB database created by build_sp3_index.
    start_time     : Query interval start (tz-aware recommended).
    end_time       : Query interval end.
    require_galileo: Only return files where has_galileo = TRUE.

    Returns
    -------
    List of Path objects sorted by start_time ascending.
    """
    index_db = Path(index_db)
    if not index_db.exists():
        raise FileNotFoundError(f"Index DB not found: {index_db}")

    gal_clause = "AND has_galileo = TRUE" if require_galileo else ""
    con = duckdb.connect(str(index_db), read_only=True)
    rows = con.execute(
        f"""
        SELECT file_path
        FROM sp3_index
        WHERE start_time <= ?
          AND end_time   >= ?
          {gal_clause}
        ORDER BY start_time ASC
        """,
        [end_time, start_time],
    ).fetchall()
    con.close()

    return [Path(r[0]) for r in rows]
