"""Tests for CarryForwardActionButton protocol."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from carry_forward.protocols.carry_forward_action_button import CarryForwardActionButton


class TestNoteBodyIsEmpty:
    """Tests for note_body_is_empty method."""

    def test_empty_note_body(self):
        """Test that a note with empty body is identified as empty."""
        handler = CarryForwardActionButton()
        note = MagicMock()
        note.body = [{"type": "text", "value": ""}]

        assert handler.note_body_is_empty(note) is True

    def test_multiple_empty_entries(self):
        """Test that a note with multiple empty entries is identified as empty."""
        handler = CarryForwardActionButton()
        note = MagicMock()
        note.body = [
            {"type": "text", "value": ""},
            {"type": "text", "value": ""},
            {"type": "text", "value": ""}
        ]

        assert handler.note_body_is_empty(note) is True

    def test_note_with_content(self):
        """Test that a note with content is not identified as empty."""
        handler = CarryForwardActionButton()
        note = MagicMock()
        note.body = [{"type": "text", "value": "some content"}]

        assert handler.note_body_is_empty(note) is False

    def test_note_with_mixed_content(self):
        """Test that a note with some empty and some non-empty entries is not empty."""
        handler = CarryForwardActionButton()
        note = MagicMock()
        note.body = [
            {"type": "text", "value": ""},
            {"type": "command", "value": "diagnose"}
        ]

        assert handler.note_body_is_empty(note) is False


class TestFindPreviousNote:
    """Tests for find_previous_note method."""

    def test_finds_most_recent_previous_note(self, mock_note, mock_previous_note):
        """Test that the most recent non-empty previous note is found."""
        handler = CarryForwardActionButton()

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_objects:
            mock_objects.filter.return_value.order_by.return_value = [mock_previous_note]

            result = handler.find_previous_note(mock_note)

            assert result == mock_previous_note
            mock_objects.filter.assert_called_once()
            call_kwargs = mock_objects.filter.call_args[1]
            assert call_kwargs["patient"] == mock_note.patient
            assert call_kwargs["note_type_version__name__in"] == handler.VISIBLE_NOTE_TYPE_NAMES
            assert call_kwargs["datetime_of_service__lt"] == mock_note.datetime_of_service

    def test_skips_empty_notes(self, mock_note):
        """Test that empty previous notes are skipped."""
        handler = CarryForwardActionButton()

        empty_note = MagicMock()
        empty_note.body = [{"type": "text", "value": ""}]
        empty_note.dbid = "empty-note"

        non_empty_note = MagicMock()
        non_empty_note.body = [{"type": "command", "value": "content"}]
        non_empty_note.dbid = "non-empty-note"

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_objects:
            mock_objects.filter.return_value.order_by.return_value = [empty_note, non_empty_note]

            result = handler.find_previous_note(mock_note)

            assert result == non_empty_note

    def test_returns_none_when_no_previous_notes(self, mock_note):
        """Test that None is returned when no previous notes exist."""
        handler = CarryForwardActionButton()

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_objects:
            mock_objects.filter.return_value.order_by.return_value = []

            result = handler.find_previous_note(mock_note)

            assert result is None

    def test_returns_none_when_all_previous_notes_empty(self, mock_note):
        """Test that None is returned when all previous notes are empty."""
        handler = CarryForwardActionButton()

        empty_note1 = MagicMock()
        empty_note1.body = [{"type": "text", "value": ""}]

        empty_note2 = MagicMock()
        empty_note2.body = [{"type": "text", "value": ""}]

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_objects:
            mock_objects.filter.return_value.order_by.return_value = [empty_note1, empty_note2]

            result = handler.find_previous_note(mock_note)

            assert result is None


class TestVisible:
    """Tests for visible method - button visibility logic."""

    def test_visible_when_all_conditions_met(self, mock_event, mock_note, mock_previous_note):
        """Test button is visible when note type correct, note empty, and previous note exists."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_objects:
            mock_objects.get.return_value = mock_note
            mock_objects.filter.return_value.order_by.return_value = [mock_previous_note]

            result = handler.visible()

            assert result is True
            mock_objects.get.assert_called_once_with(dbid="test-note-123")

    def test_hidden_when_wrong_note_type(self, mock_event, mock_note):
        """Test button is hidden when note type is not in VISIBLE_NOTE_TYPE_NAMES."""
        handler = CarryForwardActionButton()
        handler.event = mock_event
        mock_note.note_type_version.name = "Progress Note"

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_objects:
            mock_objects.get.return_value = mock_note

            result = handler.visible()

            assert result is False

    def test_hidden_when_note_not_empty(self, mock_event, mock_note, mock_previous_note):
        """Test button is hidden when note already has content."""
        handler = CarryForwardActionButton()
        handler.event = mock_event
        mock_note.body = [{"type": "command", "value": "existing content"}]

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_objects:
            mock_objects.get.return_value = mock_note
            mock_objects.filter.return_value.order_by.return_value = [mock_previous_note]

            result = handler.visible()

            assert result is False

    def test_hidden_when_no_previous_note(self, mock_event, mock_note):
        """Test button is hidden when no previous note exists."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_objects:
            mock_objects.get.return_value = mock_note
            mock_objects.filter.return_value.order_by.return_value = []

            result = handler.visible()

            assert result is False

    def test_visible_for_telehealth_note(self, mock_event, mock_note, mock_previous_note):
        """Test button is visible for Telehealth note type."""
        handler = CarryForwardActionButton()
        handler.event = mock_event
        mock_note.note_type_version.name = "Telehealth"

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_objects:
            mock_objects.get.return_value = mock_note
            mock_objects.filter.return_value.order_by.return_value = [mock_previous_note]

            result = handler.visible()

            assert result is True

    def test_visible_for_phone_call_note(self, mock_event, mock_note, mock_previous_note):
        """Test button is visible for Phone call note type."""
        handler = CarryForwardActionButton()
        handler.event = mock_event
        mock_note.note_type_version.name = "Phone call"

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_objects:
            mock_objects.get.return_value = mock_note
            mock_objects.filter.return_value.order_by.return_value = [mock_previous_note]

            result = handler.visible()

            assert result is True


class TestHandle:
    """Tests for handle method - carrying forward commands."""

    def test_handle_diagnose_command(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward a diagnose command."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "diagnose"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "diagnose": {"value": "I10"},
            "background": "Patient has hypertension",
            "today_assessment": "BP elevated",
            "approximate_date_of_onset": {"date": "2024-01-01"}
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.get.return_value = mock_note
                mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                effects = handler.handle()

                assert len(effects) == 1
                mock_cmd_objects.filter.assert_called_once()
                call_kwargs = mock_cmd_objects.filter.call_args[1]
                assert call_kwargs["note"] == mock_previous_note
                assert call_kwargs["committer__isnull"] is False
                assert call_kwargs["entered_in_error__isnull"] is True

    def test_handle_hpi_command(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward an HPI command."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "hpi"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "narrative": "Patient presents with chest pain"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.get.return_value = mock_note
                mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                effects = handler.handle()

                assert len(effects) == 1

    def test_handle_plan_command(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward a plan command."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "plan"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "narrative": "Continue current medications"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.get.return_value = mock_note
                mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                effects = handler.handle()

                assert len(effects) == 1

    def test_handle_reason_for_visit_command(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward a reason for visit command."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "reasonForVisit"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "coding": {"value": "Z00.00"},
            "comment": "Annual checkup"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                with patch("carry_forward.protocols.carry_forward_action_button.ReasonForVisitSettingCoding.objects") as mock_rfv:
                    mock_note_objects.get.return_value = mock_note
                    mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                    mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                    mock_coding = MagicMock()
                    mock_coding.id = "rfv-coding-123"
                    mock_rfv.filter.return_value.order_by.return_value.last.return_value = mock_coding

                    effects = handler.handle()

                    assert len(effects) == 1
                    mock_rfv.filter.assert_called_once_with(code="Z00.00")

    def test_handle_vitals_command(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward a vitals command."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "vitals"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "height": "70",
            "weight_lbs": "180",
            "weight_oz": "0",
            "waist_circumference": "36",
            "body_temperature": "99",
            "blood_pressure_systole": "120",
            "blood_pressure_diastole": "80",
            "pulse": "72",
            "respiration_rate": "16",
            "oxygen_saturation": "98",
            "body_temperature_site": "1",
            "blood_pressure_position_and_site": "0",
            "pulse_rhythm": "0",
            "note": "Normal vitals"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.get.return_value = mock_note
                mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                effects = handler.handle()

                assert len(effects) == 1

    def test_handle_perform_command(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward a perform command."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "perform"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "perform": {"value": "99213"},
            "notes": "Office visit"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.get.return_value = mock_note
                mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                effects = handler.handle()

                assert len(effects) == 1

    def test_handle_multiple_commands(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward multiple commands."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_cmd1 = MagicMock()
        mock_cmd1.schema_key = "hpi"
        mock_cmd1.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_cmd1.data = {"narrative": "HPI text"}

        mock_cmd2 = MagicMock()
        mock_cmd2.schema_key = "plan"
        mock_cmd2.created = datetime(2024, 12, 8, 10, 31, 0)
        mock_cmd2.data = {"narrative": "Plan text"}

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.get.return_value = mock_note
                mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                mock_cmd_objects.filter.return_value.order_by.return_value = [mock_cmd1, mock_cmd2]

                effects = handler.handle()

                # Returns 1 BatchOriginateCommandEffect wrapping both commands
                assert len(effects) == 1

    def test_handle_unsupported_command_skipped(self, mock_event, mock_note, mock_previous_note):
        """Test that unsupported command types are skipped."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_cmd1 = MagicMock()
        mock_cmd1.schema_key = "unsupportedCommand"  # Not in schema_map
        mock_cmd1.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_cmd1.data = {}

        mock_cmd2 = MagicMock()
        mock_cmd2.schema_key = "plan"
        mock_cmd2.created = datetime(2024, 12, 8, 10, 31, 0)
        mock_cmd2.data = {"narrative": "Plan text"}

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.get.return_value = mock_note
                mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                mock_cmd_objects.filter.return_value.order_by.return_value = [mock_cmd1, mock_cmd2]

                effects = handler.handle()

                # Only the plan command should be carried forward
                assert len(effects) == 1

    def test_handle_no_commands_returns_empty(self, mock_event, mock_note, mock_previous_note):
        """Test that batch effect is returned even when previous note has no commands."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.get.return_value = mock_note
                mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                mock_cmd_objects.filter.return_value.order_by.return_value = []

                effects = handler.handle()

                # Returns 1 BatchOriginateCommandEffect with empty commands list
                assert len(effects) == 1

    def test_handle_diagnose_with_missing_optional_fields(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward diagnose command with missing optional fields."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "diagnose"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "diagnose": {"value": "I10"},
            "background": None,
            "today_assessment": None,
            "approximate_date_of_onset": None
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.get.return_value = mock_note
                mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                effects = handler.handle()

                assert len(effects) == 1

    def test_handle_vitals_with_none_values(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward vitals command with None values."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "vitals"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "height": None,
            "weight_lbs": None,
            "weight_oz": None,
            "waist_circumference": None,
            "body_temperature": None,
            "blood_pressure_systole": "120",
            "blood_pressure_diastole": "80",
            "pulse": None,
            "respiration_rate": None,
            "oxygen_saturation": None,
            "body_temperature_site": None,
            "blood_pressure_position_and_site": "0",
            "pulse_rhythm": None,
            "note": None
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.get.return_value = mock_note
                mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                effects = handler.handle()

                assert len(effects) == 1

    def test_handle_assess_command(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward an assess command."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "assess"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "condition": {"value": "condition-123"},
            "background": "History of hypertension",
            "status": "stable",
            "narrative": "Blood pressure well controlled"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                with patch("carry_forward.protocols.carry_forward_action_button.Condition.objects") as mock_condition:
                    mock_note_objects.get.return_value = mock_note
                    mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                    mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                    mock_cond = MagicMock()
                    mock_cond.id = "cond-uuid-123"
                    mock_condition.filter.return_value.first.return_value = mock_cond

                    effects = handler.handle()

                    assert len(effects) == 1

    def test_handle_follow_up_command(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward a follow up command."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "followUp"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "coding": {"value": "Z00.00"},
            "reason_for_visit": "Follow up visit",
            "requested_date": {"date": "2024-12-15"},
            "note_type": {"value": "note-type-123"},
            "comment": "Check labs"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                with patch("carry_forward.protocols.carry_forward_action_button.ReasonForVisitSettingCoding.objects") as mock_rfv:
                    with patch("carry_forward.protocols.carry_forward_action_button.NoteType.objects") as mock_nt:
                        mock_note_objects.get.return_value = mock_note
                        mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                        mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                        mock_coding = MagicMock()
                        mock_coding.id = "rfv-coding-123"
                        mock_rfv.filter.return_value.order_by.return_value.last.return_value = mock_coding

                        mock_note_type = MagicMock()
                        mock_note_type.id = "note-type-uuid-123"
                        mock_nt.filter.return_value.first.return_value = mock_note_type

                        effects = handler.handle()

                        assert len(effects) == 1

    def test_handle_imaging_order_command(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward an imaging order command."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "imagingOrder"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "image": {"value": "CT, abdomen and pelvis; w/o contrast (CPT: 74176)"},
            "indications": [{"value": "I10"}],
            "priority": "Routine",
            "additional_details": "Check for abnormalities",
            "imaging_center": {
                "extra": {
                    "contact": {
                        "firstName": "John",
                        "lastName": "Doe",
                        "practiceName": "Radiology Center",
                        "specialty": "Radiology",
                        "businessAddress": "123 Main St",
                        "businessPhone": "555-1234",
                        "businessFax": "555-5678",
                        "notes": "Preferred imaging center"
                    }
                }
            },
            "comment": "Urgent review needed",
            "ordering_provider": {"value": "provider-123"},
            "linked_items": [{"value": "item-1"}]
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                with patch("carry_forward.protocols.carry_forward_action_button.Staff.objects") as mock_staff:
                    mock_note_objects.get.return_value = mock_note
                    mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                    mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                    mock_provider = MagicMock()
                    mock_provider.id = "provider-uuid-123"
                    mock_staff.filter.return_value.first.return_value = mock_provider

                    effects = handler.handle()

                    assert len(effects) == 1

    def test_handle_instruct_command(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward an instruct command."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "instruct"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "instruct": {
                "extra": {
                    "coding": [{
                        "system": "http://snomed.info/sct",
                        "code": "386661006",
                        "display": "Fever management"
                    }]
                }
            },
            "narrative": "Take medication with food"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.get.return_value = mock_note
                mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                effects = handler.handle()

                assert len(effects) == 1

    def test_handle_lab_order_command(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward a lab order command."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "labOrder"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "lab_partner": {"value": "quest"},
            "tests": [{"value": "test-123"}, {"value": "test-456"}],
            "ordering_provider": {"value": "provider-123"},
            "diagnosis": [{"value": "I10"}],
            "fasting_status": True,
            "comment": "Draw in AM"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                with patch("carry_forward.protocols.carry_forward_action_button.Staff.objects") as mock_staff:
                    mock_note_objects.get.return_value = mock_note
                    mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                    mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                    mock_provider = MagicMock()
                    mock_provider.id = "provider-uuid-123"
                    mock_staff.filter.return_value.first.return_value = mock_provider

                    effects = handler.handle()

                    assert len(effects) == 1

    def test_handle_refer_command(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward a refer command."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "refer"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "refer_to": {
                "extra": {
                    "contact": {
                        "firstName": "Jane",
                        "lastName": "Smith",
                        "practiceName": "Cardiology Specialists",
                        "specialty": "Cardiology",
                        "businessAddress": "456 Oak Ave",
                        "businessPhone": "555-9999",
                        "businessFax": "555-8888",
                        "notes": "Preferred cardiologist"
                    }
                }
            },
            "indications": [{"value": "I10"}],
            "clinical_question": "Specialized intervention",
            "priority": "Urgent",
            "notes_to_specialist": "Please evaluate chest pain",
            "include_visit_note": True,
            "internal_comment": "Patient prefers Dr. Smith",
            "linked_items": [{"value": "item-1"}]
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.get.return_value = mock_note
                mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                effects = handler.handle()

                assert len(effects) == 1

    def test_handle_task_command(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward a task command."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "task"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "title": "Follow up with patient",
            "assign_to": {"value": "assignee-123"},
            "due_date": "2024-12-15",
            "comment": "Call patient regarding test results",
            "labels": [{"text": "urgent"}, {"text": "follow-up"}],
            "linked_items": [{"value": "item-1"}]
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.get.return_value = mock_note
                mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                effects = handler.handle()

                assert len(effects) == 1

    def test_handle_refill_command(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward a refill command."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "refill"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "prescribe": {"value": "med-123"},
            "indications": [{"value": "cond-123"}],
            "sig": "Take 1 tablet daily",
            "days_supply": "30",
            "quantity_to_dispense": "30",
            "type_to_dispense": {
                "extra": {
                    "representative_ndc": "12345-678-90",
                    "erx_ncpdp_script_quantity_qualifier_code": "C48542"
                }
            },
            "refills": "3",
            "substitutions": "allowed",
            "pharmacy": {"value": "pharmacy-123"},
            "prescriber": {"value": "provider-123"},
            "supervising_provider": {"value": "supervisor-123"},
            "note_to_pharmacist": "Generic OK"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                with patch("carry_forward.protocols.carry_forward_action_button.MedicationCoding.objects") as mock_med_coding:
                    with patch("carry_forward.protocols.carry_forward_action_button.ConditionCoding.objects") as mock_cond_coding:
                        with patch("carry_forward.protocols.carry_forward_action_button.Staff.objects") as mock_staff:
                            mock_note_objects.get.return_value = mock_note
                            mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                            mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                            mock_coding = MagicMock()
                            mock_coding.code = "fdb-code-123"
                            mock_med_coding.filter.return_value.first.return_value = mock_coding

                            mock_cond = MagicMock()
                            mock_cond.code = "I10"
                            mock_cond_coding.filter.return_value.first.return_value = mock_cond

                            mock_provider = MagicMock()
                            mock_provider.id = "provider-uuid-123"
                            mock_staff.filter.return_value.first.return_value = mock_provider

                            effects = handler.handle()

                            assert len(effects) == 1

    def test_handle_update_goal_command(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward an update goal command."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "updateGoal"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "goal_statement": {"value": "goal-123"},
            "due_date": "2024-12-31",
            "achievement_status": "improving",
            "priority": "high-priority",
            "progress": "Patient making good progress"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                with patch("carry_forward.protocols.carry_forward_action_button.Goal.objects") as mock_goal:
                    mock_note_objects.get.return_value = mock_note
                    mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                    mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                    mock_goal_obj = MagicMock()
                    mock_goal_obj.id = "goal-uuid-123"
                    mock_goal.filter.return_value.first.return_value = mock_goal_obj

                    effects = handler.handle()

                    assert len(effects) == 1

    def test_handle_goal_command_transforms_to_update_goal(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward a goal command (transforms to UpdateGoalCommand)."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "goal"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.anchor_object = MagicMock()
        mock_command.anchor_object.id = "goal-uuid-123"
        mock_command.data = {
            "goal_statement": "Lose 10 pounds",
            "start_date": "2024-01-01",
            "due_date": "2024-12-31",
            "achievement_status": "in-progress",
            "priority": "medium-priority",
            "progress": "Lost 3 pounds so far"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.get.return_value = mock_note
                mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                effects = handler.handle()

                # Goal command should be transformed to UpdateGoalCommand
                assert len(effects) == 1


class TestSmartCarryForward:
    """Tests for smart carry forward transformations."""

    def test_handle_update_diagnosis_command_transforms_to_assess(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward an update diagnosis command (transforms to AssessCommand)."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "updateDiagnosis"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.anchor_object = MagicMock()
        mock_command.anchor_object.id = "condition-uuid-123"
        mock_command.data = {
            "new_condition": {"value": "I10"},
            "background": "Updated diagnosis",
            "narrative": "Changed diagnosis code"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                with patch("carry_forward.protocols.carry_forward_action_button.Condition.objects") as mock_condition:
                    mock_note_objects.get.return_value = mock_note
                    mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                    mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                    mock_cond = MagicMock()
                    mock_cond.id = "condition-uuid-456"
                    mock_condition.filter.return_value.order_by.return_value.last.return_value = mock_cond

                    effects = handler.handle()

                    # updateDiagnosis should be transformed to AssessCommand
                    assert len(effects) == 1

    def test_handle_prescribe_command_transforms_to_refill(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward a prescribe command (transforms to RefillCommand)."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "prescribe"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "prescribe": {"value": "12345"},
            "indications": [{"value": "cond-123"}],
            "sig": "Take 1 tablet daily",
            "days_supply": "30",
            "quantity_to_dispense": "30",
            "type_to_dispense": {
                "extra": {
                    "representative_ndc": "12345-678-90",
                    "erx_ncpdp_script_quantity_qualifier_code": "C48542"
                }
            },
            "refills": "3",
            "substitutions": "allowed",
            "pharmacy": {"value": "pharmacy-123"},
            "prescriber": {"value": "provider-123"},
            "supervising_provider": {"value": "supervisor-123"},
            "note_to_pharmacist": "Generic OK"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                with patch("carry_forward.protocols.carry_forward_action_button.ConditionCoding.objects") as mock_cond_coding:
                    with patch("carry_forward.protocols.carry_forward_action_button.Staff.objects") as mock_staff:
                        mock_note_objects.get.return_value = mock_note
                        mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                        mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                        mock_cond = MagicMock()
                        mock_cond.code = "I10"
                        mock_cond_coding.filter.return_value.first.return_value = mock_cond

                        mock_provider = MagicMock()
                        mock_provider.id = "provider-uuid-123"
                        mock_staff.filter.return_value.first.return_value = mock_provider

                        effects = handler.handle()

                        # prescribe should be transformed to RefillCommand
                        assert len(effects) == 1

    def test_handle_adjust_prescription_command_transforms_to_refill(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward an adjust prescription command (transforms to RefillCommand)."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "adjustPrescription"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "prescribe": {"value": "med-123"},
            "change_medication_to": {"value": "67890"},
            "indications": [{"value": "cond-123"}],
            "sig": "Take 2 tablets daily",
            "days_supply": "30",
            "quantity_to_dispense": "60",
            "type_to_dispense": {
                "extra": {
                    "representative_ndc": "67890-123-45",
                    "erx_ncpdp_script_quantity_qualifier_code": "C48542"
                }
            },
            "refills": "2",
            "substitutions": "allowed",
            "pharmacy": {"value": "pharmacy-123"},
            "prescriber": {"value": "provider-123"},
            "supervising_provider": {"value": "supervisor-123"},
            "note_to_pharmacist": "Increased dose"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                with patch("carry_forward.protocols.carry_forward_action_button.ConditionCoding.objects") as mock_cond_coding:
                    with patch("carry_forward.protocols.carry_forward_action_button.Staff.objects") as mock_staff:
                        mock_note_objects.get.return_value = mock_note
                        mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                        mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                        mock_cond = MagicMock()
                        mock_cond.code = "I10"
                        mock_cond_coding.filter.return_value.first.return_value = mock_cond

                        mock_provider = MagicMock()
                        mock_provider.id = "provider-uuid-123"
                        mock_staff.filter.return_value.first.return_value = mock_provider

                        effects = handler.handle()

                        # adjustPrescription should be transformed to RefillCommand
                        assert len(effects) == 1

    def test_handle_change_medication_command_transforms_to_refill(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward a change medication command (transforms to RefillCommand)."""
        handler = CarryForwardActionButton()
        handler.event = mock_event
        handler.note = mock_note

        mock_command = MagicMock()
        mock_command.schema_key = "changeMedication"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "medication": {"value": "med-456"},
            "sig": "Take 1 tablet twice daily"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                with patch("carry_forward.protocols.carry_forward_action_button.MedicationCoding.objects") as mock_med_coding:
                    # Set up the basic mocks
                    mock_note_objects.get.return_value = mock_note
                    mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]

                    # Mock the MedicationCoding lookup for changeMedication
                    mock_coding = MagicMock()
                    mock_coding.code = "fdb-code-789"
                    mock_med_coding.filter.return_value.first.return_value = mock_coding

                    # Mock the Command lookups for finding the source prescription
                    mock_prescribe_cmd = MagicMock()
                    mock_prescribe_cmd.schema_key = "prescribe"
                    mock_prescribe_cmd.modified = datetime(2024, 12, 7, 10, 0, 0)
                    mock_prescribe_cmd.data = {
                        "prescribe": {"value": "fdb-code-789"},
                        "indications": [],
                        "sig": "Original sig",
                        "pharmacy": {"value": "pharmacy-123"}
                    }

                    # Set up mock to return the changeMedication command first, then prescribe command for lookups
                    def command_filter_side_effect(*args, **kwargs):
                        mock_filter = MagicMock()
                        mock_order = MagicMock()

                        # First call returns the changeMedication command
                        if 'note' in kwargs:
                            mock_order.return_value = [mock_command]
                        else:
                            # Subsequent calls for finding source command
                            if 'schema_key' in kwargs and kwargs.get('schema_key') == 'prescribe':
                                mock_order.return_value.last.return_value = mock_prescribe_cmd
                            else:
                                mock_order.return_value.last.return_value = None

                        mock_filter.order_by = MagicMock(return_value=mock_order.return_value if 'note' in kwargs else mock_order)
                        return mock_filter

                    mock_cmd_objects.filter = MagicMock(side_effect=command_filter_side_effect)

                    effects = handler.handle()

                    # changeMedication should be transformed to RefillCommand
                    assert len(effects) == 1


