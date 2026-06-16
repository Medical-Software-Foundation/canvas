"""Tests for DiagnoseOrderHandler.

Three primary cases:
  (a) sleep_study_order field = 'No' (or absent) → no effect
  (b) field = 'Yes' + SLEEP_STUDIES_TEAM_ID unset → no effect + warning logged
  (c) field = 'Yes' + team configured → AddTask effect with correct fields
"""

from unittest.mock import MagicMock, call, patch

import pytest

from sleep_study_visualizer.handlers.diagnose_order import DiagnoseOrderHandler


def _make_handler(event, secrets=None):
    handler = DiagnoseOrderHandler(event=event, secrets=secrets or {})
    return handler


# ── Case (a): order = No ──────────────────────────────────────────────────

class TestDiagnoseOrderHandlerNoOrder:
    def test_no_order_field_returns_empty(self, mock_diagnose_post_commit_event):
        """When sleep_study_order = 'No', no effect is returned."""
        mock_meta = MagicMock()
        mock_meta.value = "No"

        with patch(
            "sleep_study_visualizer.handlers.diagnose_order.CommandMetadata.objects"
        ) as mock_meta_objects:
            mock_meta_objects.get.return_value = mock_meta

            handler = _make_handler(mock_diagnose_post_commit_event)
            effects = handler.compute()

        assert effects == []
        assert mock_meta_objects.mock_calls == [
            call.get(command__id="cmd-uuid-5678", key="sleep_study_order")
        ]

    def test_missing_metadata_returns_empty(self, mock_diagnose_post_commit_event):
        """When CommandMetadata row doesn't exist, returns []."""
        from canvas_sdk.v1.data.command import CommandMetadata

        with patch(
            "sleep_study_visualizer.handlers.diagnose_order.CommandMetadata.objects"
        ) as mock_meta_objects:
            mock_meta_objects.get.side_effect = CommandMetadata.DoesNotExist

            handler = _make_handler(mock_diagnose_post_commit_event)
            effects = handler.compute()

        assert effects == []
        assert mock_meta_objects.mock_calls == [
            call.get(command__id="cmd-uuid-5678", key="sleep_study_order")
        ]


# ── Case (b): order = Yes, team secret unset ──────────────────────────────

class TestDiagnoseOrderHandlerFailClosed:
    def test_yes_order_no_team_secret_returns_empty(
        self, mock_diagnose_post_commit_event, caplog
    ):
        """When order = Yes but SLEEP_STUDIES_TEAM_ID is not set, returns [] and warns."""
        import logging

        mock_meta = MagicMock()
        mock_meta.value = "Yes"

        with patch(
            "sleep_study_visualizer.handlers.diagnose_order.CommandMetadata.objects"
        ) as mock_meta_objects:
            mock_meta_objects.get.return_value = mock_meta

            handler = _make_handler(
                mock_diagnose_post_commit_event,
                secrets={},  # SLEEP_STUDIES_TEAM_ID absent
            )

            with caplog.at_level(logging.WARNING):
                effects = handler.compute()

        assert effects == []
        assert "SLEEP_STUDIES_TEAM_ID" in caplog.text
        assert mock_meta_objects.mock_calls == [
            call.get(command__id="cmd-uuid-5678", key="sleep_study_order")
        ]

    def test_yes_order_team_not_found_returns_empty(
        self, mock_diagnose_post_commit_event, caplog
    ):
        """When order = Yes but the configured team doesn't exist, returns [] and warns."""
        import logging
        from canvas_sdk.v1.data.team import Team

        mock_meta = MagicMock()
        mock_meta.value = "Yes"

        with patch(
            "sleep_study_visualizer.handlers.diagnose_order.CommandMetadata.objects"
        ) as mock_meta_objects, patch(
            "sleep_study_visualizer.handlers.diagnose_order.Team.objects"
        ) as mock_team_objects:
            mock_meta_objects.get.return_value = mock_meta
            mock_team_objects.get.side_effect = Team.DoesNotExist

            handler = _make_handler(
                mock_diagnose_post_commit_event,
                secrets={"SLEEP_STUDIES_TEAM_ID": "team-uuid-1234"},
            )

            with caplog.at_level(logging.WARNING):
                effects = handler.compute()

        assert effects == []
        assert "team-uuid-1234" in caplog.text
        assert mock_meta_objects.mock_calls == [
            call.get(command__id="cmd-uuid-5678", key="sleep_study_order")
        ]
        assert mock_team_objects.mock_calls == [call.get(id="team-uuid-1234")]

    def test_missing_patient_id_in_context_returns_empty(
        self, mock_diagnose_post_commit_event, caplog
    ):
        """No patient ID in event context → return [] with warning."""
        import logging

        mock_meta = MagicMock()
        mock_meta.value = "Yes"
        mock_diagnose_post_commit_event.context = {"note": {"uuid": "note-1"}}

        with patch(
            "sleep_study_visualizer.handlers.diagnose_order.CommandMetadata.objects"
        ) as mock_meta_objects, patch(
            "sleep_study_visualizer.handlers.diagnose_order.Team.objects"
        ) as mock_team_objects:
            mock_meta_objects.get.return_value = mock_meta
            mock_team = MagicMock()
            mock_team.id = "team-uuid"
            mock_team_objects.get.return_value = mock_team

            handler = _make_handler(
                mock_diagnose_post_commit_event,
                secrets={"SLEEP_STUDIES_TEAM_ID": "team-uuid-1234"},
            )

            with caplog.at_level(logging.WARNING):
                effects = handler.compute()

        assert effects == []
        assert "patient" in caplog.text.lower()
        assert mock_meta_objects.mock_calls == [
            call.get(command__id="cmd-uuid-5678", key="sleep_study_order")
        ]
        assert mock_team_objects.mock_calls == [call.get(id="team-uuid-1234")]


