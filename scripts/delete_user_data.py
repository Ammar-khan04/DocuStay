#!/usr/bin/env python3
"""Delete all data related to one or more user emails.

Covers: owner, tenant, manager, guest roles and related tables (properties,
units, stays, invitations, event ledger, audit logs, dashboard alerts, etc.).

Usage:
  python scripts/delete_user_data.py email1@example.com email2@example.com
  python scripts/delete_user_data.py --dry-run email@example.com   # preview only
  python scripts/delete_user_data.py -y email@example.com         # skip confirmation
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine


def _ids_from_row(row) -> list:
    """Extract list of IDs from array_agg result (handles NULL/empty)."""
    if not row or row[0] is None:
        return []
    arr = row[0]
    if isinstance(arr, list):
        return arr
    if isinstance(arr, (int, float)):
        return [int(arr)]
    return list(arr)


def get_ids(conn, emails: list[str]) -> dict:
    """Resolve user_ids and derived IDs for the given emails."""
    row = conn.execute(text("SELECT array_agg(id) FROM users WHERE lower(trim(email)) = ANY(:emails)"), {"emails": emails}).fetchone()
    user_ids = _ids_from_row(row)

    if not user_ids:
        return {"user_ids": [], "owner_profile_ids": [], "property_ids": [], "unit_ids": [], "stay_ids": [], "invitation_ids": []}

    row = conn.execute(text("SELECT array_agg(id) FROM owner_profiles WHERE user_id = ANY(:ids)"), {"ids": user_ids}).fetchone()
    owner_profile_ids = _ids_from_row(row)

    row = conn.execute(
        text("SELECT array_agg(id) FROM properties WHERE owner_profile_id = ANY(:ids)"),
        {"ids": owner_profile_ids or [0]},
    ).fetchone()
    property_ids = _ids_from_row(row)

    row = conn.execute(
        text("SELECT array_agg(id) FROM units WHERE property_id = ANY(:ids)"),
        {"ids": property_ids or [0]},
    ).fetchone()
    unit_ids = _ids_from_row(row)

    row = conn.execute(
        text(
            """
            SELECT COALESCE(array_agg(DISTINCT sid), ARRAY[]::integer[])
            FROM (
              SELECT s.id AS sid FROM stays s
              WHERE s.guest_id = ANY(:uids) OR s.owner_id = ANY(:uids) OR s.invited_by_user_id = ANY(:uids)
                 OR s.property_id = ANY(:pids)
              UNION
              SELECT s.id FROM stays s
              INNER JOIN invitations i ON i.id = s.invitation_id
              WHERE i.owner_id = ANY(:uids) OR i.invited_by_user_id = ANY(:uids) OR i.property_id = ANY(:pids)
            ) x
            """
        ),
        {"uids": user_ids, "pids": property_ids or [0]},
    ).fetchone()
    stay_ids = _ids_from_row(row)

    row = conn.execute(
        text(
            """
            SELECT COALESCE(array_agg(DISTINCT inv_id), ARRAY[]::integer[])
            FROM (
              SELECT id AS inv_id FROM invitations
              WHERE owner_id = ANY(:uids) OR invited_by_user_id = ANY(:uids) OR property_id = ANY(:pids)
              UNION
              SELECT invitation_id AS inv_id FROM stays
              WHERE id = ANY(:sids) AND invitation_id IS NOT NULL
            ) x
            """
        ),
        {"uids": user_ids, "pids": property_ids or [0], "sids": stay_ids or [0]},
    ).fetchone()
    invitation_ids = _ids_from_row(row)

    return {
        "user_ids": user_ids,
        "owner_profile_ids": owner_profile_ids,
        "property_ids": property_ids,
        "unit_ids": unit_ids,
        "stay_ids": stay_ids,
        "invitation_ids": invitation_ids,
    }


def run_deletes(conn, ids: dict, emails: list[str], dry_run: bool) -> None:
    """Execute all delete statements in correct order."""
    u, op, p, un, s, inv = (
        ids["user_ids"],
        ids["owner_profile_ids"],
        ids["property_ids"],
        ids["unit_ids"],
        ids["stay_ids"],
        ids["invitation_ids"],
    )
    u_any = u or [0]
    op_any = op or [0]
    p_any = p or [0]
    un_any = un or [0]
    s_any = s or [0]
    inv_any = inv or [0]

    def run(sql: str, params: dict | None = None):
        if dry_run:
            print(f"  [DRY-RUN] {sql[:80]}...")
        else:
            conn.execute(text(sql), params or {})

    run(
        """DELETE FROM dashboard_alerts
        WHERE user_id = ANY(:u) OR property_id = ANY(:p) OR stay_id = ANY(:s) OR invitation_id = ANY(:inv)""",
        {"u": u_any, "p": p_any, "s": s_any, "inv": inv_any},
    )
    run(
        "DELETE FROM event_ledger WHERE actor_user_id = ANY(:u) OR property_id = ANY(:p) OR unit_id = ANY(:un) OR stay_id = ANY(:s) OR invitation_id = ANY(:inv)",
        {"u": u_any, "p": p_any, "un": un_any, "s": s_any, "inv": inv_any},
    )
    run(
        "DELETE FROM audit_logs WHERE actor_user_id = ANY(:u) OR property_id = ANY(:p) OR stay_id = ANY(:s) OR invitation_id = ANY(:inv)",
        {"u": u_any, "p": p_any, "s": s_any, "inv": inv_any},
    )
    run(
        "DELETE FROM presence_away_periods WHERE stay_id = ANY(:s) OR resident_presence_id IN (SELECT id FROM resident_presences WHERE user_id = ANY(:u) OR unit_id = ANY(:un))",
        {"s": s_any, "u": u_any, "un": un_any},
    )
    run("DELETE FROM stay_presences WHERE stay_id = ANY(:s)", {"s": s_any})
    run("DELETE FROM resident_presences WHERE user_id = ANY(:u) OR unit_id = ANY(:un)", {"u": u_any, "un": un_any})
    run("DELETE FROM resident_modes WHERE user_id = ANY(:u) OR unit_id = ANY(:un)", {"u": u_any, "un": un_any})
    run(
        "DELETE FROM tenant_assignments WHERE user_id = ANY(:u) OR unit_id = ANY(:un) OR invited_by_user_id = ANY(:u)",
        {"u": u_any, "un": un_any},
    )
    run(
        "DELETE FROM property_manager_assignments WHERE user_id = ANY(:u) OR property_id = ANY(:p) OR assigned_by_user_id = ANY(:u)",
        {"u": u_any, "p": p_any},
    )
    run(
        "DELETE FROM manager_invitations WHERE invited_by_user_id = ANY(:u) OR property_id = ANY(:p) OR lower(trim(email)) = ANY(:emails)",
        {"u": u_any, "p": p_any, "emails": emails},
    )
    run("DELETE FROM guest_pending_invites WHERE user_id = ANY(:u) OR invitation_id = ANY(:inv)", {"u": u_any, "inv": inv_any})
    run(
        """DELETE FROM agreement_signatures WHERE used_by_user_id = ANY(:u) OR lower(trim(guest_email)) = ANY(:emails)
        OR invitation_code IN (
          SELECT invitation_code FROM invitations
          WHERE owner_id = ANY(:u) OR invited_by_user_id = ANY(:u) OR property_id = ANY(:p)
        )""",
        {"u": u_any, "p": p_any, "emails": emails},
    )
    run("DELETE FROM stays WHERE id = ANY(:s)", {"s": s_any})
    run(
        "DELETE FROM invitations WHERE owner_id = ANY(:u) OR invited_by_user_id = ANY(:u) OR property_id = ANY(:p)",
        {"u": u_any, "p": p_any},
    )
    run("DELETE FROM bulk_upload_jobs WHERE user_id = ANY(:u)", {"u": u_any})
    run("DELETE FROM property_authority_letters WHERE property_id = ANY(:p)", {"p": p_any})
    run("DELETE FROM property_utility_providers WHERE property_id = ANY(:p)", {"p": p_any})
    run("DELETE FROM units WHERE property_id = ANY(:p)", {"p": p_any})
    run("DELETE FROM properties WHERE owner_profile_id = ANY(:op)", {"op": op_any})
    run("DELETE FROM owner_poa_signatures WHERE used_by_user_id = ANY(:u)", {"u": u_any})
    run("DELETE FROM owner_profiles WHERE user_id = ANY(:u)", {"u": u_any})
    run("DELETE FROM guest_profiles WHERE user_id = ANY(:u)", {"u": u_any})
    run("DELETE FROM pending_registrations WHERE lower(trim(email)) = ANY(:emails)", {"emails": emails})
    run("DELETE FROM users WHERE lower(trim(email)) = ANY(:emails)", {"emails": emails})


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete all data related to one or more user emails (all roles, properties, stays, etc.)."
    )
    parser.add_argument("emails", nargs="+", help="One or more user email addresses")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without making changes")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    emails = [e.strip().lower() for e in args.emails if e.strip()]
    invalid = [e for e in emails if "@" not in e]
    if invalid:
        print(f"Invalid email(s): {invalid}")
        sys.exit(1)
    if not emails:
        print("No valid emails provided.")
        sys.exit(1)

    with engine.connect() as conn:
        ids = get_ids(conn, emails)
        user_ids = ids["user_ids"]

        if not user_ids:
            print(f"No users found with emails: {emails}")
            sys.exit(0)

        print(f"Found {len(user_ids)} user(s) matching: {emails}")
        print(
            f"  Properties: {len(ids['property_ids'])} | Units: {len(ids['unit_ids'])} | Stays: {len(ids['stay_ids'])} | Invitations (expanded): {len(ids['invitation_ids'])}"
        )

        if args.dry_run:
            print("\n[DRY-RUN] Would delete all related data. Run without --dry-run to execute.")
            run_deletes(conn, ids, emails, dry_run=True)
            return

        if not args.yes:
            confirm = input("This will permanently delete all data for these users. Type 'yes' to proceed: ")
            if confirm.strip().lower() != "yes":
                print("Aborted.")
                sys.exit(0)

        run_deletes(conn, ids, emails, dry_run=False)
        conn.commit()
        print(f"Deleted all data for {len(user_ids)} user(s).")


if __name__ == "__main__":
    main()
