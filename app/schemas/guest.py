"""Module B2: Guest onboarding schemas."""
from pydantic import BaseModel
from app.models.guest import PurposeOfStay, RelationshipToOwner


class GuestProfileCreate(BaseModel):
    full_legal_name: str
    permanent_home_address: str
    gps_checkin_acknowledgment: bool = False


class GuestProfileResponse(BaseModel):
    id: int
    full_legal_name: str
    permanent_home_address: str
    gps_checkin_acknowledgment: bool

    class Config:
        from_attributes = True
