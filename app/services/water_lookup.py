"""
Water utility lookup from EPA Safe Drinking Water data.

Primary: EPA ECHO REST API (no API key). Fallback: local SDWIS CSV (e.g. CSV.csv) with
columns pwsid, pwsname, state, contactcity, contactstate, contactphone, status, etc.
Lookup by state abbreviation and optionally city/county.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default path: project root / CSV.csv (SDWIS export)
_DEFAULT_CSV_PATH = Path(__file__).resolve().parent.parent.parent / "CSV.csv"
_water_systems: list[dict[str, Any]] | None = None


def _normalize(s: str | None) -> str:
    if not s or not isinstance(s, str):
        return ""
    return " ".join(s.strip().upper().split())


def load_water_systems_csv(csv_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Load water systems from CSV; cache in module. Returns list of row dicts."""
    global _water_systems
    path = Path(csv_path) if csv_path else _DEFAULT_CSV_PATH
    if not path.exists():
        print(f"[WaterLookup] CSV not found: {path}; water lookup will return empty")
        logger.warning("Water systems CSV not found: %s", path)
        return []
    if _water_systems is not None:
        return _water_systems
    rows: list[dict[str, Any]] = []
    try:
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row:
                    continue
                status = (row.get("status") or "").strip().upper()
                if status == "CLOSED":
                    continue
                rows.append(row)
        _water_systems = rows
        print(f"[WaterLookup] Loaded {len(rows)} active water systems from {path}")
        logger.info("Loaded %s water systems from %s", len(rows), path)
    except Exception as e:
        print(f"[WaterLookup] Failed to load CSV {path}: {e}")
        logger.exception("Failed to load water systems CSV: %s", path)
        return []
    return _water_systems


def lookup_water_providers(
    state_abbreviation: str,
    city: str | None = None,
    county_name: str | None = None,
    csv_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """
    Look up water systems by state and optionally city or county.
    Tries SQLite cache first (if populated by water_csv_job); then EPA ECHO API; then local CSV.
    Returns list of dicts with at least: name, contact_phone, contact_city, contact_state.
    """
    # Prefer SQLite cache when populated (no external call)
    try:
        from app.utility_providers.sqlite_cache import get_water_providers_from_db
        db_list = get_water_providers_from_db(state_abbreviation, city=city)
        if db_list:
            logger.info("Water from SQLite cache: %s provider(s)", len(db_list))
            return db_list
    except Exception as e:
        logger.warning("Water SQLite lookup failed, trying ECHO/CSV: %s", e)

    # Then EPA ECHO API (no key required)
    try:
        from app.services.epa_echo_water import lookup_water_providers_echo
        echo_list = lookup_water_providers_echo(
            state_abbreviation,
            county_name=county_name,
            city=city,
        )
        if echo_list:
            logger.info("Water from EPA ECHO: %s provider(s)", len(echo_list))
            return echo_list
    except Exception as e:
        logger.warning("EPA ECHO water lookup failed, falling back to CSV: %s", e)

    systems = load_water_systems_csv(csv_path)
    if not systems:
        print("[WaterLookup] No water systems loaded; returning []")
        return []

    state_norm = _normalize(state_abbreviation)
    city_norm = _normalize(city) if city else ""
    county_norm = _normalize(county_name) if county_name else ""

    matches: list[dict[str, Any]] = []
    for row in systems:
        contactstate = _normalize(row.get("contactstate") or "")
        if not contactstate:
            # CSV state column is sometimes FIPS (01, 02); we match by contactstate when available
            continue
        if contactstate != state_norm:
            continue
        # Prefer city match if we have city
        if city_norm:
            contactcity = _normalize(row.get("contactcity") or "")
            if contactcity and contactcity != city_norm:
                # Optional: still include if county matches
                if not county_norm:
                    continue
                # CSV may not have county; try name containing city
                pwsname = _normalize(row.get("pwsname") or "")
                if city_norm not in pwsname and city_norm not in contactcity:
                    continue
        matches.append({
            "name": (row.get("pwsname") or "").strip() or "Water System",
            "contact_phone": (row.get("contactphone") or "").strip() or None,
            "contact_email": (row.get("contactemail") or row.get("email") or "").strip() or None,
            "contact_city": (row.get("contactcity") or "").strip(),
            "contact_state": (row.get("contactstate") or "").strip(),
            "raw": row,
        })

    # Dedupe by name
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for m in matches:
        n = (m.get("name") or "").strip()
        if n and n not in seen:
            seen.add(n)
            unique.append(m)

    print(f"[WaterLookup] Lookup state={state_abbreviation}, city={city or '(any)'} -> {len(unique)} provider(s). Sample: {[u.get('name') for u in unique[:3]]}")
    return unique


def get_water_provider_contact(
    provider_name: str,
    state_abbreviation: str,
    city: str | None = None,
) -> dict[str, str | None]:
    """
    Look up contact email and phone for a single water provider by name and state (and optionally city).
    Used when saving a property's utility provider so we can store contact_email/contact_phone.
    Returns {"contact_email": str | None, "contact_phone": str | None}. Tries DB/cache first, then full lookup.
    """
    name_clean = (provider_name or "").strip()
    state_clean = (state_abbreviation or "").strip().upper()
    print(f"[PropertyFlow] get_water_provider_contact: name={name_clean!r}, state={state_clean!r}, city={city!r}")
    if not name_clean or not state_clean:
        print(f"[PropertyFlow] get_water_provider_contact: missing name or state -> returning null")
        return {"contact_email": None, "contact_phone": None}
    try:
        from app.utility_providers.sqlite_cache import get_water_providers_from_db
        candidates = get_water_providers_from_db(state_clean, city=city)
        source = "DB/cache"
    except Exception as e:
        candidates = []
        source = f"DB/cache error: {e}"
    if not candidates:
        # Fallback: full lookup (may hit ECHO or CSV) and match by name
        candidates = lookup_water_providers(state_clean, city=city)
        source = "full lookup (ECHO/CSV)"
    print(f"[PropertyFlow] get_water_provider_contact: source={source}, candidates={len(candidates)}")
    name_norm = _normalize(name_clean)
    for w in candidates:
        n = (w.get("name") or "").strip()
        if _normalize(n) == name_norm or (name_norm in _normalize(n)) or (_normalize(n) in name_norm):
            out = {
                "contact_email": (w.get("contact_email") or "").strip() or None,
                "contact_phone": (w.get("contact_phone") or "").strip() or None,
            }
            print(f"[PropertyFlow] get_water_provider_contact: match -> email={out['contact_email']!r}, phone={out['contact_phone']!r}")
            return out
    print(f"[PropertyFlow] get_water_provider_contact: no match -> returning null")
    return {"contact_email": None, "contact_phone": None}


def reset_water_cache() -> None:
    """Clear cached CSV so next lookup reloads from disk (e.g. after CSV update)."""
    global _water_systems
    _water_systems = None
