"""
Background job: verify user-added (pending) providers via SerpApi.

For each pending provider (name, state, county from property), we search SerpApi.
If we find organic results that match the provider name and look like an official/utility
source, we mark the provider as approved; otherwise rejected. Status in_progress while running.
"""

import re
from typing import Any

import httpx

from app.utility_providers.sqlite_cache import (
    get_pending_providers_to_verify,
    update_pending_provider_verification,
)

# Domains we treat as non-official (social, aggregators) for verification
_SKIP_DOMAINS = re.compile(
    r"facebook\.com|twitter\.com|linkedin\.com|youtube\.com|instagram\.com|"
    r"yelp\.com|yellowpages\.com|bbb\.org|wikipedia\.org|reddit\.com",
    re.I,
)


def _serpapi_search_provider(provider_name: str, state: str | None, county: str | None, api_key: str) -> dict[str, Any] | None:
    """Call SerpApi for provider + state/county + 'utility'. Returns raw JSON or None on failure."""
    name = (provider_name or "").strip()
    if not name or not api_key:
        return None
    state = (state or "").strip().upper()
    county = (county or "").strip()
    query = f'"{name}"'
    if state:
        query += f" {state}"
    if county:
        query += f" {county}"
    query += " utility"
    url = "https://serpapi.com/search.json"
    params = {"engine": "google", "q": query, "api_key": api_key, "num": 10}
    try:
        with httpx.Client(timeout=15) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        print(f"[PendingProviderVerify] SerpApi request failed: {e}")
        return None


def _normalize_for_match(text: str) -> str:
    """Lowercase, collapse spaces, remove common punctuation for fuzzy match."""
    if not text:
        return ""
    t = re.sub(r"[&.,\-']", " ", text.lower())
    t = " ".join(t.split())
    return t


def _name_matches_result(provider_name: str, title: str, snippet: str, link: str) -> bool:
    """True if provider name appears in title or snippet (fuzzy) and domain is not skipped."""
    if _SKIP_DOMAINS.search(link or ""):
        return False
    norm_name = _normalize_for_match(provider_name)
    if not norm_name:
        return False
    # Require at least first two words or a significant substring to reduce false positives
    words = norm_name.split()
    combined = _normalize_for_match((title or "") + " " + (snippet or ""))
    if not combined:
        return False
    # Strong match: full name in text, or first word + one other word
    if norm_name in combined:
        return True
    if len(words) >= 2 and words[0] in combined and words[-1] in combined:
        return True
    if len(words) == 1 and len(words[0]) >= 4 and words[0] in combined:
        return True
    return False


def verify_provider_with_serpapi(
    provider_name: str,
    state: str | None,
    county: str | None,
    api_key: str,
) -> bool:
    """
    Return True if SerpApi results suggest this is a valid utility/provider (approved), else False (rejected).
    Logic: at least one organic result has provider name in title/snippet and link is not social/aggregator.
    """
    data = _serpapi_search_provider(provider_name, state, county, api_key)
    if not data:
        return False
    results = data.get("organic_results") or []
    for item in results:
        title = (item.get("title") or "").strip()
        snippet = (item.get("snippet") or "").strip()
        link = (item.get("link") or "").strip()
        if _name_matches_result(provider_name, title, snippet, link):
            return True
    return False


def run_pending_provider_verification_job() -> None:
    """
    Load pending providers (verification_status = 'pending'), call SerpApi for each,
    set verification_status to in_progress then approved or rejected. Uses SERPAPI_KEY.
    """
    from app.config import get_settings

    print("[PendingProviderVerify] BACKGROUND JOB START: pending_provider_verification")
    api_key = (get_settings().serpapi_key or "").strip()
    if not api_key:
        print("[PendingProviderVerify] BACKGROUND JOB COMPLETE: pending_provider_verification skipped (SERPAPI_KEY not set)")
        return
    rows = get_pending_providers_to_verify(limit=50)
    if not rows:
        print("[PendingProviderVerify] BACKGROUND JOB COMPLETE: pending_provider_verification processed=0 (no pending providers)")
        return
    print(f"[PendingProviderVerify] Found {len(rows)} pending provider(s) to verify")
    approved_count = 0
    rejected_count = 0
    try:
        for row in rows:
            pid = row.get("id")
            name = row.get("provider_name") or ""
            state = row.get("state")
            county = row.get("county")
            if not name or not pid:
                continue
            print(f"[PendingProviderVerify] Verifying id={pid} name={name!r} state={state!r} county={county!r}")
            update_pending_provider_verification(pid, "in_progress")
            try:
                approved = verify_provider_with_serpapi(name, state, county, api_key)
                update_pending_provider_verification(pid, "approved" if approved else "rejected")
                if approved:
                    approved_count += 1
                else:
                    rejected_count += 1
                print(f"[PendingProviderVerify] id={pid} -> {'approved' if approved else 'rejected'}")
            except Exception as e:
                rejected_count += 1
                print(f"[PendingProviderVerify] id={pid} error: {e}; marking rejected")
                update_pending_provider_verification(pid, "rejected")
        print(f"[PendingProviderVerify] BACKGROUND JOB COMPLETE: pending_provider_verification processed={len(rows)} approved={approved_count} rejected={rejected_count}")
    except Exception as e:
        print(f"[PendingProviderVerify] BACKGROUND JOB COMPLETE: pending_provider_verification error={e!r}")
        raise
