"""Guest invite lifecycle: Dropbox Sign can complete before the guest account exists."""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.agreement_signature import AgreementSignature
from app.models.invitation import Invitation


def guest_invite_awaiting_account_after_sign(db: Session, inv: Invitation | None) -> bool:
    """True if this guest invite was consumed for signing (accepted/BURNED) but the signer has not registered yet.

    We match on invitation_code + inv.guest_email + signature.used_by_user_id IS NULL so only the invited
    email can finish signup; random visitors still see 'already used'.
    """
    if inv is None:
        return False
    if (getattr(inv, "invitation_kind", None) or "guest").strip().lower() != "guest":
        return False
    code = (inv.invitation_code or "").strip().upper()
    guest_email = (getattr(inv, "guest_email", None) or "").strip().lower()
    if not code or not guest_email:
        return False
    return (
        db.query(AgreementSignature)
        .filter(
            AgreementSignature.invitation_code == code,
            AgreementSignature.guest_email == guest_email,
            AgreementSignature.used_by_user_id.is_(None),
        )
        .first()
        is not None
    )


def guest_invitation_signing_started(db: Session, invitation_code: str) -> bool:
    """True if any signature row for this invite has Dropbox or a stored PDF — invite must not be treated as time-expired."""
    code = (invitation_code or "").strip().upper()
    if not code:
        return False
    return (
        db.query(AgreementSignature)
        .filter(
            AgreementSignature.invitation_code == code,
            or_(
                AgreementSignature.signed_pdf_bytes.isnot(None),
                AgreementSignature.dropbox_sign_request_id.isnot(None),
            ),
        )
        .first()
        is not None
    )
