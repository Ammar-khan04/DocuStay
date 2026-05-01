"""Public API (no auth): live property page by slug – evidence view; verify portal."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.database import get_db
from app.dependencies import get_optional_current_user
from app.models.owner import Property, OwnerProfile, OccupancyStatus
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
from app.services.invitation_kinds import (
    is_property_invited_tenant_signup_kind,
    normalize_invitation_kind,
    TENANT_UNIT_LEASE_KINDS,
)
from app.services.tenant_lease_cohort import map_assignment_id_to_cohort_key
from app.services.dropbox_sign import get_signed_pdf
from app.services.invitation_agreement_ledger import emit_invitation_agreement_signed_if_dropbox_complete
from app.services.audit_log import create_log, CATEGORY_VERIFY_ATTEMPT, CATEGORY_FAILED_ATTEMPT
from app.services.event_ledger import (
    ACTION_AWAY_ACTIVATED,
    ACTION_AWAY_ENDED,
    ACTION_PRESENCE_STATUS_CHANGED,
    TENANT_LIVE_PAGE_EXCLUDED_OWNER_ACTIONS,
    build_ledger_display_resolution_context,
    create_ledger_event,
    ledger_event_to_display,
    ledger_record_disclosure_lines,
    _scrub_emails_for_timeline_display,
    ACTION_VERIFY_ATTEMPT_VALID,
    ACTION_VERIFY_ATTEMPT_FAILED,
)
from app.services.property_live_ledger import merged_public_property_ledger_rows
from app.services.owner_live_slug import resolve_owner_live_slug_row
from app.services.tenant_live_slug import resolve_tenant_live_slug_row
from app.services.guest_live_slug import resolve_guest_live_slug_row
from app.services.ledger_actor_attribution import audit_actor_attribution
from app.services.shield_mode_policy import effective_shield_mode_enabled
from app.services.occupancy import (
    get_property_display_occupancy_status,
    get_unit_display_occupancy_status,
    normalize_occupancy_status_for_display,
    count_effectively_occupied_units,
)
from app.services.display_names import (
    label_for_stay,
    label_from_invitation,
    label_for_tenant_assignee,
    label_from_user_id,
)
from app.services.state_resolver import (
    resolve_invitation_display_status,
    resolve_live_property_authorization_state,
    resolve_public_tenant_assignment_row_label,
    resolve_public_tenant_stay_invitation_row_label,
    resolve_verify_guest_authorization_history_status,
    resolve_verify_primary_guest_stay_status,
)
from app.schemas.public import (
    LivePropertyPagePayload,
    LivePropertyInfo,
    LiveUnitOccupancyStatus,
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
router = APIRouter(prefix="/public", tags=["public"])

_PRESENCE_LEDGER_ACTIONS: frozenset[str] = frozenset(
    {
        ACTION_AWAY_ACTIVATED,
        ACTION_AWAY_ENDED,
        ACTION_PRESENCE_STATUS_CHANGED,
    }
)


def _presence_ledger_row_actor_is_tenant_or_guest_user(db: Session, row: EventLedger) -> bool:
    """Tenant/guest scoped live: only presence rows from resident tenant or guest accounts (not owner/manager)."""
    at = (row.action_type or "").strip()
    if at not in _PRESENCE_LEDGER_ACTIONS:
        return True
    aid = getattr(row, "actor_user_id", None)
    if not aid:
        return False
    u = db.query(User).filter(User.id == aid).first()
    if not u or getattr(u, "role", None) is None:
        return False
    return u.role in (UserRole.tenant, UserRole.guest)


def _ledger_row_hidden_from_tenant_live_timeline(row: EventLedger) -> bool:
    """Owner/manager portfolio, CSV bulk import, and owner-issued tenant lease pipeline — not tenant live evidence."""
    return (row.action_type or "").strip() in TENANT_LIVE_PAGE_EXCLUDED_OWNER_ACTIONS


def _allowed_unit_labels_active_or_accepted_for_tenant(
    db: Session, property_id: int, tenant_user_id: int, today: date
) -> list[str]:
    """Unit labels where this tenant has an active or accepted (future) lease — tenant live slug scope."""
    from app.services.tenant_lease_window import find_invitation_matching_tenant_assignment, resolve_tenant_lease_assignment_status

    rows = (
        db.query(TenantAssignment)
        .join(Unit, TenantAssignment.unit_id == Unit.id)
        .filter(
            Unit.property_id == property_id,
            TenantAssignment.user_id == tenant_user_id,
            TenantAssignment.start_date.isnot(None),
            or_(TenantAssignment.end_date.is_(None), TenantAssignment.end_date >= today),
        )
        .all()
    )
    tenant_user = db.query(User).filter(User.id == tenant_user_id).first()
    em = (tenant_user.email or "").strip().lower() if tenant_user else ""
    out: list[str] = []
    for ta in rows:
        unit = db.query(Unit).filter(Unit.id == ta.unit_id).first()
        if not unit:
            continue
        inv = find_invitation_matching_tenant_assignment(db, ta, user_email_lower=em or None)
        st = resolve_tenant_lease_assignment_status(ta, inv, today=today)
        if st in ("active", "accepted"):
            lab = (unit.unit_label or "").strip()
            if lab and lab != "—":
                out.append(lab)
    return list(dict.fromkeys(out))


def _invitation_matches_tenant_live_slug(inv: Invitation, email_lower: str, tenant_user_id: int) -> bool:
    """Tenant-specific live slug: only this tenant's lease-lane invites (and guest invites they created)."""
    nk = normalize_invitation_kind(getattr(inv, "invitation_kind", None))
    if nk in TENANT_UNIT_LEASE_KINDS:
        return (getattr(inv, "guest_email", None) or "").strip().lower() == email_lower
    if nk == "guest":
        return getattr(inv, "invited_by_user_id", None) == tenant_user_id
    return False


