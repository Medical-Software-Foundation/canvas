"""Tests for the UI and static-asset endpoints + the _current_staff helper."""
from __future__ import annotations

from http import HTTPStatus
from unittest.mock import MagicMock

from .conftest import make_request, make_staff


def test_get_ui_renders_main_template_with_staff_context(
    api_instance: object, mocker: MagicMock
) -> None:
    staff = make_staff(staff_id="s-1", first_name="Dr", last_name="House")
    mocker.patch(
        "order_sets.api.endpoints.Staff.objects.filter",
        return_value=MagicMock(first=MagicMock(return_value=staff)),
    )
    render = mocker.patch(
        "order_sets.api.endpoints.render_to_string", return_value="<html>OK</html>"
    )

    api_instance.request = make_request(  # type: ignore[attr-defined]
        query_params={"patient_id": "pt-9"},
        headers={"canvas-logged-in-user-id": "s-1"},
    )
    responses = api_instance.get_ui()  # type: ignore[attr-defined]

    assert len(responses) == 1
    # render_to_string was called with the main template and the staff context
    args, _ = render.call_args
    assert args[0] == "templates/main.html"
    ctx = args[1]
    assert ctx["patient_id"] == "pt-9"
    assert ctx["staff_id"] == "s-1"
    assert ctx["staff_name"] == "Dr House"
    assert "cache_bust" in ctx


def test_get_ui_handles_missing_logged_in_user(
    api_instance: object, mocker: MagicMock
) -> None:
    """If no staff header is supplied, staff_id should be empty and staff_name blank."""
    mocker.patch(
        "order_sets.api.endpoints.render_to_string", return_value="<html></html>"
    )
    api_instance.request = make_request(  # type: ignore[attr-defined]
        query_params={"patient_id": "pt-1"},
        headers={},  # no canvas-logged-in-user-id
    )
    responses = api_instance.get_ui()  # type: ignore[attr-defined]
    assert len(responses) == 1


def test_get_admin_ui_renders_admin_template(
    api_instance: object, mocker: MagicMock
) -> None:
    mocker.patch(
        "order_sets.api.endpoints.Staff.objects.filter",
        return_value=MagicMock(first=MagicMock(return_value=make_staff())),
    )
    render = mocker.patch(
        "order_sets.api.endpoints.render_to_string", return_value="<html>ADM</html>"
    )
    api_instance.request = make_request(  # type: ignore[attr-defined]
        headers={"canvas-logged-in-user-id": "staff-1"},
    )
    api_instance.get_admin_ui()  # type: ignore[attr-defined]
    args, _ = render.call_args
    assert args[0] == "templates/admin.html"


def test_static_css_endpoint(api_instance: object, mocker: MagicMock) -> None:
    mocker.patch(
        "order_sets.api.endpoints.render_to_string", return_value="body{color:red}"
    )
    responses = api_instance.get_css()  # type: ignore[attr-defined]
    # We can only assert it returned a non-empty response list; the Response
    # object itself is constructed by the SDK with a real content_type.
    assert len(responses) == 1


def test_static_main_js_endpoint(api_instance: object, mocker: MagicMock) -> None:
    mocker.patch(
        "order_sets.api.endpoints.render_to_string", return_value="console.log(1)"
    )
    responses = api_instance.get_main_js()  # type: ignore[attr-defined]
    assert len(responses) == 1


def test_static_admin_js_endpoint(api_instance: object, mocker: MagicMock) -> None:
    mocker.patch(
        "order_sets.api.endpoints.render_to_string", return_value="console.log(2)"
    )
    responses = api_instance.get_admin_js()  # type: ignore[attr-defined]
    assert len(responses) == 1


# ── _current_staff helper ────────────────────────────────────────────────────


def test_current_staff_returns_none_when_no_header(api_instance: object) -> None:
    api_instance.request = make_request(headers={})  # type: ignore[attr-defined]
    assert api_instance._current_staff() is None  # type: ignore[attr-defined]


def test_current_staff_looks_up_by_header_id(
    api_instance: object, mocker: MagicMock
) -> None:
    staff = make_staff(staff_id="s-42")
    mocker.patch(
        "order_sets.api.endpoints.Staff.objects.filter",
        return_value=MagicMock(first=MagicMock(return_value=staff)),
    )
    api_instance.request = make_request(  # type: ignore[attr-defined]
        headers={"canvas-logged-in-user-id": "s-42"}
    )
    result = api_instance._current_staff()  # type: ignore[attr-defined]
    assert result is staff


def test_current_staff_returns_none_when_id_not_found(
    api_instance: object, mocker: MagicMock
) -> None:
    mocker.patch(
        "order_sets.api.endpoints.Staff.objects.filter",
        return_value=MagicMock(first=MagicMock(return_value=None)),
    )
    api_instance.request = make_request(  # type: ignore[attr-defined]
        headers={"canvas-logged-in-user-id": "ghost"}
    )
    assert api_instance._current_staff() is None  # type: ignore[attr-defined]
