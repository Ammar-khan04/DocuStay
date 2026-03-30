"""Module B1: Owner onboarding."""
import csv
import logging
import io
import secrets
from datetime import date, datetime, timezone, timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, EmailStr, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User, UserRole
from app.models.owner import OwnerProfile, Property, PropertyType, USAT_TOKEN_STAGED, USAT_TOKEN_RELEASED, OccupancyStatus
from app.models.invitation import Invitation
from app.models.agreement_signature import AgreementSignature
from app.models.guest import PurposeOfStay, RelationshipToOwner
from app.models.manager_invitation import ManagerInvitation, MANAGER_INVITE_EXPIRE_DAYS
from app.models.property_manager_assignment import PropertyManagerAssignment
from app.schemas.owner import (
    AuthorityLetterResponse,
    BulkUploadResult,
    EmailProvidersResponse,
    OwnerConfigResponse,
    PendingProviderResponse,
    PropertyCreate,
    PropertyResponse,
    PropertyUpdate,
    PropertyUtilityProvidersResponse,
    SetPropertyUtilitiesRequest,
    StandardizedAddressResponse,
    UtilityOptionItem,
    UtilityProviderResponse,
    VerifyAddressAndUtilitiesResponse,
    VerifyAddressRequest,
)
from app.dependencies import get_current_user, require_owner, require_owner_onboarding_complete, get_context_mode
from app.models.stay import Stay
from app.models.unit import Unit
from app.models.guest import GuestProfile
from app.models.resident_mode import ResidentMode, ResidentModeType
from app.models.resident_presence import ResidentPresence
from app.models.tenant_assignment import TenantAssignment
from app.services.audit_log import create_log, CATEGORY_STATUS_CHANGE, CATEGORY_SHIELD_MODE
from app.services.event_ledger import (
    create_ledger_event,
    ACTION_PROPERTY_CREATED,
    ACTION_BULK_UPLOAD_PROPERTY_CREATED,
    ACTION_BULK_UPLOAD_PROPERTY_UPDATED,
    ACTION_MANAGER_INVITED,
    ACTION_PROPERTY_UPDATED,
    ACTION_PROPERTY_DELETED,
    ACTION_PROPERTY_REACTIVATED,
    ACTION_SHIELD_MODE_ON,
    ACTION_SHIELD_MODE_OFF,
    ACTION_GUEST_INVITE_CREATED,
    ACTION_INVITATION_CREATED_CSV,
    ACTION_TENANT_PENDING_INVITE_EMAIL_SENT,
    ACTION_OWNERSHIP_PROOF_UPLOADED,
    ACTION_TENANT_INVITED,
    ACTION_MANAGER_ONSITE_RESIDENT_ADDED,
    ACTION_MANAGER_ONSITE_RESIDENT_REMOVED,
    ACTION_MANAGER_REMOVED_FROM_PROPERTY,
)
from app.services.invitation_guest_completion import (
    guest_invite_awaiting_account_after_sign,
    guest_invitation_signing_started,
)
from app.services.smarty import verify_address
from app.services.utility_lookup import lookup_utility_providers, generate_authority_letters, _provider_to_raw
from app.services.utility_lookup import UtilityProvider
from app.models.property_utility import PropertyUtilityProvider, PropertyAuthorityLetter
from app.background_jobs import submit_utility_job
from app.services.provider_contact_search import run_provider_contact_lookup_job
from app.services.census_geocoder import geocode_coordinates
from app.utility_providers.pending_provider_verification_job import run_pending_provider_verification_job
from app.utility_providers.sqlite_cache import add_pending_provider, get_pending_providers_for_property
from app.config import get_settings

logger = logging.getLogger(__name__)
from app.services.authority_letter_email import send_authority_letter_to_provider
from app.services.notifications import (
    send_manager_invite_email,
    send_shield_mode_turned_on_notification,
    send_shield_mode_turned_off_notification,
    send_dead_mans_switch_enabled_notification,
    send_tenant_invite_email,
)
from app.services.dropbox_sign import get_signed_pdf
from app.services.billing import on_onboarding_properties_completed, ensure_subscription, sync_subscription_quantities
from app.services.shield_mode_policy import SHIELD_MODE_ALWAYS_ON, persisted_shield_row_int
from app.services.permissions import can_perform_action, can_assign_property_manager, Action, can_access_property, get_owner_personal_mode_units
from app.services.manager_resident import add_manager_onsite_resident, remove_manager_onsite_resident
from app.services.jle import validate_stay_duration_for_property, get_max_stay_days_for_property
from app.services.occupancy import (
    get_unit_display_occupancy_status,
    get_property_display_occupancy_status,
    get_units_occupancy_display,
)

router = APIRouter(prefix="/owners", tags=["owners"])

_PURPOSE_MAP = {"visit": PurposeOfStay.travel, "vacation": PurposeOfStay.travel, "caregiving": PurposeOfStay.personal, "house_sitting": PurposeOfStay.personal}
_REL_MAP = {"friend": RelationshipToOwner.friend, "family": RelationshipToOwner.family, "acquaintance": RelationshipToOwner.other, "tenant_applicant": RelationshipToOwner.other}


class InvitationCreate(BaseModel):
    owner_id: str | None = None
    property_id: int | None = None
    unit_id: int | None = None  # Required for tenant/manager; optional for owner (inferred for single-unit)
    invited_by_user_id: int | None = None  # Set by backend from current_user
    guest_name: str = ""
    guest_email: EmailStr = Field(..., description="Guest email (required); only this address can accept the invite")
    guest_phone: str = ""

    @field_validator("guest_email", mode="before")
    @classmethod
    def _strip_guest_email(cls, v: object) -> str:
        if v is None:
            raise ValueError("Guest email is required")
        s = str(v).strip()
        if not s:
            raise ValueError("Guest email is required")
        return s
    relationship: str = "friend"
    purpose: str = "visit"
    checkin_date: str = ""
    checkout_date: str = ""
    personal_message: str = ""
    # Dead Man's Switch: auto-protect when lease ends without owner response (default: OFF, owner can enable)
    dead_mans_switch_enabled: bool = False
    dead_mans_switch_alert_email: bool = True
    dead_mans_switch_alert_sms: bool = False
    dead_mans_switch_alert_dashboard: bool = True
    dead_mans_switch_alert_phone: bool = False
    # When only guest_name + property_id are sent, checkin/checkout default to today + 14 days


class InviteTenantRequest(BaseModel):
    tenant_name: str
    tenant_email: str = Field(..., min_length=1, description="Tenant email (required)")
    lease_start_date: str
    lease_end_date: str


class SendTenantInviteEmailBody(BaseModel):
    email: EmailStr
    tenant_name: str = Field(..., min_length=1, description="Tenant name (required; updates the invitation if changed)")


def _ensure_property_usat_token(prop: Property, db: Session) -> None:
    """Backfill USAT token for properties created before staged tokens were added."""
    if prop.usat_token:
        return
    token = "USAT-" + secrets.token_hex(12).upper()
    for _ in range(10):
        if db.query(Property).filter(Property.usat_token == token).first() is None:
            break
        token = "USAT-" + secrets.token_hex(12).upper()
    else:
        token = f"USAT-{secrets.token_hex(8).upper()}-{prop.id}"
    prop.usat_token = token
    prop.usat_token_state = USAT_TOKEN_STAGED
    db.add(prop)


def _ensure_property_live_slug(prop: Property, db: Session) -> None:
    """Set live_slug if missing (e.g. property created via bulk upload). So live link / QR section can always be shown."""
    if prop.live_slug:
        return
    for _ in range(15):
        slug = secrets.token_urlsafe(12).replace("+", "-").replace("/", "_")[:24]
        if db.query(Property).filter(Property.live_slug == slug).first() is None:
            prop.live_slug = slug
            break
    else:
        prop.live_slug = secrets.token_urlsafe(12).replace("+", "-").replace("/", "_")[:20] + "-" + str(prop.id)
    db.add(prop)


def _csv_bulk_address_line(street: str, city: str, state: str, zip_code: str | None) -> str:
    z = (zip_code or "").strip()
    return ", ".join(x for x in (street.strip(), city.strip(), state.strip(), z) if x)


def _ledger_meta_bulk_property_created(
    *,
    property_name: str,
    property_address: str,
    csv_row: int,
    property_id: int,
    occupancy_status: str | None = None,
) -> dict[str, object]:
    occ = f" Initial occupancy: {occupancy_status}." if occupancy_status else ""
    msg = (
        f"CSV bulk upload (row {csv_row}): added property \"{property_name}\" ({property_address}). "
        f"Property ID {property_id}.{occ}"
    )
    return {
        "message": msg,
        "source": "bulk_csv",
        "csv_row": csv_row,
        "property_name": property_name,
        "property_address": property_address,
        "property_id": property_id,
    }


def _ledger_meta_bulk_property_updated(
    *,
    property_name: str,
    property_address: str,
    csv_row: int,
    property_id: int,
    fields_changed: list[str],
) -> dict[str, object]:
    fields = ", ".join(fields_changed) if fields_changed else "CSV row applied"
    msg = (
        f"CSV bulk upload (row {csv_row}): updated existing property \"{property_name}\" ({property_address}). "
        f"Property ID {property_id}. Updated: {fields}."
    )
    return {
        "message": msg,
        "source": "bulk_csv",
        "csv_row": csv_row,
        "property_name": property_name,
        "property_address": property_address,
        "property_id": property_id,
        "fields_changed": fields_changed,
    }


def _ledger_meta_bulk_csv_invitation(
    *,
    property_name: str,
    property_address: str,
    unit_label: str | None,
    tenant_name: str,
    invitation_code: str,
    lease_start,
    lease_end,
    csv_row: int,
) -> dict[str, object]:
    unit_seg = f" Unit {unit_label}." if unit_label else ""
    msg = (
        f"CSV bulk upload (row {csv_row}): tenant invitation link generated for {tenant_name} "
        f"at property \"{property_name}\" ({property_address}).{unit_seg} "
        f"Invite ID {invitation_code}. Lease {lease_start} – {lease_end}. "
        "Tenant can register using the link; it stays valid until signup completes."
    )
    return {
        "message": msg,
        "source": "bulk_csv",
        "csv_row": csv_row,
        "property_name": property_name,
        "property_address": property_address,
        "unit_label": unit_label,
        "tenant_name": tenant_name,
        "invitation_code": invitation_code,
        "lease_start": str(lease_start),
        "lease_end": str(lease_end),
    }


