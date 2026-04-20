"""Convention for Invitation.invitation_kind (existing column only).

- tenant: default owner/manager invite; full single-lease overlap enforcement.
- tenant_cotenant: optional “shared lease / additional occupant” from invite modal only; overlap checks skipped on create/accept.
"""

from __future__ import annotations

TENANT_INVITE_KIND = "tenant"
TENANT_COTENANT_INVITE_KIND = "tenant_cotenant"
# Existing tenant accepts in-app; same TenantAssignment end date is updated (no new assignment row).
# Stored value must fit invitations.invitation_kind VARCHAR(20) (e.g. not "tenant_lease_extension").
TENANT_LEASE_EXTENSION_KIND = "tenant_lease_ext"

# Invitation kinds that participate in unit lease calendar (block new standard tenant invites when overlapping).
TENANT_UNIT_LEASE_KINDS: frozenset[str] = frozenset(
    {TENANT_INVITE_KIND, TENANT_COTENANT_INVITE_KIND, TENANT_LEASE_EXTENSION_KIND}
)


def normalize_invitation_kind(kind: str | None) -> str:
    return (kind or "").strip().lower()


def is_property_invited_tenant_signup_kind(kind: str | None) -> bool:
    """Signup/accept flows for property-issued tenant invites (standard, co-tenant, or lease extension)."""
    return normalize_invitation_kind(kind) in TENANT_UNIT_LEASE_KINDS


def is_tenant_lease_extension_kind(kind: str | None) -> bool:
    k = normalize_invitation_kind(kind)
    # Legacy string exceeded VARCHAR(20) and could not be inserted; still recognize if present.
    return k == TENANT_LEASE_EXTENSION_KIND or k == "tenant_lease_extension"


def is_standard_tenant_invite_kind(kind: str | None) -> bool:
    """Single-lease lane; same as historical ``invitation_kind == 'tenant'``."""
    return normalize_invitation_kind(kind) == TENANT_INVITE_KIND


def bypasses_unit_lease_overlap_for_kind(kind: str | None) -> bool:
    """True for co-tenant invites and lease extensions (overlap handled on create/accept)."""
    k = normalize_invitation_kind(kind)
    return k in (TENANT_COTENANT_INVITE_KIND, TENANT_LEASE_EXTENSION_KIND)
