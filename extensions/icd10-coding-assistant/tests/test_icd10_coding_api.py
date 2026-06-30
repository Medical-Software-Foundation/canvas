"""Tests for ICD10CodingAPI endpoints and helper methods."""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.effects.simple_api import JSONResponse
from icd10_coding_assistant.api.icd10_coding_api import ICD10CodingAPI


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class DummyEvent:
    """Minimal event with dict context so SimpleAPI.__init__ can read context['method']."""

    def __init__(self) -> None:
        self.context: dict[str, object] = {
            "method": "GET",
            "path": "/api/conditions-missing-icd10",
        }


@pytest.fixture
def mock_request() -> MagicMock:
    request = MagicMock()
    request.query_params = {}
    request.headers = {"canvas-logged-in-user-id": "provider-xyz"}
    return request


@pytest.fixture
def api_instance(mock_request: MagicMock) -> ICD10CodingAPI:
    api = ICD10CodingAPI(DummyEvent())
    api.request = mock_request
    return api


@pytest.fixture
def mock_condition_with_codings() -> MagicMock:
    condition = MagicMock()
    condition.id = str(uuid.uuid4())
    condition.dbid = 77

    coding = MagicMock()
    coding.system = "http://snomed.info/sct"
    coding.code = "73211009"
    coding.display = "Diabetes mellitus"

    condition.codings.all.return_value = [coding]
    return condition


# ---------------------------------------------------------------------------
# GET /api/conditions-missing-icd10
# ---------------------------------------------------------------------------


def test_get_conditions_returns_400_when_no_patient_id(
    api_instance: ICD10CodingAPI,
) -> None:
    api_instance.request.query_params = {}
    result = api_instance.get_conditions()
    assert len(result) == 1
    assert result[0].status_code == 400
    body = json.loads(result[0].content.decode())
    assert "patient_id parameter required" in body["error"]


def test_get_conditions_returns_conditions_list(
    api_instance: ICD10CodingAPI,
    mock_condition_with_codings: MagicMock,
) -> None:
    api_instance.request.query_params = {"patient_id": "patient-abc"}

    with patch(
        "icd10_coding_assistant.api.icd10_coding_api.get_conditions_missing_icd10",
        return_value=[mock_condition_with_codings],
    ):
        with patch("icd10_coding_assistant.api.icd10_coding_api.Command") as mock_cmd:
            mock_cmd.objects.filter.return_value.values_list.return_value = []

            with patch.object(
                api_instance,
                "_get_icd10_recommendations",
                return_value=[{"code": "E11.9", "display": "Diabetes"}],
            ):
                result = api_instance.get_conditions()

    assert len(result) == 1
    assert result[0].status_code == 200
    body = json.loads(result[0].content.decode())
    assert "conditions" in body
    assert len(body["conditions"]) == 1
    cond = body["conditions"][0]
    assert cond["name"] == "Diabetes mellitus"
    assert cond["current_system"] == "http://snomed.info/sct"
    assert cond["current_code"] == "73211009"
    assert cond["has_pending_command"] is False
    assert cond["recommendations"][0]["code"] == "E11.9"


def test_get_conditions_pending_command_detected_via_bulk_query(
    api_instance: ICD10CodingAPI,
    mock_condition_with_codings: MagicMock,
) -> None:
    """has_pending_command should be True when dbid is in the bulk query result."""
    api_instance.request.query_params = {"patient_id": "patient-abc"}
    mock_condition_with_codings.dbid = 77

    with patch(
        "icd10_coding_assistant.api.icd10_coding_api.get_conditions_missing_icd10",
        return_value=[mock_condition_with_codings],
    ):
        with patch("icd10_coding_assistant.api.icd10_coding_api.Command") as mock_cmd:
            # Bulk query returns dbid 77 — meaning it has a pending command
            mock_cmd.objects.filter.return_value.values_list.return_value = [77]

            with patch.object(
                api_instance, "_get_icd10_recommendations", return_value=[]
            ):
                result = api_instance.get_conditions()

    body = json.loads(result[0].content.decode())
    assert body["conditions"][0]["has_pending_command"] is True


