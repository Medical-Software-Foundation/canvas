"""Tests for the admin API: access gating, CSRF defence, body parsing, and each endpoint."""

import json
import re
from base64 import b64encode
from http import HTTPStatus
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from canvas_generated.messages.events_pb2 import Event as EventRequest
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse
from canvas_sdk.events import Event, EventType

from questionnaire_followup.api import routes
from questionnaire_followup.api.admin_page import ACCESS_DENIED_HTML
from questionnaire_followup.api.routes import FollowUpAdminAPI
from questionnaire_followup.services.config_store import COMPARATORS, MAX_RULES

MODULE = "questionnaire_followup.api.routes"
READ_STAFF_ID = call.headers.get("canvas-logged-in-user-id", "")
READ_ADMIN_KEYS = call.get("ADMIN_STAFF_KEYS")
UNCONFIGURED_WARNING = call.warning(
    "ADMIN_STAFF_KEYS not configured, denying Questionnaire Follow-Up access"
)

FORBIDDEN = JSONResponse({"error": "forbidden"}, status_code=HTTPStatus.FORBIDDEN)
UNSUPPORTED_MEDIA_TYPE = JSONResponse(
    {"success": False, "error": "Content-Type must be application/json"},
    status_code=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
)

# Every route, what a non-admin gets back from it, and the dependency that must not
# be touched on the way. `test_denial_cases_cover_every_route` keeps this in step
# with the routes actually registered, so a new route cannot ship ungated.
DENIAL_CASES = [
    (
        "GET",
        "/admin/ui",
        "serve_admin",
        "build_admin_html",
        HTMLResponse(ACCESS_DENIED_HTML, status_code=HTTPStatus.FORBIDDEN),
    ),
    ("GET", "/admin/config", "get_config", "load_config", FORBIDDEN),
    (
        "POST",
        "/admin/config",
        "put_config",
        "save_config",
        JSONResponse({"success": False, "error": "forbidden"}, status_code=HTTPStatus.FORBIDDEN),
    ),
    ("GET", "/admin/questionnaires", "admin_questionnaires", "list_questionnaires", FORBIDDEN),
    ("GET", "/admin/diagnose", "diagnose", "owed_forms", FORBIDDEN),
]


def _denied_warning(staff_id: str) -> Any:
    return call.warning(f"Questionnaire Follow-Up access denied for staff key '{staff_id}'")


def _event(method: str, path: str, **context: Any) -> Event:
    return Event(
        EventRequest(
            type=EventType.SIMPLE_API_REQUEST,
            context=json.dumps({"method": method, "path": path, **context}),
        )
    )


def _api(
    method: str, path: str, request: MagicMock, secrets: MagicMock | None = None
) -> FollowUpAdminAPI:
    api = FollowUpAdminAPI(event=_event(method, path))
    api.request = request
    if secrets is not None:
        api.secrets = secrets
    return api


def _request(staff_id: str, content_type: str | None = None) -> MagicMock:
    request = MagicMock()
    request.headers.get.return_value = staff_id
    request.content_type = content_type
    return request


def _secrets(admin_staff_keys: str | None) -> MagicMock:
    secrets = MagicMock()
    secrets.get.return_value = admin_staff_keys
    return secrets


# --------------------------------------------------------------------------- #
#  Access gating
# --------------------------------------------------------------------------- #


def test_listed_staff_is_allowed() -> None:
    """A staff key on the configured list gets in, even with messy separators."""
    request = _request("staff-2")
    secrets = _secrets(" staff-1 , staff-2 ,, ")

    with patch(f"{MODULE}.log") as mock_log:
        result = _api("GET", "/admin/ui", request, secrets)._admin_allowed()

        assert mock_log.mock_calls == []
        assert request.mock_calls == [READ_STAFF_ID]
        assert secrets.mock_calls == [READ_ADMIN_KEYS]
        assert result is True


@pytest.mark.parametrize(
    ("staff_id", "admin_staff_keys"),
    [
        pytest.param("staff-3", "staff-1,staff-2", id="unlisted-key"),
        pytest.param("staff-1", "staff-12", id="prefix-of-a-listed-key"),
        pytest.param("", "staff-1", id="no-logged-in-user"),
        pytest.param("staff-1", " , ,", id="only-separators"),
    ],
)
def test_unlisted_staff_is_refused_and_logged(staff_id: str, admin_staff_keys: str) -> None:
    """Anything but an exact match is refused, and the attempt leaves a trace."""
    request = _request(staff_id)
    secrets = _secrets(admin_staff_keys)

    with patch(f"{MODULE}.log") as mock_log:
        result = _api("GET", "/admin/ui", request, secrets)._admin_allowed()

        assert mock_log.mock_calls == [_denied_warning(staff_id)]
        assert request.mock_calls == [READ_STAFF_ID]
        assert secrets.mock_calls == [READ_ADMIN_KEYS]
        assert result is False


