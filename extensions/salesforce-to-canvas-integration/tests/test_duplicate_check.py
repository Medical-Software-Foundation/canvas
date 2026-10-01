"""Tests for the GET /records/duplicate-check route on SalesforceStatusAPI.

The route powers the home app Quick Add style duplicate warning inside the
audit modal. Match shape is last name case insensitive plus an exact birth
date, capped at ten rows. These tests drive the route directly against the
SDK Patient ORM, the same idiom used elsewhere in the suite.
"""

from __future__ import annotations

import json
from base64 import b64decode
from datetime import date
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, PropertyMock

import factory

from canvas_sdk.test_utils.factories import PatientFactory

from salesforce_to_canvas_integration.handlers.status_api import SalesforceStatusAPI


def _make_api() -> SalesforceStatusAPI:
    handler = SalesforceStatusAPI.__new__(SalesforceStatusAPI)
    handler.event = MagicMock()
    handler.secrets = {}
    handler.environment = {}
    handler._handler = None
    handler._path_pattern = None
    return handler


def _request(params: dict[str, str]) -> MagicMock:
    request = MagicMock()
    request.query_params = params
    return request


def _drive(api: SalesforceStatusAPI, request: MagicMock) -> list[Any]:
    type(api).request = PropertyMock(return_value=request)
    return api.duplicate_check()


def _status(effect: Any) -> int:
    return int(json.loads(effect.payload)["status_code"])


def _json_body(effect: Any) -> dict[str, Any]:
    payload = json.loads(effect.payload)
    return json.loads(b64decode(payload["body"]).decode())


def test_duplicate_check_returns_case_insensitive_matches() -> None:
    """The route matches last_name case insensitively and birth_date exactly."""
    target_dob = date(1985, 4, 12)
    PatientFactory.create(first_name="Jane", last_name="Doe", birth_date=target_dob)
    PatientFactory.create(first_name="Janet", last_name="doe", birth_date=target_dob)
    PatientFactory.create(first_name="Jim", last_name="Smith", birth_date=target_dob)
    PatientFactory.create(first_name="Other", last_name="Doe", birth_date=date(1990, 1, 1))

    responses = _drive(
        _make_api(),
        _request({"last_name": "DOE", "birth_date": "1985-04-12"}),
    )

    assert _status(responses[0]) == HTTPStatus.OK
    body = _json_body(responses[0])
    matches = body["matches"]
    assert len(matches) == 2
    names = sorted(m["first_name"] for m in matches)
    assert names == ["Jane", "Janet"]
    for entry in matches:
        assert entry["birth_date"] == "1985-04-12"
        assert entry["id"]


def test_duplicate_check_returns_400_when_last_name_is_missing() -> None:
    """An empty last_name is rejected with 400."""
    responses = _drive(
        _make_api(),
        _request({"last_name": "", "birth_date": "1985-04-12"}),
    )

    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST


def test_duplicate_check_returns_400_when_birth_date_is_invalid() -> None:
    """A non YYYY MM DD birth_date is rejected with 400."""
    responses = _drive(
        _make_api(),
        _request({"last_name": "Doe", "birth_date": "yesterday"}),
    )

    assert _status(responses[0]) == HTTPStatus.BAD_REQUEST


def test_duplicate_check_returns_empty_list_when_nothing_matches() -> None:
    """A clean lookup returns 200 with an empty match list."""
    PatientFactory.create(first_name="Anna", last_name="Hopper", birth_date=date(1906, 12, 9))

    responses = _drive(
        _make_api(),
        _request({"last_name": "Lovelace", "birth_date": "1815-12-10"}),
    )

    assert _status(responses[0]) == HTTPStatus.OK
    assert _json_body(responses[0]) == {"matches": []}


def test_duplicate_check_caps_results_at_ten() -> None:
    """A wide collision is capped at ten matches so the payload cannot blow up."""
    dob = date(2000, 1, 1)
    PatientFactory.create_batch(15, last_name="Smith", birth_date=dob)

    responses = _drive(
        _make_api(),
        _request({"last_name": "Smith", "birth_date": "2000-01-01"}),
    )

    assert _status(responses[0]) == HTTPStatus.OK
    matches = _json_body(responses[0])["matches"]
    assert len(matches) == 10
