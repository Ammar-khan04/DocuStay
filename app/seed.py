"""Seed jurisdiction rules (all 50 US states), region rules (legacy), and optional admin user.

Jurisdiction groupings — legal threshold is the REAL statutory number;
platform_renewal_cycle_days is the operational authorization period.

  Group A  (14-day common-law): CA, CO, CT, FL, ME, MO, NC
  Group B  (30-day):            AL, IN, KS, KY, NY, OH, PA
  Group C  (lease-defined, 14d default): AK, AR, DE, HI, ID, IA, LA, MA, MI, NE,
           NV, NH, NJ, NM, ND, OK, OR, RI, SC, SD, UT, VT, VA, WA, WV, WI, WY
  Group D  (behavior-based):    GA, IL, MD, MN, MS, TN, TX
  Group E  (unique):            AZ (29-day / 28-day), MT (7-day / 7-day)
"""
import os
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.region_rule import RegionRule, StayClassification, RiskLevel
from app.models.jurisdiction import Jurisdiction, JurisdictionStatute, JurisdictionZipMapping

# ---------------------------------------------------------------------------
# Grouped jurisdiction definitions
# ---------------------------------------------------------------------------

_GROUP_A = {
    "group": "A",
    "legal_threshold_days": 14,
    "platform_renewal_cycle_days": 13,
    "reminder_days_before": 3,
    "risk_level": RiskLevel.medium,
    "states": {
        "CA": ("California",  True,  "TRANSIENT_LODGER"),
        "CO": ("Colorado",    False, "REVOCABLE_LICENSE"),
        "CT": ("Connecticut", False, "REVOCABLE_LICENSE"),
        "FL": ("Florida",     False, "HB621_DECLARATION"),
        "ME": ("Maine",       False, "REVOCABLE_LICENSE"),
        "MO": ("Missouri",    False, "REVOCABLE_LICENSE"),
        "NC": ("North Carolina", False, "REVOCABLE_LICENSE"),
    },
}

_GROUP_B = {
    "group": "B",
    "legal_threshold_days": 30,
    "platform_renewal_cycle_days": 29,
    "reminder_days_before": 5,
    "risk_level": RiskLevel.high,
    "states": {
        "AL": ("Alabama",      False, "REVOCABLE_LICENSE"),
        "IN": ("Indiana",      False, "REVOCABLE_LICENSE"),
        "KS": ("Kansas",       False, "REVOCABLE_LICENSE"),
        "KY": ("Kentucky",     False, "REVOCABLE_LICENSE"),
        "NY": ("New York",     False, "REVOCABLE_LICENSE"),
        "OH": ("Ohio",         False, "REVOCABLE_LICENSE"),
        "PA": ("Pennsylvania", False, "REVOCABLE_LICENSE"),
    },
}

