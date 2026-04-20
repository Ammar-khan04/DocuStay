"""Module A: Auth schemas."""
import enum
import re
from typing import Literal, Optional
from pydantic import BaseModel, EmailStr, model_validator, field_validator
from app.models.user import UserRole, OwnerType

PHONE_MIN_DIGITS = 10
PHONE_MAX_DIGITS = 15


def _normalize_phone(value: str | None) -> str:
    if value is None:
        return ""
    s = value.strip()
    digits = re.sub(r"\D", "", s)
    return digits


def _validate_phone_digits(phone: str) -> None:
    digits = _normalize_phone(phone)
    if not digits:
        raise ValueError("Phone number is required.")
    if len(digits) < PHONE_MIN_DIGITS:
        raise ValueError(f"Phone number must have at least {PHONE_MIN_DIGITS} digits (e.g. 5551234567 or +1 555 123 4567).")
    if len(digits) > PHONE_MAX_DIGITS:
        raise ValueError(f"Phone number cannot exceed {PHONE_MAX_DIGITS} digits.")


class AccountType(str, enum.Enum):
    individual = "individual"


class UserCreate(BaseModel):
    account_type: AccountType | None = None  # individual (only)
    first_name: str | None = None
    last_name: str | None = None
    full_name: str
    email: EmailStr
    phone: str = ""
    password: str
    confirm_password: str = ""
    country: str = "USA"
    state: str
    city: str
    terms_agreed: bool = False
    privacy_agreed: bool = False
    role: UserRole = UserRole.owner
    poa_signature_id: int | None = None  # optional; owner signs POA after identity verification
    owner_type: OwnerType | None = None  # Owner of Record vs Authorized Agent (property manager)

    @field_validator("phone")
    @classmethod
    def phone_valid(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            return s
        digits = _normalize_phone(s)
        if len(digits) < PHONE_MIN_DIGITS:
            raise ValueError(f"Phone number must have at least {PHONE_MIN_DIGITS} digits (e.g. 5551234567 or +1 555 123 4567).")
        if len(digits) > PHONE_MAX_DIGITS:
            raise ValueError(f"Phone number cannot exceed {PHONE_MAX_DIGITS} digits.")
        return s

    @model_validator(mode="after")
    def passwords_match_and_agreed(self):
        if self.confirm_password != self.password:
            raise ValueError("Passwords do not match")
        if not self.terms_agreed or not self.privacy_agreed:
            raise ValueError("You must agree to Terms and Privacy Policy")
        return self

    @model_validator(mode="after")
    def account_type_fields(self):
        """Validate individual owner fields (only for owner signup)."""
        if self.role != UserRole.owner:
            return self
        at = self.account_type or AccountType.individual
        if at == AccountType.individual:
            if not (self.first_name or "").strip():
                raise ValueError("First name is required.")
            if not (self.last_name or "").strip():
                raise ValueError("Last name is required.")
        return self

    @model_validator(mode="after")
    def owner_phone_required(self):
        """Require phone with 10+ digits for owner signup."""
        if self.role != UserRole.owner:
            return self
        _validate_phone_digits(self.phone or "")
        return self


class UserLogin(BaseModel):
    email: EmailStr
    password: str
    role: UserRole | None = None  # Required to distinguish owner vs guest when same email has both
    # Local calendar YYYY-MM-DD (browser); preferred over X-Client-Calendar-Date when proxies strip headers
    client_calendar_date: str | None = None


class UserResponse(BaseModel):
    id: int
    email: str
    role: UserRole
    full_name: str | None = None
    phone: str | None = None
    state: str | None = None
    city: str | None = None
    identity_verified: bool = False
    poa_linked: bool = False  # owner has linked Master POA signature
    is_demo: bool = False

    class Config:
        from_attributes = True


class TokenPayload(BaseModel):
    sub: int
    email: str
    role: UserRole


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class DemoLoginRequest(BaseModel):
    role: UserRole
    email: EmailStr | None = None
    client_calendar_date: str | None = None


class GuestRegister(BaseModel):
    """Guest or tenant registration; invitation_code optional for guests. Same form, role sets user type."""
    role: Literal["guest", "tenant"] = "guest"
    invitation_id: str = ""
    invitation_code: str = ""
    full_name: str
    email: EmailStr
    phone: str = ""
    password: str
    confirm_password: str = ""
    permanent_address: str
    permanent_city: str
    permanent_state: str
    permanent_zip: str
    terms_agreed: bool = False
    privacy_agreed: bool = False
    guest_status_acknowledged: bool = False
    no_tenancy_acknowledged: bool = False
    vacate_acknowledged: bool = False
    agreement_signature_id: int | None = None  # optional; when set with valid invite, creates stay; otherwise invite is pending on dashboard

    @model_validator(mode="after")
    def passwords_match_and_agreed(self):
        if self.confirm_password != self.password:
            raise ValueError("Passwords do not match")
        if not self.terms_agreed or not self.privacy_agreed:
            raise ValueError("You must agree to Terms and Privacy Policy")
        # Guest-specific acknowledgments required only for guest role. Tenant is primary resident; no guest stay language.
        if self.role == "guest" and not (
            self.guest_status_acknowledged and self.no_tenancy_acknowledged and self.vacate_acknowledged
        ):
            raise ValueError("You must acknowledge all guest and vacate terms")
        if self.role == "guest" and not (self.permanent_address and self.permanent_city and self.permanent_state and self.permanent_zip):
            raise ValueError("Permanent address is required for guests")
        return self


class ManagerRegister(BaseModel):
    """Property manager registration via invite link."""
    invite_token: str
    full_name: str
    email: EmailStr  # Must match invite email
    phone: str = ""
    password: str
    confirm_password: str = ""

    @field_validator("phone")
    @classmethod
    def phone_valid(cls, v: str) -> str:
        if v and v.strip():
            _validate_phone_digits(v)
        return (v or "").strip()

    @model_validator(mode="after")
    def passwords_match_and_agreed(self):
        if self.confirm_password != self.password:
            raise ValueError("Passwords do not match")
        return self


class AcceptInvite(BaseModel):
    """Accept an invitation as an existing guest (creates Stay, marks invitation accepted).
    For tenant invitations, agreement_signature_id may be None (tenants don't sign guest agreements).
    """
    invitation_code: str
    agreement_signature_id: Optional[int] = None


class VerifyEmailRequest(BaseModel):
    """Verify email with code sent after registration."""
    user_id: int
    code: str


class ResendVerificationRequest(BaseModel):
    """Request a new verification code for pending signup."""
    user_id: int


class ForgotPasswordRequest(BaseModel):
    """Request password reset email. Role identifies owner vs guest when same email has both."""
    email: EmailStr
    role: UserRole


class ResetPasswordRequest(BaseModel):
    """Set new password using token from reset email."""
    token: str
    new_password: str
    confirm_password: str = ""

    @model_validator(mode="after")
    def passwords_match(self):
        if self.confirm_password != self.new_password:
            raise ValueError("Passwords do not match")
        return self


class RegisterPendingResponse(BaseModel):
    """Response from register when email verification is required (no token yet)."""
    user_id: int
    message: str = "Check your email for the verification code."


class LinkPOARequest(BaseModel):
    """Link an existing Master POA signature to the current owner (after identity verification)."""
    poa_signature_id: int
    authorized_agent_certified: bool = False  # required True when owner_type is authorized_agent


class PendingOwnerIdentitySessionRequest(BaseModel):
    """Optional: frontend sends return_url so Stripe redirects to same origin (preserves localStorage token)."""
    return_url: str | None = None
    force_new_session: bool = False  # when True, use a new idempotency key so Stripe creates a new session (e.g. after canceled)


class PendingOwnerIdentitySessionResponse(BaseModel):
    client_secret: str
    url: str | None = None


class PendingOwnerConfirmIdentityRequest(BaseModel):
    verification_session_id: str


class PendingOwnerMeResponse(BaseModel):
    email: str
    full_name: str | None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    account_type: str | None = None


class PendingOwnerLatestIdentitySessionResponse(BaseModel):
    """Session id we stored when creating the identity session; use when Stripe redirect omits session_id in URL."""
    verification_session_id: str


class PendingOwnerIdentityRetryRequest(BaseModel):
    """Request a fresh URL to retry identity verification (same Stripe session)."""
    verification_session_id: str


class PendingOwnerIdentityRetryResponse(BaseModel):
    """Fresh Stripe Identity URL for retry, or already_verified flag."""
    url: str | None = None
    already_verified: bool = False
    message: str | None = None


class CompleteOwnerSignupRequest(BaseModel):
    poa_signature_id: int
    client_calendar_date: str | None = None
