"""Tests for the patient screening-record endpoint, read and write.

The access question here differs from the editor's and the difference is
deliberate: the editor changes what the whole practice is measured against and
is gated to an allowlist, while this is a chart view every clinician looking
after the patient needs. So it requires a staff session and nothing more - the
same bar Canvas applies to the chart this data already appears on.

What must hold on the read: it is never public, it never invents a patient, and
it renders live rather than from stored state.

What must hold on the write, which is newer and carries more: it refuses a
forged cross-site post, it refuses anything it cannot attribute to a real
patient and a tracked screening, it never records a completion in the future,
and **it never silently does nothing** - a click that did not land has to say
so, because a write that looks like it worked is this plugin's recurring
failure mode.
"""

import json
from datetime import UTC, date, datetime, timedelta
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from canvas_generated.messages.events_pb2 import Event as EventRequest
from canvas_generated.messages.events_pb2 import EventType
from canvas_sdk.effects import EffectType
from canvas_sdk.events import Event
from canvas_sdk.handlers.simple_api.security import StaffSessionAuthMixin
from canvas_sdk.test_utils.factories import NoteFactory, PatientFactory
from canvas_sdk.v1.data import Patient
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteStates
from pytest_django import DjangoAssertNumQueries

from preventive_screenings.api.record_routes import ScreeningRecordAPI
from preventive_screenings.models import ScreeningAttestation

MODULE = "preventive_screenings.api.record_routes"
BORN = date(1970, 5, 2)
STAFF = "staff-key-1"
NOBODY = "00000000-0000-0000-0000-000000000000"


def today() -> date:
    """The route's idea of today, which is UTC.

    Not `date.today()`. That is local, and a test comparing a local date
    against a UTC one passes for most of the day and then stops - which is
    exactly what happened here on 2026-10-11.
    """
    return datetime.now(UTC).date()


def mammogram(**over: Any) -> dict:
    out: dict[str, Any] = {
        "id": "s1",
        "enabled": True,
        "protocol_card": False,
        "name": "Mammogram",
        "sex": "any",
        "min_age": 40,
        "max_age": 0,
        "grace_days": 90,
        "completions": [
            {"value_set_key": "mammography", "source": "imaging_report", "codes": [],
             "label": "", "interval_quantity": 2, "interval_unit": "years"}
        ],
        "exclusions": [],
        "order_command": "",
        "order_button": "",
        "order_code": "",
        "order_comment": "",
        "guidance": "",
    }
    out.update(over)
    return out


def colorectal(**over: Any) -> dict:
    """Two ways to satisfy it, with very different intervals.

    The pair is the point: "it was done" does not say when the next one is due
    unless the provider also says *what* was done.
    """
    return mammogram(
        id="s2",
        name="Colorectal",
        completions=[
            {"value_set_key": "colonoscopy", "source": "procedure", "codes": [],
             "label": "", "interval_quantity": 10, "interval_unit": "years"},
            {"value_set_key": "fobt", "source": "lab_result", "codes": [],
             "label": "", "interval_quantity": 1, "interval_unit": "years"},
        ],
        **over,
    )


def _api(method: str, path: str) -> ScreeningRecordAPI:
    event = Event(
        EventRequest(
            type=EventType.SIMPLE_API_REQUEST,
            context=json.dumps({"method": method, "path": path}),
        )
    )
    return ScreeningRecordAPI(event=event)


def _serve(patient_param: str, screenings: list[dict]) -> Any:
    request = MagicMock()
    request.query_params = {"patient": patient_param}

    instance = _api("GET", "/record/ui")
    instance.request = request
    with patch(f"{MODULE}.load_config", lambda: {"screenings": screenings}):
        return instance.serve_record()


def _post(
    body: Any,
    screenings: list[dict],
    *,
    content_type: str = "application/json",
    staff: str = STAFF,
) -> Any:
    request = MagicMock()
    request.content_type = content_type
    request.json.return_value = body
    request.headers = {"canvas-logged-in-user-id": staff}

    instance = _api("POST", "/record/attest")
    instance.request = request
    with patch(f"{MODULE}.load_config", lambda: {"screenings": screenings}):
        return instance.attest()


def _json(response: Any) -> dict:
    parsed: dict = json.loads(response.content)
    return parsed


