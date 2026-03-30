"""
Send a dummy Dead Man's Switch enabled email to a test address for preview.

Run from project root:
  python scripts/send_dummy_dms_enabled_email.py

Requires MAILGUN_API_KEY + MAILGUN_DOMAIN (or SENDGRID_API_KEY) in .env.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

TEST_EMAIL = "arfamujahid333@gmail.com"


def main():
    from app.database import SessionLocal
    from app.models.owner import Property
    from app.services.notifications import send_dead_mans_switch_enabled_notification

    db = SessionLocal()
    try:
        prop = db.query(Property).filter(Property.deleted_at.is_(None)).order_by(Property.id.desc()).first()
        if prop:
            property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}" if prop else "").strip(", ") or f"Property {prop.id}"
            print(f"Using Property id={prop.id}, name={property_name}")
        else:
            property_name = "Sample Property"
            print("No Property in DB; using fallback.")
    finally:
        db.close()

    guest_name = "Sample Guest"
    stay_end_date = (date.today() + timedelta(days=7)).isoformat()

    print(f"\nSending DMS enabled notification to {TEST_EMAIL}...\n")

    # Send as if owner; empty manager list
    send_dead_mans_switch_enabled_notification(
        owner_email=TEST_EMAIL,
        manager_emails=[],
        property_name=property_name,
        guest_name=guest_name,
        stay_end_date=stay_end_date,
    )

    print("DMS enabled email: SENT")
    print(f"\nDone. Check {TEST_EMAIL} (and spam folder).")


if __name__ == "__main__":
    main()
