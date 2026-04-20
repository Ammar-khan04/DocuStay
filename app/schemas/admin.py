"""Admin API response schemas (read-only views)."""
from datetime import date, datetime
from pydantic import BaseModel


class AdminUserView(BaseModel):
    id: int
    email: str
    role: str
    full_name: str | None
    created_at: datetime | None

    class Config:
        from_attributes = True


class AdminAuditLogEntry(BaseModel):
    id: int
    property_id: int | None
    stay_id: int | None
    invitation_id: int | None
    category: str
    title: str
    message: str
    actor_user_id: int | None
    actor_email: str | None  # display name for UI (legacy field name)
    ip_address: str | None
    created_at: datetime
    property_name: str | None = None

    class Config:
        from_attributes = True


class AdminPropertyView(BaseModel):
    id: int
    owner_profile_id: int
    owner_email: str | None = None
    name: str | None
    street: str
    city: str
    state: str
    zip_code: str | None
    region_code: str
    occupancy_status: str | None = None
    deleted_at: datetime | None = None
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class AdminStayView(BaseModel):
    id: int
    property_id: int
    guest_id: int
    owner_id: int
    guest_email: str | None = None
    owner_email: str | None = None
    property_name: str | None = None
    stay_start_date: date
    stay_end_date: date
    region_code: str
    checked_in_at: datetime | None = None
    checked_out_at: datetime | None = None
    cancelled_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class AdminInvitationView(BaseModel):
    id: int
    invitation_code: str
    owner_id: int
    property_id: int
    owner_email: str | None = None
    property_name: str | None = None
    guest_name: str | None
    guest_email: str | None
    stay_start_date: date
    stay_end_date: date
    status: str
    token_state: str
    created_at: datetime | None = None

    class Config:
        from_attributes = True
