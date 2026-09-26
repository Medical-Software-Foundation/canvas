"""Tests for OpenNotesAPI."""

import datetime as dt
import json
from unittest.mock import MagicMock, patch

from clinical_favorites.protocols.open_notes_api import OpenNotesAPI, _iso


def _note(
    *,
    id: str,
    state: str | None,
    note_type: str,
    dos: dt.datetime | None,
    modified: dt.datetime,
    created: dt.datetime | None = None,
) -> MagicMock:
    n = MagicMock()
    n.id = id
    if state is None:
        n.current_state = None
    else:
        n.current_state = MagicMock(state=state)
    n.note_type_version.name = note_type
    n.datetime_of_service = dos
    n.modified = modified
    n.created = created or modified
    return n


def _stub_notes(mock_note_cls: MagicMock, notes: list[MagicMock]) -> None:
    """Wire Note.objects.filter(...).select_related(...) to return notes."""
    chain = MagicMock()
    chain.__iter__ = lambda self: iter(notes)
    mock_note_cls.objects.filter.return_value.select_related.return_value = chain


def _api(patient_id: str = "pat-1") -> OpenNotesAPI:
    api = OpenNotesAPI(MagicMock())
    api.request = MagicMock()
    api.request.query_params = {"patient_id": patient_id}
    return api


