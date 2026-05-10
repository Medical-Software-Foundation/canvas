"""Tests for the SimpleAPI handlers (Phase A auth + Phase B logic)."""

import json
from collections.abc import Iterator
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from canvas_generated.messages.effects_pb2 import EffectType
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin
from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError
from django.db import DatabaseError


def _effect_name(effect: Any) -> str:
    """Effect.type is an EffectType enum (int) — resolve back to its name so
    tests can assert on human-readable command lifecycles."""
    return str(EffectType.Name(effect.type))

from nutrition_charting.api.nutrition_api import (
    NutritionChartingAPI,
    PrintNutritionNoteAPI,
    _coerce_int,
    _looks_like_uuid,
    _multi_command_effects,
    _single_command_effects,
    _staff_has_note_access,
    _structured_assessment_effects,
    _summarize_effects,
    _vitals_effects,
)


def _make_api(
    api_cls: Any,
    *,
    headers: dict[str, str] | None = None,
    secrets: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
    json_body: Any = None,
    json_raises: bool = False,
) -> Any:
    """Build an API instance bypassing the SDK's request-bound __init__."""
    instance = api_cls.__new__(api_cls)
    request = MagicMock()
    request.headers = headers or {}
    request.query_params = query_params or {}
    if json_raises:
        request.json.side_effect = ValueError("bad json")
    else:
        request.json.return_value = json_body
    instance.request = request
    instance.secrets = secrets or {}
    return instance


@pytest.fixture(autouse=True)
def _bypass_note_access_check() -> Iterator[None]:
    """The save endpoint's ownership gate rejects any note_uuid that doesn't
    resolve to a real, patient-attached Note. Existing tests pass placeholder
    note ids (`note-1`, etc.) that wouldn't pass the check; auto-stub the
    helper so tests stay focused on their actual subject. Tests that need to
    exercise the rejection path override this with their own
    `_staff_has_note_access` patch."""
    with patch(
        "nutrition_charting.api.nutrition_api._staff_has_note_access",
        return_value=True,
    ):
        yield


# ============================================================================
# Authentication
# ============================================================================
#
# NutritionChartingAPI uses the SDK's StaffSessionAuthMixin instead of a manual
# `authenticate()` method, so we just verify the composition + the mixin's
# behavior on the class. The mixin reads `credentials.logged_in_user["type"]`
# and raises InvalidCredentialsError for non-staff.

def test_charting_api_uses_staff_session_mixin() -> None:
    """The API delegates auth to the SDK's StaffSessionAuthMixin so we get
    the SDK's edge-case handling (None checks, etc.) for free."""
    assert StaffSessionAuthMixin in NutritionChartingAPI.__mro__


def test_charting_api_authenticate_accepts_staff_session() -> None:
    api_inst = _make_api(NutritionChartingAPI)
    creds = MagicMock()
    creds.logged_in_user = {"type": "Staff", "id": "u1"}

    assert api_inst.authenticate(creds) is True


def test_charting_api_authenticate_rejects_patient_session() -> None:
    api_inst = _make_api(NutritionChartingAPI)
    creds = MagicMock()
    creds.logged_in_user = {"type": "Patient"}

    with pytest.raises(InvalidCredentialsError):
        api_inst.authenticate(creds)


# ---- PrintNutritionNoteAPI hybrid auth -------------------------------------

@patch("nutrition_charting.api.nutrition_api.SessionCredentials")
def test_print_api_accepts_staff_session(mock_creds_cls: MagicMock) -> None:
    mock_creds_cls.return_value.logged_in_user = {"type": "Staff"}
    api_inst = _make_api(PrintNutritionNoteAPI)

    assert api_inst.authenticate(MagicMock()) is True


@patch("nutrition_charting.api.nutrition_api.SessionCredentials")
def test_print_api_accepts_correct_api_key(mock_creds_cls: MagicMock) -> None:
    mock_creds_cls.side_effect = InvalidCredentialsError()
    api_inst = _make_api(
        PrintNutritionNoteAPI,
        headers={"Authorization": "secret-key-123"},
        secrets={"simple-api-key": "secret-key-123"},
    )

    assert api_inst.authenticate(MagicMock()) is True


@patch("nutrition_charting.api.nutrition_api.SessionCredentials")
def test_print_api_rejects_wrong_api_key(mock_creds_cls: MagicMock) -> None:
    mock_creds_cls.side_effect = InvalidCredentialsError()
    api_inst = _make_api(
        PrintNutritionNoteAPI,
        headers={"Authorization": "bad-key"},
        secrets={"simple-api-key": "secret-key-123"},
    )

    assert api_inst.authenticate(MagicMock()) is False


@patch("nutrition_charting.api.nutrition_api.SessionCredentials")
def test_print_api_rejects_when_no_creds_and_no_key(mock_creds_cls: MagicMock) -> None:
    mock_creds_cls.side_effect = InvalidCredentialsError()
    api_inst = _make_api(PrintNutritionNoteAPI)

    assert api_inst.authenticate(MagicMock()) is False


@patch("nutrition_charting.api.nutrition_api.compare_digest")
@patch("nutrition_charting.api.nutrition_api.SessionCredentials")
def test_print_api_uses_compare_digest_for_constant_time_compare(
    mock_creds_cls: MagicMock, mock_compare: MagicMock,
) -> None:
    """Mitigates the timing-attack class flagged in security review.
    A plain `==` would be visible in the call graph; this proves we route
    through hmac.compare_digest instead."""
    mock_creds_cls.side_effect = InvalidCredentialsError()
    mock_compare.return_value = True
    api_inst = _make_api(
        PrintNutritionNoteAPI,
        headers={"Authorization": "any-key"},
        secrets={"simple-api-key": "real-secret"},
    )

    assert api_inst.authenticate(MagicMock()) is True
    mock_compare.assert_called_once_with(b"real-secret", b"any-key")


@patch("nutrition_charting.api.nutrition_api.log")
@patch("nutrition_charting.api.nutrition_api.SessionCredentials")
def test_print_api_logs_warning_on_missing_credentials(
    mock_creds_cls: MagicMock, mock_log: MagicMock,
) -> None:
    """Auth-failure paths emit a log.warning so a security monitor can
    spot brute-force / scan attempts on the print endpoint."""
    mock_creds_cls.side_effect = InvalidCredentialsError()
    api_inst = _make_api(PrintNutritionNoteAPI, headers={}, secrets={})

    assert api_inst.authenticate(MagicMock()) is False
    mock_log.warning.assert_called_once()


