# Utility Provider APIs and Datasets – Technical Reference

This document is the **technical reference** for every external API and dataset used for utility provider lookup and address handling: request/response, modules, config.

- **Property registration flow, background jobs (how to run), provider contact flow and policy:** **docs/PROPERTY_REGISTRATION_FLOW.md**
- **Paid vs free, API keys, env vars:** **docs/UTILITY_PROVIDERS_AND_KEYS.md**

**Pipeline overview:** Address → **Smarty** (lat/lon) → **Census Geocoder** (state, county) → **Rewiring America** (electric/gas), **EPA** (water), **FCC** (internet). Water and internet use SQLite caches populated by background jobs; see PROPERTY_REGISTRATION_FLOW.md §6 for job commands and env vars.

---

## 1. Address standardization: Smarty US Street API

| | |
|--|--|
| **Type** | REST API |
| **Used for** | Standardize and validate US address; get lat/lon and ZIP for downstream lookups |
| **Module** | `app.services.smarty` |
| **Config** | `SMARTY_AUTH_ID`, `SMARTY_AUTH_TOKEN` (required for address verification) |

### Request

- **URL:** `GET https://us-street.api.smarty.com/street-address`
- **Auth:** Query params `auth-id` and `auth-token`
- **Query parameters:**
  - `street` – street address line
  - `city` – city
  - `state` – state (abbreviation)
  - `zipcode` – optional; if provided, 5-digit ZIP only
  - `candidates` – we send `1` (single best match)

### Response

- **Format:** JSON array of candidate objects
- **We use first candidate:** `delivery_line_1`, `components.city_name`, `components.state_abbreviation`, `components.zipcode`, `components.plus4_code`, `metadata.latitude`, `metadata.longitude`
- **App model:** `SmartyAddressResult(delivery_line_1, city_name, state_abbreviation, zipcode, plus4_code, latitude, longitude)`  
- On no match, error, or missing credentials we return `None` and do not call downstream utilities.

---

## 2. Geocoding: U.S. Census Bureau Geocoder API

| | |
|--|--|
| **Type** | REST API (no key) |
| **Used for** | Convert lat/lon → state and county (name + FIPS) for water and internet |
| **Module** | `app.services.census_geocoder` |
| **Config** | None |

### Request

- **URL:** `GET https://geocoding.geo.census.gov/geocoder/geographies/coordinates`
- **Query parameters:**
  - `x` – longitude
  - `y` – latitude
  - `benchmark=Public_AR_Current`
  - `vintage=Current_Current`
  - `format=json`

### Response

- **Format:** JSON with `result.geographies.States` and `result.geographies.Counties`
- **We use:** First state’s `STATE` (FIPS) and `STUSAB` (abbrev); first county’s `NAME` and `COUNTY` (county FIPS, 3-digit)
- **App model:** `CensusGeography(state_fips, state_abbreviation, county_name, county_fips)`  
- Used in utility lookup to get `state_abbrev`, `county_name`, `state_fips`, `county_fips` for water (state/county/city) and internet (county cache key or fallback).

---

## 3. Electric and gas: Rewiring America API

| | |
|--|--|
| **Type** | REST API |
| **Used for** | Electric and gas utility names by ZIP (and optionally address) |
| **Module** | `app.services.utility_lookup` (`_fetch_rewiring_america`) |
| **Config** | `REWIRING_AMERICA_API_KEY` |

### Request

- **URL:** `GET https://api.rewiringamerica.org/api/v1/utilities`
- **Headers:** `Authorization: Bearer <REWIRING_AMERICA_API_KEY>`
- **Query parameters:**
  - `zip` – 5-digit ZIP (required)
  - `address` – optional; we pass when available for better matching

### Response

- **Format:** JSON with keys `utilities` (electric) and `gas_utilities`. Each may be a list or dict of items.
- **We use:** Each item’s `name` or `utility_name` or `label`; we normalize to `{ "name", "type": "electric"|"gas", "raw" }` and then to `UtilityProvider`.

