"""Tests for services/questionnaire_assignments.py.

The service is the seam through which the API reads and writes the
QuestionnaireAssignment table, so these tests cover the behavior the
API depends on. CustomModel queries are mocked — full DB integration
is exercised at deploy time.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from patient_portal_forms.services.questionnaire_assignments import (
    QuestionnaireAssignmentService,
    _parse_iso_date,
)


def _row(
    questionnaire_name: str = "PHQ-9",
    due_date: date | None = date(2026, 6, 1),
    date_assigned: datetime | None = datetime(2026, 5, 14, 10, 0),
    provider_id: str = "staff-uuid",
    provider_credentialed_name: str = "Dr. Smith",
) -> MagicMock:
    provider = MagicMock()
    provider.id = provider_id
    provider.credentialed_name = provider_credentialed_name
    provider.first_name = "Sam"
    provider.last_name = "Smith"

    row = MagicMock()
    row.questionnaire_name = questionnaire_name
    row.due_date = due_date
    row.date_assigned = date_assigned
    row.assigning_provider = provider
    return row


class TestListForPatient:
    def test_returns_none_when_no_rows(self):
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            qs = mock_qa.objects.filter.return_value.select_related.return_value
            qs.order_by.return_value = []
            assert QuestionnaireAssignmentService.list_for_patient("patient-1") is None

    def test_filters_to_outstanding_only(self):
        """Completed rows are history and should not surface in the patient/provider views."""
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            qs = mock_qa.objects.filter.return_value.select_related.return_value
            qs.order_by.return_value = []
            QuestionnaireAssignmentService.list_for_patient("patient-1")

        mock_qa.objects.filter.assert_called_once_with(
            patient__id="patient-1", completed_at__isnull=True
        )

    def test_serializes_rows_in_legacy_shape(self):
        rows = [
            _row(questionnaire_name="PHQ-9", due_date=date(2026, 6, 1)),
            _row(questionnaire_name="GAD-7", due_date=date(2026, 5, 20)),
        ]
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            qs = mock_qa.objects.filter.return_value.select_related.return_value
            qs.order_by.return_value = rows

            result = QuestionnaireAssignmentService.list_for_patient("patient-1")

        assert result is not None
        assert "questionnaires" in result
        assert len(result["questionnaires"]) == 2
        first = result["questionnaires"][0]
        assert first["questionnaire_name"] == "PHQ-9"
        assert first["due_date"] == "2026-06-01"
        assert first["assigning_provider"] == {"key": "staff-uuid", "name": "Dr. Smith"}

    def test_falls_back_to_first_last_name_when_credentialed_name_missing(self):
        row = _row(provider_credentialed_name="")
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            qs = mock_qa.objects.filter.return_value.select_related.return_value
            qs.order_by.return_value = [row]
            result = QuestionnaireAssignmentService.list_for_patient("patient-1")
        assert result["questionnaires"][0]["assigning_provider"]["name"] == "Sam Smith"


class TestAssign:
    def test_creates_one_row_per_questionnaire(self):
        patient = MagicMock()
        provider = MagicMock()
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomPatient"
        ) as mock_patient_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomStaff"
        ) as mock_staff_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            mock_patient_cls.objects.get.return_value = patient
            mock_staff_cls.objects.get.return_value = provider
            mock_qa.objects.update_or_create.return_value = (MagicMock(), True)

            QuestionnaireAssignmentService.assign(
                "patient-1",
                [
                    {"questionnaire_name": "PHQ-9", "due_date": "2026-06-01"},
                    {"questionnaire_name": "GAD-7", "due_date": "2026-06-15"},
                ],
                assigning_provider_uuid="staff-uuid",
            )

        # Provider was resolved once from the trusted kwarg, not per-entry.
        mock_staff_cls.objects.get.assert_called_once_with(id="staff-uuid")

        assert mock_qa.objects.update_or_create.call_count == 2
        first_call = mock_qa.objects.update_or_create.call_args_list[0]
        assert first_call.kwargs["patient"] is patient
        assert first_call.kwargs["questionnaire_name"] == "PHQ-9"
        # completed_at=None pins the upsert to the outstanding row only —
        # without this, a previously completed row would block the upsert
        # because the partial unique constraint covers (patient, name)
        # where completed_at IS NULL.
        assert first_call.kwargs["completed_at"] is None
        assert first_call.kwargs["defaults"]["assigning_provider"] is provider
        assert first_call.kwargs["defaults"]["due_date"] == "2026-06-01"

    def test_reassignment_uses_update_or_create_so_due_date_is_refreshed(self):
        """update_or_create is what makes re-assigning the same questionnaire
        update the row rather than fail on the unique constraint."""
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomPatient"
        ) as mock_patient_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomStaff"
        ) as mock_staff_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            mock_patient_cls.objects.get.return_value = MagicMock()
            mock_staff_cls.objects.get.return_value = MagicMock()
            mock_qa.objects.update_or_create.return_value = (MagicMock(), False)

            QuestionnaireAssignmentService.assign(
                "patient-1",
                [{"questionnaire_name": "PHQ-9", "due_date": "2026-07-01"}],
                assigning_provider_uuid="staff-uuid",
            )

        # The 'create' branch of get_or_create would raise IntegrityError on
        # the partial unique constraint, so this test pins the choice of
        # update_or_create.
        assert mock_qa.objects.update_or_create.called
        assert not mock_qa.objects.get_or_create.called

    def test_raises_when_assigning_provider_does_not_resolve(self):
        """When the session-derived staff uuid doesn't resolve to a row,
        assign() should raise instead of silently writing a row with a
        missing FK."""
        class _DNE(Exception):
            pass

        with patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomPatient"
        ) as mock_patient_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomStaff"
        ) as mock_staff_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            mock_patient_cls.objects.get.return_value = MagicMock()
            mock_staff_cls.DoesNotExist = _DNE
            mock_staff_cls.objects.get.side_effect = _DNE

            with pytest.raises(_DNE):
                QuestionnaireAssignmentService.assign(
                    "patient-1",
                    [{"questionnaire_name": "PHQ-9", "due_date": "2026-07-01"}],
                    assigning_provider_uuid="missing",
                )

        # No assignment row was written.
        mock_qa.objects.update_or_create.assert_not_called()


class TestUnassign:
    def test_deletes_outstanding_row_and_returns_count(self):
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            mock_qa.objects.filter.return_value.delete.return_value = (1, {})
            count = QuestionnaireAssignmentService.unassign("patient-1", "PHQ-9")

        assert count == 1
        # Crucially, completed history rows are not touched
        mock_qa.objects.filter.assert_called_with(
            patient__id="patient-1",
            questionnaire_name="PHQ-9",
            completed_at__isnull=True,
        )

    def test_returns_zero_when_no_matching_row(self):
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            mock_qa.objects.filter.return_value.delete.return_value = (0, {})
            assert QuestionnaireAssignmentService.unassign("patient-1", "PHQ-9") == 0


class TestMarkCompleted:
    def test_stamps_completed_at_and_answers_on_outstanding_row(self):
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            mock_qa.objects.filter.return_value.update.return_value = 1
            answers = [{"question_id": "q1", "question_type": "TEXT", "answer": "ok"}]
            count = QuestionnaireAssignmentService.mark_completed(
                "patient-1", "PHQ-9", submitted_answers=answers
            )

        assert count == 1
        # Filter targets the outstanding row only — completed history is not
        # re-stamped.
        mock_qa.objects.filter.assert_called_once_with(
            patient__id="patient-1",
            questionnaire_name="PHQ-9",
            completed_at__isnull=True,
        )
        # update() writes both completed_at AND submitted_answers.
        update_call = mock_qa.objects.filter.return_value.update.call_args
        assert update_call.kwargs["completed_at"] is not None
        assert update_call.kwargs["submitted_answers"] == answers

    def test_returns_zero_when_no_outstanding_row(self):
        """A duplicate-submit must short-circuit so we don't create a duplicate note."""
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            mock_qa.objects.filter.return_value.update.return_value = 0
            assert (
                QuestionnaireAssignmentService.mark_completed("patient-1", "PHQ-9")
                == 0
            )

    def test_accepts_explicit_completed_at(self):
        explicit = datetime(2026, 5, 14, 9, 30, tzinfo=None)
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            mock_qa.objects.filter.return_value.update.return_value = 1
            QuestionnaireAssignmentService.mark_completed(
                "patient-1", "PHQ-9", completed_at=explicit
            )
        assert (
            mock_qa.objects.filter.return_value.update.call_args.kwargs["completed_at"]
            is explicit
        )


