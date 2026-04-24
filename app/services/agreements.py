"""Agreement document generation for invitation flows. Uses JurisdictionInfo from DB SOT when available."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.models.invitation import Invitation
from app.models.owner import Property
from app.models.unit import Unit
from app.models.user import User
from app.services.jurisdiction_sot import JurisdictionInfo, get_jurisdiction_for_property
from app.services.invitation_guest_completion import guest_invite_awaiting_account_after_sign
from app.services.invitation_kinds import is_property_invited_tenant_signup_kind


def fill_guest_signature_in_content(
    content: str, guest_name: str, signed_date: str, ip_address: str | None = None
) -> str:
    """Replace the blank guest or tenant signature line with the signer's name, date, and optionally IP."""
    result = content
    # New template (guidance): **Guest Signature:** ___ or **Tenant Signature:** ___ and **Date:** ___ on same or next line
    result = re.sub(r"\*\*Guest Signature:\*\*\s*_{10,}", f"**Guest Signature:** {guest_name}", result, count=1)
    result = re.sub(r"\*\*Tenant Signature:\*\*\s*_{10,}", f"**Tenant Signature:** {guest_name}", result, count=1)
    result = re.sub(r"\*\*Date:\*\*\s*_{10,}", f"**Date:** {signed_date}", result, count=1)
    # Legacy patterns (Signed:/Guest:/ etc.)
    legacy = [
        (r"Guest Signature:\s*_{10,}\s+Date:\s*_{10,}", f"Guest Signature: {guest_name}   Date: {signed_date}"),
        (r"Signed:\s*_{10,}\s+Date:\s*_{10,}", f"Signed: {guest_name}   Date: {signed_date}"),
        (r"Licensee:\s*_{10,}\s+Date:\s*_{10,}", f"Licensee: {guest_name}   Date: {signed_date}"),
        (r"Occupant:\s*_{10,}\s+Date:\s*_{10,}", f"Occupant: {guest_name}   Date: {signed_date}"),
        (r"Guest:\s*_{10,}\s+Date:\s*_{10,}", f"Guest: {guest_name}   Date: {signed_date}"),
    ]
    for pattern, replacement in legacy:
        result = re.sub(pattern, replacement, result, count=1)
    if ip_address is not None and "IP Address:" in result:
        result = re.sub(r"IP Address:\s*_{10,}", f"IP Address: {ip_address}", result, count=1)
    return result


@dataclass(frozen=True)
class AgreementDoc:
    document_id: str
    region_code: str
    title: str
    content: str
    document_hash: str
    property_address: str | None
    stay_start_date: str | None
    stay_end_date: str | None
    host_name: str | None


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _format_address(prop: Property | None) -> str | None:
    if not prop:
        return None
    parts = [prop.street, prop.city, prop.state]
    if prop.zip_code:
        parts.append(prop.zip_code)
    return ", ".join([p for p in parts if p])


def _normalize_region(region_code: str) -> str:
    rc = (region_code or "").strip().upper()
    if rc in {"NY", "NYC"}:
        return "NY"
    return rc or "US"


def _format_stay_date_display(d) -> str | None:
    """Format invitation stay date for agreement text; safe for date/datetime/str from DB."""
    if d is None:
        return None
    if hasattr(d, "strftime"):
        try:
            return d.strftime("%B %d, %Y")
        except (AttributeError, OSError, ValueError):
            return str(d)
    return str(d) if d else None


# --- Jurisdiction-aware Guest Acknowledgment (guidance: Guest Acknowledgment and Revocable License to Occupy) ---

GUEST_ACK_TITLE = "Guest Acknowledgment and Revocable License to Occupy"

TENANT_ACK_TITLE = "Tenant Invitation Acceptance"

