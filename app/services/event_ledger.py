"""Event Ledger service. Single source of truth for all platform events.
Every meaningful action writes here; all activity views read from here.

Activity logs are visible to:
- Owners: for all owned properties (GET /dashboard/owner/logs; optional property_id).
- Property managers: for the properties they manage (GET /dashboard/manager/logs; optional property_id).

Logged actions include:
- Tenant invitations (manager/owner invites tenant to register).
- Tenant assignments (tenant accepts invitation; tenant assignment cancelled by tenant). DocuStay does not revoke or expire tenants.
- Guest invitations (owner/manager/tenant creates invite; guest invite accepted/revoked/cancelled).
- Guest authorization changes (stay revoked, formal removal initiated, check-in, check-out).
- Presence/away status changes (away activated/ended; resident temporarily absent, guests authorized, start timestamp).
- System activity events (Shield Mode, Status Confirmation, occupancy confirmed, stay end reminders, overstay, billing, agreements).

Logs create an auditable record of property activity."""
from __future__ import annotations

import enum
import json
import re
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.event_ledger import EventLedger

# Column limits (match model)
_ACTION_TYPE_LEN = 64
_TARGET_OBJECT_TYPE_LEN = 64
_IP_LEN = 64
_USER_AGENT_LEN = 500

# Action types (canonical event names)
ACTION_PROPERTY_CREATED = "PropertyCreated"
ACTION_PROPERTY_UPDATED = "PropertyUpdated"
ACTION_PROPERTY_DELETED = "PropertyDeleted"
ACTION_PROPERTY_REACTIVATED = "PropertyReactivated"
ACTION_PROPERTY_TRANSFER_INVITED = "PropertyTransferInvited"
ACTION_PROPERTY_TRANSFER_ACCEPTED = "PropertyTransferAccepted"
ACTION_PROPERTY_TRANSFER_PRIOR_OWNER = "PropertyTransferPriorOwner"
ACTION_PROPERTY_TRANSFER_INVITATION_EXPIRED = "PropertyTransferInvitationExpired"
ACTION_MANAGER_ASSIGNED = "ManagerAssigned"
ACTION_MANAGER_INVITED = "ManagerInvited"
ACTION_MANAGER_INVITE_ACCEPTED = "ManagerInviteAccepted"
ACTION_MANAGER_INVITATION_EXPIRED = "ManagerInvitationExpired"
ACTION_MANAGER_ONSITE_RESIDENT_ADDED = "ManagerOnsiteResidentAdded"
ACTION_MANAGER_ONSITE_RESIDENT_REMOVED = "ManagerOnsiteResidentRemoved"
ACTION_MANAGER_REMOVED_FROM_PROPERTY = "ManagerRemovedFromProperty"
ACTION_TENANT_INVITED = "TenantInvited"
ACTION_TENANT_ACCEPTED = "TenantAccepted"
ACTION_TENANT_LEASE_EXTENSION_OFFERED = "TenantLeaseExtensionOffered"
ACTION_TENANT_LEASE_EXTENSION_ACCEPTED = "TenantLeaseExtensionAccepted"
ACTION_TENANT_ASSIGNMENT_CANCELLED = "TenantAssignmentCancelled"
ACTION_GUEST_INVITE_CREATED = "GuestInviteCreated"
ACTION_GUEST_INVITE_ACCEPTED = "GuestInviteAccepted"
ACTION_GUEST_INVITE_REVOKED = "GuestInviteRevoked"
ACTION_GUEST_INVITE_CANCELLED = "GuestInviteCancelled"
ACTION_GUEST_CHECK_IN = "GuestCheckIn"
ACTION_GUEST_CHECK_OUT = "GuestCheckOut"
ACTION_TENANT_CHECK_OUT = "TenantCheckOut"
ACTION_STAY_CANCELLED = "StayCancelled"
ACTION_STAY_REVOKED = "StayRevoked"
ACTION_STAY_CREATED = "StayCreated"
ACTION_AWAY_ACTIVATED = "AwayActivated"
ACTION_AWAY_ENDED = "AwayEnded"
ACTION_PRESENCE_STATUS_CHANGED = "PresenceStatusChanged"
ACTION_SHIELD_MODE_ON = "ShieldModeOn"
ACTION_SHIELD_MODE_OFF = "ShieldModeOff"
ACTION_DMS_48H_ALERT = "DMS48hAlert"
ACTION_DMS_URGENT_TODAY = "DMSUrgentToday"
# Owner/manager-issued tenant unit lease (TenantAssignment — no guest Stay row)
ACTION_DMS_48H_TENANT_LEASE = "DMS48hTenantLease"
ACTION_DMS_URGENT_TODAY_TENANT_LEASE = "DMSUrgentTodayTenantLease"
ACTION_DMS_AUTO_EXECUTED = "DMSAutoExecuted"
ACTION_DMS_DISABLED = "DMSDisabled"
ACTION_OVERSTAY_OCCURRED = "OverstayOccurred"
ACTION_UNIT_VACATED = "UnitVacated"
ACTION_LEASE_RENEWED = "LeaseRenewed"
ACTION_HOLDOVER_CONFIRMED = "HoldoverConfirmed"
ACTION_VACANT_MONITORING_NO_RESPONSE = "VacantMonitoringNoResponse"
ACTION_CONFIRMED_STILL_VACANT = "ConfirmedStillVacant"
ACTION_BILLING_INVOICE_PAID = "BillingInvoicePaid"
ACTION_BILLING_INVOICE_CREATED = "BillingInvoiceCreated"
ACTION_BILLING_SUBSCRIPTION_STARTED = "BillingSubscriptionStarted"
ACTION_BILLING_INVOICE_PAYMENT_FAILED = "BillingInvoicePaymentFailed"
ACTION_AGREEMENT_SIGNED = "AgreementSigned"
ACTION_MASTER_POA_SIGNED = "MasterPOASigned"
ACTION_AGREEMENT_SIGN_FAILED = "AgreementSignFailed"
ACTION_VERIFY_ATTEMPT_VALID = "VerifyAttemptValid"
ACTION_VERIFY_ATTEMPT_FAILED = "VerifyAttemptFailed"
ACTION_EMAIL_VERIFICATION_FAILED = "EmailVerificationFailed"
ACTION_ACCEPT_INVITE_FAILED = "AcceptInviteFailed"
ACTION_LOGIN_FAILED = "LoginFailed"
ACTION_USER_LOGGED_IN = "UserLoggedIn"
ACTION_USER_ROLE_CHANGED = "UserRoleChanged"
ACTION_INVITATION_EXPIRED = "InvitationExpired"
ACTION_INVITATION_CREATED = "InvitationCreated"
ACTION_OWNERSHIP_PROOF_UPLOADED = "OwnershipProofUploaded"
ACTION_INVITATION_CREATED_CSV = "InvitationCreatedCSV"
ACTION_TENANT_PENDING_INVITE_EMAIL_SENT = "TenantPendingInviteEmailSent"
ACTION_BULK_UPLOAD_PROPERTY_CREATED = "BulkUploadPropertyCreated"
ACTION_BULK_UPLOAD_PROPERTY_UPDATED = "BulkUploadPropertyUpdated"
ACTION_GUEST_AUTHORIZATION_CREATED = "GuestAuthorizationCreated"
ACTION_GUEST_AUTHORIZATION_ACTIVE = "GuestAuthorizationActive"
ACTION_GUEST_AUTHORIZATION_REVOKED = "GuestAuthorizationRevoked"
ACTION_GUEST_AUTHORIZATION_EXPIRED = "GuestAuthorizationExpired"
ACTION_GUEST_STAY_APPROACHING_END = "GuestStayApproachingEnd"
ACTION_TENANT_GUEST_JURISDICTION_THRESHOLD_APPROACHING = "TenantGuestJurisdictionThresholdApproaching"
ACTION_TENANT_ACCESS_ACTIVATED = "TenantAccessActivated"
ACTION_GUEST_EXTENSION_REQUESTED = "GuestExtensionRequested"
ACTION_GUEST_EXTENSION_APPROVED = "GuestExtensionApproved"
ACTION_GUEST_EXTENSION_DECLINED = "GuestExtensionDeclined"


