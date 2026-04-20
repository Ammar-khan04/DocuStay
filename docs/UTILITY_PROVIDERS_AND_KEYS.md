# Utility Providers & Data Sources – Paid vs Free, API Keys

Single reference for every external service and dataset used in property registration and utility/contact lookup. **Paid** = requires subscription or payment; **Free** = no charge. **API key** = one or more env vars required. **Background job** = scheduled or manual job that fills a cache or table (see **PROPERTY_REGISTRATION_FLOW.md** §6 for how to run).

---

## API keys needed from client

Services for which the client must provide API keys (or credentials):

- **Smarty** (paid) – address validation and standardization  
- **Rewiring America** (paid) – electric and gas provider names by ZIP  
- **FCC Public Data API** (unpaid) – for internet county cache background job (username + token)  
- **SerpApi** (paid; limited free tier) – provider contact email lookup  

No API keys required for: Census Geocoder, EPA ECHO, EPA SDWIS CSV, FCC BDC CSV, water/internet SQLite caches (populated by jobs that use the keys above where applicable), or Playwright.

---

## Utility providers we use (by type)

| Utility type | Source(s) we use | Background job(s) |
|--------------|------------------|-------------------|
| **Address / geography** | Smarty (validation, lat/lon), Census Geocoder (lat/lon → state, county) | — |
| **Electric** | Rewiring America API (by ZIP) | — |
| **Gas** | Rewiring America API (by ZIP) | — |
| **Water** | SQLite `water_provider_cache` (primary at lookup), EPA ECHO API (live), EPA SDWIS CSV (fallback file) | **water_csv_job** (loads CSV → `water_provider_cache`), **sdwa_water_job** (merges SDWA CSV → `water_provider_cache`) |
| **Internet** | SQLite `internet_provider_cache` (county, primary), SQLite `internet_bdc_fallback` (national fallback) | **fcc_internet_job** (FCC API → `internet_provider_cache`), **internet_bdc_csv_job** (BDC CSV → `internet_bdc_fallback`) |
| **Provider contact email** | SerpApi (+ Playwright for 403), water cache (for water) | — (SerpApi runs as a per-request background task after set utilities, not a cache job) |

---

## Summary table (all sources)

| Source | Purpose | Paid? | API key? | Env vars | Background job |
|--------|---------|------|----------|----------|----------------|
| **Smarty US Street API** | Address validation, standardization, lat/lon | **Paid** | Yes | `SMARTY_AUTH_ID`, `SMARTY_AUTH_TOKEN` | — |
| **U.S. Census Geocoder** | lat/lon → state, county (FIPS, names) | Free | No | — | — |
| **Rewiring America API** | Electric + gas provider names by ZIP | **Paid** | Yes | `REWIRING_AMERICA_API_KEY` | — |
| **EPA ECHO SDW API** | Water systems by state/county/city (primary) | Free | No | — | — |
| **EPA SDWIS CSV** | Water fallback when ECHO fails/empty; also input to water cache job | Free | No | Optional `WATER_CSV_PATH` (default `CSV.csv`) | **water_csv_job** (reads this CSV → `water_provider_cache`) |
| **SQLite water_provider_cache** | Water lookup (populated by jobs) | Free | No | Same DB path as internet (see below) | **water_csv_job**, **sdwa_water_job** |
| **SQLite internet_provider_cache** | Internet providers by county (primary) | Free | No | Optional `FCC_INTERNET_CACHE_PATH` | **fcc_internet_job** |
| **SQLite internet_bdc_fallback** | National top-N internet (fallback) | Free | No | Same DB | **internet_bdc_csv_job** |
| **FCC Public Data API** | Download Location Coverage → fill internet cache | Free | Yes | `FCC_BROADBAND_API_USERNAME`, `FCC_PUBLIC_MAP_DATA_APIS` | **fcc_internet_job** (only caller) |
| **FCC BDC CSV** | Internet fallback data; job fills `internet_bdc_fallback` | Free | No | Optional `FCC_BROADBAND_CSV_PATH` | **internet_bdc_csv_job** (reads this CSV) |
| **SerpApi** | Provider contact email lookup (search + snippets/pages) | **Paid** (free tier limited) | Yes | `SERPAPI_KEY` | — |
| **Playwright (Chromium)** | Headless browser when result pages return 403 | Free | No | One-time: `playwright install chromium` | — |

---

## Detail

### Address & geography

- **Smarty** – Required for address verification in add-property flow. [smarty.com](https://www.smarty.com/). Paid; sign up for auth-id and auth-token.
- **Census Geocoder** – Public; no key. Used for water (state/county/city) and internet (county cache key).

### Electric & gas

- **Rewiring America** – Only source for electric and gas names by ZIP. [rewiringamerica.org](https://www.rewiringamerica.org/) / API. Paid; Bearer token in `REWIRING_AMERICA_API_KEY`.

### Water

- **EPA ECHO** – Primary; no key. Water systems by state/county/city.
- **EPA SDWIS CSV** – Fallback file (e.g. `CSV.csv`). No key.
- **water_provider_cache** – SQLite table filled by `water_csv_job` and `sdwa_water_job`; can include contact email/phone from CSV or SDWA data.

### Internet

- **internet_provider_cache** – County-level providers; filled by **FCC Public Data API** job (`fcc_internet_job`). FCC API requires `FCC_BROADBAND_API_USERNAME` (email) and `FCC_PUBLIC_MAP_DATA_APIS` (token). Free; get token at [broadbandmap.fcc.gov](https://broadbandmap.fcc.gov/) → Manage API Access.
- **internet_bdc_fallback** – National top-N from BDC CSV; job `internet_bdc_csv_job`. No API key for the CSV file.

### Provider contact email (electric, gas, internet, and water when missing)

- **SerpApi** – Google search results. Used by the app to find contact emails after saving providers (snippets first, then fetch result pages). On 403, **Playwright** headless Chromium fetches the page. SerpApi: [serpapi.com](https://serpapi.com/); paid with limited free tier. Set `SERPAPI_KEY`. Playwright: free; run `playwright install chromium` once after `pip install -r requirements.txt`.

---

## Optional / not used in current flow

| Source | Note |
|--------|------|
| **Arcadia (Genability)** | Alternative electric/gas by ZIP; 14-day trial then paid. Would use `ARCADIA_APP_ID`, `ARCADIA_APP_KEY`. Not wired in. |
| **UtilityAPI** | For pulling bills after user has an account; not used for provider lookup. `UTILITYAPI_API_KEY` in .env is unused for utilities. |
| **Brave Search API** | Alternative to SerpApi for script `find_provider_email.py`. `BRAVE_SEARCH_API_KEY`; dashboard sometimes unreachable (use SerpApi). |

---

## Running without some keys

- **Smarty:** Required for add-property address verification. Without it, verify-address and property creation will fail.
- **Rewiring America:** Without it, electric and gas options are empty at step 4.
- **FCC username + token:** Needed only to **populate** the internet county cache (background job). Lookup can still use `internet_bdc_fallback` if populated.
- **SERPAPI_KEY:** Optional. Without it, electric/gas/internet providers are saved with no contact email until you add a key and call `POST .../provider-contacts/lookup` or re-save utilities.

See **PROPERTY_REGISTRATION_FLOW.md** §6 for how to run cache population jobs.
