#!/usr/bin/env python3
"""
Backfill invitation.guest_email for tenant invitations that have no email set.
Uses the tenant's actual email from TenantAssignment (when the invitation was accepted).

Run from project root:
  python scripts/backfill_invitation_guest_emails.py         # dry-run (no changes)
  python scripts/backfill_invitation_guest_emails.py --apply # apply updates to DB

Only processes tenant invitations (invitation_kind='tenant') where guest_email is null or empty.
For each such invitation, finds the TenantAssignment for that unit with overlapping dates
and sets guest_email = that user's email.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Load .env before importing app (for DATABASE_URL etc.)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass


def main():
    apply = "--apply" in sys.argv

    from app.database import SessionLocal
    from app.models.invitation import Invitation
    from app.models.tenant_assignment import TenantAssignment
    from app.models.user import User

    db = SessionLocal()
    try:
        # Tenant invitations without guest_email
        invs = (
            db.query(Invitation)
            .filter(
                Invitation.invitation_kind == "tenant",
                Invitation.unit_id.isnot(None),
            )
            .all()
        )
        # Filter to those with no guest_email
        invs_no_email = [
            inv for inv in invs
            if not (getattr(inv, "guest_email", None) or "").strip()
        ]

        if not invs_no_email:
            print("No tenant invitations found without guest_email.")
            return

        print(f"Found {len(invs_no_email)} tenant invitation(s) without guest_email.")

        updated = 0
        skipped = 0

        for inv in invs_no_email:
            # Find TenantAssignment(s) for this unit with overlapping dates
            tas = (
                db.query(TenantAssignment)
                .filter(TenantAssignment.unit_id == inv.unit_id)
                .order_by(TenantAssignment.created_at.desc())
                .all()
            )

            tenant_email = None
            for ta in tas:
                user = db.query(User).filter(User.id == ta.user_id).first()
                if not user or not (user.email or "").strip():
                    continue
                email = (user.email or "").strip().lower()
                inv_start = inv.stay_start_date
                inv_end = inv.stay_end_date
                ta_start = ta.start_date
                ta_end = ta.end_date or inv_end
                overlaps = (
                    inv_start and inv_end and ta_start
                    and inv_start <= ta_end
                    and inv_end >= ta_start
                )
                if overlaps:
                    tenant_email = email
                    break
                if tenant_email is None:
                    tenant_email = email  # Fallback: most recent TA

            if not tenant_email:
                print(f"  SKIP inv_id={inv.id} code={inv.invitation_code} unit_id={inv.unit_id}: no TenantAssignment with email found")
                skipped += 1
                continue

            print(f"  inv_id={inv.id} code={inv.invitation_code} unit_id={inv.unit_id} -> {tenant_email}")
            if apply:
                inv.guest_email = tenant_email
                updated += 1
            else:
                updated += 1

        if apply and updated > 0:
            db.commit()
            print(f"\nUpdated {updated} invitation(s).")
        elif updated > 0:
            print(f"\nWould update {updated} invitation(s). Run with --apply to apply.")
        if skipped > 0:
            print(f"Skipped {skipped} (no matching TenantAssignment with email).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