@router.get("/config", response_model=OwnerConfigResponse)
def get_owner_config(
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Return owner-facing config (e.g. test provider email for development)."""
    settings = get_settings()
    email = (settings.test_provider_email or "").strip() or None
    return OwnerConfigResponse(test_provider_email=email)


@router.get("/properties", response_model=list[PropertyResponse])
def list_my_properties(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
    context_mode: str = Depends(get_context_mode),
    inactive: bool = False,
):
    """List properties. Business mode: all owned. Personal mode: only owner-occupied (residence). inactive=1: inactive only."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        return []
    if inactive:
        props = db.query(Property).filter(
            Property.owner_profile_id == profile.id,
            Property.deleted_at.isnot(None),
        ).all()
    else:
        props = db.query(Property).filter(
            Property.owner_profile_id == profile.id,
            Property.deleted_at.is_(None),
        ).all()
    if context_mode == "personal":
        props = [p for p in props if p.owner_occupied]
    for p in props:
        if not p.usat_token:
            _ensure_property_usat_token(p, db)
    db.commit()
    if not props:
        return []
    unit_count_rows = (
        db.query(Unit.property_id, func.count(Unit.id).label("cnt"))
        .filter(Unit.property_id.in_([p.id for p in props]))
        .group_by(Unit.property_id)
        .all()
    )
    unit_count_map = {r.property_id: r.cnt for r in unit_count_rows}
    out = []
    for p in props:
        data = PropertyResponse.model_validate(p).model_dump()
        data["unit_count"] = unit_count_map.get(p.id) or 1
        out.append(PropertyResponse(**data))
    return out


@router.post("/verify-address-and-utilities", response_model=VerifyAddressAndUtilitiesResponse)
def verify_address_and_utilities(
    data: VerifyAddressRequest,
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Run Smarty address verification and utility lookup; return standardized address and providers by type (for add-property utilities step)."""
    street = (data.street_address or "").strip()
    city = (data.city or "").strip()
    state = (data.state or "").strip()
    zip_code = (data.zip_code or "").strip() or None
    print(f"[PropertyFlow] verify_address_and_utilities: street={street!r}, city={city!r}, state={state!r}, zip={zip_code!r}")
    if not street or not city or not state:
        raise HTTPException(status_code=400, detail="street_address, city, and state are required")
    print(f"[PropertyFlow] Calling Smarty verify_address(...)")
    result = verify_address(street=street, city=city, state=state, zipcode=zip_code)
    standardized_address = None
    lat = None
    lon = None
    zip5 = zip_code
    if result:
        standardized_address = StandardizedAddressResponse(
            delivery_line_1=result.delivery_line_1,
            city_name=result.city_name,
            state_abbreviation=result.state_abbreviation,
            zipcode=result.zipcode,
            latitude=result.latitude,
            longitude=result.longitude,
        )
        lat = result.latitude
        lon = result.longitude
        zip5 = result.zipcode or zip_code
    address = ", ".join(filter(None, [
        result.delivery_line_1 if result else street,
        f"{result.city_name if result else city}, {result.state_abbreviation if result else state} {zip5 or ''}".strip(),
    ])) if result else f"{street}, {city}, {state} {zip_code or ''}".strip()
    print(f"[PropertyFlow] Smarty result: standardized={result is not None}; calling lookup_utility_providers(zip={zip5!r}, ...)")
    providers = lookup_utility_providers(
        zip_code=zip5,
        lat=lat,
        lon=lon,
        address=address,
        city=result.city_name if result else city,
        state_abbreviation=result.state_abbreviation if result else state,
    )
    print(f"[PropertyFlow] lookup_utility_providers returned {len(providers)} provider(s)")
    # Only show providers in the user's area; cap each type so we don't overwhelm the UI
    _MAX_PROVIDERS_PER_TYPE = 50
    by_type: dict[str, list[UtilityOptionItem]] = {}
    for p in providers:
        t = p.provider_type
        if t not in by_type:
            by_type[t] = []
        if len(by_type[t]) < _MAX_PROVIDERS_PER_TYPE:
            by_type[t].append(UtilityOptionItem(name=p.name, phone=p.phone))
    return VerifyAddressAndUtilitiesResponse(
        standardized_address=standardized_address,
        providers_by_type=by_type,
    )


@router.post("/properties", response_model=PropertyResponse)
def add_property(
    request: Request,
    data: PropertyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
    context_mode: str = Depends(get_context_mode),
):
    if context_mode == "personal":
        raise HTTPException(status_code=403, detail="Adding properties is only available in Business Mode. Switch to Business Mode to add a property.")
    print(f"[PropertyFlow] add_property: street={getattr(data, 'street_address', None) or getattr(data, 'street', None)!r}, ...")
    street = data.street_address or data.street
    if not street:
        raise HTTPException(status_code=400, detail="street or street_address required")
    region = (data.region_code or data.state or "US").upper()[:20]
    # Portfolio registration is business-only; primary residence is set in Personal Mode via property update.
    owner_occ = False
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        profile = OwnerProfile(user_id=current_user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    def _generate_usat_token() -> str:
        return "USAT-" + secrets.token_hex(12).upper()

    prop = Property(
        owner_profile_id=profile.id,
        name=data.property_name,
        street=street,
        city=data.city,
        state=data.state,
        zip_code=data.zip_code,
        region_code=region,
        owner_occupied=owner_occ,
        property_type=data.property_type_enum,
        property_type_label=data.property_type,
        bedrooms=data.bedrooms,
    )
    if data.tax_id is not None:
        prop.tax_id = data.tax_id.strip() or None
    if data.apn is not None:
        prop.apn = data.apn.strip() or None
    unit_count = data.unit_count if data.unit_count is not None else None
    if unit_count is not None and unit_count > 1:
        prop.is_multi_unit = True
    db.add(prop)
    db.flush()
    # Unique live_slug for public property page URL (#live/<slug>), no DB id in URL
    for _ in range(15):
        slug = secrets.token_urlsafe(12).replace("+", "-").replace("/", "_")[:24]
        if db.query(Property).filter(Property.live_slug == slug).first() is None:
            prop.live_slug = slug
            break
    else:
        prop.live_slug = secrets.token_urlsafe(12).replace("+", "-").replace("/", "_")[:20] + "-" + str(prop.id)
    for _ in range(10):
        token = _generate_usat_token()
        if db.query(Property).filter(Property.usat_token == token).first() is None:
            prop.usat_token = token
            prop.usat_token_state = USAT_TOKEN_STAGED
            break
    else:
        prop.usat_token = _generate_usat_token() + "-" + str(prop.id)
        prop.usat_token_state = USAT_TOKEN_STAGED

    custom_labels = data.unit_labels or []
    if unit_count is not None and unit_count > 1:
        for i in range(1, unit_count + 1):
            label = custom_labels[i - 1] if i - 1 < len(custom_labels) and custom_labels[i - 1].strip() else str(i)
            u = Unit(
                property_id=prop.id,
                unit_label=label.strip(),
                occupancy_status=OccupancyStatus.unknown.value,
                is_primary_residence=0,
            )
            db.add(u)

    _apply_smarty_address(prop, street, data.city, data.state, data.zip_code)
    # Utility providers are set by the frontend via POST /properties/{id}/utilities after owner selects from dropdowns

    property_display = (data.property_name or "").strip() or f"{street}, {data.city}, {data.state}".strip(", ")
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Property registered",
        f"Owner registered property: {property_display} (id={prop.id}). Occupancy status: {prop.occupancy_status} (initial).",
        property_id=prop.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "").strip() or None,
        meta={"property_id": prop.id, "street": street, "city": data.city, "state": data.state, "region_code": region, "occupancy_status_new": prop.occupancy_status},
    )
    create_ledger_event(
        db,
        ACTION_PROPERTY_CREATED,
        target_object_type="Property",
        target_object_id=prop.id,
        property_id=prop.id,
        actor_user_id=current_user.id,
        meta={"property_id": prop.id, "street": street, "city": data.city, "state": data.state, "region_code": region, "occupancy_status_new": prop.occupancy_status},
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "").strip() or None,
    )
    db.commit()
    db.refresh(prop)
    # Billing: first property upload starts flat subscription ($10/mo) with 7-day trial; no separate onboarding invoice.
    # Billing units = properties (1 property = 1 billing unit; property with 10 physical units still counts as 1).
    if profile.onboarding_billing_completed_at is None:
        total_units = db.query(Property).filter(Property.owner_profile_id == profile.id, Property.deleted_at.is_(None)).count()
        if total_units >= 1:
            try:
                on_onboarding_properties_completed(db, profile, current_user, total_units)
            except Exception as e:
                print(f"[PropertyFlow] Onboarding billing failed (property still created): {e}", flush=True)
    elif profile.onboarding_invoice_paid_at is not None and profile.stripe_customer_id and not profile.stripe_subscription_id:
        try:
            ensure_subscription(db, profile, current_user)
        except Exception as e:
            print(f"[PropertyFlow] Subscription ensure failed: {e}", flush=True)
    try:
        sync_subscription_quantities(db, profile)
    except Exception as e:
        print(f"[PropertyFlow] Subscription sync failed: {e}", flush=True)
    print(f"[PropertyFlow] add_property: created property_id={prop.id}")
    return PropertyResponse.model_validate(prop)


def _apply_smarty_address(prop: Property, street: str, city: str, state: str, zip_code: str | None) -> None:
    """Call Smarty US Street API and populate standardized address fields on the property."""
    print(f"[PropertyFlow] _apply_smarty_address: calling Smarty verify_address for property_id={prop.id}")
    result = verify_address(street=street, city=city, state=state, zipcode=zip_code)
    if result:
        prop.smarty_delivery_line_1 = result.delivery_line_1
        prop.smarty_city_name = result.city_name
        prop.smarty_state_abbreviation = result.state_abbreviation
        prop.smarty_zipcode = result.zipcode
        prop.smarty_plus4_code = result.plus4_code
        prop.smarty_latitude = result.latitude
        prop.smarty_longitude = result.longitude


def _run_utility_bucket_for_property(prop: Property, db: Session) -> None:
    """Run Utility Bucket: Census → Rewiring America → Water CSV → FCC BDC CSV; save providers + authority letters."""
    zip_code = prop.smarty_zipcode or prop.zip_code
    lat = prop.smarty_latitude
    lon = prop.smarty_longitude
    city = prop.smarty_city_name or prop.city
    state_abbrev = prop.smarty_state_abbreviation or prop.state
    address = ", ".join(
        filter(
            None,
            [
                prop.smarty_delivery_line_1 or prop.street,
                (prop.smarty_city_name or prop.city) + ", " + (prop.smarty_state_abbreviation or prop.state or "") + " " + (prop.smarty_zipcode or prop.zip_code or ""),
            ],
        )
    )
    if not address.strip():
        address = (prop.street or "") + ", " + (prop.city or "") + ", " + (prop.state or "")
    providers = lookup_utility_providers(
        zip_code=zip_code,
        lat=lat,
        lon=lon,
        address=address,
        city=city,
        state_abbreviation=state_abbrev,
    )
    if not providers:
        return
    letters = generate_authority_letters(providers, address, prop.name, prop.region_code, db=db, zip_code=prop.zip_code)
    for p, content in letters:
        prv = PropertyUtilityProvider(
            property_id=prop.id,
            provider_name=p.name,
            provider_type=p.provider_type,
            utilityapi_id=p.utilityapi_id,
            contact_phone=p.phone,
            contact_email=getattr(p, "email", None),
            raw_data=_provider_to_raw(p),
        )
        db.add(prv)
        db.flush()
        letter = PropertyAuthorityLetter(
            property_id=prop.id,
            property_utility_provider_id=prv.id,
            provider_name=p.name,
            provider_type=p.provider_type,
            letter_content=content,
        )
        db.add(letter)


def _normalize_addr(s: str | None) -> str:
    """Normalize for address matching: strip, collapse spaces, upper."""
    if not s or not isinstance(s, str):
        return ""
    return " ".join(s.strip().split()).upper()


def _parse_bool_cell(val: str | None) -> bool:
    if val is None or (isinstance(val, str) and not val.strip()):
        return False
    v = (val.strip().lower() if isinstance(val, str) else str(val)).lower()
    return v in ("1", "true", "yes", "y")


def _parse_date_cell(val: str | None) -> date | None:
    """Parse a date from CSV (YYYY-MM-DD or M/D/YYYY). Returns None if empty or invalid."""
    if val is None or (isinstance(val, str) and not val.strip()):
        return None
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


@router.post("/properties/bulk-upload", response_model=BulkUploadResult)
def bulk_upload_properties(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Upload properties via CSV. Required: Address, City, State, Zip, Occupied (YES/NO). If Occupied=YES: Tenant Name, Lease Start, Lease End required. Optional: Unit No, Shield Mode (YES/NO, default NO; independent of Occupied—owner can also turn on/off anytime in dashboard), Tax ID, APN. Each property gets a Property Lifecycle Anchor Token. Occupied=YES: burn token, set occupancy, create invite (BURNED) with DMS from lease end. Occupied=NO: token STAGED, status VACANT."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        profile = OwnerProfile(user_id=current_user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file.")

    content = b""
    try:
        content = file.file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read file: {e!s}")
    if not content:
        raise HTTPException(status_code=400, detail="File is empty.")

    try:
        text = content.decode("utf-8-sig").strip()
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded.")

    reader = csv.DictReader(io.StringIO(text))
    orig_headers = list(reader.fieldnames or [])
    norm_to_orig = {h.strip().lower().replace(" ", "_"): h for h in orig_headers}
    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=400, detail="CSV has no data rows.")

    created = 0
    updated = 0
    failed_from_row = None
    failure_reason = None
    existing_props: list[Property] = (
        db.query(Property)
        .filter(
            Property.owner_profile_id == profile.id,
            Property.deleted_at.is_(None),
        )
        .all()
    )

    def _get_cell(row: dict, *keys: str) -> str | None:
        for k in keys:
            orig = norm_to_orig.get(k) or norm_to_orig.get(k.replace("_", ""))
            if orig and row.get(orig) is not None:
                v = str(row[orig]).strip()
                if v:
                    return v
        return None

    for idx, row in enumerate(rows, start=1):
        row_num = idx
        address = _get_cell(row, "address", "street_address", "street")
        unit_no = _get_cell(row, "unit_no", "unit")
        city = _get_cell(row, "city")
        state = _get_cell(row, "state")
        zip_code = _get_cell(row, "zip", "zip_code")
        occupied_raw = _get_cell(row, "occupied")
        tenant_name = _get_cell(row, "tenant_name", "tenant_name")
        lease_start_str = _get_cell(row, "lease_start", "lease_start")
        lease_end_str = _get_cell(row, "lease_end", "lease_end")
        # Shield Mode: optional YES/NO; stored on property and shown on dashboard (Properties tab, Shield filter, per-property toggle).
        shield_mode_raw = _get_cell(row, "shield_mode", "shieldmode")
        primary_residence_raw = _get_cell(row, "is_primary_residence", "owner_occupied", "primary_residence")
        tax_id_raw = _get_cell(row, "tax_id", "tax_id")
        apn_raw = _get_cell(row, "apn", "parcel", "apn")
        property_name_raw = _get_cell(row, "property_name", "name")
        property_type_raw = _get_cell(row, "property_type", "type")
        bedrooms_raw = _get_cell(row, "bedrooms")
        units_raw = _get_cell(row, "units", "unit_count", "number_of_units")
        occupied_unit_raw = _get_cell(row, "occupied_unit", "unit_label")
        primary_residence_unit_raw = _get_cell(row, "primary_residence_unit", "primary_unit")

        street = (address or "").strip()
        if unit_no:
            street = f"{street}, {unit_no.strip()}".strip(", ")
        if not street:
            failed_from_row = row_num
            failure_reason = "Missing required column: Address (or street_address/street)."
            break
        if not city:
            failed_from_row = row_num
            failure_reason = "Missing required column: City."
            break
        if not state:
            failed_from_row = row_num
            failure_reason = "Missing required column: State."
            break
        if not zip_code:
            failed_from_row = row_num
            failure_reason = "Missing required column: Zip (or zip_code)."
            break
        if occupied_raw is None or not str(occupied_raw).strip():
            failed_from_row = row_num
            failure_reason = "Missing required column: Occupied (YES/NO)."
            break

        state_upper = state.upper()[:50]
        city_norm = _normalize_addr(city)
        street_norm = _normalize_addr(street)
        if not city_norm or not street_norm:
            failed_from_row = row_num
            failure_reason = "Address, city, and state cannot be blank after trimming."
            break

        occupied = _parse_bool_cell(occupied_raw)
        shield_mode = _parse_bool_cell(shield_mode_raw)
        primary_residence = _parse_bool_cell(primary_residence_raw)
        region_code = (state_upper).upper()[:20]
        # Name: use property_name from CSV if provided, else address
        address_as_name = f"{street.strip()}, {city.strip()}, {state_upper}".strip(", ")
        prop_name = (property_name_raw or "").strip() or address_as_name
        # Property type–based fields: house/condo/townhouse → bedrooms; apartment/duplex/triplex/quadplex → units
        multi_unit_types = ("apartment", "duplex", "triplex", "quadplex")
        pt_lower = (property_type_raw or "").strip().lower() if property_type_raw else ""
        is_multi_type = pt_lower in multi_unit_types
        unit_count_val: int | None = None
        if is_multi_type and units_raw:
            try:
                uc = int(str(units_raw).strip())
                unit_count_val = uc if uc > 0 else None
            except ValueError:
                pass
        bedrooms_val = (bedrooms_raw or "").strip() or None
        if not is_multi_type and bedrooms_val:
            bedrooms_val = bedrooms_val[:10] if bedrooms_val else None
        primary_unit_val: int | None = None
        if is_multi_type and primary_residence_unit_raw:
            try:
                pu = int(str(primary_residence_unit_raw).strip())
                primary_unit_val = pu if pu >= 1 else None
            except ValueError:
                pass

        if occupied:
            if not (tenant_name or "").strip():
                failed_from_row = row_num
                failure_reason = "When Occupied=YES, Tenant Name is required."
                break
            lease_start = _parse_date_cell(lease_start_str)
            lease_end = _parse_date_cell(lease_end_str)
            if not lease_start:
                failed_from_row = row_num
                failure_reason = "When Occupied=YES, Lease Start is required (e.g. YYYY-MM-DD)."
                break
            if not lease_end:
                failed_from_row = row_num
                failure_reason = "When Occupied=YES, Lease End is required (e.g. YYYY-MM-DD)."
                break
            if lease_end <= lease_start:
                failed_from_row = row_num
                failure_reason = "Lease End must be after Lease Start."
                break
            # Jurisdiction threshold validation is intentionally NOT applied to tenant lease dates.
            # Tenant leases can be any length (6 months, 1 year, etc.). The jurisdiction guest-to-tenancy
            # threshold only applies when creating Guest Invitations, not tenant leases.
            # Allow past lease start (e.g. existing tenancies / backfilled data)

        state_norm = _normalize_addr(state)
        existing_match = None
        for p in existing_props:
            if _normalize_addr(p.street) == street_norm and _normalize_addr(p.city) == city_norm and _normalize_addr(p.state) == state_norm:
                existing_match = p
                break

        if existing_match is None:
            # Primary residence: from primary_residence column, or when primary_unit_val is set for multi-unit
            owner_occ = primary_residence or (primary_unit_val is not None and primary_unit_val >= 1)
            occ_status = OccupancyStatus.occupied.value if (occupied or owner_occ) else OccupancyStatus.vacant.value
            prop = Property(
                owner_profile_id=profile.id,
                name=prop_name,
                street=street.strip(),
                city=city.strip(),
                state=state_upper,
                zip_code=zip_code.strip() if zip_code else None,
                region_code=region_code,
                owner_occupied=owner_occ,
                property_type=None,
                property_type_label=pt_lower if pt_lower else None,
                bedrooms=bedrooms_val if not is_multi_type else None,
                occupancy_status=occ_status,
                shield_mode_enabled=persisted_shield_row_int(csv_parsed_on=shield_mode),
                is_multi_unit=bool(unit_count_val and unit_count_val > 1),
            )
            prop.tax_id = (tax_id_raw or "").strip() or None
            prop.apn = (apn_raw or "").strip() or None
            db.add(prop)
            db.flush()
            _ensure_property_live_slug(prop, db)
            for _ in range(10):
                token = "USAT-" + secrets.token_hex(12).upper()
                if db.query(Property).filter(Property.usat_token == token).first() is None:
                    prop.usat_token = token
                    break
            else:
                prop.usat_token = "USAT-" + secrets.token_hex(8).upper() + "-" + str(prop.id)
            prop.usat_token_state = USAT_TOKEN_RELEASED if occupied else USAT_TOKEN_STAGED
            # Create Unit rows for multi-unit properties
            if unit_count_val is not None and unit_count_val > 1:
                for i in range(1, unit_count_val + 1):
                    is_primary = primary_unit_val is not None and primary_unit_val == i
                    u = Unit(
                        property_id=prop.id,
                        unit_label=str(i),
                        occupancy_status=OccupancyStatus.occupied.value if is_primary else OccupancyStatus.unknown.value,
                        is_primary_residence=1 if is_primary else 0,
                    )
                    db.add(u)
            # Address normalization and utility lookup shelved for now.
            # _apply_smarty_address(prop, street.strip(), city.strip(), state_upper, zip_code)
            # try:
            #     _run_utility_bucket_for_property(prop, db)
            # except Exception as e:
            #     print(f"[Owners] Utility bucket failed for property {prop.id} (row {row_num}): {e}")
            created += 1
            property_display = address_as_name
            create_log(
                db,
                CATEGORY_STATUS_CHANGE,
                "Property registered",
                f"Owner registered property via bulk upload: {property_display} (id={prop.id}, row {row_num}).",
                property_id=prop.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"property_id": prop.id, "bulk_upload_row": row_num, "street": street.strip(), "city": city.strip(), "state": state_upper},
            )
            _addr_line = _csv_bulk_address_line(street.strip(), city.strip(), state_upper, zip_code.strip() if zip_code else None)
            create_ledger_event(
                db,
                ACTION_BULK_UPLOAD_PROPERTY_CREATED,
                target_object_type="Property",
                target_object_id=prop.id,
                property_id=prop.id,
                actor_user_id=current_user.id,
                meta=_ledger_meta_bulk_property_created(
                    property_name=prop_name,
                    property_address=_addr_line,
                    csv_row=row_num,
                    property_id=prop.id,
                    occupancy_status=str(occ_status) if occ_status else None,
                ),
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
            )
            if occupied and (tenant_name or "").strip():
                inv_code = "INV-" + secrets.token_hex(4).upper()
                inv_unit_id: int | None = None
                if prop.is_multi_unit and occupied_unit_raw:
                    unit_label = str(occupied_unit_raw).strip()
                    unit_row = db.query(Unit).filter(Unit.property_id == prop.id, Unit.unit_label == unit_label).first()
                    if unit_row:
                        inv_unit_id = unit_row.id
                if inv_unit_id is None:
                    existing_units = db.query(Unit).filter(Unit.property_id == prop.id).all()
                    if existing_units:
                        inv_unit_id = existing_units[0].id
                    else:
                        auto_unit = Unit(property_id=prop.id, unit_label="1", occupancy_status=OccupancyStatus.occupied.value)
                        db.add(auto_unit)
                        db.flush()
                        inv_unit_id = auto_unit.id
                inv = Invitation(
                    invitation_code=inv_code,
                    owner_id=current_user.id,
                    invited_by_user_id=current_user.id,
                    property_id=prop.id,
                    unit_id=inv_unit_id,
                    guest_name=(tenant_name or "").strip(),
                    guest_email=None,
                    stay_start_date=lease_start,
                    stay_end_date=lease_end,
                    purpose_of_stay=PurposeOfStay.other,
                    relationship_to_owner=RelationshipToOwner.other,
                    region_code=prop.region_code,
                    status="ongoing",
                    token_state="BURNED",
                    invitation_kind="tenant",
                    dead_mans_switch_enabled=1,
                    dead_mans_switch_alert_email=1,
                    dead_mans_switch_alert_sms=0,
                    dead_mans_switch_alert_dashboard=1,
                    dead_mans_switch_alert_phone=0,
                )
                db.add(inv)
                db.flush()
                create_log(
                    db,
                    CATEGORY_STATUS_CHANGE,
                    "Invitation created (CSV occupied)",
                    f"Invite ID {inv_code} created (token_state=BURNED) for property {prop.id}, tenant {tenant_name}, lease {lease_start}–{lease_end}. Tenant can use invite link to sign up.",
                    property_id=prop.id,
                    invitation_id=inv.id,
                    actor_user_id=current_user.id,
                    actor_email=current_user.email,
                    ip_address=request.client.host if request.client else None,
                    user_agent=(request.headers.get("user-agent") or "").strip() or None,
                    meta={"invitation_code": inv_code, "token_state": "BURNED", "guest_name": (tenant_name or "").strip(), "lease_start": str(lease_start), "lease_end": str(lease_end)},
                )
                _ul = str(occupied_unit_raw).strip() if occupied_unit_raw else None
                if not _ul and inv_unit_id:
                    _ur = db.query(Unit).filter(Unit.id == inv_unit_id).first()
                    _ul = (_ur.unit_label if _ur else None) or None
                _inv_addr = _csv_bulk_address_line(prop.street or "", prop.city or "", prop.state or "", prop.zip_code)
                create_ledger_event(
                    db,
                    ACTION_INVITATION_CREATED_CSV,
                    target_object_type="Invitation",
                    target_object_id=inv.id,
                    property_id=prop.id,
                    unit_id=inv_unit_id,
                    invitation_id=inv.id,
                    actor_user_id=current_user.id,
                    meta=_ledger_meta_bulk_csv_invitation(
                        property_name=(prop.name or prop_name or "").strip() or prop_name,
                        property_address=_inv_addr,
                        unit_label=_ul,
                        tenant_name=(tenant_name or "").strip(),
                        invitation_code=inv_code,
                        lease_start=lease_start,
                        lease_end=lease_end,
                        csv_row=row_num,
                    ),
                    ip_address=request.client.host if request.client else None,
                    user_agent=(request.headers.get("user-agent") or "").strip() or None,
                )
            db.commit()
            db.refresh(prop)
            existing_props.append(prop)
        else:
            # Primary residence (owner-occupied) implies unit is occupied; same as tenant Occupied=YES
            owner_occ = primary_residence
            new_occ_status = OccupancyStatus.occupied.value if (occupied or owner_occ) else OccupancyStatus.vacant.value
            updates: dict[str, object] = {}
            if (existing_match.name or "").strip() != address_as_name:
                updates["name"] = address_as_name
            if street.strip() != (existing_match.street or "").strip():
                updates["street"] = street.strip()
            if city.strip() != (existing_match.city or "").strip():
                updates["city"] = city.strip()
            if state_upper != (existing_match.state or "").strip():
                updates["state"] = state_upper
            if zip_code and (existing_match.zip_code or "").strip() != zip_code.strip():
                updates["zip_code"] = zip_code.strip()
            if existing_match.owner_occupied != owner_occ:
                updates["owner_occupied"] = owner_occ
            if existing_match.occupancy_status != new_occ_status:
                updates["occupancy_status"] = new_occ_status
            if persisted_shield_row_int(csv_parsed_on=shield_mode) != (existing_match.shield_mode_enabled or 0):
                updates["shield_mode_enabled"] = persisted_shield_row_int(csv_parsed_on=shield_mode)
            tax_id_val = (tax_id_raw or "").strip() or None
            apn_val = (apn_raw or "").strip() or None
            if (existing_match.tax_id or None) != tax_id_val:
                updates["tax_id"] = tax_id_val
            if (existing_match.apn or None) != apn_val:
                updates["apn"] = apn_val
            new_token_state = USAT_TOKEN_RELEASED if occupied else USAT_TOKEN_STAGED
            if (existing_match.usat_token_state or USAT_TOKEN_STAGED) != new_token_state:
                existing_match.usat_token_state = new_token_state
                updates["usat_token_state"] = new_token_state

            for key, val in updates.items():
                if key == "name":
                    existing_match.name = val
                elif key == "street":
                    existing_match.street = val
                elif key == "city":
                    existing_match.city = val
                elif key == "state":
                    existing_match.state = val
                elif key == "zip_code":
                    existing_match.zip_code = val
                elif key == "owner_occupied":
                    existing_match.owner_occupied = val
                elif key == "occupancy_status":
                    existing_match.occupancy_status = val
                elif key == "shield_mode_enabled":
                    existing_match.shield_mode_enabled = val
                elif key == "tax_id":
                    existing_match.tax_id = val
                elif key == "apn":
                    existing_match.apn = val
            if updates:
                updated += 1
                _em_addr = _csv_bulk_address_line(
                    (existing_match.street or "").strip(),
                    (existing_match.city or "").strip(),
                    (existing_match.state or "").strip(),
                    (existing_match.zip_code or "").strip() or None,
                )
                create_ledger_event(
                    db,
                    ACTION_BULK_UPLOAD_PROPERTY_UPDATED,
                    target_object_type="Property",
                    target_object_id=existing_match.id,
                    property_id=existing_match.id,
                    actor_user_id=current_user.id,
                    meta=_ledger_meta_bulk_property_updated(
                        property_name=(existing_match.name or address_as_name or "").strip() or address_as_name,
                        property_address=_em_addr,
                        csv_row=row_num,
                        property_id=existing_match.id,
                        fields_changed=list(updates.keys()),
                    ),
                    ip_address=request.client.host if request.client else None,
                    user_agent=(request.headers.get("user-agent") or "").strip() or None,
                )
            # When updating to occupied with tenant info, create invite (BURNED) if none exists for this property+tenant+dates
            if occupied and (tenant_name or "").strip() and lease_start and lease_end:
                # Allow past lease start for existing tenancies
                existing_inv = (
                    db.query(Invitation)
                    .filter(
                        Invitation.property_id == existing_match.id,
                        Invitation.guest_name == (tenant_name or "").strip(),
                        Invitation.stay_start_date == lease_start,
                        Invitation.stay_end_date == lease_end,
                        Invitation.status.in_(["pending", "ongoing"]),
                    )
                    .first()
                )
                if not existing_inv:
                    inv_code = "INV-" + secrets.token_hex(4).upper()
                    inv_unit_id_upd: int | None = None
                    if existing_match.is_multi_unit and occupied_unit_raw:
                        _ulabel = str(occupied_unit_raw).strip()
                        _urow = db.query(Unit).filter(Unit.property_id == existing_match.id, Unit.unit_label == _ulabel).first()
                        if _urow:
                            inv_unit_id_upd = _urow.id
                    if inv_unit_id_upd is None:
                        existing_units = db.query(Unit).filter(Unit.property_id == existing_match.id).all()
                        if existing_units:
                            inv_unit_id_upd = existing_units[0].id
                        else:
                            auto_unit = Unit(property_id=existing_match.id, unit_label="1", occupancy_status=OccupancyStatus.occupied.value)
                            db.add(auto_unit)
                            db.flush()
                            inv_unit_id_upd = auto_unit.id
                    inv = Invitation(
                        invitation_code=inv_code,
                        owner_id=current_user.id,
                        invited_by_user_id=current_user.id,
                        property_id=existing_match.id,
                        unit_id=inv_unit_id_upd,
                        guest_name=(tenant_name or "").strip(),
                        guest_email=None,
                        stay_start_date=lease_start,
                        stay_end_date=lease_end,
                        purpose_of_stay=PurposeOfStay.other,
                        relationship_to_owner=RelationshipToOwner.other,
                        region_code=existing_match.region_code,
                        status="ongoing",
                        token_state="BURNED",
                        invitation_kind="tenant",
                        dead_mans_switch_enabled=1,
                        dead_mans_switch_alert_email=1,
                        dead_mans_switch_alert_sms=0,
                        dead_mans_switch_alert_dashboard=1,
                        dead_mans_switch_alert_phone=0,
                    )
                    db.add(inv)
                    db.flush()
                    create_log(
                        db,
                        CATEGORY_STATUS_CHANGE,
                        "Invitation created (CSV occupied, update)",
                        f"Invite ID {inv_code} created (token_state=BURNED) for property {existing_match.id}, tenant {tenant_name}, lease {lease_start}–{lease_end}.",
                        property_id=existing_match.id,
                        invitation_id=inv.id,
                        actor_user_id=current_user.id,
                        actor_email=current_user.email,
                        ip_address=request.client.host if request.client else None,
                        user_agent=(request.headers.get("user-agent") or "").strip() or None,
                        meta={"invitation_code": inv_code, "token_state": "BURNED", "guest_name": (tenant_name or "").strip(), "lease_start": str(lease_start), "lease_end": str(lease_end)},
                    )
                    _ul_u = str(occupied_unit_raw).strip() if occupied_unit_raw else None
                    if not _ul_u and inv_unit_id_upd:
                        _ur_u = db.query(Unit).filter(Unit.id == inv_unit_id_upd).first()
                        _ul_u = (_ur_u.unit_label if _ur_u else None) or None
                    _inv_addr_u = _csv_bulk_address_line(
                        existing_match.street or "", existing_match.city or "", existing_match.state or "", existing_match.zip_code
                    )
                    create_ledger_event(
                        db,
                        ACTION_INVITATION_CREATED_CSV,
                        target_object_type="Invitation",
                        target_object_id=inv.id,
                        property_id=existing_match.id,
                        unit_id=inv_unit_id_upd,
                        invitation_id=inv.id,
                        actor_user_id=current_user.id,
                        meta=_ledger_meta_bulk_csv_invitation(
                            property_name=(existing_match.name or address_as_name or "").strip() or address_as_name,
                            property_address=_inv_addr_u,
                            unit_label=_ul_u,
                            tenant_name=(tenant_name or "").strip(),
                            invitation_code=inv_code,
                            lease_start=lease_start,
                            lease_end=lease_end,
                            csv_row=row_num,
                        ),
                        ip_address=request.client.host if request.client else None,
                        user_agent=(request.headers.get("user-agent") or "").strip() or None,
                    )
            db.commit()

    # Billing: after bulk upload, same as single-property add — start subscription when first properties were just added, then sync subscription.
    # Billing units = properties (1 property = 1 billing unit).
    if created >= 1 or updated >= 1:
        profile_fresh = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
        if profile_fresh:
            if profile_fresh.onboarding_billing_completed_at is None:
                total_units = (
                    db.query(Property)
                    .filter(Property.owner_profile_id == profile_fresh.id, Property.deleted_at.is_(None))
                    .count()
                )
                if total_units >= 1:
                    try:
                        on_onboarding_properties_completed(db, profile_fresh, current_user, total_units)
                    except Exception as e:
                        print(f"[Owners] Onboarding billing failed after bulk upload (properties still created): {e}", flush=True)
            elif profile_fresh.onboarding_invoice_paid_at is not None and profile_fresh.stripe_customer_id and not profile_fresh.stripe_subscription_id:
                try:
                    ensure_subscription(db, profile_fresh, current_user)
                except Exception as e:
                    print(f"[Owners] Subscription ensure failed after bulk upload: {e}", flush=True)
            try:
                sync_subscription_quantities(db, profile_fresh)
            except Exception as e:
                print(f"[Owners] Subscription sync failed after bulk upload: {e}", flush=True)

    return BulkUploadResult(created=created, updated=updated, failed_from_row=failed_from_row, failure_reason=failure_reason)


# --- Async Bulk Upload (avoids nginx 504 timeouts for large CSV files) ---

class BulkUploadJobResponse(BaseModel):
    job_id: str
    total_rows: int = 0

class BulkUploadJobStatusResponse(BaseModel):
    status: str  # processing | completed | failed
    total_rows: int = 0
    processed_rows: int = 0
    created: int = 0
    updated: int = 0
    failed_from_row: int | None = None
    failure_reason: str | None = None
    error_message: str | None = None


def _process_bulk_upload_background(job_key: str, csv_text: str, user_id: int):
    """Process bulk upload in a worker thread after the async POST returns (BackgroundTasks). Uses its own DB session."""
    from app.database import SessionLocal
    from app.models.bulk_upload_job import BulkUploadJob
    from datetime import datetime, timezone as tz

    db = SessionLocal()
    try:
        job = db.query(BulkUploadJob).filter(BulkUploadJob.job_key == job_key).first()
        if not job:
            logger.warning("[BulkUpload] worker: job not found job_key=%s", job_key)
            return
        logger.info("[BulkUpload] worker started job_key=%s user_id=%s total_rows=%s", job_key, user_id, job.total_rows or 0)
        current_user = db.query(User).filter(User.id == user_id).first()
        if not current_user:
            job.status = "failed"
            job.error_message = "User not found"
            job.completed_at = datetime.now(tz.utc)
            db.commit()
            return

        profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
        if not profile:
            profile = OwnerProfile(user_id=current_user.id)
            db.add(profile)
            db.commit()
            db.refresh(profile)

        reader = csv.DictReader(io.StringIO(csv_text))
        orig_headers = list(reader.fieldnames or [])
        norm_to_orig = {h.strip().lower().replace(" ", "_"): h for h in orig_headers}
        rows = list(reader)
        if not rows:
            job.status = "completed"
            job.failure_reason = "CSV has no data rows."
            job.completed_at = datetime.now(tz.utc)
            db.commit()
            return

        job.total_rows = len(rows)
        job.processed_rows = 0
        db.commit()

        created = 0
        updated = 0
        failed_from_row = None
        failure_reason = None
        existing_props = (
            db.query(Property)
            .filter(Property.owner_profile_id == profile.id, Property.deleted_at.is_(None))
            .all()
        )

        def _get_cell(row, *keys):
            for k in keys:
                orig = norm_to_orig.get(k) or norm_to_orig.get(k.replace("_", ""))
                if orig and row.get(orig) is not None:
                    v = str(row[orig]).strip()
                    if v:
                        return v
            return None

        for idx, row in enumerate(rows, start=1):
            row_num = idx
            logger.info("[BulkUpload] processing CSV row %s/%s job_key=%s", idx, len(rows), job_key)
            address = _get_cell(row, "address", "street_address", "street")
            unit_no = _get_cell(row, "unit_no", "unit")
            city_val = _get_cell(row, "city")
            state_val = _get_cell(row, "state")
            zip_code = _get_cell(row, "zip", "zip_code")
            occupied_raw = _get_cell(row, "occupied")
            tenant_name = _get_cell(row, "tenant_name")
            lease_start_str = _get_cell(row, "lease_start")
            lease_end_str = _get_cell(row, "lease_end")
            shield_mode_raw = _get_cell(row, "shield_mode", "shieldmode")
            primary_residence_raw = _get_cell(row, "is_primary_residence", "owner_occupied", "primary_residence")
            tax_id_raw = _get_cell(row, "tax_id")
            apn_raw = _get_cell(row, "apn", "parcel")
            property_name_raw = _get_cell(row, "property_name", "name")
            occupied_unit_raw = _get_cell(row, "occupied_unit", "unit_label")

            street = (address or "").strip()
            if unit_no:
                street = f"{street}, {unit_no.strip()}".strip(", ")
            if not street:
                failed_from_row = row_num
                failure_reason = "Missing required column: Address."
                break
            if not city_val:
                failed_from_row = row_num
                failure_reason = "Missing required column: City."
                break
            if not state_val:
                failed_from_row = row_num
                failure_reason = "Missing required column: State."
                break
            if not zip_code:
                failed_from_row = row_num
                failure_reason = "Missing required column: Zip."
                break
            if occupied_raw is None or not str(occupied_raw).strip():
                failed_from_row = row_num
                failure_reason = "Missing required column: Occupied (YES/NO)."
                break

            state_upper = state_val.upper()[:50]
            city_norm = _normalize_addr(city_val)
            street_norm = _normalize_addr(street)
            if not city_norm or not street_norm:
                failed_from_row = row_num
                failure_reason = "Address, city, and state cannot be blank after trimming."
                break

            occupied = _parse_bool_cell(occupied_raw)
            shield_mode = _parse_bool_cell(shield_mode_raw)
            primary_residence = _parse_bool_cell(primary_residence_raw)
            region_code = state_upper.upper()[:20]
            address_as_name = f"{street.strip()}, {city_val.strip()}, {state_upper}".strip(", ")
            prop_name = (property_name_raw or "").strip() or address_as_name

            if occupied:
                if not (tenant_name or "").strip():
                    failed_from_row = row_num
                    failure_reason = "When Occupied=YES, Tenant Name is required."
                    break
                lease_start = _parse_date_cell(lease_start_str)
                lease_end = _parse_date_cell(lease_end_str)
                if not lease_start:
                    failed_from_row = row_num
                    failure_reason = "When Occupied=YES, Lease Start is required (e.g. YYYY-MM-DD)."
                    break
                if not lease_end:
                    failed_from_row = row_num
                    failure_reason = "When Occupied=YES, Lease End is required (e.g. YYYY-MM-DD)."
                    break
                if lease_end <= lease_start:
                    failed_from_row = row_num
                    failure_reason = "Lease End must be after Lease Start."
                    break

            state_norm_check = _normalize_addr(state_val)
            existing_match = None
            for p in existing_props:
                if _normalize_addr(p.street) == street_norm and _normalize_addr(p.city) == city_norm and _normalize_addr(p.state) == state_norm_check:
                    existing_match = p
                    break

            if existing_match is None:
                owner_occ = primary_residence
                occ_status = OccupancyStatus.occupied.value if (occupied or owner_occ) else OccupancyStatus.vacant.value
                prop = Property(
                    owner_profile_id=profile.id,
                    name=prop_name,
                    street=street.strip(),
                    city=city_val.strip(),
                    state=state_upper,
                    zip_code=zip_code.strip() if zip_code else None,
                    region_code=region_code,
                    owner_occupied=owner_occ,
                    property_type=None,
                    occupancy_status=occ_status,
                    shield_mode_enabled=persisted_shield_row_int(csv_parsed_on=shield_mode),
                )
                prop.tax_id = (tax_id_raw or "").strip() or None
                prop.apn = (apn_raw or "").strip() or None
                db.add(prop)
                db.flush()
                _ensure_property_live_slug(prop, db)
                for _ in range(10):
                    token = "USAT-" + secrets.token_hex(12).upper()
                    if db.query(Property).filter(Property.usat_token == token).first() is None:
                        prop.usat_token = token
                        break
                else:
                    prop.usat_token = "USAT-" + secrets.token_hex(8).upper() + "-" + str(prop.id)
                prop.usat_token_state = USAT_TOKEN_RELEASED if occupied else USAT_TOKEN_STAGED
                created += 1

                create_log(
                    db,
                    CATEGORY_STATUS_CHANGE,
                    "Property registered (async CSV)",
                    f"Owner registered property: {prop_name} (id={prop.id}). Occupancy status: {prop.occupancy_status} (initial).",
                    property_id=prop.id,
                    actor_user_id=current_user.id,
                    actor_email=current_user.email,
                    meta={"property_id": prop.id, "bulk_upload_row": row_num, "street": street.strip(), "city": city_val.strip(), "state": state_upper},
                )
                _addr_line_a = _csv_bulk_address_line(street.strip(), city_val.strip(), state_upper, zip_code.strip() if zip_code else None)
                create_ledger_event(
                    db,
                    ACTION_BULK_UPLOAD_PROPERTY_CREATED,
                    target_object_type="Property",
                    target_object_id=prop.id,
                    property_id=prop.id,
                    actor_user_id=current_user.id,
                    meta=_ledger_meta_bulk_property_created(
                        property_name=prop_name,
                        property_address=_addr_line_a,
                        csv_row=row_num,
                        property_id=prop.id,
                        occupancy_status=str(occ_status) if occ_status else None,
                    ),
                )
                if occupied and (tenant_name or "").strip():
                    inv_code = "INV-" + secrets.token_hex(4).upper()
                    inv_unit_id: int | None = None
                    if prop.is_multi_unit and occupied_unit_raw:
                        unit_label = str(occupied_unit_raw).strip()
                        unit_row = db.query(Unit).filter(Unit.property_id == prop.id, Unit.unit_label == unit_label).first()
                        if unit_row:
                            inv_unit_id = unit_row.id
                    if inv_unit_id is None:
                        existing_units = db.query(Unit).filter(Unit.property_id == prop.id).all()
                        if existing_units:
                            inv_unit_id = existing_units[0].id
                        else:
                            auto_unit = Unit(property_id=prop.id, unit_label="1", occupancy_status=OccupancyStatus.occupied.value)
                            db.add(auto_unit)
                            db.flush()
                            inv_unit_id = auto_unit.id
                    inv = Invitation(
                        invitation_code=inv_code,
                        owner_id=current_user.id,
                        invited_by_user_id=current_user.id,
                        property_id=prop.id,
                        unit_id=inv_unit_id,
                        guest_name=(tenant_name or "").strip(),
                        guest_email=None,
                        stay_start_date=lease_start,
                        stay_end_date=lease_end,
                        purpose_of_stay=PurposeOfStay.other,
                        relationship_to_owner=RelationshipToOwner.other,
                        region_code=prop.region_code,
                        status="ongoing",
                        token_state="BURNED",
                        invitation_kind="tenant",
                        dead_mans_switch_enabled=1,
                        dead_mans_switch_alert_email=1,
                        dead_mans_switch_alert_sms=0,
                        dead_mans_switch_alert_dashboard=1,
                        dead_mans_switch_alert_phone=0,
                    )
                    db.add(inv)
                    db.flush()
                    create_log(
                        db,
                        CATEGORY_STATUS_CHANGE,
                        "Invitation created (async CSV occupied)",
                        f"Invite ID {inv_code} created (token_state=BURNED) for property {prop.id}, tenant {tenant_name}, lease {lease_start}\u2013{lease_end}. Tenant can use invite link to sign up.",
                        property_id=prop.id,
                        invitation_id=inv.id,
                        actor_user_id=current_user.id,
                        actor_email=current_user.email,
                        meta={"invitation_code": inv_code, "token_state": "BURNED", "guest_name": (tenant_name or "").strip(), "lease_start": str(lease_start), "lease_end": str(lease_end)},
                    )
                    _ul_a = str(occupied_unit_raw).strip() if occupied_unit_raw else None
                    if not _ul_a and inv_unit_id:
                        _ur_a = db.query(Unit).filter(Unit.id == inv_unit_id).first()
                        _ul_a = (_ur_a.unit_label if _ur_a else None) or None
                    _inv_addr_a = _csv_bulk_address_line(prop.street or "", prop.city or "", prop.state or "", prop.zip_code)
                    create_ledger_event(
                        db,
                        ACTION_INVITATION_CREATED_CSV,
                        target_object_type="Invitation",
                        target_object_id=inv.id,
                        property_id=prop.id,
                        unit_id=inv_unit_id,
                        invitation_id=inv.id,
                        actor_user_id=current_user.id,
                        meta=_ledger_meta_bulk_csv_invitation(
                            property_name=(prop.name or prop_name or "").strip() or prop_name,
                            property_address=_inv_addr_a,
                            unit_label=_ul_a,
                            tenant_name=(tenant_name or "").strip(),
                            invitation_code=inv_code,
                            lease_start=lease_start,
                            lease_end=lease_end,
                            csv_row=row_num,
                        ),
                    )
                db.commit()
                db.refresh(prop)
                existing_props.append(prop)
            else:
                # Update existing property fields (same logic as sync bulk upload)
                owner_occ = primary_residence
                new_occ_status = OccupancyStatus.occupied.value if (occupied or owner_occ) else OccupancyStatus.vacant.value
                updates: dict[str, object] = {}
                if (existing_match.name or "").strip() != address_as_name:
                    updates["name"] = address_as_name
                if street.strip() != (existing_match.street or "").strip():
                    updates["street"] = street.strip()
                if city_val.strip() != (existing_match.city or "").strip():
                    updates["city"] = city_val.strip()
                if state_upper != (existing_match.state or "").strip():
                    updates["state"] = state_upper
                if zip_code and (existing_match.zip_code or "").strip() != zip_code.strip():
                    updates["zip_code"] = zip_code.strip()
                if existing_match.owner_occupied != owner_occ:
                    updates["owner_occupied"] = owner_occ
                if existing_match.occupancy_status != new_occ_status:
                    updates["occupancy_status"] = new_occ_status
                if persisted_shield_row_int(csv_parsed_on=shield_mode) != (existing_match.shield_mode_enabled or 0):
                    updates["shield_mode_enabled"] = persisted_shield_row_int(csv_parsed_on=shield_mode)
                tax_id_val = (tax_id_raw or "").strip() or None
                apn_val = (apn_raw or "").strip() or None
                if (existing_match.tax_id or None) != tax_id_val:
                    updates["tax_id"] = tax_id_val
                if (existing_match.apn or None) != apn_val:
                    updates["apn"] = apn_val
                new_token_state = USAT_TOKEN_RELEASED if occupied else USAT_TOKEN_STAGED
                if (existing_match.usat_token_state or USAT_TOKEN_STAGED) != new_token_state:
                    existing_match.usat_token_state = new_token_state
                    updates["usat_token_state"] = new_token_state

                for key, val in updates.items():
                    if key == "name":
                        existing_match.name = val
                    elif key == "street":
                        existing_match.street = val
                    elif key == "city":
                        existing_match.city = val
                    elif key == "state":
                        existing_match.state = val
                    elif key == "zip_code":
                        existing_match.zip_code = val
                    elif key == "owner_occupied":
                        existing_match.owner_occupied = val
                    elif key == "occupancy_status":
                        existing_match.occupancy_status = val
                    elif key == "shield_mode_enabled":
                        existing_match.shield_mode_enabled = val
                    elif key == "tax_id":
                        existing_match.tax_id = val
                    elif key == "apn":
                        existing_match.apn = val
                if updates:
                    updated += 1
                    _em_addr = _csv_bulk_address_line(
                        (existing_match.street or "").strip(),
                        (existing_match.city or "").strip(),
                        (existing_match.state or "").strip(),
                        (existing_match.zip_code or "").strip() or None,
                    )
                    create_ledger_event(
                        db,
                        ACTION_BULK_UPLOAD_PROPERTY_UPDATED,
                        target_object_type="Property",
                        target_object_id=existing_match.id,
                        property_id=existing_match.id,
                        actor_user_id=current_user.id,
                        meta=_ledger_meta_bulk_property_updated(
                            property_name=(existing_match.name or address_as_name or "").strip() or address_as_name,
                            property_address=_em_addr,
                            csv_row=row_num,
                            property_id=existing_match.id,
                            fields_changed=list(updates.keys()),
                        ),
                    )

                # Create invitation for occupied tenant on update (with duplicate check)
                if occupied and (tenant_name or "").strip() and lease_start and lease_end:
                    existing_inv = (
                        db.query(Invitation)
                        .filter(
                            Invitation.property_id == existing_match.id,
                            Invitation.guest_name == (tenant_name or "").strip(),
                            Invitation.stay_start_date == lease_start,
                            Invitation.stay_end_date == lease_end,
                            Invitation.status.in_(["pending", "ongoing"]),
                        )
                        .first()
                    )
                    if not existing_inv:
                        inv_code = "INV-" + secrets.token_hex(4).upper()
                        inv_unit_id_upd: int | None = None
                        if existing_match.is_multi_unit and occupied_unit_raw:
                            unit_label = str(occupied_unit_raw).strip()
                            unit_row = db.query(Unit).filter(Unit.property_id == existing_match.id, Unit.unit_label == unit_label).first()
                            if unit_row:
                                inv_unit_id_upd = unit_row.id
                        if inv_unit_id_upd is None:
                            existing_units = db.query(Unit).filter(Unit.property_id == existing_match.id).all()
                            if existing_units:
                                inv_unit_id_upd = existing_units[0].id
                            else:
                                auto_unit = Unit(property_id=existing_match.id, unit_label="1", occupancy_status=OccupancyStatus.occupied.value)
                                db.add(auto_unit)
                                db.flush()
                                inv_unit_id_upd = auto_unit.id
                        inv = Invitation(
                            invitation_code=inv_code,
                            owner_id=current_user.id,
                            invited_by_user_id=current_user.id,
                            property_id=existing_match.id,
                            unit_id=inv_unit_id_upd,
                            guest_name=(tenant_name or "").strip(),
                            guest_email=None,
                            stay_start_date=lease_start,
                            stay_end_date=lease_end,
                            purpose_of_stay=PurposeOfStay.other,
                            relationship_to_owner=RelationshipToOwner.other,
                            region_code=existing_match.region_code,
                            status="ongoing",
                            token_state="BURNED",
                            invitation_kind="tenant",
                            dead_mans_switch_enabled=1,
                            dead_mans_switch_alert_email=1,
                            dead_mans_switch_alert_sms=0,
                            dead_mans_switch_alert_dashboard=1,
                            dead_mans_switch_alert_phone=0,
                        )
                        db.add(inv)
                        db.flush()
                        create_log(
                            db,
                            CATEGORY_STATUS_CHANGE,
                            "Invitation created (async CSV occupied, update)",
                            f"Invite ID {inv_code} created (token_state=BURNED) for property {existing_match.id}, tenant {tenant_name}, lease {lease_start}\u2013{lease_end}.",
                            property_id=existing_match.id,
                            invitation_id=inv.id,
                            actor_user_id=current_user.id,
                            actor_email=current_user.email,
                            meta={"invitation_code": inv_code, "token_state": "BURNED", "guest_name": (tenant_name or "").strip(), "lease_start": str(lease_start), "lease_end": str(lease_end)},
                        )
                        _ul_au = str(occupied_unit_raw).strip() if occupied_unit_raw else None
                        if not _ul_au and inv_unit_id_upd:
                            _ur_au = db.query(Unit).filter(Unit.id == inv_unit_id_upd).first()
                            _ul_au = (_ur_au.unit_label if _ur_au else None) or None
                        _inv_addr_au = _csv_bulk_address_line(
                            existing_match.street or "", existing_match.city or "", existing_match.state or "", existing_match.zip_code
                        )
                        create_ledger_event(
                            db,
                            ACTION_INVITATION_CREATED_CSV,
                            target_object_type="Invitation",
                            target_object_id=inv.id,
                            property_id=existing_match.id,
                            unit_id=inv_unit_id_upd,
                            invitation_id=inv.id,
                            actor_user_id=current_user.id,
                            meta=_ledger_meta_bulk_csv_invitation(
                                property_name=(existing_match.name or address_as_name or "").strip() or address_as_name,
                                property_address=_inv_addr_au,
                                unit_label=_ul_au,
                                tenant_name=(tenant_name or "").strip(),
                                invitation_code=inv_code,
                                lease_start=lease_start,
                                lease_end=lease_end,
                                csv_row=row_num,
                            ),
                        )
                db.commit()

            job.processed_rows = idx
            job.created = created
            job.updated = updated
            db.commit()

        job.status = "completed"
        job.created = created
        job.updated = updated
        job.failed_from_row = failed_from_row
        job.failure_reason = failure_reason
        job.completed_at = datetime.now(tz.utc)
        db.commit()

        # Trigger billing (subscription + sync) — matches the sync bulk upload path
        if created >= 1 or updated >= 1:
            print(f"[AsyncBulkUpload] Starting billing post-processing for user_id={user_id}, created={created}, updated={updated}", flush=True)
            try:
                profile_fresh = db.query(OwnerProfile).filter(OwnerProfile.user_id == user_id).first()
                if not profile_fresh:
                    print(f"[AsyncBulkUpload] No OwnerProfile found for user_id={user_id}, skipping billing", flush=True)
                else:
                    print(f"[AsyncBulkUpload] Profile id={profile_fresh.id}, onboarding_billing_completed_at={profile_fresh.onboarding_billing_completed_at}, stripe_customer_id={profile_fresh.stripe_customer_id}", flush=True)
                    total_units = db.query(Property).filter(
                        Property.owner_profile_id == profile_fresh.id,
                        Property.deleted_at.is_(None),
                    ).count()
                    print(f"[AsyncBulkUpload] Total billing units (properties): {total_units}", flush=True)
                    if profile_fresh.onboarding_billing_completed_at is None:
                        if total_units >= 1:
                            try:
                                result_url = on_onboarding_properties_completed(db, profile_fresh, current_user, total_units)
                                print(f"[AsyncBulkUpload] Onboarding billing completed, invoice_url={result_url}", flush=True)
                            except Exception as e:
                                import traceback
                                print(f"[AsyncBulkUpload] Onboarding billing FAILED: {e}\n{traceback.format_exc()}", flush=True)
                        else:
                            print(f"[AsyncBulkUpload] No properties found (total_units=0), skipping billing setup", flush=True)
                    elif profile_fresh.onboarding_invoice_paid_at is not None and profile_fresh.stripe_customer_id and not profile_fresh.stripe_subscription_id:
                        try:
                            ensure_subscription(db, profile_fresh, current_user)
                            print(f"[AsyncBulkUpload] Subscription ensured", flush=True)
                        except Exception as e:
                            print(f"[AsyncBulkUpload] Subscription ensure FAILED: {e}", flush=True)
                    else:
                        print(f"[AsyncBulkUpload] Onboarding already completed, paid_at={profile_fresh.onboarding_invoice_paid_at}", flush=True)
                    try:
                        sync_subscription_quantities(db, profile_fresh)
                        print(f"[AsyncBulkUpload] Subscription quantities synced", flush=True)
                    except Exception as e:
                        print(f"[AsyncBulkUpload] Subscription sync FAILED: {e}", flush=True)
            except Exception as e:
                import traceback
                print(f"[AsyncBulkUpload] Billing post-processing FAILED: {e}\n{traceback.format_exc()}", flush=True)

    except Exception as e:
        try:
            job = db.query(BulkUploadJob).filter(BulkUploadJob.job_key == job_key).first()
            if job:
                job.status = "failed"
                job.error_message = str(e)[:500]
                job.completed_at = datetime.now(tz.utc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.post("/properties/bulk-upload-async", response_model=BulkUploadJobResponse)
def bulk_upload_properties_async(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Accept CSV for bulk upload and process asynchronously. Returns a job_id to poll for status."""
    from app.models.bulk_upload_job import BulkUploadJob

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file.")

    content = b""
    try:
        content = file.file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read file: {e!s}")
    if not content:
        raise HTTPException(status_code=400, detail="File is empty.")

    try:
        text = content.decode("utf-8-sig").strip()
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded.")

    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=400, detail="CSV has no data rows.")

    job_key = secrets.token_hex(16)
    job = BulkUploadJob(
        job_key=job_key,
        user_id=current_user.id,
        status="processing",
        csv_content=text,
        total_rows=len(rows),
        processed_rows=0,
    )
    db.add(job)
    db.commit()

    logger.info(
        "[BulkUpload] POST accepted job_key=%s total_rows=%s user_id=%s — scheduling background worker",
        job_key,
        len(rows),
        current_user.id,
    )
    background_tasks.add_task(_process_bulk_upload_background, job_key, text, current_user.id)

    return BulkUploadJobResponse(job_id=job_key, total_rows=len(rows))


@router.get("/properties/bulk-upload-status/{job_id}", response_model=BulkUploadJobStatusResponse)
def get_bulk_upload_status(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Poll for async bulk upload job status."""
    from app.models.bulk_upload_job import BulkUploadJob

    job = db.query(BulkUploadJob).filter(
        BulkUploadJob.job_key == job_id,
        BulkUploadJob.user_id == current_user.id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return BulkUploadJobStatusResponse(
        status=job.status,
        total_rows=job.total_rows or 0,
        processed_rows=job.processed_rows or 0,
        created=job.created,
        updated=job.updated,
        failed_from_row=job.failed_from_row,
        failure_reason=job.failure_reason,
        error_message=job.error_message,
    )


@router.get("/properties/{property_id}", response_model=PropertyResponse)
def get_property(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    print(f"[PropertyFlow] get_property: property_id={property_id}")
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    # Backfill live_slug if missing (e.g. bulk-uploaded property) so live link / QR section is always available
    if not prop.live_slug:
        _ensure_property_live_slug(prop, db)
        db.commit()
        db.refresh(prop)
    from app.schemas.owner import PropertyJurisdictionDocumentation
    from app.services.jurisdiction_sot import get_jurisdiction_for_property
    payload = PropertyResponse.model_validate(prop).model_dump()
    # Use effective occupancy (includes units with on-site manager) for display
    units = db.query(Unit).filter(Unit.property_id == property_id).all()
    payload["occupancy_status"] = get_property_display_occupancy_status(db, prop, units)
    jinfo = get_jurisdiction_for_property(db, prop.zip_code, prop.region_code)
    if jinfo:
        payload["jurisdiction_documentation"] = PropertyJurisdictionDocumentation(
            name=jinfo.name,
            region_code=jinfo.region_code,
            jurisdiction_group=jinfo.jurisdiction_group,
            legal_threshold_days=jinfo.legal_threshold_days,
            platform_renewal_cycle_days=jinfo.platform_renewal_cycle_days,
            reminder_days_before=jinfo.reminder_days_before,
            max_stay_days=jinfo.max_stay_days,
            warning_days=jinfo.warning_days or 0,
            tenancy_threshold_days=jinfo.tenancy_threshold_days,
        )
    return PropertyResponse(**payload)


class UnitSummary(BaseModel):
    id: int
    unit_label: str
    occupancy_status: str = "unknown"
    is_primary_residence: bool = False
    occupied_by: str | None = None  # guest name, "X (Property manager)", or tenant name
    invite_id: str | None = None  # invitation_code when applicable (not for manager/tenant)


@router.get("/properties/{property_id}/units", response_model=list[UnitSummary])
def list_property_units(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
    context_mode: str = Depends(get_context_mode),
):
    """List units for an owner's property. Business mode: no guest names (occupied_by, invite_id) for privacy."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
        Property.deleted_at.is_(None),
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    units = db.query(Unit).filter(Unit.property_id == property_id).all()
    if not units:
        # Single-unit property: return implicit unit (id=0 for "whole property")
        return [
            UnitSummary(
                id=0,
                unit_label="1",
                occupancy_status=prop.occupancy_status or OccupancyStatus.unknown.value,
                is_primary_residence=bool(prop.owner_occupied),
                occupied_by=None,
                invite_id=None,
            )
        ]
    unit_ids = [u.id for u in units]
    if context_mode == "personal":
        guest_detail_units = set(get_owner_personal_mode_units(db, current_user.id))
        occupancy_display = get_units_occupancy_display(
            db, unit_ids, anonymize_tenant_lane=False, guest_detail_unit_ids=guest_detail_units
        )
    else:
        occupancy_display = {}
    return [
        UnitSummary(
            id=u.id,
            unit_label=u.unit_label,
            occupancy_status=get_unit_display_occupancy_status(db, u),
            is_primary_residence=bool(getattr(u, "is_primary_residence", 0)),
            occupied_by=occupancy_display.get(u.id, {}).get("occupied_by") if context_mode == "personal" else None,
            invite_id=occupancy_display.get(u.id, {}).get("invite_id") if context_mode == "personal" else None,
        )
        for u in units
    ]


class InviteManagerRequest(BaseModel):
    email: str


@router.post("/properties/{property_id}/invite-manager")
def invite_property_manager(
    property_id: int,
    data: InviteManagerRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Owner invites a property manager by email. Manager receives an email with signup link."""
    if not can_assign_property_manager(db, current_user, property_id):
        raise HTTPException(status_code=403, detail="Only the property owner can invite managers.")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.deleted_at.is_(None),
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile or prop.owner_profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Property not found")
    email = (data.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email is required")
    from app.services.permissions import validate_invite_email_role, email_conflicts_with_property_as_tenant_or_guest
    role_err = validate_invite_email_role(db, email, UserRole.property_manager)
    if role_err:
        raise HTTPException(status_code=409, detail=role_err)
    if email_conflicts_with_property_as_tenant_or_guest(db, email=email, property_id=property_id):
        raise HTTPException(
            status_code=409,
            detail="This email is currently associated with a tenant or guest presence on this property and cannot be invited as a property manager for this property.",
        )
    existing_user = db.query(User).filter(User.email == email, User.role == UserRole.property_manager).first()
    if existing_user:
        existing_assignment = db.query(PropertyManagerAssignment).filter(
            PropertyManagerAssignment.property_id == property_id,
            PropertyManagerAssignment.user_id == existing_user.id,
        ).first()
        if existing_assignment:
            raise HTTPException(status_code=400, detail="This manager is already assigned to this property.")
    # Create invitation
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=MANAGER_INVITE_EXPIRE_DAYS)
    inv = ManagerInvitation(
        token=token,
        property_id=property_id,
        invited_by_user_id=current_user.id,
        email=email,
        status="pending",
        expires_at=expires_at,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    # Build signup link
    base_url = (get_settings().stripe_identity_return_url or get_settings().frontend_base_url or "http://localhost:5173").strip().split("#")[0].rstrip("/")
    invite_link = f"{base_url}/#register/manager/{token}"
    property_name = (prop.name or f"{prop.street}, {prop.city}").strip() or "Property"
    sent = send_manager_invite_email(email, invite_link, property_name)
    create_ledger_event(
        db,
        ACTION_MANAGER_INVITED,
        target_object_type="ManagerInvitation",
        target_object_id=inv.id,
        property_id=property_id,
        actor_user_id=current_user.id,
        meta={
            "message": f"Property manager invitation sent to {email} for {property_name}.",
            "email": email,
            "property_id": property_id,
            "invite_id": inv.id,
            "email_sent": sent,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "").strip() or None,
    )
    db.commit()
    response: dict = {"status": "success", "message": "Invitation sent." if sent else "Invitation created. Email delivery may not be configured."}
    response["invite_link"] = invite_link
    if getattr(get_settings(), "test_mode", False) or getattr(get_settings(), "dms_test_mode", False):
        logger.info("[test_mode] Property manager invite link: %s", invite_link)
    return response


class AssignedManagerItem(BaseModel):
    user_id: int
    email: str
    full_name: str | None
    has_resident_mode: bool = False
    resident_unit_id: int | None = None
    resident_unit_label: str | None = None
    presence_status: str | None = None  # "present" | "away" when has_resident_mode
    presence_away_started_at: str | None = None


@router.get("/properties/{property_id}/assigned-managers", response_model=list[AssignedManagerItem])
def list_assigned_managers(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """List property managers assigned to this property. Owner only."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        return []
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    assignments = db.query(PropertyManagerAssignment).filter(
        PropertyManagerAssignment.property_id == property_id,
    ).all()
    out = []
    for a in assignments:
        u = db.query(User).filter(User.id == a.user_id).first()
        if not u or u.role != UserRole.property_manager:
            continue
        resident = (
            db.query(ResidentMode)
            .join(Unit, ResidentMode.unit_id == Unit.id)
            .filter(
                ResidentMode.user_id == a.user_id,
                ResidentMode.mode == ResidentModeType.manager_personal,
                Unit.property_id == property_id,
            )
            .first()
        )
        unit_row = db.query(Unit).filter(Unit.id == resident.unit_id).first() if resident else None
        presence_status = None
        presence_away_started_at = None
        if resident is not None:
            pres = db.query(ResidentPresence).filter(
                ResidentPresence.user_id == a.user_id,
                ResidentPresence.unit_id == resident.unit_id,
            ).first()
            if pres:
                presence_status = pres.status.value if hasattr(pres.status, "value") else str(pres.status)
                presence_away_started_at = pres.away_started_at.isoformat() if pres.away_started_at else None
            else:
                presence_status = "away"  # default before manager has set presence
        out.append(AssignedManagerItem(
            user_id=u.id,
            email=u.email or "",
            full_name=getattr(u, "full_name", None),
            has_resident_mode=resident is not None,
            resident_unit_id=resident.unit_id if resident else None,
            resident_unit_label=unit_row.unit_label if unit_row else None,
            presence_status=presence_status,
            presence_away_started_at=presence_away_started_at,
        ))
    return out


class RemoveManagerRequest(BaseModel):
    manager_user_id: int


@router.post("/properties/{property_id}/managers/remove")
def remove_property_manager(
    property_id: int,
    data: RemoveManagerRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Remove a property manager from this property. Owner only; requires business context (can_assign_property_manager)."""
    if not can_assign_property_manager(db, current_user, property_id):
        raise HTTPException(status_code=403, detail="Only the property owner can remove managers from this property.")
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Owner profile not found")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    assn = db.query(PropertyManagerAssignment).filter(
        PropertyManagerAssignment.property_id == property_id,
        PropertyManagerAssignment.user_id == data.manager_user_id,
    ).first()
    if not assn:
        raise HTTPException(status_code=404, detail="Manager is not assigned to this property.")
    mgr = db.query(User).filter(User.id == data.manager_user_id).first()
    mgr_email = (mgr.email or "").strip() if mgr else None
    prop_name = (prop.name or f"{prop.street}, {prop.city}").strip() or f"Property {property_id}"
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_ledger_event(
        db,
        ACTION_MANAGER_REMOVED_FROM_PROPERTY,
        target_object_type="PropertyManagerAssignment",
        target_object_id=assn.id,
        property_id=property_id,
        actor_user_id=current_user.id,
        meta={
            "message": f"Property manager removed from {prop_name}: {mgr_email or data.manager_user_id}.",
            "manager_user_id": data.manager_user_id,
            "manager_email": mgr_email,
        },
        ip_address=ip,
        user_agent=ua,
    )
    db.delete(assn)
    db.commit()
    return {"status": "success", "message": "Manager removed from property."}


class AddResidentModeRequest(BaseModel):
    manager_user_id: int
    unit_id: int


@router.post("/properties/{property_id}/managers/add-resident-mode")
def add_manager_resident_mode(
    property_id: int,
    data: AddResidentModeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Grant a property manager Personal Mode for a unit (manager lives on-site). Owner only. Managers can also self-register via POST /managers/properties/{id}/my-resident-mode."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Owner profile not found")
    if not can_assign_property_manager(db, current_user, property_id):
        raise HTTPException(status_code=403, detail="Only the property owner can manage managers.")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return add_manager_onsite_resident(
        db,
        property_id,
        data.manager_user_id,
        data.unit_id,
        actor_user_id=current_user.id,
        initiator="owner",
        request=request,
    )


@router.post("/properties/{property_id}/managers/remove-resident-mode")
def remove_manager_resident_mode(
    property_id: int,
    data: RemoveManagerRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Remove a property manager as on-site resident for this property. The manager stays assigned; only their Personal Mode (resident) link is removed. Owner only. Managers can also self-remove via DELETE /managers/properties/{id}/my-resident-mode."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Owner profile not found")
    if not can_assign_property_manager(db, current_user, property_id):
        raise HTTPException(status_code=403, detail="Only the property owner can manage on-site residents.")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return remove_manager_onsite_resident(
        db,
        property_id,
        data.manager_user_id,
        actor_user_id=current_user.id,
        initiator="owner",
        request=request,
    )


@router.get("/properties/{property_id}/utilities", response_model=PropertyUtilityProvidersResponse)
def get_property_utilities(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Return utility providers and authority letters for the property (Utility Bucket)."""
    print(f"[PropertyFlow] get_property_utilities: property_id={property_id}")
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    providers = db.query(PropertyUtilityProvider).filter(PropertyUtilityProvider.property_id == prop.id).all()
    letters = db.query(PropertyAuthorityLetter).filter(PropertyAuthorityLetter.property_id == prop.id).all()
    pending_list = get_pending_providers_for_property(prop.id)
    test_email_override = (get_settings().test_provider_email or "").strip() or None
    # Known wrong email from SerpApi when searching "Test provider" - never show this for Test provider
    _wrong_test_provider_email = "contact@switchhealth.ca"
    def _is_test_provider(p) -> bool:
        return (p.provider_name or "").strip().lower() == "test provider"
    # For "Test provider", fix DB and always use TEST_PROVIDER_EMAIL from config
    if test_email_override:
        test_lower = test_email_override.lower()
        for p in providers:
            if _is_test_provider(p):
                current = (p.contact_email or "").strip().lower()
                if current != test_lower:
                    p.contact_email = test_email_override
        db.commit()
    def _contact_email(p) -> str | None:
        if _is_test_provider(p):
            # Never return wrong SerpApi email; use config or nothing
            if test_email_override:
                return test_email_override
            stored = (p.contact_email or "").strip().lower()
            if stored == _wrong_test_provider_email:
                return None
            return p.contact_email or None
        return p.contact_email
    with_email = sum(1 for p in providers if _contact_email(p))
    print(f"[PropertyFlow] get_property_utilities: returning {len(providers)} providers ({with_email} with contact_email), {len(letters)} letters, {len(pending_list)} pending")
    return PropertyUtilityProvidersResponse(
        providers=[
            UtilityProviderResponse(
                id=p.id,
                provider_name=p.provider_name,
                provider_type=p.provider_type,
                utilityapi_id=p.utilityapi_id,
                contact_phone=p.contact_phone,
                contact_email=_contact_email(p),
            )
            for p in providers
        ],
        authority_letters=[
            AuthorityLetterResponse(
                id=l.id,
                provider_name=l.provider_name,
                provider_type=l.provider_type or "",
                letter_content=l.letter_content,
                email_sent_at=getattr(l, "email_sent_at", None),
                signed_at=getattr(l, "signed_at", None),
                has_signed_pdf=bool(getattr(l, "signed_pdf_bytes", None)),
            )
            for l in letters
        ],
        pending_providers=[
            PendingProviderResponse(id=pp["id"], provider_name=pp["provider_name"], provider_type=pp["provider_type"], verification_status=pp["verification_status"])
            for pp in pending_list
        ],
    )


@router.post("/properties/{property_id}/utilities", response_model=PropertyUtilityProvidersResponse)
def set_property_utilities(
    property_id: int,
    body: SetPropertyUtilitiesRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Save owner-selected utility providers and generate authority letters. Pending (custom) providers are stored for later detail fetch."""
    print(f"[PropertyFlow] set_property_utilities: property_id={property_id}, selected={len(body.selected or [])}, pending={len(body.pending or [])}")
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    # Replace existing providers and letters for this property
    db.query(PropertyAuthorityLetter).filter(PropertyAuthorityLetter.property_id == prop.id).delete()
    db.query(PropertyUtilityProvider).filter(PropertyUtilityProvider.property_id == prop.id).delete()
    db.flush()
    print(f"[PropertyFlow] Cleared existing providers and letters for property_id={property_id}")
    address = ", ".join(filter(
        None,
        [
            prop.smarty_delivery_line_1 or prop.street,
            f"{prop.smarty_city_name or prop.city}, {prop.smarty_state_abbreviation or prop.state} {prop.smarty_zipcode or prop.zip_code or ''}".strip(),
        ],
    ))
    if not address.strip():
        address = f"{prop.street or ''}, {prop.city or ''}, {prop.state or ''}".strip(", ")
    # County for pending providers (from Census if we have lat/lon)
    county_name: str | None = None
    lat, lon = prop.smarty_latitude, prop.smarty_longitude
    if lat is not None and lon is not None:
        geo = geocode_coordinates(lon, lat)
        if geo:
            county_name = geo.county_name or None
    state_abbrev_for_pending = (prop.smarty_state_abbreviation or prop.state or "").strip().upper() or None
    # Add pending (user-added custom) providers to SQLite with property_id, state, county for verification job
    pending_count = 0
    for item in body.pending or []:
        pt = (item.provider_type or "").strip().lower()
        pn = (item.provider_name or "").strip()
        if pt and pn:
            add_pending_provider(pt, pn, property_id=prop.id, state=state_abbrev_for_pending, county=county_name)
            pending_count += 1
            print(f"[PropertyFlow] Added pending provider to SQLite: type={pt}, name={pn}, state={state_abbrev_for_pending!r}, county={county_name!r}")
    # Save selected providers and generate authority letters; look up contact for water
    state_abbrev = (prop.smarty_state_abbreviation or prop.state or "").strip().upper()
    city = (prop.smarty_city_name or prop.city or "").strip() or None
    test_email_for_save = (get_settings().test_provider_email or "").strip() or None
    print(f"[PropertyFlow] Property state={state_abbrev}, city={city or '(any)'}; saving selected providers")
    for item in body.selected or []:
        pn = (item.provider_name or "").strip()
        pt = (item.provider_type or "").strip().lower()
        if not pn or not pt:
            continue
        contact_phone: str | None = None
        contact_email: str | None = None
        if pn == "Test provider" and test_email_for_save:
            contact_email = test_email_for_save
            print(f"[PropertyFlow] Test provider selected for {pt}; using test_provider_email for authority letter")
        elif pt == "water" and state_abbrev:
            print(f"[PropertyFlow] Water provider: calling get_water_provider_contact(name={pn!r}, state={state_abbrev}, city={city!r})")
            from app.services.water_lookup import get_water_provider_contact
            contact = get_water_provider_contact(pn, state_abbrev, city=city or None)
            contact_phone = contact.get("contact_phone")
            contact_email = contact.get("contact_email")
            print(f"[PropertyFlow] Water contact result: email={contact_email!r}, phone={contact_phone!r}")
        u = UtilityProvider(name=pn, provider_type=pt, utilityapi_id=None, phone=contact_phone, email=contact_email, raw={})
        prv = PropertyUtilityProvider(
            property_id=prop.id,
            provider_name=u.name,
            provider_type=u.provider_type,
            utilityapi_id=u.utilityapi_id,
            contact_phone=u.phone,
            contact_email=u.email,
            raw_data=_provider_to_raw(u),
        )
        db.add(prv)
        db.flush()
        content = next(
            (c for _p, c in generate_authority_letters([u], address, prop.name or "", prop.region_code, db=db, zip_code=prop.zip_code)),
            "",
        )
        letter = PropertyAuthorityLetter(
            property_id=prop.id,
            property_utility_provider_id=prv.id,
            provider_name=u.name,
            provider_type=u.provider_type,
            letter_content=content,
        )
        db.add(letter)
        print(f"[PropertyFlow] Saved provider: name={pn}, type={pt}, contact_email={contact_email!r}")
    db.commit()
    print(f"[PropertyFlow] Committed {len(body.selected or [])} providers and authority letters")
    # Send authority letter email only when the provider has contact_email. In testing (TEST_PROVIDER_EMAIL set), send only to that address—never to real authorities.
    letters_for_email = db.query(PropertyAuthorityLetter).filter(PropertyAuthorityLetter.property_id == prop.id).all()
    test_email_send = (get_settings().test_provider_email or "").strip().lower() or None
    for letter in letters_for_email:
        to_email = None
        if (letter.provider_name or "").strip() == "Test provider" and test_email_send:
            to_email = test_email_send
        elif letter.property_utility_provider_id:
            prv = db.query(PropertyUtilityProvider).filter(PropertyUtilityProvider.id == letter.property_utility_provider_id).first()
            if prv and (prv.contact_email or "").strip():
                to_email = (prv.contact_email or "").strip().lower()
        if to_email:
            if test_email_send and to_email != test_email_send:
                print(f"[PropertyFlow] Testing env: skipping send to real authority {to_email} for {letter.provider_name}")
                continue
            try:
                if send_authority_letter_to_provider(db, letter, to_email, letter.provider_name, prop.name):
                    print(f"[PropertyFlow] Authority letter email sent to {to_email} for {letter.provider_name}")
            except Exception as e:
                print(f"[PropertyFlow] Failed to send authority letter email for {letter.provider_name}: {e}")
    # Start background lookup for providers missing contact_email (electric/gas/internet)
    serp_key = (get_settings().serpapi_key or "").strip()
    if serp_key:
        need_lookup = db.query(PropertyUtilityProvider).filter(
            PropertyUtilityProvider.property_id == prop.id,
            PropertyUtilityProvider.contact_email.is_(None),
            PropertyUtilityProvider.provider_type.in_(("electric", "gas", "internet")),
        ).all()
        if need_lookup:
            print(f"[PropertyFlow] BACKGROUND JOB ENQUEUED: provider_contact_lookup property_id={prop.id} ({len(need_lookup)} providers to lookup)")
            background_tasks.add_task(submit_utility_job, run_provider_contact_lookup_job, prop.id)
        else:
            print(f"[PropertyFlow] SERPAPI_KEY set but no providers need lookup (all have contact_email or water-only)")
    else:
        print(f"[PropertyFlow] SERPAPI_KEY not set; skipping background provider-contact lookup")
    if pending_count and serp_key:
        print(f"[PropertyFlow] BACKGROUND JOB ENQUEUED: pending_provider_verification ({pending_count} new pending)")
        background_tasks.add_task(submit_utility_job, run_pending_provider_verification_job)
    providers = db.query(PropertyUtilityProvider).filter(PropertyUtilityProvider.property_id == prop.id).all()
    letters = db.query(PropertyAuthorityLetter).filter(PropertyAuthorityLetter.property_id == prop.id).all()
    pending_list = get_pending_providers_for_property(prop.id)
    print(f"[PropertyFlow] set_property_utilities: returning 200 with {len(providers)} providers, {len(letters)} letters, {len(pending_list)} pending")
    return PropertyUtilityProvidersResponse(
        providers=[
            UtilityProviderResponse(
                id=p.id,
                provider_name=p.provider_name,
                provider_type=p.provider_type,
                utilityapi_id=p.utilityapi_id,
                contact_phone=p.contact_phone,
                contact_email=p.contact_email,
            )
            for p in providers
        ],
        authority_letters=[
            AuthorityLetterResponse(
                id=l.id,
                provider_name=l.provider_name,
                provider_type=l.provider_type or "",
                letter_content=l.letter_content,
                email_sent_at=getattr(l, "email_sent_at", None),
                signed_at=getattr(l, "signed_at", None),
                has_signed_pdf=bool(getattr(l, "signed_pdf_bytes", None)),
            )
            for l in letters
        ],
        pending_providers=[
            PendingProviderResponse(id=pp["id"], provider_name=pp["provider_name"], provider_type=pp["provider_type"], verification_status=pp["verification_status"])
            for pp in pending_list
        ],
    )


class ProviderContactsLookupRequest(BaseModel):
    """Optional: limit lookup to these provider row ids. If omitted, all providers for the property with null contact_email (electric/gas/internet) are looked up."""
    provider_ids: list[int] | None = None


class ProviderContactsLookupResponse(BaseModel):
    message: str


@router.post(
    "/properties/{property_id}/provider-contacts/lookup",
    response_model=ProviderContactsLookupResponse,
    status_code=202,
)
def lookup_provider_contacts(
    property_id: int,
    background_tasks: BackgroundTasks,
    body: ProviderContactsLookupRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """
    Start a background job to find contact emails for this property's providers (electric/gas/internet)
    that have no contact_email set. Uses SerpApi when SERPAPI_KEY is configured.
    Returns 202 Accepted; when the user loads the property later, provider emails may be filled.
    """
    print(f"[PropertyFlow] lookup_provider_contacts: property_id={property_id}, body.provider_ids={getattr(body, 'provider_ids', None) if body else None}")
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if not (get_settings().serpapi_key or "").strip():
        print(f"[PropertyFlow] lookup_provider_contacts: SERPAPI_KEY not set -> 202 with message (not configured)")
        return ProviderContactsLookupResponse(message="Provider contact lookup not configured (SERPAPI_KEY).")
    provider_ids = body.provider_ids if body else None
    print(f"[PropertyFlow] BACKGROUND JOB ENQUEUED: provider_contact_lookup property_id={property_id} provider_ids={provider_ids}")
    background_tasks.add_task(submit_utility_job, run_provider_contact_lookup_job, property_id, provider_ids)
    return ProviderContactsLookupResponse(message="Provider contact lookup started.")


@router.post("/properties/{property_id}/email-providers", response_model=EmailProvidersResponse)
def email_authority_letters_to_providers(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """
    Send authority letter email to each provider that has contact_email (one email per letter with sign link).
    When TEST_PROVIDER_EMAIL is set, only send to that address (i.e. only for providers the user chose as "Test provider"); never send to real authorities in testing.
    """
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    letters = db.query(PropertyAuthorityLetter).filter(PropertyAuthorityLetter.property_id == prop.id).all()
    if not letters:
        return EmailProvidersResponse(message="No authority letters for this property.", sent_count=0)
    test_email_send = (get_settings().test_provider_email or "").strip().lower() or None
    sent_count = 0
    for letter in letters:
        to_email = None
        if (letter.provider_name or "").strip() == "Test provider" and test_email_send:
            to_email = test_email_send
        elif letter.property_utility_provider_id:
            prv = db.query(PropertyUtilityProvider).filter(PropertyUtilityProvider.id == letter.property_utility_provider_id).first()
            if prv and (prv.contact_email or "").strip():
                to_email = (prv.contact_email or "").strip().lower()
        if to_email:
            if test_email_send and to_email != test_email_send:
                continue  # Testing: do not send to real authorities
            try:
                if send_authority_letter_to_provider(db, letter, to_email, letter.provider_name, prop.name, resend=True):
                    sent_count += 1
                    print(f"[PropertyFlow] email-providers: authority letter sent to {to_email} for {letter.provider_name}")
            except Exception as e:
                print(f"[PropertyFlow] email-providers: failed for {letter.provider_name}: {e}")
    return EmailProvidersResponse(
        message=f"Authority letter emails sent to {sent_count} provider(s)." if sent_count else "No emails sent (no provider with contact email, or in testing only Test provider receives emails).",
        sent_count=sent_count,
    )


@router.get("/properties/{property_id}/authority-letters/{letter_id}/signed-pdf")
def get_authority_letter_signed_pdf_owner(
    property_id: int,
    letter_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Return the signed PDF for an authority letter (owner only). Fetches from Dropbox if not yet in DB."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    letter = db.query(PropertyAuthorityLetter).filter(
        PropertyAuthorityLetter.id == letter_id,
        PropertyAuthorityLetter.property_id == prop.id,
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
            letter.signed_at = letter.signed_at or datetime.now(timezone.utc)
            db.commit()
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'inline; filename="DocuStay-Authority-Letter-{letter.provider_name or "signed"}.pdf"'},
            )
    raise HTTPException(status_code=404, detail="Signed PDF not yet available. The provider may not have signed yet.")


_ALLOWED_PROOF_TYPES = frozenset({"deed", "tax_bill", "utility_bill", "mortgage_statement"})
_MAX_PROOF_SIZE = 10 * 1024 * 1024  # 10MB
_ALLOWED_CONTENT_TYPES = frozenset({"application/pdf", "image/jpeg", "image/jpg", "image/png"})


@router.post("/properties/{property_id}/ownership-proof", response_model=PropertyResponse)
def upload_ownership_proof(
    request: Request,
    property_id: int,
    proof_type: str = Form("deed"),
    proof_file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Store ownership verification document (deed, tax bill, etc.) for the property."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    proof_type = (proof_type or "deed").strip().lower()
    if proof_type not in _ALLOWED_PROOF_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid proof_type. Use one of: {sorted(_ALLOWED_PROOF_TYPES)}")
    content_type = (proof_file.content_type or "").split(";")[0].strip().lower()
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File must be PDF or image (JPEG/PNG). Got: {content_type or 'unknown'}",
        )
    contents = proof_file.file.read()
    if len(contents) > _MAX_PROOF_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10MB.")
    filename = (proof_file.filename or "proof").strip() or "proof"
    if len(filename) > 255:
        filename = filename[:251] + filename[filename.rfind("."):] if "." in filename else filename[:255]
    now = datetime.now(timezone.utc)
    prop.ownership_proof_type = proof_type
    prop.ownership_proof_filename = filename
    prop.ownership_proof_content_type = content_type
    prop.ownership_proof_bytes = contents
    prop.ownership_proof_uploaded_at = now
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Ownership proof uploaded",
        f"Owner uploaded {proof_type} proof ({filename}) for property {prop.name or prop.street}.",
        property_id=prop.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=request.client.host if request.client else None,
        meta={"proof_type": proof_type, "filename": filename},
    )
    create_ledger_event(
        db,
        ACTION_OWNERSHIP_PROOF_UPLOADED,
        target_object_type="Property",
        target_object_id=prop.id,
        property_id=prop.id,
        actor_user_id=current_user.id,
        meta={"proof_type": proof_type, "filename": filename},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(prop)
    return PropertyResponse.model_validate(prop)


@router.get("/properties/{property_id}/ownership-proof")
def get_ownership_proof(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Return the ownership proof file for viewing/download. For properties without proof, returns 404 (no exception—frontend shows friendly message)."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if not prop.ownership_proof_bytes:
        raise HTTPException(status_code=404, detail="No ownership proof uploaded for this property.")
    content_type = prop.ownership_proof_content_type or "application/octet-stream"
    filename = prop.ownership_proof_filename or "proof"
    return Response(
        content=bytes(prop.ownership_proof_bytes),
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


def _get_owner_property(property_id: int, profile: OwnerProfile, db: Session) -> Property | None:
    return db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()


def _snapshot_property(prop: Property) -> dict:
    """Current property fields that can be updated (for change detection)."""
    return {
        "name": prop.name,
        "street": prop.street,
        "city": prop.city,
        "state": prop.state,
        "zip_code": prop.zip_code,
        "region_code": prop.region_code,
        "owner_occupied": prop.owner_occupied,
        "occupancy_status": getattr(prop, "occupancy_status", None),
        "property_type": prop.property_type.value if prop.property_type else None,
        "property_type_label": prop.property_type_label,
        "bedrooms": prop.bedrooms,
        "shield_mode_enabled": getattr(prop, "shield_mode_enabled", 0),
        "vacant_monitoring_enabled": getattr(prop, "vacant_monitoring_enabled", 0),
        "tax_id": getattr(prop, "tax_id", None),
        "apn": getattr(prop, "apn", None),
    }


@router.put("/properties/{property_id}", response_model=PropertyResponse)
def update_property(
    request: Request,
    property_id: int,
    data: PropertyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
    context_mode: str = Depends(get_context_mode),
):
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = _get_owner_property(property_id, profile, db)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if context_mode != "personal":
        # Owners set primary residence only in Personal Mode; business updates cannot change it.
        data = data.model_copy(
            update={
                "is_primary_residence": None,
                "owner_occupied": None,
                "primary_residence_unit": None,
            }
        )
    old = _snapshot_property(prop)

    if data.property_name is not None:
        prop.name = data.property_name
    if data.street_address is not None or data.street is not None:
        prop.street = (data.street_address or data.street or prop.street)
    if data.city is not None:
        prop.city = data.city
    if data.state is not None:
        prop.state = data.state
    if data.zip_code is not None:
        prop.zip_code = data.zip_code
    if data.region_code is not None:
        prop.region_code = data.region_code.upper()[:20]
    if data.owner_occupied is not None:
        prop.owner_occupied = data.owner_occupied
    if data.is_primary_residence is not None and data.owner_occupied is None:
        prop.owner_occupied = data.is_primary_residence
    # When property is marked as Primary Residence (owner-occupied), unit status is Occupied
    if prop.owner_occupied:
        prop.occupancy_status = OccupancyStatus.occupied.value
    if data.property_type_enum is not None:
        prop.property_type = data.property_type_enum
    if data.property_type is not None:
        prop.property_type_label = data.property_type
    if data.bedrooms is not None:
        prop.bedrooms = data.bedrooms
    # Convert single-unit to multi-unit when type and unit_count are provided
    multi_unit_types = ("apartment", "duplex", "triplex", "quadplex")
    pt_label = (data.property_type or "").strip().lower() if data.property_type else ""
    custom_labels = data.unit_labels or []
    if pt_label in multi_unit_types and data.unit_count is not None and not prop.is_multi_unit:
        new_count = max(1, int(data.unit_count))
        prop.is_multi_unit = True
        primary_unit_idx = data.primary_residence_unit if data.primary_residence_unit is not None else None
        for i in range(1, new_count + 1):
            is_primary = primary_unit_idx is not None and primary_unit_idx == i
            label = custom_labels[i - 1] if i - 1 < len(custom_labels) and custom_labels[i - 1].strip() else str(i)
            u = Unit(
                property_id=prop.id,
                unit_label=label,
                occupancy_status=OccupancyStatus.occupied.value if is_primary else OccupancyStatus.unknown.value,
                is_primary_residence=1 if is_primary else 0,
            )
            db.add(u)
        if primary_unit_idx is not None and primary_unit_idx >= 1:
            prop.owner_occupied = True
            prop.occupancy_status = OccupancyStatus.occupied.value
        else:
            prop.owner_occupied = False
    # Multi-unit: update unit count, labels, and/or primary residence unit
    elif prop.is_multi_unit:
        units_list = db.query(Unit).filter(Unit.property_id == prop.id).order_by(Unit.id).all()
        # Rename existing units if custom labels are provided
        if custom_labels:
            for idx, u in enumerate(units_list):
                if idx < len(custom_labels) and custom_labels[idx].strip():
                    u.unit_label = custom_labels[idx].strip()
        if data.primary_residence_unit is not None:
            for u in units_list:
                u.is_primary_residence = 0
            if data.primary_residence_unit >= 1 and data.primary_residence_unit <= len(units_list):
                units_list[data.primary_residence_unit - 1].is_primary_residence = 1
                prop.owner_occupied = True
            else:
                prop.owner_occupied = False
        if data.unit_count is not None:
            new_count = max(1, int(data.unit_count))
            current_count = len(units_list)
            if new_count > current_count:
                for i in range(current_count + 1, new_count + 1):
                    label = custom_labels[i - 1] if i - 1 < len(custom_labels) and custom_labels[i - 1].strip() else str(i)
                    u = Unit(
                        property_id=prop.id,
                        unit_label=label,
                        occupancy_status=OccupancyStatus.unknown.value,
                        is_primary_residence=0,
                    )
                    db.add(u)
            elif new_count < current_count:
                units_to_remove = units_list[new_count:]
                for u in units_to_remove:
                    has_stay = db.query(Stay).filter(Stay.unit_id == u.id).first() is not None
                    has_invite = db.query(Invitation).filter(Invitation.unit_id == u.id).first() is not None
                    has_resident_mode = db.query(ResidentMode).filter(ResidentMode.unit_id == u.id).first() is not None
                    if has_stay or has_invite or has_resident_mode:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Cannot reduce units: Unit {u.unit_label} has stays, invitations, or resident mode. Remove those first.",
                        )
                    db.delete(u)
    # DO NOT REMOVE — legacy owner Shield toggle (CR-1a: always persist ON; OFF requests ignored).
    # if data.shield_mode_enabled is not None:
    #     prop.shield_mode_enabled = 1 if data.shield_mode_enabled else 0
    if data.shield_mode_enabled is not None:
        prop.shield_mode_enabled = 1
    # Vacant-unit monitoring: only enable when property is vacant; can disable anytime.
    if data.vacant_monitoring_enabled is not None:
        if data.vacant_monitoring_enabled and (getattr(prop, "occupancy_status", None) or "").lower() != OccupancyStatus.vacant.value:
            pass  # do not enable for non-vacant
        else:
            prop.vacant_monitoring_enabled = 1 if data.vacant_monitoring_enabled else 0
    if data.tax_id is not None:
        prop.tax_id = data.tax_id.strip() or None
    if data.apn is not None:
        prop.apn = data.apn.strip() or None
    # CR-1a: heal stale DB rows (DO NOT REMOVE — keeps column aligned with always-on policy).
    if SHIELD_MODE_ALWAYS_ON and getattr(prop, "shield_mode_enabled", 0) != 1:
        prop.shield_mode_enabled = 1

    new = _snapshot_property(prop)
    changes = []
    changes_meta = {}
    for key in old:
        ov, nv = old[key], new[key]
        if nv is not None and getattr(nv, "value", None) is not None:
            nv = getattr(nv, "value", nv)
        if ov is not None and getattr(ov, "value", None) is not None:
            ov = getattr(ov, "value", ov)
        if ov != nv:
            changes.append(f"{key}: {ov!r} → {nv!r}")
            changes_meta[key] = {"old": ov, "new": nv}

    if changes:
        db.flush()
        ip = request.client.host if request.client else None
        ua = (request.headers.get("user-agent") or "").strip() or None
        # Full address for notifications (e.g. "1 Infinite Loop, Cupertino, CA 95014 USA")
        address_parts = [prop.street, prop.city, (f"{prop.state} {prop.zip_code or ''}".strip())]
        property_address = ", ".join(p for p in address_parts if p).strip()
        if property_address and not property_address.endswith("USA"):
            property_address = f"{property_address} USA"
        property_name = (prop.name or "").strip() or property_address or f"Property {property_id}"
        if not property_address:
            property_address = property_name
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            "Property updated",
            f"Owner updated property: {property_address} (id={property_id}). Changes: " + "; ".join(changes),
            property_id=prop.id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=ip,
            user_agent=ua,
            meta={"property_id": property_id, "property_name": property_address, "changes": changes_meta},
        )
        changes_summary = "; ".join(changes) if changes else "details updated"
        create_ledger_event(
            db,
            ACTION_PROPERTY_UPDATED,
            target_object_type="Property",
            target_object_id=prop.id,
            property_id=prop.id,
            actor_user_id=current_user.id,
            previous_value=old,
            new_value=new,
            meta={
                "property_id": property_id,
                "property_name": property_address,
                "changes": changes_meta,
                "message": f"Property updated: {property_address}. Change made: {changes_summary}",
            },
            ip_address=ip,
            user_agent=ua,
        )
        if "shield_mode_enabled" in changes_meta:
            new_shield = changes_meta["shield_mode_enabled"].get("new")
            shield_label = "turned off" if new_shield == 0 else "turned on"
            create_ledger_event(
                db,
                ACTION_SHIELD_MODE_OFF if new_shield == 0 else ACTION_SHIELD_MODE_ON,
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
            turned_by = "property manager" if current_user.role == UserRole.property_manager else "property owner"
            try:
                if new_shield == 1:
                    send_shield_mode_turned_on_notification(owner_email, manager_emails, property_address, turned_on_by=turned_by)
                else:
                    send_shield_mode_turned_off_notification(owner_email, manager_emails, property_address, turned_off_by=turned_by)
            except Exception as e:
                print(f"[Owners] Shield mode notification failed: {e}", flush=True)
    db.commit()
    db.refresh(prop)
    if "shield_mode_enabled" in (changes_meta or {}):
        try:
            sync_subscription_quantities(db, profile)
        except Exception as e:
            print(f"[Owners] Subscription sync failed after PATCH: {e}", flush=True)
    return PropertyResponse.model_validate(prop)


def _has_active_stay(db: Session, property_id: int) -> bool:
    """True if there is any stay at this property that is not checked out and not cancelled."""
    return (
        db.query(Stay)
        .filter(
            Stay.property_id == property_id,
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
        .first()
        is not None
    )


@router.delete("/properties/{property_id}")
def delete_property(
    request: Request,
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Soft-delete property: set deleted_at so it is hidden from dashboard and invite list; can be reactivated. Only allowed when there is no active stay (past stays are OK). Data is kept for logs."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = _get_owner_property(property_id, profile, db)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if prop.deleted_at is not None:
        return {"status": "success", "message": "Property is already inactive."}
    if _has_active_stay(db, property_id):
        raise HTTPException(
            status_code=400,
            detail="Cannot remove property: it has an active guest stay. Wait for the stay to end or be cancelled first.",
        )
    property_name = (prop.name or "").strip() or f"{prop.city}, {prop.state}".strip(", ") or f"Property {property_id}"
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Property deleted",
        f"Owner removed property from dashboard (inactive): {property_name} (id={property_id}, {prop.city}, {prop.state}). Data retained for logs.",
        property_id=property_id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"property_id": property_id, "property_name": property_name},
    )
    create_ledger_event(
        db,
        ACTION_PROPERTY_DELETED,
        target_object_type="Property",
        target_object_id=property_id,
        property_id=property_id,
        actor_user_id=current_user.id,
        meta={"property_id": property_id, "property_name": property_name},
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()
    prop.deleted_at = datetime.now(timezone.utc)
    db.commit()
    try:
        sync_subscription_quantities(db, profile)
    except Exception as e:
        print(f"[Owners] Subscription sync failed after delete: {e}", flush=True)
    return {"status": "success", "message": "Property removed from dashboard. It has been moved to Inactive properties and can be reactivated."}


@router.post("/properties/{property_id}/reactivate", response_model=PropertyResponse)
def reactivate_property(
    request: Request,
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Reactivate an inactive (soft-deleted) property so it appears in dashboard and invite list again."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = _get_owner_property(property_id, profile, db)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if prop.deleted_at is None:
        db.refresh(prop)
        return PropertyResponse.model_validate(prop)
    property_name = (prop.name or "").strip() or f"{prop.city}, {prop.state}".strip(", ") or f"Property {property_id}"
    prop.deleted_at = None
    db.commit()
    try:
        ensure_subscription(db, profile, None, allow_trial=False)  # Recreate subscription if cancelled when units went to 0 (no second trial)
        sync_subscription_quantities(db, profile)
    except Exception as e:
        print(f"[Owners] Subscription ensure/sync failed after reactivate: {e}", flush=True)
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Property reactivated",
        f"Owner reactivated property: {property_name} (id={property_id}). Property now visible in dashboard.",
        property_id=property_id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"property_id": property_id, "property_name": property_name},
    )
    create_ledger_event(
        db,
        ACTION_PROPERTY_REACTIVATED,
        target_object_type="Property",
        target_object_id=property_id,
        property_id=property_id,
        actor_user_id=current_user.id,
        meta={"property_id": property_id, "property_name": property_name},
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()
    db.refresh(prop)
    return PropertyResponse.model_validate(prop)


@router.get("/invitations/jurisdiction-limits")
def get_invitation_jurisdiction_limits(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    context_mode: str = Depends(get_context_mode),
    property_id: int | None = None,
    unit_id: int | None = None,
):
    """Return max allowed stay days for the property (for calendar/date picker). Requires access to the property or unit."""
    if property_id is None and unit_id is None:
        raise HTTPException(status_code=400, detail="property_id or unit_id required")
    prop = None
    if unit_id is not None:
        unit = db.query(Unit).filter(Unit.id == unit_id).first()
        if not unit:
            raise HTTPException(status_code=404, detail="Unit not found")
        prop = db.query(Property).filter(Property.id == unit.property_id, Property.deleted_at.is_(None)).first()
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")
        if not can_perform_action(db, current_user, Action.INVITE_GUEST, unit_id=unit_id, mode=context_mode):
            raise HTTPException(status_code=403, detail="You do not have access to invite guests for this unit")
    else:
        prop = db.query(Property).filter(Property.id == property_id, Property.deleted_at.is_(None)).first()
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")
        if current_user.role == UserRole.tenant:
            raise HTTPException(status_code=400, detail="Tenants must provide unit_id for jurisdiction limits")
        if not can_access_property(db, current_user, prop.id, context_mode):
            raise HTTPException(status_code=403, detail="You do not have access to this property")
    region_code = getattr(prop, "region_code", None) or ""
    owner_occupied = bool(getattr(prop, "owner_occupied", False))
    max_days = get_max_stay_days_for_property(db, region_code, owner_occupied)
    return {"max_stay_days": max_days}


@router.post("/invitations")
def create_invitation(
    request: Request,
    data: InvitationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    context_mode: str = Depends(get_context_mode),
):
    """Create a guest invitation only (invitation_kind=guest). Owner, Tenant, or Property Manager can create.
    Tenants may only invite guests for their assigned unit; they cannot create tenant invites."""
    if not (data.guest_name or "").strip():
        raise HTTPException(status_code=400, detail="guest_name is required")
    if not data.checkin_date or not data.checkout_date:
        raise HTTPException(status_code=400, detail="checkin_date and checkout_date are required")
    start = datetime.strptime(data.checkin_date, "%Y-%m-%d").date()
    end = datetime.strptime(data.checkout_date, "%Y-%m-%d").date()
    if end <= start:
        raise HTTPException(status_code=400, detail="checkout_date must be after checkin_date")
    if start < date.today():
        raise HTTPException(status_code=400, detail="Authorization start date cannot be in the past.")

    prop = None
    unit_id = data.unit_id
    owner_user_id = None

    if current_user.role == UserRole.owner:
        # Owner: property_id required (or unit_id to infer property)
        prop_id = data.property_id
        if unit_id is not None:
            unit = db.query(Unit).filter(Unit.id == unit_id).first()
            if not unit:
                raise HTTPException(status_code=404, detail="Unit not found")
            prop = db.query(Property).filter(Property.id == unit.property_id).first()
            if not prop:
                raise HTTPException(status_code=404, detail="Property not found")
            profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
            if not profile or prop.owner_profile_id != profile.id:
                raise HTTPException(status_code=403, detail="You do not own this property")
            if profile.onboarding_billing_completed_at is not None and profile.onboarding_invoice_paid_at is None:
                raise HTTPException(
                    status_code=403,
                    detail="Billing setup is still in progress. Open Billing to finish subscription setup, or try again shortly after adding your first property.",
                )
        elif prop_id:
            profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
            if not profile:
                raise HTTPException(status_code=404, detail="Owner profile not found")
            if profile.onboarding_billing_completed_at is not None and profile.onboarding_invoice_paid_at is None:
                raise HTTPException(
                    status_code=403,
                    detail="Billing setup is still in progress. Open Billing to finish subscription setup, or try again shortly after adding your first property.",
                )
            prop = db.query(Property).filter(Property.id == prop_id, Property.owner_profile_id == profile.id).first()
            if not prop:
                raise HTTPException(status_code=404, detail="Property not found")
            # Infer unit for single-unit: use first unit if exists; else leave null (backward compat)
            units = db.query(Unit).filter(Unit.property_id == prop.id).all()
            if not prop.is_multi_unit and units:
                unit_id = units[0].id
        else:
            raise HTTPException(status_code=400, detail="property_id or unit_id required")
        owner_user_id = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
        owner_user_id = owner_user_id.user_id if owner_user_id else current_user.id

    elif current_user.role == UserRole.tenant:
        if unit_id is None:
            raise HTTPException(status_code=400, detail="unit_id required for tenant")
        if not can_perform_action(db, current_user, Action.INVITE_GUEST, unit_id=unit_id, mode="business"):
            raise HTTPException(status_code=403, detail="You do not have access to invite guests for this unit")
        unit = db.query(Unit).filter(Unit.id == unit_id).first()
        if not unit:
            raise HTTPException(status_code=404, detail="Unit not found")
        prop = db.query(Property).filter(Property.id == unit.property_id).first()
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")
        owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
        owner_user_id = owner_profile.user_id if owner_profile else None
        if not owner_user_id:
            raise HTTPException(status_code=500, detail="Property has no owner")
        ta = (
            db.query(TenantAssignment)
            .filter(TenantAssignment.unit_id == unit_id, TenantAssignment.user_id == current_user.id)
            .order_by(TenantAssignment.start_date.desc())
            .first()
        )
        if not ta:
            raise HTTPException(status_code=403, detail="You are not assigned to this unit")
        if start < ta.start_date:
            raise HTTPException(
                status_code=400,
                detail=f"Guest authorization start date cannot be before your stay starts ({ta.start_date.isoformat()}). You can only invite guests for the duration of your own stay.",
            )
        if ta.end_date is not None and end > ta.end_date:
            raise HTTPException(
                status_code=400,
                detail=f"Guest authorization end date cannot be after your stay ends ({ta.end_date.isoformat()}). You can only invite guests for the duration of your own stay.",
            )

    elif current_user.role == UserRole.property_manager:
        if unit_id is None:
            raise HTTPException(status_code=400, detail="unit_id required for property manager")
        # Manager can invite for any unit in a property they manage (business) or where they live (personal)
        if not can_perform_action(db, current_user, Action.INVITE_GUEST, unit_id=unit_id, mode="business") and not can_perform_action(db, current_user, Action.INVITE_GUEST, unit_id=unit_id, mode="personal"):
            raise HTTPException(status_code=403, detail="You do not have access to invite guests for this unit")
        unit = db.query(Unit).filter(Unit.id == unit_id).first()
        if not unit:
            raise HTTPException(status_code=404, detail="Unit not found")
        prop = db.query(Property).filter(Property.id == unit.property_id).first()
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")
        owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
        owner_user_id = owner_profile.user_id if owner_profile else None
        if not owner_user_id:
            raise HTTPException(status_code=500, detail="Property has no owner")

    else:
        raise HTTPException(status_code=403, detail="Only owners, tenants, or property managers (personal mode) can create invitations")

    if prop.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Cannot create invitation for an inactive property. Reactivate the property first.")

    # Jurisdiction: stay duration must not exceed legal limit for this property's state/region
    region_code = getattr(prop, "region_code", None) or ""
    owner_occupied = bool(getattr(prop, "owner_occupied", False))
    jurisdiction_error = validate_stay_duration_for_property(db, region_code, owner_occupied, start, end)
    if jurisdiction_error:
        raise HTTPException(status_code=400, detail=jurisdiction_error)

    code = "INV-" + secrets.token_hex(4).upper()
    guest_email_norm = str(data.guest_email).strip().lower()
    if not guest_email_norm:
        raise HTTPException(status_code=400, detail="guest_email is required")
    from app.services.permissions import validate_invite_email_role
    role_err = validate_invite_email_role(db, guest_email_norm, UserRole.guest)
    if role_err:
        raise HTTPException(status_code=409, detail=role_err)
    purpose = _PURPOSE_MAP.get((data.purpose or "visit").lower(), PurposeOfStay.travel)
    rel = _REL_MAP.get((data.relationship or "friend").lower(), RelationshipToOwner.friend)
    dms = 1
    dms_email = 1
    dms_sms = 0
    dms_dash = 1
    dms_phone = 0
    inv = Invitation(
        invitation_code=code,
        owner_id=owner_user_id,
        property_id=prop.id,
        unit_id=unit_id,
        invited_by_user_id=current_user.id,
        guest_name=(data.guest_name or "").strip() or None,
        guest_email=guest_email_norm,
        stay_start_date=start,
        stay_end_date=end,
        purpose_of_stay=purpose,
        relationship_to_owner=rel,
        region_code=prop.region_code,
        status="pending",
        token_state="STAGED",
        invitation_kind="guest",
        dead_mans_switch_enabled=dms,
        dead_mans_switch_alert_email=dms_email,
        dead_mans_switch_alert_sms=dms_sms,
        dead_mans_switch_alert_dashboard=dms_dash,
        dead_mans_switch_alert_phone=dms_phone,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Invitation created",
        f"Invite ID {code} created (token_state=STAGED) for property {prop.id}, guest {data.guest_name or guest_email_norm or '—'}, {start}–{end}.",
        property_id=prop.id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"invitation_code": code, "token_state": "STAGED", "guest_name": (data.guest_name or "").strip(), "guest_email": guest_email_norm},
    )
    invited_by_role = getattr(current_user.role, "value", None) or str(current_user.role) if current_user.role else None
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
            "guest_name": (data.guest_name or "").strip(),
            "guest_email": guest_email_norm,
            "stay_start_date": str(start),
            "stay_end_date": str(end),
            "invited_by_role": invited_by_role,
        },
        ip_address=ip,
        user_agent=ua,
    )
    if dms == 1:
        property_name = (prop.name or "").strip() or f"{getattr(prop, 'city', '')}, {getattr(prop, 'state', '')}".strip(", ") or f"Property {prop.id}"
        owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
        owner_user = db.query(User).filter(User.id == owner_profile.user_id).first() if owner_profile else None
        owner_email = (owner_user.email or "").strip() if owner_user else ""
        manager_emails = [
            (u.email or "").strip()
            for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == prop.id).all()
            for u in [db.query(User).filter(User.id == a.user_id).first()]
            if u and (u.email or "").strip()
        ]
        guest_name = (data.guest_name or "").strip() or guest_email_norm or "Unknown invitee"
        try:
            send_dead_mans_switch_enabled_notification(owner_email, manager_emails, property_name, guest_name, str(end))
        except Exception as e:
            print(f"[Owners] DMS enabled notification failed: {e}", flush=True)
    db.commit()
    return {"invitation_code": code}


@router.post("/properties/{property_id}/invite-tenant")
def owner_invite_tenant_by_property(
    property_id: int,
    request: Request,
    data: InviteTenantRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Create a tenant invitation for a single-unit property (no Unit rows). Creates invitation with unit_id=null."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Owner profile not found")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
        Property.deleted_at.is_(None),
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    units = db.query(Unit).filter(Unit.property_id == property_id).all()
    if len(units) > 1:
        raise HTTPException(status_code=400, detail="Use unit-specific invite for multi-unit properties")
    if units:
        unit = units[0]
    else:
        unit = Unit(property_id=property_id, unit_label="1", occupancy_status=OccupancyStatus.occupied.value)
        db.add(unit)
        db.flush()
    tenant_name = (data.tenant_name or "").strip()
    tenant_email = (data.tenant_email or "").strip()
    if not tenant_name:
        raise HTTPException(status_code=400, detail="tenant_name is required")
    if tenant_email:
        from app.services.permissions import validate_invite_email_role
        role_err = validate_invite_email_role(db, tenant_email, UserRole.tenant)
        if role_err:
            raise HTTPException(status_code=409, detail=role_err)
    try:
        start = datetime.strptime(data.lease_start_date, "%Y-%m-%d").date()
        end = datetime.strptime(data.lease_end_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="lease_start_date and lease_end_date must be YYYY-MM-DD")
    if end <= start:
        raise HTTPException(status_code=400, detail="lease_end_date must be after lease_start_date")
    if start < date.today():
        raise HTTPException(status_code=400, detail="Lease start date cannot be in the past")
    overlapping = (
        db.query(Invitation)
        .filter(
            Invitation.property_id == prop.id,
            Invitation.invitation_kind == "tenant",
            Invitation.status.in_(("pending", "ongoing")),
            Invitation.token_state.notin_(("CANCELLED", "REVOKED", "EXPIRED")),
            Invitation.stay_start_date <= end,
            Invitation.stay_end_date >= start,
        )
        .first()
    )
    if overlapping:
        existing_name = overlapping.guest_name or "another tenant"
        raise HTTPException(
            status_code=409,
            detail=f"A tenant lease already exists for this property that overlaps with the selected dates ({overlapping.stay_start_date.isoformat()} – {overlapping.stay_end_date.isoformat()}, {existing_name}). Please choose dates that do not overlap with an existing tenant lease.",
        )
    code = "INV-" + secrets.token_hex(4).upper()
    inv = Invitation(
        invitation_code=code,
        owner_id=current_user.id,
        property_id=prop.id,
        unit_id=unit.id,
        invited_by_user_id=current_user.id,
        guest_name=tenant_name,
        guest_email=tenant_email or None,
        stay_start_date=start,
        stay_end_date=end,
        purpose_of_stay=PurposeOfStay.other,
        relationship_to_owner=RelationshipToOwner.other,
        region_code=prop.region_code,
        status="ongoing",
        token_state="BURNED",
        invitation_kind="tenant",
        dead_mans_switch_enabled=1,
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
        "Invitation created (owner invite tenant, single-unit)",
        f"Invite ID {code} created for tenant {tenant_name} at property {prop.id}. Owner invited tenant to register.",
        property_id=prop.id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"invitation_code": code, "tenant_name": tenant_name, "tenant_email": tenant_email or "", "property_id": property_id},
    )
    tenant_invite_message = f"Tenant invitation created for {tenant_name} at property. Invite ID {code}. Lease {start}–{end}."
    create_ledger_event(
        db,
        ACTION_TENANT_INVITED,
        target_object_type="Invitation",
        target_object_id=inv.id,
        property_id=prop.id,
        unit_id=unit.id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        meta={
            "message": tenant_invite_message,
            "invitation_code": code,
            "tenant_name": tenant_name,
            "tenant_email": tenant_email or "",
            "property_id": property_id,
            "lease_start_date": str(start),
            "lease_end_date": str(end),
        },
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()
    return {"invitation_code": code, "status": "success", "message": "Tenant invitation created. Share the invite link with the tenant."}


@router.post("/units/{unit_id}/invite-tenant")
def owner_invite_tenant(
    unit_id: int,
    request: Request,
    data: InviteTenantRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Create an invitation for a tenant to register. Owner must own the property that contains the unit."""
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Owner profile not found")
    prop = db.query(Property).filter(Property.id == unit.property_id, Property.owner_profile_id == profile.id).first()
    if not prop:
        raise HTTPException(status_code=403, detail="You do not own the property for this unit")
    tenant_name = (data.tenant_name or "").strip()
    tenant_email = (data.tenant_email or "").strip()
    if not tenant_name:
        raise HTTPException(status_code=400, detail="tenant_name is required")
    if tenant_email:
        from app.services.permissions import validate_invite_email_role
        role_err = validate_invite_email_role(db, tenant_email, UserRole.tenant)
        if role_err:
            raise HTTPException(status_code=409, detail=role_err)
    try:
        start = datetime.strptime(data.lease_start_date, "%Y-%m-%d").date()
        end = datetime.strptime(data.lease_end_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="lease_start_date and lease_end_date must be YYYY-MM-DD")
    if end <= start:
        raise HTTPException(status_code=400, detail="lease_end_date must be after lease_start_date")
    if start < date.today():
        raise HTTPException(status_code=400, detail="Lease start date cannot be in the past")
    overlapping = (
        db.query(Invitation)
        .filter(
            Invitation.unit_id == unit_id,
            Invitation.invitation_kind == "tenant",
            Invitation.status.in_(("pending", "ongoing")),
            Invitation.token_state.notin_(("CANCELLED", "REVOKED", "EXPIRED")),
            Invitation.stay_start_date <= end,
            Invitation.stay_end_date >= start,
        )
        .first()
    )
    if overlapping:
        existing_name = overlapping.guest_name or "another tenant"
        raise HTTPException(
            status_code=409,
            detail=f"A tenant lease already exists for this unit that overlaps with the selected dates ({overlapping.stay_start_date.isoformat()} – {overlapping.stay_end_date.isoformat()}, {existing_name}). Please choose dates that do not overlap with an existing tenant lease.",
        )
    code = "INV-" + secrets.token_hex(4).upper()
    inv = Invitation(
        invitation_code=code,
        owner_id=current_user.id,
        property_id=prop.id,
        unit_id=unit_id,
        invited_by_user_id=current_user.id,
        guest_name=tenant_name,
        guest_email=tenant_email or None,
        stay_start_date=start,
        stay_end_date=end,
        purpose_of_stay=PurposeOfStay.other,
        relationship_to_owner=RelationshipToOwner.other,
        region_code=prop.region_code,
        status="ongoing",
        token_state="BURNED",
        invitation_kind="tenant",
        dead_mans_switch_enabled=1,
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
        "Invitation created (owner invite tenant)",
        f"Invite ID {code} created for tenant {tenant_name} at unit {unit_id}. Owner invited tenant to register.",
        property_id=prop.id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"invitation_code": code, "tenant_name": tenant_name, "tenant_email": tenant_email or "", "unit_id": unit_id},
    )
    unit_label = getattr(unit, "unit_label", str(unit_id))
    tenant_invite_message = f"Tenant invitation created for {tenant_name} at Unit {unit_label}. Invite ID {code}. Lease {start}–{end}."
    create_ledger_event(
        db,
        ACTION_TENANT_INVITED,
        target_object_type="Invitation",
        target_object_id=inv.id,
        property_id=prop.id,
        unit_id=unit_id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        meta={
            "message": tenant_invite_message,
            "invitation_code": code,
            "tenant_name": tenant_name,
            "tenant_email": tenant_email or "",
            "unit_id": unit_id,
            "lease_start_date": str(start),
            "lease_end_date": str(end),
        },
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()
    return {"invitation_code": code, "status": "success", "message": "Tenant invitation created. Share the invite link with the tenant."}


@router.post("/invitations/{invitation_id}/send-tenant-invite-email")
def owner_send_tenant_invite_email(
    invitation_id: int,
    request: Request,
    body: SendTenantInviteEmailBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Email an existing tenant invitation link (e.g. from CSV bulk upload). Saves the tenant email on the invitation."""
    inv = db.query(Invitation).filter(Invitation.id == invitation_id).first()
    if not inv or inv.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if (getattr(inv, "invitation_kind", None) or "").strip().lower() != "tenant":
        raise HTTPException(status_code=400, detail="Not a tenant invitation")
    if inv.status not in ("pending", "ongoing"):
        raise HTTPException(status_code=400, detail="Invitation is no longer pending signup")
    if inv.unit_id and db.query(TenantAssignment).filter(TenantAssignment.unit_id == inv.unit_id).first():
        raise HTTPException(status_code=400, detail="This unit already has a tenant assignment.")
    email = (str(body.email) or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email is required")
    tenant_name_in = (body.tenant_name or "").strip()
    if not tenant_name_in:
        raise HTTPException(status_code=400, detail="Tenant name is required")
    from app.services.permissions import validate_invite_email_role
    role_err = validate_invite_email_role(db, email, UserRole.tenant)
    if role_err:
        raise HTTPException(status_code=409, detail=role_err)
    inv.guest_name = tenant_name_in
    inv.guest_email = email
    db.add(inv)
    prop = db.query(Property).filter(Property.id == inv.property_id).first()
    property_name = (prop.name if prop else None) or (f"{prop.street}, {prop.city}" if prop else None) or "Property"
    tenant_name = tenant_name_in
    base_url = (get_settings().stripe_identity_return_url or get_settings().frontend_base_url or "http://localhost:5173").strip().split("#")[0].rstrip("/")
    code = (inv.invitation_code or "").strip().upper()
    invite_link = f"{base_url}/#invite/{code}"
    sent = send_tenant_invite_email(email, invite_link, tenant_name, property_name)
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Tenant invitation email sent",
        f"Invite ID {code} emailed to {email} for property {inv.property_id}.",
        property_id=inv.property_id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"invitation_code": code, "tenant_email": email},
    )
    create_ledger_event(
        db,
        ACTION_TENANT_PENDING_INVITE_EMAIL_SENT,
        target_object_type="Invitation",
        target_object_id=inv.id,
        property_id=inv.property_id,
        unit_id=inv.unit_id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        meta={
            "message": (
                f"Pending tenant invite: email sent to {email} for {tenant_name}. "
                f"Invite ID {code}. Property: {property_name}."
            ),
            "invitation_code": code,
            "tenant_email": email,
            "tenant_name": tenant_name,
        },
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()
    return {
        "status": "success",
        "message": "Invitation email sent." if sent else "Invitation saved. Email delivery may not be configured; share the link manually.",
        "invite_link": invite_link,
    }


@router.get("/invitation-details")
def get_invitation_details(
    code: str,
    db: Session = Depends(get_db),
):
    """Public: get invitation details by code for the invite signup page (guest or tenant). Type comes from invitation_kind in DB."""
    code = code.strip().upper()
    inv = db.query(Invitation).filter(Invitation.invitation_code == code).first()
    if not inv:
        return {"valid": False, "reason": "not_found"}
    token = (inv.token_state or "").upper()
    invitation_kind = (getattr(inv, "invitation_kind", None) or "guest").strip().lower()
    is_tenant = invitation_kind == "tenant"
    awaiting_account = not is_tenant and guest_invite_awaiting_account_after_sign(db, inv)
    if inv.status == "accepted" and not awaiting_account:
        return {"valid": False, "used": True, "already_accepted": True, "reason": "already_accepted"}
    if token == "BURNED" and not is_tenant and not awaiting_account:
        return {"valid": False, "used": True, "already_accepted": True, "reason": "already_accepted"}
    if token == "REVOKED":
        return {"valid": False, "revoked": True, "reason": "revoked"}
    if token == "CANCELLED" or inv.status == "cancelled":
        return {"valid": False, "cancelled": True, "reason": "cancelled"}
    if token == "EXPIRED" or inv.status == "expired":
        return {"valid": False, "expired": True, "reason": "expired"}
    # Stay created for this invite: flow is complete; avoid false "expired" from calendar/72h rules.
    if db.query(Stay).filter(Stay.invitation_id == inv.id).first() is not None:
        return {"valid": False, "used": True, "already_accepted": True, "reason": "already_accepted"}
    # Guest: past stay end date — only expire if they never started signing (calendar is not the invite clock once signing began).
    if (
        not is_tenant
        and inv.stay_end_date
        and inv.stay_end_date < date.today()
        and not awaiting_account
        and not guest_invitation_signing_started(db, code)
    ):
        return {"valid": False, "expired": True, "reason": "expired"}

    # Pending-window expiry (72h / test mode): skip if Dropbox in flight or any signature progress exists.
    if not is_tenant:
        from app.services.invitation_cleanup import get_invitation_expire_cutoff

        threshold = get_invitation_expire_cutoff()
        if inv.status == "pending" and inv.created_at is not None and inv.created_at < threshold:
            has_pending_dropbox = (
                db.query(AgreementSignature)
                .filter(
                    AgreementSignature.invitation_code == code,
                    AgreementSignature.dropbox_sign_request_id.isnot(None),
                    AgreementSignature.signed_pdf_bytes.is_(None),
                )
                .first()
                is not None
            )
            if not has_pending_dropbox and not guest_invitation_signing_started(db, code):
                return {"valid": False, "expired": True, "reason": "expired"}

    if inv.status not in ("pending", "ongoing") and not (inv.status == "accepted" and awaiting_account):
        return {"valid": False, "reason": "invalid_status"}
    prop = db.query(Property).filter(Property.id == inv.property_id).first()
    owner = db.query(User).filter(User.id == inv.owner_id).first()
    if invitation_kind not in ("guest", "tenant"):
        invitation_kind = "guest"
    return {
        "valid": True,
        "invitation_kind": invitation_kind,
        "is_tenant_invite": is_tenant,
        "property_name": prop.name if prop else None,
        "property_address": f"{prop.street}, {prop.city}, {prop.state}{(' ' + prop.zip_code) if (prop and prop.zip_code) else ''}" if prop else None,
        "stay_start_date": str(inv.stay_start_date),
        "stay_end_date": str(inv.stay_end_date),
        "region_code": inv.region_code,
        "host_name": (owner.full_name if owner else None) or (owner.email if owner else ""),
        "guest_name": inv.guest_name,
        "guest_email": getattr(inv, "guest_email", None) or None,
    }
