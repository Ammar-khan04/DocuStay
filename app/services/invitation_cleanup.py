"""Mark pending invitations that were not accepted in time as expired (status + token_state).
Guest invitations: test_mode uses PENDING_INVITATION_EXPIRE_MINUTES_TEST; otherwise 72 hours.
Manager invitations: expire after MANAGER_INVITE_EXPIRE_DAYS (3 days) via expires_at; this job marks them status='expired'."""
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.invitation import Invitation
from app.models.manager_invitation import ManagerInvitation
from app.config import get_settings
from app.services.audit_log import create_log, CATEGORY_STATUS_CHANGE
from app.services.event_ledger import (
    create_ledger_event,
    ACTION_INVITATION_EXPIRED,
    ACTION_MANAGER_INVITATION_EXPIRED,
)
from app.services.dashboard_alerts import create_alert_for_owner_and_managers, create_alert_for_user

logger = logging.getLogger("uvicorn.error")

PENDING_INVITATION_EXPIRE_HOURS = 72
PENDING_INVITATION_EXPIRE_MINUTES_TEST = 72


def get_invitation_expire_cutoff() -> datetime:
    """Return the cutoff datetime: pending invites with created_at < this are considered expired.
    In test_mode: PENDING_INVITATION_EXPIRE_MINUTES_TEST. Otherwise: 72 hours."""
    now = datetime.now(timezone.utc)
    settings = get_settings()
    if getattr(settings, "test_mode", False):
        return now - timedelta(hours=PENDING_INVITATION_EXPIRE_MINUTES_TEST)
    return now - timedelta(hours=PENDING_INVITATION_EXPIRE_HOURS)


def run_invitation_cleanup_job() -> None:
    """Mark pending GUEST invitations older than the configured window as expired: status='expired', token_state='EXPIRED'.
    Tenant invitations are excluded; DocuStay does not expire tenants.
    
    Fix Bug #5b: Do not expire invitations that have an active Dropbox Sign request.
    These must remain valid until the callback confirms completion or the request is cancelled.
    """
    logger.info("Invitation cleanup job: started")
    db: Session = SessionLocal()
    try:
        from app.models.agreement_signature import AgreementSignature
        threshold = get_invitation_expire_cutoff()
        
        # Invitation codes with a pending Dropbox Sign request (explicit select for IN/NOT IN)
        pending_dropbox_codes = select(AgreementSignature.invitation_code).where(
            AgreementSignature.dropbox_sign_request_id.isnot(None),
            AgreementSignature.signed_pdf_bytes.is_(None),
        )

        invs = db.query(Invitation).filter(
            Invitation.status == "pending",
            Invitation.created_at < threshold,
            Invitation.invitation_kind == "guest",
            Invitation.invitation_code.notin_(pending_dropbox_codes)
        ).all()
        if invs:
            for inv in invs:
                inv.status = "expired"
                inv.token_state = "EXPIRED"
                db.add(inv)
                create_log(
                    db,
                    CATEGORY_STATUS_CHANGE,
                    "Invitation expired (not accepted in time)",
                    f"Background job marked invitation {inv.id} (code {getattr(inv, 'invitation_code', '')}) as expired; status=expired, token_state=EXPIRED.",
                    property_id=getattr(inv, "property_id", None),
                    invitation_id=inv.id,
                    meta={"invitation_id": inv.id, "invitation_code": getattr(inv, "invitation_code", None), "job": "invitation_cleanup"},
                )
                create_ledger_event(
                    db,
                    ACTION_INVITATION_EXPIRED,
                    target_object_type="Invitation",
                    target_object_id=inv.id,
                    property_id=getattr(inv, "property_id", None),
                    invitation_id=inv.id,
                    meta={"invitation_id": inv.id, "invitation_code": getattr(inv, "invitation_code", None), "job": "invitation_cleanup"},
                )
                pid = getattr(inv, "property_id", None)
                if pid:
                    create_alert_for_owner_and_managers(
                        db, pid, "invitation_expired",
                        "Invitation expired",
                        f"Guest invitation (code {getattr(inv, 'invitation_code', '') or inv.id}) was not accepted in time and has been marked expired.",
                        severity="info", invitation_id=inv.id, meta={"invitation_code": getattr(inv, "invitation_code", None)},
                    )
            db.commit()
            logger.info("Invitation cleanup job: marked %d pending guest invitation(s) as expired (status=expired, token_state=EXPIRED).", len(invs))
        else:
            logger.info("Invitation cleanup job: no pending invitations past cutoff, done")
    except Exception as e:
        logger.exception("Invitation cleanup job: failed: %s", e)
    finally:
        db.close()
        logger.info("Invitation cleanup job: finished")


def run_manager_invitation_cleanup_job() -> None:
    """Mark manager invitations with status='pending' and expires_at in the past as status='expired'."""
    logger.info("Manager invitation cleanup job: started")
    db: Session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        invs = db.query(ManagerInvitation).filter(
            ManagerInvitation.status == "pending",
            ManagerInvitation.expires_at < now,
        ).all()
        if invs:
            for inv in invs:
                inv.status = "expired"
                db.add(inv)
                create_log(
                    db,
                    CATEGORY_STATUS_CHANGE,
                    "Manager invitation expired (link not used in time)",
                    f"Background job marked manager invitation {inv.id} (email={inv.email}) as expired.",
                    property_id=inv.property_id,
                    meta={"manager_invitation_id": inv.id, "email": inv.email, "job": "manager_invitation_cleanup"},
                )
                create_ledger_event(
                    db,
                    ACTION_MANAGER_INVITATION_EXPIRED,
                    target_object_type="ManagerInvitation",
                    target_object_id=inv.id,
                    property_id=inv.property_id,
                    meta={"manager_invitation_id": inv.id, "email": inv.email, "job": "manager_invitation_cleanup"},
                )
                create_alert_for_owner_and_managers(
                    db, inv.property_id, "invitation_expired",
                    "Manager invitation expired",
                    f"Manager invitation to {inv.email} was not used in time and has been marked expired.",
                    severity="info", meta={"email": inv.email},
                )
            db.commit()
            logger.info("Manager invitation cleanup job: marked %d pending invitation(s) as expired.", len(invs))
        else:
            logger.info("Manager invitation cleanup job: no pending manager invitations past expiry, done")
    except Exception as e:
        logger.exception("Manager invitation cleanup job: failed: %s", e)
    finally:
        db.close()
        logger.info("Manager invitation cleanup job: finished")