@pytest.fixture
def woman_of_50() -> Patient:
    return PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)


def test_the_endpoint_requires_a_staff_session() -> None:
    """**Not public.** The patient id is a query parameter, so the session check
    is what stands between this and anyone who can guess one."""
    assert issubclass(ScreeningRecordAPI, StaffSessionAuthMixin)


# --- reading -----------------------------------------------------------------


@pytest.mark.django_db
def test_the_record_renders_the_patients_screenings(woman_of_50: Patient) -> None:
    responses = _serve(str(woman_of_50.id), [mammogram()])

    assert len(responses) == 1
    assert "Mammogram" in str(responses[0].content)


@pytest.mark.django_db
def test_the_record_shows_a_screening_that_is_not_carded(woman_of_50: Patient) -> None:
    """The card toggle decides what goes on the chart summary, not what the
    practice tracks. Hiding an uncarded screening here would make turning a
    card off look like deleting the screening."""
    content = str(_serve(str(woman_of_50.id), [mammogram(protocol_card=False)])[0].content)

    assert "Mammogram" in content


@pytest.mark.django_db
def test_no_patient_is_a_bad_request_not_an_empty_page(woman_of_50: Patient) -> None:
    """Opened outside a chart there is no patient, and the honest answer is to
    say so rather than render a page that looks like a clean bill of health."""
    responses = _serve("", [mammogram()])

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    assert "No patient in context" in str(responses[0].content)


@pytest.mark.django_db
def test_whitespace_is_not_a_patient(woman_of_50: Patient) -> None:
    responses = _serve("   ", [mammogram()])

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_an_unknown_patient_renders_nothing_rather_than_someone_elses_record(
    woman_of_50: Patient,
) -> None:
    """A patient id that matches nobody must not fall through to another
    patient's data."""
    responses = _serve(NOBODY, [mammogram()])

    assert "Mammogram" not in str(responses[0].content)


@pytest.mark.django_db
def test_the_page_loads_nothing_from_anywhere(woman_of_50: Patient) -> None:
    """Same requirement the security review put on the editor: no third-party
    resources.

    The page does carry a script now - the write buttons need one - so the rule
    this enforces is the one that was always meant: nothing is *fetched*. The
    script is inline, which is why `src=` is what is checked rather than the
    tag.
    """
    content = str(_serve(str(woman_of_50.id), [mammogram()])[0].content)

    for forbidden in ("http://", "https://", "<img", "@import", "src="):
        assert forbidden not in content, f"record page reaches for {forbidden}"


@pytest.mark.django_db
def test_the_patient_id_reaches_the_script_without_being_read_back_from_the_page(
    woman_of_50: Patient,
) -> None:
    """The script posts the id the server already validated, rather than
    scraping it out of the DOM where anything on the page could have set it."""
    content = str(_serve(str(woman_of_50.id), [mammogram()])[0].content)

    assert "var P=" in content
    assert str(woman_of_50.id) in content


@pytest.mark.django_db
def test_a_practice_tracking_nothing_still_gets_a_page(woman_of_50: Patient) -> None:
    """An empty configuration is a legitimate state, not an error."""
    responses = _serve(str(woman_of_50.id), [])

    assert responses[0].status_code == HTTPStatus.OK


@pytest.mark.django_db(transaction=True)
def test_an_attestation_is_shown_with_who_recorded_it(
    attestation_table: None,
) -> None:
    """The whole case for storing these outside the chart rests on this line
    being on the page. A clinician reading "up to date" has to be able to see
    whose say-so it rests on."""
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    ScreeningAttestation.objects.create(
        patient_key=str(woman.id), screening_id="s1", kind="completed",
        effective_date=date(2026, 3, 4), interval_quantity=2, interval_unit="years",
        label="", recorded_by=STAFF, recorded_at=date(2026, 3, 4),
    )

    content = str(_serve(str(woman.id), [mammogram()])[0].content)

    assert "Marked complete 4 Mar 2026" in content
    # No staff row exists for this key in the test database, so the honest
    # fallback is used rather than printing the raw key at a clinician.
    assert "a staff member" in content
    assert STAFF not in content


# --- writing -----------------------------------------------------------------


