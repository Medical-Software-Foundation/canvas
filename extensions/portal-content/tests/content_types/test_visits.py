"""Tests for SDK-backed visit notes (list, AVS, view-note, access control)."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from canvas_sdk.v1.data.note import Note as RealNote

from portal_content.content_types import visits


def _note(note_id="n1", patient_id="p1", code="off", state="LKD", encounter=True):
    note = MagicMock(id=note_id, created=datetime(2026, 1, 2, 9, 0))
    note_type = MagicMock()
    note_type.name = "Office Visit"
    note_type.code = code
    note.note_type_version = note_type
    note.patient = MagicMock(id=patient_id)
    note.current_state = MagicMock(state=state)
    provider = MagicMock()
    provider.full_name = "Dr. Who"
    note.provider = provider
    note.encounter = MagicMock(id="enc1") if encounter else None
    return note


def test_get_note_types_filter_parses_and_trims():
    assert visits.get_note_types_filter({"NOTE_TYPES": "a, b ,,c"}) == ["a", "b", "c"]
    assert visits.get_note_types_filter({}) == []


@patch("portal_content.content_types.visits.Command")
@patch("portal_content.content_types.visits.Note")
def test_list_notes_maps_and_paginates(note_model, command_model):
    query = (
        note_model.objects.filter.return_value.select_related.return_value.filter.return_value.order_by.return_value
    )
    query.count.return_value = 1
    query.__getitem__.return_value = [_note()]
    command_model.objects.filter.return_value.order_by.return_value.values_list.return_value.first.return_value = {
        "comment": "persistent cough"
    }

    data = visits.list_notes("p1", ["off"], limit=20, offset=0)

    assert data["total"] == 1
    assert data["has_more"] is False
    summary = data["summaries"][0]
    assert summary["note_id"] == "n1"
    assert summary["visit_type"] == "Office Visit"
    assert summary["provider_name"] == "Dr. Who"
    assert summary["chief_concern"] == "persistent cough"


@patch("portal_content.content_types.visits.Command")
@patch("portal_content.content_types.visits.Note")
def test_list_notes_chief_concern_absent(note_model, command_model):
    query = (
        note_model.objects.filter.return_value.select_related.return_value.filter.return_value.order_by.return_value
    )
    query.count.return_value = 1
    query.__getitem__.return_value = [_note()]
    command_model.objects.filter.return_value.order_by.return_value.values_list.return_value.first.return_value = None

    data = visits.list_notes("p1", ["off"], 20, 0)
    assert data["summaries"][0]["chief_concern"] is None


@patch("portal_content.content_types.visits.AVSRenderer")
@patch("portal_content.content_types.visits.Note")
def test_render_avs_returns_html_for_accessible_note(note_model, renderer):
    note_model.objects.select_related.return_value.get.return_value = _note(state="SGN")
    renderer.return_value.render.return_value = "<div>AVS</div>"
    assert visits.render_avs("p1", "n1", ["off"]) == "<div>AVS</div>"


@patch("portal_content.content_types.visits.Note")
def test_render_avs_denied_wrong_patient(note_model):
    note_model.objects.select_related.return_value.get.return_value = _note(patient_id="someone-else")
    assert visits.render_avs("p1", "n1", ["off"]) is None


@patch("portal_content.content_types.visits.Note")
def test_render_avs_denied_wrong_note_type(note_model):
    note_model.objects.select_related.return_value.get.return_value = _note(code="other")
    assert visits.render_avs("p1", "n1", ["off"]) is None


@patch("portal_content.content_types.visits.Note")
def test_render_avs_denied_not_finalized(note_model):
    note_model.objects.select_related.return_value.get.return_value = _note(state="DRF")
    assert visits.render_avs("p1", "n1", ["off"]) is None


@patch("portal_content.content_types.visits.Note")
def test_render_avs_missing_note_returns_none(note_model):
    note_model.DoesNotExist = RealNote.DoesNotExist
    note_model.objects.select_related.return_value.get.side_effect = RealNote.DoesNotExist
    assert visits.render_avs("p1", "n1", ["off"]) is None


@patch("portal_content.content_types.visits.DocumentReference")
@patch("portal_content.content_types.visits.Note")
def test_get_note_document_returns_content(note_model, doc_ref):
    note_model.objects.select_related.return_value.get.return_value = _note()
    document = MagicMock(id="docref-1", document_content_type="application/pdf")
    doc_ref.objects.for_patient.return_value.filter.return_value.order_by.return_value.first.return_value = document

    assert visits.get_note_document("p1", "n1", ["off"]) == {
        "content_url": "/plugin-io/api/portal_content/app/document?ref_id=docref-1",
        "content_type": "application/pdf",
    }


@patch("portal_content.content_types.visits.Note")
def test_get_note_document_none_without_encounter(note_model):
    note_model.objects.select_related.return_value.get.return_value = _note(encounter=False)
    assert visits.get_note_document("p1", "n1", ["off"]) is None


@patch("portal_content.content_types.visits.DocumentReference")
@patch("portal_content.content_types.visits.Note")
def test_get_note_document_none_when_no_document(note_model, doc_ref):
    note_model.objects.select_related.return_value.get.return_value = _note()
    doc_ref.objects.for_patient.return_value.filter.return_value.order_by.return_value.first.return_value = None
    assert visits.get_note_document("p1", "n1", ["off"]) is None
