#!/usr/bin/env python3
"""
Backfill dashboard alerts (notifications) for a given user email so they appear in the UI.

Run from project root:
  python scripts/backfill_dashboard_alerts.py fasac10631@medevsa.com
  python scripts/backfill_dashboard_alerts.py fasac10631@medevsa.com --apply   # actually write to DB
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/backfill_dashboard_alerts.py <email> [--apply]")
        sys.exit(1)
    email = sys.argv[1].strip().lower()
    apply = "--apply" in sys.argv

    from app.database import SessionLocal
    from app.models.user import User
    from app.models.dashboard_alert import DashboardAlert
    from datetime import datetime, timezone, timedelta

    db = SessionLocal()
    try:
        users = db.query(User).filter(User.email == email).all()
        if not users:
            print(f"No user(s) found with email: {email}")
            return
        print(f"Found {len(users)} user(s): {[(u.id, u.role.value) for u in users]}")
        now = datetime.now(timezone.utc)
        # Sample alerts to backfill (role-appropriate types)
        samples = [
            ("nearing_expiration", "warning", "Stay nearing end date", "A stay at your property ends in 3 days. Please confirm checkout or renewal in DocuStay."),
            ("dms_48h", "warning", "Dead Man's Switch: 48h before lease end", "Stay for Guest Name at Sample Property ends 2025-03-18. Please confirm checkout or renewal within 48 hours."),
            ("revoked", "info", "Stay revoked", "You revoked stay authorization for a guest at Sample Property. Guest must vacate within 12 hours."),
            ("renewed", "info", "Lease renewed", "Stay for Guest Name at Sample Property was renewed to 2025-06-01. Occupancy status remains Occupied."),
            ("invitation_expired", "info", "Invitation expired", "A guest invitation was not accepted in time and has been marked expired."),
        ]
        for user in users:
            for alert_type, severity, title, message in samples:
                alert = DashboardAlert(
                    user_id=user.id,
                    alert_type=alert_type,
                    title=title,
                    message=message,
                    severity=severity,
                    read_at=None,
                    meta={"backfilled": True},
                )
                if apply:
                    db.add(alert)
                print(f"  Would add alert for user_id={user.id} role={user.role.value}: {title[:50]}...")
        if apply:
            db.commit()
            print(f"Committed {len(users) * len(samples)} dashboard alert(s) for {email}.")
        else:
            print("Dry run. Add --apply to write to the database.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
