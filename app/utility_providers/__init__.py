"""
Utility provider cache and background jobs.

- SQLite cache: one DB, per-utility tables (internet_provider_cache, water_provider_cache, internet_bdc_fallback).
- Background jobs: water_csv_job (SDWIS CSV), sdwa_water_job (EPA SDWA bulk merge), internet_bdc_csv_job (BDC CSV), fcc_internet_job (FCC API).
- Lookup: (state_fips, county_fips) -> internet; state/city -> water; county miss -> BDC fallback.
"""

from app.utility_providers.sqlite_cache import (
    ensure_tables,
    get_internet_providers_for_county,
    get_internet_bdc_fallback_providers,
    get_water_providers_from_db,
    upsert_county_providers,
    upsert_water_providers_bulk,
    upsert_water_providers_merge,
    replace_internet_bdc_fallback,
)

__all__ = [
    "ensure_tables",
    "get_internet_providers_for_county",
    "get_internet_bdc_fallback_providers",
    "get_water_providers_from_db",
    "upsert_county_providers",
    "upsert_water_providers_bulk",
    "upsert_water_providers_merge",
    "replace_internet_bdc_fallback",
]
