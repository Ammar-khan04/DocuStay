"""Module F: Legal restrictions & law display (Owner / Guest views)."""
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from app.models.region_rule import StayClassification, RiskLevel


class OwnerInvitationView(BaseModel):
    """Owner view: invitation for dashboard guests list (pending and accepted)."""
    id: int
    invitation_code: str  # Invite ID (used as Stay ID for display)
    property_id: int
    property_name: str
    property_deleted_at: datetime | None = None
    unit_label: str | None = None  # Set for multi-unit properties (tenant/owner guest lists)
    guest_name: str | None = None
    guest_email: str | None
    stay_start_date: date
    stay_end_date: date
    region_code: str
    status: str  # pending, accepted, active, expired, cancelled
    invitation_kind: str = "guest"  # guest | tenant | tenant_cotenant | tenant_extension
    token_state: str = "STAGED"  # STAGED | BURNED | EXPIRED | REVOKED | CANCELLED
    created_at: datetime | None
    is_expired: bool = False  # True when pending and created_at older than 12 hours
    is_demo: bool = False


class GuestPendingInviteView(BaseModel):
    """Guest view: one pending invitation to sign on dashboard."""
    invitation_code: str
    property_name: str
    property_deleted_at: datetime | None = None
    unit_label: str | None = None  # Unit the guest is invited to (e.g. "5" for multi-unit building)
    stay_start_date: date
    stay_end_date: date
    host_name: str | None
    region_code: str
    # When True, guest has sent agreement to Dropbox but not yet completed signing; stay cannot be confirmed until signed
    needs_dropbox_signature: bool = False
    pending_signature_id: int | None = None  # signature_id to poll for completion
    # When set, signature is complete (e.g. just fetched from Dropbox) but invite not yet accepted; frontend can call acceptInvite to create stay
    accept_now_signature_id: int | None = None


class OwnerStayView(BaseModel):
    """Owner view: guest name, dates, region, classification, max stay, risk, applicable laws."""
    stay_id: int  # Real stay PK, or negative invitation id for invitation_only rows (CSV BURNED with no stay)
    property_id: int
    invite_id: str | None = None  # Invitation code (Invite ID) for this stay
    token_state: str | None = None  # STAGED | BURNED | EXPIRED | REVOKED | CANCELLED (from linked invitation)
    invitation_only: bool = False  # True when from CSV BURNED invite with no Stay (tenant has not signed up yet)
    guest_name: str
    property_name: str
    unit_label: str | None = None  # Multi-unit: which unit this stay/invite is for
    stay_start_date: date
    stay_end_date: date
    region_code: str
    legal_classification: StayClassification
    max_stay_allowed_days: int
    risk_indicator: RiskLevel
    applicable_laws: list[str]
    revoked_at: datetime | None = None
    checked_in_at: datetime | None = None  # when set, stay counts as "active" for occupancy and Status Confirmation
    checked_out_at: datetime | None = None
    cancelled_at: datetime | None = None
    usat_token_released_at: datetime | None = None  # when set, this guest can see the USAT token
    dead_mans_switch_enabled: bool = False  # stay end reminders on for this stay (alerts + confirmation flow)
    # Status confirmation: owner must select Unit Vacated | Lease Renewed | Holdover before deadline (stay_end + 48h)
    needs_occupancy_confirmation: bool = False  # True when in confirmation window, no response yet
    show_occupancy_confirmation_ui: bool = False  # True when needs_conf OR property UNCONFIRMED and this stay triggered it
    confirmation_deadline_at: datetime | None = None  # stay_end_date + 48h
    occupancy_confirmation_response: str | None = None  # vacated | renewed | holdover
    property_deleted_at: datetime | None = None


class JurisdictionStatuteInDashboard(BaseModel):
    """One statute from Jurisdiction SOT (citation + plain English)."""
    citation: str
    plain_english: str | None = None


