"""Utility Bucket: lookup utility providers for property registration.

Pipeline (see docs/UTILITY_BUCKET.md and docs/UTILITY_PROVIDERS_FLOW.md):
  1. Census Geocoder (lat/lng → county, state) for water/internet context
  2. Electric/gas: Rewiring America API (ZIP)
  3. Water: EPA ECHO API (primary), EPA SDWIS CSV fallback (state/county/city)
  4. Internet: FCC BDC provider summary CSV

All providers come from APIs or regularly updated datasets; no hardcoded provider lists.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from sqlalchemy.orm import Session

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class UtilityProvider:
    name: str
    provider_type: str  # electric, gas, water, internet
    utilityapi_id: str | None
    phone: str | None
    email: str | None  # contact email when available (e.g. from water lookup/cache)
    raw: dict[str, Any]


def _territory_paragraph_from_sot(db: Session, zip_code: str | None, region_code: str | None) -> str | None:
    """Build territory paragraph from JurisdictionInfo (SOT). Returns None if no jurisdiction found."""
    from app.services.jurisdiction_sot import get_jurisdiction_for_property
    jinfo = get_jurisdiction_for_property(db, zip_code, region_code)
    if not jinfo:
        return None
    name = (jinfo.name or jinfo.region_code or "this jurisdiction").strip()
    citations = ", ".join(s.citation for s in (jinfo.statutes or [])) if jinfo.statutes else "applicable law"
    return (
        f"This authorization is issued for the territory of {name}. "
        f"DocuStay operates in accordance with applicable short-term stay and utility authorization requirements "
        f"({citations})."
    )


def _territory_paragraph(region_code: str | None) -> str:
    """Return territory-specific paragraph for the authority letter (fallback when SOT not used)."""
    if not region_code or not (region_code := region_code.strip().upper()):
        return "This authorization is issued for the property's jurisdiction."
    _territory_text: dict[str, str] = {
        "NY": "This authorization is issued for the territory of New York. DocuStay operates in accordance with applicable New York short-term stay and utility authorization requirements.",
        "FL": "This authorization is issued for the territory of Florida. DocuStay operates in accordance with applicable Florida short-term stay and utility authorization requirements.",
        "CA": "This authorization is issued for the territory of California. DocuStay operates in accordance with applicable California short-term stay and utility authorization requirements.",
        "TX": "This authorization is issued for the territory of Texas. DocuStay operates in accordance with applicable Texas short-term stay and utility authorization requirements.",
        "WA": "This authorization is issued for the territory of Washington. DocuStay operates in accordance with applicable Washington short-term stay and utility authorization requirements.",
    }
    return _territory_text.get(region_code, f"This authorization is issued for the territory of {region_code}. DocuStay is the authorized agent for utility activation at the property listed below.")


def _authority_letter_content(
    provider: UtilityProvider,
    address: str,
    property_name: str,
    region_code: str | None = None,
    db: Session | None = None,
    zip_code: str | None = None,
) -> str:
    """Generate Authority Letter content for a utility provider. When db (and optionally zip_code) are provided, territory paragraph is built from JurisdictionInfo SOT."""
    if db is not None:
        territory_para = _territory_paragraph_from_sot(db, zip_code, region_code) or _territory_paragraph(region_code)
    else:
        territory_para = _territory_paragraph(region_code)
    return f"""DocuStay Authority Letter – Burn-In Code Authorization

To: {provider.name}
Re: Property at {address}
{f"Property Name: {property_name}" if property_name else ""}

This letter serves as official notice that DocuStay is the ONLY authorized agent to issue "Burn-In" codes (utility activation tokens) for the above address.

No other party—including tenants, guests, or squatters—may activate or modify utility services for this property without authorization through DocuStay.

Property address: {address}

{territory_para}

