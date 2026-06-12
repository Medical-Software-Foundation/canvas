"""Tests for cash_pay_profile_field/protocols/patient_metadata_fields.py."""

from unittest.mock import MagicMock, call, patch

from canvas_sdk.effects.patient_metadata import InputType
from canvas_sdk.events import EventType

from cash_pay_profile_field.protocols.patient_metadata_fields import (
    PatientMetadataFields,
)

MODULE = "cash_pay_profile_field.protocols.patient_metadata_fields"


class TestRespondsTo:
    """The handler must subscribe to the additional-fields event."""

    def test_responds_to_additional_fields_event(self):
        assert PatientMetadataFields.RESPONDS_TO == EventType.Name(
            EventType.PATIENT_METADATA__GET_ADDITIONAL_FIELDS
        )


class TestCompute:
    """compute() builds the optional 'Cash Pay Patient' single-select field."""

    def test_compute_builds_cash_pay_select_field(self):
        with patch(f"{MODULE}.PatientMetadataCreateFormEffect") as mock_form_effect, \
             patch(f"{MODULE}.FormField") as mock_form_field:
            mock_field = MagicMock()
            mock_form_field.return_value = mock_field

            mock_effect = MagicMock()
            mock_form_effect.return_value = mock_effect

            mock_event = MagicMock()
            handler = PatientMetadataFields(mock_event)
            effects = handler.compute()

            # 1. Verify FormField was constructed with the exact field config:
            #    optional, editable, Yes/No select stored under cash_pay_patient.
            assert mock_form_field.mock_calls == [
                call(
                    key="cash_pay_patient",
                    label="Cash Pay Patient",
                    type=InputType.SELECT,
                    required=False,
                    editable=True,
                    options=["Yes", "No"],
                )
            ]

            # 2. Verify the form effect was built with that single field and applied.
            assert mock_form_effect.mock_calls == [
                call(form_fields=[mock_field]),
                call().apply(),
            ]

            # 3. Verify the constructed effect was only used to call apply().
            assert mock_effect.mock_calls == [call.apply()]

            # 4. Verify the field mock had no further interactions.
            assert mock_field.mock_calls == []

            # 5. Verify the event was never inspected by compute().
            assert mock_event.mock_calls == []

            # Output: compute returns exactly the applied effect.
            assert effects == [mock_effect.apply.return_value]
