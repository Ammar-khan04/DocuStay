"""Module B2: Guest onboarding."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.models.guest import GuestProfile
from app.schemas.guest import GuestProfileCreate, GuestProfileResponse
from app.dependencies import get_current_user, require_guest

router = APIRouter(prefix="/guests", tags=["guests"])


@router.get("/profile", response_model=GuestProfileResponse | None)
def get_my_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest),
):
    profile = db.query(GuestProfile).filter(GuestProfile.user_id == current_user.id).first()
    return GuestProfileResponse.model_validate(profile) if profile else None


@router.put("/profile", response_model=GuestProfileResponse)
def create_or_update_profile(
    data: GuestProfileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest),
):
    profile = db.query(GuestProfile).filter(GuestProfile.user_id == current_user.id).first()
    if profile:
        profile.full_legal_name = data.full_legal_name
        profile.permanent_home_address = data.permanent_home_address
        profile.gps_checkin_acknowledgment = data.gps_checkin_acknowledgment
    else:
        profile = GuestProfile(
            user_id=current_user.id,
            full_legal_name=data.full_legal_name,
            permanent_home_address=data.permanent_home_address,
            gps_checkin_acknowledgment=data.gps_checkin_acknowledgment,
        )
        db.add(profile)
    db.commit()
    db.refresh(profile)
    return GuestProfileResponse.model_validate(profile)
