"""
SQLite cache for internet utility providers (county-level from FCC Location Coverage).

This module uses a dedicated table for internet only. Other utility types (electric, gas, water, etc.)
will have their own tables (and possibly their own modules/DBs) when added—do not mix utility types
in the same table.

Lookup key: (state_fips, county_fips) from Census Geocoder (address -> Smarty -> lat/lon -> Census).
Stored: one row per (state_fips, county_fips, provider_name); as_of_date for refresh tracking.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

# Per-utility tables in the same DB (see docs/UTILITY_PROVIDERS_CURRENT.md).
_TABLE = "internet_provider_cache"
_PENDING_TABLE = "pending_county_refresh"
_WATER_TABLE = "water_provider_cache"
_BDC_FALLBACK_TABLE = "internet_bdc_fallback"
_PENDING_PROVIDERS_TABLE = "pending_providers"  # user-added providers not in our list; details fetched later


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_db_path() -> str:
    """Resolve SQLite DB path from config or default."""
    from app.config import get_settings
    settings = get_settings()
    p = (settings.fcc_internet_cache_path or "").strip()
    if p and os.path.isabs(p):
        return p
    if p:
        return str(_project_root() / p)
    return str(_project_root() / "data" / "utility_providers" / "internet_cache.db")


def get_connection(read_only: bool = False) -> sqlite3.Connection:
    """Open SQLite connection; create parent dir if needed."""
    path = get_db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_water_table_only(conn: sqlite3.Connection) -> None:
    """Ensure only the water_provider_cache table exists (and contactemail column). Used by water lookup so we do not run pending_providers migrations/indexes, which can fail on old DBs with 'no such column: property_id'."""
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS {_WATER_TABLE} (
            pwsid TEXT NOT NULL PRIMARY KEY,
            pwsname TEXT NOT NULL,
            state TEXT,
            contactcity TEXT,
            contactstate TEXT NOT NULL,
            contactphone TEXT,
            contactemail TEXT,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_water_cache_state_city
        ON {_WATER_TABLE} (contactstate, contactcity);
    """)
    try:
        cur = conn.execute(f"PRAGMA table_info({_WATER_TABLE})")
        columns = [row[1] for row in cur.fetchall()]
        if "contactemail" not in columns:
            conn.execute(f"ALTER TABLE {_WATER_TABLE} ADD COLUMN contactemail TEXT")
            conn.commit()
    except Exception:
        pass
    conn.commit()