def invitation_has_csv_bulk_creation_record(db: Session, invitation_id: int | None) -> bool:
    """True when this invitation row was created by CSV bulk upload (ledger: InvitationCreatedCSV)."""
    if invitation_id is None or invitation_id <= 0:
        return False
    return (
        db.query(EventLedger.id)
        .filter(
            EventLedger.invitation_id == invitation_id,
            EventLedger.action_type == ACTION_INVITATION_CREATED_CSV,
        )
        .limit(1)
        .first()
        is not None
    )


# --- Event source classification (Live Link + dashboard audit; stored in meta["event_source"] when set at write time) ---
EVENT_SOURCE_USER_ACTION = "User Action"
EVENT_SOURCE_SYSTEM_ACTION = "System Action"
EVENT_SOURCE_IMPORT_CSV = "Import (CSV)"
EVENT_SOURCE_MODE_SWITCH = "Mode Switch"
EVENT_SOURCE_BACKGROUND_JOB = "Background Job"

PERMITTED_EVENT_SOURCES: frozenset[str] = frozenset(
    {
        EVENT_SOURCE_USER_ACTION,
        EVENT_SOURCE_SYSTEM_ACTION,
        EVENT_SOURCE_IMPORT_CSV,
        EVENT_SOURCE_MODE_SWITCH,
        EVENT_SOURCE_BACKGROUND_JOB,
    }
)

_CSV_IMPORT_ACTIONS: frozenset[str] = frozenset(
    {
        ACTION_INVITATION_CREATED_CSV,
        ACTION_BULK_UPLOAD_PROPERTY_CREATED,
        ACTION_BULK_UPLOAD_PROPERTY_UPDATED,
    }
)

