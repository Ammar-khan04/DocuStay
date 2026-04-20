"""Permission helpers for role-based access control. All checks are property/unit-scoped.

KEY RULE: Ask "What lane does this data belong to?" — not "Who owns the property?"
Permissions follow the lane (property/management, tenant, guest), not ownership status.
Ownership does NOT override privacy scope. Tenant-invited guest data stays in tenant lane.

Permission structure: User + Property/Unit + Role + Mode + Action
- User: the authenticated user
- Property/Unit: the resource being accessed
- Role: owner, property_manager, tenant, guest
- Mode: business (portfolio/management) or personal (resident)
- Action: the requested operation (VIEW_BILLING, INVITE_GUEST, SET_PRESENCE, etc.)

Personal vs Business Mode: Users can switch modes, but privacy rules still apply.
Switching to personal mode does NOT unlock tenant-private information.
Unit resident presence (SET_PRESENCE) is allowed only for users with a tenant assignment on that unit.
"""
from enum import Enum
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from app.models.user import User, UserRole
from app.models.owner import OwnerProfile, Property, OccupancyStatus
from app.models.unit import Unit
from app.models.property_manager_assignment import PropertyManagerAssignment
from app.models.tenant_assignment import TenantAssignment
from app.models.resident_mode import ResidentMode
from app.models.resident_mode import ResidentModeType
from app.models.invitation import Invitation
from app.models.stay import Stay


class Action(str, Enum):
    """Actions that can be evaluated against User + Property/Unit + Role + Mode."""
    VIEW_BILLING = "view_billing"
    MODIFY_BILLING = "modify_billing"
    INVITE_GUEST = "invite_guest"
    SET_PRESENCE = "set_presence"
    VIEW_LOGS = "view_logs"
    CONFIRM_OCCUPANCY = "confirm_occupancy"
    CONFIRM_VACANT = "confirm_vacant"
    REVOKE_STAY = "revoke_stay"
    INITIATE_REMOVAL = "initiate_removal"
    VIEW_TENANT_GUEST_HISTORY = "view_tenant_guest_history"
    INVITE_TENANT = "invite_tenant"


def can_perform_action(
    db: Session,
    user: User,
    action: Action,
    property_id: int | None = None,
    unit_id: int | None = None,
    mode: str = "business",
) -> bool:
    """Evaluate User + Property/Unit + Role + Mode + Action. Returns True if allowed."""
    if action == Action.VIEW_BILLING:
        if user.role == UserRole.owner:
            return db.query(OwnerProfile).filter(OwnerProfile.user_id == user.id).first() is not None
        if user.role == UserRole.property_manager:
            if property_id is None:
                return False
            return db.query(PropertyManagerAssignment).filter(
                PropertyManagerAssignment.property_id == property_id,
                PropertyManagerAssignment.user_id == user.id,
            ).first() is not None
        return False

    if action == Action.MODIFY_BILLING:
        if user.role != UserRole.owner:
            return False
        return db.query(OwnerProfile).filter(OwnerProfile.user_id == user.id).first() is not None

    if action == Action.INVITE_GUEST:
        if unit_id is None:
            return False
        return can_invite_guest(db, user, unit_id, mode)

    if action == Action.SET_PRESENCE:
        if unit_id is None:
            return False
        # Tenant lane only: assigned tenant on this unit (not owner/manager personal residence).
        if user.role != UserRole.tenant:
            return False
        return db.query(TenantAssignment).filter(
            TenantAssignment.unit_id == unit_id,
            TenantAssignment.user_id == user.id,
        ).first() is not None

    if action == Action.VIEW_LOGS:
        if property_id is None:
            return False
        return can_view_audit_logs(db, user, property_id)

    if action in (Action.CONFIRM_OCCUPANCY, Action.CONFIRM_VACANT, Action.REVOKE_STAY, Action.INITIATE_REMOVAL):
        # Stay-scoped: use can_confirm_occupancy or similar at endpoint with stay object
        return False

    if action == Action.VIEW_TENANT_GUEST_HISTORY:
        # Tenant-invited guest history is never exposed to owners/managers (any mode).
        return False

    if action == Action.INVITE_TENANT:
        if property_id is None:
            return False
        return can_access_property(db, user, property_id, "business") and user.role in (
            UserRole.owner,
            UserRole.property_manager,
        )

    return False