def _unit_ids_matching_labels(units: list[Unit], labels_lower: set[str]) -> set[int]:
    if not labels_lower:
        return set()
    return {
        u.id
        for u in units
        if ((getattr(u, "unit_label", None) or "").strip().lower() in labels_lower)
    }


def _scoped_live_ledger_row_matches_unit_scope(
    db: Session,
    row: EventLedger,
    *,
    property_id: int,
    allowed_unit_ids: set[int],
    allowed_labels_lower: set[str],
) -> bool:
    """Ledger row belongs to an allowed unit (tenant/guest scoped live links).

    Uses ``unit_id`` / stay / invitation linkage so presence and other rows stay visible when
    display text uses a unit label without the literal word ``Unit`` (matches live-page UI filter).
    """
    if not allowed_labels_lower:
        return False
    uid = getattr(row, "unit_id", None)
    if uid is not None and uid in allowed_unit_ids:
        return True
    sid = getattr(row, "stay_id", None)
    if sid is not None:
        st = db.query(Stay).filter(Stay.id == sid, Stay.property_id == property_id).first()
        if st and getattr(st, "unit_id", None) in allowed_unit_ids:
            return True
    iid = getattr(row, "invitation_id", None)
    if iid is not None:
        inv = db.query(Invitation).filter(Invitation.id == iid, Invitation.property_id == property_id).first()
        if inv and getattr(inv, "unit_id", None) in allowed_unit_ids:
            return True
    meta = row.meta if isinstance(row.meta, dict) else {}
    blob = " ".join(
        [
            str(getattr(row, "action_type", "") or ""),
            str(meta.get("message") or ""),
            str(meta.get("unit_label") or ""),
        ]
    ).lower()
    return any(lab and lab in blob for lab in allowed_labels_lower)


def _resolve_live_slug_context(db: Session, slug: str) -> tuple[Property | None, int | None, int | None, int | None]:
    """Resolve slug to (property, tenant_user_id_for_tenant_slug, guest_user_id_for_guest_slug, guest_unit_id)."""
    owner_row = resolve_owner_live_slug_row(db, slug)
    if owner_row:
        prop_owner = db.query(Property).filter(
            Property.id == owner_row.property_id,
            Property.deleted_at.is_(None),
        ).first()
        if prop_owner:
            return prop_owner, None, None, None
    tenant_row = resolve_tenant_live_slug_row(db, slug)
    if tenant_row:
        prop2 = db.query(Property).filter(Property.id == tenant_row.property_id, Property.deleted_at.is_(None)).first()
        if not prop2:
            return None, None, None, None
        return prop2, tenant_row.tenant_user_id, None, None
    guest_row = resolve_guest_live_slug_row(db, slug)
    if not guest_row:
        return None, None, None, None
    prop3 = db.query(Property).filter(Property.id == guest_row.property_id, Property.deleted_at.is_(None)).first()
    if not prop3:
        return None, None, None, None
    return prop3, None, guest_row.guest_user_id, guest_row.unit_id


def _safe_guest_audit_log_entry(entry: LiveLogEntry) -> bool:
    """Guest scoped live links must not surface tenant invite/presence content in timeline."""
    text = f"{entry.title or ''} {entry.message or ''}".lower()
    if "tenant" in text:
        return False
    if "lease" in text or "assignment" in text or "co-tenant" in text:
        return False
    return True


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
    return "tenant" if is_property_invited_tenant_signup_kind(kind) else "guest"


