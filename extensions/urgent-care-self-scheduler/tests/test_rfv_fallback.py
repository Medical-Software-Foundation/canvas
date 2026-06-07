from types import SimpleNamespace

from canvas_sdk.events import EventType

from urgent_care_self_scheduler.handlers.rfv_fallback import (
    CONSUMED_MARKER,
    PENDING_RFV_KEY_PREFIX,
    UrgentCareRfvOriginator,
    _build_hpi_narrative,
    _correlation_id_from_appointment,
)


def _ext_id(system: str, value: str) -> SimpleNamespace:
    return SimpleNamespace(system=system, value=value)


def _appt_with_external_ids(*ids: SimpleNamespace) -> SimpleNamespace:
    """Mock appointment with external_identifiers manager exposing .all()."""
    return SimpleNamespace(
        external_identifiers=SimpleNamespace(all=lambda: list(ids)),
    )


# ---- _correlation_id_from_appointment --------------------------------------


def test_correlation_id_returns_value_for_our_system() -> None:
    appt = _appt_with_external_ids(
        _ext_id("urgent-care-self-scheduler", "uuid-123"),
    )
    assert _correlation_id_from_appointment(appt) == "uuid-123"


def test_correlation_id_returns_none_when_no_matching_system() -> None:
    appt = _appt_with_external_ids(
        _ext_id("some-other-plugin", "uuid-456"),
    )
    assert _correlation_id_from_appointment(appt) is None


def test_correlation_id_returns_none_when_no_external_identifiers() -> None:
    appt = _appt_with_external_ids()
    assert _correlation_id_from_appointment(appt) is None


def test_correlation_id_picks_ours_among_multiple() -> None:
    appt = _appt_with_external_ids(
        _ext_id("other-system", "other-value"),
        _ext_id("urgent-care-self-scheduler", "ours-value"),
        _ext_id("third-system", "third-value"),
    )
    assert _correlation_id_from_appointment(appt) == "ours-value"


# ---- handler configuration --------------------------------------------------


def test_handler_responds_to_appointment_created_and_note_state_change() -> None:
    # Listen to both events to handle the effect-ordering race where the metadata
    # write may not have landed by the time APPOINTMENT_CREATED fires.
    assert EventType.Name(EventType.APPOINTMENT_CREATED) in UrgentCareRfvOriginator.RESPONDS_TO
    assert EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED) in UrgentCareRfvOriginator.RESPONDS_TO


def test_metadata_key_prefix_matches_book_api() -> None:
    # The same prefix must be used by BookAPI's stash and the handler's lookup.
    from urgent_care_self_scheduler.handlers.api import PENDING_RFV_KEY_PREFIX as book_prefix
    assert PENDING_RFV_KEY_PREFIX == book_prefix


def test_consumed_marker_is_non_empty_distinct_string() -> None:
    # Must be a value the handler can recognize as "already processed" so we
    # don't re-originate the RFV on every subsequent appointment update.
    assert isinstance(CONSUMED_MARKER, str) and CONSUMED_MARKER


# ---- _build_hpi_narrative ---------------------------------------------------


def test_hpi_narrative_no_changes_paths() -> None:
    intake = {
        "symptom_duration": "2 days",
        "medications": {"no_changes": True, "changes": []},
        "allergies": {"no_changes": True, "changes": []},
    }
    text = _build_hpi_narrative(intake)
    assert "Symptom duration: 2 days" in text
    assert "Medications: No changes reported." in text
    assert "Allergies: No changes reported." in text


def test_hpi_narrative_includes_flagged_meds_with_labels_and_notes() -> None:
    intake = {
        "symptom_duration": "1 week",
        "medications": {
            "no_changes": False,
            "changes": [
                {"medication_id": "m1", "label": "Lisinopril 10mg", "note": "switched to 20mg"},
                {"medication_id": "m2", "label": "Atorvastatin 20mg", "note": ""},
            ],
        },
        "allergies": {"no_changes": True, "changes": []},
    }
    text = _build_hpi_narrative(intake)
    assert "• Lisinopril 10mg (switched to 20mg)" in text
    # Med with no note: bullet but no parenthetical.
    assert "• Atorvastatin 20mg" in text
    assert "Atorvastatin 20mg (" not in text


def test_hpi_narrative_falls_back_to_unknown_label() -> None:
    intake = {
        "symptom_duration": "",
        "medications": {
            "no_changes": False,
            "changes": [{"medication_id": "m1", "label": "", "note": "stopped"}],
        },
        "allergies": {"no_changes": True, "changes": []},
    }
    text = _build_hpi_narrative(intake)
    assert "• Unknown medication (stopped)" in text


def test_hpi_narrative_omits_symptom_duration_when_empty() -> None:
    intake = {
        "symptom_duration": "",
        "medications": {"no_changes": True, "changes": []},
        "allergies": {"no_changes": True, "changes": []},
    }
    text = _build_hpi_narrative(intake)
    assert "Symptom duration" not in text
    assert "Medications: No changes reported." in text