@pytest.mark.parametrize("admin_staff_keys", [None, "", "   "], ids=["unset", "empty", "blank"])
def test_unconfigured_setting_fails_closed(admin_staff_keys: str | None) -> None:
    """With no admin list configured, nobody gets in, and it is logged."""
    request = _request("staff-1")
    secrets = _secrets(admin_staff_keys)

    with patch(f"{MODULE}.log") as mock_log:
        result = _api("GET", "/admin/ui", request, secrets)._admin_allowed()

        assert mock_log.mock_calls == [UNCONFIGURED_WARNING]
        assert request.mock_calls == [READ_STAFF_ID]
        assert secrets.mock_calls == [READ_ADMIN_KEYS]
        assert result is False


def test_no_staff_key_is_hardcoded_in_the_api_module() -> None:
    """No key is written into the source, whatever it is.

    An earlier version special-cased one specific staff key as break-glass access,
    on a claim - copied from a comment in another plugin - that it was a universal
    superuser id. Nothing substantiated that, and it was removed.

    This checks the module text rather than asserting one value is refused, which
    is both stronger (any hardcoded key fails, not just that one) and avoids
    reproducing such a value in a file that ships publicly.
    """
    source = Path(routes.__file__).read_text()

    assert re.findall(r"\b[0-9a-fA-F]{32}\b", source) == []
    assert re.findall(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b", source) == []


def test_an_unlisted_key_is_refused_when_nothing_is_configured() -> None:
    """Fails closed: with ADMIN_STAFF_KEYS unset, no key gets in at all."""
    request = _request("not-a-configured-staff-key")
    secrets = _secrets(None)

    with patch(f"{MODULE}.log") as mock_log:
        result = _api("GET", "/admin/ui", request, secrets)._admin_allowed()

        assert mock_log.mock_calls == [UNCONFIGURED_WARNING]
        assert request.mock_calls == [READ_STAFF_ID]
        assert secrets.mock_calls == [READ_ADMIN_KEYS]
        assert result is False


@pytest.mark.parametrize(("method", "path", "endpoint", "dependency", "expected"), DENIAL_CASES)
def test_every_endpoint_refuses_a_non_admin(
    method: str, path: str, endpoint: str, dependency: str, expected: HTMLResponse
) -> None:
    """A non-admin is turned away before any config is read, written or listed."""
    request = _request("staff-9", content_type="application/json")
    secrets = _secrets("staff-1")
    api = _api(method, path, request, secrets)

    with patch(f"{MODULE}.{dependency}") as mock_dependency, patch(f"{MODULE}.log") as mock_log:
        result = getattr(api, endpoint)()

        assert mock_dependency.mock_calls == []
        assert mock_log.mock_calls == [_denied_warning("staff-9")]
        assert request.mock_calls == [READ_STAFF_ID]  # the body is never parsed
        assert secrets.mock_calls == [READ_ADMIN_KEYS]
        assert result == [expected]


def test_denial_cases_cover_every_route() -> None:
    """Every registered route appears in the denial test above."""
    registered = {
        (method, pattern.pattern)
        for method, routes in FollowUpAdminAPI._ROUTES.items()
        for pattern, _handler in routes
    }

    assert registered == {(method, path) for method, path, *_ in DENIAL_CASES}


# --------------------------------------------------------------------------- #
#  CSRF defence on save
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "content_type",
    [
        pytest.param("text/plain", id="text-plain-form"),
        pytest.param("application/x-www-form-urlencoded", id="urlencoded-form"),
        pytest.param("multipart/form-data", id="multipart-form"),
        pytest.param(None, id="no-content-type"),
    ],
)
def test_put_config_refuses_a_body_a_cross_site_form_could_send(content_type: str | None) -> None:
    """Only application/json is accepted, so a forged form post never reaches the store."""
    request = _request("staff-1", content_type=content_type)
    request.json.return_value = {"config": {"rules": []}}
    secrets = _secrets("staff-1")

    with patch(f"{MODULE}.save_config") as mock_save_config:
        result = _api("POST", "/admin/config", request, secrets).put_config()

        assert mock_save_config.mock_calls == []
        assert request.mock_calls == [READ_STAFF_ID]  # the body is never parsed
        assert secrets.mock_calls == [READ_ADMIN_KEYS]
        assert result == [UNSUPPORTED_MEDIA_TYPE]


