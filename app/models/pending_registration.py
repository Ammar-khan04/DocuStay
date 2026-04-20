"""Pending signup data: user is created only after email verification."""
from sqlalchemy import Column, Integer, String, DateTime, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base
from app.models.user import UserRole


class PendingRegistration(Base):
    __tablename__ = "pending_registrations"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), nullable=False)

    full_name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    state = Column(String(50), nullable=True)
    city = Column(String(100), nullable=True)
    country = Column(String(50), nullable=True)

    verification_code = Column(String(10), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    # Role-specific: owner -> {poa_signature_id}; guest -> {invitation_code, agreement_signature_id, permanent_*, acks}
    extra_data = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
