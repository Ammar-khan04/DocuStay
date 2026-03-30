"""Module C: Stay creation and storage."""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.models.owner import Property
from app.models.stay import Stay
from app.models.guest import GuestProfile
from app.schemas.stay import StayCreate, StayResponse
from app.dependencies import get_current_user
from app.services.jle import resolve_jurisdiction
from app.services.audit_log import create_log, CATEGORY_STATUS_CHANGE
from app.services.event_ledger import create_ledger_event, ACTION_STAY_CREATED
from app.schemas.jle import JLEInput

router = APIRouter(prefix="/stays", tags=["stays"])


def _duration_days(start: date, end: date) -> int:
    return (end - start).days if end >= start else 0


@router.post("/", response_model=StayResponse)
def create_stay(
    request: Request,
    data: StayCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Resolve property and owner
    prop = db.query(Property).filter(Property.id == data.property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    owner_id = prop.owner_profile.user_id

    duration = _duration_days(data.stay_start_date, data.stay_end_date)
    if duration <= 0:
        raise HTTPException(status_code=400, detail="End date must be after start date")

    # JLE check: guest is current_user for demo (owner creates stay on behalf or guest creates)
    # Demo: allow owner to create stay for a guest; we need guest_id. For simplicity, owner creates stay and we use current_user as guest if role=guest, else we need guest_id in body.
    # Spec: Stay has guest_id, owner_id, property_id. So creation: typically guest submits, or owner invites (then guest_id would be set when guest accepts). For demo we let current_user be the guest when role=guest, or owner can pass guest_id when we add it.
    if current_user.role.value == "owner":
        guest_id = data.guest_id
        if not guest_id:
            raise HTTPException(status_code=400, detail="Owner must provide guest_id when creating a stay (invite).")
    else:
        guest_id = current_user.id

    jle_inp = JLEInput(
        region_code=data.region_code,
        stay_duration_days=duration,
        owner_occupied=prop.owner_occupied,
        property_type=prop.property_type.value if prop.property_type else None,
        guest_has_permanent_address=True,
    )
    result = resolve_jurisdiction(db, jle_inp)
    if result and result.compliance_status == "exceeds_limit":
        raise HTTPException(status_code=400, detail=result.message or "Stay duration exceeds legal limit for this region.")

    stay = Stay(
        guest_id=guest_id,
        owner_id=owner_id,
        property_id=prop.id,
        stay_start_date=data.stay_start_date,
        stay_end_date=data.stay_end_date,
        intended_stay_duration_days=duration,
        purpose_of_stay=data.purpose_of_stay,
        relationship_to_owner=data.relationship_to_owner,
        region_code=data.region_code.upper(),
    )
    db.add(stay)
    db.commit()
    db.refresh(stay)
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Stay created",
        f"Stay {stay.id} created for property {stay.property_id}, guest {stay.guest_id}, {stay.stay_start_date}–{stay.stay_end_date}.",
        property_id=stay.property_id,
        stay_id=stay.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"guest_id": stay.guest_id, "owner_id": stay.owner_id},
    )
    create_ledger_event(
        db,
        ACTION_STAY_CREATED,
        target_object_type="Stay",
        target_object_id=stay.id,
        property_id=stay.property_id,
        stay_id=stay.id,
        actor_user_id=current_user.id,
        meta={"guest_id": stay.guest_id, "owner_id": stay.owner_id, "stay_start_date": str(stay.stay_start_date), "stay_end_date": str(stay.stay_end_date)},
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()
    return StayResponse.model_validate(stay)


@router.get("/", response_model=list[StayResponse])
def list_stays(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    as_guest: bool = Query(True, description="True=stays where I am guest, False=stays where I am owner"),
):
    if as_guest:
        stays = db.query(Stay).filter(Stay.guest_id == current_user.id).all()
    else:
        stays = db.query(Stay).filter(Stay.owner_id == current_user.id).all()
    return [StayResponse.model_validate(s) for s in stays]


@router.get("/{stay_id}", response_model=StayResponse)
def get_stay(
  stay_id: int,
  db: Session = Depends(get_db),
  current_user: User = Depends(get_current_user),
):
    stay = db.query(Stay).filter(Stay.id == stay_id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    if stay.guest_id != current_user.id and stay.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your stay")
    return StayResponse.model_validate(stay)