# ---------------------------------------------------------------------------
# GET /api/search-icd10
# ---------------------------------------------------------------------------


def test_search_icd10_delegates_to_ontologies(api_instance: ICD10CodingAPI) -> None:
    api_instance.request.query_params = {"query": "diabetes"}
    with patch.object(
        api_instance,
        "_search_ontologies_icd10",
        return_value={
            "count": 1,
            "results": [{"value": "E11.9", "text": "Type 2 diabetes"}],
        },
    ) as mock_call:
        result = api_instance.search_icd10()

    mock_call.assert_called_once_with("diabetes")
    assert result[0].status_code == 200
    body = json.loads(result[0].content.decode())
    assert body["count"] == 1


def test_search_icd10_empty_query(api_instance: ICD10CodingAPI) -> None:
    api_instance.request.query_params = {}
    with patch.object(
        api_instance,
        "_search_ontologies_icd10",
        return_value={"count": 0, "results": []},
    ):
        result = api_instance.search_icd10()
    assert result[0].status_code == 200


# ---------------------------------------------------------------------------
# POST /api/approve-coding
# ---------------------------------------------------------------------------


def test_approve_coding_returns_400_on_invalid_json(
    api_instance: ICD10CodingAPI,
) -> None:
    api_instance.request.json.side_effect = ValueError("bad json")
    result = api_instance.approve_coding()
    assert result[0].status_code == 400
    body = json.loads(result[0].content.decode())
    assert "Invalid JSON" in body["error"]


def test_approve_coding_returns_400_on_missing_fields(
    api_instance: ICD10CodingAPI,
) -> None:
    api_instance.request.json.return_value = {"patient_id": "p-123"}
    result = api_instance.approve_coding()
    assert result[0].status_code == 400
    body = json.loads(result[0].content.decode())
    assert "Missing required fields" in body["error"]


def test_approve_coding_delegates_to_create_effects(
    api_instance: ICD10CodingAPI,
) -> None:
    api_instance.request.json.return_value = {
        "patient_id": "patient-abc",
        "condition_id": str(uuid.uuid4()),
        "icd10_code": "E11.9",
        "icd10_display": "Type 2 diabetes",
    }
    with patch.object(
        api_instance,
        "_create_condition_update_effects",
        return_value=[JSONResponse({"success": True, "note_id": "n1"})],
    ) as mock_create:
        result = api_instance.approve_coding()

    mock_create.assert_called_once()
    assert result[0].status_code == 200


# ---------------------------------------------------------------------------
# POST /api/approve-all
# ---------------------------------------------------------------------------


def test_approve_all_returns_400_on_invalid_json(api_instance: ICD10CodingAPI) -> None:
    api_instance.request.json.side_effect = ValueError("bad json")
    result = api_instance.approve_all()
    assert result[0].status_code == 400


def test_approve_all_returns_400_when_missing_patient_id(
    api_instance: ICD10CodingAPI,
) -> None:
    api_instance.request.json.return_value = {
        "conditions": [{"condition_id": "c1", "icd10_code": "E11.9"}]
    }
    result = api_instance.approve_all()
    assert result[0].status_code == 400


def test_approve_all_returns_400_when_empty_conditions(
    api_instance: ICD10CodingAPI,
) -> None:
    api_instance.request.json.return_value = {
        "patient_id": "patient-abc",
        "conditions": [],
    }
    result = api_instance.approve_all()
    assert result[0].status_code == 400


def test_approve_all_creates_note_and_commands(api_instance: ICD10CodingAPI) -> None:
    api_instance.request.json.return_value = {
        "patient_id": "patient-abc",
        "conditions": [
            {
                "condition_id": str(uuid.uuid4()),
                "icd10_code": "E11.9",
                "icd10_display": "T2DM",
            },
            {
                "condition_id": str(uuid.uuid4()),
                "icd10_code": "I10",
                "icd10_display": "HTN",
            },
        ],
    }
    with patch.object(
        api_instance,
        "_create_condition_update_effects",
        return_value=[JSONResponse({"success": True, "note_id": "n1"})],
    ) as mock_create:
        api_instance.approve_all()

    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args[1]
    assert len(call_kwargs["conditions_data"]) == 2


