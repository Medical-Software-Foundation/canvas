"""Tests for the MedicationHistoryButton action button handler."""

from unittest.mock import patch

from canvas_sdk.effects import EffectType
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data.patient import Patient

from medication_history.protocols.medication_history_button import (
    HISTORY_LIMIT,
    MedicationHistoryButton,
    _build_medication,
    _medication_name,
)

from tests.conftest import (
    FDB_SYSTEM,
    NDC_SYSTEM,
    RXNORM_SYSTEM,
    make_coding,
    make_medication,
)

MODULE = "medication_history.protocols.medication_history_button"


class TestButtonConfiguration:
    def test_button_title(self):
        assert MedicationHistoryButton.BUTTON_TITLE == "Med Hx"

    def test_button_key(self):
        assert MedicationHistoryButton.BUTTON_KEY == "medication_history"

    def test_button_location(self):
        assert (
            MedicationHistoryButton.BUTTON_LOCATION
            == ActionButton.ButtonLocation.CHART_SUMMARY_MEDICATIONS_SECTION
        )


class TestVisible:
    def test_visible_always_true(self, mock_event):
        handler = MedicationHistoryButton(event=mock_event)

        assert handler.visible() is True


class TestMedicationName:
    """_medication_name picks the best readable drug name from codings."""

    def test_prefers_fdb_display(self):
        med = make_medication(
            codings=[
                make_coding(NDC_SYSTEM, "UNKNOWN system=NDC code=16500-08806"),
                make_coding(RXNORM_SYSTEM, "UNKNOWN system=rxnorm code=8557"),
                make_coding(FDB_SYSTEM, "ADVAIR 100-50 DISKUS"),
            ]
        )

        assert _medication_name(med) == "ADVAIR 100-50 DISKUS"

    def test_falls_back_to_rxnorm_when_no_fdb(self):
        med = make_medication(
            codings=[
                make_coding(NDC_SYSTEM, "UNKNOWN system=NDC code=1"),
                make_coding(RXNORM_SYSTEM, "Aspirin 81 MG"),
            ]
        )

        assert _medication_name(med) == "Aspirin 81 MG"

    def test_falls_back_to_any_readable_display(self):
        med = make_medication(
            codings=[make_coding("unstructured", "Some Compounded Cream")]
        )

        assert _medication_name(med) == "Some Compounded Cream"

    def test_placeholder_when_all_displays_unknown(self):
        med = make_medication(
            codings=[
                make_coding(NDC_SYSTEM, "UNKNOWN system=NDC code=1"),
                make_coding(RXNORM_SYSTEM, "UNKNOWN system=rxnorm code=2"),
            ]
        )

        assert _medication_name(med) == "Unknown medication"

    def test_placeholder_when_no_codings(self):
        assert _medication_name(make_medication(codings=[])) == "Unknown medication"


class TestBuildMedication:
    def test_active_medication_is_formatted(self):
        result = _build_medication(make_medication())

        assert result["name"] == "ADVAIR 100-50 DISKUS"
        assert result["is_active"] is True
        assert result["status_label"] == "Active"
        assert result["start_date"] == "Sep 04, 2019"
        assert result["end_date"] == ""
        assert result["quantity"] == "1 inhaler"
        assert result["national_drug_code"] == "00173-0696-00"

    def test_inactive_medication_shows_end_date(self):
        result = _build_medication(
            make_medication(
                status="inactive",
                end_date=make_medication().start_date.replace(year=2020),
            )
        )

        assert result["is_active"] is False
        assert result["status_label"] == "Inactive"
        assert result["end_date"] == "Sep 04, 2020"

    def test_stopped_status_buckets_as_inactive_keeping_label(self):
        """A non-active/inactive status (e.g. "stopped") must still bucket as
        inactive so it isn't orphaned from both filters, while the badge keeps
        the real status text."""
        result = _build_medication(make_medication(status="stopped"))

        assert result["is_active"] is False
        assert result["status_label"] == "Stopped"

    def test_empty_status_buckets_as_inactive_with_no_label(self):
        result = _build_medication(make_medication(status=""))

        assert result["is_active"] is False
        assert result["status_label"] == ""

    def test_missing_fields_never_render_none(self):
        result = _build_medication(
            make_medication(
                status="",
                start_date=None,
                end_date=None,
                clinical_quantity_description="",
                national_drug_code="",
            )
        )

        assert result["status_label"] == ""
        assert result["start_date"] == ""
        assert result["quantity"] == ""
        assert result["national_drug_code"] == ""
        assert "None" not in [v for v in result.values() if isinstance(v, str)]


