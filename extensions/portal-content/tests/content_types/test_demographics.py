"""Tests for SDK-backed patient demographics."""

from datetime import date
from unittest.mock import MagicMock, patch

from canvas_sdk.v1.data.patient import Patient as RealPatient

from portal_content.content_types import demographics


def _patient(registered=True, pharmacy=None):
    patient = MagicMock(
        birth_date=date(1990, 5, 1),
        photo_url="https://host/photo",
        preferred_full_name="Jane Q. Doe",
    )
    user = MagicMock(is_portal_registered=registered)
    user.email = "jane@example.com"
    patient.user = user
    addr = MagicMock(
        line1="1 Main St", line2="Apt 2", city="Indy",
        state_code="IN", state="Indiana", postal_code="46077",
    )
    patient.addresses.all.return_value = [addr]
    patient.preferred_pharmacy = pharmacy
    return patient


def _patch_patient(patient):
    p = patch("portal_content.content_types.demographics.Patient")
    mock = p.start()
    mock.DoesNotExist = RealPatient.DoesNotExist
    mock.objects.select_related.return_value.prefetch_related.return_value.get.return_value = patient
    return p, mock


@patch("portal_content.content_types.demographics.CareTeamMembership")
def test_get_demographics_maps_all_sections(care_team):
    care_team.objects.values.return_value.filter.return_value = [
        {
            "staff__first_name": "Ann", "staff__last_name": "Lee",
            "staff__prefix": "Dr.", "staff__suffix": "MD", "role_display": "PCP",
        }
    ]
    p, _ = _patch_patient(_patient(pharmacy={"name": "CVS Main"}))
    try:
        result = demographics.get_demographics("patient-1")
    finally:
        p.stop()

    assert result["full_name"] == "Jane Q. Doe"
    assert result["date_of_birth"] == "May 01, 1990"
    assert result["email"] == "jane@example.com"
    assert result["addresses"][0]["line1"] == "1 Main St"
    assert result["addresses"][0]["state"] == "IN"  # state_code preferred
    assert result["care_team"][0]["name"] == "Dr. Ann Lee, MD"
    assert result["care_team"][0]["role"] == "PCP"
    assert result["preferred_pharmacy"] == "CVS Main"


@patch("portal_content.content_types.demographics.CareTeamMembership")
def test_get_demographics_unregistered_user_has_no_email_and_no_pharmacy(care_team):
    care_team.objects.values.return_value.filter.return_value = []
    p, _ = _patch_patient(_patient(registered=False, pharmacy=None))
    try:
        result = demographics.get_demographics("p")
    finally:
        p.stop()

    assert result["email"] is None
    assert result["preferred_pharmacy"] is None
    assert result["care_team"] == []


def test_get_demographics_missing_patient_returns_none():
    p = patch("portal_content.content_types.demographics.Patient")
    mock = p.start()
    mock.DoesNotExist = RealPatient.DoesNotExist
    mock.objects.select_related.return_value.prefetch_related.return_value.get.side_effect = (
        RealPatient.DoesNotExist
    )
    try:
        assert demographics.get_demographics("missing") is None
    finally:
        p.stop()
