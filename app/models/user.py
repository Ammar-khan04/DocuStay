"""Module A: User and authentication."""
from sqlalchemy import Column, Integer, String, Enum as SQLEnum, DateTime, Boolean, UniqueConstraint
from sqlalchemy.sql import func
from app.database import Base
import enum


class UserRole(str, enum.Enum):
    owner = "owner"
    property_manager = "property_manager"
    tenant = "tenant"
    guest = "guest"
    admin = "admin"


class OwnerType(str, enum.Enum):
    """Owner of Record vs Authorized Agent (e.g. property manager)."""
    owner_of_record = "owner_of_record"
    authorized_agent = "authorized_agent"


class User(Base):
    __tablename__ = "users"
    # Same email may be used for separate accounts per role (e.g. guest and tenant). Uniqueness is (email, role)
    # only—duplicate email + duplicate role is rejected by this constraint and by signup flows.
    __table_args__ = (UniqueConstraint("email", "role", name="uq_users_email_role"),)

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), nullable=False)

    full_name = Column(String(255), nullable=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    account_type = Column(String(50), nullable=True)  # individual | property_management_company | leasing_company
    phone = Column(String(50), nullable=True)
    state = Column(String(50), nullable=True)
    city = Column(String(100), nullable=True)
    country = Column(String(50), nullable=True)

    email_verified = Column(Boolean, default=False, nullable=False)
    email_verification_code = Column(String(10), nullable=True)
    email_verification_expires_at = Column(DateTime(timezone=True), nullable=True)

    # Owner/Manager identity verification (Stripe Identity) – required before POA and dashboard
    identity_verified_at = Column(DateTime(timezone=True), nullable=True)
    stripe_verification_session_id = Column(String(255), nullable=True, index=True)
    # Legacy owners (created before POA flow): waived POA requirement so they can access dashboard
    poa_waived_at = Column(DateTime(timezone=True), nullable=True)

    # Owner type: Owner of Record vs Authorized Agent (property manager)
    owner_type = Column(SQLEnum(OwnerType), nullable=True)  # only for role=owner
    authorized_agent_certified_at = Column(DateTime(timezone=True), nullable=True)  # when Agent certified authority

    # One-time password reset: set when forgot-password email is sent, cleared after successful reset
    password_reset_token = Column(String(255), nullable=True, index=True)
    password_reset_expires_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