@pytest.mark.django_db
def test_a_post_without_the_json_content_type_is_refused(woman_of_50: Patient) -> None:
    """CSRF. The SDK parses a JSON body whatever its declared type, so a
    cross-site form posting text/plain could otherwise write with a
    clinician's session."""
    responses = _post(
        {"patient": str(woman_of_50.id), "screening_id": "s1", "action": "completed"},
        [mammogram()],
        content_type="text/plain",
    )

    assert responses[0].status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    assert _json(responses[0])["success"] is False


@pytest.mark.django_db
def test_the_content_type_is_checked_before_the_body_is_parsed(
    woman_of_50: Patient, django_assert_num_queries: DjangoAssertNumQueries
) -> None:
    """A refusal that costs a database read is a refusal an attacker can use."""
    with django_assert_num_queries(0):
        _post({}, [mammogram()], content_type="text/plain")


@pytest.mark.django_db
def test_an_unknown_action_is_refused(woman_of_50: Patient) -> None:
    responses = _post(
        {"patient": str(woman_of_50.id), "screening_id": "s1", "action": "delete-chart"},
        [mammogram()],
    )

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_a_body_that_is_not_json_is_refused_rather_than_raising(
    woman_of_50: Patient,
) -> None:
    """The SDK raises a ValueError subclass on a bad body. An exception here
    would be an authenticated way to make the endpoint fall over."""
    request = MagicMock()
    request.content_type = "application/json"
    request.json.side_effect = ValueError("not json")
    request.headers = {"canvas-logged-in-user-id": STAFF}
    instance = _api("POST", "/record/attest")
    instance.request = request

    with patch(f"{MODULE}.load_config", lambda: {"screenings": [mammogram()]}):
        responses = instance.attest()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_a_json_body_that_is_not_an_object_is_refused(woman_of_50: Patient) -> None:
    responses = _post(["not", "an", "object"], [mammogram()])

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_a_screening_the_practice_does_not_track_is_refused(
    woman_of_50: Patient,
) -> None:
    """Storing a statement against an untracked rule would write a row nothing
    reads and nobody can see to undo."""
    responses = _post(
        {"patient": str(woman_of_50.id), "screening_id": "ghost", "action": "completed"},
        [mammogram()],
    )

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_a_screening_that_is_switched_off_is_refused(woman_of_50: Patient) -> None:
    responses = _post(
        {"patient": str(woman_of_50.id), "screening_id": "s1", "action": "completed"},
        [mammogram(enabled=False)],
    )

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_a_patient_who_does_not_exist_is_refused(woman_of_50: Patient) -> None:
    """Without this check a session could write rows against any string it
    liked, and nothing would ever read them or clean them up."""
    responses = _post(
        {"patient": NOBODY, "screening_id": "s1", "action": "completed"}, [mammogram()]
    )

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_a_patient_id_that_is_not_a_uuid_is_refused_rather_than_raising(
    woman_of_50: Patient,
) -> None:
    """The column is a UUID field, so a malformed id raises inside the ORM. On
    a write path an exception is a worse answer than a refusal."""
    responses = _post(
        {"patient": "1 OR 1=1", "screening_id": "s1", "action": "completed"}, [mammogram()]
    )

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db(transaction=True)
def test_marking_complete_stores_the_date_and_the_author(
    attestation_table: None,
) -> None:
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)

    responses = _post(
        {
            "patient": str(woman.id),
            "screening_id": "s1",
            "action": "completed",
            "effective_date": "2026-02-03",
        },
        [mammogram()],
    )

    assert _json(responses[0])["success"] is True
    row = ScreeningAttestation.objects.get(patient_key=str(woman.id), screening_id="s1")
    assert row.kind == "completed"
    assert row.effective_date == date(2026, 2, 3)
    assert row.recorded_by == STAFF
    assert (row.interval_quantity, row.interval_unit) == (2, "years")


@pytest.mark.django_db(transaction=True)
def test_the_chosen_signal_decides_how_long_the_completion_covers(
    attestation_table: None,
) -> None:
    """A colonoscopy buys ten years where a stool test buys one. Storing the
    wrong interval would send the patient a decade early or nine years late."""
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)

    _post(
        {
            "patient": str(woman.id),
            "screening_id": "s2",
            "action": "completed",
            "effective_date": today().isoformat(),
            "signal": 1,
        },
        [colorectal()],
    )

    row = ScreeningAttestation.objects.get(screening_id="s2")
    assert (row.interval_quantity, row.interval_unit) == (1, "years")


