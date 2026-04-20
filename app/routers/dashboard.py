"""Module F: Legal restrictions & law display (Owner and Guest views)."""
from typing import Any

import logging
import secrets
import time
from datetime import date, datetime, timezone, timedelta, time as dt_time

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Request, Body, Header
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, case
from pydantic import BaseModel, Field, EmailStr, field_validator
from app.database import get_db
from app.utils.client_calendar import parse_client_calendar_date_header as _parse_guest_client_calendar_date_header, effective_today_for_invite_start
from app.models.user import User, UserRole
from app.models.stay import Stay
from app.models.demo_account import is_demo_user_id
from app.models.invitation import Invitation
from app.models.guest import GuestProfile, PurposeOfStay, RelationshipToOwner
from app.models.region_rule import RegionRule
from app.models.owner import Property, OwnerProfile, USAT_TOKEN_STAGED, USAT_TOKEN_RELEASED, OccupancyStatus


def _property_address_line(prop: Property | None) -> str | None:
    """Single line for UI: street, city, state, zip (same style as tenant invite summaries)."""
    if not prop:
        return None
    parts: list[str] = []
    for attr in ("street", "city", "state"):
        v = getattr(prop, attr, None)
        if v:
            parts.append(str(v).strip())
    z = getattr(prop, "zip_code", None)
    if z:
        parts.append(str(z).strip())
    return ", ".join(parts) if parts else None

from app.models.property_transfer_invitation import PropertyTransferInvitation
from app.models.guest_pending_invite import GuestPendingInvite
from app.models.agreement_signature import AgreementSignature
from app.models.region_rule import StayClassification, RiskLevel
from app.schemas.dashboard import (
    OwnerStayView,
    OwnerInvitationView,
    GuestStayView,
    GuestPendingInviteView,
    TenantGuestExtensionRequestView,
    JurisdictionStatuteInDashboard,
    OwnerAuditLogEntry,
    BillingResponse,
    BillingInvoiceView,
    BillingPaymentView,
    BillingPortalSessionResponse,
    BillingSyncSubscriptionResponse,
    PortfolioLinkResponse,
    DashboardAlertView,
)
from app.services.jle import resolve_jurisdiction
from app.services.jurisdiction_sot import get_jurisdiction_for_property
from app.services.audit_log import create_log, CATEGORY_STATUS_CHANGE, CATEGORY_PRESENCE, CATEGORY_DEAD_MANS_SWITCH, CATEGORY_FAILED_ATTEMPT, CATEGORY_BILLING, CATEGORY_SHIELD_MODE
from app.services.event_ledger import (
    create_ledger_event,
    ledger_event_to_display,
    get_actor_email,
    get_actor_display_name,
    _CATEGORY_TO_ACTION_TYPES,
    OWNER_BUSINESS_ACTIONS,
    OWNER_PERSONAL_ACTIONS,
    TENANT_ALLOWED_ACTIONS,
    GUEST_ALLOWED_ACTIONS,
    ACTION_PROPERTY_DELETED,
    ACTION_PROPERTY_UPDATED,
    ACTION_BILLING_INVOICE_PAID,
    ACTION_BILLING_INVOICE_CREATED,
    ACTION_BILLING_SUBSCRIPTION_STARTED,
    ACTION_GUEST_INVITE_CANCELLED,
    ACTION_GUEST_INVITE_CREATED,
    ACTION_CONFIRMED_STILL_VACANT,
    ACTION_STAY_REVOKED,
    ACTION_UNIT_VACATED,
    ACTION_DMS_DISABLED,
    ACTION_LEASE_RENEWED,
    ACTION_HOLDOVER_CONFIRMED,
    ACTION_GUEST_CHECK_IN,
    ACTION_GUEST_CHECK_OUT,
    ACTION_TENANT_CHECK_OUT,
    ACTION_TENANT_ASSIGNMENT_CANCELLED,
    ACTION_STAY_CANCELLED,
    ACTION_GUEST_EXTENSION_REQUESTED,
    ACTION_GUEST_EXTENSION_APPROVED,
    ACTION_GUEST_EXTENSION_DECLINED,
    ACTION_PRESENCE_STATUS_CHANGED,
    ACTION_AWAY_ACTIVATED,
    ACTION_AWAY_ENDED,
    format_dt_display,
    ACTION_SHIELD_MODE_ON,
    ACTION_SHIELD_MODE_OFF,
    ACTION_PROPERTY_TRANSFER_PRIOR_OWNER,
)
from app.services.invitation_cleanup import get_invitation_expire_cutoff
from app.services.invitation_kinds import (
    TENANT_UNIT_LEASE_KINDS,
    is_property_invited_tenant_signup_kind,
    is_standard_tenant_invite_kind,
    is_tenant_lease_extension_kind,
)
from app.services.tenant_lease_window import (
    find_invitation_matching_tenant_assignment,
    find_tenant_assignment_matching_invitation,
    list_invitations_matching_tenant_assignment_lease,
)
from app.services.tenant_lease_cohort import (
    cohort_key_for_pending_invitation,
    count_cohort_members,
    map_assignment_id_to_cohort_key,
)
from app.services.invitation_guest_completion import guest_invitation_signing_started
from app.services.billing import (
    SUBSCRIPTION_FLAT_AMOUNT_CENTS,
    _count_properties_and_shield,
    sync_subscription_quantities,
    stripe_subscription_status_and_trial,
)
from app.services.shield_mode_policy import SHIELD_MODE_ALWAYS_ON
from app.services.notifications import (
    send_vacate_12h_notice,
    send_owner_guest_checkout_email,
    send_guest_checkout_confirmation_email,
    send_owner_guest_cancelled_stay_email,
    send_removal_notice_to_guest,
    send_removal_confirmation_to_owner,
    send_shield_mode_turned_on_notification,
    send_shield_mode_turned_off_notification,
    send_dms_turned_off_notification,
    send_guest_extension_request_to_tenant_email,
    send_guest_extension_approved_email,
    send_guest_extension_declined_email,
    send_email,
)
from app.services.privacy_lanes import is_tenant_lane_stay
from app.services.dashboard_alerts import create_alert_for_owner_and_managers, create_alert_for_user
from app.schemas.jle import JLEInput
from app.dependencies import get_current_user, require_owner, require_owner_onboarding_complete, require_guest, require_tenant, require_guest_or_tenant, require_owner_or_manager, require_property_manager, require_property_manager_identity_verified, get_context_mode
from app.models.audit_log import AuditLog
from app.models.event_ledger import EventLedger
from app.models.dashboard_alert import DashboardAlert
from app.services.agreements import fill_guest_signature_in_content, agreement_content_to_pdf
from app.services.dropbox_sign import get_signed_pdf
from app.services.invitation_agreement_ledger import emit_invitation_agreement_signed_if_dropbox_complete
from app.models.unit import Unit


def _unit_label_if_multi_unit(db: Session, property_id: int | None, unit_id: int | None) -> str | None:
    """Return unit label for dashboard lists when the property is multi-unit."""
    if not property_id or not unit_id:
        return None
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop or not bool(getattr(prop, "is_multi_unit", False)):
        return None
    u = db.query(Unit).filter(Unit.id == unit_id).first()
    if not u:
        return None
    lab = (getattr(u, "unit_label", None) or "").strip()
    return lab or None


