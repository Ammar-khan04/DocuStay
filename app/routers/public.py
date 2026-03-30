"""Public API (no auth): live property page by slug – evidence view; verify portal."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.database import get_db
from app.dependencies import get_optional_current_user
from app.models.owner import Property, OwnerProfile
from app.models.unit import Unit
from app.models.user import User, UserRole
from app.models.stay import Stay
from app.models.audit_log import AuditLog
from app.models.event_ledger import EventLedger
from app.models.invitation import Invitation
from app.models.tenant_assignment import TenantAssignment
from app.models.owner_poa_signature import OwnerPOASignature
from app.models.agreement_signature import AgreementSignature
from app.models.property_manager_assignment import PropertyManagerAssignment
from app.services.agreements import agreement_content_to_pdf, fill_guest_signature_in_content, poa_content_with_signature
from app.services.dropbox_sign import get_signed_pdf
from app.services.invitation_agreement_ledger import emit_invitation_agreement_signed_if_dropbox_complete
from app.services.audit_log import create_log, CATEGORY_VERIFY_ATTEMPT, CATEGORY_FAILED_ATTEMPT
from app.services.event_ledger import (
    create_ledger_event,
    ledger_event_to_display,
    ACTION_VERIFY_ATTEMPT_VALID,
    ACTION_VERIFY_ATTEMPT_FAILED,
)
from app.services.property_live_ledger import merged_public_property_ledger_rows
from app.services.shield_mode_policy import effective_shield_mode_enabled
from app.services.display_names import (
    label_for_stay,
    label_from_invitation,
    label_for_tenant_assignee,
    label_from_user_id,
)
from app.schemas.public import (
    LivePropertyPagePayload,
    LivePropertyInfo,
    LiveOwnerInfo,
    LivePropertyManagerInfo,
    LiveCurrentGuestInfo,
    LiveStaySummary,
    LiveInvitationSummary,
    LiveTenantAssignmentInfo,
    LiveLogEntry,
    JurisdictionWrap,
    JurisdictionStatuteView,
    PortfolioPagePayload,
    PortfolioOwnerInfo,
    PortfolioPropertyItem,
    VerifyRequest,
    VerifyResponse,
    VerifyAssignedTenant,
    VerifyGuestAuthorization,
)
from app.models.resident_presence import ResidentPresence, PresenceStatus

router = APIRouter(prefix="/public", tags=["public"])


def _is_active_stay(s: Stay) -> bool:
    """True if stay is checked in and not checked out/cancelled (current guest)."""
    if getattr(s, "checked_in_at", None) is None:
        return False
    if getattr(s, "checked_out_at", None) is not None:
        return False
    if getattr(s, "cancelled_at", None) is not None:
        return False
    return True


def _current_active_stays_for_live(db: Session, prop_id: int) -> list[Stay]:
    """All checked-in stays that are in-window or overstaying (public live evidence)."""
    today = date.today()
    active = [
        s
        for s in db.query(Stay).filter(Stay.property_id == prop_id).all()
        if _is_active_stay(s)
    ]
    out: list[Stay] = []
    for s in active:
        if s.stay_start_date <= today <= s.stay_end_date:
            out.append(s)
        elif s.stay_end_date < today:
            out.append(s)
    out.sort(key=lambda x: (x.unit_id or 0, x.stay_end_date, x.id))
    return out


def _agreement_signature_for_stay(db: Session, stay: Stay) -> AgreementSignature | None:
    if not stay.invitation_id:
        return None
    inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
    if not inv:
        return None
    return (
        db.query(AgreementSignature)
        .filter(AgreementSignature.invitation_code == inv.invitation_code)
        .order_by(AgreementSignature.signed_at.desc())
        .first()
    )


def _signed_agreement_offer_for_stay(db: Session, slug: str, stay: Stay) -> tuple[bool, str | None]:
    sig = _agreement_signature_for_stay(db, stay)
    if not sig:
        return False, None
    if not (getattr(sig, "signed_pdf_bytes", None) or getattr(sig, "dropbox_sign_request_id", None)):
        return False, None
    return True, f"/public/live/{slug}/signed-agreement?stay_id={stay.id}"


def _verify_signed_agreement_offer_for_invite_code(db: Session, invitation_code: str) -> tuple[bool, str | None]:
    """Public PDF URL by invite ID (same handler as verify portal) — works for any guest stay with a completed signature."""
    code = (invitation_code or "").strip()
    if not code:
        return False, None
    sig = (
        db.query(AgreementSignature)
        .filter(AgreementSignature.invitation_code == code)
        .order_by(AgreementSignature.signed_at.desc())
        .first()
    )
    if not sig:
        return False, None
    if not (getattr(sig, "signed_pdf_bytes", None) or getattr(sig, "dropbox_sign_request_id", None)):
        return False, None
    return True, f"/public/verify/{code}/signed-agreement"


def _invitation_map_for_stays(db: Session, stays: list[Stay]) -> dict[int, Invitation]:
    ids = {s.invitation_id for s in stays if getattr(s, "invitation_id", None)}
    if not ids:
        return {}
    rows = db.query(Invitation).filter(Invitation.id.in_(ids)).all()
    return {i.id: i for i in rows}


def _stay_kind_for_live(inv_map: dict[int, Invitation], stay: Stay) -> str:
    iid = getattr(stay, "invitation_id", None)
    if not iid:
        return "guest"
    inv = inv_map.get(iid)
    if not inv:
        return "guest"
    kind = (getattr(inv, "invitation_kind", None) or "guest").strip().lower()
    return "tenant" if kind == "tenant" else "guest"


def _live_guest_info_rows(db: Session, slug: str, stays: list[Stay]) -> list[LiveCurrentGuestInfo]:
    inv_map = _invitation_map_for_stays(db, stays)
    rows: list[LiveCurrentGuestInfo] = []
    for stay in stays:
        avail, url = _signed_agreement_offer_for_stay(db, slug, stay)
        iid = getattr(stay, "invitation_id", None)
        inv_row = inv_map.get(iid) if iid else None
        inv_code = inv_row.invitation_code if inv_row else None
        inv_ts = (getattr(inv_row, "token_state", None) or None) if inv_row else None
        rows.append(
            LiveCurrentGuestInfo(
                stay_id=stay.id,
                guest_name=label_for_stay(db, stay),
                stay_start_date=stay.stay_start_date,
                stay_end_date=stay.stay_end_date,
                checked_out_at=getattr(stay, "checked_out_at", None),
                dead_mans_switch_enabled=bool(getattr(stay, "dead_mans_switch_enabled", 0)),
                signed_agreement_available=avail,
                signed_agreement_url=url,
                stay_kind=_stay_kind_for_live(inv_map, stay),
                invitation_code=inv_code,
                invitation_token_state=str(inv_ts).strip() if inv_ts else None,
            )
        )
    return rows


def _fmt_short_date_live(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def _tenant_summary_strip(rows: list[LiveTenantAssignmentInfo]) -> tuple[str | None, str | None]:
    if not rows:
        return None, None
    parts: list[str] = []
    for r in rows:
        n = (r.tenant_full_name or r.tenant_email or "").strip()
        parts.append(n if n else "—")
    assignee = " · ".join(parts)
    if len(rows) == 1:
        r0 = rows[0]
        if r0.end_date is None:
            period = f"{_fmt_short_date_live(r0.start_date)} – Open-ended"
        else:
            period = f"{_fmt_short_date_live(r0.start_date)} – {_fmt_short_date_live(r0.end_date)}"
    else:
        period = "Multiple (see Current client)"
    return assignee, period


def _ta_to_live_tenant_row(
    db: Session,
    ta: TenantAssignment,
    unit: Unit | None,
    now: datetime,
) -> LiveTenantAssignmentInfo:
    u = db.query(User).filter(User.id == ta.user_id).first()
    display = label_from_user_id(db, ta.user_id) if ta.user_id else None
    if not display and u:
        display = (u.full_name or "").strip() or (u.email or "").strip() or None
    if not display:
        display = label_for_tenant_assignee(db, ta.user_id)
    tenant_email = (u.email or "").strip() if u else None
    created = ta.created_at if ta.created_at is not None else now
    return LiveTenantAssignmentInfo(
        assignment_id=ta.id,
        stay_id=None,
        unit_label=unit.unit_label if unit else "—",
        tenant_full_name=display,
        tenant_email=tenant_email or None,
        start_date=ta.start_date,
        end_date=ta.end_date,
        created_at=created,
    )


def _live_tenant_summary_for_logged_in_tenant(
    db: Session,
    property_id: int,
    viewer: User | None,
    today: date,
) -> tuple[list[LiveTenantAssignmentInfo], str | None, str | None] | None:
    """
    When the viewer is a tenant user with tenant_assignments on this property (active lease end),
    return their row(s) and summary strings for the live page tenant card (personalized view).
    """
    if not viewer or viewer.role != UserRole.tenant:
        return None
    now = datetime.now(timezone.utc)
    rows = (
        db.query(TenantAssignment)
        .join(Unit, TenantAssignment.unit_id == Unit.id)
        .filter(
            Unit.property_id == property_id,
            TenantAssignment.user_id == viewer.id,
            or_(TenantAssignment.end_date.is_(None), TenantAssignment.end_date >= today),
        )
        .order_by(TenantAssignment.unit_id.asc(), TenantAssignment.created_at.desc())
        .all()
    )
    if not rows:
        return None
    unit_ids = {ta.unit_id for ta in rows}
    units_by_id = {u.id: u for u in db.query(Unit).filter(Unit.id.in_(unit_ids)).all()}
    out = [_ta_to_live_tenant_row(db, ta, units_by_id.get(ta.unit_id), now) for ta in rows]
    assignee_s, period_s = _tenant_summary_strip(out)
    return out, assignee_s, period_s


def _live_occupying_tenants_for_property(db: Session, property_id: int, today: date) -> list[LiveTenantAssignmentInfo]:
    """
    Tenants who currently occupy per get_units_occupancy_display priority: if a checked-in guest stay,
    pending invite, or on-site manager fills the unit, the leaseholder tenant row is not shown for that unit.
    """
    from app.services.occupancy import get_units_occupancy_sources

    now = datetime.now(timezone.utc)
    unit_rows = db.query(Unit).filter(Unit.property_id == property_id).all()
    if unit_rows:
        unit_ids = [u.id for u in unit_rows]
        sources = get_units_occupancy_sources(db, unit_ids, guest_detail_unit_ids=None)
        units_by_id = {u.id: u for u in unit_rows}
        out: list[LiveTenantAssignmentInfo] = []
        for uid in sorted(unit_ids):
            if sources.get(uid) != "tenant_assignment":
                continue
            ta = (
                db.query(TenantAssignment)
                .filter(
                    TenantAssignment.unit_id == uid,
                    or_(TenantAssignment.end_date.is_(None), TenantAssignment.end_date >= today),
                )
                .order_by(TenantAssignment.created_at.desc())
                .first()
            )
            if not ta:
                continue
            out.append(_ta_to_live_tenant_row(db, ta, units_by_id.get(uid), now))
        return out

    stays = _current_active_stays_for_live(db, property_id)
    inv_map = _invitation_map_for_stays(db, stays)
    out2: list[LiveTenantAssignmentInfo] = []
    for s in stays:
        if _stay_kind_for_live(inv_map, s) != "tenant":
            continue
        if s.checked_in_at is None or s.checked_out_at is not None or getattr(s, "cancelled_at", None):
            continue
        unit = db.query(Unit).filter(Unit.id == s.unit_id).first() if getattr(s, "unit_id", None) else None
        guest_u = db.query(User).filter(User.id == s.guest_id).first() if s.guest_id else None
        label = label_for_stay(db, s)
        email = (guest_u.email or "").strip() if guest_u else None
        created = s.created_at if getattr(s, "created_at", None) is not None else now
        out2.append(
            LiveTenantAssignmentInfo(
                assignment_id=None,
                stay_id=s.id,
                unit_label=unit.unit_label if unit else "—",
                tenant_full_name=label,
                tenant_email=email or None,
                start_date=s.stay_start_date,
                end_date=s.stay_end_date,
                created_at=created,
            )
        )
    return out2


def _response_signed_agreement_pdf(db: Session, sig: AgreementSignature) -> Response:
    """Return PDF bytes for a completed (or Dropbox-pending) guest agreement signature."""
    if getattr(sig, "dropbox_sign_request_id", None):
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
            detail="Document not yet signed. Please complete signing in the link we sent you.",
        )
    if sig.signed_pdf_bytes:
        return Response(
            content=sig.signed_pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="DocuStay-Signed-{sig.invitation_code}.pdf"'},
        )
    date_str = sig.signed_at.strftime("%Y-%m-%d") if sig.signed_at else ""
    content = fill_guest_signature_in_content(
        sig.document_content, sig.typed_signature, date_str, getattr(sig, "ip_address", None)
    )
    pdf_bytes = agreement_content_to_pdf(sig.document_title, content)
    sig.signed_pdf_bytes = pdf_bytes
    db.commit()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="DocuStay-Signed-{sig.invitation_code}.pdf"'},
    )


@router.get("/live/{slug}", response_model=LivePropertyPagePayload)
def get_live_property_page(
    slug: str,
    db: Session = Depends(get_db),
    viewer: User | None = Depends(get_optional_current_user),
):
    """
    Public live property page by unique slug. Optional Bearer token: when the viewer is a tenant
    assigned to this property, the tenant summary card shows their assignment(s) instead of public occupancy.
    """
    if not slug or not slug.strip():
        raise HTTPException(status_code=404, detail="Not found")
    slug = slug.strip()
    prop = db.query(Property).filter(Property.live_slug == slug, Property.deleted_at.is_(None)).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Property not found")
    owner_user = db.query(User).filter(User.id == profile.user_id).first()
    owner_name = (owner_user.full_name if owner_user else None) or None
    _raw_email = (getattr(owner_user, "email", None) or "") if owner_user else ""
    owner_email = str(_raw_email).strip()
    owner_phone = getattr(owner_user, "phone", None) if owner_user else None
    owner_info = LiveOwnerInfo(full_name=owner_name, email=owner_email, phone=owner_phone)

    mgr_assignments = db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == prop.id).all()
    mgr_user_ids = [a.user_id for a in mgr_assignments]
    mgr_users = (
        db.query(User)
        .filter(User.id.in_(mgr_user_ids), User.role == UserRole.property_manager)
        .all()
        if mgr_user_ids
        else []
    )
    property_managers = [
        LivePropertyManagerInfo(
            full_name=(u.full_name or "").strip() or None,
            email=(u.email or "").strip(),
        )
        for u in mgr_users
        if (u.email or "").strip()
    ]

    token_state = getattr(prop, "usat_token_state", None) or "staged"
    prop_info = LivePropertyInfo(
        name=prop.name,
        street=prop.street,
        city=prop.city,
        state=prop.state,
        zip_code=prop.zip_code,
        region_code=prop.region_code,
        occupancy_status=getattr(prop, "occupancy_status", None) or "unknown",
        shield_mode_enabled=effective_shield_mode_enabled(prop),
        token_state=token_state,
        tax_id=getattr(prop, "tax_id", None) or None,
        apn=getattr(prop, "apn", None) or None,
    )

    # Jurisdictional wrap: applicable law for this property (zip → region → statutes)
    jurisdiction_wrap = None
    from app.services.jurisdiction_sot import get_jurisdiction_for_property
    jinfo = get_jurisdiction_for_property(db, prop.zip_code, prop.region_code)
    if jinfo:
        jurisdiction_wrap = JurisdictionWrap(
            state_name=jinfo.name,
            applicable_statutes=[
                JurisdictionStatuteView(citation=s.citation, plain_english=s.plain_english)
                for s in jinfo.statutes
            ],
            removal_guest_text=jinfo.removal_guest_text,
            removal_tenant_text=jinfo.removal_tenant_text,
            agreement_type=jinfo.agreement_type,
        )

    # POA for Authority layer
    poa_signed_at: datetime | None = None
    poa_signature_id: int | None = None
    poa_typed_signature: str | None = None
    if profile and profile.user_id:
        poa_sig = (
            db.query(OwnerPOASignature)
            .filter(OwnerPOASignature.used_by_user_id == profile.user_id)
            .first()
        )
        if poa_sig:
            poa_signed_at = poa_sig.signed_at
            poa_signature_id = poa_sig.id
            poa_typed_signature = (poa_sig.typed_signature or "").strip() or None

    today = date.today()
    current_stays_live = _current_active_stays_for_live(db, prop.id)

    # Logs: full property audit (all ledger rows tied to property / its stays / invitations / units)
    log_rows = merged_public_property_ledger_rows(db, prop.id, limit=500)
    logs = []
    for r in log_rows:
        cat, title, msg = ledger_event_to_display(r, db)
        logs.append(
            LiveLogEntry(
                category=cat,
                title=title,
                message=msg,
                created_at=r.created_at if r.created_at is not None else datetime.now(timezone.utc),
            )
        )

    # Invitations for this property – invite states indicate stay status (STAGED→pending, BURNED→accepted/stay, EXPIRED→ended, REVOKED→cancelled)
    inv_rows = (
        db.query(Invitation)
        .filter(Invitation.property_id == prop.id)
        .order_by(Invitation.created_at.desc())
        .limit(50)
    ).all()
    # Tenants on the live page only see guest invitations they created (same scope as GET /dashboard/tenant/invitations);
    # tenant-lease invitations for the property remain visible so verification context is preserved.
    if viewer is not None and getattr(viewer, "role", None) == UserRole.tenant:
        inv_rows = [
            inv
            for inv in inv_rows
            if (getattr(inv, "invitation_kind", None) or "guest").strip().lower() != "guest"
            or getattr(inv, "invited_by_user_id", None) == viewer.id
        ]
    invitations = []
    for inv in inv_rows:
        guest_label = label_from_invitation(db, inv)
        inv_kind = (getattr(inv, "invitation_kind", None) or "guest").strip().lower()
        agr_avail, agr_url = (False, None)
        if inv_kind == "guest":
            agr_avail, agr_url = _verify_signed_agreement_offer_for_invite_code(db, inv.invitation_code)
        invitations.append(
            LiveInvitationSummary(
                invitation_code=inv.invitation_code,
                guest_label=guest_label,
                stay_start_date=inv.stay_start_date,
                stay_end_date=inv.stay_end_date,
                status=inv.status or "pending",
                token_state=getattr(inv, "token_state", None) or "STAGED",
                signed_agreement_available=agr_avail,
                signed_agreement_url=agr_url,
                invitation_kind=inv_kind,
            )
        )

    # Logged-in guests: hide tenant-lane rows from Invitation states (privacy / relevance).
    if viewer is not None and viewer.role == UserRole.guest:
        invitations = [
            inv for inv in invitations if (inv.invitation_kind or "guest").strip().lower() != "tenant"
        ]

    current_tenant_assignments = _live_occupying_tenants_for_property(db, prop.id, today)
    tenant_summary_assignee, tenant_summary_assignment_period = _tenant_summary_strip(current_tenant_assignments)
    personalized = _live_tenant_summary_for_logged_in_tenant(db, prop.id, viewer, today)
    if personalized is not None:
        current_tenant_assignments, tenant_summary_assignee, tenant_summary_assignment_period = personalized

    if current_stays_live:
        cg_rows = _live_guest_info_rows(db, slug, current_stays_live)
        all_revoked = all(getattr(s, "revoked_at", None) for s in current_stays_live)
        authorization_state = "REVOKED" if all_revoked else "ACTIVE"
        return LivePropertyPagePayload(
            has_current_guest=True,
            property=prop_info,
            owner=owner_info,
            property_managers=property_managers,
            current_guest=cg_rows[0] if cg_rows else None,
            current_guests=cg_rows,
            last_stay=None,
            upcoming_stays=[],
            invitations=invitations,
            logs=logs,
            authorization_state=authorization_state,
            record_id=slug,
            generated_at=datetime.now(timezone.utc),
            poa_signed_at=poa_signed_at,
            poa_signature_id=poa_signature_id,
            poa_typed_signature=poa_typed_signature,
            jurisdiction_wrap=jurisdiction_wrap,
            current_tenant_assignments=current_tenant_assignments,
            tenant_summary_assignee=tenant_summary_assignee,
            tenant_summary_assignment_period=tenant_summary_assignment_period,
        )

    # No current guest: last stay (most recent ended) and upcoming
    all_stays = db.query(Stay).filter(Stay.property_id == prop.id).order_by(Stay.stay_end_date.desc()).all()
    inv_map = _invitation_map_for_stays(db, all_stays)
    last_stay = None
    for s in all_stays:
        if getattr(s, "checked_out_at", None) is not None or s.stay_end_date < today:
            gn = label_for_stay(db, s)
            last_stay = LiveStaySummary(
                guest_name=gn,
                stay_start_date=s.stay_start_date,
                stay_end_date=s.stay_end_date,
                checked_out_at=getattr(s, "checked_out_at", None),
                stay_kind=_stay_kind_for_live(inv_map, s),
            )
            break

    upcoming = []
    for s in all_stays:
        if s.stay_start_date > today and getattr(s, "cancelled_at", None) is None:
            gn = label_for_stay(db, s)
            upcoming.append(
                LiveStaySummary(
                    guest_name=gn,
                    stay_start_date=s.stay_start_date,
                    stay_end_date=s.stay_end_date,
                    checked_out_at=None,
                    stay_kind=_stay_kind_for_live(inv_map, s),
                )
            )
    upcoming.sort(key=lambda x: x.stay_start_date)

    # Guest authorization on this page is about stays. Do not infer EXPIRED from property
    # occupancy alone — a new listing can be marked occupied or unknown while the tenant
    # invite is still pending and there are no guest stays yet.
    authorization_state = "EXPIRED" if last_stay else "NONE"

    return LivePropertyPagePayload(
        has_current_guest=False,
        property=prop_info,
        owner=owner_info,
        property_managers=property_managers,
        current_guest=None,
        current_guests=[],
        last_stay=last_stay,
        upcoming_stays=upcoming,
        invitations=invitations,
        logs=logs,
        authorization_state=authorization_state,
        record_id=slug,
        generated_at=datetime.now(timezone.utc),
        poa_signed_at=poa_signed_at,
        poa_signature_id=poa_signature_id,
        poa_typed_signature=poa_typed_signature,
        jurisdiction_wrap=jurisdiction_wrap,
        current_tenant_assignments=current_tenant_assignments,
        tenant_summary_assignee=tenant_summary_assignee,
        tenant_summary_assignment_period=tenant_summary_assignment_period,
    )


def _normalize_address(s: str) -> str:
    """Collapse whitespace and lowercase for address comparison."""
    if not s:
        return ""
    return " ".join(s.lower().strip().split())


def _build_verify_record(
    db: Session,
    inv: Invitation,
    prop: Property,
    stay: Stay | None,
    valid: bool,
    reason: str,
    token_id: str,
    now: datetime,
) -> VerifyResponse:
    """Build full VerifyResponse with property, guest, dates, status, and signed agreement info."""
    prop_parts = [prop.street, prop.city, prop.state, (prop.zip_code or "").strip()]
    prop_full = ", ".join(p for p in prop_parts if p)
    token_state = getattr(inv, "token_state", None) or "STAGED"
    today = date.today()

    # Guest / tenant name
    inv_kind = (getattr(inv, "invitation_kind", None) or "").strip().lower()
    if stay:
        guest_name = label_for_stay(db, stay)
    elif inv_kind == "tenant" and inv.unit_id:
        ta = db.query(TenantAssignment).filter(TenantAssignment.unit_id == inv.unit_id).first()
        if ta:
            guest_name = label_for_tenant_assignee(db, ta.user_id)
            if guest_name == "Unknown resident":
                guest_name = label_from_invitation(db, inv)
        else:
            guest_name = label_from_invitation(db, inv)
    else:
        guest_name = label_from_invitation(db, inv)

    # Stay dates
    stay_start_date = stay.stay_start_date if stay else inv.stay_start_date
    stay_end_date = stay.stay_end_date if stay else inv.stay_end_date
    checked_in_at = getattr(stay, "checked_in_at", None) if stay else None
    checked_out_at = getattr(stay, "checked_out_at", None) if stay else None
    revoked_at = getattr(stay, "revoked_at", None) if stay else None
    cancelled_at = getattr(stay, "cancelled_at", None) if stay else None

    # Status
    if not stay:
        if token_state in ("CANCELLED", "REVOKED"):
            status = "CANCELLED"
        elif token_state == "EXPIRED":
            status = "EXPIRED"
        elif valid:
            status = "ACTIVE"
        else:
            status = "PENDING"
    elif revoked_at:
        status = "REVOKED"
    elif cancelled_at:
        status = "CANCELLED"
    elif checked_out_at:
        status = "COMPLETED"
    elif stay_end_date < today:
        status = "EXPIRED"
    elif checked_in_at:
        status = "ACTIVE"
    else:
        status = "PENDING"

    # Signed agreement
    sig = (
        db.query(AgreementSignature)
        .filter(AgreementSignature.invitation_code == inv.invitation_code)
        .order_by(AgreementSignature.signed_at.desc())
        .first()
    )
    signed_agreement_available = False
    signed_agreement_url = None
    if sig and (sig.signed_pdf_bytes or getattr(sig, "dropbox_sign_request_id", None)):
        signed_agreement_available = True
        signed_agreement_url = f"/public/verify/{token_id}/signed-agreement"

    # POA
    profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
    poa_signed_at = None
    if profile and profile.user_id:
        poa_sig = (
            db.query(OwnerPOASignature)
            .filter(OwnerPOASignature.used_by_user_id == profile.user_id)
            .first()
        )
        if poa_sig:
            poa_signed_at = poa_sig.signed_at

    # Audit entries
    log_rows = (
        db.query(AuditLog)
        .filter(AuditLog.property_id == prop.id)
        .order_by(AuditLog.created_at.desc())
        .limit(20)
    ).all()
    audit_entries = [
        LiveLogEntry(
            category=r.category or "—",
            title=r.title or "—",
            message=r.message or "—",
            created_at=r.created_at if r.created_at is not None else now,
        )
        for r in log_rows
    ]

    occ = getattr(prop, "occupancy_status", None) or "unknown"
    if valid and (occ or "").lower() == "unknown":
        occ = "occupied"

    # Assigned tenants and resident status for the unit
    assigned_tenants: list[VerifyAssignedTenant] = []
    resident_status: str | None = None
    unit_id = stay.unit_id if stay else inv.unit_id
    if unit_id:
        tas = db.query(TenantAssignment).filter(TenantAssignment.unit_id == unit_id).all()
        for ta in tas:
            t_name = label_for_tenant_assignee(db, ta.user_id)
            pres = db.query(ResidentPresence).filter(
                ResidentPresence.user_id == ta.user_id,
                ResidentPresence.unit_id == unit_id,
            ).first()
            t_status = pres.status.value if pres else "present"
            assigned_tenants.append(VerifyAssignedTenant(name=t_name, status=t_status))
        if assigned_tenants:
            has_away = any(t.status == "away" for t in assigned_tenants)
            resident_status = "away" if has_away and all(t.status == "away" for t in assigned_tenants) else "present"

    # POA URL
    poa_url: str | None = None
    if prop.live_slug and poa_signed_at:
        poa_url = f"/public/live/{prop.live_slug}/poa"

    # Event ledger entries (same full-property scope as GET /public/live/{slug})
    ledger_rows = merged_public_property_ledger_rows(db, prop.id, limit=500)
    ledger_entries = []
    for lr in ledger_rows:
        cat, title, msg = ledger_event_to_display(lr, db)
        ledger_entries.append(LiveLogEntry(
            category=cat,
            title=title,
            message=msg,
            created_at=lr.created_at if lr.created_at is not None else now,
        ))

    # Authorization history (all stays for this unit, numbered)
    authorization_history: list[VerifyGuestAuthorization] = []
    if unit_id:
        all_stays = (
            db.query(Stay)
            .filter(Stay.unit_id == unit_id)
            .order_by(Stay.created_at)
            .all()
        )
        for idx, s in enumerate(all_stays, 1):
            s_revoked = getattr(s, "revoked_at", None)
            s_cancelled = getattr(s, "cancelled_at", None)
            s_checkout = getattr(s, "checked_out_at", None)
            s_checkin = getattr(s, "checked_in_at", None)
            if s_revoked:
                s_status = "REVOKED"
            elif s_cancelled:
                s_status = "CANCELLED"
            elif s_checkout:
                s_status = "COMPLETED"
            elif s.stay_end_date and s.stay_end_date < today:
                s_status = "EXPIRED"
            elif s_checkin:
                s_status = "ACTIVE"
            else:
                s_status = "PENDING"
            g_name = label_for_stay(db, s)
            authorization_history.append(VerifyGuestAuthorization(
                authorization_number=idx,
                guest_name=g_name,
                start_date=s.stay_start_date,
                end_date=s.stay_end_date,
                status=s_status,
                revoked_at=s_revoked,
                expired_at=s.stay_end_date if s_status == "EXPIRED" else None,
                cancelled_at=s_cancelled,
                checked_out_at=s_checkout,
            ))

    return VerifyResponse(
        valid=valid,
        reason=reason,
        property_name=prop.name,
        property_address=prop_full,
        occupancy_status=occ,
        token_state=token_state,
        stay_start_date=stay_start_date,
        stay_end_date=stay_end_date,
        guest_name=guest_name,
        poa_signed_at=poa_signed_at,
        live_slug=prop.live_slug,
        generated_at=now,
        audit_entries=ledger_entries if ledger_entries else audit_entries,
        status=status,
        checked_in_at=checked_in_at,
        checked_out_at=checked_out_at,
        revoked_at=revoked_at,
        cancelled_at=cancelled_at,
        signed_agreement_available=signed_agreement_available,
        signed_agreement_url=signed_agreement_url,
        assigned_tenants=assigned_tenants,
        resident_status=resident_status,
        poa_url=poa_url,
        verified_at=now,
        authorization_history=authorization_history,
    )


@router.post("/verify", response_model=VerifyResponse)
def post_verify(
    body: VerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Public verify: check if token (Invitation ID) has an active authorization. Property address is optional;
    when provided it must match the property associated with the token. No auth. Every attempt is logged.
    """
    now = datetime.now(timezone.utc)
    token_id = (body.token_id or "").strip()
    property_address = (body.property_address or "").strip() if body.property_address else ""
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    if not token_id:
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Verify attempt – missing token",
            "token_id empty",
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "missing_input"},
        )
        db.commit()
        return VerifyResponse(
            valid=False,
            reason="Token ID is required.",
            generated_at=now,
        )

    # 1. Look up invitation by token_id (invitation_code), case-insensitive
    inv = (
        db.query(Invitation)
        .filter(func.lower(Invitation.invitation_code) == token_id.lower())
        .first()
    )
    if not inv:
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Verify attempt – no match",
            f"Token not found: {token_id[:20]}…",
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "token_not_found", "token_id_prefix": token_id[:32]},
        )
        db.commit()
        return VerifyResponse(
            valid=False,
            reason="Token not found.",
            generated_at=now,
        )

    # 2. Resolve property
    prop = db.query(Property).filter(Property.id == inv.property_id, Property.deleted_at.is_(None)).first()
    if not prop:
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Verify attempt – property not found",
            f"Property missing for invitation {inv.id}",
            property_id=inv.property_id,
            invitation_id=inv.id,
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "property_not_found"},
        )
        db.commit()
        return VerifyResponse(
            valid=False,
            reason="Property not found.",
            generated_at=now,
        )

    # 3. Match address when provided (normalized)
    prop_parts = [prop.street, prop.city, prop.state, (prop.zip_code or "").strip()]
    prop_full = ", ".join(p for p in prop_parts if p)
    if property_address:
        norm_prop = _normalize_address(prop_full)
        norm_submitted = _normalize_address(property_address)
        if norm_prop != norm_submitted:
            # Allow submitted to contain property address (e.g. extra lines) or vice versa
            if norm_prop not in norm_submitted and norm_submitted not in norm_prop:
                create_log(
                    db,
                    CATEGORY_FAILED_ATTEMPT,
                    "Identity Conflict",
                    "Address does not match property for this token.",
                    property_id=prop.id,
                    invitation_id=inv.id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    meta={
                        "result": "invalid",
                        "reason": "address_mismatch",
                        "token_id_prefix": token_id[:32],
                    },
                )
                db.commit()
                return VerifyResponse(
                    valid=False,
                    reason="Address does not match the property for this token.",
                    generated_at=now,
                )

    # 4. Stay and validity
    stay = db.query(Stay).filter(Stay.invitation_id == inv.id).first()
    today = date.today()
    token_state = getattr(inv, "token_state", None) or "STAGED"

    # Determine validity and reason
    valid = False
    reason = ""
    if token_state != "BURNED":
        create_log(
            db,
            CATEGORY_VERIFY_ATTEMPT,
            "Verify attempt – token not active",
            f"Invitation token_state={token_state}, expected BURNED",
            property_id=prop.id,
            invitation_id=inv.id,
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "token_not_burned", "token_state": token_state},
        )
        db.commit()
        if token_state in ("CANCELLED", "REVOKED"):
            reason_msg = "Status: CANCELLED — Assignment or invitation was cancelled."
        elif token_state == "EXPIRED":
            reason_msg = "Status: EXPIRED — Invitation or stay has ended."
        else:
            reason_msg = "Status: PENDING — Invitation not yet accepted."
        return _build_verify_record(
            db, inv, prop, stay,
            valid=False,
            reason=reason_msg,
            token_id=token_id,
            now=now,
        )

    if not stay:
        inv_kind = (getattr(inv, "invitation_kind", None) or "").strip().lower()
        if inv_kind == "tenant":
            ta = db.query(TenantAssignment).filter(TenantAssignment.unit_id == inv.unit_id).first()
            if ta:
                tenant = db.query(User).filter(User.id == ta.user_id).first()
                tenant_name = (tenant.full_name if tenant else None) or (tenant.email if tenant else "Tenant")
                ta_start = getattr(ta, "start_date", None) or inv.stay_start_date
                ta_end = getattr(ta, "end_date", None) or inv.stay_end_date
                ta_active = ta_start and ta_end and ta_start <= today and ta_end >= today if ta_start and ta_end else bool(ta_start and ta_start <= today)
                create_log(
                    db,
                    CATEGORY_VERIFY_ATTEMPT,
                    "Verify attempt – tenant assignment" + (" (active)" if ta_active else ""),
                    f"Tenant assignment found for unit {inv.unit_id}",
                    property_id=prop.id,
                    invitation_id=inv.id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    meta={"result": "valid" if ta_active else "invalid", "reason": "tenant_assignment"},
                )
                db.commit()
                return _build_verify_record(
                    db, inv, prop, None,
                    valid=ta_active,
                    reason="" if ta_active else "Status: Tenant assignment exists but dates are outside the current period.",
                    token_id=token_id,
                    now=now,
                )
        create_log(
            db,
            CATEGORY_VERIFY_ATTEMPT,
            "Verify attempt – no stay",
            "No stay linked to this invitation",
            property_id=prop.id,
            invitation_id=inv.id,
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "no_stay"},
        )
        db.commit()
        return _build_verify_record(
            db, inv, prop, None,
            valid=False,
            reason="Status: PENDING — Agreement signed; stay record not yet created.",
            token_id=token_id,
            now=now,
        )

    if getattr(stay, "revoked_at", None) is not None:
        create_log(
            db,
            CATEGORY_VERIFY_ATTEMPT,
            "Verify attempt – stay revoked",
            "Stay has been revoked",
            property_id=prop.id,
            stay_id=stay.id,
            invitation_id=inv.id,
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "stay_revoked"},
        )
        db.commit()
        return _build_verify_record(
            db, inv, prop, stay,
            valid=False,
            reason="Status: REVOKED — Authorization was revoked.",
            token_id=token_id,
            now=now,
        )

    if getattr(stay, "checked_out_at", None) is not None:
        create_log(
            db,
            CATEGORY_VERIFY_ATTEMPT,
            "Verify attempt – guest checked out",
            "Guest has checked out",
            property_id=prop.id,
            stay_id=stay.id,
            invitation_id=inv.id,
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "stay_checked_out"},
        )
        db.commit()
        return _build_verify_record(
            db, inv, prop, stay,
            valid=False,
            reason="Status: COMPLETED — Guest checked out.",
            token_id=token_id,
            now=now,
        )

    if getattr(stay, "cancelled_at", None) is not None:
        create_log(
            db,
            CATEGORY_VERIFY_ATTEMPT,
            "Verify attempt – stay cancelled",
            "Stay was cancelled",
            property_id=prop.id,
            stay_id=stay.id,
            invitation_id=inv.id,
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "stay_cancelled"},
        )
        db.commit()
        return _build_verify_record(
            db, inv, prop, stay,
            valid=False,
            reason="Status: CANCELLED — Stay was cancelled.",
            token_id=token_id,
            now=now,
        )

    if stay.stay_end_date < today:
        create_log(
            db,
            CATEGORY_VERIFY_ATTEMPT,
            "Verify attempt – stay ended",
            "Stay end date has passed",
            property_id=prop.id,
            stay_id=stay.id,
            invitation_id=inv.id,
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "stay_ended"},
        )
        db.commit()
        return _build_verify_record(
            db, inv, prop, stay,
            valid=False,
            reason="Status: EXPIRED — Stay end date has passed.",
            token_id=token_id,
            now=now,
        )

    # 5. Valid: log success and build response
    create_log(
        db,
        CATEGORY_VERIFY_ATTEMPT,
        "Verify attempt – valid",
        "Token and address match; active authorization confirmed.",
        property_id=prop.id,
        stay_id=stay.id,
        invitation_id=inv.id,
        ip_address=ip_address,
        user_agent=user_agent,
        meta={"result": "valid", "reason": "valid"},
    )
    create_ledger_event(
        db,
        ACTION_VERIFY_ATTEMPT_VALID,
        target_object_type="Stay",
        target_object_id=stay.id,
        property_id=prop.id,
        stay_id=stay.id,
        invitation_id=inv.id,
        meta={"result": "valid", "reason": "valid"},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()

    return _build_verify_record(
        db, inv, prop, stay,
        valid=True,
        reason="",
        token_id=token_id,
        now=now,
    )


@router.get("/verify/{token}/signed-agreement")
def get_verify_signed_agreement_pdf(
    token: str,
    db: Session = Depends(get_db),
):
    """
    Public: return signed guest agreement PDF for the invitation identified by token (invitation code).
    No auth; for use by the verify page when signed_agreement_available is true.
    """
    token = (token or "").strip()
    if not token:
        raise HTTPException(status_code=404, detail="Token required")
    inv = (
        db.query(Invitation)
        .filter(func.lower(Invitation.invitation_code) == token.lower())
        .first()
    )
    if not inv:
        raise HTTPException(status_code=404, detail="Token not found")
    sig = (
        db.query(AgreementSignature)
        .filter(AgreementSignature.invitation_code == inv.invitation_code)
        .order_by(AgreementSignature.signed_at.desc())
        .first()
    )
    if not sig:
        raise HTTPException(status_code=404, detail="No signed agreement found for this token.")
    return _response_signed_agreement_pdf(db, sig)


@router.get("/live/{slug}/signed-agreement")
def get_live_signed_agreement_pdf(
    slug: str,
    stay_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
):
    """
    Public: signed guest agreement PDF for a **current** active authorization on this property only.
    Past stays: use verify token URL or guest/tenant authenticated downloads. Keeps live link aligned with Bug #3 (current guest only).
    """
    if not slug or not slug.strip():
        raise HTTPException(status_code=404, detail="Not found")
    slug = slug.strip()
    prop = db.query(Property).filter(Property.live_slug == slug, Property.deleted_at.is_(None)).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    stay = db.query(Stay).filter(Stay.id == stay_id, Stay.property_id == prop.id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    allowed_ids = {s.id for s in _current_active_stays_for_live(db, prop.id)}
    if stay.id not in allowed_ids:
        raise HTTPException(
            status_code=404,
            detail="No active guest authorization for this stay on the live link.",
        )
    sig = _agreement_signature_for_stay(db, stay)
    if not sig:
        raise HTTPException(status_code=404, detail="No signed agreement found for this stay.")
    return _response_signed_agreement_pdf(db, sig)


@router.get("/live/{slug}/poa")
def get_live_property_poa_pdf(slug: str, db: Session = Depends(get_db)):
    """
    Public: return signed Master POA PDF for the property identified by live slug.
    No auth; for use by "View POA" on the live evidence page.
    """
    if not slug or not slug.strip():
        raise HTTPException(status_code=404, detail="Not found")
    slug = slug.strip()
    prop = db.query(Property).filter(Property.live_slug == slug, Property.deleted_at.is_(None)).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
    if not profile or not profile.user_id:
        raise HTTPException(status_code=404, detail="POA not available")
    sig = (
        db.query(OwnerPOASignature)
        .filter(OwnerPOASignature.used_by_user_id == profile.user_id)
        .first()
    )
    if not sig:
        raise HTTPException(status_code=404, detail="POA not on file for this property")

    if sig.signed_pdf_bytes:
        return Response(
            content=sig.signed_pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="DocuStay-Master-POA-Signed.pdf"'},
        )
    if getattr(sig, "dropbox_sign_request_id", None):
        pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
        if pdf_bytes:
            sig.signed_pdf_bytes = pdf_bytes
            db.commit()
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": 'inline; filename="DocuStay-Master-POA-Signed.pdf"'},
            )
    date_str = sig.signed_at.strftime("%Y-%m-%d") if sig.signed_at else ""
    content_with_sig = poa_content_with_signature(sig.document_content, sig.typed_signature, date_str)
    pdf_bytes = agreement_content_to_pdf(sig.document_title, content_with_sig)
    sig.signed_pdf_bytes = pdf_bytes
    db.commit()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="DocuStay-Master-POA-Signed.pdf"'},
    )


