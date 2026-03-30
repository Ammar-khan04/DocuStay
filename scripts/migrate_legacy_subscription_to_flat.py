"""
Migrate a legacy Stripe subscription (old per-unit / multi-line) to the flat $10/mo plan.

For owners who signed up under the previous billing model, run this once per account after
deploying flat pricing. New signups do not need it.

After migration, Stripe creates a new flat subscription with a fresh **7-day free trial**
(same as new signups). The Settings banner and billing API will show trial countdown.

Usage (project root, venv + .env):
  python scripts/migrate_legacy_subscription_to_flat.py owner@example.com
  python scripts/migrate_legacy_subscription_to_flat.py owner@example.com --dry-run
  python scripts/migrate_legacy_subscription_to_flat.py owner@example.com --force

Flags:
  --dry-run   Print actions only; do not change Stripe or the database.
  --force     Migrate even if Stripe already looks like a flat subscription (use rarely).

Requires STRIPE_SECRET_KEY and database URL as for the main app.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate owner from legacy Stripe subscription to flat $10/mo.")
    parser.add_argument("email", help="Owner user email")
    parser.add_argument("--dry-run", action="store_true", help="Print only; no Stripe or DB writes")
    parser.add_argument("--force", action="store_true", help="Run even if subscription already appears flat")
    args = parser.parse_args()

    from app.database import SessionLocal
    from app.models.user import User, UserRole
    from app.models.owner import OwnerProfile
    from app.services.billing import (
        _stripe_enabled,
        _count_properties_and_shield,
        subscription_looks_legacy_per_unit_from_stripe,
        ensure_subscription,
        sync_subscription_quantities,
    )
    from app.config import get_settings

    if not _stripe_enabled():
        print("Stripe is not configured (STRIPE_SECRET_KEY).")
        sys.exit(1)

    import stripe

    stripe.api_key = get_settings().stripe_secret_key

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == args.email.strip()).first()
        if not user:
            print(f"No user found: {args.email}")
            sys.exit(1)
        if user.role != UserRole.owner:
            print(f"User is not an owner (role={user.role}).")
            sys.exit(1)
        profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == user.id).first()
        if not profile:
            print("No owner profile.")
            sys.exit(1)
        if not profile.stripe_subscription_id:
            print("No stripe_subscription_id on profile; nothing to migrate.")
            sys.exit(0)

        try:
            sub = stripe.Subscription.retrieve(profile.stripe_subscription_id)
        except stripe.InvalidRequestError as e:
            print(f"Could not load subscription {profile.stripe_subscription_id}: {e}")
            sys.exit(1)

        db_legacy = profile.stripe_subscription_shield_item_id is not None
        stripe_legacy = subscription_looks_legacy_per_unit_from_stripe(sub)
        is_legacy = db_legacy or stripe_legacy

        print(f"Profile id={profile.id}  subscription={profile.stripe_subscription_id}")
        print(f"  DB shield item id (legacy marker): {profile.stripe_subscription_shield_item_id}")
        print(f"  Detected legacy from Stripe items: {stripe_legacy}")
        print(f"  Treat as legacy: {is_legacy or args.force}")

        if not is_legacy and not args.force:
            print("Subscription already matches flat plan; nothing to do. Use --force to replace anyway.")
            sys.exit(0)

        units, _ = _count_properties_and_shield(db, profile)
        if units < 1:
            print("Owner has no active properties; cannot create a new subscription after cancel. Add/reactivate a property first.")
            sys.exit(1)

        if args.dry_run:
            print("[dry-run] Would cancel subscription with prorate=True, clear item ids, create flat sub with 7-day trial, sync.")
            sys.exit(0)

        stripe.Subscription.cancel(profile.stripe_subscription_id, prorate=True)
        profile.stripe_subscription_id = None
        profile.stripe_subscription_baseline_item_id = None
        profile.stripe_subscription_shield_item_id = None
        db.commit()
        db.refresh(profile)

        ensure_subscription(db, profile, user, allow_trial=True)
        sync_subscription_quantities(db, profile)

        print("Done. New subscription id:", profile.stripe_subscription_id)
        if profile.stripe_subscription_id:
            try:
                new_sub = stripe.Subscription.retrieve(profile.stripe_subscription_id)
                te = getattr(new_sub, "trial_end", None)
                st = getattr(new_sub, "status", None)
                if te and st == "trialing":
                    end = datetime.fromtimestamp(int(te), tz=timezone.utc)
                    print(f"  Status: trialing — trial ends (UTC): {end.isoformat()}")
                else:
                    print(f"  Status: {st or 'unknown'} (trial info only shown when trialing)")
            except stripe.StripeError as e:
                print(f"  (Could not read trial end from new subscription: {e})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
