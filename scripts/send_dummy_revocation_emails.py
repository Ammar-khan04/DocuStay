"""
Send dummy revocation emails to a test address for preview.
Uses any Stay record from DB (or fallback data) to populate the templates.

Run from project root:
  python scripts/send_dummy_revocation_emails.py

Requires MAILGUN_API_KEY + MAILGUN_DOMAIN (or SENDGRID_API_KEY) in .env.
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

TEST_EMAIL = "arfamujahid333@gmail.com"


def main():
    from app.database import SessionLocal
    from app.models.stay import Stay
    from app.models.invitation import Invitation
    from app.models.owner import Property
    from app.models.user import User
    from app.services.notifications import (
        send_vacate_12h_notice,
        send_removal_notice_to_guest,
        send_removal_confirmation_to_owner,
    )

    db = SessionLocal()
    try:
        # Try to get a real Stay with invitation and property
        stay = (
            db.query(Stay)
            .filter(Stay.invitation_id.isnot(None))
            .order_by(Stay.id.desc())
            .first()
        )
        if not stay:
            stay = db.query(Stay).order_by(Stay.id.desc()).first()

        if stay:
            prop = db.query(Property).filter(Property.id == stay.property_id).first()
            guest = db.query(User).filter(User.id == stay.guest_id).first()
            inv = None
            if stay.invitation_id:
                inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()

            property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Sample Property"
            guest_name = (guest.full_name if guest else None) or guest.email or (inv.guest_name if inv else None) or "Sample Guest"
            property_address = ""
            if prop:
                prop_parts = [prop.street, prop.city, prop.state, (prop.zip_code or "").strip()]
                property_address = ", ".join(p for p in prop_parts if p)
            invite_code = (inv.invitation_code or "") if inv else ""
            stay_start = stay.stay_start_date.isoformat() if stay.stay_start_date else "2026-01-01"
            stay_end = stay.stay_end_date.isoformat() if stay.stay_end_date else "2026-01-15"
            region = stay.region_code or "US"
            revoked_at = (stay.revoked_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
            vacate_by = (datetime.now(timezone.utc) + timedelta(hours=12)).strftime("%Y-%m-%d %H:%M UTC")

            print(f"Using Stay id={stay.id}, property={property_name}, guest={guest_name}, invite_code={invite_code or '(none)'}")
        else:
            # Fallback when no stays exist
            property_name = "Sample Property"
            guest_name = "Sample Guest"
            property_address = "123 Main St, Miami, FL 33101"
            invite_code = "INV-DUMMY-TEST"
            stay_start = "2026-01-01"
            stay_end = "2026-01-15"
            region = "US"
            revoked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            vacate_by = (datetime.now(timezone.utc) + timedelta(hours=12)).strftime("%Y-%m-%d %H:%M UTC")
            print("No Stay in DB; using fallback data.")
    finally:
        db.close()

    print(f"\nSending 3 dummy emails to {TEST_EMAIL}...\n")

    # 1. Vacate 12h notice (guest – Kill Switch)
    ok1 = send_vacate_12h_notice(
        TEST_EMAIL,
        guest_name,
        property_name,
        vacate_by,
        region,
        property_address=property_address,
        stay_start_date=stay_start,
        stay_end_date=stay_end,
        revoked_at=revoked_at,
        invite_code=invite_code,
    )
    print(f"1. Vacate 12h notice (Kill Switch): {'SENT' if ok1 else 'FAILED'}")

    # 2. Removal notice to guest
    ok2 = send_removal_notice_to_guest(
        TEST_EMAIL,
        guest_name,
        property_name,
        region,
        property_address=property_address,
        stay_start_date=stay_start,
        stay_end_date=stay_end,
        revoked_at=revoked_at,
        invite_code=invite_code,
    )
    print(f"2. Removal notice (guest): {'SENT' if ok2 else 'FAILED'}")

    # 3. Removal confirmation to owner
    ok3 = send_removal_confirmation_to_owner(
        TEST_EMAIL,
        guest_name,
        property_name,
        region,
        property_address=property_address,
        stay_start_date=stay_start,
        stay_end_date=stay_end,
        revoked_at=revoked_at,
        invite_code=invite_code,
    )
    print(f"3. Removal confirmation (owner): {'SENT' if ok3 else 'FAILED'}")

    print(f"\nDone. Check {TEST_EMAIL} (and spam folder).")


if __name__ == "__main__":
    main()