@pytest.mark.django_db(transaction=True)
def test_a_signal_index_out_of_range_falls_back_to_the_first(
    attestation_table: None,
) -> None:
    """The rule can be edited between the page rendering and the click. The
    first completion is the one `cards.order_filter` already treats as
    representative, so it is the defensible fallback."""
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)

    _post(
        {
            "patient": str(woman.id),
            "screening_id": "s2",
            "action": "completed",
            "effective_date": today().isoformat(),
            "signal": 99,
        },
        [colorectal()],
    )

    assert ScreeningAttestation.objects.get(screening_id="s2").interval_quantity == 10


@pytest.mark.django_db(transaction=True)
def test_a_signal_that_is_not_a_number_falls_back_to_the_first(
    attestation_table: None,
) -> None:
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)

    _post(
        {
            "patient": str(woman.id),
            "screening_id": "s2",
            "action": "completed",
            "effective_date": today().isoformat(),
            "signal": "colonoscopy",
        },
        [colorectal()],
    )

    assert ScreeningAttestation.objects.get(screening_id="s2").interval_quantity == 10


@pytest.mark.django_db
def test_a_completion_well_in_the_future_is_refused(woman_of_50: Patient) -> None:
    """A screening cannot have been done days from now. Accepting one would
    make it read as satisfied on evidence that does not exist yet - the
    "unknown never means positive" rule, on the one path where a person types
    the input.

    **Two days, not one.** One day of slack is deliberate: the route's clock is
    UTC and a provider's is not, so east of UTC an ordinary "today" already
    reads as tomorrow here. Two days is nobody's timezone.

    ⚠️ **Computed in UTC, because the route is.** This used `date.today()`,
    which is local, so west of UTC it started failing every evening once UTC
    rolled over - a test that passes until 7pm and then does not. Any test
    comparing against the route's clock has to use the route's clock.
    """
    responses = _post(
        {
            "patient": str(woman_of_50.id),
            "screening_id": "s1",
            "action": "completed",
            "effective_date": (today() + timedelta(days=2)).isoformat(),
        },
        [mammogram()],
    )

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_a_date_that_is_not_a_date_is_refused(woman_of_50: Patient) -> None:
    responses = _post(
        {
            "patient": str(woman_of_50.id),
            "screening_id": "s1",
            "action": "completed",
            "effective_date": "sometime last year",
        },
        [mammogram()],
    )

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db(transaction=True)
def test_marking_not_applicable_needs_no_date(attestation_table: None) -> None:
    """"Does not apply" is a standing statement about the rule, not a dated
    event, so it is recorded as of today whatever the date field holds."""
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)

    responses = _post(
        {
            "patient": str(woman.id),
            "screening_id": "s1",
            "action": "not_applicable",
            "effective_date": "nonsense",
        },
        [mammogram()],
    )

    assert _json(responses[0])["success"] is True
    assert ScreeningAttestation.objects.get(screening_id="s1").kind == "not_applicable"


@pytest.mark.django_db(transaction=True)
def test_a_second_statement_replaces_the_first(attestation_table: None) -> None:
    """One row per patient per screening. Two live statements about the same
    screening would leave readers to pick, and they would not agree."""
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    body = {"patient": str(woman.id), "screening_id": "s1", "action": "completed",
            "effective_date": today().isoformat()}

    _post(body, [mammogram()])
    _post({**body, "action": "not_applicable"}, [mammogram()])

    rows = list(ScreeningAttestation.objects.filter(screening_id="s1"))
    assert len(rows) == 1
    assert rows[0].kind == "not_applicable"


@pytest.mark.django_db(transaction=True)
def test_undo_removes_the_statement(attestation_table: None) -> None:
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    body = {"patient": str(woman.id), "screening_id": "s1", "action": "completed",
            "effective_date": today().isoformat()}
    _post(body, [mammogram()])

    responses = _post({**body, "action": "clear"}, [mammogram()])

    assert _json(responses[0])["success"] is True
    assert not ScreeningAttestation.objects.filter(screening_id="s1").exists()