# Tenant invitation: primary resident acceptance. No guest stay language.
def _build_tenant_invitation_acceptance(
    property_address: str | None,
    tenant_name: str,
    unit_info: str,
    stay_start_date: str | None = None,
    stay_end_date: str | None = None,
) -> str:
    dates_info = ""
    if stay_start_date and stay_end_date:
        dates_info = f"\n**Lease/Assignment Period:** {stay_start_date} to {stay_end_date}"

    return f"""**Tenant Invitation Acceptance**

DocuStay is a documentation platform for property status and guest authorizations. This document confirms your acceptance of an invitation to be the primary resident of a unit.

**1. Acceptance of Invitation**
You accept this invitation to access and occupy the unit at the property as the assigned tenant/resident. You understand you are the primary resident of this unit.

**2. Platform Use**
You agree to use the DocuStay platform in accordance with the Terms of Service and Privacy Policy. You may use the platform to manage your own guest authorizations for temporary visitors to your unit.

**3. Documentation Only**
This acceptance documents your status as the tenant/resident of the unit. DocuStay does not manage leases or tenancy agreements; your lease or rental agreement with the property owner governs your tenancy.

**Property:** {property_address or '[Property Address]'}
**Unit:** {unit_info or '[Unit]'}
**Tenant:** {tenant_name}{dates_info}

**Tenant Signature:** __________________________
**Date:** __________________________
IP Address: ______________________
"""

# Shared sections (Guest Acknowledgment guidance — same framing for all jurisdictions)
def _section1_authority() -> str:
    return """**Acknowledgment of Authority:** You acknowledge that the Property Owner has granted a limited Power of Attorney to DocuStay, a third-party documentation platform, authorizing it to maintain records of property status, including your occupancy as a guest."""

def _section2_revocable_license() -> str:
    return """**Grant of Revocable License:** You acknowledge that your authorization to be on the property is a revocable license and does not create a tenancy or any other interest in the property. This license is personal to you and may not be assigned or transferred. You may not sublet any part of the property."""

def _section4_no_hold_over(checkout: str) -> str:
    return f"""**No Right to Hold Over:** You have no right to remain on the property after {checkout} (the "End Date" of your authorized stay). Any continued occupancy beyond the authorized period may be addressed by the Property Owner in accordance with applicable law."""

def _section5_revocation() -> str:
    return """**Revocation:** You acknowledge that this license is revocable at the will of the Property Owner. The Owner may terminate your occupancy subject to applicable law and any required notice provisions."""

def _section_platform_role() -> str:
    return """**Platform Role.** Guest acknowledges that DocuStay is a third-party recordkeeping platform and does not determine legal rights, enforce occupancy decisions, or provide legal advice."""

def _section3_fallback(statute_citation: str, *, state_name: str | None = None) -> str:
    """Fallback Section 3 when no pre-written clause is stored in the DB (guidance-aligned)."""
    including = f", including {state_name}," if (state_name or "").strip() else ""
    # Do not use f-string for statute_citation — citations may contain `{` / `}` and break formatting.
    return (
        "**Acknowledgment of Guest Status:** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property "
        "is that of a temporary guest and is intended to reflect a temporary, revocable license to occupy and not a lease. "
        "The legal characterization of any occupancy may depend on applicable law and the specific facts of the stay. "
        "Certain jurisdictions"
        + including
        + " may recognize tenancy or other occupancy rights based on the duration or nature of a stay. "
        "The Guest acknowledges that applicable law may vary and that this document reflects the parties' intended arrangement, "
        "not a legal determination. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. "
        "You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager. "
        "You understand that under "
        + statute_citation
        + ", a written lease may be required for tenancy; that reference is informational context only, not legal advice."
    )

def _disclaimer_phrase(region_code: str, state_name: str) -> str:
    """Return the state/law phrase for section 6 disclaimer."""
    rc = (region_code or "").strip().upper()
    if rc == "CA":
        return "California law"
    if rc == "FL":
        return "the Florida Residential Landlord and Tenant Act"
    if rc in ("NY", "NYC"):
        return "New York Real Property Law"
    return "applicable state and local law"

def _build_guest_acknowledgment(
    region_code: str,
    jinfo: JurisdictionInfo,
    *,
    property_address: str | None,
    guest_name: str,
    checkin: str,
    checkout: str,
) -> str:
    """Build full Guest Acknowledgment content with jurisdiction-specific section 3 and disclaimer. Uses ** for bold labels."""
    prop_display = (property_address or "[Address, Unit]").strip()
    statute_citation = "applicable state and local law"
    if jinfo.statutes:
        statute_citation = jinfo.statutes[0].citation
    state_name = jinfo.name or ""

    rc = (region_code or "").strip().upper()
    if jinfo.section_3_clause:
        section3 = jinfo.section_3_clause
    else:
        section3 = _section3_fallback(statute_citation, state_name=(state_name or "").strip() or None)

    disclaimer_law = _disclaimer_phrase(rc, state_name)
    section6 = f"""**Disclaimer:** This document is a record of your authorized occupancy as a guest under a revocable license. It is not a lease and does not grant you any rights of a tenant under {disclaimer_law}. DocuStay is not a law firm and does not provide legal advice."""

    # section3 comes from DB (jurisdiction clause) and may contain `{` / `}` — never interpolate it inside an f-string.
    head = f"""**{GUEST_ACK_TITLE}**

**Property:** {prop_display}
**Guest:** {guest_name}
**Authorized Stay:** {checkin} to {checkout}

{_section1_authority()}

{_section2_revocable_license()}

"""
    tail = f"""

{_section4_no_hold_over(checkout)}

{_section5_revocation()}

{_section_platform_role()}

{section6}

**Guest Signature:** __________________________
**Date:** __________________________
IP Address: ______________________
"""
    return head + section3 + tail


