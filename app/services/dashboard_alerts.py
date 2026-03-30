"""Create in-platform dashboard alerts and log notification attempts. Dashboard alerts are required; email/SMS are optional.

Alerts are written to the dashboard_alerts table in a dedicated session and committed here, so they are always
persisted regardless of the caller's transaction."""
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.dashboard_alert import DashboardAlert
from app.models.notification_attempt import NotificationAttempt
from app.models.user import User
from app.models.owner import Property
from app.models.property_manager_assignment import PropertyManagerAssignment


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


def _persist_alert(
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
    """Create a dashboard alert in a dedicated session and commit so it is always saved to dashboard_alerts."""
    db = SessionLocal()
    try:
        create_dashboard_alert(
            db, user_id, alert_type, title, message,
            severity=severity, property_id=property_id, stay_id=stay_id,
            invitation_id=invitation_id, meta=meta,
        )
        db.commit()
    except Exception as e:
        logging.getLogger(__name__).warning("Failed to persist dashboard alert to dashboard_alerts table: %s", e)
        db.rollback()
        raise
    finally:
        db.close()


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
    """Create dashboard alerts for the property owner and all assigned managers."""
    if property_id is None:
        logging.getLogger(__name__).warning("create_alert_for_owner_and_managers: property_id is None, skipping alerts")
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
    if owner_user_id is not None:
        _persist_alert(
            owner_user_id, alert_type, title, message,
            severity=severity, property_id=property_id, stay_id=stay_id,
            invitation_id=invitation_id, meta=meta,
        )
    for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == property_id).all():
        _persist_alert(
            a.user_id, alert_type, title, message,
            severity=severity, property_id=property_id, stay_id=stay_id,
            invitation_id=invitation_id, meta=meta,
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
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        logging.getLogger(__name__).warning("create_alert_for_property_managers_or_owner: property_id=%s not found", property_id)
        return
    assignments = db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == property_id).all()
    if assignments:
        for a in assignments:
            _persist_alert(
                a.user_id, alert_type, title, message,
                severity=severity, property_id=property_id, stay_id=stay_id,
                invitation_id=invitation_id, meta=meta,
            )
        return
    owner_user_id = _get_owner_user_id(db, prop)
    if owner_user_id is not None:
        _persist_alert(
            owner_user_id, alert_type, title, message,
            severity=severity, property_id=property_id, stay_id=stay_id,
            invitation_id=invitation_id, meta=meta,
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
    """Create a single dashboard alert for one user (e.g. guest) and persist to dashboard_alerts table."""
    _persist_alert(
        user_id, alert_type, title, message,
        severity=severity, property_id=property_id, stay_id=stay_id,
        invitation_id=invitation_id, meta=meta,
    )
