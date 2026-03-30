"""Jurisdiction SOT service: deterministic lookup by zip or region_code from DB."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from sqlalchemy.orm import Session

from app.models.jurisdiction import Jurisdiction, JurisdictionStatute, JurisdictionZipMapping
from app.models.region_rule import RiskLevel, StayClassification


@dataclass
class StatuteInfo:
    citation: str
    plain_english: str | None


@dataclass
class JurisdictionInfo:
    region_code: str
    state_code: str
    name: str
    jurisdiction_group: str | None
    legal_threshold_days: int | None
    platform_renewal_cycle_days: int
    reminder_days_before: int
    # Backward-compat aliases
    max_stay_days: int
    tenancy_threshold_days: int | None
    warning_days: int | None
    agreement_type: str | None
    section_3_clause: str | None
    removal_guest_text: str | None
    removal_tenant_text: str | None
    statutes: List[StatuteInfo]
    risk_level: RiskLevel
    stay_classification: StayClassification
    allow_extended_if_owner_occupied: bool


def _normalize_zip(zip_code: str | None) -> str | None:
    """Return 5-digit zip or None."""
    if not zip_code or not str(zip_code).strip():
        return None
    s = str(zip_code).strip().split("-")[0][:5]
    if len(s) < 5 or not s.isdigit():
        return None
    return s


def get_jurisdiction_for_zip(db: Session, zip_code: str | None) -> JurisdictionInfo | None:
    """Look up jurisdiction by 5-digit zip. Returns None if zip not in mapping or jurisdiction missing."""
    normalized = _normalize_zip(zip_code)
    if not normalized:
        return None
    mapping = db.query(JurisdictionZipMapping).filter(
        JurisdictionZipMapping.zip_code == normalized
    ).first()
    if not mapping:
        return None
    return get_jurisdiction_for_region(db, mapping.region_code)


def get_jurisdiction_for_region(db: Session, region_code: str | None) -> JurisdictionInfo | None:
    """Load jurisdiction and its statutes by region_code. Returns None if not found."""
    if not region_code or not str(region_code).strip():
        return None
    rc = str(region_code).strip().upper()
    jur = db.query(Jurisdiction).filter(Jurisdiction.region_code == rc).first()
    if not jur:
        return None
    statute_rows = (
        db.query(JurisdictionStatute)
        .filter(
            JurisdictionStatute.region_code == rc,
            JurisdictionStatute.use_in_authority_package == True,
        )
        .order_by(JurisdictionStatute.sort_order, JurisdictionStatute.id)
        .all()
    )
    statutes = [
        StatuteInfo(citation=s.citation, plain_english=s.plain_english)
        for s in statute_rows
    ]
    return JurisdictionInfo(
        region_code=jur.region_code,
        state_code=jur.state_code,
        name=jur.name,
        jurisdiction_group=getattr(jur, "jurisdiction_group", None),
        legal_threshold_days=getattr(jur, "legal_threshold_days", None),
        platform_renewal_cycle_days=getattr(jur, "platform_renewal_cycle_days", None) or jur.max_stay_days,
        reminder_days_before=getattr(jur, "reminder_days_before", None) or jur.warning_days or 3,
        max_stay_days=jur.max_stay_days,
        tenancy_threshold_days=jur.tenancy_threshold_days,
        warning_days=jur.warning_days,
        agreement_type=jur.agreement_type,
        section_3_clause=getattr(jur, "section_3_clause", None),
        removal_guest_text=jur.removal_guest_text,
        removal_tenant_text=jur.removal_tenant_text,
        statutes=statutes,
        risk_level=jur.risk_level,
        stay_classification=jur.stay_classification_label,
        allow_extended_if_owner_occupied=jur.allow_extended_if_owner_occupied,
    )


def get_jurisdiction_for_property(db: Session, zip_code: str | None, region_code: str | None) -> JurisdictionInfo | None:
    """Resolve jurisdiction for a property: try zip first, then fall back to region_code."""
    info = get_jurisdiction_for_zip(db, zip_code)
    if info is not None:
        return info
    return get_jurisdiction_for_region(db, region_code)