def _build_agreement_from_jurisdiction(
    jinfo: JurisdictionInfo,
    *,
    owner_name: str,
    guest_name: str,
    today: str,
    checkin: str,
    checkout: str,
    property_address: str | None,
) -> tuple[str, str]:
    """Build Guest Acknowledgment title and content from JurisdictionInfo (SOT). Returns (title, content)."""
    content = _build_guest_acknowledgment(
        jinfo.region_code,
        jinfo,
        property_address=property_address,
        guest_name=guest_name,
        checkin=checkin,
        checkout=checkout,
    )
    return (GUEST_ACK_TITLE, content)


def _build_guest_acknowledgment_fallback(
    *,
    property_address: str | None,
    guest_name: str,
    checkin: str,
    checkout: str,
) -> str:
    """Fallback when no jurisdiction: generic Guest Acknowledgment with applicable state and local law."""
    prop_display = (property_address or "[Address, Unit]").strip()
    section3 = _section3_fallback("applicable state and local law", state_name=None)
    section6 = """**Disclaimer:** This document is a record of your authorized occupancy as a guest under a revocable license. It is not a lease and does not grant you any rights of a tenant under applicable state and local law. DocuStay is not a law firm and does not provide legal advice."""

    return f"""**{GUEST_ACK_TITLE}**

**Property:** {prop_display}
**Guest:** {guest_name}
**Authorized Stay:** {checkin} to {checkout}

{_section1_authority()}

{_section2_revocable_license()}

{section3}

{_section4_no_hold_over(checkout)}

{_section5_revocation()}

{_section_platform_role()}

{section6}

**Guest Signature:** __________________________
**Date:** __________________________
IP Address: ______________________
"""


