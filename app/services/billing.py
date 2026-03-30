"""Billing service: Stripe subscription for owners.

Pricing: $10/month flat (not per property). New subscriptions include a 7-day free trial;
recurring charges begin after the trial unless cancelled.

Legacy: some accounts may still have the old two-line subscription (baseline + Shield);
sync keeps quantities for those until migrated in Stripe.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.owner import OwnerProfile, Property
from app.models.user import User
from app.services.audit_log import create_log, CATEGORY_BILLING
from app.services.event_ledger import create_ledger_event, ACTION_BILLING_SUBSCRIPTION_STARTED

logger = logging.getLogger(__name__)

SUBSCRIPTION_FLAT_AMOUNT_CENTS = 1000  # $10.00 / month
SUBSCRIPTION_TRIAL_DAYS = 7

_FLAT_PRODUCT_NAME = "DocuStay Subscription (monthly)"


def _stripe_enabled() -> bool:
    s = get_settings()
    return bool((s.stripe_secret_key or "").strip())


def _is_placeholder_customer_id(customer_id: str | None) -> bool:
    """True if this is a non-Stripe placeholder (e.g. from identity verification), not a real Stripe customer."""
    if not customer_id or not isinstance(customer_id, str):
        return True
    c = customer_id.strip()
    if not c.startswith("cus_"):
        return True
    if c.lower() in ("cus_verified_placeholder", "cus_placeholder"):
        return True
    if "placeholder" in c.lower() or "test" in c.lower():
        return True
    return False


def get_or_create_stripe_customer(profile: OwnerProfile, user: User) -> str | None:
    """Ensure Stripe customer exists for this owner; return stripe_customer_id or None if Stripe disabled."""
    if not _stripe_enabled():
        return None
    import stripe

    stripe.api_key = get_settings().stripe_secret_key
    if profile.stripe_customer_id and not _is_placeholder_customer_id(profile.stripe_customer_id):
        try:
            stripe.Customer.retrieve(profile.stripe_customer_id)
            return profile.stripe_customer_id
        except stripe.InvalidRequestError:
            pass
    email = (user.email or "").strip()
    name = (user.full_name or email or "DocuStay Owner").strip() or None
    customer = stripe.Customer.create(email=email or None, name=name, metadata={"owner_profile_id": str(profile.id)})
    return customer.id


def _count_properties_and_shield(db: Session, profile: OwnerProfile) -> tuple[int, int]:
    """Return (billing_unit_count, shield_count). Billing unit count = non-deleted properties (1 property = 1 unit)."""
    q = db.query(Property).filter(
        Property.owner_profile_id == profile.id,
        Property.deleted_at.is_(None),
    )
    property_count = q.count()
    from app.services.shield_mode_policy import SHIELD_MODE_ALWAYS_ON

    if SHIELD_MODE_ALWAYS_ON:
        return property_count, property_count
    shield_count = q.filter(Property.shield_mode_enabled == 1).count()
    return property_count, shield_count


def stripe_subscription_status_and_trial(
    subscription: object,
) -> tuple[str | None, datetime | None, int | None]:
    """From a Stripe Subscription object: status, trial_end (UTC), calendar days left (UTC dates) while trialing."""
    status = getattr(subscription, "status", None) or None
    te_raw = getattr(subscription, "trial_end", None)
    trial_end_at: datetime | None = None
    if te_raw is not None:
        trial_end_at = datetime.fromtimestamp(int(te_raw), tz=timezone.utc)
    trial_days_remaining: int | None = None
    if status == "trialing" and trial_end_at is not None:
        now = datetime.now(timezone.utc)
        if trial_end_at <= now:
            trial_days_remaining = 0
        else:
            trial_days_remaining = (trial_end_at.date() - now.date()).days
    return status, trial_end_at, trial_days_remaining


def subscription_looks_legacy_per_unit_from_stripe(subscription: object) -> bool:
    """True if subscription is not the current flat single-price line (e.g. old $1/unit ± Shield lines)."""
    items_obj = getattr(subscription, "items", None)
    data = getattr(items_obj, "data", None) if items_obj is not None else None
    items = data or []
    if len(items) > 1:
        return True
    if not items:
        return False
    for item in items:
        price = getattr(item, "price", None)
        ua = getattr(price, "unit_amount", None) if price else None
        if ua is None:
            continue
        if int(ua) != SUBSCRIPTION_FLAT_AMOUNT_CENTS:
            return True
    return False


def _get_or_create_flat_subscription_product_id() -> str:
    import stripe

    stripe.api_key = get_settings().stripe_secret_key
    for prod in stripe.Product.list(limit=100).auto_paging_iter():
        if (prod.name or "").strip() == _FLAT_PRODUCT_NAME:
            return prod.id
    p = stripe.Product.create(name=_FLAT_PRODUCT_NAME)
    return p.id


def ensure_subscription(
    db: Session,
    profile: OwnerProfile,
    user: User | None = None,
    *,
    allow_trial: bool = True,
) -> None:
    """Create Stripe subscription ($10/mo flat) if not already created. Idempotent.

    If allow_trial is True (default), new subscriptions get SUBSCRIPTION_TRIAL_DAYS free days.
    Set allow_trial False when recreating after cancel or after a legacy paid onboarding invoice.
    """
    if not _stripe_enabled():
        return
    import stripe

    stripe.api_key = get_settings().stripe_secret_key
    if _is_placeholder_customer_id(profile.stripe_customer_id) or not profile.stripe_customer_id:
        u = user or db.query(User).filter(User.id == profile.user_id).first()
        if u:
            customer_id = get_or_create_stripe_customer(profile, u)
            if customer_id:
                profile.stripe_customer_id = customer_id
                db.commit()
                db.refresh(profile)
        if not profile.stripe_customer_id or _is_placeholder_customer_id(profile.stripe_customer_id):
            return
    else:
        try:
            stripe.Customer.retrieve(profile.stripe_customer_id)
        except stripe.InvalidRequestError:
            u = user or db.query(User).filter(User.id == profile.user_id).first()
            if u:
                customer_id = get_or_create_stripe_customer(profile, u)
                if customer_id:
                    profile.stripe_customer_id = customer_id
                    db.commit()
                    db.refresh(profile)
            if not profile.stripe_customer_id or _is_placeholder_customer_id(profile.stripe_customer_id):
                return

    if profile.stripe_subscription_id:
        try:
            stripe.Subscription.retrieve(profile.stripe_subscription_id)
            return
        except Exception:
            pass

    units, _shield_units = _count_properties_and_shield(db, profile)
    if units < 1:
        return

    flat_prod_id = _get_or_create_flat_subscription_product_id()
    create_kwargs: dict = {
        "customer": profile.stripe_customer_id,
        "items": [
            {
                "price_data": {
                    "currency": "usd",
                    "unit_amount": SUBSCRIPTION_FLAT_AMOUNT_CENTS,
                    "recurring": {"interval": "month"},
                    "product": flat_prod_id,
                },
                "quantity": 1,
            }
        ],
        "metadata": {"owner_profile_id": str(profile.id)},
        "payment_behavior": "default_incomplete",
    }
    if allow_trial:
        create_kwargs["trial_period_days"] = SUBSCRIPTION_TRIAL_DAYS

    try:
        sub = stripe.Subscription.create(**create_kwargs)
        baseline_item_id: str | None = None
        items_data = getattr(sub, "items", None)
        if items_data is not None:
            data = getattr(items_data, "data", None) or []
            for item in data:
                price = getattr(item, "price", None)
                amt = (getattr(price, "unit_amount", 0) or 0) if price else 0
                item_id = getattr(item, "id", None)
                if amt == SUBSCRIPTION_FLAT_AMOUNT_CENTS and item_id:
                    baseline_item_id = item_id
                    break
        profile.stripe_subscription_id = sub.id
        profile.stripe_subscription_baseline_item_id = baseline_item_id
        profile.stripe_subscription_shield_item_id = None
        db.commit()
        logger.info(
            "Subscription created for profile_id=%s (flat $10/mo, trial=%s)",
            profile.id,
            allow_trial,
        )
    except stripe.StripeError as e:
        logger.exception("Stripe error creating subscription for profile_id=%s: %s", profile.id, e)
        raise


def sync_subscription_quantities(db: Session, profile: OwnerProfile) -> None:
    """Update Stripe subscription to match account state.

    Flat plan: single line item, quantity 1 whenever there is at least one property; cancel if zero properties.
    Legacy (baseline + Shield item IDs stored): update per-unit quantities as before.
    """
    if not _stripe_enabled() or not profile.stripe_subscription_id:
        return
    units, shield_units = _count_properties_and_shield(db, profile)

    import stripe

    stripe.api_key = get_settings().stripe_secret_key
    try:
        if units <= 0:
            stripe.Subscription.cancel(profile.stripe_subscription_id, prorate=True)
            profile.stripe_subscription_id = None
            profile.stripe_subscription_baseline_item_id = None
            profile.stripe_subscription_shield_item_id = None
            db.commit()
            logger.info("Subscription cancelled for profile_id=%s (0 units); billing stopped (prorated).", profile.id)
            return

        if profile.stripe_subscription_shield_item_id:
            items = []
            if profile.stripe_subscription_baseline_item_id:
                items.append({"id": profile.stripe_subscription_baseline_item_id, "quantity": units})
            items.append({"id": profile.stripe_subscription_shield_item_id, "quantity": shield_units})
            if items:
                stripe.Subscription.modify(profile.stripe_subscription_id, items=items)
            logger.info(
                "Subscription quantities synced (legacy) for profile_id=%s: units=%s, shield=%s",
                profile.id,
                units,
                shield_units,
            )
            return

        if profile.stripe_subscription_baseline_item_id:
            stripe.Subscription.modify(
                profile.stripe_subscription_id,
                items=[{"id": profile.stripe_subscription_baseline_item_id, "quantity": 1}],
            )
            logger.info("Subscription synced (flat plan) for profile_id=%s", profile.id)
    except stripe.StripeError as e:
        logger.warning("Stripe error syncing subscription for profile_id=%s: %s", profile.id, e)


def charge_onboarding_fee(
    db: Session,
    profile: OwnerProfile,
    user: User,
    total_units: int,
) -> str | None:
    """First-property onboarding: create Stripe customer, flat subscription with trial, and mark billing complete.

    No one-time onboarding invoice. Returns None (no hosted invoice URL).

    Idempotent: no-op if onboarding billing was already completed (unless Stripe was off and is now on — see below).
    """
    if total_units < 1:
        return None

    if profile.onboarding_billing_completed_at is not None:
        if _stripe_enabled() and not profile.stripe_customer_id:
            logger.info(
                "Billing was marked complete without Stripe for profile_id=%s, resetting to create customer/subscription",
                profile.id,
            )
            profile.onboarding_billing_completed_at = None
            profile.onboarding_billing_unit_count = None
            profile.onboarding_invoice_paid_at = None
            db.commit()
        else:
            logger.info("Billing onboarding already completed for profile_id=%s, skipping", profile.id)
            return None

    if not _stripe_enabled():
        logger.warning("Stripe not configured; marking billing complete without subscription for profile_id=%s", profile.id)
        profile.onboarding_billing_completed_at = datetime.now(timezone.utc)
        profile.onboarding_billing_unit_count = total_units
        profile.onboarding_invoice_paid_at = datetime.now(timezone.utc)
        db.commit()
        return None

    customer_id = get_or_create_stripe_customer(profile, user)
    if not customer_id:
        return None
    profile.stripe_customer_id = customer_id
    db.commit()
    db.refresh(profile)

    ensure_subscription(db, profile, user, allow_trial=True)

    profile.onboarding_billing_completed_at = datetime.now(timezone.utc)
    profile.onboarding_billing_unit_count = total_units
    profile.onboarding_invoice_paid_at = datetime.now(timezone.utc)
    create_log(
        db,
        CATEGORY_BILLING,
        "Subscription started",
        "7-day free trial started. Billing is $10/month flat after the trial. Add a default payment method before the trial ends.",
        property_id=None,
        actor_user_id=user.id,
        actor_email=user.email,
        meta={"unit_count": total_units, "trial_days": SUBSCRIPTION_TRIAL_DAYS, "flat_monthly_cents": SUBSCRIPTION_FLAT_AMOUNT_CENTS},
    )
    create_ledger_event(
        db,
        ACTION_BILLING_SUBSCRIPTION_STARTED,
        actor_user_id=user.id,
        meta={
            "billing_setup": "flat_subscription_trial",
            "unit_count": total_units,
            "trial_days": SUBSCRIPTION_TRIAL_DAYS,
        },
    )
    db.commit()
    logger.info("Onboarding billing complete for profile_id=%s (flat subscription + trial)", profile.id)
    return None


def on_onboarding_properties_completed(
    db: Session,
    profile: OwnerProfile,
    user: User,
    total_units: int,
) -> str | None:
    """Called when owner has just completed their first property upload. Starts subscription with trial. Returns None."""
    return charge_onboarding_fee(db, profile, user, total_units)
