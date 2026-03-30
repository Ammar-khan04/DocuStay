"""Agreement signatures tied to invitation-based guest flows."""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text, LargeBinary
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class AgreementSignature(Base):
    __tablename__ = "agreement_signatures"

    id = Column(Integer, primary_key=True, index=True)

    invitation_code = Column(String(64), index=True, nullable=False)
    region_code = Column(String(20), nullable=False)

    guest_email = Column(String(255), index=True, nullable=False)
    guest_full_name = Column(String(255), nullable=False)

    typed_signature = Column(String(255), nullable=False)
    signature_method = Column(String(20), nullable=False, default="typed")  # typed (future: drawn)

    acks_read = Column(Boolean, nullable=False, default=False)
    acks_temporary = Column(Boolean, nullable=False, default=False)
    acks_vacate = Column(Boolean, nullable=False, default=False)
    acks_electronic = Column(Boolean, nullable=False, default=False)

    document_id = Column(String(100), nullable=False)
    document_title = Column(String(255), nullable=False)
    document_hash = Column(String(64), nullable=False)
    document_content = Column(Text, nullable=False)

    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(400), nullable=True)

    signed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    used_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True)

    dropbox_sign_request_id = Column(String(64), nullable=True, index=True)

    # Signed PDF stored in DB when document is signed (so we can serve without Dropbox)
    signed_pdf_bytes = Column(LargeBinary, nullable=True)

    used_by_user = relationship("User")