def can_access_property(db: Session, user: User, property_id: int, mode: str = "business") -> bool:
    """True if user can access this property in the given mode."""
    if user.role == UserRole.owner:
        profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == user.id).first()
        if not profile:
            return False
        prop = db.query(Property).filter(
            Property.id == property_id,
            Property.owner_profile_id == profile.id,
            Property.deleted_at.is_(None),
        ).first()
        if prop is None:
            return False
        # Personal mode: only properties owner has marked as primary (owner_occupied)
        if mode == "personal":
            return bool(prop.owner_occupied)
        return True
    if user.role == UserRole.property_manager:
        # Business: only properties assigned to this manager. Personal: only properties they are assigned to live on (ResidentMode).
        if mode == "business":
            return db.query(PropertyManagerAssignment).filter(
                PropertyManagerAssignment.property_id == property_id,
                PropertyManagerAssignment.user_id == user.id,
            ).first() is not None
        if mode == "personal":
            unit_ids = [r[0] for r in db.query(Unit.id).filter(Unit.property_id == property_id).all()]
            if not unit_ids:
                return False
            return db.query(ResidentMode).filter(
                ResidentMode.unit_id.in_(unit_ids),
                ResidentMode.user_id == user.id,
                ResidentMode.mode == ResidentModeType.manager_personal,
            ).first() is not None
    if user.role == UserRole.tenant:
        # Tenant can only access property via their assigned unit
        ta = db.query(TenantAssignment).join(Unit).filter(
            TenantAssignment.user_id == user.id,
            Unit.property_id == property_id,
        ).first()
        return ta is not None
    return False


def can_access_unit(db: Session, user: User, unit_id: int, mode: str = "business") -> bool:
    """True if user can access this unit in the given mode."""
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        return False
    if user.role == UserRole.owner:
        profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == user.id).first()
        if not profile:
            return False
        prop = db.query(Property).filter(
            Property.id == unit.property_id,
            Property.owner_profile_id == profile.id,
        ).first()
        if prop is None:
            return False
        # Personal mode: only units the owner personally occupies (primary residence), not rented units.
        if mode == "personal":
            if not prop.owner_occupied:
                return False
            allowed = set(get_owner_personal_mode_units(db, user.id))
            return unit.id in allowed
        return True
    if user.role == UserRole.property_manager:
        if mode == "business":
            return db.query(PropertyManagerAssignment).filter(
                PropertyManagerAssignment.property_id == unit.property_id,
                PropertyManagerAssignment.user_id == user.id,
            ).first() is not None
        if mode == "personal":
            return db.query(ResidentMode).filter(
                ResidentMode.unit_id == unit_id,
                ResidentMode.user_id == user.id,
                ResidentMode.mode == ResidentModeType.manager_personal,
            ).first() is not None
    if user.role == UserRole.tenant:
        return db.query(TenantAssignment).filter(
            TenantAssignment.unit_id == unit_id,
            TenantAssignment.user_id == user.id,
        ).first() is not None
    return False


def can_invite_guest(db: Session, user: User, unit_id: int, mode: str = "business") -> bool:
    """True if user can invite guests for this unit (owner, manager in personal mode, or tenant)."""
    return can_access_unit(db, user, unit_id, mode)


def can_modify_billing(db: Session, user: User, owner_profile_id: int) -> bool:
    """True only for owners who own this profile. Property managers cannot modify billing."""
    if user.role != UserRole.owner:
        return False
    profile = db.query(OwnerProfile).filter(
        OwnerProfile.id == owner_profile_id,
        OwnerProfile.user_id == user.id,
    ).first()
    return profile is not None


