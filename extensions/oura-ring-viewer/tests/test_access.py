"""Tests for per-patient access, against real Staff, Patient and care-team rows.

The SDK's staff session only proves the caller is staff. These tests prove the
plugin's own rule decides which patients that staff member can see, and that a
refused request changes nothing.
"""

import datetime as dt
import json
from http import HTTPStatus
from typing import Any

import pytest
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse
from canvas_sdk.test_utils.factories import PatientFactory, StaffFactory
from canvas_sdk.v1.data.care_team import CareTeamMembership, CareTeamMembershipStatus

from oura_ring_viewer.models import OuraOAuthToken
from oura_ring_viewer.protocols.chart_api import OuraChartAPI
from oura_ring_viewer.services.access import (
    DEFAULT_RULE,
    RULE_CARE_TEAM,
    RULE_PRACTICE,
    logged_in_staff_id,
    resolve_rule,
    staff_can_view,
)
from oura_ring_viewer.services.storage import get_sync_state, upsert_tokens

SECRETS = {
    "OURA_CLIENT_ID": "cid",
    "OURA_CLIENT_SECRET": "sec",
    "OURA_REDIRECT_URI": "https://acme.canvasmedical.com/plugin-io/api/oura_ring_viewer/callback",
    "OURA_ENVIRONMENT": "sandbox",
    "OURA_MAGIC_LINK_SECRET": "m" * 40,
}


def _ids(*, active: bool = True) -> tuple[str, str]:
    """A fresh (staff_id, patient_id) pair backed by real rows."""
    return str(StaffFactory.create(active=active).id), str(PatientFactory.create().id)


def _join_care_team(staff_id: str, patient_id: str, status: str = CareTeamMembershipStatus.ACTIVE) -> None:
    from canvas_sdk.v1.data import Patient, Staff

    CareTeamMembership.objects.create(
        patient=Patient.objects.get(id=patient_id),
        staff=Staff.objects.get(id=staff_id),
        status=status,
        lead=False,
    )


class TestRuleSetting:
    def test_unset_means_the_strict_default(self) -> None:
        assert DEFAULT_RULE == RULE_CARE_TEAM
        assert resolve_rule(None) == RULE_CARE_TEAM
        assert resolve_rule({"OURA_ACCESS_RULE": "  "}) == RULE_CARE_TEAM

    @pytest.mark.parametrize("raw, rule", [("practice", RULE_PRACTICE), (" CARE_TEAM ", RULE_CARE_TEAM)])
    def test_recognized_values(self, raw: str, rule: str) -> None:
        assert resolve_rule({"OURA_ACCESS_RULE": raw}) == rule

    @pytest.mark.parametrize("raw", ["everyone", "all", "care team", "none"])
    def test_unrecognized_values_are_never_widened(self, raw: str) -> None:
        assert resolve_rule({"OURA_ACCESS_RULE": raw}) is None


class TestCallerIdentity:
    def test_staff_session(self) -> None:
        headers = {"canvas-logged-in-user-type": "Staff", "canvas-logged-in-user-id": " s-1 "}
        assert logged_in_staff_id(headers) == "s-1"

    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"canvas-logged-in-user-id": "s-1"},
            {"canvas-logged-in-user-type": "Patient", "canvas-logged-in-user-id": "p-1"},
            {"canvas-logged-in-user-type": "Staff", "canvas-logged-in-user-id": "  "},
        ],
    )
    def test_anything_else_is_not_staff(self, headers: dict[str, str]) -> None:
        assert logged_in_staff_id(headers) is None


class TestCareTeamRule:
    def test_active_member(self) -> None:
        staff_id, patient_id = _ids()
        _join_care_team(staff_id, patient_id)
        assert staff_can_view(staff_id, patient_id, RULE_CARE_TEAM) is True

    def test_not_a_member(self) -> None:
        staff_id, patient_id = _ids()
        assert staff_can_view(staff_id, patient_id, RULE_CARE_TEAM) is False

    def test_member_of_a_different_patients_team(self) -> None:
        staff_id, patient_id = _ids()
        _, other_patient = _ids()
        _join_care_team(staff_id, other_patient)
        assert staff_can_view(staff_id, patient_id, RULE_CARE_TEAM) is False

    @pytest.mark.parametrize(
        "status",
        [
            CareTeamMembershipStatus.PROPOSED,
            CareTeamMembershipStatus.SUSPENDED,
            CareTeamMembershipStatus.INACTIVE,
            CareTeamMembershipStatus.ENTERED_IN_ERROR,
        ],
    )
    def test_only_an_active_membership_counts(self, status: str) -> None:
        staff_id, patient_id = _ids()
        _join_care_team(staff_id, patient_id, status)
        assert staff_can_view(staff_id, patient_id, RULE_CARE_TEAM) is False

    def test_inactive_staff_lose_access_even_on_the_team(self) -> None:
        staff_id, patient_id = _ids(active=False)
        _join_care_team(staff_id, patient_id)
        assert staff_can_view(staff_id, patient_id, RULE_CARE_TEAM) is False


