"""Shield Mode product policy (CR-1a / CR-1b).

DO NOT REMOVE: The `Property.shield_mode_enabled` column and all legacy toggle,
notification, and billing hooks stay in the codebase so Shield can become
optional again later. When ``SHIELD_MODE_ALWAYS_ON`` is True:

- Every property is treated as Shield ON for API responses and billing counts.
- Status Confirmation / timeline behavior does not depend on turning Shield off.
- Writes that used to set Shield OFF are disabled (original code preserved in
  ``if not SHIELD_MODE_ALWAYS_ON`` branches or comments).
"""

from __future__ import annotations

# Set to False only when product re-enables an owner-facing Shield toggle.
SHIELD_MODE_ALWAYS_ON: bool = True


def effective_shield_mode_enabled(prop: object | None) -> bool:
    """What clients should show for Shield (ignores stale DB 0 when always-on)."""
    if SHIELD_MODE_ALWAYS_ON:
        return True
    if prop is None:
        return False
    return bool(getattr(prop, "shield_mode_enabled", 0))


def persisted_shield_row_int(*, csv_parsed_on: bool) -> int:
    """Integer written to ``Property.shield_mode_enabled`` on create/update from CSV/API.

    DO NOT REMOVE ``csv_parsed_on`` — when ``SHIELD_MODE_ALWAYS_ON`` is False,
    restore: ``return 1 if csv_parsed_on else 0``.
    """
    if SHIELD_MODE_ALWAYS_ON:
        return 1
    return 1 if csv_parsed_on else 0
