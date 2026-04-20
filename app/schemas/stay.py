"""Module C: Stay schemas."""
from datetime import date
from pydantic import BaseModel
from app.models.guest import PurposeOfStay, RelationshipToOwner


class StayCreate(BaseModel):
    property_id: int
    guest_id: int | None = None  # Required when owner creates stay (invite)
    stay_start_date: date
    stay_end_date: date
    purpose_of_stay: PurposeOfStay
    relationship_to_owner: RelationshipToOwner
    region_code: str


class StayResponse(BaseModel):
    id: int
    guest_id: int
    owner_id: int
    property_id: int
    stay_start_date: date
    stay_end_date: date
    intended_stay_duration_days: int
    purpose_of_stay: PurposeOfStay
    relationship_to_owner: RelationshipToOwner
    region_code: str

    class Config:
        from_attributes = True