def can_assign_property_manager(db: Session, user: User, property_id: int) -> bool:
    """True only for owners who own this property."""
    return can_access_property(db, user, property_id, "business") and user.role == UserRole.owner


def can_confirm_occupancy(db: Session, user: User, stay) -> bool:
    """True if user can confirm occupancy for this stay (owner or assigned manager)."""
    if user.role == UserRole.owner:
        return user_owns_property_by_profile(db, user.id, stay.property_id)
    if user.role == UserRole.property_manager:
        return db.query(PropertyManagerAssignment).filter(
            PropertyManagerAssignment.property_id == stay.property_id,
            PropertyManagerAssignment.user_id == user.id,
        ).first() is not None
    return False


def can_confirm_occupancy_for_property(db: Session, user: User, property_id: int) -> bool:
    """Owner of the property or a manager assigned to it (business portfolio)."""
    if user.role == UserRole.owner:
        profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == user.id).first()
        if not profile:
            return False
        return (
            db.query(Property)
            .filter(
                Property.id == property_id,
                Property.owner_profile_id == profile.id,
                Property.deleted_at.is_(None),
            )
            .first()
            is not None
        )
    if user.role == UserRole.property_manager:
        return (
            db.query(PropertyManagerAssignment)
            .filter(
                PropertyManagerAssignment.property_id == property_id,
                PropertyManagerAssignment.user_id == user.id,
            )
            .first()
            is not None
        )
    return False


def can_confirm_occupancy_for_tenant_assignment(db: Session, user: User, ta: TenantAssignment) -> bool:
    """Property/management-lane tenant unit lease only; owner or assigned manager for that property."""
    unit = db.query(Unit).filter(Unit.id == ta.unit_id).first()
    if not unit:
        return False
    if not can_confirm_occupancy_for_property(db, user, unit.property_id):
        return False
    inviter_id = getattr(ta, "invited_by_user_id", None)
    if inviter_id is None:
        return True
    inviter = db.query(User).filter(User.id == inviter_id).first()
    if not inviter:
        return True
    return inviter.role in (UserRole.owner, UserRole.property_manager)


def can_view_audit_logs(db: Session, user: User, property_id: int) -> bool:
    """True for owners and assigned property managers."""
    if user.role == UserRole.owner:
        return can_access_property(db, user, property_id, "business")
    if user.role == UserRole.property_manager:
        return db.query(PropertyManagerAssignment).filter(
            PropertyManagerAssignment.property_id == property_id,
            PropertyManagerAssignment.user_id == user.id,
        ).first() is not None
    return False


def get_owner_personal_mode_units(db: Session, user_id: int) -> list[int]:
    """Return unit IDs where this owner personally resides (presence, guest visibility in personal mode).

    Only `owner_occupied` properties are considered. On multi-unit properties, only unit(s) marked
    `is_primary_residence` are included — not units rented to tenants. Single-unit properties use the
    sole Unit row."""
    unit_ids: list[int] = []
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == user_id).first()
    if not profile:
        return []

    primary_props = (
        db.query(Property)
        .filter(
            Property.owner_profile_id == profile.id,
            Property.deleted_at.is_(None),
            Property.owner_occupied == True,
        )
        .all()
    )
    for prop in primary_props:
        units = db.query(Unit).filter(Unit.property_id == prop.id).order_by(Unit.id).all()
        if units:
            if len(units) == 1:
                unit_ids.append(units[0].id)
            else:
                primaries = [u for u in units if int(getattr(u, "is_primary_residence", 0) or 0) == 1]
                for u in primaries:
                    unit_ids.append(u.id)
        elif not prop.is_multi_unit:
            u = Unit(
                property_id=prop.id,
                unit_label="1",
                occupancy_status=prop.occupancy_status or OccupancyStatus.vacant.value,
            )
            db.add(u)
            db.flush()
            unit_ids.append(u.id)

    return list(dict.fromkeys(unit_ids))