# Scheduled / automated platform paths (no interactive user actor at write time).
_BACKGROUND_JOB_ACTIONS: frozenset[str] = frozenset(
    {
        ACTION_DMS_48H_ALERT,
        ACTION_DMS_URGENT_TODAY,
        ACTION_DMS_AUTO_EXECUTED,
        ACTION_DMS_48H_TENANT_LEASE,
        ACTION_DMS_URGENT_TODAY_TENANT_LEASE,
        ACTION_GUEST_STAY_APPROACHING_END,
        ACTION_GUEST_AUTHORIZATION_EXPIRED,
        ACTION_OVERSTAY_OCCURRED,
        ACTION_BILLING_INVOICE_PAID,
        ACTION_BILLING_INVOICE_CREATED,
        ACTION_BILLING_SUBSCRIPTION_STARTED,
        ACTION_BILLING_INVOICE_PAYMENT_FAILED,
        ACTION_INVITATION_EXPIRED,
        ACTION_MANAGER_INVITATION_EXPIRED,
        ACTION_TENANT_GUEST_JURISDICTION_THRESHOLD_APPROACHING,
        ACTION_VACANT_MONITORING_NO_RESPONSE,
        ACTION_CONFIRMED_STILL_VACANT,
    }
)

# Guest agreement signing often has no actor_user_id until after account linkage; treat as user-driven.
_USER_ACTION_WITHOUT_ACTOR_ACTIONS: frozenset[str] = frozenset(
    {
        ACTION_AGREEMENT_SIGNED,
        ACTION_VERIFY_ATTEMPT_VALID,
        ACTION_VERIFY_ATTEMPT_FAILED,
    }
)


def resolve_event_source_for_entry(entry: EventLedger) -> str:
    """Return one of PERMITTED_EVENT_SOURCES for API and disclosure copy."""
    meta = entry.meta if isinstance(entry.meta, dict) else {}
    raw = meta.get("event_source")
    if isinstance(raw, str) and raw.strip() in PERMITTED_EVENT_SOURCES:
        return raw.strip()
    if meta.get("mode_switch") is True or meta.get("context_mode_switch"):
        return EVENT_SOURCE_MODE_SWITCH
    action = (entry.action_type or "").strip()
    if action in _CSV_IMPORT_ACTIONS:
        return EVENT_SOURCE_IMPORT_CSV
    if action in _BACKGROUND_JOB_ACTIONS:
        return EVENT_SOURCE_BACKGROUND_JOB
    if entry.actor_user_id:
        return EVENT_SOURCE_USER_ACTION
    if action in _USER_ACTION_WITHOUT_ACTOR_ACTIONS:
        return EVENT_SOURCE_USER_ACTION
    return EVENT_SOURCE_SYSTEM_ACTION


def _compact_json_for_audit_blob(v: Any, max_len: int = 320) -> str:
    if v is None:
        return ""
    try:
        s = json.dumps(v, default=str, ensure_ascii=True)
    except Exception:
        s = str(v)
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def summarize_state_change_for_ledger(
    previous_value: dict[str, Any] | None,
    new_value: dict[str, Any] | None,
) -> str | None:
    """One-line description of prior/new JSON on the ledger row, if any."""
    ps = _compact_json_for_audit_blob(previous_value)
    ns = _compact_json_for_audit_blob(new_value)
    if not ps and not ns:
        return None
    if ps and ns:
        return f"Prior stored values: {ps} → New stored values: {ns}"
    if ns:
        return f"New stored values: {ns}"
    return f"Prior stored values: {ps} (cleared or superseded)"


def ledger_record_disclosure_lines(entry: EventLedger, *, display_title: str) -> dict[str, str | None]:
    """Structured disclosure fields for audit APIs and Live Link timeline."""
    meta = entry.meta if isinstance(entry.meta, dict) else {}
    event_source = resolve_event_source_for_entry(entry)
    bm = meta.get("business_meaning")
    if isinstance(bm, str) and bm.strip():
        business_meaning = bm.strip()
    else:
        business_meaning = (
            f"The append-only log records this event: {display_title}."
            if display_title
            else "The append-only log records this event."
        )
    trig = meta.get("trigger_description")
    trigger = trig.strip() if isinstance(trig, str) and trig.strip() else None
    state_line = summarize_state_change_for_ledger(
        entry.previous_value if isinstance(entry.previous_value, dict) else None,
        entry.new_value if isinstance(entry.new_value, dict) else None,
    )
    return {
        "event_source": event_source,
        "business_meaning_on_record": business_meaning,
        "trigger_on_record": trigger,
        "state_change_on_record": state_line,
    }


def append_ledger_disclosure_to_message(message: str, entry: EventLedger, *, display_title: str) -> str:
    """Append state snapshot, explicit writer-supplied meaning/trigger, and event source (keeps body readable)."""
    d = ledger_record_disclosure_lines(entry, display_title=display_title)
    meta = entry.meta if isinstance(entry.meta, dict) else {}
    parts: list[str] = [message.rstrip()]
    if d.get("state_change_on_record"):
        parts.append(f"State change on record: {d['state_change_on_record']}")
    bm = meta.get("business_meaning")
    if isinstance(bm, str) and bm.strip():
        parts.append(f"Business meaning on record: {bm.strip()}")
    trig = meta.get("trigger_description")
    if isinstance(trig, str) and trig.strip():
        parts.append(f"Trigger on record: {trig.strip()}")
    parts.append(f"Event source: {d['event_source']}.")
    return "\n\n".join(p for p in parts if p)