from app.models.guest_extension_request import GuestExtensionRequest
from app.models.tenant_assignment import TenantAssignment
from app.models.property_manager_assignment import PropertyManagerAssignment
from app.models.resident_presence import ResidentPresence, PresenceStatus
from app.models.owner_poa_signature import OwnerPOASignature
from app.models.stay_presence import StayPresence, PresenceAwayPeriod
from app.services.permissions import (
    can_access_unit,
    can_access_property,
    can_confirm_occupancy,
    can_confirm_occupancy_for_tenant_assignment,
    can_perform_action,
    Action,
    get_owner_personal_mode_units,
    get_manager_personal_mode_units,
    get_owner_personal_mode_property_ids,
    get_manager_personal_mode_property_ids,
    owner_profile_property_ids,
    owner_personal_guest_scope_unit_ids,
    invitation_in_owner_personal_guest_scope,
    stay_in_owner_personal_guest_scope,
    invitation_in_manager_personal_guest_scope,
    stay_in_manager_personal_guest_scope,
    user_owns_property_by_profile,
)
from app.services.privacy_lanes import (
    is_tenant_lane_invitation,
    is_tenant_lane_stay,
    get_tenant_lane_invitation_ids,
    get_tenant_lane_stay_ids,
    filter_property_lane_invitations_for_owner,
    filter_property_lane_stays_for_owner,
    filter_property_lane_invitations_for_manager,
    filter_property_lane_stays_for_manager,
    filter_tenant_lane_from_ledger_rows,
    filter_tenant_presence_from_owner_manager_ledger,
    filter_manager_presence_on_tenant_leased_units,
    REDACTED_GUEST_AUTHORIZATION_LABEL,
    viewer_is_relationship_owner_for_stay,
    viewer_is_relationship_owner_for_invitation,
)
from app.services.display_names import label_for_stay, label_from_invitation, label_from_user_id
from app.services.occupancy import get_property_display_occupancy_status
from app.services.occupancy import normalize_occupancy_status_for_display, get_unit_display_occupancy_status
from app.config import get_settings
from app.services.stay_timer import (
    _status_confirmation_eligible_stay,
    dms_test_mode_effective_end_utc,
    dms_test_mode_unknown_deadline_utc,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class TenantGuestInvitationCreate(BaseModel):
    unit_id: int = Field(..., gt=0, description="Unit ID (required)")
    guest_name: str = Field("", description="Guest full name")
    guest_email: EmailStr = Field(..., description="Guest email (required); only this address can accept the invite")
    checkin_date: str = Field("", description="Start date (YYYY-MM-DD)")
    checkout_date: str = Field("", description="End date (YYYY-MM-DD)")
    client_calendar_date: str | None = Field(
        None,
        description="Browser local calendar date YYYY-MM-DD (same as X-Client-Calendar-Date); preferred when headers are stripped by proxies",
    )

    @field_validator("guest_email", mode="before")
    @classmethod
    def _strip_tenant_guest_email(cls, v: object) -> str:
        if v is None:
            raise ValueError("Guest email is required")
        s = str(v).strip()
        if not s:
            raise ValueError("Guest email is required")
        return s


class BulkShieldModeRequest(BaseModel):
    property_ids: list[int] = Field(..., description="Property IDs to update")
    shield_mode_enabled: bool = Field(..., description="True to turn Shield ON, False to turn OFF")


class TenantDeadMansSwitchRequest(BaseModel):
    unit_id: int = Field(..., gt=0, description="Assigned unit ID")
    dead_mans_switch_enabled: bool = Field(..., description="True to enable, False to disable")


class GuestExtensionRequestBody(BaseModel):
    """Optional note from guest; routed to the tenant who invited them only."""
    message: str | None = Field(None, max_length=500)


class TenantExtensionDecisionBody(BaseModel):
    """Optional note from tenant, emailed to the guest when declining an extension request."""
    message: str | None = Field(None, max_length=1000)


class TenantApproveExtensionBody(BaseModel):
    """Approve: extension is fulfilled by a new guest invitation; guest email must include its link."""
    invitation_code: str = Field(..., min_length=1, max_length=512, description="Invite ID or full invite URL for the new dates")
    message: str | None = Field(None, max_length=1000)


# Alert types each role is allowed to see (only role-relevant alerts are returned).
_ALERT_TYPES_BY_ROLE = {
    UserRole.owner: {
        "overstay",
        "nearing_expiration",
        "dms_48h",
        "dms_urgent",
        "dms_executed",
        "dms_reminder",
        "tenant_lease_48h",
        "tenant_lease_urgent",
        "shield_on", "revoked", "renewed", "vacated", "holdover", "expired",
        "invitation_expired", "invitation_accepted", "tenant_accepted",
        "vacant_monitoring", "removal_initiated",
        "property_transfer_completed",
        "property_transfer_accepted",
        "property_transfer_invited",
        "property_transfer_invite_expired",
    },
    UserRole.property_manager: {
        "overstay",
        "nearing_expiration",
        "dms_48h",
        "dms_urgent",
        "dms_executed",
        "dms_reminder",
        "tenant_lease_48h",
        "tenant_lease_urgent",
        "shield_on", "revoked", "renewed", "vacated", "holdover", "expired",
        "invitation_expired", "invitation_accepted", "tenant_accepted",
        "vacant_monitoring", "removal_initiated",
        "property_transfer_completed",
        "property_transfer_accepted",
        "property_transfer_invited",
        "property_transfer_invite_expired",
    },
    UserRole.guest: {"overstay", "nearing_expiration", "revoked", "expired", "removal_initiated"},
    UserRole.tenant: {
        "invitation_expired",
        "invitation_accepted",
        "guest_stay_ending",
        "guest_extension_request",
        "revoked",  # you revoked a guest stay you invited (tenant lane; not shown to owners/managers)
    },
    UserRole.admin: None,  # None = no filter, show all
}

# Owner/manager personal mode: only in-app alerts tied to a property-lane guest invitation or stay on
# personal-mode units (not tenant lane). Excludes billing (no invitation/stay), shield, vacant monitoring,
# tenant_accepted, and any alert with only a property_id.
_OWNER_PERSONAL_GUEST_ALERT_TYPES = frozenset(
    {
        "invitation_expired",
        "invitation_accepted",
        "revoked",
        "overstay",
        "nearing_expiration",
        "dms_48h",
        "dms_urgent",
        "dms_executed",
        "dms_reminder",
        "tenant_lease_48h",
        "tenant_lease_urgent",
        "renewed",
        "vacated",
        "holdover",
        "expired",
        "removal_initiated",
    }
)

# Ownership-transfer alerts: show in personal mode too (account-level, not guest-lane).
_PROPERTY_TRANSFER_ALERT_TYPES = frozenset(
    {
        "property_transfer_completed",
        "property_transfer_accepted",
        "property_transfer_invited",
        "property_transfer_invite_expired",
    }
)


def _owner_alert_allowed_personal_guest_mode(
    db: Session, alert: DashboardAlert, allowed_unit_ids: set[int]
) -> bool:
    if alert.alert_type not in _OWNER_PERSONAL_GUEST_ALERT_TYPES:
        return False
    inv_id = getattr(alert, "invitation_id", None)
    stay_id = getattr(alert, "stay_id", None)
    if not inv_id and not stay_id:
        return False
    if inv_id:
        inv = db.query(Invitation).filter(Invitation.id == inv_id).first()
        if not inv or is_tenant_lane_invitation(db, inv):
            return False
        if not invitation_in_owner_personal_guest_scope(db, inv, allowed_unit_ids):
            return False
    if stay_id:
        stay = db.query(Stay).filter(Stay.id == stay_id).first()
        if not stay or is_tenant_lane_stay(db, stay):
            return False
        if not stay_in_owner_personal_guest_scope(db, stay, allowed_unit_ids):
            return False
    return True


def _manager_alert_allowed_personal_guest_mode(
    db: Session, alert: DashboardAlert, manager_unit_ids: set[int]
) -> bool:
    if alert.alert_type not in _OWNER_PERSONAL_GUEST_ALERT_TYPES:
        return False
    inv_id = getattr(alert, "invitation_id", None)
    stay_id = getattr(alert, "stay_id", None)
    if not inv_id and not stay_id:
        return False
    if inv_id:
        inv = db.query(Invitation).filter(Invitation.id == inv_id).first()
        if not inv or is_tenant_lane_invitation(db, inv):
            return False
        if not invitation_in_manager_personal_guest_scope(db, inv, manager_unit_ids):
            return False
    if stay_id:
        stay = db.query(Stay).filter(Stay.id == stay_id).first()
        if not stay or is_tenant_lane_stay(db, stay):
            return False
        if not stay_in_manager_personal_guest_scope(db, stay, manager_unit_ids):
            return False
    return True


@router.get("/alerts", response_model=list[DashboardAlertView])
def list_alerts(
    unread_only: bool = False,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    context_mode: str = Depends(get_context_mode),
):
    """List in-platform dashboard alerts for the current user. Only alerts relevant to the user's role are returned.
    Business mode (owner/manager): alerts for owned/assigned properties plus account-level (no property_id).
    Personal mode (owner): only property-lane guest invitation/stay alerts scoped to the owner's personal-mode units —
    no billing, no tenant_accepted, no shield/vacant monitoring, no property-only rows.
    Personal mode (manager): same rule for on-site resident units. Tenant-lane notifications never show to owners/managers."""
    q = db.query(DashboardAlert).filter(DashboardAlert.user_id == current_user.id)
    if unread_only:
        q = q.filter(DashboardAlert.read_at.is_(None))
    allowed_types = _ALERT_TYPES_BY_ROLE.get(current_user.role)
    if allowed_types is not None:
        q = q.filter(DashboardAlert.alert_type.in_(allowed_types))
    q = q.order_by(DashboardAlert.created_at.desc()).limit(limit)
    alerts = q.all()

    # Scope by context mode for owner and property_manager: business vs personal property set; exclude tenant-lane in both modes
    if current_user.role in (UserRole.owner, UserRole.property_manager):
        if context_mode == "business":
            if current_user.role == UserRole.owner:
                profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
                allowed_property_ids = (
                    [p.id for p in db.query(Property).filter(Property.owner_profile_id == profile.id, Property.deleted_at.is_(None)).all()]
                    if profile is not None else []
                )
            else:
                allowed_property_ids = [
                    r[0] for r in db.query(PropertyManagerAssignment.property_id).filter(
                        PropertyManagerAssignment.user_id == current_user.id,
                    ).all()
                ]
            # Business: include alerts with no property_id (e.g. billing) or property_id in business set
            allowed_property_ids_set = set(allowed_property_ids)
            alerts = [a for a in alerts if a.property_id is None or a.property_id in allowed_property_ids_set]
        else:
            # Personal mode: only property-lane guest invite/stay alerts on personal-mode units (see module constants).
            if current_user.role == UserRole.owner:
                allowed_units = owner_personal_guest_scope_unit_ids(db, current_user.id)
                if not allowed_units:
                    alerts = []
                else:
                    alerts = [
                        a
                        for a in alerts
                        if _owner_alert_allowed_personal_guest_mode(db, a, allowed_units)
                        or (a.alert_type in _PROPERTY_TRANSFER_ALERT_TYPES)
                    ]
            else:
                manager_units = set(get_manager_personal_mode_units(db, current_user.id))
                if not manager_units:
                    alerts = []
                else:
                    alerts = [
                        a
                        for a in alerts
                        if _manager_alert_allowed_personal_guest_mode(db, a, manager_units)
                        or (a.alert_type in _PROPERTY_TRANSFER_ALERT_TYPES)
                    ]

        # Exclude tenant-lane: owners/managers never see notifications about tenant-invited guests
        inv_ids = [a.invitation_id for a in alerts if getattr(a, "invitation_id", None) is not None]
        stay_ids = [a.stay_id for a in alerts if getattr(a, "stay_id", None) is not None]
        tenant_inv_ids = get_tenant_lane_invitation_ids(db, inv_ids) if inv_ids else set()
        tenant_stay_ids = get_tenant_lane_stay_ids(db, stay_ids) if stay_ids else set()
        alerts = [
            a for a in alerts
            if getattr(a, "invitation_id", None) not in tenant_inv_ids and getattr(a, "stay_id", None) not in tenant_stay_ids
        ]

    return [DashboardAlertView.model_validate(a) for a in alerts]


@router.patch("/alerts/{alert_id}/read", response_model=DashboardAlertView)
def mark_alert_read(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a dashboard alert as read."""
    alert = db.query(DashboardAlert).filter(DashboardAlert.id == alert_id, DashboardAlert.user_id == current_user.id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert.read_at is None:
        alert.read_at = datetime.now(timezone.utc)
        db.add(alert)
        db.commit()
        db.refresh(alert)
    return DashboardAlertView.model_validate(alert)


@router.post("/alerts/mark-occupancy-prompt-read/{stay_id}")
def mark_occupancy_prompt_alerts_read(
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
):
    """After Vacant/Occupied response, mark all unread lease-end confirmation alerts for this stay for the current user."""
    stay = db.query(Stay).filter(Stay.id == stay_id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    if not can_confirm_occupancy(db, current_user, stay):
        raise HTTPException(status_code=403, detail="You do not have permission to clear these alerts for this stay")
    now = datetime.now(timezone.utc)
    marked = 0
    for alert in (
        db.query(DashboardAlert)
        .filter(
            DashboardAlert.user_id == current_user.id,
            DashboardAlert.stay_id == stay_id,
            DashboardAlert.alert_type.in_(["dms_48h", "dms_urgent", "dms_reminder"]),
            DashboardAlert.read_at.is_(None),
        )
        .all()
    ):
        alert.read_at = now
        db.add(alert)
        marked += 1
    db.commit()
    return {"status": "success", "marked_count": marked}


def _mark_tenant_lease_occupancy_alerts_read(db: Session, user_id: int, tenant_assignment_id: int) -> int:
    now = datetime.now(timezone.utc)
    marked = 0
    for alert in (
        db.query(DashboardAlert)
        .filter(
            DashboardAlert.user_id == user_id,
            DashboardAlert.alert_type.in_(["tenant_lease_48h", "tenant_lease_urgent"]),
            DashboardAlert.read_at.is_(None),
        )
        .all()
    ):
        meta = alert.meta or {}
        if meta.get("tenant_assignment_id") != tenant_assignment_id:
            continue
        alert.read_at = now
        db.add(alert)
        marked += 1
    return marked


@router.get("/guest/pending-invites", response_model=list[GuestPendingInviteView])
def guest_pending_invites(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest_or_tenant),
):
    """List invitations this guest/tenant has as pending (saved from dashboard paste or login/signup with link; not yet signed)."""
    if current_user.role == UserRole.tenant:
        return []
    pendings = (
        db.query(GuestPendingInvite)
        .filter(GuestPendingInvite.user_id == current_user.id)
        .all()
    )
    out = []
    guest_email = (current_user.email or "").strip().lower()
    for p in pendings:
        inv = db.query(Invitation).filter(Invitation.id == p.invitation_id, Invitation.status.in_(["pending", "ongoing", "accepted"])).first()
        if not inv:
            continue
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
        unit_label_val = None
        if getattr(inv, "unit_id", None):
            unit_row = db.query(Unit).filter(Unit.id == inv.unit_id).first()
            if unit_row:
                unit_label_val = unit_row.unit_label
        owner = db.query(User).filter(User.id == inv.owner_id).first()
        host_name = (owner.full_name if owner else None) or (owner.email if owner else "")
        needs_dropbox = False
        pending_sig_id = None
        accept_now_sig_id = None
        if guest_email:
            sig = (
                db.query(AgreementSignature)
                .filter(
                    AgreementSignature.invitation_code == inv.invitation_code,
                    AgreementSignature.guest_email == guest_email,
                    AgreementSignature.used_by_user_id.is_(None),
                )
                .order_by(AgreementSignature.signed_at.desc())
                .first()
            )
            if sig:
                if getattr(sig, "dropbox_sign_request_id", None):
                    if not getattr(sig, "signed_pdf_bytes", None):
                        pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
                        if pdf_bytes:
                            sig.signed_pdf_bytes = pdf_bytes
                            emit_invitation_agreement_signed_if_dropbox_complete(db, sig)
                            db.commit()
                            db.refresh(sig)
                    if not getattr(sig, "signed_pdf_bytes", None):
                        needs_dropbox = True
                        pending_sig_id = sig.id
                    elif getattr(sig, "used_by_user_id", None) is None:
                        accept_now_sig_id = sig.id
                elif getattr(sig, "signed_pdf_bytes", None) and getattr(sig, "used_by_user_id", None) is None:
                    accept_now_sig_id = sig.id
        out.append(
            GuestPendingInviteView(
                invitation_code=inv.invitation_code,
                property_name=property_name,
                property_deleted_at=getattr(prop, "deleted_at", None) if prop else None,
                unit_label=unit_label_val,
                stay_start_date=inv.stay_start_date,
                stay_end_date=inv.stay_end_date,
                host_name=host_name,
                region_code=inv.region_code,
                needs_dropbox_signature=needs_dropbox,
                pending_signature_id=pending_sig_id,
                accept_now_signature_id=accept_now_sig_id,
            )
        )
    return out


@router.post("/guest/pending-invites", response_model=GuestPendingInviteView)
def guest_add_pending_invite(
    request: Request,
    invitation_code: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest_or_tenant),
):
    """Add an invitation to this guest's or tenant's pending list. Used when a logged-in guest or tenant pastes an invitation link on the dashboard or after login/signup with link. Returns invite details; frontend then shows the agreement modal to view and sign."""
    code = (invitation_code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="invitation_code is required")
    inv = db.query(Invitation).filter(
        Invitation.invitation_code == code,
        Invitation.status.in_(["pending", "ongoing", "accepted"]),
        or_(
            Invitation.invitation_kind.in_(tuple(TENANT_UNIT_LEASE_KINDS)),
            Invitation.token_state != "BURNED",
        ),
    ).first()
    if not inv:
        ip = request.client.host if request.client else None
        ua = (request.headers.get("user-agent") or "").strip() or None
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Invalid or expired invitation code",
            f"Guest attempted to add pending invite with invalid or expired code: {code}.",
            property_id=None,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=ip,
            user_agent=ua,
            meta={"invitation_code_attempted": code},
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired invitation code")

    inv_kind = (getattr(inv, "invitation_kind", None) or "guest").strip().lower()
    if inv_kind == "guest" and current_user.role == UserRole.tenant:
        raise HTTPException(
            status_code=400,
            detail="Guest invitations must be completed with a guest account. Sign out and register or sign in as a guest using the invited email address.",
        )
    # Reject if invitation was sent to a different email address
    inv_guest_email = (getattr(inv, "guest_email", None) or "").strip().lower()
    if inv_kind == "guest" and not inv_guest_email:
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Add pending invite: guest invitation missing guest_email",
            f"User {current_user.email} attempted to add guest invitation {code} with no guest_email on record.",
            property_id=inv.property_id,
            invitation_id=inv.id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "").strip() or None,
            meta={"invitation_code": code},
        )
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="This invitation link is incomplete. Ask your host to send a new invitation that includes your email address.",
        )
    if inv_guest_email and (current_user.email or "").strip().lower() != inv_guest_email:
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Add pending invite: email mismatch",
            f"User {current_user.email} attempted to add invitation {code} intended for {inv.guest_email}.",
            property_id=inv.property_id,
            invitation_id=inv.id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "").strip() or None,
            meta={"invitation_code": code, "invitation_guest_email": inv.guest_email},
        )
        db.commit()
        raise HTTPException(
            status_code=403,
            detail="This invitation was sent to a different email address. You cannot add an invitation intended for someone else.",
        )

    # Reject if this invitation overlaps any existing stay for this guest (block before signing)
    existing_stays = db.query(Stay).filter(Stay.guest_id == current_user.id).all()
    for s in existing_stays:
        if inv.stay_start_date < s.stay_end_date and inv.stay_end_date > s.stay_start_date:
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Add pending invite: overlapping stay",
                f"Guest attempted to add invitation {code} which overlaps with existing stay(s).",
                property_id=inv.property_id,
                invitation_id=inv.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code": code},
            )
            db.commit()
            raise HTTPException(
                status_code=400,
                detail="This invitation overlaps with an existing stay. Only one stay can be accepted at a time.",
            )

    existing = (
        db.query(GuestPendingInvite)
        .filter(GuestPendingInvite.user_id == current_user.id, GuestPendingInvite.invitation_id == inv.id)
        .first()
    )
    if existing:
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
        owner = db.query(User).filter(User.id == inv.owner_id).first()
        host_name = (owner.full_name if owner else None) or (owner.email if owner else "")
        needs_dropbox, pending_sig_id = False, None
        accept_now_sig_id = None
        guest_email = (current_user.email or "").strip().lower()
        if guest_email:
            sig = (
                db.query(AgreementSignature)
                .filter(
                    AgreementSignature.invitation_code == inv.invitation_code,
                    AgreementSignature.guest_email == guest_email,
                    AgreementSignature.used_by_user_id.is_(None),
                )
                .order_by(AgreementSignature.signed_at.desc())
                .first()
            )
            if sig:
                if getattr(sig, "dropbox_sign_request_id", None):
                    if not getattr(sig, "signed_pdf_bytes", None):
                        pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
                        if pdf_bytes:
                            sig.signed_pdf_bytes = pdf_bytes
                            emit_invitation_agreement_signed_if_dropbox_complete(db, sig)
                            db.commit()
                            db.refresh(sig)
                    if not getattr(sig, "signed_pdf_bytes", None):
                        needs_dropbox, pending_sig_id = True, sig.id
                    elif getattr(sig, "used_by_user_id", None) is None:
                        accept_now_sig_id = sig.id
                elif getattr(sig, "signed_pdf_bytes", None) and getattr(sig, "used_by_user_id", None) is None:
                    accept_now_sig_id = sig.id
        unit_label_val = None
        if getattr(inv, "unit_id", None):
            unit_row = db.query(Unit).filter(Unit.id == inv.unit_id).first()
            if unit_row:
                unit_label_val = unit_row.unit_label
        return GuestPendingInviteView(
            invitation_code=inv.invitation_code,
            property_name=property_name,
            property_deleted_at=getattr(prop, "deleted_at", None) if prop else None,
            unit_label=unit_label_val,
            stay_start_date=inv.stay_start_date,
            stay_end_date=inv.stay_end_date,
            host_name=host_name,
            region_code=inv.region_code,
            needs_dropbox_signature=needs_dropbox,
            pending_signature_id=pending_sig_id,
            accept_now_signature_id=accept_now_sig_id,
        )
    pending = GuestPendingInvite(user_id=current_user.id, invitation_id=inv.id)
    db.add(pending)
    db.commit()
    prop = db.query(Property).filter(Property.id == inv.property_id).first()
    property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
    unit_label_val = None
    if getattr(inv, "unit_id", None):
        unit_row = db.query(Unit).filter(Unit.id == inv.unit_id).first()
        if unit_row:
            unit_label_val = unit_row.unit_label
    owner = db.query(User).filter(User.id == inv.owner_id).first()
    host_name = (owner.full_name if owner else None) or (owner.email if owner else "")
    # Check for an existing completed signature so the frontend can accept directly without re-signing
    needs_dropbox = False
    pending_sig_id = None
    accept_now_sig_id = None
    guest_email = (current_user.email or "").strip().lower()
    if guest_email:
        sig = (
            db.query(AgreementSignature)
            .filter(
                AgreementSignature.invitation_code == inv.invitation_code,
                AgreementSignature.guest_email == guest_email,
                AgreementSignature.used_by_user_id.is_(None),
            )
            .order_by(AgreementSignature.signed_at.desc())
            .first()
        )
        if sig:
            if getattr(sig, "dropbox_sign_request_id", None):
                if not getattr(sig, "signed_pdf_bytes", None):
                    pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
                    if pdf_bytes:
                        sig.signed_pdf_bytes = pdf_bytes
                        emit_invitation_agreement_signed_if_dropbox_complete(db, sig)
                        db.commit()
                        db.refresh(sig)
                if not getattr(sig, "signed_pdf_bytes", None):
                    needs_dropbox = True
                    pending_sig_id = sig.id
                elif getattr(sig, "used_by_user_id", None) is None:
                    accept_now_sig_id = sig.id
            elif getattr(sig, "signed_pdf_bytes", None) and getattr(sig, "used_by_user_id", None) is None:
                accept_now_sig_id = sig.id
    return GuestPendingInviteView(
        invitation_code=inv.invitation_code,
        property_name=property_name,
        property_deleted_at=getattr(prop, "deleted_at", None) if prop else None,
        unit_label=unit_label_val,
        stay_start_date=inv.stay_start_date,
        stay_end_date=inv.stay_end_date,
        host_name=host_name,
        region_code=inv.region_code,
        needs_dropbox_signature=needs_dropbox,
        pending_signature_id=pending_sig_id,
        accept_now_signature_id=accept_now_sig_id,
    )


@router.get("/owner/tenants")
def owner_tenants(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """List tenants (assigned + pending invitation) for the owner's properties. Business-mode safe."""
    from app.services.state_resolver import resolve_tenant_state
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        return []
    prop_ids = [p.id for p in profile.properties]
    if not prop_ids:
        return []
    unit_rows = db.query(Unit).filter(Unit.property_id.in_(prop_ids)).all()
    unit_map = {u.id: u for u in unit_rows}
    unit_ids = list(unit_map.keys())
    prop_map = {p.id: p for p in db.query(Property).filter(Property.id.in_(prop_ids)).all()}
    out = []
    seen_unit_user = set()
    all_owner_tas = (
        db.query(TenantAssignment).filter(TenantAssignment.unit_id.in_(unit_ids)).all() if unit_ids else []
    )
    assignment_cohort_map = map_assignment_id_to_cohort_key(all_owner_tas)

    if unit_ids:
        assignments = (
            db.query(TenantAssignment)
            .filter(TenantAssignment.unit_id.in_(unit_ids))
            .order_by(TenantAssignment.created_at.desc())
            .all()
        )
        for ta in assignments:
            tenant = db.query(User).filter(User.id == ta.user_id).first()
            unit = unit_map.get(ta.unit_id)
            prop = prop_map.get(unit.property_id) if unit else None
            today = date.today()
            seen_unit_user.add((ta.unit_id, ta.user_id))
            start = ta.start_date
            end = ta.end_date
            inv_code = None
            tenant_email = (tenant.email or "").strip().lower() if tenant else ""
            inv = None
            if tenant_email:
                inv = find_invitation_matching_tenant_assignment(db, ta, user_email_lower=tenant_email)
            if not inv:
                inv = find_invitation_matching_tenant_assignment(db, ta, user_email_lower=None)
            if inv:
                start = start or inv.stay_start_date
                end = end or inv.stay_end_date
                inv_code = inv.invitation_code
            resolved = resolve_tenant_state(db, tenant_assignment=ta, tenant_invitation=inv)
            active = resolved.assignment_status == "active"
            overall_status = resolved.assignment_status  # pending | accepted | active | expired
            out.append({
                "id": ta.id,
                "invitation_id": inv.id if inv else None,
                "tenant_name": (tenant.full_name if tenant else None) or (tenant.email if tenant else "Unknown"),
                "tenant_email": tenant.email if tenant else None,
                "property_name": (prop.name if prop else None) or "Property",
                "property_address_line": _property_address_line(prop),
                "property_id": prop.id if prop else None,
                "unit_label": unit.unit_label if unit else None,
                "unit_id": ta.unit_id,
                "start_date": str(start) if start else None,
                "end_date": str(end) if end else None,
                "active": active,
                # Source of truth is invite_status/assignment_status/stay_status.
                "status": overall_status,
                "invite_status": resolved.invite_status,
                "assignment_status": resolved.assignment_status,
                "stay_status": resolved.stay_status,
                "invitation_code": inv_code,
                "created_at": ta.created_at.isoformat() if ta.created_at else None,
                "lease_cohort_id": assignment_cohort_map.get(ta.id),
            })

    tenant_invs = (
        db.query(Invitation)
        .filter(
            Invitation.owner_id == current_user.id,
            Invitation.invitation_kind.in_(tuple(TENANT_UNIT_LEASE_KINDS)),
            Invitation.status.in_(["pending", "ongoing", "accepted"]),
            Invitation.token_state.notin_(["CANCELLED", "REVOKED", "EXPIRED"]),
        )
        .order_by(Invitation.created_at.desc())
        .all()
    )
    for inv in tenant_invs:
        if is_tenant_lease_extension_kind(getattr(inv, "invitation_kind", None)):
            continue
        if getattr(inv, "status", None) == "accepted":
            continue
        has_assignment = (
            db.query(TenantAssignment)
            .filter(TenantAssignment.unit_id == inv.unit_id)
            .first()
        ) if inv.unit_id else None
        if has_assignment and is_standard_tenant_invite_kind(getattr(inv, "invitation_kind", None)):
            continue
        unit = unit_map.get(inv.unit_id) if inv.unit_id else None
        prop = prop_map.get(inv.property_id)
        resolved = resolve_tenant_state(db, tenant_assignment=None, tenant_invitation=inv)
        out.append({
            "id": -inv.id,
            "invitation_id": inv.id,
            "tenant_name": (inv.guest_name or "").strip() or (inv.guest_email or "").strip() or "Invited tenant",
            "tenant_email": inv.guest_email,
            "property_name": (prop.name if prop else None) or "Property",
            "property_address_line": _property_address_line(prop),
            "property_id": prop.id if prop else None,
            "unit_label": unit.unit_label if unit else None,
            "unit_id": inv.unit_id,
            "start_date": str(inv.stay_start_date) if inv.stay_start_date else None,
            "end_date": str(inv.stay_end_date) if inv.stay_end_date else None,
            "active": False,
            "status": "pending",
            "invite_status": resolved.invite_status,
            "assignment_status": resolved.assignment_status,
            "stay_status": resolved.stay_status,
            "invitation_code": inv.invitation_code,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
            "lease_cohort_id": cohort_key_for_pending_invitation(inv, all_owner_tas),
        })
    count_cohort_members(out)
    return out


@router.get("/owner/invitations", response_model=list[OwnerInvitationView])
def owner_invitations(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
    context_mode: str = Depends(get_context_mode),
):
    """Owner view: invitations with property name.
    Business mode: property-issued tenant invites (standard and co-tenant / shared lease).
    Personal mode: property-lane guest invitations only (owner/manager-invited; NEVER tenant-invited guest data).
    Guest name/email are redacted when the viewer is not the relationship owner for that invitation (e.g. manager-created guest invite)."""
    owned_ids = owner_profile_property_ids(db, current_user.id)
    if context_mode == "business":
        invs = (
            db.query(Invitation)
            .filter(
                Invitation.owner_id == current_user.id,
                Invitation.invitation_kind.in_(tuple(TENANT_UNIT_LEASE_KINDS)),
            )
            .order_by(Invitation.created_at.desc())
            .all()
        )
        # Defensive guard for legacy rows: owner business-mode invitations must never include guest invites.
        invs = [i for i in invs if is_property_invited_tenant_signup_kind(getattr(i, "invitation_kind", None))]
        invs = [i for i in invs if i.property_id in owned_ids]
        return _invitations_to_owner_views(invs, db, get_invitation_expire_cutoff, viewer_user_id=current_user.id)
    all_invs = db.query(Invitation).filter(Invitation.owner_id == current_user.id).order_by(Invitation.created_at.desc()).all()
    all_invs = [i for i in all_invs if i.property_id in owned_ids]
    invs = filter_property_lane_invitations_for_owner(db, all_invs, current_user.id)
    allowed_units = owner_personal_guest_scope_unit_ids(db, current_user.id)
    invs = [inv for inv in invs if invitation_in_owner_personal_guest_scope(db, inv, allowed_units)]
    return _invitations_to_owner_views(invs, db, get_invitation_expire_cutoff, viewer_user_id=current_user.id)


def _invitations_to_owner_views(
    invs: list,
    db: Session,
    get_invitation_expire_cutoff_fn,
    *,
    viewer_user_id: int,
) -> list:
    """Build OwnerInvitationView list from invitation list. Shared by owner and manager. Redacts guest PII when viewer is not the relationship owner."""
    from app.services.state_resolver import resolve_invite_status, resolve_tenant_state
    threshold = get_invitation_expire_cutoff_fn()
    out = []
    for inv in invs:
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
        
        # Bug #5b: Do not mark as expired if there's a pending Dropbox Sign request
        has_pending_dropbox = db.query(AgreementSignature).filter(
            AgreementSignature.invitation_code == inv.invitation_code,
            AgreementSignature.dropbox_sign_request_id.isnot(None),
            AgreementSignature.signed_pdf_bytes.is_(None)
        ).first() is not None

        is_expired = (
            inv.status == "expired"
            or (
                inv.status == "pending"
                and inv.created_at is not None
                and inv.created_at < threshold
                and not has_pending_dropbox
                and not guest_invitation_signing_started(db, inv.invitation_code)
            )
        )
        is_tenant_inv = is_property_invited_tenant_signup_kind(getattr(inv, "invitation_kind", None))
        if is_tenant_inv:
            # Tenant invites: status follows lease-window rules.
            # pending  -> invite not accepted yet
            # accepted -> invite accepted but lease start is in the future
            # active   -> invite accepted and today is inside [start, end]
            # expired  -> lease window ended (or invite revoked/cancelled/expired)
            matching_assignment = None
            if inv.unit_id is not None and inv.stay_start_date is not None:
                asg_q = db.query(TenantAssignment).filter(
                    TenantAssignment.unit_id == inv.unit_id,
                    TenantAssignment.start_date == inv.stay_start_date,
                )
                if inv.stay_end_date is None:
                    asg_q = asg_q.filter(TenantAssignment.end_date.is_(None))
                else:
                    asg_q = asg_q.filter(TenantAssignment.end_date == inv.stay_end_date)
                matching_assignment = asg_q.first()
            resolved_tenant = resolve_tenant_state(
                db,
                tenant_assignment=matching_assignment,
                tenant_invitation=inv,
            )
            assignment_status = resolved_tenant.assignment_status
            display_status = assignment_status if assignment_status in ("pending", "accepted", "active", "expired") else "pending"
        else:
            has_stay = db.query(Stay).filter(Stay.invitation_id == inv.id).first() is not None
            token_state = (getattr(inv, "token_state", None) or "STAGED").upper()
            if inv.status == "cancelled":
                display_status = "cancelled"
            elif inv.status == "expired" or is_expired:
                display_status = "expired"
            elif inv.status == "ongoing" or has_stay or inv.status == "accepted" or (token_state == "BURNED" and inv.status == "pending"):
                display_status = "active"
            else:
                display_status = "pending"
        demo_flag = is_demo_user_id(db, getattr(inv, "invited_by_user_id", None) or getattr(inv, "owner_id", None))
        show_guest_pii = viewer_is_relationship_owner_for_invitation(inv, viewer_user_id)
        guest_name_out = inv.guest_name if show_guest_pii else REDACTED_GUEST_AUTHORIZATION_LABEL
        guest_email_out = inv.guest_email if show_guest_pii else None
        out.append(
            OwnerInvitationView(
                id=inv.id,
                invitation_code=inv.invitation_code,
                property_id=inv.property_id,
                property_name=property_name,
                property_deleted_at=getattr(prop, "deleted_at", None) if prop else None,
                guest_name=guest_name_out,
                guest_email=guest_email_out,
                stay_start_date=inv.stay_start_date,
                stay_end_date=inv.stay_end_date,
                region_code=inv.region_code,
                status=display_status,
                invitation_kind=(getattr(inv, "invitation_kind", None) or "guest").strip().lower(),
                token_state=getattr(inv, "token_state", None) or "STAGED",
                created_at=inv.created_at,
                is_expired=is_expired,
                is_demo=demo_flag,
            )
        )
    return out


@router.get("/manager/invitations", response_model=list[OwnerInvitationView])
def manager_invitations(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_property_manager_identity_verified),
    context_mode: str = Depends(get_context_mode),
):
    """Manager view: invitations. Business mode: returns [] (no guest data for privacy). Personal mode: only invitations the manager created (property lane); NEVER tenant-invited guest data."""
    if context_mode == "business":
        return []
    personal_unit_ids = get_manager_personal_mode_units(db, current_user.id)
    if not personal_unit_ids:
        return []
    units = db.query(Unit).filter(Unit.id.in_(personal_unit_ids)).all()
    property_ids = list({u.property_id for u in units})
    if not property_ids:
        return []
    all_invs = (
        db.query(Invitation)
        .filter(Invitation.property_id.in_(property_ids))
        .order_by(Invitation.created_at.desc())
        .all()
    )
    invs = filter_property_lane_invitations_for_manager(db, all_invs, current_user.id)
    mu = set(personal_unit_ids)
    invs = [inv for inv in invs if invitation_in_manager_personal_guest_scope(db, inv, mu)]
    return _invitations_to_owner_views(invs, db, get_invitation_expire_cutoff, viewer_user_id=current_user.id)


@router.post("/owner/invitations/{invitation_id}/cancel")
def owner_cancel_invitation(
    request: Request,
    invitation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel a pending invitation. Owner or the inviter can cancel. Owner cannot cancel tenant-invited invitations (tenant lane)."""
    inv = db.query(Invitation).filter(Invitation.id == invitation_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found")
    is_inviter = getattr(inv, "invited_by_user_id", None) == current_user.id
    is_owner = inv.owner_id == current_user.id
    is_tenant_lane = is_tenant_lane_invitation(db, inv)
    if is_tenant_lane and is_owner and not is_inviter:
        raise HTTPException(status_code=403, detail="Tenant-invited guest data is private to the tenant. Only the tenant who created the invitation can cancel it.")
    if not is_owner and not is_inviter:
        raise HTTPException(status_code=403, detail="Only the property owner or the person who created the invitation can cancel it")
    if inv.status != "pending":
        if inv.status in ("accepted", "ongoing", "active"):
            raise HTTPException(
                status_code=400,
                detail="This invitation was already accepted. Use “Revoke stay” on the guest’s authorization row instead of cancelling the invitation.",
            )
        raise HTTPException(status_code=400, detail="Only pending invitations can be cancelled.")
    inv.status = "cancelled"
    prev_token = getattr(inv, "token_state", None) or "STAGED"
    inv.token_state = "REVOKED"
    db.commit()
    prop = db.query(Property).filter(Property.id == inv.property_id).first()
    property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Invitation cancelled",
        f"Invite ID {inv.invitation_code} token_state {prev_token} -> REVOKED (owner cancelled). Property {property_name}, guest {inv.guest_name or inv.guest_email or '—'}.",
        property_id=inv.property_id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"invitation_code": inv.invitation_code, "token_state_previous": prev_token, "token_state_new": "REVOKED"},
    )
    create_ledger_event(
        db,
        ACTION_GUEST_INVITE_CANCELLED,
        target_object_type="Invitation",
        target_object_id=inv.id,
        property_id=inv.property_id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        meta={"invitation_code": inv.invitation_code, "token_state_previous": prev_token, "token_state_new": "REVOKED"},
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()
    return {"status": "success", "message": "Invitation cancelled."}


@router.post("/owner/properties/{property_id}/confirm-vacant")
def owner_confirm_vacant(
    request: Request,
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
):
    """Confirm that a vacant unit is still vacant (vacant-unit monitoring response). Owner or assigned manager can confirm."""
    if not can_access_property(db, current_user, property_id, "business"):
        raise HTTPException(status_code=403, detail="You do not have access to this property")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.deleted_at.is_(None),
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if (getattr(prop, "occupancy_status", None) or "").lower() != OccupancyStatus.vacant.value:
        raise HTTPException(status_code=400, detail="Property is not vacant. Confirm vacancy only for vacant units.")
    now = datetime.now(timezone.utc)
    prop.vacant_monitoring_confirmed_at = now
    prop.vacant_monitoring_response_due_at = None
    db.add(prop)
    property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else f"Property {property_id}")
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Owner confirmed still vacant",
        f"Owner confirmed unit still vacant for {property_name} (vacant monitoring).",
        property_id=prop.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "").strip() or None,
    )
    create_ledger_event(
        db,
        ACTION_CONFIRMED_STILL_VACANT,
        target_object_type="Property",
        target_object_id=prop.id,
        property_id=prop.id,
        actor_user_id=current_user.id,
        meta={"property_name": property_name},
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "").strip() or None,
    )
    db.commit()
    return {"status": "success", "message": "Vacancy confirmed. Next prompt will be sent at the next interval."}


@router.post("/properties/bulk-shield-mode")
def bulk_shield_mode(
    request: Request,
    data: BulkShieldModeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
):
    """Bulk update Shield Mode for multiple properties. Owner or assigned manager can update. Each property is verified via can_access_property."""
    if SHIELD_MODE_ALWAYS_ON and not data.shield_mode_enabled:
        raise HTTPException(
            status_code=400,
            detail="Shield Mode is always on for all properties and cannot be turned off.",
        )
    if not data.property_ids:
        return {"status": "success", "updated_count": 0, "message": "No properties selected."}
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    turned_by = "property manager" if current_user.role == UserRole.property_manager else "property owner"
    updated_count = 0
    owner_profiles_to_sync = set()
    for property_id in data.property_ids:
        if not can_access_property(db, current_user, property_id, "business"):
            continue
        prop = db.query(Property).filter(Property.id == property_id, Property.deleted_at.is_(None)).first()
        if not prop:
            continue
        new_val = 1 if data.shield_mode_enabled else 0
        old_val = getattr(prop, "shield_mode_enabled", 0) or 0
        if new_val == old_val:
            continue
        prop.shield_mode_enabled = new_val
        property_address = _format_property_address_for_log(prop)
        create_log(
            db,
            CATEGORY_SHIELD_MODE,
            "Shield Mode turned off" if new_val == 0 else "Shield Mode turned on",
            f"{turned_by.title()} turned {'off' if new_val == 0 else 'on'} Shield Mode for {property_address} (bulk).",
            property_id=prop.id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=ip,
            user_agent=ua,
            meta={"property_id": property_id, "property_name": property_address},
        )
        shield_label = "turned off" if new_val == 0 else "turned on"
        create_ledger_event(
            db,
            ACTION_SHIELD_MODE_OFF if new_val == 0 else ACTION_SHIELD_MODE_ON,
            target_object_type="Property",
            target_object_id=prop.id,
            property_id=prop.id,
            actor_user_id=current_user.id,
            meta={
                "property_id": property_id,
                "property_name": property_address,
                "message": f"Shield Mode {shield_label} for {property_address}.",
            },
            ip_address=ip,
            user_agent=ua,
        )
        if getattr(prop, "owner_profile_id", None):
            owner_profiles_to_sync.add(prop.owner_profile_id)
        owner_user = None
        if getattr(prop, "owner_profile_id", None):
            prof = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            owner_user = db.query(User).filter(User.id == prof.user_id).first() if prof else None
        owner_email = (owner_user.email or "").strip() if owner_user else ""
        manager_emails = [
            (u.email or "").strip()
            for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == prop.id).all()
            for u in [db.query(User).filter(User.id == a.user_id).first()]
            if u and (u.email or "").strip()
        ]
        try:
            if new_val == 1:
                send_shield_mode_turned_on_notification(owner_email, manager_emails, property_address, turned_on_by=turned_by)
            else:
                send_shield_mode_turned_off_notification(owner_email, manager_emails, property_address, turned_off_by=turned_by)
        except Exception as e:
            print(f"[Dashboard] Shield mode notification failed for property {property_id}: {e}", flush=True)
        updated_count += 1
    db.commit()
    for profile_id in owner_profiles_to_sync:
        profile = db.query(OwnerProfile).filter(OwnerProfile.id == profile_id).first()
        if profile:
            try:
                sync_subscription_quantities(db, profile)
            except Exception as e:
                print(f"[Dashboard] Subscription sync failed after bulk Shield: {e}", flush=True)
    return {"status": "success", "updated_count": updated_count, "message": f"Shield Mode turned {'on' if data.shield_mode_enabled else 'off'} for {updated_count} propert{'y' if updated_count == 1 else 'ies'}."}


@router.get("/owner/stays", response_model=list[OwnerStayView])
def owner_stays(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
    context_mode: str = Depends(get_context_mode),
):
    """Owner view: guest stays. Business mode: returns [] (no guest data). Personal mode: property-lane stays only (owner/manager-invited; NEVER tenant-invited guest stays). Guest PII and invite codes are shown only when the owner is the relationship owner for that stay/invitation (typically the inviter)."""
    if context_mode == "business":
        return []
    owned_prop_ids = owner_profile_property_ids(db, current_user.id)
    # Load stays on owned properties (OwnerProfile), not Stay.owner_id — that column can lag after ownership transfer.
    stays_by_owner = db.query(Stay).filter(Stay.property_id.in_(owned_prop_ids)).all() if owned_prop_ids else []
    inv_ids = [r[0] for r in db.query(Invitation.id).filter(Invitation.owner_id == current_user.id).all()]
    stays_by_inv = db.query(Stay).filter(Stay.invitation_id.in_(inv_ids)).all() if inv_ids else []
    seen_ids = {s.id for s in stays_by_owner}
    stays = list(stays_by_owner)
    for s in stays_by_inv:
        if s.id not in seen_ids:
            seen_ids.add(s.id)
            stays.append(s)
    stays = [s for s in stays if s.property_id in owned_prop_ids]
    stays = filter_property_lane_stays_for_owner(db, stays, current_user.id)
    allowed_units = owner_personal_guest_scope_unit_ids(db, current_user.id)
    stays = [s for s in stays if stay_in_owner_personal_guest_scope(db, s, allowed_units)]
    out = []
    for s in stays:
        show_guest_pii = viewer_is_relationship_owner_for_stay(db, s, current_user.id)
        guest_name = label_for_stay(db, s) if show_guest_pii else REDACTED_GUEST_AUTHORIZATION_LABEL

        prop = db.query(Property).filter(Property.id == s.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"

        rule = db.query(RegionRule).filter(RegionRule.region_code == s.region_code).first()
        jle = resolve_jurisdiction(
            db,
            JLEInput(
                region_code=s.region_code,
                stay_duration_days=s.intended_stay_duration_days,
                owner_occupied=True,  # would come from property
                property_type=None,
                guest_has_permanent_address=True,
            ),
        )
        max_days = rule.max_stay_days if rule else 0
        classification = (jle.legal_classification if jle else None) or (rule.stay_classification_label if rule else None) or StayClassification.guest
        risk = (jle.risk_level if jle else None) or (rule.risk_level if rule else None) or RiskLevel.low
        statutes = (jle.applicable_statutes if jle else []) or ([rule.statute_reference] if rule and rule.statute_reference else [])

        # Status confirmation: prod = deadline stay_end + 48h; test mode = effective simulated end + 5 min (see stay_timer)
        checked_out = getattr(s, "checked_out_at", None) is not None
        cancelled = getattr(s, "cancelled_at", None) is not None
        conf_resp = getattr(s, "occupancy_confirmation_response", None)
        dms_on = bool(getattr(s, "dead_mans_switch_enabled", 0))
        now = datetime.now(timezone.utc)
        _dms_test = bool(getattr(get_settings(), "dms_test_mode", False))
        eff_test = (
            dms_test_mode_effective_end_utc(s)
            if _dms_test and _status_confirmation_eligible_stay(db, s)
            else None
        )
        if eff_test is not None:
            confirmation_deadline_at = dms_test_mode_unknown_deadline_utc(db, s)
            needs_conf = (
                not checked_out
                and not cancelled
                and dms_on
                and conf_resp is None
                and confirmation_deadline_at is not None
                and now < confirmation_deadline_at
            )
        else:
            confirmation_deadline_at = datetime.combine(
                s.stay_end_date + timedelta(days=2), dt_time.min, tzinfo=timezone.utc
            ) if s.stay_end_date else None
            needs_conf = (
                not checked_out and not cancelled
                and dms_on
                and conf_resp is None
                and confirmation_deadline_at is not None
                and now < confirmation_deadline_at
                and s.stay_end_date <= (date.today() + timedelta(days=2))  # in prompt window (48h before or after)
            )
        prop_status = (
            normalize_occupancy_status_for_display(
                db,
                prop.id,
                getattr(s, "unit_id", None),
                getattr(prop, "occupancy_status", None) or OccupancyStatus.vacant.value,
            )
            if prop
            else OccupancyStatus.vacant.value
        )
        show_confirm_ui = needs_conf or (
            prop_status in (OccupancyStatus.unconfirmed.value, OccupancyStatus.unknown.value)
            and not checked_out
            and not cancelled
            and dms_on
            and conf_resp is None
            and (
                (eff_test is not None and now >= eff_test)
                or (eff_test is None and s.stay_end_date < date.today())
            )
        )

        invite_id_val = None
        token_state_val = None
        if getattr(s, "invitation_id", None):
            inv = db.query(Invitation).filter(Invitation.id == s.invitation_id).first()
            if inv:
                invite_id_val = inv.invitation_code if show_guest_pii else None
                token_state_val = getattr(inv, "token_state", None) or "BURNED"
        out.append(
            OwnerStayView(
                stay_id=s.id,
                property_id=s.property_id,
                invite_id=invite_id_val,
                token_state=token_state_val,
                invitation_only=False,
                guest_name=guest_name,
                property_name=property_name,
                stay_start_date=s.stay_start_date,
                stay_end_date=s.stay_end_date,
                region_code=s.region_code,
                legal_classification=classification,
                max_stay_allowed_days=max_days,
                risk_indicator=risk,
                applicable_laws=statutes,
                revoked_at=getattr(s, "revoked_at", None),
                checked_in_at=getattr(s, "checked_in_at", None),
                checked_out_at=getattr(s, "checked_out_at", None),
                cancelled_at=getattr(s, "cancelled_at", None),
                usat_token_released_at=getattr(s, "usat_token_released_at", None),
                dead_mans_switch_enabled=dms_on,
                needs_occupancy_confirmation=needs_conf,
                show_occupancy_confirmation_ui=show_confirm_ui,
                confirmation_deadline_at=confirmation_deadline_at if show_confirm_ui else None,
                occupancy_confirmation_response=conf_resp,
                property_deleted_at=getattr(prop, "deleted_at", None) if prop else None,
            )
        )

    # Include BURNED and EXPIRED invitations that have no Stay so they show in Stays section (CSV tenants, or invites where Stay was never created).
    # Exclude: (1) invitation_id already linked to a Stay, (2) status='accepted', (3) any Stay exists for same property + dates (covers old Stays created without invitation_id).
    invitation_ids_with_stay = {s.invitation_id for s in stays if getattr(s, "invitation_id", None) is not None}
    stay_key = {(s.property_id, s.stay_start_date, s.stay_end_date) for s in stays}
    q = db.query(Invitation).filter(
        Invitation.owner_id == current_user.id,
        Invitation.token_state.in_(["BURNED", "EXPIRED"]),
        Invitation.status != "accepted",
    )
    if invitation_ids_with_stay:
        q = q.filter(~Invitation.id.in_(invitation_ids_with_stay))
    invs_no_stay = filter_property_lane_invitations_for_owner(db, q.all(), current_user.id)
    invs_no_stay = [inv for inv in invs_no_stay if invitation_in_owner_personal_guest_scope(db, inv, allowed_units)]
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    for inv in invs_no_stay:
        if (inv.property_id, inv.stay_start_date, inv.stay_end_date) in stay_key:
            continue
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        if prop is None:
            continue
        if profile is None or prop.owner_profile_id != profile.id:
            continue  # ensure property belongs to this owner
        property_name = (prop.name or "").strip() or (f"{getattr(prop, 'city', '')}, {getattr(prop, 'state', '')}".strip(", ")) or "Property"
        region = (getattr(inv, "region_code", None) or "").strip() or (getattr(prop, "region_code", None) or "") or "US"
        start = inv.stay_start_date
        end = inv.stay_end_date
        duration_days = (end - start).days if start and end else 0
        rule = db.query(RegionRule).filter(RegionRule.region_code == region).first()
        jle = resolve_jurisdiction(
            db,
            JLEInput(
                region_code=region,
                stay_duration_days=duration_days,
                owner_occupied=True,
                property_type=None,
                guest_has_permanent_address=True,
            ),
        )
        max_days = rule.max_stay_days if rule else 0
        classification = (jle.legal_classification if jle else None) or (rule.stay_classification_label if rule else None) or StayClassification.guest
        risk = (jle.risk_level if jle else None) or (rule.risk_level if rule else None) or RiskLevel.low
        statutes = (jle.applicable_statutes if jle else []) or ([rule.statute_reference] if rule and rule.statute_reference else [])
        token_state = (getattr(inv, "token_state", None) or "BURNED").upper()
        is_expired = token_state == "EXPIRED"
        # For EXPIRED (no Stay row), show as completed so past stays appear
        checked_out_dt = datetime.combine(end, dt_time.min, tzinfo=timezone.utc) if is_expired and end else None
        show_guest_pii = viewer_is_relationship_owner_for_invitation(inv, current_user.id)
        inv_guest_name = label_from_invitation(db, inv) if show_guest_pii else REDACTED_GUEST_AUTHORIZATION_LABEL
        out.append(
            OwnerStayView(
                stay_id=-inv.id,
                property_id=inv.property_id,
                invite_id=inv.invitation_code if show_guest_pii else None,
                token_state=token_state,
                invitation_only=True,
                guest_name=inv_guest_name,
                property_name=property_name,
                stay_start_date=start,
                stay_end_date=end,
                region_code=region,
                legal_classification=classification,
                max_stay_allowed_days=max_days,
                risk_indicator=risk,
                applicable_laws=statutes,
                revoked_at=None,
                checked_in_at=None,
                checked_out_at=checked_out_dt,
                cancelled_at=None,
                usat_token_released_at=None,
                dead_mans_switch_enabled=bool(getattr(inv, "dead_mans_switch_enabled", 0)),
                needs_occupancy_confirmation=False,
                show_occupancy_confirmation_ui=False,
                confirmation_deadline_at=None,
                occupancy_confirmation_response=None,
                property_deleted_at=getattr(prop, "deleted_at", None),
            )
        )

    return out


def _manager_property_ids(db: Session, user_id: int) -> list[int]:
    """Property IDs assigned to this manager."""
    rows = db.query(PropertyManagerAssignment.property_id).filter(
        PropertyManagerAssignment.user_id == user_id,
    ).distinct().all()
    return [r[0] for r in rows]


@router.get("/manager/stays", response_model=list[OwnerStayView])
def manager_stays(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_property_manager_identity_verified),
    context_mode: str = Depends(get_context_mode),
):
    """Manager view: stays. Business mode: returns [] (no guest data for privacy). Personal mode: only stays for guests the manager invited (property lane); NEVER tenant-invited guest stays. Guest PII is redacted when the viewer is not the relationship owner (defense in depth; list is normally manager-invited only)."""
    if context_mode == "business":
        return []
    personal_unit_ids = get_manager_personal_mode_units(db, current_user.id)
    if not personal_unit_ids:
        return []
    mu = set(personal_unit_ids)
    units = db.query(Unit).filter(Unit.id.in_(personal_unit_ids)).all()
    property_ids = list({u.property_id for u in units})
    if not property_ids:
        return []
    stays = db.query(Stay).filter(Stay.property_id.in_(property_ids)).all()
    inv_ids = [r[0] for r in db.query(Invitation.id).filter(
        Invitation.property_id.in_(property_ids),
    ).all()]
    stays_by_inv = db.query(Stay).filter(Stay.invitation_id.in_(inv_ids)).all() if inv_ids else []
    seen_ids = {s.id for s in stays}
    for s in stays_by_inv:
        if s.id not in seen_ids:
            seen_ids.add(s.id)
            stays.append(s)
    stays = filter_property_lane_stays_for_manager(db, stays, current_user.id)
    stays = [s for s in stays if stay_in_manager_personal_guest_scope(db, s, mu)]
    out = []
    for s in stays:
        show_guest_pii = viewer_is_relationship_owner_for_stay(db, s, current_user.id)
        guest_name = label_for_stay(db, s) if show_guest_pii else REDACTED_GUEST_AUTHORIZATION_LABEL
        prop = db.query(Property).filter(Property.id == s.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
        rule = db.query(RegionRule).filter(RegionRule.region_code == s.region_code).first()
        jle = resolve_jurisdiction(db, JLEInput(region_code=s.region_code, stay_duration_days=s.intended_stay_duration_days, owner_occupied=True, property_type=None, guest_has_permanent_address=True))
        max_days = rule.max_stay_days if rule else 0
        classification = (jle.legal_classification if jle else None) or (rule.stay_classification_label if rule else None) or StayClassification.guest
        risk = (jle.risk_level if jle else None) or (rule.risk_level if rule else None) or RiskLevel.low
        statutes = (jle.applicable_statutes if jle else []) or ([rule.statute_reference] if rule and rule.statute_reference else [])
        checked_out = getattr(s, "checked_out_at", None) is not None
        cancelled = getattr(s, "cancelled_at", None) is not None
        conf_resp = getattr(s, "occupancy_confirmation_response", None)
        dms_on = bool(getattr(s, "dead_mans_switch_enabled", 0))
        now = datetime.now(timezone.utc)
        _dms_test = bool(getattr(get_settings(), "dms_test_mode", False))
        eff_test = (
            dms_test_mode_effective_end_utc(s)
            if _dms_test and _status_confirmation_eligible_stay(db, s)
            else None
        )
        if eff_test is not None:
            confirmation_deadline_at = dms_test_mode_unknown_deadline_utc(db, s)
            needs_conf = (
                not checked_out
                and not cancelled
                and dms_on
                and conf_resp is None
                and confirmation_deadline_at is not None
                and now < confirmation_deadline_at
            )
        else:
            confirmation_deadline_at = (
                datetime.combine(s.stay_end_date + timedelta(days=2), dt_time.min, tzinfo=timezone.utc)
                if s.stay_end_date
                else None
            )
            needs_conf = (
                not checked_out
                and not cancelled
                and dms_on
                and conf_resp is None
                and confirmation_deadline_at is not None
                and now < confirmation_deadline_at
                and s.stay_end_date <= (date.today() + timedelta(days=2))
            )
        prop_status = (
            normalize_occupancy_status_for_display(
                db,
                prop.id,
                getattr(s, "unit_id", None),
                getattr(prop, "occupancy_status", None) or OccupancyStatus.vacant.value,
            )
            if prop
            else OccupancyStatus.vacant.value
        )
        show_confirm_ui = needs_conf or (
            prop_status in (OccupancyStatus.unconfirmed.value, OccupancyStatus.unknown.value)
            and not checked_out
            and not cancelled
            and dms_on
            and conf_resp is None
            and (
                (eff_test is not None and now >= eff_test)
                or (eff_test is None and s.stay_end_date < date.today())
            )
        )
        invite_id_val = None
        token_state_val = None
        if getattr(s, "invitation_id", None):
            inv = db.query(Invitation).filter(Invitation.id == s.invitation_id).first()
            if inv:
                invite_id_val = inv.invitation_code if show_guest_pii else None
                token_state_val = getattr(inv, "token_state", None) or "BURNED"
        out.append(OwnerStayView(
            stay_id=s.id, property_id=s.property_id, invite_id=invite_id_val, token_state=token_state_val, invitation_only=False,
            guest_name=guest_name, property_name=property_name, stay_start_date=s.stay_start_date, stay_end_date=s.stay_end_date,
            region_code=s.region_code, legal_classification=classification, max_stay_allowed_days=max_days, risk_indicator=risk, applicable_laws=statutes,
            revoked_at=getattr(s, "revoked_at", None), checked_in_at=getattr(s, "checked_in_at", None), checked_out_at=getattr(s, "checked_out_at", None), cancelled_at=getattr(s, "cancelled_at", None),
            usat_token_released_at=getattr(s, "usat_token_released_at", None), dead_mans_switch_enabled=dms_on,
            needs_occupancy_confirmation=needs_conf, show_occupancy_confirmation_ui=show_confirm_ui, confirmation_deadline_at=confirmation_deadline_at if show_confirm_ui else None, occupancy_confirmation_response=conf_resp,
            property_deleted_at=getattr(prop, "deleted_at", None) if prop else None,
        ))
    invitation_ids_with_stay = {s.invitation_id for s in stays if getattr(s, "invitation_id", None) is not None}
    stay_key = {(s.property_id, s.stay_start_date, s.stay_end_date) for s in stays}
    q = db.query(Invitation).filter(
        Invitation.property_id.in_(property_ids),
        Invitation.token_state.in_(["BURNED", "EXPIRED"]),
        Invitation.status != "accepted",
    )
    if invitation_ids_with_stay:
        q = q.filter(~Invitation.id.in_(invitation_ids_with_stay))
    invs_for_invitation_only = filter_property_lane_invitations_for_manager(db, q.all(), current_user.id)
    invs_for_invitation_only = [inv for inv in invs_for_invitation_only if invitation_in_manager_personal_guest_scope(db, inv, mu)]
    for inv in invs_for_invitation_only:
        if (inv.property_id, inv.stay_start_date, inv.stay_end_date) in stay_key:
            continue
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        if not prop:
            continue
        property_name = (prop.name or "").strip() or (f"{getattr(prop, 'city', '')}, {getattr(prop, 'state', '')}".strip(", ")) or "Property"
        region = (getattr(inv, "region_code", None) or "").strip() or (getattr(prop, "region_code", None) or "") or "US"
        start, end = inv.stay_start_date, inv.stay_end_date
        duration_days = (end - start).days if start and end else 0
        rule = db.query(RegionRule).filter(RegionRule.region_code == region).first()
        jle = resolve_jurisdiction(db, JLEInput(region_code=region, stay_duration_days=duration_days, owner_occupied=True, property_type=None, guest_has_permanent_address=True))
        max_days = rule.max_stay_days if rule else 0
        classification = (jle.legal_classification if jle else None) or (rule.stay_classification_label if rule else None) or StayClassification.guest
        risk = (jle.risk_level if jle else None) or (rule.risk_level if rule else None) or RiskLevel.low
        statutes = (jle.applicable_statutes if jle else []) or ([rule.statute_reference] if rule and rule.statute_reference else [])
        token_state = (getattr(inv, "token_state", None) or "BURNED").upper()
        is_expired = token_state == "EXPIRED"
        checked_out_dt = datetime.combine(end, dt_time.min, tzinfo=timezone.utc) if is_expired and end else None
        show_guest_pii = viewer_is_relationship_owner_for_invitation(inv, current_user.id)
        inv_guest_name = label_from_invitation(db, inv) if show_guest_pii else REDACTED_GUEST_AUTHORIZATION_LABEL
        out.append(OwnerStayView(
            stay_id=-inv.id, property_id=inv.property_id, invite_id=inv.invitation_code if show_guest_pii else None, token_state=token_state, invitation_only=True,
            guest_name=inv_guest_name, property_name=property_name, stay_start_date=start, stay_end_date=end,
            region_code=region, legal_classification=classification, max_stay_allowed_days=max_days, risk_indicator=risk, applicable_laws=statutes,
            revoked_at=None, checked_in_at=None, checked_out_at=checked_out_dt, cancelled_at=None, usat_token_released_at=None,
            dead_mans_switch_enabled=bool(getattr(inv, "dead_mans_switch_enabled", 0)), needs_occupancy_confirmation=False, show_occupancy_confirmation_ui=False, confirmation_deadline_at=None, occupancy_confirmation_response=None,
            property_deleted_at=getattr(prop, "deleted_at", None),
        ))
    return out


def _tenant_assert_can_revoke_guest_stay(db: Session, tenant_user: User, stay: Stay) -> None:
    """Tenant may revoke only tenant-lane stays they created, while assigned to the stay's unit."""
    if not is_tenant_lane_stay(db, stay):
        raise HTTPException(status_code=403, detail="You can only revoke stays for guests you invited.")
    inv_id = getattr(stay, "invitation_id", None)
    if not inv_id:
        raise HTTPException(status_code=400, detail="Stay is not linked to an invitation.")
    inv = db.query(Invitation).filter(Invitation.id == inv_id).first()
    if not inv or inv.invited_by_user_id != tenant_user.id:
        raise HTTPException(status_code=403, detail="You can only revoke stays for guests you invited.")
    today = date.today()
    q = db.query(TenantAssignment).filter(
        TenantAssignment.user_id == tenant_user.id,
        (TenantAssignment.end_date.is_(None)) | (TenantAssignment.end_date >= today),
    )
    if stay.unit_id:
        q = q.filter(TenantAssignment.unit_id == stay.unit_id)
    else:
        uids = [r[0] for r in db.query(Unit.id).filter(Unit.property_id == stay.property_id).all()]
        if not uids:
            raise HTTPException(status_code=403, detail="You do not have access to revoke this stay.")
        q = q.filter(TenantAssignment.unit_id.in_(uids))
    if not q.first():
        raise HTTPException(status_code=403, detail="You do not have access to revoke this stay.")


def _perform_stay_revoke(
    db: Session,
    request: Request,
    stay: Stay,
    actor_user: User,
    *,
    guest_revoker: str,
    notify_owner_and_managers: bool,
    actor_label: str,
) -> dict:
    """
    Kill switch: revoked_at + invitation REVOKED, 12h vacate, email, ledger, dashboard alerts.
    guest_revoker: 'owner' | 'host' (wording for guest email/in-app).
    actor_label: short description for audit log (e.g. 'owner', 'tenant').
    """
    if stay.revoked_at:
        return {"status": "success", "message": "Stay was already revoked."}
    now = datetime.now(timezone.utc)
    stay.revoked_at = now
    vacate_by = now + timedelta(hours=12)
    vacate_by_iso = vacate_by.strftime("%Y-%m-%d %H:%M UTC")
    invite_code = None
    prev_token = None
    if getattr(stay, "invitation_id", None):
        inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
        if inv:
            prev_token = getattr(inv, "token_state", None) or "BURNED"
            inv.token_state = "REVOKED"
            invite_code = inv.invitation_code
            db.add(inv)
    db.commit()
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    log_meta = {"vacate_by": vacate_by_iso, "revoked_by": guest_revoker}
    if invite_code and prev_token is not None:
        log_meta["invitation_code"] = invite_code
        log_meta["token_state_previous"] = prev_token
        log_meta["token_state_new"] = "REVOKED"
    revoke_message = (
        f"Stay {stay.id} revoked by {actor_label}. Guest must vacate by {vacate_by_iso}."
        + (f" Invite ID {invite_code} token_state → REVOKED." if invite_code else "")
    )
    log_meta["message"] = revoke_message
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Stay revoked",
        revoke_message,
        property_id=stay.property_id,
        stay_id=stay.id,
        invitation_id=getattr(stay, "invitation_id", None),
        actor_user_id=actor_user.id,
        actor_email=actor_user.email,
        ip_address=ip,
        user_agent=ua,
        meta=log_meta,
    )
    create_ledger_event(
        db,
        ACTION_STAY_REVOKED,
        target_object_type="Stay",
        target_object_id=stay.id,
        property_id=stay.property_id,
        stay_id=stay.id,
        invitation_id=getattr(stay, "invitation_id", None),
        actor_user_id=actor_user.id,
        meta=log_meta,
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()
    guest = db.query(User).filter(User.id == stay.guest_id).first()
    guest_email = (guest.email if guest else "").strip()
    guest_name = label_for_stay(db, stay)
    prop = db.query(Property).filter(Property.id == stay.property_id).first()
    property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "the property"
    prop_parts = [prop.street, prop.city, prop.state, (prop.zip_code or "").strip()] if prop else []
    property_address = ", ".join(p for p in prop_parts if p) if prop else ""
    if guest_email:
        send_vacate_12h_notice(
            guest_email,
            guest_name,
            property_name,
            vacate_by_iso,
            stay.region_code or "",
            property_address=property_address,
            stay_start_date=stay.stay_start_date.isoformat() if stay.stay_start_date else "",
            stay_end_date=stay.stay_end_date.isoformat() if stay.stay_end_date else "",
            revoked_at=now.strftime("%Y-%m-%d %H:%M UTC"),
            invite_code=invite_code or "",
            revoker=guest_revoker,
        )
    guest_alert_body = (
        f"Your stay at {property_name} has been revoked by your host. You must vacate by {vacate_by_iso}. Your utility access (USAT token) has been revoked."
        if guest_revoker == "host"
        else f"Your stay at {property_name} has been revoked by the property owner. You must vacate by {vacate_by_iso}. Your utility access (USAT token) has been revoked."
    )
    create_alert_for_user(
        db,
        stay.guest_id,
        "revoked",
        "Stay authorization revoked",
        guest_alert_body,
        severity="urgent",
        property_id=stay.property_id,
        stay_id=stay.id,
        meta={
            "vacate_by": vacate_by_iso,
            "revoked_at": now.strftime("%Y-%m-%d %H:%M UTC"),
            "revoked_by": guest_revoker,
        },
    )
    if notify_owner_and_managers:
        create_alert_for_owner_and_managers(
            db,
            stay.property_id,
            "revoked",
            "Stay revoked",
            f"You revoked stay authorization for {guest_name} at {property_name}. Guest must vacate by {vacate_by_iso}.",
            severity="info",
            stay_id=stay.id,
            meta={"vacate_by": vacate_by_iso, "guest_name": guest_name},
        )
    else:
        create_alert_for_user(
            db,
            actor_user.id,
            "revoked",
            "Guest stay revoked",
            f"You revoked stay authorization for {guest_name} at {property_name}. Guest must vacate by {vacate_by_iso}.",
            severity="info",
            property_id=stay.property_id,
            stay_id=stay.id,
            meta={
                "vacate_by": vacate_by_iso,
                "guest_name": guest_name,
                "revoked_by_tenant": True,
            },
        )
    db.commit()
    return {"status": "success", "message": "Stay revoked. Guest must vacate within 12 hours. Email sent."}


@router.post("/owner/stays/{stay_id}/revoke")
def revoke_stay(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Revoke a stay (Kill Switch): set revoked_at, guest must vacate in 12 hours. Owner cannot revoke tenant-invited guest stays (tenant lane)."""
    stay = db.query(Stay).filter(Stay.id == stay_id).first()
    if not stay or not user_owns_property_by_profile(db, current_user.id, stay.property_id):
        raise HTTPException(status_code=404, detail="Stay not found")
    if is_tenant_lane_stay(db, stay):
        raise HTTPException(status_code=403, detail="Tenant-invited guest stays are private to the tenant. Only the tenant who invited can revoke.")
    return _perform_stay_revoke(
        db,
        request,
        stay,
        current_user,
        guest_revoker="owner",
        notify_owner_and_managers=True,
        actor_label="owner",
    )


@router.post("/tenant/stays/{stay_id}/revoke")
def tenant_revoke_guest_stay(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """Revoke a guest stay the tenant invited (same kill switch as owner). Tenant-lane only; does not notify owner/managers (privacy)."""
    stay = db.query(Stay).filter(Stay.id == stay_id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    _tenant_assert_can_revoke_guest_stay(db, current_user, stay)
    return _perform_stay_revoke(
        db,
        request,
        stay,
        current_user,
        guest_revoker="host",
        notify_owner_and_managers=False,
        actor_label="tenant",
    )


@router.post("/owner/stays/{stay_id}/initiate-removal")
def initiate_removal(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Initiate formal removal for an overstayed guest. Owner cannot initiate removal for tenant-invited guest stays (tenant lane)."""
    stay = db.query(Stay).filter(Stay.id == stay_id).first()
    if not stay or not user_owns_property_by_profile(db, current_user.id, stay.property_id):
        raise HTTPException(status_code=404, detail="Stay not found")
    if is_tenant_lane_stay(db, stay):
        raise HTTPException(status_code=403, detail="Tenant-invited guest stays are private to the tenant. Only the tenant who invited can initiate removal.")

    # Only allow initiate-removal for overstayed guests
    today = date.today()
    if stay.stay_end_date >= today:
        raise HTTPException(status_code=400, detail="Guest is not in overstay. Initiate removal is only for overstayed guests.")
    if getattr(stay, "checked_out_at", None):
        raise HTTPException(status_code=400, detail="Guest has already checked out.")

    prop = db.query(Property).filter(Property.id == stay.property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    now = datetime.now(timezone.utc)
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None

    # Revoke USAT token for this stay
    usat_revoked = False
    if stay.usat_token_released_at is not None:
        stay.usat_token_released_at = None
        usat_revoked = True

    # Also revoke the property-level USAT token if it was released
    if prop.usat_token_state == USAT_TOKEN_RELEASED:
        prop.usat_token_state = USAT_TOKEN_STAGED
        prop.usat_token_released_at = None
        usat_revoked = True

    # Mark stay as revoked if not already
    already_revoked = stay.revoked_at is not None
    if not already_revoked:
        stay.revoked_at = now

    # Update occupancy status to reflect overstay/removal
    occ_prev = getattr(prop, "occupancy_status", None) or OccupancyStatus.vacant.value

    db.add(stay)
    db.add(prop)
    db.commit()

    # Get guest and owner info for emails
    guest = db.query(User).filter(User.id == stay.guest_id).first()
    guest_email = (guest.email if guest else "").strip()
    guest_name = label_for_stay(db, stay)
    property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "the property"
    owner_email = current_user.email
    prop_parts = [prop.street, prop.city, prop.state, (prop.zip_code or "").strip()] if prop else []
    property_address = ", ".join(p for p in prop_parts if p) if prop else ""
    invite_code = ""
    if getattr(stay, "invitation_id", None):
        inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
        if inv:
            invite_code = inv.invitation_code or ""

    # Send emails
    if guest_email:
        send_removal_notice_to_guest(
            guest_email,
            guest_name,
            property_name,
            stay.region_code or "",
            property_address=property_address,
            stay_start_date=stay.stay_start_date.isoformat() if stay.stay_start_date else "",
            stay_end_date=stay.stay_end_date.isoformat() if stay.stay_end_date else "",
            revoked_at=now.strftime("%Y-%m-%d %H:%M UTC"),
            invite_code=invite_code,
        )
    if owner_email:
        send_removal_confirmation_to_owner(
            owner_email,
            guest_name,
            property_name,
            stay.region_code or "",
            property_address=property_address,
            stay_start_date=stay.stay_start_date.isoformat() if stay.stay_start_date else "",
            stay_end_date=stay.stay_end_date.isoformat() if stay.stay_end_date else "",
            revoked_at=now.strftime("%Y-%m-%d %H:%M UTC"),
            invite_code=invite_code,
        )

    # Create audit log and event ledger (guest authorization change – visible in activity logs)
    removal_message = (
        f"Owner initiated formal removal for stay {stay.id} (guest: {guest_name}, property: {property_name}). "
        "USAT token revoked. Guest and owner notified."
    )
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Removal initiated",
        removal_message,
        property_id=stay.property_id,
        stay_id=stay.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={
            "guest_name": guest_name,
            "guest_email": guest_email,
            "property_name": property_name,
            "usat_revoked": usat_revoked,
            "was_already_revoked": already_revoked,
            "occupancy_status_previous": occ_prev,
        },
    )
    create_ledger_event(
        db,
        ACTION_STAY_REVOKED,
        target_object_type="Stay",
        target_object_id=stay.id,
        property_id=stay.property_id,
        stay_id=stay.id,
        actor_user_id=current_user.id,
        meta={
            "message": removal_message,
            "guest_name": guest_name,
            "property_name": property_name,
            "usat_revoked": usat_revoked,
        },
        ip_address=ip,
        user_agent=ua,
    )
    create_alert_for_user(
        db, stay.guest_id, "removal_initiated",
        "Formal removal initiated",
        f"The property owner has initiated formal removal for your stay at {property_name}. Your utility access (USAT token) has been revoked. Please vacate as required.",
        severity="urgent", property_id=stay.property_id, stay_id=stay.id,
        meta={"revoked_at": now.strftime("%Y-%m-%d %H:%M UTC")},
    )
    create_alert_for_owner_and_managers(
        db, stay.property_id, "removal_initiated",
        "Removal initiated",
        f"You initiated formal removal for {guest_name} at {property_name}. USAT token revoked. Guest and owner notified.",
        severity="info", stay_id=stay.id, meta={"guest_name": guest_name},
    )
    db.commit()

    return {
        "status": "success",
        "message": "Removal initiated. USAT token revoked. Guest and owner notified via email.",
        "usat_revoked": usat_revoked,
    }


@router.post("/owner/stays/{stay_id}/confirm-occupancy")
def confirm_occupancy_status(
    request: Request,
    stay_id: int,
    action: str = Body(..., embed=True),  # vacant | occupied | vacated | renewed | holdover
    new_lease_end_date: str | None = Body(None, embed=True),  # required when action=renewed
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
):
    """Owner or assigned manager confirms unit status. Cannot confirm for tenant-invited guest stays (tenant lane)."""
    stay = db.query(Stay).filter(Stay.id == stay_id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    if is_tenant_lane_stay(db, stay):
        raise HTTPException(status_code=403, detail="Tenant-invited guest stays are private to the tenant. Only the tenant can confirm occupancy.")
    if not can_confirm_occupancy(db, current_user, stay):
        raise HTTPException(status_code=403, detail="You do not have permission to confirm occupancy for this stay")
    action = (action or "").strip().lower()
    if action == "vacant":
        action = "vacated"
    elif action == "occupied":
        action = "holdover"
    if action not in ("vacated", "renewed", "holdover"):
        raise HTTPException(status_code=400, detail="action must be vacant, occupied, vacated, renewed, or holdover")
    if action == "renewed" and not new_lease_end_date:
        raise HTTPException(status_code=400, detail="new_lease_end_date is required when action is renewed")

    prop = db.query(Property).filter(Property.id == stay.property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    prev_status = getattr(prop, "occupancy_status", None) or OccupancyStatus.vacant.value
    now = datetime.now(timezone.utc)
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None

    if action == "vacated":
        stay.checked_out_at = now
        stay.occupancy_confirmation_response = "vacated"
        stay.occupancy_confirmation_responded_at = now
        prop.occupancy_status = OccupancyStatus.vacant.value
        # DO NOT REMOVE — legacy: turn Shield off on vacated confirm (disabled CR-1a while SHIELD_MODE_ALWAYS_ON).
        if not SHIELD_MODE_ALWAYS_ON:
            if getattr(prop, "shield_mode_enabled", 0) == 1:
                prop.shield_mode_enabled = 0  # Unit status update: vacated → Shield off; billing prorated
                owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
                owner_user = db.query(User).filter(User.id == owner_profile.user_id).first() if owner_profile else None
                owner_email = (owner_user.email or "").strip() if owner_user else ""
                manager_emails = [
                    (u.email or "").strip()
                    for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == prop.id).all()
                    for u in [db.query(User).filter(User.id == a.user_id).first()]
                    if u and (u.email or "").strip()
                ]
                property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else "Property")
                try:
                    send_shield_mode_turned_off_notification(owner_email, manager_emails, property_name, turned_off_by="system (unit vacated)")
                except Exception:
                    pass
                addr = _format_property_address_for_log(prop)
                create_ledger_event(
                    db,
                    ACTION_SHIELD_MODE_OFF,
                    target_object_type="Property",
                    target_object_id=prop.id,
                    property_id=prop.id,
                    stay_id=stay.id,
                    actor_user_id=current_user.id,
                    meta={
                        "property_name": addr,
                        "message": f"Shield Mode turned off for {addr} (unit vacated).",
                        "reason": "unit_vacated",
                    },
                    ip_address=ip,
                    user_agent=ua,
                )
        if prop.usat_token_state == USAT_TOKEN_RELEASED:
            prop.usat_token_state = USAT_TOKEN_STAGED
            prop.usat_token_released_at = None
        unit_id = getattr(stay, "unit_id", None)
        if unit_id:
            unit = db.query(Unit).filter(Unit.id == unit_id).first()
            if unit:
                unit.occupancy_status = OccupancyStatus.vacant.value
                db.add(unit)
        invite_code = None
        if getattr(stay, "invitation_id", None):
            inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
            if inv:
                prev_token = getattr(inv, "token_state", None) or "BURNED"
                inv.token_state = "EXPIRED"
                invite_code = inv.invitation_code
                db.add(inv)
        db.add(stay)
        db.add(prop)
        db.commit()
        vacated_meta = {"occupancy_status_previous": prev_status, "occupancy_status_new": OccupancyStatus.vacant.value, "action": "vacated"}
        if invite_code:
            vacated_meta["invitation_code"] = invite_code
            vacated_meta["token_state_previous"] = prev_token
            vacated_meta["token_state_new"] = "EXPIRED"
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            "Owner confirmed: Unit Vacated",
            f"Stay {stay.id}: Owner confirmed unit vacated. Previous status: {prev_status}." + (f" Invite ID {invite_code} token_state -> EXPIRED." if invite_code else ""),
            property_id=stay.property_id,
            stay_id=stay.id,
            invitation_id=getattr(stay, "invitation_id", None),
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=ip,
            user_agent=ua,
            meta=vacated_meta,
        )
        db.commit()
        try:
            profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            if profile:
                sync_subscription_quantities(db, profile)
        except Exception:
            pass
        # Status Confirmation stay reminders off when stay ends (vacated)
        if getattr(stay, "dead_mans_switch_enabled", 0) == 1:
            owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            owner_user = db.query(User).filter(User.id == owner_profile.user_id).first() if owner_profile else None
            owner_email = (owner_user.email or "").strip() if owner_user else ""
            manager_emails = [
                (u.email or "").strip()
                for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == prop.id).all()
                for u in [db.query(User).filter(User.id == a.user_id).first()]
                if u and (u.email or "").strip()
            ]
            guest_name = label_for_stay(db, stay)
            property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else "Property")
            try:
                send_dms_turned_off_notification(owner_email, manager_emails, property_name, guest_name, stay.stay_end_date.isoformat(), reason="unit vacated")
            except Exception:
                pass
        create_alert_for_owner_and_managers(
            db, stay.property_id, "vacated",
            "Unit vacated",
            f"Stay for {guest_name} at {property_name} was confirmed as vacated. Occupancy status set to Vacant.",
            severity="info", stay_id=stay.id, meta={"guest_name": guest_name},
        )
        db.commit()
        return {"status": "success", "message": "Unit marked as vacated.", "occupancy_status": "vacant"}

    if action == "renewed":
        try:
            new_end = date.fromisoformat(new_lease_end_date.strip())
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="new_lease_end_date must be YYYY-MM-DD")
        if new_end <= stay.stay_end_date:
            raise HTTPException(status_code=400, detail="new_lease_end_date must be after current stay end date")
        stay.stay_end_date = new_end
        stay.occupancy_confirmation_response = "renewed"
        stay.occupancy_confirmation_responded_at = now
        # Update intended duration to match extended stay
        new_duration_days = (new_end - stay.stay_start_date).days
        stay.intended_stay_duration_days = new_duration_days
        # Renewal: ensure invite token is BURNED (e.g. if stay had expired and token was EXPIRED, renewal brings it back to active)
        invite_code = None
        prev_token = None
        if getattr(stay, "invitation_id", None):
            inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
            if inv:
                prev_token = getattr(inv, "token_state", None) or "BURNED"
                inv.token_state = "BURNED"
                invite_code = inv.invitation_code
                db.add(inv)
        # If new lease end is > 48h away, turn off stay reminders (owner renewed out of the 48h window)
        today = date.today()
        cutoff = today + timedelta(days=2)
        if new_end > cutoff and getattr(stay, "dead_mans_switch_enabled", 0) == 1:
            stay.dead_mans_switch_enabled = 0
            stay.dead_mans_switch_triggered_at = None
            create_log(
                db,
                CATEGORY_DEAD_MANS_SWITCH,
                "Status Confirmation reminders off (lease extended beyond 48h)",
                f"Stay {stay.id}: Lease extended to {new_end.isoformat()} (>48h away). Status Confirmation reminders disabled for this stay.",
                property_id=stay.property_id,
                stay_id=stay.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=ip,
                user_agent=ua,
                meta={"new_lease_end_date": new_end.isoformat(), "new_duration_days": new_duration_days},
            )
            owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            owner_user = db.query(User).filter(User.id == owner_profile.user_id).first() if owner_profile else None
            owner_email = (owner_user.email or "").strip() if owner_user else ""
            manager_emails = [
                (u.email or "").strip()
                for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == prop.id).all()
                for u in [db.query(User).filter(User.id == a.user_id).first()]
                if u and (u.email or "").strip()
            ]
            guest_name = label_for_stay(db, stay)
            property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else "Property")
            try:
                send_dms_turned_off_notification(owner_email, manager_emails, property_name, guest_name, new_end.isoformat(), reason="lease extended beyond 48h")
            except Exception:
                pass
        prop.occupancy_status = OccupancyStatus.occupied.value
        db.add(stay)
        db.add(prop)
        db.commit()
        renewed_meta = {"occupancy_status_previous": prev_status, "occupancy_status_new": OccupancyStatus.occupied.value, "action": "renewed", "new_lease_end_date": new_end.isoformat()}
        if invite_code:
            renewed_meta["invitation_code"] = invite_code
            renewed_meta["token_state_previous"] = prev_token
            renewed_meta["token_state_new"] = "BURNED"
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            "Owner confirmed: Lease Renewed",
            f"Stay {stay.id}: Owner renewed lease to {new_end.isoformat()}. Previous status: {prev_status}." + (f" Invite ID {invite_code} token_state {prev_token} -> BURNED." if invite_code else ""),
            property_id=stay.property_id,
            stay_id=stay.id,
            invitation_id=getattr(stay, "invitation_id", None),
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=ip,
            user_agent=ua,
            meta=renewed_meta,
        )
        db.commit()
        create_alert_for_owner_and_managers(
            db, stay.property_id, "renewed",
            "Lease renewed",
            f"Stay for {guest_name} at {property_name} was renewed to {new_end.isoformat()}. Occupancy status remains Occupied.",
            severity="info", stay_id=stay.id, meta={"guest_name": guest_name, "new_lease_end_date": new_end.isoformat()},
        )
        db.commit()
        return {"status": "success", "message": "Lease renewed.", "occupancy_status": "occupied", "new_lease_end_date": new_end.isoformat()}

    # holdover
    stay.occupancy_confirmation_response = "holdover"
    stay.occupancy_confirmation_responded_at = now
    prop.occupancy_status = OccupancyStatus.occupied.value
    db.add(stay)
    db.add(prop)
    db.commit()
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Owner confirmed: Holdover",
        f"Stay {stay.id}: Owner confirmed holdover (guest still in unit). Previous status: {prev_status}.",
        property_id=stay.property_id,
        stay_id=stay.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"occupancy_status_previous": prev_status, "occupancy_status_new": OccupancyStatus.occupied.value, "action": "holdover"},
    )
    create_alert_for_owner_and_managers(
        db, stay.property_id, "holdover",
        "Holdover confirmed",
        f"Stay for {guest_name} at {property_name} was confirmed as holdover (guest still in unit). Occupancy status set to Occupied.",
        severity="info", stay_id=stay.id, meta={"guest_name": guest_name},
    )
    db.commit()
    return {"status": "success", "message": "Holdover confirmed.", "occupancy_status": "occupied"}


