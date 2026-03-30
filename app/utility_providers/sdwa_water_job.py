"""
Background job: populate/update SQLite water_provider_cache from EPA SDWA bulk data.

Source: EPA ECHO SDWA download (ZIP) or local extracted folder/CSV.
- ZIP URL: https://echo.epa.gov/files/echodownloads/SDWA_latest_downloads.zip
- CSV inside: SDWA_PUB_WATER_SYSTEMS.csv with PWSID, PWS_NAME, STATE_CODE, EMAIL_ADDR, PHONE_NUMBER, etc.

Merges into water_provider_cache (adds new providers, updates existing by PWSID). Does not remove
rows that exist in the DB but are not in the CSV. Contact email and phone are extracted and stored.

Do not schedule in startup; run via script or scheduler when needed.
"""

from __future__ import annotations

import csv
import logging
import os
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.request import urlretrieve

from app.config import get_settings
from app.utility_providers.sqlite_cache import (
    ensure_tables,
    get_connection,
    upsert_water_providers_merge,
)

logger = logging.getLogger(__name__)

_JOB_NAME = "sdwa_water_job"
_SDWA_ZIP_URL = "https://echo.epa.gov/files/echodownloads/SDWA_latest_downloads.zip"
_CSV_NAME = "SDWA_PUB_WATER_SYSTEMS.csv"

# SDWA CSV column names (EPA export)
_PWSID = "PWSID"
_PWS_NAME = "PWS_NAME"
_STATE_CODE = "STATE_CODE"
_EMAIL_ADDR = "EMAIL_ADDR"
_PHONE_NUMBER = "PHONE_NUMBER"
_CITY_NAME = "CITY_NAME"
_PWS_ACTIVITY_CODE = "PWS_ACTIVITY_CODE"
_PWS_DEACTIVATION_DATE = "PWS_DEACTIVATION_DATE"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_sdwa_csv_path() -> Path | None:
    """
    Resolve path to SDWA_PUB_WATER_SYSTEMS.csv.
    Checks: WATER_SDWA_CSV_PATH env, water_sdwa_csv_path config, SDWA_latest_downloads/SDWA_PUB_WATER_SYSTEMS.csv, project root CSV.
    """
    settings = get_settings()
    configured = (getattr(settings, "water_sdwa_csv_path", "") or os.environ.get("WATER_SDWA_CSV_PATH") or "").strip()
    if configured:
        p = Path(configured)
        if p.is_file():
            return p
        if (p / _CSV_NAME).is_file():
            return p / _CSV_NAME
    root = _project_root()
    # Repo folder: SDWA_latest_downloads/SDWA_PUB_WATER_SYSTEMS.csv
    default_dir = root / "SDWA_latest_downloads"
    if (default_dir / _CSV_NAME).is_file():
        return default_dir / _CSV_NAME
    if (root / _CSV_NAME).is_file():
        return root / _CSV_NAME
    return None


def _map_sdwa_row_to_cache(row: dict[str, Any]) -> dict[str, Any] | None:
    """Map one SDWA_PUB_WATER_SYSTEMS.csv row to water_provider_cache row. Returns None if skip."""
    pwsid = (row.get(_PWSID) or "").strip()
    if not pwsid:
        return None
    # Skip deactivated/closed systems
    activity = (row.get(_PWS_ACTIVITY_CODE) or "").strip().upper()
    deactivation = (row.get(_PWS_DEACTIVATION_DATE) or "").strip()
    if activity and activity != "A" and activity != "":
        return None
    if deactivation:
        return None

    state = (row.get(_STATE_CODE) or "").strip()
    pwsname = (row.get(_PWS_NAME) or "").strip() or "Water System"
    city = (row.get(_CITY_NAME) or "").strip()
    email = (row.get(_EMAIL_ADDR) or "").strip()
    phone = (row.get(_PHONE_NUMBER) or "").strip()

    return {
        "pwsid": pwsid,
        "pwsname": pwsname,
        "state": state,
        "contactcity": city,
        "contactstate": state,
        "contactphone": phone,
        "contactemail": email,
        "status": "Active",
    }


