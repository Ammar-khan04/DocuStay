"""
Database connection and session.

Schema source of truth: app.models. On startup, Base.metadata.create_all(bind=engine)
creates all tables and columns from the current models. For a fresh database, the full
schema is created in one step; no migration scripts are needed.

PostgreSQL pool sizing comes from Settings (``db_pool_size``, ``db_max_overflow``); defaults
are conservative for hosted Postgres (e.g. Supabase direct connections). Tune via env if needed.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool
from fastapi import HTTPException
from app.config import get_settings

logger = logging.getLogger("app.startup")
settings = get_settings()
logger.info("[startup] Database: creating engine")


def _normalize_url_for_parse(url: str) -> str:
    u = url.strip()
    if u.startswith("postgresql+psycopg2://"):
        return "postgresql://" + u[len("postgresql+psycopg2://") :]
    if u.startswith("postgres://"):
        return "postgresql://" + u[len("postgres://") :]
    return u


def is_supabase_session_mode_pooler(url: str) -> bool:
    """True when URL targets Supabase Session pooler (port 5432). Transaction mode uses 6543."""
    try:
        parsed = urlparse(_normalize_url_for_parse(url))
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if "pooler.supabase.com" not in host:
        return False
    port = parsed.port or 5432
    return port == 5432


# connect_timeout avoids hanging startup when PostgreSQL is unreachable (e.g. wrong host or DB down)
_connect_args: dict = {}
_db_url = settings.database_url.strip()
if _db_url.startswith("postgresql"):
    _connect_args["connect_timeout"] = 10
    # TCP keepalives: fewer idle disconnects through NAT / VPN / cloud load balancers.
    _connect_args.update(
        {
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        }
    )
elif _db_url.startswith("sqlite"):
    # Bulk upload and other work runs in a background thread; SQLite default blocks other threads.
    _connect_args["check_same_thread"] = False

_engine_kwargs: dict = {
    "pool_pre_ping": True,
    "pool_reset_on_return": "rollback",
    "connect_args": _connect_args,
}
if _db_url.startswith("postgresql"):
    _pool_size = int(getattr(settings, "db_pool_size", 5))
    _max_overflow = int(getattr(settings, "db_max_overflow", 5))
    _pool_timeout = int(getattr(settings, "db_pool_timeout", 30))
    _pool_recycle = int(getattr(settings, "db_pool_recycle", 300))
    if getattr(settings, "db_supabase_session_pooler_cap", True) and is_supabase_session_mode_pooler(
        _db_url
    ):
        # Session pooler: each pooled client holds a dedicated server session; stay within MaxClientsInSessionMode.
        # 3+2 lets the dashboard issue several parallel requests; background jobs use a separate NullPool engine
        # so they do not block waiting for these slots (see SessionLocalBackground below).
        _pool_size = min(_pool_size, 3)
        _max_overflow = min(_max_overflow, 2)
        _pool_recycle = min(_pool_recycle, 120)
        logger.info(
            "[startup] Database: Supabase Session pooler host detected — using pool_size=%s max_overflow=%s "
            "pool_recycle=%ss. For more connections use Transaction pool (port 6543) or direct Postgres; "
            "set DB_SUPABASE_SESSION_POOLER_CAP=false to disable this cap.",
            _pool_size,
            _max_overflow,
            _pool_recycle,
        )
    _engine_kwargs.update(
        {
            "pool_size": _pool_size,
            "max_overflow": _max_overflow,
            "pool_timeout": _pool_timeout,
            "pool_recycle": _pool_recycle,
        }
    )

engine = create_engine(settings.database_url, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Second engine for APScheduler (and similar): avoids QueuePool starvation when HTTP holds all slots.
_use_background_null_pool = (
    _db_url.startswith("postgresql")
    and getattr(settings, "db_supabase_session_pooler_cap", True)
    and is_supabase_session_mode_pooler(_db_url)
)
if _use_background_null_pool:
    _background_engine = create_engine(
        settings.database_url,
        poolclass=NullPool,
        pool_pre_ping=True,
        pool_reset_on_return="rollback",
        connect_args=_connect_args,
    )
    SessionLocalBackground = sessionmaker(autocommit=False, autoflush=False, bind=_background_engine)
    logger.info(
        "[startup] Database: background jobs use NullPool engine (no QueuePool wait; one connection per job run)"
    )
else:
    SessionLocalBackground = None

if _db_url.startswith("postgresql"):
    logger.info(
        "[startup] Database: pool_size=%s max_overflow=%s pool_recycle=%ss",
        _engine_kwargs.get("pool_size"),
        _engine_kwargs.get("max_overflow"),
        _engine_kwargs.get("pool_recycle"),
    )
logger.info("[startup] Database: engine and SessionLocal ready")


def get_background_job_session() -> Session:
    """Session for cron/background work. On Supabase Session pooler, uses NullPool so jobs do not wait on HTTP's QueuePool."""
    factory = SessionLocalBackground or SessionLocal
    return factory()


def get_db():
    try:
        db = SessionLocal()
    except Exception as e:
        logger.exception("Database session creation failed: %s", e)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from e
    try:
        yield db
    finally:
        db.close()