def _live_occupancy_summary_detail(
    db: Session,
    prop: Property,
    display_occupancy: str,
    active_stays: list[Stay],
    tenant_assignment_rows: list[LiveTenantAssignmentInfo],
) -> str:
    """One or two sentences for the public live page: why status is occupied/vacant (owner residence vs guest vs tenant)."""
    occ = (display_occupancy or "unknown").strip().lower()
    owner_occ = bool(getattr(prop, "owner_occupied", False))
    inv_map = _invitation_map_for_stays(db, active_stays)
    n_tenant_stay = sum(1 for s in active_stays if _stay_kind_for_live(inv_map, s) == "tenant")
    n_guest_stay = len(active_stays) - n_tenant_stay
    n_assign = len(tenant_assignment_rows or [])

    if occ == "vacant":
        if n_guest_stay or n_tenant_stay:
            return (
                "Vacant on the property record while checked-in authorization(s) still appear on this page — "
                "verify the Current guest section below."
            )
        if n_assign:
            return (
                "Vacant on the property record while tenant assignment row(s) still appear below — "
                "verify dates and unit against your records."
            )
        return "Vacant — no checked-in guest authorization or active tenant assignment is shown on this page."

    if occ == "unconfirmed":
        return (
            "Unconfirmed — occupancy has not been confirmed on the property record. "
            "Use invitation states and the audit timeline below to verify."
        )

    if occ == "unknown":
        return "Unknown — occupancy has not been classified on the property record."

    # occupied (or any other non-vacant display string): explain drivers
    bits: list[str] = []
    if n_guest_stay:
        bits.append(
            f"{n_guest_stay} active guest authorization{'s' if n_guest_stay != 1 else ''} (checked-in stay)"
        )
    if n_tenant_stay:
        bits.append(
            f"{n_tenant_stay} active tenant stay{'s' if n_tenant_stay != 1 else ''} (checked-in)"
        )
    if n_assign and (n_guest_stay + n_tenant_stay) == 0:
        bits.append(
            f"active tenant assignment{'s' if n_assign != 1 else ''} on file ({n_assign})"
        )

    if bits:
        lead = "Occupied — " + "; ".join(bits) + "."
        tail = (
            " The owner has also listed this address as a primary residence on file."
            if owner_occ
            else " See Current guest and tenant sections below for names and dates."
        )
        return lead + tail

    if owner_occ:
        return (
            "Occupied — owner primary residence. The owner has listed this address as a primary residence on file. "
            "No checked-in guest stay or tenant assignment appears on this page."
        )

    return (
        "Occupied on the property record — no checked-in guest stay or tenant assignment appears on this page. "
        "Verify invitation states and the audit timeline below."
    )


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
                dead_mans_switch_enabled=False,
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
    today: date,
    *,
    cohort_id: str | None = None,
    cohort_member_count: int | None = None,
) -> LiveTenantAssignmentInfo:
    u = db.query(User).filter(User.id == ta.user_id).first()
    display = label_from_user_id(db, ta.user_id) if ta.user_id else None
    if not display and u:
        display = (u.full_name or "").strip() or (u.email or "").strip() or None
    if not display:
        display = label_for_tenant_assignee(db, ta.user_id)
    tenant_email = (u.email or "").strip() if u else None
    created = ta.created_at if ta.created_at is not None else now
    lease_invite = resolve_public_tenant_assignment_row_label(db, ta, today)
    return LiveTenantAssignmentInfo(
        assignment_id=ta.id,
        stay_id=None,
        unit_label=unit.unit_label if unit else "—",
        tenant_full_name=display,
        tenant_email=tenant_email or None,
        start_date=ta.start_date,
        end_date=ta.end_date,
        created_at=created,
        lease_cohort_id=cohort_id,
        lease_cohort_member_count=cohort_member_count,
        lease_invite_resolved_status=lease_invite,
    )


