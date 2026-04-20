"""Module G: Stay Timer, legal notifications, and Status Confirmation (stay end reminders)."""
import logging
from datetime import date, timedelta, datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from sqlalchemy import or_
from sqlalchemy.sql import func

logger = logging.getLogger("uvicorn.error")
from app.database import get_background_job_session
from app.models.stay import Stay
from app.models.invitation import Invitation
from app.models.user import User, UserRole
from app.models.agreement_signature import AgreementSignature
from app.models.event_ledger import EventLedger
from app.models.region_rule import RegionRule
from app.models.audit_log import AuditLog
from app.models.owner import OwnerProfile, Property, USAT_TOKEN_STAGED, USAT_TOKEN_RELEASED, OccupancyStatus
from app.models.property_manager_assignment import PropertyManagerAssignment
from app.models.tenant_assignment import TenantAssignment
from app.models.unit import Unit
from app.services.notifications import (
    send_stay_legal_warning,
    send_overstay_alert,
    send_dead_mans_switch_48h_before_to_owner_and_managers,
    send_dead_mans_switch_urgent_today_to_owner_and_managers,
    send_shield_mode_turned_on_notification,
    send_shield_mode_turned_off_notification,
    send_vacant_monitoring_prompt,
    send_vacant_monitoring_flipped,
    send_dms_triggered_set_status_notification,
    send_dms_turned_off_notification,
    send_status_confirmation_daily_reminder_email,
    send_tenant_guest_authorization_ending_notice,
    send_tenant_guest_jurisdiction_threshold_approaching_notice,
    send_guest_authorization_dates_only_email,
)
from app.services.privacy_lanes import is_tenant_lane_stay, is_tenant_lane_invitation
from app.services.audit_log import create_log, CATEGORY_STATUS_CHANGE, CATEGORY_SHIELD_MODE, CATEGORY_DEAD_MANS_SWITCH
from app.services.event_ledger import (
    create_ledger_event,
    ACTION_OVERSTAY_OCCURRED,
    ACTION_SHIELD_MODE_ON,
    ACTION_VACANT_MONITORING_NO_RESPONSE,
    ACTION_GUEST_STAY_APPROACHING_END,
    ACTION_TENANT_GUEST_JURISDICTION_THRESHOLD_APPROACHING,
    ACTION_DMS_48H_ALERT,
    ACTION_DMS_URGENT_TODAY,
    ACTION_DMS_48H_TENANT_LEASE,
    ACTION_DMS_URGENT_TODAY_TENANT_LEASE,
    ACTION_DMS_AUTO_EXECUTED,
)
from app.services.billing import sync_subscription_quantities
from app.services.dashboard_alerts import (
    create_alert_for_owner_and_managers,
    create_alert_for_user,
    create_alert_for_property_managers_or_owner,
)
from app.config import get_settings
from app.services.property_scope import property_is_managed_by_docustay

settings = get_settings()

# Status Confirmation audit titles (for idempotency; internal category remains dead_mans_switch)
DMS_TITLE_48H_BEFORE = "Status Confirmation: 48h before lease end"
DMS_TITLE_URGENT_TODAY = "Status Confirmation: lease ends today"
DMS_TITLE_48H_BEFORE_TENANT_LEASE = "Status Confirmation: 48h before tenant lease end"
DMS_TITLE_URGENT_TODAY_TENANT_LEASE = "Status Confirmation: tenant lease ends today"
DMS_TITLE_NO_RESPONSE_UNKNOWN = "Status Confirmation: no response by deadline – occupancy unknown"
# In-app / email copy: single question for PM or owner
OCCUPANCY_CONFIRM_QUESTION = "Is this unit/property now VACANT or OCCUPIED?"
OCC_PROMPT_RESPOND_DETAIL = (
    f"{OCCUPANCY_CONFIRM_QUESTION} Respond in DocuStay (Vacant or Occupied). "
    "To extend the lease with a new end date, use Lease renewed on the property page after responding."
)
# Legacy idempotency (before rename)
_LEGACY_DMS_AUTO_EXECUTED_TITLE = "Dead Man's Switch: auto-executed"
SHIELD_ACTIVATED_LAST_DAY = "Shield Mode activated (last day of stay)"
# Test mode: effective "lease end" = stay checked_in_at (or created_at) + this duration
DMS_TEST_MODE_MINUTES_AFTER_CREATE = 2
# Test mode: minutes after latest Status Confirmation *notification* (in-app alert or audit log) before occupancy → Unknown
DMS_TEST_MODE_RESPONSE_WINDOW_MINUTES = 5

# Tenant-invited guest authorization ending (separate from property Status Confirmation)
TENANT_NOTICE_GUEST_AUTH_48H = "Tenant notice: guest authorization ends in 2 days"
TENANT_NOTICE_GUEST_AUTH_TODAY = "Tenant notice: guest authorization ends today"
GUEST_NOTICE_AUTH_48H = "Guest notice: authorization ends in 2 days"
GUEST_NOTICE_AUTH_TODAY = "Guest notice: authorization ends today"
# Unified idempotency for guest date-only notice (see run_tenant_lane_guest_stay_ending_notifications)
GUEST_NOTICE_AUTH_END_WINDOW = "Guest notice: stay end within 2 days (informational)"

# Tenant invited guest: jurisdiction threshold approaching (2-day buffer)
TENANT_NOTICE_GUEST_JURISDICTION_THRESHOLD_48H = "Tenant notice: guest stay approaching jurisdiction threshold (2 days)"


def _status_confirmation_eligible_stay(db: Session, stay: Stay) -> bool:
    """Property Status Confirmation applies only to property/management-lane stays (tenant lease), not tenant-invited guests."""
    return not is_tenant_lane_stay(db, stay)


def _deadline_no_response_already_logged(db: Session, stay_id: int) -> bool:
    return _dms_already_logged(db, DMS_TITLE_NO_RESPONSE_UNKNOWN, stay_id=stay_id) or _dms_already_logged(
        db, _LEGACY_DMS_AUTO_EXECUTED_TITLE, stay_id=stay_id
    )


def _guest_end_window_notice_already_sent(db: Session, stay_id: int) -> bool:
    """True if this stay already received the informational guest end-window notice (current or legacy audit title)."""
    return (
        _dms_already_logged(db, GUEST_NOTICE_AUTH_END_WINDOW, stay_id=stay_id)
        or _dms_already_logged(db, GUEST_NOTICE_AUTH_48H, stay_id=stay_id)
        or _dms_already_logged(db, GUEST_NOTICE_AUTH_TODAY, stay_id=stay_id)
    )


def get_overstays(db: Session) -> list[Stay]:
    """Stays whose end date has passed and guest has not checked out or cancelled (overstay). Only includes stays that have been checked into."""
    today = date.today()
    return db.query(Stay).filter(
        Stay.checked_in_at.isnot(None),
        Stay.stay_end_date < today,
        Stay.checked_out_at.is_(None),
        Stay.cancelled_at.is_(None),
    ).all()


def _relationship_owner_user_id_for_stay(db: Session, stay: Stay) -> int | None:
    """Notification relationship owner: prefer stay.invited_by_user_id, else invitation inviter."""
    uid = getattr(stay, "invited_by_user_id", None)
    if uid is not None:
        return uid
    inv_id = getattr(stay, "invitation_id", None)
    if inv_id is None:
        return None
    inv = db.query(Invitation).filter(Invitation.id == inv_id).first()
    return getattr(inv, "invited_by_user_id", None) if inv else None


def send_overstay_alerts_and_log(db: Session) -> None:
    """For each overstay not yet logged: email stakeholders and guest, then append audit log.

    Tenant-lane stays route to the relationship owner (stay.invited_by_user_id, else invitation
    inviter) and the guest only — not the property owner/manager by default. If the stay is
    tenant-lane but no relationship owner with email can be resolved, escalates to the property
    owner/manager path.
    """
    from app.services.display_names import label_for_stay

    overstays = get_overstays(db)
    for stay in overstays:
        if not property_is_managed_by_docustay(db, stay.property_id):
            continue
        # Only act once per stay: skip if we already logged this overstay
        existing = (
            db.query(AuditLog)
            .filter(
                AuditLog.stay_id == stay.id,
                AuditLog.title == "Overstay occurred",
            )
            .first()
        )
        if existing:
            continue

        owner = db.query(User).filter(User.id == stay.owner_id).first()
        guest = db.query(User).filter(User.id == stay.guest_id).first()
        prop = db.query(Property).filter(Property.id == stay.property_id).first()
        if not owner or not guest:
            continue

        guest_name = label_for_stay(db, stay)
        property_name = "Property"
        if prop:
            property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else "Property")
        end_str = stay.stay_end_date.isoformat()

        rel_owner_id = _relationship_owner_user_id_for_stay(db, stay)
        rel_owner = db.query(User).filter(User.id == rel_owner_id).first() if rel_owner_id else None
        tenant_lane = is_tenant_lane_stay(db, stay)
        rel_email = (rel_owner.email or "").strip() if rel_owner else ""
        route_via_relationship_owner = tenant_lane and rel_owner is not None and bool(rel_email)

        try:
            if route_via_relationship_owner:
                send_overstay_alert(
                    rel_owner.email,
                    guest_name=guest_name,
                    stay_end_date=end_str,
                    region_code=stay.region_code or "",
                    is_owner=True,
                    property_name=property_name,
                )
                if (guest.email or "").strip() and (guest.email or "").strip().lower() != rel_email.lower():
                    send_overstay_alert(
                        guest.email,
                        guest_name=guest_name,
                        stay_end_date=end_str,
                        region_code=stay.region_code or "",
                        is_owner=False,
                        property_name=property_name,
                    )
            else:
                send_overstay_alert(
                    owner.email,
                    guest_name=guest_name,
                    stay_end_date=end_str,
                    region_code=stay.region_code or "",
                    is_owner=True,
                    property_name=property_name,
                )
                send_overstay_alert(
                    guest.email,
                    guest_name=guest_name,
                    stay_end_date=end_str,
                    region_code=stay.region_code or "",
                    is_owner=False,
                    property_name=property_name,
                )
        except Exception:
            pass

        event_meta = {"guest_id": stay.guest_id, "owner_id": stay.owner_id, "stay_end_date": end_str}
        if route_via_relationship_owner:
            event_meta["relationship_owner_id"] = rel_owner_id
            event_meta["notification_route"] = "tenant_lane"
            audit_detail = (
                f"Overstay detected: stay {stay.id}, property {stay.property_id}, guest {guest_name}, end date was {end_str}. "
                f"Emails sent to relationship owner (user {rel_owner_id}) and guest."
            )
            guest_alert_message = (
                f"Your stay end date ({end_str}) has passed. Please coordinate with the resident who authorized "
                "your stay to check out or extend."
            )
        else:
            audit_detail = (
                f"Overstay detected: stay {stay.id}, property {stay.property_id}, guest {guest_name}, end date was {end_str}. "
                "Emails sent to owner and guest."
            )
            guest_alert_message = (
                f"Your stay end date ({end_str}) has passed. Please coordinate with the property owner to check out or extend."
            )

        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            "Overstay occurred",
            audit_detail,
            property_id=stay.property_id,
            stay_id=stay.id,
            actor_email=None,
            meta=event_meta,
        )
        create_ledger_event(
            db,
            ACTION_OVERSTAY_OCCURRED,
            target_object_type="Stay",
            target_object_id=stay.id,
            property_id=stay.property_id,
            stay_id=stay.id,
            meta=event_meta,
        )
        if route_via_relationship_owner:
            create_alert_for_user(
                db,
                rel_owner_id,
                "overstay",
                "Overstay occurred",
                f"Stay end date ({end_str}) has passed. Guest {guest_name} has not checked out.",
                severity="urgent",
                property_id=stay.property_id,
                stay_id=stay.id,
                invitation_id=getattr(stay, "invitation_id", None),
                meta={"stay_end_date": end_str, "guest_name": guest_name},
            )
        else:
            create_alert_for_owner_and_managers(
                db, stay.property_id, "overstay",
                "Overstay occurred",
                f"Stay end date ({end_str}) has passed. Guest {guest_name} has not checked out. Emails sent to owner and guest.",
                severity="urgent", stay_id=stay.id, meta={"stay_end_date": end_str, "guest_name": guest_name},
            )
        create_alert_for_user(
            db, stay.guest_id, "overstay",
            "Overstay at " + property_name,
            guest_alert_message,
            severity="urgent", property_id=stay.property_id, stay_id=stay.id, invitation_id=getattr(stay, "invitation_id", None), meta={"stay_end_date": end_str},
        )
        db.commit()


