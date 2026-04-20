# Background Jobs: Scheduled vs Trigger-Based

This document lists which jobs are **scheduled** (time-based) vs **trigger-based** (run on demand or when an event occurs). For deployment, time-based jobs are **not** currently scheduled (scheduler is disabled in `app/main.py`).

---

## Summary

| Job | Type | Currently scheduled? | How to run |
|-----|------|----------------------|------------|
| Stay notification (legal warning emails) | Time-based (cron) | **No** | Manually: `POST /notifications/run-stay-warnings` or re-enable scheduler |
| FCC internet cache (county-level) | Time-based (cron) | **No** | Script: `python -m scripts.run_utility_provider_jobs fcc_internet` |
| Water CSV → cache | Time-based (optional) | **No** | Script: `python -m scripts.run_utility_provider_jobs water` |
| Internet BDC CSV → fallback | Time-based (optional) | **No** | Script: `python -m scripts.run_utility_provider_jobs internet_bdc` |
| SDWA water merge | Time-based (optional) | **No** | Script: `python -m scripts.run_sdwa_water_job` (or `run_utility_provider_jobs sdwa_water`) |
| **Provider contact lookup** (SerpApi, etc.) | **Trigger-based** | N/A (runs when triggered) | Triggered when owner saves property/utilities or clicks "Look up contacts" |
| **Pending provider verification** (SerpApi) | **Trigger-based** | N/A (runs when triggered) | Triggered when owner adds custom provider or via script `run_utility_provider_jobs pending_verify` |

---

## Jobs that are NOT scheduled (time-based, intentionally off)

These would run on a schedule if the APScheduler block in `app/main.py` were enabled. It is currently **commented out** so no cron jobs run at startup or on a timer.

1. **Stay notification job**  
   - **Purpose:** Send legal warning emails for stays approaching or past their end date.  
   - **Would run:** Cron at 09:00 daily (when `notification_cron_enabled` is True).  
   - **How to run now:** Call `POST /notifications/run-stay-warnings` (authenticated) or use an external cron/scheduler to hit that endpoint.

2. **FCC internet cache job**  
   - **Purpose:** Populate SQLite `internet_provider_cache` from FCC Location Coverage API (county-level).  
   - **Would run:** Cron 1st of month at 03:00 + once at startup in background.  
   - **How to run now:** `python -m scripts.run_utility_provider_jobs fcc_internet`

3. **Water CSV job**  
   - **Purpose:** Populate `water_provider_cache` from EPA SDWIS-style CSV (e.g. `CSV.csv`).  
   - **How to run now:** `python -m scripts.run_utility_provider_jobs water`

4. **Internet BDC CSV job**  
   - **Purpose:** Populate `internet_bdc_fallback` from BDC provider summary CSV.  
   - **How to run now:** `python -m scripts.run_utility_provider_jobs internet_bdc`

5. **SDWA water job**  
   - **Purpose:** Merge EPA SDWA bulk data into `water_provider_cache` (contact email/phone).  
   - **How to run now:** `python -m scripts.run_sdwa_water_job` or `run_utility_provider_jobs sdwa_water`

---

## Jobs that remain trigger-based (unchanged)

These run when triggered by the API or a manual script; they are **not** time-based.

1. **Provider contact lookup**  
   - **Purpose:** Fetch contact info (e.g. via SerpApi) for property utility providers.  
   - **Trigger:** Owner registers/updates property utilities, or clicks "Look up contacts" on the Utilities tab.  
   - **Code:** `app/services/provider_contact_search.py`; enqueued via `submit_utility_job(run_provider_contact_lookup_job, ...)` in `app/routers/owners.py`.

2. **Pending provider verification**  
   - **Purpose:** Verify user-added (custom) providers via SerpApi; set `verification_status` to approved/rejected.  
   - **Trigger:** Owner adds a provider not in the list, or run manually: `python -m scripts.run_utility_provider_jobs pending_verify`.  
   - **Code:** `app/utility_providers/pending_provider_verification_job.py`; enqueued via `submit_utility_job(run_pending_provider_verification_job)` in `app/routers/owners.py`.

---

## Scheduler status in code

- **File:** `app/main.py`  
- **Status:** The block that creates `BackgroundScheduler`, adds cron jobs (stay notifications, FCC cache), and calls `scheduler.start()` is **commented out**.  
- **Log message at startup:** `Step 3 skipped: background scheduler disabled (cache/utility jobs)`.

No code changes are required to keep time-based jobs unscheduled; they remain off until the scheduler block is re-enabled and deployed.
