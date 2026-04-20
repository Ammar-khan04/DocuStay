"""Agreement generation + signing endpoints for invite flows and owner Master POA."""
import logging
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import get_db
from app.models.invitation import Invitation
from app.models.user import User, UserRole
from app.models.agreement_signature import AgreementSignature
from app.models.owner_poa_signature import OwnerPOASignature
from app.models.property_utility import PropertyAuthorityLetter
from app.models.owner import Property
from app.schemas.agreements import (
    AgreementDocResponse,
    AgreementSignRequest,
    AgreementSignResponse,
    AuthorityLetterDocResponse,
    AuthorityLetterSignRequest,
    OwnerPOADocResponse,
    OwnerPOASignRequest,
    OwnerPOASignatureResponse,
    SignatureStatusResponse,
)
from app.services.agreements import (
    build_invitation_agreement,
    build_owner_poa_document,
    fill_guest_signature_in_content,
    fill_owner_poa_signature_line,
    poa_content_with_signature,
    agreement_content_to_pdf,
)
from app.services.audit_log import create_log, CATEGORY_GUEST_SIGNATURE, CATEGORY_STATUS_CHANGE, CATEGORY_FAILED_ATTEMPT
from app.services.invitation_kinds import TENANT_UNIT_LEASE_KINDS, is_property_invited_tenant_signup_kind
from app.services.event_ledger import create_ledger_event, ACTION_AGREEMENT_SIGNED, ACTION_MASTER_POA_SIGNED, ACTION_AGREEMENT_SIGN_FAILED
from app.services.notifications import send_email
from app.services.dropbox_sign import send_signature_request, get_signed_pdf, get_embedded_sign_url
from app.services.invitation_agreement_ledger import emit_invitation_agreement_signed_if_dropbox_complete
from app.services.invitation_guest_completion import guest_invite_awaiting_account_after_sign
from app.dependencies import require_owner, get_current_user
from app.models.demo_account import is_demo_user_id

router = APIRouter(prefix="/agreements", tags=["agreements"])


@router.get("/invitation/{invitation_code}", response_model=AgreementDocResponse)
def get_invitation_agreement(
    invitation_code: str,
    guest_full_name: str | None = Query(None),
    guest_email: str | None = Query(None),
    db: Session = Depends(get_db),
):
    code = (invitation_code or "").strip().upper()
    if code:
        inv = db.query(Invitation).filter(Invitation.invitation_code == code).first()
        is_tenant_inv = is_property_invited_tenant_signup_kind(getattr(inv, "invitation_kind", None)) if inv else False
        if inv and not is_tenant_inv:
            awaiting = guest_invite_awaiting_account_after_sign(db, inv)
            tok = (getattr(inv, "token_state", None) or "").upper()
            st = (getattr(inv, "status", None) or "").lower()
            if not awaiting and (tok == "BURNED" or st == "accepted"):
                raise HTTPException(status_code=400, detail="Invitation already used")
        # Check for expiration after 72 hours
        from app.services.invitation_cleanup import get_invitation_expire_cutoff
        threshold = get_invitation_expire_cutoff()
        if (
            inv
            and not is_tenant_inv
            and inv.status == "pending"
            and inv.created_at is not None
            and inv.created_at < threshold
        ):
            # Check if there is a pending dropbox sign request before failing
            has_pending_dropbox = db.query(AgreementSignature).filter(
                AgreementSignature.invitation_code == code,
                AgreementSignature.dropbox_sign_request_id.isnot(None),
                AgreementSignature.signed_pdf_bytes.is_(None)
            ).first() is not None
            if not has_pending_dropbox:
                raise HTTPException(status_code=400, detail="This invite has expired. Please contact your host to request a new one.")
        if inv and inv.status == "expired":
            raise HTTPException(status_code=400, detail="This invite has expired. Please contact your host to request a new one.")
    doc = build_invitation_agreement(db, invitation_code=invitation_code, guest_full_name=guest_full_name)
    if not doc:
        logging.getLogger("uvicorn.error").warning(
            "Agreement lookup 404: invitation_code=%r (check: code exists, status pending/ongoing, guest=STAGED or tenant)",
            (invitation_code or "").strip().upper(),
        )
        raise HTTPException(status_code=404, detail="Invitation not found or not pending")

    content = doc.content
    already_signed = False
    signed_at = None
    signed_by = None
    signature_id = None
    has_dropbox_signed_pdf = False

    email_clean = guest_email.strip().lower() if guest_email else ""
    if email_clean:
        try:
            sig = (
                db.query(AgreementSignature)
                .filter(
                    AgreementSignature.invitation_code == invitation_code.strip().upper(),
                    AgreementSignature.guest_email == email_clean,
                )
                .order_by(AgreementSignature.signed_at.desc())
                .first()
            )
            if sig:
                already_signed = True
                signed_at = sig.signed_at
                signed_by = sig.typed_signature
                signature_id = sig.id
                # Only true when we have the actual signed PDF from Dropbox (not just "sent to Dropbox")
                if sig.signed_pdf_bytes:
                    has_dropbox_signed_pdf = True
                elif getattr(sig, "dropbox_sign_request_id", None):
                    pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
                    if pdf_bytes:
                        sig.signed_pdf_bytes = pdf_bytes
                        emit_invitation_agreement_signed_if_dropbox_complete(db, sig)
                        db.commit()
                        has_dropbox_signed_pdf = True
                    else:
                        has_dropbox_signed_pdf = False
                else:
                    has_dropbox_signed_pdf = False
                date_str = sig.signed_at.strftime("%Y-%m-%d") if sig.signed_at else ""
                content = fill_guest_signature_in_content(doc.content, sig.typed_signature, date_str, getattr(sig, "ip_address", None))
        except Exception:
            logging.getLogger("uvicorn.error").exception(
                "get_invitation_agreement: failed loading signature/Dropbox state for code=%r",
                (invitation_code or "").strip().upper(),
            )

    return AgreementDocResponse(
        document_id=doc.document_id,
        region_code=doc.region_code,
        title=doc.title,
        content=content,
        document_hash=doc.document_hash,
        property_address=doc.property_address,
        stay_start_date=doc.stay_start_date,
        stay_end_date=doc.stay_end_date,
        host_name=doc.host_name,
        already_signed=already_signed,
        signed_at=signed_at,
        signed_by=signed_by,
        signature_id=signature_id,
        has_dropbox_signed_pdf=has_dropbox_signed_pdf,
    )


@router.get("/invitation/{invitation_code}/pdf")
def get_invitation_agreement_pdf(
    invitation_code: str,
    guest_full_name: str | None = Query(None),
    guest_email: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Return the agreement as a PDF. If guest_email is provided and a signature exists, the PDF includes the signature."""
    doc = build_invitation_agreement(db, invitation_code=invitation_code, guest_full_name=guest_full_name)
    if not doc:
        raise HTTPException(status_code=404, detail="Invitation not found or not pending")

    content = doc.content
    email_clean = guest_email.strip().lower() if guest_email else ""
    if email_clean:
        sig = (
            db.query(AgreementSignature)
            .filter(
                AgreementSignature.invitation_code == invitation_code.strip().upper(),
                AgreementSignature.guest_email == email_clean,
            )
            .order_by(AgreementSignature.signed_at.desc())
            .first()
        )
        if sig:
            date_str = sig.signed_at.strftime("%Y-%m-%d") if sig.signed_at else ""
            content = fill_guest_signature_in_content(doc.content, sig.typed_signature, date_str, getattr(sig, "ip_address", None))

    pdf_bytes = agreement_content_to_pdf(doc.title, content)
    filename = f"DocuStay-Agreement-{invitation_code.strip().upper()}.pdf"
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'})


@router.get("/invitation/{invitation_code}/demo-stored-unsigned-pdf")
def get_demo_stored_unsigned_invitation_pdf(invitation_code: str, db: Session = Depends(get_db)):
    """Public: unsigned guest agreement PDF for demo-originated invites (generated on demand; URL kept for clients)."""
    code = (invitation_code or "").strip().upper()
    inv = db.query(Invitation).filter(Invitation.invitation_code == code).first()
    if not inv or (getattr(inv, "invitation_kind", None) or "guest").strip().lower() != "guest":
        raise HTTPException(status_code=404, detail="Invitation not found")
    from app.services.demo_static_docs import build_demo_unsigned_guest_agreement_pdf_bytes

    raw = build_demo_unsigned_guest_agreement_pdf_bytes(db, inv)
    if not raw:
        raise HTTPException(status_code=404, detail="Unsigned agreement not available for this invitation")
    filename = f"DocuStay-Guest-Agreement-Unsigned-{code}.pdf"
    return Response(
        content=raw,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/demo/unsigned-poa")
def get_demo_unsigned_poa_pdf(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Authenticated demo owners only: unsigned Master POA PDF (generated on demand)."""
    if current_user.role != UserRole.owner or not is_demo_user_id(db, current_user.id):
        raise HTTPException(status_code=403, detail="Demo owner access only")
    from app.services.demo_static_docs import build_demo_owner_unsigned_poa_pdf_bytes

    pdf_bytes = build_demo_owner_unsigned_poa_pdf_bytes(db, current_user)
    if not pdf_bytes:
        raise HTTPException(status_code=404, detail="Unsigned POA PDF not available")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="DocuStay-Master-POA-Unsigned-Demo.pdf"'},
    )


@router.post("/sign", response_model=AgreementSignResponse)
def sign_invitation_agreement(
    req: Request,
    data: AgreementSignRequest,
    db: Session = Depends(get_db),
):
    code = (data.invitation_code or "").strip().upper()
    inv = db.query(Invitation).filter(
        Invitation.invitation_code == code,
        Invitation.status.in_(["pending", "ongoing", "accepted", "expired"]),
        or_(
            Invitation.invitation_kind.in_(tuple(TENANT_UNIT_LEASE_KINDS)),
            Invitation.token_state != "BURNED",
        ),
    ).first()
    if not inv:
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Agreement sign: invalid or expired invitation",
            f"Sign attempt with invalid or expired invitation code: {code}.",
            property_id=None,
            invitation_id=None,
            actor_email=data.guest_email,
            ip_address=req.client.host if req.client else None,
            user_agent=(req.headers.get("user-agent") or "").strip() or None,
            meta={"invitation_code_attempted": code},
        )
        create_ledger_event(
            db,
            ACTION_AGREEMENT_SIGN_FAILED,
            meta={"invitation_code_attempted": code, "reason": "invalid_or_expired_invitation"},
            ip_address=req.client.host if req.client else None,
            user_agent=(req.headers.get("user-agent") or "").strip() or None,
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired invitation code")

    # Check for expiration after 72 hours
    is_tenant_inv = is_property_invited_tenant_signup_kind(getattr(inv, "invitation_kind", None))
    if not is_tenant_inv:
        from app.services.invitation_cleanup import get_invitation_expire_cutoff
        threshold = get_invitation_expire_cutoff()
        if inv.status == "expired" or (
            inv.status == "pending"
            and inv.created_at is not None
            and inv.created_at < threshold
        ):
            # Check if there is a pending dropbox sign request before failing
            has_pending_dropbox = db.query(AgreementSignature).filter(
                AgreementSignature.invitation_code == code,
                AgreementSignature.dropbox_sign_request_id.isnot(None),
                AgreementSignature.signed_pdf_bytes.is_(None)
            ).first() is not None
            if not has_pending_dropbox:
                raise HTTPException(status_code=400, detail="This invite has expired. Please contact your host to request a new one.")

    doc = build_invitation_agreement(db, invitation_code=code, guest_full_name=data.guest_full_name)
    if not doc:
        raise HTTPException(status_code=400, detail="Agreement could not be generated")
    if (data.document_hash or "").strip().lower() != doc.document_hash.lower():
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Agreement sign: document hash mismatch",
            f"Sign attempt with outdated document hash for invitation {code}. Stale agreement copy.",
            property_id=inv.property_id,
            invitation_id=inv.id,
            actor_email=data.guest_email,
            ip_address=req.client.host if req.client else None,
            user_agent=(req.headers.get("user-agent") or "").strip() or None,
            meta={"invitation_code": code, "expected_hash": doc.document_hash},
        )
        create_ledger_event(
            db,
            ACTION_AGREEMENT_SIGN_FAILED,
            target_object_type="Invitation",
            target_object_id=inv.id,
            property_id=inv.property_id,
            invitation_id=inv.id,
            meta={"invitation_code": code, "expected_hash": doc.document_hash, "reason": "document_hash_mismatch"},
            ip_address=req.client.host if req.client else None,
            user_agent=(req.headers.get("user-agent") or "").strip() or None,
        )
        db.commit()
        raise HTTPException(status_code=409, detail="Agreement has changed. Please reopen and sign again.")

    ip = (data.ip_address and data.ip_address.strip()[:64]) or (req.client.host if req.client else None) or None
    ua = (req.headers.get("user-agent") or "").strip() or None

    sig = AgreementSignature(
        invitation_code=code,
        region_code=doc.region_code,
        guest_email=str(data.guest_email).strip().lower(),
        guest_full_name=data.guest_full_name.strip(),
        typed_signature=data.typed_signature.strip(),
        signature_method="typed",
        acks_read=data.acks.read,
        acks_temporary=data.acks.temporary,
        acks_vacate=data.acks.vacate,
        acks_electronic=data.acks.electronic,
        document_id=doc.document_id,
        document_title=doc.title,
        document_hash=doc.document_hash,
        document_content=doc.content,
        ip_address=ip,
        user_agent=ua[:400] if ua else None,
    )
    db.add(sig)
    db.commit()
    db.refresh(sig)

    date_str = sig.signed_at.strftime("%Y-%m-%d") if sig.signed_at else ""
    content_with_sig = fill_guest_signature_in_content(doc.content, sig.typed_signature, date_str, sig.ip_address)
    sig.signed_pdf_bytes = agreement_content_to_pdf(doc.title, content_with_sig)
    db.commit()

    create_log(
        db,
        CATEGORY_GUEST_SIGNATURE,
        "Agreement signed",
        f"Guest signed agreement for invitation {code}: {sig.guest_full_name} <{sig.guest_email}>, signature_id={sig.id}.",
        property_id=inv.property_id,
        invitation_id=inv.id,
        actor_email=sig.guest_email,
        ip_address=ip,
        user_agent=ua,
        meta={"signature_id": sig.id, "invitation_code": code, "document_id": doc.document_id},
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
            "document_id": doc.document_id,
            "guest_email": sig.guest_email,
            "guest_full_name": sig.guest_full_name,
        },
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()

    owner = db.query(User).filter(User.id == inv.owner_id).first()
    owner_email = (owner.email if owner else None) or None
    subject = f"[DocuStay] Agreement signed for invitation {code}"

    text = (
        f"DocuStay Agreement Signed\n\n"
        f"Invitation: {code}\n"
        f"Region: {doc.region_code}\n"
        f"Guest: {sig.guest_full_name} <{sig.guest_email}>\n"
        f"Signed At: {sig.signed_at}\n"
        f"IP: {sig.ip_address or '-'}\n\n"
        f"Document ID: {doc.document_id}\n"
        f"Document Hash: {doc.document_hash}\n\n"
        f"{doc.content}\n"
    )
    html = (
        f"<p><strong>DocuStay Agreement Signed</strong></p>"
        f"<p><strong>Invitation:</strong> {code}<br/>"
        f"<strong>Region:</strong> {doc.region_code}<br/>"
        f"<strong>Guest:</strong> {sig.guest_full_name} &lt;{sig.guest_email}&gt;</p>"
        f"<p><strong>Document ID:</strong> {doc.document_id}<br/>"
        f"<strong>Document Hash:</strong> {doc.document_hash}</p>"
        f"<pre style='white-space:pre-wrap;font-family:ui-monospace,Menlo,monospace'>{doc.content}</pre>"
    )

    # Fire-and-forget: sending failures should not block signature recording.
    try:
        send_email(sig.guest_email, subject, html_content=html, text_content=text)
        if owner_email and owner_email.lower() != sig.guest_email.lower():
            send_email(owner_email, subject, html_content=html, text_content=text)
    except Exception:
        pass

    return AgreementSignResponse(signature_id=sig.id)


@router.post("/sign-with-dropbox", response_model=AgreementSignResponse)
def sign_invitation_agreement_with_dropbox(
    req: Request,
    data: AgreementSignRequest,
    db: Session = Depends(get_db),
):
    """Record signature and send the agreement to Dropbox Sign. Signer receives email to sign; signed PDF available once complete."""
    code = (data.invitation_code or "").strip().upper()
    inv = db.query(Invitation).filter(
        Invitation.invitation_code == code,
        Invitation.status.in_(["pending", "ongoing", "accepted"]),
        or_(
            Invitation.invitation_kind.in_(tuple(TENANT_UNIT_LEASE_KINDS)),
            Invitation.token_state != "BURNED",
        ),
    ).first()
    if not inv:
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Agreement sign (Dropbox): invalid or expired invitation",
            f"Sign attempt with invalid or expired invitation code: {code}.",
            property_id=None,
            invitation_id=None,
            actor_email=data.guest_email,
            ip_address=req.client.host if req.client else None,
            user_agent=(req.headers.get("user-agent") or "").strip() or None,
            meta={"invitation_code_attempted": code},
        )
        create_ledger_event(
            db,
            ACTION_AGREEMENT_SIGN_FAILED,
            meta={"invitation_code_attempted": code, "reason": "invalid_or_expired_invitation", "method": "dropbox"},
            ip_address=req.client.host if req.client else None,
            user_agent=(req.headers.get("user-agent") or "").strip() or None,
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired invitation code")

    doc = build_invitation_agreement(db, invitation_code=code, guest_full_name=data.guest_full_name)
    if not doc:
        raise HTTPException(status_code=400, detail="Agreement could not be generated")
    if (data.document_hash or "").strip().lower() != doc.document_hash.lower():
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Agreement sign (Dropbox): document hash mismatch",
            f"Sign attempt with outdated document hash for invitation {code}.",
            property_id=inv.property_id,
            invitation_id=inv.id,
            actor_email=data.guest_email,
            ip_address=req.client.host if req.client else None,
            user_agent=(req.headers.get("user-agent") or "").strip() or None,
            meta={"invitation_code": code, "expected_hash": doc.document_hash},
        )
        create_ledger_event(
            db,
            ACTION_AGREEMENT_SIGN_FAILED,
            target_object_type="Invitation",
            target_object_id=inv.id,
            property_id=inv.property_id,
            invitation_id=inv.id,
            meta={"invitation_code": code, "expected_hash": doc.document_hash, "reason": "document_hash_mismatch", "method": "dropbox"},
            ip_address=req.client.host if req.client else None,
            user_agent=(req.headers.get("user-agent") or "").strip() or None,
        )
        db.commit()
        raise HTTPException(status_code=409, detail="Agreement has changed. Please reopen and sign again.")

    ip = (data.ip_address and data.ip_address.strip()[:64]) or (req.client.host if req.client else None) or None
    ua = (req.headers.get("user-agent") or "").strip() or None

    sig = AgreementSignature(
        invitation_code=code,
        region_code=doc.region_code,
        guest_email=str(data.guest_email).strip().lower(),
        guest_full_name=data.guest_full_name.strip(),
        typed_signature=data.typed_signature.strip(),
        signature_method="typed",
        acks_read=data.acks.read,
        acks_temporary=data.acks.temporary,
        acks_vacate=data.acks.vacate,
        acks_electronic=data.acks.electronic,
        document_id=doc.document_id,
        document_title=doc.title,
        document_hash=doc.document_hash,
        document_content=doc.content,
        ip_address=ip,
        user_agent=ua[:400] if ua else None,
    )
    db.add(sig)
    db.commit()
    db.refresh(sig)

    # Ledger + "Agreement signed" notifications fire only after Dropbox returns the signed PDF
    # (see emit_invitation_agreement_signed_if_dropbox_complete).

    # Build PDF from current templates at send time; include guest name, date, and IP
    doc_send = build_invitation_agreement(db, invitation_code=code, guest_full_name=data.guest_full_name)
    if not doc_send:
        raise HTTPException(status_code=500, detail="Agreement could not be generated for sending")
    date_str = sig.signed_at.strftime("%Y-%m-%d") if sig.signed_at else date.today().strftime("%Y-%m-%d")
    content_with_ip = fill_guest_signature_in_content(doc_send.content, sig.guest_full_name, date_str, ip)
    pdf_bytes = agreement_content_to_pdf(doc_send.title, content_with_ip)
    request_id, signer_sig_id = send_signature_request(
        pdf_bytes,
        title=doc_send.title,
        signer_email=sig.guest_email,
        signer_name=sig.guest_full_name,
    )
    sign_url = None
    if request_id:
        sig.dropbox_sign_request_id = request_id
        db.commit()
        if signer_sig_id:
            sign_url = get_embedded_sign_url(signer_sig_id)

    return AgreementSignResponse(signature_id=sig.id, sign_url=sign_url)