@pytest.mark.django_db
def test_storage_that_is_not_ready_is_reported_rather_than_claimed(
    woman_of_50: Patient,
) -> None:
    """No attestation table here, so the write genuinely fails. It must come
    back as a failure: a button that looks like it worked and did not is the
    exact failure this plugin has already shipped three times."""
    responses = _post(
        {
            "patient": str(woman_of_50.id),
            "screening_id": "s1",
            "action": "completed",
            "effective_date": today().isoformat(),
        },
        [mammogram()],
    )

    assert _json(responses[0])["success"] is False
    assert "namespace" in _json(responses[0])["error"]


# --- keeping the cards in step ------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_practice_with_no_cards_gets_no_effects(attestation_table: None) -> None:
    """The default configuration. Nothing is carded, so there is no card to be
    out of step - and the unproven "return an effect from a route" mechanism is
    never exercised at all."""
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)

    responses = _post(
        {"patient": str(woman.id), "screening_id": "s1", "action": "not_applicable"},
        [mammogram(protocol_card=False)],
    )

    assert len(responses) == 1


@pytest.mark.django_db(transaction=True)
def test_a_carded_screening_gets_its_card_rewritten_and_the_patient_requeued(
    attestation_table: None,
) -> None:
    """Both mechanisms, because the first is unproven: the recomputed card
    comes back with the response, *and* the patient is pushed to the front of
    the sweep's queue so the card is rewritten even if returning an effect from
    a route turns out to do nothing."""
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)

    with patch(f"{MODULE}.invalidate_patient") as requeue:
        responses = _post(
            {"patient": str(woman.id), "screening_id": "s1", "action": "not_applicable"},
            [mammogram(protocol_card=True)],
        )

    assert len(responses) == 2
    requeue.assert_called_once()


# --- the query budget --------------------------------------------------------
#
# This endpoint is the one surface that computes on demand, so its cost lands on
# a provider waiting for a panel to paint rather than on a background sweep. It
# inherits the batching in `review_patient`, and these guards are what keep that
# true: nothing else on this path would notice a per-screening query creeping
# back, because the rendered record looks identical either way - only slower.
#
# **If one of these fails, fix the query. Do not raise the number.**


@pytest.mark.django_db
def test_the_record_costs_a_fixed_number_of_queries(
    woman_of_50: Patient, django_assert_num_queries: DjangoAssertNumQueries
) -> None:
    """Twenty screenings cost one patient read, one read per source, one snooze
    read and one attestation read - not twenty of anything.

    Mammography spans two sources (imaging and procedure), so this is 5. It was
    4 before the attestation read, and it moved by exactly one for twenty
    screenings, which is the evidence that read is per-request rather than per
    screening. `load_config` is patched out here; in production it adds one,
    for 6.
    """
    screenings = [mammogram(id=f"s{index}", name=f"S{index}") for index in range(20)]

    with django_assert_num_queries(5):
        responses = _serve(str(woman_of_50.id), screenings)

    assert "S19" in str(responses[0].content)


@pytest.mark.django_db(transaction=True)
def test_only_a_record_with_something_attested_looks_up_staff_names(
    attestation_table: None, django_assert_num_queries: DjangoAssertNumQueries
) -> None:
    """Almost no record has an attestation on it. The name lookup exists only
    to label one, so the common page must not pay for it - and when it does
    run, it is one query for the page rather than one per statement."""
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    screenings = [mammogram(id=f"s{index}", name=f"S{index}") for index in range(3)]

    with django_assert_num_queries(5):  # patient, imaging, procedure, snooze, attestation
        _serve(str(woman.id), screenings)

    for index in range(3):
        ScreeningAttestation.objects.create(
            patient_key=str(woman.id), screening_id=f"s{index}", kind="completed",
            effective_date=today(), interval_quantity=2, interval_unit="years",
            label="", recorded_by=f"{STAFF}-{index}", recorded_at=today(),
        )

    with django_assert_num_queries(6):  # the same, plus one staff read for all three
        _serve(str(woman.id), screenings)