For verification, please contact DocuStay.
"""


# --- Rewiring America API (electric + gas by zip or address) ---

_REWIRING_AMERICA_BASE = "https://api.rewiringamerica.org"


def _fetch_rewiring_america(zip5: str, address: str | None) -> list[dict[str, Any]]:
    """Fetch electric and gas utilities from Rewiring America. Returns list of {name, type, raw} dicts."""
    settings = get_settings()
    api_key = (settings.rewiring_america_api_key or "").strip()
    if not api_key:
        print("[UtilityLookup] Rewiring America: API key not set; skipping")
        return []

    # API often returns 400 when address is included; use zip-only.
    params: dict[str, str] = {"zip": zip5}
    print(f"[UtilityLookup] Calling Rewiring America API: zip={zip5}")
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(
                f"{_REWIRING_AMERICA_BASE}/api/v1/utilities",
                params=params,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            r.raise_for_status()
            data = r.json()
        print(f"[UtilityLookup] Rewiring America response: keys={list(data.keys()) if isinstance(data, dict) else 'n/a'}")
    except Exception as e:
        print(f"[UtilityLookup] Rewiring America request failed: {e}")
        logger.warning("Rewiring America utilities request failed: %s", e)
        return []

    out: list[dict[str, Any]] = []
    # utilities: electric; gas_utilities: gas. Handle list or dict of items.
    for key, ptype in (("utilities", "electric"), ("gas_utilities", "gas")):
        raw_list = data.get(key)
        if not raw_list:
            continue
        if isinstance(raw_list, list):
            items = raw_list
        elif isinstance(raw_list, dict):
            items = list(raw_list.values()) if raw_list else []
        else:
            continue
        for item in items:
            if isinstance(item, dict):
                name = item.get("name") or item.get("utility_name") or item.get("label")
            elif isinstance(item, str):
                name = item
            else:
                continue
            if name and isinstance(name, str) and name.strip():
                out.append({"name": name.strip(), "type": ptype, "raw": item if isinstance(item, dict) else {"name": name}})
            continue

    return out


def _raw_to_providers(raw_list: list[dict[str, Any]]) -> list[UtilityProvider]:
    """Convert API raw entries to UtilityProvider list (no duplicates by name+type)."""
    seen: set[tuple[str, str]] = set()
    result: list[UtilityProvider] = []
    for p in raw_list:
        name = (p.get("name") or "").strip()
        ptype = (p.get("type") or "electric").strip().lower() or "electric"
        if not name or (name, ptype) in seen:
            continue
        seen.add((name, ptype))
        result.append(
            UtilityProvider(
                name=name,
                provider_type=ptype,
                utilityapi_id=p.get("utilityapi_id"),
                phone=p.get("phone"),
                email=(p.get("email") or p.get("contact_email")) or None,
                raw=p.get("raw") if isinstance(p.get("raw"), dict) else p,
            )
        )
    return result


def lookup_utility_providers(
    zip_code: str | None,
    lat: float | None = None,
    lon: float | None = None,
    address: str | None = None,
    city: str | None = None,
    state_abbreviation: str | None = None,
    water_csv_path: Path | str | None = None,
) -> list[UtilityProvider]:
    """
    Build Utility Bucket for a location: electric, gas, water, internet.

    All data from APIs or regularly updated datasets: Census (lat/lng → county, state),
    Rewiring America (electric/gas by ZIP), EPA SDWIS CSV (water), FCC BDC CSV (internet).
    """
    zip5 = None
    if zip_code and str(zip_code).strip():
        zip5 = str(zip_code).strip().split("-")[0][:5]
    print(f"[UtilityLookup] Starting lookup: zip={zip5}, lat={lat}, lon={lon}, address={address or '(none)'}")

    # Step 1: Census geocoder (lat/lng → county, state) for water/internet context
    county_name: str | None = None
    state_abbrev: str | None = state_abbreviation
    state_fips: str | None = None
    county_fips: str | None = None
    if lat is not None and lon is not None:
        try:
            from app.services.census_geocoder import lat_lng_to_geography
            geo = lat_lng_to_geography(lat, lon)
            if geo:
                county_name = geo.county_name or None
                if geo.state_abbreviation:
                    state_abbrev = geo.state_abbreviation
                state_fips = (geo.state_fips or "").strip() or None
                county_fips = (geo.county_fips or "").strip() or None
                print(f"[UtilityLookup] Census result: state={state_abbrev}, county={county_name}, state_fips={state_fips}, county_fips={county_fips}")
        except Exception as e:
            print(f"[UtilityLookup] Census geocoder failed: {e}")

    if not zip5:
        print("[UtilityLookup] No ZIP code; electric/gas may be missing; water needs state")

    raw_list: list[dict[str, Any]] = []

    # Step 2: Electric + gas — Rewiring America (by ZIP)
    if zip5:
        ra = _fetch_rewiring_america(zip5, address)
        if ra:
            raw_list.extend(ra)
            print(f"[UtilityLookup] Rewiring America returned {len(ra)} electric/gas entries")

    # Step 3: Water — EPA SDWIS CSV (state/county/city)
    if state_abbrev:
        try:
            from app.services.water_lookup import lookup_water_providers
            water_providers = lookup_water_providers(
                state_abbrev,
                city=city,
                county_name=county_name,
                csv_path=water_csv_path,
            )
            for w in water_providers:
                raw_list.append({
                    "name": w.get("name") or "Water System",
                    "type": "water",
                    "utilityapi_id": None,
                    "phone": w.get("contact_phone"),
                    "email": w.get("contact_email"),
                    "raw": w.get("raw") or w,
                })
            if water_providers:
                print(f"[UtilityLookup] Water CSV lookup returned {len(water_providers)} provider(s)")
        except Exception as e:
            print(f"[UtilityLookup] Water lookup failed: {e}")

    # Step 4: Internet — county cache (state_fips/county_fips) or fallback to FCC BDC CSV
    try:
        from app.services.fcc_broadband import fetch_fcc_providers
        fcc_providers = fetch_fcc_providers(
            lat or 0.0, lon or 0.0,
            zip_code=zip5,
            state_abbreviation=state_abbrev,
            state_fips=state_fips,
            county_fips=county_fips,
        )
        for f in fcc_providers:
            name = (f.get("name") or "").strip()
            if name:
                raw_list.append({
                    "name": name,
                    "type": "internet",
                    "utilityapi_id": None,
                    "phone": None,
                    "raw": f.get("raw") or f,
                })
        if fcc_providers:
            print(f"[UtilityLookup] Internet providers: {len(fcc_providers)} (cache or CSV)")
    except Exception as e:
        print(f"[UtilityLookup] FCC CSV lookup failed: {e}")

    result = _raw_to_providers(raw_list)
    print(f"[UtilityLookup] Final bucket: {len(result)} provider(s). Types: {[p.provider_type for p in result]}")
    logger.info("[UtilityLookup] ZIP=%s lat=%s lon=%s -> %s provider(s)", zip5, lat, lon, len(result))
    return result


def _provider_to_raw(p: UtilityProvider) -> str | None:
    """JSON-serialize raw provider dict for storage."""
    d = dict(p.raw) if p.raw else {}
    return json.dumps(d) if d else None


def generate_authority_letters(
    providers: list[UtilityProvider],
    address: str,
    property_name: str | None = None,
    region_code: str | None = None,
    db: Session | None = None,
    zip_code: str | None = None,
) -> list[tuple[UtilityProvider, str]]:
    """Generate Authority Letter content for each provider. When db is provided, territory text uses JurisdictionInfo SOT (zip_code optional). Returns [(provider, letter_content), ...]"""
    return [
        (p, _authority_letter_content(p, address, property_name or "", region_code, db=db, zip_code=zip_code))
        for p in providers
    ]