def owner_profile_property_ids(db: Session, user_id: int) -> set[int]:
    """Property IDs this user owns via ``OwnerProfile`` (portfolio scope; not ``Stay.owner_id``)."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == user_id).first()
    if not profile:
        return set()
    return {r[0] for r in db.query(Property.id).filter(Property.owner_profile_id == profile.id).all()}


def user_owns_property_by_profile(db: Session, user_id: int, property_id: int) -> bool:
    """True if ``property_id`` is on this user's owner profile (current record owner in DocuStay)."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == user_id).first()
    if not profile:
        return False
    return (
        db.query(Property.id)
        .filter(Property.id == property_id, Property.owner_profile_id == profile.id)
        .first()
        is not None
    )


def owner_personal_guest_scope_unit_ids(db: Session, user_id: int) -> set[int]:
    """Units where an owner may see property-lane guest invites/stays in personal mode (units they occupy)."""
    return set(get_owner_personal_mode_units(db, user_id))


def invitation_in_owner_personal_guest_scope(db: Session, inv: Invitation, allowed_unit_ids: set[int]) -> bool:
    """True if this invitation's guest activity may be shown to the owner in personal mode."""
    if inv.unit_id is not None:
        return inv.unit_id in allowed_unit_ids
    rows = db.query(Unit.id).filter(Unit.property_id == inv.property_id).all()
    ids = [r[0] for r in rows]
    if len(ids) == 1 and ids[0] in allowed_unit_ids:
        return True
    return False


def stay_in_owner_personal_guest_scope(db: Session, stay: Stay, allowed_unit_ids: set[int]) -> bool:
    """True if this stay's guest activity may be shown to the owner in personal mode."""
    if stay.unit_id is not None:
        return stay.unit_id in allowed_unit_ids
    if stay.invitation_id:
        inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
        if inv:
            return invitation_in_owner_personal_guest_scope(db, inv, allowed_unit_ids)
    rows = db.query(Unit.id).filter(Unit.property_id == stay.property_id).all()
    ids = [r[0] for r in rows]
    if len(ids) == 1 and ids[0] in allowed_unit_ids:
        return True
    return False


def invitation_in_manager_personal_guest_scope(db: Session, inv: Invitation, manager_unit_ids: set[int]) -> bool:
    """Manager sees guest data only for units where they are the on-site resident."""
    if inv.unit_id is not None:
        return inv.unit_id in manager_unit_ids
    rows = db.query(Unit.id).filter(Unit.property_id == inv.property_id).all()
    ids = [r[0] for r in rows]
    if len(ids) == 1 and ids[0] in manager_unit_ids:
        return True
    return False


def stay_in_manager_personal_guest_scope(db: Session, stay: Stay, manager_unit_ids: set[int]) -> bool:
    if stay.unit_id is not None:
        return stay.unit_id in manager_unit_ids
    if stay.invitation_id:
        inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
        if inv:
            return invitation_in_manager_personal_guest_scope(db, inv, manager_unit_ids)
    rows = db.query(Unit.id).filter(Unit.property_id == stay.property_id).all()
    ids = [r[0] for r in rows]
    if len(ids) == 1 and ids[0] in manager_unit_ids:
        return True
    return False


def get_manager_personal_mode_units(db: Session, user_id: int) -> list[int]:
    """Return unit IDs where this property manager has Personal Mode (lives on-site)."""
    rows = db.query(ResidentMode.unit_id).filter(
        ResidentMode.user_id == user_id,
        ResidentMode.mode == ResidentModeType.manager_personal,
    ).all()
    return [r[0] for r in rows]