@patch("nutrition_charting.api.nutrition_api.log")
@patch("nutrition_charting.api.nutrition_api.SessionCredentials")
def test_print_api_logs_warning_on_api_key_mismatch(
    mock_creds_cls: MagicMock, mock_log: MagicMock,
) -> None:
    mock_creds_cls.side_effect = InvalidCredentialsError()
    api_inst = _make_api(
        PrintNutritionNoteAPI,
        headers={"Authorization": "wrong"},
        secrets={"simple-api-key": "right"},
    )

    assert api_inst.authenticate(MagicMock()) is False
    mock_log.warning.assert_called_once()
    assert "did not match" in mock_log.warning.call_args.args[0]


# Phase 1 hardening (Risk #4): both hybrid-auth branches must lead to a
# successful index() render. The earlier tests cover authenticate() in
# isolation; this pair locks in that nothing between authenticate() and
# index() (e.g. a future middleware) silently breaks one branch.

@patch("nutrition_charting.api.nutrition_api.build_print_payload")
@patch("nutrition_charting.api.nutrition_api.SessionCredentials")
def test_print_api_staff_session_branch_renders_index(
    mock_creds_cls: MagicMock, mock_build: MagicMock,
) -> None:
    mock_creds_cls.return_value.logged_in_user = {"type": "Staff"}
    mock_build.return_value = {
        "patient": {"full_name": "Test Patient"},
        "note": {"note_type_name": "Nutrition Initial", "provider_name": "Test Provider"},
        "visit_type": "initial",
        "chart": {"missing": True}, "anthropometrics": {},
        "questionnaires": {}, "estimated_requirements": {},
        "intervention": {}, "monitoring": {},
        "coordination": {"monitor_team_meeting": {"checked": False}},
    }
    api_inst = _make_api(
        PrintNutritionNoteAPI,
        query_params={"patient_id": "pat-1", "note_id": "note-1"},
    )

    assert api_inst.authenticate(MagicMock()) is True
    responses = api_inst.index()
    assert responses[0].status_code == HTTPStatus.OK
    body = responses[0].content
    body = body.decode() if isinstance(body, bytes) else body
    assert "Test Patient" in body


@patch("nutrition_charting.api.nutrition_api.build_print_payload")
@patch("nutrition_charting.api.nutrition_api.SessionCredentials")
def test_print_api_api_key_branch_renders_index(
    mock_creds_cls: MagicMock, mock_build: MagicMock,
) -> None:
    mock_creds_cls.side_effect = InvalidCredentialsError()
    mock_build.return_value = {
        "patient": {"full_name": "Test Patient"},
        "note": {"note_type_name": "Nutrition Initial", "provider_name": "Test Provider"},
        "visit_type": "initial",
        "chart": {"missing": True}, "anthropometrics": {},
        "questionnaires": {}, "estimated_requirements": {},
        "intervention": {}, "monitoring": {},
        "coordination": {"monitor_team_meeting": {"checked": False}},
    }
    api_inst = _make_api(
        PrintNutritionNoteAPI,
        headers={"Authorization": "secret-key-123"},
        secrets={"simple-api-key": "secret-key-123"},
        query_params={"patient_id": "pat-1", "note_id": "note-1"},
    )

    assert api_inst.authenticate(MagicMock()) is True
    responses = api_inst.index()
    assert responses[0].status_code == HTTPStatus.OK
    body = responses[0].content
    body = body.decode() if isinstance(body, bytes) else body
    assert "Test Patient" in body


# ============================================================================
# Phase B: auto-populate
# ============================================================================

@patch("nutrition_charting.api.nutrition_api.build_chart_review")
def test_auto_populate_returns_chart_payload(mock_build: MagicMock) -> None:
    mock_build.return_value = {"missing": False, "age": 36, "sex": "F"}
    api_inst = _make_api(NutritionChartingAPI, query_params={"patient_id": "pat-1"})

    responses = api_inst.auto_populate()

    mock_build.assert_called_once_with("pat-1", cache={})
    body = json.loads(responses[0].content)
    assert body["success"] is True
    assert body["data"]["age"] == 36


