"""One-time migration: update Invitation.status='ongoing' rows to 'accepted'.

The 'ongoing' status was used by CSV/bulk imports for occupied tenants.
The new 4-state model uses: pending, accepted, cancelled, expired.
Legacy 'ongoing' rows should be 'accepted' since they represent
already-occupied (i.e. accepted) tenants.

Usage:
    python -m scripts.fix_ongoing_status          # dry-run (default)
    python -m scripts.fix_ongoing_status --apply  # actually commit changes
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models.invitation import Invitation


def main():
    parser = argparse.ArgumentParser(description="Fix Invitation.status='ongoing' → 'accepted'")
    parser.add_argument("--apply", action="store_true", help="Actually commit changes (default is dry-run)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        rows = db.query(Invitation).filter(Invitation.status == "ongoing").all()
        print(f"Found {len(rows)} invitation(s) with status='ongoing'")

        for inv in rows:
            code = getattr(inv, "invitation_code", "?")
            kind = getattr(inv, "invitation_kind", "?")
            token = getattr(inv, "token_state", "?")
            print(f"  {code}  kind={kind}  token_state={token}  -> status='accepted'")
            inv.status = "accepted"

        if args.apply:
            db.commit()
            print(f"\nCommitted: {len(rows)} row(s) updated to status='accepted'.")
        else:
            db.rollback()
            print(f"\nDry run — no changes committed. Re-run with --apply to commit.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
