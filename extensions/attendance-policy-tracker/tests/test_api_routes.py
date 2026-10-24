"""Tests for the review surface and configuration routes in handlers/api.py.

Every route is driven through the platform's own two pass protocol, an
authentication event followed by a request event, built from plain
dictionaries with no database and no network involved in the dispatch itself.
The recipe is the pure Python one the SDK ships in its own test suite, see
canvas_sdk/tests/handlers/simple_api/test_api.py.

The Canvas facing collaborators api.py builds inline, Clock, CanvasVisitSource
and NamespaceSettingsStore, are patched at the names api.py imports them
under, so a route runs the same composition it runs in production while every
question about history and stored policy is answered by a fake this file
controls directly. A real Django row is used only where an effect's own
validation insists one exists, matching the pattern already used for the
tagging effect elsewhere in this suite.
"""

import json
from base64 import b64decode, b64encode
from collections.abc import Mapping
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

import arrow
import pytest
from canvas_sdk.effects import Effect
from canvas_sdk.events import Event, EventRequest, EventType
from canvas_sdk.v1.data.appointment import Appointment as RealAppointment
from canvas_sdk.v1.data.patient import Patient

from attendance_policy_tracker.canvas.states import CANCELLED_STATES, NO_SHOW_STATES
from attendance_policy_tracker.core.clock import FixedClock
from attendance_policy_tracker.core.history import AppointmentHistory, Transition
from attendance_policy_tracker.core.view_preference import SHOW_NON_COUNTING
from attendance_policy_tracker.handlers import api as api_module
from attendance_policy_tracker.handlers.api import ACCESS_VARIABLE, AttendancePolicyAPI

NOW = arrow.get("2026-08-20T12:00:00+00:00")
STAFF_KEY = "a" * 32
OTHER_STAFF_KEY = "b" * 32


# ---------------------------------------------------------------------------
# The platform's own two pass recipe, reproduced locally per the project's
# established pattern of local duplication over cross test file imports.
# ---------------------------------------------------------------------------


