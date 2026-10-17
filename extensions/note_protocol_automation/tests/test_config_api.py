"""Config API CRUD round-trip + admin-gate authorization. We test the handler
methods directly with a faked request (the SimpleAPI HTTP plumbing is exercised in
live UAT). The faked request supplies a JSON body, path params, and headers via the
handler's `_req` test seam; the admin gate compares the request's
`canvas-logged-in-user-id` header against the `ADMIN_STAFF_IDS` secret string, so
these tests exercise the real gate by varying header id vs. secret contents (no
Staff-table query is involved)."""

import json
from http import HTTPStatus
from typing import Any

import pytest

from note_protocol_automation.handlers.config_api import ConfigAPI
from note_protocol_automation.models.rule import Rule

_ADMIN_ID = "staff-key"


class _Req:
    """Minimal typed stand-in for self.request: json body + path params + headers."""

    def __init__(
        self,
        body: dict[str, Any] | None = None,
        path_params: dict[str, str] | None = None,
        staff_id: str = _ADMIN_ID,
    ) -> None:
        """Hold a JSON body and path params; headers mimic a logged-in staff session."""
        self._body: dict[str, Any] = body or {}
        self.path_params: dict[str, str] = path_params or {}
        self.headers: dict[str, str] = {"canvas-logged-in-user-id": staff_id}

    def json(self) -> dict[str, Any]:
        """Return the request's JSON body."""
        return self._body


def _api(req: _Req, secrets: dict[str, str] | None = None) -> ConfigAPI:
    """Construct a ConfigAPI bound to the faked request via the `_req` test seam.

    `secrets` defaults to an ADMIN_STAFF_IDS allow-list containing the default
    staff id so ordinary CRUD tests authorize; pass an explicit dict (or `{}`) to
    exercise the non-admin / missing-secret deny paths.
    """
    h = ConfigAPI.__new__(ConfigAPI)
    h._req = req
    h.secrets = {"ADMIN_STAFF_IDS": _ADMIN_ID} if secrets is None else secrets
    return h


@pytest.mark.integtest
@pytest.mark.django_db
def test_create_then_list_then_delete() -> None:
    """POST creates a Rule row; GET lists it; DELETE removes it."""
    body: dict[str, Any] = {
        "name": "Annual Physical",
        "note_type_id": "nt-1",
        "enabled": True,
        "match": "all",
        "priority": 0,
        "predicates": [{"signal": "age", "operator": ">=", "value": 18}],
        "commands": ["diagnose", "plan"],
    }
    created = _api(_Req(body=body)).create_rule()
    dbid = json.loads(created[0].content)["dbid"]
    assert Rule.objects.filter(dbid=dbid).exists()

    listed = json.loads(_api(_Req()).list_rules()[0].content)
    assert any(
        r["name"] == "Annual Physical" and r["commands"] == ["diagnose", "plan"] for r in listed
    )

    _api(_Req(path_params={"dbid": str(dbid)})).delete_rule()
    assert not Rule.objects.filter(dbid=dbid).exists()


@pytest.mark.integtest
@pytest.mark.django_db
def test_admin_staff_allowed() -> None:
    """A staff id present in ADMIN_STAFF_IDS may create a rule (no 403)."""
    body: dict[str, Any] = {"name": "Admin rule", "note_type_id": "nt-1"}
    api = _api(_Req(body=body, staff_id=_ADMIN_ID), secrets={"ADMIN_STAFF_IDS": _ADMIN_ID})
    resp = api.create_rule()
    assert resp[0].status_code == HTTPStatus.CREATED
    assert Rule.objects.filter(dbid=json.loads(resp[0].content)["dbid"]).exists()


@pytest.mark.integtest
@pytest.mark.django_db
def test_non_admin_staff_denied() -> None:
    """A logged-in staff NOT in ADMIN_STAFF_IDS is denied (403) on every endpoint
    and writes nothing to the table."""
    secrets = {"ADMIN_STAFF_IDS": "some-other-admin"}
    body: dict[str, Any] = {"name": "Sneaky rule", "note_type_id": "nt-1"}
    create = _api(_Req(body=body, staff_id="not-an-admin"), secrets=secrets).create_rule()
    assert create[0].status_code == HTTPStatus.FORBIDDEN
    assert not Rule.objects.filter(name="Sneaky rule").exists()

    assert (
        _api(_Req(staff_id="not-an-admin"), secrets=secrets).list_rules()[0].status_code
        == HTTPStatus.FORBIDDEN
    )
    assert (
        _api(_Req(path_params={"dbid": "1"}, staff_id="not-an-admin"), secrets=secrets)
        .delete_rule()[0]
        .status_code
        == HTTPStatus.FORBIDDEN
    )


@pytest.mark.integtest
@pytest.mark.django_db
def test_missing_admin_secret_fails_closed() -> None:
    """With ADMIN_STAFF_IDS unset/empty the gate fails closed — even the otherwise
    valid default staff is denied (403)."""
    for secrets in ({}, {"ADMIN_STAFF_IDS": ""}, {"ADMIN_STAFF_IDS": "  ,  "}):
        body: dict[str, Any] = {"name": "Should not save", "note_type_id": "nt-1"}
        resp = _api(_Req(body=body), secrets=secrets).create_rule()
        assert resp[0].status_code == HTTPStatus.FORBIDDEN
    assert not Rule.objects.filter(name="Should not save").exists()
