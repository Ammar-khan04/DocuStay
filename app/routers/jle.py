"""Module E: Mini Jurisdiction Logic Resolver."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.jle import JLEInput, JLEResult
from app.services.jle import resolve_jurisdiction
from app.dependencies import get_current_user

router = APIRouter(prefix="/jle", tags=["jle"])


@router.post("/resolve", response_model=JLEResult)
def resolve(
    inp: JLEInput,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = resolve_jurisdiction(db, inp)
    if not result:
        raise HTTPException(status_code=404, detail=f"No region rule for {inp.region_code}")
    return result