def _sanitize_json_value(v: Any) -> Any:
    """Convert to JSON-serializable value."""
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, enum.Enum):
        return getattr(v, "value", str(v))
    if isinstance(v, dict):
        return {str(k): _sanitize_json_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_sanitize_json_value(x) for x in v]
    return str(v)


def _sanitize_meta(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    if meta is None:
        return None
    try:
        return {str(k): _sanitize_json_value(v) for k, v in meta.items()}
    except Exception:
        return {"_error": "meta_serialization", "raw_keys": list(meta.keys())[:10]}


# Mapping: action_type -> (category, title) for backward-compatible display
_ACTION_DISPLAY: dict[str, tuple[str, str]] = {
    ACTION_PROPERTY_CREATED: ("status_change", "Property registered"),
    ACTION_BULK_UPLOAD_PROPERTY_CREATED: ("status_change", "CSV bulk upload: property added"),
    ACTION_BULK_UPLOAD_PROPERTY_UPDATED: ("status_change", "CSV bulk upload: property updated"),
    ACTION_PROPERTY_UPDATED: ("status_change", "Property updated"),
    ACTION_PROPERTY_DELETED: ("status_change", "Property deleted"),
    ACTION_PROPERTY_REACTIVATED: ("status_change", "Property reactivated"),
    ACTION_PROPERTY_TRANSFER_INVITED: ("status_change", "Property ownership transfer invited"),
    ACTION_PROPERTY_TRANSFER_ACCEPTED: ("status_change", "Property ownership transferred"),
    ACTION_PROPERTY_TRANSFER_PRIOR_OWNER: ("status_change", "Property ownership transferred (you transferred out)"),
    ACTION_PROPERTY_TRANSFER_INVITATION_EXPIRED: ("status_change", "Property transfer invitation expired"),
    ACTION_MANAGER_ASSIGNED: ("tenant_assignment", "Manager assigned"),
    ACTION_MANAGER_INVITED: ("tenant_assignment", "Property manager invited"),
    ACTION_MANAGER_INVITE_ACCEPTED: ("tenant_assignment", "Property manager invite accepted"),
    ACTION_TENANT_INVITED: ("status_change", "Invitation created"),
    ACTION_TENANT_ACCEPTED: ("status_change", "Tenant assignment accepted"),
    ACTION_TENANT_LEASE_EXTENSION_OFFERED: ("status_change", "Tenant lease extension offered"),
    ACTION_TENANT_LEASE_EXTENSION_ACCEPTED: ("status_change", "Tenant lease extension accepted"),
    ACTION_TENANT_ASSIGNMENT_CANCELLED: ("status_change", "Tenant assignment cancelled"),
    ACTION_GUEST_INVITE_CREATED: ("status_change", "Invitation created"),
    ACTION_GUEST_INVITE_ACCEPTED: ("status_change", "Invitation accepted"),
    ACTION_GUEST_INVITE_REVOKED: ("status_change", "Invitation revoked"),
    ACTION_GUEST_INVITE_CANCELLED: ("status_change", "Invitation cancelled"),
    ACTION_GUEST_CHECK_IN: ("status_change", "Guest checked in"),
    ACTION_GUEST_CHECK_OUT: ("status_change", "Guest checked out"),
    ACTION_TENANT_CHECK_OUT: ("status_change", "Tenant checked out"),
    ACTION_STAY_CANCELLED: ("status_change", "Stay cancelled by guest"),
    ACTION_STAY_REVOKED: ("status_change", "Stay revoked"),
    ACTION_STAY_CREATED: ("status_change", "Stay created"),
    ACTION_AWAY_ACTIVATED: ("presence", "Away status activated"),
    ACTION_AWAY_ENDED: ("presence", "Away status ended"),
    ACTION_PRESENCE_STATUS_CHANGED: ("presence", "Presence status changed"),
    ACTION_SHIELD_MODE_ON: ("shield_mode", "Shield Mode turned on"),
    ACTION_SHIELD_MODE_OFF: ("shield_mode", "Shield Mode turned off"),
    ACTION_DMS_48H_ALERT: ("dead_mans_switch", "Status Confirmation: 48h before lease end"),
    ACTION_DMS_URGENT_TODAY: ("dead_mans_switch", "Status Confirmation: lease ends today"),
    ACTION_DMS_AUTO_EXECUTED: ("dead_mans_switch", "Status Confirmation: no response – occupancy unknown"),
    ACTION_DMS_DISABLED: ("dead_mans_switch", "Status Confirmation reminders turned off"),
    ACTION_OVERSTAY_OCCURRED: ("status_change", "Overstay occurred"),
    ACTION_UNIT_VACATED: ("status_change", "Owner confirmed: Unit Vacated"),
    ACTION_LEASE_RENEWED: ("status_change", "Owner confirmed: Lease Renewed"),
    ACTION_HOLDOVER_CONFIRMED: ("status_change", "Owner confirmed: Holdover"),
    ACTION_VACANT_MONITORING_NO_RESPONSE: ("status_change", "Vacant monitoring: no response – status UNCONFIRMED"),
    ACTION_CONFIRMED_STILL_VACANT: ("status_change", "Owner confirmed still vacant"),
    ACTION_BILLING_INVOICE_PAID: ("billing", "Invoice paid"),
    ACTION_BILLING_INVOICE_CREATED: ("billing", "Invoice created"),
    ACTION_BILLING_SUBSCRIPTION_STARTED: ("billing", "Subscription started (free trial)"),
    ACTION_BILLING_INVOICE_PAYMENT_FAILED: ("billing", "Payment failed"),
    ACTION_AGREEMENT_SIGNED: ("guest_signature", "Agreement signed"),
    ACTION_MASTER_POA_SIGNED: ("status_change", "Master POA signed"),
    ACTION_AGREEMENT_SIGN_FAILED: ("failed_attempt", "Agreement sign failed"),
    ACTION_VERIFY_ATTEMPT_VALID: ("verify_attempt", "Verify attempt – valid"),
    ACTION_VERIFY_ATTEMPT_FAILED: ("failed_attempt", "Verify attempt – failed"),
    ACTION_EMAIL_VERIFICATION_FAILED: ("failed_attempt", "Email verification failed"),
    ACTION_ACCEPT_INVITE_FAILED: ("failed_attempt", "Accept invite failed"),
    ACTION_LOGIN_FAILED: ("failed_attempt", "Login failed"),
    ACTION_USER_LOGGED_IN: ("status_change", "User logged in"),
    ACTION_USER_ROLE_CHANGED: ("status_change", "User role changed"),
    ACTION_INVITATION_EXPIRED: ("status_change", "Invitation expired (not accepted in time)"),
    ACTION_MANAGER_INVITATION_EXPIRED: ("status_change", "Manager invitation expired (link not used in time)"),
    ACTION_INVITATION_CREATED: ("status_change", "Invitation created"),
    ACTION_OWNERSHIP_PROOF_UPLOADED: ("status_change", "Ownership proof uploaded"),
    ACTION_INVITATION_CREATED_CSV: ("status_change", "CSV bulk upload: tenant invitation created"),
    ACTION_TENANT_PENDING_INVITE_EMAIL_SENT: ("status_change", "Pending tenant: invitation email sent"),
    ACTION_GUEST_AUTHORIZATION_CREATED: ("status_change", "Guest authorization created"),
    ACTION_GUEST_AUTHORIZATION_ACTIVE: ("status_change", "Guest authorization active"),
    ACTION_GUEST_AUTHORIZATION_REVOKED: ("status_change", "Guest authorization revoked"),
    ACTION_GUEST_AUTHORIZATION_EXPIRED: ("status_change", "Guest authorization expired"),
    ACTION_GUEST_STAY_APPROACHING_END: ("status_change", "Stay approaching end date"),
    ACTION_TENANT_GUEST_JURISDICTION_THRESHOLD_APPROACHING: ("status_change", "Guest stay approaching jurisdiction threshold"),
    ACTION_TENANT_ACCESS_ACTIVATED: ("status_change", "Tenant access activated"),
    ACTION_GUEST_EXTENSION_REQUESTED: ("status_change", "Guest requested stay extension"),
    ACTION_GUEST_EXTENSION_APPROVED: ("status_change", "Host approved stay extension request"),
    ACTION_GUEST_EXTENSION_DECLINED: ("status_change", "Host declined stay extension request"),
    ACTION_MANAGER_ONSITE_RESIDENT_ADDED: ("tenant_assignment", "Manager added as on-site resident"),
    ACTION_MANAGER_ONSITE_RESIDENT_REMOVED: ("tenant_assignment", "Manager removed as on-site resident"),
    ACTION_MANAGER_REMOVED_FROM_PROPERTY: ("tenant_assignment", "Manager removed from property"),
}

_CATEGORY_TO_ACTION_TYPES: dict[str, list[str]] = {
    k: [a for a in _ACTION_DISPLAY if _ACTION_DISPLAY[a][0] == k]
    for k in {"status_change", "guest_signature", "failed_attempt", "shield_mode", "dead_mans_switch", "billing", "verify_attempt", "presence", "tenant_assignment"}
}

# Match email-shaped tokens in ledger copy so timelines can show names instead of raw addresses.
_EMAIL_IN_TEXT_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# Match ISO 8601 timestamps embedded in message text so they render as "Apr 16, 2026, 7:09 PM".
_ISO_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)"
)


