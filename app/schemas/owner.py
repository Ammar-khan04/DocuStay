"""Module B1: Owner onboarding schemas."""
from datetime import datetime
from pydantic import BaseModel, field_validator
from app.models.owner import PropertyType
from app.services.shield_mode_policy import SHIELD_MODE_ALWAYS_ON


class PropertyCreate(BaseModel):
    """Accepts reference app field names: property_name, street_address, etc."""
    property_name: str | None = None
    street_address: str | None = None
    street: str | None = None
    city: str
    state: str
    zip_code: str | None = None
    country: str = "USA"
    region_code: str | None = None
    property_type: str | None = None  # house, apartment, condo, townhouse
    bedrooms: str | None = None
    is_primary_residence: bool = False
    owner_occupied: bool | None = None
    property_type_enum: PropertyType | None = None
    unit_count: int | None = None  # When > 1: set is_multi_unit=True and create Unit rows
    unit_labels: list[str] | None = None  # Custom unit names; length must match unit_count
    primary_residence_unit: int | None = None  # For multi-unit: 1-based index of owner's primary residence unit
    tax_id: str | None = None
    apn: str | None = None


class PropertyUpdate(BaseModel):
    """All optional; only provided fields are updated."""
    property_name: str | None = None
    street_address: str | None = None
    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    region_code: str | None = None
    property_type: str | None = None
    bedrooms: str | None = None
    unit_count: int | None = None  # For multi-unit: number of units (adds/removes Unit rows)
    unit_labels: list[str] | None = None  # Custom unit names; length should match unit_count
    primary_residence_unit: int | None = None  # For multi-unit: 1-based index of owner's primary residence unit
    is_primary_residence: bool | None = None
    owner_occupied: bool | None = None
    property_type_enum: PropertyType | None = None
    shield_mode_enabled: bool | None = None
    vacant_monitoring_enabled: bool | None = None
    tax_id: str | None = None
    apn: str | None = None


class BulkUploadResult(BaseModel):
    """Result of CSV bulk upload: counts and first failure info."""
    created: int = 0
    updated: int = 0
    units_created: int = 0
    failed_from_row: int | None = None  # 1-based; None if all succeeded
    failure_reason: str | None = None


class PropertyJurisdictionDocumentation(BaseModel):
    """Jurisdiction info for property Documentation tab (from JurisdictionInfo SOT)."""
    name: str
    region_code: str
    jurisdiction_group: str | None = None
    legal_threshold_days: int | None = None
    platform_renewal_cycle_days: int
    reminder_days_before: int
    # Backward compat
    max_stay_days: int
    warning_days: int
    tenancy_threshold_days: int | None = None


class PropertyResponse(BaseModel):
    id: int
    live_slug: str | None = None  # unique public slug for live link URL (#live/<slug>)
    name: str | None
    street: str
    city: str
    state: str
    zip_code: str | None
    region_code: str
    jurisdiction_documentation: PropertyJurisdictionDocumentation | None = None  # from SOT for Documentation tab
    owner_occupied: bool
    property_type: PropertyType | None
    property_type_label: str | None
    bedrooms: str | None
    usat_token: str | None = None
    usat_token_state: str = "staged"
    usat_token_released_at: datetime | None = None
    deleted_at: datetime | None = None
    shield_mode_enabled: bool = False
    occupancy_status: str = "vacant"  # vacant | occupied | unknown (Status Confirmation only) | unconfirmed
    ownership_proof_filename: str | None = None
    ownership_proof_type: str | None = None
    ownership_proof_uploaded_at: datetime | None = None
    tax_id: str | None = None
    apn: str | None = None

    # Vacant-unit monitoring
    vacant_monitoring_enabled: bool = False
    vacant_monitoring_response_due_at: datetime | None = None

    # Multi-unit: when True, property has Unit rows (apartment, duplex, triplex, quadplex)
    is_multi_unit: bool = False
    # Number of units (1 for single-unit; from Unit table for multi-unit). Included in list response for dashboard counts.
    unit_count: int | None = None
    # Occupancy counts (for multi-unit card/status display). For single-unit, these may be 0/1 depending on effective occupancy.
    occupied_unit_count: int | None = None
    vacant_unit_count: int | None = None

    # Smarty standardized address (ZIP-code utility bucket / authority letters)
    smarty_delivery_line_1: str | None = None
    smarty_city_name: str | None = None
    smarty_state_abbreviation: str | None = None
    smarty_zipcode: str | None = None
    smarty_plus4_code: str | None = None
    smarty_latitude: float | None = None
    smarty_longitude: float | None = None

    @field_validator("shield_mode_enabled", mode="before")
    @classmethod
    def coerce_shield_mode(cls, v: bool | int | None) -> bool:
        # CR-1a: API always exposes Shield ON (DO NOT REMOVE validator — stale DB rows may still be 0).
        if SHIELD_MODE_ALWAYS_ON:
            return True
        if v is None:
            return False
        return bool(v)

    @field_validator("vacant_monitoring_enabled", mode="before")
    @classmethod
    def coerce_vacant_monitoring(cls, v: bool | int | None) -> bool:
        if v is None:
            return False
        return bool(v)

    class Config:
        from_attributes = True


class OwnerProfileCreate(BaseModel):
    pass


class UtilityProviderResponse(BaseModel):
    id: int
    provider_name: str
    provider_type: str
    utilityapi_id: str | None
    contact_phone: str | None
    contact_email: str | None


class AuthorityLetterResponse(BaseModel):
    id: int
    provider_name: str
    provider_type: str = ""
    letter_content: str
    email_sent_at: datetime | None = None
    signed_at: datetime | None = None
    has_signed_pdf: bool = False


class PendingProviderResponse(BaseModel):
    """User-added provider not in our list; verification status from background job."""
    id: int
    provider_name: str
    provider_type: str
    verification_status: str  # pending | in_progress | approved | rejected


class PropertyUtilityProvidersResponse(BaseModel):
    providers: list[UtilityProviderResponse]
    authority_letters: list[AuthorityLetterResponse]
    pending_providers: list[PendingProviderResponse] = []  # custom providers with verification status


# --- Verify address + utility options (for add-property flow) ---


class VerifyAddressRequest(BaseModel):
    street_address: str
    city: str
    state: str
    zip_code: str | None = None


class UtilityOptionItem(BaseModel):
    name: str
    phone: str | None = None


class StandardizedAddressResponse(BaseModel):
    delivery_line_1: str | None = None
    city_name: str | None = None
    state_abbreviation: str | None = None
    zipcode: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class VerifyAddressAndUtilitiesResponse(BaseModel):
    standardized_address: StandardizedAddressResponse | None = None
    providers_by_type: dict[str, list[UtilityOptionItem]]  # electric, gas, water, internet


class SelectedUtilityItem(BaseModel):
    provider_type: str  # electric, gas, water, internet
    provider_name: str


class SetPropertyUtilitiesRequest(BaseModel):
    selected: list[SelectedUtilityItem] = []  # user-chosen from list (or None skipped)
    pending: list[SelectedUtilityItem] = []  # user-added custom names -> go to pending_providers table


class OwnerConfigResponse(BaseModel):
    """Config exposed to owner frontend (e.g. dev-only test provider email)."""
    test_provider_email: str | None = None


class EmailProvidersResponse(BaseModel):
    """Result of sending authority letters to providers (or test address in dev)."""
    message: str
    sent_count: int = 0