def build_invitation_agreement(
    db: Session,
    invitation_code: str,
    guest_full_name: str | None = None,
) -> AgreementDoc | None:
    code = (invitation_code or "").strip().upper()
    if not code:
        return None

    inv = db.query(Invitation).filter(Invitation.invitation_code == code).first()
    if not inv:
        return None

    inv_kind = (getattr(inv, "invitation_kind", None) or "").strip().lower()

    # Property-issued tenant / co-tenant invite: primary resident acceptance. No guest stay language.
    if is_property_invited_tenant_signup_kind(inv_kind):
        if inv.status not in ("pending", "ongoing", "accepted", "expired"):
            return None
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        owner = db.query(User).filter(User.id == inv.owner_id).first()
        property_address = _format_address(prop)
        host_name = (owner.full_name if owner else None) or (owner.email if owner else None)
        tenant_name = (guest_full_name or "[Tenant Name]").strip() or "[Tenant Name]"
        unit_info = ""
        if inv.unit_id:
            unit = db.query(Unit).filter(Unit.id == inv.unit_id).first()
            if unit:
                unit_info = unit.unit_label or str(inv.unit_id)
        start_date = _format_stay_date_display(inv.stay_start_date)
        end_date = _format_stay_date_display(inv.stay_end_date)
        content = _build_tenant_invitation_acceptance(
            property_address=property_address,
            tenant_name=tenant_name,
            unit_info=unit_info,
            stay_start_date=start_date,
            stay_end_date=end_date,
        )
        region = _normalize_region(inv.region_code or (prop.region_code if prop else ""))
        document_id = f"DSA-Tenant-{code}"
        doc_hash = _sha256_hex(content)
        return AgreementDoc(
            document_id=document_id,
            region_code=region,
            title=TENANT_ACK_TITLE,
            content=content,
            document_hash=doc_hash,
            property_address=property_address,
            stay_start_date=str(inv.stay_start_date) if inv.stay_start_date else None,
            stay_end_date=str(inv.stay_end_date) if inv.stay_end_date else None,
            host_name=host_name,
        )

    # Guest path
    tok = (inv.token_state or "").upper()
    st = inv.status
    if st == "cancelled" or tok in ("REVOKED", "CANCELLED"):
        return None
    if st in ("pending", "ongoing", "accepted", "expired") and tok != "BURNED":
        pass
    elif st == "accepted" and tok == "BURNED" and guest_invite_awaiting_account_after_sign(db, inv):
        pass
    else:
        return None

    prop = db.query(Property).filter(Property.id == inv.property_id).first()
    owner = db.query(User).filter(User.id == inv.owner_id).first()

    region = _normalize_region(inv.region_code or (prop.region_code if prop else ""))
    host_name = (owner.full_name if owner else None) or (owner.email if owner else None)
    property_address = _format_address(prop)

    # Use provided guest name when building for display/PDF; otherwise placeholder for hashing.
    guest_name = (guest_full_name or "[Guest Name]").strip() or "[Guest Name]"
    owner_name = (host_name or "").strip() or "[Owner Name]"
    today = date.today().strftime("%B %d, %Y")
    checkin = _format_stay_date_display(inv.stay_start_date) or "[Check-in Date]"
    checkout = _format_stay_date_display(inv.stay_end_date) or "[Check-out Date]"

    # Prefer JurisdictionInfo from DB SOT so statute citations and removal text are dynamic.
    jinfo = get_jurisdiction_for_property(db, prop.zip_code if prop else None, region)
    if jinfo is not None:
        title, content = _build_agreement_from_jurisdiction(
            jinfo,
            owner_name=owner_name,
            guest_name=guest_name,
            today=today,
            checkin=checkin,
            checkout=checkout,
            property_address=property_address,
        )
        document_id = f"DSA-{code}-{jinfo.region_code}"
        doc_hash = _sha256_hex(content)
        return AgreementDoc(
            document_id=document_id,
            region_code=jinfo.region_code,
            title=title,
            content=content,
            document_hash=doc_hash,
            property_address=property_address,
            stay_start_date=str(inv.stay_start_date) if inv.stay_start_date else None,
            stay_end_date=str(inv.stay_end_date) if inv.stay_end_date else None,
            host_name=host_name,
        )

    # Fallback: no jurisdiction found; use generic template.
    content = _build_guest_acknowledgment_fallback(
        property_address=property_address,
        guest_name=guest_name,
        checkin=checkin,
        checkout=checkout,
    )
    document_id = f"DSA-{code}-{region}"
    doc_hash = _sha256_hex(content)

    return AgreementDoc(
        document_id=document_id,
        region_code=region,
        title=GUEST_ACK_TITLE,
        content=content,
        document_hash=doc_hash,
        property_address=property_address,
        stay_start_date=str(inv.stay_start_date) if inv.stay_start_date else None,
        stay_end_date=str(inv.stay_end_date) if inv.stay_end_date else None,
        host_name=host_name,
    )


# --- Master Power of Attorney (owner onboarding) ---

POA_DOCUMENT_ID = "DSA-Master-POA"
POA_TITLE = "Limited Power of Attorney and Agent Authorization"

DOCUSTAY_ADDRESS = "950 South Ash St, Apt 303, Spokane, WA 99204"

