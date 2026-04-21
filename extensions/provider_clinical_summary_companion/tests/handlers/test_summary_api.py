"""Tests for summary_api.SummaryAPI and its section builders."""
import json
from datetime import date, datetime, timezone
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

from provider_clinical_summary_companion.handlers import summary_api
from provider_clinical_summary_companion.handlers.summary_api import (
    SECTION_KEYS,
    VITAL_TYPES,
    SummaryAPI,
    _iso,
    _normalize_vital_members,
    _parse_sections,
    _primary_coding,
    _display_name,
    _serialize_allergy,
    _serialize_condition,
    _serialize_immunization,
    _serialize_immunization_statement,
    _serialize_interview_response,
    _serialize_medication,
    _weight_oz_to_lbs,
    build_allergies,
    build_conditions,
    build_immunizations,
    build_medications,
    build_social_determinants,
    build_surgical_history,
    build_vitals,
)

STAFF_UUID = "00000000-0000-0000-0000-000000000001"
PATIENT_UUID = "00000000-0000-0000-0000-0000000000aa"


def _make_api(
    query_params: dict | None = None,
    body: dict | None = None,
    headers: dict | None = None,
) -> SummaryAPI:
    api = SummaryAPI.__new__(SummaryAPI)
    api.request = SimpleNamespace(
        headers=headers or {"canvas-logged-in-user-id": STAFF_UUID},
        query_params=query_params or {},
        json=lambda: body,
    )
    return api


def _make_codings(rows):
    """Return a fake 'codings' manager whose .first() yields the first row or None."""
    qs = MagicMock()
    qs.first.return_value = rows[0] if rows else None
    return qs


class TestIso:
    def test_datetime(self) -> None:
        dt = datetime(2026, 4, 19, tzinfo=timezone.utc)
        assert _iso(dt) == "2026-04-19T00:00:00+00:00"

    def test_date(self) -> None:
        assert _iso(date(2026, 4, 19)) == "2026-04-19"

    def test_none(self) -> None:
        assert _iso(None) is None

    def test_falls_back_to_str(self) -> None:
        assert _iso("already-a-string") == "already-a-string"


class TestPrimaryCoding:
    def test_returns_empty_when_no_codings_attr(self) -> None:
        assert _primary_coding(SimpleNamespace()) == {}

    def test_returns_empty_when_first_is_none(self) -> None:
        obj = SimpleNamespace(codings=_make_codings([]))
        assert _primary_coding(obj) == {}

    def test_returns_code_display_system(self) -> None:
        coding = SimpleNamespace(code="I10", display="Hypertension", system="ICD10")
        obj = SimpleNamespace(codings=_make_codings([coding]))
        assert _primary_coding(obj) == {
            "code": "I10",
            "display": "Hypertension",
            "system": "ICD10",
        }

    def test_blank_strings_stay_empty(self) -> None:
        coding = SimpleNamespace(code="", display="", system="")
        obj = SimpleNamespace(codings=_make_codings([coding]))
        assert _primary_coding(obj) == {"code": "", "display": "", "system": ""}

    def test_falls_back_to_singular_coding_attr(self) -> None:
        # ImmunizationStatementCoding is related via `related_name="coding"`
        # (singular) rather than "codings". The helper must honor that.
        coding = SimpleNamespace(code="FLU", display="Influenza", system="CVX")
        obj = SimpleNamespace(coding=_make_codings([coding]))
        assert _primary_coding(obj) == {
            "code": "FLU",
            "display": "Influenza",
            "system": "CVX",
        }


class TestDisplayName:
    def test_uses_primary_display(self) -> None:
        coding = SimpleNamespace(code="X", display="X Disease", system="S")
        obj = SimpleNamespace(codings=_make_codings([coding]))
        assert _display_name(obj) == "X Disease"

    def test_falls_back(self) -> None:
        obj = SimpleNamespace(codings=_make_codings([]))
        assert _display_name(obj, fallback="Fallback") == "Fallback"


