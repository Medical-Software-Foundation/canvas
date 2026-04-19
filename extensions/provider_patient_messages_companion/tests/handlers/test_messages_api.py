"""Tests for provider_patient_messages_companion.handlers.messages_api."""
import contextlib
import json
from datetime import datetime, timezone
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

from provider_patient_messages_companion.handlers import messages_api
from provider_patient_messages_companion.handlers.messages_api import (
    PatientMessagesAPI,
    _latest_message_per_thread,
    _panel_patients,
    _serialize_message,
    _serialize_thread,
    _unread_counts,
)

STAFF_UUID = "00000000-0000-0000-0000-000000000001"
PATIENT_1 = "11111111-1111-1111-1111-111111111111"
PATIENT_2 = "22222222-2222-2222-2222-222222222222"
MESSAGE_1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _make_api(
    headers: dict | None = None,
    query_params: dict | None = None,
    path_params: dict | None = None,
    json_body: dict | None = None,
) -> PatientMessagesAPI:
    api = PatientMessagesAPI.__new__(PatientMessagesAPI)
    api.request = SimpleNamespace(
        headers=headers or {"canvas-logged-in-user-id": STAFF_UUID},
        query_params=query_params or {},
        path_params=path_params or {},
        json=lambda: json_body if json_body is not None else {},
    )
    return api


@contextlib.contextmanager
def _effect_validation_bypass():
    """Patch the SDK Message effect's DB-backed existence checks to always succeed."""
    with (
        patch("canvas_sdk.effects.note.message.Patient") as mock_patient,
        patch("canvas_sdk.effects.note.message.Staff") as mock_staff,
        patch("canvas_sdk.effects.note.message.MessageModel") as mock_message,
    ):
        for mock_model in (mock_patient, mock_staff, mock_message):
            mock_model.objects.filter.return_value.exists.return_value = True
        yield


class TestPanelPatients:
    def test_dedupes_skips_null_orders(self) -> None:
        patient_a = SimpleNamespace(id=PATIENT_1, first_name="Ann", last_name="Alpha")
        patient_b = SimpleNamespace(id=PATIENT_2, first_name="Ben", last_name="Bravo")
        memberships = [
            SimpleNamespace(patient=patient_a),
            SimpleNamespace(patient=patient_a),
            SimpleNamespace(patient=None),
            SimpleNamespace(patient=patient_b),
        ]
        queryset = MagicMock()
        queryset.select_related.return_value = queryset
        queryset.order_by.return_value = memberships

        with patch.object(messages_api, "CareTeamMembership") as mock_model:
            mock_model.objects.filter.return_value = queryset
            result = _panel_patients(STAFF_UUID)

        assert list(result.keys()) == [PATIENT_1, PATIENT_2]
        assert mock_model.objects.filter.mock_calls[0] == call(
            staff__id=STAFF_UUID,
            status=messages_api.CareTeamMembershipStatus.ACTIVE,
        )

    def test_empty_memberships_returns_empty_dict(self) -> None:
        queryset = MagicMock()
        queryset.select_related.return_value = queryset
        queryset.order_by.return_value = []
        with patch.object(messages_api, "CareTeamMembership") as mock_model:
            mock_model.objects.filter.return_value = queryset
            assert _panel_patients(STAFF_UUID) == {}


class TestLatestMessageHelper:
    def test_empty_list_short_circuits(self) -> None:
        with patch.object(messages_api, "Message") as mock_model:
            assert _latest_message_per_thread(STAFF_UUID, []) == []
        assert mock_model.mock_calls == []

    def test_returns_distinct_on_result(self) -> None:
        queryset = MagicMock()
        queryset.filter.return_value = queryset
        queryset.annotate.return_value = queryset
        queryset.order_by.return_value = queryset
        row = SimpleNamespace(id=MESSAGE_1, thread_patient_id=PATIENT_1)
        queryset.distinct.return_value = [row]

        with patch.object(messages_api, "Message") as mock_model:
            mock_model.objects.filter.return_value = queryset
            result = _latest_message_per_thread(STAFF_UUID, [PATIENT_1])

        assert result == [row]
        assert queryset.distinct.mock_calls == [call("thread_patient_id")]


