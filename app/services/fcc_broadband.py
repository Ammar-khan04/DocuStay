"""
Internet providers from FCC BDC fixed broadband provider summary (CSV).

Replaces the FCC Broadband Map API with the local BDC provider summary file, e.g.:
  bdc_us_fixed_broadband_provider_summary_J25_17feb2026.csv

CSV columns: provider_id, holding_company, technology_code, ... unit_count_res, unit_count_bus.
We aggregate by holding_company (sum of units), return top providers for the pipeline.
BDC releases twice per year (January + June); J25 = June 2025.
"""
from __future__ import annotations

import csv
import logging
import os
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

# In-memory cache: list of {name, raw} from last CSV load
_cached_providers: list[dict[str, Any]] | None = None
_cached_csv_path: str | None = None

# Default filename in project root or data/fcc/
_DEFAULT_CSV_NAME = "bdc_us_fixed_broadband_provider_summary_J25_17feb2026.csv"
# Number of top providers to return from the national BDC CSV (aggregated by holding_company)
_TOP_N = 10


def _find_fcc_csv_path() -> str | None:
    """Resolve path to FCC BDC provider summary CSV."""
    settings = get_settings()
    configured = (settings.fcc_broadband_csv_path or "").strip()
    if configured and os.path.isfile(configured):
        return os.path.abspath(configured)
    root = Path(__file__).resolve().parents[2]
    for base in (root, root / "data" / "fcc"):
        p = base / _DEFAULT_CSV_NAME
        if p.is_file():
            return str(p)
    return None


def _load_all_from_csv(csv_path: str) -> list[dict[str, Any]]:
    """Load BDC CSV, aggregate by holding_company, return all sorted by total units (for fallback)."""
    totals: dict[str, int] = {}
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("holding_company") or "").strip()
            if not name:
                continue
            try:
                res = int(row.get("unit_count_res") or 0)
                bus = int(row.get("unit_count_bus") or 0)
            except (TypeError, ValueError):
                res = bus = 0
            totals[name] = totals.get(name, 0) + res + bus
    ordered = sorted(totals.items(), key=lambda x: -x[1])
    return [{"name": name, "raw": {"holding_company": name, "total_units": total}} for name, total in ordered]


def fetch_fcc_providers(
    lat: float,
    lon: float,
    zip_code: str | None = None,
    state_abbreviation: str | None = None,
    state_fips: str | None = None,
    county_fips: str | None = None,
) -> list[dict[str, Any]]:
    """
    Return internet providers: try SQLite county cache first (if state_fips + county_fips given);
    on miss fall back to national BDC CSV (top _TOP_N). Do not call FCC API during request.
    Optionally enqueue (state_fips, county_fips) for next background refresh on cache miss.
    """
    # Try county-level cache first when we have state + county FIPS (e.g. from Census Geocoder)
    if state_fips and county_fips:
        state_fips = state_fips.strip()
        county_fips = county_fips.strip()
        if len(state_fips) == 2 and len(county_fips) == 3:
            try:
                from app.utility_providers.sqlite_cache import (
                    get_internet_providers_for_county,
                    enqueue_county_for_refresh,
                )
                cached = get_internet_providers_for_county(state_fips, county_fips)
                if cached:
                    out = [{"name": n, "raw": {"brand_name": n, "source": "fcc_county_cache"}} for n in cached]
                    print(f"[FCC] County cache hit ({state_fips}/{county_fips}): {len(out)} provider(s)")
                    return out
                # Miss: enqueue for next background job; show BDC fallback so user has options
                enqueue_county_for_refresh(state_fips, county_fips)
                from app.utility_providers.sqlite_cache import get_internet_bdc_fallback_providers
                fallback = get_internet_bdc_fallback_providers(limit=15)
                if fallback:
                    print(f"[FCC] County cache miss ({state_fips}/{county_fips}); using BDC fallback: {len(fallback)} provider(s)")
                return fallback
            except Exception as e:
                logger.warning("FCC county cache lookup failed: %s", e)
                return []
    # No state/county FIPS: try BDC fallback so user still sees options
    try:
        from app.utility_providers.sqlite_cache import get_internet_bdc_fallback_providers
        return get_internet_bdc_fallback_providers(limit=15)
    except Exception:
        return []


def get_internet_provider_names(
    lat: float,
    lon: float,
    zip_code: str | None = None,
    state_abbreviation: str | None = None,
    state_fips: str | None = None,
    county_fips: str | None = None,
) -> list[str]:
    """Return list of internet provider names; uses county cache when state_fips/county_fips provided."""
    providers = fetch_fcc_providers(
        lat, lon,
        zip_code=zip_code,
        state_abbreviation=state_abbreviation,
        state_fips=state_fips,
        county_fips=county_fips,
    )
    return [(p.get("name") or "").strip() for p in providers if (p.get("name") or "").strip()]
