"""Module E: Mini Jurisdiction Logic Resolver schemas."""
from pydantic import BaseModel
from app.models.region_rule import StayClassification, RiskLevel


class JLEInput(BaseModel):
    region_code: str
    stay_duration_days: int
    owner_occupied: bool
    property_type: str | None = None  # entire_home | private_room
    guest_has_permanent_address: bool = True  # presence only


class JLEResult(BaseModel):
    legal_classification: StayClassification
    maximum_allowed_duration_days: int
    compliance_status: str  # "within_limit" | "exceeds_limit"
    applicable_statutes: list[str]
    risk_level: RiskLevel
    message: str | None = None
    legal_threshold_days: int | None = None
    platform_renewal_cycle_days: int | None = None
    jurisdiction_group: str | None = None