def test_hpi_narrative_separates_sections_with_blank_lines() -> None:
    intake = {
        "symptom_duration": "2 days",
        "medications": {"no_changes": True, "changes": []},
        "allergies": {"no_changes": True, "changes": []},
    }
    text = _build_hpi_narrative(intake)
    # Each section separated by an explicit blank line for visual clarity.
    assert "\n\n" in text


# ---- UrgentCareRfvOriginator.compute / _resolve_appointment ----------------


def _make_handler_with_event(event_type, target_id="appt-uuid", note_id=None):
    """Build a handler with a stubbed self.event."""
    from canvas_sdk.events import EventType

    event = SimpleNamespace(
        type=event_type,
        target=SimpleNamespace(id=target_id),
        context={"note_id": note_id} if note_id else {},
    )
    handler = UrgentCareRfvOriginator.__new__(UrgentCareRfvOriginator)
    handler.event = event
    handler.secrets = {}
    return handler


def _appt_with_metadata(*, correlation_id, intake_json, has_note=True):
    """Returns a SimpleNamespace appointment matching the handler's expectations."""
    metadata_record = SimpleNamespace(value=intake_json)
    metadata_qs = SimpleNamespace(filter=lambda **_: SimpleNamespace(first=lambda: metadata_record))
    patient = SimpleNamespace(id="patient-uuid", metadata=metadata_qs)

    note = SimpleNamespace(id="note-uuid") if has_note else None

    ext_id = SimpleNamespace(
        system="urgent-care-self-scheduler",
        value=correlation_id,
    )
    return SimpleNamespace(
        id="appt-uuid",
        note=note,
        patient=patient,
        external_identifiers=SimpleNamespace(all=lambda: [ext_id]),
    )


def test_compute_returns_empty_when_appointment_not_found(mocker):
    from canvas_sdk.events import EventType
    from canvas_sdk.v1.data.appointment import Appointment

    base_qs = SimpleNamespace(
        get=mocker.Mock(side_effect=Appointment.DoesNotExist),
    )
    select_related = SimpleNamespace(
        prefetch_related=lambda *_a: base_qs,
    )
    mocker.patch.object(
        Appointment.objects, "select_related", return_value=select_related
    )

    handler = _make_handler_with_event(EventType.APPOINTMENT_CREATED)
    assert handler.compute() == []


def test_compute_returns_empty_when_appointment_has_no_external_identifier(mocker):
    """Appointment exists but isn't one of ours."""
    from canvas_sdk.events import EventType
    from canvas_sdk.v1.data.appointment import Appointment

    appt = SimpleNamespace(
        id="appt-uuid",
        external_identifiers=SimpleNamespace(all=lambda: []),  # no urgent-care system
    )
    base_qs = SimpleNamespace(get=lambda **_: appt)
    select_related = SimpleNamespace(prefetch_related=lambda *_a: base_qs)
    mocker.patch.object(Appointment.objects, "select_related", return_value=select_related)

    handler = _make_handler_with_event(EventType.APPOINTMENT_CREATED)
    assert handler.compute() == []


def test_compute_returns_empty_when_appointment_has_no_linked_note(mocker):
    from canvas_sdk.events import EventType
    from canvas_sdk.v1.data.appointment import Appointment

    appt = _appt_with_metadata(correlation_id="cid", intake_json="{}", has_note=False)
    base_qs = SimpleNamespace(get=lambda **_: appt)
    select_related = SimpleNamespace(prefetch_related=lambda *_a: base_qs)
    mocker.patch.object(Appointment.objects, "select_related", return_value=select_related)

    handler = _make_handler_with_event(EventType.APPOINTMENT_CREATED)
    assert handler.compute() == []


def test_compute_returns_empty_when_metadata_consumed(mocker):
    from canvas_sdk.events import EventType
    from canvas_sdk.v1.data.appointment import Appointment

    appt = _appt_with_metadata(correlation_id="cid", intake_json=CONSUMED_MARKER)
    base_qs = SimpleNamespace(get=lambda **_: appt)
    select_related = SimpleNamespace(prefetch_related=lambda *_a: base_qs)
    mocker.patch.object(Appointment.objects, "select_related", return_value=select_related)

    handler = _make_handler_with_event(EventType.APPOINTMENT_CREATED)
    assert handler.compute() == []


def test_compute_returns_empty_when_metadata_missing(mocker):
    from canvas_sdk.events import EventType
    from canvas_sdk.v1.data.appointment import Appointment

    patient = SimpleNamespace(
        id="patient-uuid",
        metadata=SimpleNamespace(filter=lambda **_: SimpleNamespace(first=lambda: None)),
    )
    appt = SimpleNamespace(
        id="appt-uuid",
        note=SimpleNamespace(id="note-uuid"),
        patient=patient,
        external_identifiers=SimpleNamespace(all=lambda: [
            SimpleNamespace(system="urgent-care-self-scheduler", value="cid"),
        ]),
    )
    base_qs = SimpleNamespace(get=lambda **_: appt)
    select_related = SimpleNamespace(prefetch_related=lambda *_a: base_qs)
    mocker.patch.object(Appointment.objects, "select_related", return_value=select_related)

    handler = _make_handler_with_event(EventType.APPOINTMENT_CREATED)
    assert handler.compute() == []


