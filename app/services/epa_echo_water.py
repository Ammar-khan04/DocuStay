"""
Water utility lookup via EPA ECHO Safe Drinking Water REST API.

No API key required. Uses get_systems (state/county/city) -> QueryID, then get_qid
to fetch water system rows. Returns same shape as water_lookup CSV path for drop-in use.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_ECHO_BASE = "https://echodata.epa.gov/echo"
_TIMEOUT = 45.0  # ECHO server can be slow; CSV fallback used on timeout
_MAX_PAGES = 3  # cap pages per lookup to avoid huge responses


def _get_systems(state: str, county: str | None = None, city: str | None = None) -> dict | None:
    """Call get_systems; returns JSON with QueryID and QueryRows."""
    params: dict[str, str] = {"p_st": state.strip().upper()[:2], "output": "JSON"}
    if county and str(county).strip():
        params["p_cty"] = str(county).strip()
    if city and str(city).strip():
        params["p_city"] = str(city).strip()
    url = f"{_ECHO_BASE}/sdw_rest_services.get_systems"
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            r = client.get(url, params=params)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("EPA ECHO get_systems failed: %s", e)
        return None


def _get_qid(qid: str, pageno: int = 1) -> dict | None:
    """Fetch one page of water system results by QID."""
    url = f"{_ECHO_BASE}/sdw_rest_services.get_qid"
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            r = client.get(url, params={"qid": qid, "pageno": pageno, "output": "JSON"})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("EPA ECHO get_qid failed (qid=%s, pageno=%s): %s", qid, pageno, e)
        return None


def lookup_water_providers_echo(
    state_abbreviation: str,
    county_name: str | None = None,
    city: str | None = None,
) -> list[dict[str, Any]]:
    """
    Look up water systems via EPA ECHO API by state and optionally county/city.
    Returns list of dicts with: name, contact_phone, contact_city, contact_state, raw.
    ECHO does not provide phone in the API; contact_phone will be None.
    """
    data = _get_systems(state_abbreviation, county=county_name, city=city)
    if not data:
        return []
    res = data.get("Results") or {}
    qid = res.get("QueryID")
    if not qid:
        return []
    try:
        query_rows = int(res.get("QueryRows") or 0)
    except (TypeError, ValueError):
        query_rows = 0
    if query_rows == 0:
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pageno in range(1, _MAX_PAGES + 1):
        page = _get_qid(str(qid), pageno=pageno)
        if not page:
            break
        results = page.get("Results") or page
        if not isinstance(results, dict):
            break
        systems = results.get("WaterSystems")
        if not isinstance(systems, list):
            break
        for row in systems:
            if not isinstance(row, dict):
                continue
            name = (row.get("PWSName") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            cities_served = (row.get("CitiesServed") or "").strip()
            state_code = (row.get("StateCode") or "").strip()
            out.append({
                "name": name or "Water System",
                "contact_phone": None,  # ECHO API does not expose phone in this endpoint
                "contact_city": cities_served[:200] if cities_served else "",
                "contact_state": state_code,
                "raw": row,
            })
        if len(systems) < 5000:  # last page
            break
    return out
