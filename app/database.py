"""
Database connection and session.

Schema source of truth: app.models. On startup, Base.metadata.create_all(bind=engine)
creates all tables and columns from the current models. For a fresh database, the full
schema is created in one step; no migration scripts are needed.
"""
import logging
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from app.config import get_settings

logger = logging.getLogger("app.startup")
settings = get_settings()
logger.info("[startup] Database: creating engine")
# connect_timeout avoids hanging startup when PostgreSQL is unreachable (e.g. wrong host or DB down)
_connect_args: dict = {}
_db_url = settings.database_url.strip()
if _db_url.startswith("postgresql"):
    _connect_args["connect_timeout"] = 10
elif _db_url.startswith("sqlite"):
    # Bulk upload and other work runs in a background thread; SQLite default blocks other threads.
    _connect_args["check_same_thread"] = False

_engine_kwargs: dict = {"pool_pre_ping": True, "connect_args": _connect_args}
if _db_url.startswith("postgresql"):
    _engine_kwargs.update(
        {
            "pool_size": int(getattr(settings, "db_pool_size", 5)),
            "max_overflow": int(getattr(settings, "db_max_overflow", 0)),
            "pool_timeout": int(getattr(settings, "db_pool_timeout", 30)),
            "pool_recycle": int(getattr(settings, "db_pool_recycle", 1800)),
        }
    )

engine = create_engine(settings.database_url, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
logger.info("[startup] Database: engine and SessionLocal ready")


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