_GROUP_C = {
    "group": "C",
    "legal_threshold_days": None,  # lease-defined — no statutory day count
    "platform_renewal_cycle_days": 14,
    "reminder_days_before": 3,
    "risk_level": RiskLevel.medium,
    "states": {
        "AK": ("Alaska",         False, "REVOCABLE_LICENSE"),
        "AR": ("Arkansas",       False, "REVOCABLE_LICENSE"),
        "DE": ("Delaware",       False, "REVOCABLE_LICENSE"),
        "HI": ("Hawaii",         False, "REVOCABLE_LICENSE"),
        "ID": ("Idaho",          False, "REVOCABLE_LICENSE"),
        "IA": ("Iowa",           False, "REVOCABLE_LICENSE"),
        "LA": ("Louisiana",      False, "REVOCABLE_LICENSE"),
        "MA": ("Massachusetts",  False, "REVOCABLE_LICENSE"),
        "MI": ("Michigan",       False, "REVOCABLE_LICENSE"),
        "NE": ("Nebraska",       False, "REVOCABLE_LICENSE"),
        "NV": ("Nevada",         False, "REVOCABLE_LICENSE"),
        "NH": ("New Hampshire",  False, "REVOCABLE_LICENSE"),
        "NJ": ("New Jersey",     False, "REVOCABLE_LICENSE"),
        "NM": ("New Mexico",     False, "REVOCABLE_LICENSE"),
        "ND": ("North Dakota",   False, "REVOCABLE_LICENSE"),
        "OK": ("Oklahoma",       False, "REVOCABLE_LICENSE"),
        "OR": ("Oregon",         False, "REVOCABLE_LICENSE"),
        "RI": ("Rhode Island",   False, "REVOCABLE_LICENSE"),
        "SC": ("South Carolina", False, "REVOCABLE_LICENSE"),
        "SD": ("South Dakota",   False, "REVOCABLE_LICENSE"),
        "UT": ("Utah",           False, "REVOCABLE_LICENSE"),
        "VT": ("Vermont",        False, "REVOCABLE_LICENSE"),
        "VA": ("Virginia",       False, "REVOCABLE_LICENSE"),
        "WA": ("Washington",     False, "ANTI_SQUATTER_DECLARATION"),
        "WV": ("West Virginia",  False, "REVOCABLE_LICENSE"),
        "WI": ("Wisconsin",      False, "REVOCABLE_LICENSE"),
        "WY": ("Wyoming",        False, "REVOCABLE_LICENSE"),
    },
}

_GROUP_D = {
    "group": "D",
    "legal_threshold_days": None,  # behavior-based — no fixed day count
    "platform_renewal_cycle_days": 14,
    "reminder_days_before": 3,
    "risk_level": RiskLevel.medium,
    "states": {
        "GA": ("Georgia",    False, "REVOCABLE_LICENSE"),
        "IL": ("Illinois",   False, "REVOCABLE_LICENSE"),
        "MD": ("Maryland",   False, "REVOCABLE_LICENSE"),
        "MN": ("Minnesota",  False, "REVOCABLE_LICENSE"),
        "MS": ("Mississippi", False, "REVOCABLE_LICENSE"),
        "TN": ("Tennessee",  False, "REVOCABLE_LICENSE"),
        "TX": ("Texas",      False, "TRANSIENT_GUEST"),
    },
}

_GROUP_E_STATES = [
    {
        "group": "E",
        "state_code": "AZ",
        "name": "Arizona",
        "legal_threshold_days": 29,
        "platform_renewal_cycle_days": 28,
        "reminder_days_before": 5,
        "risk_level": RiskLevel.medium,
        "allow_extended": False,
        "agreement_type": "REVOCABLE_LICENSE",
    },
    {
        "group": "E",
        "state_code": "MT",
        "name": "Montana",
        "legal_threshold_days": 7,
        "platform_renewal_cycle_days": 7,
        "reminder_days_before": 2,
        "risk_level": RiskLevel.high,
        "allow_extended": False,
        "agreement_type": "REVOCABLE_LICENSE",
    },
]

ALL_GROUPS = [_GROUP_A, _GROUP_B, _GROUP_C, _GROUP_D]

# ---------------------------------------------------------------------------
# Section 3 clause text per state (stored in DB, used in guest acknowledgments)
# ---------------------------------------------------------------------------
_S3_THRESHOLD_TMPL = (
    "**3. Acknowledgment of Guest Status ({name}):** "
    "By signing this document, you explicitly acknowledge and agree that your occupancy at the Property "
    "is that of a temporary guest and does not constitute a tenancy. You understand that under {statute} "
    "and applicable common law, a continuous stay of {days} days or more may lead to the establishment "
    "of tenant rights. This acknowledgment serves as a clear record of your temporary status for the "
    "duration specified herein. You agree that you have no right to occupy the Property beyond the "
    "authorized period without a new, written authorization from the Property Owner/Manager."
)