# ---------------------------------------------------------------------------
# _create_condition_update_effects
# ---------------------------------------------------------------------------


def test_create_condition_update_effects_creates_note_and_command(
    api_instance: ICD10CodingAPI,
    mock_condition_with_codings: MagicMock,
) -> None:
    """One note + one UpdateDiagnosisCommand + success JSONResponse for single condition."""
    with patch.object(
        api_instance,
        "_get_note_context",
        return_value=((MagicMock(id="nt-1"), "prov-1", "loc-1"), None),
    ):
        with patch(
            "icd10_coding_assistant.api.icd10_coding_api.Condition"
        ) as mock_condition_cls:
            mock_condition_cls.objects.get.return_value = mock_condition_with_codings
            mock_condition_cls.DoesNotExist = Exception

            with patch.object(
                api_instance, "_get_current_code", return_value="73211009"
            ):
                with patch(
                    "icd10_coding_assistant.api.icd10_coding_api.NoteEffect"
                ) as mock_note:
                    with patch(
                        "icd10_coding_assistant.api.icd10_coding_api.UpdateDiagnosisCommand"
                    ) as mock_cmd:
                        mock_note.return_value = MagicMock()
                        mock_cmd.return_value = MagicMock()

                        result = api_instance._create_condition_update_effects(
                            patient_id="patient-abc",
                            conditions_data=[
                                {
                                    "condition_id": str(mock_condition_with_codings.id),
                                    "icd10_code": "E11.9",
                                    "icd10_display": "Diabetes",
                                }
                            ],
                            note_title="ICD-10 Update",
                        )

    # Note effect + command + success response = 3
    assert len(result) == 3
    last = result[-1]
    body = json.loads(last.content.decode())
    assert body["success"] is True
    assert "note_id" in body


def test_create_condition_update_effects_skips_nonexistent_condition(
    api_instance: ICD10CodingAPI,
) -> None:
    """If Condition.DoesNotExist, skip without crashing — still return note + success."""

    class FakeDoesNotExist(Exception):
        pass

    with patch.object(
        api_instance,
        "_get_note_context",
        return_value=((MagicMock(id="nt-1"), "prov-1", "loc-1"), None),
    ):
        with patch(
            "icd10_coding_assistant.api.icd10_coding_api.Condition"
        ) as mock_condition_cls:
            mock_condition_cls.DoesNotExist = FakeDoesNotExist
            mock_condition_cls.objects.get.side_effect = FakeDoesNotExist("not found")

            with patch(
                "icd10_coding_assistant.api.icd10_coding_api.NoteEffect"
            ) as mock_note:
                mock_note.return_value = MagicMock()
                with patch(
                    "icd10_coding_assistant.api.icd10_coding_api.UpdateDiagnosisCommand"
                ) as mock_cmd:
                    result = api_instance._create_condition_update_effects(
                        patient_id="patient-abc",
                        conditions_data=[
                            {"condition_id": "bad-id", "icd10_code": "E11.9"}
                        ],
                        note_title="Test",
                    )

    # Note effect + success response; no command (condition not found)
    assert len(result) == 2
    mock_cmd.assert_not_called()
    body = json.loads(result[-1].content.decode())
    assert body["success"] is True


