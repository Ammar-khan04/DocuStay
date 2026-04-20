"""Stripe webhook for billing events. Logs invoice.paid to audit log."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.owner import OwnerProfile
from app.models.user import User
from app.services.audit_log import create_log, CATEGORY_BILLING
from app.services.event_ledger import create_ledger_event, ACTION_BILLING_INVOICE_PAID, ACTION_BILLING_INVOICE_PAYMENT_FAILED

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Stripe webhook events. Verifies signature and logs invoice.paid to audit."""
    settings = get_settings()
    secret = (settings.stripe_webhook_secret or "").strip()
    if not secret:
        raise HTTPException(status_code=501, detail="Stripe webhook not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing stripe-signature")

    import stripe
    stripe.api_key = settings.stripe_secret_key
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}") from e
    except stripe.SignatureVerificationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid signature: {e}") from e

    if event.type == "invoice.paid":
        inv = event.data.object
        meta = getattr(inv, "metadata", None) or {}
        profile_id_str = meta.get("owner_profile_id")
        if not profile_id_str:
            logger.warning("invoice.paid missing owner_profile_id in metadata: %s", inv.id)
            return {"received": True}
        try:
            profile_id = int(profile_id_str)
        except (TypeError, ValueError):
            logger.warning("invoice.paid invalid owner_profile_id: %s", profile_id_str)
            return {"received": True}

        profile = db.query(OwnerProfile).filter(OwnerProfile.id == profile_id).first()
        if not profile:
            logger.warning("invoice.paid profile_id=%s not found", profile_id)
            return {"received": True}
        user = db.query(User).filter(User.id == profile.user_id).first()
        amount_paid = getattr(inv, "amount_paid", 0) or 0
        currency = (getattr(inv, "currency", None) or "usd").upper()
        create_log(
            db,
            CATEGORY_BILLING,
            "Invoice paid",
            f"Invoice {getattr(inv, 'number', inv.id)} paid: ${amount_paid / 100:.2f} {currency}.",
            property_id=None,
            actor_user_id=user.id if user else None,
            actor_email=user.email if user else None,
            meta={"stripe_invoice_id": inv.id, "amount_paid_cents": amount_paid, "currency": currency},
        )
        create_ledger_event(
            db,
            ACTION_BILLING_INVOICE_PAID,
            actor_user_id=user.id if user else None,
            meta={"stripe_invoice_id": inv.id, "amount_paid_cents": amount_paid, "currency": currency, "invoice_number": getattr(inv, "number", str(inv.id))},
        )
        # If this is the onboarding invoice (metadata has onboarding_units), mark profile and create monthly subscription
        if meta.get("onboarding_units") and profile.onboarding_invoice_paid_at is None:
            from datetime import datetime, timezone
            profile.onboarding_invoice_paid_at = datetime.now(timezone.utc)
            logger.info("Set onboarding_invoice_paid_at for profile_id=%s (invoice %s)", profile_id, inv.id)
            db.commit()
            # Create flat monthly subscription now that legacy onboarding invoice is paid
            try:
                from app.services.billing import ensure_subscription
                # Legacy onboarding invoice was paid — start flat subscription without a second free trial
                ensure_subscription(db, profile, user, allow_trial=False)
            except Exception as e:
                logger.warning("Subscription creation failed after onboarding payment (profile_id=%s): %s", profile_id, e)
        else:
            db.commit()
        logger.info("Logged invoice.paid for profile_id=%s invoice=%s", profile_id, inv.id)

    elif event.type == "invoice.payment_failed":
        inv = event.data.object
        meta = getattr(inv, "metadata", None) or {}
        profile_id_str = meta.get("owner_profile_id")
        if not profile_id_str:
            logger.warning("invoice.payment_failed missing owner_profile_id in metadata: %s", inv.id)
            return {"received": True}
        try:
            profile_id = int(profile_id_str)
        except (TypeError, ValueError):
            logger.warning("invoice.payment_failed invalid owner_profile_id: %s", profile_id_str)
            return {"received": True}
        profile = db.query(OwnerProfile).filter(OwnerProfile.id == profile_id).first()
        if not profile:
            logger.warning("invoice.payment_failed profile_id=%s not found", profile_id)
            return {"received": True}
        user = db.query(User).filter(User.id == profile.user_id).first()
        amount_due = getattr(inv, "amount_due", 0) or getattr(inv, "amount_remaining", 0) or 0
        currency = (getattr(inv, "currency", None) or "usd").upper()
        attempt_count = getattr(inv, "attempt_count", None)
        create_log(
            db,
            CATEGORY_BILLING,
            "Payment failed",
            f"Invoice {getattr(inv, 'number', inv.id)} payment failed. Amount due: ${amount_due / 100:.2f} {currency}. Please update your payment method.",
            property_id=None,
            actor_user_id=user.id if user else None,
            actor_email=user.email if user else None,
            meta={"stripe_invoice_id": inv.id, "amount_due_cents": amount_due, "currency": currency, "attempt_count": attempt_count},
        )
        create_ledger_event(
            db,
            ACTION_BILLING_INVOICE_PAYMENT_FAILED,
            actor_user_id=user.id if user else None,
            meta={"stripe_invoice_id": inv.id, "amount_due_cents": amount_due, "currency": currency, "invoice_number": getattr(inv, "number", str(inv.id))},
        )
        db.commit()
        logger.info("Logged invoice.payment_failed for profile_id=%s invoice=%s", profile_id, inv.id)

    return {"received": True}