def _live_tenant_summary_for_logged_in_tenant(
    db: Session,
    property_id: int,
    viewer: User | None,
    today: date,
) -> tuple[list[LiveTenantAssignmentInfo], str | None, str | None] | None:
    """
    When the viewer is a tenant user with tenant_assignments on this property (active or accepted/future lease),
    return their row(s) and summary strings for the live page tenant card (personalized view).

    Includes overlapping **co-tenant** assignments on the same unit(s) with matching lease-cohort keys and
    per-row ``lease_invite_resolved_status`` so shared-lease state matches ``_live_occupying_tenants_for_property``.
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
            TenantAssignment.start_date.isnot(None),
            or_(TenantAssignment.end_date.is_(None), TenantAssignment.end_date >= today),
        )
        .order_by(TenantAssignment.unit_id.asc(), TenantAssignment.created_at.desc())
        .all()
    )
    if not rows:
        return None
    unit_ids_list = list({ta.unit_id for ta in rows if ta.unit_id})
    if not unit_ids_list:
        return None
    # Same overlap pool as property-wide live assignments so cohort keys / sizes align.
    siblings = (
        db.query(TenantAssignment)
        .join(Unit, TenantAssignment.unit_id == Unit.id)
        .filter(
            Unit.property_id == property_id,
            TenantAssignment.unit_id.in_(unit_ids_list),
            TenantAssignment.start_date.isnot(None),
            or_(TenantAssignment.end_date.is_(None), TenantAssignment.end_date >= today),
        )
        .all()
    )
    cohort_map = map_assignment_id_to_cohort_key(siblings)
    cohort_sizes: dict[str, int] = {}
    for _ta in siblings:
        ck = cohort_map.get(_ta.id)
        if ck:
            cohort_sizes[ck] = cohort_sizes.get(ck, 0) + 1

    units_by_id = {u.id: u for u in db.query(Unit).filter(Unit.id.in_(unit_ids_list)).all()}
    viewer_row_ids = {ta.id for ta in rows}
    viewer_cohort_keys = {cohort_map.get(ta.id) for ta in rows if cohort_map.get(ta.id)}

    out: list[LiveTenantAssignmentInfo] = []
    seen_ta_ids: set[int] = set()

    def append_row(ta: TenantAssignment) -> None:
        if ta.id in seen_ta_ids:
            return
        seen_ta_ids.add(ta.id)
        ck = cohort_map.get(ta.id)
        cnt = cohort_sizes.get(ck, 1) if ck else 1
        out.append(
            _ta_to_live_tenant_row(
                db,
                ta,
                units_by_id.get(ta.unit_id),
                now,
                today,
                cohort_id=ck,
                cohort_member_count=cnt if ck else 1,
            )
        )

    for ta in sorted(rows, key=lambda t: (t.unit_id or 0, t.created_at or now, t.id)):
        append_row(ta)

    for ta in sorted(siblings, key=lambda t: (t.unit_id or 0, t.user_id or 0, t.id)):
        if ta.user_id == viewer.id:
            continue
        ck = cohort_map.get(ta.id)
        if not ck or cohort_sizes.get(ck, 0) < 2:
            continue
        if ck not in viewer_cohort_keys:
            continue
        append_row(ta)

    assignee_s, period_s = _tenant_summary_strip(out)
    return out, assignee_s, period_s


def _live_occupying_tenants_for_property(db: Session, property_id: int, today: date) -> list[LiveTenantAssignmentInfo]:
    """
    Tenant lease rows for live page tenant sections:
    - active/in-window assignments (occupying) per get_units_occupancy_display priority
    - accepted/future assignments (start_date > today) so upcoming accepted leases are visible
    """
    from app.services.occupancy import get_units_occupancy_sources
    from app.services.unit_display_order import query_units_for_property_ordered

    now = datetime.now(timezone.utc)
    unit_rows = query_units_for_property_ordered(db, property_id).all()
    if unit_rows:
        unit_ids = [u.id for u in unit_rows]
        sources = get_units_occupancy_sources(db, unit_ids, guest_detail_unit_ids=None)
        units_by_id = {u.id: u for u in unit_rows}
        out: list[LiveTenantAssignmentInfo] = []
        live_tas = (
            db.query(TenantAssignment)
            .filter(
                TenantAssignment.unit_id.in_(unit_ids),
                TenantAssignment.start_date.isnot(None),
                or_(TenantAssignment.end_date.is_(None), TenantAssignment.end_date >= today),
            )
            .all()
        )
        cohort_map = map_assignment_id_to_cohort_key(live_tas)
        cohort_sizes: dict[str, int] = {}
        for _ta in live_tas:
            ck = cohort_map.get(_ta.id)
            if ck:
                cohort_sizes[ck] = cohort_sizes.get(ck, 0) + 1
        for u in unit_rows:
            uid = u.id
            unit_tas = [x for x in live_tas if x.unit_id == uid]
            if not unit_tas:
                continue
            in_window_tas = [x for x in unit_tas if x.start_date and x.start_date <= today]
            future_tas = [x for x in unit_tas if x.start_date and x.start_date > today]
            rows_for_unit = []
            if sources.get(uid) == "tenant_assignment":
                rows_for_unit.extend(in_window_tas)
            rows_for_unit.extend(future_tas)
            if not rows_for_unit:
                continue
            for ta in sorted(rows_for_unit, key=lambda t: (t.start_date or today, t.user_id or 0, t.id)):
                ck = cohort_map.get(ta.id)
                out.append(
                    _ta_to_live_tenant_row(
                        db,
                        ta,
                        units_by_id.get(uid),
                        now,
                        today,
                        cohort_id=ck,
                        cohort_member_count=cohort_sizes.get(ck) if ck else 1,
                    )
                )
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
        iid = getattr(s, "invitation_id", None)
        inv_row = inv_map.get(iid) if iid else None
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
                lease_invite_resolved_status=resolve_public_tenant_stay_invitation_row_label(
                    inv_row, today=today, db=db
                ),
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
    prop, tenant_slug_user_id, guest_slug_user_id, guest_slug_unit_id = _resolve_live_slug_context(db, slug)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    link_audience = "tenant" if tenant_slug_user_id else ("guest" if guest_slug_user_id else "property")
    effective_viewer = viewer
    tenant_slug_email_lower = ""
    guest_slug_user_email_lower = ""
    if tenant_slug_user_id is not None:
        tenant_slug_user = db.query(User).filter(User.id == tenant_slug_user_id).first()
        if tenant_slug_user and tenant_slug_user.role == UserRole.tenant:
            effective_viewer = tenant_slug_user
            tenant_slug_email_lower = (tenant_slug_user.email or "").strip().lower()
    if guest_slug_user_id is not None:
        guest_slug_user = db.query(User).filter(User.id == guest_slug_user_id).first()
        if guest_slug_user and guest_slug_user.role == UserRole.guest:
            effective_viewer = guest_slug_user
            guest_slug_user_email_lower = (guest_slug_user.email or "").strip().lower()

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
    from app.services.unit_display_order import query_units_for_property_ordered

    units_for_live = query_units_for_property_ordered(db, prop.id).all()
    unit_statuses_for_live = [
        LiveUnitOccupancyStatus(
            unit_label=(u.unit_label or "").strip() or "—",
            occupancy_status=get_unit_display_occupancy_status(db, u),
        )
        for u in units_for_live
    ]
    display_occupancy = get_property_display_occupancy_status(db, prop, units_for_live)
    owner_occ_flag = bool(getattr(prop, "owner_occupied", False))
    is_multi = bool(getattr(prop, "is_multi_unit", False))
    occ_lower = (display_occupancy or "").lower()
    occupied_units = (
        count_effectively_occupied_units(db, units_for_live)
        if units_for_live
        else (1 if occ_lower == OccupancyStatus.occupied.value else 0)
    )
    total_units = len(units_for_live) if units_for_live else (1 if not is_multi else 0)
    unit_count_val = total_units or 1
    vacant_units = max(0, int(unit_count_val) - int(occupied_units))
    from app.services.property_invitation_summary import (
        filter_invitations_for_live_property_evidence,
        invitation_counts_dict,
    )

    inv_for_counts = filter_invitations_for_live_property_evidence(
        db, property_id=prop.id, viewer=effective_viewer
    )
    if tenant_slug_user_id is not None and tenant_slug_email_lower:
        inv_for_counts = [
            inv
            for inv in inv_for_counts
            if _invitation_matches_tenant_live_slug(inv, tenant_slug_email_lower, tenant_slug_user_id)
        ]
    if guest_slug_user_id is not None:
        inv_for_counts = [
            inv
            for inv in inv_for_counts
            if normalize_invitation_kind(getattr(inv, "invitation_kind", None)) == "guest"
            and (getattr(inv, "guest_email", None) or "").strip().lower() == guest_slug_user_email_lower
        ]
    inv_count_fields = invitation_counts_dict(inv_for_counts, db)
    prop_info = LivePropertyInfo(
        name=prop.name,
        street=prop.street,
        city=prop.city,
        state=prop.state,
        zip_code=prop.zip_code,
        region_code=prop.region_code,
        occupancy_status=display_occupancy,
        shield_mode_enabled=effective_shield_mode_enabled(prop),
        token_state=token_state,
        tax_id=getattr(prop, "tax_id", None) or None,
        apn=getattr(prop, "apn", None) or None,
        owner_occupied=owner_occ_flag,
        occupancy_summary_detail="",
        is_multi_unit=is_multi,
        unit_count=unit_count_val,
        occupied_unit_count=occupied_units,
        vacant_unit_count=vacant_units,
        unit_statuses=unit_statuses_for_live,
        **inv_count_fields,
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
    allowed_tenant_live_units: list[str] = []
    if tenant_slug_user_id is not None:
        allowed_tenant_live_units = _allowed_unit_labels_active_or_accepted_for_tenant(
            db, prop.id, tenant_slug_user_id, today
        )
    allowed_guest_live_units: list[str] = []
    if guest_slug_user_id is not None and guest_slug_unit_id is not None:
        unit_row = db.query(Unit).filter(Unit.id == guest_slug_unit_id, Unit.property_id == prop.id).first()
        lab = (unit_row.unit_label or "").strip() if unit_row else ""
        if lab and lab != "—":
            allowed_guest_live_units = [lab]
    current_stays_live = _current_active_stays_for_live(db, prop.id)
    # Invitation rows can lag the physical stay (token/status still STAGED/pending). Align with
    # ``resolve_public_tenant_stay_invitation_row_label`` / verify: checked-in stay ⇒ display active.
    invitation_ids_with_checked_in_stay = {
        int(s.invitation_id)
        for s in current_stays_live
        if getattr(s, "invitation_id", None) is not None
    }
    if tenant_slug_user_id is not None:
        current_stays_live = []

    # Assigned tenant (Bearer): same personalization as the tenant card; include guest-stay ledger rows.
    personalized = _live_tenant_summary_for_logged_in_tenant(db, prop.id, effective_viewer, today)

    # Logs: property-scoped audit; guest-stay lane omitted unless viewer is that assigned tenant.
    log_rows = merged_public_property_ledger_rows(
        db,
        prop.id,
        limit=500,
        exclude_guest_stay_actions=(personalized is None),
    )
    tenant_slug_scoped = tenant_slug_user_id is not None
    labels_for_tenant_live: set[str] | None = None
    if tenant_slug_scoped:
        labels_for_tenant_live = {x.strip().lower() for x in allowed_tenant_live_units if x.strip()}
    bearer_tenant_scoped = (
        not tenant_slug_scoped
        and guest_slug_user_id is None
        and personalized is not None
        and effective_viewer is not None
        and getattr(effective_viewer, "role", None) == UserRole.tenant
    )
    if bearer_tenant_scoped:
        labs = _allowed_unit_labels_active_or_accepted_for_tenant(db, prop.id, effective_viewer.id, today)
        labels_for_tenant_live = {x.strip().lower() for x in labs if x.strip()}

    if tenant_slug_scoped or bearer_tenant_scoped:
        if not labels_for_tenant_live:
            log_rows = []
        else:
            aid = _unit_ids_matching_labels(list(units_for_live), labels_for_tenant_live)
            log_rows = [
                r
                for r in log_rows
                if _scoped_live_ledger_row_matches_unit_scope(
                    db,
                    r,
                    property_id=prop.id,
                    allowed_unit_ids=aid,
                    allowed_labels_lower=labels_for_tenant_live,
                )
                and _presence_ledger_row_actor_is_tenant_or_guest_user(db, r)
                and not _ledger_row_hidden_from_tenant_live_timeline(r)
            ]
    elif guest_slug_user_id is not None:
        uset = {x.strip().lower() for x in allowed_guest_live_units if x.strip()}
        if uset:
            aid = _unit_ids_matching_labels(list(units_for_live), uset)
            log_rows = [
                r
                for r in log_rows
                if _scoped_live_ledger_row_matches_unit_scope(
                    db, r, property_id=prop.id, allowed_unit_ids=aid, allowed_labels_lower=uset
                )
                and _presence_ledger_row_actor_is_tenant_or_guest_user(db, r)
                and not _ledger_row_hidden_from_tenant_live_timeline(r)
            ]
        else:
            log_rows = []
    ledger_ctx = build_ledger_display_resolution_context(db, log_rows)
    logs = []
    for r in log_rows:
        cat, title, msg = ledger_event_to_display(r, db, resolution_context=ledger_ctx)
        attr = audit_actor_attribution(db, actor_user_id=r.actor_user_id, property_id=prop.id)
        disc = ledger_record_disclosure_lines(r, display_title=title)
        logs.append(
            LiveLogEntry(
                category=cat,
                title=title,
                message=msg,
                created_at=r.created_at if r.created_at is not None else datetime.now(timezone.utc),
                actor_user_id=r.actor_user_id,
                actor_role=attr["role"],
                actor_role_label=attr["role_label"],
                actor_name=attr["name"],
                actor_email=attr["email"],
                event_source=disc.get("event_source"),
                business_meaning_on_record=disc.get("business_meaning_on_record"),
                trigger_on_record=disc.get("trigger_on_record"),
                state_change_on_record=disc.get("state_change_on_record"),
            )
        )
    if guest_slug_user_id is not None:
        logs = [lg for lg in logs if _safe_guest_audit_log_entry(lg)]

    # Invitations for this property – invite states indicate stay status (STAGED→pending, BURNED→accepted/stay, EXPIRED→ended, REVOKED→cancelled)
    inv_rows = (
        db.query(Invitation)
        .filter(Invitation.property_id == prop.id)
        .order_by(Invitation.created_at.desc())
        .limit(50)
    ).all()
    if tenant_slug_user_id is not None and tenant_slug_email_lower:
        inv_rows = [
            inv
            for inv in inv_rows
            if _invitation_matches_tenant_live_slug(inv, tenant_slug_email_lower, tenant_slug_user_id)
        ]
    if guest_slug_user_id is not None:
        inv_rows = [
            inv
            for inv in inv_rows
            if normalize_invitation_kind(getattr(inv, "invitation_kind", None)) == "guest"
            and (getattr(inv, "guest_email", None) or "").strip().lower() == guest_slug_user_email_lower
        ]
    # Tenants on the live page only see guest invitations they created (same scope as GET /dashboard/tenant/invitations);
    # tenant-lease invitations for the property remain visible so verification context is preserved.
    if effective_viewer is not None and getattr(effective_viewer, "role", None) == UserRole.tenant:
        inv_rows = [
            inv
            for inv in inv_rows
            if (getattr(inv, "invitation_kind", None) or "guest").strip().lower() != "guest"
            or getattr(inv, "invited_by_user_id", None) == effective_viewer.id
        ]
    unit_label_by_unit_id: dict[int, str] = {
        u.id: ((u.unit_label or "").strip() or "—") for u in units_for_live
    }
    invitations = []
    for inv in inv_rows:
        guest_label = label_from_invitation(db, inv)
        inv_kind = (getattr(inv, "invitation_kind", None) or "guest").strip().lower()
        inviter = (
            db.query(User).filter(User.id == getattr(inv, "invited_by_user_id", None)).first()
            if getattr(inv, "invited_by_user_id", None)
            else None
        )
        inviter_role = None
        if inviter and getattr(inviter, "role", None) is not None:
            ir = getattr(inviter, "role", None)
            inviter_role = ir.value if hasattr(ir, "value") else str(ir)
        agr_avail, agr_url = (False, None)
        if inv_kind == "guest":
            agr_avail, agr_url = _verify_signed_agreement_offer_for_invite_code(db, inv.invitation_code)
        inv_unit_id = getattr(inv, "unit_id", None)
        inv_unit_label: str | None = None
        if inv_unit_id is not None and inv_unit_id in unit_label_by_unit_id:
            inv_unit_label = unit_label_by_unit_id[inv_unit_id]
        elif not is_multi and units_for_live and len(units_for_live) == 1:
            inv_unit_label = (units_for_live[0].unit_label or "").strip() or "1"
        invitations.append(
            LiveInvitationSummary(
                invitation_code=inv.invitation_code,
                guest_label=guest_label,
                stay_start_date=inv.stay_start_date,
                stay_end_date=inv.stay_end_date,
                status=resolve_invitation_display_status(
                    inv,
                    today=today,
                    has_live_stay=bool(getattr(inv, "id", None) in invitation_ids_with_checked_in_stay),
                    db=db,
                ),
                token_state=getattr(inv, "token_state", None) or "STAGED",
                signed_agreement_available=agr_avail,
                signed_agreement_url=agr_url,
                invitation_kind=inv_kind,
                invited_by_role=inviter_role,
                invited_by_name=((getattr(inviter, "full_name", None) or "").strip() or None) if inviter else None,
                invited_by_email=((getattr(inviter, "email", None) or "").strip() or None) if inviter else None,
                unit_label=inv_unit_label,
            )
        )

    # Logged-in guests: hide tenant-lane rows from Invitation states (privacy / relevance).
    if effective_viewer is not None and effective_viewer.role == UserRole.guest:
        invitations = [
            inv for inv in invitations if not is_property_invited_tenant_signup_kind(inv.invitation_kind)
        ]

    scoped_unit_labels: list[str] = []
    if tenant_slug_user_id is not None:
        scoped_unit_labels = list(allowed_tenant_live_units)
    if guest_slug_user_id is not None:
        scoped_unit_labels = list(allowed_guest_live_units)

    current_tenant_assignments = _live_occupying_tenants_for_property(db, prop.id, today)
    tenant_summary_assignee, tenant_summary_assignment_period = _tenant_summary_strip(current_tenant_assignments)
    if personalized is not None:
        current_tenant_assignments, tenant_summary_assignee, tenant_summary_assignment_period = personalized
    if guest_slug_user_id is not None:
        current_tenant_assignments = []
        tenant_summary_assignee = None
        tenant_summary_assignment_period = None

    occ_summary = _live_occupancy_summary_detail(
        db, prop, display_occupancy, current_stays_live, current_tenant_assignments
    )
    prop_info = prop_info.model_copy(update={"occupancy_summary_detail": occ_summary})

    if tenant_slug_user_id is not None:
        owner_info = LiveOwnerInfo(full_name=owner_info.full_name, email="", phone=None)
        property_managers = []
        allowed_set = {x.strip() for x in allowed_tenant_live_units if x.strip()}
        filtered_us = [u for u in prop_info.unit_statuses if (u.unit_label or "").strip() in allowed_set]
        occ_ct = sum(
            1 for u in filtered_us if (u.occupancy_status or "").lower() == OccupancyStatus.occupied.value
        )
        n = len(filtered_us)
        prop_info = prop_info.model_copy(
            update={
                "name": None,
                "tax_id": None,
                "apn": None,
                "unit_statuses": filtered_us,
                "unit_count": max(1, n),
                "is_multi_unit": n > 1,
                "occupied_unit_count": occ_ct,
                "vacant_unit_count": max(0, n - occ_ct) if n else 0,
            }
        )
    if guest_slug_user_id is not None:
        owner_info = LiveOwnerInfo(full_name=owner_info.full_name, email="", phone=None)
        property_managers = []
        allowed_set = {x.strip() for x in allowed_guest_live_units if x.strip()}
        filtered_us = [u for u in prop_info.unit_statuses if (u.unit_label or "").strip() in allowed_set]
        occ_ct = sum(
            1 for u in filtered_us if (u.occupancy_status or "").lower() == OccupancyStatus.occupied.value
        )
        n = len(filtered_us)
        prop_info = prop_info.model_copy(
            update={
                "name": None,
                "tax_id": None,
                "apn": None,
                "unit_statuses": filtered_us,
                "unit_count": max(1, n),
                "is_multi_unit": n > 1,
                "occupied_unit_count": occ_ct,
                "vacant_unit_count": max(0, n - occ_ct) if n else 0,
            }
        )

    if current_stays_live:
        cg_rows = _live_guest_info_rows(db, slug, current_stays_live)
        authorization_state = resolve_live_property_authorization_state(
            has_current_guest_stays=True,
            all_current_stays_revoked=all(getattr(s, "revoked_at", None) for s in current_stays_live),
            has_last_ended_stay=False,
            viewer_is_record_owner_for_property=False,
        )
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
            link_audience=link_audience,
            scoped_unit_labels=scoped_unit_labels,
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

    if tenant_slug_user_id is not None:
        last_stay = None
        upcoming = []

    # Guest authorization on this page is about stays. Do not infer EXPIRED from property
    # occupancy alone — a new listing can be marked occupied or unknown while the tenant
    # invite is still pending and there are no guest stays yet.
    viewer_is_owner = False
    if effective_viewer is not None and getattr(effective_viewer, "role", None) == UserRole.owner:
        vprof = db.query(OwnerProfile).filter(OwnerProfile.user_id == effective_viewer.id).first()
        viewer_is_owner = bool(vprof and vprof.id == prop.owner_profile_id)
    authorization_state = resolve_live_property_authorization_state(
        has_current_guest_stays=False,
        all_current_stays_revoked=False,
        has_last_ended_stay=last_stay is not None,
        viewer_is_record_owner_for_property=viewer_is_owner,
    )

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
        link_audience=link_audience,
        scoped_unit_labels=scoped_unit_labels,
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

    status = resolve_verify_primary_guest_stay_status(inv, stay, today=today, db=db)

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
    audit_entries: list[LiveLogEntry] = []
    for r in log_rows:
        if (r.category or "").lower() == "presence":
            continue
        attr = audit_actor_attribution(db, actor_user_id=r.actor_user_id, property_id=prop.id)
        audit_entries.append(
            LiveLogEntry(
                category=r.category or "—",
                title=_scrub_emails_for_timeline_display(db, r.title or "—"),
                message=_scrub_emails_for_timeline_display(db, r.message or "—"),
                created_at=r.created_at if r.created_at is not None else now,
                actor_user_id=r.actor_user_id,
                actor_role=attr["role"],
                actor_role_label=attr["role_label"],
                actor_name=attr["name"],
                actor_email=attr["email"],
            )
        )

    occ = normalize_occupancy_status_for_display(
        db, prop.id, None, getattr(prop, "occupancy_status", None) or OccupancyStatus.vacant.value
    )
    if valid and (occ or "").lower() == "unknown":
        occ = "occupied"

    # Assigned tenant names only (no presence — verify is public / above-tenant).
    assigned_tenants: list[VerifyAssignedTenant] = []
    unit_id = stay.unit_id if stay else inv.unit_id
    if unit_id:
        tas = db.query(TenantAssignment).filter(TenantAssignment.unit_id == unit_id).all()
        for ta in tas:
            t_name = label_for_tenant_assignee(db, ta.user_id)
            assigned_tenants.append(VerifyAssignedTenant(name=t_name))

    # POA URL
    poa_url: str | None = None
    if poa_signed_at:
        poa_url = f"/public/live/{slug}/poa"

    # Event ledger entries (same full-property scope as GET /public/live/{slug})
    ledger_rows = merged_public_property_ledger_rows(db, prop.id, limit=500)
    verify_ledger_ctx = build_ledger_display_resolution_context(db, ledger_rows)
    ledger_entries = []
    for lr in ledger_rows:
        cat, title, msg = ledger_event_to_display(lr, db, resolution_context=verify_ledger_ctx)
        attr = audit_actor_attribution(db, actor_user_id=lr.actor_user_id, property_id=prop.id)
        ledger_entries.append(LiveLogEntry(
            category=cat,
            title=title,
            message=msg,
            created_at=lr.created_at if lr.created_at is not None else now,
            actor_user_id=lr.actor_user_id,
            actor_role=attr["role"],
            actor_role_label=attr["role_label"],
            actor_name=attr["name"],
            actor_email=attr["email"],
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
            s_status = resolve_verify_guest_authorization_history_status(s, today=today)
            s_revoked = getattr(s, "revoked_at", None)
            s_cancelled = getattr(s, "cancelled_at", None)
            s_checkout = getattr(s, "checked_out_at", None)
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
        poa_url=poa_url,
        verified_at=now,
        authorization_history=authorization_history,
        verification_subject="tenant_invite" if inv_kind == "tenant" else "guest_stay",
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
    resolved_inv_status = resolve_invitation_display_status(inv, today=today, db=db)

    # Determine validity and reason
    valid = False
    reason = ""
    if resolved_inv_status not in ("accepted", "active"):
        create_log(
            db,
            CATEGORY_VERIFY_ATTEMPT,
            "Verify attempt – invitation not active",
            f"Invitation resolved status={resolved_inv_status}",
            property_id=prop.id,
            invitation_id=inv.id,
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "invitation_not_active", "resolved_status": resolved_inv_status},
        )
        db.commit()
        if resolved_inv_status == "cancelled":
            reason_msg = "Status: CANCELLED — Assignment or invitation was cancelled."
        elif resolved_inv_status == "expired":
            reason_msg = "Status: EXPIRED — Invitation or stay has ended."
        elif resolved_inv_status == "accepted":
            reason_msg = "Status: ACCEPTED — Invitation accepted; active stay window has not started."
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
    prop, _tenant_slug_user_id, _guest_slug_user_id, _guest_slug_unit_id = _resolve_live_slug_context(db, slug)
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
    prop, _tenant_slug_user_id, _guest_slug_user_id, _guest_slug_unit_id = _resolve_live_slug_context(db, slug)
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