# The body a hostile page produces from <form enctype="text/plain"> with one input
# named `{"config":{"rules":[]},"x":"` and valued `"}`: the browser joins them with
# "=", and the result is valid JSON.
FORGED_FORM_BODY = b'{"config":{"rules":[]},"x":"="}'


@pytest.mark.parametrize(
    ("content_type", "saved", "expected"),
    [
        pytest.param("text/plain", [], [UNSUPPORTED_MEDIA_TYPE], id="forged-form-post-refused"),
        pytest.param(
            "application/json",
            [call({"rules": []})],
            [JSONResponse({"success": True})],
            id="same-body-as-json-saved",
        ),
    ],
)
def test_forged_form_body_is_stopped_by_content_type_alone(
    content_type: str, saved: list, expected: list
) -> None:
    """Through the SDK's real Request: the forged body parses, and only its type blocks it."""
    event = _event(
        "POST",
        "/admin/config",
        query_string="",
        body=b64encode(FORGED_FORM_BODY).decode(),
        headers={
            "Content-Type": content_type,
            "canvas-logged-in-user-id": "staff-1",
            "canvas-logged-in-user-type": "Staff",
        },
    )
    api = FollowUpAdminAPI(event=event, secrets={"ADMIN_STAFF_KEYS": "staff-1"})

    with patch(f"{MODULE}.save_config") as mock_save_config, patch(f"{MODULE}.log") as mock_log:
        mock_save_config.return_value = True

        result = api.put_config()

        assert mock_save_config.mock_calls == saved
        assert mock_log.mock_calls == []
        assert result == expected


# --------------------------------------------------------------------------- #
#  Request body parsing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("parsed", "expected"),
    [
        pytest.param({"config": {"rules": []}}, {"config": {"rules": []}}, id="object"),
        pytest.param([1, 2], {}, id="non-object"),
    ],
)
def test_parse_body_accepts_only_a_json_object(parsed: object, expected: dict) -> None:
    """A JSON body that is not an object is treated as empty."""
    request = MagicMock()
    request.json.return_value = parsed

    result = _api("POST", "/admin/config", request)._parse_body()

    assert request.mock_calls == [call.json()]
    assert result == expected


def test_parse_body_treats_an_undecodable_body_as_empty() -> None:
    """A body the SDK cannot decode reads as empty rather than raising."""
    request = MagicMock()
    request.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")

    result = _api("POST", "/admin/config", request)._parse_body()

    assert request.mock_calls == [call.json()]
    assert result == {}


# --------------------------------------------------------------------------- #
#  Endpoints, as an admin
# --------------------------------------------------------------------------- #


def test_serve_admin_returns_the_editor() -> None:
    """An admin gets the pairing editor page."""
    request = _request("staff-1")
    secrets = _secrets("staff-1")

    with patch(f"{MODULE}.build_admin_html") as mock_build_admin_html:
        mock_build_admin_html.return_value = "<html>editor</html>"

        result = _api("GET", "/admin/ui", request, secrets).serve_admin()

        assert mock_build_admin_html.mock_calls == [call()]
        assert request.mock_calls == [READ_STAFF_ID]
        assert secrets.mock_calls == [READ_ADMIN_KEYS]
        assert result == [HTMLResponse("<html>editor</html>")]


