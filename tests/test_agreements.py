"""Unit tests for jurisdiction-aware Guest Acknowledgment (agreements.py)."""
import unittest

from app.models.region_rule import RiskLevel, StayClassification
from app.services.agreements import (
    GUEST_ACK_TITLE,
    _build_guest_acknowledgment,
    _build_guest_acknowledgment_fallback,
    _sha256_hex,
    fill_guest_signature_in_content,
    agreement_content_to_pdf,
)
from app.services.jurisdiction_sot import JurisdictionInfo, StatuteInfo


def _make_jinfo(region_code: str, name: str, statute_citation: str | None = None) -> JurisdictionInfo:
    statutes = [StatuteInfo(citation=statute_citation or "applicable law", plain_english=None)] if statute_citation else []
    return JurisdictionInfo(
        region_code=region_code,
        state_code=region_code if region_code != "NYC" else "NY",
        name=name,
        max_stay_days=29,
        tenancy_threshold_days=30,
        warning_days=5,
        agreement_type="REVOCABLE_LICENSE",
        removal_guest_text=None,
        removal_tenant_text=None,
        statutes=statutes,
        risk_level=RiskLevel.medium,
        stay_classification=StayClassification.guest,
        allow_extended_if_owner_occupied=False,
    )


class TestGuestAcknowledgmentBuilder(unittest.TestCase):
    def test_title_is_guidance_title(self) -> None:
        self.assertEqual(GUEST_ACK_TITLE, "Guest Acknowledgment and Revocable License to Occupy")

    def test_california_section3_and_disclaimer(self) -> None:
        jinfo = _make_jinfo("CA", "California", "Cal. Civ. Code § 1940")
        content = _build_guest_acknowledgment(
            "CA", jinfo,
            property_address="123 Main St",
            guest_name="[Guest Name]",
            checkin="2026-03-15",
            checkout="2026-03-18",
        )
        self.assertIn("Transient Occupancy (California)", content)
        self.assertIn("fourteen (14) days within any six-month period", content)
        self.assertIn("seven (7) consecutive nights", content)
        self.assertIn("California law", content)
        self.assertIn("DocuStay is not a law firm", content)

    def test_florida_section3_and_disclaimer(self) -> None:
        jinfo = _make_jinfo("FL", "Florida", "Florida Statutes § 82.036")
        content = _build_guest_acknowledgment(
            "FL", jinfo,
            property_address="456 Oak Ave",
            guest_name="[Guest Name]",
            checkin="2026-04-01",
            checkout="2026-04-05",
        )
        self.assertIn("Status under Florida Law", content)
        self.assertIn("not a current or former tenant", content)
        self.assertIn("Florida Statutes § 82.036", content)
        self.assertIn("Florida Residential Landlord and Tenant Act", content)

    def test_new_york_section3_and_disclaimer(self) -> None:
        jinfo = _make_jinfo("NYC", "New York", "NYC Admin Code § 26-521")
        content = _build_guest_acknowledgment(
            "NYC", jinfo,
            property_address="100 Broadway",
            guest_name="[Guest Name]",
            checkin="2026-03-10",
            checkout="2026-03-14",
        )
        self.assertIn("Occupancy Limits (New York)", content)
        self.assertIn("twenty-nine (29) consecutive days", content)
        self.assertIn("thirty (30) consecutive days", content)
        self.assertIn("New York Real Property Law", content)

    def test_generic_section3_for_tx(self) -> None:
        jinfo = _make_jinfo("TX", "Texas", "Texas Property Code § 92.001")
        content = _build_guest_acknowledgment(
            "TX", jinfo,
            property_address="789 Elm St",
            guest_name="[Guest Name]",
            checkin="2026-05-01",
            checkout="2026-05-07",
        )
        self.assertIn("Acknowledgment of Guest Status", content)
        self.assertIn("Texas Property Code § 92.001", content)
        self.assertIn("applicable state and local law", content)

    def test_document_hash_deterministic(self) -> None:
        jinfo = _make_jinfo("CA", "California", "Cal. Civ. Code § 1940")
        content1 = _build_guest_acknowledgment(
            "CA", jinfo,
            property_address="123 Main",
            guest_name="[Guest Name]",
            checkin="2026-03-15",
            checkout="2026-03-18",
        )
        content2 = _build_guest_acknowledgment(
            "CA", jinfo,
            property_address="123 Main",
            guest_name="[Guest Name]",
            checkin="2026-03-15",
            checkout="2026-03-18",
        )
        self.assertEqual(content1, content2)
        self.assertEqual(_sha256_hex(content1), _sha256_hex(content2))

    def test_fallback_contains_generic_law(self) -> None:
        content = _build_guest_acknowledgment_fallback(
            property_address="999 Fallback Rd",
            guest_name="[Guest Name]",
            checkin="2026-01-01",
            checkout="2026-01-05",
        )
        self.assertIn(GUEST_ACK_TITLE, content)
        self.assertIn("applicable state and local law", content)
        self.assertIn("Acknowledgment of Authority", content)
        self.assertIn("Revocation", content)

    def test_fill_guest_signature_new_template(self) -> None:
        content = "**Guest Signature:** __________________________\n**Date:** __________________________\nIP Address: ______________________"
        filled = fill_guest_signature_in_content(content, "Jane Doe", "2026-03-15", "192.168.1.1")
        self.assertIn("Jane Doe", filled)
        self.assertIn("2026-03-15", filled)
        self.assertIn("192.168.1.1", filled)

    def test_pdf_generates_with_bold(self) -> None:
        title = GUEST_ACK_TITLE
        content = "**Property:** 123 Main St\n**Guest:** [Guest Name]\n**1. Acknowledgment of Authority:** Some text."
        pdf_bytes = agreement_content_to_pdf(title, content)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 500)


if __name__ == "__main__":
    unittest.main()
