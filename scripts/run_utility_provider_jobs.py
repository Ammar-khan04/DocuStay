"""
Run utility provider SQLite population jobs.

Usage:
  python -m scripts.run_utility_provider_jobs              # run all jobs
  python -m scripts.run_utility_provider_jobs water          # water CSV only
  python -m scripts.run_utility_provider_jobs internet_bdc   # internet BDC CSV only
  python -m scripts.run_utility_provider_jobs fcc_internet  # FCC Location Coverage API only
  python -m scripts.run_utility_provider_jobs fcc_internet --from-state 06  # Resume from California (skip Florida)
  python -m scripts.run_utility_provider_jobs fcc_internet --retry-files 1448854 1448907 1449018 1449007  # Retry only failed file IDs

Jobs:
  - water:         EPA SDWIS CSV -> water_provider_cache
  - sdwa_water:    EPA SDWA bulk (ZIP/CSV) -> water_provider_cache merge (contact email/phone); not in 'all'
  - internet_bdc:  FCC BDC provider summary CSV -> internet_bdc_fallback
  - fcc_internet:  FCC Public Data API (Location Coverage) -> internet_provider_cache (county-level)
  - pending_verify: Verify user-added (pending) providers via SerpApi -> set verification_status (approved/rejected); also enqueued when user adds custom providers
"""

from __future__ import annotations

import argparse
import logging
import sys

# Ensure project root is on path when run as script
from pathlib import Path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Run utility provider cache population jobs")
    parser.add_argument(
        "job",
        nargs="?",
        choices=["all", "water", "sdwa_water", "internet_bdc", "fcc_internet", "pending_verify"],
        default="all",
        help="Which job to run (default: all). Note: 'all' does not include sdwa_water or pending_verify.",
    )
    parser.add_argument(
        "--from-state",
        type=str,
        metavar="FIPS",
        help="For fcc_internet only: resume from this state FIPS (e.g. 06 for California). Skips earlier states.",
    )
    parser.add_argument(
        "--retry-files",
        type=str,
        nargs="*",
        metavar="FILE_ID",
        default=None,
        help="For fcc_internet only: retry only these file IDs (e.g. 1448854 1448907). Merges into existing cache.",
    )
    args = parser.parse_args()

    jobs_to_run = []
    if args.job == "all":
        jobs_to_run = ["water", "internet_bdc", "fcc_internet"]
    else:
        jobs_to_run = [args.job]

    results = []
    for name in jobs_to_run:
        if name == "water":
            from app.utility_providers.water_csv_job import run_water_csv_job
            results.append(("water", run_water_csv_job()))
        elif name == "sdwa_water":
            from app.utility_providers.sdwa_water_job import run_sdwa_water_job
            results.append(("sdwa_water", run_sdwa_water_job(use_local_only=True)))
        elif name == "internet_bdc":
            from app.utility_providers.internet_bdc_csv_job import run_internet_bdc_csv_job
            results.append(("internet_bdc", run_internet_bdc_csv_job()))
        elif name == "fcc_internet":
            from app.utility_providers.fcc_internet_job import run_fcc_internet_cache_job, run_fcc_internet_retry_files
            if args.retry_files is not None and len(args.retry_files) > 0:
                results.append(("fcc_internet", run_fcc_internet_retry_files(args.retry_files)))
            else:
                results.append(("fcc_internet", run_fcc_internet_cache_job(from_state_fips=args.from_state)))
        elif name == "pending_verify":
            from app.utility_providers.pending_provider_verification_job import run_pending_provider_verification_job
            run_pending_provider_verification_job()
            results.append(("pending_verify", {"success": True}))

    # water/internet_bdc have "success"; fcc_internet has "errors" list
    failed = []
    for name, summary in results:
        if summary.get("success") is False:
            failed.append(name)
        elif name == "fcc_internet" and summary.get("errors"):
            failed.append(name)
    if failed:
        print(f"Jobs with errors: {failed}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