@pytest.mark.django_db
def test_opening_the_record_outside_a_chart_never_touches_the_database(
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """No patient means no work. The route answers before it reads anything,
    which matters because the app icon can be clicked from anywhere."""
    with django_assert_num_queries(0):
        _serve("", [mammogram()])


# --- the patient id in the page's script ---------------------------------------


@pytest.mark.django_db
def test_an_id_that_could_break_out_of_the_script_never_reaches_it() -> None:
    """**The read route embeds the patient id in a JS string literal**, and the
    id arrives as a query parameter on a route any staff session can call with
    anything it likes.

    What keeps that safe is refusing everything that is not a UUID, rather than
    escaping on the way in - escaping is one forgotten call away from an XSS,
    and a patient id has no legitimate reason to contain a quote.
    """
    for hostile in (
        "'+alert(1)+'",
        "</script><script>alert(1)</script>",
        '"><img src=x onerror=alert(1)>',
        "1 OR 1=1",
        "\\",
    ):
        responses = _serve(hostile, [mammogram()])

        assert responses[0].status_code == HTTPStatus.BAD_REQUEST, hostile
        assert "alert(1)" not in str(responses[0].content), hostile
        assert "<script" not in str(responses[0].content), hostile


@pytest.mark.django_db
def test_hex_that_is_not_a_uuid_is_refused_rather_than_raising() -> None:
    """Passes the character check and is still not an id. The column is a UUID
    field, so handing this to the ORM raises instead of matching nothing."""
    for not_an_id in ("abc", "----", "deadbeef"):
        assert _serve(not_an_id, [mammogram()])[0].status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_an_id_shaped_like_a_uuid_but_matching_nobody_is_still_rendered() -> None:
    """Refusing non-UUIDs must not turn into refusing unknown patients - the
    honest answer there is an empty record, not an error."""
    responses = _serve(NOBODY, [mammogram()])

    assert responses[0].status_code == HTTPStatus.OK


# --- ordering from the panel ---------------------------------------------------


def open_note_for(patient: Patient) -> Note:
    """A note this patient's order can be staged into."""
    note = NoteFactory.create(patient=patient, datetime_of_service=datetime.now(UTC))
    CurrentNoteStateEvent.objects.create(note=note, state=NoteStates.NEW.value)
    return note


def _is_order(response: Any) -> bool:
    """Whether this is the staged imaging-order effect.

    Matched on `type`, not on the payload: `ORIGINATE_..._COMMAND` is the
    effect's type, and `effect.type` is an **int** rather than a string - a
    detail that has misled this repo's tooling before.
    """
    found: bool = getattr(response, "type", None) == EffectType.ORIGINATE_IMAGING_ORDER_COMMAND
    return found


def orderable(**over: Any) -> dict:
    return mammogram(order_command="imaging_order", order_code="77067",
                     order_button="Order mammogram",
                     order_comment="Screening mammogram", **over)


@pytest.mark.django_db(transaction=True)
def test_ordering_stages_the_command_and_records_it(attestation_table: None) -> None:
    """One click does both halves: the command lands in the open note, and the
    screening starts reading "awaiting result" instead of overdue."""
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    note = open_note_for(woman)

    responses = _post(
        {"patient": str(woman.id), "screening_id": "s1", "action": "ordered"},
        [orderable()],
    )

    assert _json(responses[0])["success"] is True
    staged = [r for r in responses[1:] if _is_order(r)]
    assert len(staged) == 1
    assert str(note.id) in staged[0].payload
    row = ScreeningAttestation.objects.get(screening_id="s1")
    assert row.kind == "ordered"
    assert row.recorded_by == STAFF
    assert row.label == "Screening mammogram"


@pytest.mark.django_db(transaction=True)
def test_ordering_without_an_open_note_is_refused_with_something_to_do(
    attestation_table: None,
) -> None:
    """**The one failure the provider can fix themselves.** This app is
    patient-scoped, so the panel can be open beside a chart with no note at
    all, and there is no effect that creates one."""
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)

    responses = _post(
        {"patient": str(woman.id), "screening_id": "s1", "action": "ordered"},
        [orderable()],
    )

    assert responses[0].status_code == HTTPStatus.CONFLICT
    assert "Open a note" in _json(responses[0])["error"]
    assert not ScreeningAttestation.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_nothing_is_staged_for_a_screening_with_no_order_command(
    attestation_table: None,
) -> None:
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    open_note_for(woman)

    responses = _post(
        {"patient": str(woman.id), "screening_id": "s1", "action": "ordered"},
        [mammogram(order_command="")],
    )

    assert _json(responses[0])["success"] is False
    assert not ScreeningAttestation.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_an_order_lands_even_if_the_bookkeeping_cannot(
    woman_of_50: Patient,
) -> None:
    """No attestation table here. A provider who clicked "order" and got an
    order is better served than one who got a refusal because a custom-data
    table was unavailable - so the command still goes, and the panel says the
    record did not."""
    open_note_for(woman_of_50)

    responses = _post(
        {"patient": str(woman_of_50.id), "screening_id": "s1", "action": "ordered"},
        [orderable()],
    )

    assert _json(responses[0])["success"] is False
    assert any(_is_order(r) for r in responses[1:])


