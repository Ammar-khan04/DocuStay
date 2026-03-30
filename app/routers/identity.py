"""Stripe Identity verification for owner/manager onboarding."""
from datetime import datetime, timezone
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserRole
from app.dependencies import get_current_user, require_owner_or_manager
from app.config import get_settings

router = APIRouter(prefix="/auth/identity", tags=["identity"])


class VerificationSessionRequest(BaseModel):
    """Optional return_url so frontend can use owner vs manager landing paths (e.g. .../identity-complete vs .../identity-complete/manager)."""
    return_url: str | None = None


class VerificationSessionResponse(BaseModel):
    client_secret: str
    url: str | None = None


class IdentityConfirmRequest(BaseModel):
    verification_session_id: str


class LatestIdentitySessionResponse(BaseModel):
    verification_session_id: str


def _stripe_configured() -> bool:
    s = get_settings()
    return bool(s.stripe_secret_key and s.stripe_identity_return_url)


@router.post("/verification-session", response_model=VerificationSessionResponse)
def create_verification_session(
    data: VerificationSessionRequest | None = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
):
    """Create a Stripe Identity VerificationSession for owner or property manager. Optional return_url from frontend (e.g. .../identity-complete/manager for manager)."""
    if not _stripe_configured():
        raise HTTPException(
            status_code=503,
            detail="Identity verification is not configured. Set STRIPE_SECRET_KEY and STRIPE_IDENTITY_RETURN_URL in .env.",
        )
    if current_user.identity_verified_at:
        raise HTTPException(status_code=400, detail="Identity is already verified.")

    import stripe
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key

    return_url = (settings.stripe_identity_return_url or "").strip()
    if data and data.return_url:
        candidate = (data.return_url or "").strip()
        if candidate.startswith("http://") or candidate.startswith("https://"):
            return_url = candidate
    if not return_url:
        raise HTTPException(status_code=503, detail="STRIPE_IDENTITY_RETURN_URL is not set.")

    try:
        flow_id = (
            (settings.stripe_identity_flow_id_manager or "").strip()
            if current_user.role == UserRole.property_manager
            else (settings.stripe_identity_flow_id or "").strip()
        )
        if flow_id:
            create_params = {
                "verification_flow": flow_id,
                "return_url": return_url,
                "metadata": {"user_id": str(current_user.id)},
            }
        else:
            create_params = {
                "type": "document",
                "return_url": return_url,
                "metadata": {"user_id": str(current_user.id)},
                "options": {
                    "document": {
                        "allowed_types": ["driving_license", "passport", "id_card"],
                        "require_matching_selfie": True,
                    },
                },
            }
        session = stripe.identity.VerificationSession.create(
            **create_params,
            idempotency_key=f"identity_user_{current_user.id}",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Stripe error: {getattr(e, 'message', str(e))}")

    url = getattr(session, "url", None) or (session.get("url") if hasattr(session, "get") and callable(session.get) else None)
    if not url:
        raise HTTPException(status_code=502, detail="Stripe did not return a verification URL. Check Stripe Identity and return_url configuration.")
    # Store session id so when Stripe redirects back without session_id in URL we can still confirm (manager/owner flow).
    session_id = getattr(session, "id", None) or (session.get("id") if hasattr(session, "get") and callable(session.get) else None)
    if session_id:
        current_user.stripe_verification_session_id = session_id
        db.commit()
    return VerificationSessionResponse(client_secret=session.client_secret, url=url)


@router.get("/latest-session", response_model=LatestIdentitySessionResponse)
def get_latest_identity_session(
    current_user: User = Depends(require_owner_or_manager),
):
    """Return the verification_session_id we stored when creating the session. Use when Stripe redirects without session_id in URL (e.g. manager/owner flow)."""
    sid = (current_user.stripe_verification_session_id or "").strip()
    if not sid:
        raise HTTPException(
            status_code=404,
            detail="No verification session found. Please start identity verification again.",
        )
    return LatestIdentitySessionResponse(verification_session_id=sid)


@router.post("/confirm")
def confirm_identity(
    data: IdentityConfirmRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
):
    """Confirm identity after Stripe redirect. Verifies the session with Stripe and marks the user as identity-verified (for owner or property manager)."""
    if not _stripe_configured():
        raise HTTPException(status_code=503, detail="Identity verification is not configured.")
    if current_user.identity_verified_at:
        return {"status": "ok", "message": "Identity already verified."}

    import stripe
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key

    session_id = (data.verification_session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="verification_session_id is required.")

    try:
        session = stripe.identity.VerificationSession.retrieve(session_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid verification session: {getattr(e, 'message', str(e))}")

    if session.metadata.get("user_id") != str(current_user.id):
        raise HTTPException(status_code=403, detail="This verification session does not belong to your account.")

    if session.status != "verified":
        raise HTTPException(
            status_code=400,
            detail=f"Verification not completed. Status: {session.status}. Please complete the verification flow.",
        )

    current_user.identity_verified_at = datetime.now(timezone.utc)
    current_user.stripe_verification_session_id = session_id
    db.commit()
    db.refresh(current_user)

    return {"status": "ok", "message": "Identity verified successfully."}
