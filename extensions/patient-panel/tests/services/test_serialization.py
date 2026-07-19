"""Tests for patient_panel.services.serialization.

resolve_metadata_value is pure (string/JSON in, string out). process_patient /
get_builtin_column are covered end-to-end by the get_table endpoint tests in
tests/api/.
"""

__is_plugin__ = True

import json

import arrow
import pytest

from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data.patient import PatientMetadata as PatientMetadataRecord

from patient_panel.services.columns import enrich_columns_for_render
from patient_panel.services.patient_query import build_base_queryset
from patient_panel.services.serialization import (
    DEFAULT_AVATAR,
    _patient_photo_url,
    process_patient,
    resolve_metadata_value,
)


class TestResolveMetadataValue:
    def test_plain_string_passthrough(self) -> None:
        assert resolve_metadata_value("hello", "") == "hello"

    def test_full_json_rendered_when_no_path(self) -> None:
        raw = json.dumps({"a": 1, "b": 2})
        assert resolve_metadata_value(raw, "") == raw

    def test_dotted_path_into_dict(self) -> None:
        raw = json.dumps({"ide-gas": {"status": "signed"}})
        assert resolve_metadata_value(raw, "ide-gas.status") == "signed"

    def test_missing_path_segment_returns_empty(self) -> None:
        raw = json.dumps({"ide-gas": {"status": "signed"}})
        assert resolve_metadata_value(raw, "ide-gas.nope") == ""

    def test_list_index_path(self) -> None:
        raw = json.dumps(["a", "b", "c"])
        assert resolve_metadata_value(raw, "1") == "b"

    def test_wildcard_maps_over_list(self) -> None:
        raw = json.dumps([{"name": "x"}, {"name": "y"}])
        assert resolve_metadata_value(raw, "*.name") == "x, y"

    def test_non_json_with_path_returns_raw(self) -> None:
        # Unparseable JSON short-circuits to the raw string.
        assert resolve_metadata_value("not json", "a.b") == "not json"

    def test_deeply_nested_json_does_not_raise(self) -> None:
        # Balanced but pathologically deep — json.loads raises RecursionError,
        # which must be caught (it is not a JSONDecodeError).
        raw = "[" * 100000 + "]" * 100000
        assert resolve_metadata_value(raw, "") == raw


pytestmark = pytest.mark.django_db

_SECRETS = {
    "highlight_green": 1,
    "highlight_yellow": 3,
    "highlight_red": 7,
    "insurances_logos": {},
}

# A representative column set covering built-in, observation, and metadata
# (plain, tags, dotted-path) rendering branches.
_COLUMNS = [
    {"type": "built-in", "key": "patient"},
    {"type": "built-in", "key": "care_team"},
    {"type": "built-in", "key": "last_visit"},
    {"type": "built-in", "key": "facility"},
    {"type": "built-in", "key": "room"},
    {"type": "built-in", "key": "tasks"},
    {"type": "built-in", "key": "gaps"},
    {"type": "built-in", "key": "insurance"},
    {"type": "built-in", "key": "caption"},
    {"type": "built-in", "key": "next_visit"},
    {"type": "built-in", "key": "mrn"},
    {"type": "built-in", "key": "phone"},
    {"type": "built-in", "key": "email"},
    {"type": "built-in", "key": "address"},
    {"type": "built-in", "key": "default_provider"},
    {"type": "built-in", "key": "conditions"},
    {"type": "built-in", "key": "medications"},
    {"type": "built-in", "key": "allergies"},
    {"type": "built-in", "key": "referrals"},
    {"type": "built-in", "key": "active_status"},
    {"type": "observation", "key": "a1c", "loinc": "4548-4", "format": "value_units"},
    {"type": "metadata", "key": "risk_score"},
    {"type": "metadata", "key": "services", "render": "tags"},
]


def _ctx() -> dict[str, object]:
    return {
        "base_path": "/plugin-io/api/patient_panel",
        "prefix": "/app",
        "cache_bust": "123",
        "format_local": lambda dt, fmt: arrow.get(dt).to("UTC").format(fmt),
        "get_care_team": lambda p: [],
    }


