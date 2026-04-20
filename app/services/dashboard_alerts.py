"""Create in-platform dashboard alerts and log notification attempts. Dashboard alerts are required; email/SMS are optional.

Alerts are added to the **caller's** SQLAlchemy session. The caller must ``commit()`` so rows reach ``dashboard_alerts``.
This avoids opening a second pooled connection while a request or background job already holds one (prevents pool
exhaustion when ``pool_size`` is small and ``max_overflow`` is 0, e.g. Supabase session pooler).
"""
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.dashboard_alert import DashboardAlert
from app.models.notification_attempt import NotificationAttempt
from app.models.user import User
from app.models.owner import Property
from app.models.property_manager_assignment import PropertyManagerAssignment
from app.services.property_scope import property_is_managed_by_docustay


def create_dashboard_alert(
    db: Session,
    user_id: int,
    alert_type: str,
    title: str,
    message: str,
    *,
    severity: str = "info",
    property_id: int | None = None,
    stay_id: int | None = None,
    invitation_id: int | None = None,
    meta: dict | None = None,
) -> DashboardAlert:
    """Create one in-platform dashboard alert for a user and add to the given session (caller must commit)."""
    alert = DashboardAlert(
        user_id=user_id,
        alert_type=alert_type,
        title=title,
        message=message,
        severity=severity,
        property_id=property_id,
        stay_id=stay_id,
        invitation_id=invitation_id,
        meta=meta,
    )
    db.add(alert)
    db.flush()  # get alert.id
    log_notification_attempt(db, alert.id, "in_app", success=True)
    return alert


def _add_alerts_for_user_ids_on_session(
    db: Session,
    user_ids: list[int],
    alert_type: str,
    title: str,
    message: str,
    *,
    severity: str = "info",
    property_id: int | None = None,
    stay_id: int | None = None,
    invitation_id: int | None = None,
    meta: dict | None = None,
) -> None:
    """Same alert for many users on the caller's session only (no extra pool checkout)."""
    seen: set[int] = set()
    for uid in user_ids:
        if uid is None or uid in seen:
            continue
        seen.add(uid)
        create_dashboard_alert(
            db,
            uid,
            alert_type,
            title,
            message,
            severity=severity,
            property_id=property_id,
            stay_id=stay_id,
            invitation_id=invitation_id,
            meta=meta,
        )


def log_notification_attempt(
    db: Session,
    dashboard_alert_id: int,
    channel: str,
    success: bool,
    error_message: str | None = None,
) -> None:
    """Log a notification delivery attempt (email, sms, etc.) for repeat attempts and auditing."""
    attempt = NotificationAttempt(
        dashboard_alert_id=dashboard_alert_id,
        channel=channel,
        success=success,
        error_message=error_message,
    )
    db.add(attempt)


def _get_owner_user_id(db: Session, prop: Property | None) -> int | None:
    if not prop or not getattr(prop, "owner_profile_id", None):
        return None
    from app.models.owner import OwnerProfile
    profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
    return profile.user_id if profile else None


def create_alert_for_owner_and_managers(
    db: Session,
    property_id: int,
    alert_type: str,
    title: str,
    message: str,
    *,
    severity: str = "warning",
    stay_id: int | None = None,
    invitation_id: int | None = None,
    meta: dict | None = None,
) -> None:
    """Create dashboard alerts for the property owner and all assigned managers (caller's session; caller commits)."""
    if property_id is None:
        logging.getLogger(__name__).warning("create_alert_for_owner_and_managers: property_id is None, skipping alerts")
        return
    if not property_is_managed_by_docustay(db, property_id):
        return
    prop = db.query(Property).filter(Property.id == property_id).first()
    owner_user_id = _get_owner_user_id(db, prop) if prop else None
    # Fallback: if property not found (e.g. deleted) but we have invitation_id, notify invitation owner so they still see "Tenant accepted"
    if owner_user_id is None and invitation_id is not None:
        from app.models.invitation import Invitation
        inv = db.query(Invitation).filter(Invitation.id == invitation_id).first()
        if inv and getattr(inv, "owner_id", None) is not None:
            owner_user_id = inv.owner_id
            logging.getLogger(__name__).info("create_alert_for_owner_and_managers: using invitation owner_id=%s for alert (property_id=%s)", owner_user_id, property_id)
    if not prop and owner_user_id is None:
        logging.getLogger(__name__).warning("create_alert_for_owner_and_managers: property_id=%s not found and no owner fallback, skipping alerts", property_id)
        return
    if prop and owner_user_id is None:
        logging.getLogger(__name__).warning("create_alert_for_owner_and_managers: no owner for property_id=%s (owner_profile_id=%s), skipping owner alert", property_id, getattr(prop, "owner_profile_id", None))
    recipient_ids: list[int] = []
    if owner_user_id is not None:
        recipient_ids.append(owner_user_id)
    for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == property_id).all():
        recipient_ids.append(a.user_id)
    _add_alerts_for_user_ids_on_session(
        db,
        recipient_ids,
        alert_type,
        title,
        message,
        severity=severity,
        property_id=property_id,
        stay_id=stay_id,
        invitation_id=invitation_id,
        meta=meta,
    )


def create_alert_for_property_managers_or_owner(
    db: Session,
    property_id: int,
    alert_type: str,
    title: str,
    message: str,
    *,
    severity: str = "warning",
    stay_id: int | None = None,
    invitation_id: int | None = None,
    meta: dict | None = None,
) -> None:
    """Status confirmation: notify assigned manager(s) only if any; otherwise the property owner."""
    if property_id is None:
        logging.getLogger(__name__).warning("create_alert_for_property_managers_or_owner: property_id is None, skipping")
        return
    if not property_is_managed_by_docustay(db, property_id):
        return
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        logging.getLogger(__name__).warning("create_alert_for_property_managers_or_owner: property_id=%s not found", property_id)
        return
    assignments = db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == property_id).all()
    if assignments:
        _add_alerts_for_user_ids_on_session(
            db,
            [a.user_id for a in assignments],
            alert_type,
            title,
            message,
            severity=severity,
            property_id=property_id,
            stay_id=stay_id,
            invitation_id=invitation_id,
            meta=meta,
        )
        return
    owner_user_id = _get_owner_user_id(db, prop)
    if owner_user_id is not None:
        create_dashboard_alert(
            db,
            owner_user_id,
            alert_type,
            title,
            message,
            severity=severity,
            property_id=property_id,
            stay_id=stay_id,
            invitation_id=invitation_id,
            meta=meta,
        )


def create_alert_for_user(
    db: Session,
    user_id: int,
    alert_type: str,
    title: str,
    message: str,
    *,
    severity: str = "info",
    property_id: int | None = None,
    stay_id: int | None = None,
    invitation_id: int | None = None,
    meta: dict | None = None,
) -> None:
    """Create a single dashboard alert for one user (e.g. guest). Caller's session; caller commits."""
    if property_id is not None and not property_is_managed_by_docustay(db, property_id):
        return
    create_dashboard_alert(
        db,
        user_id,
        alert_type,
        title,
        message,
        severity=severity,
        property_id=property_id,
        stay_id=stay_id,
        invitation_id=invitation_id,
        meta=meta,
    )
