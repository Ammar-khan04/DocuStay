"""
U.S. Census Bureau Geocoder API: convert latitude/longitude to county and state.

No API key required. Used by the Utility Bucket to get state + county for water lookups.

API: https://geocoding.geo.census.gov/geocoder/geographies/coordinates
Params: x=longitude, y=latitude, benchmark=Public_AR_Current, vintage=Current_Current, format=json
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

_CENSUS_COORDINATES_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"

logger = logging.getLogger(__name__)


@dataclass
class CensusGeography:
    """State and county from Census geocoder."""
    state_fips: str  # e.g. "06"
    state_abbreviation: str  # e.g. "CA"
    county_name: str  # e.g. "Santa Clara County"
    county_fips: str | None  # e.g. "085"


def lat_lng_to_geography(lat: float, lon: float) -> CensusGeography | None:
    """
    Call Census Geocoder API to get state and county for a point.
    x = longitude, y = latitude (Census uses x/y).
    """
    params = {
        "x": lon,
        "y": lat,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }
    print(f"[CensusGeocoder] Calling Census API: {_CENSUS_COORDINATES_URL} with x={lon}, y={lat}")
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(_CENSUS_COORDINATES_URL, params=params)
            r.raise_for_status()
            data: dict[str, Any] = r.json()
    except Exception as e:
        print(f"[CensusGeocoder] API call failed: {e}")
        logger.warning("Census geocoder request failed: %s", e)
        return None

    result = data.get("result") or {}
    geographies = result.get("geographies") or {}
    print(f"[CensusGeocoder] Response keys: {list(geographies.keys())}")

    states = geographies.get("States") or []
    counties = geographies.get("Counties") or []

    state_fips = ""
    state_abbreviation = ""
    if states and isinstance(states, list) and len(states) > 0:
        s = states[0]
        if isinstance(s, dict):
            state_fips = (s.get("STATE") or s.get("GEOID") or "").strip()
            state_abbreviation = (s.get("STUSAB") or "").strip().upper()
            print(f"[CensusGeocoder] State: FIPS={state_fips}, STUSAB={state_abbreviation}")
    if not state_abbreviation and state_fips:
        # Fallback: map FIPS to abbrev for common states if API didn't return STUSAB
        _FIPS_TO_ABBREV = {
            "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT",
            "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL",
            "18": "IN", "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME", "24": "MD",
            "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT", "31": "NE",
            "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
            "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
            "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA", "54": "WV",
            "55": "WI", "56": "WY",
        }
        state_abbreviation = _FIPS_TO_ABBREV.get(state_fips, "")

    county_name = ""
    county_fips = None
    if counties and isinstance(counties, list) and len(counties) > 0:
        c = counties[0]
        if isinstance(c, dict):
            county_name = (c.get("NAME") or c.get("BASENAME") or "").strip()
            county_fips = (c.get("COUNTY") or c.get("GEOID") or "").strip() or None
            print(f"[CensusGeocoder] County: NAME={county_name}, COUNTY={county_fips}")
    if not county_name and not state_abbreviation:
        print("[CensusGeocoder] No state or county in response; returning None")
        return None

    return CensusGeography(
        state_fips=state_fips,
        state_abbreviation=state_abbreviation,
        county_name=county_name,
        county_fips=county_fips,
    )


def geocode_coordinates(lon: float, lat: float) -> CensusGeography | None:
    """Alias: get geography (state, county) for a point. Args: longitude, latitude (same order as owners use)."""
    return lat_lng_to_geography(lat, lon)
