"""
Background job: populate SQLite cache with county-level internet providers from FCC Location Coverage.

Runs for all counties in target states (Florida, California, Texas, New York).
Scheduled monthly; can be run once at startup or via CLI.

Flow per state:
  1. List Location Coverage files for that state (Fixed Broadband).
  2. Download each file (ZIP -> CSV), parse rows (block_geoid, brand_name).
  3. Aggregate by county: block_geoid[:5] = state_fips + county_fips -> set of brand_name.
  4. Upsert into SQLite (internet_provider_cache).
"""

from __future__ import annotations

import csv
import io
import logging
import time
import zipfile
from collections.abc import Iterator
from typing import Any

import httpx

from app.config import get_settings
from app.utility_providers.constants import TARGET_STATES
from app.utility_providers.sqlite_cache import (
    ensure_tables,
    get_connection,
    get_internet_providers_for_county,
    upsert_county_providers,
)

logger = logging.getLogger(__name__)

FCC_BASE = "https://broadbandmap.fcc.gov/api/public"
TIMEOUT = 60
# Large files (~50MB+); use streaming + long read timeout and retries for flaky connections
DOWNLOAD_TIMEOUT = 900  # 15 min total per attempt
DOWNLOAD_RETRIES = 4     # 1 initial + 3 retries
RETRY_BACKOFF_SECONDS = [15, 45, 120]  # wait before retries 1, 2, 3
DATA_TYPE_AVAILABILITY = "availability"


def _auth_headers() -> dict[str, str]:
    settings = get_settings()
    username = (settings.fcc_broadband_api_username or "").strip()
    token = (settings.fcc_public_map_data_apis or "").strip()
    if not username or not token:
        raise ValueError("FCC_BROADBAND_API_USERNAME and FCC_PUBLIC_MAP_DATA_APIS must be set")
    return {"username": username, "hash_value": token, "user-agent": "play/0.0.0"}


