"""Module D: Region rules schemas."""
from pydantic import BaseModel
from app.models.region_rule import StayClassification, RiskLevel


class RegionRuleResponse(BaseModel):
    id: int
    region_code: str
    max_stay_days: int
    stay_classification_label: StayClassification
    risk_level: RiskLevel
    statute_reference: str | None
    plain_english_explanation: str | None
    allow_extended_if_owner_occupied: bool

    class Config:
        from_attributes = True
