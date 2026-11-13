import json
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.templates.utils import _engine_for_plugin

from auto_fax.handlers import fax_orders_api, fax_orders_button
from auto_fax.handlers.fax_orders_api import FaxOrdersAPI
from auto_fax.handlers.fax_orders_button import (
    API_PATH,
    FaxOrdersButton,
    _safe_json,
    preview_context,
)
from auto_fax.services.config import (
    SEND_ORDER_DOCUMENTS,
    SEND_WHOLE_NOTE,
    TRIGGER_FAX_ORDERS_BUTTON,
    RecipientSpec,
    Rule,
)
from auto_fax.services.orders import Delivery, Order, Plan

BUTTON = "auto_fax.handlers.fax_orders_button"
API = "auto_fax.handlers.fax_orders_api"
PLUGIN_DIR = Path(fax_orders_button.__file__).resolve().parents[1]
T0 = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)

RULE = Rule(
    name="orders",
    note_type_codes=frozenset({"*"}),
    trigger_states=frozenset(),
    recipients=(RecipientSpec(type="facility"),),
    trigger=TRIGGER_FAX_ORDERS_BUTTON,
    order_types=frozenset({"lab", "dme"}),
    send_as=SEND_WHOLE_NOTE,
)
LAB = Order("c1", "lab", "CBC", T0, None)
DME = Order("c2", "dme", "", T0, None)


def _secrets(mode="live"):
    rule = {
        "name": "orders",
        "trigger": "fax_orders_button",
        "note_type_codes": ["*"],
        "order_types": ["lab"],
        "send_as": "whole_note",
        "recipients": [{"type": "facility"}],
    }
    return {
        "AUTO_FAX_MODE": mode,
        "AUTO_FAX_RULES": json.dumps([rule]),
        "AUTO_FAX_TEST_FAX_NUMBER": "",
    }


def _plan(deliveries=(), problems=(), metadata_notes=()):
    return Plan(
        note_id="note-1",
        location_id="loc-1",
        deliveries=list(deliveries),
        problems=list(problems),
        order_types=frozenset({"lab", "dme"}),
        metadata_notes=list(metadata_notes),
    )


def _delivery(send_as=SEND_WHOLE_NOTE, already=False, last_sent=None, name="Oak"):
    return Delivery(
        name=name,
        kind="facility",
        digits="5552340111",
        rule=RULE,
        send_as=send_as,
        orders=[LAB, DME],
        unsent=[LAB],
        already_sent=already,
        last_sent=last_sent,
    )


# --- preview ----------------------------------------------------------------


def test_safe_json_cannot_close_the_script_tag():
    assert _safe_json({"a": "</script>&"}) == ('{"a": "\\u003c/script\\u003e\\u0026"}')


def test_preview_context():
    plan = _plan(
        [_delivery(already=True, last_sent=T0, name="")],
        metadata_notes=["Prescription: only alert_facility = Yes"],
    )
    context = preview_context(plan, dry_run=True)
    assert context["deliveries"] == [
        {
            "name": "Recipient",
            "fax": "(555) 234-0111",
            "whole_note": True,
            "fax_count": 1,
            "already_sent": True,
            "last_sent": "2026-11-04T15:00:00+00:00",
            "orders": [
                {"type": "Lab order", "label": "CBC"},
                {"type": "DME order", "label": ""},
            ],
        }
    ]
    assert context["order_types"] == "DME order, Lab order"
    assert context["has_orders"] is True
    assert context["all_already_sent"] is True
    assert context["dry_run"] is True
    assert context["request_json"] == '{"note_id": "note-1"}'
    assert context["api_path"] == API_PATH == "/plugin-io/api/auto_fax/fax-orders/send"


def test_preview_context_order_documents_and_never_sent():
    context = preview_context(
        _plan([_delivery(send_as=SEND_ORDER_DOCUMENTS)]), dry_run=False
    )
    (delivery,) = context["deliveries"]
    assert delivery["whole_note"] is False
    assert delivery["fax_count"] == 1
    assert delivery["last_sent"] == ""


@pytest.mark.parametrize(
    ("plan", "expected", "unexpected"),
    [
        (_plan([_delivery()]), ["To Oak, fax (555) 234-0111", "CBC", "Send fax"], []),
        (
            _plan([_delivery(already=True, last_sent=T0)]),
            ["Send again", 'data-resend="true"', "Already faxed"],
            ["Send fax"],
        ),
        (
            _plan(problems=["Oak House (facility): facility has no fax number"]),
            ["Can't fax Oak House", "Nothing to fax", "Fix the problem above"],
            ['id="send"'],
        ),
        (_plan(), ["no committed orders of these types: DME order, Lab order"], []),
    ],
)
def test_template_renders(plan, expected, unexpected):
    html = _engine_for_plugin(str(PLUGIN_DIR)).render_to_string(
        str(PLUGIN_DIR / "templates" / "fax_orders_modal.html"),
        context=preview_context(plan, dry_run=False),
    )
    for text in expected:
        assert text in html
    for text in unexpected:
        assert text not in html


# --- button -----------------------------------------------------------------


def _button(context=None, mode="live"):
    button = FaxOrdersButton.__new__(FaxOrdersButton)
    button.event = SimpleNamespace(context=context)
    button.secrets = _secrets(mode)
    return button


def test_button_metadata():
    assert FaxOrdersButton.BUTTON_TITLE == "Fax orders"
    assert FaxOrdersButton.BUTTON_KEY == "AUTO_FAX_FAX_ORDERS"
    assert FaxOrdersButton.BUTTON_LOCATION == FaxOrdersButton.ButtonLocation.NOTE_HEADER