class TestUnreadCounts:
    def test_empty_list_short_circuits(self) -> None:
        with patch.object(messages_api, "Message") as mock_model:
            assert _unread_counts(STAFF_UUID, []) == {}
        assert mock_model.mock_calls == []

    def test_returns_counts_dict(self) -> None:
        queryset = MagicMock()
        queryset.values_list.return_value = queryset
        queryset.annotate.return_value = [(PATIENT_1, 3), (PATIENT_2, 1)]

        with patch.object(messages_api, "Message") as mock_model:
            mock_model.objects.filter.return_value = queryset
            result = _unread_counts(STAFF_UUID, [PATIENT_1, PATIENT_2])

        assert result == {PATIENT_1: 3, PATIENT_2: 1}
        assert mock_model.objects.filter.mock_calls[0] == call(
            sender__patient__id__in=[PATIENT_1, PATIENT_2],
            recipient__staff__id=STAFF_UUID,
            read__isnull=True,
        )


class TestSerializeThread:
    def test_with_last_message(self) -> None:
        patient = SimpleNamespace(id=PATIENT_1, first_name="Jane", last_name="Doe")
        last_message = SimpleNamespace(
            id=MESSAGE_1,
            content="hello",
            created=datetime(2026, 4, 18, 12, tzinfo=timezone.utc),
            sender=SimpleNamespace(is_staff=True),
        )
        result = _serialize_thread(patient, last_message, unread=2)
        assert result == {
            "patient_id": PATIENT_1,
            "patient_name": "Jane Doe",
            "last_message": {
                "id": MESSAGE_1,
                "content": "hello",
                "created": "2026-04-18T12:00:00+00:00",
                "sent_by_me": True,
            },
            "unread_count": 2,
        }

    def test_without_last_message(self) -> None:
        patient = SimpleNamespace(id=PATIENT_1, first_name="Jane", last_name="Doe")
        result = _serialize_thread(patient, None, unread=0)
        assert result["last_message"] is None
        assert result["unread_count"] == 0

    def test_patient_sender_sets_sent_by_me_false(self) -> None:
        patient = SimpleNamespace(id=PATIENT_1, first_name="Jane", last_name="Doe")
        last_message = SimpleNamespace(
            id=MESSAGE_1,
            content="hi",
            created=datetime(2026, 4, 18, 12, tzinfo=timezone.utc),
            sender=SimpleNamespace(is_staff=False),
        )
        assert _serialize_thread(patient, last_message, 0)["last_message"]["sent_by_me"] is False

    def test_null_sender_sent_by_me_false(self) -> None:
        patient = SimpleNamespace(id=PATIENT_1, first_name="Jane", last_name="Doe")
        last_message = SimpleNamespace(
            id=MESSAGE_1,
            content="hi",
            created=None,
            sender=None,
        )
        serialized = _serialize_thread(patient, last_message, 0)
        assert serialized["last_message"]["sent_by_me"] is False
        assert serialized["last_message"]["created"] is None