def _load_sdwa_csv(csv_path: Path) -> tuple[list[dict[str, Any]], int, int]:
    """
    Load SDWA_PUB_WATER_SYSTEMS.csv and map to cache rows.
    Returns (rows_to_upsert, rows_skipped_invalid, rows_skipped_inactive).
    """
    rows: list[dict[str, Any]] = []
    skipped_invalid = 0
    skipped_inactive = 0
    with open(csv_path, newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            pwsid = (row.get(_PWSID) or "").strip()
            if not pwsid:
                skipped_invalid += 1
                continue
            activity = (row.get(_PWS_ACTIVITY_CODE) or "").strip().upper()
            deactivation = (row.get(_PWS_DEACTIVATION_DATE) or "").strip()
            if activity and activity not in ("A", ""):
                skipped_inactive += 1
                continue
            if deactivation:
                skipped_inactive += 1
                continue
            mapped = _map_sdwa_row_to_cache(row)
            if mapped:
                rows.append(mapped)
    return rows, skipped_invalid, skipped_inactive


def _download_and_extract_sdwa_zip() -> Path | None:
    """Download SDWA zip to temp dir, extract, return path to SDWA_PUB_WATER_SYSTEMS.csv or None."""
    try:
        with tempfile.TemporaryDirectory(prefix="sdwa_") as tmpdir:
            zip_path = Path(tmpdir) / "SDWA_latest_downloads.zip"
            logger.info("[%s] Downloading %s ...", _JOB_NAME, _SDWA_ZIP_URL)
            urlretrieve(_SDWA_ZIP_URL, zip_path)
            csv_path = Path(tmpdir) / _CSV_NAME
            with zipfile.ZipFile(zip_path, "r") as zf:
                for name in zf.namelist():
                    if name.endswith(_CSV_NAME) or name == _CSV_NAME:
                        zf.extract(name, tmpdir)
                        extracted = Path(tmpdir) / name
                        if extracted.is_file():
                            return extracted
                        # sometimes path includes folder
                        for p in Path(tmpdir).rglob(_CSV_NAME):
                            if p.is_file():
                                return p
            return None
    except Exception as e:
        logger.exception("[%s] Download/extract failed: %s", _JOB_NAME, e)
        return None


def run_sdwa_water_job(
    *,
    use_local_only: bool = False,
    local_csv_path: Path | str | None = None,
) -> dict[str, Any]:
    """
    Run the SDWA water population job: load SDWA_PUB_WATER_SYSTEMS (from local path or download zip),
    merge into SQLite water_provider_cache (add new, update existing by PWSID). Adds contact email and phone.

    Args:
        use_local_only: If True, do not download; use only local path.
        local_csv_path: Override path to CSV or folder containing SDWA_PUB_WATER_SYSTEMS.csv.

    Returns:
        Summary dict: success, csv_path, source, rows_loaded, rows_merged, rows_skipped, skipped_inactive, duration_seconds, error.
    """
    start = time.perf_counter()
    summary: dict[str, Any] = {
        "job": _JOB_NAME,
        "success": False,
        "csv_path": None,
        "source": None,
        "rows_loaded": 0,
        "rows_merged": 0,
        "rows_skipped": 0,
        "skipped_inactive": 0,
        "duration_seconds": 0.0,
        "error": None,
    }
    logger.info("[%s] ========== Starting SDWA water job ==========", _JOB_NAME)

    csv_path: Path | None = None
    if local_csv_path is not None:
        p = Path(local_csv_path)
        if p.is_file():
            csv_path = p
        elif (p / _CSV_NAME).is_file():
            csv_path = p / _CSV_NAME
    if csv_path is None:
        csv_path = _resolve_sdwa_csv_path()
    if csv_path is not None:
        summary["source"] = "local"
        summary["csv_path"] = str(csv_path)
    else:
        if use_local_only:
            summary["error"] = "Local SDWA CSV not found and use_local_only=True"
            summary["duration_seconds"] = round(time.perf_counter() - start, 2)
            return summary
        summary["source"] = "download"
        csv_path = _download_and_extract_sdwa_zip()
        if csv_path:
            summary["csv_path"] = str(csv_path)
        else:
            summary["error"] = "Downloaded zip did not contain SDWA_PUB_WATER_SYSTEMS.csv or download failed"
            summary["duration_seconds"] = round(time.perf_counter() - start, 2)
            return summary

    try:
        rows, skipped_invalid, skipped_inactive = _load_sdwa_csv(csv_path)
        summary["rows_loaded"] = len(rows)
        summary["skipped_inactive"] = skipped_inactive
        if not rows:
            logger.warning("[%s] No rows to merge", _JOB_NAME)
            summary["success"] = True
            summary["duration_seconds"] = round(time.perf_counter() - start, 2)
            return summary

        conn = get_connection()
        try:
            ensure_tables(conn)
            merged, skipped = upsert_water_providers_merge(rows, conn=conn)
            summary["rows_merged"] = merged
            summary["rows_skipped"] = skipped
        finally:
            conn.close()

        logger.info("[%s] Merged %d water providers (skipped %d invalid)", _JOB_NAME, merged, skipped)
        summary["success"] = True
    except Exception as e:
        summary["error"] = str(e)
        logger.exception("[%s] Job failed: %s", _JOB_NAME, e)

    summary["duration_seconds"] = round(time.perf_counter() - start, 2)
    logger.info("[%s] ========== Finished in %.2fs (success=%s) ==========", _JOB_NAME, summary["duration_seconds"], summary["success"])
    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run SDWA water provider job (merge into water_provider_cache)")
    parser.add_argument("--local-only", action="store_true", help="Use only local CSV; do not download zip")
    parser.add_argument("--csv", type=str, default=None, help="Path to SDWA_PUB_WATER_SYSTEMS.csv or folder containing it")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    result = run_sdwa_water_job(use_local_only=args.local_only, local_csv_path=args.csv)
    print(result)
    raise SystemExit(0 if result.get("success") else 1)