def test_compute_returns_empty_for_malformed_intake_json(mocker):
    from canvas_sdk.events import EventType
    from canvas_sdk.v1.data.appointment import Appointment

    appt = _appt_with_metadata(correlation_id="cid", intake_json="not valid json{{")
    base_qs = SimpleNamespace(get=lambda **_: appt)
    select_related = SimpleNamespace(prefetch_related=lambda *_a: base_qs)
    mocker.patch.object(Appointment.objects, "select_related", return_value=select_related)

    handler = _make_handler_with_event(EventType.APPOINTMENT_CREATED)
    assert handler.compute() == []


def test_compute_returns_empty_when_rfv_text_empty(mocker):
    import json as _json
    from canvas_sdk.events import EventType
    from canvas_sdk.v1.data.appointment import Appointment

    appt = _appt_with_metadata(
        correlation_id="cid",
        intake_json=_json.dumps({"reason_for_visit": "  ", "symptom_duration": "1 day"}),
    )
    base_qs = SimpleNamespace(get=lambda **_: appt)
    select_related = SimpleNamespace(prefetch_related=lambda *_a: base_qs)
    mocker.patch.object(Appointment.objects, "select_related", return_value=select_related)

    handler = _make_handler_with_event(EventType.APPOINTMENT_CREATED)
    assert handler.compute() == []


def test_compute_originates_rfv_and_hpi_and_consumes_metadata(mocker):
    """Happy path: compute returns 3 effects (RFV + HPI + consume marker)."""
    import json as _json
    from canvas_sdk.commands import ReasonForVisitCommand, HistoryOfPresentIllnessCommand
    from canvas_sdk.effects.patient_metadata import PatientMetadata
    from canvas_sdk.events import EventType
    from canvas_sdk.v1.data.appointment import Appointment

    appt = _appt_with_metadata(
        correlation_id="cid",
        intake_json=_json.dumps({
            "reason_for_visit": "sore throat",
            "symptom_duration": "2 days",
            "medications": {"no_changes": True, "changes": []},
            "allergies": {"no_changes": True, "changes": []},
        }),
    )
    base_qs = SimpleNamespace(get=lambda **_: appt)
    select_related = SimpleNamespace(prefetch_related=lambda *_a: base_qs)
    mocker.patch.object(Appointment.objects, "select_related", return_value=select_related)

    # Bypass note_uuid + patient_id DB validation in originate/upsert by replacing
    # the methods with stub Effects. We're testing the compute orchestration here,
    # not the SDK's command validation (covered separately by SDK tests).
    rfv_effect = SimpleNamespace(name="rfv")
    hpi_effect = SimpleNamespace(name="hpi")
    upsert_effect = SimpleNamespace(name="upsert")
    mocker.patch.object(ReasonForVisitCommand, "originate", return_value=rfv_effect)
    mocker.patch.object(HistoryOfPresentIllnessCommand, "originate", return_value=hpi_effect)
    mocker.patch.object(PatientMetadata, "upsert", return_value=upsert_effect)

    handler = _make_handler_with_event(EventType.APPOINTMENT_CREATED)
    effects = handler.compute()
    assert effects == [rfv_effect, hpi_effect, upsert_effect]


def test_compute_resolves_appointment_via_note_for_state_change_event(mocker):
    import json as _json
    from canvas_sdk.commands import ReasonForVisitCommand, HistoryOfPresentIllnessCommand
    from canvas_sdk.effects.patient_metadata import PatientMetadata
    from canvas_sdk.events import EventType
    from canvas_sdk.v1.data.appointment import Appointment

    appt = _appt_with_metadata(
        correlation_id="cid",
        intake_json=_json.dumps({
            "reason_for_visit": "headache",
            "symptom_duration": "1 day",
            "medications": {"no_changes": True, "changes": []},
            "allergies": {"no_changes": True, "changes": []},
        }),
    )
    base_qs = SimpleNamespace(
        get=lambda **_: appt,
        filter=lambda **_: SimpleNamespace(first=lambda: appt),
    )
    select_related = SimpleNamespace(prefetch_related=lambda *_a: base_qs)
    mocker.patch.object(Appointment.objects, "select_related", return_value=select_related)
    mocker.patch.object(ReasonForVisitCommand, "originate", return_value=SimpleNamespace())
    mocker.patch.object(HistoryOfPresentIllnessCommand, "originate", return_value=SimpleNamespace())
    mocker.patch.object(PatientMetadata, "upsert", return_value=SimpleNamespace())

    handler = _make_handler_with_event(
        EventType.NOTE_STATE_CHANGE_EVENT_CREATED,
        note_id="note-uuid",
    )
    assert len(handler.compute()) == 3


def test_compute_returns_empty_for_state_change_event_without_note_id(mocker):
    from canvas_sdk.events import EventType

    handler = _make_handler_with_event(EventType.NOTE_STATE_CHANGE_EVENT_CREATED, note_id=None)
    handler.event.context = {}  # ensure no note_id
    assert handler.compute() == []
