"""Billing service: Stripe subscription for owners.

Pricing: $10/month per UNIT. New subscriptions include a 7-day free trial;
recurring charges begin after the trial unless cancelled.

Legacy: some accounts may still have the old two-line subscription (baseline + Shield);
sync keeps quantities for those until migrated in Stripe.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

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
    """Return (billing_unit_count, shield_property_count).

    Billing units = total units across active properties.
    If a property has no Unit rows (common for single-unit properties), it counts as 1 unit.
    """
    from sqlalchemy import func
    from app.models.unit import Unit

    q = db.query(Property.id, Property.shield_mode_enabled).filter(
        Property.owner_profile_id == profile.id,
        Property.deleted_at.is_(None),
    )
    prop_rows = q.all()
    if not prop_rows:
        return 0, 0
    prop_ids = [r[0] for r in prop_rows]
    property_count = len(prop_ids)

    unit_counts = (
        db.query(Unit.property_id, func.count(Unit.id).label("cnt"))
        .filter(Unit.property_id.in_(prop_ids))
        .group_by(Unit.property_id)
        .all()
    )
    unit_count_map = {r.property_id: int(r.cnt or 0) for r in unit_counts}
    billing_units = sum((unit_count_map.get(pid) or 0) or 1 for pid in prop_ids)
    from app.services.shield_mode_policy import SHIELD_MODE_ALWAYS_ON

    if SHIELD_MODE_ALWAYS_ON:
        return billing_units, property_count

    shield_prop_ids = [pid for (pid, shield_on) in prop_rows if bool(shield_on)]
    shield_property_count = len(shield_prop_ids)
    return billing_units, shield_property_count


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
    """True if subscription is not the current flat-total model (e.g. multiple lines or odd cent amounts).

    Current model: typically one line with unit_amount = N * $10.00 for N properties (still a multiple of $10).
    Legacy: multiple items, or a single item priced at something not divisible by $10 (e.g. old $1/unit).
    """
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
        cents = int(ua)
        if cents <= 0:
            return True
        if cents % int(SUBSCRIPTION_FLAT_AMOUNT_CENTS) != 0:
            return True
    return False


def _stripe_price_unit_amount_cents(price_obj: object | None) -> int | None:
    """Unit amount in cents from an expanded Stripe Price, a dict-like object, or by retrieving price_* id."""
    if price_obj is None:
        return None
    ua = None
    if isinstance(price_obj, dict):
        ua = price_obj.get("unit_amount")
    else:
        ua = getattr(price_obj, "unit_amount", None)
    if ua is not None:
        try:
            return int(ua)
        except (TypeError, ValueError):
            pass
    pid = None
    if isinstance(price_obj, dict):
        pid = price_obj.get("id")
    else:
        pid = getattr(price_obj, "id", None)
    if isinstance(pid, str) and pid.startswith("price_"):
        import stripe

        try:
            p = stripe.Price.retrieve(pid)
            u = getattr(p, "unit_amount", None)
            return int(u) if u is not None else None
        except Exception:
            return None
    return None


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
    """Create Stripe subscription ($10/mo per unit) if not already created. Idempotent.

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
    total_cents = int(SUBSCRIPTION_FLAT_AMOUNT_CENTS) * int(units)
    create_kwargs: dict = {
        "customer": profile.stripe_customer_id,
        "items": [
            {
                "price_data": {
                    "currency": "usd",
                    # Single flat line: $10 * number of units (quantity=1).
                    "unit_amount": total_cents,
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
                item_id = getattr(item, "id", None)
                if item_id:
                    baseline_item_id = item_id
                    break
        profile.stripe_subscription_id = sub.id
        profile.stripe_subscription_baseline_item_id = baseline_item_id
        profile.stripe_subscription_shield_item_id = None
        db.commit()
        logger.info(
            "Subscription created for profile_id=%s ($10/mo per unit, units=%s, trial=%s)",
            profile.id,
            units,
            allow_trial,
        )
    except stripe.StripeError as e:
        logger.exception("Stripe error creating subscription for profile_id=%s: %s", profile.id, e)
        raise


def _replace_subscription_items_with_flat_total(
    subscription_id: str,
    existing_items: list,
    units: int,
    *,
    owner_profile_id: int | None = None,
    stripe_request_trace: list[dict[str, Any]] | None = None,
) -> object:
    """Stripe modify: remove all current line items and add one recurring line at $10 * units (qty 1)."""
    import stripe

    stripe.api_key = get_settings().stripe_secret_key
    flat_prod_id = _get_or_create_flat_subscription_product_id()
    new_total_cents = int(SUBSCRIPTION_FLAT_AMOUNT_CENTS) * int(units)
    meta: dict[str, str] = {"billing_model": "flat_total"}
    if owner_profile_id is not None:
        meta["owner_profile_id"] = str(owner_profile_id)
    if stripe_request_trace is not None:
        stripe_request_trace.append(
            {
                "stripe_request": "POST https://api.stripe.com/v1/prices",
                "body": {
                    "currency": "usd",
                    "unit_amount": new_total_cents,
                    "recurring": {"interval": "month"},
                    "product": flat_prod_id,
                    "metadata": dict(meta),
                },
            }
        )
    price = stripe.Price.create(
        currency="usd",
        unit_amount=new_total_cents,
        recurring={"interval": "month"},
        product=flat_prod_id,
        metadata=meta,
    )
    mod_items: list = []
    for it in existing_items:
        iid = getattr(it, "id", None)
        if iid:
            mod_items.append({"id": iid, "deleted": True})
    mod_items.append({"price": price.id, "quantity": 1})
    if stripe_request_trace is not None:
        stripe_request_trace.append(
            {
                "stripe_request": f"POST https://api.stripe.com/v1/subscriptions/{subscription_id}",
                "body": {
                    "items": mod_items,
                    "proration_behavior": "none",
                },
            }
        )
    return stripe.Subscription.modify(
        subscription_id,
        items=mod_items,
        proration_behavior="none",
    )


def sync_subscription_quantities(
    db: Session,
    profile: OwnerProfile,
    *,
    stripe_request_trace: list[dict[str, Any]] | None = None,
) -> None:
    """Update Stripe subscription to match account state.

    Single line item: amount = $10 * units (quantity=1). Multi-line (legacy) subs are consolidated here.

    If ``stripe_request_trace`` is a list, append JSON-serializable copies of Stripe API payloads (for client console debugging).
    """
    if not _stripe_enabled() or not profile.stripe_subscription_id:
        return
    units, _shield_units = _count_properties_and_shield(db, profile)

    import stripe

    stripe.api_key = get_settings().stripe_secret_key
    try:
        logger.info(
            "sync_subscription_quantities start profile_id=%s units=%s subscription_id=%s",
            profile.id,
            units,
            profile.stripe_subscription_id,
        )
        if units <= 0:
            sub_id = profile.stripe_subscription_id
            if stripe_request_trace is not None:
                stripe_request_trace.append(
                    {
                        "stripe_request": f"DELETE https://api.stripe.com/v1/subscriptions/{sub_id}",
                        "query": {"prorate": "true"},
                    }
                )
            stripe.Subscription.cancel(sub_id, prorate=True)
            profile.stripe_subscription_id = None
            profile.stripe_subscription_baseline_item_id = None
            profile.stripe_subscription_shield_item_id = None
            db.commit()
            logger.info("Subscription cancelled for profile_id=%s (0 units); billing stopped (prorated).", profile.id)
            return

        sub_id = profile.stripe_subscription_id
        if stripe_request_trace is not None:
            stripe_request_trace.append(
                {
                    "stripe_request": f"GET https://api.stripe.com/v1/subscriptions/{sub_id}",
                    "query": {"expand[]": "items.data.price"},
                }
            )
        sub = stripe.Subscription.retrieve(
            sub_id,
            expand=["items.data.price"],
        )
        raw_items = list(getattr(getattr(sub, "items", None), "data", None) or [])
        actual_ids = {getattr(i, "id", None) for i in raw_items if getattr(i, "id", None)}

        # Stale DB item IDs (e.g. Shield removed in Stripe) caused legacy branch or wrong modifies to fail silently.
        id_dirty = False
        if (
            profile.stripe_subscription_baseline_item_id
            and profile.stripe_subscription_baseline_item_id not in actual_ids
        ):
            profile.stripe_subscription_baseline_item_id = None
            id_dirty = True
        if profile.stripe_subscription_shield_item_id and profile.stripe_subscription_shield_item_id not in actual_ids:
            profile.stripe_subscription_shield_item_id = None
            id_dirty = True
        if id_dirty:
            db.commit()

        if len(raw_items) > 1:
            _replace_subscription_items_with_flat_total(
                profile.stripe_subscription_id,
                raw_items,
                units,
                owner_profile_id=profile.id,
                stripe_request_trace=stripe_request_trace,
            )
            sub2 = stripe.Subscription.retrieve(profile.stripe_subscription_id, expand=["items.data"])
            data2 = list(getattr(getattr(sub2, "items", None), "data", None) or [])
            new_baseline = getattr(data2[0], "id", None) if data2 else None
            profile.stripe_subscription_baseline_item_id = new_baseline
            profile.stripe_subscription_shield_item_id = None
            db.commit()
            logger.info(
                "Subscription consolidated to flat total ($10*units) for profile_id=%s (units=%s)",
                profile.id,
                units,
            )
            return

        if len(raw_items) == 1 and profile.stripe_subscription_shield_item_id:
            profile.stripe_subscription_shield_item_id = None
            db.commit()

        if len(raw_items) == 1 and getattr(raw_items[0], "id", None):
            profile.stripe_subscription_baseline_item_id = raw_items[0].id

        if profile.stripe_subscription_baseline_item_id:
            new_total_cents = int(SUBSCRIPTION_FLAT_AMOUNT_CENTS) * int(units)
            if len(raw_items) == 1:
                po = getattr(raw_items[0], "price", None)
                cur_ua = _stripe_price_unit_amount_cents(po)
                if cur_ua is not None and cur_ua == new_total_cents:
                    if stripe_request_trace is not None:
                        stripe_request_trace.append(
                            {
                                "note": "no_stripe_write",
                                "reason": "subscription_item_unit_amount_already_matches_unit_count",
                                "expected_unit_amount_cents": new_total_cents,
                                "units_billed": units,
                            }
                        )
                    db.commit()
                    return
            flat_prod_id = _get_or_create_flat_subscription_product_id()
            meta = {"owner_profile_id": str(profile.id), "billing_model": "flat_total"}
            if stripe_request_trace is not None:
                stripe_request_trace.append(
                    {
                        "stripe_request": "POST https://api.stripe.com/v1/prices",
                        "body": {
                            "currency": "usd",
                            "unit_amount": new_total_cents,
                            "recurring": {"interval": "month"},
                            "product": flat_prod_id,
                            "metadata": meta,
                        },
                    }
                )
            price = stripe.Price.create(
                currency="usd",
                unit_amount=new_total_cents,
                recurring={"interval": "month"},
                product=flat_prod_id,
                metadata=meta,
            )
            modify_items = [{"id": profile.stripe_subscription_baseline_item_id, "price": price.id, "quantity": 1}]
            if stripe_request_trace is not None:
                stripe_request_trace.append(
                    {
                        "stripe_request": f"POST https://api.stripe.com/v1/subscriptions/{profile.stripe_subscription_id}",
                        "body": {"items": modify_items},
                    }
                )
            stripe.Subscription.modify(
                profile.stripe_subscription_id,
                items=modify_items,
            )
            logger.info("Subscription synced ($10*units) for profile_id=%s (units=%s)", profile.id, units)
            db.commit()
    except stripe.StripeError as e:
        if stripe_request_trace is not None:
            stripe_request_trace.append(
                {
                    "stripe_error": str(e),
                    "stripe_error_code": getattr(e, "code", None),
                    "note": "Stripe rejected a request in this sync (common: API key IP restrictions). Entries after this would be Price.create / Subscription.modify — those were not sent.",
                }
            )
        logger.warning(
            "Stripe error syncing subscription for profile_id=%s (units=%s sub=%s): %s",
            profile.id,
            units,
            profile.stripe_subscription_id,
            e,
            exc_info=True,
        )


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
        "7-day free trial started. Billing is $10/month per unit after the trial. Add a default payment method before the trial ends.",
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