class TestSerializeMessage:
    def test_outbound_from_this_staff(self) -> None:
        message = SimpleNamespace(
            id=MESSAGE_1,
            content="ok",
            created=datetime(2026, 4, 18, 12, tzinfo=timezone.utc),
            read=None,
            sender=SimpleNamespace(
                is_staff=True,
                person_subclass=SimpleNamespace(id=STAFF_UUID),
            ),
        )
        result = _serialize_message(message, STAFF_UUID)
        assert result["sent_by_me"] is True
        assert result["read"] is None
        assert result["created"] == "2026-04-18T12:00:00+00:00"

    def test_inbound_from_patient(self) -> None:
        message = SimpleNamespace(
            id=MESSAGE_1,
            content="hi",
            created=datetime(2026, 4, 18, 12, tzinfo=timezone.utc),
            read=datetime(2026, 4, 18, 12, 5, tzinfo=timezone.utc),
            sender=SimpleNamespace(
                is_staff=False,
                person_subclass=SimpleNamespace(id=PATIENT_1),
            ),
        )
        result = _serialize_message(message, STAFF_UUID)
        assert result["sent_by_me"] is False
        assert result["read"] == "2026-04-18T12:05:00+00:00"

    def test_staff_sender_different_from_logged_in(self) -> None:
        message = SimpleNamespace(
            id=MESSAGE_1,
            content="",
            created=None,
            read=None,
            sender=SimpleNamespace(
                is_staff=True,
                person_subclass=SimpleNamespace(id="other-staff"),
            ),
        )
        assert _serialize_message(message, STAFF_UUID)["sent_by_me"] is False

    def test_null_sender(self) -> None:
        message = SimpleNamespace(
            id=MESSAGE_1, content="", created=None, read=None, sender=None,
        )
        assert _serialize_message(message, STAFF_UUID)["sent_by_me"] is False


class TestAuthenticate:
    def test_staff_session_passes(self) -> None:
        api = _make_api()
        creds = MagicMock(logged_in_user={"id": STAFF_UUID, "type": "Staff"})
        assert api.authenticate(creds) is True

    def test_patient_session_rejected(self) -> None:
        api = _make_api()
        creds = MagicMock(logged_in_user={"id": STAFF_UUID, "type": "Patient"})
        with pytest.raises(InvalidCredentialsError):
            api.authenticate(creds)


class TestIndex:
    def test_returns_html_with_ws_url_and_cache_bust(self) -> None:
        api = _make_api()
        with patch.object(messages_api, "render_to_string", return_value="<html/>") as mock_render:
            response = api.index()[0]

        assert response.status_code == HTTPStatus.OK
        ctx = mock_render.mock_calls[0].args[1]
        assert ctx["ws_url"] == (
            "/plugin-io/ws/provider_patient_messages_companion/staff-"
            + STAFF_UUID + "/"
        )
        assert ctx["cache_bust"] == messages_api._CACHE_BUST


class TestThreadsEndpoint:
    def test_empty_panel(self) -> None:
        api = _make_api()
        with (
            patch.object(messages_api, "_panel_patients", return_value={}),
            patch.object(messages_api, "_latest_message_per_thread", return_value=[]),
            patch.object(messages_api, "_unread_counts", return_value={}),
        ):
            response = api.threads()[0]
        assert json.loads(response.content) == {"threads": []}

    def test_assembles_threads_including_empty_and_unread(self) -> None:
        api = _make_api()
        patient_1 = SimpleNamespace(id=PATIENT_1, first_name="Ann", last_name="Alpha")
        patient_2 = SimpleNamespace(id=PATIENT_2, first_name="Ben", last_name="Bravo")
        panel = {PATIENT_1: patient_1, PATIENT_2: patient_2}

        last_msg = SimpleNamespace(
            id=MESSAGE_1,
            content="most recent",
            created=datetime(2026, 4, 18, 12, tzinfo=timezone.utc),
            sender=SimpleNamespace(is_staff=False),
            thread_patient_id=PATIENT_1,
        )
        with (
            patch.object(messages_api, "_panel_patients", return_value=panel),
            patch.object(messages_api, "_latest_message_per_thread", return_value=[last_msg]),
            patch.object(messages_api, "_unread_counts", return_value={PATIENT_1: 2}),
        ):
            response = api.threads()[0]

        payload = json.loads(response.content)["threads"]
        assert payload[0]["patient_id"] == PATIENT_1
        assert payload[0]["unread_count"] == 2
        assert payload[0]["last_message"]["content"] == "most recent"
        assert payload[1]["patient_id"] == PATIENT_2
        assert payload[1]["unread_count"] == 0
        assert payload[1]["last_message"] is None


