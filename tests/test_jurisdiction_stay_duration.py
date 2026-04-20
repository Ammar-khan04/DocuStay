"""Tests for jurisdiction stay-duration validation (calendar / invite date limits).

Covers: validate_stay_duration_for_property, get_max_stay_days_for_property, resolve_jurisdiction.
Ensures stays that exceed the legal limit for a property's region are rejected with a clear error.
"""
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.region_rule import RegionRule, StayClassification, RiskLevel
from app.schemas.jle import JLEInput
from app.services.jle import (
    resolve_jurisdiction,
    validate_stay_duration_for_property,
    get_max_stay_days_for_property,
)


def _make_session():
    """In-memory SQLite session with region_rules table."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _add_region_rule(db, region_code: str, max_stay_days: int, allow_extended_if_owner_occupied: bool = False):
    r = RegionRule(
        region_code=region_code,
        max_stay_days=max_stay_days,
        stay_classification_label=StayClassification.guest,
        risk_level=RiskLevel.medium,
        allow_extended_if_owner_occupied=allow_extended_if_owner_occupied,
    )
    db.add(r)
    db.commit()
    return r


class TestJurisdictionStayDuration(unittest.TestCase):
    """Test that stay duration is validated against region rules."""

    @patch("app.services.jurisdiction_sot.get_jurisdiction_for_region")
    def test_validate_within_limit_returns_none(self, mock_get_jurisdiction):
        mock_get_jurisdiction.return_value = None
        db = _make_session()
        _add_region_rule(db, "FL", 30)
        start = date.today()
        end = start + timedelta(days=30)
        err = validate_stay_duration_for_property(db, "FL", False, start, end)
        self.assertIsNone(err, "30-day stay in 30-day region should be valid")
        db.close()

    @patch("app.services.jurisdiction_sot.get_jurisdiction_for_region")
    def test_validate_exceeds_limit_returns_error_message(self, mock_get_jurisdiction):
        mock_get_jurisdiction.return_value = None
        db = _make_session()
        _add_region_rule(db, "FL", 30)
        start = date.today()
        end = start + timedelta(days=45)
        err = validate_stay_duration_for_property(db, "FL", False, start, end)
        self.assertIsNotNone(err)
        self.assertIn("45", err)
        self.assertIn("30", err)
        self.assertIn("exceeds", err.lower())
        db.close()

    @patch("app.services.jurisdiction_sot.get_jurisdiction_for_region")
    def test_validate_no_region_rule_allows_any_duration(self, mock_get_jurisdiction):
        mock_get_jurisdiction.return_value = None
        db = _make_session()
        # No RegionRule added; region "XX" has no rule
        start = date.today()
        end = start + timedelta(days=90)
        err = validate_stay_duration_for_property(db, "XX", False, start, end)
        self.assertIsNone(err, "No rule for region should allow")
        db.close()

    @patch("app.services.jurisdiction_sot.get_jurisdiction_for_region")
    def test_validate_empty_region_code_returns_none(self, mock_get_jurisdiction):
        db = _make_session()
        start = date.today()
        end = start + timedelta(days=60)
        err = validate_stay_duration_for_property(db, "", False, start, end)
        self.assertIsNone(err)
        db.close()

    @patch("app.services.jurisdiction_sot.get_jurisdiction_for_region")
    def test_validate_end_before_start_returns_error(self, mock_get_jurisdiction):
        db = _make_session()
        start = date.today()
        end = start - timedelta(days=1)
        err = validate_stay_duration_for_property(db, "FL", False, start, end)
        self.assertIsNotNone(err)
        self.assertIn("after start", err.lower())
        db.close()

    @patch("app.services.jurisdiction_sot.get_jurisdiction_for_region")
    def test_get_max_stay_days_returns_rule_limit(self, mock_get_jurisdiction):
        mock_get_jurisdiction.return_value = None
        db = _make_session()
        _add_region_rule(db, "CA", 29)
        max_days = get_max_stay_days_for_property(db, "CA", False)
        self.assertEqual(max_days, 29)
        db.close()

    @patch("app.services.jurisdiction_sot.get_jurisdiction_for_region")
    def test_get_max_stay_days_no_rule_returns_none(self, mock_get_jurisdiction):
        mock_get_jurisdiction.return_value = None
        db = _make_session()
        max_days = get_max_stay_days_for_property(db, "ZZ", False)
        self.assertIsNone(max_days)
        db.close()

    @patch("app.services.jurisdiction_sot.get_jurisdiction_for_region")
    def test_resolve_jurisdiction_within_limit(self, mock_get_jurisdiction):
        mock_get_jurisdiction.return_value = None
        db = _make_session()
        _add_region_rule(db, "FL", 30)
        inp = JLEInput(region_code="FL", stay_duration_days=30, owner_occupied=False)
        result = resolve_jurisdiction(db, inp)
        self.assertIsNotNone(result)
        self.assertEqual(result.compliance_status, "within_limit")
        self.assertEqual(result.maximum_allowed_duration_days, 30)
        db.close()

    @patch("app.services.jurisdiction_sot.get_jurisdiction_for_region")
    def test_resolve_jurisdiction_exceeds_limit(self, mock_get_jurisdiction):
        mock_get_jurisdiction.return_value = None
        db = _make_session()
        _add_region_rule(db, "FL", 30)
        inp = JLEInput(region_code="FL", stay_duration_days=31, owner_occupied=False)
        result = resolve_jurisdiction(db, inp)
        self.assertIsNotNone(result)
        self.assertEqual(result.compliance_status, "exceeds_limit")
        self.assertIsNotNone(result.message)
        self.assertIn("31", result.message)
        self.assertIn("30", result.message)
        db.close()


if __name__ == "__main__":
    unittest.main()
