"""Browser local calendar day vs UTC for date-only API validation."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import Request


def parse_client_calendar_date_header(raw: str | None) -> date | None:
    """Parse ``X-Client-Calendar-Date: YYYY-MM-DD`` from the browser (local calendar, no clock time)."""
    if not raw or not str(raw).strip():
        return None
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None


def effective_today_for_invite_start(
    request: Request,
    *,
    client_calendar_date: str | None = None,
) -> date:
    """
    Calendar "today" for rules like invite start cannot be in the past.

    Prefer ``client_calendar_date`` from the JSON body (same YYYY-MM-DD as local ``<input type=\"date\">``),
    then ``X-Client-Calendar-Date`` — body survives reverse proxies that drop unknown headers.
    Clamp the chosen value to UTC calendar date ±1 day so obviously spoofed values cannot backdate
    invites by years.

    When both are absent or invalid (e.g. non-browser API clients), fall back to UTC calendar date.
    """
    utc_today = datetime.now(timezone.utc).date()
    raw = (client_calendar_date or "").strip() or (request.headers.get("X-Client-Calendar-Date") or "").strip()
    parsed = parse_client_calendar_date_header(raw if raw else None)
    if parsed is None:
        return utc_today
    lo, hi = utc_today - timedelta(days=1), utc_today + timedelta(days=1)
    if parsed < lo:
        return lo
    if parsed > hi:
        return hi
    return parsed
