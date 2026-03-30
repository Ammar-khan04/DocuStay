"""
Provider contact email lookup via SerpApi (Google search).

Flow: call SerpApi → process results → final result is emails (if found).
1. Extract emails from snippets (related_questions + organic_results).
2. If none found, fetch top organic result URLs and extract emails from page HTML.
Excludes or deprioritizes billing/payments emails so only general contact emails are returned.
"""

import re
from typing import Any

import httpx

# Max organic results to fetch when snippets have no emails
PAGE_FETCH_MAX_URLS = 4
PAGE_FETCH_MAX_CHARS = 200_000

# Email regex
EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)

# Exclude these (non-contact / noise)
SKIP_EMAIL_PATTERNS = re.compile(
    r"noreply|no-reply|donotreply|do-not-reply|"
    r"example\.com|@.*\.(png|jpg|jpeg|gif|svg|woff2?)(\s|$)|"
    r"@2x\.|wixpress|schema\.org|sentry\.io|"
    r"gravatar|facebook\.com|twitter\.com|linkedin\.com|youtube\.com|"
    r"w3\.org|googleapis|gstatic|google\.com|microsoft\.com|"
    r"placeholder|test@|user@|admin@(?!.*\.(gov|org))",
    re.I
)

# Prefer these local-parts (contact-style)
PREFER_LOCAL = re.compile(
    r"^(contact|info|customerservice|customercare|support|"
    r"customer\.service|utility|authority|consumer|energydatarequest)",
    re.I
)

# Deprioritize billing/payments (we want contact, not billing)
BILLING_LOCAL = re.compile(
    r"^(billing|payments|pay|bill|careandfera|pgesocialmedia)$",
    re.I
)


def _score_email(email: str) -> int:
    """Higher = better for contact. Billing-style gets negative score."""
    local = email.split("@")[0] if "@" in email else ""
    score = 0
    if PREFER_LOCAL.match(local):
        score += 10
    if email.endswith(".gov") or email.endswith(".org"):
        score += 5
    if BILLING_LOCAL.match(local):
        score -= 15  # strongly deprioritize so contact emails rank first
    return score


def _extract_emails_from_text(text: str) -> set[str]:
    """Return set of candidate emails from text (filtered)."""
    found: set[str] = set()
    for m in EMAIL_RE.finditer(text):
        email = m.group(0).strip().lower()
        if len(email) > 254:
            continue
        if SKIP_EMAIL_PATTERNS.search(email):
            continue
        if "/" in email or "?" in email or "=" in email:
            continue
        found.add(email)
    return found


def _html_to_text(html: str) -> str:
    """Strip scripts/styles/tags and normalize whitespace."""
    if len(html) > PAGE_FETCH_MAX_CHARS:
        html = html[:PAGE_FETCH_MAX_CHARS]
    html = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text