_S3_BEHAVIOR_TMPL = (
    "**3. Acknowledgment of Guest Status ({name}):** "
    "By signing this document, you explicitly acknowledge and agree that your occupancy at the Property "
    "is that of a temporary guest and does not constitute a tenancy. You understand that under {statute}, "
    "tenancy is determined by behavior rather than a fixed number of days. Actions such as contributing to "
    "rent or utilities, receiving mail at the Property, or possessing a key without the owner present may "
    "trigger tenant rights. This acknowledgment serves as a clear record of your temporary, non-tenant "
    "status. You agree that you have no right to occupy the Property beyond the authorized period without "
    "a new, written authorization from the Property Owner/Manager."
)

_S3_LEASE_TMPL = (
    "**3. Acknowledgment of Guest Status ({name}):** "
    "By signing this document, you explicitly acknowledge and agree that your occupancy at the Property "
    "is that of a temporary guest and does not constitute a tenancy. You understand that in {name}, the "
    "nature of occupancy is primarily defined by the agreement between the parties. This document serves "
    "as that agreement, establishing your status as a temporary guest for the duration specified herein. "
    "You agree that you have no right to occupy the Property beyond the authorized period without a new, "
    "written authorization from the Property Owner/Manager."
)


def _build_section_3_clauses() -> dict[str, str]:
    """Build Section 3 clause text for all 50 states."""
    c: dict[str, str] = {}

    # --- Group A: 14-day threshold ---
    c["CA"] = (
        "**3. Acknowledgment of Transient Occupancy (California):** "
        "By signing this document, you explicitly acknowledge and agree that your occupancy at the Property "
        "is that of a temporary guest and does not constitute a tenancy. You understand that under California "
        "Civil Code Sections 1940.1 and 1946.5, a guest who stays more than 14 consecutive days or more than "
        "14 days in any 6-month period may acquire tenant rights. This acknowledgment serves as a clear "
        "record of your temporary status for the duration specified herein. You agree that you have no right "
        "to occupy the Property beyond the authorized period without a new, written authorization from the "
        "Property Owner/Manager."
    )
    c["FL"] = (
        "**3. Acknowledgment of Status under Florida Law:** "
        "By signing this document, you explicitly acknowledge and agree that your occupancy at the Property "
        "is that of a temporary guest and does not constitute a tenancy. You understand that under Florida "
        "Statute Section 82.036 (HB 621) and applicable common law, a guest who stays more than 14 "
        "consecutive days or more than 14 days in any 6-month period may acquire tenant rights. This "
        "acknowledgment serves as a clear record of your temporary status for the duration specified herein. "
        "You agree that you have no right to occupy the Property beyond the authorized period without a new, "
        "written authorization from the Property Owner/Manager."
    )
    for sc, name, statute in [
        ("CO", "Colorado", "Colorado Revised Statutes Section 38-12-301"),
        ("CT", "Connecticut", "Connecticut General Statutes Section 47a-1"),
        ("ME", "Maine", "Maine common law"),
        ("MO", "Missouri", "Missouri common law"),
        ("NC", "North Carolina", "North Carolina common law"),
    ]:
        c[sc] = _S3_THRESHOLD_TMPL.format(name=name, statute=statute, days=14)

    # --- Group B: 30-day threshold ---
    c["NY"] = (
        "**3. Acknowledgment of Occupancy Limits (New York):** "
        "By signing this document, you explicitly acknowledge and agree that your occupancy at the Property "
        "is that of a temporary guest and does not constitute a tenancy. You understand that under New York "
        "Real Property Actions and Proceedings Law (RPAPL) Section 711, a continuous stay of 30 days or more "
        "may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of "
        "your temporary status for the duration specified herein. You agree that you have no right to occupy "
        "the Property beyond the authorized period without a new, written authorization from the Property "
        "Owner/Manager."
    )
    for sc, name, statute in [
        ("AL", "Alabama", "the Code of Alabama Section 35-9A-141"),
        ("IN", "Indiana", "Indiana Code IC 32-31-1-1"),
        ("KS", "Kansas", "K.S.A. Section 58-2540"),
        ("KY", "Kentucky", "KRS Section 383.010"),
        ("OH", "Ohio", "Ohio Revised Code Section 5321.01"),
        ("PA", "Pennsylvania", "68 P.S. Section 250.1"),
    ]:
        c[sc] = _S3_THRESHOLD_TMPL.format(name=name, statute=statute, days=30)

    # --- Group D: behavior-based ---
    for sc, name, statute in [
        ("GA", "Georgia", "Georgia law (O.C.G.A. Section 44-7-1)"),
        ("IL", "Illinois", "Illinois law (765 ILCS 705/1)"),
        ("MD", "Maryland", "Maryland Real Property Section 8-101"),
        ("MN", "Minnesota", "Minnesota Statutes Section 504B.001"),
        ("MS", "Mississippi", "Mississippi Code Section 89-7-1"),
        ("TN", "Tennessee", "Tennessee Code Section 66-28-102"),
        ("TX", "Texas", "Texas Property Code Section 92.001 and Penal Code Section 30.05"),
    ]:
        c[sc] = _S3_BEHAVIOR_TMPL.format(name=name, statute=statute)

    # --- Group E: unique ---
    c["AZ"] = (
        "**3. Acknowledgment of Guest Status (Arizona):** "
        "By signing this document, you explicitly acknowledge and agree that your occupancy at the Property "
        "is that of a temporary guest and does not constitute a tenancy. You understand that under Arizona "
        "Revised Statutes Section 33-14 and the Arizona Department of Revenue short-term lodging regulations, "
        "a stay of 29 days or more may trigger transient lodging tax obligations and tenant rights. This "
        "acknowledgment serves as a clear record of your temporary status for the duration specified herein. "
        "You agree that you have no right to occupy the Property beyond the authorized period without a new, "
        "written authorization from the Property Owner/Manager."
    )
    c["MT"] = (
        "**3. Acknowledgment of Guest Status (Montana):** "
        "By signing this document, you explicitly acknowledge and agree that your occupancy at the Property "
        "is that of a temporary guest and does not constitute a tenancy. You understand that under Montana "
        "Code Section 70-24-103, a continuous stay of 7 days or more without a written agreement may lead to "
        "the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary "
        "status for the duration specified herein. You agree that you have no right to occupy the Property "
        "beyond the authorized period without a new, written authorization from the Property Owner/Manager."
    )

    # --- Group C: lease-defined (standard template) ---
    for sc, (name, _, _) in _GROUP_C["states"].items():
        if sc in c:
            continue  # skip if already defined (WA, OR)
        c[sc] = _S3_LEASE_TMPL.format(name=name)

    # Special Group C states with statute references
    c["OR"] = (
        "**3. Acknowledgment of Guest Status (Oregon):** "
        "By signing this document, you explicitly acknowledge and agree that your occupancy at the Property "
        "is that of a temporary guest under a Temporary Occupancy Agreement as defined by Oregon Revised "
        "Statutes Section 90.275. This document serves as that agreement, establishing your status as a "
        "temporary guest for the duration specified herein. You agree that you have no right to occupy the "
        "Property beyond the authorized period without a new, written authorization from the Property "
        "Owner/Manager, which would constitute a new Temporary Occupancy Agreement under ORS 90.275."
    )
    c["WA"] = (
        "**3. Acknowledgment of Guest Status (Washington):** "
        "By signing this document, you explicitly acknowledge and agree that your occupancy at the Property "
        "is that of a temporary guest and does not constitute a tenancy. You understand that under Washington "
        "Revised Code Section 9A.52.105, the nature of occupancy is primarily defined by the agreement "
        "between the parties. This document serves as that agreement, establishing your status as a temporary "
        "guest for the duration specified herein. You agree that you have no right to occupy the Property "
        "beyond the authorized period without a new, written authorization from the Property Owner/Manager."
    )
    return c