def _refresh_property_occupancy_status_from_units(db: Session, prop: Property) -> str:
    """Recompute Property.occupancy_status from all units + tenant assignments (matches owner dashboard list)."""
    db.flush()
    units = db.query(Unit).filter(Unit.property_id == prop.id).all()
    eff = get_property_display_occupancy_status(db, prop, units)
    prop.occupancy_status = eff
    db.add(prop)
    return eff


@router.post("/tenant-assignments/{tenant_assignment_id}/confirm-occupancy")
def confirm_tenant_assignment_occupancy(
    request: Request,
    tenant_assignment_id: int,
    action: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
):
    """Owner/manager: Vacant or Occupied for a unit tenant lease (no guest Stay row). Clears tenant lease Status Confirmation alerts."""
    ta = db.query(TenantAssignment).filter(TenantAssignment.id == tenant_assignment_id).first()
    if not ta:
        raise HTTPException(status_code=404, detail="Tenant assignment not found")
    if not can_confirm_occupancy_for_tenant_assignment(db, current_user, ta):
        raise HTTPException(status_code=403, detail="You do not have permission to confirm occupancy for this tenant lease")

    unit = db.query(Unit).filter(Unit.id == ta.unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    prop = db.query(Property).filter(Property.id == unit.property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    action = (action or "").strip().lower()
    if action == "vacant":
        action = "vacated"
    elif action == "occupied":
        action = "holdover"
    if action not in ("vacated", "holdover"):
        raise HTTPException(status_code=400, detail="action must be vacant, occupied, vacated, or holdover")

    prev_status = getattr(prop, "occupancy_status", None) or OccupancyStatus.vacant.value
    now = datetime.now(timezone.utc)
    today = date.today()
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    tenant_name = label_from_user_id(db, ta.user_id) or "Tenant"
    property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else "Property")

    if action == "vacated":
        unit.occupancy_status = OccupancyStatus.vacant.value
        db.add(unit)
        # Resolve invites BEFORE shortening ta.end_date — matching uses exact lease end equality.
        for inv_row in list_invitations_matching_tenant_assignment_lease(db, ta):
            inv_row.token_state = "EXPIRED"
            db.add(inv_row)
        # End assignment for occupancy engine (otherwise active TA keeps unit "occupied" on dashboard)
        lease_end = ta.end_date if ta.end_date is not None else today
        ta.end_date = min(lease_end, today) - timedelta(days=1)
        db.add(ta)
        if not SHIELD_MODE_ALWAYS_ON:
            if getattr(prop, "shield_mode_enabled", 0) == 1:
                prop.shield_mode_enabled = 0
                owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
                owner_user = db.query(User).filter(User.id == owner_profile.user_id).first() if owner_profile else None
                owner_email = (owner_user.email or "").strip() if owner_user else ""
                manager_emails = [
                    (u.email or "").strip()
                    for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == prop.id).all()
                    for u in [db.query(User).filter(User.id == a.user_id).first()]
                    if u and (u.email or "").strip()
                ]
                try:
                    send_shield_mode_turned_off_notification(owner_email, manager_emails, property_name, turned_off_by="system (unit vacated)")
                except Exception:
                    pass
                addr = _format_property_address_for_log(prop)
                create_ledger_event(
                    db,
                    ACTION_SHIELD_MODE_OFF,
                    target_object_type="Property",
                    target_object_id=prop.id,
                    property_id=prop.id,
                    unit_id=unit.id,
                    stay_id=None,
                    actor_user_id=current_user.id,
                    meta={
                        "property_name": addr,
                        "message": f"Shield Mode turned off for {addr} (tenant unit vacated).",
                        "reason": "unit_vacated",
                        "tenant_assignment_id": ta.id,
                    },
                    ip_address=ip,
                    user_agent=ua,
                )
        if prop.usat_token_state == USAT_TOKEN_RELEASED:
            prop.usat_token_state = USAT_TOKEN_STAGED
            prop.usat_token_released_at = None
        eff_status = _refresh_property_occupancy_status_from_units(db, prop)
        db.commit()
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            "Owner confirmed: Unit Vacated (tenant lease)",
            f"Tenant assignment {ta.id}: Owner confirmed unit vacated after tenant lease. Previous property status: {prev_status}.",
            property_id=prop.id,
            stay_id=None,
            invitation_id=None,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=ip,
            user_agent=ua,
            meta={
                "occupancy_status_previous": prev_status,
                "occupancy_status_new": eff_status,
                "action": "vacated",
                "tenant_assignment_id": ta.id,
                "unit_id": unit.id,
            },
        )
        db.commit()
        try:
            profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            if profile:
                sync_subscription_quantities(db, profile)
        except Exception:
            pass
        create_alert_for_owner_and_managers(
            db,
            prop.id,
            "vacated",
            "Unit vacated",
            f"Tenant lease for {tenant_name} at {property_name} was confirmed as vacated. Occupancy set to Vacant.",
            severity="info",
            stay_id=None,
            meta={"tenant_name": tenant_name, "tenant_assignment_id": ta.id},
        )
        _mark_tenant_lease_occupancy_alerts_read(db, current_user.id, ta.id)
        db.commit()
        return {"status": "success", "message": "Unit marked as vacated.", "occupancy_status": eff_status}

    unit.occupancy_status = OccupancyStatus.occupied.value
    db.add(unit)
    if ta.end_date is not None and ta.end_date < today:
        ta.end_date = today
        db.add(ta)
    eff_status = _refresh_property_occupancy_status_from_units(db, prop)
    db.commit()
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Owner confirmed: Holdover (tenant lease)",
        f"Tenant assignment {ta.id}: Owner confirmed holdover (tenant still in unit). Previous property status: {prev_status}.",
        property_id=prop.id,
        stay_id=None,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={
            "occupancy_status_previous": prev_status,
            "occupancy_status_new": eff_status,
            "action": "holdover",
            "tenant_assignment_id": ta.id,
            "unit_id": unit.id,
        },
    )
    db.commit()
    create_alert_for_owner_and_managers(
        db,
        prop.id,
        "holdover",
        "Holdover confirmed",
        f"Tenant lease for {tenant_name} at {property_name} was confirmed as holdover (tenant still in unit). Occupancy set to Occupied.",
        severity="info",
        stay_id=None,
        meta={"tenant_name": tenant_name, "tenant_assignment_id": ta.id},
    )
    _mark_tenant_lease_occupancy_alerts_read(db, current_user.id, ta.id)
    db.commit()
    return {"status": "success", "message": "Holdover confirmed.", "occupancy_status": eff_status}


