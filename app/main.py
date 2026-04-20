"""DocuStay Demo – FastAPI application."""
import logging
from pathlib import Path

# Load .env before any app code that might read config
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError as SQLOperationalError

from app.config import get_settings
from app.database import Base, engine
# Import models so Base.metadata has all tables before create_all (schema source of truth)
from app.models import (  # noqa: F401
    User, OwnerProfile, Property, GuestProfile, Stay, RegionRule,
    Jurisdiction, JurisdictionStatute, JurisdictionZipMapping,
    Invitation, GuestPendingInvite, AgreementSignature, ReferenceOption,
    AuditLog, EventLedger, OwnerPOASignature, PendingRegistration,
    PropertyUtilityProvider, PropertyAuthorityLetter,
    Unit, PropertyManagerAssignment, TenantAssignment, ResidentMode, ResidentPresence,
    StayPresence, PresenceAwayPeriod,
    ManagerInvitation, PropertyTransferInvitation, DashboardAlert, NotificationAttempt,
    BulkUploadJob, GuestExtensionRequest,
    DemoAccount,
)
from app.routers import auth, identity, owners, guests, stays, region_rules, jle, dashboard, notifications, agreements, billing_webhook, public, admin, managers

logger = logging.getLogger("app.startup")
settings = get_settings()
logger.info("[startup] Config loaded: app_name=%s debug=%s", settings.app_name, settings.debug)

app = FastAPI(title=settings.app_name, debug=settings.debug)
logger.info("[startup] FastAPI app created")


@app.exception_handler(SQLOperationalError)
def db_operational_error_handler(_request: Request, exc: SQLOperationalError) -> JSONResponse:
    """Return 503 when DB is unreachable (e.g. DNS failure, connection refused)."""
    logger.warning("Database operational error: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "Service temporarily unavailable. Please check your connection and try again."},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("[startup] CORS middleware added")

app.include_router(auth.router)
app.include_router(identity.router)
app.include_router(owners.router)
app.include_router(guests.router)
app.include_router(stays.router)
app.include_router(region_rules.router)
app.include_router(jle.router)
app.include_router(dashboard.router)
app.include_router(notifications.router)
app.include_router(agreements.router)
app.include_router(billing_webhook.router)
app.include_router(public.router)
app.include_router(admin.router)
app.include_router(managers.router)
logger.info("[startup] Routers registered (auth, identity, owners, guests, stays, region_rules, jle, dashboard, notifications, agreements, billing_webhook, public, admin, managers)")


@app.on_event("startup")
def startup():
    logger.info("[startup] ---------- Startup begin ----------")
    # Mailgun
    logger.info("[startup] Step 1: Mailgun / email config")
    if settings.mailgun_api_key and settings.mailgun_domain:
        from_addr = getattr(settings, "mailgun_from_email", "") or ""
        from_domain = from_addr.split("@")[-1].lower() if "@" in from_addr else ""
        send_domain = (settings.mailgun_domain or "").strip().lower()
        if from_domain and send_domain and from_domain != send_domain:
            print(f"[Mailgun] WARNING: from={from_addr} does not match domain={settings.mailgun_domain}. Emails may not be delivered!")
            print(f"[Mailgun] Fix: in .env set MAILGUN_FROM_EMAIL=noreply@{settings.mailgun_domain} then restart")
        else:
            print(f"[Mailgun] App using domain={settings.mailgun_domain} from={from_addr or '(none)'} (verification & all emails use this)")
        logger.info("[startup] Mailgun configured: domain=%s", settings.mailgun_domain)
    else:
        print("[Mailgun] Not configured - verification emails will be skipped; set MAILGUN_API_KEY and MAILGUN_DOMAIN in .env and restart")
        logger.info("[startup] Mailgun not configured (verification emails skipped)")

    # Database
    logger.info("[startup] Step 2: Database (create tables, seed region rules)")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("[startup] Database tables created/verified")
        from app.database import SessionLocal
        from app.seed import seed_region_rules, seed_jurisdiction_sot, seed_admin_user
        db = SessionLocal()
        try:
            seed_region_rules(db)
            seed_jurisdiction_sot(db)
            seed_admin_user(db)
            logger.info("[startup] Region rules, jurisdiction SOT, and admin user seeded")
        finally:
            db.close()
        logger.info("[startup] Step 2 done: database OK")
    except Exception as e:
        logger.warning("[startup] Database startup failed (tables/seed skipped). Check DATABASE_URL and network. Error: %s", e)

    # Scheduler: (1) invite-expire job (hourly, or every minute when TEST_MODE=true), (2) DMS 2-min-after-accept when DMS_TEST_MODE=true
    # Scheduler: (1) invite-expire job (hourly, or every minute when TEST_MODE=true), (2) Status Confirmation 2-min-after-checkin when DMS_TEST_MODE=true
    # logger.info("[startup] Step 3: Background scheduler (invitation expire; DMS 2-min from accept_invite when test mode)")
    logger.info("[startup] Step 3: Background scheduler (invitation expire; Status Confirmation 2-min from check-in when test mode)")
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from app.services.invitation_cleanup import run_all_invitation_cleanup_jobs

        scheduler = BackgroundScheduler()
        # Guest / manager / transfer invitation expiry in one DB session (fewer pool checkouts on Supabase Session pooler).
        if getattr(settings, "test_mode", False):
            scheduler.add_job(run_all_invitation_cleanup_jobs, "cron", minute="*")  # every minute when test_mode
            logger.info("[startup] Scheduler: invitation cleanup jobs added (every minute, test_mode)")
        else:
            scheduler.add_job(run_all_invitation_cleanup_jobs, "cron", minute=0)  # every hour at :00
            logger.info("[startup] Scheduler: invitation cleanup jobs added (cron every hour at :00)")
        if getattr(settings, "dms_test_mode", False):
            from app.services.stay_timer import run_dms_test_mode_catchup_job
            # every minute: turn DMS on for stays that checked in >2 min ago (legacy comment; same job as below)
            scheduler.add_job(run_dms_test_mode_catchup_job, "cron", minute="*")  # every minute: turn stay reminders on for stays that checked in >2 min ago
            # logger.info("[startup] Scheduler: DMS test-mode catchup job added (every minute)")
            logger.info("[startup] Scheduler: Status Confirmation test-mode catchup job added (every minute)")
        scheduler.start()
        app.state.scheduler = scheduler
        logger.info("[startup] Step 3 done: scheduler started")
    except Exception as e:
        logger.warning("[startup] Scheduler failed to start: %s", e)
        app.state.scheduler = None

    logger.info("[startup] ---------- Startup complete ----------")


@app.get("/")
def root():
    return {"app": settings.app_name, "status": "ok"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/db-setup")
def db_setup():
    """Dev/demo only: create tables and seed region rules if DB is now available."""
    import logging
    from fastapi.responses import JSONResponse
    log = logging.getLogger("uvicorn.error")
    try:
        Base.metadata.create_all(bind=engine)
        from app.database import SessionLocal
        from app.seed import seed_region_rules, seed_jurisdiction_sot
        db = SessionLocal()
        try:
            seed_region_rules(db)
            seed_jurisdiction_sot(db)
        finally:
            db.close()
        return {"status": "ok", "message": "Tables created and region rules + jurisdiction SOT seeded."}
    except Exception as e:
        log.exception("db-setup failed")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )
