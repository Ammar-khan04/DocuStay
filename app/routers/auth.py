"""Module A: Authentication & role selection."""
import logging
import random
import secrets
import string
from datetime import date, datetime, timezone, timedelta
from urllib.parse import unquote
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_

from app.database import get_db
from app.models.user import User, UserRole
from app.models.invitation import Invitation
from app.models.stay import Stay
from app.models.agreement_signature import AgreementSignature
from app.models.guest_pending_invite import GuestPendingInvite
from app.models.owner import OwnerProfile, Property, OccupancyStatus
from app.models.owner_poa_signature import OwnerPOASignature
from app.models.pending_registration import PendingRegistration
from app.services.audit_log import create_log, CATEGORY_STATUS_CHANGE, CATEGORY_GUEST_SIGNATURE, CATEGORY_FAILED_ATTEMPT
from app.services.invitation_guest_completion import (
    guest_invite_awaiting_account_after_sign,
    guest_invitation_signing_started,
)
from app.services.event_ledger import (
    create_ledger_event,
    ACTION_LOGIN_FAILED,
    ACTION_USER_LOGGED_IN,
    ACTION_GUEST_INVITE_ACCEPTED,
    ACTION_AGREEMENT_SIGN_FAILED,
    ACTION_VERIFY_ATTEMPT_FAILED,
    ACTION_EMAIL_VERIFICATION_FAILED,
    ACTION_ACCEPT_INVITE_FAILED,
    ACTION_MANAGER_INVITE_ACCEPTED,
    ACTION_MANAGER_ASSIGNED,
    ACTION_TENANT_ACCEPTED,
    ACTION_TENANT_LEASE_EXTENSION_ACCEPTED,
    ACTION_SHIELD_MODE_OFF,
)
from app.services.billing import sync_subscription_quantities
from app.services.agreements import (
    agreement_content_to_pdf,
    build_invitation_agreement,
    fill_guest_signature_in_content,
)
from app.services.registration_email import (
    normalize_registration_email,
    enforce_email_available_for_intended_role,
    enforce_no_conflicting_user_before_pending_completion,
    same_role_already_registered_message,
    _role_labels,
)
from app.schemas.auth import (
    UserCreate,
    UserLogin,
    Token,
    UserResponse,
    GuestRegister,
    ManagerRegister,
    AcceptInvite,
    VerifyEmailRequest,
    ResendVerificationRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    RegisterPendingResponse,
    LinkPOARequest,
    PendingOwnerIdentitySessionRequest,
    PendingOwnerIdentitySessionResponse,
    PendingOwnerConfirmIdentityRequest,
    PendingOwnerMeResponse,
    PendingOwnerLatestIdentitySessionResponse,
    PendingOwnerIdentityRetryRequest,
    PendingOwnerIdentityRetryResponse,
    CompleteOwnerSignupRequest,
    DemoLoginRequest,
)
from app.services.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    create_pending_owner_token,
    create_password_reset_token,
    decode_token_with_error,
)
from app.services.dropbox_sign import get_signed_pdf
from app.services.invitation_agreement_ledger import emit_invitation_agreement_signed_if_dropbox_complete
from app.services.notifications import (
    send_verification_email,
    send_password_reset_email,
    send_owner_welcome_email,
    send_guest_welcome_email,
    send_guest_signup_welcome_email,
    send_guest_stay_added_email,
    send_manager_welcome_email,
    send_tenant_guest_accepted_invite,
    send_shield_mode_turned_off_notification,
)
from app.services.dashboard_alerts import create_alert_for_owner_and_managers, create_alert_for_user
from app.dependencies import get_current_user, require_owner, require_guest, require_guest_or_tenant, get_pending_owner
from app.models.guest import GuestProfile
from app.models.manager_invitation import ManagerInvitation
from app.models.property_transfer_invitation import PropertyTransferInvitation
from app.models.tenant_assignment import TenantAssignment
from app.models.property_manager_assignment import PropertyManagerAssignment
from app.services.invitation_kinds import (
    TENANT_UNIT_LEASE_KINDS,
    is_property_invited_tenant_signup_kind,
    is_tenant_lease_extension_kind,
)
from app.services.tenant_lease_window import (
    assert_can_record_tenant_assignment_for_invite_or_raise,
    assert_tenant_lease_extension_no_other_occupant_conflict,
    find_tenant_assignment_matching_invitation,
    find_tenant_assignment_for_lease_extension_accept,
    list_invitations_matching_tenant_assignment_lease,
)
from app.config import get_settings
from app.services.shield_mode_policy import SHIELD_MODE_ALWAYS_ON


def _user_to_response(user: User, db: Session) -> UserResponse:
    """Build UserResponse with identity_verified and poa_linked."""
    identity_verified = bool(getattr(user, "identity_verified_at", None))
    poa_linked = False
    if user.role == UserRole.owner:
        has_poa = db.query(OwnerPOASignature).filter(OwnerPOASignature.used_by_user_id == user.id).first() is not None
        poa_waived = bool(getattr(user, "poa_waived_at", None))
        poa_linked = has_poa or poa_waived
    from app.models.demo_account import DemoAccount
    is_demo = db.query(DemoAccount).filter(DemoAccount.user_id == user.id).first() is not None
    return UserResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        full_name=user.full_name,
        phone=user.phone,
        state=user.state,
        city=user.city,
        identity_verified=identity_verified,
        poa_linked=poa_linked,
        is_demo=is_demo,
    )

router = APIRouter(prefix="/auth", tags=["auth"])

VERIFICATION_CODE_EXPIRE_MINUTES = 10

logger = logging.getLogger(__name__)


@router.post("/demo/login", response_model=Token)
def demo_login(request: Request, data: DemoLoginRequest, db: Session = Depends(get_db)):
    """Demo-only login: bypasses credentials and verification entirely.

    This endpoint is isolated under /auth/demo/* and is only reachable from the demo UI entrypoint.
    Normal /auth/login and /auth/register behavior is unchanged.
    """
    now = datetime.now(timezone.utc)
    role = data.role

    # Demo can use a user-supplied email (saved as entered), otherwise a stable default per role.
    email = ((data.email or "").strip().lower() or f"demo+{role.value}@docustay.demo").lower()
    user = db.query(User).filter(func.lower(func.trim(User.email)) == email, User.role == role).first()
    if user:
        from app.models.demo_account import DemoAccount
        if db.query(DemoAccount).filter(DemoAccount.user_id == user.id).first() is None:
            raise HTTPException(
                status_code=400,
                detail="That email is already registered for this role. Please use a different email for demo mode.",
            )
    else:
        raw_pw = f"demo-{role.value}-{secrets.token_urlsafe(12)}"
        user = User(
            email=email,
            hashed_password=get_password_hash(raw_pw),
            role=role,
            full_name=f"Demo {role.value.replace('_', ' ').title()}",
            email_verified=True,
            email_verification_code=None,
            email_verification_expires_at=None,
        )
        # Ensure demo can access role-gated dashboards.
        if role in (UserRole.owner, UserRole.property_manager):
            user.identity_verified_at = now
        if role == UserRole.owner:
            user.poa_waived_at = now
        db.add(user)
        db.commit()
        db.refresh(user)

    from app.models.demo_account import DemoAccount
    if db.query(DemoAccount).filter(DemoAccount.user_id == user.id).first() is None:
        db.add(DemoAccount(user_id=user.id))
        db.commit()

    # Minimal demo data so dashboards have something real to load.
    try:
        from app.models.owner import OwnerProfile, Property, OccupancyStatus
        from app.models.unit import Unit
        from app.models.property_manager_assignment import PropertyManagerAssignment
        from app.models.tenant_assignment import TenantAssignment

        owner_email = "demo+owner@docustay.demo"
        demo_owner = db.query(User).filter(func.lower(func.trim(User.email)) == owner_email, User.role == UserRole.owner).first()
        if not demo_owner:
            demo_owner = User(
                email=owner_email,
                hashed_password=get_password_hash(f"demo-owner-{secrets.token_urlsafe(12)}"),
                role=UserRole.owner,
                full_name="Demo Owner",
                email_verified=True,
                identity_verified_at=now,
                poa_waived_at=now,
            )
            db.add(demo_owner)
            db.commit()
            db.refresh(demo_owner)
            if db.query(DemoAccount).filter(DemoAccount.user_id == demo_owner.id).first() is None:
                db.add(DemoAccount(user_id=demo_owner.id))
                db.commit()

        profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == demo_owner.id).first()
        if not profile:
            profile = OwnerProfile(user_id=demo_owner.id)
            db.add(profile)
            db.commit()
            db.refresh(profile)

        prop = db.query(Property).filter(Property.owner_profile_id == profile.id, Property.deleted_at.is_(None)).first()
        if not prop:
            prop = Property(
                owner_profile_id=profile.id,
                name="Demo Property",
                street="123 Demo St",
                city="Demo City",
                state="TX",
                zip_code="78701",
                region_code="TX",
                owner_occupied=False,
                occupancy_status=OccupancyStatus.occupied.value,
                live_slug=secrets.token_hex(12),
                shield_mode_enabled=1,
            )
            db.add(prop)
            db.flush()
            db.commit()
            db.refresh(prop)

        unit = db.query(Unit).filter(Unit.property_id == prop.id).first()
        if not unit:
            unit = Unit(property_id=prop.id, unit_label="1", occupancy_status=OccupancyStatus.occupied.value, is_primary_residence=0)
            db.add(unit)
            db.commit()
            db.refresh(unit)

        if role == UserRole.property_manager:
            if not db.query(PropertyManagerAssignment).filter(
                PropertyManagerAssignment.user_id == user.id,
                PropertyManagerAssignment.property_id == prop.id,
            ).first():
                db.add(PropertyManagerAssignment(user_id=user.id, property_id=prop.id, assigned_by_user_id=demo_owner.id))
                db.commit()
        if role == UserRole.tenant:
            if not db.query(TenantAssignment).filter(
                TenantAssignment.user_id == user.id,
                TenantAssignment.unit_id == unit.id,
            ).first():
                db.add(TenantAssignment(user_id=user.id, unit_id=unit.id, invited_by_user_id=demo_owner.id, start_date=date.today(), end_date=None))
                db.commit()

        # Demo convenience: if a demo property manager logs in with an email that has pending manager invitations,
        # auto-accept them all so the manager can immediately see assigned properties.
        if role == UserRole.property_manager and user.email:
            pending_manager_invites = (
                db.query(ManagerInvitation)
                .filter(
                    func.lower(func.trim(ManagerInvitation.email)) == user.email.strip().lower(),
                    ManagerInvitation.status == "pending",
                    ManagerInvitation.expires_at > now,
                )
                .all()
            )
            for mi in pending_manager_invites:
                existing_assignment = db.query(PropertyManagerAssignment).filter(
                    PropertyManagerAssignment.property_id == mi.property_id,
                    PropertyManagerAssignment.user_id == user.id,
                ).first()
                if not existing_assignment:
                    db.add(
                        PropertyManagerAssignment(
                            property_id=mi.property_id,
                            user_id=user.id,
                            assigned_by_user_id=mi.invited_by_user_id,
                        )
                    )
                mi.status = "accepted"
                mi.accepted_at = now
                try:
                    create_ledger_event(
                        db,
                        ACTION_MANAGER_INVITE_ACCEPTED,
                        target_object_type="ManagerInvitation",
                        target_object_id=mi.id,
                        property_id=mi.property_id,
                        actor_user_id=user.id,
                        meta={"email": user.email, "property_id": mi.property_id, "demo_auto_accept": True},
                    )
                    create_ledger_event(
                        db,
                        ACTION_MANAGER_ASSIGNED,
                        target_object_type="PropertyManagerAssignment",
                        target_object_id=(existing_assignment.id if existing_assignment else None),
                        property_id=mi.property_id,
                        actor_user_id=mi.invited_by_user_id,
                        meta={"manager_email": user.email, "manager_user_id": user.id, "property_id": mi.property_id, "demo_auto_accept": True},
                    )
                except Exception:
                    pass
            db.commit()
    except Exception:
        pass

    cal = _effective_client_calendar_date_for_auth(request, data.client_calendar_date)
    _trigger_guest_approaching_end_notifications_after_auth(db, user, request, client_calendar_date=cal)
    token = create_access_token(user.id, user.email, user.role)
    return Token(access_token=token, user=_user_to_response(user, db))


def _client_calendar_date_from_request(request: Request) -> date | None:
    """Parse guest app local calendar day from ``X-Client-Calendar-Date: YYYY-MM-DD`` (date only, no time)."""
    raw = (request.headers.get("X-Client-Calendar-Date") or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _effective_client_calendar_date_for_auth(
    request: Request | None,
    body_ymd: str | None = None,
) -> date | None:
    """Prefer JSON ``client_calendar_date`` (YYYY-MM-DD), then ``X-Client-Calendar-Date`` header."""
    raw = (body_ymd or "").strip()
    if raw:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            pass
    if request is not None:
        return _client_calendar_date_from_request(request)
    return None


def _trigger_guest_approaching_end_notifications_after_auth(
    db: Session,
    user: User,
    request: Request | None = None,
    *,
    client_calendar_date: date | None = None,
) -> None:
    """After guest, tenant, owner, or property manager obtains a session, materialize notifications (idempotent; does not block auth on failure).

    For owners and property managers, runs Status Confirmation for their properties only, using the client's
    calendar day when provided so e.g. ``stay_end_date == today + 2 days`` (lease ends in two calendar days) can
    generate the 48h-before in-app alert and email on sign-in, not only when the server cron runs.
    """
    cal = client_calendar_date
    if cal is None and request is not None:
        cal = _client_calendar_date_from_request(request)
    if user.role == UserRole.guest:
        try:
            from app.services.stay_timer import run_guest_stay_approaching_end_notifications_on_login

            run_guest_stay_approaching_end_notifications_on_login(db, user.id, client_calendar_date=cal)
        except Exception:
            logger.exception(
                "Guest approaching-end notification after auth failed (non-fatal); user_id=%s",
                user.id,
            )
    if user.role == UserRole.tenant:
        try:
            from app.services.stay_timer import run_tenant_invited_guest_jurisdiction_threshold_notifications

            run_tenant_invited_guest_jurisdiction_threshold_notifications(
                db, only_tenant_user_id=user.id, client_calendar_date=cal
            )
        except Exception:
            logger.exception(
                "Tenant jurisdiction-threshold notification after auth failed (non-fatal); user_id=%s",
                user.id,
            )
    if user.role in (UserRole.owner, UserRole.property_manager):
        try:
            from app.services.stay_timer import run_status_confirmation_materialize_for_user

            run_status_confirmation_materialize_for_user(db, user, client_calendar_date=cal)
        except Exception:
            logger.exception(
                "Status Confirmation materialization after auth failed (non-fatal); user_id=%s",
                user.id,
            )


def _mailgun_configured() -> bool:
    s = get_settings()
    return bool(s.mailgun_api_key and s.mailgun_domain)


def _generate_verification_code() -> str:
    return "".join(random.choices(string.digits, k=6))


def _register_email_taken_message(existing_role: UserRole) -> str:
    """Same email + same role already exists (finish onboarding or log in)."""
    return same_role_already_registered_message(existing_role)


def _validate_and_claim_owner_poa(
    db: Session,
    poa_signature_id: int,
    owner_email: str,
    *,
    dropbox_incomplete_message: str = "Please complete signing in Dropbox before continuing. Then try again.",
) -> None:
    """Validate POA signature exists, email matches, not already used, and (when sent to Dropbox) completed in Dropbox. Raises HTTPException on failure."""
    sig = db.query(OwnerPOASignature).filter(OwnerPOASignature.id == poa_signature_id).first()
    if not sig:
        raise HTTPException(status_code=400, detail="Invalid Master POA signature. Please sign the document again.")
    if sig.owner_email.strip().lower() != (owner_email or "").strip().lower():
        raise HTTPException(status_code=400, detail="Master POA signature email does not match registration email.")
    if sig.used_by_user_id is not None:
        raise HTTPException(status_code=400, detail="This Master POA signature was already used for another account.")
    if getattr(sig, "dropbox_sign_request_id", None) and not getattr(sig, "signed_pdf_bytes", None):
        pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
        if pdf_bytes:
            sig.signed_pdf_bytes = pdf_bytes
            db.commit()
        else:
            raise HTTPException(status_code=400, detail=dropbox_incomplete_message)


def _owner_onboarding_complete(db: Session, user: User) -> bool:
    """True if owner has completed identity verification and linked Master POA."""
    if user.role != UserRole.owner:
        return True
    if not getattr(user, "identity_verified_at", None):
        return False
    poa = db.query(OwnerPOASignature).filter(OwnerPOASignature.used_by_user_id == user.id).first()
    return poa is not None


@router.post("/register")
def register(data: UserCreate, db: Session = Depends(get_db)):
    # Normalize email so "already registered" and storage are case-insensitive.
    email = normalize_registration_email(str(data.email) if data.email else "")
    if not email:
        raise HTTPException(status_code=400, detail="Email is required.")
    enforce_email_available_for_intended_role(db, email, data.role, allow_same_role_pending=True)
    existing_same_role = (
        db.query(User)
        .filter(func.lower(func.trim(User.email)) == email, User.role == data.role)
        .first()
    )
    if existing_same_role:
        # Owner who hasn't finished onboarding can "continue" by submitting the form with correct password
        if existing_same_role.role == UserRole.owner and not _owner_onboarding_complete(db, existing_same_role):
            if not verify_password(data.password, existing_same_role.hashed_password):
                raise HTTPException(
                    status_code=400,
                    detail="An account with this email exists but onboarding wasn't completed. Please log in with your password on the Owner Login page to continue.",
                )
            print(f"[Auth] Existing owner (incomplete onboarding): returning token for {email} — no verification email sent.", flush=True)
            token = create_access_token(existing_same_role.id, existing_same_role.email, existing_same_role.role)
            return Token(access_token=token, user=_user_to_response(existing_same_role, db))
        raise HTTPException(
            status_code=400,
            detail=_register_email_taken_message(existing_same_role.role),
        )

    # Owner: POA is linked after identity verification (separate step); do not require or claim here
    if data.role == UserRole.owner and data.poa_signature_id:
        _validate_and_claim_owner_poa(
            db, data.poa_signature_id, email,
            dropbox_incomplete_message="Please complete signing in Dropbox before completing signup.",
        )

    # Owner signup always requires email verification via Mailgun (no bypass).
    if data.role == UserRole.owner:
        # Remove any existing pending owner for this email so they can start fresh (e.g. abandoned email verify or Stripe failed).
        existing_pending = db.query(PendingRegistration).filter(
            PendingRegistration.email == email,
            PendingRegistration.role == UserRole.owner,
        ).all()
        for p in existing_pending:
            db.delete(p)
        if existing_pending:
            db.commit()
            print(f"[Auth] Removed {len(existing_pending)} existing pending owner(s) for {email} so signup can start fresh", flush=True)

        # Reload config so UI flow uses same .env as script (avoid stale cache)
        from app.services.notifications import _get_fresh_settings
        _get_fresh_settings()
        if not _mailgun_configured():
            raise HTTPException(
                status_code=503,
                detail="Email verification is required for owner signup. Please configure MAILGUN_API_KEY and MAILGUN_DOMAIN in .env and restart the server.",
            )
        code = _generate_verification_code()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_CODE_EXPIRE_MINUTES)
        account_type_val = data.account_type.value if data.account_type else "individual"
        extra = {
            "owner_type": (data.owner_type.value if data.owner_type else None),
            "account_type": account_type_val,
            "first_name": data.first_name or None,
            "last_name": data.last_name or None,
        }
        pending = PendingRegistration(
            email=email,
            hashed_password=get_password_hash(data.password),
            role=UserRole.owner,
            full_name=data.full_name or None,
            phone=data.phone or None,
            state=data.state or None,
            city=data.city or None,
            country=data.country or None,
            verification_code=code,
            expires_at=expires_at,
            extra_data=extra,
        )
        db.add(pending)
        db.commit()
        db.refresh(pending)
        _log_mailgun_status = _mailgun_configured()
        print(f"[Auth] Owner signup: Mailgun configured={_log_mailgun_status} domain={get_settings().mailgun_domain or '(none)'}", flush=True)
        print(f"[Auth] Sending verification email to {email} (owner signup pending_id={pending.id})", flush=True)
        try:
            # send_verification_email clears config cache and calls send_email -> _send_email_mailgun
            sent = send_verification_email(email, code)
        except Exception as e:
            print(f"[Auth] Verification email exception: {type(e).__name__}: {e}", flush=True)
            db.delete(pending)
            db.commit()
            raise HTTPException(
                status_code=503,
                detail="We could not send the verification email. Please check MAILGUN_API_KEY, MAILGUN_DOMAIN, and MAILGUN_FROM_EMAIL in .env, then restart the server and try again.",
            ) from e
        print(f"[Auth] Verification email sent={sent} for {email}", flush=True)
        if not sent:
            db.delete(pending)
            db.commit()
            raise HTTPException(
                status_code=503,
                detail="We could not send the verification email. Please check MAILGUN_API_KEY, MAILGUN_DOMAIN, and MAILGUN_FROM_EMAIL in .env and restart the server, then try again.",
            )
        return RegisterPendingResponse(user_id=pending.id)

    bypass_verification = not _mailgun_configured()

    if bypass_verification and data.role != UserRole.owner:
        # Guest with no mailgun: create user immediately
        user = User(
            email=email,
            hashed_password=get_password_hash(data.password),
            role=data.role,
            full_name=data.full_name or None,
            phone=data.phone or None,
            state=data.state or None,
            city=data.city or None,
            country=data.country or None,
            email_verified=True,
            email_verification_code=None,
            email_verification_expires_at=None,
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError as e:
            db.rollback()
            msg = str(getattr(getattr(e, "orig", None), "args", [""])[0] if hasattr(e, "orig") and e.orig else str(e))
            if "email" in msg.lower() or "unique" in msg.lower():
                raise HTTPException(status_code=400, detail=_register_email_taken_message(data.role))
            raise
        db.refresh(user)
        _trigger_guest_approaching_end_notifications_after_auth(db, user, request)
        token = create_access_token(user.id, user.email, user.role)
        return Token(access_token=token, user=_user_to_response(user, db))

    # Guest (or other roles): store pending and send verification email, or create user immediately if Mailgun not configured.
    if not bypass_verification:
        # Store pending registration; user is created only after email verification.
        code = _generate_verification_code()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_CODE_EXPIRE_MINUTES)
        pending = PendingRegistration(
            email=email,
            hashed_password=get_password_hash(data.password),
            role=data.role,
            full_name=data.full_name or None,
            phone=data.phone or None,
            state=data.state or None,
            city=data.city or None,
            country=data.country or None,
            verification_code=code,
            expires_at=expires_at,
            extra_data=(
            {"poa_signature_id": data.poa_signature_id, "owner_type": (data.owner_type.value if data.owner_type else None)}
            if data.role == UserRole.owner else None
        ),
        )
        db.add(pending)
        db.commit()
        db.refresh(pending)
        sent = send_verification_email(email, code)
        if not sent:
            db.delete(pending)
            db.commit()
            print(f"Verification email not sent to {email}. Check MAILGUN_* settings (domain, from_email).", flush=True)
            raise HTTPException(
                status_code=503,
                detail="We could not send the verification email. Please check your email address and try again, or try again later. If the problem continues, check that Mailgun is configured with MAILGUN_DOMAIN and MAILGUN_FROM_EMAIL for your sending domain.",
            )
        return RegisterPendingResponse(user_id=pending.id)


def _normalized_login_role(role: UserRole | None) -> str | None:
    """Return lowercase role value for login branching."""
    if role is None:
        return None
    v = getattr(role, "value", None) or str(role)
    return (v or "").strip().lower() or None


def _log_login_failure(
    db: Session,
    request: Request,
    email: str,
    reason: str,
    user_id: int | None,
) -> None:
    """Log failed login (audit + ledger) and commit. Does not raise."""
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_FAILED_ATTEMPT,
        "Login failed",
        f"Failed login attempt for email: {email}.",
        actor_email=email,
        ip_address=ip,
        user_agent=ua,
        meta={"reason": reason},
    )
    create_ledger_event(
        db,
        ACTION_LOGIN_FAILED,
        meta={"email": email, "reason": reason},
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()


@router.post("/login", response_model=Token)
def login(request: Request, data: UserLogin, db: Session = Depends(get_db)):
    # Normalize email for case-insensitive lookup (trim + lower; DB side trimmed so stored spaces don't break match)
    email_normalized = (data.email or "").strip().lower()
    if not email_normalized:
        raise HTTPException(status_code=400, detail="Email is required")
    role_key = _normalized_login_role(data.role)
    # Compare against trimmed+lowered email in DB so leading/trailing spaces in stored email don't prevent match
    email_match = func.lower(func.trim(User.email)) == email_normalized
    if not role_key:
        user = db.query(User).filter(email_match).first()
    elif role_key == "guest":
        user = db.query(User).filter(email_match, User.role == UserRole.guest).first()
    elif role_key == "tenant":
        user = db.query(User).filter(email_match, User.role == UserRole.tenant).first()
    else:
        user = db.query(User).filter(
            email_match,
            User.role == data.role,
        ).first()
    if not user:
        # Wrong tab: password matches an account under another role. Or recover if primary query missed the row (edge cases).
        if role_key:
            candidates = db.query(User).filter(email_match).all()
            for u in candidates:
                if not verify_password(data.password, u.hashed_password):
                    continue
                if role_key == "guest":
                    if u.role != UserRole.guest:
                        ex_label, ex_page = _role_labels(u.role)
                        _log_login_failure(db, request, data.email, "wrong_login_portal_guest", u.id)
                        raise HTTPException(
                            status_code=401,
                            detail=(
                                f"This email is registered as a {ex_label}. "
                                f"Use the {ex_page} login page."
                            ),
                        )
                    user = u
                    break
                elif role_key == "tenant":
                    if u.role != UserRole.tenant:
                        ex_label, ex_page = _role_labels(u.role)
                        _log_login_failure(db, request, data.email, "wrong_login_portal_tenant", u.id)
                        raise HTTPException(
                            status_code=401,
                            detail=(
                                f"This email is registered as a {ex_label}. "
                                f"Use the {ex_page} login page."
                            ),
                        )
                    user = u
                    break
                elif _normalized_login_role(u.role) != role_key:
                    ex_label, ex_page = _role_labels(u.role)
                    _log_login_failure(db, request, data.email, "wrong_login_portal", u.id)
                    raise HTTPException(
                        status_code=401,
                        detail=(
                            f"This email is registered as a {ex_label}. "
                            f"Use the {ex_page} login page."
                        ),
                    )
                else:
                    user = u
                    break
        if not user:
            _log_login_failure(db, request, data.email, "user_not_found", None)
            raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(data.password, user.hashed_password):
        _log_login_failure(db, request, data.email, "password_mismatch", user.id)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.role == UserRole.owner and not getattr(user, "email_verified", True):
        raise HTTPException(
            status_code=401,
            detail="Please verify your email first. Check your inbox or use the verification page to resend the code.",
        )
    create_ledger_event(
        db,
        ACTION_USER_LOGGED_IN,
        target_object_type="User",
        target_object_id=user.id,
        actor_user_id=user.id,
        meta={"email": user.email, "role": user.role.value if hasattr(user.role, "value") else str(user.role)},
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "").strip() or None,
    )
    db.commit()
    cal = _effective_client_calendar_date_for_auth(request, data.client_calendar_date)
    _trigger_guest_approaching_end_notifications_after_auth(db, user, request, client_calendar_date=cal)
    token = create_access_token(user.id, user.email, user.role)
    return Token(access_token=token, user=_user_to_response(user, db))


def _normalize_manager_invite_token(token: str) -> str:
    """Strip and URL-decode token so link clicks from email clients match DB."""
    if not token or not isinstance(token, str):
        return ""
    return (unquote(token).strip() or "")


@router.get("/manager-invite/{token}")
def get_manager_invite(token: str, db: Session = Depends(get_db)):
    """Return manager invite details for pre-filling signup or login. Public endpoint.

    After the invite is accepted, the row is no longer ``pending``; we still return email/property so the app
    can show "already accepted — log in" instead of a false "expired" error when the user revisits the link.
    """
    norm_token = _normalize_manager_invite_token(token)
    if not norm_token:
        raise HTTPException(status_code=404, detail="Invitation not found or expired.")
    inv = db.query(ManagerInvitation).filter(ManagerInvitation.token == norm_token).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found or expired.")
    now = datetime.now(timezone.utc)
    if inv.status in ("cancelled", "expired"):
        raise HTTPException(status_code=404, detail="Invitation not found or expired.")
    if inv.status == "pending" and inv.expires_at <= now:
        raise HTTPException(status_code=404, detail="Invitation not found or expired.")
    if inv.status not in ("pending", "accepted"):
        raise HTTPException(status_code=404, detail="Invitation not found or expired.")
    already_accepted = inv.status == "accepted"
    prop = db.query(Property).filter(Property.id == inv.property_id).first()
    property_name = (prop.name or f"{prop.street or ''}, {prop.city or ''}".strip(", ")).strip() or "Property" if prop else "Property"
    from app.models.demo_account import is_demo_user_id
    email_out = (inv.email or "").strip().lower()
    return {
        "email": email_out,
        "property_name": property_name,
        "property_id": inv.property_id,
        "is_demo": is_demo_user_id(db, inv.invited_by_user_id),
        "already_accepted": already_accepted,
    }


@router.get("/property-transfer-invite/{token}")
def get_property_transfer_invite(token: str, db: Session = Depends(get_db)):
    """Public: transfer invite details for signup/login landing (same contract shape as manager invite where applicable)."""
    norm_token = _normalize_manager_invite_token(token)
    if not norm_token:
        raise HTTPException(status_code=404, detail="Invitation not found or expired.")
    inv = db.query(PropertyTransferInvitation).filter(PropertyTransferInvitation.token == norm_token).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found or expired.")
    now = datetime.now(timezone.utc)
    if inv.status in ("cancelled", "expired"):
        raise HTTPException(status_code=404, detail="Invitation not found or expired.")
    if inv.status == "pending" and inv.expires_at <= now:
        raise HTTPException(status_code=404, detail="Invitation not found or expired.")
    if inv.status not in ("pending", "accepted"):
        raise HTTPException(status_code=404, detail="Invitation not found or expired.")
    already_accepted = inv.status == "accepted"
    prop = db.query(Property).filter(Property.id == inv.property_id).first()
    property_name = (prop.name or f"{prop.street or ''}, {prop.city or ''}".strip(", ")).strip() or "Property" if prop else "Property"
    from app.models.demo_account import is_demo_user_id

    email_out = (inv.email or "").strip().lower()
    return {
        "email": email_out,
        "property_name": property_name,
        "property_id": inv.property_id,
        "is_demo": is_demo_user_id(db, inv.from_user_id),
        "already_accepted": already_accepted,
    }