POA_CONTENT = """**Limited Power of Attorney and Agent Authorization**
This Limited Power of Attorney and Agent Authorization ("Authorization") is made effective as of the date of electronic signature below.

**1. Parties**

• The Principal: {principal_name}
{principal_address}
(Hereinafter "Principal")
• The Agent: DOCUSTAY LLC, a Washington limited liability company
950 South Ash St, Apt 303, Spokane, WA 99204
(Hereinafter "Agent" or "DocuStay")

**2. Recitals**

WHEREAS, Principal owns or is the duly authorized property manager for the real properties listed in the Principal's DocuStay account (the "Properties"); and

WHEREAS, Principal desires to appoint Agent for the sole and limited purpose of providing a technology-enabled system to record, maintain, and present documentation reflecting user-directed activity and stated authorizations relating to the occupancy and status of the Properties, without making any legal determinations or representations as to the legal effect of such documentation.

NOW, THEREFORE, in consideration of the premises and the mutual covenants contained herein, the parties agree as follows:

**3. Grant of Limited Power of Attorney**

Principal hereby appoints Agent as Principal's true and lawful attorney-in-fact, to act in Principal's name, place, and stead solely in a ministerial, non-discretionary capacity for the limited purposes and with the limited powers set forth in Section 4 below.

**4. Enumerated Limited Powers**

Agent's authority shall be strictly limited to the following acts with respect to the Properties:

• **Generate Occupancy Documentation:** To record, compile, and maintain documentation reflecting occupancy-related information as provided by the Principal or other authorized users.
• **Maintain Status Ledger:** To maintain a time-stamped, append-only ledger of property status events, including but not limited to periods of vacancy, occupancy by authorized guests, and maintenance periods as directed by the Principal.
• **Assemble Documentation Packages:** To assemble and present, upon Principal's request, documentation packages containing records of property status, guest acknowledgments, and occupancy history for a given Property.
• **Act as Third-Party Record Keeper:** To provide records generated by the platform in the ordinary course of its operation, together with associated metadata and audit logs reflecting system activity. Agent's provision of such records is limited to the transmission of system-generated data and does not constitute certification, authentication, or verification of the legal accuracy, completeness, or enforceability of such records.

**5. Limitations on Authority**

This Authorization is strictly limited to the powers enumerated in Section 4. For the avoidance of doubt, Agent shall have NO AUTHORITY to:

• Enter into any lease, rental agreement, or contract of sale on behalf of Principal.
• Collect, hold, or manage any funds, including rents or security deposits, on behalf of Principal.
• Initiate or conduct any legal proceeding, including eviction actions, on behalf of Principal.
• Bind the Principal to any contract or financial obligation not directly related to the enumerated powers.
• Act as a property manager, real estate broker, or legal representative.
• Determine or represent whether any individual is a tenant, guest, licensee, or unauthorized occupant under applicable law.

**5.1 No Independent Authority; Ministerial Role.** Agent's role is strictly ministerial and administrative. Agent shall not exercise independent judgment or discretion and shall act solely to record, maintain, and present information as directed by the Principal or as generated through user activity within the platform. Agent shall not interpret, evaluate, or make determinations regarding the legal significance of any recorded information.

**6. No Legal Determination**

Agent does not determine, adjudicate, or represent the legal status of any occupancy, tenancy, or property rights. All records generated through the platform reflect system-logged activity and user-provided information only and are intended to document stated authorizations and historical events. Such records do not constitute legal conclusions, do not establish enforceable rights, and do not replace the need for legally compliant agreements or independent legal advice.

**6.1 No Agency or Fiduciary Relationship.** Nothing in this Authorization shall be deemed to create any agency, fiduciary, property management, brokerage, or legal representation relationship between Agent and Principal or any third party. Agent acts solely as a neutral technology provider facilitating documentation.

**7. Term and Revocation**

This Authorization shall become effective upon the date of its electronic execution by the Principal and shall remain in full force and effect until it is revoked. Revocation shall not affect the retention of previously generated records maintained as part of the platform's append-only system architecture. Principal may revoke this Authorization at any time by providing written notice to the Agent via the DocuStay platform or via email to michael@docustay.online. Revocation will be effective upon Agent's acknowledgment of receipt.

**8. Durability**

This shall be a durable Power of Attorney. The authority of the Agent shall not terminate if the Principal becomes incapacitated.

**9. Governing Law**

This Authorization shall be governed by and construed in accordance with the laws of the State of Washington, without regard to its conflict of law principles.

**10. Indemnification and Limitation of Liability**

Principal agrees to indemnify, defend, and hold Agent harmless from and against any and all claims, damages, liabilities, costs, and expenses (including reasonable attorneys' fees) arising out of or related to:

• The accuracy or completeness of information provided by Principal or other users;
• Any use or reliance on platform-generated records;
• Any dispute relating to occupancy, tenancy, or property rights; or
• Any third-party interpretation or use of documentation generated through the Services.

**Third-Party Reliance.** Principal acknowledges that any sharing of platform-generated records with third parties is done at Principal's direction and risk. Agent shall have no liability arising from third-party interpretation, reliance, or use of such records.

**11. Third-Party Reliance and Use**

Principal acknowledges that any sharing of platform-generated records with third parties is done at Principal's direction and risk. Agent makes no representations regarding how any third party, including courts, law enforcement, or governmental authorities, will interpret or rely upon such records. Any reliance on platform-generated documentation is at the sole risk of the Principal or such third party.

**12. Acknowledgment and Signature**

By signing below, Principal acknowledges that they have read, understood, and agree to the terms of this Limited Power of Attorney and Agent Authorization. Principal affirms that they are either the legal owner of the Properties or a property manager with the full legal authority to grant this Authorization.

This instrument may be executed electronically. The parties agree that an electronic signature is the legal equivalent of a manual signature on this Authorization.

PRINCIPAL:

Signature: [Electronic Signature]

Printed Name: {principal_name}

Title: {principal_title}

Date: {signature_date}
"""