class TestConversationEndpoint:
    def _patched_messages(self, messages):
        queryset = MagicMock()
        queryset.filter.return_value = queryset
        queryset.select_related.return_value = queryset
        queryset.order_by.return_value = messages
        queryset.__getitem__.return_value = messages
        mock_model = MagicMock()
        mock_model.objects.filter.return_value = queryset
        return queryset, mock_model

    def test_not_on_panel_returns_404(self) -> None:
        api = _make_api(path_params={"patient_id": PATIENT_1})
        with patch.object(messages_api, "_panel_patients", return_value={}):
            response = api.conversation()[0]
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_invalid_before_returns_400(self) -> None:
        api = _make_api(
            path_params={"patient_id": PATIENT_1},
            query_params={"before": "not-a-date"},
        )
        panel = {PATIENT_1: SimpleNamespace(id=PATIENT_1)}
        with patch.object(messages_api, "_panel_patients", return_value=panel):
            response = api.conversation()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_success_returns_messages_chronological(self) -> None:
        api = _make_api(
            path_params={"patient_id": PATIENT_1},
            query_params={"limit": "5", "before": "2026-04-19T00:00:00Z"},
        )
        patient = SimpleNamespace(id=PATIENT_1, first_name="Jane", last_name="Doe")
        panel = {PATIENT_1: patient}

        msg_new = SimpleNamespace(
            id="msg-new", content="b", created=datetime(2026, 4, 18, 13, tzinfo=timezone.utc),
            read=None,
            sender=SimpleNamespace(is_staff=False, person_subclass=SimpleNamespace(id=PATIENT_1)),
        )
        msg_old = SimpleNamespace(
            id="msg-old", content="a", created=datetime(2026, 4, 18, 12, tzinfo=timezone.utc),
            read=None,
            sender=SimpleNamespace(is_staff=True, person_subclass=SimpleNamespace(id=STAFF_UUID)),
        )
        descending = [msg_new, msg_old]
        _, mock_model = self._patched_messages(descending)

        with (
            patch.object(messages_api, "_panel_patients", return_value=panel),
            patch.object(messages_api, "Message", mock_model),
        ):
            response = api.conversation()[0]

        payload = json.loads(response.content)["messages"]
        # Returned in chronological order (oldest first).
        assert [m["id"] for m in payload] == ["msg-old", "msg-new"]
        assert payload[1]["sent_by_me"] is False

    def test_limit_nonpositive_falls_back_to_default(self) -> None:
        api = _make_api(
            path_params={"patient_id": PATIENT_1},
            query_params={"limit": "0"},
        )
        panel = {PATIENT_1: SimpleNamespace(id=PATIENT_1)}
        _, mock_model = self._patched_messages([])
        with (
            patch.object(messages_api, "_panel_patients", return_value=panel),
            patch.object(messages_api, "Message", mock_model),
        ):
            response = api.conversation()[0]
        # The branch that resets `limit` runs; endpoint still succeeds.
        assert response.status_code == HTTPStatus.OK

    def test_invalid_limit_value_falls_back(self) -> None:
        api = _make_api(
            path_params={"patient_id": PATIENT_1},
            query_params={"limit": "not-a-number"},
        )
        panel = {PATIENT_1: SimpleNamespace(id=PATIENT_1)}
        queryset, mock_model = self._patched_messages([])
        with (
            patch.object(messages_api, "_panel_patients", return_value=panel),
            patch.object(messages_api, "Message", mock_model),
        ):
            response = api.conversation()[0]
        assert response.status_code == HTTPStatus.OK


