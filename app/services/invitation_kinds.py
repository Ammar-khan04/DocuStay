"""Convention for Invitation.invitation_kind (existing column only).

- tenant: default owner/manager invite; full single-lease overlap enforcement.
- tenant_cotenant: optional “shared lease / additional occupant” from invite modal only; overlap checks skipped on create/accept.
"""

from __future__ import annotations

TENANT_INVITE_KIND = "tenant"
TENANT_COTENANT_INVITE_KIND = "tenant_cotenant"

# Invitation kinds that participate in unit lease calendar (block new standard tenant invites when overlapping).
TENANT_UNIT_LEASE_KINDS: frozenset[str] = frozenset({TENANT_INVITE_KIND, TENANT_COTENANT_INVITE_KIND})


def normalize_invitation_kind(kind: str | None) -> str:
    return (kind or "").strip().lower()


def is_property_invited_tenant_signup_kind(kind: str | None) -> bool:
    """Signup/accept flows for property-issued tenant invites (standard or co-tenant)."""
    return normalize_invitation_kind(kind) in TENANT_UNIT_LEASE_KINDS


def is_standard_tenant_invite_kind(kind: str | None) -> bool:
    """Single-lease lane; same as historical ``invitation_kind == 'tenant'``."""
    return normalize_invitation_kind(kind) == TENANT_INVITE_KIND


def bypasses_unit_lease_overlap_for_kind(kind: str | None) -> bool:
    """True only for co-tenant / shared-lease invites."""
    return normalize_invitation_kind(kind) == TENANT_COTENANT_INVITE_KIND