---

## 4. Water: EPA ECHO Safe Drinking Water API (primary)

| | |
|--|--|
| **Type** | REST API (no key) |
| **Used for** | Water systems by state and optionally county/city |
| **Module** | `app.services.epa_echo_water` |
| **Config** | None |

### Request (step 1 – get query ID)

- **URL:** `GET https://echodata.epa.gov/echo/sdw_rest_services.get_systems`
- **Query parameters:**
  - `p_st` – state abbreviation (2-letter)
  - `p_cty` – optional county name
  - `p_city` – optional city name
  - `output=JSON`

### Response (step 1)

- **Format:** JSON with `Results.QueryID` and `Results.QueryRows`
- We use `QueryID` to fetch pages of results.

### Request (step 2 – get water systems)

- **URL:** `GET https://echodata.epa.gov/echo/sdw_rest_services.get_qid`
- **Query parameters:** `qid`, `pageno`, `output=JSON`

### Response (step 2)

- **Format:** JSON with `Results.WaterSystems` (array of objects)
- **We use:** `PWSName`, `CitiesServed`, `StateCode`; ECHO does **not** expose contact phone in this endpoint, so we set `contact_phone: None`. We normalize to `{ name, contact_phone, contact_city, contact_state, raw }` for drop-in use with the CSV fallback path.

---

## 5. Water: EPA SDWIS CSV (fallback dataset)

| | |
|--|--|
| **Type** | Local CSV dataset |
| **Used for** | Water systems when EPA ECHO fails or returns no results |
| **Module** | `app.services.water_lookup` |
| **Config** | Optional `water_csv_path` in lookup; default file: `CSV.csv` in project root |

### Dataset

- **File:** e.g. `CSV.csv` (SDWIS export). Path can be overridden per call.
- **Columns we use:** `pwsid`, `pwsname`, `state`, `contactcity`, `contactstate`, `contactphone`, `status`
- **Filter:** We skip rows with `status == "CLOSED"`.
- **Lookup:** By normalized `contactstate` (and optionally city/county). We return same shape as ECHO: `{ name, contact_phone, contact_city, contact_state, raw }` so callers see a single contract.

---

## 6. Internet: SQLite county cache (primary)

| | |
|--|--|
| **Type** | Local SQLite database (no external request at lookup time) |
| **Used for** | County-level internet provider names for target states (FL, CA, TX, NY) |
| **Module** | `app.utility_providers.sqlite_cache` |
| **Config** | `FCC_INTERNET_CACHE_PATH` (optional; default `data/utility_providers/internet_cache.db`) |

### Schema

- **Table:** `internet_provider_cache`  
  Columns: `state_fips`, `county_fips`, `provider_name`, `as_of_date`, `updated_at`  
  PK: `(state_fips, county_fips, provider_name)`
- **Lookup key:** `(state_fips, county_fips)` from Census (2-digit state FIPS + 3-digit county FIPS)
- **Behavior:** If the key is in cache we return the list of provider names and **do not call any FCC API** during the request. On cache miss we fall back to the BDC CSV and may enqueue the county for the next background refresh (`pending_county_refresh` table).

**Population:** A background job (see §8) downloads FCC Location Coverage data per state and writes county-aggregated providers into this table. Job runs monthly and once at startup.

---

## 7. Internet: FCC BDC provider summary CSV (fallback dataset)

| | |
|--|--|
| **Type** | Local CSV dataset |
| **Used for** | National top-N internet providers when county is not in SQLite cache (or state not in target list) |
| **Module** | `app.services.fcc_broadband` |
| **Config** | `FCC_BROADBAND_CSV_PATH` (optional; default: look for `bdc_us_fixed_broadband_provider_summary_J25_17feb2026.csv` in project root or `data/fcc/`) |

### Dataset

- **File:** BDC fixed broadband provider summary CSV (e.g. J25 = June 2025); updated periodically by FCC.
- **Columns we use:** `holding_company`, `unit_count_res`, `unit_count_bus`
- **Logic:** We aggregate by `holding_company` (sum of residential + business units), sort by total, and return top 10. No FCC API is called during the request.

