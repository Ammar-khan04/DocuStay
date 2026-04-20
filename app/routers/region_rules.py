"""Module D: Region rules (read-only, pre-seeded)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.region_rule import RegionRule
from app.schemas.region_rule import RegionRuleResponse
from app.dependencies import get_current_user

router = APIRouter(prefix="/region-rules", tags=["region-rules"])


@router.get("/", response_model=list[RegionRuleResponse])
def list_region_rules(
    region_code: str | None = Query(None, description="Filter by NYC, FL, CA, TX"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = db.query(RegionRule)
    if region_code:
        q = q.filter(RegionRule.region_code == region_code.upper())
    return [RegionRuleResponse.model_validate(r) for r in q.all()]


@router.get("/{region_code}", response_model=RegionRuleResponse)
def get_region_rule(
    region_code: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rule = db.query(RegionRule).filter(RegionRule.region_code == region_code.upper()).first()
    if not rule:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Region rule not found")
    return RegionRuleResponse.model_validate(rule)
