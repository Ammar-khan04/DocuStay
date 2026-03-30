"""
Background job: populate SQLite internet_bdc_fallback from FCC BDC provider summary CSV.

Single source: local BDC fixed broadband provider summary CSV (e.g. bdc_us_fixed_broadband_provider_summary_*.csv).
Aggregates by holding_company (sum of unit_count_res + unit_count_bus), ranks by total, writes top providers
to internet_bdc_fallback table for use when county cache misses.
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
    replace_internet_bdc_fallback,
)

logger = logging.getLogger(__name__)

_JOB_NAME = "internet_bdc_csv_job"
_DEFAULT_CSV_NAME = "bdc_us_fixed_broadband_provider_summary_J25_17feb2026.csv"
_TOP_N = 200  # Store top N in DB; lookup typically uses top 10


def _resolve_bdc_csv_path() -> Path | None:
    """Resolve path to FCC BDC provider summary CSV from config or default locations."""
    settings = get_settings()
    configured = (settings.fcc_broadband_csv_path or "").strip()
    if configured and os.path.isfile(configured):
        return Path(os.path.abspath(configured))
    root = Path(__file__).resolve().parents[2]
    for base in (root, root / "data" / "fcc"):
        p = base / _DEFAULT_CSV_NAME
        if p.is_file():
            return p
    # Try any bdc*provider*summary*.csv in data/fcc
    fcc_dir = root / "data" / "fcc"
    if fcc_dir.is_dir():
        for f in fcc_dir.glob("bdc*provider*summary*.csv"):
            return f
    return None


def _load_and_aggregate_bdc(csv_path: Path) -> list[tuple[str, int]]:
    """
    Load BDC CSV, aggregate by holding_company (sum of unit_count_res + unit_count_bus).
    Returns list of (provider_name, total_units) sorted by total descending.
    """
    totals: dict[str, int] = {}
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("holding_company") or "").strip()
            if not name:
                continue
            try:
                res = int(row.get("unit_count_res") or 0)
                bus = int(row.get("unit_count_bus") or 0)
            except (TypeError, ValueError):
                res = bus = 0
            totals[name] = totals.get(name, 0) + res + bus
    ordered = sorted(totals.items(), key=lambda x: -x[1])
    return ordered


def run_internet_bdc_csv_job() -> dict[str, Any]:
    """
    Run the internet BDC CSV population job: read CSV, aggregate by holding_company,
    write top _TOP_N to internet_bdc_fallback table.
    Returns summary dict: csv_path, providers_aggregated, rows_written, duration_seconds, success, error.
    """
    start = time.perf_counter()
    summary: dict[str, Any] = {
        "job": _JOB_NAME,
        "csv_path": None,
        "providers_aggregated": 0,
        "rows_written": 0,
        "duration_seconds": 0.0,
        "success": False,
        "error": None,
    }
    logger.info("[%s] ========== Starting internet BDC CSV population job ==========", _JOB_NAME)
    print(f"[{_JOB_NAME}] ========== Starting internet BDC CSV population job ==========")

    csv_path = _resolve_bdc_csv_path()
    if not csv_path:
        msg = "BDC provider summary CSV not found: set FCC_BROADBAND_CSV_PATH or place file in project root or data/fcc/"
        summary["error"] = msg
        logger.warning("[%s] %s", _JOB_NAME, msg)
        print(f"[{_JOB_NAME}] ERROR: {msg}")
        summary["duration_seconds"] = round(time.perf_counter() - start, 2)
        return summary

    summary["csv_path"] = str(csv_path)
    logger.info("[%s] Using CSV path: %s", _JOB_NAME, csv_path)
    print(f"[{_JOB_NAME}] Using CSV path: {csv_path}")

    try:
        logger.info("[%s] Reading CSV and aggregating by holding_company...", _JOB_NAME)
        print(f"[{_JOB_NAME}] Reading CSV and aggregating by holding_company...")
        ordered = _load_and_aggregate_bdc(csv_path)
        summary["providers_aggregated"] = len(ordered)
        logger.info("[%s] Aggregated %d unique holding companies", _JOB_NAME, len(ordered))
        print(f"[{_JOB_NAME}] Aggregated {len(ordered)} unique holding companies")

        to_store = ordered[:_TOP_N]
        as_of = csv_path.stem.replace("bdc_us_fixed_broadband_provider_summary_", "").replace("_", " ") or None

        logger.info("[%s] Writing top %d providers to internet_bdc_fallback (as_of=%s)...", _JOB_NAME, len(to_store), as_of)
        print(f"[{_JOB_NAME}] Writing top {len(to_store)} providers to internet_bdc_fallback (as_of={as_of})...")
        conn = get_connection()
        try:
            ensure_tables(conn)
            written = replace_internet_bdc_fallback(to_store, as_of_date=as_of, conn=conn)
            summary["rows_written"] = written
        finally:
            conn.close()

        logger.info("[%s] Wrote %d rows to internet_bdc_fallback", _JOB_NAME, written)
        print(f"[{_JOB_NAME}] Wrote {written} rows to internet_bdc_fallback")
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
    run_internet_bdc_csv_job()