def _latest_as_of_date() -> str:
    logger.info("[fcc_internet_job] Fetching latest FCC as_of_date...")
    print("[fcc_internet_job] Fetching latest FCC as_of_date...")
    r = httpx.get(f"{FCC_BASE}/map/listAsOfDates", headers=_auth_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "successful" or not data.get("data"):
        raise ValueError("listAsOfDates failed or empty")
    dates = [item["as_of_date"] for item in data["data"] if item.get("data_type") == "availability"]
    as_of = max(dates)
    logger.info("[fcc_internet_job] Using as_of_date: %s", as_of)
    print(f"[fcc_internet_job] Using as_of_date: {as_of}")
    return as_of


def _list_location_coverage_files(state_name: str, as_of_date: str) -> list[dict[str, Any]]:
    logger.info("[fcc_internet_job] Listing Location Coverage files for %s (as_of=%s)", state_name, as_of_date)
    params = {
        "category": "State",
        "subcategory": "Location Coverage",
        "technology_type": "Fixed Broadband",
    }
    r = httpx.get(
        f"{FCC_BASE}/map/downloads/listAvailabilityData/{as_of_date}",
        headers=_auth_headers(),
        params=params,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "successful":
        raise ValueError(f"listAvailabilityData failed: {data.get('message', data)}")
    files = data.get("data") or []
    state_lower = state_name.strip().lower()
    matched = [f for f in files if (f.get("state_name") or "").strip().lower() == state_lower]
    logger.info("[fcc_internet_job] Found %d file(s) for %s", len(matched), state_name)
    print(f"[fcc_internet_job] Found {len(matched)} file(s) for {state_name}")
    return matched


def _download_file(file_id: str) -> bytes:
    """Download file with streaming and retries to handle large files and flaky server connections."""
    url = f"{FCC_BASE}/map/downloads/downloadFile/{DATA_TYPE_AVAILABILITY}/{file_id}"
    last_error: Exception | None = None
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        try:
            if attempt > 1:
                wait = RETRY_BACKOFF_SECONDS[attempt - 2] if attempt - 2 < len(RETRY_BACKOFF_SECONDS) else 120
                logger.info("[fcc_internet_job] Retry %d/%d for file_id=%s in %ds...", attempt, DOWNLOAD_RETRIES, file_id, wait)
                print(f"[fcc_internet_job] Retry {attempt}/{DOWNLOAD_RETRIES} for file_id={file_id} in {wait}s...")
                time.sleep(wait)
            logger.info("[fcc_internet_job] Downloading file_id=%s (attempt %d, timeout=%ds, streaming)", file_id, attempt, DOWNLOAD_TIMEOUT)
            print(f"[fcc_internet_job] Downloading file_id={file_id} (attempt {attempt}, timeout={DOWNLOAD_TIMEOUT}s)...")
            # Stream to avoid loading full body in memory and to get clearer errors on disconnect
            with httpx.stream(
                "GET",
                url,
                headers=_auth_headers(),
                timeout=httpx.Timeout(DOWNLOAD_TIMEOUT),
            ) as r:
                r.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                for chunk in r.iter_bytes(chunk_size=262144):  # 256KB
                    chunks.append(chunk)
                    total += len(chunk)
                raw = b"".join(chunks)
            logger.info("[fcc_internet_job] Downloaded %d bytes for file_id=%s", len(raw), file_id)
            print(f"[fcc_internet_job] Downloaded {len(raw)} bytes for file_id={file_id}")
            return raw
        except (httpx.HTTPError, OSError) as e:
            last_error = e
            logger.warning("[fcc_internet_job] Download attempt %d failed for file_id=%s: %s", attempt, file_id, e)
            print(f"[fcc_internet_job] Attempt {attempt} failed: {e}")
            if attempt == DOWNLOAD_RETRIES:
                raise last_error
    raise last_error or RuntimeError("Download failed")


def _stream_csv_rows(raw: bytes) -> Iterator[dict[str, Any]]:
    """
    Stream CSV rows from ZIP or raw CSV one row at a time (avoids loading full decompressed CSV into memory).
    Yields row dicts. Use for large files to prevent MemoryError.
    """
    if raw[:4] == b"PK\x03\x04" or raw[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
                for info in sorted(zf.namelist()):
                    if info.lower().endswith(".csv"):
                        with zf.open(info) as f:
                            text_stream = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
                            reader = csv.DictReader(text_stream)
                            for row in reader:
                                yield row
                        return
        except zipfile.BadZipFile:
            logger.warning("[fcc_internet_job] ZIP corrupt (e.g. Bad CRC), trying raw CSV fallback")
            text = raw.decode("utf-8", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                yield row
    else:
        text = raw.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            yield row


def _extract_csv_rows(raw: bytes) -> list[dict[str, Any]]:
    """Extract CSV rows from ZIP or raw CSV (loads all into memory; use _stream_csv_rows for large files)."""
    return list(_stream_csv_rows(raw))


def _aggregate_by_county(rows: Iterator[dict[str, Any]] | list[dict[str, Any]], state_fips: str) -> dict[str, set[str]]:
    """Map county_fips (3-digit) -> set of brand_name. Accepts list or stream of rows to avoid MemoryError on huge files."""
    by_county: dict[str, set[str]] = {}
    count = 0
    for row in rows:
        count += 1
        bg = (row.get("block_geoid") or "").strip()
        if len(bg) < 5 or not bg.startswith(state_fips):
            continue
        county_fips = bg[2:5]
        name = (row.get("brand_name") or "").strip()
        if name:
            by_county.setdefault(county_fips, set()).add(name)
    logger.info("[fcc_internet_job] Aggregated %d rows into %d counties for state_fips=%s", count, len(by_county), state_fips)
    return by_county


def run_fcc_internet_retry_files(file_ids: list[str]) -> dict[str, Any]:
    """
    Retry only the given file IDs: download each, merge new providers into existing county cache.
    Use after a full run that reported failed files (e.g. 1448854 1448907 1449018 1449007).
    Returns summary: files_processed, counties_updated, errors.
    """
    if not file_ids:
        return {"files_processed": 0, "counties_updated": 0, "errors": []}
    file_ids = [str(f).strip() for f in file_ids if str(f).strip()]
    if not file_ids:
        return {"files_processed": 0, "counties_updated": 0, "errors": []}

    logger.info("[fcc_internet_job] ========== Retry %d file(s) only ==========", len(file_ids))
    print(f"[fcc_internet_job] ========== Retry {len(file_ids)} file(s) only ==========")
    summary: dict[str, Any] = {"files_processed": 0, "counties_updated": 0, "errors": []}

    try:
        as_of_date = _latest_as_of_date()
    except Exception as e:
        summary["errors"].append(f"get as_of_date: {e}")
        return summary

    # Build file_id -> (state_name, state_fips) by listing files per state
    file_to_state: dict[str, tuple[str, str]] = {}
    for state_name, state_fips in TARGET_STATES:
        try:
            files = _list_location_coverage_files(state_name, as_of_date)
            for f in files:
                fid = str(f.get("file_id"))
                if fid:
                    file_to_state[fid] = (state_name, state_fips)
        except Exception as e:
            logger.warning("[fcc_internet_job] List files for %s failed: %s", state_name, e)
    missing = [f for f in file_ids if f not in file_to_state]
    if missing:
        summary["errors"].append(f"File ID(s) not found in any target state: {missing}")
        print(f"[fcc_internet_job] Warning: file IDs not found: {missing}")

    conn = get_connection()
    try:
        ensure_tables(conn)
        for file_id in file_ids:
            if file_id not in file_to_state:
                continue
            state_name, state_fips = file_to_state[file_id]
            logger.info("[fcc_internet_job] Retrying file_id=%s (%s)", file_id, state_name)
            print(f"[fcc_internet_job] Retrying file_id={file_id} ({state_name})...")
            last_err: Exception | None = None
            for extract_attempt in range(1, 3):  # 2 attempts: corrupt ZIP often succeeds on re-download
                try:
                    if extract_attempt > 1:
                        logger.warning("[fcc_internet_job] BadZipFile/corrupt download, re-downloading file_id=%s (attempt %d)", file_id, extract_attempt)
                        print(f"[fcc_internet_job] Re-downloading file_id={file_id} (attempt {extract_attempt})...")
                    raw = _download_file(file_id)
                    by_county = _aggregate_by_county(_stream_csv_rows(raw), state_fips)
                    for county_fips, new_providers in by_county.items():
                        existing = get_internet_providers_for_county(state_fips, county_fips)
                        merged = set(existing) | new_providers
                        upsert_county_providers(state_fips, county_fips, list(merged), as_of_date, conn=conn)
                        summary["counties_updated"] += 1
                    summary["files_processed"] += 1
                    logger.info("[fcc_internet_job] file_id=%s: merged into %d counties", file_id, len(by_county))
                    print(f"[fcc_internet_job] file_id={file_id}: merged into {len(by_county)} counties")
                    last_err = None
                    break
                except zipfile.BadZipFile as e:
                    last_err = e
                    if extract_attempt == 2:
                        err_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                        summary["errors"].append(f"{state_name} file {file_id}: {err_msg}")
                        logger.warning("[fcc_internet_job] Retry failed for file_id=%s (corrupt ZIP): %s", file_id, err_msg)
                except Exception as e:
                    last_err = e
                    err_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                    summary["errors"].append(f"{state_name} file {file_id}: {err_msg}")
                    logger.warning("[fcc_internet_job] Retry failed for file_id=%s: %s", file_id, err_msg)
                    break
    finally:
        conn.close()

    logger.info("[fcc_internet_job] Retry finished: files_processed=%d, counties_updated=%d, errors=%d",
                summary["files_processed"], summary["counties_updated"], len(summary["errors"]))
    print(f"[fcc_internet_job] Retry finished: files_processed={summary['files_processed']}, counties_updated={summary['counties_updated']}, errors={len(summary['errors'])}")
    return summary


def run_fcc_internet_cache_job(from_state_fips: str | None = None) -> dict[str, Any]:
    """
    Run the full job: for each target state, fetch Location Coverage, aggregate by county, write to SQLite.
    If from_state_fips is set (e.g. "06"), skip states before that FIPS so you can resume from a given state.
    Returns summary dict: states_processed, counties_updated, as_of_date, errors.
    """
    logger.info("[fcc_internet_job] ========== Starting FCC internet cache job ==========")
    print("[fcc_internet_job] ========== Starting FCC internet cache job ==========")
    if from_state_fips:
        logger.info("[fcc_internet_job] Resuming from state FIPS %s", from_state_fips)
        print(f"[fcc_internet_job] Resuming from state FIPS {from_state_fips}")
    summary: dict[str, Any] = {"states_processed": 0, "counties_updated": 0, "as_of_date": None, "errors": []}
    try:
        as_of_date = _latest_as_of_date()
        summary["as_of_date"] = as_of_date
    except Exception as e:
        summary["errors"].append(f"get as_of_date: {e}")
        logger.exception("[fcc_internet_job] Failed to get as_of_date: %s", e)
        return summary

    logger.info("[fcc_internet_job] Ensuring SQLite tables exist...")
    print("[fcc_internet_job] Ensuring SQLite tables exist...")
    conn = get_connection()
    try:
        ensure_tables(conn)
        logger.info("[fcc_internet_job] Tables ready.")
        print("[fcc_internet_job] Tables ready.")
    finally:
        conn.close()

    states_to_process = TARGET_STATES
    if from_state_fips:
        try:
            idx = next(i for i, (_, f) in enumerate(TARGET_STATES) if f == from_state_fips.strip())
            states_to_process = TARGET_STATES[idx:]
        except StopIteration:
            pass
    for state_name, state_fips in states_to_process:
        logger.info("[fcc_internet_job] ---------- Processing state: %s (FIPS %s) ----------", state_name, state_fips)
        print(f"[fcc_internet_job] ---------- Processing state: {state_name} (FIPS {state_fips}) ----------")
        try:
            files = _list_location_coverage_files(state_name, as_of_date)
            if not files:
                summary["errors"].append(f"{state_name}: no Location Coverage files")
                logger.warning("[fcc_internet_job] Skipping %s: no files found", state_name)
                continue
            all_by_county: dict[str, set[str]] = {}
            for i, f in enumerate(files):
                file_id = str(f.get("file_id"))
                logger.info("[fcc_internet_job] [%s] File %d/%d file_id=%s", state_name, i + 1, len(files), file_id)
                last_file_err: Exception | None = None
                for extract_attempt in range(1, 3):
                    try:
                        if extract_attempt > 1:
                            logger.warning("[fcc_internet_job] BadZipFile/corrupt, re-downloading file_id=%s", file_id)
                        raw = _download_file(file_id)
                        by_county_file = _aggregate_by_county(_stream_csv_rows(raw), state_fips)
                        for county_fips, providers in by_county_file.items():
                            all_by_county.setdefault(county_fips, set()).update(providers)
                        last_file_err = None
                        break
                    except zipfile.BadZipFile as e:
                        last_file_err = e
                        if extract_attempt == 2:
                            err_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                            summary["errors"].append(f"{state_name} file {file_id}: {err_msg}")
                            logger.warning("[fcc_internet_job] Download failed for %s file_id=%s: %s", state_name, file_id, err_msg)
                    except Exception as e:
                        last_file_err = e
                        err_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                        summary["errors"].append(f"{state_name} file {file_id}: {err_msg}")
                        logger.warning("[fcc_internet_job] Download failed for %s file_id=%s: %s", state_name, file_id, err_msg)
                        break
            logger.info("[fcc_internet_job] [%s] Counties with data: %d", state_name, len(all_by_county))
            print(f"[fcc_internet_job] [{state_name}] Counties with data: {len(all_by_county)}")
            by_county = all_by_county
            logger.info("[fcc_internet_job] [%s] Writing %d counties to SQLite...", state_name, len(by_county))
            print(f"[fcc_internet_job] [{state_name}] Writing {len(by_county)} counties to SQLite...")
            conn = get_connection()
            try:
                for county_fips, providers in by_county.items():
                    upsert_county_providers(
                        state_fips,
                        county_fips,
                        list(providers),
                        as_of_date,
                        conn=conn,
                    )
                    summary["counties_updated"] += 1
                    logger.debug("[fcc_internet_job] [%s] County %s: %d providers", state_name, county_fips, len(providers))
            finally:
                conn.close()
            summary["states_processed"] += 1
            logger.info("[fcc_internet_job] [%s] Done. Counties written: %d", state_name, len(by_county))
            print(f"[fcc_internet_job] [{state_name}] Done. Counties written: {len(by_county)}")
        except Exception as e:
            summary["errors"].append(f"{state_name}: {e}")
            logger.exception("[fcc_internet_job] Processing failed for %s: %s", state_name, e)

    logger.info(
        "[fcc_internet_job] ========== Job finished: states_processed=%d, counties_updated=%d, errors=%d ==========",
        summary["states_processed"],
        summary["counties_updated"],
        len(summary["errors"]),
    )
    print("[fcc_internet_job] ========== Job finished ==========")
    print(f"[fcc_internet_job] Summary: states_processed={summary['states_processed']}, counties_updated={summary['counties_updated']}, errors={len(summary['errors'])}")
    if summary["errors"]:
        for err in summary["errors"]:
            logger.error("[fcc_internet_job] Error: %s", err)
            print(f"[fcc_internet_job] Error: {err}")
    return summary


if __name__ == "__main__":
    import argparse as _ap
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    p = _ap.ArgumentParser()
    p.add_argument("--from-state", type=str, metavar="FIPS", help="Resume from this state FIPS (e.g. 06)")
    p.add_argument("--retry-files", type=str, nargs="*", metavar="FILE_ID", help="Retry only these file IDs; merge into existing cache")
    a = p.parse_args()
    if a.retry_files:
        result = run_fcc_internet_retry_files(a.retry_files)
    else:
        result = run_fcc_internet_cache_job(from_state_fips=a.from_state)
    print("Result:", result)
