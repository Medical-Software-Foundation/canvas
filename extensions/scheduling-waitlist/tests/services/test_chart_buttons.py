"""Refreshing the chart's waitlist button after a write.

The button decides its label when the chart header renders. Nothing redraws it
on its own, so without this a chart keeps offering "Add to waitlist" for a
patient who was just added from the roster.
"""

from unittest.mock import MagicMock

from scheduling_waitlist.services.chart_buttons import reload_chart_buttons


def _entry(patient_id="patient-uuid"):
    entry = MagicMock()
    entry.patient.id = patient_id
    return entry


class TestReloadChartButtons:
    def test_the_patients_chart_is_asked_to_redraw(self):
        effects = reload_chart_buttons(_entry("abc-123"))

        assert len(effects) == 1
        assert effects[0].id == "abc-123"

    def test_the_identifier_is_sent_as_text(self):
        # The effect addresses a chart by key, not by row id.
        entry = MagicMock()
        entry.patient.id = 12345

        assert reload_chart_buttons(entry)[0].id == "12345"

    def test_an_entry_with_no_patient_refreshes_nothing(self):
        # An effect keyed on nothing addresses no chart, matching the banner.
        entry = MagicMock()
        entry.patient = None

        assert reload_chart_buttons(entry) == []

    def test_a_patient_without_a_key_refreshes_nothing(self):
        assert reload_chart_buttons(_entry(patient_id=None)) == []

    def test_a_missing_entry_refreshes_nothing(self):
        assert reload_chart_buttons(None) == []