@router.get("/signature/{signature_id}/signed-pdf")
def get_signed_agreement_pdf(
    signature_id: int,
    db: Session = Depends(get_db),
):
    """Return the signed PDF: from DB if stored, else from Dropbox Sign once signing is complete. Never returns our generated PDF as signed."""
    sig = db.query(AgreementSignature).filter(AgreementSignature.id == signature_id).first()
    if not sig:
        raise HTTPException(status_code=404, detail="Signed PDF not available")

    if sig.signed_pdf_bytes:
        return Response(
            content=sig.signed_pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="DocuStay-Signed-{sig.invitation_code}.pdf"'},
        )
    if sig.dropbox_sign_request_id:
        pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
        if pdf_bytes:
            sig.signed_pdf_bytes = pdf_bytes
            emit_invitation_agreement_signed_if_dropbox_complete(db, sig)
            db.commit()
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'inline; filename="DocuStay-Signed-{sig.invitation_code}.pdf"'},
            )
        raise HTTPException(
            status_code=404,
            detail="Document not yet signed in Dropbox. Please complete signing in the link we sent you, then try again.",
        )

    raise HTTPException(
        status_code=404,
        detail="Signed PDF not available. Please complete signing in Dropbox.",
    )


@router.get("/signature/{signature_id}/status", response_model=SignatureStatusResponse)
def get_signature_status(
    signature_id: int,
    db: Session = Depends(get_db),
):
    """Return whether this agreement signature has been completed in Dropbox (signed PDF available). Used by frontend to poll until signing is done."""
    sig = db.query(AgreementSignature).filter(AgreementSignature.id == signature_id).first()
    if not sig:
        raise HTTPException(status_code=404, detail="Signature not found")
    if sig.signed_pdf_bytes:
        return SignatureStatusResponse(completed=True)
    if getattr(sig, "dropbox_sign_request_id", None):
        pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
        if pdf_bytes:
            sig.signed_pdf_bytes = pdf_bytes
            emit_invitation_agreement_signed_if_dropbox_complete(db, sig)
            db.commit()
            return SignatureStatusResponse(completed=True)
        return SignatureStatusResponse(completed=False)
    return SignatureStatusResponse(completed=False)