def get_stays_approaching_limit(db: Session, days_before: int | None = None) -> list[Stay]:
    """Stays whose end date is within days_before (default from config) or on final day."""
    days = days_before if days_before is not None else settings.notification_days_before_limit
    threshold = date.today() + timedelta(days=days)
    return db.query(Stay).filter(
        Stay.stay_end_date >= date.today(),
        Stay.stay_end_date <= threshold,
    ).all()


def send_legal_warnings_for_stay(stay: Stay, db: Session, statute_ref: str) -> None:
    """Send email to owner and guest with legal warning (Module G). Also create dashboard alerts."""
    from app.services.display_names import label_for_stay

    if not property_is_managed_by_docustay(db, stay.property_id):
        return
    owner = db.query(User).filter(User.id == stay.owner_id).first()
    guest = db.query(User).filter(User.id == stay.guest_id).first()
    if not owner or not guest:
        return
    guest_name = label_for_stay(db, stay)

    end_str = stay.stay_end_date.isoformat()
    send_stay_legal_warning(
        owner.email,
        guest_name=guest_name,
        stay_end_date=end_str,
        region_code=stay.region_code,
        statute_ref=statute_ref,
        is_owner=True,
    )
    send_stay_legal_warning(
        guest.email,
        guest_name=guest_name,
        stay_end_date=end_str,
        region_code=stay.region_code,
        statute_ref=statute_ref,
        is_owner=False,
    )
    prop = db.query(Property).filter(Property.id == stay.property_id).first()
    property_name = _get_property_name(db, prop)
    create_alert_for_owner_and_managers(
        db, stay.property_id, "nearing_expiration",
        "Stay nearing end date – legal notice",
        f"Stay for {guest_name} at {property_name} ends {end_str}. Regional limits apply ({statute_ref}). Email sent to you and guest.",
        severity="warning", stay_id=stay.id, meta={"stay_end_date": end_str, "statute_ref": statute_ref},
    )
    create_alert_for_user(
        db, stay.guest_id, "nearing_expiration",
        "Stay nearing end date",
        f"Your stay at {property_name} ends {end_str}. Regional limits apply. Please coordinate with the property owner.",
        severity="warning", property_id=stay.property_id, stay_id=stay.id, meta={"stay_end_date": end_str},
    )
    db.commit()


def _dms_already_logged(
    db: Session,
    title: str,
    stay_id: int | None = None,
    property_id: int | None = None,
    since_date: date | None = None,
) -> bool:
    """Return True if we already logged this event (for this stay or this property, optionally since date)."""
    q = db.query(AuditLog).filter(AuditLog.title == title)
    if stay_id is not None:
        q = q.filter(AuditLog.stay_id == stay_id)
    if property_id is not None:
        q = q.filter(AuditLog.property_id == property_id)
    if since_date is not None:
        from datetime import time as dt_time
        start_of_day = datetime.combine(since_date, dt_time.min).replace(tzinfo=timezone.utc)
        q = q.filter(AuditLog.created_at >= start_of_day)
    return q.first() is not None


def _dms_ledger_sent(db: Session, action_type: str, stay_id: int) -> bool:
    """True if an EventLedger row already exists for this Status Confirmation stage and stay."""
    return (
        db.query(EventLedger)
        .filter(EventLedger.action_type == action_type, EventLedger.stay_id == stay_id)
        .first()
        is not None
    )


def _dms_tenant_assignment_ledger_sent(db: Session, action_type: str, tenant_assignment_id: int) -> bool:
    return (
        db.query(EventLedger)
        .filter(
            EventLedger.action_type == action_type,
            EventLedger.target_object_type == "TenantAssignment",
            EventLedger.target_object_id == tenant_assignment_id,
        )
        .first()
        is not None
    )


def _ta_status_confirmation_audit_logged(db: Session, title: str, tenant_assignment_id: int) -> bool:
    for row in (
        db.query(AuditLog)
        .filter(AuditLog.title == title, AuditLog.category == CATEGORY_DEAD_MANS_SWITCH)
        .all()
    ):
        meta = row.meta or {}
        if meta.get("tenant_assignment_id") == tenant_assignment_id:
            return True
    return False


def _tenant_assignment_property_lane_eligible(db: Session, ta: TenantAssignment) -> bool:
    """Status Confirmation for unit tenant lease: owner/manager-issued assignments only (not tenant-private lane)."""
    inviter_id = getattr(ta, "invited_by_user_id", None)
    if inviter_id is None:
        return True
    inviter = db.query(User).filter(User.id == inviter_id).first()
    if not inviter:
        return True
    return inviter.role in (UserRole.owner, UserRole.property_manager)


def _tenant_label_for_assignment(db: Session, ta: TenantAssignment) -> str:
    u = db.query(User).filter(User.id == ta.user_id).first()
    if not u:
        return f"Tenant {ta.user_id}"
    return ((u.full_name or "").strip() or (u.email or "").strip() or f"Tenant {ta.user_id}")


