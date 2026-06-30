"""Tests for group_therapy.services.medications."""

from unittest.mock import MagicMock, patch

from group_therapy.services.medications import active_medications


def _med(display):
    coding = MagicMock()
    coding.display = display
    med = MagicMock()
    med.codings.all.return_value = [coding]
    return med


@patch("group_therapy.services.medications.Medication")
def test_active_medications_returns_display_names(mock_med):
    qs = MagicMock()
    qs.prefetch_related.return_value = [_med("Sertraline 50 mg"), _med("Lisinopril 10 mg")]
    mock_med.objects.for_patient.return_value.active.return_value = qs
    assert active_medications("pat1") == ["Sertraline 50 mg", "Lisinopril 10 mg"]
    mock_med.objects.for_patient.assert_called_once_with("pat1")


@patch("group_therapy.services.medications.Medication")
def test_active_medications_skips_codingless(mock_med):
    med = MagicMock()
    med.codings.all.return_value = []
    qs = MagicMock()
    qs.prefetch_related.return_value = [med]
    mock_med.objects.for_patient.return_value.active.return_value = qs
    assert active_medications("pat1") == []


@patch("group_therapy.services.medications.Medication")
def test_active_medications_skips_blank_coding_then_takes_next(mock_med):
    blank, real = MagicMock(), MagicMock()
    blank.display = ""
    real.display = "Fluoxetine 20 mg"
    med = MagicMock()
    med.codings.all.return_value = [blank, real]
    qs = MagicMock()
    qs.prefetch_related.return_value = [med]
    mock_med.objects.for_patient.return_value.active.return_value = qs
    assert active_medications("pat1") == ["Fluoxetine 20 mg"]


@patch("group_therapy.services.medications.Medication")
def test_active_medications_degrades_on_error(mock_med):
    mock_med.objects.for_patient.side_effect = AttributeError("boom")
    assert active_medications("pat1") == []
