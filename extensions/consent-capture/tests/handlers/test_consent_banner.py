"""Tests for consent_capture/handlers/consent_banner.py."""

from unittest.mock import patch

from consent_capture.constants import BANNER_KEY, BANNER_NARRATIVE
from consent_capture.handlers.consent_banner import ConsentBanner

MODULE = "consent_capture.handlers.consent_banner"


def _handler(context=None, target=None, secrets=None):
    h = ConsentBanner()
    h.context = context or {}
    h.target = target
    if secrets is not None:
        h.secrets = secrets
    return h


class TestPatientId:
    def test_prefers_context_patient_id(self):
        # Consent events carry the patient under context.patient.id.
        h = _handler(context={"patient": {"id": "p-ctx"}}, target="consent-123")
        assert h._patient_id() == "p-ctx"

    def test_falls_back_to_target(self):
        # Patient events carry the patient id as the event target.
        h = _handler(context={}, target="p-target")
        assert h._patient_id() == "p-target"

    def test_no_patient_returns_empty(self):
        assert _handler(context={}, target=None)._patient_id() == ""


class TestCompute:
    def test_adds_warning_chart_banner_when_required_incomplete(self):
        h = _handler(context={"patient": {"id": "p1"}})
        with patch(f"{MODULE}.is_eligible_patient", return_value=True), patch(
            f"{MODULE}.has_incomplete_required", return_value=True
        ) as mock_check:
            effects = h.compute()
        mock_check.assert_called_once_with("p1")
        assert len(effects) == 1
        eff = effects[0]
        assert eff["type"] == "AddBannerAlert"
        assert eff["patient_id"] == "p1"
        assert eff["key"] == BANNER_KEY
        assert eff["narrative"] == BANNER_NARRATIVE
        assert eff["placement"] == ["chart", "profile"]
        assert eff["intent"] == "warning"        # warning styling
        assert eff["href"] is None               # banners can't launch the modal

    def test_removes_banner_when_nothing_outstanding(self):
        h = _handler(context={"patient": {"id": "p1"}})
        with patch(f"{MODULE}.is_eligible_patient", return_value=True), patch(
            f"{MODULE}.has_incomplete_required", return_value=False
        ):
            effects = h.compute()
        assert len(effects) == 1
        assert effects[0] == {"type": "RemoveBannerAlert", "key": BANNER_KEY, "patient_id": "p1"}

    def test_ineligible_patient_banner_removed_even_if_required_missing(self):
        # An inactive OR deceased patient must never carry the banner, regardless of
        # consents (is_eligible_patient is False for both).
        h = _handler(context={"patient": {"id": "p1"}})
        with patch(f"{MODULE}.is_eligible_patient", return_value=False), patch(
            f"{MODULE}.has_incomplete_required", return_value=True
        ) as mock_check:
            effects = h.compute()
        assert effects == [{"type": "RemoveBannerAlert", "key": BANNER_KEY, "patient_id": "p1"}]
        mock_check.assert_not_called()  # ineligibility short-circuits before consent check

    def test_no_patient_id_does_nothing(self):
        h = _handler(context={}, target=None)
        with patch(f"{MODULE}.is_eligible_patient") as mock_active, patch(
            f"{MODULE}.has_incomplete_required"
        ) as mock_check:
            assert h.compute() == []
        mock_active.assert_not_called()
        mock_check.assert_not_called()

    def test_disabled_flag_removes_banner_without_checking_status(self):
        # CONSENT_BANNERS_ENABLED off: clear any banner and never evaluate eligibility
        # or consent status, so the feature is fully suppressed.
        h = _handler(
            context={"patient": {"id": "p1"}},
            secrets={"CONSENT_BANNERS_ENABLED": "false"},
        )
        with patch(f"{MODULE}.is_eligible_patient") as mock_active, patch(
            f"{MODULE}.has_incomplete_required", return_value=True
        ) as mock_check:
            effects = h.compute()
        assert effects == [{"type": "RemoveBannerAlert", "key": BANNER_KEY, "patient_id": "p1"}]
        mock_active.assert_not_called()
        mock_check.assert_not_called()

    def test_enabled_flag_behaves_normally(self):
        # An explicit "true" is the same as the default (adds when required missing).
        h = _handler(
            context={"patient": {"id": "p1"}},
            secrets={"CONSENT_BANNERS_ENABLED": "true"},
        )
        with patch(f"{MODULE}.is_eligible_patient", return_value=True), patch(
            f"{MODULE}.has_incomplete_required", return_value=True
        ):
            effects = h.compute()
        assert effects[0]["type"] == "AddBannerAlert"


class TestBannerCopy:
    def test_narrative_within_limit_and_no_em_dash(self):
        assert len(BANNER_NARRATIVE) <= 90
        assert "—" not in BANNER_NARRATIVE  # no em dash


class TestResponds:
    def test_responds_to_consent_and_patient_events(self):
        assert set(ConsentBanner.RESPONDS_TO) == {
            "CONSENT_CREATED", "CONSENT_UPDATED", "CONSENT_DELETED",
            "PATIENT_CREATED", "PATIENT_UPDATED",
        }