class TestListGrouped:
    """list_grouped powers the pending/completed tabs on both list views."""

    def test_empty_when_no_rows(self):
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            mock_qa.objects.filter.return_value.select_related.return_value.order_by.return_value = []
            result = QuestionnaireAssignmentService.list_grouped("patient-1")
        assert result == {"pending_items": [], "completed_groups": [], "pending_names": []}

    def test_groups_completed_by_name_and_flags_has_pending(self):
        """A reassignment scenario: questionnaire X has one completed
        history row and one new outstanding row. The completed group must
        carry has_pending=True so the UI can render the badge."""
        # Two completed PHQ-9 rows + one outstanding PHQ-9 row + one completed GAD-7
        phq_completed_old = _row(
            questionnaire_name="PHQ-9",
            date_assigned=datetime(2026, 1, 1),
        )
        phq_completed_old.completed_at = datetime(2026, 2, 1)
        phq_completed_new = _row(
            questionnaire_name="PHQ-9",
            date_assigned=datetime(2026, 3, 1),
        )
        phq_completed_new.completed_at = datetime(2026, 4, 1)
        phq_outstanding = _row(
            questionnaire_name="PHQ-9",
            date_assigned=datetime(2026, 5, 1),
        )
        phq_outstanding.completed_at = None
        gad_completed = _row(
            questionnaire_name="GAD-7",
            date_assigned=datetime(2026, 3, 15),
        )
        gad_completed.completed_at = datetime(2026, 3, 20)

        with patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            mock_qa.objects.filter.return_value.select_related.return_value.order_by.return_value = [
                phq_outstanding,
                phq_completed_new,
                phq_completed_old,
                gad_completed,
            ]
            result = QuestionnaireAssignmentService.list_grouped("patient-1")

        assert len(result["pending_items"]) == 1
        assert result["pending_items"][0]["questionnaire_name"] == "PHQ-9"
        assert result["pending_names"] == ["PHQ-9"]

        # Two groups: PHQ-9 (has_pending=True) and GAD-7 (has_pending=False),
        # sorted by latest_completed_date descending.
        assert len(result["completed_groups"]) == 2
        phq_group = next(
            g for g in result["completed_groups"] if g["questionnaire_name"] == "PHQ-9"
        )
        assert phq_group["submission_count"] == 2
        assert phq_group["has_pending"] is True
        # Latest is the 2026-04-01 submission
        assert phq_group["latest_completed_date"] == "2026-04-01"
        # Submission dates list is newest-first; JSON variant is also populated
        # for the data-attribute the popover reads.
        assert phq_group["submission_dates"] == ["2026-04-01", "2026-02-01"]
        assert "2026-04-01" in phq_group["submission_dates_json"]

        gad_group = next(
            g for g in result["completed_groups"] if g["questionnaire_name"] == "GAD-7"
        )
        assert gad_group["submission_count"] == 1
        assert gad_group["has_pending"] is False


