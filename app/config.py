"""Application configuration from environment."""
from pathlib import Path

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings
from functools import lru_cache

# Load .env from project root (parent of app/) so env vars are available everywhere
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)


class Settings(BaseSettings):
    app_name: str = "DocuStay Demo"
    app_env: str = "development"
    debug: bool = True
    secret_key: str = "change-me"

    database_url: str = "postgresql://postgres:postgres@localhost:5432/docustay_demo"
    # SQLAlchemy QueuePool: pool_size permanent slots + max_overflow extra under burst.
    # Defaults stay small so one API process fits Supabase direct-connection limits; parallel dashboard
    # requests may queue briefly under load. Raise DB_POOL_SIZE / DB_MAX_OVERFLOW for local Postgres or pooler URLs.
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout: int = 30
    # Stale TLS sockets → psycopg2 "SSL SYSCALL error: EOF detected". Cloud poolers often idle-out
    # well before 30m; 300s recycle is a safe default (raise locally if you want less churn).
    db_pool_recycle: int = 300  # seconds; env: DB_POOL_RECYCLE
    # Supabase Session pooler (pooler.*.supabase.com:5432) enforces MaxClientsInSessionMode.
    # When True, the engine auto-caps pool_size / max_overflow for that URL pattern.
    # Prefer Transaction pooler (port 6543) or direct Postgres for higher concurrency. Env: DB_SUPABASE_SESSION_POOLER_CAP
    db_supabase_session_pooler_cap: bool = True

    jwt_secret_key: str = "jwt-secret-change-me"
    jwt_algorithm: str = "HS256"

    @field_validator("jwt_secret_key")
    @classmethod
    def strip_jwt_secret(cls, v: str) -> str:
        return (v or "").strip()

    jwt_access_token_expire_minutes: int = 60
    # Pending-owner signup flow (email verified → identity → POA) can take a while; use longer expiry
    jwt_pending_owner_expire_minutes: int = 60 * 24  # 24 hours

    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "noreply@docustay.demo"
    sendgrid_from_name: str = "DocuStay"

    mailgun_api_key: str = ""
    mailgun_domain: str = ""
    mailgun_base_url: str = "https://api.mailgun.net"
    mailgun_from_email: str = "noreply@docustay.demo"
    mailgun_from_name: str = "DocuStay"

    @field_validator("mailgun_api_key", "mailgun_domain", "mailgun_base_url", "mailgun_from_email", mode="before")
    @classmethod
    def strip_mailgun(cls, v: str) -> str:
        return (v or "").strip()

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_phone_number: str = ""

    dropbox_sign_api_key: str = ""
    dropbox_sign_client_id: str = ""

    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_identity_flow_id: str = ""
    stripe_identity_flow_id_manager: str = ""  # Property manager Stripe Identity flow (optional; falls back to stripe_identity_flow_id)
    stripe_identity_return_url: str = ""
    stripe_webhook_secret: str = ""  # Webhook signing secret (whsec_...) for billing events
    # When True, do not self-heal onboarding_invoice_paid_at when listing billing (so you can re-test payment flow after running set_onboarding_invoice_unpaid.py)
    stripe_skip_onboarding_self_heal: bool = False

    notification_days_before_limit: int = 5
    notification_cron_enabled: bool = True
    # Calendar-only rules for guest stay end reminders (stay dates are date fields, no time-of-day). Cron uses this IANA zone when the client does not send X-Client-Calendar-Date. Env: NOTIFICATION_CALENDAR_IANA_TZ
    notification_calendar_iana_tz: str = "America/Chicago"
    # Dead Man's Switch test mode: when True, DMS uses effective "lease end" = check-in (or stay created_at) + 2 minutes;
    # Status Confirmation test mode: when True, effective "lease end" = check-in (or stay created_at) + 2 minutes;
    # occupancy becomes Unknown only after 5 minutes from the latest Status Confirmation notification (in-app alert or audit log).
    dms_test_mode: bool = False
    # When True, pending invitation links expire after 5 minutes; otherwise 12 hours. Cleanup job runs every minute in test mode.
    test_mode: bool = False
    # Vacant-unit monitoring: prompt interval (days) and response deadline (days after each prompt)
    vacant_monitoring_interval_days: int = 7
    vacant_monitoring_response_days: int = 7

    # Smarty US Street API (address standardization / ZIP-code utility bucket)
    smarty_auth_id: str = ""
    smarty_auth_token: str = ""
    smarty_api_name: str = ""

    @field_validator("smarty_auth_id", "smarty_auth_token", "smarty_api_name", mode="before")
    @classmethod
    def strip_smarty(cls, v: str) -> str:
        return (v or "").strip()

    # Utility Bucket: Rewiring America, Water CSV, FCC BDC CSV (see docs/UTILITY_BUCKET.md)
    rewiring_america_api_key: str = ""  # Electric + gas by ZIP
    water_csv_path: str = ""  # EPA SDWIS CSV (e.g. CSV.csv); empty = project root CSV.csv
    water_sdwa_csv_path: str = ""  # EPA SDWA bulk: path to SDWA_PUB_WATER_SYSTEMS.csv or folder (e.g. SDWA_latest_downloads); empty = auto-detect
    fcc_broadband_csv_path: str = ""  # BDC provider summary CSV; empty = auto-detect in project root or data/fcc/
    # FCC National Broadband Map Public Data API (location-based internet; optional)
    fcc_broadband_api_username: str = ""  # FCC login email (e.g. from broadbandmap.fcc.gov)
    fcc_public_map_data_apis: str = ""  # API token from Manage API Access
    # SQLite cache for county-level internet providers (FCC Location Coverage); populated by background job
    fcc_internet_cache_path: str = ""  # e.g. data/utility_providers/internet_cache.db; empty = default under project root
    # Reserved for future use (e.g. bill fetch): utilityapi_api_key
    utilityapi_api_key: str = ""
    # Provider contact lookup (SerpApi): find contact email for electric/gas/internet providers in background
    serpapi_key: str = ""
    # Max concurrent utility background jobs (provider contact lookup, pending verification); excess jobs are queued
    utility_background_jobs_max_workers: int = 2
    # Development: email for "Test provider" shown per utility type (frontend-only); emails to providers can be sent here
    test_provider_email: str = ""
    # Base URL of the frontend app (for provider authority letter links in emails), e.g. https://app.docustay.com
    frontend_base_url: str = ""

    @field_validator("rewiring_america_api_key", "water_csv_path", "water_sdwa_csv_path", "fcc_broadband_csv_path", "fcc_broadband_api_username", "fcc_public_map_data_apis", "fcc_internet_cache_path", "utilityapi_api_key", "serpapi_key", "test_provider_email", "frontend_base_url", mode="before")
    @classmethod
    def strip_utility(cls, v: str) -> str:
        return (v or "").strip()

    class Config:
        env_file = str(_env_path)
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
