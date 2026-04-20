"""
Create a manual one-off Stripe invoice for the flat monthly plan ($10/mo) for a given owner.

Run from project root: python scripts/create_manual_subscription_invoice.py <owner_email>
Prints the hosted invoice URL; the invoice appears in the owner's Billing tab.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/create_manual_subscription_invoice.py <owner_email>")
        sys.exit(1)
    email = sys.argv[1].strip()

    from app.database import SessionLocal
    from app.models.user import User, UserRole
    from app.models.owner import OwnerProfile
    from app.services.billing import _count_properties_and_shield, _stripe_enabled, SUBSCRIPTION_FLAT_AMOUNT_CENTS
    from app.config import get_settings

    if not _stripe_enabled():
        print("Stripe is not configured (STRIPE_SECRET_KEY).")
        sys.exit(1)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"No user found with email: {email}")
            sys.exit(1)
        if user.role != UserRole.owner:
            print(f"User {email} is not an owner (role={user.role}).")
            sys.exit(1)

        profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == user.id).first()
        if not profile:
            print(f"No owner profile found for {email}.")
            sys.exit(1)
        if not profile.stripe_customer_id:
            print(f"Owner {email} has no Stripe customer ID. They need to have gone through billing once (e.g. add a property).")
            sys.exit(1)

        units, _shield = _count_properties_and_shield(db, profile)
        if units < 1:
            print(f"Owner {email} has no non-deleted properties (units=0). Cannot create subscription-style invoice.")
            sys.exit(1)

        import stripe

        stripe.api_key = get_settings().stripe_secret_key

        invoice = stripe.Invoice.create(
            customer=profile.stripe_customer_id,
            collection_method="charge_automatically",
            metadata={
                "owner_profile_id": str(profile.id),
                "manual_monthly_subscription_test": "true",
            },
            description="DocuStay monthly subscription (manual test, flat rate)",
        )
        stripe.InvoiceItem.create(
            customer=profile.stripe_customer_id,
            invoice=invoice.id,
            amount=SUBSCRIPTION_FLAT_AMOUNT_CENTS,
            currency="usd",
            description="DocuStay Subscription (monthly) — flat rate",
        )

        stripe.Invoice.finalize_invoice(invoice.id)
        inv = stripe.Invoice.retrieve(invoice.id)
        url = getattr(inv, "hosted_invoice_url", None) or None

        print(f"Created manual monthly subscription invoice for {email} (profile_id={profile.id}).")
        print(f"  Flat amount: ${SUBSCRIPTION_FLAT_AMOUNT_CENTS / 100:.2f} USD.")
        print(f"  Invoice ID: {inv.id}")
        if url:
            print(f"  Hosted invoice URL: {url}")
        else:
            print("  (No hosted URL; check Stripe Dashboard.)")
    except Exception as e:
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
