"""Tests for services/daily_notes.py — same-day note bundling.

The service is the seam through which submit_questionnaire decides whether
to create a fresh note or reuse the day's existing bundle. SDK queries
(CustomPatient, PatientDailyNote, Note) are mocked — full DB integration
runs at deploy time.
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import MagicMock, patch

from canvas_sdk.v1.data.note import NoteStates

from patient_portal_forms.services.daily_notes import (
    DailyNoteService,
    _note_is_reusable,
)


# ----- _note_is_reusable ----------------------------------------------------


class TestNoteIsReusable:
    def test_none_note_is_not_reusable(self):
        assert _note_is_reusable(None) is False

    def test_note_with_no_current_state_is_reusable(self):
        """The CurrentNoteStateEvent view may have no row for a freshly-
        created note. That note is not yet locked, so it's reusable.
        This was the root cause of the v2 bug the user reported: the v2
        check rejected notes whose state row hadn't been written yet."""
        note = MagicMock()
        note.current_state = None
        assert _note_is_reusable(note) is True

    def test_note_in_new_state_is_reusable(self):
        note = MagicMock()
        note.current_state = MagicMock(state=NoteStates.NEW)
        assert _note_is_reusable(note) is True

    def test_locked_relocked_deleted_cancelled_not_reusable(self):
        for blocked_state in (
            NoteStates.LOCKED,
            NoteStates.RELOCKED,
            NoteStates.DELETED,
            NoteStates.CANCELLED,
        ):
            note = MagicMock()
            note.current_state = MagicMock(state=blocked_state)
            assert _note_is_reusable(note) is False, blocked_state


# ----- DailyNoteService.resolve --------------------------------------------


class TestResolveNoBundle:
    """bundle=False — used for the Data Import fallback path."""

    def test_returns_fresh_uuid_and_does_not_touch_pointer_table(self):
        with patch(
            "patient_portal_forms.services.daily_notes.CustomPatient"
        ) as mock_patient_cls, patch(
            "patient_portal_forms.services.daily_notes.PatientDailyNote"
        ) as mock_pdn:
            note_uuid, reuse = DailyNoteService.resolve(
                "patient-1", date(2026, 5, 15), bundle=False
            )

        assert reuse is False
        assert isinstance(note_uuid, uuid.UUID)
        # No DB I/O at all when bundling is disabled — DATA notes are one-shot
        mock_patient_cls.objects.get.assert_not_called()
        mock_pdn.objects.filter.assert_not_called()
        mock_pdn.objects.update_or_create.assert_not_called()