class TestGetOutstandingRow:
    def test_returns_raw_row_object(self):
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            row = MagicMock()
            mock_qa.objects.filter.return_value.select_related.return_value.first.return_value = row
            result = QuestionnaireAssignmentService.get_outstanding_row(
                "patient-1", "PHQ-9"
            )
        assert result is row
        # Filter scopes to outstanding only — completed history is not the
        # source of truth for the submit endpoint's provider derivation.
        mock_qa.objects.filter.assert_called_once_with(
            patient__id="patient-1",
            questionnaire_name="PHQ-9",
            completed_at__isnull=True,
        )

    def test_returns_none_when_no_outstanding_row(self):
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            mock_qa.objects.filter.return_value.select_related.return_value.first.return_value = None
            assert (
                QuestionnaireAssignmentService.get_outstanding_row("patient-1", "PHQ-9")
                is None
            )


class TestGetCompletedEntries:
    def test_returns_newest_first_with_submitted_answers(self):
        old = _row()
        old.completed_at = datetime(2026, 2, 1)
        old.submitted_answers = [{"question_id": "q1", "question_type": "TEXT", "answer": "old"}]
        new = _row()
        new.completed_at = datetime(2026, 4, 1)
        new.submitted_answers = [{"question_id": "q1", "question_type": "TEXT", "answer": "new"}]

        with patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            mock_qa.objects.filter.return_value.select_related.return_value.order_by.return_value = [new, old]
            result = QuestionnaireAssignmentService.get_completed_entries(
                "patient-1", "PHQ-9"
            )

        # Order-by is delegated to the queryset (-completed_at) — assert
        # the orm orders by descending completed_at.
        mock_qa.objects.filter.return_value.select_related.return_value.order_by.assert_called_once_with(
            "-completed_at"
        )
        assert len(result) == 2
        assert result[0]["completed_date"] == "2026-04-01"
        assert result[0]["submitted_answers"][0]["answer"] == "new"

    def test_returns_empty_list_when_no_history(self):
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            mock_qa.objects.filter.return_value.select_related.return_value.order_by.return_value = []
            result = QuestionnaireAssignmentService.get_completed_entries(
                "patient-1", "Ghost"
            )
        assert result == []