def format_dt_display(dt_val: datetime | None) -> str:
    """Format a datetime as 'Apr 16, 2026, 7:09 PM' for human-readable timeline display."""
    if dt_val is None:
        return "\u2014"
    formatted = dt_val.strftime("%b %d, %Y, %I:%M %p")
    # Strip leading zero from hour: "07:09 PM" -> "7:09 PM"
    parts = formatted.rsplit(", ", 1)
    if len(parts) == 2 and parts[1].startswith("0"):
        parts[1] = parts[1][1:]
    return ", ".join(parts)


def _humanize_iso_timestamps(text: str) -> str:
    """Replace raw ISO timestamps in display text with human-readable format."""
    if not text:
        return text

    def _repl(m: re.Match[str]) -> str:
        try:
            dt = datetime.fromisoformat(m.group(0))
            return format_dt_display(dt)
        except (ValueError, TypeError):
            return m.group(0)

    return _ISO_TIMESTAMP_RE.sub(_repl, text)


def _display_name_for_email(
    db: Session,
    email: str,
    *,
    invitation_id: int | None = None,
) -> str:
    """Resolve a mailbox string to a person label for audit display (never returns the email)."""
    em = (email or "").strip()
    if not em:
        return "Guest"
    from app.models.invitation import Invitation
    from app.models.user import User

    if invitation_id is not None:
        inv_row = db.query(Invitation).filter(Invitation.id == invitation_id).first()
        if inv_row and (inv_row.guest_email or "").strip().lower() == em.lower():
            gn = (inv_row.guest_name or "").strip()
            if gn:
                return gn

    u = db.query(User).filter(func.lower(User.email) == em.lower()).first()
    if u:
        fn = (u.full_name or "").strip()
        if fn:
            return fn
    inv = (
        db.query(Invitation)
        .filter(func.lower(Invitation.guest_email) == em.lower())
        .order_by(Invitation.created_at.desc())
        .first()
    )
    if inv:
        gn = (inv.guest_name or "").strip()
        if gn:
            return gn
    return "Guest"


