"""Module D: Region rules database (demo legal brain)."""
from sqlalchemy import Column, Integer, String, Boolean, Enum as SQLEnum
from app.database import Base
import enum


class StayClassification(str, enum.Enum):
    guest = "guest"
    lodger = "lodger"
    tenant_risk = "tenant_risk"


class RiskLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class RegionRule(Base):
    __tablename__ = "region_rules"

    id = Column(Integer, primary_key=True, index=True)
    region_code = Column(String(20), nullable=False, index=True)  # NYC, FL, CA, TX

    max_stay_days = Column(Integer, nullable=False)
    stay_classification_label = Column(SQLEnum(StayClassification), nullable=False)
    risk_level = Column(SQLEnum(RiskLevel), nullable=False)

    statute_reference = Column(String(255), nullable=True)
    plain_english_explanation = Column(String(1000), nullable=True)

    # For CA: if True, extended stay allowed only when owner is occupied (lodger branch)
    allow_extended_if_owner_occupied = Column(Boolean, default=False)