_SECTION_3_CLAUSES = _build_section_3_clauses()


def seed_region_rules(db: Session) -> None:
    if db.query(RegionRule).count() > 0:
        return
    for grp in ALL_GROUPS:
        for sc, (name, ext, _) in grp["states"].items():
            db.add(RegionRule(
                region_code=sc,
                max_stay_days=grp["platform_renewal_cycle_days"],
                stay_classification_label=StayClassification.guest,
                risk_level=grp["risk_level"],
                allow_extended_if_owner_occupied=ext,
            ))
    for e in _GROUP_E_STATES:
        db.add(RegionRule(
            region_code=e["state_code"],
            max_stay_days=e["platform_renewal_cycle_days"],
            stay_classification_label=StayClassification.guest,
            risk_level=e["risk_level"],
            allow_extended_if_owner_occupied=e["allow_extended"],
        ))
    db.commit()


def _build_jurisdiction(state_code, name, grp, legal_threshold, renewal, reminder, risk, allow_ext, agreement_type):
    return Jurisdiction(
        region_code=state_code,
        state_code=state_code,
        name=name,
        jurisdiction_group=grp,
        legal_threshold_days=legal_threshold,
        platform_renewal_cycle_days=renewal,
        reminder_days_before=reminder,
        max_stay_days=renewal,                   # backward compat
        tenancy_threshold_days=legal_threshold,   # backward compat
        warning_days=reminder,                    # backward compat
        agreement_type=agreement_type,
        section_3_clause=_SECTION_3_CLAUSES.get(state_code),
        stay_classification_label=StayClassification.guest,
        risk_level=risk,
        allow_extended_if_owner_occupied=allow_ext,
    )