class TestHandle:
    def test_handle_renders_committed_meds_in_modal(self, mock_event, mock_patient):
        handler = MedicationHistoryButton(event=mock_event)
        meds = [
            make_medication(),
            make_medication(
                status="inactive",
                codings=[make_coding(FDB_SYSTEM, "ASPIRIN EC 500 MG")],
            ),
            make_medication(
                status="stopped",
                codings=[make_coding(FDB_SYSTEM, "PREDNISONE 10 MG")],
            ),
        ]

        with patch(f"{MODULE}.Patient.objects") as mock_patient_objects:
            mock_patient_objects.get.return_value = mock_patient
            with patch(f"{MODULE}.Medication.objects") as mock_meds:
                chain = (
                    mock_meds.filter.return_value.prefetch_related.return_value.order_by.return_value
                )
                chain.__getitem__.return_value = meds
                with patch(
                    f"{MODULE}.render_to_string", return_value="<html>ok</html>"
                ) as mock_render:
                    effects = handler.handle()

                    mock_patient_objects.get.assert_called_once_with(id="patient-123")
                    mock_meds.filter.assert_called_once_with(
                        patient=mock_patient,
                        deleted=False,
                        entered_in_error__isnull=True,
                    )

                    template_name, context = mock_render.call_args[0]
                    assert template_name == "templates/medication_history.html"
                    assert context["patient_name"] == "Jane Doe"
                    assert len(context["medications"]) == 3
                    assert context["medications"][1]["name"] == "ASPIRIN EC 500 MG"
                    # "stopped" must count under inactive, not vanish.
                    assert context["active_count"] == 1
                    assert context["inactive_count"] == 2

        assert len(effects) == 1
        assert effects[0].type == EffectType.LAUNCH_MODAL
        assert "<html>ok</html>" in effects[0].payload
        assert "right_chart_pane_large" in effects[0].payload

    def test_handle_renders_empty_state_when_no_meds(self, mock_event, mock_patient):
        handler = MedicationHistoryButton(event=mock_event)

        with patch(f"{MODULE}.Patient.objects") as mock_patient_objects:
            mock_patient_objects.get.return_value = mock_patient
            with patch(f"{MODULE}.Medication.objects") as mock_meds:
                chain = (
                    mock_meds.filter.return_value.prefetch_related.return_value.order_by.return_value
                )
                chain.__getitem__.return_value = []
                with patch(
                    f"{MODULE}.render_to_string", return_value="<html>empty</html>"
                ) as mock_render:
                    effects = handler.handle()

                    assert mock_render.call_args[0][1]["medications"] == []

        assert len(effects) == 1
        assert effects[0].type == EffectType.LAUNCH_MODAL

    def test_handle_returns_empty_when_patient_missing(self, mock_event):
        handler = MedicationHistoryButton(event=mock_event)

        with patch(f"{MODULE}.Patient.objects") as mock_patient_objects:
            mock_patient_objects.get.side_effect = Patient.DoesNotExist
            with patch(f"{MODULE}.log") as mock_log:
                effects = handler.handle()

                mock_patient_objects.get.assert_called_once_with(id="patient-123")
                mock_log.warning.assert_called_once()

        assert effects == []


def test_history_limit_is_capped():
    assert HISTORY_LIMIT == 250