def _user_display_name_for_dashboard(db: Session, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        return None
    fn = (u.full_name or "").strip()
    return fn or (u.email or "").strip() or None


def _guest_stay_exists_for_invitation(db: Session, guest_user_id: int, inv: Invitation) -> bool:
    """True if this guest already has a Stay for this invitation, including legacy rows with invitation_id unset
    or dates adjusted after booking (overlap match)."""
    if (
        db.query(Stay)
        .filter(Stay.guest_id == guest_user_id, Stay.invitation_id == inv.id)
        .first()
    ):
        return True
    inv_unit = getattr(inv, "unit_id", None)
    # Legacy: invitation_id never set but same trip (exact dates)
    legacy_exact = [
        Stay.guest_id == guest_user_id,
        Stay.property_id == inv.property_id,
        Stay.stay_start_date == inv.stay_start_date,
        Stay.stay_end_date == inv.stay_end_date,
        Stay.invitation_id.is_(None),
    ]
    if inv_unit is not None:
        # Stay rows sometimes omit unit_id; treat as matching the invite's unit.
        legacy_exact.append(or_(Stay.unit_id == inv_unit, Stay.unit_id.is_(None)))
    if db.query(Stay).filter(and_(*legacy_exact)).first():
        return True
    # Same guest/property with overlapping stay window (extended dates, reissued invite, or legacy link).
    overlap_filters = [
        Stay.guest_id == guest_user_id,
        Stay.property_id == inv.property_id,
        Stay.stay_start_date <= inv.stay_end_date,
        Stay.stay_end_date >= inv.stay_start_date,
    ]
    if inv_unit is not None:
        overlap_filters.append(or_(Stay.unit_id == inv_unit, Stay.unit_id.is_(None)))
    return db.query(Stay).filter(and_(*overlap_filters)).first() is not None


def _guest_agreement_archive_stay_views(db: Session, current_user: User) -> list[GuestStayView]:
    """Signed guest agreements with no Stay row (e.g. pending invite expired before accept-invite). Keeps permanent history + PDF access."""
    if current_user.role != UserRole.guest:
        return []
    guest_email = (current_user.email or "").strip().lower()
    if not guest_email:
        return []
    candidates = (
        db.query(AgreementSignature)
        .filter(
            or_(
                func.lower(AgreementSignature.guest_email) == guest_email,
                AgreementSignature.used_by_user_id == current_user.id,
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
    out: list[GuestStayView] = []
    for sig in picked.values():
        code_norm = (sig.invitation_code or "").strip().upper()
        inv = db.query(Invitation).filter(Invitation.invitation_code == code_norm).first()
        if not inv:
            continue
        if (getattr(inv, "invitation_kind", None) or "").strip().lower() != "guest":
            continue
        # Invite already produced a Stay row — never show agreement-only archive for it.
        if db.query(Stay).filter(Stay.invitation_id == inv.id).first():
            continue
        if _guest_stay_exists_for_invitation(db, current_user.id, inv):
            continue
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
        region_code = (prop.region_code if prop else None) or sig.region_code
        jinfo = get_jurisdiction_for_property(db, prop.zip_code if prop else None, region_code)
        if jinfo is not None:
            classification = jinfo.stay_classification.value
            statute = jinfo.statutes[0].citation if jinfo.statutes else None
            explanation = jinfo.statutes[0].plain_english if jinfo.statutes and jinfo.statutes[0].plain_english else None
            laws = [st.citation + (f": {st.plain_english}" if st.plain_english else "") for st in jinfo.statutes]
            legal_notice = jinfo.removal_guest_text or "This stay does not grant tenancy or homestead rights."
            jurisdiction_state_name = jinfo.name
            jurisdiction_statutes = [JurisdictionStatuteInDashboard(citation=st.citation, plain_english=st.plain_english) for st in jinfo.statutes]
            removal_guest_text = jinfo.removal_guest_text
            removal_tenant_text = jinfo.removal_tenant_text
        else:
            rule = db.query(RegionRule).filter(RegionRule.region_code == region_code).first()
            classification = rule.stay_classification_label.value if rule else "guest"
            statute = rule.statute_reference if rule else None
            explanation = rule.plain_english_explanation if rule else None
            laws = [rule.statute_reference] if rule and rule.statute_reference else []
            legal_notice = "This stay does not grant tenancy or homestead rights."
            jurisdiction_state_name = None
            jurisdiction_statutes = []
            removal_guest_text = None
            removal_tenant_text = None
        unit_label_val = None
        if getattr(inv, "unit_id", None):
            unit_row = db.query(Unit).filter(Unit.id == inv.unit_id).first()
            if unit_row:
                unit_label_val = unit_row.unit_label
        arch_assigned = _user_display_name_for_dashboard(db, inv.owner_id)
        arch_accepted = (sig.guest_full_name or sig.guest_email or "").strip() or None
        out.append(
            GuestStayView(
                stay_id=0,
                record_kind="agreement_archive",
                agreement_signature_id=sig.id,
                invite_id=inv.invitation_code,
                token_state=getattr(inv, "token_state", None) or "EXPIRED",
                property_live_slug=prop.live_slug if prop else None,
                property_name=property_name,
                unit_label=unit_label_val,
                approved_stay_start_date=inv.stay_start_date,
                approved_stay_end_date=inv.stay_end_date,
                region_code=region_code,
                region_classification=classification,
                legal_notice=legal_notice,
                statute_reference=statute,
                plain_english_explanation=explanation,
                applicable_laws=laws,
                jurisdiction_state_name=jurisdiction_state_name,
                jurisdiction_statutes=jurisdiction_statutes,
                removal_guest_text=removal_guest_text,
                removal_tenant_text=removal_tenant_text,
                usat_token=None,
                revoked_at=None,
                vacate_by=None,
                checked_in_at=None,
                checked_out_at=None,
                cancelled_at=None,
                residence_assigned_by_name=arch_assigned,
                stay_accepted_by_name=arch_accepted,
                property_deleted_at=getattr(prop, "deleted_at", None) if prop else None,
            )
        )
    return out


# Guest approaching-end ledger rows are normally created by the daily stay-notification job.
# Materialize them when guests load the app so dev / no-cron environments still get in-app notifications (idempotent).
_guest_end_ledger_last_sync_mono: dict[tuple[int, str], float] = {}
_GUEST_END_LEDGER_SYNC_INTERVAL_SEC = 35.0


def _guest_invitation_ids_for_ledger(db: Session, guest_user: User) -> set[int]:
    """Stay-linked invitation IDs plus archive-only rows (signed agreement, no ``Stay``) so ledger events with ``stay_id`` NULL still appear."""
    if guest_user.role != UserRole.guest:
        return set()
    out: set[int] = set()
    for s in db.query(Stay).filter(Stay.guest_id == guest_user.id).all():
        if getattr(s, "invitation_id", None):
            out.add(int(s.invitation_id))
    for row in db.query(GuestPendingInvite).filter(GuestPendingInvite.user_id == guest_user.id).all():
        if getattr(row, "invitation_id", None):
            out.add(int(row.invitation_id))
    guest_email = (guest_user.email or "").strip().lower()
    if not guest_email:
        return out
    inv_ids_with_stay = set(out)
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
    for sig in picked.values():
        code_norm = (sig.invitation_code or "").strip().upper()
        inv = db.query(Invitation).filter(Invitation.invitation_code == code_norm).first()
        if not inv:
            continue
        if inv.id in inv_ids_with_stay:
            continue
        if (getattr(inv, "invitation_kind", None) or "").strip().lower() != "guest":
            continue
        if db.query(Stay).filter(Stay.invitation_id == inv.id).first():
            continue
        if _guest_stay_exists_for_invitation(db, guest_user.id, inv):
            continue
        out.add(inv.id)
    return out


def _maybe_materialize_guest_approaching_end_ledger(
    db: Session,
    guest_user_id: int,
    client_calendar_date: date | None = None,
) -> None:
    global _guest_end_ledger_last_sync_mono
    ck = client_calendar_date.isoformat() if client_calendar_date else "default"
    key = (guest_user_id, ck)
    now = time.monotonic()
    last = _guest_end_ledger_last_sync_mono.get(key, 0.0)
    if now - last < _GUEST_END_LEDGER_SYNC_INTERVAL_SEC:
        return
    _guest_end_ledger_last_sync_mono[key] = now
    from app.services.stay_timer import run_tenant_lane_guest_stay_ending_notifications

    run_tenant_lane_guest_stay_ending_notifications(
        db,
        only_guest_user_id=guest_user_id,
        client_calendar_date=client_calendar_date,
    )


@router.get("/guest/stays", response_model=list[GuestStayView])
def guest_stays(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest_or_tenant),
    x_client_calendar_date: str | None = Header(None, alias="X-Client-Calendar-Date"),
):
    """Guest view: stays where this user is the guest. Tenants must not use this endpoint — guest stays they host appear under /dashboard/tenant/guest-history."""
    if current_user.role == UserRole.tenant:
        return []
    if current_user.role == UserRole.guest:
        _maybe_materialize_guest_approaching_end_ledger(
            db,
            current_user.id,
            _parse_guest_client_calendar_date_header(x_client_calendar_date),
        )
    stays = db.query(Stay).filter(Stay.guest_id == current_user.id).order_by(Stay.stay_start_date.desc()).limit(_GUEST_STAYS_LIMIT).all()
    out = []
    for s in stays:
        prop = db.query(Property).filter(Property.id == s.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
        region_code = (prop.region_code if prop else None) or s.region_code
        # Prefer Jurisdiction SOT (DB) for classification, statutes, removal text — same source as live page and agreements
        jinfo = get_jurisdiction_for_property(db, prop.zip_code if prop else None, region_code)
        if jinfo is not None:
            classification = jinfo.stay_classification.value
            statute = jinfo.statutes[0].citation if jinfo.statutes else None
            explanation = jinfo.statutes[0].plain_english if jinfo.statutes and jinfo.statutes[0].plain_english else None
            laws = [st.citation + (f": {st.plain_english}" if st.plain_english else "") for st in jinfo.statutes]
            legal_notice = jinfo.removal_guest_text or "This stay does not grant tenancy or homestead rights."
            jurisdiction_state_name = jinfo.name
            jurisdiction_statutes = [JurisdictionStatuteInDashboard(citation=st.citation, plain_english=st.plain_english) for st in jinfo.statutes]
            removal_guest_text = jinfo.removal_guest_text
            removal_tenant_text = jinfo.removal_tenant_text
        else:
            rule = db.query(RegionRule).filter(RegionRule.region_code == s.region_code).first()
            classification = rule.stay_classification_label.value if rule else "guest"
            statute = rule.statute_reference if rule else None
            explanation = rule.plain_english_explanation if rule else None
            laws = [rule.statute_reference] if rule and rule.statute_reference else []
            legal_notice = "This stay does not grant tenancy or homestead rights."
            jurisdiction_state_name = None
            jurisdiction_statutes = []
            removal_guest_text = None
            removal_tenant_text = None
        # Owner tokens are not shared with guests; guest never sees USAT token.
        usat_token = None
        revoked_at = getattr(s, "revoked_at", None)
        vacate_by = (revoked_at + timedelta(hours=12)).isoformat() if revoked_at else None
        checked_out_at = getattr(s, "checked_out_at", None)
        cancelled_at = getattr(s, "cancelled_at", None)
        invite_id_val = None
        token_state_val = None
        unit_label_val = None
        if getattr(s, "unit_id", None):
            unit_row = db.query(Unit).filter(Unit.id == s.unit_id).first()
            if unit_row:
                unit_label_val = unit_row.unit_label
        if getattr(s, "invitation_id", None):
            inv = db.query(Invitation).filter(Invitation.id == s.invitation_id).first()
            if inv:
                invite_id_val = inv.invitation_code
                token_state_val = getattr(inv, "token_state", None) or "BURNED"
        ext_pending = (
            db.query(GuestExtensionRequest)
            .filter(GuestExtensionRequest.stay_id == s.id, GuestExtensionRequest.status == "pending")
            .first()
        )
        can_request_extension = bool(
            is_tenant_lane_stay(db, s)
            and getattr(s, "checked_in_at", None)
            and not checked_out_at
            and not cancelled_at
            and not revoked_at
            and ext_pending is None
        )
        assigned_nm = _user_display_name_for_dashboard(db, s.owner_id)
        accepted_nm = _user_display_name_for_dashboard(db, s.guest_id)
        out.append(
            GuestStayView(
                stay_id=s.id,
                record_kind="stay",
                agreement_signature_id=None,
                invite_id=invite_id_val,
                token_state=token_state_val,
                property_live_slug=prop.live_slug if prop else None,
                property_name=property_name,
                unit_label=unit_label_val,
                approved_stay_start_date=s.stay_start_date,
                approved_stay_end_date=s.stay_end_date,
                region_code=s.region_code,
                region_classification=classification,
                legal_notice=legal_notice,
                statute_reference=statute,
                plain_english_explanation=explanation,
                applicable_laws=laws,
                jurisdiction_state_name=jurisdiction_state_name,
                jurisdiction_statutes=jurisdiction_statutes,
                removal_guest_text=removal_guest_text,
                removal_tenant_text=removal_tenant_text,
                usat_token=usat_token,
                revoked_at=revoked_at,
                vacate_by=vacate_by,
                checked_in_at=getattr(s, "checked_in_at", None),
                checked_out_at=checked_out_at,
                cancelled_at=cancelled_at,
                can_request_extension=can_request_extension,
                residence_assigned_by_name=assigned_nm,
                stay_accepted_by_name=accepted_nm,
                property_deleted_at=getattr(prop, "deleted_at", None) if prop else None,
            )
        )
    out.extend(_guest_agreement_archive_stay_views(db, current_user))
    out.sort(
        key=lambda v: (
            v.approved_stay_end_date,
            v.approved_stay_start_date,
            1 if getattr(v, "record_kind", None) != "agreement_archive" else 0,
        ),
        reverse=True,
    )
    return out


@router.get("/guest/logs", response_model=list[OwnerAuditLogEntry])
def guest_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest_or_tenant),
    from_ts: str | None = None,
    to_ts: str | None = None,
    category: str | None = None,
    search: str | None = None,
    stay_id: int | None = None,
    x_client_calendar_date: str | None = Header(None, alias="X-Client-Calendar-Date"),
):
    """Guest lane logs only: events for the guest's own stays. No property management or other users' data."""
    from sqlalchemy import desc, cast, String

    if current_user.role == UserRole.guest:
        _maybe_materialize_guest_approaching_end_ledger(
            db,
            current_user.id,
            _parse_guest_client_calendar_date_header(x_client_calendar_date),
        )
    stays = db.query(Stay).filter(Stay.guest_id == current_user.id).all()
    stay_ids = [s.id for s in stays]
    inv_ids = _guest_invitation_ids_for_ledger(db, current_user) if current_user.role == UserRole.guest else set()
    if not stay_ids and not inv_ids:
        return []
    if stay_id is not None and stay_id != 0 and stay_id not in stay_ids:
        return []
    q = db.query(EventLedger).filter(EventLedger.action_type.in_(GUEST_ALLOWED_ACTIONS))
    scope = []
    if stay_ids:
        scope.append(EventLedger.stay_id.in_(stay_ids))
    if inv_ids:
        scope.append(EventLedger.invitation_id.in_(list(inv_ids)))
    if not scope:
        return []
    q = q.filter(or_(*scope))
    if stay_id is not None and stay_id != 0:
        q = q.filter(EventLedger.stay_id == stay_id)
    from_dt = _parse_optional_utc(from_ts)
    to_dt = _parse_optional_utc(to_ts)
    if from_dt is not None:
        q = q.filter(EventLedger.created_at >= from_dt)
    if to_dt is not None:
        q = q.filter(EventLedger.created_at <= to_dt)
    if category and category.strip():
        action_types = _CATEGORY_TO_ACTION_TYPES.get(category.strip(), [])
        if action_types:
            q = q.filter(EventLedger.action_type.in_(action_types))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter((EventLedger.action_type.ilike(term)) | (cast(EventLedger.meta, String).ilike(term)))
    rows = q.order_by(desc(EventLedger.created_at)).limit(200).all()
    prop_ids = {r.property_id for r in rows if r.property_id}
    props = {}
    if prop_ids:
        for p in db.query(Property).filter(Property.id.in_(prop_ids)).all():
            props[p.id] = _format_property_address_for_log(p)
    out = []
    for r in rows:
        cat, title, msg = ledger_event_to_display(r, db)
        actor_email = get_actor_email(db, r.actor_user_id)
        out.append(
            OwnerAuditLogEntry(
                id=r.id, property_id=r.property_id, stay_id=r.stay_id, invitation_id=r.invitation_id,
                category=cat, title=title, message=msg,
                actor_user_id=r.actor_user_id, actor_email=actor_email, ip_address=r.ip_address,
                created_at=r.created_at if r.created_at else datetime.now(timezone.utc),
                property_name=props.get(r.property_id) if r.property_id else None,
            )
        )
    return out


@router.post("/guest/stays/{stay_id}/check-in")
def guest_check_in(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest_or_tenant),
):
    """Guest/tenant records check-in: sets checked_in_at and property occupancy to OCCUPIED. Stay must be on or after start date, not already checked in/out/cancelled."""
    stay = db.query(Stay).filter(Stay.id == stay_id, Stay.guest_id == current_user.id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    if getattr(stay, "checked_in_at", None):
        return {"status": "success", "message": "Already checked in."}
    if getattr(stay, "checked_out_at", None):
        raise HTTPException(status_code=400, detail="Cannot check in to a stay you have already checked out of.")
    if getattr(stay, "cancelled_at", None):
        raise HTTPException(status_code=400, detail="Cannot check in to a cancelled stay.")
    today = date.today()
    if stay.stay_start_date > today:
        raise HTTPException(status_code=400, detail="Check-in is only available on or after your stay start date.")
    now = datetime.now(timezone.utc)
    stay.checked_in_at = now
    db.add(stay)
    prop = db.query(Property).filter(Property.id == stay.property_id).first()
    shield_turned_off_on_checkin = False
    if prop:
        prop.occupancy_status = OccupancyStatus.occupied.value
        # DO NOT REMOVE — legacy: Shield off when guest checks in (disabled CR-1a while SHIELD_MODE_ALWAYS_ON).
        if not SHIELD_MODE_ALWAYS_ON:
            if getattr(prop, "shield_mode_enabled", 0) == 1:
                prop.shield_mode_enabled = 0
                shield_turned_off_on_checkin = True
                owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
                owner_user = db.query(User).filter(User.id == owner_profile.user_id).first() if owner_profile else None
                owner_email = (owner_user.email or "").strip() if owner_user else ""
                manager_emails = [
                    (u.email or "").strip()
                    for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == prop.id).all()
                    for u in [db.query(User).filter(User.id == a.user_id).first()]
                    if u and (u.email or "").strip()
                ]
                property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else "Property")
                try:
                    send_shield_mode_turned_off_notification(owner_email, manager_emails, property_name, turned_off_by="system (guest checked in)")
                except Exception:
                    pass
        db.add(prop)
    unit_id = getattr(stay, "unit_id", None)
    if unit_id:
        unit = db.query(Unit).filter(Unit.id == unit_id).first()
        if unit:
            unit.occupancy_status = OccupancyStatus.occupied.value
            db.add(unit)
    db.commit()
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    guest_name = label_for_stay(db, stay)
    property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}".strip(", ") if prop and (prop.city or prop.state) else None) or f"property {stay.property_id}"
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Guest checked in",
        f"{guest_name} checked in at {property_name}. Occupancy set to occupied.",
        property_id=stay.property_id,
        stay_id=stay.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"occupancy_status_new": "occupied", "guest_name": guest_name, "guest_id": stay.guest_id},
    )
    create_ledger_event(
        db,
        ACTION_GUEST_CHECK_IN,
        property_id=stay.property_id,
        unit_id=unit_id,
        stay_id=stay.id,
        actor_user_id=current_user.id,
        ip_address=ip,
        user_agent=ua,
        meta={
            "message": f"{guest_name} checked in at {property_name}. Occupancy set to occupied.",
            "guest_name": guest_name,
            "guest_id": stay.guest_id,
        },
    )
    if shield_turned_off_on_checkin and prop:
        addr = _format_property_address_for_log(prop)
        create_ledger_event(
            db,
            ACTION_SHIELD_MODE_OFF,
            target_object_type="Property",
            target_object_id=prop.id,
            property_id=prop.id,
            stay_id=stay.id,
            actor_user_id=current_user.id,
            meta={
                "property_name": addr,
                "message": f"Shield Mode turned off for {addr} (guest checked in).",
                "reason": "guest_checked_in",
            },
            ip_address=ip,
            user_agent=ua,
        )
    db.commit()

    # Dev/test only: turn Status Confirmation reminders on 2 min after check-in (from invitation preference). In prod, they turn on 48h before lease end (stay_timer).
    try:
        from app.config import get_settings
        from app.database import SessionLocal
        from app.services.stay_timer import run_dead_mans_switch_job
        _settings = get_settings()
        scheduler = getattr(request.app.state, "scheduler", None)
        dms_test = getattr(_settings, "dms_test_mode", False)
        if scheduler and dms_test:
            stay_id = stay.id
            run_at = now + timedelta(minutes=2)

            def _turn_dms_on_2min_after_checkin(sid: int):
                _db = SessionLocal()
                logger.info("Status Confirmation 2min-after-checkin job started for stay_id=%s", sid)
                try:
                    _stay = _db.query(Stay).filter(Stay.id == sid).first()
                    if not _stay:
                        logger.info("Status Confirmation 2min-after-checkin job: stay_id=%s not found, skipped", sid)
                        return
                    if getattr(_stay, "dead_mans_switch_enabled", 0) == 1:
                        logger.info(
                            "Status Confirmation 2min-after-checkin job: stay_id=%s already has stay reminders on, skipped",
                            sid,
                        )
                    elif getattr(_stay, "dead_mans_switch_enabled", 0) == 0:
                        inv = None
                        if getattr(_stay, "invitation_id", None):
                            inv = _db.query(Invitation).filter(Invitation.id == _stay.invitation_id).first()
                        # In test mode always turn stay reminders on after 2 min so testing works. Otherwise only if invitation had them enabled.
                        turn_on = getattr(_settings, "dms_test_mode", False) or (
                            inv and getattr(inv, "dead_mans_switch_enabled", 0)
                        )
                        if not turn_on:
                            if not inv:
                                logger.info(
                                    "Status Confirmation 2min-after-checkin job: stay_id=%s has no invitation, skipped (stay reminders not turned on)",
                                    sid,
                                )
                            else:
                                logger.info(
                                    "Status Confirmation 2min-after-checkin job: stay_id=%s invitation has stay reminders off, skipped",
                                    sid,
                                )
                        elif is_tenant_lane_stay(_db, _stay):
                            logger.info(
                                "Status Confirmation 2min-after-checkin job: stay_id=%s is tenant-lane guest stay; Status Confirmation not enabled",
                                sid,
                            )
                        else:
                            _stay.dead_mans_switch_enabled = 1
                            _db.add(_stay)
                            _db.commit()
                            logger.info(
                                "Status Confirmation 2min-after-checkin job: turned stay reminders on for stay_id=%s (test_mode=%s, inv_pref=%s)",
                                sid,
                                getattr(_settings, "dms_test_mode", False),
                                getattr(inv, "dead_mans_switch_enabled", 0) if inv else None,
                            )
                    if getattr(_settings, "dms_test_mode", False):
                        logger.info("Status Confirmation 2min-after-checkin job: running Status Confirmation job handler (test mode)")
                        run_dead_mans_switch_job(_db)
                except Exception as e:
                    logger.exception(
                        "Status Confirmation 2min-after-checkin job: stay_id=%s failed: %s",
                        sid,
                        e,
                    )
                finally:
                    _db.close()
                    logger.info("Status Confirmation 2min-after-checkin job finished for stay_id=%s", sid)

            logger.info(
                "Status Confirmation 2min-after-checkin: scheduling job for stay_id=%s, run_at=%s",
                stay_id,
                run_at.isoformat(),
            )
            scheduler.add_job(_turn_dms_on_2min_after_checkin, "date", run_date=run_at, args=[stay_id])
        else:
            logger.info(
                "Status Confirmation 2min-after-checkin: not scheduling for stay_id=%s (dms_test_mode=%s, scheduler=%s)",
                stay.id,
                dms_test,
                scheduler is not None,
            )
    except Exception as e:
        logger.warning("Status Confirmation 2min-after-checkin: failed to schedule job for stay_id=%s: %s", stay.id, e)

    return {"status": "success", "message": "You are checked in. Your stay is now active."}