def _unit_has_property_lane_checked_in_stay_ending_on(
    db: Session, unit_id: int, end_date: date
) -> bool:
    """If a checked-in property-lane guest Stay ends the same calendar day on this unit, Stay-based Status Confirmation owns the prompt."""
    for s in (
        db.query(Stay)
        .filter(
            Stay.unit_id == unit_id,
            Stay.stay_end_date == end_date,
            Stay.checked_in_at.isnot(None),
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
        .all()
    ):
        if _status_confirmation_eligible_stay(db, s):
            return True
    return False


def _materialize_tenant_assignment_status_confirmation(
    db: Session,
    *,
    target_end_date: date,
    restrict_property_ids: set[int] | None,
    phase: str,
    occ_prompt_detail: str,
) -> None:
    """48h-before or lease-ends-today for owner/manager tenant unit leases (TenantAssignment without guest Stay)."""
    from app.services.tenant_lease_window import find_invitation_matching_tenant_assignment

    if phase == "48h":
        title = DMS_TITLE_48H_BEFORE_TENANT_LEASE
        ledger_action = ACTION_DMS_48H_TENANT_LEASE
        alert_type = "tenant_lease_48h"
        alert_title = "Tenant lease ending soon — confirm occupancy"
    elif phase == "urgent_today":
        title = DMS_TITLE_URGENT_TODAY_TENANT_LEASE
        ledger_action = ACTION_DMS_URGENT_TODAY_TENANT_LEASE
        alert_type = "tenant_lease_urgent"
        alert_title = "Tenant lease ends today — confirm occupancy"
    else:
        return

    q = (
        db.query(TenantAssignment)
        .join(Unit, Unit.id == TenantAssignment.unit_id)
        .filter(
            TenantAssignment.end_date == target_end_date,
            TenantAssignment.end_date.isnot(None),
        )
    )
    if restrict_property_ids is not None:
        q = q.filter(Unit.property_id.in_(list(restrict_property_ids)))

    for ta in q.all():
        if not _tenant_assignment_property_lane_eligible(db, ta):
            continue
        if _unit_has_property_lane_checked_in_stay_ending_on(db, ta.unit_id, target_end_date):
            continue
        if _dms_tenant_assignment_ledger_sent(db, ledger_action, ta.id):
            continue

        unit = db.query(Unit).filter(Unit.id == ta.unit_id).first()
        prop = db.query(Property).filter(Property.id == unit.property_id).first() if unit else None
        if not unit or not prop:
            continue
        if getattr(prop, "deleted_at", None) is not None:
            continue

        inv = find_invitation_matching_tenant_assignment(db, ta, user_email_lower=None)
        if inv and is_tenant_lane_invitation(db, inv):
            continue

        alert_email_on = True
        if inv is not None:
            alert_email_on = getattr(inv, "dead_mans_switch_alert_email", 1) == 1

        end_str = target_end_date.isoformat()
        tenant_nm = _tenant_label_for_assignment(db, ta)
        prop_nm = _get_property_name(db, prop)
        unit_lbl = (getattr(unit, "unit_label", None) or str(unit.id)).strip()
        place = f"{prop_nm} (Unit {unit_lbl})"

        if _ta_status_confirmation_audit_logged(db, title, ta.id):
            create_ledger_event(
                db,
                ledger_action,
                target_object_type="TenantAssignment",
                target_object_id=ta.id,
                property_id=prop.id,
                unit_id=ta.unit_id,
                invitation_id=inv.id if inv else None,
                actor_user_id=None,
                meta={
                    "message": (
                        f"Tenant lease ends in {'2 days' if phase == '48h' else 'today'} ({end_str}). {occ_prompt_detail}"
                    ),
                    "lease_end_date": end_str,
                    "tenant_assignment_id": ta.id,
                    "ledger_backfill": True,
                },
            )
            db.commit()
            continue

        owner = None
        if getattr(prop, "owner_profile_id", None):
            profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            if profile:
                owner = db.query(User).filter(User.id == profile.user_id).first()

        if not owner or not alert_email_on:
            continue

        owner_email, manager_emails = _get_owner_and_manager_emails(db, prop)
        try:
            if phase == "48h":
                send_dead_mans_switch_48h_before_to_owner_and_managers(
                    owner_email,
                    manager_emails,
                    tenant_nm,
                    place,
                    end_str,
                )
            else:
                send_dead_mans_switch_urgent_today_to_owner_and_managers(
                    owner_email,
                    manager_emails,
                    tenant_nm,
                    place,
                    end_str,
                )
        except Exception:
            pass

        create_log(
            db,
            CATEGORY_DEAD_MANS_SWITCH,
            title,
            f"Tenant assignment {ta.id}: {phase} alert for unit {ta.unit_id}, lease ends {end_str}.",
            property_id=prop.id,
            stay_id=None,
            meta={
                "tenant_assignment_id": ta.id,
                "unit_id": ta.unit_id,
                "lease_end_date": end_str,
                "tenant_user_id": ta.user_id,
            },
        )
        msg_48h = (
            f"{OCCUPANCY_CONFIRM_QUESTION} Tenant lease for {tenant_nm} at {place} ends {end_str}. {occ_prompt_detail}"
        )
        msg_urgent = (
            f"Reminder: {OCCUPANCY_CONFIRM_QUESTION} Tenant lease for {tenant_nm} at {place} ends today ({end_str}). {occ_prompt_detail}"
        )
        create_alert_for_property_managers_or_owner(
            db,
            prop.id,
            alert_type,
            alert_title,
            msg_48h if phase == "48h" else msg_urgent,
            severity="warning" if phase == "48h" else "urgent",
            stay_id=None,
            invitation_id=inv.id if inv else None,
            meta={
                "lease_end_date": end_str,
                "tenant_assignment_id": ta.id,
                "unit_id": ta.unit_id,
                "occupancy_prompt": True,
                "phase": "48h_before" if phase == "48h" else "lease_end_day",
                "tenant_lease": True,
            },
        )
        create_ledger_event(
            db,
            ledger_action,
            target_object_type="TenantAssignment",
            target_object_id=ta.id,
            property_id=prop.id,
            unit_id=ta.unit_id,
            invitation_id=inv.id if inv else None,
            actor_user_id=None,
            meta={
                "message": (
                    f"Tenant lease ends in {'2 days' if phase == '48h' else 'today'} ({end_str}). {occ_prompt_detail}"
                ),
                "lease_end_date": end_str,
                "tenant_assignment_id": ta.id,
            },
        )
        db.commit()


def _get_guest_name(db: Session, stay: Stay) -> str:
    from app.services.display_names import label_for_stay

    return label_for_stay(db, stay)


def _get_property_name(db: Session, prop: Property | None) -> str:
    if not prop:
        return "Property"
    return (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else "Property")


def _get_owner_and_manager_emails(db: Session, prop: Property | None) -> tuple[str, list[str]]:
    """Return (owner_email, manager_emails) for a property."""
    if not prop:
        return ("", [])
    owner_user = None
    if getattr(prop, "owner_profile_id", None):
        profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
        owner_user = db.query(User).filter(User.id == profile.user_id).first() if profile else None
    owner_email = (owner_user.email or "").strip() if owner_user else ""
    manager_emails = [
        (u.email or "").strip()
        for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == prop.id).all()
        for u in [db.query(User).filter(User.id == a.user_id).first()]
        if u and (u.email or "").strip()
    ]
    return (owner_email, manager_emails)


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """Return datetime with UTC tzinfo; if naive, assume UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def dms_test_mode_effective_end_utc(stay: Stay) -> datetime | None:
    """Simulated lease end instant in Status Confirmation test mode: check-in + 2 min, else stay created_at + 2 min."""
    checked_in_at = getattr(stay, "checked_in_at", None)
    if checked_in_at:
        base_dt = _ensure_utc(checked_in_at)
    else:
        created_at = getattr(stay, "created_at", None)
        if not created_at:
            return None
        base_dt = _ensure_utc(created_at)
    if base_dt is None:
        return None
    return base_dt + timedelta(minutes=DMS_TEST_MODE_MINUTES_AFTER_CREATE)


def dms_test_mode_unknown_deadline_utc(db: Session, stay: Stay) -> datetime | None:
    """Test mode: UTC deadline before occupancy may flip to Unknown = latest notification time + response window.

    Notification time is the latest of: in-app ``dms_48h`` / ``dms_urgent`` dashboard alerts for this stay, or
    matching Status Confirmation audit log entries (covers runs before in-app alerts were added to test mode).
    """
    from app.models.dashboard_alert import DashboardAlert

    latest_alert_ts = (
        db.query(func.max(DashboardAlert.created_at))
        .filter(
            DashboardAlert.stay_id == stay.id,
            DashboardAlert.alert_type.in_(["dms_48h", "dms_urgent"]),
        )
        .scalar()
    )
    latest_audit_ts = (
        db.query(func.max(AuditLog.created_at))
        .filter(
            AuditLog.stay_id == stay.id,
            AuditLog.category == CATEGORY_DEAD_MANS_SWITCH,
            AuditLog.title.in_((DMS_TITLE_48H_BEFORE, DMS_TITLE_URGENT_TODAY)),
        )
        .scalar()
    )
    latest: datetime | None = None
    for ts in (latest_alert_ts, latest_audit_ts):
        u = _ensure_utc(ts)
        if u is None:
            continue
        latest = u if latest is None else max(latest, u)
    if latest is None:
        return None
    return latest + timedelta(minutes=DMS_TEST_MODE_RESPONSE_WINDOW_MINUTES)


def _run_dead_mans_switch_job_test_mode(db: Session) -> None:
    """Status Confirmation test mode: simulated lease end + 2 min; in-app + audit notifications; Unknown 5 min after latest notification if no response."""
    now = datetime.now(timezone.utc)
    effective_end_delta = timedelta(minutes=DMS_TEST_MODE_MINUTES_AFTER_CREATE)
    urgent_window_before_end = timedelta(minutes=1)  # "urgent" = last 1 min before effective end

    def dms_enabled(s: Stay) -> bool:
        return getattr(s, "dead_mans_switch_enabled", 0) == 1

    def alert_email(s: Stay) -> bool:
        return getattr(s, "dead_mans_switch_alert_email", 1) == 1

    stays = (
        db.query(Stay)
        .filter(
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
        .all()
    )
    dms_stays = [s for s in stays if dms_enabled(s)]
    logger.info(
        "Status Confirmation job (test mode): started, %d total stays, %d with stay reminders on",
        len(stays),
        len(dms_stays),
    )
    for stay in stays:
        if not dms_enabled(stay):
            continue
        if not _status_confirmation_eligible_stay(db, stay):
            continue
        if not property_is_managed_by_docustay(db, stay.property_id):
            continue
        # Prefer checked_in_at + 2 min (when testing via check-in flow); else created_at + 2 min (accept-invite flow)
        checked_in_at = getattr(stay, "checked_in_at", None)
        if checked_in_at:
            base_dt = _ensure_utc(checked_in_at)
        else:
            created_at = getattr(stay, "created_at", None)
            if not created_at:
                continue
            base_dt = _ensure_utc(created_at)
        effective_end_dt = base_dt + effective_end_delta
        effective_end_date_str = effective_end_dt.date().isoformat()

        # 1) 48h before (test: before effective end, send once)
        if now < effective_end_dt and not _dms_already_logged(db, DMS_TITLE_48H_BEFORE, stay_id=stay.id):
            owner = db.query(User).filter(User.id == stay.owner_id).first()
            prop = db.query(Property).filter(Property.id == stay.property_id).first()
            if owner and alert_email(stay):
                owner_email, manager_emails = _get_owner_and_manager_emails(db, prop)
                try:
                    send_dead_mans_switch_48h_before_to_owner_and_managers(
                        owner_email,
                        manager_emails,
                        _get_guest_name(db, stay),
                        _get_property_name(db, prop),
                        effective_end_date_str,
                    )
                except Exception:
                    pass
                create_log(
                    db,
                    CATEGORY_DEAD_MANS_SWITCH,
                    DMS_TITLE_48H_BEFORE,
                    f"Stay {stay.id}: 48h before (test mode, effective end {effective_end_date_str}) alert sent to owner.",
                    property_id=stay.property_id,
                    stay_id=stay.id,
                    meta={"guest_id": stay.guest_id, "owner_id": stay.owner_id, "dms_test_mode": True},
                )
                db.commit()
                guest_nm = _get_guest_name(db, stay)
                prop_nm = _get_property_name(db, prop)
                create_alert_for_property_managers_or_owner(
                    db,
                    stay.property_id,
                    "dms_48h",
                    "Lease ending soon — confirm occupancy",
                    f"{OCCUPANCY_CONFIRM_QUESTION} Stay/lease for {guest_nm} at {prop_nm} ends {effective_end_date_str}. {OCC_PROMPT_RESPOND_DETAIL}",
                    severity="warning",
                    stay_id=stay.id,
                    invitation_id=getattr(stay, "invitation_id", None),
                    meta={
                        "stay_end_date": effective_end_date_str,
                        "occupancy_prompt": True,
                        "phase": "48h_before",
                        "dms_test_mode": True,
                    },
                )
                db.commit()

        # 2) Urgent today (test: last minute before effective end)
        if (
            effective_end_dt - urgent_window_before_end <= now < effective_end_dt
            and not _dms_already_logged(db, DMS_TITLE_URGENT_TODAY, stay_id=stay.id)
        ):
            owner = db.query(User).filter(User.id == stay.owner_id).first()
            prop = db.query(Property).filter(Property.id == stay.property_id).first()
            if owner and alert_email(stay):
                owner_email, manager_emails = _get_owner_and_manager_emails(db, prop)
                try:
                    send_dead_mans_switch_urgent_today_to_owner_and_managers(
                        owner_email,
                        manager_emails,
                        _get_guest_name(db, stay),
                        _get_property_name(db, prop),
                        effective_end_date_str,
                    )
                except Exception:
                    pass
                create_log(
                    db,
                    CATEGORY_DEAD_MANS_SWITCH,
                    DMS_TITLE_URGENT_TODAY,
                    f"Stay {stay.id}: urgent (test mode, effective end {effective_end_date_str}) alert sent to owner.",
                    property_id=stay.property_id,
                    stay_id=stay.id,
                    meta={"guest_id": stay.guest_id, "owner_id": stay.owner_id, "dms_test_mode": True},
                )
                db.commit()
                guest_nm = _get_guest_name(db, stay)
                prop_nm = _get_property_name(db, prop)
                create_alert_for_property_managers_or_owner(
                    db,
                    stay.property_id,
                    "dms_urgent",
                    "Lease ends today — confirm occupancy",
                    f"Reminder: {OCCUPANCY_CONFIRM_QUESTION} Stay/lease for {guest_nm} at {prop_nm} ends today ({effective_end_date_str}). {OCC_PROMPT_RESPOND_DETAIL}",
                    severity="urgent",
                    stay_id=stay.id,
                    invitation_id=getattr(stay, "invitation_id", None),
                    meta={
                        "stay_end_date": effective_end_date_str,
                        "occupancy_prompt": True,
                        "phase": "lease_end_day",
                        "dms_test_mode": True,
                    },
                )
                db.commit()

        # 3) No confirmation within 5m after latest notification (in-app alert / audit) → occupancy Unknown
        unknown_deadline_dt = dms_test_mode_unknown_deadline_utc(db, stay)
        if unknown_deadline_dt is None or now < unknown_deadline_dt:
            continue
        if getattr(stay, "occupancy_confirmation_response", None) is not None:
            continue
        if getattr(stay, "dead_mans_switch_triggered_at", None) is not None:
            continue
        if _deadline_no_response_already_logged(db, stay.id):
            continue

        owner = db.query(User).filter(User.id == stay.owner_id).first()
        prop = db.query(Property).filter(Property.id == stay.property_id).first()
        guest_name = _get_guest_name(db, stay)
        property_name = _get_property_name(db, prop)

        stay.dead_mans_switch_triggered_at = now
        db.add(stay)

        prev_status = "unknown"
        if prop:
            prev_status = getattr(prop, "occupancy_status", None) or OccupancyStatus.vacant.value
            prop.occupancy_status = OccupancyStatus.unknown.value
            db.add(prop)

        create_log(
            db,
            CATEGORY_DEAD_MANS_SWITCH,
            DMS_TITLE_NO_RESPONSE_UNKNOWN,
            f"Stay {stay.id}: No confirmation within {DMS_TEST_MODE_RESPONSE_WINDOW_MINUTES}m after latest Status Confirmation notification (test mode). Occupancy set to Unknown; reminders continue. No Shield or vacancy changes.",
            property_id=stay.property_id,
            stay_id=stay.id,
            meta={
                "guest_id": stay.guest_id,
                "owner_id": stay.owner_id,
                "stay_end_date": effective_end_date_str,
                "occupancy_status_previous": prev_status,
                "occupancy_status_new": OccupancyStatus.unknown.value,
                "dms_test_mode": True,
            },
        )
        db.commit()
        if owner and alert_email(stay):
            owner_email, manager_emails = _get_owner_and_manager_emails(db, prop)
            try:
                send_dms_triggered_set_status_notification(
                    owner_email,
                    manager_emails,
                    property_name,
                    stay.property_id,
                    guest_name,
                    effective_end_date_str,
                )
            except Exception:
                pass

    # Shield activation (test mode): skip last-day Shield activation tied to real stay_end_date to avoid side effects
    logger.info("Status Confirmation job (test mode): finished")
    return


def run_dms_test_mode_catchup_job() -> None:
    """Test mode only: find stays that checked in >2 min ago but still have stay reminders off, turn them on and run Status Confirmation job. Handles missed one-off job (e.g. server restart)."""
    if not getattr(settings, "dms_test_mode", False):
        logger.debug("Status Confirmation test-mode catchup job: skipped (dms_test_mode=False)")
        return
    logger.info("Status Confirmation test-mode catchup job: started")
    db = get_background_job_session()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=DMS_TEST_MODE_MINUTES_AFTER_CREATE)
        stays = (
            db.query(Stay)
            .filter(
                Stay.checked_in_at.isnot(None),
                Stay.checked_in_at < cutoff,
                Stay.checked_out_at.is_(None),
                Stay.cancelled_at.is_(None),
            )
            .all()
        )
        to_turn_on = [
            s for s in stays
            if getattr(s, "dead_mans_switch_enabled", 0) == 0 and _status_confirmation_eligible_stay(db, s)
        ]
        logger.info(
            "Status Confirmation test-mode catchup job: found %d stay(s) checked in >2min ago, %d with stay reminders off",
            len(stays),
            len(to_turn_on),
        )
        changed = False
        for stay in to_turn_on:
            stay.dead_mans_switch_enabled = 1
            db.add(stay)
            changed = True
        if changed:
            db.commit()
            logger.info(
                "Status Confirmation test-mode catchup job: turned stay reminders on for %d stay(s), running run_dead_mans_switch_job",
                len(to_turn_on),
            )
            run_dead_mans_switch_job(db)
        else:
            logger.info("Status Confirmation test-mode catchup job: no stays needed stay reminders on, done")
    except Exception as e:
        logger.exception("Status Confirmation test-mode catchup job: failed: %s", e)
    finally:
        db.close()
        logger.info("Status Confirmation test-mode catchup job: finished")


def run_dead_mans_switch_job(
    db: Session,
    *,
    reference_date: date | None = None,
    restrict_property_ids: set[int] | None = None,
) -> None:
    """Status Confirmation: 48h before alert, today alert, 48h after auto-execute. When DMS_TEST_MODE=true, simulated end +2 min from check-in/create; Unknown 5 min after latest notification if no response.

    reference_date: calendar \"today\" for eligibility (e.g. browser date on login).
    restrict_property_ids: when set, only process stays on these properties (owner/manager materialization).
    """
    if settings.dms_test_mode:
        logger.info(
            "Status Confirmation job: running test-mode path (effective end = check-in/create + %d min; unknown %d min after latest notification)",
            DMS_TEST_MODE_MINUTES_AFTER_CREATE,
            DMS_TEST_MODE_RESPONSE_WINDOW_MINUTES,
        )
        _run_dead_mans_switch_job_test_mode(db)
        return

    today = reference_date if reference_date is not None else date.today()
    two_days_later = today + timedelta(days=2)
    two_days_ago = today - timedelta(days=2)

    # Stays with stay reminders enabled (integer 1)
    def dms_enabled(s: Stay) -> bool:
        return getattr(s, "dead_mans_switch_enabled", 0) == 1

    def alert_email(s: Stay) -> bool:
        return getattr(s, "dead_mans_switch_alert_email", 1) == 1

    def _stay_scope_filter(q):
        if restrict_property_ids is not None:
            return q.filter(Stay.property_id.in_(list(restrict_property_ids)))
        return q

    occ_prompt_detail = OCC_PROMPT_RESPOND_DETAIL

    # 1) 48 hours before lease end: turn stay reminders on for this stay (prod: not on from creation) and send alert
    for stay in _stay_scope_filter(
        db.query(Stay).filter(
            Stay.checked_in_at.isnot(None),
            Stay.stay_end_date == two_days_later,
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
    ).all():
        if not _status_confirmation_eligible_stay(db, stay):
            continue
        if not property_is_managed_by_docustay(db, stay.property_id):
            continue
        # In prod, stay reminders turn on here (48h before lease end), not at creation or check-in
        if not dms_enabled(stay):
            stay.dead_mans_switch_enabled = 1
            db.add(stay)
            db.commit()
        if _dms_ledger_sent(db, ACTION_DMS_48H_ALERT, stay.id):
            continue
        if _dms_already_logged(db, DMS_TITLE_48H_BEFORE, stay_id=stay.id):
            create_ledger_event(
                db,
                ACTION_DMS_48H_ALERT,
                target_object_type="Stay",
                target_object_id=stay.id,
                property_id=stay.property_id,
                unit_id=getattr(stay, "unit_id", None),
                stay_id=stay.id,
                invitation_id=getattr(stay, "invitation_id", None),
                actor_user_id=None,
                meta={
                    "message": f"Lease or stay ends in 2 days ({stay.stay_end_date.isoformat()}). {occ_prompt_detail}",
                    "stay_end_date": stay.stay_end_date.isoformat(),
                    "ledger_backfill": True,
                },
            )
            db.commit()
            continue
        owner = db.query(User).filter(User.id == stay.owner_id).first()
        prop = db.query(Property).filter(Property.id == stay.property_id).first()
        if not owner or not alert_email(stay):
            continue
        owner_email, manager_emails = _get_owner_and_manager_emails(db, prop)
        try:
            send_dead_mans_switch_48h_before_to_owner_and_managers(
                owner_email,
                manager_emails,
                _get_guest_name(db, stay),
                _get_property_name(db, prop),
                stay.stay_end_date.isoformat(),
            )
        except Exception:
            pass
        create_log(
            db,
            CATEGORY_DEAD_MANS_SWITCH,
            DMS_TITLE_48H_BEFORE,
            f"Stay {stay.id}: 48h before lease end alert sent to owner.",
            property_id=stay.property_id,
            stay_id=stay.id,
            meta={"guest_id": stay.guest_id, "owner_id": stay.owner_id},
        )
        create_alert_for_property_managers_or_owner(
            db,
            stay.property_id,
            "dms_48h",
            "Lease ending soon — confirm occupancy",
            f"{OCCUPANCY_CONFIRM_QUESTION} Stay/lease for {_get_guest_name(db, stay)} at {_get_property_name(db, prop)} ends {stay.stay_end_date.isoformat()}. {occ_prompt_detail}",
            severity="warning",
            stay_id=stay.id,
            invitation_id=getattr(stay, "invitation_id", None),
            meta={
                "stay_end_date": stay.stay_end_date.isoformat(),
                "occupancy_prompt": True,
                "phase": "48h_before",
            },
        )
        create_ledger_event(
            db,
            ACTION_DMS_48H_ALERT,
            target_object_type="Stay",
            target_object_id=stay.id,
            property_id=stay.property_id,
            unit_id=getattr(stay, "unit_id", None),
            stay_id=stay.id,
            invitation_id=getattr(stay, "invitation_id", None),
            actor_user_id=None,
            meta={
                "message": f"Lease or stay ends in 2 days ({stay.stay_end_date.isoformat()}). {occ_prompt_detail}",
                "stay_end_date": stay.stay_end_date.isoformat(),
            },
        )
        db.commit()

    _materialize_tenant_assignment_status_confirmation(
        db,
        target_end_date=two_days_later,
        restrict_property_ids=restrict_property_ids,
        phase="48h",
        occ_prompt_detail=occ_prompt_detail,
    )

    # 1.5) Last day of guest's stay: activate Shield Mode for the property (any checked-in stay ending today)
    stays_ending_today = [
        s
        for s in _stay_scope_filter(
            db.query(Stay).filter(
                Stay.checked_in_at.isnot(None),
                Stay.stay_end_date == today,
                Stay.checked_out_at.is_(None),
                Stay.cancelled_at.is_(None),
            )
        ).all()
        if _status_confirmation_eligible_stay(db, s)
    ]
    property_ids_ending_today = {s.property_id for s in stays_ending_today}
    for prop_id in property_ids_ending_today:
        if restrict_property_ids is not None and prop_id not in restrict_property_ids:
            continue
        if not property_is_managed_by_docustay(db, prop_id):
            continue
        prop = db.query(Property).filter(Property.id == prop_id).first()
        if not prop or getattr(prop, "shield_mode_enabled", 0) == 1:
            continue
        if _dms_already_logged(db, SHIELD_ACTIVATED_LAST_DAY, property_id=prop_id, since_date=today):
            continue
        stay_for_prop = next((s for s in stays_ending_today if s.property_id == prop_id), None)
        if not stay_for_prop:
            continue
        owner = db.query(User).filter(User.id == stay_for_prop.owner_id).first()
        prop.shield_mode_enabled = 1
        db.add(prop)
        create_log(
            db,
            CATEGORY_SHIELD_MODE,
            SHIELD_ACTIVATED_LAST_DAY,
            f"Shield Mode activated for property {prop_id} (last day of stay {stay_for_prop.id}).",
            property_id=prop_id,
            stay_id=stay_for_prop.id,
            meta={"owner_id": stay_for_prop.owner_id},
        )
        pn = _get_property_name(db, prop)
        create_ledger_event(
            db,
            ACTION_SHIELD_MODE_ON,
            target_object_type="Property",
            target_object_id=prop_id,
            property_id=prop_id,
            stay_id=stay_for_prop.id,
            actor_user_id=None,
            meta={
                "property_name": pn,
                "message": f"Shield Mode turned on for {pn} (last day of stay).",
                "reason": "last_day_of_stay",
            },
        )
        db.commit()
        try:
            profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            if profile:
                sync_subscription_quantities(db, profile)
        except Exception:
            pass
        if owner:
            owner_email, manager_emails = _get_owner_and_manager_emails(db, prop)
            try:
                send_shield_mode_turned_on_notification(
                    owner_email,
                    manager_emails,
                    _get_property_name(db, prop),
                    turned_on_by="system (last day of stay)",
                )
            except Exception:
                pass
        create_alert_for_owner_and_managers(
            db, prop_id, "shield_on",
            "Shield Mode activated (last day of stay)",
            f"Shield Mode was turned on for {_get_property_name(db, prop)} (last day of stay).",
            severity="info", stay_id=stay_for_prop.id, meta={},
        )
        db.commit()

    # 2) Lease end date = today (urgent; only for checked-in stays)
    for stay in _stay_scope_filter(
        db.query(Stay).filter(
            Stay.checked_in_at.isnot(None),
            Stay.stay_end_date == today,
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
    ).all():
        if not _status_confirmation_eligible_stay(db, stay):
            continue
        if not property_is_managed_by_docustay(db, stay.property_id):
            continue
        if not dms_enabled(stay):
            continue
        if _dms_ledger_sent(db, ACTION_DMS_URGENT_TODAY, stay.id):
            continue
        if _dms_already_logged(db, DMS_TITLE_URGENT_TODAY, stay_id=stay.id):
            create_ledger_event(
                db,
                ACTION_DMS_URGENT_TODAY,
                target_object_type="Stay",
                target_object_id=stay.id,
                property_id=stay.property_id,
                unit_id=getattr(stay, "unit_id", None),
                stay_id=stay.id,
                invitation_id=getattr(stay, "invitation_id", None),
                actor_user_id=None,
                meta={
                    "message": f"Lease or stay ends today ({stay.stay_end_date.isoformat()}). {occ_prompt_detail}",
                    "stay_end_date": stay.stay_end_date.isoformat(),
                    "ledger_backfill": True,
                },
            )
            db.commit()
            continue
        owner = db.query(User).filter(User.id == stay.owner_id).first()
        prop = db.query(Property).filter(Property.id == stay.property_id).first()
        if not owner or not alert_email(stay):
            continue
        owner_email, manager_emails = _get_owner_and_manager_emails(db, prop)
        try:
            send_dead_mans_switch_urgent_today_to_owner_and_managers(
                owner_email,
                manager_emails,
                _get_guest_name(db, stay),
                _get_property_name(db, prop),
                stay.stay_end_date.isoformat(),
            )
        except Exception:
            pass
        create_log(
            db,
            CATEGORY_DEAD_MANS_SWITCH,
            DMS_TITLE_URGENT_TODAY,
            f"Stay {stay.id}: urgent lease-ends-today alert sent to owner.",
            property_id=stay.property_id,
            stay_id=stay.id,
            meta={"guest_id": stay.guest_id, "owner_id": stay.owner_id},
        )
        create_alert_for_property_managers_or_owner(
            db,
            stay.property_id,
            "dms_urgent",
            "Lease ends today — confirm occupancy",
            f"Reminder: {OCCUPANCY_CONFIRM_QUESTION} Stay/lease for {_get_guest_name(db, stay)} at {_get_property_name(db, prop)} ends today ({stay.stay_end_date.isoformat()}). {occ_prompt_detail}",
            severity="urgent",
            stay_id=stay.id,
            invitation_id=getattr(stay, "invitation_id", None),
            meta={
                "stay_end_date": stay.stay_end_date.isoformat(),
                "occupancy_prompt": True,
                "phase": "lease_end_day",
            },
        )
        create_ledger_event(
            db,
            ACTION_DMS_URGENT_TODAY,
            target_object_type="Stay",
            target_object_id=stay.id,
            property_id=stay.property_id,
            unit_id=getattr(stay, "unit_id", None),
            stay_id=stay.id,
            invitation_id=getattr(stay, "invitation_id", None),
            actor_user_id=None,
            meta={
                "message": f"Lease or stay ends today ({stay.stay_end_date.isoformat()}). {occ_prompt_detail}",
                "stay_end_date": stay.stay_end_date.isoformat(),
            },
        )
        db.commit()

    _materialize_tenant_assignment_status_confirmation(
        db,
        target_end_date=today,
        restrict_property_ids=restrict_property_ids,
        phase="urgent_today",
        occ_prompt_detail=occ_prompt_detail,
    )

    # 3) 48 hours after lease end – occupancy Unknown until PM/owner confirms (no auto-checkout; no Shield; no USAT staging)
    for stay in _stay_scope_filter(
        db.query(Stay).filter(
            Stay.checked_in_at.isnot(None),
            Stay.stay_end_date <= two_days_ago,
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
    ).all():
        if not _status_confirmation_eligible_stay(db, stay):
            continue
        if not property_is_managed_by_docustay(db, stay.property_id):
            continue
        if not dms_enabled(stay):
            continue
        if getattr(stay, "occupancy_confirmation_response", None) is not None:
            continue
        if getattr(stay, "dead_mans_switch_triggered_at", None) is not None:
            continue
        if _deadline_no_response_already_logged(db, stay.id):
            continue

        owner = db.query(User).filter(User.id == stay.owner_id).first()
        prop = db.query(Property).filter(Property.id == stay.property_id).first()
        guest_name = _get_guest_name(db, stay)
        property_name = _get_property_name(db, prop)
        now = datetime.now(timezone.utc)

        stay.dead_mans_switch_triggered_at = now
        db.add(stay)

        prev_status = "unknown"
        if prop:
            prev_status = getattr(prop, "occupancy_status", None) or OccupancyStatus.vacant.value
            prop.occupancy_status = OccupancyStatus.unknown.value
            db.add(prop)

        create_log(
            db,
            CATEGORY_DEAD_MANS_SWITCH,
            DMS_TITLE_NO_RESPONSE_UNKNOWN,
            f"Stay {stay.id}: No confirmation by 48h after lease end. Occupancy set to Unknown; reminders continue. No Shield or vacancy changes.",
            property_id=stay.property_id,
            stay_id=stay.id,
            meta={
                "guest_id": stay.guest_id,
                "owner_id": stay.owner_id,
                "stay_end_date": stay.stay_end_date.isoformat(),
                "occupancy_status_previous": prev_status,
                "occupancy_status_new": OccupancyStatus.unknown.value,
            },
        )
        create_ledger_event(
            db,
            ACTION_DMS_AUTO_EXECUTED,
            target_object_type="Stay",
            target_object_id=stay.id,
            property_id=stay.property_id,
            unit_id=getattr(stay, "unit_id", None),
            stay_id=stay.id,
            invitation_id=getattr(stay, "invitation_id", None),
            actor_user_id=None,
            meta={
                "message": f"No status confirmation after lease end ({stay.stay_end_date.isoformat()}). Occupancy set to Unknown. {occ_prompt_detail}",
                "stay_end_date": stay.stay_end_date.isoformat(),
                "occupancy_status_previous": prev_status,
                "occupancy_status_new": OccupancyStatus.unknown.value,
            },
        )
        db.commit()

        if owner and alert_email(stay):
            owner_email, manager_emails = _get_owner_and_manager_emails(db, prop)
            try:
                send_dms_triggered_set_status_notification(
                    owner_email,
                    manager_emails,
                    property_name,
                    stay.property_id,
                    guest_name,
                    stay.stay_end_date.isoformat(),
                )
            except Exception:
                pass
        create_alert_for_property_managers_or_owner(
            db,
            stay.property_id,
            "dms_executed",
            "Status Confirmation: response needed",
            f"No confirmation within 48h after lease end. Occupancy is Unknown for {_get_property_name(db, prop)} (guest/tenant on file: {guest_name}). {occ_prompt_detail} Reminders will continue.",
            severity="urgent",
            stay_id=stay.id,
            meta={"stay_end_date": stay.stay_end_date.isoformat(), "guest_name": guest_name},
        )
        db.commit()

    # Vacant monitoring audit title (idempotency)
VACANT_MONITORING_FLIPPED = "Vacant monitoring: no response – status UNCONFIRMED"


def run_status_confirmation_materialize_for_user(
    db: Session,
    user: User,
    *,
    client_calendar_date: date | None = None,
) -> None:
    """After owner or property manager authenticates (or opens logs): run Status Confirmation for their properties only (idempotent).

    Uses the client's calendar ``today`` when provided so notifications tied to calendar dates (e.g. lease ends
    in two calendar days → 48h-before alert) materialize on sign-in, not only on server cron.
    """
    if user.role == UserRole.owner:
        profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == user.id).first()
        if not profile:
            return
        prop_ids = {
            r[0]
            for r in db.query(Property.id)
            .filter(Property.owner_profile_id == profile.id, Property.deleted_at.is_(None))
            .all()
        }
    elif user.role == UserRole.property_manager:
        raw_ids = {
            a.property_id
            for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.user_id == user.id).all()
        }
        if not raw_ids:
            prop_ids = set()
        else:
            prop_ids = {
                r[0]
                for r in db.query(Property.id)
                .filter(Property.id.in_(list(raw_ids)), Property.deleted_at.is_(None))
                .all()
            }
    else:
        return
    if not prop_ids:
        return
    ref = client_calendar_date or date.today()
    run_dead_mans_switch_job(db, reference_date=ref, restrict_property_ids=prop_ids)


def run_vacant_monitoring_job(db: Session) -> None:
    """Vacant-unit monitoring: prompt at defined intervals; no response by deadline → flip to UNCONFIRMED, Shield on."""
    interval_days = getattr(settings, "vacant_monitoring_interval_days", 7) or 7
    response_days = getattr(settings, "vacant_monitoring_response_days", 7) or 7
    now = datetime.now(timezone.utc)
    today = now.date()

    vacant_with_monitoring = (
        db.query(Property)
        .filter(
            Property.occupancy_status == OccupancyStatus.vacant.value,
            Property.deleted_at.is_(None),
        )
        .all()
    )
    # Filter by vacant_monitoring_enabled (attribute may not exist on older DBs)
    monitored = [p for p in vacant_with_monitoring if getattr(p, "vacant_monitoring_enabled", 0) == 1]

    for prop in monitored:
        last_prompted = getattr(prop, "vacant_monitoring_last_prompted_at", None)
        response_due = getattr(prop, "vacant_monitoring_response_due_at", None)
        confirmed_at = getattr(prop, "vacant_monitoring_confirmed_at", None)

        # 1) Send prompt if due (never prompted, or interval has elapsed since last prompt)
        due_for_prompt = last_prompted is None or (
            (now - last_prompted).total_seconds() >= interval_days * 24 * 3600
        )
        if due_for_prompt:
            prop.vacant_monitoring_last_prompted_at = now
            prop.vacant_monitoring_response_due_at = now + timedelta(days=response_days)
            db.add(prop)
            db.commit()
            profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            owner = db.query(User).filter(User.id == profile.user_id).first() if profile else None
            if owner and owner.email:
                property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else "Property")
                response_due_date = (now + timedelta(days=response_days)).strftime("%Y-%m-%d")
                try:
                    send_vacant_monitoring_prompt(owner.email, property_name, response_due_date)
                except Exception:
                    pass
            continue  # do not also flip in same run for this property

        # 2) Flip to UNCONFIRMED if response_due_at has passed and no confirmation since last prompt
        if response_due is None:
            continue
        if response_due.tzinfo is None:
            response_due = response_due.replace(tzinfo=timezone.utc)
        if response_due > now:
            continue
        if confirmed_at is not None and last_prompted is not None and confirmed_at >= last_prompted:
            continue
        if _dms_already_logged(db, VACANT_MONITORING_FLIPPED, property_id=prop.id):
            continue

        prev_status = getattr(prop, "occupancy_status", None) or "vacant"
        prop.occupancy_status = OccupancyStatus.unconfirmed.value
        prop.shield_mode_enabled = 1
        prop.vacant_monitoring_response_due_at = None
        db.add(prop)
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            VACANT_MONITORING_FLIPPED,
            f"Vacant monitoring: no response by deadline. Property {prop.id} status {prev_status} -> unconfirmed; Shield Mode on.",
            property_id=prop.id,
            meta={"occupancy_status_previous": prev_status, "occupancy_status_new": OccupancyStatus.unconfirmed.value},
        )
        pn = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else f"Property {prop.id}")
        create_ledger_event(
            db,
            ACTION_SHIELD_MODE_ON,
            target_object_type="Property",
            target_object_id=prop.id,
            property_id=prop.id,
            actor_user_id=None,
            meta={
                "property_name": pn,
                "message": f"Shield Mode turned on for {pn} (vacant monitoring — no response by deadline).",
                "reason": "vacant_monitoring",
            },
        )
        db.commit()
        profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
        try:
            if profile:
                sync_subscription_quantities(db, profile)
        except Exception:
            pass
        owner = db.query(User).filter(User.id == profile.user_id).first() if profile else None
        if owner and owner.email:
            property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else "Property")
            owner_email, manager_emails = _get_owner_and_manager_emails(db, prop)
            try:
                send_vacant_monitoring_flipped(owner.email, property_name)
                send_shield_mode_turned_on_notification(
                    owner_email,
                    manager_emails,
                    property_name,
                    turned_on_by="system (vacant monitoring)",
                )
            except Exception:
                pass
        create_alert_for_owner_and_managers(
            db, prop.id, "vacant_monitoring",
            "Vacant monitoring: no response – status set to Unconfirmed",
            f"No response by deadline. Property status set to Unconfirmed; Shield Mode turned on.",
            severity="warning", meta={"occupancy_status_previous": prev_status},
        )
        db.commit()


DMS_24H_UNCONFIRMED_TO_UNKNOWN = "Status Confirmation: 24h no response – status set to Unknown"
_LEGACY_DMS_24H_UNCONFIRMED_TITLE = "DMS: 24h no response – status set to Unknown"


def _coerce_stay_calendar_date(value: date | datetime) -> date:
    """Stay start/end are stored as dates; some drivers may return datetime — comparisons use calendar date only (no time)."""
    if isinstance(value, datetime):
        return value.date()
    return value


def _guest_archive_invitations_for_user(db: Session, guest_user: User) -> list[Invitation]:
    """Invitations that match _guest_agreement_archive_stay_views: signed agreement, guest lane, no Stay for this user."""
    if guest_user.role != UserRole.guest:
        return []
    guest_email = (guest_user.email or "").strip().lower()
    if not guest_email:
        return []
    stays = db.query(Stay).filter(Stay.guest_id == guest_user.id).all()
    inv_ids_with_stay = {s.invitation_id for s in stays if getattr(s, "invitation_id", None)}
    candidates = (
        db.query(AgreementSignature)
        .filter(
            or_(
                func.lower(AgreementSignature.guest_email) == guest_email,
                AgreementSignature.used_by_user_id == guest_user.id,
            )
        )
        .order_by(AgreementSignature.id.desc())
        .all()
    )
    picked: dict[str, AgreementSignature] = {}
    for sig in candidates:
        code = (sig.invitation_code or "").strip().upper()
        if code and code not in picked:
            picked[code] = sig
    out: list[Invitation] = []
    for sig in picked.values():
        inv = db.query(Invitation).filter(Invitation.invitation_code == sig.invitation_code).first()
        if not inv:
            continue
        if (getattr(inv, "invitation_kind", None) or "").strip().lower() != "guest":
            continue
        if inv.id in inv_ids_with_stay:
            continue
        if (
            db.query(Stay)
            .filter(Stay.guest_id == guest_user.id, Stay.invitation_id == inv.id)
            .first()
        ) is not None:
            continue
        out.append(inv)
    return out


def _materialize_guest_archive_approaching_end_notifications(
    db: Session, guest_user: User, calendar_refs: list[date]
) -> None:
    """Approaching-end notice for guests who only have agreement-on-file (no Stay row). Same date-only window as Stay-based path."""
    for inv in _guest_archive_invitations_for_user(db, guest_user):
        if not property_is_managed_by_docustay(db, inv.property_id):
            continue
        end_cal = _coerce_stay_calendar_date(inv.stay_end_date)
        qualifying_refs = [r for r in calendar_refs if 0 <= (end_cal - r).days <= 2]
        if not qualifying_refs:
            continue
        if (
            db.query(EventLedger)
            .filter(
                EventLedger.action_type == ACTION_GUEST_STAY_APPROACHING_END,
                EventLedger.invitation_id == inv.id,
            )
            .first()
        ):
            continue
        days_left = min((end_cal - r).days for r in qualifying_refs)
        ends_today = any((end_cal - r).days == 0 for r in calendar_refs)
        start_cal = _coerce_stay_calendar_date(inv.stay_start_date)
        start_s = start_cal.isoformat()
        end_s = end_cal.isoformat()
        guest_email = (guest_user.email or "").strip()
        if guest_email:
            try:
                send_guest_authorization_dates_only_email(
                    guest_email, start_s, end_s, ends_today=ends_today
                )
            except Exception:
                pass
        create_ledger_event(
            db,
            ACTION_GUEST_STAY_APPROACHING_END,
            target_object_type="Invitation",
            target_object_id=inv.id,
            property_id=inv.property_id,
            stay_id=None,
            invitation_id=inv.id,
            actor_user_id=None,
            meta={
                "message": f"Your stay runs from {start_s} to {end_s}.",
                "stay_start_date": start_s,
                "stay_end_date": end_s,
                "recipient_user_id": guest_user.id,
                "archive_agreement_only": True,
            },
        )
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            GUEST_NOTICE_AUTH_END_WINDOW,
            f"Invitation {inv.id}: guest notified (archive, dates only) – end within 2 days (days_left={days_left}).",
            property_id=inv.property_id,
            invitation_id=inv.id,
            meta={"guest_id": guest_user.id, "days_left": days_left, "archive_only": True},
        )
        db.commit()


def _guest_end_notification_calendar_refs(*, client_calendar_date: date | None = None) -> list[date]:
    """Reference calendar days for eligibility (date arithmetic only).

    When the app sends ``X-Client-Calendar-Date`` (guest's local YYYY-MM-DD), that anchors the window so it matches the dashboard.
    Otherwise we use ``notification_calendar_iana_tz`` (default US Central), not UTC, so "today" is a normal calendar day for US stays.
    Slop of ±1 day still covers edge cases around the international date line.
    """
    if client_calendar_date is not None:
        anchor = client_calendar_date
    else:
        raw = (get_settings().notification_calendar_iana_tz or "").strip() or "America/Chicago"
        try:
            tz = ZoneInfo(raw)
        except Exception:
            tz = ZoneInfo("America/Chicago")
        anchor = datetime.now(tz).date()
    return [anchor + timedelta(days=k) for k in (-1, 0, 1)]


def run_tenant_lane_guest_stay_ending_notifications(
    db: Session,
    *,
    only_guest_user_id: int | None = None,
    client_calendar_date: date | None = None,
) -> None:
    """Tenant-invited guest stays only: alert tenant; informational email to guest (dates only). Not Status Confirmation.

    Runs with real calendar dates even when DMS_TEST_MODE is true (Status Confirmation uses a short test window; guest-ending notices do not).

    All eligibility uses **calendar dates** only (``datetime.date`` / ISO date strings). Stay ``stay_end_date`` / ``stay_start_date`` are compared as dates, never times.

    When ``client_calendar_date`` is set (from ``X-Client-Calendar-Date``), the guest's local calendar day drives the window so it matches the UI.

    When ``only_guest_user_id`` is set, only stays for that guest user are processed (used on guest login / dashboard for that user).
    """
    calendar_refs = _guest_end_notification_calendar_refs(client_calendar_date=client_calendar_date)
    # SQL prefilter: stays that could fall in the window for some ref (end between min(ref) and max(ref)+2).
    end_lo = min(calendar_refs)
    end_hi = max(calendar_refs) + timedelta(days=2)
    # Guest date reminders are informational (planned authorization dates). Do not require check-in:
    # guests may have a signed agreement and valid dates but never complete in-app check-in / confirmation.
    q = (
        db.query(Stay)
        .filter(
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
            Stay.revoked_at.is_(None),
            Stay.stay_end_date >= end_lo,
            Stay.stay_end_date <= end_hi,
        )
    )
    if only_guest_user_id is not None:
        q = q.filter(Stay.guest_id == only_guest_user_id)
    candidates = q.all()
    for stay in candidates:
        if not property_is_managed_by_docustay(db, stay.property_id):
            continue
        prop = db.query(Property).filter(Property.id == stay.property_id).first()
        property_name = _get_property_name(db, prop)
        guest_user = db.query(User).filter(User.id == stay.guest_id).first()
        guest_email = (guest_user.email or "").strip() if guest_user else ""
        inv = (
            db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
            if getattr(stay, "invitation_id", None)
            else None
        )
        tenant_uid = getattr(stay, "invited_by_user_id", None) or (
            getattr(inv, "invited_by_user_id", None) if inv else None
        )
        tenant = db.query(User).filter(User.id == tenant_uid).first() if tenant_uid else None
        tenant_email = (tenant.email or "").strip() if tenant else ""
        guest_name = _get_guest_name(db, stay)
        end_cal = _coerce_stay_calendar_date(stay.stay_end_date)
        start_cal = _coerce_stay_calendar_date(stay.stay_start_date)
        start_s = start_cal.isoformat()
        end_s = end_cal.isoformat()
        qualifying_refs = [r for r in calendar_refs if 0 <= (end_cal - r).days <= 2]
        if not qualifying_refs:
            continue
        days_left = min((end_cal - r).days for r in qualifying_refs)
        ends_today = any((end_cal - r).days == 0 for r in calendar_refs)
        tenant_two_day = any((end_cal - r).days == 2 for r in calendar_refs)

        if ends_today:
            if not _dms_already_logged(db, TENANT_NOTICE_GUEST_AUTH_TODAY, stay_id=stay.id):
                if tenant_email:
                    try:
                        send_tenant_guest_authorization_ending_notice(
                            tenant_email, guest_name, property_name, start_s, end_s, ends_today=True
                        )
                    except Exception:
                        pass
                if tenant_uid:
                    create_alert_for_user(
                        db,
                        tenant_uid,
                        "guest_stay_ending",
                        "Guest authorization ends today",
                        f"Your guest {guest_name} at {property_name} ends today ({end_s}).",
                        severity="urgent",
                        property_id=stay.property_id,
                        stay_id=stay.id,
                        meta={"stay_end_date": end_s},
                    )
                create_log(
                    db,
                    CATEGORY_STATUS_CHANGE,
                    TENANT_NOTICE_GUEST_AUTH_TODAY,
                    f"Stay {stay.id}: tenant-lane guest authorization ends today; tenant notified.",
                    property_id=stay.property_id,
                    stay_id=stay.id,
                    meta={"guest_id": stay.guest_id, "tenant_user_id": tenant_uid},
                )
                db.commit()
        elif tenant_two_day and is_tenant_lane_stay(db, stay) and not _dms_already_logged(
            db, TENANT_NOTICE_GUEST_AUTH_48H, stay_id=stay.id
        ):
            if tenant_email:
                try:
                    send_tenant_guest_authorization_ending_notice(
                        tenant_email, guest_name, property_name, start_s, end_s, ends_today=False
                    )
                except Exception:
                    pass
            if tenant_uid:
                create_alert_for_user(
                    db,
                    tenant_uid,
                    "guest_stay_ending",
                    "Guest authorization ends in 2 days",
                    f"Your guest {guest_name} at {property_name} is scheduled to end on {end_s}.",
                    severity="warning",
                    property_id=stay.property_id,
                    stay_id=stay.id,
                    meta={"stay_end_date": end_s},
                )
            create_log(
                db,
                CATEGORY_STATUS_CHANGE,
                TENANT_NOTICE_GUEST_AUTH_48H,
                f"Stay {stay.id}: tenant-lane guest authorization ends in 2 days; tenant notified.",
                property_id=stay.property_id,
                stay_id=stay.id,
                meta={"guest_id": stay.guest_id, "tenant_user_id": tenant_uid},
            )
            db.commit()

        if not _guest_end_window_notice_already_sent(db, stay.id):
            if guest_email:
                try:
                    send_guest_authorization_dates_only_email(
                        guest_email, start_s, end_s, ends_today=ends_today
                    )
                except Exception:
                    pass
            if guest_user:
                create_ledger_event(
                    db,
                    ACTION_GUEST_STAY_APPROACHING_END,
                    target_object_type="Stay",
                    target_object_id=stay.id,
                    property_id=stay.property_id,
                    stay_id=stay.id,
                    invitation_id=getattr(stay, "invitation_id", None),
                    actor_user_id=None,
                    meta={
                        "message": f"Your stay runs from {start_s} to {end_s}.",
                        "stay_start_date": start_s,
                        "stay_end_date": end_s,
                        "recipient_user_id": guest_user.id,
                    },
                )
            create_log(
                db,
                CATEGORY_STATUS_CHANGE,
                GUEST_NOTICE_AUTH_END_WINDOW,
                f"Stay {stay.id}: guest notified (dates only) – end within 2 days (days_left={days_left}).",
                property_id=stay.property_id,
                stay_id=stay.id,
                meta={"guest_id": stay.guest_id, "days_left": days_left},
            )
            db.commit()

    if only_guest_user_id is not None:
        u = db.query(User).filter(User.id == only_guest_user_id).first()
        if u and u.role == UserRole.guest:
            _materialize_guest_archive_approaching_end_notifications(db, u, calendar_refs)


def _iter_tenant_jurisdiction_archive_invitations(
    db: Session,
    calendar_refs: list[date],
    *,
    only_tenant_user_id: int | None,
) -> list[Invitation]:
    """Tenant-lane guest invitations with a signed agreement and no Stay row, end date in the jurisdiction-threshold window."""
    end_lo = min(calendar_refs) + timedelta(days=2)
    end_hi = max(calendar_refs) + timedelta(days=2)
    q = db.query(Invitation).filter(
        Invitation.stay_end_date >= end_lo,
        Invitation.stay_end_date <= end_hi,
        Invitation.invited_by_user_id.isnot(None),
    )
    if only_tenant_user_id is not None:
        q = q.filter(Invitation.invited_by_user_id == only_tenant_user_id)
    out: list[Invitation] = []
    for inv in q.all():
        if (getattr(inv, "invitation_kind", None) or "").strip().lower() != "guest":
            continue
        if not is_tenant_lane_invitation(db, inv):
            continue
        if db.query(Stay).filter(Stay.invitation_id == inv.id).first():
            continue
        if not db.query(AgreementSignature).filter(AgreementSignature.invitation_code == inv.invitation_code).first():
            continue
        end_cal = _coerce_stay_calendar_date(inv.stay_end_date)
        if not any((end_cal - r).days == 2 for r in calendar_refs):
            continue
        out.append(inv)
    return out


def _emit_tenant_jurisdiction_threshold_for_archive_invitation(db: Session, inv: Invitation) -> None:
    if not property_is_managed_by_docustay(db, inv.property_id):
        return
    inv_id = inv.id
    already = (
        db.query(EventLedger)
        .filter(
            EventLedger.action_type == ACTION_TENANT_GUEST_JURISDICTION_THRESHOLD_APPROACHING,
            EventLedger.invitation_id == inv_id,
            EventLedger.stay_id.is_(None),
        )
        .first()
    )
    if already:
        return

    tenant_uid = inv.invited_by_user_id
    tenant = db.query(User).filter(User.id == tenant_uid).first() if tenant_uid else None
    tenant_email = (tenant.email or "").strip() if tenant else ""
    prop = db.query(Property).filter(Property.id == inv.property_id).first()
    property_name = _get_property_name(db, prop)
    end_cal = _coerce_stay_calendar_date(inv.stay_end_date)
    end_s = end_cal.isoformat()

    if tenant_email:
        try:
            send_tenant_guest_jurisdiction_threshold_approaching_notice(
                tenant_email, property_name, end_s
            )
        except Exception:
            pass
    if tenant_uid:
        create_alert_for_user(
            db,
            tenant_uid,
            "guest_jurisdiction_threshold",
            "Your guest's stay is approaching the threshold",
            "Your guest's stay is approaching the threshold. You can let it expire naturally, or issue a new invite—when they accept it, it replaces the previous authorization.",
            severity="warning",
            property_id=inv.property_id,
            stay_id=None,
            invitation_id=inv_id,
            meta={"stay_end_date": end_s},
        )

    create_ledger_event(
        db,
        ACTION_TENANT_GUEST_JURISDICTION_THRESHOLD_APPROACHING,
        target_object_type="Invitation",
        target_object_id=inv.id,
        property_id=inv.property_id,
        stay_id=None,
        invitation_id=inv_id,
        actor_user_id=None,
        meta={
            "message": "Your guest's stay is approaching the threshold. You can let it expire naturally, or issue a new invite—when they accept it, it replaces the previous authorization.",
            "stay_end_date": end_s,
            "recipient_user_id": tenant_uid,
            "archive_invitation_only": True,
        },
    )
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        TENANT_NOTICE_GUEST_JURISDICTION_THRESHOLD_48H,
        f"Invitation {inv_id} (archive, no stay): tenant notified guest authorization approaching jurisdiction threshold (2-day buffer).",
        property_id=inv.property_id,
        stay_id=None,
        invitation_id=inv_id,
        meta={"tenant_user_id": tenant_uid, "stay_end_date": end_s},
    )
    db.commit()


def run_tenant_invited_guest_jurisdiction_threshold_notifications(
    db: Session,
    *,
    only_tenant_user_id: int | None = None,
    client_calendar_date: date | None = None,
) -> None:
    """Tenant who invited the guest: dashboard + email alert 2 calendar days before the jurisdiction threshold date.

    Today is a calendar date (not a time). Threshold date is represented by the documented stay end date.
    Covers active Stays and archive-only invitations (signed agreement on file, no Stay row).
    Idempotent per (stay_id, invitation_id) for stays; per invitation with stay_id NULL for archives.
    """
    calendar_refs = _guest_end_notification_calendar_refs(client_calendar_date=client_calendar_date)
    # Pre-filter: anything that could have (end - ref) == 2
    end_lo = min(calendar_refs) + timedelta(days=2)
    end_hi = max(calendar_refs) + timedelta(days=2)
    q = (
        db.query(Stay)
        .filter(
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
            Stay.revoked_at.is_(None),
            Stay.stay_end_date >= end_lo,
            Stay.stay_end_date <= end_hi,
            Stay.invited_by_user_id.isnot(None),
        )
    )
    if only_tenant_user_id is not None:
        q = q.filter(Stay.invited_by_user_id == only_tenant_user_id)
    stays = q.all()
    for s in stays:
        if not property_is_managed_by_docustay(db, s.property_id):
            continue
        # Tenant lane only (tenant-invited guest)
        if not is_tenant_lane_stay(db, s):
            continue
        inv_id = getattr(s, "invitation_id", None)
        if inv_id is None:
            continue
        # Exactly 2-day buffer for at least one reference calendar day
        end_cal = _coerce_stay_calendar_date(s.stay_end_date)
        if not any((end_cal - r).days == 2 for r in calendar_refs):
            continue
        # Idempotent: already emitted for this stay+invitation
        already = (
            db.query(EventLedger)
            .filter(
                EventLedger.action_type == ACTION_TENANT_GUEST_JURISDICTION_THRESHOLD_APPROACHING,
                EventLedger.stay_id == s.id,
                EventLedger.invitation_id == inv_id,
            )
            .first()
        )
        if already:
            continue

        tenant_uid = getattr(s, "invited_by_user_id", None)
        tenant = db.query(User).filter(User.id == tenant_uid).first() if tenant_uid else None
        tenant_email = (tenant.email or "").strip() if tenant else ""
        prop = db.query(Property).filter(Property.id == s.property_id).first()
        property_name = _get_property_name(db, prop)
        end_s = end_cal.isoformat()

        # Email + dashboard alert to tenant inviter
        if tenant_email:
            try:
                send_tenant_guest_jurisdiction_threshold_approaching_notice(
                    tenant_email, property_name, end_s
                )
            except Exception:
                pass
        if tenant_uid:
            create_alert_for_user(
                db,
                tenant_uid,
                "guest_jurisdiction_threshold",
                "Your guest's stay is approaching the threshold",
                "Your guest's stay is approaching the threshold. You can let it expire naturally, or issue a new invite—when they accept it, it replaces the previous authorization.",
                severity="warning",
                property_id=s.property_id,
                stay_id=s.id,
                invitation_id=inv_id,
                meta={"stay_end_date": end_s},
            )

        create_ledger_event(
            db,
            ACTION_TENANT_GUEST_JURISDICTION_THRESHOLD_APPROACHING,
            target_object_type="Stay",
            target_object_id=s.id,
            property_id=s.property_id,
            stay_id=s.id,
            invitation_id=inv_id,
            actor_user_id=None,
            meta={
                "message": "Your guest's stay is approaching the threshold. You can let it expire naturally, or issue a new invite—when they accept it, it replaces the previous authorization.",
                "stay_end_date": end_s,
                "recipient_user_id": tenant_uid,
            },
        )
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            TENANT_NOTICE_GUEST_JURISDICTION_THRESHOLD_48H,
            f"Stay {s.id}: tenant notified guest stay approaching jurisdiction threshold (2-day buffer).",
            property_id=s.property_id,
            stay_id=s.id,
            invitation_id=inv_id,
            meta={"tenant_user_id": tenant_uid, "stay_end_date": end_s},
        )
        db.commit()

    for inv in _iter_tenant_jurisdiction_archive_invitations(
        db, calendar_refs, only_tenant_user_id=only_tenant_user_id
    ):
        _emit_tenant_jurisdiction_threshold_for_archive_invitation(db, inv)


def run_guest_stay_approaching_end_notifications_on_login(
    db: Session,
    guest_user_id: int,
    *,
    client_calendar_date: date | None = None,
) -> None:
    """Login / auth success hook: materialize approaching-end notices for this guest only (idempotent).

    Separate from cron so guests always get in-app ledger rows when they authenticate, even if dashboard polling or background jobs did not run.
    """
    run_tenant_lane_guest_stay_ending_notifications(
        db,
        only_guest_user_id=guest_user_id,
        client_calendar_date=client_calendar_date,
    )


def run_status_confirmation_daily_reminder_job(db: Session) -> None:
    """After initial 'unknown' outcome, remind PM/owner daily until they confirm."""
    today_utc = datetime.now(timezone.utc).date()
    reminder_title = f"Status Confirmation: daily reminder – {today_utc.isoformat()}"
    stays = (
        db.query(Stay)
        .filter(
            Stay.dead_mans_switch_triggered_at.isnot(None),
            Stay.occupancy_confirmation_response.is_(None),
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
        .all()
    )
    for stay in stays:
        if not _status_confirmation_eligible_stay(db, stay):
            continue
        if not getattr(stay, "dead_mans_switch_enabled", 0):
            continue
        trig = _ensure_utc(stay.dead_mans_switch_triggered_at)
        if trig is not None and trig.astimezone(timezone.utc).date() >= today_utc:
            continue
        prop = db.query(Property).filter(Property.id == stay.property_id).first()
        if not prop:
            continue
        if not property_is_managed_by_docustay(db, stay.property_id):
            continue
        if (getattr(prop, "occupancy_status", None) or "").lower() != OccupancyStatus.unknown.value:
            continue
        if _dms_already_logged(db, reminder_title, stay_id=stay.id):
            continue
        if getattr(stay, "dead_mans_switch_alert_email", 1) != 1:
            continue
        guest_name = _get_guest_name(db, stay)
        property_name = _get_property_name(db, prop)
        owner_email, manager_emails = _get_owner_and_manager_emails(db, prop)
        try:
            send_status_confirmation_daily_reminder_email(
                owner_email,
                manager_emails,
                property_name,
                stay.property_id,
                guest_name,
                stay.stay_end_date.isoformat(),
            )
        except Exception:
            pass
        create_log(
            db,
            CATEGORY_DEAD_MANS_SWITCH,
            reminder_title,
            f"Stay {stay.id}: daily Status Confirmation reminder (occupancy unknown until confirmed).",
            property_id=stay.property_id,
            stay_id=stay.id,
        )
        create_alert_for_property_managers_or_owner(
            db,
            stay.property_id,
            "dms_reminder",
            "Reminder: Confirm property status",
            f"Occupancy is still Unknown for {property_name}. {OCCUPANCY_CONFIRM_QUESTION} Please respond Vacant or Occupied for the stay ({guest_name}).",
            severity="warning",
            stay_id=stay.id,
            invitation_id=getattr(stay, "invitation_id", None),
            meta={"stay_end_date": stay.stay_end_date.isoformat(), "occupancy_prompt": True, "phase": "unknown_reminder"},
        )
        db.commit()


def run_dms_24h_unconfirmed_to_unknown_job(db: Session) -> None:
    """24h after Status Confirmation deadline: if owner/manager has not confirmed (vacated/renewed/holdover), set property status to Unknown."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    stays = (
        db.query(Stay)
        .filter(
            Stay.dead_mans_switch_triggered_at.isnot(None),
            Stay.dead_mans_switch_triggered_at <= cutoff,
            Stay.occupancy_confirmation_response.is_(None),
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
        .all()
    )
    for stay in stays:
        prop = db.query(Property).filter(Property.id == stay.property_id).first()
        if not prop:
            continue
        if not property_is_managed_by_docustay(db, stay.property_id):
            continue
        if (getattr(prop, "occupancy_status", None) or "").lower() != OccupancyStatus.unconfirmed.value:
            continue
        if _dms_already_logged(db, DMS_24H_UNCONFIRMED_TO_UNKNOWN, stay_id=stay.id) or _dms_already_logged(
            db, _LEGACY_DMS_24H_UNCONFIRMED_TITLE, stay_id=stay.id
        ):
            continue
        prev_status = getattr(prop, "occupancy_status", None) or "unconfirmed"
        prop.occupancy_status = OccupancyStatus.unknown.value
        db.add(prop)
        create_log(
            db,
            CATEGORY_DEAD_MANS_SWITCH,
            DMS_24H_UNCONFIRMED_TO_UNKNOWN,
            f"Stay {stay.id}: No response within 24h of Status Confirmation deadline. Property {prop.id} status {prev_status} -> unknown.",
            property_id=prop.id,
            stay_id=stay.id,
            meta={"occupancy_status_previous": prev_status, "occupancy_status_new": OccupancyStatus.unknown.value},
        )
        db.commit()
        logger.info(
            "Status Confirmation 24h job: property %s status set to Unknown (stay %s, no response)",
            prop.id,
            stay.id,
        )


def mark_expired_guest_authorizations(db: Session) -> None:
    """Find stays that have ended (stay_end_date < today) without check-out, revocation, or cancellation,
    and create a GuestAuthorizationExpired ledger event for each. Idempotent: only fires once per stay."""
    from app.services.event_ledger import ACTION_GUEST_AUTHORIZATION_EXPIRED, create_ledger_event
    today = date.today()
    expired_stays = db.query(Stay).filter(
        Stay.stay_end_date < today,
        Stay.checked_out_at.is_(None),
        Stay.revoked_at.is_(None),
        Stay.cancelled_at.is_(None),
        Stay.checked_in_at.isnot(None),
    ).all()
    from app.models.event_ledger import EventLedger
    for s in expired_stays:
        if not property_is_managed_by_docustay(db, s.property_id):
            continue
        already = db.query(EventLedger).filter(
            EventLedger.action_type == ACTION_GUEST_AUTHORIZATION_EXPIRED,
            EventLedger.stay_id == s.id,
        ).first()
        if already:
            continue
        create_ledger_event(
            db,
            ACTION_GUEST_AUTHORIZATION_EXPIRED,
            target_object_type="Stay",
            target_object_id=s.id,
            property_id=s.property_id,
            unit_id=s.unit_id,
            stay_id=s.id,
            invitation_id=s.invitation_id,
            meta={"message": "Guest authorization expired", "stay_end_date": str(s.stay_end_date)},
        )
        prop = db.query(Property).filter(Property.id == s.property_id).first()
        property_name = _get_property_name(db, prop)
        create_alert_for_owner_and_managers(
            db, s.property_id, "expired",
            "Guest authorization expired",
            f"Stay end date ({s.stay_end_date}) has passed; guest has not checked out. Authorization is now expired.",
            severity="info", stay_id=s.id, meta={"stay_end_date": str(s.stay_end_date)},
        )
        create_alert_for_user(
            db, s.guest_id, "expired",
            "Stay authorization expired",
            f"Your stay at {property_name} ended on {s.stay_end_date}. Your authorization is now expired. Please coordinate with the property owner if you need to extend.",
            severity="info", property_id=s.property_id, stay_id=s.id, meta={"stay_end_date": str(s.stay_end_date)},
        )
    db.commit()


def run_stay_notification_job() -> None:
    """Run once per day (or on demand): find stays approaching limit, send emails; then detect overstays, email owner+guest and log; then Status Confirmation job; then 24h follow-up."""
    if not settings.notification_cron_enabled:
        return
    db = get_background_job_session()
    try:
        stays = get_stays_approaching_limit(db)
        for stay in stays:
            rule = db.query(RegionRule).filter(RegionRule.region_code == stay.region_code).first()
            statute_ref = rule.statute_reference if rule else stay.region_code
            send_legal_warnings_for_stay(stay, db, statute_ref or stay.region_code)
        send_overstay_alerts_and_log(db)
        mark_expired_guest_authorizations(db)
        run_dead_mans_switch_job(db)
        run_tenant_lane_guest_stay_ending_notifications(db)
        run_tenant_invited_guest_jurisdiction_threshold_notifications(db)
        run_status_confirmation_daily_reminder_job(db)
        run_vacant_monitoring_job(db)
        run_dms_24h_unconfirmed_to_unknown_job(db)
    finally:
        db.close()