@router.post("/register/manager", response_model=Token)
def register_manager(request: Request, data: ManagerRegister, db: Session = Depends(get_db)):
    """Property manager signup via invite link. Creates User and PropertyManagerAssignment."""
    norm_token = _normalize_manager_invite_token(data.invite_token)
    if not norm_token:
        raise HTTPException(status_code=400, detail="Invitation not found or expired.")
    inv = db.query(ManagerInvitation).filter(ManagerInvitation.token == norm_token).first()
    if not inv:
        raise HTTPException(status_code=400, detail="Invitation not found or expired.")
    now = datetime.now(timezone.utc)
    if inv.status in ("cancelled", "expired"):
        raise HTTPException(status_code=400, detail="Invitation not found or expired.")
    if inv.email.strip().lower() != (data.email or "").strip().lower():
        raise HTTPException(status_code=400, detail="Email must match the invited email address.")
    inv_email_norm = normalize_registration_email(inv.email)
    if inv.status == "accepted":
        existing_done = (
            db.query(User)
            .filter(
                func.lower(func.trim(User.email)) == inv_email_norm,
                User.role == UserRole.property_manager,
            )
            .first()
        )
        if not existing_done:
            raise HTTPException(
                status_code=400,
                detail="This invitation has already been used. Please log in with your property manager account.",
            )
        if not verify_password(data.password, existing_done.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid password. Please use the password for your Property Manager account.")
        assn_done = db.query(PropertyManagerAssignment).filter(
            PropertyManagerAssignment.property_id == inv.property_id,
            PropertyManagerAssignment.user_id == existing_done.id,
        ).first()
        if not assn_done:
            raise HTTPException(
                status_code=400,
                detail="This invitation has already been used. Please log in with your property manager account.",
            )
        token = create_access_token(existing_done.id, existing_done.email, existing_done.role)
        return Token(access_token=token, user=_user_to_response(existing_done, db))
    if inv.status != "pending" or inv.expires_at <= now:
        raise HTTPException(status_code=400, detail="Invitation not found or expired.")
    enforce_email_available_for_intended_role(
        db, inv_email_norm, UserRole.property_manager, allow_same_role_pending=True
    )
    from app.services.permissions import email_conflicts_with_property_as_tenant_or_guest
    if email_conflicts_with_property_as_tenant_or_guest(db, email=inv_email_norm, property_id=inv.property_id):
        raise HTTPException(
            status_code=409,
            detail="This email is currently associated with a tenant or guest presence on this property and cannot be used to manage this property.",
        )
    existing = (
        db.query(User)
        .filter(
            func.lower(func.trim(User.email)) == inv_email_norm,
            User.role == UserRole.property_manager,
        )
        .first()
    )
    if existing:
        existing_assignment = db.query(PropertyManagerAssignment).filter(
            PropertyManagerAssignment.property_id == inv.property_id,
            PropertyManagerAssignment.user_id == existing.id,
        ).first()
        if existing_assignment:
            raise HTTPException(status_code=400, detail="You are already assigned to this property. Please log in.")
        if not verify_password(data.password, existing.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid password. Please use the password for your Property Manager account.")
        user = existing
        assn = PropertyManagerAssignment(
            property_id=inv.property_id,
            user_id=user.id,
            assigned_by_user_id=inv.invited_by_user_id,
        )
        db.add(assn)
    else:
        user = User(
            email=inv_email_norm,
            hashed_password=get_password_hash(data.password),
            role=UserRole.property_manager,
            full_name=data.full_name or inv_email_norm.split("@")[0],
            phone=data.phone or None,
            email_verified=True,
            email_verification_code=None,
            email_verification_expires_at=None,
        )
        db.add(user)
        db.flush()
        assn = PropertyManagerAssignment(
            property_id=inv.property_id,
            user_id=user.id,
            assigned_by_user_id=inv.invited_by_user_id,
        )
        db.add(assn)
    inv.status = "accepted"
    inv.accepted_at = datetime.now(timezone.utc)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError as e:
        db.rollback()
        msg = str(getattr(getattr(e, "orig", None), "args", [""])[0] if hasattr(e, "orig") and e.orig else str(e))
        if "unique" in msg.lower() or "duplicate" in msg.lower():
            raise HTTPException(status_code=400, detail="This email is already registered. Please log in.")
        raise
    prop_for_msg = db.query(Property).filter(Property.id == inv.property_id).first()
    prop_label = (
        (prop_for_msg.name or f"{prop_for_msg.street or ''}, {prop_for_msg.city or ''}".strip(", ").strip() or f"Property {inv.property_id}")
        if prop_for_msg
        else f"Property {inv.property_id}"
    )
    create_ledger_event(
        db,
        ACTION_MANAGER_INVITE_ACCEPTED,
        target_object_type="ManagerInvitation",
        target_object_id=inv.id,
        property_id=inv.property_id,
        actor_user_id=user.id,
        meta={
            "message": f"Property manager {user.email} accepted the invitation for {prop_label}.",
            "email": user.email,
            "property_id": inv.property_id,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "").strip() or None,
    )
    create_ledger_event(
        db,
        ACTION_MANAGER_ASSIGNED,
        target_object_type="PropertyManagerAssignment",
        target_object_id=assn.id,
        property_id=inv.property_id,
        actor_user_id=inv.invited_by_user_id,
        meta={
            "message": f"Property manager {user.email} assigned to {prop_label}.",
            "manager_email": user.email,
            "manager_user_id": user.id,
            "property_id": inv.property_id,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "").strip() or None,
    )
    db.commit()
    property_name = (
        (prop_for_msg.name or f"{prop_for_msg.street or ''}, {prop_for_msg.city or ''}".strip(", ")).strip() or "your properties"
        if prop_for_msg
        else "your properties"
    )
    send_manager_welcome_email(user.email, user.full_name, property_name)
    token = create_access_token(user.id, user.email, user.role)
    return Token(access_token=token, user=_user_to_response(user, db))


@router.post("/accept-manager-invite/{token}")
def accept_manager_invite(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Accept a manager invitation as an already-logged-in property manager. Creates PropertyManagerAssignment."""
    if current_user.role != UserRole.property_manager:
        raise HTTPException(status_code=403, detail="Only property managers can accept manager invitations.")
    norm_token = _normalize_manager_invite_token(token)
    if not norm_token:
        raise HTTPException(status_code=400, detail="Invitation not found or expired.")
    inv = db.query(ManagerInvitation).filter(ManagerInvitation.token == norm_token).first()
    if not inv:
        raise HTTPException(status_code=400, detail="Invitation not found or expired.")
    if inv.email.strip().lower() != (current_user.email or "").strip().lower():
        raise HTTPException(status_code=403, detail="This invitation was sent to a different email address.")
    from app.services.permissions import email_conflicts_with_property_as_tenant_or_guest
    if email_conflicts_with_property_as_tenant_or_guest(db, email=current_user.email, property_id=inv.property_id):
        raise HTTPException(
            status_code=409,
            detail="Your email is currently associated with a tenant or guest presence on this property and cannot be used to manage this property.",
        )
    existing_assignment = db.query(PropertyManagerAssignment).filter(
        PropertyManagerAssignment.property_id == inv.property_id,
        PropertyManagerAssignment.user_id == current_user.id,
    ).first()
    if existing_assignment:
        return {"status": "success", "message": "You are already assigned to this property."}
    now = datetime.now(timezone.utc)
    if inv.status == "accepted":
        raise HTTPException(
            status_code=400,
            detail="This invitation is no longer active. If you need access, ask the property owner for a new invitation.",
        )
    if inv.status != "pending" or inv.expires_at <= now:
        raise HTTPException(status_code=400, detail="Invitation not found or expired.")
    assn = PropertyManagerAssignment(
        property_id=inv.property_id,
        user_id=current_user.id,
        assigned_by_user_id=inv.invited_by_user_id,
    )
    db.add(assn)
    db.flush()
    inv.status = "accepted"
    inv.accepted_at = datetime.now(timezone.utc)
    prop_for_inv = db.query(Property).filter(Property.id == inv.property_id).first()
    prop_label = (
        (prop_for_inv.name or f"{prop_for_inv.street or ''}, {prop_for_inv.city or ''}".strip(", ").strip() or f"Property {inv.property_id}")
        if prop_for_inv
        else f"Property {inv.property_id}"
    )
    create_ledger_event(
        db,
        ACTION_MANAGER_INVITE_ACCEPTED,
        target_object_type="ManagerInvitation",
        target_object_id=inv.id,
        property_id=inv.property_id,
        actor_user_id=current_user.id,
        meta={
            "message": f"Property manager {current_user.email} accepted the invitation for {prop_label}.",
            "email": current_user.email,
            "property_id": inv.property_id,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "").strip() or None,
    )
    create_ledger_event(
        db,
        ACTION_MANAGER_ASSIGNED,
        target_object_type="PropertyManagerAssignment",
        target_object_id=assn.id,
        property_id=inv.property_id,
        actor_user_id=inv.invited_by_user_id,
        meta={
            "message": f"Property manager {current_user.email} assigned to {prop_label}.",
            "manager_email": current_user.email,
            "manager_user_id": current_user.id,
            "property_id": inv.property_id,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "").strip() or None,
    )
    db.commit()
    return {"status": "success", "message": "Invitation accepted. You can now manage this property."}


def _complete_pending_owner(db: Session, pending: PendingRegistration) -> User:
    """Create User from pending owner, link POA, delete pending. Returns the new User."""
    from app.models.user import OwnerType
    extra = pending.extra_data or {}
    poa_id = extra.get("poa_signature_id")
    owner_type_val = extra.get("owner_type")
    owner_type = OwnerType(owner_type_val) if owner_type_val in ("owner_of_record", "authorized_agent") else None
    user = User(
        email=pending.email,
        hashed_password=pending.hashed_password,
        role=UserRole.owner,
        full_name=pending.full_name,
        phone=pending.phone,
        state=pending.state,
        city=pending.city,
        country=pending.country,
        email_verified=True,
        email_verification_code=None,
        email_verification_expires_at=None,
        owner_type=owner_type,
    )
    db.add(user)
    db.flush()
    if poa_id:
        poa = db.query(OwnerPOASignature).filter(OwnerPOASignature.id == poa_id).first()
        if poa and poa.owner_email.strip().lower() == user.email.strip().lower():
            poa.used_by_user_id = user.id
            poa.used_at = datetime.now(timezone.utc)
    db.delete(pending)
    db.commit()
    db.refresh(user)
    return user


def _complete_pending_tenant(db: Session, pending: PendingRegistration) -> User:
    """Create User with role=tenant from pending. Tenant does not sign any agreement; when they register with
    valid tenant invite code, create TenantAssignment directly (accept invite / access to unit)."""
    user = User(
        email=pending.email,
        hashed_password=pending.hashed_password,
        role=UserRole.tenant,
        full_name=pending.full_name,
        phone=pending.phone,
        state=pending.state,
        city=pending.city,
        country="USA",
        email_verified=True,
        email_verification_code=None,
        email_verification_expires_at=None,
    )
    db.add(user)
    db.flush()
    extra = pending.extra_data or {}
    code = (extra.get("invitation_code") or "").strip().upper()

    # Find the tenant invitation (any token_state; CSV/onboarding may create STAGED until signup completes)
    inv = None
    if code:
        inv = (
            db.query(Invitation)
            .filter(
                Invitation.invitation_code == code,
                Invitation.status.in_(["pending", "ongoing", "accepted"]),
                Invitation.unit_id.isnot(None),
                Invitation.invitation_kind.in_(tuple(TENANT_UNIT_LEASE_KINDS)),
            )
            .first()
        )

    if inv:
        # Tenant does not sign any agreement. Create TenantAssignment directly (accept invite / access to unit).
        assert_can_record_tenant_assignment_for_invite_or_raise(db, inv, user.id)
        ta = TenantAssignment(
            unit_id=inv.unit_id,
            user_id=user.id,
            start_date=inv.stay_start_date,
            end_date=inv.stay_end_date,
            invited_by_user_id=getattr(inv, "invited_by_user_id", None),
        )
        db.add(ta)
        db.flush()
        inv.status = "accepted"
        inv.token_state = "BURNED"
        create_ledger_event(
            db,
            ACTION_TENANT_ACCEPTED,
            target_object_type="TenantAssignment",
            target_object_id=ta.id,
            property_id=inv.property_id,
            unit_id=inv.unit_id,
            invitation_id=inv.id,
            actor_user_id=user.id,
            meta={"invitation_code": code, "unit_id": inv.unit_id, "tenant_email": user.email},
        )

    db.delete(pending)
    db.commit()
    db.refresh(user)
    send_guest_signup_welcome_email(user.email, user.full_name)  # Reuse generic welcome for tenant
    return user


def _complete_pending_guest(
    request: Request, db: Session, pending: PendingRegistration
) -> User:
    """Create User and GuestProfile from pending guest; handle invite/stay; delete pending. Returns the new User."""
    extra = pending.extra_data or {}
    code = (extra.get("invitation_code") or "").strip().upper()
    inv = None
    if code:
        inv = db.query(Invitation).filter(Invitation.invitation_code == code).first()
        if inv and (getattr(inv, "invitation_kind", None) or "").strip().lower() != "guest":
            inv = None
        elif inv:
            awaiting_signup = guest_invite_awaiting_account_after_sign(db, inv)
            tok = (inv.token_state or "").upper()
            if not awaiting_signup and (
                inv.status not in ("pending", "ongoing", "accepted") or tok == "BURNED"
            ):
                inv = None
    sig = None
    sig_id = extra.get("agreement_signature_id")
    if sig_id and code:
        sig = db.query(AgreementSignature).filter(AgreementSignature.id == sig_id).first()
        if sig and (sig.invitation_code or "").strip().upper() != code:
            sig = None
        if sig and (sig.guest_email or "").strip().lower() != (pending.email or "").strip().lower():
            sig = None
        if sig and sig.used_by_user_id is not None:
            sig = None
        if sig and not (sig.acks_read and sig.acks_temporary and sig.acks_vacate and sig.acks_electronic):
            sig = None

    user = User(
        email=pending.email,
        hashed_password=pending.hashed_password,
        role=UserRole.guest,
        full_name=pending.full_name,
        phone=pending.phone,
        state=extra.get("permanent_state"),
        city=extra.get("permanent_city"),
        country="USA",
        email_verified=True,
        email_verification_code=None,
        email_verification_expires_at=None,
    )
    db.add(user)
    db.flush()
    permanent_address = extra.get("permanent_address") or ""
    permanent_city = extra.get("permanent_city") or ""
    permanent_state = extra.get("permanent_state") or ""
    permanent_zip = extra.get("permanent_zip") or ""
    permanent_home = f"{permanent_address}, {permanent_city}, {permanent_state} {permanent_zip}".strip()
    profile = GuestProfile(
        user_id=user.id,
        full_legal_name=pending.full_name or "",
        permanent_home_address=permanent_home,
        gps_checkin_acknowledgment=False,
    )
    db.add(profile)
    db.flush()

    prop = None
    if code and inv and sig:
        duration = (inv.stay_end_date - inv.stay_start_date).days
        if duration <= 0:
            duration = 1
        from app.services.guest_stay_overlap import enforce_guest_stay_no_overlap_or_resolve

        enforce_guest_stay_no_overlap_or_resolve(db, guest_id=user.id, inv=inv)
        stay = Stay(
            guest_id=user.id,
            owner_id=inv.owner_id,
            property_id=inv.property_id,
            unit_id=getattr(inv, "unit_id", None),
            invitation_id=inv.id,
            invited_by_user_id=getattr(inv, "invited_by_user_id", None),
            stay_start_date=inv.stay_start_date,
            stay_end_date=inv.stay_end_date,
            intended_stay_duration_days=duration,
            purpose_of_stay=inv.purpose_of_stay,
            relationship_to_owner=inv.relationship_to_owner,
            region_code=inv.region_code,
        )
        db.add(stay)
        # Fix Bug #5b: Do NOT mark invitation as accepted/BURNED here for Dropbox flow.
        # For Dropbox, this is handled in emit_invitation_agreement_signed_if_dropbox_complete
        # once the signed PDF is actually received.
        if not sig.dropbox_sign_request_id:
            inv.status = "accepted"
            if hasattr(inv, "token_state"):
                inv.token_state = "BURNED"
        
        sig.used_by_user_id = user.id
        sig.used_at = datetime.now(timezone.utc)
        # Occupancy is set to OCCUPIED only when guest checks in (guest_check_in endpoint).
        db.flush()
        ip = request.client.host if request.client else None
        ua = (request.headers.get("user-agent") or "").strip() or None
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            "Invitation accepted (stay created)",
            f"Guest registered and accepted invitation {code}; stay {stay.id} created for property {inv.property_id}. Occupancy will be set when guest checks in.",
            property_id=inv.property_id,
            stay_id=stay.id,
            invitation_id=inv.id,
            actor_user_id=user.id,
            actor_email=user.email,
            ip_address=ip,
            user_agent=ua,
            meta={"invitation_code": code, "signature_id": sig.id},
        )
        create_ledger_event(
            db,
            ACTION_GUEST_INVITE_ACCEPTED,
            target_object_type="Stay",
            target_object_id=stay.id,
            property_id=inv.property_id,
            stay_id=stay.id,
            invitation_id=inv.id,
            actor_user_id=user.id,
            meta={"invitation_code": code, "signature_id": sig.id},
            ip_address=ip,
            user_agent=ua,
        )
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}".strip(", ") if prop and (prop.city or prop.state) else None) or "the property"
        send_guest_welcome_email(user.email, user.full_name, property_name=property_name, stay_end_date=str(inv.stay_end_date))
        if getattr(inv, "invited_by_user_id", None):
            invited_by_user = db.query(User).filter(User.id == inv.invited_by_user_id).first()
            if invited_by_user and invited_by_user.role == UserRole.tenant and (invited_by_user.email or "").strip():
                guest_name = (user.full_name or "").strip() or (user.email or "").strip() or "Unknown invitee"
                try:
                    send_tenant_guest_accepted_invite(invited_by_user.email.strip(), guest_name, property_name)
                except Exception:
                    pass
    elif code and inv:
        pending_inv = GuestPendingInvite(user_id=user.id, invitation_id=inv.id)
        db.add(pending_inv)
    if not (code and inv and sig):
        send_guest_signup_welcome_email(user.email, user.full_name)

    db.delete(pending)
    db.commit()
    db.refresh(user)
    if prop:
        try:
            profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            if profile:
                sync_subscription_quantities(db, profile)
        except Exception:
            pass
    return user


def _normalize_verification_code(raw: str | None) -> str:
    """Return stripped string, or empty string if not exactly 6 digits."""
    s = (raw or "").strip()
    if len(s) != 6 or not s.isdigit():
        return ""
    return s


@router.post("/verify-email", response_model=Token)
def verify_email(request: Request, data: VerifyEmailRequest, db: Session = Depends(get_db)):
    """Verify email with the 6-digit code. Creates user only after verification (from pending) or marks existing user verified (legacy)."""
    raw_code = (data.code or "").strip()
    code = _normalize_verification_code(data.code)
    if raw_code and not code:
        raise HTTPException(status_code=400, detail="Verification code must be exactly 6 digits.")
    pending = db.query(PendingRegistration).filter(PendingRegistration.id == data.user_id).first()
    if pending:
        stored_code = _normalize_verification_code(pending.verification_code)
        if not code or not stored_code or stored_code != code:
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Email verification failed",
                f"Invalid or wrong verification code for pending_id={data.user_id}.",
                actor_email=pending.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"pending_id": data.user_id, "reason": "invalid_or_expired_code"},
            )
            db.commit()
            raise HTTPException(status_code=400, detail="Invalid or expired verification code.")
        if pending.expires_at < datetime.now(timezone.utc):
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Email verification failed",
                f"Expired verification code for pending_id={data.user_id}.",
                actor_email=pending.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"pending_id": data.user_id, "reason": "expired_code"},
            )
            db.commit()
            raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new one.")
        if pending.role == UserRole.owner:
            # Owner: do NOT create user yet. Mark email verified, return pending-owner token. User is created after identity + POA.
            # Assign new dict so SQLAlchemy persists JSONB (in-place mutation may not be detected).
            pending.extra_data = {**(pending.extra_data or {}), "email_verified_at": datetime.now(timezone.utc).isoformat()}
            db.commit()
            db.refresh(pending)
            token = create_pending_owner_token(pending.id, pending.email)
            fake_user = UserResponse(
                id=0,
                email=pending.email,
                role=UserRole.owner,
                full_name=pending.full_name,
                phone=pending.phone,
                state=pending.state,
                city=pending.city,
                identity_verified=False,
                poa_linked=False,
            )
            return Token(access_token=token, user=fake_user)
        pending_email_norm = normalize_registration_email(pending.email)
        enforce_no_conflicting_user_before_pending_completion(db, pending_email_norm, pending.role)
        if pending.role == UserRole.tenant:
            user = _complete_pending_tenant(db, pending)
        else:
            user = _complete_pending_guest(request, db, pending)
        _trigger_guest_approaching_end_notifications_after_auth(db, user, request)
        token = create_access_token(user.id, user.email, user.role)
        return Token(access_token=token, user=_user_to_response(user, db))

    # Legacy: already-created unverified user (from before pending flow)
    user = db.query(User).filter(User.id == data.user_id).first()
    if not user:
        raise HTTPException(
            status_code=400,
            detail="Verification session not found. Please go back to registration and sign up again.",
        )
    # Only skip code check when user is already verified AND no code was provided (re-requesting token).
    # If a code was provided we must validate it so a wrong code never returns success.
    if getattr(user, "email_verified", False) and (not code or len(code) != 6):
        _trigger_guest_approaching_end_notifications_after_auth(db, user, request)
        token = create_access_token(user.id, user.email, user.role)
        return Token(access_token=token, user=_user_to_response(user, db))
    stored_user_code = _normalize_verification_code(user.email_verification_code)
    if not code or not stored_user_code or stored_user_code != code:
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Email verification failed",
            f"Invalid or wrong verification code for user_id={data.user_id}.",
            actor_email=user.email,
            ip_address=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "").strip() or None,
            meta={"user_id": data.user_id, "reason": "invalid_or_expired_code"},
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")
    if user.email_verification_expires_at and user.email_verification_expires_at < datetime.now(timezone.utc):
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Email verification failed",
            f"Expired verification code for user_id={data.user_id}.",
            actor_email=user.email,
            ip_address=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "").strip() or None,
            meta={"user_id": data.user_id, "reason": "expired_code"},
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new one.")
    user.email_verified = True
    user.email_verification_code = None
    user.email_verification_expires_at = None
    db.commit()
    db.refresh(user)
    if user.role == UserRole.owner:
        send_owner_welcome_email(user.email, user.full_name)
    _trigger_guest_approaching_end_notifications_after_auth(db, user, request)
    token = create_access_token(user.id, user.email, user.role)
    return Token(access_token=token, user=_user_to_response(user, db))


@router.post("/resend-verification")
def resend_verification(data: ResendVerificationRequest, db: Session = Depends(get_db)):
    """Send a new verification code. Works for pending registration or legacy unverified user."""
    pending = db.query(PendingRegistration).filter(PendingRegistration.id == data.user_id).first()
    if pending:
        code = _generate_verification_code()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_CODE_EXPIRE_MINUTES)
        pending.verification_code = code
        pending.expires_at = expires_at
        db.commit()
        sent = send_verification_email(pending.email, code)
        if not sent:
            print(f"Resend verification email not sent to {pending.email}", flush=True)
            raise HTTPException(
                status_code=503,
                detail="We could not send the verification email. Check MAILGUN_DOMAIN and MAILGUN_FROM_EMAIL in .env and restart the server, then try again.",
            )
        return {"status": "ok", "message": "Verification code sent. Check your email."}

    user = db.query(User).filter(User.id == data.user_id).first()
    if not user:
        raise HTTPException(
            status_code=400,
            detail="Verification session not found. Please go back to registration and sign up again.",
        )
    if getattr(user, "email_verified", False):
        return {"status": "ok", "message": "Email is already verified."}
    code = _generate_verification_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_CODE_EXPIRE_MINUTES)
    user.email_verification_code = code
    user.email_verification_expires_at = expires_at
    db.commit()
    sent = send_verification_email(user.email, code)
    if not sent:
        print(f"Resend verification email not sent to {user.email}", flush=True)
        raise HTTPException(
            status_code=503,
            detail="We could not send the verification email. Check MAILGUN_DOMAIN and MAILGUN_FROM_EMAIL in .env and restart the server, then try again.",
        )
    return {"status": "ok", "message": "Verification code sent. Check your email."}


@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Request a password reset email. ``role`` selects which account when the same email has multiple roles."""
    email_norm = normalize_registration_email(str(data.email) if data.email else "")
    if not email_norm:
        raise HTTPException(status_code=400, detail="Email is required.")
    user = db.query(User).filter(
        func.lower(func.trim(User.email)) == email_norm,
        User.role == data.role,
    ).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="No account found for this email. Check the spelling, or register first.",
        )
    base_url = (get_settings().frontend_base_url or "").strip().rstrip("/")
    if not base_url:
        # No frontend URL configured; cannot build reset link. Return same message (no email enumeration).
        return {"status": "ok", "message": "If an account exists for this email, you will receive a password reset link shortly."}
    reset_secret = secrets.token_urlsafe(32)
    user.password_reset_token = reset_secret
    user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    db.commit()
    token = create_password_reset_token(user.id, user.email, user.role, reset_secret)
    reset_link = f"{base_url}/#reset-password?token={token}&role={user.role.value}"
    sent = send_password_reset_email(user.email, reset_link, user.role.value)
    if not sent:
        print(f"[Auth] Password reset email not sent to {user.email}", flush=True)
        raise HTTPException(
            status_code=503,
            detail="We could not send the password reset email. Please try again later or contact support.",
        )
    return {"status": "ok", "message": "If an account exists for this email, you will receive a password reset link shortly."}


@router.post("/reset-password")
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Set new password using the token from the reset email. Token is one-time use; invalid after first use."""
    payload, err = decode_token_with_error(data.token)
    if err or not payload:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link. Please request a new password reset.")
    if payload.get("type") != "password_reset":
        raise HTTPException(status_code=400, detail="Invalid reset link. Please use the link from your email.")
    reset_secret = payload.get("reset_secret")
    if not reset_secret:
        raise HTTPException(status_code=400, detail="Invalid reset link. Please request a new password reset.")
    try:
        user_id = int(payload.get("sub") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid reset link.")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid reset link. Please request a new password reset.")
    now = datetime.now(timezone.utc)
    if not user.password_reset_token or user.password_reset_token != reset_secret:
        raise HTTPException(status_code=400, detail="This reset link has already been used. Request a new password reset if needed.")
    if user.password_reset_expires_at and user.password_reset_expires_at < now:
        user.password_reset_token = None
        user.password_reset_expires_at = None
        db.commit()
        raise HTTPException(status_code=400, detail="This reset link has expired. Please request a new password reset.")
    user.hashed_password = get_password_hash(data.new_password)
    user.password_reset_token = None
    user.password_reset_expires_at = None
    db.commit()
    return {"status": "ok", "message": "Password updated. You can sign in now."}


@router.get("/me", response_model=UserResponse)
def me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _user_to_response(current_user, db)


def _stripe_identity_configured():
    s = get_settings()
    return bool(s.stripe_secret_key and (s.stripe_identity_return_url or s.stripe_identity_flow_id))


def _log_stripe_session(session, stage: str) -> None:
    """Print Stripe VerificationSession fields so we can decide based on success/failure."""
    try:
        sid = getattr(session, "id", None) or (session.get("id") if hasattr(session, "get") and callable(session.get) else None)
        status = getattr(session, "status", None) or (session.get("status") if hasattr(session, "get") and callable(session.get) else None)
        last_error = getattr(session, "last_error", None) or (session.get("last_error") if hasattr(session, "get") and callable(session.get) else None)
        meta = getattr(session, "metadata", None) or (session.get("metadata") if hasattr(session, "get") and callable(session.get) else None)
        err_code = getattr(last_error, "code", None) if last_error else (last_error.get("code") if isinstance(last_error, dict) else None)
        err_reason = getattr(last_error, "reason", None) if last_error else (last_error.get("reason") if isinstance(last_error, dict) else None)
        print(f"[Stripe Identity] {stage} -> id={sid} status={status} last_error.code={err_code} last_error.reason={err_reason} metadata={meta}")
        if status == "verified":
            print(f"[Stripe Identity] SUCCESS verification completed for session_id={sid}")
        elif status == "requires_input" and stage == "CREATE":
            print(f"[Stripe Identity] CREATE: requires_input is expected (user has not verified yet)")
        elif status and status != "verified":
            print(f"[Stripe Identity] NOT_VERIFIED status={status} (use last_error above for failure reason)")
    except Exception as e:
        print(f"[Stripe Identity] {stage} -> log parse error: {e}")


def _stripe_session_failure_detail(session) -> str:
    """Build user-facing failure message from Stripe session. Success is session.status == 'verified'; anything else is failure."""
    status = getattr(session, "status", None) or (session.get("status") if hasattr(session, "get") and callable(session.get) else None)
    last_error = getattr(session, "last_error", None) or (session.get("last_error") if hasattr(session, "get") and callable(session.get) else None)
    err_reason = None
    err_code = None
    if last_error:
        err_code = getattr(last_error, "code", None) if not isinstance(last_error, dict) else last_error.get("code")
        err_reason = getattr(last_error, "reason", None) if not isinstance(last_error, dict) else last_error.get("reason")
    parts = [f"Verification not completed. Status: {status or 'unknown'}."]
    if err_reason:
        parts.append(f" Reason: {err_reason}.")
    if err_code and not err_reason:
        parts.append(f" Code: {err_code}.")
    parts.append(" Please complete the verification flow or try again.")
    return "".join(parts)


@router.post("/pending-owner/identity-session", response_model=PendingOwnerIdentitySessionResponse)
def pending_owner_create_identity_session(
    data: PendingOwnerIdentitySessionRequest | None = Body(None),
    db: Session = Depends(get_db),
    pending: PendingRegistration = Depends(get_pending_owner),
):
    """Create Stripe Identity session for pending owner (after email verified). return_url from frontend ensures Stripe redirects to same origin (preserves localStorage token)."""
    if not _stripe_identity_configured():
        raise HTTPException(status_code=503, detail="Identity verification is not configured.")
    import stripe
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key
    # Use STRIPE_IDENTITY_RETURN_URL or FRONTEND_BASE_URL from .env; no hardcoded localhost.
    base_url = (settings.stripe_identity_return_url or settings.frontend_base_url or "").strip().split("#")[0].rstrip("/")
    candidate = (data.return_url or "").strip().split("#")[0].rstrip("/") if data and data.return_url else ""
    if candidate and (candidate.startswith("http://") or candidate.startswith("https://")):
        return_url = f"{candidate.rstrip('/')}/onboarding/identity-complete"
    elif base_url:
        return_url = f"{base_url}/onboarding/identity-complete"
    else:
        raise HTTPException(
            status_code=503,
            detail="Identity verification is not configured. Set STRIPE_IDENTITY_RETURN_URL or FRONTEND_BASE_URL in .env.",
        )
    try:
        flow_id = (settings.stripe_identity_flow_id or "").strip()
        if flow_id:
            create_params = {"verification_flow": flow_id, "return_url": return_url, "metadata": {"pending_id": str(pending.id)}}
        else:
            create_params = {
                "type": "document",
                "return_url": return_url,
                "metadata": {"pending_id": str(pending.id)},
                "options": {"document": {"allowed_types": ["driving_license", "passport", "id_card"], "require_matching_selfie": True}},
            }
        idempotency_key = (
            f"identity_pending_{pending.id}_new_{int(datetime.now(timezone.utc).timestamp())}"
            if (data and getattr(data, "force_new_session", False))
            else f"identity_pending_{pending.id}"
        )
        session = stripe.identity.VerificationSession.create(**create_params, idempotency_key=idempotency_key)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Stripe error: {getattr(e, 'message', str(e))}")
    _url = getattr(session, "url", None) or (session.get("url") if hasattr(session, "get") and callable(session.get) else None)
    url = str(_url).strip() if _url else None
    if not url or not url.startswith("http"):
        raise HTTPException(status_code=502, detail="Stripe did not return a verification URL. Check Stripe Identity and return_url configuration.")
    _log_stripe_session(session, "CREATE")
    sid = getattr(session, "id", None) or (session.get("id") if hasattr(session, "get") and callable(session.get) else None)
    if sid:
        # Assign a new dict so SQLAlchemy detects the JSONB change (in-place mutation may not be persisted).
        pending.extra_data = {**(pending.extra_data or {}), "last_identity_session_id": str(sid)}
        db.commit()
        print(f"[Auth] Stripe Identity session created and stored: id={sid} pending_id={pending.id} url={url[:70]}...")
    else:
        print(f"[Auth] Stripe Identity session created (no id to store): url={url[:70]}...")
    return PendingOwnerIdentitySessionResponse(client_secret=str(session.client_secret), url=url)


@router.post("/pending-owner/confirm-identity")
def pending_owner_confirm_identity(
    data: PendingOwnerConfirmIdentityRequest,
    db: Session = Depends(get_db),
    pending: PendingRegistration = Depends(get_pending_owner),
):
    """After Stripe redirect: verify session and mark pending as identity-verified."""
    if not _stripe_identity_configured():
        raise HTTPException(status_code=503, detail="Identity verification is not configured.")
    import stripe
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key
    session_id = (data.verification_session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="verification_session_id is required.")
    try:
        session = stripe.identity.VerificationSession.retrieve(session_id)
    except Exception as e:
        print(f"[Stripe Identity] RETRIEVE FAILED session_id={session_id} error={type(e).__name__}: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid verification session: {getattr(e, 'message', str(e))}")
    _log_stripe_session(session, "RETRIEVE")
    if session.metadata.get("pending_id") != str(pending.id):
        raise HTTPException(status_code=403, detail="This verification session does not match your signup.")
    # Success = Stripe status "verified"; any other status (requires_input, processing, canceled, etc.) = failure.
    if session.status != "verified":
        print(f"[Stripe Identity] VERIFICATION NOT COMPLETED status={session.status} session_id={session_id} (use status/last_error above to decide)")
        # Do NOT delete pending; user can retry via identity-retry endpoint.
        detail_msg = _stripe_session_failure_detail(session)
        last_error = getattr(session, "last_error", None) or (session.get("last_error") if hasattr(session, "get") and callable(session.get) else None)
        err_code = None
        if last_error:
            err_code = getattr(last_error, "code", None) if not isinstance(last_error, dict) else last_error.get("code")
        raise HTTPException(
            status_code=400,
            detail={
                "detail": detail_msg,
                "error_code": err_code,
                "session_id": session_id,
            },
        )
    print(f"[Stripe Identity] SUCCESS confirm-identity: marking pending_id={pending.id} as identity-verified")
    pending.extra_data = {
        **(pending.extra_data or {}),
        "identity_verified_at": datetime.now(timezone.utc).isoformat(),
        "stripe_verification_session_id": session_id,
    }
    db.commit()
    return {"status": "ok", "message": "Identity verified. Now sign the Master POA to complete signup."}


@router.get("/pending-owner/me", response_model=PendingOwnerMeResponse)
def pending_owner_me(pending: PendingRegistration = Depends(get_pending_owner)):
    """Return email and full_name for the pending owner (e.g. for POA sign modal)."""
    extra = pending.extra_data or {}
    return PendingOwnerMeResponse(
        email=pending.email,
        full_name=pending.full_name,
        city=pending.city,
        state=pending.state,
        country=pending.country,
        account_type=extra.get("account_type"),
    )


@router.get("/pending-owner/latest-identity-session", response_model=PendingOwnerLatestIdentitySessionResponse)
def pending_owner_latest_identity_session(pending: PendingRegistration = Depends(get_pending_owner)):
    """Return the verification_session_id we stored when creating the identity session. Use when Stripe redirects without session_id in URL (e.g. some test or redirect flows)."""
    extra = pending.extra_data or {}
    sid = extra.get("last_identity_session_id")
    if not sid:
        raise HTTPException(status_code=404, detail="No identity session found for this signup. Start verification from the identity step.")
    return PendingOwnerLatestIdentitySessionResponse(verification_session_id=sid)


@router.post("/pending-owner/identity-retry", response_model=PendingOwnerIdentityRetryResponse)
def pending_owner_identity_retry(
    data: PendingOwnerIdentityRetryRequest,
    pending: PendingRegistration = Depends(get_pending_owner),
):
    """Return a fresh Stripe Identity URL for the same session so the user can retry verification (e.g. after requires_input)."""
    if not _stripe_identity_configured():
        raise HTTPException(status_code=503, detail="Identity verification is not configured.")
    import stripe
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key
    session_id = (data.verification_session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="verification_session_id is required.")
    try:
        session = stripe.identity.VerificationSession.retrieve(session_id)
    except Exception as e:
        print(f"[Stripe Identity] RETRIEVE (retry) FAILED session_id={session_id} error={type(e).__name__}: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid or expired verification session: {getattr(e, 'message', str(e))}")
    _log_stripe_session(session, "RETRIEVE_RETRY")
    meta = getattr(session, "metadata", None) or (session.get("metadata") if hasattr(session, "get") and callable(session.get) else {})
    if meta.get("pending_id") != str(pending.id):
        raise HTTPException(status_code=403, detail="This verification session does not match your signup.")
    status = getattr(session, "status", None) or (session.get("status") if hasattr(session, "get") and callable(session.get) else None)
    if status == "canceled":
        raise HTTPException(
            status_code=400,
            detail="This verification link is no longer valid. Please start verification again.",
        )
    if status == "verified":
        return PendingOwnerIdentityRetryResponse(
            url=None,
            already_verified=True,
            message="Identity is already verified. You can continue to sign the Master POA.",
        )
    if status == "requires_input":
        _url = getattr(session, "url", None) or (session.get("url") if hasattr(session, "get") and callable(session.get) else None)
        url = str(_url).strip() if _url else None
        if not url or not url.startswith("http"):
            raise HTTPException(status_code=502, detail="Stripe did not return a retry URL. Please start verification again.")
        return PendingOwnerIdentityRetryResponse(url=url, already_verified=False)
    raise HTTPException(
        status_code=400,
        detail=f"Verification session is not ready for retry (status: {status}). Please complete the flow or start verification again.",
    )


@router.post("/pending-owner/complete-signup", response_model=Token)
def complete_owner_signup(
    request: Request,
    data: CompleteOwnerSignupRequest,
    db: Session = Depends(get_db),
    pending: PendingRegistration = Depends(get_pending_owner),
):
    """After identity + POA: create User, link POA, delete pending, return real token. User is taken to dashboard."""
    extra = dict(pending.extra_data or {})
    # One-time backfill for pendings created before JSONB persistence fix: they have the token (so email was verified) and may have last_identity_session_id (so identity was completed) but keys were never saved.
    if not extra.get("email_verified_at"):
        extra["email_verified_at"] = datetime.now(timezone.utc).isoformat()
    if not extra.get("identity_verified_at") and extra.get("last_identity_session_id"):
        extra["identity_verified_at"] = datetime.now(timezone.utc).isoformat()
        extra["stripe_verification_session_id"] = extra["last_identity_session_id"]
    if extra != (pending.extra_data or {}):
        pending.extra_data = extra
        db.commit()
    has_email = bool(extra.get("email_verified_at"))
    has_identity = bool(extra.get("identity_verified_at"))
    if not has_email:
        print(f"[Auth] complete-signup 400: pending_id={pending.id} email={pending.email} missing email_verified_at in extra_data (keys={list(extra.keys())})")
        raise HTTPException(status_code=400, detail="Email not verified. Please complete the flow from the start.")
    if not has_identity:
        print(f"[Auth] complete-signup 400: pending_id={pending.id} missing identity_verified_at in extra_data (keys={list(extra.keys())})")
        raise HTTPException(status_code=400, detail="Identity not verified. Please complete identity verification first.")
    try:
        _validate_and_claim_owner_poa(
            db, data.poa_signature_id, pending.email,
            dropbox_incomplete_message="Please complete signing in Dropbox before completing signup.",
        )
    except HTTPException as e:
        print(f"[Auth] complete-signup 400: pending_id={pending.id} poa_signature_id={data.poa_signature_id} detail={e.detail}")
        raise
    from app.models.user import OwnerType
    owner_type_val = extra.get("owner_type")
    owner_type = OwnerType(owner_type_val) if owner_type_val in ("owner_of_record", "authorized_agent") else None
    account_type_val = extra.get("account_type")
    pending_owner_email_norm = normalize_registration_email(pending.email)
    enforce_no_conflicting_user_before_pending_completion(db, pending_owner_email_norm, UserRole.owner)
    user = User(
        email=pending_owner_email_norm,
        hashed_password=pending.hashed_password,
        role=UserRole.owner,
        full_name=pending.full_name,
        first_name=extra.get("first_name"),
        last_name=extra.get("last_name"),
        account_type=account_type_val,
        phone=pending.phone,
        state=pending.state,
        city=pending.city,
        country=pending.country,
        email_verified=True,
        email_verification_code=None,
        email_verification_expires_at=None,
        identity_verified_at=datetime.fromisoformat(extra["identity_verified_at"].replace("Z", "+00:00")) if isinstance(extra.get("identity_verified_at"), str) else datetime.now(timezone.utc),
        stripe_verification_session_id=extra.get("stripe_verification_session_id"),
        owner_type=owner_type,
    )
    db.add(user)
    db.flush()
    profile = OwnerProfile(user_id=user.id)
    db.add(profile)
    db.flush()
    poa = db.query(OwnerPOASignature).filter(OwnerPOASignature.id == data.poa_signature_id).first()
    if poa:
        poa.used_by_user_id = user.id
        poa.used_at = datetime.now(timezone.utc)
    db.delete(pending)
    db.commit()
    db.refresh(user)
    send_owner_welcome_email(user.email, user.full_name)
    cal = _effective_client_calendar_date_for_auth(request, data.client_calendar_date)
    _trigger_guest_approaching_end_notifications_after_auth(db, user, request, client_calendar_date=cal)
    token = create_access_token(user.id, user.email, user.role)
    return Token(access_token=token, user=_user_to_response(user, db))


@router.post("/owner/link-poa")
def link_owner_poa(
    data: LinkPOARequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """Link a Master POA signature to the current owner. Requires identity verification first. Call after owner has signed the POA (e.g. from onboarding POA step)."""
    if not getattr(current_user, "identity_verified_at", None):
        raise HTTPException(
            status_code=403,
            detail="Complete identity verification before linking your Master POA. Go to Identity Verification.",
        )
    from app.models.user import OwnerType
    if getattr(current_user, "owner_type", None) == OwnerType.authorized_agent and not data.authorized_agent_certified:
        raise HTTPException(
            status_code=400,
            detail="As an Authorized Agent you must certify that you have authority under your management agreement to delegate documentation authority to DocuStay.",
        )
    _validate_and_claim_owner_poa(
        db, data.poa_signature_id, current_user.email,
        dropbox_incomplete_message="Please complete signing in Dropbox before linking your Master POA.",
    )
    poa = db.query(OwnerPOASignature).filter(OwnerPOASignature.id == data.poa_signature_id).first()
    if poa:
        poa.used_by_user_id = current_user.id
        poa.used_at = datetime.now(timezone.utc)
        if getattr(current_user, "owner_type", None) == OwnerType.authorized_agent:
            current_user.authorized_agent_certified_at = datetime.now(timezone.utc)
            create_log(
                db,
                CATEGORY_STATUS_CHANGE,
                "Authorized Agent certification",
                f"Authorized Agent certified authority under management agreement to delegate documentation authority to DocuStay (user_id={current_user.id}, email={current_user.email}).",
                actor_user_id=current_user.id,
                actor_email=current_user.email,
            )
        db.commit()
    return {"status": "ok", "message": "Master POA linked to your account."}


@router.get("/register/guest")
def register_guest_get():
    """Browsers and link checkers issue GET; registration is POST-only."""
    return JSONResponse(
        status_code=405,
        content={
            "detail": "Guest registration requires HTTP POST with a JSON body to this URL. Opening this address in a browser will not register an account.",
        },
    )


@router.post("/register/guest")
def register_guest(request: Request, data: GuestRegister, db: Session = Depends(get_db)):
    """Register a guest or tenant. When Mailgun is configured, stores pending and returns user_id for verification. Invitation code optional for guests."""
    code = (data.invitation_code or data.invitation_id or "").strip().upper()
    target_role = UserRole.tenant if (getattr(data, "role", None) == "tenant") else UserRole.guest
    guest_email = normalize_registration_email(str(data.email) if data.email else "")
    if not guest_email:
        raise HTTPException(status_code=400, detail="Email is required.")
    enforce_email_available_for_intended_role(db, guest_email, target_role, allow_same_role_pending=True)

    existing = (
        db.query(User)
        .filter(func.lower(func.trim(User.email)) == guest_email, User.role == target_role)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail=same_role_already_registered_message(target_role))

    if _mailgun_configured():
        # Validate invite kind vs requested role before storing pending.
        if code:
            inv_check = db.query(Invitation).filter(Invitation.invitation_code == code).first()
            if inv_check:
                inv_kind = (getattr(inv_check, "invitation_kind", None) or "").strip().lower()
                if target_role == UserRole.guest and is_property_invited_tenant_signup_kind(inv_kind):
                    raise HTTPException(
                        status_code=400,
                        detail="This invitation is for a tenant, not a guest. Please use the tenant signup with this link.",
                    )
                if target_role == UserRole.tenant and is_tenant_lease_extension_kind(inv_kind):
                    raise HTTPException(
                        status_code=400,
                        detail="This link is for a lease extension. Sign in with your tenant account and accept it there — you cannot register a new account with this invitation.",
                    )
                if target_role == UserRole.tenant and not is_property_invited_tenant_signup_kind(inv_kind):
                    raise HTTPException(
                        status_code=400,
                        detail="This invitation is for a guest stay, not a tenant. Please use the guest signup with this link.",
                    )
                if target_role == UserRole.guest and not is_property_invited_tenant_signup_kind(inv_kind):
                    inv_guest_email_check = (getattr(inv_check, "guest_email", None) or "").strip().lower()
                    if not inv_guest_email_check:
                        raise HTTPException(
                            status_code=400,
                            detail="This invitation link is incomplete. Ask your host to send a new invitation that includes your email address.",
                        )
                    if guest_email != inv_guest_email_check:
                        raise HTTPException(
                            status_code=400,
                            detail="Please use the email address this invitation was sent to.",
                        )
        verification_code = _generate_verification_code()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_CODE_EXPIRE_MINUTES)
        extra = {
            "invitation_code": code,
            "agreement_signature_id": data.agreement_signature_id,
            "permanent_address": data.permanent_address,
            "permanent_city": data.permanent_city,
            "permanent_state": data.permanent_state,
            "permanent_zip": data.permanent_zip,
            "guest_status_acknowledged": data.guest_status_acknowledged,
            "no_tenancy_acknowledged": data.no_tenancy_acknowledged,
            "vacate_acknowledged": data.vacate_acknowledged,
        }
        pending = PendingRegistration(
            email=guest_email,
            hashed_password=get_password_hash(data.password),
            role=target_role,
            full_name=data.full_name or None,
            phone=data.phone or None,
            state=data.permanent_state or None,
            city=data.permanent_city or None,
            country="USA",
            verification_code=verification_code,
            expires_at=expires_at,
            extra_data=extra,
        )
        db.add(pending)
        db.commit()
        db.refresh(pending)
        sent = send_verification_email(guest_email, verification_code)
        if not sent:
            db.delete(pending)
            db.commit()
            raise HTTPException(
                status_code=503,
                detail="We could not send the verification email. Please try again later.",
            )
        return RegisterPendingResponse(user_id=pending.id)

    # No verification: create user immediately. Validate invite for guest or tenant.
    inv = None
    if code and target_role == UserRole.guest:
        inv = db.query(Invitation).filter(Invitation.invitation_code == code).first()
        if not inv:
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Guest register: invalid or expired invitation code",
                f"Guest registration attempted with invalid or expired invitation code: {code}.",
                property_id=None,
                actor_email=guest_email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code_attempted": code},
            )
            db.commit()
            raise HTTPException(status_code=400, detail="Invalid or expired invitation code")

        awaiting_signup = guest_invite_awaiting_account_after_sign(db, inv)

        # Check for expiration after 72 hours (skip when invite already signed via Dropbox; guest is finishing account creation)
        from app.services.invitation_cleanup import get_invitation_expire_cutoff
        threshold = get_invitation_expire_cutoff()
        if not awaiting_signup and (
            inv.status == "expired"
            or (
                inv.status == "pending"
                and inv.created_at is not None
                and inv.created_at < threshold
            )
        ):
            has_pending_dropbox = db.query(AgreementSignature).filter(
                AgreementSignature.invitation_code == code,
                AgreementSignature.dropbox_sign_request_id.isnot(None),
                AgreementSignature.signed_pdf_bytes.is_(None)
            ).first() is not None
            if not has_pending_dropbox and not guest_invitation_signing_started(db, code):
                raise HTTPException(status_code=400, detail="This invite has expired. Please contact your host to request a new one.")

        tok = (inv.token_state or "").upper()
        if not awaiting_signup and (
            inv.status not in ("pending", "ongoing", "accepted", "expired") or tok == "BURNED"
        ):
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Guest register: invalid or expired invitation code",
                f"Guest registration attempted with invalid or expired invitation code: {code}.",
                property_id=None,
                actor_email=guest_email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code_attempted": code},
            )
            db.commit()
            raise HTTPException(status_code=400, detail="Invalid or expired invitation code")

        inv_kind = (getattr(inv, "invitation_kind", None) or "").strip().lower()
        if is_property_invited_tenant_signup_kind(inv_kind):
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Guest register: invitation is for tenant",
                f"Guest registration attempted with a tenant invitation code: {code}.",
                property_id=inv.property_id,
                actor_email=guest_email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code_attempted": code},
            )
            db.commit()
            raise HTTPException(
                status_code=400,
                detail="This invitation is for a tenant, not a guest. Please use the tenant signup with this link.",
            )
        inv_guest_email = (getattr(inv, "guest_email", None) or "").strip().lower()
        if not inv_guest_email:
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Guest register: guest invitation missing guest_email",
                f"Guest registration attempted for invitation {code} with no guest_email on record.",
                property_id=inv.property_id,
                actor_email=guest_email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code_attempted": code},
            )
            db.commit()
            raise HTTPException(
                status_code=400,
                detail="This invitation link is incomplete. Ask your host to send a new invitation that includes your email address.",
            )
        if guest_email != inv_guest_email:
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Guest register: invitation email mismatch",
                f"Guest registration with email {guest_email} for invitation {code} intended for {inv.guest_email}.",
                property_id=inv.property_id,
                actor_email=guest_email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code_attempted": code, "invitation_guest_email": inv.guest_email},
            )
            db.commit()
            raise HTTPException(
                status_code=400,
                detail="Please use the email address this invitation was sent to.",
            )
    if code and target_role == UserRole.tenant:
        inv = (
            db.query(Invitation)
            .filter(
                Invitation.invitation_code == code,
                Invitation.status.in_(["pending", "ongoing", "accepted", "expired"]),
                Invitation.unit_id.isnot(None),
            )
            .first()
        )
        if not inv:
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Tenant register: invalid or no longer valid invitation code",
                f"Tenant registration attempted with invalid or no longer valid invitation code: {code}.",
                property_id=None,
                actor_email=guest_email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code_attempted": code},
            )
            db.commit()
            raise HTTPException(status_code=400, detail="Invalid or no longer valid tenant invitation code.")
        
        # Check for expiration after 72 hours for tenant invitations (though DocuStay typically doesn't expire them)
        from app.services.invitation_cleanup import get_invitation_expire_cutoff
        threshold = get_invitation_expire_cutoff()
        if inv.status == "expired" or (
            inv.status == "pending"
            and inv.created_at is not None
            and inv.created_at < threshold
        ):
             # Tenant invitations are not supposed to expire by default, but if they do, show the error.
             raise HTTPException(status_code=400, detail="This invite has expired. Please contact your host to request a new one.")

        inv_kind = (getattr(inv, "invitation_kind", None) or "").strip().lower()
        if not is_property_invited_tenant_signup_kind(inv_kind):
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Tenant register: invitation is for guest",
                f"Tenant registration attempted with a guest invitation code: {code}.",
                property_id=inv.property_id,
                actor_email=guest_email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code_attempted": code},
            )
            db.commit()
            raise HTTPException(
                status_code=400,
                detail="This invitation is for a guest stay, not a tenant. Please use the guest signup with this link.",
            )
        if is_tenant_lease_extension_kind(inv_kind):
            raise HTTPException(
                status_code=400,
                detail="This link is for a lease extension. Sign in with your tenant account and accept it there — you cannot register a new account with this invitation.",
            )
        inv_guest_email = (getattr(inv, "guest_email", None) or "").strip().lower()
        if inv_guest_email and guest_email != inv_guest_email:
            raise HTTPException(
                status_code=400,
                detail="Please use the email address this invitation was sent to.",
            )

    sig = None
    if data.agreement_signature_id and data.agreement_signature_id > 0:
        sig = db.query(AgreementSignature).filter(AgreementSignature.id == data.agreement_signature_id).first()
        if sig and (sig.invitation_code or "").strip().upper() != code:
            sig = None
        if sig and (sig.guest_email or "").strip().lower() != guest_email:
            sig = None
        if sig and sig.used_by_user_id is not None:
            sig = None
        if sig and not (sig.acks_read and sig.acks_temporary and sig.acks_vacate and sig.acks_electronic):
            sig = None

    user = User(
        email=guest_email,
        hashed_password=get_password_hash(data.password),
        role=target_role,
        full_name=data.full_name or None,
        phone=data.phone or None,
        state=data.permanent_state or None,
        city=data.permanent_city or None,
        country="USA",
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        msg = str(getattr(getattr(e, "orig", None), "args", [""])[0] if hasattr(e, "orig") and e.orig else str(e))
        if "email" in msg.lower() or "unique" in msg.lower():
            raise HTTPException(
                status_code=400,
                detail=same_role_already_registered_message(target_role),
            )
        raise
    if target_role == UserRole.guest:
        permanent_home = f"{data.permanent_address}, {data.permanent_city}, {data.permanent_state} {data.permanent_zip}".strip()
        profile = GuestProfile(
            user_id=user.id,
            full_legal_name=data.full_name,
            permanent_home_address=permanent_home,
            gps_checkin_acknowledgment=False,
        )
        db.add(profile)
    if target_role == UserRole.tenant and code and inv:
        # Tenant does not sign any agreement. Create TenantAssignment in the same transaction as the user.
        try:
            assert_can_record_tenant_assignment_for_invite_or_raise(db, inv, user.id)
        except HTTPException:
            db.rollback()
            raise
        ta = TenantAssignment(
            unit_id=inv.unit_id,
            user_id=user.id,
            start_date=inv.stay_start_date,
            end_date=inv.stay_end_date,
            invited_by_user_id=getattr(inv, "invited_by_user_id", None),
        )
        db.add(ta)
        db.flush()
        inv.status = "accepted"
        inv.token_state = "BURNED"
        create_ledger_event(
            db,
            ACTION_TENANT_ACCEPTED,
            target_object_type="TenantAssignment",
            target_object_id=ta.id,
            property_id=inv.property_id,
            unit_id=inv.unit_id,
            invitation_id=inv.id,
            actor_user_id=user.id,
            meta={"invitation_code": code, "unit_id": inv.unit_id, "tenant_email": user.email},
        )
        try:
            create_alert_for_owner_and_managers(
                db,
                inv.property_id,
                "tenant_accepted",
                "Tenant accepted invitation",
                "A tenant accepted the invitation and is now assigned to the unit.",
                severity="info",
                invitation_id=inv.id,
            )
        except Exception as e:
            logging.getLogger(__name__).warning("Failed to create tenant_accepted dashboard alert (register): %s", e)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        msg = str(getattr(getattr(e, "orig", None), "args", [""])[0] if hasattr(e, "orig") and e.orig else str(e))
        if "email" in msg.lower() or "unique" in msg.lower():
            raise HTTPException(
                status_code=400,
                detail=same_role_already_registered_message(target_role),
            )
        raise
    db.refresh(user)

    # Full accept path (guests only): code + valid signature -> create stay, mark inv accepted, token BURNED
    if target_role == UserRole.guest and code and inv and sig:
        duration = (inv.stay_end_date - inv.stay_start_date).days
        if duration <= 0:
            duration = 1
        from app.services.guest_stay_overlap import enforce_guest_stay_no_overlap_or_resolve

        enforce_guest_stay_no_overlap_or_resolve(db, guest_id=user.id, inv=inv)
        stay = Stay(
            guest_id=user.id,
            owner_id=inv.owner_id,
            property_id=inv.property_id,
            unit_id=getattr(inv, "unit_id", None),
            invitation_id=inv.id,
            invited_by_user_id=getattr(inv, "invited_by_user_id", None),
            stay_start_date=inv.stay_start_date,
            stay_end_date=inv.stay_end_date,
            intended_stay_duration_days=duration,
            purpose_of_stay=inv.purpose_of_stay,
            relationship_to_owner=inv.relationship_to_owner,
            region_code=inv.region_code,
            dead_mans_switch_enabled=0,  # Stay reminders turn on 2 min after guest checks in (see guest_check_in)
            dead_mans_switch_alert_email=getattr(inv, "dead_mans_switch_alert_email", 1) or 1,
            dead_mans_switch_alert_sms=getattr(inv, "dead_mans_switch_alert_sms", 0) or 0,
            dead_mans_switch_alert_dashboard=getattr(inv, "dead_mans_switch_alert_dashboard", 1) or 1,
            dead_mans_switch_alert_phone=getattr(inv, "dead_mans_switch_alert_phone", 0) or 0,
        )
        db.add(stay)
        inv.status = "accepted"
        prev_token_state = getattr(inv, "token_state", None) or "STAGED"
        inv.token_state = "BURNED"
        sig.used_by_user_id = user.id
        sig.used_at = datetime.now(timezone.utc)
        # Occupancy is set to OCCUPIED only when guest checks in (guest_check_in endpoint).
        db.commit()
        db.refresh(stay)
        # DO NOT REMOVE — legacy: Shield off when guest accepts invite (disabled CR-1a while SHIELD_MODE_ALWAYS_ON).
        prop_for_shield = db.query(Property).filter(Property.id == inv.property_id).first()
        if not SHIELD_MODE_ALWAYS_ON and prop_for_shield and getattr(prop_for_shield, "shield_mode_enabled", 0) == 1:
            prop_for_shield.shield_mode_enabled = 0
            owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop_for_shield.owner_profile_id).first()
            owner_user = db.query(User).filter(User.id == owner_profile.user_id).first() if owner_profile else None
            owner_email = (owner_user.email or "").strip() if owner_user else ""
            manager_emails = [
                (u.email or "").strip()
                for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == prop_for_shield.id).all()
                for u in [db.query(User).filter(User.id == a.user_id).first()]
                if u and (u.email or "").strip()
            ]
            property_name = (prop_for_shield.name or "").strip() or (f"{prop_for_shield.city}, {prop_for_shield.state}".strip(", ") if (prop_for_shield.city or prop_for_shield.state) else "Property")
            try:
                send_shield_mode_turned_off_notification(owner_email, manager_emails, property_name, turned_off_by="system (new guest accepted invitation)")
            except Exception:
                pass
            ip_shield = request.client.host if request.client else None
            ua_shield = (request.headers.get("user-agent") or "").strip() or None
            create_ledger_event(
                db,
                ACTION_SHIELD_MODE_OFF,
                target_object_type="Property",
                target_object_id=prop_for_shield.id,
                property_id=prop_for_shield.id,
                stay_id=stay.id,
                invitation_id=inv.id,
                actor_user_id=user.id,
                meta={
                    "property_name": property_name,
                    "message": f"Shield Mode turned off for {property_name} (new guest accepted invitation).",
                    "reason": "invitation_accepted",
                },
                ip_address=ip_shield,
                user_agent=ua_shield,
            )
            db.add(prop_for_shield)
        ip = request.client.host if request.client else None
        ua = (request.headers.get("user-agent") or "").strip() or None
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            "Invitation accepted (stay created)",
            f"Invite ID {code} token_state {prev_token_state} -> BURNED; guest registered, stay {stay.id} created for property {inv.property_id}. Occupancy will be set when guest checks in.",
            property_id=inv.property_id,
            stay_id=stay.id,
            invitation_id=inv.id,
            actor_user_id=user.id,
            actor_email=user.email,
            ip_address=ip,
            user_agent=ua,
            meta={"invitation_code": code, "token_state_previous": prev_token_state, "token_state_new": "BURNED", "signature_id": sig.id},
        )
        create_ledger_event(
            db,
            ACTION_GUEST_INVITE_ACCEPTED,
            target_object_type="Stay",
            target_object_id=stay.id,
            property_id=inv.property_id,
            stay_id=stay.id,
            invitation_id=inv.id,
            actor_user_id=user.id,
            meta={"invitation_code": code, "token_state_previous": prev_token_state, "token_state_new": "BURNED", "signature_id": sig.id},
            ip_address=ip,
            user_agent=ua,
        )
        db.commit()
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}".strip(", ") if prop and (prop.city or prop.state) else None) or "the property"
        send_guest_welcome_email(
            user.email,
            user.full_name,
            property_name=property_name,
            stay_end_date=str(inv.stay_end_date),
        )
        if getattr(inv, "invited_by_user_id", None):
            invited_by_user = db.query(User).filter(User.id == inv.invited_by_user_id).first()
            if invited_by_user and invited_by_user.role == UserRole.tenant and (invited_by_user.email or "").strip():
                guest_name = (user.full_name or "").strip() or (user.email or "").strip() or "Unknown invitee"
                try:
                    send_tenant_guest_accepted_invite(invited_by_user.email.strip(), guest_name, property_name)
                except Exception:
                    pass
        try:
            create_alert_for_owner_and_managers(
                db,
                inv.property_id,
                "invitation_accepted",
                "Guest accepted invitation",
                f"A guest accepted the invitation and a stay was created for {property_name}.",
                severity="info",
                stay_id=stay.id,
                invitation_id=inv.id,
            )
            if getattr(inv, "invited_by_user_id", None):
                invited_by = db.query(User).filter(User.id == inv.invited_by_user_id).first()
                if invited_by and invited_by.role == UserRole.tenant:
                    create_alert_for_user(
                        db,
                        inv.invited_by_user_id,
                        "invitation_accepted",
                        "Guest accepted your invitation",
                        f"A guest accepted your invitation for {property_name}.",
                        severity="info",
                        property_id=inv.property_id,
                        stay_id=stay.id,
                        invitation_id=inv.id,
                    )
        except Exception as e:
            logging.getLogger(__name__).warning("Failed to create invitation_accepted dashboard alerts (register): %s", e)
        db.commit()
    elif target_role == UserRole.guest and code and inv:
        # Invite provided but not signed: add to pending so dashboard shows agreement modal
        pending = GuestPendingInvite(user_id=user.id, invitation_id=inv.id)
        db.add(pending)
        db.commit()

    # Send welcome email when guest/tenant did not get the stay-specific welcome
    if target_role == UserRole.tenant or not (code and inv and sig):
        send_guest_signup_welcome_email(user.email, user.full_name)

    _trigger_guest_approaching_end_notifications_after_auth(db, user, request)
    token = create_access_token(user.id, user.email, user.role)
    return Token(access_token=token, user=_user_to_response(user, db))


@router.post("/accept-invite")
def accept_invite(
    request: Request,
    data: AcceptInvite,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest_or_tenant),
):
    """Accept an invitation as an existing guest or tenant: create Stay and mark invitation accepted."""
    code = (data.invitation_code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Invitation code is required")
    inv = db.query(Invitation).filter(Invitation.invitation_code == code).first()
    if not inv:
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Accept invite: invalid or expired invitation code",
            f"Accept-invite attempted with invalid or expired code: {code}.",
            property_id=None,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "").strip() or None,
            meta={"invitation_code_attempted": code},
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired invitation code")

    inv_kind_raw = (getattr(inv, "invitation_kind", None) or "").strip().lower()
    is_tenant_invite = is_property_invited_tenant_signup_kind(inv_kind_raw)
    from app.models.demo_account import is_demo_user_id
    demo_session_user = is_demo_user_id(db, current_user.id)
    demo_originated_invite = is_demo_user_id(db, getattr(inv, "invited_by_user_id", None) or getattr(inv, "owner_id", None))

    if is_tenant_invite:
        if inv.status not in ("pending", "ongoing", "accepted"):
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Accept invite: tenant invitation not open",
                f"Accept-invite for tenant code {code}: status={inv.status}.",
                property_id=getattr(inv, "property_id", None),
                invitation_id=inv.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code": code},
            )
            db.commit()
            raise HTTPException(status_code=400, detail="Invalid or expired invitation code")
    else:
        # Check for expiration after 72 hours for guest invitations
        from app.services.invitation_cleanup import get_invitation_expire_cutoff
        threshold = get_invitation_expire_cutoff()
        if inv.status == "expired" or (
            inv.status == "pending"
            and inv.created_at is not None
            and inv.created_at < threshold
        ):
            # Check if there is a pending dropbox sign request before failing
            has_pending_dropbox = db.query(AgreementSignature).filter(
                AgreementSignature.invitation_code == code,
                AgreementSignature.dropbox_sign_request_id.isnot(None),
                AgreementSignature.signed_pdf_bytes.is_(None)
            ).first() is not None
            has_completed_signature = db.query(AgreementSignature).filter(
                AgreementSignature.invitation_code == code,
                AgreementSignature.signed_pdf_bytes.isnot(None),
            ).first() is not None
            if not has_pending_dropbox and not has_completed_signature:
                create_log(
                    db,
                    CATEGORY_FAILED_ATTEMPT,
                    "Accept invite: guest invitation expired",
                    f"Accept-invite for guest code {code}: status={inv.status}, created_at={inv.created_at}.",
                    property_id=getattr(inv, "property_id", None),
                    invitation_id=inv.id,
                    actor_user_id=current_user.id,
                    actor_email=current_user.email,
                    ip_address=request.client.host if request.client else None,
                    user_agent=(request.headers.get("user-agent") or "").strip() or None,
                    meta={"invitation_code": code},
                )
                db.commit()
                raise HTTPException(status_code=400, detail="This invite has expired. Please contact your host to request a new one.")

        # Recovery: legacy path marked invitation accepted/BURNED when Dropbox returned PDF but never created Stay.
        if not is_tenant_invite and inv.status == "accepted" and (getattr(inv, "token_state", None) or "").upper() == "BURNED":
            if db.query(Stay).filter(Stay.invitation_id == inv.id).first() is None:
                inv.status = "pending"
                if hasattr(inv, "token_state"):
                    inv.token_state = "STAGED"
                db.add(inv)
                db.flush()

        if inv.status not in ("pending", "ongoing", "accepted"):
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Accept invite: guest invitation not open",
                f"Accept-invite for guest code {code}: status={inv.status}.",
                property_id=getattr(inv, "property_id", None),
                invitation_id=inv.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code": code},
            )
            db.commit()
            raise HTTPException(status_code=400, detail="Invalid or expired invitation code")
        if inv.status in ("pending", "ongoing", "accepted") and (getattr(inv, "token_state", None) or "") == "BURNED":
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Accept invite: guest invitation already consumed",
                f"Accept-invite for guest code {code}: token_state=BURNED with status {inv.status}.",
                property_id=getattr(inv, "property_id", None),
                invitation_id=inv.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code": code},
            )
            db.commit()
            raise HTTPException(status_code=400, detail="Invalid or expired invitation code")

    # Reject immediately if invite type doesn't match user role
    if is_tenant_invite and current_user.role == UserRole.guest:
        raise HTTPException(
            status_code=400,
            detail="This invitation is for a tenant. Please sign in as a tenant to accept it.",
        )
    if not is_tenant_invite and current_user.role == UserRole.tenant:
        raise HTTPException(
            status_code=400,
            detail="This invitation is for a guest. Please sign in as a guest to accept it.",
        )

    # Guest stays: invitation must include the authorized email; tenant invites may omit it (legacy CSV).
    # Demo exception: for demo-originated invites accepted by a demo account, allow bypassing the email lock.
    inv_guest_email = (getattr(inv, "guest_email", None) or "").strip().lower()
    if not is_tenant_invite:
        if demo_session_user and demo_originated_invite:
            inv_guest_email = (current_user.email or "").strip().lower()
        if not inv_guest_email:
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Accept invite: guest invitation missing guest_email",
                f"User {current_user.email} attempted to accept guest invitation {code} with no guest_email on record.",
                property_id=inv.property_id,
                invitation_id=inv.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code": code},
            )
            db.commit()
            raise HTTPException(
                status_code=400,
                detail="This invitation link is incomplete. Ask your host to send a new invitation that includes your email address.",
            )
        if (current_user.email or "").strip().lower() != inv_guest_email:
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Accept invite: email mismatch",
                f"User {current_user.email} attempted to accept invitation {code} intended for {inv.guest_email}.",
                property_id=inv.property_id,
                invitation_id=inv.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code": code, "invitation_guest_email": inv.guest_email},
            )
            db.commit()
            raise HTTPException(
                status_code=403,
                detail="This invitation was sent to a different email address. You cannot accept an invitation intended for someone else.",
            )
    elif inv_guest_email and (current_user.email or "").strip().lower() != inv_guest_email:
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Accept invite: email mismatch",
            f"User {current_user.email} attempted to accept invitation {code} intended for {inv.guest_email}.",
            property_id=inv.property_id,
            invitation_id=inv.id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "").strip() or None,
            meta={"invitation_code": code, "invitation_guest_email": inv.guest_email},
        )
        db.commit()
        raise HTTPException(
            status_code=403,
            detail="This invitation was sent to a different email address. You cannot accept an invitation intended for someone else.",
        )

    sig = None
    if is_tenant_invite:
        # Tenant invitations don't require an agreement signature
        pass
    else:
        # Demo exception: auto-create signature for demo-originated invites accepted by demo accounts.
        # Use the same agreement body, document id/title/hash, and PDF pipeline as production typed signing.
        if demo_session_user and demo_originated_invite and not (data.agreement_signature_id and data.agreement_signature_id > 0):
            guest_fn = (current_user.full_name or "").strip() or (current_user.email or "").strip() or "Demo Guest"
            doc = build_invitation_agreement(db, invitation_code=code, guest_full_name=guest_fn)
            if not doc:
                create_log(
                    db,
                    CATEGORY_FAILED_ATTEMPT,
                    "Accept invite (demo): agreement build failed",
                    f"Could not build invitation agreement for demo accept-invite code {code}.",
                    property_id=getattr(inv, "property_id", None),
                    invitation_id=inv.id,
                    actor_user_id=current_user.id,
                    actor_email=current_user.email,
                    ip_address=request.client.host if request.client else None,
                    user_agent=(request.headers.get("user-agent") or "").strip() or None,
                    meta={"invitation_code": code},
                )
                db.commit()
                raise HTTPException(
                    status_code=400,
                    detail="Agreement could not be generated for this invitation. Please try again.",
                )
            ip = request.client.host if request.client else None
            ua = (request.headers.get("user-agent") or "").strip() or None
            sig = AgreementSignature(
                invitation_code=code,
                region_code=doc.region_code,
                guest_email=(current_user.email or "").strip().lower(),
                guest_full_name=guest_fn,
                typed_signature=guest_fn,
                signature_method="typed",
                acks_read=True,
                acks_temporary=True,
                acks_vacate=True,
                acks_electronic=True,
                document_id=doc.document_id,
                document_title=doc.title,
                document_hash=doc.document_hash,
                document_content=doc.content,
                ip_address=ip,
                user_agent=ua[:400] if ua else None,
                used_by_user_id=current_user.id,
                used_at=datetime.now(timezone.utc),
            )
            db.add(sig)
            db.flush()
            date_str = sig.signed_at.strftime("%Y-%m-%d") if sig.signed_at else ""
            content_with_sig = fill_guest_signature_in_content(
                doc.content, sig.typed_signature, date_str, sig.ip_address
            )
            try:
                sig.signed_pdf_bytes = agreement_content_to_pdf(doc.title, content_with_sig)
            except Exception:
                logging.getLogger(__name__).warning(
                    "Demo accept-invite: agreement_content_to_pdf failed for invitation %s", code, exc_info=True
                )
            db.flush()
        else:
            sig = db.query(AgreementSignature).filter(AgreementSignature.id == data.agreement_signature_id).first()

        if not sig:
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Accept invite: missing or invalid signature",
                f"Accept-invite for {code} with invalid or missing agreement_signature_id.",
                property_id=inv.property_id,
                invitation_id=inv.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code": code, "signature_id_attempted": data.agreement_signature_id},
            )
            db.commit()
            raise HTTPException(status_code=400, detail="Agreement must be signed before accepting invitation")
        if (sig.invitation_code or "").strip().upper() != code:
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Accept invite: signature does not match invitation",
                f"Accept-invite for {code}: signature {sig.id} does not match invitation.",
                property_id=inv.property_id,
                invitation_id=inv.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code": code, "signature_id": sig.id},
            )
            db.commit()
            raise HTTPException(status_code=400, detail="Agreement signature does not match this invitation")
        if (sig.guest_email or "").strip().lower() != (current_user.email or "").strip().lower():
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Accept invite: signature email does not match",
                f"Accept-invite for {code}: signature email does not match current user.",
                property_id=inv.property_id,
                invitation_id=inv.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code": code},
            )
            db.commit()
            raise HTTPException(status_code=400, detail="Agreement signature email does not match current user")
        if sig.used_by_user_id is not None and sig.used_by_user_id != current_user.id:
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Accept invite: signature already used",
                f"Accept-invite for {code}: signature {sig.id} already used by another user.",
                property_id=inv.property_id,
                invitation_id=inv.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code": code, "signature_id": sig.id},
            )
            db.commit()
            raise HTTPException(status_code=400, detail="Agreement signature has already been used")
        if getattr(sig, "dropbox_sign_request_id", None) and not getattr(sig, "signed_pdf_bytes", None):
            pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
            if pdf_bytes:
                sig.signed_pdf_bytes = pdf_bytes
                emit_invitation_agreement_signed_if_dropbox_complete(
                    db,
                    sig,
                    ip_address=request.client.host if request.client else None,
                    user_agent=(request.headers.get("user-agent") or "").strip() or None,
                )
                db.commit()
            else:
                create_log(
                    db,
                    CATEGORY_FAILED_ATTEMPT,
                    "Accept invite: Dropbox signing not complete",
                    f"Accept-invite for {code}: signature {sig.id} sent to Dropbox but not yet signed.",
                    property_id=inv.property_id,
                    invitation_id=inv.id,
                    actor_user_id=current_user.id,
                    actor_email=current_user.email,
                    ip_address=request.client.host if request.client else None,
                    user_agent=(request.headers.get("user-agent") or "").strip() or None,
                    meta={"invitation_code": code, "signature_id": sig.id},
                )
                db.commit()
                raise HTTPException(
                    status_code=400,
                    detail="Please complete signing in Dropbox before accepting the invitation.",
                )
        if not (sig.acks_read and sig.acks_temporary and sig.acks_vacate and sig.acks_electronic):
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Accept invite: not all acknowledgments accepted",
                f"Accept-invite for {code}: agreement acknowledgments incomplete.",
                property_id=inv.property_id,
                invitation_id=inv.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code": code},
            )
            db.commit()
            raise HTTPException(status_code=400, detail="All agreement acknowledgments must be accepted")

    # Idempotent: if this invite was already accepted by this user (stay exists), return success without creating duplicate.
    # Still clean up any leftover GuestPendingInvite and mark the signature as used so the dashboard
    # does not keep triggering accept_invite in an infinite loop.
    existing_stay = (
        db.query(Stay)
        .filter(Stay.guest_id == current_user.id, Stay.invitation_id == inv.id)
        .first()
    )
    if existing_stay:
        if sig and sig.used_by_user_id is None:
            sig.used_by_user_id = current_user.id
            sig.used_at = datetime.now(timezone.utc)
        inv.status = "accepted"
        inv.token_state = "BURNED"
        db.query(GuestPendingInvite).filter(
            GuestPendingInvite.user_id == current_user.id,
            GuestPendingInvite.invitation_id == inv.id,
        ).delete(synchronize_session="fetch")
        db.commit()
        return {"status": "success", "message": "Invitation already accepted."}

    inv_kind = (getattr(inv, "invitation_kind", None) or "").strip().lower()
    if is_property_invited_tenant_signup_kind(inv_kind) and current_user.role == UserRole.tenant:
        if is_tenant_lease_extension_kind(inv_kind):
            ta_ext = find_tenant_assignment_for_lease_extension_accept(db, current_user.id, inv)
            if not ta_ext:
                create_log(
                    db,
                    CATEGORY_FAILED_ATTEMPT,
                    "Accept invite: lease extension could not be matched to assignment",
                    f"User {current_user.email} could not match extension invite {code} to a tenant assignment.",
                    property_id=getattr(inv, "property_id", None),
                    invitation_id=inv.id,
                    actor_user_id=current_user.id,
                    actor_email=current_user.email,
                    ip_address=request.client.host if request.client else None,
                    user_agent=(request.headers.get("user-agent") or "").strip() or None,
                    meta={"invitation_code": code},
                )
                db.commit()
                raise HTTPException(
                    status_code=400,
                    detail="We could not match this offer to your current lease. Ask the property owner to send a new lease extension.",
                )
            new_end = inv.stay_end_date
            if ta_ext.end_date is not None:
                if new_end <= ta_ext.end_date:
                    raise HTTPException(
                        status_code=400,
                        detail="This extension is out of date compared to your current lease. Ask the owner for an updated offer.",
                    )
            elif new_end <= ta_ext.start_date:
                raise HTTPException(status_code=400, detail="Invalid lease extension end date.")
            assert_tenant_lease_extension_no_other_occupant_conflict(db, ta_ext, new_end)
            prior_invs = list_invitations_matching_tenant_assignment_lease(db, ta_ext)
            ta_ext.end_date = new_end
            for p in prior_invs:
                p.stay_end_date = new_end
            inv.status = "accepted"
            prev_token_state = getattr(inv, "token_state", None) or "STAGED"
            inv.token_state = "BURNED"
            db.add(inv)
            if sig and sig.used_by_user_id is None:
                sig.used_by_user_id = current_user.id
                sig.used_at = datetime.now(timezone.utc)
            db.query(GuestPendingInvite).filter(
                GuestPendingInvite.user_id == current_user.id,
                GuestPendingInvite.invitation_id == inv.id,
            ).delete(synchronize_session="fetch")
            try:
                create_alert_for_owner_and_managers(
                    db,
                    inv.property_id,
                    "tenant_accepted",
                    "Tenant accepted lease extension",
                    "A tenant accepted a lease extension; the existing assignment end date was updated.",
                    severity="info",
                    invitation_id=inv.id,
                )
            except Exception as e:
                logging.getLogger(__name__).warning("Failed to create lease extension dashboard alert: %s", e)
            ip = request.client.host if request.client else None
            ua = (request.headers.get("user-agent") or "").strip() or None
            create_log(
                db,
                CATEGORY_STATUS_CHANGE,
                "Tenant lease extension accepted",
                f"Invite ID {code} BURNED; TenantAssignment {ta_ext.id} end date -> {new_end.isoformat()}.",
                property_id=inv.property_id,
                stay_id=None,
                invitation_id=inv.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=ip,
                user_agent=ua,
                meta={
                    "invitation_code": code,
                    "tenant_assignment_id": ta_ext.id,
                    "lease_end_date": new_end.isoformat(),
                },
            )
            create_ledger_event(
                db,
                ACTION_TENANT_LEASE_EXTENSION_ACCEPTED,
                target_object_type="TenantAssignment",
                target_object_id=ta_ext.id,
                property_id=inv.property_id,
                unit_id=inv.unit_id,
                stay_id=None,
                invitation_id=inv.id,
                actor_user_id=current_user.id,
                meta={
                    "invitation_code": code,
                    "tenant_assignment_id": ta_ext.id,
                    "lease_end_date": new_end.isoformat(),
                    "tenant_email": current_user.email,
                },
                ip_address=ip,
                user_agent=ua,
            )
            db.commit()
            return {"status": "success", "message": "Lease extension accepted."}

        # Tenant accepting a tenant invitation: create TenantAssignment (no Stay)
        matching_ta = find_tenant_assignment_matching_invitation(db, current_user.id, inv)
        if matching_ta:
            if sig and sig.used_by_user_id is None:
                sig.used_by_user_id = current_user.id
                sig.used_at = datetime.now(timezone.utc)
            inv.status = "accepted"
            inv.token_state = "BURNED"
            db.query(GuestPendingInvite).filter(
                GuestPendingInvite.user_id == current_user.id,
                GuestPendingInvite.invitation_id == inv.id,
            ).delete(synchronize_session="fetch")
            db.commit()
            return {"status": "success", "message": "Invitation already accepted."}
        assert_can_record_tenant_assignment_for_invite_or_raise(db, inv, current_user.id)
        ta = TenantAssignment(
            unit_id=inv.unit_id,
            user_id=current_user.id,
            start_date=inv.stay_start_date,
            end_date=inv.stay_end_date,
            invited_by_user_id=getattr(inv, "invited_by_user_id", None),
        )
        db.add(ta)
        db.flush()
        inv.status = "accepted"
        prev_token_state = getattr(inv, "token_state", None) or "STAGED"
        inv.token_state = "BURNED"
        db.add(inv)
        if sig and sig.used_by_user_id is None:
            sig.used_by_user_id = current_user.id
            sig.used_at = datetime.now(timezone.utc)
        db.query(GuestPendingInvite).filter(
            GuestPendingInvite.user_id == current_user.id,
            GuestPendingInvite.invitation_id == inv.id,
        ).delete(synchronize_session="fetch")
        try:
            create_alert_for_owner_and_managers(
                db,
                inv.property_id,
                "tenant_accepted",
                "Tenant accepted invitation",
                "A tenant accepted the invitation and is now assigned to the unit.",
                severity="info",
                invitation_id=inv.id,
            )
        except Exception as e:
            logging.getLogger(__name__).warning("Failed to create tenant_accepted dashboard alert: %s", e)
        ip = request.client.host if request.client else None
        ua = (request.headers.get("user-agent") or "").strip() or None
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            "Tenant invitation accepted",
            f"Invite ID {code} token_state {prev_token_state} -> BURNED; TenantAssignment {ta.id} created for unit {inv.unit_id}.",
            property_id=inv.property_id,
            stay_id=None,
            invitation_id=inv.id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=ip,
            user_agent=ua,
            meta={"invitation_code": code, "token_state_previous": prev_token_state, "token_state_new": "BURNED", "signature_id": sig.id if sig else None, "tenant_assignment_id": ta.id},
        )
        create_ledger_event(
            db,
            ACTION_TENANT_ACCEPTED,
            target_object_type="TenantAssignment",
            target_object_id=ta.id,
            property_id=inv.property_id,
            unit_id=inv.unit_id,
            stay_id=None,
            invitation_id=inv.id,
            actor_user_id=current_user.id,
            meta={"invitation_code": code, "token_state_previous": prev_token_state, "token_state_new": "BURNED", "signature_id": sig.id if sig else None, "tenant_email": current_user.email},
            ip_address=ip,
            user_agent=ua,
        )
        db.flush()
        db.commit()
        return {"status": "success", "message": "Invitation accepted"}

    from app.services.guest_stay_overlap import enforce_guest_stay_no_overlap_or_resolve

    enforce_guest_stay_no_overlap_or_resolve(db, guest_id=current_user.id, inv=inv)

    duration = (inv.stay_end_date - inv.stay_start_date).days
    if duration <= 0:
        duration = 1
    inv_dms = getattr(inv, "dead_mans_switch_enabled", 0) or 0
    # Stay reminders are always off at stay creation; they turn on 2 min after guest checks in (see guest_check_in)
    stay = Stay(
        guest_id=current_user.id,
        owner_id=inv.owner_id,
        property_id=inv.property_id,
        unit_id=getattr(inv, "unit_id", None),
        invitation_id=inv.id,
        invited_by_user_id=getattr(inv, "invited_by_user_id", None),
        stay_start_date=inv.stay_start_date,
        stay_end_date=inv.stay_end_date,
        intended_stay_duration_days=duration,
        purpose_of_stay=inv.purpose_of_stay,
        relationship_to_owner=inv.relationship_to_owner,
        region_code=inv.region_code,
        dead_mans_switch_enabled=0,
        dead_mans_switch_alert_email=getattr(inv, "dead_mans_switch_alert_email", 1) or 1,
        dead_mans_switch_alert_sms=getattr(inv, "dead_mans_switch_alert_sms", 0) or 0,
        dead_mans_switch_alert_dashboard=getattr(inv, "dead_mans_switch_alert_dashboard", 1) or 1,
        dead_mans_switch_alert_phone=getattr(inv, "dead_mans_switch_alert_phone", 0) or 0,
    )
    db.add(stay)
    inv.status = "accepted"
    prev_token_state = getattr(inv, "token_state", None) or "STAGED"
    inv.token_state = "BURNED"
    if sig and sig.used_by_user_id is None:
        sig.used_by_user_id = current_user.id
        sig.used_at = datetime.now(timezone.utc)
    db.query(GuestPendingInvite).filter(
        GuestPendingInvite.user_id == current_user.id,
        GuestPendingInvite.invitation_id == inv.id,
    ).delete(synchronize_session="fetch")
    db.commit()
    db.refresh(stay)
    # DO NOT REMOVE — legacy: Shield off when guest accepts invite (disabled CR-1a while SHIELD_MODE_ALWAYS_ON).
    _prop = db.query(Property).filter(Property.id == inv.property_id).first()
    if not SHIELD_MODE_ALWAYS_ON and _prop and getattr(_prop, "shield_mode_enabled", 0) == 1:
        _prop.shield_mode_enabled = 0
        owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == _prop.owner_profile_id).first()
        owner_user = db.query(User).filter(User.id == owner_profile.user_id).first() if owner_profile else None
        owner_email = (owner_user.email or "").strip() if owner_user else ""
        manager_emails = [
            (u.email or "").strip()
            for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == _prop.id).all()
            for u in [db.query(User).filter(User.id == a.user_id).first()]
            if u and (u.email or "").strip()
        ]
        property_name = (_prop.name or "").strip() or (f"{_prop.city}, {_prop.state}".strip(", ") if (_prop.city or _prop.state) else "Property")
        try:
            send_shield_mode_turned_off_notification(owner_email, manager_emails, property_name, turned_off_by="system (new guest accepted invitation)")
        except Exception:
            pass
        ip_shield = request.client.host if request.client else None
        ua_shield = (request.headers.get("user-agent") or "").strip() or None
        create_ledger_event(
            db,
            ACTION_SHIELD_MODE_OFF,
            target_object_type="Property",
            target_object_id=_prop.id,
            property_id=_prop.id,
            stay_id=stay.id,
            invitation_id=inv.id,
            actor_user_id=current_user.id,
            meta={
                "property_name": property_name,
                "message": f"Shield Mode turned off for {property_name} (new guest accepted invitation).",
                "reason": "invitation_accepted",
            },
            ip_address=ip_shield,
            user_agent=ua_shield,
        )
        db.add(_prop)
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Invitation accepted",
        f"Invite ID {code} token_state {prev_token_state} -> BURNED; stay {stay.id} created for property {inv.property_id}. Occupancy will be set when guest checks in.",
        property_id=inv.property_id,
        stay_id=stay.id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"invitation_code": code, "token_state_previous": prev_token_state, "token_state_new": "BURNED", "signature_id": sig.id if sig else None},
    )
    create_ledger_event(
        db,
        ACTION_GUEST_INVITE_ACCEPTED,
        target_object_type="Stay",
        target_object_id=stay.id,
        property_id=inv.property_id,
        stay_id=stay.id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        meta={"invitation_code": code, "token_state_previous": prev_token_state, "token_state_new": "BURNED", "signature_id": sig.id if sig else None},
        ip_address=ip,
        user_agent=ua,
    )
    _prop_for_alert = db.query(Property).filter(Property.id == inv.property_id).first()
    _property_name = "Property"
    if _prop_for_alert:
        _property_name = (_prop_for_alert.name or "").strip() or (f"{getattr(_prop_for_alert, 'city', '')}, {getattr(_prop_for_alert, 'state', '')}".strip(", ") if (getattr(_prop_for_alert, "city", None) or getattr(_prop_for_alert, "state", None)) else "") or "Property"
    try:
        create_alert_for_owner_and_managers(
            db,
            inv.property_id,
            "invitation_accepted",
            "Guest accepted invitation",
            f"A guest accepted the invitation and a stay was created for {_property_name}.",
            severity="info",
            stay_id=stay.id,
            invitation_id=inv.id,
        )
        if getattr(inv, "invited_by_user_id", None):
            invited_by = db.query(User).filter(User.id == inv.invited_by_user_id).first()
            if invited_by and invited_by.role == UserRole.tenant:
                create_alert_for_user(
                    db,
                    inv.invited_by_user_id,
                    "invitation_accepted",
                    "Guest accepted your invitation",
                    f"A guest accepted your invitation for {_property_name}.",
                    severity="info",
                    property_id=inv.property_id,
                    stay_id=stay.id,
                    invitation_id=inv.id,
                )
    except Exception as e:
        logging.getLogger(__name__).warning("Failed to create invitation_accepted dashboard alerts (accept-invite): %s", e)
    db.commit()
    _prop = db.query(Property).filter(Property.id == inv.property_id).first()
    if _prop:
        try:
            profile = db.query(OwnerProfile).filter(OwnerProfile.id == _prop.owner_profile_id).first()
            if profile:
                sync_subscription_quantities(db, profile)
        except Exception:
            pass
    prop = db.query(Property).filter(Property.id == inv.property_id).first()
    property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}".strip(", ") if prop and (prop.city or prop.state) else None) or "Property"
    send_guest_stay_added_email(
        current_user.email,
        current_user.full_name,
        property_name=property_name,
        stay_end_date=str(inv.stay_end_date),
    )
    if getattr(inv, "invited_by_user_id", None):
        invited_by_user = db.query(User).filter(User.id == inv.invited_by_user_id).first()
        if invited_by_user and invited_by_user.role == UserRole.tenant and (invited_by_user.email or "").strip():
            guest_name = (current_user.full_name or "").strip() or (current_user.email or "").strip() or "Unknown invitee"
            try:
                send_tenant_guest_accepted_invite(invited_by_user.email.strip(), guest_name, property_name)
            except Exception:
                pass
    # Stay reminders turn on 2 min after guest checks in (see guest_check_in), not at accept
    return {"status": "success", "message": "Invitation accepted"}