def _agreement_signature_pdf_file_response(db: Session, sig: AgreementSignature) -> Response:
    """Build PDF Response for a guest agreement signature (Dropbox, stored bytes, or generated from HTML)."""
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
            detail="Document not yet signed in Dropbox. Please complete signing in the link we sent you.",
        )
    if sig.signed_pdf_bytes:
        return Response(
            content=sig.signed_pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="DocuStay-Signed-{sig.invitation_code}.pdf"'},
        )
    date_str = sig.signed_at.strftime("%Y-%m-%d") if sig.signed_at else ""
    content = fill_guest_signature_in_content(sig.document_content, sig.typed_signature, date_str, getattr(sig, "ip_address", None))
    pdf_bytes = agreement_content_to_pdf(sig.document_title, content)
    sig.signed_pdf_bytes = pdf_bytes
    db.commit()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="DocuStay-Signed-{sig.invitation_code}.pdf"'},
    )


@router.get("/guest/signatures/{signature_id}/signed-agreement-pdf")
def guest_agreement_pdf_by_signature(
    signature_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest_or_tenant),
):
    """Authenticated download of a signed guest agreement by signature id (e.g. agreement-archive rows with no Stay)."""
    if current_user.role != UserRole.guest:
        raise HTTPException(status_code=403, detail="Guest access only.")
    sig = db.query(AgreementSignature).filter(AgreementSignature.id == signature_id).first()
    if not sig:
        raise HTTPException(status_code=404, detail="Signed agreement not found")
    em = (current_user.email or "").strip().lower()
    ok = (sig.used_by_user_id == current_user.id) or (
        em and (sig.guest_email or "").strip().lower() == em
    )
    if not ok:
        raise HTTPException(status_code=403, detail="You can only download your own signed agreements.")
    return _agreement_signature_pdf_file_response(db, sig)


@router.get("/guest/stays/{stay_id}/signed-agreement-pdf")
def guest_stay_signed_agreement_pdf(
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest_or_tenant),
):
    """Return the signed guest agreement PDF for this stay. Guest/tenant must own the stay. Returns 404 if no signed agreement (e.g. stay created before signing flow)."""
    stay = db.query(Stay).filter(Stay.id == stay_id, Stay.guest_id == current_user.id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    inv = None
    if stay.invitation_id:
        inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
    if not inv:
        inv = (
            db.query(Invitation)
            .filter(
                Invitation.property_id == stay.property_id,
                Invitation.stay_start_date == stay.stay_start_date,
                Invitation.stay_end_date == stay.stay_end_date,
                Invitation.status.in_(["accepted", "expired"]),
            )
            .first()
        )
    if not inv:
        raise HTTPException(status_code=404, detail="No signed agreement found for this stay.")
    g_em = (current_user.email or "").strip().lower()
    q = db.query(AgreementSignature).filter(AgreementSignature.invitation_code == inv.invitation_code)
    if g_em:
        q = q.filter(
            or_(
                AgreementSignature.used_by_user_id == current_user.id,
                func.lower(AgreementSignature.guest_email) == g_em,
            )
        )
    else:
        q = q.filter(AgreementSignature.used_by_user_id == current_user.id)
    sig = q.order_by(AgreementSignature.signed_at.desc()).first()
    if not sig:
        raise HTTPException(status_code=404, detail="No signed agreement found for this stay.")
    return _agreement_signature_pdf_file_response(db, sig)


@router.get("/tenant/guest-stays/{stay_id}/signed-agreement-pdf")
def tenant_invited_guest_stay_signed_agreement_pdf(
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """Signed guest agreement PDF for a stay the tenant created by inviting that guest (tenant lane)."""
    stay = db.query(Stay).filter(Stay.id == stay_id).first()
    if not stay or not stay.invitation_id:
        raise HTTPException(status_code=404, detail="Stay not found")
    inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
    if not inv or inv.invited_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only view agreements for guests you invited.")
    if (getattr(inv, "invitation_kind", None) or "guest").strip().lower() != "guest":
        raise HTTPException(status_code=403, detail="Not a guest invitation.")
    sig = (
        db.query(AgreementSignature)
        .filter(
            AgreementSignature.invitation_code == inv.invitation_code,
            AgreementSignature.used_by_user_id == stay.guest_id,
        )
        .order_by(AgreementSignature.signed_at.desc())
        .first()
    )
    if not sig:
        raise HTTPException(status_code=404, detail="No signed agreement found for this stay.")
    return _agreement_signature_pdf_file_response(db, sig)


@router.get("/tenant/guest-signatures/{signature_id}/signed-agreement-pdf")
def tenant_invited_guest_signature_signed_agreement_pdf(
    signature_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """Signed agreement PDF by signature id when the tenant invited the guest (e.g. signed before stay row exists)."""
    sig = db.query(AgreementSignature).filter(AgreementSignature.id == signature_id).first()
    if not sig:
        raise HTTPException(status_code=404, detail="Signature not found")
    inv = db.query(Invitation).filter(Invitation.invitation_code == sig.invitation_code).first()
    if not inv or inv.invited_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only view agreements for guests you invited.")
    if (getattr(inv, "invitation_kind", None) or "guest").strip().lower() != "guest":
        raise HTTPException(status_code=403, detail="Not a guest invitation.")
    if not sig.used_by_user_id:
        raise HTTPException(status_code=404, detail="Agreement is not signed yet.")
    return _agreement_signature_pdf_file_response(db, sig)


@router.post("/guest/stays/{stay_id}/end")
def guest_end_stay(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest_or_tenant),
):
    """Let the guest/tenant end an ongoing stay (set end date to today). Revoked stays can still be ended so the guest can record checkout."""
    stay = db.query(Stay).filter(Stay.id == stay_id, Stay.guest_id == current_user.id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    today = date.today()
    if stay.stay_start_date > today:
        raise HTTPException(status_code=400, detail="Cannot end a future stay.")
    if stay.stay_end_date < today:
        raise HTTPException(status_code=400, detail="This stay has already ended.")
    if getattr(stay, "checked_out_at", None):
        raise HTTPException(status_code=400, detail="You have already checked out of this stay.")
    stay.stay_end_date = today
    stay.checked_out_at = datetime.now(timezone.utc)
    invite_code = None
    if getattr(stay, "invitation_id", None):
        inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
        if inv:
            prev_token = getattr(inv, "token_state", None) or "BURNED"
            inv.token_state = "EXPIRED"
            invite_code = inv.invitation_code
            db.add(inv)
    db.add(stay)
    db.flush()
    from app.services.guest_stay_overlap import (
        other_checked_in_guest_stay_on_property,
        other_checked_in_guest_stay_on_same_unit,
    )

    uid = getattr(stay, "unit_id", None)
    other_in_prop = other_checked_in_guest_stay_on_property(
        db, property_id=stay.property_id, exclude_stay_id=stay.id
    )
    other_on_unit = other_checked_in_guest_stay_on_same_unit(
        db, property_id=stay.property_id, unit_id=uid, exclude_stay_id=stay.id
    )
    occ_prev = None
    if not other_in_prop:
        prop = db.query(Property).filter(Property.id == stay.property_id).first()
        if prop:
            occ_prev = getattr(prop, "occupancy_status", None) or OccupancyStatus.vacant.value
            if prop.usat_token_state == USAT_TOKEN_RELEASED:
                prop.usat_token_state = USAT_TOKEN_STAGED
                prop.usat_token_released_at = None
            prop.occupancy_status = OccupancyStatus.vacant.value
            db.add(prop)
    if uid and not other_on_unit:
        unit = db.query(Unit).filter(Unit.id == uid).first()
        if unit:
            unit.occupancy_status = OccupancyStatus.vacant.value
            db.add(unit)
    db.commit()
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    log_meta = {}
    if occ_prev is not None:
        log_meta["occupancy_status_previous"] = occ_prev
        log_meta["occupancy_status_new"] = "vacant"
    if invite_code:
        log_meta["invitation_code"] = invite_code
        log_meta["token_state_previous"] = prev_token
        log_meta["token_state_new"] = "EXPIRED"
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Guest checked out",
        f"Guest checked out of stay {stay.id} (property {stay.property_id}). End date set to {today.isoformat()}." + (f" Invite ID {invite_code} token_state -> EXPIRED." if invite_code else "") + (f" Occupancy status: {occ_prev} -> vacant." if occ_prev is not None else ""),
        property_id=stay.property_id,
        stay_id=stay.id,
        invitation_id=getattr(stay, "invitation_id", None),
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta=log_meta if log_meta else None,
    )
    _guest_name = label_for_stay(db, stay)
    _prop = db.query(Property).filter(Property.id == stay.property_id).first()
    _property_name = (_prop.name if _prop else None) or (f"{_prop.city}, {_prop.state}".strip(", ") if _prop and (_prop.city or _prop.state) else None) or f"property {stay.property_id}"
    checkout_meta = dict(log_meta) if log_meta else {}
    checkout_meta["message"] = f"Guest checked out of stay {stay.id} ({_property_name}). End date set to {today.isoformat()}."
    checkout_meta["guest_name"] = _guest_name
    create_ledger_event(
        db,
        ACTION_GUEST_CHECK_OUT,
        property_id=stay.property_id,
        unit_id=getattr(stay, "unit_id", None),
        stay_id=stay.id,
        invitation_id=getattr(stay, "invitation_id", None),
        actor_user_id=current_user.id,
        ip_address=ip,
        user_agent=ua,
        meta=checkout_meta,
    )
    db.commit()
    # Notify owner and guest about checkout; stay reminders off when stay ends
    owner = db.query(User).filter(User.id == stay.owner_id).first()
    property_obj = db.query(Property).filter(Property.id == stay.property_id).first()
    guest_name = (current_user.full_name or "").strip() or (current_user.email or "").strip() or "Unknown invitee"
    property_name = (property_obj.name if property_obj else None) or "your property"
    if getattr(stay, "dead_mans_switch_enabled", 0) == 1 and property_obj:
        owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == property_obj.owner_profile_id).first()
        owner_user = db.query(User).filter(User.id == owner_profile.user_id).first() if owner_profile else None
        owner_email = (owner_user.email or "").strip() if owner_user else ""
        manager_emails = [
            (u.email or "").strip()
            for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == stay.property_id).all()
            for u in [db.query(User).filter(User.id == a.user_id).first()]
            if u and (u.email or "").strip()
        ]
        prop_name = (property_obj.name or "").strip() or (f"{property_obj.city}, {property_obj.state}".strip(", ") if property_obj and (property_obj.city or property_obj.state) else "Property")
        try:
            send_dms_turned_off_notification(owner_email, manager_emails, prop_name, guest_name, today.isoformat(), reason="guest checked out")
        except Exception:
            pass
    # Email to owner
    if owner and owner.email:
        send_owner_guest_checkout_email(
            owner.email,
            guest_name,
            property_name,
            today.isoformat(),
        )
    # Email to guest (checkout confirmation)
    if current_user.email:
        send_guest_checkout_confirmation_email(
            current_user.email,
            guest_name,
            property_name,
            today.isoformat(),
        )
    return {"status": "success", "message": "Stay ended."}


@router.post("/guest/stays/{stay_id}/cancel")
def guest_cancel_stay(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest_or_tenant),
):
    """Let the guest/tenant cancel a future stay (set end date to day before start so the stay is no longer upcoming)."""
    stay = db.query(Stay).filter(Stay.id == stay_id, Stay.guest_id == current_user.id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    today = date.today()
    if stay.stay_start_date <= today:
        raise HTTPException(status_code=400, detail="Only future stays can be cancelled. Use checkout to end an ongoing stay.")
    if getattr(stay, "cancelled_at", None):
        raise HTTPException(status_code=400, detail="This stay has already been cancelled.")
    original_start = stay.stay_start_date
    # Set end date to day before start so the stay is effectively cancelled and shows as past
    stay.stay_end_date = original_start - timedelta(days=1)
    stay.cancelled_at = datetime.now(timezone.utc)
    invite_code = None
    if getattr(stay, "invitation_id", None):
        inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
        if inv:
            prev_token = getattr(inv, "token_state", None) or "BURNED"
            inv.token_state = "REVOKED"
            invite_code = inv.invitation_code
            db.add(inv)
    db.add(stay)
    db.flush()
    from app.services.guest_stay_overlap import (
        other_checked_in_guest_stay_on_property,
        other_checked_in_guest_stay_on_same_unit,
    )

    cancel_uid = getattr(stay, "unit_id", None)
    other_in_prop = other_checked_in_guest_stay_on_property(
        db, property_id=stay.property_id, exclude_stay_id=stay.id
    )
    other_on_unit = other_checked_in_guest_stay_on_same_unit(
        db, property_id=stay.property_id, unit_id=cancel_uid, exclude_stay_id=stay.id
    )
    occ_prev = None
    if not other_in_prop:
        prop = db.query(Property).filter(Property.id == stay.property_id).first()
        if prop:
            occ_prev = getattr(prop, "occupancy_status", None) or OccupancyStatus.vacant.value
            if prop.usat_token_state == USAT_TOKEN_RELEASED:
                prop.usat_token_state = USAT_TOKEN_STAGED
                prop.usat_token_released_at = None
            prop.occupancy_status = OccupancyStatus.vacant.value
            db.add(prop)
    if cancel_uid and not other_on_unit:
        unit = db.query(Unit).filter(Unit.id == cancel_uid).first()
        if unit:
            unit.occupancy_status = OccupancyStatus.vacant.value
            db.add(unit)
    db.commit()
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    log_meta = {"original_start_date": str(original_start)}
    if occ_prev is not None:
        log_meta["occupancy_status_previous"] = occ_prev
        log_meta["occupancy_status_new"] = "vacant"
    if invite_code:
        log_meta["invitation_code"] = invite_code
        log_meta["token_state_previous"] = prev_token
        log_meta["token_state_new"] = "REVOKED"
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Stay cancelled by guest",
        f"Guest cancelled stay {stay.id} (property {stay.property_id}). Original start was {original_start.isoformat()}." + (f" Invite ID {invite_code} token_state -> REVOKED." if invite_code else "") + (f" Occupancy status: {occ_prev} -> vacant." if occ_prev else ""),
        property_id=stay.property_id,
        stay_id=stay.id,
        invitation_id=getattr(stay, "invitation_id", None),
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta=log_meta,
    )
    db.commit()
    # Notify owner that guest cancelled
    owner = db.query(User).filter(User.id == stay.owner_id).first()
    property_obj = db.query(Property).filter(Property.id == stay.property_id).first()
    if owner and owner.email:
        guest_name = (current_user.full_name or "").strip() or (current_user.email or "").strip() or "Unknown invitee"
        property_name = (property_obj.name if property_obj else None) or "your property"
        send_owner_guest_cancelled_stay_email(
            owner.email,
            guest_name,
            property_name,
            original_start.isoformat(),
        )
    return {"status": "success", "message": "Stay cancelled."}


_EXTENSION_REQ_LOG_TITLE = "Guest extension request sent"
_EXTENSION_REQ_COOLDOWN_HOURS = 24


def _parse_invitation_code_input(raw: str | None) -> str:
    """Normalize pasted invite URL or Invite ID to uppercase code (matches guest/tenant invite parsers)."""
    if not raw:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    low = s.lower()
    if "#demo/invite/" in low:
        s = s.split("#demo/invite/", 1)[-1]
    elif "#invite/" in s:
        s = s.split("#invite/", 1)[-1]
    elif "/demo/invite/" in low:
        s = s.split("demo/invite/", 1)[-1]
    elif "/invite/" in low:
        s = s.split("invite/", 1)[-1]
    s = s.split("?", 1)[0].split("#", 1)[0].strip()
    return s.upper()


def _guest_invite_frontend_url(invitation_code: str, *, is_demo: bool = False) -> str:
    settings = get_settings()
    base = (settings.stripe_identity_return_url or settings.frontend_base_url or "http://localhost:5173").strip().split("#")[0].rstrip("/")
    code = (invitation_code or "").strip().upper()
    if not code:
        return base
    return f"{base}/#demo/invite/{code}" if is_demo else f"{base}/#invite/{code}"


def _guest_extension_request_to_view(db: Session, row: GuestExtensionRequest) -> TenantGuestExtensionRequestView | None:
    stay = db.query(Stay).filter(Stay.id == row.stay_id).first()
    if not stay:
        return None
    prop = db.query(Property).filter(Property.id == row.property_id).first()
    guest_u = db.query(User).filter(User.id == row.guest_user_id).first()
    property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop and (prop.city or prop.state) else None) or "Property"
    guest_name = ((guest_u.full_name or "").strip() or (guest_u.email or "").strip() or "Guest") if guest_u else "Guest"
    guest_email = (guest_u.email or "").strip() if guest_u else ""
    unit_id = getattr(stay, "unit_id", None)
    unit_label = None
    if unit_id:
        ur = db.query(Unit).filter(Unit.id == unit_id).first()
        if ur:
            unit_label = ur.unit_label
    return TenantGuestExtensionRequestView(
        id=row.id,
        stay_id=row.stay_id,
        property_id=row.property_id,
        property_name=property_name,
        unit_id=unit_id,
        unit_label=unit_label,
        guest_name=guest_name,
        guest_email=guest_email,
        stay_start_date=stay.stay_start_date,
        stay_end_date=stay.stay_end_date,
        message=row.message,
        status=row.status,
        created_at=row.created_at,
        responded_at=row.responded_at,
        tenant_note=row.tenant_note,
    )


@router.get("/tenant/guest-extension-requests", response_model=list[TenantGuestExtensionRequestView])
def tenant_list_guest_extension_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
    pending_only: bool = False,
):
    """Tenant: list guest extension requests you need to answer or have answered (newest first; pending at top)."""
    q = db.query(GuestExtensionRequest).filter(GuestExtensionRequest.tenant_user_id == current_user.id)
    if pending_only:
        q = q.filter(GuestExtensionRequest.status == "pending")
    rows = (
        q.order_by(
            case((GuestExtensionRequest.status == "pending", 0), else_=1),
            GuestExtensionRequest.created_at.desc(),
        )
        .limit(100)
        .all()
    )
    out: list[TenantGuestExtensionRequestView] = []
    for r in rows:
        v = _guest_extension_request_to_view(db, r)
        if v:
            out.append(v)
    return out


