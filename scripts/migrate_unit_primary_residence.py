#!/usr/bin/env python3
"""Add is_primary_residence column to units table if it does not exist.
Works with both SQLite and PostgreSQL (uses app database URL)."""
import os
import sys

# Add project root so app imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from app.config import get_settings


def column_exists(conn, dialect_name: str) -> bool:
    if dialect_name == "sqlite":
        r = conn.execute(text("PRAGMA table_info(units)"))
        return any(row[1] == "is_primary_residence" for row in r.fetchall())
    if dialect_name == "postgresql":
        r = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'units' AND column_name = 'is_primary_residence'"
            )
        )
        return r.fetchone() is not None
    return False


def migrate():
    settings = get_settings()
    engine = create_engine(settings.database_url)
    dialect_name = engine.dialect.name

    with engine.connect() as conn:
        if column_exists(conn, dialect_name):
            print("is_primary_residence already exists in units table.")
            return
        # ADD COLUMN: INTEGER NOT NULL DEFAULT 0 works on both SQLite and PostgreSQL
        conn.execute(text("ALTER TABLE units ADD COLUMN is_primary_residence INTEGER NOT NULL DEFAULT 0"))
        conn.commit()
    print("Added is_primary_residence to units table.")


if __name__ == "__main__":
    migrate()