class TestPracticeRule:
    def test_any_active_staff_member(self) -> None:
        staff_id, patient_id = _ids()
        assert staff_can_view(staff_id, patient_id, RULE_PRACTICE) is True

    def test_inactive_staff(self) -> None:
        staff_id, patient_id = _ids(active=False)
        assert staff_can_view(staff_id, patient_id, RULE_PRACTICE) is False

    def test_unknown_patient_cannot_be_probed(self) -> None:
        staff_id, _ = _ids()
        assert staff_can_view(staff_id, "no-such-patient", RULE_PRACTICE) is False

    def test_unknown_staff(self) -> None:
        _, patient_id = _ids()
        assert staff_can_view("no-such-staff", patient_id, RULE_PRACTICE) is False


def test_an_unknown_rule_grants_nothing() -> None:
    staff_id, patient_id = _ids()
    _join_care_team(staff_id, patient_id)
    assert staff_can_view(staff_id, patient_id, "everyone") is False


# ---- the gate, through the real routes ------------------------------------------


class _Request:
    def __init__(self, query: dict[str, str], headers: dict[str, str]) -> None:
        self.query_params = query
        self.headers = headers


class _Event:
    def __init__(self, method: str, path: str) -> None:
        self.context = {"method": method, "path": path}


def _call(
    name: str,
    staff_id: str | None,
    patient_id: str,
    *,
    secrets: dict[str, str] | None = None,
    user_type: str = "Staff",
    query: dict[str, str] | None = None,
) -> list[Any]:
    method = "GET" if name in ("chart_shell", "chart_data") else "POST"
    handler = OuraChartAPI(event=_Event(method, "/"))
    headers = {} if staff_id is None else {
        "canvas-logged-in-user-type": user_type, "canvas-logged-in-user-id": staff_id,
    }
    handler.request = _Request({"patient_id": patient_id, **(query or {})}, headers)
    handler.secrets = SECRETS if secrets is None else secrets
    return list(getattr(handler, name)())


def _body(effect: Any) -> Any:
    assert isinstance(effect, JSONResponse)
    return json.loads(effect.content)


class TestGate:
    def test_care_team_member_gets_data(self) -> None:
        staff_id, patient_id = _ids()
        _join_care_team(staff_id, patient_id)
        effect = _call("chart_data", staff_id, patient_id)[0]
        assert effect.status_code == HTTPStatus.OK
        assert _body(effect)["connection_status"] == "disconnected"

    def test_non_member_gets_a_generic_refusal(self) -> None:
        staff_id, patient_id = _ids()
        effect = _call("chart_data", staff_id, patient_id)[0]
        assert effect.status_code == HTTPStatus.FORBIDDEN
        assert _body(effect) == {"error": "forbidden"}

    def test_the_chart_drawer_gets_a_readable_refusal(self) -> None:
        staff_id, patient_id = _ids()
        effect = _call("chart_shell", staff_id, patient_id)[0]
        assert isinstance(effect, HTMLResponse)
        assert effect.status_code == HTTPStatus.FORBIDDEN
        page = effect.content.decode()
        assert "You do not have access to this patient" in page
        assert "care team" not in page and "OURA_ACCESS_RULE" not in page
        assert "data-patient-id" not in page, "a refused request must not receive the chart"

    def test_practice_rule_admits_any_active_staff(self) -> None:
        staff_id, patient_id = _ids()
        effect = _call("chart_data", staff_id, patient_id,
                       secrets={**SECRETS, "OURA_ACCESS_RULE": "practice"})[0]
        assert effect.status_code == HTTPStatus.OK

    @pytest.mark.parametrize("name", ["chart_data", "chart_shell"])
    def test_an_invalid_rule_refuses_service(self, name: str) -> None:
        staff_id, patient_id = _ids()
        _join_care_team(staff_id, patient_id)
        effect = _call(name, staff_id, patient_id,
                       secrets={**SECRETS, "OURA_ACCESS_RULE": "everyone"})[0]
        assert effect.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        text = effect.content.decode()
        assert "OURA_ACCESS_RULE (must be one of: care_team, practice)" in text

    @pytest.mark.parametrize("staff_id, user_type", [(None, "Staff"), ("p-1", "Patient")])
    def test_non_staff_callers(self, staff_id: str | None, user_type: str) -> None:
        _, patient_id = _ids()
        effect = _call("chart_data", staff_id, patient_id, user_type=user_type)[0]
        assert effect.status_code == HTTPStatus.FORBIDDEN
        assert _body(effect) == {"error": "not_staff"}

    def test_a_refused_link_request_issues_nothing(self) -> None:
        staff_id, patient_id = _ids()
        effects = _call("send_link", staff_id, patient_id, query={"channels": ""})
        assert len(effects) == 1 and effects[0].status_code == HTTPStatus.FORBIDDEN
        assert get_sync_state(patient_id) is None

    def test_a_refused_disconnect_deletes_nothing(self) -> None:
        staff_id, patient_id = _ids()
        now = dt.datetime.now(dt.UTC)
        upsert_tokens(patient_id, access_token_ciphertext="AT", refresh_token_ciphertext="RT",
                      expires_at=now, scopes="daily", now=now, is_initial_connection=True)
        effect = _call("disconnect", staff_id, patient_id)[0]
        assert effect.status_code == HTTPStatus.FORBIDDEN
        assert OuraOAuthToken.objects.filter(patient__id=patient_id).exists()