@router.post("/guest/stays/{stay_id}/request-extension")
def guest_request_stay_extension(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest_or_tenant),
    payload: GuestExtensionRequestBody = Body(default_factory=GuestExtensionRequestBody),
):
    """Tenant-invited guests only: notify the inviter (tenant) that they are interested in a longer stay. Owner/PM are not notified."""
    stay = db.query(Stay).filter(Stay.id == stay_id, Stay.guest_id == current_user.id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    if not is_tenant_lane_stay(db, stay):
        raise HTTPException(status_code=403, detail="Extension requests are only available when you were invited by a resident on DocuStay.")
    if not getattr(stay, "checked_in_at", None):
        raise HTTPException(status_code=400, detail="Check in before requesting an extension.")
    if getattr(stay, "checked_out_at", None) or getattr(stay, "cancelled_at", None):
        raise HTTPException(status_code=400, detail="This stay is no longer active.")
    if getattr(stay, "revoked_at", None):
        raise HTTPException(status_code=400, detail="Authorization was revoked; you cannot request an extension for this stay.")

    pending_ext = (
        db.query(GuestExtensionRequest)
        .filter(GuestExtensionRequest.stay_id == stay.id, GuestExtensionRequest.status == "pending")
        .first()
    )
    if pending_ext:
        raise HTTPException(
            status_code=409,
            detail="Your host has not responded to your extension request yet.",
        )

    since = datetime.now(timezone.utc) - timedelta(hours=_EXTENSION_REQ_COOLDOWN_HOURS)
    recent = (
        db.query(AuditLog)
        .filter(
            AuditLog.stay_id == stay.id,
            AuditLog.title == _EXTENSION_REQ_LOG_TITLE,
            AuditLog.created_at >= since,
        )
        .first()
    )
    if recent:
        raise HTTPException(
            status_code=429,
            detail="You already sent an extension request recently. You can send another after 24 hours.",
        )

    inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first() if getattr(stay, "invitation_id", None) else None
    tenant_uid = getattr(stay, "invited_by_user_id", None) or (getattr(inv, "invited_by_user_id", None) if inv else None)
    tenant = db.query(User).filter(User.id == tenant_uid).first() if tenant_uid else None
    tenant_email = (tenant.email or "").strip() if tenant else ""
    if not tenant_uid or not tenant_email:
        raise HTTPException(status_code=400, detail="Could not reach your host on file. Please contact them directly.")

    prop = db.query(Property).filter(Property.id == stay.property_id).first()
    property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop and (prop.city or prop.state) else None) or "Property"
    guest_name = (current_user.full_name or "").strip() or (current_user.email or "").strip() or "Guest"
    start_s = stay.stay_start_date.isoformat()
    end_s = stay.stay_end_date.isoformat()
    note = (payload.message or "").strip() or None

    ext_row = GuestExtensionRequest(
        stay_id=stay.id,
        property_id=stay.property_id,
        guest_user_id=current_user.id,
        tenant_user_id=tenant_uid,
        message=note,
        status="pending",
    )
    db.add(ext_row)
    db.flush()

    if tenant_email:
        try:
            send_guest_extension_request_to_tenant_email(
                tenant_email, guest_name, property_name, start_s, end_s, guest_note=note
            )
        except Exception:
            logger.exception("guest_request_stay_extension: failed to send email to tenant")

    create_alert_for_user(
        db,
        tenant_uid,
        "guest_extension_request",
        "Guest asked about extending their stay",
        f"{guest_name} at {property_name} ({start_s} to {end_s}) would like a longer stay. Open Guest extension requests on your dashboard to approve or decline.",
        severity="info",
        property_id=stay.property_id,
        stay_id=stay.id,
        invitation_id=getattr(stay, "invitation_id", None),
        meta={"guest_user_id": current_user.id, "stay_id": stay.id, "extension_request_id": ext_row.id},
    )
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    ext_meta = {
        "tenant_user_id": tenant_uid,
        "guest_user_id": current_user.id,
        "stay_start": start_s,
        "stay_end": end_s,
        "extension_request_id": ext_row.id,
    }
    if note:
        ext_meta["guest_note"] = note
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        _EXTENSION_REQ_LOG_TITLE,
        f"Stay {stay.id}: guest {guest_name} requested extension; tenant {tenant_uid} notified (email + in-app).",
        property_id=stay.property_id,
        stay_id=stay.id,
        invitation_id=getattr(stay, "invitation_id", None),
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta=ext_meta,
    )
    create_ledger_event(
        db,
        ACTION_GUEST_EXTENSION_REQUESTED,
        target_object_type="Stay",
        target_object_id=stay.id,
        property_id=stay.property_id,
        stay_id=stay.id,
        invitation_id=getattr(stay, "invitation_id", None),
        actor_user_id=current_user.id,
        meta={
            "message": f"{guest_name} requested a longer stay ({start_s} to {end_s}).",
            "property_name": property_name,
            "guest_note": note,
            "extension_request_id": ext_row.id,
        },
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()
    return {"status": "success", "message": "Your host has been notified."}


@router.post("/tenant/guest-extension-requests/{request_id}/approve")
def tenant_approve_guest_extension(
    request: Request,
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
    body: TenantApproveExtensionBody = Body(...),
):
    """Tenant: approve with the new extension invitation; guest email includes the invite link and new dates."""
    row = db.query(GuestExtensionRequest).filter(GuestExtensionRequest.id == request_id).first()
    if not row or row.tenant_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Request not found")
    if row.status != "pending":
        raise HTTPException(status_code=400, detail="This request has already been answered.")

    stay = db.query(Stay).filter(Stay.id == row.stay_id).first()
    guest_u = db.query(User).filter(User.id == row.guest_user_id).first()
    prop = db.query(Property).filter(Property.id == row.property_id).first()
    property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop and (prop.city or prop.state) else None) or "Property"
    guest_email = (guest_u.email or "").strip() if guest_u else ""
    current_start_s = stay.stay_start_date.isoformat() if stay else ""
    current_end_s = stay.stay_end_date.isoformat() if stay else ""

    code = _parse_invitation_code_input(body.invitation_code)
    if not code:
        raise HTTPException(status_code=400, detail="Invitation code or link is required.")
    inv = db.query(Invitation).filter(Invitation.invitation_code == code).first()
    if not inv:
        raise HTTPException(status_code=404, detail="No invitation found for that Invite ID or link.")
    if (inv.invited_by_user_id or 0) != current_user.id:
        raise HTTPException(status_code=403, detail="You did not create this invitation.")
    if inv.property_id != row.property_id:
        raise HTTPException(status_code=400, detail="This invitation is for a different property than the guest's stay.")
    if stay and getattr(stay, "unit_id", None) and getattr(inv, "unit_id", None) and stay.unit_id != inv.unit_id:
        raise HTTPException(status_code=400, detail="This invitation is for a different unit than the guest's current stay.")
    if (inv.invitation_kind or "guest") != "guest":
        raise HTTPException(status_code=400, detail="Only a guest invitation can be used for a stay extension.")
    if (inv.token_state or "").upper() != "STAGED":
        raise HTTPException(
            status_code=400,
            detail="That invitation is not still pending (it may already be accepted). Create a new guest invitation with the extension dates.",
        )
    inv_guest_email = (inv.guest_email or "").strip().lower()
    guest_email_lower = (guest_u.email or "").strip().lower() if guest_u else ""
    if not inv_guest_email:
        raise HTTPException(status_code=400, detail="That invitation has no guest email. Recreate it using the same email as this guest.")
    if guest_email_lower and inv_guest_email != guest_email_lower:
        raise HTTPException(status_code=400, detail="This invitation is addressed to a different email than this guest's account.")

    row.status = "approved"
    row.responded_at = datetime.now(timezone.utc)
    row.tenant_note = (body.message or "").strip() or None
    db.add(row)

    new_start_s = inv.stay_start_date.isoformat()
    new_end_s = inv.stay_end_date.isoformat()
    invite_url = _guest_invite_frontend_url(
        inv.invitation_code,
        is_demo=is_demo_user_id(db, getattr(inv, "invited_by_user_id", None) or getattr(inv, "owner_id", None)),
    )

    if guest_email and stay:
        try:
            send_guest_extension_approved_email(
                guest_email,
                property_name,
                current_stay_start=current_start_s,
                current_stay_end=current_end_s,
                new_stay_start=new_start_s,
                new_stay_end=new_end_s,
                invite_url=invite_url,
                invitation_code=inv.invitation_code,
                host_note=row.tenant_note,
            )
        except Exception:
            logger.exception("tenant_approve_guest_extension: email to guest failed")

    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Guest extension request approved",
        f"Extension request {row.id}: tenant approved with new invitation {inv.invitation_code}; guest notified with link.",
        property_id=row.property_id,
        stay_id=row.stay_id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={
            "extension_request_id": row.id,
            "guest_user_id": row.guest_user_id,
            "new_invitation_id": inv.id,
            "new_invitation_code": inv.invitation_code,
        },
    )
    create_ledger_event(
        db,
        ACTION_GUEST_EXTENSION_APPROVED,
        target_object_type="GuestExtensionRequest",
        target_object_id=row.id,
        property_id=row.property_id,
        stay_id=row.stay_id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        meta={
            "message": f"Approved stay extension request (stay {row.stay_id}); new invite {inv.invitation_code}.",
            "property_name": property_name,
            "new_invitation_code": inv.invitation_code,
        },
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()
    return {"status": "success", "message": "The guest has been emailed with the new invitation link."}


@router.post("/tenant/guest-extension-requests/{request_id}/decline")
def tenant_decline_guest_extension(
    request: Request,
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
    body: TenantExtensionDecisionBody = Body(default_factory=TenantExtensionDecisionBody),
):
    """Tenant: decline a guest's extension request and notify the guest."""
    row = db.query(GuestExtensionRequest).filter(GuestExtensionRequest.id == request_id).first()
    if not row or row.tenant_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Request not found")
    if row.status != "pending":
        raise HTTPException(status_code=400, detail="This request has already been answered.")

    stay = db.query(Stay).filter(Stay.id == row.stay_id).first()
    guest_u = db.query(User).filter(User.id == row.guest_user_id).first()
    prop = db.query(Property).filter(Property.id == row.property_id).first()
    property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop and (prop.city or prop.state) else None) or "Property"
    guest_email = (guest_u.email or "").strip() if guest_u else ""
    start_s = stay.stay_start_date.isoformat() if stay else ""
    end_s = stay.stay_end_date.isoformat() if stay else ""

    row.status = "declined"
    row.responded_at = datetime.now(timezone.utc)
    row.tenant_note = (body.message or "").strip() or None
    db.add(row)

    if guest_email and stay:
        try:
            send_guest_extension_declined_email(
                guest_email,
                property_name,
                start_s,
                end_s,
                host_note=row.tenant_note,
            )
        except Exception:
            logger.exception("tenant_decline_guest_extension: email to guest failed")

    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Guest extension request declined",
        f"Extension request {row.id}: tenant declined; guest notified.",
        property_id=row.property_id,
        stay_id=row.stay_id,
        invitation_id=getattr(stay, "invitation_id", None) if stay else None,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"extension_request_id": row.id, "guest_user_id": row.guest_user_id},
    )
    create_ledger_event(
        db,
        ACTION_GUEST_EXTENSION_DECLINED,
        target_object_type="GuestExtensionRequest",
        target_object_id=row.id,
        property_id=row.property_id,
        stay_id=row.stay_id,
        invitation_id=getattr(stay, "invitation_id", None) if stay else None,
        actor_user_id=current_user.id,
        meta={
            "message": f"Declined stay extension request (stay {row.stay_id}).",
            "property_name": property_name,
        },
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()
    return {"status": "success", "message": "The guest has been notified."}


@router.get("/tenant/debug")
def tenant_debug(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """Diagnostic: counts of TenantAssignments and Stays for the current user. Helps verify data exists after accept-invite."""
    today = date.today()
    ta_count = db.query(TenantAssignment).filter(
        TenantAssignment.user_id == current_user.id,
        (TenantAssignment.end_date.is_(None)) | (TenantAssignment.end_date >= today),
    ).count()
    stays_count = db.query(Stay).filter(Stay.guest_id == current_user.id).count()
    return {"tenant_assignments_count": ta_count, "stays_count": stays_count}


def _lease_cohort_context_for_assignment(
    db: Session, ta: TenantAssignment, current_user: "User"
) -> tuple[str | None, list[dict], int]:
    all_on_unit = db.query(TenantAssignment).filter(TenantAssignment.unit_id == ta.unit_id).all()
    cmap = map_assignment_id_to_cohort_key(all_on_unit)
    ck = cmap.get(ta.id)
    peers: list[dict] = []
    if ck:
        for o in all_on_unit:
            if o.user_id == current_user.id or cmap.get(o.id) != ck:
                continue
            u = db.query(User).filter(User.id == o.user_id).first()
            peers.append({
                "name": label_from_user_id(db, o.user_id) or ((u.email or "").strip() if u else "Tenant"),
                "email": (u.email or "").strip() if u else None,
            })
    member_count = sum(1 for o in all_on_unit if cmap.get(o.id) == ck) if ck else 1
    return ck, peers, member_count


def _lease_cohort_context_for_pending_invitation(
    db: Session, inv: Invitation, current_user: "User"
) -> tuple[str | None, list[dict], int]:
    from app.services.tenant_lease_cohort import date_ranges_overlap

    all_on_unit = db.query(TenantAssignment).filter(TenantAssignment.unit_id == inv.unit_id).all()
    peers: list[dict] = []
    if inv.stay_start_date:
        for o in all_on_unit:
            if not date_ranges_overlap(inv.stay_start_date, inv.stay_end_date, o.start_date, o.end_date):
                continue
            u = db.query(User).filter(User.id == o.user_id).first()
            peers.append({
                "name": label_from_user_id(db, o.user_id) or ((u.email or "").strip() if u else "Tenant"),
                "email": (u.email or "").strip() if u else None,
            })
    ck = cohort_key_for_pending_invitation(inv, all_on_unit)
    member_count = max(len(peers) + 1, 1)
    return ck, peers, member_count


def _tenant_property_transfer_notice(
    db: Session,
    prop: Property | None,
    relationship_started_at: datetime | None,
) -> str | None:
    """When the tenant's lease row predates a completed ownership transfer, explain current owner of record."""
    if not prop or not relationship_started_at:
        return None
    pti = (
        db.query(PropertyTransferInvitation)
        .filter(
            PropertyTransferInvitation.property_id == prop.id,
            PropertyTransferInvitation.status == "accepted",
            PropertyTransferInvitation.accepted_at.isnot(None),
        )
        .order_by(PropertyTransferInvitation.accepted_at.desc())
        .first()
    )
    if not pti or not pti.accepted_at:
        return None
    rs = relationship_started_at
    aa = pti.accepted_at
    if getattr(rs, "tzinfo", None) is None:
        rs = rs.replace(tzinfo=timezone.utc)
    if getattr(aa, "tzinfo", None) is None:
        aa = aa.replace(tzinfo=timezone.utc)
    if rs >= aa:
        return None
    op = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
    if not op:
        return None
    nu = db.query(User).filter(User.id == op.user_id).first()
    if not nu:
        return None
    label = ((nu.full_name or "").strip() or (nu.email or "").strip() or "the new owner")
    return f"The property was transferred to {label}."


def _tenant_unit_item(db: Session, ta: TenantAssignment, current_user: "User") -> dict:
    """Build one unit item for tenant_unit response. Use invitation accepted by THIS user (match guest_email) to avoid showing another tenant's dates."""
    unit = db.query(Unit).filter(Unit.id == ta.unit_id).first()
    if not unit:
        return {
            "unit": None, "property": None, "invite_id": None, "token_state": None,
            "stay_start_date": ta.start_date.isoformat() if ta.start_date else None,
            "stay_end_date": ta.end_date.isoformat() if ta.end_date else None,
            "live_slug": None, "region_code": None,
            "jurisdiction_state_name": None, "jurisdiction_statutes": [],
            "removal_guest_text": None, "removal_tenant_text": None,
            "assigned_by_name": None, "accepted_by_name": (getattr(current_user, "full_name", None) or "").strip() or (current_user.email or ""),
            "dead_mans_switch_enabled": True,
            "lease_cohort_id": None,
            "cohort_member_count": 1,
            "co_tenants": [],
            "property_deleted_at": None,
            "property_owner_transfer_notice": None,
        }
    prop = db.query(Property).filter(Property.id == unit.property_id).first()
    address = ", ".join(filter(None, [prop.street, prop.city, prop.state])) if prop else ""
    user_email = (current_user.email or "").strip().lower()
    tenant_inv = find_invitation_matching_tenant_assignment(
        db, ta, user_email_lower=user_email or None
    )
    invite_id = tenant_inv.invitation_code if tenant_inv else None
    token_state = getattr(tenant_inv, "token_state", None) if tenant_inv else None
    stay_start = (tenant_inv.stay_start_date if tenant_inv else ta.start_date)
    stay_end = (tenant_inv.stay_end_date if tenant_inv else ta.end_date)
    live_slug = getattr(prop, "live_slug", None) if prop else None
    region_code = getattr(prop, "region_code", None) if prop else None
    jurisdiction_state_name = None
    jurisdiction_statutes = []
    removal_guest_text = None
    removal_tenant_text = None
    if prop:
        jinfo = get_jurisdiction_for_property(db, getattr(prop, "zip_code", None), region_code)
        if jinfo is not None:
            jurisdiction_state_name = jinfo.name
            jurisdiction_statutes = [JurisdictionStatuteInDashboard(citation=st.citation, plain_english=st.plain_english) for st in jinfo.statutes]
            removal_guest_text = jinfo.removal_guest_text
            removal_tenant_text = jinfo.removal_tenant_text
    assigned_by_name = get_actor_display_name(db, getattr(tenant_inv, "invited_by_user_id", None)) if tenant_inv else None
    accepted_by_name = (getattr(current_user, "full_name", None) or "").strip() or (current_user.email or "")
    latest_tenant_guest_inv = (
        db.query(Invitation)
        .filter(
            Invitation.unit_id == ta.unit_id,
            Invitation.invitation_kind == "guest",
            Invitation.invited_by_user_id == current_user.id,
        )
        .order_by(Invitation.created_at.desc())
        .first()
    )
    dms_enabled = bool(
        getattr(latest_tenant_guest_inv, "dead_mans_switch_enabled", None)
        if latest_tenant_guest_inv is not None
        else (getattr(tenant_inv, "dead_mans_switch_enabled", 1) if tenant_inv else 1)
    )
    lease_cohort_id, co_tenants, cohort_member_count = _lease_cohort_context_for_assignment(db, ta, current_user)
    p_del = getattr(prop, "deleted_at", None) if prop else None
    transfer_notice = _tenant_property_transfer_notice(db, prop, getattr(ta, "created_at", None))
    return {
        "unit": {
            "id": unit.id,
            "unit_label": unit.unit_label,
            "occupancy_status": get_unit_display_occupancy_status(db, unit),
        }
        if unit
        else None,
        "property": {"id": prop.id, "name": prop.name, "address": address} if prop else None,
        "invite_id": invite_id,
        "token_state": token_state,
        "stay_start_date": stay_start.isoformat() if stay_start else None,
        "stay_end_date": stay_end.isoformat() if stay_end else None,
        "live_slug": live_slug,
        "region_code": region_code,
        "jurisdiction_state_name": jurisdiction_state_name,
        "jurisdiction_statutes": jurisdiction_statutes,
        "removal_guest_text": removal_guest_text,
        "removal_tenant_text": removal_tenant_text,
        "assigned_by_name": assigned_by_name,
        "accepted_by_name": accepted_by_name,
        "dead_mans_switch_enabled": dms_enabled,
        "lease_cohort_id": lease_cohort_id,
        "cohort_member_count": cohort_member_count,
        "co_tenants": co_tenants,
        "property_deleted_at": p_del.isoformat() if p_del else None,
        "property_owner_transfer_notice": transfer_notice,
    }


def _tenant_unit_item_from_invitation(db: Session, inv: Invitation, current_user: "User") -> dict | None:
    """Build unit item from a tenant invitation (for pending invitations addressed to this tenant)."""
    if not inv.unit_id:
        return None
    unit = db.query(Unit).filter(Unit.id == inv.unit_id).first()
    if not unit:
        return None
    prop = db.query(Property).filter(Property.id == inv.property_id).first()
    if not prop:
        return None
    address = ", ".join(filter(None, [getattr(prop, "street", None), prop.city, prop.state])) if prop else ""
    region_code = getattr(prop, "region_code", None) or "US"
    jinfo = get_jurisdiction_for_property(db, getattr(prop, "zip_code", None), region_code)
    jurisdiction_statutes = [JurisdictionStatuteInDashboard(citation=st.citation, plain_english=st.plain_english) for st in jinfo.statutes] if jinfo and jinfo.statutes else []
    assigned_by_name = get_actor_display_name(db, getattr(inv, "invited_by_user_id", None))
    accepted_by_name = (getattr(current_user, "full_name", None) or "").strip() or (current_user.email or "") if current_user else None
    lease_cohort_id, co_tenants, cohort_member_count = _lease_cohort_context_for_pending_invitation(db, inv, current_user)
    p_del = getattr(prop, "deleted_at", None)
    transfer_notice = _tenant_property_transfer_notice(db, prop, getattr(inv, "created_at", None))
    return {
        "unit": {"id": unit.id, "unit_label": unit.unit_label, "occupancy_status": get_unit_display_occupancy_status(db, unit)},
        "property": {"id": prop.id, "name": prop.name, "address": address},
        "invite_id": inv.invitation_code,
        "token_state": getattr(inv, "token_state", None) or "STAGED",
        "stay_start_date": inv.stay_start_date.isoformat() if inv.stay_start_date else None,
        "stay_end_date": inv.stay_end_date.isoformat() if inv.stay_end_date else None,
        "live_slug": getattr(prop, "live_slug", None),
        "region_code": region_code,
        "jurisdiction_state_name": jinfo.name if jinfo else None,
        "jurisdiction_statutes": jurisdiction_statutes,
        "removal_guest_text": jinfo.removal_guest_text if jinfo else None,
        "removal_tenant_text": jinfo.removal_tenant_text if jinfo else None,
        "pending_acceptance": True,
        "assigned_by_name": assigned_by_name,
        "accepted_by_name": accepted_by_name,
        "dead_mans_switch_enabled": bool(getattr(inv, "dead_mans_switch_enabled", 1)),
        "lease_cohort_id": lease_cohort_id,
        "cohort_member_count": cohort_member_count,
        "co_tenants": co_tenants,
        "property_deleted_at": p_del.isoformat() if p_del else None,
        "property_owner_transfer_notice": transfer_notice,
    }


# Max units/stays to return for tenant dashboard (show all; no artificial cap of 2).
_TENANT_UNIT_LIMIT = 500
_GUEST_STAYS_LIMIT = 500


@router.get("/tenant/unit")
def tenant_unit(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """Return all of the tenant's assigned units plus pending tenant invitations addressed to them. Only filter: user_id (tenant id). No limit—all assignments are returned (up to _TENANT_UNIT_LIMIT)."""
    assignments = (
        db.query(TenantAssignment)
        .join(Unit)
        .filter(TenantAssignment.user_id == current_user.id)
        .order_by(TenantAssignment.start_date.desc())
        .limit(_TENANT_UNIT_LIMIT)
        .all()
    )
    units = [_tenant_unit_item(db, ta, current_user) for ta in assignments]
    user_email = (current_user.email or "").strip().lower()
    if user_email:
        pending_invs = (
            db.query(Invitation)
            .filter(
                Invitation.invitation_kind.in_(tuple(TENANT_UNIT_LEASE_KINDS)),
                Invitation.unit_id.isnot(None),
                Invitation.status.in_(["pending", "ongoing", "accepted"]),
                func.lower(func.coalesce(Invitation.guest_email, "")) == user_email,
            )
            .order_by(Invitation.created_at.desc())
            .all()
        )
        for inv in pending_invs:
            token = (getattr(inv, "token_state", None) or "").upper()
            if token in ("CANCELLED", "REVOKED", "EXPIRED"):
                continue
            if find_tenant_assignment_matching_invitation(db, current_user.id, inv):
                continue
            item = _tenant_unit_item_from_invitation(db, inv, current_user)
            if item:
                units.append(item)
    return {"units": units}


@router.post("/tenant/dead-mans-switch")
def tenant_set_dead_mans_switch(
    request: Request,
    data: TenantDeadMansSwitchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    # """Tenant can toggle Dead Man's Switch preference for an assigned unit/property."""
    """Tenant can toggle stay end reminder (Status Confirmation) preference for an assigned unit/property."""
    unit_id = data.unit_id
    if not can_perform_action(db, current_user, Action.INVITE_GUEST, unit_id=unit_id, mode="business"):
        # raise HTTPException(status_code=403, detail="You do not have access to change Dead Man's Switch for this unit.")
        raise HTTPException(status_code=403, detail="You do not have access to change stay end reminders for this unit.")
    ta = (
        db.query(TenantAssignment)
        .filter(TenantAssignment.user_id == current_user.id, TenantAssignment.unit_id == unit_id)
        .order_by(TenantAssignment.start_date.desc())
        .first()
    )
    if not ta:
        raise HTTPException(status_code=404, detail="No assignment found for this unit.")
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    prop = db.query(Property).filter(Property.id == unit.property_id).first() if unit else None
    if not unit or not prop or getattr(prop, "deleted_at", None):
        raise HTTPException(status_code=404, detail="Property or unit not found.")

    new_val = 1 if data.dead_mans_switch_enabled else 0
    updated_count = 0

    # Persist preference on the tenant-assignment invitation (if exists).
    user_email = (current_user.email or "").strip().lower()
    tenant_inv = (
        db.query(Invitation)
        .filter(
            Invitation.unit_id == unit_id,
            Invitation.invitation_kind.in_(tuple(TENANT_UNIT_LEASE_KINDS)),
            func.lower(func.coalesce(Invitation.guest_email, "")) == user_email,
        )
        .order_by(Invitation.created_at.desc())
        .first()
    )
    if tenant_inv and (getattr(tenant_inv, "dead_mans_switch_enabled", 1) or 0) != new_val:
        tenant_inv.dead_mans_switch_enabled = new_val
        db.add(tenant_inv)
        updated_count += 1

    # Also apply to active/pending guest invitations created by this tenant for this unit.
    guest_invs = (
        db.query(Invitation)
        .filter(
            Invitation.unit_id == unit_id,
            Invitation.invitation_kind == "guest",
            Invitation.invited_by_user_id == current_user.id,
            Invitation.status.in_(["pending", "ongoing", "accepted"]),
        )
        .all()
    )
    for inv in guest_invs:
        token_state = (getattr(inv, "token_state", None) or "STAGED").upper()
        if token_state in ("CANCELLED", "REVOKED", "EXPIRED"):
            continue
        if (getattr(inv, "dead_mans_switch_enabled", 1) or 0) != new_val:
            inv.dead_mans_switch_enabled = new_val
            db.add(inv)
            updated_count += 1

    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else f"Property {prop.id}")
    # title = "Dead Man's Switch turned on" if new_val == 1 else "Dead Man's Switch turned off"
    # msg = f"Tenant turned {'on' if new_val == 1 else 'off'} Dead Man's Switch for {property_name} (unit {unit.unit_label})."
    title = "Stay end reminders turned on" if new_val == 1 else "Stay end reminders turned off"
    msg = f"Tenant turned {'on' if new_val == 1 else 'off'} stay end reminders for {property_name} (unit {unit.unit_label})."
    create_log(
        db,
        CATEGORY_DEAD_MANS_SWITCH,
        title,
        msg,
        property_id=prop.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"unit_id": unit_id, "dead_mans_switch_enabled": bool(new_val), "updated_count": updated_count},
    )
    # Use DMSDisabled ledger action when turning off; keep status_change action when turning on.
    create_ledger_event(
        db,
        ACTION_DMS_DISABLED if new_val == 0 else ACTION_PROPERTY_UPDATED,
        target_object_type="Property",
        target_object_id=prop.id,
        property_id=prop.id,
        unit_id=unit_id,
        actor_user_id=current_user.id,
        meta={
            "property_name": property_name,
            "unit_id": unit_id,
            "dead_mans_switch_enabled": bool(new_val),
            "message": msg,
        },
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()
    return {
        "status": "success",
        "dead_mans_switch_enabled": bool(new_val),
        "updated_count": updated_count,
        # "message": f"Dead Man's Switch turned {'on' if new_val == 1 else 'off'} for this property.",
        "message": f"Stay end reminders turned {'on' if new_val == 1 else 'off'} for this property.",
    }


@router.post("/tenant/cancel-future-assignment")
def tenant_cancel_future_assignment(
    request: Request,
    unit_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """Let the tenant cancel their future unit assignment (effective before start date). Pass unit_id to cancel a specific assignment when tenant has multiple."""
    today = date.today()
    q = (
        db.query(TenantAssignment)
        .join(Unit)
        .filter(TenantAssignment.user_id == current_user.id)
    )
    if unit_id is not None:
        q = q.filter(TenantAssignment.unit_id == unit_id)
    ta = q.order_by(TenantAssignment.start_date.desc()).first()
    if not ta:
        raise HTTPException(status_code=404, detail="No assignment found")
    # Use same "effective" start as tenant unit display: invitation stay_start if present, else assignment start_date
    tenant_inv = find_invitation_matching_tenant_assignment(
        db, ta, user_email_lower=(current_user.email or "").strip().lower() or None
    )
    effective_start = tenant_inv.stay_start_date if tenant_inv else ta.start_date
    if effective_start <= today:
        raise HTTPException(
            status_code=400,
            detail="Only future assignments can be cancelled. Your stay has already started.",
        )
    original_start = effective_start
    ta.end_date = original_start - timedelta(days=1)
    db.add(ta)
    db.flush()
    # Mark the tenant invitation as cancelled (tenant self-cancel; DocuStay does not revoke tenants)
    invite_code = None
    if tenant_inv:
        invite_code = tenant_inv.invitation_code
        tenant_inv.token_state = "CANCELLED"
        db.add(tenant_inv)
    unit = db.query(Unit).filter(Unit.id == ta.unit_id).first()
    prop = db.query(Property).filter(Property.id == unit.property_id).first() if unit else None
    occ_prev = None
    if unit:
        occ_prev = getattr(unit, "occupancy_status", None) or OccupancyStatus.vacant.value
        unit.occupancy_status = OccupancyStatus.vacant.value
        db.add(unit)
    if prop:
        prop.occupancy_status = OccupancyStatus.vacant.value
        db.add(prop)
        occ_prev = occ_prev or getattr(prop, "occupancy_status", None)
    db.commit()
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    log_message = (
        f"Tenant cancelled future assignment (unit_id={ta.unit_id}, original start {original_start.isoformat()})."
        + (f" Invite ID {invite_code} token_state -> CANCELLED." if invite_code else "")
        + (f" Occupancy -> vacant." if occ_prev else "")
    )
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Tenant cancelled future assignment",
        log_message,
        property_id=prop.id if prop else None,
        stay_id=None,
        invitation_id=tenant_inv.id if tenant_inv else None,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"original_start_date": str(original_start), "unit_id": ta.unit_id},
    )
    if prop:
        create_ledger_event(
            db,
            ACTION_TENANT_ASSIGNMENT_CANCELLED,
            target_object_type="TenantAssignment",
            target_object_id=ta.id,
            property_id=prop.id,
            unit_id=ta.unit_id,
            invitation_id=tenant_inv.id if tenant_inv else None,
            actor_user_id=current_user.id,
            meta={"message": log_message, "unit_id": ta.unit_id, "tenant_email": current_user.email},
            ip_address=ip,
            user_agent=ua,
        )
    db.commit()
    return {"status": "success", "message": "Future stay cancelled."}


@router.post("/tenant/end-assignment")
def tenant_end_assignment(
    request: Request,
    unit_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """Let the tenant end their ongoing assignment (checkout): set end_date to today. Pass unit_id when tenant has multiple assignments."""
    today = date.today()
    q = (
        db.query(TenantAssignment)
        .join(Unit)
        .filter(TenantAssignment.user_id == current_user.id)
    )
    if unit_id is not None:
        q = q.filter(TenantAssignment.unit_id == unit_id)
    ta = q.order_by(TenantAssignment.start_date.desc()).first()
    if not ta:
        raise HTTPException(status_code=404, detail="No assignment found")
    if ta.start_date > today:
        raise HTTPException(status_code=400, detail="Your stay has not started yet. You can cancel it instead.")
    if ta.end_date is not None and ta.end_date < today:
        raise HTTPException(status_code=400, detail="This assignment has already ended.")
    ta.end_date = today
    db.add(ta)
    db.flush()
    unit = db.query(Unit).filter(Unit.id == ta.unit_id).first()
    prop = db.query(Property).filter(Property.id == unit.property_id).first() if unit else None
    if unit:
        unit.occupancy_status = OccupancyStatus.vacant.value
        db.add(unit)
    if prop:
        prop.occupancy_status = OccupancyStatus.vacant.value
        db.add(prop)
    db.commit()
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Tenant ended assignment (checkout)",
        f"Tenant ended assignment (unit_id={ta.unit_id}, end_date set to {today.isoformat()}). Unit/property set to vacant.",
        property_id=prop.id if prop else None,
        stay_id=None,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"unit_id": ta.unit_id, "end_date": str(today)},
    )
    create_ledger_event(
        db,
        ACTION_TENANT_CHECK_OUT,
        property_id=prop.id if prop else None,
        unit_id=ta.unit_id,
        actor_user_id=current_user.id,
        ip_address=ip,
        user_agent=ua,
        meta={
            "message": f"Tenant ended assignment (unit_id={ta.unit_id}, end_date set to {today.isoformat()}). Unit/property set to vacant.",
            "unit_id": ta.unit_id,
            "end_date": str(today),
        },
    )
    db.commit()
    return {"status": "success", "message": "Checkout complete. Your stay has ended."}


def _parse_date(s: str) -> date | None:
    """Parse date from YYYY-MM-DD or MM/DD/YYYY. Returns None if invalid."""
    if not s or not s.strip():
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


@router.post("/tenant/invitations")
def tenant_create_invitation(
    request: Request,
    data: TenantGuestInvitationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """Create a guest invitation for the tenant's assigned unit only."""
    try:
        guest_name = (data.guest_name or "").strip()
        if not guest_name:
            raise HTTPException(status_code=400, detail="Guest name is required.")
        if not data.checkin_date or not data.checkout_date:
            raise HTTPException(status_code=400, detail="Start and end dates are required.")
        start = _parse_date(data.checkin_date)
        end = _parse_date(data.checkout_date)
        if not start:
            raise HTTPException(status_code=400, detail="Invalid start date. Use YYYY-MM-DD format.")
        if not end:
            raise HTTPException(status_code=400, detail="Invalid end date. Use YYYY-MM-DD format.")
        if end <= start:
            raise HTTPException(status_code=400, detail="End date must be after start date.")
        if start < effective_today_for_invite_start(request, client_calendar_date=data.client_calendar_date):
            raise HTTPException(status_code=400, detail="Authorization start date cannot be in the past.")

        unit_id = data.unit_id
        if not unit_id or unit_id <= 0:
            raise HTTPException(status_code=400, detail="Invalid unit. Please refresh the page and try again.")
        if not can_perform_action(db, current_user, Action.INVITE_GUEST, unit_id=unit_id, mode="business"):
            raise HTTPException(status_code=403, detail="You do not have access to invite guests for this unit.")

        unit = db.query(Unit).filter(Unit.id == unit_id).first()
        if not unit:
            raise HTTPException(status_code=404, detail="Unit not found.")
        prop = db.query(Property).filter(Property.id == unit.property_id).first()
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found.")
        if prop.deleted_at is not None:
            raise HTTPException(status_code=400, detail="Cannot create invitation for an inactive property.")

        ta = (
            db.query(TenantAssignment)
            .filter(TenantAssignment.unit_id == unit_id, TenantAssignment.user_id == current_user.id)
            .order_by(TenantAssignment.start_date.desc())
            .first()
        )
        if not ta:
            raise HTTPException(status_code=403, detail="You are not assigned to this unit.")
        # Use same effective stay dates as tenant_unit display (tenant invitation if available, else assignment)
        tenant_inv = find_invitation_matching_tenant_assignment(
            db, ta, user_email_lower=(current_user.email or "").strip().lower() or None
        )
        effective_start = tenant_inv.stay_start_date if tenant_inv else ta.start_date
        effective_end = tenant_inv.stay_end_date if tenant_inv else ta.end_date
        if start < effective_start:
            raise HTTPException(
                status_code=400,
                detail=f"Guest authorization start date cannot be before your stay starts ({effective_start.isoformat()}).",
            )
        if effective_end is not None and end > effective_end:
            raise HTTPException(
                status_code=400,
                detail=f"Guest authorization end date cannot be after your stay ends ({effective_end.isoformat()}).",
            )

        owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
        owner_user_id = owner_profile.user_id if owner_profile else None
        if not owner_user_id:
            raise HTTPException(status_code=500, detail="Property configuration error. Please contact support.")

        guest_email = (data.guest_email or "").strip().lower()
        if not guest_email:
            raise HTTPException(status_code=400, detail="Guest email is required.")
        from app.services.permissions import validate_invite_email_role
        role_err = validate_invite_email_role(db, guest_email, UserRole.guest)
        if role_err:
            raise HTTPException(status_code=409, detail=role_err)
        code = "INV-" + secrets.token_hex(4).upper()
        dms_pref = int(getattr(tenant_inv, "dead_mans_switch_enabled", 1) or 0) if tenant_inv else 1
        inv = Invitation(
            invitation_code=code,
            owner_id=owner_user_id,
            property_id=prop.id,
            unit_id=unit_id,
            invited_by_user_id=current_user.id,
            guest_name=guest_name,
            guest_email=guest_email,
            stay_start_date=start,
            stay_end_date=end,
            purpose_of_stay=PurposeOfStay.travel,
            relationship_to_owner=RelationshipToOwner.friend,
            region_code=prop.region_code or "US",
            status="pending",
            token_state="STAGED",
            invitation_kind="guest",
            dead_mans_switch_enabled=dms_pref,
            dead_mans_switch_alert_email=1,
            dead_mans_switch_alert_sms=0,
            dead_mans_switch_alert_dashboard=1,
            dead_mans_switch_alert_phone=0,
        )
        db.add(inv)
        db.commit()
        db.refresh(inv)

        ip = request.client.host if request.client else None
        ua = (request.headers.get("user-agent") or "").strip() or None
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            "Tenant guest invitation created",
            f"Tenant created guest invite {code} for unit {unit_id}, guest {guest_name}, {start}–{end}.",
            property_id=prop.id,
            invitation_id=inv.id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=ip,
            user_agent=ua,
            meta={"invitation_code": code, "token_state": "STAGED", "guest_name": guest_name},
        )
        create_ledger_event(
            db,
            ACTION_GUEST_INVITE_CREATED,
            target_object_type="Invitation",
            target_object_id=inv.id,
            property_id=prop.id,
            unit_id=unit_id,
            invitation_id=inv.id,
            actor_user_id=current_user.id,
            meta={
                "invitation_code": code,
                "token_state": "STAGED",
                "guest_name": guest_name,
                "stay_start_date": str(start),
                "stay_end_date": str(end),
                "invited_by_role": "tenant",
            },
            ip_address=ip,
            user_agent=ua,
        )
        db.commit()
        return {"invitation_code": code}
    except HTTPException:
        raise
    except Exception:
        logger.exception("tenant_create_invitation unexpected error")
        raise HTTPException(status_code=500, detail="Failed to create invitation. Please try again.")


@router.get("/tenant/invitations", response_model=list[OwnerInvitationView])
def tenant_invitations(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """List guest invitations created by this tenant (not tenant-lease invitations from other flows)."""
    invs = (
        db.query(Invitation)
        .filter(
            Invitation.invited_by_user_id == current_user.id,
            or_(Invitation.invitation_kind == "guest", Invitation.invitation_kind.is_(None)),
        )
        .order_by(Invitation.created_at.desc())
        .all()
    )
    threshold = get_invitation_expire_cutoff()
    out = []
    for inv in invs:
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
        has_pending_dropbox = db.query(AgreementSignature).filter(
            AgreementSignature.invitation_code == inv.invitation_code,
            AgreementSignature.dropbox_sign_request_id.isnot(None),
            AgreementSignature.signed_pdf_bytes.is_(None),
        ).first() is not None
        is_expired = (
            inv.status == "expired"
            or (
                inv.status == "pending"
                and inv.created_at is not None
                and inv.created_at < threshold
                and not has_pending_dropbox
                and not guest_invitation_signing_started(db, inv.invitation_code)
            )
        )
        stays_for_inv = db.query(Stay).filter(Stay.invitation_id == inv.id).all()
        active_stay = next(
            (
                s
                for s in stays_for_inv
                if s.revoked_at is None and s.checked_out_at is None and s.cancelled_at is None
            ),
            None,
        )
        any_stay = len(stays_for_inv) > 0
        all_stays_terminal = bool(any_stay and active_stay is None)
        token_state = (getattr(inv, "token_state", None) or "STAGED").upper()
        if inv.status == "cancelled":
            display_status = "cancelled"
        elif inv.status == "expired" or is_expired:
            display_status = "expired"
        elif active_stay is not None or inv.status == "ongoing":
            display_status = "active"
        elif all_stays_terminal:
            display_status = "expired"
        elif inv.status == "accepted" or (token_state == "BURNED" and inv.status == "pending"):
            display_status = "active"
        else:
            display_status = "pending"
        demo_flag = is_demo_user_id(db, getattr(inv, "invited_by_user_id", None) or getattr(inv, "owner_id", None))
        unit_label = _unit_label_if_multi_unit(db, inv.property_id, getattr(inv, "unit_id", None))
        out.append(
            OwnerInvitationView(
                id=inv.id,
                invitation_code=inv.invitation_code,
                property_id=inv.property_id,
                property_name=property_name,
                property_deleted_at=getattr(prop, "deleted_at", None) if prop else None,
                unit_label=unit_label,
                guest_name=inv.guest_name,
                guest_email=inv.guest_email,
                stay_start_date=inv.stay_start_date,
                stay_end_date=inv.stay_end_date,
                region_code=inv.region_code,
                status=display_status,
                token_state=getattr(inv, "token_state", None) or "STAGED",
                created_at=inv.created_at,
                is_expired=is_expired,
                is_demo=demo_flag,
            )
        )
    return out


@router.post("/tenant/invitations/{invitation_id}/resend")
def tenant_resend_invitation(
    invitation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """
    Fix Bug #5c: Re-send an expired guest invitation.
    Resets the created_at timestamp to 'now' so it's no longer expired.
    Only allowed for invitations created by this tenant.
    """
    inv = db.query(Invitation).filter(
        Invitation.id == invitation_id,
        Invitation.invited_by_user_id == current_user.id
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    if inv.status == "accepted" or (getattr(inv, "token_state", None) or "").upper() == "BURNED":
        raise HTTPException(status_code=400, detail="Invitation has already been accepted.")
    
    # Reset status and timestamp
    inv.status = "pending"
    inv.token_state = "STAGED"
    inv.created_at = datetime.now(timezone.utc)
    db.add(inv)
    
    # Log the resend
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Invitation re-sent",
        f"Tenant re-sent guest invite {inv.invitation_code}. Expiry timer reset.",
        property_id=inv.property_id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        meta={"invitation_code": inv.invitation_code, "action": "resend"}
    )
    
    db.commit()
    return {"status": "success", "message": "Invitation expiry reset. You can now share the link again."}


@router.get("/tenant/guest-history", response_model=list[OwnerStayView])
def tenant_guest_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """Stays for guests invited by this tenant (guest invitations only — not prior tenants' or tenant-lease invites)."""
    guest_inv_filter = (
        Invitation.invited_by_user_id == current_user.id,
        or_(Invitation.invitation_kind == "guest", Invitation.invitation_kind.is_(None)),
    )
    stays = (
        db.query(Stay)
        .join(Invitation, Stay.invitation_id == Invitation.id)
        .filter(*guest_inv_filter)
        .all()
    )
    out = []
    for s in stays:
        guest_name = label_for_stay(db, s)
        prop = db.query(Property).filter(Property.id == s.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
        rule = db.query(RegionRule).filter(RegionRule.region_code == s.region_code).first()
        jle = resolve_jurisdiction(db, JLEInput(region_code=s.region_code, stay_duration_days=s.intended_stay_duration_days, owner_occupied=True, property_type=None, guest_has_permanent_address=True))
        max_days = rule.max_stay_days if rule else 0
        classification = (jle.legal_classification if jle else None) or (rule.stay_classification_label if rule else None) or StayClassification.guest
        risk = (jle.risk_level if jle else None) or (rule.risk_level if rule else None) or RiskLevel.low
        statutes = (jle.applicable_statutes if jle else []) or ([rule.statute_reference] if rule and rule.statute_reference else [])
        dms_on = bool(getattr(s, "dead_mans_switch_enabled", 0))
        confirmation_deadline_at = datetime.combine(s.stay_end_date + timedelta(days=2), dt_time.min, tzinfo=timezone.utc) if s.stay_end_date else None
        conf_resp = getattr(s, "occupancy_confirmation_response", None)
        # Property Status Confirmation is for PM/owner only — not tenant-invited guest stays
        needs_conf = False
        show_confirm_ui = False
        invite_id_val = None
        token_state_val = None
        inv_for_stay = None
        if getattr(s, "invitation_id", None):
            inv_for_stay = db.query(Invitation).filter(Invitation.id == s.invitation_id).first()
            if inv_for_stay:
                invite_id_val = inv_for_stay.invitation_code
                token_state_val = getattr(inv_for_stay, "token_state", None) or "BURNED"
        unit_id_for_label = getattr(s, "unit_id", None) or (
            getattr(inv_for_stay, "unit_id", None) if inv_for_stay else None
        )
        stay_unit_label = _unit_label_if_multi_unit(db, s.property_id, unit_id_for_label)
        out.append(OwnerStayView(
            stay_id=s.id, property_id=s.property_id, invite_id=invite_id_val, token_state=token_state_val, invitation_only=False,
            guest_name=guest_name, property_name=property_name, unit_label=stay_unit_label, stay_start_date=s.stay_start_date, stay_end_date=s.stay_end_date,
            region_code=s.region_code, legal_classification=classification, max_stay_allowed_days=max_days, risk_indicator=risk, applicable_laws=statutes,
            revoked_at=getattr(s, "revoked_at", None), checked_in_at=getattr(s, "checked_in_at", None), checked_out_at=getattr(s, "checked_out_at", None), cancelled_at=getattr(s, "cancelled_at", None),
            usat_token_released_at=getattr(s, "usat_token_released_at", None), dead_mans_switch_enabled=dms_on,
            needs_occupancy_confirmation=needs_conf, show_occupancy_confirmation_ui=show_confirm_ui, confirmation_deadline_at=confirmation_deadline_at if show_confirm_ui else None, occupancy_confirmation_response=conf_resp,
            property_deleted_at=getattr(prop, "deleted_at", None) if prop else None,
        ))
    invitation_ids_with_stay = {s.invitation_id for s in stays if getattr(s, "invitation_id", None) is not None}
    q = db.query(Invitation).filter(
        Invitation.invited_by_user_id == current_user.id,
        or_(Invitation.invitation_kind == "guest", Invitation.invitation_kind.is_(None)),
        Invitation.token_state.in_(["BURNED", "EXPIRED"]),
    )
    if invitation_ids_with_stay:
        q = q.filter(~Invitation.id.in_(invitation_ids_with_stay))
    for inv in q.all():
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        if not prop:
            continue
        property_name = (prop.name or "").strip() or (f"{getattr(prop, 'city', '')}, {getattr(prop, 'state', '')}".strip(", ")) or "Property"
        region = (getattr(inv, "region_code", None) or "").strip() or (getattr(prop, "region_code", None) or "") or "US"
        start, end = inv.stay_start_date, inv.stay_end_date
        duration_days = (end - start).days if start and end else 0
        rule = db.query(RegionRule).filter(RegionRule.region_code == region).first()
        jle = resolve_jurisdiction(db, JLEInput(region_code=region, stay_duration_days=duration_days, owner_occupied=True, property_type=None, guest_has_permanent_address=True))
        max_days = rule.max_stay_days if rule else 0
        classification = (jle.legal_classification if jle else None) or (rule.stay_classification_label if rule else None) or StayClassification.guest
        risk = (jle.risk_level if jle else None) or (rule.risk_level if rule else None) or RiskLevel.low
        statutes = (jle.applicable_statutes if jle else []) or ([rule.statute_reference] if rule and rule.statute_reference else [])
        token_state = (getattr(inv, "token_state", None) or "BURNED").upper()
        is_expired = token_state == "EXPIRED"
        checked_out_dt = datetime.combine(end, dt_time.min, tzinfo=timezone.utc) if is_expired and end else None
        inv_only_label = _unit_label_if_multi_unit(db, inv.property_id, getattr(inv, "unit_id", None))
        out.append(OwnerStayView(
            stay_id=-inv.id, property_id=inv.property_id, invite_id=inv.invitation_code, token_state=token_state, invitation_only=True,
            guest_name=label_from_invitation(db, inv), property_name=property_name, unit_label=inv_only_label, stay_start_date=start, stay_end_date=end,
            region_code=region, legal_classification=classification, max_stay_allowed_days=max_days, risk_indicator=risk, applicable_laws=statutes,
            revoked_at=None, checked_in_at=None, checked_out_at=checked_out_dt, cancelled_at=None, usat_token_released_at=None,
            dead_mans_switch_enabled=bool(getattr(inv, "dead_mans_switch_enabled", 0)), needs_occupancy_confirmation=False, show_occupancy_confirmation_ui=False, confirmation_deadline_at=None, occupancy_confirmation_response=None,
            property_deleted_at=getattr(prop, "deleted_at", None),
        ))
    # Cancelled invitations (tenant/owner cancelled before guest accepted): no Stay row — show in ended list
    cancelled_invs = (
        db.query(Invitation)
        .filter(
            Invitation.invited_by_user_id == current_user.id,
            or_(Invitation.invitation_kind == "guest", Invitation.invitation_kind.is_(None)),
            Invitation.status == "cancelled",
        )
        .all()
    )
    for inv in cancelled_invs:
        if db.query(Stay).filter(Stay.invitation_id == inv.id).first():
            continue
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        if not prop:
            continue
        property_name = (prop.name or "").strip() or (f"{getattr(prop, 'city', '')}, {getattr(prop, 'state', '')}".strip(", ")) or "Property"
        region = (getattr(inv, "region_code", None) or "").strip() or (getattr(prop, "region_code", None) or "") or "US"
        start, end = inv.stay_start_date, inv.stay_end_date
        duration_days = (end - start).days if start and end else 0
        rule = db.query(RegionRule).filter(RegionRule.region_code == region).first()
        jle = resolve_jurisdiction(db, JLEInput(region_code=region, stay_duration_days=duration_days, owner_occupied=True, property_type=None, guest_has_permanent_address=True))
        max_days = rule.max_stay_days if rule else 0
        classification = (jle.legal_classification if jle else None) or (rule.stay_classification_label if rule else None) or StayClassification.guest
        risk = (jle.risk_level if jle else None) or (rule.risk_level if rule else None) or RiskLevel.low
        statutes = (jle.applicable_statutes if jle else []) or ([rule.statute_reference] if rule and rule.statute_reference else [])
        ts = (getattr(inv, "token_state", None) or "REVOKED").upper()
        cancelled_ts = inv.created_at if getattr(inv, "created_at", None) else datetime.now(timezone.utc)
        cancelled_inv_label = _unit_label_if_multi_unit(db, inv.property_id, getattr(inv, "unit_id", None))
        out.append(OwnerStayView(
            stay_id=-inv.id, property_id=inv.property_id, invite_id=inv.invitation_code, token_state=ts, invitation_only=True,
            guest_name=label_from_invitation(db, inv), property_name=property_name, unit_label=cancelled_inv_label, stay_start_date=start, stay_end_date=end,
            region_code=region, legal_classification=classification, max_stay_allowed_days=max_days, risk_indicator=risk, applicable_laws=statutes,
            revoked_at=None, checked_in_at=None, checked_out_at=None, cancelled_at=cancelled_ts, usat_token_released_at=None,
            dead_mans_switch_enabled=bool(getattr(inv, "dead_mans_switch_enabled", 0)), needs_occupancy_confirmation=False, show_occupancy_confirmation_ui=False, confirmation_deadline_at=None, occupancy_confirmation_response=None,
            property_deleted_at=getattr(prop, "deleted_at", None),
        ))
    return out


@router.get("/tenant/signed-documents")
def tenant_signed_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """Return signed agreements for this tenant: (1) agreements they signed as a guest, (2) agreements signed by guests they invited."""

    def _row(sig: AgreementSignature, record_type: str) -> dict:
        inv = db.query(Invitation).filter(Invitation.invitation_code == sig.invitation_code).first()
        prop = db.query(Property).filter(Property.id == inv.property_id).first() if inv else None
        property_name = None
        if prop:
            property_name = (prop.name or "").strip() or ", ".join(filter(None, [prop.street, prop.city, prop.state])) or "Property"
        return {
            "signature_id": sig.id,
            "invitation_code": sig.invitation_code,
            "document_title": sig.document_title or "Agreement",
            "signed_at": sig.signed_at.isoformat() if sig.signed_at else None,
            "signed_by": sig.guest_full_name,
            "has_signed_pdf": sig.signed_pdf_bytes is not None,
            "property_name": property_name,
            "stay_start_date": str(inv.stay_start_date) if inv else None,
            "stay_end_date": str(inv.stay_end_date) if inv else None,
            "record_type": record_type,
        }

    self_sigs = (
        db.query(AgreementSignature)
        .filter(
            (AgreementSignature.used_by_user_id == current_user.id)
            | (AgreementSignature.guest_email == current_user.email)
        )
        .order_by(AgreementSignature.signed_at.desc())
        .all()
    )

    tenant_guest_codes = [
        row[0]
        for row in db.query(Invitation.invitation_code)
        .filter(
            Invitation.invited_by_user_id == current_user.id,
            Invitation.invitation_kind == "guest",
        )
        .all()
        if row[0]
    ]
    guest_sigs: list[AgreementSignature] = []
    if tenant_guest_codes:
        guest_sigs = (
            db.query(AgreementSignature)
            .filter(AgreementSignature.invitation_code.in_(tenant_guest_codes))
            .order_by(AgreementSignature.signed_at.desc())
            .all()
        )

    seen: set[int] = set()
    out: list[dict] = []
    for sig in self_sigs:
        if sig.id in seen:
            continue
        seen.add(sig.id)
        out.append(_row(sig, "self"))
    for sig in guest_sigs:
        if sig.id in seen:
            continue
        seen.add(sig.id)
        out.append(_row(sig, "guest_invited_by_you"))

    out.sort(key=lambda r: r.get("signed_at") or "", reverse=True)
    return out


@router.get("/tenant/property-verification")
def tenant_property_verification(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """Return verification record for tenant's assigned property: POA status, guest agreements, property status."""
    today = date.today()
    ta = (
        db.query(TenantAssignment)
        .join(Unit)
        .filter(
            TenantAssignment.user_id == current_user.id,
            (TenantAssignment.end_date.is_(None)) | (TenantAssignment.end_date >= today),
        )
        .order_by(TenantAssignment.start_date.desc())
        .first()
    )
    if not ta:
        return {"poa_signed_at": None, "poa_url": None, "guest_agreements": [], "property_status": None}

    unit = db.query(Unit).filter(Unit.id == ta.unit_id).first()
    prop = db.query(Property).filter(Property.id == unit.property_id).first() if unit else None
    if not prop:
        return {"poa_signed_at": None, "poa_url": None, "guest_agreements": [], "property_status": None}

    owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
    poa_signed_at = None
    poa_url = None
    if owner_profile and owner_profile.user_id:
        poa_sig = (
            db.query(OwnerPOASignature)
            .filter(OwnerPOASignature.used_by_user_id == owner_profile.user_id)
            .first()
        )
        if poa_sig:
            poa_signed_at = poa_sig.signed_at.isoformat() if poa_sig.signed_at else None
            if prop.live_slug:
                poa_url = f"/public/live/{prop.live_slug}/poa"

    guest_agreements = []
    # Tenant lane: only guest invitations this tenant created (not owner/manager invites).
    property_invitations = (
        db.query(Invitation)
        .filter(
            Invitation.property_id == prop.id,
            Invitation.invited_by_user_id == current_user.id,
            or_(Invitation.invitation_kind == "guest", Invitation.invitation_kind.is_(None)),
        )
        .all()
    )
    inv_codes = [inv.invitation_code for inv in property_invitations]
    if inv_codes:
        sigs = (
            db.query(AgreementSignature)
            .filter(AgreementSignature.invitation_code.in_(inv_codes))
            .order_by(AgreementSignature.signed_at.desc())
            .all()
        )
        for sig in sigs:
            inv = next((i for i in property_invitations if i.invitation_code == sig.invitation_code), None)
            guest_agreements.append({
                "signature_id": sig.id,
                "invitation_code": sig.invitation_code,
                "document_title": sig.document_title or "Guest Agreement",
                "guest_name": (sig.guest_full_name or sig.guest_email or "").strip() or (label_from_invitation(db, inv) if inv else "Unknown invitee"),
                "signed_at": sig.signed_at.isoformat() if sig.signed_at else None,
                "stay_start_date": str(inv.stay_start_date) if inv and inv.stay_start_date else None,
                "stay_end_date": str(inv.stay_end_date) if inv and inv.stay_end_date else None,
                "token_state": getattr(inv, "token_state", None) if inv else None,
            })

    property_status = normalize_occupancy_status_for_display(
        db, prop.id, None, getattr(prop, "occupancy_status", None) or OccupancyStatus.vacant.value
    )

    return {
        "poa_signed_at": poa_signed_at,
        "poa_url": poa_url,
        "guest_agreements": guest_agreements,
        "property_status": property_status,
    }


@router.get("/presence")
def get_presence(
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current presence for a unit. Tenant lane only (assigned tenant on this unit)."""
    if not can_perform_action(db, current_user, Action.SET_PRESENCE, unit_id=unit_id):
        raise HTTPException(status_code=403, detail="You do not have access to view presence for this unit")
    pres = db.query(ResidentPresence).filter(
        ResidentPresence.user_id == current_user.id,
        ResidentPresence.unit_id == unit_id,
    ).first()
    if not pres:
        return {"status": "present", "unit_id": unit_id, "away_started_at": None, "away_ended_at": None, "guests_authorized_during_away": False}
    return {
        "status": pres.status.value,
        "unit_id": unit_id,
        "away_started_at": pres.away_started_at.isoformat() if pres.away_started_at else None,
        "away_ended_at": pres.away_ended_at.isoformat() if pres.away_ended_at else None,
        "guests_authorized_during_away": bool(pres.guests_authorized_during_away),
    }


@router.post("/presence")
def set_presence(
    request: Request,
    unit_id: int = Body(..., embed=True),
    status: str = Body(..., embed=True),
    guests_authorized_during_away: bool | None = Body(None, embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set presence/away status for a unit. Tenant lane only (assigned tenant on this unit)."""
    if status not in ("present", "away"):
        raise HTTPException(status_code=400, detail="status must be 'present' or 'away'")
    if not can_perform_action(db, current_user, Action.SET_PRESENCE, unit_id=unit_id):
        raise HTTPException(status_code=403, detail="You do not have access to set presence for this unit")
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    property_id = unit.property_id

    pres = db.query(ResidentPresence).filter(
        ResidentPresence.user_id == current_user.id,
        ResidentPresence.unit_id == unit_id,
    ).first()
    status_enum = PresenceStatus.present if status == "present" else PresenceStatus.away
    now = datetime.now(timezone.utc)
    prev_status = pres.status if pres else None

    if pres:
        pres.status = status_enum
        pres.updated_at = now
        if status == "away":
            pres.away_started_at = now
            pres.away_ended_at = None
            pres.guests_authorized_during_away = bool(guests_authorized_during_away) if guests_authorized_during_away is not None else False
        else:
            pres.away_ended_at = now
            if guests_authorized_during_away is not None:
                pres.guests_authorized_during_away = bool(guests_authorized_during_away)
    else:
        pres = ResidentPresence(
            user_id=current_user.id,
            unit_id=unit_id,
            status=status_enum,
            away_started_at=now if status == "away" else None,
            away_ended_at=None,
            guests_authorized_during_away=bool(guests_authorized_during_away) if guests_authorized_during_away is not None else False,
        )
        db.add(pres)

    if prev_status != status_enum:
        unit_label = getattr(unit, "unit_label", None) or f"Unit {unit_id}"
        log_message = f"Tenant {current_user.email or 'Unknown'} set presence to {status} for {unit_label}."
        if status == "away":
            away_display = format_dt_display(pres.away_started_at)
            guests_ok = "Yes" if pres.guests_authorized_during_away else "No"
            audit_message = (
                f"{log_message} "
                f"Resident is temporarily absent. "
                f"Guests authorized during this period: {guests_ok}. "
                f"Absence started at: {away_display}."
            )
        else:
            audit_message = log_message
        create_log(
            db,
            CATEGORY_PRESENCE,
            "Presence status changed",
            audit_message,
            property_id=property_id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=request.client.host if request.client else None,
            meta={
                "status": status,
                "unit_id": unit_id,
                "away_started_at": pres.away_started_at.isoformat() if pres.away_started_at else None,
                "away_ended_at": pres.away_ended_at.isoformat() if pres.away_ended_at else None,
                "guests_authorized_during_away": pres.guests_authorized_during_away,
            },
        )
        if status == "away":
            away_display = format_dt_display(pres.away_started_at)
            guests_ok = "Yes" if pres.guests_authorized_during_away else "No"
            ledger_message = (
                f"{log_message} "
                f"Resident is temporarily absent. "
                f"Guests authorized during this period: {guests_ok}. "
                f"Absence started at: {away_display}."
            )
            create_ledger_event(
                db,
                ACTION_AWAY_ACTIVATED,
                property_id=property_id,
                unit_id=unit_id,
                actor_user_id=current_user.id,
                ip_address=request.client.host if request.client else None,
                meta={
                    "message": ledger_message,
                    "status": status,
                    "unit_label": unit_label,
                    "resident_temporarily_absent": True,
                    "guests_authorized_during_away": pres.guests_authorized_during_away,
                    "away_started_at": pres.away_started_at.isoformat() if pres.away_started_at else None,
                },
            )
        elif status == "present":
            ledger_message = f"{log_message} Resident returned; away status ended."
            create_ledger_event(
                db,
                ACTION_AWAY_ENDED,
                property_id=property_id,
                unit_id=unit_id,
                actor_user_id=current_user.id,
                ip_address=request.client.host if request.client else None,
                meta={"message": ledger_message, "status": status, "unit_label": unit_label},
            )
            # Full timeline: append completed away period to history
            if pres.away_started_at is not None:
                db.add(PresenceAwayPeriod(
                    resident_presence_id=pres.id,
                    stay_id=None,
                    away_started_at=pres.away_started_at,
                    away_ended_at=now,
                    guests_authorized_during_away=pres.guests_authorized_during_away,
                ))
        else:
            create_ledger_event(
                db,
                ACTION_PRESENCE_STATUS_CHANGED,
                property_id=property_id,
                unit_id=unit_id,
                actor_user_id=current_user.id,
                ip_address=request.client.host if request.client else None,
                meta={"message": log_message, "status": status, "unit_label": unit_label},
            )

    db.commit()
    db.refresh(pres)
    return {
        "status": "success",
        "presence": status,
        "unit_id": unit_id,
        "away_started_at": pres.away_started_at.isoformat() if pres.away_started_at else None,
        "away_ended_at": pres.away_ended_at.isoformat() if pres.away_ended_at else None,
        "guests_authorized_during_away": pres.guests_authorized_during_away,
    }


@router.get("/guest/presence")
def get_stay_presence(
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get presence for an ongoing stay. Guest only; stay must be checked in and not checked out."""
    stay = db.query(Stay).filter(Stay.id == stay_id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    if stay.guest_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this stay")
    if not stay.checked_in_at or stay.checked_out_at:
        raise HTTPException(status_code=400, detail="Presence is only available for an ongoing stay after check-in")
    pres = db.query(StayPresence).filter(StayPresence.stay_id == stay_id).first()
    if not pres:
        return {
            "status": "present",
            "stay_id": stay_id,
            "away_started_at": None,
            "away_ended_at": None,
            "guests_authorized_during_away": False,
        }
    return {
        "status": pres.status.value,
        "stay_id": stay_id,
        "away_started_at": pres.away_started_at.isoformat() if pres.away_started_at else None,
        "away_ended_at": pres.away_ended_at.isoformat() if pres.away_ended_at else None,
        "guests_authorized_during_away": bool(pres.guests_authorized_during_away),
    }


@router.post("/guest/presence")
def set_stay_presence(
    request: Request,
    stay_id: int = Body(..., embed=True),
    status: str = Body(..., embed=True),
    guests_authorized_during_away: bool | None = Body(None, embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set present/away for an ongoing stay. Guest only; stay must be checked in and not checked out."""
    if status not in ("present", "away"):
        raise HTTPException(status_code=400, detail="status must be 'present' or 'away'")
    stay = db.query(Stay).filter(Stay.id == stay_id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    if stay.guest_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this stay")
    if not stay.checked_in_at or stay.checked_out_at:
        raise HTTPException(status_code=400, detail="Presence is only available for an ongoing stay after check-in")
    property_id = stay.property_id
    unit_id = stay.unit_id
    unit_label = None
    if unit_id:
        unit = db.query(Unit).filter(Unit.id == unit_id).first()
        unit_label = getattr(unit, "unit_label", None) if unit else None
    unit_label = unit_label or (f"Unit {unit_id}" if unit_id else "Property")

    pres = db.query(StayPresence).filter(StayPresence.stay_id == stay_id).first()
    status_enum = PresenceStatus.present if status == "present" else PresenceStatus.away
    now = datetime.now(timezone.utc)
    prev_status = pres.status if pres else None

    if pres:
        pres.status = status_enum
        pres.updated_at = now
        if status == "away":
            pres.away_started_at = now
            pres.away_ended_at = None
            pres.guests_authorized_during_away = bool(guests_authorized_during_away) if guests_authorized_during_away is not None else False
        else:
            pres.away_ended_at = now
            if guests_authorized_during_away is not None:
                pres.guests_authorized_during_away = bool(guests_authorized_during_away)
    else:
        pres = StayPresence(
            stay_id=stay_id,
            status=status_enum,
            away_started_at=now if status == "away" else None,
            away_ended_at=None,
            guests_authorized_during_away=bool(guests_authorized_during_away) if guests_authorized_during_away is not None else False,
        )
        db.add(pres)

    if prev_status != status_enum:
        log_message = f"Guest {current_user.email or 'Unknown'} set presence to {status} for stay {stay_id} ({unit_label})."
        if status == "away":
            away_display = format_dt_display(pres.away_started_at)
            guests_ok = "Yes" if pres.guests_authorized_during_away else "No"
            audit_message = (
                f"{log_message} "
                f"Resident is temporarily absent. "
                f"Guests authorized during this period: {guests_ok}. "
                f"Absence started at: {away_display}."
            )
        else:
            audit_message = log_message
        create_log(
            db,
            CATEGORY_PRESENCE,
            "Presence status changed",
            audit_message,
            property_id=property_id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=request.client.host if request.client else None,
            meta={
                "status": status,
                "stay_id": stay_id,
                "unit_id": unit_id,
                "away_started_at": pres.away_started_at.isoformat() if pres.away_started_at else None,
                "away_ended_at": pres.away_ended_at.isoformat() if pres.away_ended_at else None,
                "guests_authorized_during_away": pres.guests_authorized_during_away,
            },
        )
        if status == "away":
            away_display = format_dt_display(pres.away_started_at)
            guests_ok = "Yes" if pres.guests_authorized_during_away else "No"
            ledger_message = (
                f"{log_message} "
                f"Guest is temporarily absent. "
                f"Guests authorized during this period: {guests_ok}. "
                f"Absence started at: {away_display}."
            )
            create_ledger_event(
                db,
                ACTION_AWAY_ACTIVATED,
                property_id=property_id,
                unit_id=unit_id,
                stay_id=stay_id,
                actor_user_id=current_user.id,
                ip_address=request.client.host if request.client else None,
                meta={
                    "message": ledger_message,
                    "status": status,
                    "unit_label": unit_label,
                    "resident_temporarily_absent": True,
                    "guests_authorized_during_away": pres.guests_authorized_during_away,
                    "away_started_at": pres.away_started_at.isoformat() if pres.away_started_at else None,
                },
            )
        elif status == "present":
            ledger_message = f"{log_message} Guest returned; away status ended."
            create_ledger_event(
                db,
                ACTION_AWAY_ENDED,
                property_id=property_id,
                unit_id=unit_id,
                stay_id=stay_id,
                actor_user_id=current_user.id,
                ip_address=request.client.host if request.client else None,
                meta={"message": ledger_message, "status": status, "unit_label": unit_label},
            )
            if pres.away_started_at is not None:
                db.add(PresenceAwayPeriod(
                    resident_presence_id=None,
                    stay_id=stay_id,
                    away_started_at=pres.away_started_at,
                    away_ended_at=now,
                    guests_authorized_during_away=pres.guests_authorized_during_away,
                ))

    db.commit()
    db.refresh(pres)
    return {
        "status": "success",
        "presence": status,
        "stay_id": stay_id,
        "away_started_at": pres.away_started_at.isoformat() if pres.away_started_at else None,
        "away_ended_at": pres.away_ended_at.isoformat() if pres.away_ended_at else None,
        "guests_authorized_during_away": pres.guests_authorized_during_away,
    }


def _parse_optional_utc(s: str | None) -> datetime | None:
    if not s or not s.strip():
        return None
    try:
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except (ValueError, TypeError):
        return None


def _invoice_metadata_dict(inv: object) -> dict[str, Any]:
    """Normalize Stripe ``Invoice.metadata`` (a ``StripeObject``) to a plain ``dict``.

    Do not call ``dict(stripe_object)`` — the Stripe SDK can raise ``KeyError`` during coercion.
    """
    raw = getattr(inv, "metadata", None)
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    to_dict = getattr(raw, "to_dict", None)
    if callable(to_dict):
        try:
            out = to_dict()
            if isinstance(out, dict):
                return {str(k): out[k] for k in out}
        except Exception:
            pass
    keys_fn = getattr(raw, "keys", None)
    if callable(keys_fn):
        try:
            return {str(k): raw[k] for k in keys_fn()}  # type: ignore[index]
        except Exception:
            pass
    return {}


def _stripe_invoice_visible_in_dashboard(inv: object) -> bool:
    """Hide $0 Stripe invoices (e.g. subscription free-trial bookkeeping with status paid, $0).

    List only invoices that need payment (amount_due) or record a real charge (amount_paid).
    """
    amount_due = int(getattr(inv, "amount_due", 0) or 0)
    amount_paid = int(getattr(inv, "amount_paid", 0) or 0)
    return amount_due > 0 or amount_paid > 0


@router.get("/owner/billing", response_model=BillingResponse)
def owner_billing(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """List Stripe invoices and payments for the current owner. Returns empty lists if Stripe is not configured or no customer yet.
    can_invite is False while billing onboarding is incomplete (e.g. subscription setup still in progress after first property add)."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        return BillingResponse(invoices=[], payments=[], can_invite=True, current_unit_count=0, current_shield_count=0)
    _units, _shield = _count_properties_and_shield(db, profile)
    if not profile.stripe_customer_id:
        can_invite = profile.onboarding_billing_completed_at is None or profile.onboarding_invoice_paid_at is not None
        return BillingResponse(invoices=[], payments=[], can_invite=can_invite, current_unit_count=_units, current_shield_count=_shield)

    from app.config import get_settings
    settings = get_settings()
    if not (settings.stripe_secret_key or "").strip():
        can_invite = profile.onboarding_billing_completed_at is None or profile.onboarding_invoice_paid_at is not None
        return BillingResponse(
            invoices=[],
            payments=[],
            can_invite=can_invite,
            current_unit_count=_units,
            current_shield_count=_shield,
        )

    import stripe

    stripe.api_key = settings.stripe_secret_key
    # Copy before sync: commit() inside sync_subscription_quantities expires ORM state; lazy-loading
    # stripe_customer_id during a long Stripe.list iteration can stall on the pool (QueuePool timeout).
    stripe_customer_id = profile.stripe_customer_id
    if profile.stripe_subscription_id:
        try:
            sync_subscription_quantities(db, profile)
        except Exception as e:
            logger.warning(
                "owner_billing: subscription sync failed profile_id=%s: %s",
                profile.id,
                e,
                exc_info=True,
            )
    try:
        db.refresh(profile)
    except Exception:
        logger.warning("owner_billing: db.refresh(profile) after sync failed", exc_info=True)
    invoices: list[BillingInvoiceView] = []
    payments: list[BillingPaymentView] = []
    try:
        for inv in stripe.Invoice.list(customer=stripe_customer_id, limit=100).auto_paging_iter():
            # Auto-finalize drafts so user gets a payable invoice; skip if finalize fails
            if inv.status == "draft":
                try:
                    inv = stripe.Invoice.finalize_invoice(inv.id)
                except stripe.StripeError:
                    continue
            # Never expose draft to the client
            if inv.status == "draft":
                continue
            created_dt = datetime.fromtimestamp(inv.created, tz=timezone.utc) if inv.created else datetime.now(timezone.utc)
            amount_due = getattr(inv, "amount_due", 0) or 0
            amount_paid = getattr(inv, "amount_paid", 0) or 0
            desc = getattr(inv, "description", None) or None
            if not desc and getattr(inv, "lines", None) and getattr(inv.lines, "data", None) and len(inv.lines.data) > 0:
                desc = getattr(inv.lines.data[0], "description", None)
            # Self-heal: if webhook missed invoice.paid, set onboarding_invoice_paid_at and record in audit log so it shows in Logs (skip when stripe_skip_onboarding_self_heal for re-testing)
            meta = _invoice_metadata_dict(inv)
            if not settings.stripe_skip_onboarding_self_heal and inv.status == "paid" and meta.get("onboarding_units") and profile.onboarding_invoice_paid_at is None:
                profile.onboarding_invoice_paid_at = datetime.now(timezone.utc)
                user = db.query(User).filter(User.id == profile.user_id).first()
                create_log(
                    db,
                    CATEGORY_BILLING,
                    "Invoice paid",
                    f"Invoice {getattr(inv, 'number', inv.id)} paid: ${amount_paid / 100:.2f} {(inv.currency or 'usd').upper()}.",
                    property_id=None,
                    actor_user_id=user.id if user else None,
                    actor_email=user.email if user else None,
                    meta={"stripe_invoice_id": inv.id, "amount_paid_cents": amount_paid, "currency": (inv.currency or "usd").upper(), "self_heal": True},
                )
                db.commit()
            if not _stripe_invoice_visible_in_dashboard(inv):
                continue
            invoices.append(
                BillingInvoiceView(
                    id=inv.id,
                    number=getattr(inv, "number", None) or None,
                    description=desc,
                    amount_due_cents=amount_due,
                    amount_paid_cents=amount_paid,
                    currency=(inv.currency or "usd").upper(),
                    status=inv.status or "open",
                    created=created_dt,
                    hosted_invoice_url=getattr(inv, "hosted_invoice_url", None) or None,
                )
            )
            if inv.status == "paid" and amount_paid > 0:
                paid_at = datetime.fromtimestamp(inv.status_transitions.paid_at, tz=timezone.utc) if getattr(inv, "status_transitions", None) and getattr(inv.status_transitions, "paid_at", None) else created_dt
                payments.append(
                    BillingPaymentView(
                        invoice_id=inv.id,
                        amount_cents=amount_paid,
                        currency=(inv.currency or "usd").upper(),
                        paid_at=paid_at,
                        description=desc,
                    )
                )
    except stripe.StripeError as e:
        print(f"[Billing] StripeError fetching invoices for customer={stripe_customer_id}: {e}", flush=True)
        try:
            db.refresh(profile)
        except Exception:
            pass
        can_invite = profile.onboarding_billing_completed_at is None or profile.onboarding_invoice_paid_at is not None
        sub_status, trial_end_at, trial_days_remaining = None, None, None
        if profile.stripe_subscription_id:
            try:
                sub = stripe.Subscription.retrieve(profile.stripe_subscription_id)
                sub_status, trial_end_at, trial_days_remaining = stripe_subscription_status_and_trial(sub)
            except stripe.StripeError:
                pass
        return BillingResponse(
            invoices=[],
            payments=[],
            can_invite=can_invite,
            current_unit_count=_units,
            current_shield_count=_shield,
            subscription_status=sub_status,
            trial_end_at=trial_end_at,
            trial_days_remaining=trial_days_remaining,
        )

    # Sort invoices by created desc, payments by paid_at desc
    invoices.sort(key=lambda x: x.created, reverse=True)
    payments.sort(key=lambda x: x.paid_at, reverse=True)
    try:
        db.refresh(profile)
    except Exception:
        logger.warning("owner_billing: db.refresh(profile) after invoice loop failed", exc_info=True)
    # Recompute property counts (billing units) and can_invite (may have been set by self-heal above)
    _units, _shield = _count_properties_and_shield(db, profile)
    can_invite = profile.onboarding_billing_completed_at is None or profile.onboarding_invoice_paid_at is not None
    sub_status, trial_end_at, trial_days_remaining = None, None, None
    if profile.stripe_subscription_id:
        try:
            sub = stripe.Subscription.retrieve(profile.stripe_subscription_id)
            sub_status, trial_end_at, trial_days_remaining = stripe_subscription_status_and_trial(sub)
        except stripe.StripeError:
            pass
    return BillingResponse(
        invoices=invoices,
        payments=payments,
        can_invite=can_invite,
        current_unit_count=_units,
        current_shield_count=_shield,
        subscription_status=sub_status,
        trial_end_at=trial_end_at,
        trial_days_remaining=trial_days_remaining,
    )


@router.post("/owner/billing/sync-subscription", response_model=BillingSyncSubscriptionResponse)
def sync_owner_billing_subscription(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Reconcile Stripe subscription amount with active property count. Optional: opening the billing portal runs sync internally — avoid chaining both before redirect (doubles latency)."""
    if current_user.role == UserRole.property_manager:
        raise HTTPException(status_code=403, detail="Property managers cannot modify billing. Contact the property owner.")
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        return BillingSyncSubscriptionResponse(
            ok=True,
            properties_billed=0,
            monthly_total_cents=0,
            per_property_cents=int(SUBSCRIPTION_FLAT_AMOUNT_CENTS),
        )
    units, _shield_units = _count_properties_and_shield(db, profile)
    monthly_total_cents = int(SUBSCRIPTION_FLAT_AMOUNT_CENTS) * int(units)
    meta = BillingSyncSubscriptionResponse(
        ok=True,
        properties_billed=units,
        monthly_total_cents=monthly_total_cents,
        per_property_cents=int(SUBSCRIPTION_FLAT_AMOUNT_CENTS),
    )
    if not profile.stripe_subscription_id:
        return meta.model_copy(
            update={
                "stripe_modification_requests": [
                    {
                        "note": "no_stripe_subscription_id",
                        "properties_billed": units,
                        "target_monthly_total_cents": monthly_total_cents,
                        "detail": "Sync did not call Stripe — no subscription id on this profile yet.",
                    }
                ]
            }
        )
    if not (get_settings().stripe_secret_key or "").strip():
        raise HTTPException(status_code=501, detail="Stripe is not configured")
    trace: list[dict[str, Any]] = [
        {
            "note": "billing_sync_context",
            "stripe_subscription_id": profile.stripe_subscription_id,
            "properties_billed": units,
            "target_monthly_total_cents": monthly_total_cents,
        }
    ]
    try:
        sync_subscription_quantities(db, profile, stripe_request_trace=trace)
    except Exception as e:
        trace.append(
            {
                "note": "sync_raised_exception",
                "error": str(e),
            }
        )
        raise HTTPException(status_code=502, detail=f"Could not sync subscription: {e}") from e
    return meta.model_copy(update={"stripe_modification_requests": trace})


@router.post("/owner/billing/portal-session", response_model=BillingPortalSessionResponse)
def create_billing_portal_session(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Create a Stripe Customer Billing Portal session. Redirect the user to the returned URL to pay invoices.
    After payment (including Klarna or other redirect methods), Stripe redirects back to our app (return_url).
    This avoids the issue where paying via Klarna leaves the user stuck on pay.test.klarna.com with no way back."""
    if current_user.role == UserRole.property_manager:
        raise HTTPException(status_code=403, detail="Property managers cannot modify billing. Contact the property owner.")
    from app.config import get_settings
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile or not profile.stripe_customer_id:
        raise HTTPException(status_code=404, detail="No billing customer. Add a property first.")
    settings = get_settings()
    if not (settings.stripe_secret_key or "").strip():
        raise HTTPException(status_code=501, detail="Stripe is not configured")
    # Copy before sync: commits inside sync_subscription_quantities expire ORM state; avoid lazy-load of customer id under pool pressure.
    stripe_customer_id = profile.stripe_customer_id
    # Match Stripe line item to current property count before opening Customer Portal (single sync here — do not duplicate from the client).
    try:
        sync_subscription_quantities(db, profile)
    except Exception as e:
        logger.warning(
            "billing portal: pre-sync failed profile_id=%s: %s",
            profile.id,
            e,
            exc_info=True,
        )
    try:
        db.refresh(profile)
    except Exception:
        logger.warning("billing portal: db.refresh(profile) after sync failed", exc_info=True)
    base = (settings.stripe_identity_return_url or settings.frontend_base_url or "").strip().split("#")[0].rstrip("/")
    if not base:
        raise HTTPException(status_code=501, detail="Billing return URL not configured. Set STRIPE_IDENTITY_RETURN_URL or FRONTEND_BASE_URL in .env.")
    # Land on Billing tab so we can refetch and show updated status (frontend detects payment return via query params)
    return_url = f"{base}/#dashboard/billing"
    import stripe
    stripe.api_key = settings.stripe_secret_key
    try:
        session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=return_url,
        )
        return BillingPortalSessionResponse(url=session.url)
    except stripe.StripeError as e:
        raise HTTPException(status_code=502, detail=f"Stripe error: {e}")


@router.get("/owner/personal-mode-units")
def owner_personal_mode_units(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Unit IDs where this owner has Personal Mode (lives as resident). Used for Mode Switcher."""
    unit_ids = get_owner_personal_mode_units(db, current_user.id)
    db.commit()  # commit any new Units created for single-unit properties for Personal Mode routing
    return {"unit_ids": unit_ids}


@router.get("/owner/properties/{property_id}/personal-mode-unit")
def owner_property_personal_mode_unit(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Unit ID for this property when the owner has Personal Mode (on-site residence) for that property."""
    unit_ids = get_owner_personal_mode_units(db, current_user.id)
    db.commit()  # commit any new Units created for single-unit properties for Personal Mode routing
    for uid in unit_ids:
        u = db.query(Unit).filter(Unit.id == uid, Unit.property_id == property_id).first()
        if u:
            return {"unit_id": u.id}
    return {"unit_id": None}


@router.get("/manager/personal-mode-units")
def manager_personal_mode_units(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_property_manager_identity_verified),
):
    """Unit IDs where this manager has Personal Mode (lives on-site). Used for Mode Switcher."""
    unit_ids = get_manager_personal_mode_units(db, current_user.id)
    return {"unit_ids": unit_ids}


@router.get("/owner/portfolio-link", response_model=PortfolioLinkResponse)
def owner_portfolio_link(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Get or create the current owner's portfolio slug and URL. Used in Settings to view/copy portfolio link."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Owner profile not found")
    slug = getattr(profile, "portfolio_slug", None)
    if not slug:
        for _ in range(20):
            slug = secrets.token_urlsafe(8).replace("+", "-").replace("/", "_")[:16]
            if db.query(OwnerProfile).filter(OwnerProfile.portfolio_slug == slug).first() is None:
                profile.portfolio_slug = slug
                db.add(profile)
                db.commit()
                break
        else:
            slug = f"p-{profile.id}-{secrets.token_hex(4)}"
            profile.portfolio_slug = slug
            db.add(profile)
            db.commit()
    return PortfolioLinkResponse(portfolio_slug=slug, portfolio_url=f"portfolio/{slug}")


def _format_property_address_for_log(p: Property) -> str:
    """Full address for log/notification display (e.g. '1 Infinite Loop, Cupertino, CA 95014 USA')."""
    parts = [p.street, p.city, (f"{p.state or ''} {p.zip_code or ''}".strip())]
    addr = ", ".join(x for x in parts if x).strip()
    if addr and not addr.endswith("USA"):
        addr = f"{addr} USA"
    return addr or p.name or f"{p.city}, {p.state}" or ""


@router.get("/owner/logs", response_model=list[OwnerAuditLogEntry])
def owner_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
    context_mode: str = Depends(get_context_mode),
    from_ts: str | None = None,
    to_ts: str | None = None,
    category: str | None = None,
    search: str | None = None,
    property_id: int | None = None,
    x_client_calendar_date: str | None = Header(None, alias="X-Client-Calendar-Date"),
):
    """Business mode: full property/management lane for all owned properties (including soft-deleted) so timelines stay complete.
    Personal mode: when no property_id filter, only primary-residence properties; when property_id is set, any property the owner
    owns (including inactive) so property detail history is not empty."""
    from sqlalchemy import or_, desc, cast, String

    try:
        from app.services.stay_timer import run_status_confirmation_materialize_for_user

        run_status_confirmation_materialize_for_user(
            db, current_user, client_calendar_date=_parse_guest_client_calendar_date_header(x_client_calendar_date)
        )
    except Exception:
        pass

    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        return []

    is_personal = context_mode == "personal"

    owned_all_property_ids = [
        r[0]
        for r in db.query(Property.id).filter(Property.owner_profile_id == profile.id).all()
    ]

    if is_personal:
        allowed_actions = OWNER_PERSONAL_ACTIONS
        ledger_property_ids = get_owner_personal_mode_property_ids(db, current_user.id)
    else:
        allowed_actions = OWNER_BUSINESS_ACTIONS
        # Include inactive properties so business ledger and timelines stay complete after soft-delete
        ledger_property_ids = owned_all_property_ids

    if property_id is not None and property_id not in owned_all_property_ids:
        return []
    # Property-scoped view: allow any owned property (including inactive / outside personal-mode subset) for read-only history

    from_dt = _parse_optional_utc(from_ts)
    to_dt = _parse_optional_utc(to_ts)

    billing_actions = _CATEGORY_TO_ACTION_TYPES.get("billing", [])

    if is_personal and not ledger_property_ids and property_id is None:
        return []

    if property_id is not None:
        q = db.query(EventLedger).filter(EventLedger.property_id == property_id)
    elif ledger_property_ids:
        if is_personal:
            q = db.query(EventLedger).filter(EventLedger.property_id.in_(ledger_property_ids))
        else:
            q = db.query(EventLedger).filter(
                or_(
                    EventLedger.property_id.in_(ledger_property_ids),
                    (EventLedger.action_type == ACTION_PROPERTY_DELETED) & (EventLedger.actor_user_id == current_user.id),
                    (EventLedger.action_type.in_(billing_actions)) & (EventLedger.actor_user_id == current_user.id),
                    (EventLedger.action_type == ACTION_PROPERTY_TRANSFER_PRIOR_OWNER) & (EventLedger.actor_user_id == current_user.id),
                )
            )
    else:
        q = db.query(EventLedger).filter(
            or_(
                (EventLedger.action_type == ACTION_PROPERTY_DELETED) & (EventLedger.actor_user_id == current_user.id),
                (EventLedger.action_type.in_(billing_actions)) & (EventLedger.actor_user_id == current_user.id),
                (EventLedger.action_type == ACTION_PROPERTY_TRANSFER_PRIOR_OWNER) & (EventLedger.actor_user_id == current_user.id),
            )
        )
    q = q.filter(EventLedger.action_type.in_(allowed_actions))
    if from_dt is not None:
        q = q.filter(EventLedger.created_at >= from_dt)
    if to_dt is not None:
        q = q.filter(EventLedger.created_at <= to_dt)
    if category and category.strip():
        action_types = _CATEGORY_TO_ACTION_TYPES.get(category.strip(), [])
        if action_types:
            allowed = [a for a in action_types if a in allowed_actions]
            q = q.filter(EventLedger.action_type.in_(allowed))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter(
            (EventLedger.action_type.ilike(term)) | (cast(EventLedger.meta, String).ilike(term))
        )
    q = q.order_by(desc(EventLedger.created_at))
    rows = q.all()
    rows = filter_tenant_lane_from_ledger_rows(db, rows)
    rows = filter_tenant_presence_from_owner_manager_ledger(db, rows)

    prop_ids = {r.property_id for r in rows if r.property_id}
    props = {}
    if prop_ids:
        for p in db.query(Property).filter(Property.id.in_(prop_ids)).all():
            props[p.id] = _format_property_address_for_log(p)

    def _property_name(r) -> str | None:
        if r.property_id:
            return props.get(r.property_id)
        if r.action_type == ACTION_PROPERTY_DELETED and r.meta and isinstance(r.meta, dict):
            return r.meta.get("property_name")
        if r.action_type == ACTION_PROPERTY_TRANSFER_PRIOR_OWNER and r.meta and isinstance(r.meta, dict):
            return r.meta.get("property_address") or r.meta.get("property_name")
        return None

    out = []
    for r in rows:
        cat, title, msg = ledger_event_to_display(r, db)
        actor_email = get_actor_email(db, r.actor_user_id)
        out.append(
            OwnerAuditLogEntry(
                id=r.id,
                property_id=r.property_id,
                stay_id=r.stay_id,
                invitation_id=r.invitation_id,
                category=cat,
                title=title,
                message=msg,
                actor_user_id=r.actor_user_id,
                actor_email=actor_email,
                ip_address=r.ip_address,
                created_at=r.created_at if r.created_at else datetime.now(timezone.utc),
                property_name=_property_name(r),
            )
        )
    return out


@router.get("/manager/logs", response_model=list[OwnerAuditLogEntry])
def manager_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_property_manager_identity_verified),
    context_mode: str = Depends(get_context_mode),
    from_ts: str | None = None,
    to_ts: str | None = None,
    category: str | None = None,
    search: str | None = None,
    property_id: int | None = None,
    x_client_calendar_date: str | None = Header(None, alias="X-Client-Calendar-Date"),
):
    """Business mode: full management lane for assigned properties. Personal mode: guest-residence events only
    for on-site resident properties (same ledger action set as owner Personal mode)."""
    from sqlalchemy import desc, cast, String

    try:
        from app.services.stay_timer import run_status_confirmation_materialize_for_user

        run_status_confirmation_materialize_for_user(
            db, current_user, client_calendar_date=_parse_guest_client_calendar_date_header(x_client_calendar_date)
        )
    except Exception:
        pass

    property_ids = _manager_property_ids(db, current_user.id)
    if not property_ids:
        return []
    is_personal = context_mode == "personal"
    if is_personal:
        personal_ids = set(get_manager_personal_mode_property_ids(db, current_user.id))
        effective_ids = [pid for pid in property_ids if pid in personal_ids]
        action_set = OWNER_PERSONAL_ACTIONS
    else:
        effective_ids = property_ids
        action_set = OWNER_BUSINESS_ACTIONS
    if not effective_ids:
        return []
    if property_id is not None and property_id not in property_ids:
        return []
    if property_id is not None and property_id not in effective_ids:
        return []
    from_dt = _parse_optional_utc(from_ts)
    to_dt = _parse_optional_utc(to_ts)
    q = db.query(EventLedger).filter(EventLedger.property_id.in_(effective_ids))
    q = q.filter(EventLedger.action_type.in_(action_set))
    if property_id is not None:
        q = q.filter(EventLedger.property_id == property_id)
    if from_dt is not None:
        q = q.filter(EventLedger.created_at >= from_dt)
    if to_dt is not None:
        q = q.filter(EventLedger.created_at <= to_dt)
    if category and category.strip():
        action_types = _CATEGORY_TO_ACTION_TYPES.get(category.strip(), [])
        if action_types:
            allowed = [a for a in action_types if a in action_set]
            q = q.filter(EventLedger.action_type.in_(allowed))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter((EventLedger.action_type.ilike(term)) | (cast(EventLedger.meta, String).ilike(term)))
    rows = q.order_by(desc(EventLedger.created_at)).all()
    rows = filter_tenant_lane_from_ledger_rows(db, rows)
    rows = filter_tenant_presence_from_owner_manager_ledger(db, rows)
    rows = filter_manager_presence_on_tenant_leased_units(db, rows)

    prop_ids = {r.property_id for r in rows if r.property_id}
    props = {}
    if prop_ids:
        for p in db.query(Property).filter(Property.id.in_(prop_ids)).all():
            props[p.id] = _format_property_address_for_log(p)

    out = []
    for r in rows:
        cat, title, msg = ledger_event_to_display(r, db)
        actor_email = get_actor_email(db, r.actor_user_id)
        out.append(
            OwnerAuditLogEntry(
                id=r.id, property_id=r.property_id, stay_id=r.stay_id, invitation_id=r.invitation_id,
                category=cat, title=title, message=msg,
                actor_user_id=r.actor_user_id, actor_email=actor_email, ip_address=r.ip_address,
                created_at=r.created_at if r.created_at else datetime.now(timezone.utc),
                property_name=props.get(r.property_id) if r.property_id else None,
            )
        )
    return out


@router.get("/tenant/logs", response_model=list[OwnerAuditLogEntry])
def tenant_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
    from_ts: str | None = None,
    to_ts: str | None = None,
    category: str | None = None,
    search: str | None = None,
    property_id: int | None = None,
    x_client_calendar_date: str | None = Header(None, alias="X-Client-Calendar-Date"),
):
    """Tenant lane logs only: tenant's own actions, their guest invitations/stays, their presence.
    Excludes billing, property management, shield mode, owner/manager-only Status Confirmation activity, and other tenants' data."""
    from sqlalchemy import desc, cast, String, or_

    # Materialize tenant-invited guest threshold alerts on demand (idempotent; helps in no-cron environments).
    try:
        from app.services.stay_timer import run_tenant_invited_guest_jurisdiction_threshold_notifications

        run_tenant_invited_guest_jurisdiction_threshold_notifications(
            db,
            only_tenant_user_id=current_user.id,
            client_calendar_date=_parse_guest_client_calendar_date_header(x_client_calendar_date),
        )
    except Exception:
        pass

    tenant_property_id = None
    ta = (
        db.query(TenantAssignment)
        .filter(TenantAssignment.user_id == current_user.id)
        .order_by(TenantAssignment.start_date.desc())
        .first()
    )
    if ta:
        unit = db.query(Unit).filter(Unit.id == ta.unit_id).first()
        if unit:
            tenant_property_id = unit.property_id
    if property_id is not None and tenant_property_id is not None and property_id != tenant_property_id:
        return []
    invitation_ids = [r[0] for r in db.query(Invitation.id).filter(Invitation.invited_by_user_id == current_user.id).all()]
    stay_ids = [r[0] for r in db.query(Stay.id).filter(Stay.invitation_id.in_(invitation_ids)).all()] if invitation_ids else []
    conditions = [
        EventLedger.actor_user_id == current_user.id,
    ]
    if invitation_ids:
        conditions.append(EventLedger.invitation_id.in_(invitation_ids))
    if stay_ids:
        conditions.append(EventLedger.stay_id.in_(stay_ids))
    if not conditions:
        return []
    from_dt = _parse_optional_utc(from_ts)
    to_dt = _parse_optional_utc(to_ts)
    q = db.query(EventLedger).filter(or_(*conditions))
    q = q.filter(EventLedger.action_type.in_(TENANT_ALLOWED_ACTIONS))
    if property_id is not None and tenant_property_id is not None:
        q = q.filter(EventLedger.property_id == property_id)
    if from_dt is not None:
        q = q.filter(EventLedger.created_at >= from_dt)
    if to_dt is not None:
        q = q.filter(EventLedger.created_at <= to_dt)
    if category and category.strip():
        action_types = _CATEGORY_TO_ACTION_TYPES.get(category.strip(), [])
        if action_types:
            allowed = [a for a in action_types if a in TENANT_ALLOWED_ACTIONS]
            q = q.filter(EventLedger.action_type.in_(allowed))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter((EventLedger.action_type.ilike(term)) | (cast(EventLedger.meta, String).ilike(term)))
    rows = q.order_by(desc(EventLedger.created_at)).limit(500).all()
    prop_ids = {r.property_id for r in rows if r.property_id}
    props = {}
    if prop_ids:
        for p in db.query(Property).filter(Property.id.in_(prop_ids)).all():
            props[p.id] = _format_property_address_for_log(p)
    out = []
    for r in rows:
        cat, title, msg = ledger_event_to_display(r, db)
        actor_email = get_actor_email(db, r.actor_user_id)
        out.append(
            OwnerAuditLogEntry(
                id=r.id, property_id=r.property_id, stay_id=r.stay_id, invitation_id=r.invitation_id,
                category=cat, title=title, message=msg,
                actor_user_id=r.actor_user_id, actor_email=actor_email, ip_address=r.ip_address,
                created_at=r.created_at if r.created_at else datetime.now(timezone.utc),
                property_name=props.get(r.property_id) if r.property_id else None,
            )
        )
    return out


@router.get("/manager/billing", response_model=BillingResponse)
def manager_billing(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_property_manager_identity_verified),
):
    """Read-only billing for the owner of properties this manager is assigned to."""
    property_ids = _manager_property_ids(db, current_user.id)
    if not property_ids:
        return BillingResponse(invoices=[], payments=[], can_invite=False, current_unit_count=0, current_shield_count=0)
    props = db.query(Property).filter(Property.id.in_(property_ids)).all()
    owner_profile_ids = list({p.owner_profile_id for p in props})
    if not owner_profile_ids:
        return BillingResponse(invoices=[], payments=[], can_invite=False, current_unit_count=0, current_shield_count=0)
    profile = db.query(OwnerProfile).filter(OwnerProfile.id == owner_profile_ids[0]).first()
    if not profile:
        return BillingResponse(invoices=[], payments=[], can_invite=False, current_unit_count=0, current_shield_count=0)
    _units, _shield = _count_properties_and_shield(db, profile)
    if not profile.stripe_customer_id:
        return BillingResponse(invoices=[], payments=[], can_invite=False, current_unit_count=_units, current_shield_count=_shield)
    from app.config import get_settings
    import stripe
    settings = get_settings()
    if not (settings.stripe_secret_key or "").strip():
        return BillingResponse(invoices=[], payments=[], current_unit_count=_units, current_shield_count=_shield)
    stripe.api_key = settings.stripe_secret_key
    invoices: list[BillingInvoiceView] = []
    payments: list[BillingPaymentView] = []
    try:
        for inv in stripe.Invoice.list(customer=profile.stripe_customer_id, limit=100).auto_paging_iter():
            if inv.status == "draft":
                try:
                    inv = stripe.Invoice.finalize_invoice(inv.id)
                except stripe.StripeError:
                    continue
            if inv.status == "draft":
                continue
            created_dt = datetime.fromtimestamp(inv.created, tz=timezone.utc) if inv.created else datetime.now(timezone.utc)
            amount_due = getattr(inv, "amount_due", 0) or 0
            amount_paid = getattr(inv, "amount_paid", 0) or 0
            desc = getattr(inv, "description", None) or None
            if not desc and getattr(inv, "lines", None) and getattr(inv.lines, "data", None) and len(inv.lines.data) > 0:
                desc = getattr(inv.lines.data[0], "description", None)
            if not _stripe_invoice_visible_in_dashboard(inv):
                continue
            invoices.append(BillingInvoiceView(
                id=inv.id, number=getattr(inv, "number", None) or None, description=desc, amount_due_cents=amount_due, amount_paid_cents=amount_paid,
                currency=(inv.currency or "usd").upper(), status=inv.status or "open", created=created_dt, hosted_invoice_url=getattr(inv, "hosted_invoice_url", None) or None,
            ))
            if inv.status == "paid" and amount_paid > 0:
                paid_at = datetime.fromtimestamp(inv.status_transitions.paid_at, tz=timezone.utc) if getattr(inv, "status_transitions", None) and getattr(inv.status_transitions, "paid_at", None) else created_dt
                payments.append(BillingPaymentView(invoice_id=inv.id, amount_cents=amount_paid, currency=(inv.currency or "usd").upper(), paid_at=paid_at, description=desc))
    except stripe.StripeError:
        pass
    invoices.sort(key=lambda x: x.created, reverse=True)
    payments.sort(key=lambda x: x.paid_at, reverse=True)
    return BillingResponse(invoices=invoices, payments=payments, can_invite=False, current_unit_count=_units, current_shield_count=_shield)