def ensure_tables(conn: sqlite3.Connection) -> None:
    """Create all utility cache tables if they do not exist (internet, water, internet BDC fallback)."""
    # Create tables (no indexes on pending_providers yet — we migrate that table first if it's old)
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            state_fips TEXT NOT NULL,
            county_fips TEXT NOT NULL,
            provider_name TEXT NOT NULL,
            as_of_date TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (state_fips, county_fips, provider_name)
        );
        CREATE INDEX IF NOT EXISTS idx_internet_cache_county
        ON {_TABLE} (state_fips, county_fips);

        CREATE TABLE IF NOT EXISTS {_PENDING_TABLE} (
            state_fips TEXT NOT NULL,
            county_fips TEXT NOT NULL,
            enqueued_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (state_fips, county_fips)
        );

        CREATE TABLE IF NOT EXISTS {_WATER_TABLE} (
            pwsid TEXT NOT NULL PRIMARY KEY,
            pwsname TEXT NOT NULL,
            state TEXT,
            contactcity TEXT,
            contactstate TEXT NOT NULL,
            contactphone TEXT,
            contactemail TEXT,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_water_cache_state_city
        ON {_WATER_TABLE} (contactstate, contactcity);

        CREATE TABLE IF NOT EXISTS {_BDC_FALLBACK_TABLE} (
            rank INTEGER NOT NULL,
            provider_name TEXT NOT NULL,
            total_units INTEGER NOT NULL,
            as_of_date TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (rank)
        );
        CREATE INDEX IF NOT EXISTS idx_bdc_fallback_rank
        ON {_BDC_FALLBACK_TABLE} (rank);

        CREATE TABLE IF NOT EXISTS {_PENDING_PROVIDERS_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider_type TEXT NOT NULL,
            provider_name TEXT NOT NULL,
            property_id INTEGER,
            state TEXT,
            county TEXT,
            verification_status TEXT NOT NULL DEFAULT 'pending',
            verified_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_pending_providers_type
        ON {_PENDING_PROVIDERS_TABLE} (provider_type);
    """)
    # Migration: add contactemail to water_provider_cache if table existed without it
    try:
        cur = conn.execute(f"PRAGMA table_info({_WATER_TABLE})")
        columns = [row[1] for row in cur.fetchall()]
        if "contactemail" not in columns:
            conn.execute(f"ALTER TABLE {_WATER_TABLE} ADD COLUMN contactemail TEXT")
            conn.commit()
    except Exception:
        pass
    # Migration: add pending_providers columns if table existed without them (e.g. old DB)
    # Must run before creating indexes on property_id/verification_status or they fail
    try:
        cur = conn.execute(f"PRAGMA table_info({_PENDING_PROVIDERS_TABLE})")
        columns = [row[1] for row in cur.fetchall()]
        for col, typ in [("property_id", "INTEGER"), ("state", "TEXT"), ("county", "TEXT"), ("verification_status", "TEXT"), ("verified_at", "TEXT")]:
            if col not in columns:
                conn.execute(f"ALTER TABLE {_PENDING_PROVIDERS_TABLE} ADD COLUMN {col} {typ}")
        conn.execute(f"UPDATE {_PENDING_PROVIDERS_TABLE} SET verification_status = 'pending' WHERE verification_status IS NULL")
        conn.commit()
    except Exception:
        pass
    # Create indexes that depend on possibly-migrated columns (after migration so old DBs get columns first)
    try:
        conn.executescript(f"""
            CREATE INDEX IF NOT EXISTS idx_pending_providers_property
            ON {_PENDING_PROVIDERS_TABLE} (property_id);
            CREATE INDEX IF NOT EXISTS idx_pending_providers_verification
            ON {_PENDING_PROVIDERS_TABLE} (verification_status);
        """)
        conn.commit()
    except Exception:
        pass
    conn.commit()


def get_internet_providers_for_county(state_fips: str, county_fips: str) -> List[str]:
    """
    Look up cached internet provider names for (state_fips, county_fips).
    Returns empty list on miss or if not in cache.
    state_fips = 2 digits (e.g. 06), county_fips = 3 digits (e.g. 085).
    """
    state_fips = (state_fips or "").strip()
    county_fips = (county_fips or "").strip()
    if len(state_fips) != 2 or len(county_fips) != 3:
        return []
    try:
        conn = get_connection(read_only=True)
        try:
            ensure_tables(conn)
            cur = conn.execute(
                f"SELECT provider_name FROM {_TABLE} WHERE state_fips = ? AND county_fips = ? ORDER BY provider_name",
                (state_fips, county_fips),
            )
            return [row[0] for row in cur.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Internet cache lookup failed: %s", e)
        return []


def upsert_county_providers(
    state_fips: str,
    county_fips: str,
    provider_names: List[str],
    as_of_date: str,
    conn: sqlite3.Connection | None = None,
) -> None:
    """
    Replace cached providers for (state_fips, county_fips) with the given list.
    as_of_date = FCC data vintage (e.g. 2025-06-30).
    """
    state_fips = (state_fips or "").strip()
    county_fips = (county_fips or "").strip()
    if len(state_fips) != 2 or len(county_fips) != 3:
        return
    own = conn is None
    if conn is None:
        conn = get_connection()
    try:
        ensure_tables(conn)
        # Dedupe provider names (same county must not have duplicate provider_name)
        orig_count = sum(1 for n in provider_names if (n or "").strip())
        seen_names = list(dict.fromkeys((n or "").strip() for n in provider_names))
        provider_names = [n for n in seen_names if n]
        if len(provider_names) < orig_count:
            logger.debug("Internet county cache: deduped providers for %s/%s from %d to %d", state_fips, county_fips, orig_count, len(provider_names))
        conn.execute(f"DELETE FROM {_TABLE} WHERE state_fips = ? AND county_fips = ?", (state_fips, county_fips))
        now = __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        for name in provider_names:
            conn.execute(
                f"INSERT INTO {_TABLE} (state_fips, county_fips, provider_name, as_of_date, updated_at) VALUES (?, ?, ?, ?, ?)",
                (state_fips, county_fips, name, as_of_date, now),
            )
        conn.commit()
    finally:
        if own and conn:
            conn.close()


def enqueue_county_for_refresh(state_fips: str, county_fips: str) -> None:
    """Optionally record (state_fips, county_fips) for next background job run."""
    state_fips = (state_fips or "").strip()
    county_fips = (county_fips or "").strip()
    if len(state_fips) != 2 or len(county_fips) != 3:
        return
    try:
        conn = get_connection()
        try:
            ensure_tables(conn)
            conn.execute(
                f"INSERT OR REPLACE INTO {_PENDING_TABLE} (state_fips, county_fips, enqueued_at) VALUES (?, ?, datetime('now'))",
                (state_fips, county_fips),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Enqueue county for refresh failed: %s", e)


def get_pending_counties() -> List[tuple[str, str]]:
    """Return list of (state_fips, county_fips) enqueued for refresh."""
    try:
        conn = get_connection(read_only=True)
        try:
            ensure_tables(conn)
            cur = conn.execute(f"SELECT state_fips, county_fips FROM {_PENDING_TABLE}")
            return [tuple(row) for row in cur.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Get pending counties failed: %s", e)
        return []


# ---------- Water provider cache (EPA SDWIS CSV) ----------


def upsert_water_providers_bulk(
    rows: List[dict],
    conn: sqlite3.Connection | None = None,
) -> int:
    """
    Replace all rows in water_provider_cache with the given list.
    Each row dict must have keys: pwsid, pwsname, state, contactcity, contactstate, contactphone, status;
    contactemail is optional.
    Duplicate pwsid in input are deduped (last occurrence wins). Uses INSERT OR REPLACE for idempotency.
    Returns number of rows written.
    """
    own = conn is None
    if conn is None:
        conn = get_connection()
    try:
        ensure_tables(conn)
        # Dedupe by pwsid (last occurrence wins) so we never insert duplicate pwsid
        by_pwsid: dict[str, dict] = {}
        for row in rows:
            pwsid = (row.get("pwsid") or "").strip()
            if pwsid:
                by_pwsid[pwsid] = row
        if len(by_pwsid) < len(rows):
            logger.info("Water cache: deduped by pwsid from %d to %d rows", len(rows), len(by_pwsid))
        conn.execute(f"DELETE FROM {_WATER_TABLE}")
        now = __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        count = 0
        for row in by_pwsid.values():
            pwsid = (row.get("pwsid") or "").strip()
            pwsname = (row.get("pwsname") or "").strip() or ""
            state = (row.get("state") or "").strip()
            contactcity = (row.get("contactcity") or "").strip()
            contactstate = (row.get("contactstate") or "").strip()
            contactphone = (row.get("contactphone") or "").strip()
            contactemail = (row.get("contactemail") or row.get("EMAIL_ADDR") or row.get("email") or "").strip()
            status = (row.get("status") or "").strip() or "Active"
            conn.execute(
                f"""INSERT OR REPLACE INTO {_WATER_TABLE}
                    (pwsid, pwsname, state, contactcity, contactstate, contactphone, contactemail, status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (pwsid, pwsname, state, contactcity, contactstate, contactphone, contactemail, status, now),
            )
            count += 1
        conn.commit()
        return count
    finally:
        if own and conn:
            conn.close()


def upsert_water_providers_merge(
    rows: List[dict],
    conn: sqlite3.Connection | None = None,
) -> tuple[int, int]:
    """
    Merge water provider rows into water_provider_cache (add new, update existing by pwsid).
    Does not delete existing rows that are not in the input. Each row dict must have keys:
    pwsid, pwsname, state, contactcity, contactstate, contactphone, status; contactemail optional.
    Returns (rows_inserted_or_updated, rows_skipped_invalid).
    """
    own = conn is None
    if conn is None:
        conn = get_connection()
    try:
        ensure_tables(conn)
        now = __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        count = 0
        skipped = 0
        for row in rows:
            pwsid = (row.get("pwsid") or "").strip()
            if not pwsid:
                skipped += 1
                continue
            pwsname = (row.get("pwsname") or "").strip() or ""
            state = (row.get("state") or "").strip()
            contactcity = (row.get("contactcity") or "").strip()
            contactstate = (row.get("contactstate") or "").strip()
            if not contactstate:
                contactstate = state
            contactphone = (row.get("contactphone") or "").strip()
            contactemail = (row.get("contactemail") or row.get("EMAIL_ADDR") or row.get("email") or "").strip()
            status = (row.get("status") or "").strip() or "Active"
            conn.execute(
                f"""INSERT OR REPLACE INTO {_WATER_TABLE}
                    (pwsid, pwsname, state, contactcity, contactstate, contactphone, contactemail, status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (pwsid, pwsname, state, contactcity, contactstate, contactphone, contactemail, status, now),
            )
            count += 1
        conn.commit()
        return (count, skipped)
    finally:
        if own and conn:
            conn.close()


def get_water_providers_from_db(
    state_abbreviation: str,
    city: str | None = None,
) -> List[dict]:
    """
    Look up water providers from cache by contactstate (and optionally contactcity).
    state_abbreviation should be 2-letter uppercase. Returns list of dicts with name, contact_phone, contact_city, contact_state, raw.
    """
    state = (state_abbreviation or "").strip().upper()
    if not state:
        return []
    try:
        conn = get_connection(read_only=True)
        try:
            _ensure_water_table_only(conn)
            if city and (city or "").strip():
                city_norm = " ".join((city or "").strip().upper().split())
                cur = conn.execute(
                    f"""SELECT pwsid, pwsname, contactcity, contactstate, contactphone, contactemail FROM {_WATER_TABLE}
                        WHERE UPPER(TRIM(contactstate)) = ? AND UPPER(TRIM(contactcity)) = ?
                        ORDER BY pwsname LIMIT 100""",
                    (state, city_norm),
                )
            else:
                cur = conn.execute(
                    f"""SELECT pwsid, pwsname, contactcity, contactstate, contactphone, contactemail FROM {_WATER_TABLE}
                        WHERE UPPER(TRIM(contactstate)) = ?
                        ORDER BY pwsname LIMIT 100""",
                    (state,),
                )
            out = []
            for row in cur.fetchall():
                r = dict(row)
                out.append({
                    "name": (r.get("pwsname") or "").strip() or "Water System",
                    "contact_phone": (r.get("contactphone") or "").strip() or None,
                    "contact_email": (r.get("contactemail") or "").strip() or None,
                    "contact_city": (r.get("contactcity") or "").strip(),
                    "contact_state": (r.get("contactstate") or "").strip(),
                    "raw": r,
                })
            return out
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Water cache lookup failed: %s", e)
        return []


# ---------- Internet BDC fallback (national top-N from CSV) ----------


def replace_internet_bdc_fallback(
    provider_rows: List[tuple[str, int]],
    as_of_date: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """
    Replace all rows in internet_bdc_fallback with the given list.
    provider_rows: list of (provider_name, total_units) sorted by total_units descending.
    Duplicate provider_name in input are deduped (first occurrence wins, i.e. highest total_units).
    as_of_date optional (e.g. data vintage). Returns number of rows written.
    """
    own = conn is None
    if conn is None:
        conn = get_connection()
    try:
        ensure_tables(conn)
        # Dedupe by provider_name (first occurrence wins = highest total_units when list is sorted desc)
        seen: set[str] = set()
        deduped: List[tuple[str, int]] = []
        for name, total_units in provider_rows:
            n = (name or "").strip()
            if not n or n in seen:
                continue
            seen.add(n)
            deduped.append((n, total_units))
        if len(deduped) < len(provider_rows):
            logger.info("Internet BDC fallback: deduped by provider_name from %d to %d", len(provider_rows), len(deduped))
        conn.execute(f"DELETE FROM {_BDC_FALLBACK_TABLE}")
        now = __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        count = 0
        for rank, (name, total_units) in enumerate(deduped, start=1):
            conn.execute(
                f"""INSERT OR REPLACE INTO {_BDC_FALLBACK_TABLE} (rank, provider_name, total_units, as_of_date, updated_at)
                VALUES (?, ?, ?, ?, ?)""",
                (rank, name, total_units, as_of_date or "", now),
            )
            count += 1
        conn.commit()
        return count
    finally:
        if own and conn:
            conn.close()


def get_internet_bdc_fallback_providers(limit: int = 10) -> List[dict]:
    """Return top N providers from internet_bdc_fallback table (for fallback when county cache misses)."""
    try:
        conn = get_connection(read_only=True)
        try:
            ensure_tables(conn)
            cur = conn.execute(
                f"SELECT rank, provider_name, total_units FROM {_BDC_FALLBACK_TABLE} ORDER BY rank LIMIT ?",
                (limit,),
            )
            return [{"name": row[1], "raw": {"holding_company": row[1], "total_units": row[2], "rank": row[0]}} for row in cur.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Internet BDC fallback lookup failed: %s", e)
        return []


# ---------- Pending providers (user-added, not in list; details fetched later) ----------


def add_pending_provider(
    provider_type: str,
    provider_name: str,
    property_id: int | None = None,
    state: str | None = None,
    county: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Insert a user-added provider (not in our list) for later verification. state/county from property (Smarty/Census)."""
    pt = (provider_type or "").strip().lower()
    pn = (provider_name or "").strip()
    if not pt or not pn:
        return
    state = (state or "").strip() or None
    county = (county or "").strip() or None
    own = conn is None
    if conn is None:
        conn = get_connection()
    try:
        ensure_tables(conn)
        conn.execute(
            f"""INSERT INTO {_PENDING_PROVIDERS_TABLE}
                (provider_type, provider_name, property_id, state, county, verification_status) VALUES (?, ?, ?, ?, ?, 'pending')""",
            (pt, pn, property_id, state, county),
        )
        conn.commit()
    finally:
        if own and conn:
            conn.close()


def get_pending_providers_for_property(property_id: int) -> List[dict]:
    """Return pending providers for a property (for UI: name, type, verification_status)."""
    try:
        conn = get_connection(read_only=True)
        try:
            ensure_tables(conn)
            cur = conn.execute(
                f"""SELECT id, provider_type, provider_name, state, county, verification_status, verified_at, created_at
                    FROM {_PENDING_PROVIDERS_TABLE} WHERE property_id = ? ORDER BY created_at DESC""",
                (property_id,),
            )
            return [
                {
                    "id": row[0],
                    "provider_type": row[1] or "",
                    "provider_name": row[2] or "",
                    "state": row[3],
                    "county": row[4],
                    "verification_status": row[5] or "pending",
                    "verified_at": row[6],
                    "created_at": row[7],
                }
                for row in cur.fetchall()
            ]
        finally:
            conn.close()
    except Exception as e:
        logger.warning("get_pending_providers_for_property failed: %s", e)
        return []


def get_pending_providers_to_verify(limit: int = 50) -> List[dict]:
    """Return pending providers that have verification_status = 'pending' for the verification job."""
    try:
        conn = get_connection(read_only=True)
        try:
            ensure_tables(conn)
            cur = conn.execute(
                f"""SELECT id, provider_type, provider_name, property_id, state, county
                    FROM {_PENDING_PROVIDERS_TABLE} WHERE verification_status = 'pending' ORDER BY created_at ASC LIMIT ?""",
                (limit,),
            )
            return [
                {
                    "id": row[0],
                    "provider_type": row[1] or "",
                    "provider_name": row[2] or "",
                    "property_id": row[3],
                    "state": row[4],
                    "county": row[5],
                }
                for row in cur.fetchall()
            ]
        finally:
            conn.close()
    except Exception as e:
        logger.warning("get_pending_providers_to_verify failed: %s", e)
        return []


def update_pending_provider_verification(
    pending_id: int,
    verification_status: str,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Set verification_status ('in_progress' | 'approved' | 'rejected') and verified_at for approved/rejected."""
    status = (verification_status or "").strip().lower()
    if status not in ("in_progress", "approved", "rejected"):
        return
    now = __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ") if status in ("approved", "rejected") else None
    own = conn is None
    if conn is None:
        conn = get_connection()
    try:
        ensure_tables(conn)
        if now:
            conn.execute(
                f"UPDATE {_PENDING_PROVIDERS_TABLE} SET verification_status = ?, verified_at = ? WHERE id = ?",
                (status, now, pending_id),
            )
        else:
            conn.execute(
                f"UPDATE {_PENDING_PROVIDERS_TABLE} SET verification_status = ? WHERE id = ?",
                (status, pending_id),
            )
        conn.commit()
    finally:
        if own and conn:
            conn.close()
