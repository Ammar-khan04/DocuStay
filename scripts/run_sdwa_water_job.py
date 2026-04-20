"""
Run the SDWA water provider job: load EPA SDWA_PUB_WATER_SYSTEMS.csv (local or download),
merge into SQLite water_provider_cache (add new providers, update existing by PWSID).
Contact email and phone are extracted and stored.

Usage:
  python -m scripts.run_sdwa_water_job                    # use local CSV (SDWA_latest_downloads or WATER_SDWA_CSV_PATH)
  python -m scripts.run_sdwa_water_job --download        # download zip from EPA if local not found
  python -m scripts.run_sdwa_water_job --csv path/to/SDWA_PUB_WATER_SYSTEMS.csv
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    import argparse
    parser = argparse.ArgumentParser(description="Run SDWA water job (merge contact info into water_provider_cache)")
    parser.add_argument("--download", action="store_true", help="Download EPA zip if local CSV not found")
    parser.add_argument("--csv", type=str, default=None, help="Path to SDWA_PUB_WATER_SYSTEMS.csv or folder")
    args = parser.parse_args()

    from app.utility_providers.sdwa_water_job import run_sdwa_water_job

    result = run_sdwa_water_job(
        use_local_only=not args.download,
        local_csv_path=args.csv,
    )
    print("Result:", result)
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