def test_get_config_returns_the_stored_rules() -> None:
    """An admin gets the current config document."""
    request = _request("staff-1")
    secrets = _secrets("staff-1")

    with patch(f"{MODULE}.load_config") as mock_load_config:
        mock_load_config.return_value = {"rules": [{"name": "Depression"}]}

        result = _api("GET", "/admin/config", request, secrets).get_config()

        assert mock_load_config.mock_calls == [call()]
        assert request.mock_calls == [READ_STAFF_ID]
        assert secrets.mock_calls == [READ_ADMIN_KEYS]
        assert result == [JSONResponse({"config": {"rules": [{"name": "Depression"}]}})]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="no-config"),
        pytest.param({"config": "rules"}, id="config-not-an-object"),
        pytest.param({"config": {}}, id="no-rules"),
        pytest.param({"config": {"rules": {"name": "Depression"}}}, id="rules-not-a-list"),
    ],
)
def test_put_config_rejects_a_malformed_document(body: dict) -> None:
    """A document without a rules list is refused rather than saved."""
    request = _request("staff-1", content_type="application/json")
    request.json.return_value = body
    secrets = _secrets("staff-1")

    with patch(f"{MODULE}.save_config") as mock_save_config:
        result = _api("POST", "/admin/config", request, secrets).put_config()

        assert mock_save_config.mock_calls == []
        assert request.mock_calls == [READ_STAFF_ID, call.json()]
        assert secrets.mock_calls == [READ_ADMIN_KEYS]
        assert result == [
            JSONResponse(
                {"success": False, "error": "Invalid configuration"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        ]


def test_put_config_refuses_more_rules_than_the_cap() -> None:
    """Every portal page load reads the rule set, so an oversized one is never saved."""
    rules = [{"name": f"Rule {i}"} for i in range(MAX_RULES + 1)]
    request = _request("staff-1", content_type="application/json")
    request.json.return_value = {"config": {"rules": rules}}
    secrets = _secrets("staff-1")

    with patch(f"{MODULE}.save_config") as mock_save_config:
        result = _api("POST", "/admin/config", request, secrets).put_config()

        assert mock_save_config.mock_calls == []
        assert request.mock_calls == [READ_STAFF_ID, call.json()]
        assert secrets.mock_calls == [READ_ADMIN_KEYS]
        assert result == [
            JSONResponse(
                {"success": False, "error": "At most 50 pairings can be saved."},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        ]


def test_put_config_refuses_a_score_rule_it_cannot_read() -> None:
    """Storing one and coercing it on read could invert the rule, so it is refused here.

    A comparator this version does not know would normalize to "at least" on the
    way back out: an "at most" rule from a newer version would then fire for
    exactly the patients it was written to skip.
    """
    request = _request("staff-1", content_type="application/json")
    request.json.return_value = {
        "config": {"rules": [{"name": "Depression", "comparator": "sometime_soon"}]}
    }
    secrets = _secrets("staff-1")

    with patch(f"{MODULE}.save_config") as mock_save_config:
        result = _api("POST", "/admin/config", request, secrets).put_config()

        assert mock_save_config.mock_calls == []
        assert request.mock_calls == [READ_STAFF_ID, call.json()]
        assert secrets.mock_calls == [READ_ADMIN_KEYS]
        assert result == [
            JSONResponse(
                {"success": False, "error": "Unrecognized score rule: sometime_soon"},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        ]


@pytest.mark.parametrize("comparator", [*COMPARATORS, None, ""])
def test_put_config_saves_every_score_rule_the_editor_can_send(comparator: str | None) -> None:
    """Each comparator in the dropdown is accepted, and so is a rule from before them."""
    rule: dict[str, object] = {"name": "Depression"}
    if comparator is not None:
        rule["comparator"] = comparator
    request = _request("staff-1", content_type="application/json")
    request.json.return_value = {"config": {"rules": [rule]}}
    secrets = _secrets("staff-1")

    with patch(f"{MODULE}.save_config", return_value=True) as mock_save_config:
        result = _api("POST", "/admin/config", request, secrets).put_config()

        assert mock_save_config.mock_calls == [call({"rules": [rule]})]
        assert result == [JSONResponse({"success": True})]


@pytest.mark.parametrize(
    ("saved", "expected"),
    [
        pytest.param(True, JSONResponse({"success": True}), id="saved"),
        pytest.param(
            False,
            JSONResponse(
                {
                    "success": False,
                    "error": "Could not save - the custom data namespace may not be set up. "
                    "Reinstall the plugin.",
                }
            ),
            id="custom-data-unavailable",
        ),
    ],
)
def test_put_config_saves_the_document(saved: bool, expected: JSONResponse) -> None:
    """A well-formed JSON document is handed to the store, and its outcome is reported."""
    config = {"rules": [{"name": "Depression", "threshold": "4"}]}
    request = _request("staff-1", content_type="application/json")
    request.json.return_value = {"config": config}
    secrets = _secrets("staff-1")

    with patch(f"{MODULE}.save_config") as mock_save_config:
        mock_save_config.return_value = saved

        result = _api("POST", "/admin/config", request, secrets).put_config()

        assert mock_save_config.mock_calls == [call(config)]
        assert request.mock_calls == [READ_STAFF_ID, call.json()]
        assert secrets.mock_calls == [READ_ADMIN_KEYS]
        assert result == [expected]


def test_admin_questionnaires_lists_the_instance_questionnaires() -> None:
    """An admin gets the questionnaire list for the pairing pickers."""
    questionnaires = [{"name": "PHQ-9", "code": "44249-1"}]
    request = _request("staff-1")
    secrets = _secrets("staff-1")

    with patch(f"{MODULE}.list_questionnaires") as mock_list_questionnaires:
        mock_list_questionnaires.return_value = questionnaires

        api = _api("GET", "/admin/questionnaires", request, secrets)
        result = api.admin_questionnaires()

        assert mock_list_questionnaires.mock_calls == [call()]
        assert request.mock_calls == [READ_STAFF_ID]
        assert secrets.mock_calls == [READ_ADMIN_KEYS]
        assert result == [JSONResponse({"questionnaires": questionnaires})]


# --------------------------------------------------------------------------- #
#  Diagnostic
# --------------------------------------------------------------------------- #


def _diagnose_request(staff_id: str, patient: str | None) -> MagicMock:
    request = _request(staff_id)
    request.query_params.get.return_value = patient
    return request


READ_PATIENT_PARAM = call.query_params.get("patient")


def test_diagnose_needs_a_patient() -> None:
    """Without ?patient= there is nothing to explain, and it says so rather than 500ing."""
    request = _diagnose_request("staff-1", None)
    secrets = _secrets("staff-1")

    with patch(f"{MODULE}.owed_forms") as mock_owed_forms:
        result = _api("GET", "/admin/diagnose", request, secrets).diagnose()

        assert mock_owed_forms.mock_calls == []
        assert request.mock_calls == [READ_STAFF_ID, READ_PATIENT_PARAM]
        assert result == [
            JSONResponse(
                {"error": "Pass ?patient=<patient id>"}, status_code=HTTPStatus.BAD_REQUEST
            )
        ]


def test_diagnose_reports_rules_that_can_never_fire() -> None:
    """A switched-off rule never reaches owed_forms, so the endpoint accounts for it.

    Without this, the commonest answer of all - "that pairing is switched off" -
    would show up as the rule simply being absent from the report.
    """
    config = {
        "rules": [
            {
                "id": "r1",
                "name": "Off",
                "enabled": False,
                "comparator": "at_least",
                "threshold": 3,
                "trigger_code": "a",
                "followup_code": "b",
            },
            {
                "id": "r2",
                "name": "Unaddressed",
                "enabled": True,
                "comparator": "at_least",
                "threshold": 3,
                "trigger_code": "",
                "followup_code": "b",
            },
        ]
    }
    request = _diagnose_request("staff-1", "patient-1")
    secrets = _secrets("staff-1")

    with (
        patch(f"{MODULE}.load_config") as mock_load_config,
        patch(f"{MODULE}.owed_forms") as mock_owed_forms,
        patch(f"{MODULE}.editable_note_ids") as mock_editable_note_ids,
    ):
        mock_load_config.return_value = config
        mock_owed_forms.return_value = []
        mock_editable_note_ids.return_value = {}

        result = _api("GET", "/admin/diagnose", request, secrets).diagnose()

        # No rule is active, so owed_forms is called with an empty list.
        assert mock_owed_forms.mock_calls[0].args[0] == []
        assert mock_editable_note_ids.mock_calls == [call(set())]
        payload = json.loads(result[0].content)
        assert payload["patient_id"] == "patient-1"
        assert payload["rules_configured"] == 2
        assert payload["forms_owed"] == []
        assert [(r["rule"], r["outcome"], r["detail"]) for r in payload["rules"]] == [
            ("Off", "inactive", "switched off"),
            ("Unaddressed", "inactive", "no trigger questionnaire chosen"),
        ]


def test_diagnose_returns_the_trace_in_configured_order() -> None:
    """owed_forms traces in gate order; the report reads in the order the admin edits."""
    config = {
        "rules": [
            {
                "id": "r1",
                "name": "First",
                "enabled": True,
                "comparator": "at_least",
                "threshold": 3,
                "trigger_code": "a",
                "followup_code": "b",
            },
            {
                "id": "r2",
                "name": "Second",
                "enabled": True,
                "comparator": "at_least",
                "threshold": 3,
                "trigger_code": "c",
                "followup_code": "d",
            },
        ]
    }
    request = _diagnose_request("staff-1", "patient-1")
    secrets = _secrets("staff-1")

    def _trace(rules: Any, patient_id: Any, now: Any, trace: Any) -> list[Any]:
        # Gate order: the second rule stopped at an earlier gate than the first.
        trace.append({"rule_id": "r2", "rule": "Second", "outcome": "no_screen", "detail": ""})
        trace.append({"rule_id": "r1", "rule": "First", "outcome": "owed", "detail": ""})
        return []

    with (
        patch(f"{MODULE}.load_config") as mock_load_config,
        patch(f"{MODULE}.owed_forms", side_effect=_trace),
        patch(f"{MODULE}.editable_note_ids") as mock_editable_note_ids,
    ):
        mock_load_config.return_value = config
        mock_editable_note_ids.return_value = {}

        result = _api("GET", "/admin/diagnose", request, secrets).diagnose()

        payload = json.loads(result[0].content)
        assert [r["rule"] for r in payload["rules"]] == ["First", "Second"]


def test_diagnose_names_the_note_an_owed_form_would_land_in() -> None:
    """The note is the answer to "where does the follow-up go", so it is reported."""
    rule = {
        "id": "r1",
        "name": "Depression",
        "enabled": True,
        "comparator": "at_least",
        "threshold": 3,
        "trigger_code": "a",
        "followup_code": "44249-1",
    }
    screen = MagicMock(note_id=77)
    followup = MagicMock()
    followup.name = "PHQ-9"
    request = _diagnose_request("staff-1", "patient-1")
    secrets = _secrets("staff-1")

    with (
        patch(f"{MODULE}.load_config") as mock_load_config,
        patch(f"{MODULE}.owed_forms") as mock_owed_forms,
        patch(f"{MODULE}.editable_note_ids") as mock_editable_note_ids,
    ):
        mock_load_config.return_value = {"rules": [rule]}
        mock_owed_forms.return_value = [(rule, screen, followup)]
        mock_editable_note_ids.return_value = {77: "note-uuid"}

        result = _api("GET", "/admin/diagnose", request, secrets).diagnose()

        assert mock_editable_note_ids.mock_calls == [call({77})]
        assert json.loads(result[0].content)["forms_owed"] == [
            {
                "rule": "Depression",
                "questionnaire": "PHQ-9",
                "code": "44249-1",
                "note": "note-uuid",
            }
        ]


def test_diagnose_says_so_when_a_follow_up_would_open_a_new_note() -> None:
    """A locked screening note means Canvas makes one, which is worth seeing up front."""
    rule = {
        "id": "r1",
        "name": "Depression",
        "enabled": True,
        "comparator": "at_least",
        "threshold": 3,
        "trigger_code": "a",
        "followup_code": "44249-1",
    }
    screen = MagicMock(note_id=77)
    followup = MagicMock()
    followup.name = "PHQ-9"
    request = _diagnose_request("staff-1", "patient-1")
    secrets = _secrets("staff-1")

    with (
        patch(f"{MODULE}.load_config") as mock_load_config,
        patch(f"{MODULE}.owed_forms") as mock_owed_forms,
        patch(f"{MODULE}.editable_note_ids") as mock_editable_note_ids,
    ):
        mock_load_config.return_value = {"rules": [rule]}
        mock_owed_forms.return_value = [(rule, screen, followup)]
        mock_editable_note_ids.return_value = {}

        result = _api("GET", "/admin/diagnose", request, secrets).diagnose()

        assert json.loads(result[0].content)["forms_owed"][0]["note"] == "a new note"


def test_the_only_route_returning_patient_data_is_not_cached() -> None:
    """Screening scores and dates must not be left in a browser or proxy cache.

    The diagnostic is the one endpoint here that says anything about a patient.
    """
    rule = {
        "id": "r1",
        "name": "Depression",
        "enabled": True,
        "comparator": "at_least",
        "threshold": 3,
        "trigger_code": "a",
        "followup_code": "b",
    }
    request = _diagnose_request("staff-1", "patient-1")
    secrets = _secrets("staff-1")

    with (
        patch(f"{MODULE}.load_config") as mock_load_config,
        patch(f"{MODULE}.owed_forms") as mock_owed_forms,
        patch(f"{MODULE}.editable_note_ids") as mock_editable_note_ids,
    ):
        mock_load_config.return_value = {"rules": [rule]}
        mock_owed_forms.return_value = []
        mock_editable_note_ids.return_value = {}

        result = _api("GET", "/admin/diagnose", request, secrets).diagnose()

        assert result[0].headers["Cache-Control"] == "no-store"
