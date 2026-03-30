"""
Background job: populate SQLite water_provider_cache from EPA SDWIS CSV.

Single source: local CSV (e.g. CSV.csv) with columns pwsid, pwsname, state,
contactcity, contactstate, contactphone, status. Rows with status=CLOSED are skipped.
Run on schedule or after updating the CSV; lookup can then use DB instead of parsing CSV.
"""

from __future__ import annotations

import csv
import logging
import os
import time
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.utility_providers.sqlite_cache import (
    ensure_tables,
    get_connection,
    upsert_water_providers_bulk,
)

logger = logging.getLogger(__name__)

_JOB_NAME = "water_csv_job"
_DEFAULT_CSV_NAME = "CSV.csv"


def _resolve_water_csv_path() -> Path | None:
    """Resolve path to EPA SDWIS water CSV from config or default locations."""
    settings = get_settings()
    configured = (settings.water_csv_path or "").strip()
    if configured and os.path.isfile(configured):
        return Path(os.path.abspath(configured))
    root = Path(__file__).resolve().parents[2]
    default = root / _DEFAULT_CSV_NAME
    if default.is_file():
        return default
    return None


def _load_water_rows(csv_path: Path) -> tuple[list[dict[str, Any]], int]:
    """
    Load CSV rows, skipping status=CLOSED. Returns (rows_to_insert, skipped_closed_count).
    """
    rows: list[dict[str, Any]] = []
    skipped = 0
    with open(csv_path, newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            status = (row.get("status") or "").strip().upper()
            if status == "CLOSED":
                skipped += 1
                continue
            rows.append(row)
    return rows, skipped


def run_water_csv_job() -> dict[str, Any]:
    """
    Run the water CSV population job: read SDWIS CSV, filter out CLOSED, write to SQLite.
    Returns summary dict: csv_path, rows_read, rows_skipped_closed, rows_inserted, duration_seconds, success, error.
    """
    start = time.perf_counter()
    summary: dict[str, Any] = {
        "job": _JOB_NAME,
        "csv_path": None,
        "rows_read": 0,
        "rows_skipped_closed": 0,
        "rows_inserted": 0,
        "duration_seconds": 0.0,
        "success": False,
        "error": None,
    }
    logger.info("[%s] ========== Starting water CSV population job ==========", _JOB_NAME)
    print(f"[{_JOB_NAME}] ========== Starting water CSV population job ==========")

    csv_path = _resolve_water_csv_path()
    if not csv_path:
        msg = "Water CSV not found: set WATER_CSV_PATH or place CSV.csv in project root"
        summary["error"] = msg
        logger.warning("[%s] %s", _JOB_NAME, msg)
        print(f"[{_JOB_NAME}] ERROR: {msg}")
        summary["duration_seconds"] = round(time.perf_counter() - start, 2)
        return summary

    summary["csv_path"] = str(csv_path)
    logger.info("[%s] Using CSV path: %s", _JOB_NAME, csv_path)
    print(f"[{_JOB_NAME}] Using CSV path: {csv_path}")

    try:
        logger.info("[%s] Reading CSV and filtering out CLOSED status...", _JOB_NAME)
        print(f"[{_JOB_NAME}] Reading CSV and filtering out CLOSED status...")
        rows, skipped = _load_water_rows(csv_path)
        summary["rows_read"] = len(rows) + skipped
        summary["rows_skipped_closed"] = skipped
        logger.info("[%s] CSV read: %d active rows, %d skipped (CLOSED)", _JOB_NAME, len(rows), skipped)
        print(f"[{_JOB_NAME}] CSV read: {len(rows)} active rows, {skipped} skipped (CLOSED)")

        if not rows:
            logger.warning("[%s] No active rows to insert; water cache will be empty", _JOB_NAME)
            print(f"[{_JOB_NAME}] No active rows to insert; water cache will be empty")
            summary["success"] = True
            summary["duration_seconds"] = round(time.perf_counter() - start, 2)
            return summary

        logger.info("[%s] Ensuring SQLite tables and writing %d rows to water_provider_cache...", _JOB_NAME, len(rows))
        print(f"[{_JOB_NAME}] Ensuring SQLite tables and writing {len(rows)} rows to water_provider_cache...")
        conn = get_connection()
        try:
            ensure_tables(conn)
            inserted = upsert_water_providers_bulk(rows, conn=conn)
            summary["rows_inserted"] = inserted
        finally:
            conn.close()

        logger.info("[%s] Inserted %d water provider rows into SQLite", _JOB_NAME, inserted)
        print(f"[{_JOB_NAME}] Inserted {inserted} water provider rows into SQLite")
        summary["success"] = True
    except Exception as e:
        summary["error"] = str(e)
        logger.exception("[%s] Job failed: %s", _JOB_NAME, e)
        print(f"[{_JOB_NAME}] ERROR: {e}")

    summary["duration_seconds"] = round(time.perf_counter() - start, 2)
    logger.info("[%s] ========== Job finished in %.2fs (success=%s) ==========", _JOB_NAME, summary["duration_seconds"], summary["success"])
    print(f"[{_JOB_NAME}] ========== Job finished in {summary['duration_seconds']}s (success={summary['success']}) ==========")
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    run_water_csv_job()
