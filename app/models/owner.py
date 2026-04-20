"""Module B1: Owner onboarding."""
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Enum as SQLEnum, DateTime, Text, LargeBinary, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum

USAT_TOKEN_STAGED = "staged"
USAT_TOKEN_RELEASED = "released"


class OccupancyStatus(str, enum.Enum):
    """VACANT / OCCUPIED by default; UNCONFIRMED = vacant monitoring/no response; UNKNOWN = Status Confirmation fired, confirmation still unanswered (never a default)."""
    vacant = "vacant"
    occupied = "occupied"
    unknown = "unknown"
    unconfirmed = "unconfirmed"


class PropertyType(str, enum.Enum):
    entire_home = "entire_home"
    private_room = "private_room"


class OwnerProfile(Base):
    __tablename__ = "owner_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Billing (Stripe): flat monthly subscription ($10/mo after trial); legacy rows may still reference two line items
    stripe_customer_id = Column(String(255), nullable=True, index=True)
    stripe_subscription_id = Column(String(255), nullable=True, index=True)
    stripe_subscription_baseline_item_id = Column(String(255), nullable=True)  # primary subscription line (flat $10/mo or legacy $1/unit)
    stripe_subscription_shield_item_id = Column(String(255), nullable=True)   # legacy Shield metered line only
    onboarding_billing_completed_at = Column(DateTime(timezone=True), nullable=True)
    onboarding_billing_unit_count = Column(Integer, nullable=True)
    onboarding_invoice_paid_at = Column(DateTime(timezone=True), nullable=True)  # Billing gate for invites: set when subscription+trial starts (no separate onboarding invoice in current product)

    # Public portfolio page: unique slug for URL (e.g. /#portfolio/abc123)
    portfolio_slug = Column(String(32), unique=True, nullable=True, index=True)


    user = relationship("User", backref="owner_profile")
    properties = relationship("Property", back_populates="owner_profile")


class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, index=True)
    owner_profile_id = Column(Integer, ForeignKey("owner_profiles.id"), nullable=False)

    name = Column(String(255), nullable=True)  # e.g. "Miami Beach Condo"
    street = Column(String(255), nullable=False)
    city = Column(String(100), nullable=False)
    state = Column(String(50), nullable=False)
    zip_code = Column(String(20), nullable=True)
    region_code = Column(String(20), nullable=False)  # NYC, FL, CA, TX

    # Smarty US Street API – standardized address for ZIP-code utility bucket / authority letters
    smarty_delivery_line_1 = Column(String(64), nullable=True)
    smarty_city_name = Column(String(64), nullable=True)
    smarty_state_abbreviation = Column(String(2), nullable=True)
    smarty_zipcode = Column(String(5), nullable=True)
    smarty_plus4_code = Column(String(4), nullable=True)
    smarty_latitude = Column(Float, nullable=True)
    smarty_longitude = Column(Float, nullable=True)

    owner_occupied = Column(Boolean, nullable=False)  # is_primary_residence
    property_type = Column(SQLEnum(PropertyType), nullable=True)
    property_type_label = Column(String(50), nullable=True)  # house, apartment, condo, townhouse
    bedrooms = Column(String(10), nullable=True)  # "1", "2", "3", "4", "5+"

    # Pre-generated USAT token: created at property registration, staged until owner releases to resident guest(s)
    usat_token = Column(String(64), unique=True, nullable=True, index=True)
    usat_token_state = Column(String(20), nullable=False, default=USAT_TOKEN_STAGED)
    usat_token_released_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Soft delete: when set, property is hidden from dashboard and invite list; can be reactivated
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Shield Mode: software monitoring. Independent of vacant/occupied. Owner can turn ON or OFF anytime.
    # ON: automatically on last day of guest's stay, and when Status Confirmation runs (48h after stay end). OFF: when owner turns off, or when a new guest accepts an invitation.
    # CR-1a: default ON for new rows (DO NOT REMOVE column; legacy off-path code preserved elsewhere).
    shield_mode_enabled = Column(Integer, nullable=False, default=1)

    # Ownership verification proof (deed, tax bill, etc.) – stored in DB for property and user
    ownership_proof_type = Column(String(50), nullable=True)  # deed, tax_bill, utility_bill, mortgage_statement
    ownership_proof_filename = Column(String(255), nullable=True)
    ownership_proof_content_type = Column(String(100), nullable=True)
    ownership_proof_bytes = Column(LargeBinary, nullable=True)
    ownership_proof_uploaded_at = Column(DateTime(timezone=True), nullable=True)

    # Status: VACANT default for new properties; UNKNOWN only after Status Confirmation with no owner response; UNCONFIRMED = vacant monitoring deadline missed.
    occupancy_status = Column(String(32), nullable=False, default=OccupancyStatus.vacant.value)

    # Public live link: unique slug for URL (no DB id in URL). Used for #live/<slug> property info page.
    live_slug = Column(String(32), unique=True, nullable=True, index=True)

    # Property identifier for authority package (Jurisdictional POA wrap)
    tax_id = Column(String(64), nullable=True)
    apn = Column(String(64), nullable=True)

    # Multi-unit: when True, units are in Unit table; when False, 1 Property = 1 implicit unit
    is_multi_unit = Column(Boolean, nullable=False, default=False)

    # Vacant-unit monitoring: if enabled, system prompts at intervals; no response → UNCONFIRMED
    vacant_monitoring_enabled = Column(Integer, nullable=False, default=0)
    vacant_monitoring_last_prompted_at = Column(DateTime(timezone=True), nullable=True)
    vacant_monitoring_response_due_at = Column(DateTime(timezone=True), nullable=True)
    vacant_monitoring_confirmed_at = Column(DateTime(timezone=True), nullable=True)

    owner_profile = relationship("OwnerProfile", back_populates="properties")