class TestProcessPatient:
    def test_builds_template_dict_over_all_column_types(self) -> None:
        patient = PatientFactory.create()
        PatientMetadataRecord.objects.create(patient=patient, key="risk_score", value="High")
        PatientMetadataRecord.objects.create(patient=patient, key="services", value="PCP|SNF")
        annotated = build_base_queryset().get(id=patient.id)

        obs_data = {"4548-4": {str(patient.id): {"value": "7.2", "units": "%"}}}
        data = process_patient(annotated, _SECRETS, _COLUMNS, obs_data, {}, _ctx())

        assert data["id"] == patient.id
        assert data["url"] == f"/patient/{patient.id}"
        # built-in patient cell — a bare factory patient has no photo, so the
        # DB-backed photo_url resolves to the default avatar.
        assert data["patient"]["photo_url"] == DEFAULT_AVATAR
        assert "name" in data["patient"]
        # count columns default to 0 with no related rows
        assert data["conditions"] == {"count": 0}
        assert data["active_status"] in ("Active", "Inactive")
        # observation value_units formatting
        assert data["a1c"] == "7.2 %"
        # metadata plain + tags
        assert data["risk_score"] == "High"
        assert data["services"] == ["PCP", "SNF"]
        # columns_data mirrors columns with values attached
        assert len(data["columns_data"]) == len(_COLUMNS)

    def test_inline_edit_descriptor_reaches_columns_data(self) -> None:
        # End-to-end: enriched columns flow through process_patient into
        # columns_data so the template can render an editable control. The
        # tags column must NOT become editable (would clobber the list).
        patient = PatientFactory.create()
        PatientMetadataRecord.objects.create(patient=patient, key="risk_score", value="High")
        annotated = build_base_queryset().get(id=patient.id)
        secrets = {
            "METADATA_FIELDS": json.dumps([
                {"key": "risk_score", "type": "SELECT",
                 "options": ["Low", "Medium", "High"], "editable": True},
                {"key": "services", "type": "TEXT", "editable": True},
            ])
        }
        cols = enrich_columns_for_render(
            [
                {"type": "metadata", "key": "risk_score"},
                {"type": "metadata", "key": "services", "render": "tags"},
            ],
            secrets,
        )
        data = process_patient(annotated, secrets, cols, {}, {}, _ctx())
        by_key = {c["key"]: c for c in data["columns_data"]}
        assert by_key["risk_score"]["inline_edit"] == {
            "type": "SELECT", "options": ["Low", "Medium", "High"]
        }
        assert by_key["risk_score"]["value"] == "High"
        assert "inline_edit" not in by_key["services"]

    def test_last_visit_reads_annotation(self) -> None:
        """The serializer reads the `last_visit_ann` datetime annotation set by
        build_base_queryset — NOT a ctx `get_last_visit` callable. ctx no longer
        carries that key, so reading it would raise.
        """
        patient = PatientFactory.create()
        annotated = build_base_queryset().get(id=patient.id)
        # Annotation is a plain attribute on the fetched row; set it directly
        # to keep this a focused serializer test (no note seeding required).
        annotated.last_visit_ann = arrow.utcnow().shift(hours=-2).datetime
        data = process_patient(
            annotated, _SECRETS, [{"type": "built-in", "key": "last_visit"}],
            {}, {}, _ctx(),
        )
        assert data["last_visit"]["date"] is not None
        assert data["last_visit"]["color"] == "highlight-green"

    def test_last_visit_none_when_annotation_absent(self) -> None:
        patient = PatientFactory.create()
        annotated = build_base_queryset().get(id=patient.id)  # last_visit_ann is None
        data = process_patient(
            annotated, _SECRETS, [{"type": "built-in", "key": "last_visit"}],
            {}, {}, _ctx(),
        )
        assert data["last_visit"]["date"] is None
        assert data["last_visit"]["color"] is None

    def test_missing_metadata_renders_empty(self) -> None:
        patient = PatientFactory.create()
        annotated = build_base_queryset().get(id=patient.id)
        cols = [
            {"type": "metadata", "key": "risk_score"},
            {"type": "metadata", "key": "services", "render": "tags"},
        ]
        data = process_patient(annotated, _SECRETS, cols, {}, {}, _ctx())
        assert data["risk_score"] == ""
        assert data["services"] == []


class TestPatientPhotoUrl:
    def test_reads_photo_url_property(self) -> None:
        class _P:
            @property
            def photo_url(self) -> str:
                return "https://signed.example/abc.jpg"

        assert _patient_photo_url(_P()) == "https://signed.example/abc.jpg"

    def test_falls_back_to_default_avatar_on_error(self) -> None:
        class _P:
            @property
            def photo_url(self) -> str:
                raise ValueError("AWS credentials not configured")

        assert _patient_photo_url(_P()) == DEFAULT_AVATAR