def _scrub_emails_for_timeline_display(db: Session, text: str) -> str:
    """Replace embedded emails in timeline title/message with display names when resolvable."""
    if not text:
        return text

    def repl(m: re.Match[str]) -> str:
        return _display_name_for_email(db, m.group(0))

    return _EMAIL_IN_TEXT_RE.sub(repl, text)


def _scrub_dms_word_from_display(text: str) -> str:
    """Remove the substring ``dms`` as a word/token from timeline copy; do not drop the event."""
    if not text:
        return text
    out = re.sub(r"\bdms[\w.-]*\b", "", text, flags=re.IGNORECASE)
    return " ".join(out.split())


# ---------------------------------------------------------------------------
# Privacy-lane action type sets
# ---------------------------------------------------------------------------

OWNER_BUSINESS_ACTIONS: set[str] = {
    ACTION_PROPERTY_CREATED,
    ACTION_BULK_UPLOAD_PROPERTY_CREATED,
    ACTION_BULK_UPLOAD_PROPERTY_UPDATED,
    ACTION_PROPERTY_UPDATED,
    ACTION_PROPERTY_DELETED,
    ACTION_PROPERTY_REACTIVATED,
    ACTION_PROPERTY_TRANSFER_INVITED,
    ACTION_PROPERTY_TRANSFER_ACCEPTED,
    ACTION_PROPERTY_TRANSFER_PRIOR_OWNER,
    ACTION_PROPERTY_TRANSFER_INVITATION_EXPIRED,
    ACTION_MANAGER_ASSIGNED,
    ACTION_MANAGER_INVITED,
    ACTION_MANAGER_INVITE_ACCEPTED,
    ACTION_MANAGER_INVITATION_EXPIRED,
    ACTION_MANAGER_ONSITE_RESIDENT_ADDED,
    ACTION_MANAGER_ONSITE_RESIDENT_REMOVED,
    ACTION_MANAGER_REMOVED_FROM_PROPERTY,
    ACTION_TENANT_INVITED,
    ACTION_TENANT_ACCEPTED,
    ACTION_TENANT_LEASE_EXTENSION_OFFERED,
    ACTION_TENANT_LEASE_EXTENSION_ACCEPTED,
    ACTION_TENANT_ASSIGNMENT_CANCELLED,
    ACTION_TENANT_ACCESS_ACTIVATED,
    ACTION_TENANT_CHECK_OUT,
    ACTION_SHIELD_MODE_ON, ACTION_SHIELD_MODE_OFF,
    ACTION_DMS_48H_ALERT,
    ACTION_DMS_URGENT_TODAY,
    ACTION_DMS_AUTO_EXECUTED,
    ACTION_DMS_DISABLED,
    ACTION_BILLING_INVOICE_PAID,
    ACTION_BILLING_INVOICE_CREATED,
    ACTION_BILLING_SUBSCRIPTION_STARTED,
    ACTION_BILLING_INVOICE_PAYMENT_FAILED,
    ACTION_OWNERSHIP_PROOF_UPLOADED,
    ACTION_INVITATION_CREATED_CSV,
    ACTION_TENANT_PENDING_INVITE_EMAIL_SENT,
    ACTION_UNIT_VACATED, ACTION_LEASE_RENEWED, ACTION_HOLDOVER_CONFIRMED,
    ACTION_VACANT_MONITORING_NO_RESPONSE, ACTION_CONFIRMED_STILL_VACANT,
    ACTION_MASTER_POA_SIGNED,
    ACTION_OVERSTAY_OCCURRED,
    ACTION_INVITATION_EXPIRED,
    # Property/management-lane guest stays: visible after privacy filter (tenant-lane revokes excluded).
    ACTION_STAY_REVOKED,
}

