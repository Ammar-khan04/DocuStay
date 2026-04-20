"""Ledger + audit for guest invitation agreements completed via Dropbox Sign.

`ACTION_AGREEMENT_SIGNED` must be recorded only after the signed PDF is available from Dropbox,
not when the signature request is merely sent (email to guest)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.agreement_signature import AgreementSignature
from app.models.event_ledger import EventLedger
from app.models.invitation import Invitation
from app.models.user import User
from app.services.audit_log import CATEGORY_GUEST_SIGNATURE, create_log
from app.services.event_ledger import ACTION_AGREEMENT_SIGNED, create_ledger_event
from app.services.notifications import send_email


def emit_invitation_agreement_signed_if_dropbox_complete(
    db: Session,
    sig: AgreementSignature,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> bool:
    """
    If this row is a Dropbox Sign flow and we now have the signed PDF bytes, record audit + ledger once.
    Sends the same completion emails as typed /agreements/sign (guest + owner when distinct).
    Returns True if a new ledger row was created.
    """
    if not getattr(sig, "dropbox_sign_request_id", None):
        return False
    if not getattr(sig, "signed_pdf_bytes", None):
        return False
    existing = (
        db.query(EventLedger)
        .filter(
            EventLedger.action_type == ACTION_AGREEMENT_SIGNED,
            EventLedger.target_object_type == "AgreementSignature",
            EventLedger.target_object_id == sig.id,
        )
        .first()
    )
    if existing:
        return False
    code = (sig.invitation_code or "").strip().upper()
    inv = db.query(Invitation).filter(Invitation.invitation_code == code).first()
    if not inv:
        return False
    ua = (user_agent or "").strip()[:400] if user_agent else None
    create_log(
        db,
        CATEGORY_GUEST_SIGNATURE,
        "Agreement signed (Dropbox Sign)",
        f"Guest completed agreement via Dropbox Sign for invitation {code}: {sig.guest_full_name} <{sig.guest_email}>, signature_id={sig.id}.",
        property_id=inv.property_id,
        invitation_id=inv.id,
        actor_email=sig.guest_email,
        ip_address=ip_address,
        user_agent=ua,
        meta={"signature_id": sig.id, "invitation_code": code, "document_id": sig.document_id},
    )
    create_ledger_event(
        db,
        ACTION_AGREEMENT_SIGNED,
        target_object_type="AgreementSignature",
        target_object_id=sig.id,
        property_id=inv.property_id,
        invitation_id=inv.id,
        meta={
            "signature_id": sig.id,
            "invitation_code": code,
            "document_id": sig.document_id,
            "guest_email": sig.guest_email,
            "guest_full_name": sig.guest_full_name,
            "method": "dropbox",
        },
        ip_address=ip_address,
        user_agent=ua,
    )
    # Match typed /agreements/sign: notify guest and property owner when signing is fully complete.
    # Keep invitation pending/ongoing here; POST /accept-invite marks accepted and BURNED after Stay is created.
    owner = db.query(User).filter(User.id == inv.owner_id).first()
    owner_email = (owner.email if owner else None) or None

    subject = f"[DocuStay] Agreement signed for invitation {code}"
    region = sig.region_code or ""
    doc_body = (sig.document_content or "").strip() or ""
    text = (
        f"DocuStay Agreement Signed\n\n"
        f"Invitation: {code}\n"
        f"Region: {region}\n"
        f"Guest: {sig.guest_full_name} <{sig.guest_email}>\n"
        f"Signed At: {sig.signed_at}\n"
        f"IP: {sig.ip_address or '-'}\n\n"
        f"Document ID: {sig.document_id}\n"
        f"Document Hash: {sig.document_hash}\n\n"
        f"{doc_body}\n"
    )
    html = (
        f"<p><strong>DocuStay Agreement Signed</strong></p>"
        f"<p><strong>Invitation:</strong> {code}<br/>"
        f"<strong>Region:</strong> {region}<br/>"
        f"<strong>Guest:</strong> {sig.guest_full_name} &lt;{sig.guest_email}&gt;</p>"
        f"<p><strong>Document ID:</strong> {sig.document_id}<br/>"
        f"<strong>Document Hash:</strong> {sig.document_hash}</p>"
        f"<pre style='white-space:pre-wrap;font-family:ui-monospace,Menlo,monospace'>{doc_body}</pre>"
    )
    try:
        send_email(sig.guest_email, subject, html_content=html, text_content=text)
        if owner_email and owner_email.lower() != sig.guest_email.lower():
            send_email(owner_email, subject, html_content=html, text_content=text)
    except Exception:
        pass
    return True