class TestSendEndpoint:
    def test_not_on_panel_returns_404(self) -> None:
        api = _make_api(
            path_params={"patient_id": PATIENT_1},
            json_body={"content": "hi"},
        )
        with patch.object(messages_api, "_panel_patients", return_value={}):
            response = api.send()[0]
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_empty_content_returns_400(self) -> None:
        api = _make_api(
            path_params={"patient_id": PATIENT_1},
            json_body={"content": "   "},
        )
        panel = {PATIENT_1: SimpleNamespace(id=PATIENT_1)}
        with patch.object(messages_api, "_panel_patients", return_value=panel):
            response = api.send()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_missing_content_key_returns_400(self) -> None:
        api = _make_api(path_params={"patient_id": PATIENT_1}, json_body={})
        panel = {PATIENT_1: SimpleNamespace(id=PATIENT_1)}
        with patch.object(messages_api, "_panel_patients", return_value=panel):
            response = api.send()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_null_body_returns_400(self) -> None:
        api = _make_api(path_params={"patient_id": PATIENT_1}, json_body=None)
        api.request.json = lambda: None
        panel = {PATIENT_1: SimpleNamespace(id=PATIENT_1)}
        with patch.object(messages_api, "_panel_patients", return_value=panel):
            response = api.send()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_success_emits_create_message(self) -> None:
        api = _make_api(
            path_params={"patient_id": PATIENT_1},
            json_body={"content": "reply"},
        )
        panel = {PATIENT_1: SimpleNamespace(id=PATIENT_1)}
        with (
            patch.object(messages_api, "_panel_patients", return_value=panel),
            _effect_validation_bypass(),
        ):
            effect, response = api.send()

        assert response.status_code == HTTPStatus.ACCEPTED
        assert effect.type == EffectType.CREATE_MESSAGE
        data = json.loads(effect.payload)["data"]
        assert data["sender_id"] == STAFF_UUID
        assert data["recipient_id"] == PATIENT_1
        assert data["content"] == "reply"


class TestMarkReadEndpoint:
    def test_not_on_panel_returns_404(self) -> None:
        api = _make_api(path_params={"patient_id": PATIENT_1})
        with patch.object(messages_api, "_panel_patients", return_value={}):
            response = api.mark_read()[0]
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_no_unread_returns_zero(self) -> None:
        api = _make_api(path_params={"patient_id": PATIENT_1})
        panel = {PATIENT_1: SimpleNamespace(id=PATIENT_1)}

        queryset = MagicMock()
        queryset.values_list.return_value = []
        mock_model = MagicMock()
        mock_model.objects.filter.return_value = queryset

        with (
            patch.object(messages_api, "_panel_patients", return_value=panel),
            patch.object(messages_api, "Message", mock_model),
        ):
            response = api.mark_read()[0]

        assert json.loads(response.content) == {"marked": 0}

    def test_unread_emits_edit_effects(self) -> None:
        api = _make_api(path_params={"patient_id": PATIENT_1})
        panel = {PATIENT_1: SimpleNamespace(id=PATIENT_1)}

        queryset = MagicMock()
        queryset.values_list.return_value = [
            ("msg-a", "hi"),
            ("msg-b", "there"),
        ]
        mock_model = MagicMock()
        mock_model.objects.filter.return_value = queryset

        with (
            patch.object(messages_api, "_panel_patients", return_value=panel),
            patch.object(messages_api, "Message", mock_model),
            _effect_validation_bypass(),
        ):
            result = api.mark_read()

        effects = result[:-1]
        response = result[-1]
        assert len(effects) == 2
        assert all(e.type == EffectType.EDIT_MESSAGE for e in effects)
        first_data = json.loads(effects[0].payload)["data"]
        assert first_data["message_id"] == "msg-a"
        assert first_data["read"] is not None
        assert json.loads(response.content) == {"marked": 2}


class TestStaticEndpoints:
    def test_main_js(self) -> None:
        api = _make_api()
        with patch.object(messages_api, "render_to_string", return_value="// js"):
            response = api.main_js()[0]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"// js"
        assert response.headers["Content-Type"] == "text/javascript"

    def test_styles_css(self) -> None:
        api = _make_api()
        with patch.object(messages_api, "render_to_string", return_value="body{}"):
            response = api.styles_css()[0]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"body{}"
        assert response.headers["Content-Type"] == "text/css"
