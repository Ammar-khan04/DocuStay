"""Schemas for public live property page and portfolio (no auth)."""
from datetime import date, datetime

from pydantic import BaseModel


# --- Portfolio (owner public page) ---


class PortfolioPropertyItem(BaseModel):
    """Single property for portfolio listing (public info only)."""
    id: int
    name: str | None
    city: str
    state: str
    region_code: str
    property_type_label: str | None = None
    bedrooms: str | None = None
    is_multi_unit: bool = False
    unit_count: int | None = None  # when is_multi_unit, number of units


class PortfolioOwnerInfo(BaseModel):
    """Owner basic info for portfolio page."""
    full_name: str | None = None
    email: str = ""
    phone: str | None = None
    state: str | None = None


class PortfolioPagePayload(BaseModel):
    """Payload for GET /public/portfolio/{slug}."""
    owner: PortfolioOwnerInfo
    properties: list[PortfolioPropertyItem] = []


class LivePropertyInfo(BaseModel):
    """Property summary for live page."""
    name: str | None
    street: str
    city: str
    state: str
    zip_code: str | None
    region_code: str
    occupancy_status: str  # vacant | occupied | unknown | unconfirmed
    shield_mode_enabled: bool  # Independent of occupancy. When True, display as PASSIVE GUARD (occupied) or ACTIVE MONITORING (vacant).
    token_state: str = "staged"  # staged | released – for Quick Decision layer
    tax_id: str | None = None
    apn: str | None = None
    # Owner primary residence (dashboard “personal” / show in personal mode). Public wording avoids internal mode names.
    owner_occupied: bool = False
    # Plain-language explanation of why occupancy reads as it does (guest vs tenant vs owner residence).
    occupancy_summary_detail: str = ""


class LiveOwnerInfo(BaseModel):
    """Owner contact for live page."""
    full_name: str | None
    email: str
    phone: str | None


class LivePropertyManagerInfo(BaseModel):
    """Assigned property manager for authority chain (live page)."""
    full_name: str | None
    email: str


class LiveCurrentGuestInfo(BaseModel):
    """Current guest and stay for live page (active authorization only; historical PDFs via ledger / verify)."""
    stay_id: int
    guest_name: str
    stay_start_date: date
    stay_end_date: date
    checked_out_at: datetime | None  # when set, guest has checked out
    # Public live evidence does not surface stay-end reminder (DMS) state; always false on this payload.
    dead_mans_switch_enabled: bool = False
    signed_agreement_available: bool = False
    signed_agreement_url: str | None = None  # relative API path; use with backend base URL
    stay_kind: str = "guest"  # guest | tenant — from linked invitation when present
    invitation_code: str | None = None  # Invite ID linked to this stay, when present
    invitation_token_state: str | None = None  # STAGED, BURNED, EXPIRED, etc. from linked invitation


class LiveStaySummary(BaseModel):
    """Past or upcoming stay summary."""
    guest_name: str
    stay_start_date: date
    stay_end_date: date
    checked_out_at: datetime | None = None
    stay_kind: str = "guest"  # guest | tenant — from linked invitation when present


class LiveTenantAssignmentInfo(BaseModel):
    """Currently occupying tenant per unit-occupancy rules (see get_units_occupancy_sources)."""

    assignment_id: int | None = None  # tenant_assignments.id when occupier is the leaseholder row
    stay_id: int | None = None  # when property has no Unit rows; checked-in tenant-lane stay
    unit_label: str
    tenant_full_name: str | None
    tenant_email: str | None
    start_date: date
    end_date: date | None = None  # null = open-ended / ongoing
    created_at: datetime
    lease_cohort_id: str | None = None
    lease_cohort_member_count: int | None = None


class LiveInvitationSummary(BaseModel):
    """Invitation summary for live page – invite states indicate stay status."""
    invitation_code: str
    guest_label: str | None  # guest_name or guest_email (no PII beyond what owner entered)
    stay_start_date: date
    stay_end_date: date
    status: str  # pending, accepted, active, expired, cancelled
    token_state: str  # STAGED, BURNED, EXPIRED, REVOKED, CANCELLED
    signed_agreement_available: bool = False
    signed_agreement_url: str | None = None  # GET /public/verify/{invite_id}/signed-agreement
    invitation_kind: str = "guest"  # guest | tenant


