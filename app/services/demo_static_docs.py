"""Unsigned demo PDFs: built on demand via the same agreement/POA pipeline (no DB blob columns)."""
from __future__ import annotations

import logging
from sqlalchemy.orm import Session

from app.models.demo_account import is_demo_user_id
from app.models.invitation import Invitation
from app.models.owner import OwnerProfile, Property
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)


def build_demo_owner_unsigned_poa_pdf_bytes(db: Session, owner_user: User) -> bytes | None:
    """Unsigned Master POA PDF for demo owners (same template as onboarding; no typed signature overlay)."""
    if owner_user.role != UserRole.owner or not is_demo_user_id(db, owner_user.id):
        return None
    from app.services.agreements import agreement_content_to_pdf, build_owner_poa_document

    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == owner_user.id).first()
    addr = None
    if profile:
        prop = (
            db.query(Property)
            .filter(Property.owner_profile_id == profile.id, Property.deleted_at.is_(None))
            .order_by(Property.id.asc())
            .first()
        )
        if prop:
            parts = [prop.street, prop.city, prop.state, prop.zip_code]
            addr = ", ".join(p for p in parts if p)
    name = (owner_user.full_name or "").strip() or (owner_user.email or "").strip()
    _doc_id, title, content, _h = build_owner_poa_document(
        principal_name=name,
        principal_address=addr,
        principal_title="Owner",
    )
    return agreement_content_to_pdf(title, content)


def build_demo_unsigned_guest_agreement_pdf_bytes(db: Session, inv: Invitation) -> bytes | None:
    """Unsigned guest agreement PDF when the invite was created by a demo user (on demand; not stored)."""
    kind = (getattr(inv, "invitation_kind", None) or "guest").strip().lower()
    if kind != "guest":
        return None
    uid = getattr(inv, "invited_by_user_id", None) or getattr(inv, "owner_id", None)
    if not is_demo_user_id(db, uid):
        return None
    try:
        from app.services.agreements import agreement_content_to_pdf, build_invitation_agreement

        gn = (inv.guest_name or "").strip() or None
        doc = build_invitation_agreement(db, invitation_code=inv.invitation_code, guest_full_name=gn)
        if doc:
            return agreement_content_to_pdf(doc.title, doc.content)
    except Exception:
        logger.exception("build_demo_unsigned_guest_agreement_pdf_bytes failed for code=%r", inv.invitation_code)
    return None