# Personal-mode additions: guest activity the owner/manager initiated on their owner-occupied properties
OWNER_PERSONAL_GUEST_ACTIONS: set[str] = {
    ACTION_GUEST_INVITE_CREATED, ACTION_GUEST_INVITE_ACCEPTED, ACTION_GUEST_INVITE_REVOKED,
    ACTION_GUEST_INVITE_CANCELLED,
    ACTION_GUEST_CHECK_IN, ACTION_GUEST_CHECK_OUT,
    ACTION_STAY_CREATED, ACTION_STAY_CANCELLED, ACTION_STAY_REVOKED,
    ACTION_AGREEMENT_SIGNED,
    ACTION_INVITATION_CREATED,
    ACTION_GUEST_AUTHORIZATION_CREATED, ACTION_GUEST_AUTHORIZATION_ACTIVE,
    ACTION_GUEST_AUTHORIZATION_REVOKED,     ACTION_GUEST_AUTHORIZATION_EXPIRED,
}

# Owner/manager Personal mode (Event ledger + Notifications panel): guest-residence lane only — not portfolio,
# tenants, managers, billing, property CRUD, shield/vacant bulk ops, POA, CSV, etc. (aligned with tenant privacy,
# plus Status Confirmation/overstay for the home where they host guests.) Tenant/resident presence is tenant-lane only.
OWNER_PERSONAL_MODE_LEDGER_ACTIONS: set[str] = set(OWNER_PERSONAL_GUEST_ACTIONS) | {
    ACTION_DMS_48H_ALERT,
    ACTION_DMS_URGENT_TODAY,
    ACTION_DMS_AUTO_EXECUTED,
    ACTION_DMS_DISABLED,
    ACTION_OVERSTAY_OCCURRED,
    ACTION_INVITATION_EXPIRED,
    ACTION_GUEST_EXTENSION_REQUESTED,
    ACTION_GUEST_EXTENSION_APPROVED,
    ACTION_GUEST_EXTENSION_DECLINED,
}

OWNER_PERSONAL_ACTIONS: set[str] = OWNER_PERSONAL_MODE_LEDGER_ACTIONS

TENANT_ALLOWED_ACTIONS: set[str] = {
    ACTION_GUEST_INVITE_CREATED, ACTION_GUEST_INVITE_ACCEPTED, ACTION_GUEST_INVITE_REVOKED,
    ACTION_GUEST_INVITE_CANCELLED,
    ACTION_GUEST_CHECK_IN, ACTION_GUEST_CHECK_OUT,
    ACTION_STAY_CANCELLED, ACTION_STAY_REVOKED, ACTION_STAY_CREATED,
    ACTION_AWAY_ACTIVATED, ACTION_AWAY_ENDED, ACTION_PRESENCE_STATUS_CHANGED,
    ACTION_TENANT_ACCEPTED,
    ACTION_TENANT_LEASE_EXTENSION_ACCEPTED,
    ACTION_TENANT_ASSIGNMENT_CANCELLED,
    ACTION_TENANT_CHECK_OUT,
    ACTION_TENANT_ACCESS_ACTIVATED,
    ACTION_AGREEMENT_SIGNED,
    ACTION_INVITATION_EXPIRED,
    ACTION_INVITATION_CREATED,
    ACTION_GUEST_AUTHORIZATION_CREATED, ACTION_GUEST_AUTHORIZATION_ACTIVE,
    ACTION_GUEST_AUTHORIZATION_REVOKED,     ACTION_GUEST_AUTHORIZATION_EXPIRED,
    ACTION_USER_LOGGED_IN,
    ACTION_GUEST_EXTENSION_REQUESTED,
    ACTION_GUEST_EXTENSION_APPROVED,
    ACTION_GUEST_EXTENSION_DECLINED,
    ACTION_TENANT_GUEST_JURISDICTION_THRESHOLD_APPROACHING,
}

GUEST_ALLOWED_ACTIONS: set[str] = {
    ACTION_GUEST_INVITE_CREATED,
    ACTION_INVITATION_CREATED,
    ACTION_INVITATION_EXPIRED,
    ACTION_GUEST_INVITE_ACCEPTED,
    ACTION_GUEST_INVITE_REVOKED,
    ACTION_GUEST_INVITE_CANCELLED,
    ACTION_GUEST_CHECK_IN, ACTION_GUEST_CHECK_OUT,
    ACTION_STAY_CANCELLED, ACTION_STAY_REVOKED, ACTION_STAY_CREATED,
    ACTION_AGREEMENT_SIGNED,
    ACTION_GUEST_AUTHORIZATION_CREATED, ACTION_GUEST_AUTHORIZATION_ACTIVE,
    ACTION_GUEST_AUTHORIZATION_REVOKED, ACTION_GUEST_AUTHORIZATION_EXPIRED,
    ACTION_GUEST_STAY_APPROACHING_END,
    ACTION_OVERSTAY_OCCURRED,
    ACTION_VERIFY_ATTEMPT_VALID,
    ACTION_AWAY_ACTIVATED, ACTION_AWAY_ENDED,     ACTION_PRESENCE_STATUS_CHANGED,
    ACTION_GUEST_EXTENSION_REQUESTED,
    ACTION_GUEST_EXTENSION_APPROVED,
    ACTION_GUEST_EXTENSION_DECLINED,
}


def get_actor_email(db: Session, actor_user_id: int | None) -> str | None:
    """API field name is legacy; returns actor display name for logs/alerts (never raw mailbox)."""
    return get_actor_display_name(db, actor_user_id)


