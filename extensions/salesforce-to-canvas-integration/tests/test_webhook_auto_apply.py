"""Tests for the auto apply evaluator wired into the Sync webhook.

The webhook captures a Sync event, then the evaluator decides whether the row
applies automatically or holds for a human. A hold writes the reasons onto the
row and returns the 202 unchanged. An auto apply builds the Canvas effect,
appends it to the 202, and resolves the row under the automation actor so the
Activity ledger shows Automatic sync as who acted. The Delete event runs through
the same evaluator, holding by default and dispatching the configured delete
action when auto delete is enabled.

These drive the route against the real ORM. The link lookup, the duplicate
lookup, and the chart snapshot are patched at the names the handler calls.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

from canvas_sdk.test_utils.factories import PatientFactory

from salesforce_to_canvas_integration.models.incoming_patient_record import (
    IncomingPatientRecord,
)
from salesforce_to_canvas_integration.models.resolution_audit_entry import (
    ResolutionAuditEntry,
)
from salesforce_to_canvas_integration.handlers.webhook_base import (
    _REASON_FHIR_DELETE_FAILED,
    _REASON_FHIR_NOT_CONFIGURED,
)
from salesforce_to_canvas_integration.services.canvas_fhir_client import (
    CanvasFhirError,
)
from salesforce_to_canvas_integration.services.resolution import AUTOMATIC_STAFF_NAME
from salesforce_to_canvas_integration.services.sync_rules import (
    DELETE_ACTION_MARK_INACTIVE,
    DELETE_ACTION_TAG_DELETED,
    DELETE_ACTION_UNLINK,
    REASON_AUTO_DELETE_OFF,
    REASON_DUPLICATE_MATCH,
    REASON_INCOMPLETE_ADDRESS,
    REASON_LINK_PENDING,
    REASON_PREVIOUSLY_SKIPPED,
    SyncSettings,
)

# Reuse the request harness from the capture tests so the body signing and the
# handler construction stay defined in one place.
from tests.test_webhook_api import (
    _envelope,
    _make_api,
    _request,
    _secrets,
    _status,
)

_LINK = "salesforce_to_canvas_integration.handlers.webhook_base.find_linked_patient_id"
_DUP = "salesforce_to_canvas_integration.handlers.webhook_base.find_duplicate_patients"
_SETTINGS = "salesforce_to_canvas_integration.handlers.webhook_base.load_sync_settings"


def _drive(
    payload: Any,
    *,
    linked_patient_id: str | None = None,
    duplicates: list[dict[str, Any]] | None = None,
) -> list[Any]:
    """Invoke the sync route with the link and duplicate lookups controlled."""
    api = _make_api(_secrets())
    type(api).request = PropertyMock(return_value=_request(payload))
    with (
        patch(_LINK, return_value=linked_patient_id),
        patch(_DUP, return_value=duplicates or []),
    ):
        responses: list[Any] = api.sync_route()
    return responses


def _full_create(record_id: str, **overrides: str) -> dict[str, Any]:
    """A create payload that clears the default filters, name, dob, and phone."""
    record = {
        "Id": record_id,
        "FirstName": "Jane",
        "LastName": "Doe",
        "Birthdate": "1990-05-01",
        "Phone": "5551234567",
    }
    record.update(overrides)
    return _envelope("sync", record)


def _row(external_id: str) -> IncomingPatientRecord:
    row: IncomingPatientRecord = IncomingPatientRecord.objects.get(
        external_id=external_id
    )
    return row


def _entries(external_id: str) -> list[ResolutionAuditEntry]:
    return list(
        ResolutionAuditEntry.objects.filter(external_id=external_id).order_by("dbid")
    )


# ---------------------------------------------------------------------------
# Create, the happy path and the automation actor.
# ---------------------------------------------------------------------------


def test_create_full_payload_auto_applies_and_logs_automation_actor() -> None:
    responses = _drive(_full_create("003AUTO"), linked_patient_id=None)

    # 202 ack plus the appended create effect.
    assert _status(responses[0]) == HTTPStatus.ACCEPTED
    assert len(responses) == 2

    row = _row("003AUTO")
    assert row.status == "accepted"
    assert row.hold_reasons == []
    # The automation actor carries no staff dbid.
    assert row.actioned_by_id is None

    entries = _entries("003AUTO")
    assert len(entries) == 1
    assert entries[0].action_taken == "created"
    assert entries[0].staff_name == AUTOMATIC_STAFF_NAME
    assert entries[0].staff_key == ""
    assert entries[0].note.startswith("Automatically applied create")


# ---------------------------------------------------------------------------
# Create, the layer two holds. Each writes its reasons and applies nothing.
# ---------------------------------------------------------------------------


def test_create_holds_on_missing_required_birthdate() -> None:
    payload = _envelope("sync", {"Id": "003NODOB", "FirstName": "Jane", "LastName": "Doe"})

    responses = _drive(payload, linked_patient_id=None)

    assert _status(responses[0]) == HTTPStatus.ACCEPTED
    assert len(responses) == 1  # nothing applied
    row = _row("003NODOB")
    assert row.status == "new"
    assert "missing required date of birth" in row.hold_reasons
    assert _entries("003NODOB") == []


def test_create_holds_on_invalid_birthdate() -> None:
    payload = _full_create("003BADDOB", Birthdate="not-a-date")

    responses = _drive(payload, linked_patient_id=None)

    assert len(responses) == 1
    row = _row("003BADDOB")
    assert row.status == "new"
    assert "invalid date of birth" in row.hold_reasons


def test_create_holds_on_partial_address() -> None:
    payload = _full_create("003ADDR", MailingStreet="1 Main St")  # street only

    responses = _drive(payload, linked_patient_id=None)

    assert len(responses) == 1
    row = _row("003ADDR")
    assert row.status == "new"
    assert REASON_INCOMPLETE_ADDRESS in row.hold_reasons


def test_create_holds_on_duplicate_match() -> None:
    dupes = [{"id": "p1", "first_name": "Jane", "last_name": "Doe", "birth_date": "1990-05-01"}]

    responses = _drive(_full_create("003DUP2"), linked_patient_id=None, duplicates=dupes)

    assert len(responses) == 1
    row = _row("003DUP2")
    assert row.status == "new"
    assert REASON_DUPLICATE_MATCH in row.hold_reasons


# ---------------------------------------------------------------------------
# Create, the hard gates over history.
# ---------------------------------------------------------------------------


def test_link_pending_race_holds_the_second_create() -> None:
    # First create auto applies and flips the row to accepted, but its patient
    # link lands asynchronously, so the link lookup still returns None.
    _drive(_full_create("003RACE"), linked_patient_id=None)
    assert _row("003RACE").status == "accepted"

    # A second, different create arrives before the link lands. It still derives
    # create because the lookup is empty, and the accepted create gate holds it.
    responses = _drive(
        _full_create("003RACE", Email="jane@new.example"), linked_patient_id=None
    )

    assert len(responses) == 1
    newest = (
        IncomingPatientRecord.objects.filter(external_id="003RACE", action="create")
        .order_by("-received_at", "-dbid")
        .first()
    )
    assert newest is not None
    assert newest.status == "new"
    assert REASON_LINK_PENDING in newest.hold_reasons


def test_previously_skipped_gate_holds_new_arrival() -> None:
    # A prior skip decision for the contact stands in for a never sync flag.
    ResolutionAuditEntry.objects.create(
        external_id="003SKIP",
        event_id=1,
        action="create",
        action_taken="skipped",
        staff_key="abc",
        staff_name="Reviewer",
    )

    responses = _drive(_full_create("003SKIP"), linked_patient_id=None)

    assert len(responses) == 1
    row = _row("003SKIP")
    assert row.status == "new"
    assert REASON_PREVIOUSLY_SKIPPED in row.hold_reasons


def test_reopen_after_skip_releases_the_gate() -> None:
    # A reopen is the newest decision, so the skipped gate no longer fires and a
    # fresh arrival auto applies.
    ResolutionAuditEntry.objects.create(
        external_id="003REOPEN", event_id=1, action="create", action_taken="skipped"
    )
    ResolutionAuditEntry.objects.create(
        external_id="003REOPEN", event_id=1, action="create", action_taken="reopened"
    )

    responses = _drive(_full_create("003REOPEN"), linked_patient_id=None)

    assert len(responses) == 2
    assert _row("003REOPEN").status == "accepted"


# ---------------------------------------------------------------------------
# Modify, applies and holds.
# ---------------------------------------------------------------------------


def test_modify_full_payload_auto_applies_under_automation_actor() -> None:
    # The update effect validates the patient exists, so the linked id must point
    # at a real Canvas patient.
    patient = PatientFactory.create()
    pid = str(patient.id)

    responses = _drive(_full_create("003MOD"), linked_patient_id=pid)

    assert _status(responses[0]) == HTTPStatus.ACCEPTED
    assert len(responses) == 2
    row = _row("003MOD")
    assert row.action == "modify"
    assert row.status == "accepted"

    entries = _entries("003MOD")
    assert len(entries) == 1
    assert entries[0].action_taken == "modify_applied"
    assert entries[0].staff_name == AUTOMATIC_STAFF_NAME
    assert entries[0].result_patient_id == pid
    assert entries[0].note.startswith("Automatically applied modify")


def test_modify_holds_on_missing_required() -> None:
    payload = _envelope(
        "sync", {"Id": "003MODNO", "FirstName": "Jane", "LastName": "Doe"}
    )

    responses = _drive(payload, linked_patient_id="patient-9")

    assert len(responses) == 1
    row = _row("003MODNO")
    assert row.action == "modify"
    assert row.status == "new"
    assert "missing required date of birth" in row.hold_reasons
    assert _entries("003MODNO") == []


# ---------------------------------------------------------------------------
# Dedup runs before evaluation.
# ---------------------------------------------------------------------------


def test_identical_resend_drops_before_evaluation() -> None:
    _drive(_full_create("003IDEM"), linked_patient_id=None)
    # The second identical body dedups, so no second row, no second decision.
    responses = _drive(_full_create("003IDEM"), linked_patient_id=None)

    assert _status(responses[0]) == HTTPStatus.ACCEPTED
    assert len(responses) == 1  # the dropped dup applies nothing
    assert IncomingPatientRecord.objects.filter(external_id="003IDEM").count() == 1
    assert len(_entries("003IDEM")) == 1  # only the first apply logged


# ---------------------------------------------------------------------------
# Delete, the off toggle, the three configured actions, and the degradations.
# The delete actions read settings.auto_delete and settings.delete_action, so
# the tests drive the settings loader rather than persisting a singleton row.
# ---------------------------------------------------------------------------


def _fhir_secrets() -> dict[str, str]:
    """Secrets that pass canvas_fhir_configured, for the mark inactive and unlink paths."""
    secrets = _secrets()
    secrets.update(
        {
            "CANVAS_API_CLIENT_ID": "canvas-cid",
            "CANVAS_API_CLIENT_SECRET": "canvas-csec",
            "FUMAGE_BASE_URL": "https://fumage-example.canvasmedical.com",
        }
    )
    return secrets


class _FakeFhirClient:
    """Records the FHIR delete calls and lets a test script a failure."""

    def __init__(self, *, raise_exc: Exception | None = None) -> None:
        self.inactive_calls: list[str] = []
        self.unlink_calls: list[tuple[str, str]] = []
        self._raise = raise_exc

    def mark_patient_inactive(self, patient_id: str) -> None:
        self.inactive_calls.append(patient_id)
        if self._raise is not None:
            raise self._raise

    def remove_salesforce_identifier(self, patient_id: str, sf_external_id: str) -> None:
        self.unlink_calls.append((patient_id, sf_external_id))
        if self._raise is not None:
            raise self._raise


def _drive_delete(
    record_id: str,
    *,
    settings: SyncSettings,
    linked_patient_id: str | None,
    secrets: dict[str, Any] | None = None,
    fhir_client: _FakeFhirClient | None = None,
) -> list[Any]:
    """Invoke the sync route with a delete intent and the settings controlled."""
    api = _make_api(secrets if secrets is not None else _secrets())
    if fhir_client is not None:

        def _fake_client(config: Any) -> _FakeFhirClient:
            return fhir_client

        api._build_canvas_fhir_client = _fake_client  # type: ignore[assignment,method-assign]
    payload = _envelope("delete", {"Id": record_id})
    type(api).request = PropertyMock(return_value=_request(payload))
    with (
        patch(_LINK, return_value=linked_patient_id),
        patch(_SETTINGS, return_value=settings),
    ):
        responses: list[Any] = api.sync_route()
    return responses


def test_delete_off_toggle_holds_with_reason() -> None:
    # Auto delete is off in the defaults, so a delete for a linked patient holds
    # for a human with the disabled reason, exactly the manual flow as before.
    responses = _drive_delete(
        "003DELOFF", settings=SyncSettings(auto_delete=False), linked_patient_id="p1"
    )

    assert _status(responses[0]) == HTTPStatus.ACCEPTED
    assert len(responses) == 1
    row = _row("003DELOFF")
    assert row.action == "delete"
    assert row.status == "new"
    assert row.hold_reasons == [REASON_AUTO_DELETE_OFF]
    assert _entries("003DELOFF") == []


def test_delete_auto_applies_tag_deleted() -> None:
    # Tag deleted is effect based, and the effect validates the patient exists at
    # build time, so the linked id must point at a real Canvas patient.
    patient = PatientFactory.create()
    pid = str(patient.id)

    responses = _drive_delete(
        "003DELTAG",
        settings=SyncSettings(auto_delete=True, delete_action=DELETE_ACTION_TAG_DELETED),
        linked_patient_id=pid,
    )

    assert _status(responses[0]) == HTTPStatus.ACCEPTED
    assert len(responses) == 2  # the 202 plus the tag effect
    row = _row("003DELTAG")
    assert row.status == "accepted"
    assert row.hold_reasons == []

    entries = _entries("003DELTAG")
    assert len(entries) == 1
    assert entries[0].action_taken == "tag_deleted"
    assert entries[0].staff_name == AUTOMATIC_STAFF_NAME
    assert entries[0].result_patient_id == pid
    assert entries[0].note.startswith("Automatically applied delete (tag deleted)")


def test_delete_auto_applies_mark_inactive() -> None:
    # Mark inactive routes through the FHIR client, never an effect, so a stub id
    # is enough, the fake client records the call.
    fake = _FakeFhirClient()
    responses = _drive_delete(
        "003DELINACT",
        settings=SyncSettings(
            auto_delete=True, delete_action=DELETE_ACTION_MARK_INACTIVE
        ),
        linked_patient_id="patient-7",
        secrets=_fhir_secrets(),
        fhir_client=fake,
    )

    assert _status(responses[0]) == HTTPStatus.ACCEPTED
    assert len(responses) == 1  # FHIR call, no effect appended
    assert fake.inactive_calls == ["patient-7"]
    row = _row("003DELINACT")
    assert row.status == "accepted"
    assert row.hold_reasons == []

    entries = _entries("003DELINACT")
    assert len(entries) == 1
    assert entries[0].action_taken == "mark_inactive"
    assert entries[0].staff_name == AUTOMATIC_STAFF_NAME
    assert entries[0].result_patient_id == "patient-7"
    assert entries[0].note.startswith("Automatically applied delete (mark inactive)")


def test_delete_auto_applies_unlink() -> None:
    fake = _FakeFhirClient()
    responses = _drive_delete(
        "003DELUNLINK",
        settings=SyncSettings(auto_delete=True, delete_action=DELETE_ACTION_UNLINK),
        linked_patient_id="patient-8",
        secrets=_fhir_secrets(),
        fhir_client=fake,
    )

    assert _status(responses[0]) == HTTPStatus.ACCEPTED
    assert len(responses) == 1
    assert fake.unlink_calls == [("patient-8", "003DELUNLINK")]
    row = _row("003DELUNLINK")
    assert row.status == "accepted"

    entries = _entries("003DELUNLINK")
    assert len(entries) == 1
    assert entries[0].action_taken == "unlink"
    assert entries[0].note.startswith("Automatically applied delete (unlink)")


def test_delete_degrades_to_hold_when_fhir_unconfigured() -> None:
    # The default secrets carry no Canvas FHIR keys, so canvas_fhir_configured is
    # false and the mark inactive delete degrades to a manual hold, never an error.
    responses = _drive_delete(
        "003DELNOFHIR",
        settings=SyncSettings(
            auto_delete=True, delete_action=DELETE_ACTION_MARK_INACTIVE
        ),
        linked_patient_id="patient-9",
    )

    assert _status(responses[0]) == HTTPStatus.ACCEPTED
    assert len(responses) == 1
    row = _row("003DELNOFHIR")
    assert row.status == "new"
    assert row.hold_reasons == [_REASON_FHIR_NOT_CONFIGURED]
    assert _entries("003DELNOFHIR") == []


def test_delete_degrades_to_hold_when_fhir_fails() -> None:
    # A transport or auth failure from the FHIR client degrades to a manual hold
    # naming the failure, the webhook still answers 202.
    fake = _FakeFhirClient(raise_exc=CanvasFhirError("boom"))
    responses = _drive_delete(
        "003DELFAIL",
        settings=SyncSettings(
            auto_delete=True, delete_action=DELETE_ACTION_MARK_INACTIVE
        ),
        linked_patient_id="patient-10",
        secrets=_fhir_secrets(),
        fhir_client=fake,
    )

    assert _status(responses[0]) == HTTPStatus.ACCEPTED
    assert len(responses) == 1
    assert fake.inactive_calls == ["patient-10"]
    row = _row("003DELFAIL")
    assert row.status == "new"
    assert row.hold_reasons == [_REASON_FHIR_DELETE_FAILED]
    assert _entries("003DELFAIL") == []


def test_delete_with_no_linked_patient_stays_activity_only_when_on() -> None:
    # Auto delete on but nothing in Canvas to delete, so it is captured and left
    # in the Activity feed with no hold reason and no resolution.
    responses = _drive_delete(
        "003DELNONE",
        settings=SyncSettings(
            auto_delete=True, delete_action=DELETE_ACTION_MARK_INACTIVE
        ),
        linked_patient_id=None,
    )

    assert _status(responses[0]) == HTTPStatus.ACCEPTED
    assert len(responses) == 1
    row = _row("003DELNONE")
    assert row.action == "delete"
    assert row.status == "new"
    assert row.hold_reasons == []
    assert _entries("003DELNONE") == []


def test_delete_with_no_linked_patient_stays_activity_only_when_off() -> None:
    # Off and no patient, the no-patient short circuit wins over the disabled
    # reason, so it is Activity only rather than a held actionable row.
    responses = _drive_delete(
        "003DELNONEOFF", settings=SyncSettings(auto_delete=False), linked_patient_id=None
    )

    assert len(responses) == 1
    row = _row("003DELNONEOFF")
    assert row.status == "new"
    assert row.hold_reasons == []
    assert _entries("003DELNONEOFF") == []