def test_create_condition_update_effects_skips_condition_with_no_current_code(
    api_instance: ICD10CodingAPI,
    mock_condition_with_codings: MagicMock,
) -> None:
    """Conditions where _get_current_code returns None are skipped — never sent as N/A."""
    with patch.object(
        api_instance,
        "_get_note_context",
        return_value=((MagicMock(id="nt-1"), "prov-1", "loc-1"), None),
    ):
        with patch(
            "icd10_coding_assistant.api.icd10_coding_api.Condition"
        ) as mock_condition_cls:
            mock_condition_cls.objects.get.return_value = mock_condition_with_codings
            mock_condition_cls.DoesNotExist = Exception

            with patch.object(api_instance, "_get_current_code", return_value=None):
                with patch(
                    "icd10_coding_assistant.api.icd10_coding_api.NoteEffect"
                ) as mock_note:
                    with patch(
                        "icd10_coding_assistant.api.icd10_coding_api.UpdateDiagnosisCommand"
                    ) as mock_cmd:
                        mock_note.return_value = MagicMock()

                        result = api_instance._create_condition_update_effects(
                            patient_id="patient-abc",
                            conditions_data=[
                                {
                                    "condition_id": str(mock_condition_with_codings.id),
                                    "icd10_code": "E11.9",
                                }
                            ],
                            note_title="Test",
                        )

    # No command because current_code is None
    mock_cmd.assert_not_called()
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Helper methods
# ---------------------------------------------------------------------------


def test_get_display_name_returns_first_display(
    api_instance: ICD10CodingAPI,
    mock_condition_with_codings: MagicMock,
) -> None:
    assert (
        api_instance._get_display_name(mock_condition_with_codings)
        == "Diabetes mellitus"
    )


def test_get_display_name_fallback_when_no_codings(
    api_instance: ICD10CodingAPI,
    mock_condition_no_codings: MagicMock,
) -> None:
    name = api_instance._get_display_name(mock_condition_no_codings)
    assert name.startswith("Condition ")


def test_get_current_system_returns_first_system(
    api_instance: ICD10CodingAPI,
    mock_condition_with_codings: MagicMock,
) -> None:
    assert (
        api_instance._get_current_system(mock_condition_with_codings)
        == "http://snomed.info/sct"
    )


def test_get_current_system_fallback(
    api_instance: ICD10CodingAPI,
    mock_condition_no_codings: MagicMock,
) -> None:
    assert api_instance._get_current_system(mock_condition_no_codings) == "None"


def test_get_current_code_returns_first_code(
    api_instance: ICD10CodingAPI,
    mock_condition_with_codings: MagicMock,
) -> None:
    """Returns string code, never 'N/A'."""
    result = api_instance._get_current_code(mock_condition_with_codings)
    assert result == "73211009"
    assert result != "N/A"


def test_get_current_code_returns_none_when_no_codings(
    api_instance: ICD10CodingAPI,
    mock_condition_no_codings: MagicMock,
) -> None:
    """Must return None, never 'N/A', when no codings exist."""
    result = api_instance._get_current_code(mock_condition_no_codings)
    assert result is None


def test_get_icd10_recommendations_returns_transformed_list(
    api_instance: ICD10CodingAPI,
    mock_condition_with_codings: MagicMock,
) -> None:
    with patch.object(
        api_instance,
        "_search_ontologies_icd10",
        return_value={
            "count": 1,
            "results": [{"value": "E11.9", "text": "Type 2 diabetes"}],
        },
    ):
        result = api_instance._get_icd10_recommendations(mock_condition_with_codings)

    assert len(result) == 1
    assert result[0]["code"] == "E11.9"
    assert result[0]["display"] == "Type 2 diabetes"


def test_get_icd10_recommendations_returns_empty_when_no_display(
    api_instance: ICD10CodingAPI,
    mock_condition_no_codings: MagicMock,
) -> None:
    """No meaningful display → empty list, API not called."""
    mock_condition_no_codings.id = "fallback-id"
    with patch.object(api_instance, "_search_ontologies_icd10") as mock_call:
        result = api_instance._get_icd10_recommendations(mock_condition_no_codings)

    assert result == []
    mock_call.assert_not_called()