def make_event(
    event_type: EventType,
    method: str,
    path: str,
    query_string: str | None = None,
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> Event:
    """A SIMPLE_API_AUTHENTICATE or SIMPLE_API_REQUEST event from plain values."""
    if event_type == EventType.SIMPLE_API_AUTHENTICATE:
        body = b""
    return Event(
        event_request=EventRequest(
            type=event_type,
            target=None,
            context=json.dumps(
                {
                    "method": method,
                    "path": path,
                    "query_string": query_string or "",
                    "body": b64encode(body or b"").decode(),
                    "headers": dict(headers) if headers else {},
                }
            ),
            target_type=None,
        )
    )


def run_route(
    method: str,
    path: str,
    query_string: str | None = None,
    body: dict[str, Any] | None = None,
    staff_key: str | None = STAFF_KEY,
    secrets: dict[str, Any] | None = None,
) -> list[Effect]:
    """Mimic the platform's two pass request handling for one route.

    Authenticate first, and only send the request event on if that succeeds,
    exactly as home-app does. A staff key of None leaves the session headers
    off entirely, for the one test that cares what an unauthenticated caller
    sees.
    """
    headers: dict[str, str] = {}
    if staff_key is not None:
        headers = {
            "canvas-logged-in-user-type": "Staff",
            "canvas-logged-in-user-id": staff_key,
        }
    encoded_body = json.dumps(body).encode() if body is not None else None

    handler = AttendancePolicyAPI(
        make_event(EventType.SIMPLE_API_AUTHENTICATE, method, path, query_string, encoded_body, headers),
        secrets=secrets or {},
    )
    effects: list[Any] = handler.compute()
    payload = json.loads(effects[0].payload)
    if payload["status_code"] != HTTPStatus.OK:
        return effects

    handler = AttendancePolicyAPI(
        make_event(EventType.SIMPLE_API_REQUEST, method, path, query_string, encoded_body, headers),
        secrets=secrets or {},
    )
    served: list[Any] = handler.compute()
    return served


def json_body(effect: Effect) -> Any:
    """The decoded JSON a response effect carries."""
    payload = json.loads(effect.payload)
    return json.loads(b64decode(payload["body"]))


def status_of(effect: Effect) -> int:
    """The HTTP status a response effect carries."""
    return int(json.loads(effect.payload)["status_code"])


# ---------------------------------------------------------------------------
# Fakes for the collaborators _parts() builds inline. Local copies rather than
# imports from another test file's fakes, matching the pattern already
# established across this suite.
# ---------------------------------------------------------------------------


class FakeStore:
    """A settings store backed by a plain dictionary."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values: dict[str, str] = dict(values or {})

    def read(self) -> dict[str, str]:
        return dict(self.values)

    def write(self, values: dict[str, str]) -> None:
        for key, value in values.items():
            if f"{value}".strip():
                self.values[key] = f"{value}".strip()
            else:
                self.values.pop(key, None)


class FakeSource:
    """Hands the engine and the routes whatever a test wants, keyed by patient.

    changed_ids and moved_ids stand in for the two discovery queries the real
    adapter runs. Both default to empty so a test that never mentions
    discovery is unaffected by their presence.
    """

    def __init__(
        self,
        histories: list[AppointmentHistory] | None = None,
        cancellations: list[AppointmentHistory] | None = None,
        changed_ids: list[str] | None = None,
        moved_ids: list[str] | None = None,
    ) -> None:
        self._by_patient: dict[str, list[AppointmentHistory]] = {}
        for entry in histories or []:
            self._by_patient.setdefault(entry.patient_id, []).append(entry)
        self._cancellations = list(cancellations or [])
        self._changed_ids = list(changed_ids or [])
        self._moved_ids = list(moved_ids or [])

    def histories_for(self, patient_id: str) -> list[AppointmentHistory]:
        return list(self._by_patient.get(patient_id, []))

    def recent_cancellations(self, since: Any) -> list[AppointmentHistory]:
        return list(self._cancellations)

    def patients_with_changes_between(self, start: Any, end: Any, states: Any) -> list[str]:
        return list(self._changed_ids)

    def patients_with_changes_since(self, since: Any, states: Any) -> list[str]:
        return list(self._changed_ids)

    def patients_with_moves_between(self, start: Any, end: Any) -> list[str]:
        return list(self._moved_ids)


class FakeAppointmentTable:
    """A stand in for canvas_sdk.v1.data.appointment.Appointment.

    Only the chain _correctable_cancellation actually calls is implemented,
    filter().values_list().first(), which answers the note id for an
    appointment. An identifier naming nothing answers None, which is what
    tells the route to refuse.

    The appointment's own state is deliberately not modelled here any more.
    The route reads it from the note state history instead of from the
    current_state view, so the state lives in FakeNoteStateTable below and
    these two fakes are keyed to meet on the note id.
    """

    def __init__(self, states: dict[str, str] | None = None) -> None:
        self._states = dict(states or {})
        self._matched: str | None = None
        self.objects = self

    def filter(self, **kwargs: Any) -> "FakeAppointmentTable":
        self._matched = kwargs.get("id")
        return self

    def values_list(self, *args: Any, **kwargs: Any) -> "FakeAppointmentTable":
        return self

    def first(self) -> Any:
        """The note id, which for these fakes is the appointment id itself.

        Keeping them the same value is what lets one appointment_states
        mapping drive both fakes without a second mapping to keep in step.
        """
        if self._matched is None or self._matched not in self._states:
            return None
        return self._matched


class FakeNoteStateTable:
    """A stand in for canvas_sdk.v1.data.note.NoteStateChangeEvent.

    Only the chain _correctable_cancellation calls is implemented,
    filter().order_by().values_list().first(), which answers the most recent
    state recorded against a note. Shares the appointment mapping, since the
    fakes treat the note id and the appointment id as the same value.
    """

    def __init__(self, states: dict[str, str] | None = None) -> None:
        self._states = dict(states or {})
        self._matched: Any = None
        self.objects = self

    def filter(self, **kwargs: Any) -> "FakeNoteStateTable":
        self._matched = kwargs.get("note_id")
        return self

    def order_by(self, *args: Any) -> "FakeNoteStateTable":
        return self

    def values_list(self, *args: Any, **kwargs: Any) -> "FakeNoteStateTable":
        return self

    def first(self) -> Any:
        if self._matched is None:
            return None
        return self._states.get(self._matched)


def wire(
    monkeypatch: pytest.MonkeyPatch,
    store_values: dict[str, str] | None = None,
    histories: list[AppointmentHistory] | None = None,
    cancellations: list[AppointmentHistory] | None = None,
    changed_ids: list[str] | None = None,
    moved_ids: list[str] | None = None,
    appointment_states: dict[str, str] | None = None,
) -> SimpleNamespace:
    """Patch Clock, CanvasVisitSource, NamespaceSettingsStore and Appointment.

    These are the four names api.py imports and constructs directly, in
    _parts() and, for the store, again in save_preferences and save_config.
    Patched at the module they are imported into, per the composition root
    warning, no test here reaches into canvas/source.py or core/config.py.
    """
    store = FakeStore(store_values)
    source = FakeSource(
        histories=histories,
        cancellations=cancellations,
        changed_ids=changed_ids,
        moved_ids=moved_ids,
    )
    clock = FixedClock(NOW.datetime)
    appointments = FakeAppointmentTable(appointment_states)
    note_states = FakeNoteStateTable(appointment_states)

    monkeypatch.setattr(api_module, "Clock", lambda: clock)
    monkeypatch.setattr(api_module, "CanvasVisitSource", lambda: source)
    monkeypatch.setattr(api_module, "NamespaceSettingsStore", lambda: store)
    monkeypatch.setattr(api_module, "Appointment", appointments)
    monkeypatch.setattr(api_module, "NoteStateChangeEvent", note_states)

    return SimpleNamespace(
        store=store,
        source=source,
        clock=clock,
        appointments=appointments,
        note_states=note_states,
    )


def _real_appointment() -> RealAppointment:
    """A bare Appointment row, so AddAppointmentLabel can validate against it.

    That effect checks the appointment it names actually exists before it can
    be applied, so a test expecting the add branch to succeed needs a real row
    behind the id it carries, the same seam test_core.py works around for the
    same reason.
    """
    return RealAppointment.objects.create(
        start_time=NOW.datetime,
        duration_minutes=30,
        status="unconfirmed",
        telehealth_instructions_sent=False,
    )


def _noshow_history(appointment_id: str, patient_id: str) -> AppointmentHistory:
    """A history that produces exactly one counted no show incident.

    A no show needs no clock relative gap the way a late cancellation or a
    late move does, so it is the simplest fixture that reliably reaches a
    line.
    """
    start = NOW.shift(days=-3)
    return AppointmentHistory(
        appointment_id=appointment_id,
        patient_id=patient_id,
        provider_id="provider-1",
        start_time=start.datetime,
        transitions=[Transition(state=NO_SHOW_STATES[0], occurred_at=start.shift(hours=1).datetime)],
    )


# ---------------------------------------------------------------------------
# 1. The tag route.
# ---------------------------------------------------------------------------


class TestTagRoute:
    def test_add_tags_a_correctable_cancellation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        appointment = _real_appointment()
        wire(
            monkeypatch,
            appointment_states={str(appointment.id): CANCELLED_STATES[0]},
        )

        effects = run_route(
            "POST", "/app/tag", body={"appointment_id": str(appointment.id), "action": "add"}
        )

        assert status_of(effects[0]) == HTTPStatus.OK
        assert json_body(effects[0])["action"] == "add"
        assert len(effects) == 2
        payload = json.loads(effects[1].payload)["data"]
        assert payload["appointment_id"] == str(appointment.id)
        assert payload["labels"] == ["clinic-cancelled"]

    def test_remove_untags_a_correctable_cancellation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wire(monkeypatch, appointment_states={"appt-1": CANCELLED_STATES[0]})

        effects = run_route(
            "POST", "/app/tag", body={"appointment_id": "appt-1", "action": "remove"}
        )

        assert status_of(effects[0]) == HTTPStatus.OK
        assert json_body(effects[0])["action"] == "remove"
        assert len(effects) == 2
        payload = json.loads(effects[1].payload)["data"]
        assert payload["appointment_id"] == "appt-1"
        assert payload["labels"] == ["clinic-cancelled"]

    def test_an_invalid_action_is_refused_before_anything_is_tagged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A typo must not fall silently into the add branch.

        The appointment is deliberately left correctable, so the only thing
        that can be failing this request is the action check itself.
        """
        wire(monkeypatch, appointment_states={"appt-1": CANCELLED_STATES[0]})

        effects = run_route(
            "POST", "/app/tag", body={"appointment_id": "appt-1", "action": "delete"}
        )

        assert status_of(effects[0]) == HTTPStatus.BAD_REQUEST
        assert len(effects) == 1
        assert "action" in json_body(effects[0])["error"].lower()

    def test_a_missing_appointment_id_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wire(monkeypatch)

        effects = run_route("POST", "/app/tag", body={"action": "add"})

        assert status_of(effects[0]) == HTTPStatus.BAD_REQUEST
        assert len(effects) == 1

    def test_an_absent_appointment_is_refused_rather_than_no_opping(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The identifier names nothing at all, an arbitrary or stale id."""
        wire(monkeypatch, appointment_states={})

        effects = run_route(
            "POST", "/app/tag", body={"appointment_id": "does-not-exist", "action": "add"}
        )

        assert status_of(effects[0]) == HTTPStatus.BAD_REQUEST
        assert len(effects) == 1
        assert "correctable" in json_body(effects[0])["error"].lower()

    def test_a_no_show_is_refused_because_it_is_not_correctable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A no show is unambiguous, matching is_correctable, a label
        cannot move it off the patient, so the tag route must not try."""
        wire(monkeypatch, appointment_states={"appt-1": NO_SHOW_STATES[0]})

        effects = run_route(
            "POST", "/app/tag", body={"appointment_id": "appt-1", "action": "add"}
        )

        assert status_of(effects[0]) == HTTPStatus.BAD_REQUEST
        assert len(effects) == 1


# ---------------------------------------------------------------------------
# 2. The evaluate route.
# ---------------------------------------------------------------------------


class TestEvaluateRoute:
    def test_it_runs_and_reports_a_true_summary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        histories = [_noshow_history("a1", "p1"), _noshow_history("a2", "p2")]
        wire(
            monkeypatch,
            store_values={"warning_line": "1", "warning_team_id": "team-1"},
            histories=histories,
            changed_ids=["p1", "p2"],
        )

        effects = run_route("POST", "/app/evaluate")

        body = json_body(effects[0])
        assert body["swept"] == 2
        assert body["runs_tagged"] == 0
        assert body["effects"] == 2
        assert body["truncated"] is False
        # The summary response plus one task effect per patient.
        assert len(effects) == 3

    def test_the_effect_cap_holds_and_preserves_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        patient_ids = ["p1", "p2", "p3", "p4"]
        histories = [_noshow_history(f"a{i}", pid) for i, pid in enumerate(patient_ids)]
        wire(
            monkeypatch,
            store_values={"warning_line": "1", "warning_team_id": "team-1"},
            histories=histories,
            changed_ids=patient_ids,
        )
        monkeypatch.setattr(api_module, "EFFECT_LIMIT", 2)

        effects = run_route("POST", "/app/evaluate")

        summary = json_body(effects[0])
        assert summary["swept"] == 4
        assert summary["effects"] == 2
        assert summary["truncated"] is True
        # The summary plus exactly the capped number of effects, no more.
        assert len(effects) == 3

        returned_patients = [
            json.loads(effect.payload)["data"]["patient"]["id"] for effect in effects[1:]
        ]
        assert returned_patients == ["p1", "p2"]

    def test_no_activity_still_answers_cleanly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wire(monkeypatch)

        effects = run_route("POST", "/app/evaluate")

        body = json_body(effects[0])
        assert body == {"swept": 0, "runs_tagged": 0, "effects": 0, "truncated": False}
        assert len(effects) == 1


# ---------------------------------------------------------------------------
# 3. Both configuration routes, the authorization wiring itself.
# ---------------------------------------------------------------------------


class TestConfigurationGate:
    def test_get_config_refuses_a_staff_member_absent_from_the_access_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wire(monkeypatch)

        effects = run_route(
            "GET", "/app/config", secrets={ACCESS_VARIABLE: OTHER_STAFF_KEY}
        )

        assert status_of(effects[0]) == HTTPStatus.FORBIDDEN
        assert "access" in json_body(effects[0])["error"].lower()

    def test_get_config_permits_a_listed_staff_member(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wire(monkeypatch)
        # The picker options query Team and TaskLabel directly and are outside
        # this fix's scope, and TaskLabel's modules__contains lookup is not
        # supported on the sqlite backend this suite runs against. Stubbed out
        # so this test stays focused on the authorization gate.
        monkeypatch.setattr(AttendancePolicyAPI, "_teams", lambda self: [])
        monkeypatch.setattr(AttendancePolicyAPI, "_labels", lambda self, module: [])

        effects = run_route("GET", "/app/config", secrets={ACCESS_VARIABLE: STAFF_KEY})

        assert status_of(effects[0]) == HTTPStatus.OK
        body = json_body(effects[0])
        assert "policy" in body
        assert "options" in body

    def test_post_config_refuses_a_staff_member_absent_from_the_access_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wire(monkeypatch)

        effects = run_route(
            "POST",
            "/app/config",
            body={"late_cutoff_hours": "48"},
            secrets={ACCESS_VARIABLE: OTHER_STAFF_KEY},
        )

        assert status_of(effects[0]) == HTTPStatus.FORBIDDEN
        assert "access" in json_body(effects[0])["error"].lower()

    def test_post_config_permits_a_listed_staff_member(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wired = wire(monkeypatch)

        effects = run_route(
            "POST",
            "/app/config",
            body={"late_cutoff_hours": "48"},
            secrets={ACCESS_VARIABLE: STAFF_KEY},
        )

        assert status_of(effects[0]) == HTTPStatus.OK
        assert json_body(effects[0])["ok"] is True
        assert wired.store.values["late_cutoff_hours"] == "48"


# ---------------------------------------------------------------------------
# 4. Name lookup batching.
# ---------------------------------------------------------------------------


class TestNameBatching:
    def test_an_empty_page_of_patients_reads_nothing_at_all(self, db: None) -> None:
        handler = AttendancePolicyAPI(
            make_event(EventType.SIMPLE_API_REQUEST, "GET", "/app/patients")
        )
        assert handler._names_for([]) == {}

    def test_names_for_a_page_costs_exactly_one_query(
        self, db: None, django_assert_num_queries: Any
    ) -> None:
        first = Patient.objects.create(first_name="Ann", last_name="Lee", birth_date="1990-01-01")
        second = Patient.objects.create(first_name="Bo", last_name="Kim", birth_date="1991-01-01")
        handler = AttendancePolicyAPI(
            make_event(EventType.SIMPLE_API_REQUEST, "GET", "/app/patients")
        )

        with django_assert_num_queries(1):
            names = handler._names_for([str(first.id), str(second.id), str(first.id)])

        assert names[str(first.id)] == "Ann Lee"
        assert names[str(second.id)] == "Bo Kim"

    def test_a_patient_with_no_readable_name_is_simply_absent(self, db: None) -> None:
        handler = AttendancePolicyAPI(
            make_event(EventType.SIMPLE_API_REQUEST, "GET", "/app/patients")
        )

        assert handler._names_for(["not-a-real-patient"]) == {}

    def test_name_of_falls_back_to_the_single_patient_lookup(self, db: None) -> None:
        patient = Patient.objects.create(
            first_name="Cy", last_name="Ng", birth_date="1992-01-01"
        )
        handler = AttendancePolicyAPI(
            make_event(EventType.SIMPLE_API_REQUEST, "GET", "/app/patients")
        )

        assert handler._name_of(str(patient.id)) == "Cy Ng"
        assert handler._name_of("missing-patient") == "missing-patient"

    def test_the_activity_route_batches_names_across_its_rows(
        self, monkeypatch: pytest.MonkeyPatch, db: None
    ) -> None:
        patient = Patient.objects.create(
            first_name="Dee", last_name="Osei", birth_date="1993-01-01"
        )
        histories = [_noshow_history("a1", str(patient.id))]
        wire(monkeypatch, histories=histories, changed_ids=[str(patient.id)])

        start = NOW.shift(days=-4)
        end = NOW.shift(days=-2)
        effects = run_route(
            "GET",
            "/app/activity",
            query_string=urlencode({"from": start.isoformat(), "to": end.isoformat()}),
        )

        rows = json_body(effects[0])["activity"]
        assert len(rows) == 1
        assert rows[0]["name"] == "Dee Osei"


# ---------------------------------------------------------------------------
# 5. The patients route cap.
# ---------------------------------------------------------------------------


class TestPatientsRouteCap:
    def test_unbounded_activity_is_capped_after_sorting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Three patients, three different counts, so the ordering the cap
        # keeps is unambiguous. Three separate no show histories against the
        # same patient each count once, since a no show is unambiguous and
        # always counts against the patient.
        histories = (
            [_noshow_history("a1", "p1")]
            + [_noshow_history(f"b{i}", "p2") for i in range(2)]
            + [_noshow_history(f"c{i}", "p3") for i in range(3)]
        )
        wire(monkeypatch, histories=histories, changed_ids=["p1", "p2", "p3"])
        monkeypatch.setattr(api_module, "PATIENTS_LIMIT", 2)

        effects = run_route("GET", "/app/patients")

        body = json_body(effects[0])
        assert body["truncated"] is True
        assert [row["patient_id"] for row in body["patients"]] == ["p3", "p2"]
        assert [row["count"] for row in body["patients"]] == [3, 2]

    def test_activity_within_the_limit_is_not_marked_truncated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        histories = [_noshow_history("a1", "p1")]
        wire(monkeypatch, histories=histories, changed_ids=["p1"])

        effects = run_route("GET", "/app/patients")

        body = json_body(effects[0])
        assert body["truncated"] is False
        assert len(body["patients"]) == 1


# ---------------------------------------------------------------------------
# 6. The plain read routes, the surface itself, its assets, and the resolved
#    policy every page loads on open and again on every live refresh.
# ---------------------------------------------------------------------------


def _fake_render_to_string(template: str, context: dict[str, Any] | None = None) -> str:
    """Stands in for canvas_sdk.templates.render_to_string.

    The real one needs a plugin context this test suite does not run inside,
    the same reason every other route test drives dispatch through the
    platform's own plain dictionary recipe rather than a live template
    engine. Echoing the template name and its context back as text is enough
    for a route test to see what it was handed.
    """
    return f"{template}:{context or {}}"


class TestSurfaceAndAssetRoutes:
    def test_index_renders_and_reports_configuration_access(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wire(monkeypatch)
        monkeypatch.setattr(api_module, "render_to_string", _fake_render_to_string)

        effects = run_route("GET", "/app/index", secrets={ACCESS_VARIABLE: STAFF_KEY})

        assert status_of(effects[0]) == HTTPStatus.OK
        body = b64decode(json.loads(effects[0].payload)["body"]).decode()
        assert STAFF_KEY in body
        assert "'can_configure': True" in body

    def test_index_is_reachable_by_a_staff_member_with_no_configuration_access(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Gated for nobody, since a person needs to read their own key to
        # hand it to an administrator before they have been granted access.
        wire(monkeypatch)
        monkeypatch.setattr(api_module, "render_to_string", _fake_render_to_string)

        effects = run_route("GET", "/app/index", secrets={ACCESS_VARIABLE: OTHER_STAFF_KEY})

        assert status_of(effects[0]) == HTTPStatus.OK
        body = b64decode(json.loads(effects[0].payload)["body"]).decode()
        assert "'can_configure': False" in body

    def test_the_css_asset_route_serves_the_stylesheet(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wire(monkeypatch)
        monkeypatch.setattr(api_module, "render_to_string", _fake_render_to_string)

        effects = run_route("GET", "/app/canvas-plugin-ui.css")

        assert status_of(effects[0]) == HTTPStatus.OK

    def test_the_js_asset_route_serves_the_components(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wire(monkeypatch)
        monkeypatch.setattr(api_module, "render_to_string", _fake_render_to_string)

        effects = run_route("GET", "/app/canvas-plugin-ui.js")

        assert status_of(effects[0]) == HTTPStatus.OK

    def test_the_policy_route_reports_thresholds_and_the_shared_preference(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wire(monkeypatch, store_values={"warning_line": "2"})

        effects = run_route("GET", "/app/policy")

        assert status_of(effects[0]) == HTTPStatus.OK
        body = json_body(effects[0])
        assert body["policy"]["warning_line"] == 2
        assert body["show_non_counting"] is False


# ---------------------------------------------------------------------------
# 7. The shared view preference route.
# ---------------------------------------------------------------------------


class TestSavePreferencesRoute:
    def test_turning_the_shared_filter_on_is_stored_and_echoed_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wired = wire(monkeypatch)

        effects = run_route(
            "POST", "/app/preferences", body={"show_non_counting": True}
        )

        assert status_of(effects[0]) == HTTPStatus.OK
        assert json_body(effects[0]) == {"ok": True, "show_non_counting": True}
        assert wired.store.values[SHOW_NON_COUNTING] == "true"

    def test_a_body_with_nothing_to_save_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wire(monkeypatch)

        effects = run_route("POST", "/app/preferences", body={})

        assert status_of(effects[0]) == HTTPStatus.BAD_REQUEST
        assert "nothing" in json_body(effects[0])["error"].lower()

    def test_not_being_permitted_to_configure_policy_does_not_block_this_route(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Deliberately not gated behind configuration access, unlike every
        # other stored setting.
        wire(monkeypatch)

        effects = run_route(
            "POST",
            "/app/preferences",
            body={"show_non_counting": False},
            secrets={ACCESS_VARIABLE: OTHER_STAFF_KEY},
        )

        assert status_of(effects[0]) == HTTPStatus.OK


# ---------------------------------------------------------------------------
# 8. save_config's own validation, beyond the authorization gate covered by
#    TestConfigurationGate above.
# ---------------------------------------------------------------------------


class TestSaveConfigValidation:
    def test_an_empty_submission_is_refused_before_anything_is_written(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wired = wire(monkeypatch)

        effects = run_route(
            "POST", "/app/config", body={}, secrets={ACCESS_VARIABLE: STAFF_KEY}
        )

        assert status_of(effects[0]) == HTTPStatus.BAD_REQUEST
        assert "nothing" in json_body(effects[0])["error"].lower()
        assert wired.store.values == {}

    def test_a_submission_that_contradicts_what_is_already_stored_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # warning_line arrives fine on its own, but the review line already
        # sitting in storage is now below it, so the merged policy is
        # incoherent and must be refused rather than half written.
        wired = wire(monkeypatch, store_values={"discharge_review_line": "4"})

        effects = run_route(
            "POST",
            "/app/config",
            body={"warning_line": "6"},
            secrets={ACCESS_VARIABLE: STAFF_KEY},
        )

        assert status_of(effects[0]) == HTTPStatus.BAD_REQUEST
        assert "warning_line" not in wired.store.values


# ---------------------------------------------------------------------------
# 9. The activity route's own input validation, ahead of the batching
#    already covered in TestNameBatching.
# ---------------------------------------------------------------------------


class TestActivityRouteValidation:
    def test_a_missing_from_or_to_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wire(monkeypatch)

        effects = run_route(
            "GET", "/app/activity", query_string=urlencode({"from": NOW.isoformat()})
        )

        assert status_of(effects[0]) == HTTPStatus.BAD_REQUEST

    def test_an_unparseable_instant_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wire(monkeypatch)

        effects = run_route(
            "GET",
            "/app/activity",
            query_string=urlencode({"from": "not-a-moment", "to": NOW.isoformat()}),
        )

        assert status_of(effects[0]) == HTTPStatus.BAD_REQUEST
        assert "timestamps" in json_body(effects[0])["error"].lower()

    def test_a_to_instant_at_or_before_from_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wire(monkeypatch)

        effects = run_route(
            "GET",
            "/app/activity",
            query_string=urlencode({"from": NOW.isoformat(), "to": NOW.isoformat()}),
        )

        assert status_of(effects[0]) == HTTPStatus.BAD_REQUEST
        assert "after" in json_body(effects[0])["error"].lower()


# ---------------------------------------------------------------------------
# 10. The single patient incidents route.
# ---------------------------------------------------------------------------


class TestIncidentsRoute:
    def test_a_missing_patient_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        wire(monkeypatch)

        effects = run_route("GET", "/app/incidents")

        assert status_of(effects[0]) == HTTPStatus.BAD_REQUEST

    def test_a_known_patient_reports_their_recomputed_total(
        self, monkeypatch: pytest.MonkeyPatch, db: None
    ) -> None:
        patient = Patient.objects.create(
            first_name="Eve", last_name="Ito", birth_date="1994-01-01"
        )
        histories = [_noshow_history("a1", str(patient.id))]
        wire(monkeypatch, histories=histories)

        effects = run_route(
            "GET", "/app/incidents", query_string=urlencode({"patient": str(patient.id)})
        )

        assert status_of(effects[0]) == HTTPStatus.OK
        body = json_body(effects[0])
        assert body["count"] == 1
        assert body["name"] == "Eve Ito"
        assert body["clinic_tag"] == "clinic-cancelled"


# ---------------------------------------------------------------------------
# 11. The picker options, driven against real rows rather than stubbed out,
#     unlike TestConfigurationGate above, which only proves the gate itself.
# ---------------------------------------------------------------------------


class TestTeamsPickerReadsRealRows:
    def test_teams_come_back_as_plain_id_and_name_pairs(self, db: None) -> None:
        from canvas_sdk.v1.data.team import Team

        team = Team.objects.create(name="Front desk", responsibilities=[])

        handler = AttendancePolicyAPI(
            make_event(EventType.SIMPLE_API_REQUEST, "GET", "/app/config")
        )

        assert handler._teams() == [{"id": str(team.id), "name": "Front desk"}]


# ---------------------------------------------------------------------------
# 12. The request body reader, ahead of any route that calls it.
# ---------------------------------------------------------------------------


class TestBodyParsing:
    def _handler(self) -> AttendancePolicyAPI:
        return AttendancePolicyAPI(
            make_event(EventType.SIMPLE_API_REQUEST, "POST", "/app/preferences")
        )

    def test_an_absent_body_reads_as_an_empty_mapping(self) -> None:
        handler = self._handler()
        handler.request = SimpleNamespace(body=None)
        assert handler._body() == {}

    def test_unparseable_json_reads_as_an_empty_mapping(self) -> None:
        handler = self._handler()
        handler.request = SimpleNamespace(body=b"{not json")
        assert handler._body() == {}

    def test_a_json_array_body_is_not_treated_as_a_mapping(self) -> None:
        # A well formed JSON document that is nonetheless not the shape
        # every route assumes, so it is refused the same as unparseable text.
        handler = self._handler()
        handler.request = SimpleNamespace(body=b"[1, 2, 3]")
        assert handler._body() == {}

    def test_a_plain_string_body_is_parsed_without_decoding_first(self) -> None:
        handler = self._handler()
        handler.request = SimpleNamespace(body='{"show_non_counting": true}')
        assert handler._body() == {"show_non_counting": True}
