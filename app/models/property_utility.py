"""Utility providers and authority letters for properties (ZIP-code utility bucket)."""
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, LargeBinary
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.database import Base


class PropertyUtilityProvider(Base):
    """Utility providers serving a property (electric, gas, water, internet)."""
    __tablename__ = "property_utility_providers"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)

    provider_name = Column(String(255), nullable=False)
    provider_type = Column(String(32), nullable=False)  # electric, gas, water, internet
    utilityapi_id = Column(String(64), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    contact_email = Column(String(255), nullable=True)
    raw_data = Column(Text, nullable=True)  # JSON string of full provider data

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PropertyAuthorityLetter(Base):
    """Authority letter content for each utility provider at a property."""
    __tablename__ = "property_authority_letters"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    property_utility_provider_id = Column(Integer, ForeignKey("property_utility_providers.id", ondelete="CASCADE"), nullable=True)

    provider_name = Column(String(255), nullable=False)
    provider_type = Column(String(32), nullable=False)  # electric, gas, water, internet
    letter_content = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Provider sign flow: email with link -> provider opens app -> signs via Dropbox Sign -> we store signed PDF
    sign_token = Column(String(64), unique=True, nullable=True, index=True)  # token in link; one-time use per letter
    email_sent_at = Column(DateTime(timezone=True), nullable=True)
    dropbox_sign_request_id = Column(String(64), nullable=True, index=True)
    signed_at = Column(DateTime(timezone=True), nullable=True)
    signed_pdf_bytes = Column(LargeBinary, nullable=True)
    signer_email = Column(String(255), nullable=True)