@patch("nutrition_charting.api.nutrition_api.build_chart_review")
def test_auto_populate_returns_500_on_chart_extraction_failure(mock_build: MagicMock) -> None:
    # `auto_populate` only catches `DatabaseError` (everything else
    # propagates so Sentry sees it). Simulate a transient ORM error.
    mock_build.side_effect = DatabaseError("DB went away")
    api_inst = _make_api(NutritionChartingAPI, query_params={"patient_id": "pat-1"})

    responses = api_inst.auto_populate()

    assert responses[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    body = json.loads(responses[0].content)
    assert body["success"] is False
    assert body["error"] == "auto_populate_failed"


@patch("nutrition_charting.api.nutrition_api.build_chart_review")
def test_auto_populate_propagates_non_db_errors_to_sentry(mock_build: MagicMock) -> None:
    """Bugs (AttributeError after a refactor, etc.) must NOT be swallowed by
    the handler — they need to bubble up to the SimpleAPI framework so the
    logging integration captures them in Sentry. Locks in the narrowed
    catch from the broad-except cleanup."""
    mock_build.side_effect = AttributeError("renamed field")
    api_inst = _make_api(NutritionChartingAPI, query_params={"patient_id": "pat-1"})

    with pytest.raises(AttributeError):
        api_inst.auto_populate()


# ============================================================================
# Phase B: form-state
# ============================================================================

@patch("nutrition_charting.api.nutrition_api._get_form_state")
def test_get_form_state_returns_persistence_payload(mock_get: MagicMock) -> None:
    mock_get.return_value = {
        "sections": {"medical_chart_review": {"height": "67"}},
        "visit_type": "initial",
    }
    api_inst = _make_api(NutritionChartingAPI, query_params={"note_id": "note-1"})

    responses = api_inst.get_form_state()

    mock_get.assert_called_once_with("note-1")
    body = json.loads(responses[0].content)
    assert body == {
        "success": True,
        "sections": {"medical_chart_review": {"height": "67"}},
        "visit_type": "initial",
    }


# ============================================================================
# Phase 4.5: refer-search typeahead
# ============================================================================

def _mock_provider(
    *, id_: str, first: str, last: str, specialty: str, practice: str,
    label: str | None = None,
) -> MagicMock:
    p = MagicMock()
    p.id = id_
    p.first_name = first
    p.last_name = last
    p.specialty = specialty
    p.practice_name = practice
    p.full_name_and_specialty = label or f"{first} {last} ({practice}), {specialty}"
    return p


@patch("nutrition_charting.api.nutrition_api.ServiceProviderRecord")
def test_refer_search_returns_results_for_matching_query(
    mock_record_cls: MagicMock,
) -> None:
    qs_chain = (
        mock_record_cls.objects.filter.return_value.order_by.return_value
    )
    qs_chain.__getitem__.return_value = [
        _mock_provider(
            id_="sp-1", first="Sarah", last="Cohen",
            specialty="Cardiology", practice="Heart Center",
        ),
    ]
    api_inst = _make_api(NutritionChartingAPI, query_params={"q": "coh"})

    responses = api_inst.refer_search()

    body = json.loads(responses[0].content)
    assert body["success"] is True
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["id"] == "sp-1"
    assert result["last_name"] == "Cohen"
    assert result["specialty"] == "Cardiology"
    assert result["practice_name"] == "Heart Center"
    assert "label" in result


@patch("nutrition_charting.api.nutrition_api.ServiceProviderRecord")
def test_refer_search_short_query_skips_db_hit(
    mock_record_cls: MagicMock,
) -> None:
    """A 0/1-char query is too noisy to be useful and would scan the
    whole directory — skip it client-side AND server-side."""
    api_inst = _make_api(NutritionChartingAPI, query_params={"q": "a"})

    responses = api_inst.refer_search()

    body = json.loads(responses[0].content)
    assert body == {"success": True, "results": []}
    mock_record_cls.objects.filter.assert_not_called()


@patch("nutrition_charting.api.nutrition_api.ServiceProviderRecord")
def test_refer_search_returns_empty_results_on_miss(
    mock_record_cls: MagicMock,
) -> None:
    qs_chain = (
        mock_record_cls.objects.filter.return_value.order_by.return_value
    )
    qs_chain.__getitem__.return_value = []
    api_inst = _make_api(NutritionChartingAPI, query_params={"q": "zzzz"})

    responses = api_inst.refer_search()

    body = json.loads(responses[0].content)
    assert body == {"success": True, "results": []}


# ============================================================================
# Phase B: save section
# ============================================================================

@patch("nutrition_charting.api.nutrition_api._save_section")
def test_save_section_persists_section_and_returns_success(
    mock_save_section: MagicMock,
) -> None:
    api_inst = _make_api(
        NutritionChartingAPI,
        query_params={"section": "dietary_intake", "note_id": "note-1"},
        json_body={"breakfast": "eggs"},
    )

    responses = api_inst.save_section()

    # save_section now takes visit_type as a kwarg so both writes share one
    # AttributeHub fetch; the test passes no visit_type so kwarg is None.
    mock_save_section.assert_called_once_with(
        "note-1", "dietary_intake", {"breakfast": "eggs"}, visit_type=None,
    )
    body = json.loads(responses[0].content)
    assert body["success"] is True
    assert body["section"] == "dietary_intake"
    # No commands emitted for the bare dietary_intake save in this test (the
    # questionnaire path is mocked out elsewhere) so all effect counts are 0.
    assert body["effects"] == {"originate": 0, "edit": 0, "delete": 0}
    assert len(responses) == 1  # No VitalsCommand for non-medical-chart-review sections


@patch("nutrition_charting.api.nutrition_api._save_section")
def test_save_section_passes_visit_type_through_to_save_section(
    mock_save_section: MagicMock,
) -> None:
    """visit_type rides on the same `_save_section` call now (was a separate
    `_save_visit_type` call) — saves one redundant AttributeHub fetch."""
    api_inst = _make_api(
        NutritionChartingAPI,
        query_params={"section": "dietary_intake", "note_id": "note-1"},
        json_body={"breakfast": "eggs", "visit_type": "follow_up"},
    )

    api_inst.save_section()

    mock_save_section.assert_called_once_with(
        "note-1", "dietary_intake", {"breakfast": "eggs"},
        visit_type="follow_up",
    )
    # `visit_type` is popped from the section payload before saving.
    saved_args = mock_save_section.call_args
    assert "visit_type" not in saved_args.args[2]


@patch("nutrition_charting.api.nutrition_api._save_section")
def test_save_section_emits_vitals_for_flat_payload(
    mock_save_section: MagicMock,
) -> None:
    """The real front-end posts a flat object — that path must emit Vitals."""
    api_inst = _make_api(
        NutritionChartingAPI,
        query_params={"section": "medical_chart_review", "note_id": "note-uuid-9"},
        json_body={"height": "67", "weight": "165", "bmi": "25.8", "ubw": None, "ibw": None},
    )

    responses = api_inst.save_section()

    assert len(responses) == 2
    body = json.loads(responses[0].content)
    assert body["success"] is True
    assert "note-uuid-9" in responses[1].payload


@patch("nutrition_charting.api.nutrition_api._save_section")
def test_save_section_emits_vitals_for_nested_payload(
    mock_save_section: MagicMock,
) -> None:
    """A nested anthropometrics block also works (future-proofing)."""
    api_inst = _make_api(
        NutritionChartingAPI,
        query_params={"section": "medical_chart_review", "note_id": "note-uuid-9"},
        json_body={"anthropometrics": {"height": "67", "weight": "165"}},
    )

    responses = api_inst.save_section()

    assert len(responses) == 2
    assert "note-uuid-9" in responses[1].payload


@patch("nutrition_charting.api.nutrition_api._save_section")
def test_save_section_skips_vitals_when_no_height_or_weight(
    mock_save_section: MagicMock,
) -> None:
    api_inst = _make_api(
        NutritionChartingAPI,
        query_params={"section": "medical_chart_review", "note_id": "note-uuid-9"},
        json_body={"height": None, "weight": None, "ubw": "150"},
    )

    responses = api_inst.save_section()

    assert len(responses) == 1


def test_save_section_rejects_invalid_json() -> None:
    api_inst = _make_api(
        NutritionChartingAPI,
        query_params={"section": "x", "note_id": "n"},
        json_raises=True,
    )

    responses = api_inst.save_section()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    body = json.loads(responses[0].content)
    assert body["error"] == "invalid_json"


def test_save_section_rejects_non_object_body() -> None:
    api_inst = _make_api(
        NutritionChartingAPI,
        query_params={"section": "x", "note_id": "n"},
        json_body=["not", "an", "object"],
    )

    responses = api_inst.save_section()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST


# ============================================================================
# Defense-in-depth: UUID-shape + note-existence helpers
# ============================================================================

def test_looks_like_uuid_accepts_valid_uuid() -> None:
    assert _looks_like_uuid("12345678-1234-5678-1234-567812345678") is True


def test_looks_like_uuid_rejects_garbage() -> None:
    """The helper is annotated to accept `str` but defends against `None`
    too — exercise that defensive branch via a typing escape hatch."""
    for bad in ("", "note-1", "not-a-uuid", "1234"):
        assert _looks_like_uuid(bad) is False
    # `None` is outside the type signature; cast through Any to confirm
    # the runtime guard still rejects it.
    assert _looks_like_uuid(None) is False  # type: ignore[arg-type]


@patch("nutrition_charting.api.nutrition_api.Note")
def test_staff_has_note_access_true_when_note_and_patient_exist(
    mock_note_cls: MagicMock,
) -> None:
    note = MagicMock()
    note.patient = MagicMock()
    mock_note_cls.objects.select_related.return_value.get.return_value = note
    assert _staff_has_note_access("12345678-1234-5678-1234-567812345678") is True
    mock_note_cls.objects.select_related.assert_called_once_with("patient")
    mock_note_cls.objects.select_related.return_value.get.assert_called_once_with(
        id="12345678-1234-5678-1234-567812345678",
    )


@patch("nutrition_charting.api.nutrition_api.Note")
def test_staff_has_note_access_false_when_note_missing(
    mock_note_cls: MagicMock,
) -> None:
    class _DNE(Exception):
        pass

    mock_note_cls.DoesNotExist = _DNE
    mock_note_cls.objects.select_related.return_value.get.side_effect = _DNE()
    assert _staff_has_note_access("12345678-1234-5678-1234-567812345678") is False


@patch("nutrition_charting.api.nutrition_api.Note")
def test_staff_has_note_access_false_when_note_has_no_patient(
    mock_note_cls: MagicMock,
) -> None:
    """A Note row with patient=None usually means an admin-test or
    stale-import artifact. Treat it as not-accessible so writes can't land
    against a phantom patient."""
    note = MagicMock()
    note.patient = None
    mock_note_cls.objects.select_related.return_value.get.return_value = note
    assert _staff_has_note_access("12345678-1234-5678-1234-567812345678") is False


def test_staff_has_note_access_short_circuits_on_invalid_uuid() -> None:
    """Cheap shape check skips the DB hit entirely for malformed input."""
    assert _staff_has_note_access("not-a-uuid") is False
    assert _staff_has_note_access("") is False


def test_save_section_returns_403_when_no_note_access() -> None:
    """Tampered / stale / patient-less note_ids get the same 403 so the
    response doesn't leak which failure mode tripped the gate."""
    with patch(
        "nutrition_charting.api.nutrition_api._staff_has_note_access",
        return_value=False,
    ):
        api_inst = _make_api(
            NutritionChartingAPI,
            query_params={"section": "goals", "note_id": "not-a-real-uuid"},
            json_body={"rows": []},
        )

        responses = api_inst.save_section()

    assert len(responses) == 1
    assert responses[0].status_code == HTTPStatus.FORBIDDEN
    body = json.loads(responses[0].content)
    assert body["error"] == "access_denied"


def test_save_section_rejects_missing_section_param() -> None:
    api_inst = _make_api(
        NutritionChartingAPI,
        query_params={"note_id": "n"},
        json_body={"some": "data"},
    )

    responses = api_inst.save_section()

    assert responses[0].status_code == HTTPStatus.BAD_REQUEST
    body = json.loads(responses[0].content)
    assert body["error"] == "section_required"


# ============================================================================
# Phase B: helpers
# ============================================================================

def test_coerce_int_rounds_and_handles_blanks() -> None:
    assert _coerce_int("67.4") == 67
    assert _coerce_int("67.6") == 68
    assert _coerce_int(165) == 165
    assert _coerce_int("") is None
    assert _coerce_int(None) is None
    assert _coerce_int("not a number") is None


def test_vitals_effects_skips_when_no_note_uuid() -> None:
    assert _vitals_effects("", {"height": 67}) == []


def test_vitals_effects_skips_when_payload_is_empty_or_unrelated() -> None:
    assert _vitals_effects("note-1", {}) == []
    assert _vitals_effects("note-1", {"ubw": "150", "ibw": "140"}) == []


def test_vitals_effects_skips_when_both_height_and_weight_missing() -> None:
    assert _vitals_effects("note-1", {"height": "", "weight": None}) == []


@patch("nutrition_charting.api.nutrition_api._record_originated_command")
@patch("nutrition_charting.api.nutrition_api._get_originated_command", return_value=None)
def test_vitals_effects_originates_on_first_save(
    mock_get: MagicMock, mock_record: MagicMock,
) -> None:
    effects = _vitals_effects("note-uuid-1", {"height": "67", "weight": "165"})

    assert len(effects) == 1
    assert "note-uuid-1" in effects[0].payload
    # The originated UUID is stashed for the next save to edit instead of duplicate
    mock_record.assert_called_once()
    assert mock_record.call_args.args[0] == "note-uuid-1"
    assert mock_record.call_args.args[1] == "medical_chart_review"
    assert mock_record.call_args.args[2]  # generated UUID is non-empty


@patch("nutrition_charting.api.nutrition_api._record_originated_command")
@patch(
    "nutrition_charting.api.nutrition_api._get_originated_command",
    return_value="cmd-uuid-existing",
)
def test_vitals_effects_edits_existing_command_on_resave(
    mock_get: MagicMock, mock_record: MagicMock,
) -> None:
    effects = _vitals_effects("note-uuid-1", {"height": "67", "weight": "165"})

    # Edits in place — does NOT record a new UUID
    assert len(effects) == 1
    mock_record.assert_not_called()
    assert "cmd-uuid-existing" in effects[0].payload


def test_vitals_effects_handles_nested_payload() -> None:
    with patch(
        "nutrition_charting.api.nutrition_api._get_originated_command",
        return_value=None,
    ), patch("nutrition_charting.api.nutrition_api._record_originated_command"):
        effects = _vitals_effects(
            "note-uuid-1", {"anthropometrics": {"height": "67", "weight": "165"}}
        )
    assert len(effects) == 1
    assert "note-uuid-1" in effects[0].payload


# ============================================================================
# Phase C: StructuredAssessmentCommand emission for questionnaire sections
# ============================================================================

@patch("nutrition_charting.api.nutrition_api.StructuredAssessmentCommand")
@patch("nutrition_charting.api.nutrition_api._record_originated_command")
@patch("nutrition_charting.api.nutrition_api._get_originated_command", return_value=None)
@patch("nutrition_charting.api.nutrition_api.resolve_questionnaire_id",
       return_value="11111111-2222-3333-4444-555555555555")
def test_sa_effects_originates_then_edits_with_responses_on_first_save(
    mock_resolve: MagicMock, mock_get: MagicMock, mock_record: MagicMock,
    mock_cmd_cls: MagicMock,
) -> None:
    cmd_instance = MagicMock()
    cmd_instance.originate.return_value = MagicMock(payload="originate-effect")
    cmd_instance.edit.return_value = MagicMock(payload="edit-effect")
    # 8 questions in social_diet_history
    cmd_instance.questions = [MagicMock() for _ in range(8)]
    mock_cmd_cls.return_value = cmd_instance

    effects = _structured_assessment_effects(
        "note-uuid-1", "social_diet_history",
        {"appetite": "good", "chew_swallow": "intact"},
    )

    # First save emits BOTH originate (creates the row) and edit (applies responses)
    assert len(effects) == 2
    mock_resolve.assert_called_once_with("social_diet_history")
    kwargs = mock_cmd_cls.call_args.kwargs
    assert kwargs["note_uuid"] == "note-uuid-1"
    assert kwargs["questionnaire_id"] == "11111111-2222-3333-4444-555555555555"
    assert "Appetite: good" in kwargs.get("result", "")
    assert "Chew/Swallow: intact" in kwargs.get("result", "")
    cmd_instance.originate.assert_called_once()
    cmd_instance.edit.assert_called_once()
    # Responses were attached to the right questions, in YAML order
    cmd_instance.questions[0].add_response.assert_called_once_with(text="good")
    cmd_instance.questions[1].add_response.assert_called_once_with(text="intact")
    # Empty fields don't produce add_response calls
    cmd_instance.questions[2].add_response.assert_not_called()
    # The originated command_uuid is stashed for the next save to edit in place
    mock_record.assert_called_once()
    assert mock_record.call_args.args[1] == "social_diet_history"


@patch("nutrition_charting.api.nutrition_api.StructuredAssessmentCommand")
@patch("nutrition_charting.api.nutrition_api._record_originated_command")
@patch(
    "nutrition_charting.api.nutrition_api._get_originated_command",
    return_value="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
)
@patch("nutrition_charting.api.nutrition_api.resolve_questionnaire_id",
       return_value="11111111-2222-3333-4444-555555555555")
def test_sa_effects_edits_in_place_on_resave(
    mock_resolve: MagicMock, mock_get: MagicMock, mock_record: MagicMock,
    mock_cmd_cls: MagicMock,
) -> None:
    cmd_instance = MagicMock()
    cmd_instance.edit.return_value = MagicMock(payload="edit-effect")
    cmd_instance.questions = [MagicMock() for _ in range(8)]
    mock_cmd_cls.return_value = cmd_instance

    effects = _structured_assessment_effects(
        "note-uuid-1", "social_diet_history", {"appetite": "fair"},
    )

    # Resave: edit only — no duplicate originate
    assert len(effects) == 1
    mock_record.assert_not_called()
    kwargs = mock_cmd_cls.call_args.kwargs
    assert kwargs["command_uuid"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    cmd_instance.edit.assert_called_once()
    cmd_instance.originate.assert_not_called()
    cmd_instance.questions[0].add_response.assert_called_once_with(text="fair")


@patch("nutrition_charting.api.nutrition_api.resolve_questionnaire_id",
       return_value=None)
def test_sa_effects_skips_when_questionnaire_not_registered(
    mock_resolve: MagicMock,
) -> None:
    effects = _structured_assessment_effects(
        "note-uuid-1", "social_diet_history", {"appetite": "good"},
    )
    assert effects == []


def test_sa_effects_skips_for_non_questionnaire_section() -> None:
    effects = _structured_assessment_effects(
        "note-uuid-1", "medical_chart_review", {"height": "67"},
    )
    assert effects == []


def test_sa_effects_skips_when_no_note_uuid() -> None:
    effects = _structured_assessment_effects(
        "", "social_diet_history", {"appetite": "good"},
    )
    assert effects == []


@patch("nutrition_charting.api.nutrition_api.StructuredAssessmentCommand")
@patch("nutrition_charting.api.nutrition_api._save_section")
@patch("nutrition_charting.api.nutrition_api._record_originated_command")
@patch("nutrition_charting.api.nutrition_api._get_originated_command", return_value=None)
@patch("nutrition_charting.api.nutrition_api.resolve_questionnaire_id",
       return_value="22222222-3333-4444-5555-666666666666")
def test_save_section_emits_sa_for_pes(
    mock_resolve: MagicMock, mock_get: MagicMock, mock_record: MagicMock,
    mock_save_section: MagicMock,
    mock_cmd_cls: MagicMock,
) -> None:
    cmd_instance = MagicMock()
    cmd_instance.originate.return_value = MagicMock(payload="originate-effect")
    cmd_instance.edit.return_value = MagicMock(payload="edit-effect")
    cmd_instance.questions = [MagicMock() for _ in range(3)]  # PES has 3 questions
    mock_cmd_cls.return_value = cmd_instance

    api_inst = _make_api(
        NutritionChartingAPI,
        query_params={"section": "nutrition_diagnosis_pes", "note_id": "note-1"},
        json_body={
            "problem": "Inadequate energy intake",
            "etiology": "Limited access",
            "signs_symptoms": "5 lb wt loss",
        },
    )

    responses = api_inst.save_section()

    # JSON ack + originate + edit (with responses)
    assert len(responses) == 3
    body = json.loads(responses[0].content)
    assert body["success"] is True
    assert body["section"] == "nutrition_diagnosis_pes"
    # The mocked StructuredAssessmentCommand returns MagicMock effects whose
    # `.type` doesn't resolve via EffectType.Name — that's fine; the counts
    # just stay at zero. The real type-name lookup is exercised elsewhere.
    assert body["effects"] == {"originate": 0, "edit": 0, "delete": 0}
    mock_save_section.assert_called_once()
    kwargs = mock_cmd_cls.call_args.kwargs
    assert kwargs["questionnaire_id"] == "22222222-3333-4444-5555-666666666666"
    assert "Problem: Inadequate energy intake" in kwargs.get("result", "")
    cmd_instance.originate.assert_called_once()
    cmd_instance.edit.assert_called_once()
    cmd_instance.questions[0].add_response.assert_called_once_with(text="Inadequate energy intake")
    cmd_instance.questions[1].add_response.assert_called_once_with(text="Limited access")
    cmd_instance.questions[2].add_response.assert_called_once_with(text="5 lb wt loss")


# ============================================================================
# Print API stub (still Phase A)
# ============================================================================

# ============================================================================
# Phase D pass 2: single-command delete-on-clear (Task gating)
# ============================================================================

@patch("nutrition_charting.api.nutrition_api._clear_originated_command")
@patch("nutrition_charting.api.nutrition_api._get_originated_command",
       return_value="task-uuid-existing")
def test_single_command_effects_deletes_when_no_longer_emit_ready(
    mock_get: MagicMock, mock_clear: MagicMock,
) -> None:
    """Dietician unchecks 'Monitor at team meeting' after a previous save —
    the previously-emitted Task command must be deleted so the note doesn't
    keep stale data."""
    effects = _single_command_effects(
        "note-uuid-1", "monitor_team_meeting", {"monitor": False},
    )

    assert len(effects) == 1
    assert "task-uuid-existing" in effects[0].payload
    assert _effect_name(effects[0]) == "DELETE_TASK_COMMAND"
    mock_clear.assert_called_once_with("note-uuid-1", "monitor_team_meeting")


@patch("nutrition_charting.api.nutrition_api._clear_originated_command")
@patch("nutrition_charting.api.nutrition_api._get_originated_command",
       return_value=None)
def test_single_command_effects_skips_clear_when_never_originated(
    mock_get: MagicMock, mock_clear: MagicMock,
) -> None:
    effects = _single_command_effects(
        "note-uuid-1", "monitor_team_meeting", {"monitor": False},
    )
    assert effects == []
    mock_clear.assert_not_called()


@patch("nutrition_charting.api.nutrition_api._record_originated_command")
@patch("nutrition_charting.api.nutrition_api._get_originated_command",
       return_value=None)
def test_single_command_effects_originates_task_when_checkbox_checked(
    mock_get: MagicMock, mock_record: MagicMock,
) -> None:
    effects = _single_command_effects(
        "note-uuid-1", "monitor_team_meeting",
        {"monitor": True, "comment": "discuss labs"},
    )
    assert len(effects) == 1
    assert _effect_name(effects[0]) == "ORIGINATE_TASK_COMMAND"
    assert "discuss labs" in effects[0].payload
    mock_record.assert_called_once()


# ============================================================================
# Phase D pass 2: multi-command effects (Goals / Educational Materials / Refer)
# ============================================================================

@patch("nutrition_charting.api.nutrition_api._save_multi_command_map")
@patch("nutrition_charting.api.nutrition_api._get_multi_command_map", return_value={})
def test_multi_command_effects_originates_each_new_row(
    mock_get_map: MagicMock, mock_save_map: MagicMock,
) -> None:
    effects = _multi_command_effects(
        "note-uuid-1",
        "goals",
        {"rows": [
            {"row_id": "goal:row-a", "goal_statement": "Drink 64oz water/day"},
            {"row_id": "goal:row-b", "goal_statement": "Walk 30 min/day"},
        ]},
    )

    assert len(effects) == 2
    types = sorted(_effect_name(eff) for eff in effects)
    assert types == ["ORIGINATE_GOAL_COMMAND", "ORIGINATE_GOAL_COMMAND"]

    saved_map = mock_save_map.call_args.args[2]
    # Each row got a fresh command_uuid stashed under its row_id
    assert set(saved_map.keys()) == {"goal:row-a", "goal:row-b"}
    assert all(saved_map.values())
    assert len(set(saved_map.values())) == 2  # distinct uuids


@patch("nutrition_charting.api.nutrition_api._save_multi_command_map")
@patch(
    "nutrition_charting.api.nutrition_api._get_multi_command_map",
    return_value={"goal:row-a": "cmd-uuid-existing-a"},
)
def test_multi_command_effects_edits_existing_row_in_place(
    mock_get_map: MagicMock, mock_save_map: MagicMock,
) -> None:
    effects = _multi_command_effects(
        "note-uuid-1",
        "goals",
        {"rows": [
            {"row_id": "goal:row-a", "goal_statement": "Drink 80oz water/day"},
        ]},
    )

    assert len(effects) == 1
    assert _effect_name(effects[0]) == "EDIT_GOAL_COMMAND"
    assert "cmd-uuid-existing-a" in effects[0].payload
    saved_map = mock_save_map.call_args.args[2]
    assert saved_map == {"goal:row-a": "cmd-uuid-existing-a"}


@patch("nutrition_charting.api.nutrition_api._save_multi_command_map")
@patch(
    "nutrition_charting.api.nutrition_api._get_multi_command_map",
    return_value={
        "goal:row-a": "cmd-uuid-a",
        "goal:row-b": "cmd-uuid-b",
    },
)
def test_multi_command_effects_deletes_rows_removed_from_payload(
    mock_get_map: MagicMock, mock_save_map: MagicMock,
) -> None:
    """Row B was previously saved; user removed it before resaving. The
    server must emit a delete for the orphaned command and drop it from the
    map."""
    effects = _multi_command_effects(
        "note-uuid-1",
        "goals",
        {"rows": [
            {"row_id": "goal:row-a", "goal_statement": "still here"},
        ]},
    )

    types = [_effect_name(eff) for eff in effects]
    assert "EDIT_GOAL_COMMAND" in types
    assert "DELETE_GOAL_COMMAND" in types
    delete_payloads = [
        eff.payload for eff in effects if _effect_name(eff) == "DELETE_GOAL_COMMAND"
    ]
    assert any("cmd-uuid-b" in p for p in delete_payloads)
    saved_map = mock_save_map.call_args.args[2]
    assert "goal:row-b" not in saved_map


@patch("nutrition_charting.api.nutrition_api._save_multi_command_map")
@patch(
    "nutrition_charting.api.nutrition_api._get_multi_command_map",
    return_value={"goal:row-a": "cmd-uuid-a"},
)
def test_multi_command_effects_deletes_row_when_text_cleared(
    mock_get_map: MagicMock, mock_save_map: MagicMock,
) -> None:
    """If the user blanks a previously-saved goal's text without removing
    the row, treat it as a delete (the command shouldn't have empty text)."""
    effects = _multi_command_effects(
        "note-uuid-1",
        "goals",
        {"rows": [{"row_id": "goal:row-a", "goal_statement": "  "}]},
    )

    assert len(effects) == 1
    assert _effect_name(effects[0]) == "DELETE_GOAL_COMMAND"
    saved_map = mock_save_map.call_args.args[2]
    assert "goal:row-a" not in saved_map


@patch("nutrition_charting.api.nutrition_api._save_multi_command_map")
@patch("nutrition_charting.api.nutrition_api._get_multi_command_map", return_value={})
def test_multi_command_effects_skips_blank_new_rows(
    mock_get_map: MagicMock, mock_save_map: MagicMock,
) -> None:
    """Empty rows the user added but never filled in shouldn't originate
    anything."""
    effects = _multi_command_effects(
        "note-uuid-1",
        "goals",
        {"rows": [
            {"row_id": "goal:row-new", "goal_statement": ""},
        ]},
    )

    assert effects == []
    mock_save_map.assert_called_once_with("note-uuid-1", "goals", {})


@patch("nutrition_charting.api.nutrition_api._save_multi_command_map")
@patch("nutrition_charting.api.nutrition_api._get_multi_command_map", return_value={})
def test_multi_command_effects_handles_educational_materials_canonical_rows(
    mock_get_map: MagicMock, mock_save_map: MagicMock,
) -> None:
    """The canonical-checklist front-end posts rows with stable
    `material:<key>` row_ids. We originate one Instruct per checked option."""
    effects = _multi_command_effects(
        "note-uuid-1",
        "educational_materials",
        {"rows": [
            {"row_id": "material:dash_diet", "name": "DASH diet"},
            {"row_id": "material:mediterranean", "name": "Mediterranean diet"},
        ]},
    )

    assert len(effects) == 2
    assert all(_effect_name(eff) == "ORIGINATE_INSTRUCT_COMMAND" for eff in effects)
    saved_map = mock_save_map.call_args.args[2]
    assert set(saved_map.keys()) == {"material:dash_diet", "material:mediterranean"}


def test_multi_command_effects_skips_unknown_section() -> None:
    assert _multi_command_effects("note-1", "not_a_section", {"rows": []}) == []


def test_multi_command_effects_skips_when_no_note_uuid() -> None:
    assert _multi_command_effects("", "goals", {"rows": []}) == []


@patch("nutrition_charting.api.nutrition_api._save_multi_command_map")
@patch("nutrition_charting.api.nutrition_api._get_multi_command_map", return_value={})
def test_multi_command_effects_drops_rows_without_row_id(
    mock_get_map: MagicMock, mock_save_map: MagicMock,
) -> None:
    """Defensive: malformed rows missing `row_id` are ignored, not crashed on."""
    effects = _multi_command_effects(
        "note-uuid-1",
        "goals",
        {"rows": [
            {"goal_statement": "no row_id"},
            {"row_id": "", "goal_statement": "blank row_id"},
            {"row_id": "goal:ok", "goal_statement": "valid"},
        ]},
    )
    assert len(effects) == 1
    assert _effect_name(effects[0]) == "ORIGINATE_GOAL_COMMAND"


# ============================================================================
# Phase D pass 2: save_section dispatches multi-command sections
# ============================================================================

@patch("nutrition_charting.api.nutrition_api._save_multi_command_map")
@patch("nutrition_charting.api.nutrition_api._get_multi_command_map", return_value={})
@patch("nutrition_charting.api.nutrition_api._save_section")
def test_save_section_dispatches_multi_command(
    mock_save_section: MagicMock,
    mock_get_map: MagicMock, mock_save_map: MagicMock,
) -> None:
    api_inst = _make_api(
        NutritionChartingAPI,
        query_params={"section": "goals", "note_id": "note-uuid-1"},
        json_body={"rows": [
            {"row_id": "goal:abc", "goal_statement": "Walk 30 min/day"},
        ]},
    )

    responses = api_inst.save_section()

    # JSON ack + originate effect
    assert len(responses) == 2
    assert _effect_name(responses[1]) == "ORIGINATE_GOAL_COMMAND"
    body = json.loads(responses[0].content)
    assert body["success"] is True
    assert body["section"] == "goals"
    # Real GoalCommand.originate() effect — _summarize_effects buckets it as
    # an originate, no deletes. So no refresh affordance is shown.
    assert body["effects"] == {"originate": 1, "edit": 0, "delete": 0}


# ============================================================================
# Phase D pass 2 follow-up: effects summary in save ack
# ============================================================================

def test_summarize_effects_buckets_by_lifecycle() -> None:
    """Real Goal command lifecycle effects bucket correctly."""
    from canvas_sdk.commands import GoalCommand

    cmd = GoalCommand(note_uuid="n-1", command_uuid="g-1", goal_statement="x")
    effects = [cmd.originate(), cmd.edit(), GoalCommand(command_uuid="g-2").delete()]

    assert _summarize_effects(effects) == {"originate": 1, "edit": 1, "delete": 1}


def test_summarize_effects_returns_zeros_for_empty_list() -> None:
    assert _summarize_effects([]) == {"originate": 0, "edit": 0, "delete": 0}


def test_summarize_effects_skips_unrecognized_types() -> None:
    """A MagicMock effect whose `.type` doesn't resolve via EffectType.Name
    must not crash — counts stay at zero."""
    bogus = MagicMock()
    bogus.type = -999  # not a valid EffectType
    assert _summarize_effects([bogus]) == {"originate": 0, "edit": 0, "delete": 0}


@patch("nutrition_charting.api.nutrition_api._save_multi_command_map")
@patch(
    "nutrition_charting.api.nutrition_api._get_multi_command_map",
    return_value={"goal:row-a": "cmd-uuid-a"},
)
@patch("nutrition_charting.api.nutrition_api._save_section")
def test_save_section_ack_reports_delete_count_for_destructive_save(
    mock_save_section: MagicMock,
    mock_get_map: MagicMock, mock_save_map: MagicMock,
) -> None:
    """When the dietician removes a previously-saved goal row, the ack body
    must include `effects.delete >= 1` so the front-end un-hides the
    "↻ Refresh to see changes" affordance."""
    api_inst = _make_api(
        NutritionChartingAPI,
        query_params={"section": "goals", "note_id": "note-uuid-1"},
        json_body={"rows": []},  # row-a was previously saved; now removed
    )

    responses = api_inst.save_section()

    body = json.loads(responses[0].content)
    assert body["effects"]["delete"] == 1
    assert body["effects"]["originate"] == 0


@patch("nutrition_charting.api.nutrition_api.build_print_payload")
def test_print_api_index_renders_full_template(mock_build: MagicMock) -> None:
    """Phase E: the print API delegates to build_print_payload + render_print_html
    and returns a 200 with the assembled HTML."""
    mock_build.return_value = {
        "patient": {"full_name": "Test Patient", "age": 42, "sex_at_birth": "F"},
        "note": {"note_type_name": "Nutrition Initial", "provider_name": "Test Provider"},
        "visit_type": "initial",
        "chart": {"missing": True},
        "anthropometrics": {},
        "questionnaires": {},
        "estimated_requirements": {},
        "intervention": {"educational_materials": ["DASH diet"]},
        "monitoring": {"goals": ["Drink 64oz water/day"]},
        "coordination": {"recommended_labs": [], "monitor_team_meeting": {"checked": False}},
    }
    api_inst = _make_api(
        PrintNutritionNoteAPI,
        query_params={"patient_id": "pat-7", "note_id": "note-9"},
        secrets={
            "practice-name": "Test Practice",
            "practice-address": "123 Main St",
            "practice-phone": "555-1212",
            "practice-fax": "555-3434",
        },
    )

    responses = api_inst.index()

    mock_build.assert_called_once_with("note-9", "pat-7")
    raw = responses[0].content
    body = raw.decode() if isinstance(raw, bytes) else raw
    # Home-app print chrome + populated content cards
    assert "Test Patient" in body
    assert "Test Provider" in body
    assert "Drink 64oz water/day" in body
    assert "DASH diet" in body
    # Auto-print on load + print stylesheet
    assert "window.print()" in body
    assert "@media print" in body
    # Practice info from secrets reaches the rendered HTML
    assert "Test Practice" in body
    assert "123 Main St" in body
    assert "555-1212" in body
    assert "555-3434" in body


@patch("nutrition_charting.api.nutrition_api.build_print_payload")
def test_print_api_index_renders_without_practice_secrets(mock_build: MagicMock) -> None:
    """Customers who haven't configured the practice-* secrets yet still
    get a usable print — the practice block degrades cleanly."""
    mock_build.return_value = {
        "patient": {"full_name": "Test Patient"},
        "note": {"note_type_name": "Nutrition Initial", "provider_name": "Test Provider"},
        "visit_type": "initial",
        "chart": {"missing": True}, "anthropometrics": {},
        "questionnaires": {}, "estimated_requirements": {},
        "intervention": {}, "monitoring": {},
        "coordination": {"monitor_team_meeting": {"checked": False}},
    }
    api_inst = _make_api(
        PrintNutritionNoteAPI,
        query_params={"patient_id": "pat-7", "note_id": "note-9"},
        secrets={},
    )

    responses = api_inst.index()

    raw = responses[0].content
    body = raw.decode() if isinstance(raw, bytes) else raw
    # No "None" values surface because of unset secrets.
    assert "None" not in body.split("<title>")[0]
    assert ">None<" not in body


@patch("nutrition_charting.api.nutrition_api.build_print_payload")
def test_print_api_index_returns_500_on_payload_failure(mock_build: MagicMock) -> None:
    """On a transient DB error during payload assembly, the API returns a 500
    with a fallback HTML error page rather than an opaque blank modal. Real
    bugs (AttributeError etc.) propagate so they reach Sentry — see
    `test_print_api_index_propagates_non_db_errors_to_sentry`."""
    mock_build.side_effect = DatabaseError("DB blew up")
    api_inst = _make_api(
        PrintNutritionNoteAPI,
        query_params={"patient_id": "pat-7", "note_id": "bad"},
    )

    responses = api_inst.index()

    assert responses[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    raw = responses[0].content
    body = raw.decode() if isinstance(raw, bytes) else raw
    assert "render failed" in body


@patch("nutrition_charting.api.nutrition_api.build_print_payload")
def test_print_api_index_propagates_non_db_errors_to_sentry(mock_build: MagicMock) -> None:
    mock_build.side_effect = AttributeError("renamed field")
    api_inst = _make_api(
        PrintNutritionNoteAPI,
        query_params={"patient_id": "pat-7", "note_id": "bad"},
    )

    with pytest.raises(AttributeError):
        api_inst.index()