@patch("clinical_favorites.protocols.open_notes_api.Note")
@patch("clinical_favorites.protocols.open_notes_api.Patient")
def test_get_returns_open_notes_sorted_by_dos_desc(
    mock_patient_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    mock_patient_cls.objects.get.return_value = MagicMock(
        id="pat-1", first_name="Ada", last_name="Lovelace", mrn="MRN1"
    )

    note_new = _note(
        id="uuid-new",
        state="NEW",
        note_type="Office visit",
        dos=dt.datetime(2026, 4, 21, 12, 0, 0, tzinfo=dt.timezone.utc),
        modified=dt.datetime(2026, 4, 22, 12, 0, 0, tzinfo=dt.timezone.utc),
    )
    note_old = _note(
        id="uuid-old",
        state="ULK",
        note_type="Phone call",
        dos=dt.datetime(2026, 3, 15, 9, 0, 0, tzinfo=dt.timezone.utc),
        modified=dt.datetime(2026, 4, 21, 11, 0, 0, tzinfo=dt.timezone.utc),
    )
    _stub_notes(mock_note_cls, [note_old, note_new])

    body = json.loads(_api().get()[0].content)

    assert body["success"] is True
    assert body["count"] == 2
    assert body["patient_name"] == "Ada Lovelace"
    assert body["notes"][0]["id"] == "uuid-new"
    assert body["notes"][1]["id"] == "uuid-old"
    assert body["notes"][0]["datetime_of_service"].startswith("2026-04-21")
    assert body["notes"][0]["locked"] is False
    assert body["notes"][0]["state"] == "NEW"


@patch("clinical_favorites.protocols.open_notes_api.Note")
@patch("clinical_favorites.protocols.open_notes_api.Patient")
def test_get_flags_locked_notes(
    mock_patient_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    mock_patient_cls.objects.get.return_value = MagicMock(
        id="pat-1", first_name="Ada", last_name="Lovelace", mrn="MRN1"
    )

    note_locked = _note(
        id="uuid-locked",
        state="LKD",
        note_type="Chart review",
        dos=dt.datetime(2026, 4, 17, 11, 57, 0, tzinfo=dt.timezone.utc),
        modified=dt.datetime(2026, 4, 22, 19, 2, 0, tzinfo=dt.timezone.utc),
    )
    _stub_notes(mock_note_cls, [note_locked])

    body = json.loads(_api().get()[0].content)

    assert body["notes"][0]["locked"] is True
    assert body["notes"][0]["state"] == "LKD"


@patch("clinical_favorites.protocols.open_notes_api.Note")
@patch("clinical_favorites.protocols.open_notes_api.Patient")
def test_get_flags_signed_notes(
    mock_patient_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    mock_patient_cls.objects.get.return_value = MagicMock(
        id="pat-1", first_name="Ada", last_name="Lovelace", mrn="MRN1"
    )
    note_signed = _note(
        id="uuid-signed",
        state="SGN",
        note_type="Office visit",
        dos=dt.datetime(2026, 4, 10, 9, 0, 0, tzinfo=dt.timezone.utc),
        modified=dt.datetime(2026, 4, 10, 10, 0, 0, tzinfo=dt.timezone.utc),
    )
    _stub_notes(mock_note_cls, [note_signed])

    body = json.loads(_api().get()[0].content)
    assert body["notes"][0]["locked"] is True
    assert body["notes"][0]["state"] == "SGN"


@patch("clinical_favorites.protocols.open_notes_api.Note")
@patch("clinical_favorites.protocols.open_notes_api.Patient")
def test_get_falls_back_to_created_when_dos_missing(
    mock_patient_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    mock_patient_cls.objects.get.return_value = MagicMock(
        id="pat-1", first_name="Ada", last_name="Lovelace", mrn="MRN1"
    )
    created = dt.datetime(2026, 4, 1, 8, 0, 0, tzinfo=dt.timezone.utc)
    note_no_dos = _note(
        id="uuid-no-dos",
        state="NEW",
        note_type="Phone call",
        dos=None,
        modified=dt.datetime(2026, 4, 2, 8, 0, 0, tzinfo=dt.timezone.utc),
        created=created,
    )
    _stub_notes(mock_note_cls, [note_no_dos])

    body = json.loads(_api().get()[0].content)
    assert body["notes"][0]["datetime_of_service"].startswith("2026-04-01")


@patch("clinical_favorites.protocols.open_notes_api.Note")
@patch("clinical_favorites.protocols.open_notes_api.Patient")
def test_get_empty_when_no_open_notes(
    mock_patient_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    mock_patient_cls.objects.get.return_value = MagicMock(
        id="pat-1", first_name="Ada", last_name="Lovelace", mrn="MRN1"
    )
    _stub_notes(mock_note_cls, [])

    body = json.loads(_api().get()[0].content)
    assert body["success"] is True
    assert body["count"] == 0
    assert body["notes"] == []


@patch("clinical_favorites.protocols.open_notes_api.Note")
@patch("clinical_favorites.protocols.open_notes_api.Patient")
def test_get_skips_notes_with_no_current_state(
    mock_patient_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    mock_patient_cls.objects.get.return_value = MagicMock(
        id="pat-1", first_name="Ada", last_name="Lovelace", mrn="MRN1"
    )

    note_with_state = _note(
        id="uuid-ok",
        state="NEW",
        note_type="Office visit",
        dos=dt.datetime(2026, 4, 1, 9, 0, 0, tzinfo=dt.timezone.utc),
        modified=dt.datetime(2026, 4, 1, 10, 0, 0, tzinfo=dt.timezone.utc),
    )
    note_without_state = _note(
        id="uuid-orphan",
        state=None,
        note_type="Office visit",
        dos=dt.datetime(2026, 4, 2, 9, 0, 0, tzinfo=dt.timezone.utc),
        modified=dt.datetime(2026, 4, 2, 10, 0, 0, tzinfo=dt.timezone.utc),
    )
    _stub_notes(mock_note_cls, [note_with_state, note_without_state])

    body = json.loads(_api().get()[0].content)
    assert body["count"] == 1
    assert body["notes"][0]["id"] == "uuid-ok"


@patch("clinical_favorites.protocols.open_notes_api.Note")
@patch("clinical_favorites.protocols.open_notes_api.Patient")
def test_get_patient_name_falls_back_to_mrn_when_name_blank(
    mock_patient_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    mock_patient_cls.objects.get.return_value = MagicMock(
        id="pat-1", first_name="", last_name="", mrn="MRN1"
    )
    _stub_notes(mock_note_cls, [])

    body = json.loads(_api().get()[0].content)
    assert body["patient_name"] == "MRN1"


def test_get_requires_patient_id() -> None:
    api = OpenNotesAPI(MagicMock())
    api.request = MagicMock()
    api.request.query_params = {}
    body = json.loads(api.get()[0].content)
    assert body["success"] is False
    assert "patient_id" in body["error"]


@patch("clinical_favorites.protocols.open_notes_api.Patient")
def test_get_patient_not_found(mock_patient_cls: MagicMock) -> None:
    mock_patient_cls.DoesNotExist = Exception
    mock_patient_cls.objects.get.side_effect = mock_patient_cls.DoesNotExist()
    body = json.loads(_api().get()[0].content)
    assert body["success"] is False
    assert "Patient" in body["error"]


def test_iso_helper_returns_empty_for_none_and_passes_through_strings() -> None:
    assert _iso(None) == ""
    assert _iso("2026-04-21") == "2026-04-21"


@patch("clinical_favorites.protocols.open_notes_api.Note")
@patch("clinical_favorites.protocols.open_notes_api.Patient")
def test_get_swallows_note_type_version_exceptions(
    mock_patient_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    mock_patient_cls.objects.get.return_value = MagicMock(
        id="pat-1", first_name="Ada", last_name="Lovelace", mrn="MRN1"
    )

    note = MagicMock()
    note.id = "uuid-broken"
    note.current_state = MagicMock(state="NEW")
    type(note).note_type_version = property(
        lambda self: (_ for _ in ()).throw(RuntimeError("broken relation"))
    )
    note.datetime_of_service = dt.datetime(
        2026, 4, 1, 8, 0, 0, tzinfo=dt.timezone.utc
    )
    note.modified = dt.datetime(2026, 4, 1, 9, 0, 0, tzinfo=dt.timezone.utc)
    note.created = note.modified
    _stub_notes(mock_note_cls, [note])

    body = json.loads(_api().get()[0].content)
    assert body["notes"][0]["note_type"] == ""