# ── Case (c): order = Yes, team configured ────────────────────────────────

class TestDiagnoseOrderHandlerSuccess:
    def test_yes_order_creates_add_task_effect(self, mock_diagnose_post_commit_event):
        """When order = Yes and team is configured, returns an AddTask effect."""
        mock_meta = MagicMock()
        mock_meta.value = "Yes"

        mock_team = MagicMock()
        mock_team.id = "team-uuid-sleep"

        mock_patient = MagicMock()
        mock_patient.id = "patient-abc"
        mock_patient.dbid = 42
        mock_patient.first_name = "John"
        mock_patient.last_name = "Doe"
        mock_patient.mrn = "MRN001"

        mock_command = MagicMock()
        mock_command.data = {
            "diagnose": {
                "text": "Obstructive sleep apnea",
                "extra": {"coding": [{"code": "G47.33", "display": "Obstructive sleep apnea"}]},
            }
        }

        with patch(
            "sleep_study_visualizer.handlers.diagnose_order.CommandMetadata.objects"
        ) as mock_meta_objects, patch(
            "sleep_study_visualizer.handlers.diagnose_order.Team.objects"
        ) as mock_team_objects, patch(
            "sleep_study_visualizer.handlers.diagnose_order.Patient.objects"
        ) as mock_patient_objects, patch(
            "sleep_study_visualizer.handlers.diagnose_order.Command.objects"
        ) as mock_command_objects:
            mock_meta_objects.get.return_value = mock_meta
            mock_team_objects.get.return_value = mock_team
            mock_patient_objects.get.return_value = mock_patient
            mock_command_objects.get.return_value = mock_command

            handler = _make_handler(
                mock_diagnose_post_commit_event,
                secrets={"SLEEP_STUDIES_TEAM_ID": "team-uuid-1234"},
            )
            effects = handler.compute()

        assert len(effects) == 1
        assert mock_meta_objects.mock_calls == [
            call.get(command__id="cmd-uuid-5678", key="sleep_study_order")
        ]
        assert mock_team_objects.mock_calls == [call.get(id="team-uuid-1234")]
        assert mock_patient_objects.mock_calls == [call.get(id="patient-abc")]
        assert mock_command_objects.mock_calls == [call.get(id="cmd-uuid-5678")]

    def test_task_title_includes_patient_name_and_icd10(
        self, mock_diagnose_post_commit_event
    ):
        """Task title must contain patient name, MRN, and ICD-10 code."""
        from sleep_study_visualizer.handlers.diagnose_order import _build_order_task

        mock_patient = MagicMock()
        mock_patient.id = "patient-abc"
        mock_patient.first_name = "Jane"
        mock_patient.last_name = "Smith"
        mock_patient.mrn = "MRN999"

        mock_command = MagicMock()
        mock_command.data = {
            "diagnose": {
                "text": "Obstructive sleep apnea",
                "extra": {"coding": [{"code": "G47.33", "display": "Obstructive sleep apnea"}]},
            }
        }

        task_effect = _build_order_task(
            patient=mock_patient,
            command=mock_command,
            team_id="team-uuid-sleep",
        )

        title = task_effect.title
        assert "Jane" in title
        assert "Smith" in title
        assert "MRN999" in title
        assert "G47.33" in title
