"""
Set an owner's onboarding invoice as unpaid in the DB (clear onboarding_invoice_paid_at).
Use this to re-test the payment flow. Stripe invoice remains paid; only our DB is reset.

Before opening Billing in the app, set STRIPE_SKIP_ONBOARDING_SELF_HEAL=true in .env so the
billing endpoint does not immediately re-set the flag when it sees the paid invoice in Stripe.

Run from project root: python scripts/set_onboarding_invoice_unpaid.py <owner_email>
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/set_onboarding_invoice_unpaid.py <owner_email>")
        sys.exit(1)
    email = sys.argv[1].strip()

    from app.database import SessionLocal
    from app.models.user import User, UserRole
    from app.models.owner import OwnerProfile

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"No user found with email: {email}")
            return
        if user.role != UserRole.owner:
            print(f"User {email} is not an owner (role={user.role}).")
            return

        profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == user.id).first()
        if not profile:
            print(f"No owner profile found for {email}.")
            return

        old_val = profile.onboarding_invoice_paid_at
        profile.onboarding_invoice_paid_at = None
        db.commit()
        print(f"Set onboarding invoice as unpaid for {email} (owner_profile_id={profile.id}).")
        if old_val:
            print(f"  Previous onboarding_invoice_paid_at: {old_val}")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