@pytest.mark.django_db(transaction=True)
def test_an_ordered_screening_reads_as_awaiting_on_the_page(
    attestation_table: None,
) -> None:
    """End to end: order it, reopen the panel, and it no longer shouts."""
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    open_note_for(woman)
    _post(
        {"patient": str(woman.id), "screening_id": "s1", "action": "ordered"},
        [orderable()],
    )

    content = str(_serve(str(woman.id), [orderable()])[0].content)

    assert "Awaiting result" in content
    assert "Overdue by" not in content


@pytest.mark.django_db(transaction=True)
def test_a_command_the_sdk_will_not_stage_is_not_recorded_as_ordered(
    attestation_table: None,
) -> None:
    """If the order never reached the note, nothing may claim it did -
    recording "awaiting result" here would stop the screening reading as due
    on the strength of an order that does not exist."""
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    open_note_for(woman)

    with patch(f"{MODULE}.stage_order", return_value=None):
        responses = _post(
            {"patient": str(woman.id), "screening_id": "s1", "action": "ordered"},
            [orderable()],
        )

    assert _json(responses[0])["success"] is False
    assert not ScreeningAttestation.objects.exists()


# --- one click, one date -------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_one_click_does_not_produce_two_different_days(
    attestation_table: None,
) -> None:
    """**Found on a real chart.** The panel read "Marked complete 13 Oct 2026
    by <clinician>, recorded 14 Oct 2026" for a single click, because the
    completion date came from the browser and `recorded_at` came from the
    server's UTC clock, which had already rolled over.

    That second date exists to show a *genuine backdate*. Firing it on a
    timezone skew makes every evening entry look like somebody typed in an old
    result.
    """
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    # 9pm in Chicago: the server is on tomorrow, the provider is not.
    local = (today() - timedelta(days=1)).isoformat()

    _post(
        {"patient": str(woman.id), "screening_id": "s1", "action": "completed",
         "effective_date": local, "local_date": local},
        [mammogram()],
    )

    row = ScreeningAttestation.objects.get(screening_id="s1")
    assert row.effective_date == row.recorded_at, "one action, one date"
    # The rendered clause, not the bare word - the page's own script carries a
    # comment mentioning it.
    content = str(_serve(str(woman.id), [mammogram()])[0].content)
    assert ", recorded" not in content


@pytest.mark.django_db(transaction=True)
def test_a_genuine_backdate_still_shows_both_dates(attestation_table: None) -> None:
    """The clause has to keep working for what it is actually for: a screening
    done months ago and typed in now."""
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)

    _post(
        {"patient": str(woman.id), "screening_id": "s1", "action": "completed",
         "effective_date": "2026-03-04", "local_date": today().isoformat()},
        [mammogram()],
    )

    content = str(_serve(str(woman.id), [mammogram()])[0].content)
    assert "Marked complete 4 Mar 2026" in content
    assert ", recorded" in content


@pytest.mark.django_db(transaction=True)
def test_an_order_is_dated_in_the_providers_frame(attestation_table: None) -> None:
    woman = PatientFactory.create(birth_date=BORN, sex_at_birth="F", deceased=False)
    open_note_for(woman)
    local = (today() - timedelta(days=1)).isoformat()

    _post(
        {"patient": str(woman.id), "screening_id": "s1", "action": "ordered",
         "local_date": local},
        [orderable()],
    )

    row = ScreeningAttestation.objects.get(screening_id="s1")
    assert row.effective_date == date.fromisoformat(local)
    assert row.recorded_at == date.fromisoformat(local)
