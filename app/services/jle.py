"""Module E: Mini Jurisdiction Logic Resolver (deterministic, spec-aligned). Uses jurisdiction SOT when available.

Key distinction:
  legal_threshold_days        – the real statutory threshold (displayed to users as the actual law)
  platform_renewal_cycle_days – operational authorization period (drives stay creation and renewal)
Compliance is checked against the platform_renewal_cycle_days (the operational limit the platform
enforces). The legal_threshold_days is informational — shown in UI, agreements, and authority packages.
"""
from __future__ import annotations

from datetime import date
from sqlalchemy.orm import Session
from app.models.region_rule import RegionRule, StayClassification, RiskLevel
from app.schemas.jle import JLEInput, JLEResult


def resolve_jurisdiction(db: Session, inp: JLEInput) -> JLEResult | None:
    """Resolve legal classification and limits. Prefer jurisdiction SOT (DB); fall back to region_rules."""
    from app.services.jurisdiction_sot import get_jurisdiction_for_region

    rc = inp.region_code.upper() if inp.region_code else ""
    jinfo = get_jurisdiction_for_region(db, rc)
    if jinfo:
        operational_limit = jinfo.platform_renewal_cycle_days
        classification = jinfo.stay_classification
        if jinfo.allow_extended_if_owner_occupied and inp.owner_occupied:
            operational_limit = 90
            classification = StayClassification.lodger
        statutes = [s.citation for s in jinfo.statutes]
        within = inp.stay_duration_days <= operational_limit
        compliance = "within_limit" if within else "exceeds_limit"
        message = None
        legal = jinfo.legal_threshold_days
        if not within and legal:
            message = (
                f"Stay of {inp.stay_duration_days} days exceeds the platform renewal cycle "
                f"of {operational_limit} days (jurisdiction legal threshold: {legal} days)."
            )
        elif not within:
            message = f"Stay of {inp.stay_duration_days} days exceeds the platform renewal cycle of {operational_limit} days."
        return JLEResult(
            legal_classification=classification,
            maximum_allowed_duration_days=operational_limit,
            compliance_status=compliance,
            applicable_statutes=statutes,
            risk_level=jinfo.risk_level,
            message=message,
            legal_threshold_days=legal,
            platform_renewal_cycle_days=operational_limit,
            jurisdiction_group=jinfo.jurisdiction_group,
        )

    # Fallback: legacy region_rules
    rule = db.query(RegionRule).filter(RegionRule.region_code == rc).first()
    if not rule:
        return None

    max_days = rule.max_stay_days
    classification = rule.stay_classification_label
    risk = rule.risk_level
    statutes = [rule.statute_reference] if rule.statute_reference else []

    if rule.allow_extended_if_owner_occupied and inp.owner_occupied:
        max_days = 90
        classification = StayClassification.lodger
        statutes.append("CA Civil Code § 1946.5 (Single Lodger)")

    within = inp.stay_duration_days <= max_days
    compliance = "within_limit" if within else "exceeds_limit"
    message = None
    if not within:
        message = f"Stay of {inp.stay_duration_days} days exceeds maximum allowed {max_days} days for this region."

    return JLEResult(
        legal_classification=classification,
        maximum_allowed_duration_days=max_days,
        compliance_status=compliance,
        applicable_statutes=statutes,
        risk_level=risk,
        message=message,
    )


def get_max_stay_days_for_property(db: Session, region_code: str | None, owner_occupied: bool) -> int | None:
    """Return maximum allowed stay duration (days) for this property's jurisdiction, or None if no rule."""
    if not region_code or not str(region_code).strip():
        return None
    inp = JLEInput(
        region_code=region_code.strip().upper(),
        stay_duration_days=0,
        owner_occupied=bool(owner_occupied),
    )
    result = resolve_jurisdiction(db, inp)
    return result.maximum_allowed_duration_days if result else None


def validate_stay_duration_for_property(
    db: Session,
    region_code: str,
    owner_occupied: bool,
    start_date: date,
    end_date: date,
) -> str | None:
    """Validate that stay duration is within legal limit for the property's jurisdiction.
    Returns an error message if the stay exceeds the limit, or None if valid."""
    duration_days = (end_date - start_date).days
    if duration_days <= 0:
        return "End date must be after start date."
    rc = (region_code or "").strip().upper() or None
    if not rc:
        return None  # no region rule, no restriction
    inp = JLEInput(
        region_code=rc,
        stay_duration_days=duration_days,
        owner_occupied=bool(owner_occupied),
    )
    result = resolve_jurisdiction(db, inp)
    if result is None:
        return None  # no rule for region, allow
    if result.compliance_status == "exceeds_limit":
        return result.message or f"Stay of {duration_days} days exceeds maximum allowed {result.maximum_allowed_duration_days} days for this jurisdiction."
    return None