def get_owner_personal_mode_property_ids(db: Session, user_id: int) -> list[int]:
    """Return property IDs where this owner has Personal Mode (properties marked as primary / owner_occupied).
    Used to scope dashboard alerts in personal mode: only alerts for these properties are shown."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == user_id).first()
    if not profile:
        return []
    rows = (
        db.query(Property.id)
        .filter(
            Property.owner_profile_id == profile.id,
            Property.deleted_at.is_(None),
            Property.owner_occupied == True,
        )
        .all()
    )
    return [r[0] for r in rows]


def get_manager_personal_mode_property_ids(db: Session, user_id: int) -> list[int]:
    """Return property IDs where this manager has Personal Mode (lives on-site).
    Used to scope dashboard alerts in personal mode: only alerts for these properties are shown."""
    unit_ids = get_manager_personal_mode_units(db, user_id)
    if not unit_ids:
        return []
    rows = db.query(Unit.property_id).filter(Unit.id.in_(unit_ids)).distinct().all()
    return [r[0] for r in rows]


def validate_invite_email_role(db: Session, email: str, expected_role: UserRole) -> str | None:
    """If this email already has a user account for ``expected_role``, return a short message (avoid duplicate signup).

    The same email may exist under other roles; that does not block invitations for this role.
    """
    if not email or not email.strip():
        return None
    # Tenants and guests can legitimately have multiple leases/stays/invitations over time; having an existing
    # account must NOT block inviting or assigning them again.
    if expected_role in (UserRole.tenant, UserRole.guest):
        return None
    existing_same_role = (
        db.query(User)
        .filter(User.email == email.strip().lower(), User.role == expected_role)
        .first()
    )
    if not existing_same_role:
        return None
    role_labels = {
        UserRole.owner: "property owner",
        UserRole.property_manager: "property manager",
        UserRole.tenant: "tenant",
        UserRole.guest: "guest",
        UserRole.admin: "admin",
    }
    target_label = role_labels.get(expected_role, expected_role.value)
    return (
        f"This email is already registered as a {target_label}. "
        "Use login or assign them with their existing account if your workflow supports it."
    )


def email_conflicts_with_property_as_tenant_or_guest(db: Session, *, email: str, property_id: int) -> bool:
    """True if this email has tenant/guest presence on the given property.

    Rule: A property manager account must never be able to manage a property they are a tenant or guest of.
    Cross-role reuse of an email is allowed elsewhere, but for *this* property it must be rejected.
    """
    email_norm = (email or "").strip().lower()
    if not email_norm or not property_id:
        return False

    # Tenant conflict: a tenant user with this email has a tenant assignment on any unit in this property.
    tenant_user_ids = [
        r[0]
        for r in db.query(User.id)
        .filter(func.lower(func.trim(User.email)) == email_norm, User.role == UserRole.tenant)
        .all()
    ]
    if tenant_user_ids:
        ta = (
            db.query(TenantAssignment)
            .join(Unit, TenantAssignment.unit_id == Unit.id)
            .filter(TenantAssignment.user_id.in_(tenant_user_ids), Unit.property_id == property_id)
            .first()
        )
        if ta is not None:
            return True

    # Guest conflict: either a guest user with this email has a stay on this property, or an invitation on this
    # property targets this email (covers "registered guest elsewhere" and invite-only records).
    guest_user_ids = [
        r[0]
        for r in db.query(User.id)
        .filter(func.lower(func.trim(User.email)) == email_norm, User.role == UserRole.guest)
        .all()
    ]
    stay_guest_cond = Stay.guest_id.in_(guest_user_ids) if guest_user_ids else False
    inv_email_cond = func.lower(func.trim(Invitation.guest_email)) == email_norm
    guest_hit = (
        db.query(Stay.id)
        .outerjoin(Invitation, Stay.invitation_id == Invitation.id)
        .filter(
            Stay.property_id == property_id,
            or_(stay_guest_cond, inv_email_cond),
        )
        .first()
        is not None
    )
    if guest_hit:
        return True

    inv_hit = (
        db.query(Invitation.id)
        .filter(Invitation.property_id == property_id, inv_email_cond)
        .first()
        is not None
    )
    return inv_hit