@pytest.mark.parametrize(("found", "visible"), [(None, False), (("n", [RULE]), True)])
def test_button_visibility(found, visible):
    with patch(f"{BUTTON}.find_note", return_value=found) as find:
        assert _button({"note_id": 7}).visible() is visible
    assert find.call_args.kwargs == {"dbid": 7}


def test_button_hidden_with_no_context():
    with patch(f"{BUTTON}.find_note", return_value=None) as find:
        assert _button(None).visible() is False
    assert find.call_args.kwargs == {"dbid": None}


def test_click_on_an_uncovered_note_does_nothing():
    with patch(f"{BUTTON}.find_note", return_value=None):
        assert _button({"note_id": 7}).handle() == []


def test_click_opens_the_preview():
    plan = _plan([_delivery()])
    with (
        patch(f"{BUTTON}.find_note", return_value=("note", [RULE])),
        patch(f"{BUTTON}.build_plan", return_value=plan) as build,
        patch(f"{BUTTON}.render_to_string", return_value="<html>") as render,
        patch(f"{BUTTON}.LaunchModalEffect") as modal,
    ):
        effects = _button({"note_id": 7}, mode="dry_run").handle()
    build.assert_called_once_with("note", [RULE], None)
    template, context = render.call_args.args
    assert template == "templates/fax_orders_modal.html"
    assert context["dry_run"] is True
    modal.assert_called_once_with(
        target=modal.TargetType.DEFAULT_MODAL, content="<html>", title="Fax orders"
    )
    assert effects == [modal.return_value.apply.return_value]


# --- API --------------------------------------------------------------------


def _api(body, mode="live", raises=False):
    handler = FaxOrdersAPI.__new__(FaxOrdersAPI)
    request = MagicMock()
    if raises:
        request.json.side_effect = ValueError("bad json")
    else:
        request.json.return_value = body
    request.headers = {"canvas-logged-in-user-id": "staff-1"}
    handler.request = request
    handler.secrets = _secrets(mode)
    return handler


def _body(response):
    return json.loads(response.content)


def test_api_route():
    assert FaxOrdersAPI.PREFIX == "/fax-orders"


@pytest.mark.parametrize(
    "handler",
    [
        _api(None, raises=True),
        _api([]),
        _api({}),
        _api({"note_id": 7}),
    ],
)
def test_api_rejects_a_bad_body(handler):
    (response,) = handler.send()
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert _body(response) == {"status": "error", "message": "note_id is required"}


@pytest.mark.parametrize("body", [{"note_id": "  "}, {"note_id": "note-9"}])
def test_api_unknown_note(body):
    with patch(f"{API}.find_note", return_value=None):
        (response,) = _api(body).send()
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert _body(response)["message"] == "Fax orders is not available for this note."


@pytest.mark.parametrize(
    ("problems", "message"),
    [
        ([], "Nothing was sent: this note has no committed orders to fax."),
        (
            ["Oak House (facility): facility has no fax number"],
            "Nothing was sent. Oak House (facility): facility has no fax number",
        ),
    ],
)
def test_api_nothing_to_send(problems, message):
    with (
        patch(f"{API}.find_note", return_value=("note", [RULE])),
        patch(f"{API}.build_plan", return_value=_plan(problems=problems)),
        patch(f"{API}.fax_effects") as fax,
    ):
        (response,) = _api({"note_id": "note-1"}).send()
    assert _body(response) == {"status": "nothing", "faxes": 0, "message": message}
    fax.assert_not_called()


@pytest.mark.parametrize(
    ("mode", "resend", "result", "status", "message"),
    [
        ("live", False, ([], 0), "already_sent", "These orders were already faxed."),
        ("dry_run", False, ([], 2), "dry_run", "Dry run: 2 fax(es) would be sent."),
        ("live", True, (["e1", "e2"], 2), "sent", "Sent 2 fax(es)."),
    ],
)
def test_api_send(mode, resend, result, status, message):
    plan = _plan([_delivery()])
    with (
        patch(f"{API}.find_note", return_value=("note", [RULE])) as find,
        patch(f"{API}.build_plan", return_value=plan),
        patch(f"{API}.fax_effects", return_value=result) as fax,
        patch(f"{API}.log") as log,
    ):
        response, *effects = _api(
            {"note_id": " note-1 ", "resend": resend}, mode=mode
        ).send()
    assert find.call_args.kwargs == {"note_id": "note-1"}
    fax.assert_called_once_with(plan, resend=resend, dry_run=mode == "dry_run")
    body = _body(response)
    assert body["status"] == status
    assert body["faxes"] == result[1]
    assert body["message"].startswith(message)
    assert effects == result[0]
    logged = log.info.call_args.args[0]
    assert "by staff staff-1" in logged
    assert ("(resend)" in logged) is resend


def test_api_resend_must_be_exactly_true():
    with (
        patch(f"{API}.find_note", return_value=("note", [RULE])),
        patch(f"{API}.build_plan", return_value=_plan([_delivery()])),
        patch(f"{API}.fax_effects", return_value=([], 0)) as fax,
    ):
        _api({"note_id": "note-1", "resend": "true"}).send()
    assert fax.call_args.kwargs["resend"] is False


def test_modules_import():
    assert fax_orders_api.FaxOrdersAPI is FaxOrdersAPI
    assert fax_orders_button.FaxOrdersButton is FaxOrdersButton