# --- Owner Master POA (onboarding) ---

@router.get("/owner-poa", response_model=OwnerPOADocResponse)
def get_owner_poa_document(
    owner_email: str | None = Query(None),
    owner_full_name: str | None = Query(None),
    owner_city: str | None = Query(None),
    owner_state: str | None = Query(None),
    owner_country: str | None = Query(None),
    principal_title: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Get the Master POA document for owner signup. If owner_email is provided and that email has already signed, returns already_signed and signature_id."""
    principal_name = (owner_full_name or "").strip() or None
    principal_address: str | None = None
    resolved_title: str | None = principal_title.strip() if principal_title and principal_title.strip() else None
    if owner_email and owner_email.strip():
        user = (
            db.query(User)
            .filter(User.email == owner_email.strip().lower(), User.role == UserRole.owner)
            .first()
        )
        if user:
            if not principal_name and user.full_name:
                principal_name = user.full_name
            addr_parts = [p for p in [user.city, user.state, user.country] if p]
            if addr_parts:
                principal_address = ", ".join(addr_parts)
            if not resolved_title:
                ot = getattr(user, "owner_type", None)
                if ot:
                    resolved_title = "Property Manager" if str(ot) == "authorized_agent" else "Owner"
    if not principal_address:
        addr_parts = [p.strip() for p in [owner_city, owner_state, owner_country] if p and p.strip()]
        if addr_parts:
            principal_address = ", ".join(addr_parts)
    doc_id, title, content, doc_hash = build_owner_poa_document(
        principal_name=principal_name,
        principal_address=principal_address,
        principal_title=resolved_title,
    )
    already_signed = False
    signed_at = None
    signed_by = None
    signature_id = None
    has_dropbox_signed_pdf = False
    if owner_email and (owner_email or "").strip():
        email_clean = owner_email.strip().lower()
        sig = (
            db.query(OwnerPOASignature)
            .filter(OwnerPOASignature.owner_email == email_clean)
            .order_by(OwnerPOASignature.signed_at.desc())
            .first()
        )
        if sig:
            already_signed = True
            signed_at = sig.signed_at
            signed_by = sig.typed_signature
            signature_id = sig.id
            if getattr(sig, "signed_pdf_bytes", None):
                has_dropbox_signed_pdf = True
            elif getattr(sig, "dropbox_sign_request_id", None):
                pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
                if pdf_bytes:
                    sig.signed_pdf_bytes = pdf_bytes
                    db.commit()
                    has_dropbox_signed_pdf = True
    return OwnerPOADocResponse(
        document_id=doc_id,
        title=title,
        content=content,
        document_hash=doc_hash,
        already_signed=already_signed,
        signed_at=signed_at,
        signed_by=signed_by,
        signature_id=signature_id,
        has_dropbox_signed_pdf=has_dropbox_signed_pdf,
    )


@router.post("/owner-poa/sign-with-dropbox", response_model=AgreementSignResponse)
def sign_owner_poa_with_dropbox(
    req: Request,
    data: OwnerPOASignRequest,
    db: Session = Depends(get_db),
):
    """Record Master POA signature and send to Dropbox Sign. Used during owner signup (no auth)."""
    principal_name = (data.owner_full_name or "").strip() or None
    principal_address: str | None = None
    resolved_title: str | None = data.principal_title.strip() if data.principal_title and data.principal_title.strip() else None
    if data.owner_email:
        user = (
            db.query(User)
            .filter(
                User.email == str(data.owner_email).strip().lower(),
                User.role == UserRole.owner,
            )
            .first()
        )
        if user:
            addr_parts = [p for p in [user.city, user.state, user.country] if p]
            if addr_parts:
                principal_address = ", ".join(addr_parts)
            if not resolved_title:
                ot = getattr(user, "owner_type", None)
                if ot:
                    resolved_title = "Property Manager" if str(ot) == "authorized_agent" else "Owner"
    if not principal_address:
        addr_parts = [p.strip() for p in [data.owner_city, data.owner_state, data.owner_country] if p and p.strip()]
        if addr_parts:
            principal_address = ", ".join(addr_parts)
    doc_id, title, content, doc_hash = build_owner_poa_document(
        principal_name=principal_name,
        principal_address=principal_address,
        principal_title=resolved_title,
    )
    if (data.document_hash or "").strip().lower() != doc_hash.lower():
        raise HTTPException(status_code=409, detail="Document has changed. Please refresh and sign again.")
    ip = (req.client.host if req.client else None) or None
    ua = (req.headers.get("user-agent") or "").strip() or None
    sig = OwnerPOASignature(
        owner_email=str(data.owner_email).strip().lower(),
        owner_full_name=data.owner_full_name.strip(),
        typed_signature=data.typed_signature.strip(),
        signature_method="typed",
        acks_read=data.acks.read,
        acks_temporary=data.acks.temporary,
        acks_vacate=data.acks.vacate,
        acks_electronic=data.acks.electronic,
        document_id=doc_id,
        document_title=title,
        document_hash=doc_hash,
        document_content=content,
        ip_address=ip,
        user_agent=ua[:400] if ua else None,
    )
    db.add(sig)
    db.commit()
    db.refresh(sig)

    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Master POA signed",
        f"Owner signed Master POA: {sig.owner_full_name} <{sig.owner_email}>, signature_id={sig.id}.",
        actor_email=sig.owner_email,
        ip_address=ip,
        user_agent=ua,
        meta={"signature_id": sig.id, "document_id": doc_id},
    )
    create_ledger_event(
        db,
        ACTION_MASTER_POA_SIGNED,
        target_object_type="OwnerPOASignature",
        target_object_id=sig.id,
        meta={"signature_id": sig.id, "document_id": doc_id, "owner_email": sig.owner_email},
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()

    _doc_id, send_title, send_content, _ = build_owner_poa_document(
        principal_name=principal_name,
        principal_address=principal_address,
        principal_title=resolved_title,
    )
    signed_date = sig.signed_at.strftime("%Y-%m-%d") if sig.signed_at else date.today().strftime("%Y-%m-%d")
    content_filled = fill_owner_poa_signature_line(send_content, sig.owner_full_name, signed_date)
    content_with_sig = poa_content_with_signature(content_filled, sig.owner_full_name, signed_date)
    pdf_bytes = agreement_content_to_pdf(send_title, content_with_sig)
    request_id, signer_sig_id = send_signature_request(
        pdf_bytes,
        title=send_title,
        signer_email=sig.owner_email,
        signer_name=sig.owner_full_name,
        subject="DocuStay – Please sign the Master POA (documentation & records)",
        message="Please sign the Master Power of Attorney for documentation and property records to complete your owner account registration.",
    )
    sign_url = None
    if request_id:
        sig.dropbox_sign_request_id = request_id
        db.commit()
        if signer_sig_id:
            sign_url = get_embedded_sign_url(signer_sig_id)
    return AgreementSignResponse(signature_id=sig.id, sign_url=sign_url)


@router.get("/owner-poa/my-signature", response_model=OwnerPOASignatureResponse | None)
def get_my_owner_poa_signature(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """Return the current owner's Master POA signature (for Settings)."""
    sig = (
        db.query(OwnerPOASignature)
        .filter(OwnerPOASignature.used_by_user_id == current_user.id)
        .order_by(OwnerPOASignature.signed_at.desc())
        .first()
    )
    if not sig:
        return None
    has_dropbox_signed_pdf = bool(getattr(sig, "signed_pdf_bytes", None))
    if not has_dropbox_signed_pdf and getattr(sig, "dropbox_sign_request_id", None):
        pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
        if pdf_bytes:
            sig.signed_pdf_bytes = pdf_bytes
            db.commit()
            has_dropbox_signed_pdf = True
    return OwnerPOASignatureResponse(
        signature_id=sig.id,
        signed_at=sig.signed_at,
        signed_by=sig.typed_signature,
        document_title=sig.document_title,
        document_id=sig.document_id,
        has_dropbox_signed_pdf=has_dropbox_signed_pdf,
    )


@router.get("/owner-poa/signature/{signature_id}/signed-pdf")
def get_owner_poa_signed_pdf(
    signature_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """Return the signed Master POA PDF: from DB if stored, else from Dropbox once signing is complete. Never returns our generated PDF as signed."""
    sig = db.query(OwnerPOASignature).filter(OwnerPOASignature.id == signature_id).first()
    if not sig or sig.used_by_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Signed PDF not available")

    if sig.signed_pdf_bytes:
        return Response(
            content=sig.signed_pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="DocuStay-Master-POA-Signed.pdf"'},
        )
    if sig.dropbox_sign_request_id:
        pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
        if pdf_bytes:
            sig.signed_pdf_bytes = pdf_bytes
            db.commit()
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": 'inline; filename="DocuStay-Master-POA-Signed.pdf"'},
            )
        raise HTTPException(
            status_code=404,
            detail="Document not yet signed in Dropbox. Please complete signing in the link we sent you, then try again.",
        )

    raise HTTPException(
        status_code=404,
        detail="Signed PDF not available. Please complete signing in Dropbox.",
    )


# --- Authority letter (utility provider sign via token link) ---


def _format_property_address(prop: Property | None) -> str | None:
    if not prop:
        return None
    parts = [prop.street, prop.city, prop.state]
    if prop.zip_code:
        parts.append(prop.zip_code)
    return ", ".join([p for p in parts if p])


@router.get("/authority-letter/{token}", response_model=AuthorityLetterDocResponse)
def get_authority_letter_by_token(
    token: str,
    db: Session = Depends(get_db),
):
    """Public: get authority letter by sign token (from email link). No auth."""
    letter = db.query(PropertyAuthorityLetter).filter(
        PropertyAuthorityLetter.sign_token == (token or "").strip(),
    ).first()
    if not letter:
        raise HTTPException(status_code=404, detail="Authority letter not found or link expired")
    prop = db.query(Property).filter(Property.id == letter.property_id).first()
    return AuthorityLetterDocResponse(
        letter_id=letter.id,
        provider_name=letter.provider_name,
        provider_type=letter.provider_type or "",
        content=letter.letter_content,
        property_address=_format_property_address(prop),
        property_name=prop.name if prop else None,
        already_signed=letter.signed_at is not None,
        signed_at=letter.signed_at,
        has_dropbox_signed_pdf=bool(letter.dropbox_sign_request_id or letter.signed_pdf_bytes),
    )


@router.post("/authority-letter/{token}/sign-with-dropbox", response_model=AgreementSignResponse)
def sign_authority_letter_with_dropbox(
    token: str,
    data: AuthorityLetterSignRequest,
    req: Request,
    db: Session = Depends(get_db),
):
    """Public: record signer and send authority letter to Dropbox Sign. Signer gets email to sign; we store request_id."""
    letter = db.query(PropertyAuthorityLetter).filter(
        PropertyAuthorityLetter.sign_token == (token or "").strip(),
    ).first()
    if not letter:
        raise HTTPException(status_code=404, detail="Authority letter not found or link expired")
    if letter.signed_at is not None:
        raise HTTPException(status_code=400, detail="This authority letter has already been signed")

    from datetime import datetime, timezone

    title = f"DocuStay Authority Letter – {letter.provider_name}"
    pdf_bytes = agreement_content_to_pdf(title, letter.letter_content)
    request_id = send_signature_request(
        pdf_bytes,
        title=title,
        signer_email=data.signer_email,
        signer_name=data.signer_name,
        subject="DocuStay – Please sign the authority letter",
        message="Please sign this authority letter to confirm receipt and authorization.",
    )
    if not request_id:
        raise HTTPException(status_code=503, detail="Signature service is not configured")

    letter.dropbox_sign_request_id = request_id
    letter.signer_email = (data.signer_email or "").strip().lower()
    db.commit()

    return AgreementSignResponse(signature_id=letter.id)


@router.get("/authority-letter/{token}/signed-pdf")
def get_authority_letter_signed_pdf(
    token: str,
    db: Session = Depends(get_db),
):
    """Public: return signed PDF for this authority letter (from DB or fetch from Dropbox Sign)."""
    letter = db.query(PropertyAuthorityLetter).filter(
        PropertyAuthorityLetter.sign_token == (token or "").strip(),
    ).first()
    if not letter:
        raise HTTPException(status_code=404, detail="Authority letter not found")

    if letter.signed_pdf_bytes:
        return Response(
            content=letter.signed_pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="DocuStay-Authority-Letter-{letter.provider_name or "signed"}.pdf"'},
        )
    if letter.dropbox_sign_request_id:
        pdf_bytes = get_signed_pdf(letter.dropbox_sign_request_id)
        if pdf_bytes:
            from datetime import datetime, timezone
            letter.signed_pdf_bytes = pdf_bytes
            letter.signed_at = datetime.now(timezone.utc)  # approximate; Dropbox doesn't give exact time in this flow
            db.commit()
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'inline; filename="DocuStay-Authority-Letter-{letter.provider_name or "signed"}.pdf"'},
            )

    raise HTTPException(status_code=404, detail="Signed PDF not yet available. The document may still be pending signature.")

