"""
Check that invitations have owner_id set and that Stay rows have the correct invitation_id
for the owner_stays API. Use this when "Stays (active & past)" is empty but invitations show.

Run from project root (use the same Python/venv as the app so dependencies are available):
  python scripts/check_owner_stays.py              # all owners
  python scripts/check_owner_stays.py <owner_email>  # one owner

Output:
  - Invitations (BURNED/EXPIRED) with NO Stay row (these get synthetic rows if property in profile)
  - Stays with owner_id != invitation.owner_id (would be fixed by loading stays by invitation)
  - OwnerProfile and property count (needed for synthetic rows)
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))


def main():
    owner_email = sys.argv[1].strip() if len(sys.argv) > 1 else None

    from app.database import SessionLocal
    from app.models.user import User, UserRole
    from app.models.invitation import Invitation
    from app.models.stay import Stay
    from app.models.owner import OwnerProfile, Property

    db = SessionLocal()
    try:
        if owner_email:
            user = db.query(User).filter(User.email == owner_email).first()
            if not user:
                print(f"No user found with email: {owner_email}")
                return
            if user.role != UserRole.owner:
                print(f"User {owner_email} has role={user.role}, not owner.")
                return
            owners = [(user.id, user.email)]
        else:
            owners = [(u.id, u.email) for u in db.query(User).filter(User.role == UserRole.owner).all()]
            if not owners:
                print("No owner users in DB.")
                return

        for owner_id, email in owners:
            print(f"\n--- Owner: {email} (user_id={owner_id}) ---")

            invs = db.query(Invitation).filter(Invitation.owner_id == owner_id).order_by(Invitation.id).all()
            print(f"  Invitations: {len(invs)}")
            if not invs:
                print("  (none)")
                continue

            inv_ids = [inv.id for inv in invs]
            stays_by_owner = db.query(Stay).filter(Stay.owner_id == owner_id).all()
            stays_by_inv = db.query(Stay).filter(Stay.invitation_id.in_(inv_ids)).all() if inv_ids else []
            seen = {s.id for s in stays_by_owner}
            for s in stays_by_inv:
                seen.add(s.id)
            all_stays = stays_by_owner + [s for s in stays_by_inv if s.id not in {x.id for x in stays_by_owner}]
            stay_by_inv_id = {s.invitation_id: s for s in all_stays if s.invitation_id is not None}

            # Invitations with BURNED/EXPIRED but no Stay
            missing = []
            for inv in invs:
                token = (inv.token_state or "").upper()
                if token not in ("BURNED", "EXPIRED"):
                    continue
                st = stay_by_inv_id.get(inv.id)
                if not st:
                    missing.append(inv)

            if missing:
                print(f"  Invitations (BURNED/EXPIRED) with NO Stay: {len(missing)}")
                for inv in missing:
                    print(f"    id={inv.id} code={inv.invitation_code} owner_id={inv.owner_id} token_state={inv.token_state} guest={inv.guest_name or inv.guest_email or '—'}")
            else:
                print("  All BURNED/EXPIRED invitations have a Stay row.")

            # Stays with wrong owner_id
            wrong_owner = [s for s in all_stays if s.owner_id != owner_id]
            if wrong_owner:
                print(f"  Stays with owner_id != {owner_id}: {len(wrong_owner)}")
                for s in wrong_owner:
                    inv = db.query(Invitation).filter(Invitation.id == s.invitation_id).first() if s.invitation_id else None
                    inv_owner = inv.owner_id if inv else "—"
                    print(f"    stay_id={s.id} invitation_id={s.invitation_id} stay.owner_id={s.owner_id} inv.owner_id={inv_owner}")
            else:
                print("  All stays have owner_id matching this owner (or were found via invitation).")

            # Profile and property count (for synthetic rows)
            profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == owner_id).first()
            if not profile:
                print("  No OwnerProfile (synthetic BURNED rows will not be added).")
            else:
                prop_count = db.query(Property).filter(Property.owner_profile_id == profile.id, Property.deleted_at.is_(None)).count()
                print(f"  OwnerProfile id={profile.id}, non-deleted properties={prop_count}")

            print(f"  Total Stay rows for this owner (by owner_id or invitation): {len(all_stays)}")

        print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