class LiveLogEntry(BaseModel):
    """Single audit log entry for property (public view)."""
    category: str
    title: str
    message: str
    created_at: datetime
    # Attribution from actor_user_id + property (not inferred from message text alone).
    actor_user_id: int | None = None
    actor_role: str | None = None  # owner | property_manager | tenant | guest | admin | system | unknown
    actor_role_label: str | None = None
    actor_name: str | None = None
    actor_email: str | None = None
    event_source: str | None = None
    business_meaning_on_record: str | None = None
    trigger_on_record: str | None = None
    state_change_on_record: str | None = None


class JurisdictionStatuteView(BaseModel):
    """Single statute citation for authority wrap."""
    citation: str
    plain_english: str | None = None


class JurisdictionWrap(BaseModel):
    """Jurisdictional POA wrap: applicable law for this property (by zip/region)."""
    state_name: str
    applicable_statutes: list[JurisdictionStatuteView] = []
    removal_guest_text: str | None = None
    removal_tenant_text: str | None = None
    agreement_type: str | None = None


class LivePropertyPagePayload(BaseModel):
    """Full payload for GET /api/public/live/{slug} – evidence view."""
    has_current_guest: bool
    property: LivePropertyInfo
    owner: LiveOwnerInfo
    property_managers: list[LivePropertyManagerInfo] = []
    current_guest: LiveCurrentGuestInfo | None = None  # first of current_guests (backward compatible)
    current_guests: list[LiveCurrentGuestInfo] = []  # all active guest authorizations for this property
    last_stay: LiveStaySummary | None = None
    upcoming_stays: list[LiveStaySummary] = []
    invitations: list[LiveInvitationSummary] = []  # invite states → stay status
    logs: list[LiveLogEntry] = []
    # Quick Decision / evidence layer
    authorization_state: str  # ACTIVE | NONE | EXPIRED | REVOKED
    record_id: str  # live_slug for re-verification
    generated_at: datetime
    # Authority layer (Master POA)
    poa_signed_at: datetime | None = None
    poa_signature_id: int | None = None  # for View POA link
    poa_typed_signature: str | None = None  # signature text to display on live page
    # Jurisdictional wrap: applicable law for this property (by zip)
    jurisdiction_wrap: JurisdictionWrap | None = None
    # Occupying tenant(s): same priority as owner/manager occupancy (guest stay > pending invite > manager > tenant)
    current_tenant_assignments: list[LiveTenantAssignmentInfo] = []
    tenant_summary_assignee: str | None = None
    tenant_summary_assignment_period: str | None = None


# --- Verify portal (token = Invitation ID, no auth) ---


class VerifyRequest(BaseModel):
    """Request for POST /public/verify. Token ID = invitation code (Invite ID)."""
    token_id: str  # Invitation code (e.g. INV-XXXX)
    property_address: str | None = None  # Optional; when provided, must match property for this token
    name: str | None = None  # Optional; logged only
    phone: str | None = None  # Optional; logged only


class VerifyAssignedTenant(BaseModel):
    """Tenant assigned to a unit (name only on verify; presence is not public)."""
    name: str


class VerifyGuestAuthorization(BaseModel):
    """Archived / historical guest authorization record."""
    authorization_number: int
    guest_name: str
    start_date: date | None = None
    end_date: date | None = None
    status: str  # ACTIVE | REVOKED | EXPIRED | CANCELLED | COMPLETED | PENDING
    revoked_at: datetime | None = None
    expired_at: date | None = None
    cancelled_at: datetime | None = None
    checked_out_at: datetime | None = None


class VerifyResponse(BaseModel):
    """Response for POST /public/verify. Read-only, live state. Full record returned whenever invitation/stay exists."""
    valid: bool
    reason: str | None = None
    property_name: str | None = None
    property_address: str | None = None
    occupancy_status: str | None = None
    token_state: str | None = None
    stay_start_date: date | None = None
    stay_end_date: date | None = None
    guest_name: str | None = None
    poa_signed_at: datetime | None = None
    live_slug: str | None = None
    generated_at: datetime | None = None
    audit_entries: list[LiveLogEntry] = []
    status: str | None = None  # PENDING | ACTIVE | REVOKED | EXPIRED | CANCELLED | COMPLETED
    checked_in_at: datetime | None = None
    checked_out_at: datetime | None = None
    revoked_at: datetime | None = None
    cancelled_at: datetime | None = None
    signed_agreement_available: bool = False
    signed_agreement_url: str | None = None
    # New: live property status snapshot
    assigned_tenants: list[VerifyAssignedTenant] = []
    poa_url: str | None = None
    ledger_url: str | None = None
    verified_at: datetime | None = None
    verification_source: str = "DocuStay Verification Portal"
    # Authorization archive (all authorizations for this unit, numbered)
    authorization_history: list[VerifyGuestAuthorization] = []
