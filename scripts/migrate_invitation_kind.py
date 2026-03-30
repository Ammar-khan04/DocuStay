#!/usr/bin/env python3
"""Add invitation_kind column to invitations table if it does not exist.
Backfill: tenant where token_state='BURNED' and unit_id IS NOT NULL, else guest.
Works with both SQLite and PostgreSQL."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from app.config import get_settings


def column_exists(conn, dialect_name: str) -> bool:
    if dialect_name == "sqlite":
        r = conn.execute(text("PRAGMA table_info(invitations)"))
        return any(row[1] == "invitation_kind" for row in r.fetchall())
    if dialect_name == "postgresql":
        r = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'invitations' AND column_name = 'invitation_kind'"
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
            print("invitation_kind already exists in invitations table.")
            return
        conn.execute(
            text("ALTER TABLE invitations ADD COLUMN invitation_kind VARCHAR(20) NOT NULL DEFAULT 'guest'")
        )
        conn.commit()

        # Backfill: tenant where token_state='BURNED' and unit_id IS NOT NULL
        conn.execute(
            text(
                "UPDATE invitations SET invitation_kind = 'tenant' "
                "WHERE UPPER(TRIM(COALESCE(token_state, ''))) = 'BURNED' AND unit_id IS NOT NULL"
            )
        )
        conn.commit()
    print("Added invitation_kind to invitations and backfilled (tenant/guest).")


if __name__ == "__main__":
    migrate()
