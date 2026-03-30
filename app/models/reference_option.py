"""Reference/lookup options stored in DB for dropdowns (states, property types, etc.)."""
from sqlalchemy import Column, Integer, String
from app.database import Base


class ReferenceOption(Base):
    __tablename__ = "reference_options"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(64), nullable=False, index=True)  # state, property_type, relationship, purpose, bedrooms, proof_type
    value = Column(String(128), nullable=False)
    label = Column(String(255), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