def build_owner_poa_document(
    principal_name: str | None = None,
    principal_address: str | None = None,
    principal_title: str | None = None,
) -> tuple[str, str, str, str]:
    """Return (document_id, title, content, document_hash) for the Master POA.
    Populates principal name, address, title, and date into the template."""
    name = (principal_name or "").strip() or "[User's Full Legal Name or Entity Name]"
    address = (principal_address or "").strip() or "[User's Full Address]"
    title = (principal_title or "").strip() or "Owner"
    sig_date = date.today().strftime("%B %d, %Y")
    content = POA_CONTENT.strip().format(
        principal_name=name,
        principal_address=address,
        principal_title=title,
        signature_date=sig_date,
    )
    doc_hash = _sha256_hex(content)
    return (POA_DOCUMENT_ID, POA_TITLE, content, doc_hash)


def fill_owner_poa_signature_line(content: str, owner_name: str, signed_date: str) -> str:
    """Fill signature placeholders in POA signature block with actual name and date."""
    result = re.sub(r"Owner:\s*_+", f"Owner: {owner_name}", content, count=1)
    result = re.sub(r"Printed Name:\s*\[User's Full Legal Name\]", f"Printed Name: {owner_name}", result, count=1)
    result = re.sub(r"Signature:\s*\[Electronic Signature\]", f"Signature: {owner_name}", result, count=1)
    # Replace date — handle both placeholder and pre-filled date formats
    result = re.sub(r"Date:\s*\[Date of Signature\]", f"Date: {signed_date}", result, count=1)
    result = re.sub(r"(PRINCIPAL:.*?)\nDate:\s*\w+ \d{1,2}, \d{4}", rf"\1\nDate: {signed_date}", result, count=1, flags=re.DOTALL)
    result = re.sub(r"Date:\s*_+", f"Date: {signed_date}", result, count=1)
    return result


def poa_content_with_signature(content: str, signer_name: str, signed_date: str) -> str:
    """Append signature line to POA content for generating a signed PDF."""
    return content.rstrip() + f"\n\nSigned by {signer_name} on {signed_date}"


def _escape_for_reportlab(s: str) -> str:
    """Escape text for ReportLab Paragraph (XML-like markup)."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _content_to_reportlab_paragraph(line: str, body_style) -> "Paragraph":
    """Convert a line that may contain **bold** to a ReportLab Paragraph with bold segments."""
    from reportlab.platypus import Paragraph

    parts = re.split(r"\*\*(.+?)\*\*", line)
    if len(parts) == 1:
        return Paragraph(_escape_for_reportlab(line), body_style)
    # parts alternate: [normal, bold, normal, bold, ...]
    frags = []
    for i, seg in enumerate(parts):
        if not seg:
            continue
        escaped = _escape_for_reportlab(seg)
        if i % 2 == 1:
            frags.append(f"<b>{escaped}</b>")
        else:
            frags.append(escaped)
    return Paragraph("".join(frags), body_style)


def agreement_content_to_pdf(title: str, content: str) -> bytes:
    """Generate a PDF from agreement title and content using reportlab. Content wraps to page width and is justified. Supports **bold** in content."""
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    body_style = styles["Normal"].clone("JustifiedBody", alignment=TA_JUSTIFY, spaceAfter=6)

    story = [Paragraph(_escape_for_reportlab(title.replace("\n", " ")), title_style), Spacer(1, 0.2 * inch)]

    for line in content.splitlines():
        line_stripped = line.strip()
        if line_stripped:
            story.append(_content_to_reportlab_paragraph(line_stripped, body_style))
        else:
            story.append(Spacer(1, 0.12 * inch))

    doc.build(story)
    return buf.getvalue()