def seed_jurisdiction_sot(db: Session) -> None:
    """Seed all 50 US states using grouped jurisdiction buckets. Idempotent."""
    if db.query(Jurisdiction).count() > 0:
        return

    for grp in ALL_GROUPS:
        for sc, (name, ext, agr) in grp["states"].items():
            db.add(_build_jurisdiction(
                sc, name, grp["group"],
                grp["legal_threshold_days"], grp["platform_renewal_cycle_days"],
                grp["reminder_days_before"], grp["risk_level"], ext, agr,
            ))
    for e in _GROUP_E_STATES:
        db.add(_build_jurisdiction(
            e["state_code"], e["name"], e["group"],
            e["legal_threshold_days"], e["platform_renewal_cycle_days"],
            e["reminder_days_before"], e["risk_level"], e["allow_extended"], e["agreement_type"],
        ))
    db.flush()

    statutes = [
        ("NY", "RPAPL § 711", "Occupying a dwelling for 30+ consecutive days creates tenancy rights.", 0),
        ("FL", "FL Statute § 82.036 (HB 621)", "Sheriff may remove unauthorized person with signed affidavit; no lease.", 0),
        ("CA", "CA Civil Code § 1940.1, AB 1482", "Transient occupancy; common-law tenancy may form around 14 days.", 0),
        ("CA", "CA Civil Code § 1946.5", "Single lodger; owner-occupied; removal as trespasser after notice.", 1),
        ("TX", "Texas Property Code § 92.001, Penal Code § 30.05", "Transient housing exempt from landlord-tenant; criminal trespass after notice.", 0),
        ("WA", "RCW 9A.52.105", "Tenancy is fact-specific; owner declaration can assist police removal.", 0),
        ("AZ", "A.R.S. § 33-1413", "Guest occupancy for 29+ days may create tenant rights.", 0),
        ("MT", "Montana Code § 70-24-103", "Tenant at will after 7 days of occupancy.", 0),
        ("CO", "C.R.S. § 38-12-101", "Common-law tenancy principles; no fixed statutory threshold.", 0),
        ("CT", "C.G.S. § 47a-1", "Tenancy implied from occupancy; common-law 14-day doctrine.", 0),
        ("AL", "Code of Alabama § 35-9A-141", "Tenancy after 30 days of continuous occupancy.", 0),
        ("IN", "IC 32-31-1-1", "30-day threshold for tenant protections.", 0),
        ("KS", "K.S.A. § 58-2540", "30-day continuous occupancy creates tenancy.", 0),
        ("KY", "KRS § 383.010", "30-day tenancy threshold.", 0),
        ("OH", "ORC § 5321.01", "Tenant rights attach after 30 days.", 0),
        ("PA", "68 P.S. § 250.102", "Occupant becomes tenant after 30 continuous days.", 0),
        ("GA", "O.C.G.A. § 44-7-1", "Tenancy determined by behavior and intent, not duration alone.", 0),
        ("IL", "765 ILCS 705/0.01", "Behavior-based; intent and conduct determine tenancy.", 0),
        ("MD", "MD Real Prop. § 8-101", "Behavior-based tenancy determination.", 0),
        ("MN", "Minn. Stat. § 504B.001", "Tenancy from conduct and circumstances.", 0),
        ("MS", "Miss. Code § 89-7-1", "Behavior-based tenancy.", 0),
        ("TN", "Tenn. Code § 66-28-102", "Tenancy determined by behavior.", 0),
    ]
    for region_code, citation, plain_english, sort_order in statutes:
        db.add(JurisdictionStatute(
            region_code=region_code,
            citation=citation,
            plain_english=plain_english,
            use_in_authority_package=True,
            sort_order=sort_order,
        ))
    db.flush()

    zip_mappings = [
        ("10001", "NY"), ("10002", "NY"), ("10003", "NY"), ("11201", "NY"), ("11238", "NY"),
        ("33101", "FL"), ("33139", "FL"), ("32034", "FL"), ("33001", "FL"), ("33401", "FL"),
        ("90210", "CA"), ("94102", "CA"), ("90001", "CA"), ("92101", "CA"), ("95814", "CA"),
        ("77001", "TX"), ("75201", "TX"), ("78701", "TX"), ("78205", "TX"), ("76102", "TX"),
        ("98101", "WA"), ("98102", "WA"), ("98104", "WA"), ("98122", "WA"), ("99201", "WA"),
        ("85001", "AZ"), ("85281", "AZ"), ("59601", "MT"), ("59101", "MT"),
        ("80202", "CO"), ("06101", "CT"), ("04101", "ME"), ("63101", "MO"), ("27601", "NC"),
        ("35203", "AL"), ("46204", "IN"), ("66101", "KS"), ("40202", "KY"),
        ("43215", "OH"), ("19101", "PA"),
        ("30301", "GA"), ("60601", "IL"), ("21201", "MD"), ("55401", "MN"),
        ("39201", "MS"), ("37201", "TN"),
    ]
    for zip_code, region_code in zip_mappings:
        db.add(JurisdictionZipMapping(zip_code=zip_code, region_code=region_code))

    db.commit()


def seed_admin_user(db: Session) -> None:
    """Create default admin user for fresh installs (admin@docustay.com). Uses ADMIN_EMAIL/ADMIN_PASSWORD if set."""
    from app.models.user import User, UserRole
    from app.services.auth import get_password_hash

    admin_email = (os.environ.get("ADMIN_EMAIL") or "admin@docustay.com").strip().lower()
    admin_password = os.environ.get("ADMIN_PASSWORD") or "DreamsOfDreams89"
    admin_full_name = os.environ.get("ADMIN_FULL_NAME", "Admin").strip() or "Admin"

    existing = db.query(User).filter(User.email == admin_email, User.role == UserRole.admin).first()
    hashed = get_password_hash(admin_password)
    now = datetime.now(timezone.utc)

    if existing:
        existing.hashed_password = hashed
        existing.email_verified = True
        existing.identity_verified_at = now
        existing.poa_waived_at = now
        db.commit()
        return

    user = User(
        email=admin_email,
        hashed_password=hashed,
        role=UserRole.admin,
        full_name=admin_full_name,
        email_verified=True,
        identity_verified_at=now,
        poa_waived_at=now,
    )
    db.add(user)
    db.commit()