def get_actor_display_name(db: Session, actor_user_id: int | None) -> str | None:
    """Resolve actor full name for ledger / timeline display (never falls back to email)."""
    if not actor_user_id:
        return None
    from app.models.user import User
    u = db.query(User).filter(User.id == actor_user_id).first()
    if not u:
        return None
    fn = (u.full_name or "").strip()
    return fn or "User"


def ledger_event_to_display(entry: EventLedger, db: Session | None = None) -> tuple[str, str, str]:
    """Map ledger entry to (category, title, message) for OwnerAuditLogEntry / LiveLogEntry.
    When db is provided and message is generic, appends ' by <actor name>' for attribution.
    Timelines avoid showing raw email addresses; names are preferred, then neutral labels (Guest / User).

    Agreement-signed events often have no actor_user_id (guest signs before account exists); signer is taken
    from meta guest_full_name / guest_email."""
    action = entry.action_type or ""
    cat, title = _ACTION_DISPLAY.get(
        action,
        ("status_change", entry.action_type or "—"),
    )
    meta = entry.meta if isinstance(entry.meta, dict) else {}
    has_custom_message = bool(meta.get("message"))

    if cat == "presence" and db and entry.actor_user_id:
        actor_name = get_actor_display_name(db, entry.actor_user_id)
        if actor_name:
            title = f"{title} — {actor_name}"

    if action == ACTION_AGREEMENT_SIGNED:
        name = (meta.get("guest_full_name") or "").strip()
        email = (meta.get("guest_email") or "").strip()
        if name:
            title = f"{title} — {name}"
            msg = f"Signed by {name}"
        elif email:
            signer = (
                _display_name_for_email(db, email, invitation_id=entry.invitation_id)
                if db
                else "Guest"
            )
            title = f"{title} — {signer}"
            msg = f"Signed by {signer}"
        elif has_custom_message:
            msg = str(meta["message"])
        elif meta.get("property_name"):
            msg = f"{title} for {meta['property_name']}"
        else:
            msg = title
    elif has_custom_message:
        msg = str(meta["message"])
    elif meta.get("property_name"):
        msg = f"{title} for {meta['property_name']}"
    else:
        msg = title
    # User attribution: only append to generic messages so custom body stays separate from actor line
    if action != ACTION_AGREEMENT_SIGNED and not has_custom_message and db and entry.actor_user_id:
        actor_name = get_actor_display_name(db, entry.actor_user_id)
        if actor_name and f"by {actor_name}" not in msg:
            msg = f"{msg} by {actor_name}"

    if db:
        title = _scrub_emails_for_timeline_display(db, title)
        msg = _scrub_emails_for_timeline_display(db, msg)

    title = _scrub_dms_word_from_display(title)
    msg = _scrub_dms_word_from_display(msg)

    title = _humanize_iso_timestamps(title)
    msg = _humanize_iso_timestamps(msg)

    msg = append_ledger_disclosure_to_message(msg, entry, display_title=title)

    return (cat, title, msg)


def create_ledger_event(
    db: Session,
    action_type: str,
    *,
    target_object_type: str | None = None,
    target_object_id: int | None = None,
    property_id: int | None = None,
    unit_id: int | None = None,
    stay_id: int | None = None,
    invitation_id: int | None = None,
    actor_user_id: int | None = None,
    previous_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    event_source: str | None = None,
    business_meaning: str | None = None,
    trigger_description: str | None = None,
) -> EventLedger | None:
    """Append one immutable ledger event. All timestamps are UTC (server_default).
    Returns None when the property is inactive (soft-deleted)."""
    from app.services.property_scope import suppress_new_audit_for_inactive_property

    if suppress_new_audit_for_inactive_property(
        db, property_id=property_id, stay_id=stay_id, invitation_id=invitation_id
    ):
        return None
    action = (action_type or "")[:_ACTION_TYPE_LEN].strip() or "Unknown"
    target_type = (target_object_type or "")[:_TARGET_OBJECT_TYPE_LEN].strip() or None
    ip = (ip_address[: _IP_LEN] if ip_address else None) or None
    ua = (str(user_agent)[: _USER_AGENT_LEN] if user_agent else None) or None
    safe_meta = _sanitize_meta(meta) or {}
    if event_source and str(event_source).strip() in PERMITTED_EVENT_SOURCES:
        safe_meta["event_source"] = str(event_source).strip()
    if business_meaning and str(business_meaning).strip():
        safe_meta["business_meaning"] = str(business_meaning).strip()
    if trigger_description and str(trigger_description).strip():
        safe_meta["trigger_description"] = str(trigger_description).strip()
    safe_meta = safe_meta or None
    safe_prev = _sanitize_meta(previous_value)
    safe_new = _sanitize_meta(new_value)

    entry = EventLedger(
        action_type=action,
        target_object_type=target_type,
        target_object_id=target_object_id,
        property_id=property_id,
        unit_id=unit_id,
        stay_id=stay_id,
        invitation_id=invitation_id,
        actor_user_id=actor_user_id,
        previous_value=safe_prev,
        new_value=safe_new,
        meta=safe_meta,
        ip_address=ip,
        user_agent=ua,
    )
    db.add(entry)
    db.flush()
    return entry
