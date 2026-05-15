"""Tests for availability_web_app.py."""

from unittest.mock import MagicMock, patch

from provider_availability_manager.handlers.availability_web_app import (
    AvailabilityWebApp,
    _safe_json_for_script,
)


def test_safe_json_for_script_escapes_script_breakout():
    payload = [{"name": "Bob</script><script>alert(1)</script>"}]
    out = _safe_json_for_script(payload)
    # Critical characters must be hex-escaped so the surrounding <script> tag
    # in the template can't be terminated.
    assert "</script>" not in out
    assert "\\u003c" in out
    assert "\\u003e" in out


def test_safe_json_for_script_escapes_ampersand_and_apostrophe():
    out = _safe_json_for_script({"k": "a&b'c"})
    assert "\\u0026" in out
    assert "\\u0027" in out


def test_safe_json_for_script_round_trips_via_json_parse():
    """Browser JSON.parse should still recover the original value."""
    import json

    original = {"name": "<a>&'\"></a>", "n": 5, "ok": True}
    out = _safe_json_for_script(original)
    assert json.loads(out) == original


def _handler(request_headers=None, secrets=None):
    h = AvailabilityWebApp.__new__(AvailabilityWebApp)
    request = MagicMock()
    request.headers = request_headers or {}
    h.request = request
    h.secrets = secrets or {"SCHEDULABLE_STAFF_ROLES": "MD,NP"}
    return h


def test_index_returns_html_response():
    h = _handler(request_headers={"canvas-logged-in-user-id": "user-1"})

    provider = MagicMock()
    provider.id = "prov-1"
    provider.credentialed_name = "Bob, MD"
    provider.full_name = "Bob Smith"

    location = MagicMock()
    location.id = "loc-1"
    location.full_name = "Loc"

    note_type = MagicMock()
    note_type.id = "nt-1"
    note_type.name = "Visit"

    event = MagicMock()

    with patch(
        "provider_availability_manager.handlers.availability_web_app.Staff"
    ) as mock_staff, patch(
        "provider_availability_manager.handlers.availability_web_app.PracticeLocation"
    ) as mock_loc, patch(
        "provider_availability_manager.handlers.availability_web_app.NoteType"
    ) as mock_nt, patch(
        "provider_availability_manager.handlers.availability_web_app.Event"
    ) as mock_event_cls, patch(
        "provider_availability_manager.handlers.availability_web_app.render_to_string",
        return_value="<html>",
    ), patch(
        "provider_availability_manager.handlers.availability_web_app._serialize_event",
        return_value={"id": "ev-1"},
    ):
        # Two filter chains with .distinct()
        providers_qs = MagicMock()
        providers_qs.__iter__ = lambda self: iter([provider])
        mock_staff.objects.filter.return_value.distinct.return_value = providers_qs
        mock_staff.objects.filter.return_value.values_list.return_value = ["prov-1"]
        mock_loc.objects.filter.return_value = [location]
        # Two NoteType.objects calls: filter() and all().
        mock_nt.objects.filter.return_value = [note_type]
        mock_nt.objects.all.return_value = [note_type]
        mock_event_cls.objects.all.return_value.select_related.return_value.prefetch_related.return_value = [event]

        result = h.index()
        assert len(result) == 1


def test_get_main_js_returns_response():
    h = _handler()
    with patch(
        "provider_availability_manager.handlers.availability_web_app.render_to_string",
        return_value="// js",
    ):
        result = h.get_main_js()
        assert len(result) == 1


def test_get_css_returns_response():
    h = _handler()
    with patch(
        "provider_availability_manager.handlers.availability_web_app.render_to_string",
        return_value="body{}",
    ):
        result = h.get_css()
        assert len(result) == 1