class TestMigrateFromMetadata:
    def test_creates_outstanding_rows_from_legacy_payload(self):
        patient = MagicMock()
        provider = MagicMock()
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomPatient"
        ) as mock_patient_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomStaff"
        ) as mock_staff_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            mock_patient_cls.objects.get.return_value = patient
            mock_staff_cls.objects.get.return_value = provider
            mock_qa.objects.filter.return_value.exists.return_value = False
            mock_qa.objects.create.return_value = MagicMock(pk=1)

            result = QuestionnaireAssignmentService.migrate_from_metadata(
                "patient-1",
                {
                    "questionnaires": [
                        {
                            "questionnaire_name": "PHQ-9",
                            "due_date": "2026-06-01",
                            "date_assigned": "2026-05-01",
                            "assigning_provider": {"key": "staff-uuid", "name": "Dr. S"},
                        }
                    ]
                },
            )

        assert result == {"created": 1, "skipped": 0, "errors": []}
        # Existence check is scoped to outstanding rows only — a completed
        # history row should not block re-migration as a new outstanding row.
        exists_call = mock_qa.objects.filter.call_args_list[0]
        assert exists_call.kwargs["completed_at__isnull"] is True
        mock_qa.objects.create.assert_called_once()
        # Backfills date_assigned via a follow-up update().
        mock_qa.objects.filter.return_value.update.assert_called_once()

    def test_skips_rows_with_unknown_staff_and_logs_error(self):
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomPatient"
        ) as mock_patient_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomStaff"
        ) as mock_staff_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            mock_patient_cls.objects.get.return_value = MagicMock()
            # in_bulk returns an empty dict — the lookup of the referenced
            # uuid yields None, simulating a missing Staff record.
            mock_staff_cls.objects.in_bulk.return_value = {}

            result = QuestionnaireAssignmentService.migrate_from_metadata(
                "patient-1",
                {
                    "questionnaires": [
                        {
                            "questionnaire_name": "PHQ-9",
                            "due_date": "2026-06-01",
                            "assigning_provider": {"key": "gone", "name": ""},
                        }
                    ]
                },
            )

        assert result["created"] == 0
        assert result["skipped"] == 1
        assert any("gone" in err for err in result["errors"])
        assert not mock_qa.objects.create.called

    def test_skipped_when_required_field_missing(self):
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomPatient"
        ) as mock_patient_cls:
            mock_patient_cls.objects.get.return_value = MagicMock()
            result = QuestionnaireAssignmentService.migrate_from_metadata(
                "patient-1",
                {"questionnaires": [{"questionnaire_name": "PHQ-9"}]},
            )
        assert result["skipped"] == 1
        assert result["created"] == 0

    def test_creates_completed_row_from_v2_completed_entry(self):
        """v2 entries can have ``completed_date`` and ``submitted_answers``.
        These become history rows with ``completed_at`` set and the answers
        snapshotted onto the row."""
        patient = MagicMock()
        provider = MagicMock()
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomPatient"
        ) as mock_patient_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomStaff"
        ) as mock_staff_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa, patch(
            "patient_portal_forms.models.PatientDailyNote"
        ):
            mock_patient_cls.objects.get.return_value = patient
            mock_staff_cls.objects.get.return_value = provider
            mock_qa.objects.filter.return_value.exists.return_value = False
            mock_qa.objects.create.return_value = MagicMock(pk=1)

            answers = [{"question_id": 42, "question_type": "SING", "answer": 101}]
            result = QuestionnaireAssignmentService.migrate_from_metadata(
                "patient-1",
                {
                    "questionnaires": [
                        {
                            "questionnaire_name": "PHQ-9",
                            "due_date": "2026-01-01",
                            "date_assigned": "2025-12-15",
                            "completed_date": "2026-01-05",
                            "assigning_provider": {"key": "staff-uuid", "name": "Dr. S"},
                            "submitted_answers": answers,
                        }
                    ]
                },
            )

        assert result["created"] == 1
        assert result["skipped"] == 0
        # Row was created with completed_at set and submitted_answers carried over
        create_kwargs = mock_qa.objects.create.call_args.kwargs
        assert create_kwargs["completed_at"] is not None
        assert create_kwargs["submitted_answers"] == answers

    def test_v2_idempotency_skips_existing_completed_row(self):
        """Re-running the migration must not duplicate completed history."""
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomPatient"
        ) as mock_patient_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomStaff"
        ) as mock_staff_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa, patch(
            "patient_portal_forms.models.PatientDailyNote"
        ):
            mock_patient_cls.objects.get.return_value = MagicMock()
            mock_staff_cls.objects.get.return_value = MagicMock()
            # A row with this completed_at already exists.
            mock_qa.objects.filter.return_value.exists.return_value = True

            result = QuestionnaireAssignmentService.migrate_from_metadata(
                "patient-1",
                {
                    "questionnaires": [
                        {
                            "questionnaire_name": "PHQ-9",
                            "due_date": "2026-01-01",
                            "completed_date": "2026-01-05",
                            "assigning_provider": {"key": "s", "name": ""},
                            "submitted_answers": [],
                        }
                    ]
                },
            )

        assert result["created"] == 0
        assert result["skipped"] == 1
        assert not mock_qa.objects.create.called

    def test_skips_completed_entry_with_unparseable_date(self):
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomPatient"
        ) as mock_patient_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomStaff"
        ) as mock_staff_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa, patch(
            "patient_portal_forms.models.PatientDailyNote"
        ):
            mock_patient_cls.objects.get.return_value = MagicMock()
            mock_staff_cls.objects.get.return_value = MagicMock()
            result = QuestionnaireAssignmentService.migrate_from_metadata(
                "patient-1",
                {
                    "questionnaires": [
                        {
                            "questionnaire_name": "PHQ-9",
                            "due_date": "2026-01-01",
                            "completed_date": "not a date",
                            "assigning_provider": {"key": "s", "name": ""},
                            "submitted_answers": [],
                        }
                    ]
                },
            )
        assert result["created"] == 0
        assert result["skipped"] == 1
        assert any("completed_date" in e for e in result["errors"])
        assert not mock_qa.objects.create.called

    def test_migrates_v2_daily_notes_map(self):
        """v2 stores a {date: note_uuid} map alongside the questionnaires
        list. Migration writes one PatientDailyNote row per entry, using
        update_or_create so re-runs are safe."""
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomPatient"
        ) as mock_patient_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomStaff"
        ), patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa, patch(
            "patient_portal_forms.models.PatientDailyNote"
        ) as mock_pdn:
            patient = MagicMock()
            mock_patient_cls.objects.get.return_value = patient
            mock_qa.objects.filter.return_value.exists.return_value = False

            note_uuid_a = "11111111-2222-3333-4444-555555555555"
            note_uuid_b = "66666666-7777-8888-9999-aaaaaaaaaaaa"
            result = QuestionnaireAssignmentService.migrate_from_metadata(
                "patient-1",
                {
                    "questionnaires": [],
                    "daily_notes": {
                        "2026-01-05": note_uuid_a,
                        "2026-02-10": note_uuid_b,
                    },
                },
            )

        assert result["errors"] == []
        assert mock_pdn.objects.update_or_create.call_count == 2
        # Each call writes (patient, date, defaults={note_uuid: ...})
        for kwargs in (
            c.kwargs for c in mock_pdn.objects.update_or_create.call_args_list
        ):
            assert kwargs["patient"] is patient
            assert "date" in kwargs
            assert "note_uuid" in kwargs["defaults"]

    def test_daily_notes_with_unparseable_date_is_logged(self):
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomPatient"
        ) as mock_patient_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomStaff"
        ), patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ), patch(
            "patient_portal_forms.models.PatientDailyNote"
        ) as mock_pdn:
            mock_patient_cls.objects.get.return_value = MagicMock()
            result = QuestionnaireAssignmentService.migrate_from_metadata(
                "patient-1",
                {
                    "questionnaires": [],
                    "daily_notes": {"junk": "11111111-2222-3333-4444-555555555555"},
                },
            )
        assert any("junk" in e for e in result["errors"])
        mock_pdn.objects.update_or_create.assert_not_called()

    def test_skips_when_outstanding_row_already_exists(self):
        with patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomPatient"
        ) as mock_patient_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomStaff"
        ) as mock_staff_cls, patch(
            "patient_portal_forms.services.questionnaire_assignments.QuestionnaireAssignment"
        ) as mock_qa:
            mock_patient_cls.objects.get.return_value = MagicMock()
            mock_staff_cls.objects.get.return_value = MagicMock()
            mock_qa.objects.filter.return_value.exists.return_value = True

            result = QuestionnaireAssignmentService.migrate_from_metadata(
                "patient-1",
                {
                    "questionnaires": [
                        {
                            "questionnaire_name": "PHQ-9",
                            "due_date": "2026-06-01",
                            "assigning_provider": {"key": "staff", "name": ""},
                        }
                    ]
                },
            )
        assert result == {"created": 0, "skipped": 1, "errors": []}
        assert not mock_qa.objects.create.called

    def test_missing_patient_short_circuits(self):
        class _DNE(Exception):
            pass

        with patch(
            "patient_portal_forms.services.questionnaire_assignments.CustomPatient"
        ) as mock_patient_cls:
            mock_patient_cls.DoesNotExist = _DNE
            mock_patient_cls.objects.get.side_effect = _DNE
            result = QuestionnaireAssignmentService.migrate_from_metadata(
                "ghost", {"questionnaires": [{}]}
            )
        assert result == {"created": 0, "skipped": 0, "errors": ["patient ghost not found"]}


class TestParseIsoDate:
    @pytest.mark.parametrize(
        "value,expected_date",
        [
            ("2026-05-14", date(2026, 5, 14)),
            ("2026-05-14T10:30:00", date(2026, 5, 14)),
        ],
    )
    def test_parses_iso_strings(self, value, expected_date):
        result = _parse_iso_date(value)
        assert result is not None
        assert result.date() == expected_date

    def test_returns_none_on_garbage(self):
        assert _parse_iso_date("not a date") is None