@router.get("/portfolio/{slug}", response_model=PortfolioPagePayload)
def get_portfolio_page(slug: str, db: Session = Depends(get_db)):
    """
    Public portfolio page by owner's unique slug (no auth).
    Returns owner basic info and list of active properties (public details only).
    """
    if not slug or not slug.strip():
        raise HTTPException(status_code=404, detail="Portfolio not found")
    slug = slug.strip()
    profile = db.query(OwnerProfile).filter(OwnerProfile.portfolio_slug == slug).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    owner_user = db.query(User).filter(User.id == profile.user_id).first()
    owner_name = (owner_user.full_name if owner_user else None) or None
    _raw_email = (getattr(owner_user, "email", None) or "") if owner_user else ""
    owner_email = str(_raw_email).strip()
    owner_phone = getattr(owner_user, "phone", None) if owner_user else None
    owner_state = getattr(owner_user, "state", None) if owner_user else None
    owner_info = PortfolioOwnerInfo(
        full_name=owner_name,
        email=owner_email,
        phone=owner_phone,
        state=owner_state,
    )
    properties = (
        db.query(Property)
        .filter(Property.owner_profile_id == profile.id, Property.deleted_at.is_(None))
        .order_by(Property.created_at.asc())
        .all()
    )
    property_items = []
    for p in properties:
        unit_count = None
        if getattr(p, "is_multi_unit", False):
            unit_count = db.query(Unit).filter(Unit.property_id == p.id).count() or 0
        property_items.append(
            PortfolioPropertyItem(
                id=p.id,
                name=p.name,
                city=p.city,
                state=p.state,
                region_code=p.region_code,
                property_type_label=getattr(p, "property_type_label", None) or (p.property_type.value if p.property_type else None),
                bedrooms=getattr(p, "bedrooms", None),
                is_multi_unit=getattr(p, "is_multi_unit", False),
                unit_count=unit_count,
            )
        )
    return PortfolioPagePayload(owner=owner_info, properties=property_items)
