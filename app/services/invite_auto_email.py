"""Send invitation emails when invite rows are created (tenant lease / guest)."""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models.demo_account import is_demo_user_id
from app.models.invitation import Invitation
from app.models.owner import Property
from app.services.audit_log import CATEGORY_STATUS_CHANGE, create_log
from app.services.event_ledger import ACTION_TENANT_PENDING_INVITE_EMAIL_SENT, create_ledger_event
from app.services.invitation_kinds import is_property_invited_tenant_signup_kind, is_tenant_lease_extension_kind
from app.services.notifications import (
    build_invitation_app_url,
    send_guest_invite_email,
    send_tenant_invite_email,
    send_tenant_lease_extension_email,
)

logger = logging.getLogger(__name__)


def auto_email_tenant_invitation_if_addressed(
    db: Session,
    inv: Invitation,
    prop: Property,
    *,
    tenant_display_name: str,
    ip: str | None,
    ua: str | None,
    actor_user_id: int,
    actor_email: str | None,
) -> None:
    """If the invitation has a tenant email, send the registration or lease-extension email. Failures are logged only."""
    if not is_property_invited_tenant_signup_kind(getattr(inv, "invitation_kind", None)):
        return
    em = (inv.guest_email or "").strip().lower()
    if not em or "@" not in em:
        return
    property_name = (prop.name or "").strip() or (f"{prop.street}, {prop.city}" if prop else None) or "Property"
    inviter_id = inv.invited_by_user_id or inv.owner_id
    code = (inv.invitation_code or "").strip().upper()
    try:
        invite_link = build_invitation_app_url(code, is_demo=is_demo_user_id(db, inviter_id))
        if is_tenant_lease_extension_kind(inv.invitation_kind):
            sent = send_tenant_lease_extension_email(
                em,
                invite_link,
                tenant_display_name,
                property_name,
                new_end_date=str(inv.stay_end_date),
            )
        else:
            sent = send_tenant_invite_email(em, invite_link, tenant_display_name, property_name)
    except Exception:
        logger.exception("auto_email_tenant_invitation_if_addressed failed invitation_id=%s", getattr(inv, "id", None))
        return
    if not sent:
        return
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Tenant invitation email sent",
        f"Invite ID {code} emailed to {em} for property {inv.property_id}.",
        property_id=inv.property_id,
        invitation_id=inv.id,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        ip_address=ip,
        user_agent=ua,
        meta={"invitation_code": code, "tenant_email": em},
    )
    create_ledger_event(
        db,
        ACTION_TENANT_PENDING_INVITE_EMAIL_SENT,
        target_object_type="Invitation",
        target_object_id=inv.id,
        property_id=inv.property_id,
        unit_id=inv.unit_id,
        invitation_id=inv.id,
        actor_user_id=actor_user_id,
        meta={
            "message": (
                f"Pending tenant invite: email sent to {em} for {tenant_display_name}. "
                f"Invite ID {code}. Property: {property_name}."
            ),
            "invitation_code": code,
            "tenant_email": em,
            "tenant_name": tenant_display_name,
        },
        ip_address=ip,
        user_agent=ua,
    )


def auto_email_guest_invitation_if_addressed(
    db: Session,
    inv: Invitation,
    prop: Property,
    *,
    guest_display_name: str,
    stay_start: date,
    stay_end: date,
    invited_by_tenant: bool,
    ip: str | None,
    ua: str | None,
    actor_user_id: int,
    actor_email: str | None,
) -> None:
    """Email the guest when a guest invitation is created. Failures are logged only."""
    em = (inv.guest_email or "").strip().lower()
    if not em or "@" not in em:
        return
    property_name = (prop.name or "").strip() or f"{getattr(prop, 'city', '')}, {getattr(prop, 'state', '')}".strip(", ") or f"Property {prop.id}"
    code = (inv.invitation_code or "").strip().upper()
    try:
        invite_link = build_invitation_app_url(code, is_demo=is_demo_user_id(db, inv.invited_by_user_id or inv.owner_id))
        sent = send_guest_invite_email(
            em,
            invite_link,
            guest_display_name,
            property_name,
            str(stay_start),
            str(stay_end),
            invited_by_tenant=invited_by_tenant,
        )
    except Exception:
        logger.exception("auto_email_guest_invitation_if_addressed failed invitation_id=%s", getattr(inv, "id", None))
        return
    if not sent:
        return
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Guest invitation email sent",
        f"Invite ID {code} emailed to {em} for property {inv.property_id}.",
        property_id=inv.property_id,
        invitation_id=inv.id,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        ip_address=ip,
        user_agent=ua,
        meta={"invitation_code": code, "guest_email": em},
    )
