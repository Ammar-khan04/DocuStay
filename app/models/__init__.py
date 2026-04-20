"""
All SQLAlchemy models. Schema is the source of truth for new DBs.
Base.metadata.create_all() creates every table; no migration scripts needed for fresh installs.
"""
from app.models.user import User
from app.models.owner import OwnerProfile, Property
from app.models.guest import GuestProfile
from app.models.stay import Stay
from app.models.region_rule import RegionRule
from app.models.jurisdiction import Jurisdiction, JurisdictionStatute, JurisdictionZipMapping
from app.models.invitation import Invitation
from app.models.guest_pending_invite import GuestPendingInvite
from app.models.agreement_signature import AgreementSignature
from app.models.reference_option import ReferenceOption
from app.models.audit_log import AuditLog
from app.models.event_ledger import EventLedger
from app.models.owner_poa_signature import OwnerPOASignature
from app.models.pending_registration import PendingRegistration
from app.models.property_utility import PropertyUtilityProvider, PropertyAuthorityLetter
from app.models.unit import Unit
from app.models.property_manager_assignment import PropertyManagerAssignment
from app.models.tenant_assignment import TenantAssignment
from app.models.resident_mode import ResidentMode
from app.models.resident_presence import ResidentPresence
from app.models.stay_presence import StayPresence, PresenceAwayPeriod
from app.models.manager_invitation import ManagerInvitation
from app.models.property_transfer_invitation import PropertyTransferInvitation
from app.models.dashboard_alert import DashboardAlert
from app.models.notification_attempt import NotificationAttempt
from app.models.bulk_upload_job import BulkUploadJob
from app.models.guest_extension_request import GuestExtensionRequest
from app.models.demo_account import DemoAccount

__all__ = [
    "User",
    "OwnerProfile",
    "Property",
    "GuestProfile",
    "Stay",
    "RegionRule",
    "Jurisdiction",
    "JurisdictionStatute",
    "JurisdictionZipMapping",
    "Invitation",
    "GuestPendingInvite",
    "AgreementSignature",
    "ReferenceOption",
    "AuditLog",
    "EventLedger",
    "OwnerPOASignature",
    "PendingRegistration",
    "PropertyUtilityProvider",
    "PropertyAuthorityLetter",
    "Unit",
    "PropertyManagerAssignment",
    "TenantAssignment",
    "ResidentMode",
    "ResidentPresence",
    "StayPresence",
    "PresenceAwayPeriod",
    "ManagerInvitation",
    "PropertyTransferInvitation",
    "DashboardAlert",
    "NotificationAttempt",
    "BulkUploadJob",
    "GuestExtensionRequest",
    "DemoAccount",
]
