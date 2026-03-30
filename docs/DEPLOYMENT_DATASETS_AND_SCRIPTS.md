# Deployment: Datasets (CSV) and Scripts

## CSV / dataset usage

### 1. `CSV.csv` (project root) — **USED**

- **Used by:**  
  - `app/services/water_lookup.py` (fallback when SQLite cache and EPA ECHO are not used)  
  - `app/utility_providers/water_csv_job.py` (populates `water_provider_cache`)  
- **Config:** `WATER_CSV_PATH` (optional); default = project root `CSV.csv`.

**Columns used (by name; no column-index dependency in code):**

- `pwsid` — required  
- `pwsname` — required  
- `state` — required  
- `status` — required (rows with `status=CLOSED` are skipped)  
- `contactcity` — required for cache/lookup  
- `contactstate` — required  
- `contactphone` — used  
- One of: `contactemail`, `EMAIL_ADDR`, or `email` — used when present (for contact email)

**Columns you can remove to reduce size (unused):**

- `regulatingagencyname`
- `naics`
- `epa_region`
- `geography_type`
- `pwsdeactivationdate`
- `pwstype`
- `psource`
- `psource_longname`
- `owner`
- `sizecat5`
- `retpopsrvd`
- `contact`
- `contactorgname`
- `contactaddress1`
- `contactaddress2`
- `contactzip`

**Safe to delete:** Only the columns listed above. Keep: `pwsid`, `pwsname`, `state`, `status`, `contactcity`, `contactstate`, `contactphone`, and at least one of `contactemail` / `EMAIL_ADDR` / `email` if you want contact email in cache/lookup. All code uses `row.get("column_name")` — no column indices.

---

### 2. `bdc_us_fixed_broadband_provider_summary_J25_17feb2026.csv` — **USED**

- **Used by:**  
  - `app/services/fcc_broadband.py` (aggregate by `holding_company`, top-N providers)  
  - `app/utility_providers/internet_bdc_csv_job.py` (same; writes to `internet_bdc_fallback`)  
- **Config:** `FCC_BROADBAND_CSV_PATH` (optional); default = project root or `data/fcc/` with this filename.  
- **Location:** Project root or `data/fcc/`.

**Columns used (by name only):**

- `holding_company`
- `unit_count_res`
- `unit_count_bus`

**Columns you can remove to reduce size (unused):**

- `provider_id`
- `technology_code`
- `technology_code_desc`
- `location_count_res`
- `location_count_bus`

**Safe to delete:** Only the columns above. Code uses `row.get("...")` only for the three used columns; no column indices.

---

### 3. `data/fcc/bdc_provider_summary_2025-06-30.csv` — **NOT USED**

- **Not referenced** anywhere in the application code.  
- The app looks for filenames like `bdc_us_fixed_broadband_provider_summary_*.csv` (different prefix).  
- The script `scripts/refresh_fcc_csv_from_api.py` *writes* files named `bdc_provider_summary_{date}.csv`; nothing in the app *reads* that pattern.  
- **Safe to delete** this file for deployment to save space.

---

## Scripts kept after cleanup

- **List users in DB:** `scripts/list_user_emails.py` — run: `python scripts/list_user_emails.py`  
- **Background jobs:**  
  - `scripts/run_utility_provider_jobs.py` — run: `python -m scripts.run_utility_provider_jobs [all|water|internet_bdc|fcc_internet|sdwa_water|pending_verify]`  
  - `scripts/run_sdwa_water_job.py` — run: `python -m scripts.run_sdwa_water_job` (SDWA water merge into cache)

All other scripts under `scripts/` (migrations, tests, seeds, delete/check helpers, etc.) have been removed for deployment; schema is built from `app.models` via `Base.metadata.create_all()` on a fresh DB.