class GuestStayView(BaseModel):
    """Guest view: property, approved dates, region classification, legal notice and laws from Jurisdiction SOT. usat_token when released; vacate_by when revoked.
    agreement_archive: signed agreement on file but no Stay row (stay_id=0), e.g. invitation timed out before accept-invite."""
    stay_id: int
    record_kind: Literal["stay", "agreement_archive"] = "stay"
    agreement_signature_id: int | None = None
    invite_id: str | None = None  # Invite ID (invitation code) for this stay
    token_state: str | None = None  # STAGED | BURNED | EXPIRED | REVOKED | CANCELLED
    property_live_slug: str | None = None  # for building live link URL (#live/<slug>)
    property_name: str
    unit_label: str | None = None  # Unit the guest is invited to (e.g. "5" for multi-unit building)
    approved_stay_start_date: date
    approved_stay_end_date: date
    region_code: str
    region_classification: str
    legal_notice: str = "This stay does not grant tenancy or homestead rights."
    statute_reference: str | None = None
    plain_english_explanation: str | None = None
    applicable_laws: list[str] = []
    # Jurisdiction wrap from SOT (same as live property page): state name, statutes, removal text
    jurisdiction_state_name: str | None = None
    jurisdiction_statutes: list[JurisdictionStatuteInDashboard] = []
    removal_guest_text: str | None = None
    removal_tenant_text: str | None = None
    usat_token: str | None = None
    revoked_at: datetime | None = None
    vacate_by: str | None = None  # ISO datetime: revoked_at + 12 hours
    checked_in_at: datetime | None = None  # when set, stay is "active" (occupancy / Status Confirmation); guest can Check in on or after start date
    checked_out_at: datetime | None = None  # when set, stay is view-only (no Checkout button)
    cancelled_at: datetime | None = None  # when set, stay is view-only (no Cancel stay button)
    # True when invited by a tenant (tenant lane): guest may request extension; notified to inviter only.
    can_request_extension: bool = False
    # Guest-facing copy: property owner (stay owner_id) vs guest who accepted (stay guest_id); archive uses signature guest.
    residence_assigned_by_name: str | None = None
    stay_accepted_by_name: str | None = None
    property_deleted_at: datetime | None = None


class TenantGuestExtensionRequestView(BaseModel):
    """Tenant view: one guest extension request (pending or resolved)."""
    id: int
    stay_id: int
    property_id: int
    property_name: str
    unit_id: int | None = None
    unit_label: str | None = None
    guest_name: str
    guest_email: str
    stay_start_date: date
    stay_end_date: date
    message: str | None = None  # optional note from guest
    status: str  # pending | approved | declined
    created_at: datetime
    responded_at: datetime | None = None
    tenant_note: str | None = None  # optional note to guest when approving/declining


class OwnerAuditLogEntry(BaseModel):
    """Single append-only audit log entry for owner logs view."""
    id: int
    property_id: int | None
    stay_id: int | None
    invitation_id: int | None
    category: str
    title: str
    message: str
    actor_user_id: int | None
    actor_email: str | None  # legacy key: actor display name (full name / User / Guest), not a mailbox
    ip_address: str | None
    created_at: datetime
    property_name: str | None = None  # resolved for display
    # Neutral record disclosure (also summarized in ``message`` for older clients).
    event_source: str | None = None
    business_meaning_on_record: str | None = None
    trigger_on_record: str | None = None
    state_change_on_record: str | None = None

    class Config:
        from_attributes = True


class BillingInvoiceView(BaseModel):
    """Single Stripe invoice for billing tab."""
    id: str
    number: str | None
    description: str | None
    amount_due_cents: int
    amount_paid_cents: int
    currency: str
    status: str  # draft, open, paid, uncollectible, void
    created: datetime
    hosted_invoice_url: str | None = None


class BillingPaymentView(BaseModel):
    """Single payment (paid invoice) for billing tab."""
    invoice_id: str
    amount_cents: int
    currency: str
    paid_at: datetime
    description: str | None = None


class BillingResponse(BaseModel):
    """Invoices and payments for owner billing section."""
    invoices: list[BillingInvoiceView] = []
    payments: list[BillingPaymentView] = []
    can_invite: bool = True  # False until onboarding invoice is paid (when onboarding was charged)
    current_unit_count: int | None = None  # Active properties (for subscription); shown so user sees subscription reflects current count
    current_shield_count: int | None = None  # Properties with Shield on
    subscription_status: str | None = None  # Stripe subscription status (e.g. trialing, active)
    trial_end_at: datetime | None = None  # When the free trial ends (UTC), if applicable
    trial_days_remaining: int | None = None  # Whole calendar days left in trial (UTC dates); only set when trialing


class BillingSyncSubscriptionResponse(BaseModel):
    """Stripe subscription was reconciled with current property count (no-op if already in sync)."""

    ok: bool = True
    properties_billed: int = 0
    monthly_total_cents: int = 0
    per_property_cents: int = 1000
    stripe_modification_requests: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Echo of Stripe API payloads used during sync (debug / console).",
    )


class BillingPortalSessionResponse(BaseModel):
    """URL for Stripe Customer Billing Portal; redirect here so after payment (e.g. Klarna) user returns to our app."""
    url: str


class PortfolioLinkResponse(BaseModel):
    """Owner portfolio public page: slug and hash path for building full URL."""
    portfolio_slug: str
    portfolio_url: str  # e.g. "portfolio/abc123" (hash part without #); frontend builds full URL


class DashboardAlertView(BaseModel):
    """In-platform dashboard alert (required for status changes; email/SMS are optional)."""
    id: int
    alert_type: str
    title: str
    message: str
    severity: str  # info | warning | urgent
    property_id: int | None = None
    stay_id: int | None = None
    invitation_id: int | None = None
    read_at: datetime | None = None
    created_at: datetime
    meta: dict | None = None

    class Config:
        from_attributes = True