class TestQuestionnaireCommands:
    """Tests for questionnaire-based commands with editing effects."""

    def test_handle_questionnaire_command(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward a questionnaire command."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "questionnaire"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "questionnaire": {
                "extra": {
                    "pk": "questionnaire-123"
                }
            },
            "question-1": "Answer 1",
            "question-2": "selected-option-id",
            "skip-1": False,
            "skip-2": True
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                with patch("carry_forward.protocols.carry_forward_action_button.Questionnaire.objects") as mock_q:
                    mock_note_objects.get.return_value = mock_note
                    mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                    mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                    mock_questionnaire = MagicMock()
                    mock_questionnaire.id = "q-uuid-123"
                    mock_q.filter.return_value.first.return_value = mock_questionnaire

                    effects = handler.handle()

                    # Questionnaire commands return batch effect + editing effect
                    assert len(effects) >= 1

    def test_handle_ros_command(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward a review of systems command."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "ros"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "questionnaire": {
                "extra": {
                    "pk": "ros-questionnaire-456"
                }
            },
            "question-1": "Negative",
            "question-2": "Positive"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                with patch("carry_forward.protocols.carry_forward_action_button.Questionnaire.objects") as mock_q:
                    mock_note_objects.get.return_value = mock_note
                    mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                    mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                    mock_questionnaire = MagicMock()
                    mock_questionnaire.id = "ros-uuid-456"
                    mock_q.filter.return_value.first.return_value = mock_questionnaire

                    effects = handler.handle()

                    # ROS commands return batch effect + editing effect
                    assert len(effects) >= 1

    def test_handle_exam_command(self, mock_event, mock_note, mock_previous_note):
        """Test carrying forward a physical exam command."""
        handler = CarryForwardActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.schema_key = "exam"
        mock_command.created = datetime(2024, 12, 8, 10, 30, 0)
        mock_command.data = {
            "questionnaire": {
                "extra": {
                    "pk": "exam-questionnaire-789"
                }
            },
            "question-1": "Normal",
            "question-2": "Abnormal findings"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Note.objects") as mock_note_objects:
            with patch("carry_forward.protocols.carry_forward_action_button.Command.objects") as mock_cmd_objects:
                with patch("carry_forward.protocols.carry_forward_action_button.Questionnaire.objects") as mock_q:
                    mock_note_objects.get.return_value = mock_note
                    mock_note_objects.filter.return_value.order_by.return_value = [mock_previous_note]
                    mock_cmd_objects.filter.return_value.order_by.return_value = [mock_command]

                    mock_questionnaire = MagicMock()
                    mock_questionnaire.id = "exam-uuid-789"
                    mock_q.filter.return_value.first.return_value = mock_questionnaire

                    effects = handler.handle()

                    # Exam commands return batch effect + editing effect
                    assert len(effects) >= 1


class TestCarryForwardMethods:
    """Direct unit tests for all _carry_forward_* methods."""

    def test_carry_forward_diagnose(self):
        """Test _carry_forward_diagnose method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {
            "diagnose": {"value": "I10"},
            "background": "Patient has hypertension",
            "today_assessment": "BP elevated",
            "approximate_date_of_onset": {"date": "2024-01-01"}
        }

        result = handler._carry_forward_diagnose(effect, data)

        assert result.icd10_code == "I10"
        assert result.background == "Patient has hypertension"
        assert result.today_assessment == "BP elevated"

    def test_carry_forward_diagnose_missing_optional(self):
        """Test _carry_forward_diagnose with missing optional fields."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {
            "diagnose": {"value": "I10"},
            "background": None,
            "today_assessment": None,
            "approximate_date_of_onset": None
        }

        result = handler._carry_forward_diagnose(effect, data)

        assert result.icd10_code == "I10"
        assert result.background == ""
        assert result.today_assessment == ""

    def test_carry_forward_goal(self):
        """Test _carry_forward_goal method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {
            "goal_statement": "Lose 10 pounds",
            "start_date": "2024-01-01",
            "due_date": "2024-12-31",
            "achievement_status": "in-progress",
            "priority": "medium-priority",
            "progress": "Lost 3 pounds so far"
        }

        result = handler._carry_forward_goal(effect, data)

        assert result.goal_statement == "Lose 10 pounds"
        assert result.achievement_status is not None
        assert result.priority is not None
        assert result.progress == "Lost 3 pounds so far"

    def test_carry_forward_prescribe(self):
        """Test _carry_forward_prescribe method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {
            "prescribe": {"value": "12345"},
            "indications": [{"value": "cond-123"}],
            "sig": "Take 1 tablet daily",
            "days_supply": "30",
            "quantity_to_dispense": "30",
            "type_to_dispense": {
                "extra": {
                    "representative_ndc": "12345-678-90",
                    "erx_ncpdp_script_quantity_qualifier_code": "C48542"
                }
            },
            "refills": "3",
            "substitutions": "allowed",
            "pharmacy": {"value": "pharmacy-123"},
            "prescriber": {"value": "provider-123"},
            "supervising_provider": {"value": "supervisor-123"},
            "note_to_pharmacist": "Generic OK"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.ConditionCoding.objects") as mock_cond_coding:
            with patch("carry_forward.protocols.carry_forward_action_button.Staff.objects") as mock_staff:
                mock_cond = MagicMock()
                mock_cond.code = "I10"
                mock_cond_coding.filter.return_value.first.return_value = mock_cond

                mock_provider = MagicMock()
                mock_provider.id = "provider-uuid-123"
                mock_staff.filter.return_value.first.return_value = mock_provider

                result = handler._carry_forward_prescribe(effect, data)

                assert result.fdb_code == "12345"
                assert result.sig == "Take 1 tablet daily"
                assert result.days_supply == "30"
                assert result.note_to_pharmacist == "Generic OK"

    def test_carry_forward_plan(self):
        """Test _carry_forward_plan method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {"narrative": "Continue current medications"}

        result = handler._carry_forward_plan(effect, data)

        assert result.narrative == "Continue current medications"

    def test_carry_forward_hpi(self):
        """Test _carry_forward_hpi method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {"narrative": "Patient presents with chest pain"}

        result = handler._carry_forward_hpi(effect, data)

        assert result.narrative == "Patient presents with chest pain"

    def test_carry_forward_reason_for_visit(self):
        """Test _carry_forward_reason_for_visit method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {
            "coding": {"value": "Z00.00"},
            "comment": "Annual checkup"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.ReasonForVisitSettingCoding.objects") as mock_rfv:
            mock_coding = MagicMock()
            mock_coding.id = "rfv-coding-123"
            mock_rfv.filter.return_value.order_by.return_value.last.return_value = mock_coding

            result = handler._carry_forward_reason_for_visit(effect, data)

            assert result.coding == "rfv-coding-123"
            assert result.structured is True
            assert result.comment == "Annual checkup"

    def test_carry_forward_assess(self):
        """Test _carry_forward_assess method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {
            "condition": {"value": "condition-123"},
            "background": "History of hypertension",
            "status": "stable",
            "narrative": "Blood pressure well controlled"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Condition.objects") as mock_condition:
            mock_cond = MagicMock()
            mock_cond.id = "cond-uuid-123"
            mock_condition.filter.return_value.first.return_value = mock_cond

            result = handler._carry_forward_assess(effect, data)

            assert result.background == "History of hypertension"
            assert result.narrative == "Blood pressure well controlled"

    def test_carry_forward_diagnose_to_assess(self):
        """Test _carry_forward_diagnose_to_assess method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        command = MagicMock()
        command.anchor_object = MagicMock()
        command.anchor_object.id = "condition-uuid-123"
        data = {
            "diagnose": {"value": "I10"},
            "background": "Patient has hypertension",
            "today_assessment": "BP elevated"
        }

        result = handler._carry_forward_diagnose_to_assess(effect, data, command)

        assert result.condition_id == "condition-uuid-123"
        assert result.background == "Patient has hypertension"
        assert result.narrative == "BP elevated"

    def test_carry_forward_update_diagnosis_to_assess(self):
        """Test _carry_forward_update_diagnosis_to_assess method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        command = MagicMock()
        command.anchor_object = MagicMock()
        command.anchor_object.id = "condition-uuid-456"
        data = {
            "new_condition": {"value": "I10"},
            "background": "Updated diagnosis",
            "narrative": "Changed diagnosis code"
        }

        result = handler._carry_forward_update_diagnosis_to_assess(effect, data, command)

        assert result.condition_id == "condition-uuid-456"
        assert result.background == "Updated diagnosis"
        assert result.narrative == "Changed diagnosis code"

    def test_carry_forward_perform(self):
        """Test _carry_forward_perform method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {
            "perform": {"value": "99213"},
            "notes": "Office visit"
        }

        result = handler._carry_forward_perform(effect, data)

        assert result.cpt_code == "99213"
        assert result.notes == "Office visit"

    def test_carry_forward_vitals(self):
        """Test _carry_forward_vitals method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {
            "height": "70",
            "weight_lbs": "180",
            "weight_oz": "0",
            "waist_circumference": "36",
            "body_temperature": "99",
            "blood_pressure_systole": "120",
            "blood_pressure_diastole": "80",
            "pulse": "72",
            "respiration_rate": "16",
            "oxygen_saturation": "98",
            "body_temperature_site": "1",
            "blood_pressure_position_and_site": "0",
            "pulse_rhythm": "0",
            "note": "Normal vitals"
        }

        result = handler._carry_forward_vitals(effect, data)

        assert result.height == 70
        assert result.weight_lbs == 180
        assert result.pulse == 72
        assert result.note == "Normal vitals"

    def test_carry_forward_goal_as_update_goal(self):
        """Test _carry_forward_goal_as_update_goal method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        command = MagicMock()
        command.anchor_object = MagicMock()
        command.anchor_object.id = "goal-uuid-123"
        data = {
            "goal_statement": "Lose 10 pounds",
            "start_date": "2024-01-01",
            "due_date": "2024-12-31",
            "achievement_status": "in-progress",
            "priority": "medium-priority",
            "progress": "Lost 3 pounds so far"
        }

        result = handler._carry_forward_goal_as_update_goal(effect, data, command)

        assert result.goal_id == "goal-uuid-123"

    def test_carry_forward_update_goal(self):
        """Test _carry_forward_update_goal method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        effect.goal_id = None
        data = {
            "goal_statement": {"value": "goal-123"},
            "due_date": "2024-12-31",
            "achievement_status": "improving",
            "priority": "high-priority",
            "progress": "Patient making good progress"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Goal.objects") as mock_goal:
            mock_goal_obj = MagicMock()
            mock_goal_obj.id = "goal-uuid-123"
            mock_goal.filter.return_value.first.return_value = mock_goal_obj

            result = handler._carry_forward_update_goal(effect, data)

            assert result.progress == "Patient making good progress"

    def test_carry_forward_follow_up(self):
        """Test _carry_forward_follow_up method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {
            "coding": {"value": "Z00.00"},
            "requested_date": {"date": "2024-12-15"},
            "note_type": {"value": "note-type-123"},
            "comment": "Check labs"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.ReasonForVisitSettingCoding.objects") as mock_rfv:
            with patch("carry_forward.protocols.carry_forward_action_button.NoteType.objects") as mock_nt:
                mock_coding = MagicMock()
                mock_coding.id = "rfv-coding-123"
                mock_rfv.filter.return_value.order_by.return_value.last.return_value = mock_coding

                mock_note_type = MagicMock()
                mock_note_type.id = "note-type-uuid-123"
                mock_nt.filter.return_value.first.return_value = mock_note_type

                result = handler._carry_forward_follow_up(effect, data)

                assert result.structured is True
                assert result.comment == "Check labs"

    def test_carry_forward_instruct(self):
        """Test _carry_forward_instruct method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {
            "instruct": {
                "extra": {
                    "coding": [{
                        "system": "http://snomed.info/sct",
                        "code": "386661006",
                        "display": "Fever management"
                    }]
                }
            },
            "narrative": "Take medication with food"
        }

        result = handler._carry_forward_instruct(effect, data)

        assert result.comment == "Take medication with food"

    def test_carry_forward_imaging_order(self):
        """Test _carry_forward_imaging_order method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {
            "image": {"value": "CT, abdomen and pelvis; w/o contrast (CPT: 74176)"},
            "indications": [{"value": "I10"}],
            "priority": "Routine",
            "additional_details": "Check for abnormalities",
            "imaging_center": {
                "extra": {
                    "contact": {
                        "firstName": "John",
                        "lastName": "Doe",
                        "practiceName": "Radiology Center",
                        "specialty": "Radiology",
                        "businessAddress": "123 Main St",
                        "businessPhone": "555-1234",
                        "businessFax": "555-5678",
                        "notes": "Preferred imaging center"
                    }
                }
            },
            "comment": "Urgent review needed",
            "ordering_provider": {"value": "provider-123"},
            "linked_items": [{"value": "item-1"}]
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Staff.objects") as mock_staff:
            mock_provider = MagicMock()
            mock_provider.id = "provider-uuid-123"
            mock_staff.filter.return_value.first.return_value = mock_provider

            result = handler._carry_forward_imaging_order(effect, data)

            assert result.image_code == "74176"
            assert result.additional_details == "Check for abnormalities"
            assert result.comment == "Urgent review needed"

    def test_carry_forward_lab_order(self):
        """Test _carry_forward_lab_order method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {
            "lab_partner": {"value": "quest"},
            "tests": [{"value": "test-123"}, {"value": "test-456"}],
            "ordering_provider": {"value": "provider-123"},
            "diagnosis": [{"value": "I10"}],
            "fasting_status": True,
            "comment": "Draw in AM"
        }

        with patch("carry_forward.protocols.carry_forward_action_button.Staff.objects") as mock_staff:
            mock_provider = MagicMock()
            mock_provider.id = "provider-uuid-123"
            mock_staff.filter.return_value.first.return_value = mock_provider

            result = handler._carry_forward_lab_order(effect, data)

            assert result.lab_partner == "quest"
            assert result.fasting_required is True
            assert result.comment == "Draw in AM"

    def test_carry_forward_refer(self):
        """Test _carry_forward_refer method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {
            "refer_to": {
                "extra": {
                    "contact": {
                        "firstName": "Jane",
                        "lastName": "Smith",
                        "practiceName": "Cardiology Specialists",
                        "specialty": "Cardiology",
                        "businessAddress": "456 Oak Ave",
                        "businessPhone": "555-9999",
                        "businessFax": "555-8888",
                        "notes": "Preferred cardiologist"
                    }
                }
            },
            "indications": [{"value": "I10"}],
            "clinical_question": "Specialized intervention",
            "priority": "Urgent",
            "notes_to_specialist": "Please evaluate chest pain",
            "include_visit_note": True,
            "internal_comment": "Patient prefers Dr. Smith",
            "linked_items": [{"value": "item-1"}]
        }

        result = handler._carry_forward_refer(effect, data)

        assert result.notes_to_specialist == "Please evaluate chest pain"
        assert result.include_visit_note is True
        assert result.comment == "Patient prefers Dr. Smith"

    def test_carry_forward_refill(self):
        """Test _carry_forward_refill method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {
            "prescribe": {"value": "med-123"},
            "indications": [{"value": "cond-123"}],
            "sig": "Take 1 tablet daily",
            "pharmacy": {"value": "pharmacy-123"}
        }

        with patch("carry_forward.protocols.carry_forward_action_button.MedicationCoding.objects") as mock_med_coding:
            with patch("carry_forward.protocols.carry_forward_action_button.ConditionCoding.objects") as mock_cond_coding:
                with patch("carry_forward.protocols.carry_forward_action_button.Staff.objects"):
                    mock_coding = MagicMock()
                    mock_coding.code = "fdb-code-123"
                    mock_med_coding.filter.return_value.first.return_value = mock_coding

                    mock_cond = MagicMock()
                    mock_cond.code = "I10"
                    mock_cond_coding.filter.return_value.first.return_value = mock_cond

                    result = handler._carry_forward_refill(effect, data)

                    assert result.fdb_code == "fdb-code-123"

    def test_carry_forward_prescribe_as_refill(self):
        """Test _carry_forward_prescribe_as_refill method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {
            "prescribe": {"value": "12345"},
            "indications": [],
            "sig": "Take 1 tablet daily",
            "pharmacy": {"value": "pharmacy-123"}
        }

        with patch("carry_forward.protocols.carry_forward_action_button.ConditionCoding.objects"):
            with patch("carry_forward.protocols.carry_forward_action_button.Staff.objects"):
                result = handler._carry_forward_prescribe_as_refill(effect, data)

                assert result.fdb_code == "12345"

    def test_carry_forward_adjust_prescription_as_refill(self):
        """Test _carry_forward_adjust_prescription_as_refill method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {
            "prescribe": {"value": "med-123"},
            "change_medication_to": {"value": "67890"},
            "indications": [],
            "sig": "Take 2 tablets daily",
            "pharmacy": {"value": "pharmacy-123"}
        }

        with patch("carry_forward.protocols.carry_forward_action_button.ConditionCoding.objects"):
            with patch("carry_forward.protocols.carry_forward_action_button.Staff.objects"):
                result = handler._carry_forward_adjust_prescription_as_refill(effect, data)

                assert result.fdb_code == "67890"

    def test_carry_forward_task(self):
        """Test _carry_forward_task method directly."""
        handler = CarryForwardActionButton()
        effect = MagicMock()
        data = {
            "title": "Follow up with patient",
            "assign_to": {"value": "assignee-123"},
            "due_date": "2024-12-15",
            "comment": "Call patient regarding test results",
            "labels": [{"text": "urgent"}, {"text": "follow-up"}],
            "linked_items": [{"value": "item-1"}]
        }

        result = handler._carry_forward_task(effect, data)

        assert result.title == "Follow up with patient"
        assert result.comment == "Call patient regarding test results"
