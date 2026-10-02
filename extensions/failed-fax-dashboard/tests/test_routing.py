import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from canvas_generated.messages.effects_pb2 import EffectType
from canvas_sdk.test_utils.factories import StaffRoleFactory, TaskFactory
from canvas_sdk.v1.data import CareTeamMembership, CareTeamRole, StaffRole

from failed_fax_dashboard.models import AlertStart
from failed_fax_dashboard.services.alerts import alert_effects
from failed_fax_dashboard.services.dashboard import dashboard_page
from failed_fax_dashboard.services.routing import provider_ids, routing_from
from tests.helpers import make_event, make_staff

pytestmark = pytest.mark.django_db

ENVIRONMENT = {"CUSTOMER_IDENTIFIER": "acme", "INSTALLATION_TIME_ZONE": "America/New_York"}
NOW = datetime.now(timezone.utc)
SETTINGS = {"PROVIDER_ROLES": "MD, NP, RN, DO, PA", "PROVIDER_FAX_TASK_ROLE": "Care Navigator - Primary"}


def run(secrets: dict[str, str]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (EffectType.Name(effect.type), json.loads(effect.payload)["data"])
        for effect in alert_effects(secrets, ENVIRONMENT, NOW)
    ]


def started() -> None:
    AlertStart.objects.all().delete()
    AlertStart.objects.create(started_at=NOW - timedelta(hours=1))


def with_role(first: str, last: str, code: str, name: str, abbreviation: str | None = None) -> Any:
    """A staff member holding only this role (the staff factory adds a Physician role by default)."""
    staff = make_staff(first, last)
    StaffRole.objects.filter(staff=staff).delete()
    StaffRoleFactory.create(
        staff=staff, internal_code=code, public_abbreviation=code if abbreviation is None else abbreviation, name=name
    )
    return staff


def provider(first: str = "Pat", last: str = "Provider", code: str = "MD") -> Any:
    return with_role(first, last, code, "Physician")


def on_care_team(patient: Any, staff: Any, role_name: str = "Care Navigator - Primary", status: str = "active") -> None:
    role, _ = CareTeamRole.objects.get_or_create(
        display=role_name, defaults={"code": "x", "system": "http://snomed.info/sct", "active": True}
    )
    CareTeamMembership.objects.create(
        patient=patient,
        staff=staff,
        role=role,
        status=status,
        lead=False,
        role_code="",
        role_system="",
        role_display="",
    )


def test_a_providers_failed_fax_goes_to_the_patients_care_navigator() -> None:
    sender = provider("Pat", "Provider")
    navigator = make_staff("Nora", "Navigator")
    event = make_event("lab_order", originator=sender.user)
    on_care_team(event.lab_order.patient, navigator)
    started()

    effects = run(SETTINGS)

    task, comment = effects[0][1], effects[1][1]
    assert task["assignee"] == {"id": navigator.id}
    assert "Sent by Pat Provider. Assigned to Nora Navigator, the patient's Care Navigator - Primary." in comment["body"]


def test_no_care_navigator_sends_it_back_to_the_provider() -> None:
    sender = provider()
    make_event("note", originator=sender.user)
    started()

    assert run(SETTINGS)[0][1]["assignee"] == {"id": sender.id}


def test_inactive_membership_or_another_role_does_not_count() -> None:
    sender = provider()
    event = make_event("note", originator=sender.user)
    on_care_team(event.note.patient, make_staff("Old", "Navigator"), status="inactive")
    on_care_team(event.note.patient, make_staff("Care", "Manager"), role_name="Care Manager - Primary")
    started()

    assert run(SETTINGS)[0][1]["assignee"] == {"id": sender.id}


def test_someone_who_is_not_a_provider_keeps_their_own_task() -> None:
    sender = with_role("Cara", "Coordinator", "CC", "Care Coordinator")
    event = make_event("note", originator=sender.user)
    on_care_team(event.note.patient, make_staff("Nora", "Navigator"))
    started()

    assert run(SETTINGS)[0][1]["assignee"] == {"id": sender.id}


@pytest.mark.parametrize(
    "settings",
    [
        {"PROVIDER_ROLES": "MD", "PROVIDER_FAX_TASK_ROLE": ""},
        {"PROVIDER_ROLES": "", "PROVIDER_FAX_TASK_ROLE": "Care Navigator - Primary"},
        {},
    ],
)
def test_either_setting_empty_turns_rerouting_off(settings: dict[str, str]) -> None:
    sender = provider()
    event = make_event("note", originator=sender.user)
    on_care_team(event.note.patient, make_staff("Nora", "Navigator"))
    started()

    assert run(settings)[0][1]["assignee"] == {"id": sender.id}


def test_a_role_name_that_matches_nothing_is_logged_and_tasks_go_to_the_sender(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sender = provider()
    event = make_event("note", originator=sender.user)
    on_care_team(event.note.patient, make_staff("Nora", "Navigator"))
    started()

    effects = run({**SETTINGS, "PROVIDER_FAX_TASK_ROLE": "Care Navigtor"})

    assert effects[0][1]["assignee"] == {"id": sender.id}
    assert "matches no care team role" in caplog.text


def test_role_names_ignore_capitals_and_match_code_abbreviation_or_name() -> None:
    by_code = provider("A", "Code", code="RN")
    by_name = with_role("B", "Name", "ZZ", "Physician Assistant", abbreviation="")
    other = with_role("C", "Other", "MA", "Medical Assistant")
    routing = routing_from({"PROVIDER_ROLES": " rn , physician assistant", "PROVIDER_FAX_TASK_ROLE": "care navigator - primary"})

    assert provider_ids(routing, {by_code.id, by_name.id, other.id}) == {by_code.id, by_name.id}


def test_a_later_provider_failure_moves_the_task_to_the_care_navigator() -> None:
    coordinator = with_role("Cara", "Coordinator", "CC", "Care Coordinator")
    sender = provider("Pat", "Provider")
    navigator = make_staff("Nora", "Navigator")
    first = make_event("note", originator=coordinator.user, age_days=1)
    on_care_team(first.note.patient, navigator)
    started()
    task_id = run(SETTINGS)[0][1]["id"]
    TaskFactory.create(id=task_id, assignee=coordinator, team=None, patient=first.note.patient)
    make_event("note", note=first.note, originator=sender.user)

    update, comment = (data for _, data in run(SETTINGS))

    assert update["assignee"] == {"id": navigator.id}
    assert "Moved from Cara Coordinator to Nora Navigator." in comment["body"]
    assert "Sent by Pat Provider. Assigned to Nora Navigator" in comment["body"]


def test_a_waiting_provider_row_sits_under_the_care_navigator() -> None:
    sender = provider()
    navigator = make_staff("Nora", "Navigator")
    event = make_event("note", originator=sender.user)
    on_care_team(event.note.patient, navigator)
    started()

    for_navigator = dashboard_page("sent", {}, navigator.id, secrets=SETTINGS)
    for_sender = dashboard_page("sent", {}, sender.id, secrets=SETTINGS)

    assert [row["mine"] for row in for_navigator["rows"]] == [True]
    assert [row["mine"] for row in for_sender["rows"]] == [False]