class TestResolveBundleReuse:
    """bundle=True path — main bundling behavior."""

    def test_reuses_existing_note_when_state_is_open(self):
        existing_uuid = str(uuid.uuid4())
        with patch(
            "patient_portal_forms.services.daily_notes.CustomPatient"
        ) as mock_patient_cls, patch(
            "patient_portal_forms.services.daily_notes.PatientDailyNote"
        ) as mock_pdn, patch(
            "patient_portal_forms.services.daily_notes.Note"
        ) as mock_note_cls:
            mock_patient_cls.objects.get.return_value = MagicMock()
            pointer = MagicMock(note_uuid=existing_uuid)
            mock_pdn.objects.filter.return_value.first.return_value = pointer
            open_note = MagicMock()
            open_note.current_state = MagicMock(state=NoteStates.NEW)
            mock_note_cls.objects.select_related.return_value.filter.return_value.first.return_value = (
                open_note
            )

            note_uuid, reuse = DailyNoteService.resolve(
                "patient-1", date(2026, 5, 15), bundle=True
            )

        assert reuse is True
        assert str(note_uuid) == existing_uuid
        # Pointer is not rewritten when we're reusing
        mock_pdn.objects.update_or_create.assert_not_called()

    def test_reuses_existing_note_even_when_current_state_missing(self):
        """Freshly created notes may not have a state row yet — they're
        still reusable. This is the fix for v2's bug."""
        existing_uuid = str(uuid.uuid4())
        with patch(
            "patient_portal_forms.services.daily_notes.CustomPatient"
        ) as mock_patient_cls, patch(
            "patient_portal_forms.services.daily_notes.PatientDailyNote"
        ) as mock_pdn, patch(
            "patient_portal_forms.services.daily_notes.Note"
        ) as mock_note_cls:
            mock_patient_cls.objects.get.return_value = MagicMock()
            pointer = MagicMock(note_uuid=existing_uuid)
            mock_pdn.objects.filter.return_value.first.return_value = pointer
            note_with_no_state = MagicMock()
            note_with_no_state.current_state = None
            mock_note_cls.objects.select_related.return_value.filter.return_value.first.return_value = (
                note_with_no_state
            )

            note_uuid, reuse = DailyNoteService.resolve(
                "patient-1", date(2026, 5, 15), bundle=True
            )

        assert reuse is True
        assert str(note_uuid) == existing_uuid
        mock_pdn.objects.update_or_create.assert_not_called()

    def test_mints_new_when_existing_note_is_locked(self):
        existing_uuid = str(uuid.uuid4())
        with patch(
            "patient_portal_forms.services.daily_notes.CustomPatient"
        ) as mock_patient_cls, patch(
            "patient_portal_forms.services.daily_notes.PatientDailyNote"
        ) as mock_pdn, patch(
            "patient_portal_forms.services.daily_notes.Note"
        ) as mock_note_cls:
            patient = MagicMock()
            mock_patient_cls.objects.get.return_value = patient
            pointer = MagicMock(note_uuid=existing_uuid)
            mock_pdn.objects.filter.return_value.first.return_value = pointer
            locked_note = MagicMock()
            locked_note.current_state = MagicMock(state=NoteStates.LOCKED)
            mock_note_cls.objects.select_related.return_value.filter.return_value.first.return_value = (
                locked_note
            )

            note_uuid, reuse = DailyNoteService.resolve(
                "patient-1", date(2026, 5, 15), bundle=True
            )

        assert reuse is False
        assert str(note_uuid) != existing_uuid
        # Pointer is rewritten in place — UniqueConstraint(patient, date) holds.
        mock_pdn.objects.update_or_create.assert_called_once()
        call = mock_pdn.objects.update_or_create.call_args
        assert call.kwargs["patient"] is patient
        assert call.kwargs["date"] == date(2026, 5, 15)
        assert call.kwargs["defaults"]["note_uuid"] == str(note_uuid)

    def test_mints_new_when_note_does_not_exist(self):
        """The pointer references a UUID that doesn't resolve to a Note row.
        Could happen if a prior submission's NoteEffect failed runtime apply
        — the service self-heals by replacing the pointer."""
        with patch(
            "patient_portal_forms.services.daily_notes.CustomPatient"
        ) as mock_patient_cls, patch(
            "patient_portal_forms.services.daily_notes.PatientDailyNote"
        ) as mock_pdn, patch(
            "patient_portal_forms.services.daily_notes.Note"
        ) as mock_note_cls:
            mock_patient_cls.objects.get.return_value = MagicMock()
            pointer = MagicMock(note_uuid=str(uuid.uuid4()))
            mock_pdn.objects.filter.return_value.first.return_value = pointer
            mock_note_cls.objects.select_related.return_value.filter.return_value.first.return_value = (
                None
            )

            _note_uuid, reuse = DailyNoteService.resolve(
                "patient-1", date(2026, 5, 15), bundle=True
            )

        assert reuse is False
        mock_pdn.objects.update_or_create.assert_called_once()

    def test_creates_pointer_when_none_exists_for_the_day(self):
        with patch(
            "patient_portal_forms.services.daily_notes.CustomPatient"
        ) as mock_patient_cls, patch(
            "patient_portal_forms.services.daily_notes.PatientDailyNote"
        ) as mock_pdn:
            mock_patient_cls.objects.get.return_value = MagicMock()
            mock_pdn.objects.filter.return_value.first.return_value = None

            note_uuid, reuse = DailyNoteService.resolve(
                "patient-1", date(2026, 5, 15), bundle=True
            )

        assert reuse is False
        assert isinstance(note_uuid, uuid.UUID)
        mock_pdn.objects.update_or_create.assert_called_once()
