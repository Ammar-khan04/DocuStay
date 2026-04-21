"""Resolve audit/ledger actor role for a property (Owner vs Property manager vs Tenant vs Guest).

Used for evidence timelines where narrative ``meta.message`` must not be the sole source of
legal attribution — role is derived from ``actor_user_id`` plus property-scoped assignments.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.owner import OwnerProfile, Property
from app.models.property_manager_assignment import PropertyManagerAssignment
from app.models.tenant_assignment import TenantAssignment
from app.models.unit import Unit
from app.models.user import User, UserRole
from app.services.event_ledger import get_actor_display_name


def audit_actor_attribution(
    db: Session,
    *,
    actor_user_id: int | None,
    property_id: int | None,
) -> dict[str, str | None]:
    """
    Return machine ``role``, human ``role_label``, display ``name``, and ``email`` for the actor.

    ``role`` is one of: system, owner, property_manager, tenant, guest, admin, unknown.
    """
    if not actor_user_id:
        return {
            "role": "system",
            "role_label": "System",
            "name": "System",
            "email": None,
        }
    u = db.query(User).filter(User.id == actor_user_id).first()
    if not u:
        return {
            "role": "unknown",
            "role_label": "Unknown",
            "name": "Unknown user",
            "email": None,
        }
    email = (u.email or "").strip() or None
    name = get_actor_display_name(db, actor_user_id) or "User"

    if property_id:
        prop = db.query(Property).filter(Property.id == property_id).first()
        if prop:
            op = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            if op and op.user_id == actor_user_id:
                return {
                    "role": "owner",
                    "role_label": "Owner",
                    "name": name,
                    "email": email,
                }
            has_ma = (
                db.query(PropertyManagerAssignment)
                .filter(
                    PropertyManagerAssignment.property_id == property_id,
                    PropertyManagerAssignment.user_id == actor_user_id,
                )
                .first()
            )
            if has_ma:
                return {
                    "role": "property_manager",
                    "role_label": "Manager",
                    "name": name,
                    "email": email,
                }
            unit_ids = [r[0] for r in db.query(Unit.id).filter(Unit.property_id == property_id).all()]
            if unit_ids:
                has_ta = (
                    db.query(TenantAssignment)
                    .filter(
                        TenantAssignment.user_id == actor_user_id,
                        TenantAssignment.unit_id.in_(unit_ids),
                    )
                    .first()
                )
                if has_ta:
                    return {
                        "role": "tenant",
                        "role_label": "Tenant",
                        "name": name,
                        "email": email,
                    }

    if u.role == UserRole.guest:
        return {"role": "guest", "role_label": "Guest", "name": name, "email": email}
    if u.role == UserRole.admin:
        return {"role": "admin", "role_label": "Administrator", "name": name, "email": email}
    # Without a property match, do not infer "Owner" from UserRole alone (account may own other properties).
    if not property_id:
        if u.role == UserRole.owner:
            return {"role": "owner", "role_label": "Owner", "name": name, "email": email}
        if u.role == UserRole.property_manager:
            return {
                "role": "property_manager",
                "role_label": "Manager",
                "name": name,
                "email": email,
            }
        if u.role == UserRole.tenant:
            return {"role": "tenant", "role_label": "Tenant", "name": name, "email": email}

    role_key = u.role.value if hasattr(u.role, "value") else str(u.role)
    role_label = role_key.replace("_", " ").title()
    return {"role": "unknown", "role_label": role_label, "name": name, "email": email}
