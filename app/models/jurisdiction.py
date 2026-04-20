"""Jurisdiction SOT: single source of truth for jurisdiction rules, statutes, and zip-based lookup."""
from sqlalchemy import Column, Integer, String, Boolean, Enum as SQLEnum, ForeignKey, Text
from app.database import Base
from app.models.region_rule import StayClassification, RiskLevel


class Jurisdiction(Base):
    """One row per state. Drives authority wrap, agreements, JLE.

    Key separation:
      legal_threshold_days    – the real statutory threshold (e.g. 30 for NY, 14 for CA)
      platform_renewal_cycle_days – how long each authorization period is (operational; usually threshold - 1)
      reminder_days_before    – days before renewal cycle ends to prompt the user
      max_stay_days           – kept for backward compat, equals platform_renewal_cycle_days
      tenancy_threshold_days  – kept for backward compat, equals legal_threshold_days
    """
    __tablename__ = "jurisdictions"

    id = Column(Integer, primary_key=True, index=True)
    region_code = Column(String(20), nullable=False, unique=True, index=True)
    state_code = Column(String(10), nullable=False)
    name = Column(String(100), nullable=False)

    jurisdiction_group = Column(String(2), nullable=True)  # A, B, C, D, E

    legal_threshold_days = Column(Integer, nullable=True)
    platform_renewal_cycle_days = Column(Integer, nullable=False)
    reminder_days_before = Column(Integer, nullable=False, default=3)

    # Backward-compat aliases (synced with new fields in seed)
    max_stay_days = Column(Integer, nullable=False)
    tenancy_threshold_days = Column(Integer, nullable=True)
    warning_days = Column(Integer, nullable=True)

    agreement_type = Column(String(64), nullable=True)
    section_3_clause = Column(Text, nullable=True)
    removal_guest_text = Column(Text, nullable=True)
    removal_tenant_text = Column(Text, nullable=True)

    stay_classification_label = Column(SQLEnum(StayClassification), nullable=False)
    risk_level = Column(SQLEnum(RiskLevel), nullable=False)
    allow_extended_if_owner_occupied = Column(Boolean, default=False)


class JurisdictionStatute(Base):
    """Statute citations and plain-English per jurisdiction. Multiple per region."""
    __tablename__ = "jurisdiction_statutes"

    id = Column(Integer, primary_key=True, index=True)
    region_code = Column(String(20), nullable=False, index=True)
    citation = Column(String(255), nullable=False)
    plain_english = Column(Text, nullable=True)
    use_in_authority_package = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)


class JurisdictionZipMapping(Base):
    """Zip code (5-digit) or zip prefix -> region_code. Deterministic lookup."""
    __tablename__ = "jurisdiction_zip_mappings"

    id = Column(Integer, primary_key=True, index=True)
    zip_code = Column(String(5), nullable=False, index=True)  # 5-digit zip
    region_code = Column(String(20), nullable=False, index=True)