---

## 8. Internet: FCC Public Data API (background job only)

| | |
|--|--|
| **Type** | REST API (used only by the cache population job, not during user requests) |
| **Used for** | Download Location Coverage (Fixed Broadband) by state → aggregate by county → fill SQLite cache |
| **Module** | `app.utility_providers.fcc_internet_job` |
| **Config** | `FCC_BROADBAND_API_USERNAME`, `FCC_PUBLIC_MAP_DATA_APIS` |

### Request flow (job)

1. **List as-of dates:** `GET https://broadbandmap.fcc.gov/api/public/map/listAsOfDates`  
   Headers: `username`, `hash_value`, `user-agent`  
   Response: list of `as_of_date` for `data_type=availability`; we take the latest.

2. **List state files:** `GET https://broadbandmap.fcc.gov/api/public/map/downloads/listAvailabilityData/{as_of_date}`  
   Params: `category=State`, `subcategory=Location Coverage`, `technology_type=Fixed Broadband`  
   Response: list of files per state; we filter by target state name (Florida, California, Texas, New York).

3. **Download file:** `GET https://broadbandmap.fcc.gov/api/public/map/downloads/downloadFile/availability/{file_id}`  
   Response: ZIP containing CSV with columns including `block_geoid`, `brand_name`. We use first 5 chars of `block_geoid` as state FIPS (2) + county FIPS (3), aggregate unique `brand_name` per county, then upsert into `internet_provider_cache`.

### Response (per file)

- ZIP → CSV rows. No per-request API call is made for internet during registration; lookup uses only SQLite cache or BDC CSV fallback.

---

## Summary table

| Purpose | Type | Request / Input | Response / Output | Called during user request? |
|--------|------|------------------|-------------------|-----------------------------|
| Address standardization | API | GET Smarty US Street (street, city, state, zipcode) | Standardized address + lat/lon | Yes |
| Geocoding | API | GET Census coordinates (x=lon, y=lat) | state_fips, state_abbrev, county_name, county_fips | Yes |
| Electric + gas | API | GET Rewiring America /utilities (zip, optional address) | utilities, gas_utilities lists | Yes |
| Water (primary) | API | GET EPA ECHO get_systems → get_qid (state, optional county/city) | WaterSystems: PWSName, etc. | Yes |
| Water (fallback) | Dataset | CSV path; filter by state/city/county | Rows with pwsname, contactphone, etc. | Yes (if ECHO fails/empty) |
| Internet (primary) | Local DB | SQLite lookup by (state_fips, county_fips) | List of provider names | Yes (no FCC call) |
| Internet (fallback) | Dataset | BDC CSV path; aggregate by holding_company | Top 10 providers | Yes (no FCC call) |
| Internet cache fill | API | FCC listAsOfDates → listAvailabilityData → downloadFile (per state) | ZIP/CSV → county-level providers written to SQLite | No (background job only) |

---

## Env vars reference

| Variable | Used by | Required for |
|----------|--------|---------------|
| `SMARTY_AUTH_ID`, `SMARTY_AUTH_TOKEN` | Smarty | Address verification |
| `REWIRING_AMERICA_API_KEY` | Rewiring America | Electric + gas |
| `WATER_CSV_PATH` | water_csv_job, water_lookup | Water fallback CSV (optional; default project root `CSV.csv`) |
| `FCC_BROADBAND_CSV_PATH` | fcc_broadband, internet_bdc_csv_job | Internet fallback CSV (optional; has default path) |
| `FCC_INTERNET_CACHE_PATH` | sqlite_cache | All utility cache tables (optional; default `data/utility_providers/internet_cache.db`) |
| `FCC_BROADBAND_API_USERNAME`, `FCC_PUBLIC_MAP_DATA_APIS` | fcc_internet_job | Populating internet county cache (background job) |

EPA ECHO and Census Geocoder do not require any API keys.