def _fetch_page_text_headless(url: str) -> str:
    """Fetch URL via headless Chromium (Playwright). Used when httpx gets 403 Forbidden."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                html = page.content()
                return _html_to_text(html)
            finally:
                browser.close()
    except Exception as e:
        print(f"[ProviderContact] Headless fetch {url}: {e}")
        return ""


def _fetch_page_text(url: str) -> str:
    """Fetch URL and return body as plain text. On 403 Forbidden, retry with headless browser."""
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            r = client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            )
            if r.status_code == 403:
                print(f"[ProviderContact] Fetch {url}: 403 Forbidden, trying headless browser")
                return _fetch_page_text_headless(url)
            r.raise_for_status()
            return _html_to_text(r.text)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            print(f"[ProviderContact] Fetch {url}: 403 Forbidden, trying headless browser")
            return _fetch_page_text_headless(url)
        print(f"[ProviderContact] Fetch {url}: {e}")
        return ""
    except Exception as e:
        print(f"[ProviderContact] Fetch {url}: {e}")
        return ""


def _emails_from_organic_pages(data: dict[str, Any], max_urls: int = PAGE_FETCH_MAX_URLS) -> list[str]:
    """
    Fetch top organic result URLs from SerpApi response, extract emails from page HTML,
    score and return best-first. Used when snippet extraction returns no emails.
    """
    results = data.get("organic_results") or []
    urls: list[str] = []
    for item in results[:max_urls]:
        link = item.get("link")
        if isinstance(link, str) and link.startswith("http"):
            urls.append(link)
    if not urls:
        return []
    print(f"[ProviderContact] No emails in snippets; fetching {len(urls)} result page(s)")
    scored: list[tuple[str, int]] = []
    seen: set[str] = set()
    for u in urls:
        text = _fetch_page_text(u)
        for email in _extract_emails_from_text(text):
            if email not in seen:
                seen.add(email)
                scored.append((email, _score_email(email)))
    scored.sort(key=lambda x: -x[1])
    return [e for e, _ in scored]


def extract_emails_from_serpapi_response(data: dict[str, Any]) -> list[str]:
    """
    Extract and rank contact emails from SerpApi Google search JSON.
    Scans related_questions[].snippet, organic_results[].snippet, and
    organic_results[].about_this_result.source.description.
    Returns list of emails best-first; billing-style emails are deprioritized.
    """
    texts: list[str] = []
    for item in data.get("related_questions") or []:
        s = item.get("snippet")
        if isinstance(s, str) and s.strip():
            texts.append(s)
    for item in data.get("organic_results") or []:
        s = item.get("snippet")
        if isinstance(s, str) and s.strip():
            texts.append(s)
        desc = (item.get("about_this_result") or {}).get("source") or {}
        d = desc.get("description")
        if isinstance(d, str) and d.strip():
            texts.append(d)
    combined = " ".join(texts)
    candidates = _extract_emails_from_text(combined)
    if not candidates:
        return []
    scored: list[tuple[str, int]] = [(e, _score_email(e)) for e in candidates]
    scored.sort(key=lambda x: -x[1])
    return [e for e, _ in scored]


def find_provider_emails_serpapi(
    provider_name: str,
    state: str | None,
    api_key: str,
) -> list[str]:
    """
    Call SerpApi for provider + state + "contact email", process results, return emails.
    Final result is always a list of emails (if found):
    1. Extract from snippets (related_questions + organic_results).
    2. If none, fetch top organic result pages and extract emails from HTML.
    Returns best-first (contact preferred, billing deprioritized).
    """
    name = (provider_name or "").strip()
    if not name:
        return []
    state = (state or "").strip().upper()
    query = f'"{name}"'
    if state:
        query += f" {state}"
    query += " contact email"
    url = "https://serpapi.com/search.json"
    params = {"engine": "google", "q": query, "api_key": api_key, "num": 10}
    print(f"[ProviderContact] Calling SerpApi: GET {url} q={query!r}")
    try:
        with httpx.Client(timeout=15) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        print(f"[ProviderContact] SerpApi request failed: {e}")
        return []
    # 1. Snippets first
    emails = extract_emails_from_serpapi_response(data)
    # 2. If no emails in snippets, fetch result pages and extract from HTML
    if not emails:
        emails = _emails_from_organic_pages(data)
    print(f"[ProviderContact] SerpApi final result: {len(emails)} email(s), best-first: {emails[:3]!r}")
    return emails


def run_provider_contact_lookup_job(
    property_id: int,
    provider_ids: list[int] | None = None,
) -> None:
    """
    Background job: for each property utility provider (with null contact_email),
    call SerpApi to find contact email and update the row.
    Use a new DB session (call from BackgroundTasks after request ends).
    """
    from app.database import SessionLocal
    from app.config import get_settings
    from app.models.property_utility import PropertyUtilityProvider
    from app.models.owner import Property

    print(f"[ProviderContact] BACKGROUND JOB START: provider_contact_lookup property_id={property_id} provider_ids={provider_ids}")
    api_key = (get_settings().serpapi_key or "").strip()
    if not api_key:
        print(f"[ProviderContact] BACKGROUND JOB COMPLETE: provider_contact_lookup property_id={property_id} skipped (SERPAPI_KEY not set)")
        return
    db = SessionLocal()
    updated = 0
    try:
        prop = db.query(Property).filter(Property.id == property_id).first()
        if not prop:
            print(f"[ProviderContact] BACKGROUND JOB COMPLETE: provider_contact_lookup property_id={property_id} skipped (property not found)")
            return
        state = (prop.smarty_state_abbreviation or prop.state or "").strip().upper() or None
        q = db.query(PropertyUtilityProvider).filter(
            PropertyUtilityProvider.property_id == property_id,
            PropertyUtilityProvider.contact_email.is_(None),
            PropertyUtilityProvider.provider_type.in_(("electric", "gas", "internet")),
        )
        if provider_ids is not None:
            q = q.filter(PropertyUtilityProvider.id.in_(provider_ids))
        rows = q.all()
        print(f"[ProviderContact] run_provider_contact_lookup_job: found {len(rows)} provider(s) with null contact_email (state={state!r})")
        test_provider_email = (get_settings().test_provider_email or "").strip() or None
        for row in rows:
            print(f"[ProviderContact] Looking up contact for: provider_name={row.provider_name!r}, type={row.provider_type}, id={row.id}")
            # Never call SerpApi for "Test provider" - search returns wrong results (e.g. contact@switchhealth.ca from Switch Health). Use TEST_PROVIDER_EMAIL or leave null.
            if (row.provider_name or "").strip().lower() == "test provider":
                if test_provider_email:
                    row.contact_email = test_provider_email
                    updated += 1
                    print(f"[ProviderContact] Test provider: using TEST_PROVIDER_EMAIL, not SerpApi")
                else:
                    print(f"[ProviderContact] Test provider: skipping SerpApi (set TEST_PROVIDER_EMAIL in .env to store test address)")
                continue
            emails = find_provider_emails_serpapi(row.provider_name, state, api_key)
            if emails:
                row.contact_email = emails[0]
                updated += 1
                print(f"[ProviderContact] Updated property_utility_providers.id={row.id} contact_email={emails[0]!r}")
            else:
                print(f"[ProviderContact] No email found for provider_name={row.provider_name!r}")
        db.commit()
        # Send authority letter email to providers we just found contact for. In testing (TEST_PROVIDER_EMAIL set), do not send to real authorities—only test provider gets emails.
        from app.config import get_settings
        from app.models.property_utility import PropertyAuthorityLetter
        from app.services.authority_letter_email import send_authority_letter_to_provider
        test_email = (get_settings().test_provider_email or "").strip().lower() or None
        for row in rows:
            if not (row.contact_email or "").strip():
                continue
            if test_email:
                print(f"[ProviderContact] Testing env: skipping send to real authority for {row.provider_name}")
                continue
            letter = db.query(PropertyAuthorityLetter).filter(
                PropertyAuthorityLetter.property_utility_provider_id == row.id,
            ).first()
            if letter and not letter.email_sent_at:
                try:
                    if send_authority_letter_to_provider(db, letter, row.contact_email, row.provider_name, prop.name if prop else None):
                        print(f"[ProviderContact] Authority letter email sent to {row.contact_email} for {row.provider_name}")
                except Exception as e:
                    print(f"[ProviderContact] Failed to send authority letter email for {row.provider_name}: {e}")
        print(f"[ProviderContact] BACKGROUND JOB COMPLETE: provider_contact_lookup property_id={property_id} updated={updated} total={len(rows)}")
    except Exception as e:
        print(f"[ProviderContact] BACKGROUND JOB COMPLETE: provider_contact_lookup property_id={property_id} error={e!r}")
        raise
    finally:
        db.close()