class TestSerializers:
    def test_condition(self) -> None:
        coding = SimpleNamespace(code="I10", display="HTN", system="ICD10")
        cond = SimpleNamespace(
            id="c-1",
            clinical_status="active",
            onset_date=date(2019, 5, 1),
            resolution_date=None,
            codings=_make_codings([coding]),
        )
        assert _serialize_condition(cond) == {
            "id": "c-1",
            "name": "HTN",
            "clinical_status": "active",
            "onset_date": "2019-05-01",
            "resolution_date": None,
            "coding": {"code": "I10", "display": "HTN", "system": "ICD10"},
        }

    def test_medication(self) -> None:
        coding = SimpleNamespace(code="MED", display="Amoxicillin", system="RXNORM")
        med = SimpleNamespace(
            id="m-1",
            status="active",
            start_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
            end_date=None,
            clinical_quantity_description="500 mg bid",
            codings=_make_codings([coding]),
        )
        result = _serialize_medication(med)
        assert result["name"] == "Amoxicillin"
        assert result["status"] == "active"
        assert result["sig"] == "500 mg bid"
        assert result["start_date"].startswith("2026-01-10")

    def test_allergy(self) -> None:
        coding = SimpleNamespace(code="A", display="Penicillin", system="RXNORM")
        allergy = SimpleNamespace(
            id="a-1",
            severity="moderate",
            status="active",
            narrative="Hives",
            onset_date=date(2021, 6, 1),
            codings=_make_codings([coding]),
        )
        assert _serialize_allergy(allergy) == {
            "id": "a-1",
            "name": "Penicillin",
            "severity": "moderate",
            "status": "active",
            "narrative": "Hives",
            "onset_date": "2021-06-01",
        }

    def test_immunization(self) -> None:
        coding = SimpleNamespace(code="I", display="Influenza", system="CVX")
        imm = SimpleNamespace(
            id="i-1",
            sig_original="Yearly flu shot",
            date_ordered=date(2025, 10, 1),
            codings=_make_codings([coding]),
        )
        assert _serialize_immunization(imm) == {
            "id": "i-1",
            "kind": "administered",
            "name": "Influenza",
            "date": "2025-10-01",
            "comment": "Yearly flu shot",
        }

    def test_immunization_statement(self) -> None:
        # ImmunizationStatement exposes its coding under `.coding` (singular),
        # not `.codings` like every other model — the primary-coding helper
        # must handle both names.
        coding = SimpleNamespace(code="I", display="Flu 2020", system="CVX")
        stmt = SimpleNamespace(
            id="s-1",
            comment="Reported by patient",
            date=date(2020, 9, 15),
            coding=_make_codings([coding]),
        )
        assert _serialize_immunization_statement(stmt) == {
            "id": "s-1",
            "kind": "statement",
            "name": "Flu 2020",
            "date": "2020-09-15",
            "comment": "Reported by patient",
        }

    def test_interview_response_uses_response_option_value(self) -> None:
        question = SimpleNamespace(name=" Housing stable? ")
        resp = SimpleNamespace(
            id="r-1",
            question=question,
            response_option=SimpleNamespace(value="stable"),
            response_option_value="Yes",
            comment="",
            modified=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        result = _serialize_interview_response(resp)
        assert result == {
            "id": "r-1",
            "question": "Housing stable?",
            "value": "Yes",
            "recorded_at": "2026-02-01T00:00:00+00:00",
        }

    def test_interview_response_falls_back_to_option_value(self) -> None:
        question = SimpleNamespace(name="Transport")
        resp = SimpleNamespace(
            id="r-2",
            question=question,
            response_option=SimpleNamespace(value="bus"),
            response_option_value="",
            comment="",
            modified=None,
        )
        assert _serialize_interview_response(resp)["value"] == "bus"

    def test_interview_response_falls_back_to_comment(self) -> None:
        question = SimpleNamespace(name="Food security")
        resp = SimpleNamespace(
            id="r-3",
            question=question,
            response_option=None,
            response_option_value="",
            comment="Sometimes skips meals",
            modified=None,
        )
        assert _serialize_interview_response(resp)["value"] == "Sometimes skips meals"


class TestVitalNormalization:
    def test_weight_oz_to_lbs_rounds_for_values_over_one_pound(self) -> None:
        assert _weight_oz_to_lbs("2640") == "165"   # 2640 oz / 16 = 165 lbs
        assert _weight_oz_to_lbs("2648") == "166"   # 165.5 rounds up

    def test_weight_oz_to_lbs_preserves_decimal_for_sub_pound(self) -> None:
        assert _weight_oz_to_lbs("8") == "0.5"      # 0.5 lb neonate weight

    def test_weight_oz_to_lbs_passes_through_garbage(self) -> None:
        assert _weight_oz_to_lbs("not a number") == "not a number"

    def test_normalize_skips_blank_and_excluded_names(self) -> None:
        members = [
            SimpleNamespace(name="", value="ignored"),
            SimpleNamespace(name="note", value="clinician note, skip"),
            SimpleNamespace(name="pulse_rhythm", value="regular"),
            SimpleNamespace(name="pulse", value=""),          # blank value
            SimpleNamespace(name="oxygen_saturation", value="98"),
        ]
        assert _normalize_vital_members(members) == {"oxygen_saturation": "98"}

    def test_normalize_maps_blood_pressure_and_weight_specially(self) -> None:
        members = [
            SimpleNamespace(name="blood_pressure", value="118/76"),
            SimpleNamespace(name="weight", value="2640"),
            SimpleNamespace(name="height", value="70"),
        ]
        assert _normalize_vital_members(members) == {
            "bp": "118/76",
            "weight_lbs": "165",
            "height": "70",
        }

    def test_normalize_drops_unknown_names(self) -> None:
        assert _normalize_vital_members(
            [SimpleNamespace(name="mystery_vital", value="42")]
        ) == {}


class TestParseSections:
    def test_none_returns_all(self) -> None:
        assert _parse_sections(None) == list(SECTION_KEYS)

    def test_empty_returns_all(self) -> None:
        assert _parse_sections("") == list(SECTION_KEYS)

    def test_filters_unknown(self) -> None:
        assert _parse_sections("conditions,bogus,vitals") == ["conditions", "vitals"]

    def test_strips_whitespace(self) -> None:
        assert _parse_sections("  conditions , medications ") == ["conditions", "medications"]


class TestConditionBuilders:
    def _patch_condition(self, surgical_value_returned):
        qs = MagicMock()
        qs.committed.return_value = qs
        qs.filter.return_value = qs
        qs.order_by.return_value = surgical_value_returned
        return patch.object(summary_api, "Condition", objects=MagicMock(for_patient=MagicMock(return_value=qs))), qs

    def test_build_conditions_filters_non_surgical(self) -> None:
        coding = SimpleNamespace(code="X", display="Dx", system="S")
        cond = SimpleNamespace(
            id="c-1",
            clinical_status="active",
            onset_date=date(2022, 1, 1),
            resolution_date=None,
            codings=_make_codings([coding]),
        )
        patcher, qs = self._patch_condition([cond])
        with patcher as mock_cls:
            result = build_conditions(PATIENT_UUID)

        assert len(result) == 1
        assert result[0]["name"] == "Dx"
        assert mock_cls.objects.for_patient.call_args == call(PATIENT_UUID)
        assert qs.filter.call_args == call(surgical=False)

    def test_build_surgical_history_filters_surgical(self) -> None:
        patcher, qs = self._patch_condition([])
        with patcher as mock_cls:
            result = build_surgical_history(PATIENT_UUID)

        assert result == []
        assert qs.filter.call_args == call(surgical=True)


class TestOtherBuilders:
    def test_medications_uses_for_patient_and_order(self) -> None:
        med = SimpleNamespace(
            id="m-1",
            status="active",
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_date=None,
            clinical_quantity_description="1 tab daily",
            codings=_make_codings([SimpleNamespace(code="R", display="Rx", system="RX")]),
        )
        qs = MagicMock()
        qs.committed.return_value = qs
        qs.order_by.return_value = [med]
        with patch.object(summary_api, "Medication") as mock_cls:
            mock_cls.objects.for_patient.return_value = qs
            out = build_medications(PATIENT_UUID)
        assert len(out) == 1
        assert out[0]["name"] == "Rx"
        assert qs.order_by.call_args == call("-start_date")

    def test_allergies(self) -> None:
        allergy = SimpleNamespace(
            id="a-1",
            status="active",
            severity="severe",
            narrative="",
            onset_date=None,
            codings=_make_codings([SimpleNamespace(code="A", display="Peanut", system="S")]),
        )
        qs = MagicMock()
        qs.committed.return_value = qs
        qs.order_by.return_value = [allergy]
        with patch.object(summary_api, "AllergyIntolerance") as mock_cls:
            mock_cls.objects.for_patient.return_value = qs
            out = build_allergies(PATIENT_UUID)
        assert out[0]["name"] == "Peanut"

    def test_vitals_returns_types_and_panels_with_mapped_values(self) -> None:
        panel = SimpleNamespace(
            id="panel-1",
            effective_datetime=datetime(2026, 4, 18, tzinfo=timezone.utc),
        )
        members = [
            SimpleNamespace(name="blood_pressure", value="120/80"),
            SimpleNamespace(name="pulse", value="72"),
            SimpleNamespace(name="weight", value="2640"),  # oz → 165 lbs
            SimpleNamespace(name="pulse_rhythm", value="regular"),  # skipped
            SimpleNamespace(name="", value=""),  # ignored
        ]

        panel_qs = MagicMock()
        panel_qs.committed.return_value = panel_qs
        panel_qs.filter.return_value = panel_qs
        panel_qs.order_by.return_value = [panel]

        members_qs = MagicMock()
        members_qs.filter.return_value = members

        with patch.object(summary_api, "Observation") as mock_cls:
            # First call is `.for_patient(...)` for panels; second and on are
            # bare `.committed()` for member fetches inside the loop.
            mock_cls.objects.for_patient.return_value = panel_qs
            mock_cls.objects.committed.return_value = members_qs
            out = build_vitals(PATIENT_UUID)

        assert out["types"] == list(VITAL_TYPES)
        assert len(out["panels"]) == 1
        panel_out = out["panels"][0]
        assert panel_out["id"] == "panel-1"
        assert panel_out["effective_datetime"].startswith("2026-04-18")
        assert panel_out["values"] == {
            "bp": "120/80",
            "pulse": "72",
            "weight_lbs": "165",
        }
        assert panel_qs.filter.call_args == call(
            category="vital-signs", name="Vital Signs Panel"
        )
        assert members_qs.filter.call_args == call(is_member_of=panel)

    def test_vitals_empty_when_no_panels(self) -> None:
        qs = MagicMock()
        qs.committed.return_value = qs
        qs.filter.return_value = qs
        qs.order_by.return_value = []
        with patch.object(summary_api, "Observation") as mock_cls:
            mock_cls.objects.for_patient.return_value = qs
            out = build_vitals(PATIENT_UUID)
        assert out == {"types": list(VITAL_TYPES), "panels": []}

    def test_immunizations_merges_and_sorts(self) -> None:
        imm = SimpleNamespace(
            id="i-1",
            sig_original="",
            date_ordered=date(2024, 1, 1),
            codings=_make_codings([SimpleNamespace(code="A", display="Admin", system="X")]),
        )
        stmt = SimpleNamespace(
            id="s-1",
            comment="",
            date=date(2025, 1, 1),
            coding=_make_codings([SimpleNamespace(code="S", display="Stated", system="X")]),
        )
        imm_qs = MagicMock()
        imm_qs.filter.return_value = imm_qs
        imm_qs.order_by.return_value = [imm]
        stmt_qs = MagicMock()
        stmt_qs.filter.return_value = stmt_qs
        stmt_qs.order_by.return_value = [stmt]
        with patch.object(summary_api, "Immunization") as mock_imm, \
             patch.object(summary_api, "ImmunizationStatement") as mock_stmt:
            mock_imm.objects.for_patient.return_value = imm_qs
            mock_stmt.objects.for_patient.return_value = stmt_qs
            out = build_immunizations(PATIENT_UUID)

        # Immunization and ImmunizationStatement lack committer/entered_in_error
        # columns, so the builder filters by `deleted=False` instead of
        # `.committed()`. Assert the correct filter call was used.
        assert imm_qs.filter.call_args == call(deleted=False)
        assert stmt_qs.filter.call_args == call(deleted=False)
        assert [row["name"] for row in out] == ["Stated", "Admin"]  # newest first

    def test_social_determinants_skips_incomplete_rows(self) -> None:
        valid_response = SimpleNamespace(
            id="r-1",
            question=SimpleNamespace(name="Housing"),
            response_option=SimpleNamespace(value="Stable"),
            response_option_value="Stable",
            comment="",
            modified=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        blank_response = SimpleNamespace(
            id="r-2",
            question=SimpleNamespace(name=""),
            response_option=None,
            response_option_value="",
            comment="",
            modified=None,
        )
        responses_qs = MagicMock()
        responses_qs.order_by.return_value = [valid_response, blank_response]
        responses_rel = MagicMock()
        responses_rel.select_related.return_value = responses_qs
        interview = SimpleNamespace(interview_responses=responses_rel)

        interview_qs = MagicMock()
        interview_qs.committed.return_value = interview_qs
        interview_qs.filter.return_value = interview_qs
        interview_qs.distinct.return_value = interview_qs
        interview_qs.order_by.return_value = [interview]
        with patch.object(summary_api, "Interview") as mock_cls:
            mock_cls.objects.for_patient.return_value = interview_qs
            out = build_social_determinants(PATIENT_UUID)

        assert [r["question"] for r in out] == ["Housing"]


class TestAuthenticate:
    def test_staff_passes(self) -> None:
        api = _make_api()
        credentials = MagicMock(logged_in_user={"id": STAFF_UUID, "type": "Staff"})
        assert api.authenticate(credentials) is True

    def test_non_staff_rejected(self) -> None:
        api = _make_api()
        credentials = MagicMock(logged_in_user={"id": STAFF_UUID, "type": "Patient"})
        with pytest.raises(InvalidCredentialsError):
            api.authenticate(credentials)


class TestIndex:
    def test_returns_html_with_no_store(self) -> None:
        api = _make_api()
        with patch.object(summary_api, "render_to_string", return_value="<html/>") as mock_render:
            response = api.index()[0]
        assert mock_render.mock_calls == [
            call("static/index.html", {"cache_bust": summary_api._CACHE_BUST})
        ]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"<html/>"
        assert response.headers.get("Cache-Control") == "no-store"


class TestData:
    def test_missing_patient_id_returns_400(self) -> None:
        api = _make_api(query_params={})
        response = api.data()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_blank_patient_id_returns_400(self) -> None:
        api = _make_api(query_params={"patient_id": "   "})
        response = api.data()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_full_bundle_calls_every_builder(self) -> None:
        api = _make_api(query_params={"patient_id": PATIENT_UUID})
        builder_mocks = {
            key: MagicMock(return_value=[{"id": key + "-row"}]) for key in SECTION_KEYS
        }
        with patch.dict(summary_api.SECTION_BUILDERS, builder_mocks, clear=False):
            response = api.data()[0]
        body = json.loads(response.content)
        assert body["patient_id"] == PATIENT_UUID
        assert list(body["sections"].keys()) == list(SECTION_KEYS)
        for key, mock in builder_mocks.items():
            mock.assert_called_once_with(PATIENT_UUID)

    def test_filtered_sections_call_only_requested(self) -> None:
        api = _make_api(
            query_params={"patient_id": PATIENT_UUID, "sections": "conditions,bogus,vitals"}
        )
        called = {
            "conditions": MagicMock(return_value=[{"id": "c"}]),
            "vitals": MagicMock(return_value=[{"id": "v"}]),
        }
        not_called = {
            key: MagicMock() for key in SECTION_KEYS if key not in called
        }
        with patch.dict(summary_api.SECTION_BUILDERS, {**called, **not_called}, clear=False):
            response = api.data()[0]
        body = json.loads(response.content)
        assert set(body["sections"].keys()) == {"conditions", "vitals"}
        called["conditions"].assert_called_once_with(PATIENT_UUID)
        called["vitals"].assert_called_once_with(PATIENT_UUID)
        for key, mock in not_called.items():
            assert mock.call_count == 0


class TestStaticEndpoints:
    def test_main_js(self) -> None:
        api = _make_api()
        with patch.object(summary_api, "render_to_string", return_value="// js") as mock_render:
            response = api.main_js()[0]
        assert mock_render.mock_calls == [call("static/main.js")]
        assert response.content == b"// js"
        assert response.headers["Content-Type"] == "text/javascript"

    def test_styles_css(self) -> None:
        api = _make_api()
        with patch.object(summary_api, "render_to_string", return_value="body{}") as mock_render:
            response = api.styles_css()[0]
        assert mock_render.mock_calls == [call("static/styles.css")]
        assert response.content == b"body{}"
        assert response.headers["Content-Type"] == "text/css"
