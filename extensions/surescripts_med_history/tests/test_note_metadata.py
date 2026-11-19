import json
from unittest.mock import patch

import arrow
import canvas_sdk.effects.note_metadata.base as note_metadata_base
import pytest

from surescripts_med_history.protocols.note_metadata import request_metadata_effects

# Note.id is a UUIDField, so the effect layer rejects anything else.
NOTE_ID = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"

# canvas_sdk_data_api_notemetadata_001
KEY_MAX_LENGTH = 32


@pytest.fixture
def existing_note():
    """Stub the effect layer's note-existence check (it hits the DB)."""
    with patch.object(note_metadata_base, "Note") as mock_note:
        mock_note.objects.filter.return_value.exists.return_value = True
        yield mock_note


def _payloads(effects):
    return [json.loads(effect.payload)["data"] for effect in effects]


class TestRequestMetadataEffects:
    def test_no_note_produces_no_effects(self):
        """Callers blindly extend their effect list with the result."""
        assert request_metadata_effects("", "med_history") == []

    @pytest.mark.parametrize("request_type", ["eligibility", "med_history"])
    def test_stamps_status_and_timestamp(self, existing_note, request_type):
        before = arrow.utcnow()
        data = _payloads(request_metadata_effects(NOTE_ID, request_type))
        after = arrow.utcnow()

        assert len(data) == 2
        status, timestamp = data

        assert status["note_id"] == NOTE_ID
        assert status["key"] == "surescripts_%s_status" % request_type
        assert status["value"] == "requested"

        assert timestamp["note_id"] == NOTE_ID
        assert timestamp["key"] == "surescripts_%s_at" % request_type
        # Stored as ISO-8601 with UTC offset — the modal sorts these keys
        # lexicographically to find the most recent request.
        stamped = arrow.get(timestamp["value"])
        assert before <= stamped <= after
        assert timestamp["value"].endswith("+00:00")

    @pytest.mark.parametrize("request_type", ["eligibility", "med_history"])
    def test_keys_fit_the_notemetadata_column(self, existing_note, request_type):
        for data in _payloads(request_metadata_effects(NOTE_ID, request_type)):
            assert len(data["key"]) <= KEY_MAX_LENGTH

    def test_keys_match_what_the_modal_reads_back(self, existing_note):
        """`_last_requested_display` filters on these exact key names — if the
        writer's keys drift, the modal silently stops showing a last-requested
        time. Assert writer and reader agree rather than trusting both."""
        from unittest.mock import MagicMock

        from surescripts_med_history.protocols import action_button

        written = {
            data["key"]
            for request_type in ("eligibility", "med_history")
            for data in _payloads(request_metadata_effects(NOTE_ID, request_type))
        }

        with patch.object(action_button, "NoteMetadata") as mock_metadata:
            (
                mock_metadata.objects.filter.return_value.order_by.return_value.values_list.return_value.first.return_value
            ) = ""
            action_button._last_requested_display(MagicMock())

        read = set(mock_metadata.objects.filter.call_args.kwargs["key__in"])
        assert read <= written, "modal reads keys the request path never writes"

    def test_effects_are_upsert_note_metadata(self, existing_note):
        effects = request_metadata_effects(NOTE_ID, "med_history")
        assert all(effect.type == effects[0].type for effect in effects)
        assert len(effects) == 2