def test_search_ontologies_icd10_success(api_instance: ICD10CodingAPI) -> None:
    """Maps ontologies `icd10_code`/`icd10_text` into `value`/`text` results."""
    mock_cache = MagicMock()
    mock_cache.get.return_value = None

    with patch(
        "icd10_coding_assistant.api.icd10_coding_api.get_cache",
        return_value=mock_cache,
    ):
        with patch(
            "icd10_coding_assistant.api.icd10_coding_api.ontologies_http"
        ) as mock_ontologies:
            mock_ontologies.get_json.return_value.json.return_value = {
                "results": [{"icd10_code": "E11.9", "icd10_text": "Type 2 diabetes"}]
            }

            result = api_instance._search_ontologies_icd10("diabetes")

    assert result == {
        "count": 1,
        "results": [{"value": "E11.9", "text": "Type 2 diabetes"}],
    }


def test_search_ontologies_icd10_degrades_on_connection_error(
    api_instance: ICD10CodingAPI,
) -> None:
    """A failed ontologies lookup degrades to an empty result, never raises."""
    mock_cache = MagicMock()
    mock_cache.get.return_value = None

    with patch(
        "icd10_coding_assistant.api.icd10_coding_api.get_cache",
        return_value=mock_cache,
    ):
        with patch(
            "icd10_coding_assistant.api.icd10_coding_api.ontologies_http"
        ) as mock_ontologies:
            # requests' ConnectionError subclasses OSError; the builtin does too.
            mock_ontologies.get_json.side_effect = ConnectionError("dns failure")

            result = api_instance._search_ontologies_icd10("anything")

    assert result == {"count": 0, "results": []}


def test_search_ontologies_icd10_uses_cache(api_instance: ICD10CodingAPI) -> None:
    """Cached value is returned directly without calling ontologies."""
    cached_data: dict[str, object] = {
        "count": 5,
        "results": [{"value": "E11.9", "text": "Type 2 diabetes"}],
    }
    mock_cache = MagicMock()
    mock_cache.get.return_value = cached_data

    with patch(
        "icd10_coding_assistant.api.icd10_coding_api.get_cache",
        return_value=mock_cache,
    ):
        with patch(
            "icd10_coding_assistant.api.icd10_coding_api.ontologies_http"
        ) as mock_ontologies:
            result = api_instance._search_ontologies_icd10("diabetes")

    assert result == cached_data
    mock_ontologies.get_json.assert_not_called()


def test_get_note_context_returns_note_type_provider_location(
    api_instance: ICD10CodingAPI,
) -> None:
    with patch(
        "icd10_coding_assistant.api.icd10_coding_api.NoteType"
    ) as mock_note_type_cls:
        with patch(
            "icd10_coding_assistant.api.icd10_coding_api.PracticeLocation"
        ) as mock_loc_cls:
            mock_nt = MagicMock()
            mock_note_type_cls.objects.filter.return_value.first.return_value = mock_nt
            mock_loc_cls.objects.filter.return_value.values_list.return_value.first.return_value = "loc-1"

            result, error = api_instance._get_note_context()

    assert error is None
    assert result is not None
    nt, provider, loc = result
    assert nt == mock_nt
    assert provider == "provider-xyz"
    assert loc == "loc-1"


def test_get_note_context_fails_closed_when_no_note_type(
    api_instance: ICD10CodingAPI,
) -> None:
    with patch(
        "icd10_coding_assistant.api.icd10_coding_api.NoteType"
    ) as mock_note_type_cls:
        mock_note_type_cls.objects.filter.return_value.first.return_value = None
        result, error = api_instance._get_note_context()

    assert result is None
    assert error is not None
    assert error[0].status_code == 500


def test_get_note_context_fails_closed_when_no_provider(
    api_instance: ICD10CodingAPI,
) -> None:
    api_instance.request.headers = {}  # no canvas-logged-in-user-id
    with patch(
        "icd10_coding_assistant.api.icd10_coding_api.NoteType"
    ) as mock_note_type_cls:
        mock_nt = MagicMock()
        mock_note_type_cls.objects.filter.return_value.first.return_value = mock_nt
        result, error = api_instance._get_note_context()

    assert result is None
    assert error is not None
    assert error[0].status_code == 401
    body = json.loads(error[0].content.decode())
    assert "Authentication required" in body["error"]
