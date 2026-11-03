"""Tests for the CoverageAPI SimpleAPI handler."""

import json
from datetime import date
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from canvas_generated.messages.effects_pb2 import EffectType
from canvas_sdk.effects.coverage import Coverage as RealCoverageEffect
from canvas_sdk.effects.coverage import PhotoSide
from canvas_sdk.handlers.simple_api import StoredFilePart, StringFormPart
from canvas_sdk.handlers.simple_api.tools import MultiDict
from pydantic_core import InitErrorDetails, PydanticCustomError, ValidationError

from patient_coverage_companion.handlers import coverage_api
from patient_coverage_companion.handlers.coverage_api import (
    CoverageAPI,
    _build_effect_fields,
    _field_errors_from_pydantic,
    _parse_date,
    _serialize_coverage,
)

STAFF_UUID = "00000000-0000-0000-0000-000000000001"
PATIENT_UUID = "00000000-0000-0000-0000-0000000000aa"
COVERAGE_UUID = "00000000-0000-0000-0000-0000000000cc"

VALID_CREATE_BODY = {
    "patient_id": PATIENT_UUID,
    "issuer_id": "00000000-0000-0000-0000-0000000000bb",
    "coverage_rank": 1,
    "id_number": "MEM-1",
    "patient_relationship_to_subscriber": "18",
}


def _make_api(
    query_params: dict | None = None,
    body: dict | None = None,
    form_parts: list | None = None,
    path_params: dict | None = None,
    headers: dict | None = None,
) -> CoverageAPI:
    """Build a CoverageAPI instance with a stubbed request — no auth flow,
    matches the pattern used by the reference companion plugin tests."""
    api = CoverageAPI.__new__(CoverageAPI)
    api.request = SimpleNamespace(
        headers=headers or {"canvas-logged-in-user-id": STAFF_UUID},
        query_params=query_params or {},
        path_params=path_params or {},
        json=lambda: body,
        # Production form_data() returns the SDK MultiDict of FormParts.
        form_data=lambda: MultiDict((p.name, p) for p in (form_parts or [])),
    )
    return api


def _stored(
    name: str, key: str | None = None, error: str | None = None
) -> StoredFilePart:
    return StoredFilePart(
        name=name,
        filename=f"{name}.jpg",
        content_type="image/jpeg",
        content_length=10,
        key=key,
        error=error,
    )


def _sdk_error(message: str, loc: tuple = ()) -> ValidationError:
    """A ValidationError shaped like the SDK's effect checks (no loc by default)."""
    detail: dict = {"type": PydanticCustomError("value", message), "input": None}
    if loc:
        detail["loc"] = loc
    return ValidationError.from_exception_data("Coverage", [InitErrorDetails(detail)])


# ---------- helpers ----------


class TestParseDate:
    def test_blank_returns_none(self) -> None:
        assert _parse_date("") is None
        assert _parse_date(None) is None

    def test_valid_iso(self) -> None:
        assert _parse_date("2026-05-19") == date(2026, 5, 19)

    def test_passthrough_date(self) -> None:
        d = date(2026, 1, 2)
        assert _parse_date(d) == d

    def test_bad_format_raises(self) -> None:
        with pytest.raises(ValueError):
            _parse_date("not-a-date")


class TestBuildEffectFields:
    def test_drops_empty_values(self) -> None:
        """Blank / null values are dropped so updates don't clobber unset fields."""
        out, err = _build_effect_fields(
            {"plan": "", "group": None, "id_number": "MEM-1"}
        )
        assert err is None
        assert out == {"id_number": "MEM-1"}

    def test_parses_rank_as_int(self) -> None:
        out, err = _build_effect_fields({"coverage_rank": "2"})
        assert err is None
        assert out["coverage_rank"] == 2

    def test_rejects_non_int_rank(self) -> None:
        _, err = _build_effect_fields({"coverage_rank": "high"})
        assert err is not None

    def test_rejects_unknown_stack(self) -> None:
        _, err = _build_effect_fields({"stack": "MAYBE"})
        assert err is not None

    def test_parses_dates(self) -> None:
        out, err = _build_effect_fields(
            {"coverage_start_date": "2026-01-01", "coverage_end_date": "2026-12-31"}
        )
        assert err is None
        assert out["coverage_start_date"] == date(2026, 1, 1)
        assert out["coverage_end_date"] == date(2026, 12, 31)

    def test_drops_plan_type(self) -> None:
        """Plan type follows the payer; the SDK effect forbids it as an extra field."""
        out, err = _build_effect_fields({"plan_type": "commercial", "id_number": "M"})
        assert err is None
        assert "plan_type" not in out

    def test_bad_date_returns_error(self) -> None:
        _, err = _build_effect_fields({"coverage_start_date": "soon"})
        assert err is not None and "date" in err

    def test_keeps_valid_stack(self) -> None:
        out, err = _build_effect_fields({"stack": "OTHER"})
        assert err is None
        assert out["stack"] == "OTHER"

    def test_keeps_image_upload_keys(self) -> None:
        out, err = _build_effect_fields(
            {
                "card_image_front_upload_key": "plugin-uploads/x/y-front.jpg",
                "card_image_back_upload_key": "plugin-uploads/x/y-back.jpg",
            }
        )
        assert err is None
        assert out["card_image_front_upload_key"] == "plugin-uploads/x/y-front.jpg"
        assert out["card_image_back_upload_key"] == "plugin-uploads/x/y-back.jpg"


# ---------- data + payer endpoints ----------


class TestData:
    def test_missing_patient_id_returns_400(self) -> None:
        api = _make_api(query_params={})
        (response,) = api.data()
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_unknown_patient_returns_404(self) -> None:
        api = _make_api(query_params={"patient_id": PATIENT_UUID})
        with patch.object(coverage_api, "Patient") as patient_cls:
            patient_cls.DoesNotExist = Exception
            patient_cls.objects.get.side_effect = patient_cls.DoesNotExist
            (response,) = api.data()
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_returns_coverages_and_options(self) -> None:
        api = _make_api(query_params={"patient_id": PATIENT_UUID})
        coverage = MagicMock()
        with (
            patch.object(coverage_api, "Patient") as patient_cls,
            patch.object(coverage_api, "Coverage") as coverage_cls,
            patch.object(
                coverage_api, "_serialize_coverage", return_value={"id": "c1"}
            ),
        ):
            patient_cls.objects.get.return_value = SimpleNamespace(id=PATIENT_UUID)
            chain = coverage_cls.objects.filter.return_value.exclude.return_value
            chain.select_related.return_value.order_by.return_value = [coverage]
            (response,) = api.data()
        body = json.loads(response.content)
        assert body["patient_id"] == PATIENT_UUID
        assert body["coverages"] == [{"id": "c1"}]
        assert set(body["options"]) == {"relationship", "rank"}


class TestSerializeCoverage:
    def _coverage(self, snapshot: object = None) -> SimpleNamespace:
        return SimpleNamespace(
            id=COVERAGE_UUID,
            issuer_id=7,
            issuer=SimpleNamespace(id="payer-uuid", name="Acme Health"),
            subscriber_id=None,
            subscriber=None,
            patient_relationship_to_subscriber="18",
            subscriber_identifier=None,
            coverage_rank=1,
            plan_type="commercial",
            coverage_type=None,
            id_number="MEM-1",
            plan=None,
            sub_plan=None,
            group=None,
            sub_group=None,
            employer=None,
            coverage_start_date=date(2026, 1, 1),
            coverage_end_date=None,
            comments=None,
            stack="IN_USE",
            snapshot=snapshot,
        )

    def test_issuer_id_is_payer_uuid_not_fk(self) -> None:
        """The form posts issuer_id back to the effect, which wants the UUID."""
        out = _serialize_coverage(self._coverage())
        assert out["issuer_id"] == "payer-uuid"
        assert out["issuer_name"] == "Acme Health"
        assert out["coverage_start_date"] == "2026-01-01"
        assert out["coverage_end_date"] == ""
        assert out["card_image_front_url"] is None

    def test_reads_card_image_urls_from_snapshot(self) -> None:
        images = [
            SimpleNamespace(tag="FRONT_IMAGE", image_url="https://f"),
            SimpleNamespace(tag="BACK_IMAGE", image_url="https://b"),
            SimpleNamespace(tag="OTHER", image_url="https://o"),
        ]
        snapshot = SimpleNamespace(images=SimpleNamespace(all=lambda: images))
        out = _serialize_coverage(self._coverage(snapshot))
        assert out["card_image_front_url"] == "https://f"
        assert out["card_image_back_url"] == "https://b"


class TestPayersSearch:
    def test_short_query_returns_empty(self) -> None:
        api = _make_api(query_params={"q": "a"})
        (response,) = api.payers_search()
        body = json.loads(response.content)
        assert body == {"results": []}

    def test_returns_payer_uuid(self) -> None:
        """Coverage(issuer_id=...) takes the Transactor UUID, so search must return it."""
        api = _make_api(query_params={"q": "acme"})
        payer = SimpleNamespace(
            id="payer-uuid", dbid=12, name="Acme Health", payer_id=None
        )
        with patch.object(coverage_api, "Transactor") as transactor_cls:
            transactor_cls.objects.filter.return_value.order_by.return_value = [payer]
            (response,) = api.payers_search()
        body = json.loads(response.content)
        assert body["results"] == [
            {"id": "payer-uuid", "name": "Acme Health", "payer_id": ""}
        ]


# ---------- error mapping ----------


class TestFieldErrorsFromPydantic:
    def test_uses_loc_when_present(self) -> None:
        exc = _sdk_error("bad", loc=("id_number",))
        assert _field_errors_from_pydantic(exc) == {"id_number": "bad"}

    def test_parses_field_name_from_sdk_message(self) -> None:
        exc = _sdk_error("Field 'issuer_id' must name an existing payer.")
        assert set(_field_errors_from_pydantic(exc)) == {"issuer_id"}

    def test_maps_rank_conflict_to_rank_field(self) -> None:
        exc = _sdk_error(
            "The patient already has an active IN_USE coverage with rank 1."
        )
        assert set(_field_errors_from_pydantic(exc)) == {"coverage_rank"}

    def test_falls_back_to_form_key(self) -> None:
        exc = _sdk_error("Something about the whole coverage.")
        assert set(_field_errors_from_pydantic(exc)) == {"__form__"}

    def test_real_effect_rejects_plan_type(self) -> None:
        """Guard for why the form no longer sends plan_type."""
        with pytest.raises(ValidationError) as info:
            RealCoverageEffect(patient_id=PATIENT_UUID, plan_type="commercial")
        assert "plan_type" in _field_errors_from_pydantic(info.value)


# ---------- coverage CRUD endpoints ----------


class TestCreateCoverage:
    def test_missing_patient_id_returns_400(self) -> None:
        api = _make_api(body={"issuer_id": "x"})
        (response,) = api.create_coverage()
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_blank_body_returns_field_errors(self) -> None:
        """A blank create payload returns 400 with per-field error messages
        for each missing required field — not a generic 'Save failed'."""
        api = _make_api(body={"patient_id": PATIENT_UUID})
        (response,) = api.create_coverage()
        assert response.status_code == HTTPStatus.BAD_REQUEST
        body = json.loads(response.content)
        assert "field_errors" in body
        for required in (
            "issuer_id",
            "id_number",
            "coverage_rank",
            "patient_relationship_to_subscriber",
        ):
            assert required in body["field_errors"], (
                f"expected {required!r} in field_errors, got {body['field_errors']!r}"
            )
        assert "plan_type" not in body["field_errors"]

    def test_bad_rank_returns_400(self) -> None:
        api = _make_api(body={**VALID_CREATE_BODY, "coverage_rank": "first"})
        (response,) = api.create_coverage()
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_create_emits_create_effect(self) -> None:
        """A valid create body produces a CREATE_COVERAGE effect plus a 202
        JSON acknowledgement."""
        api = _make_api(body=dict(VALID_CREATE_BODY))
        with patch.object(coverage_api, "CoverageEffect") as eff_cls:
            instance = eff_cls.return_value
            instance.create.return_value = MagicMock(
                type=EffectType.CREATE_COVERAGE, payload=""
            )
            results = api.create_coverage()
        assert len(results) == 2
        eff_cls.assert_called_once()
        kwargs = eff_cls.call_args.kwargs
        assert kwargs["patient_id"] == PATIENT_UUID
        assert kwargs["coverage_rank"] == 1
        assert kwargs["id_number"] == "MEM-1"
        # Response is the 202
        assert results[-1].status_code == HTTPStatus.ACCEPTED

    def test_rank_conflict_returns_400(self) -> None:
        """The SDK's synchronous rank check surfaces as an inline rank error,
        not a 202 'submitted' that silently fails async."""
        api = _make_api(body=dict(VALID_CREATE_BODY))
        with patch.object(coverage_api, "CoverageEffect") as eff_cls:
            eff_cls.return_value.create.side_effect = _sdk_error(
                "The patient already has an active IN_USE coverage with rank 1."
            )
            (response,) = api.create_coverage()
        assert response.status_code == HTTPStatus.BAD_REQUEST
        body = json.loads(response.content)
        assert "coverage_rank" in body["field_errors"]

    def test_sdk_validation_error_returns_400(self) -> None:
        """If the SDK effect raises ValidationError during .create(), the
        handler translates it into a structured 400 instead of letting it
        bubble up as a 500."""
        api = _make_api(body=dict(VALID_CREATE_BODY))
        with patch.object(coverage_api, "CoverageEffect") as eff_cls:
            eff_cls.return_value.create.side_effect = _sdk_error(
                "Field 'issuer_id' must name an existing payer."
            )
            (response,) = api.create_coverage()
        assert response.status_code == HTTPStatus.BAD_REQUEST
        body = json.loads(response.content)
        assert body["field_errors"].get("issuer_id")


class TestUpdateCoverage:
    def test_update_with_image_only(self) -> None:
        api = _make_api(
            body={"card_image_back_upload_key": "plugin-uploads/x/y-back.jpg"},
            path_params={"coverage_id": "cov-1"},
        )
        with patch.object(coverage_api, "CoverageEffect") as eff_cls:
            instance = eff_cls.return_value
            instance.update.return_value = MagicMock(
                type=EffectType.UPDATE_COVERAGE, payload=""
            )
            results = api.update_coverage()
        assert len(results) == 2
        eff_cls.assert_called_once()
        kwargs = eff_cls.call_args.kwargs
        assert kwargs["coverage_id"] == "cov-1"
        assert kwargs["card_image_back_upload_key"] == "plugin-uploads/x/y-back.jpg"
        # No clobbering: plan / id_number / etc. not in kwargs
        assert "plan" not in kwargs
        assert "id_number" not in kwargs

    def test_bad_body_returns_400(self) -> None:
        api = _make_api(body={"stack": "MAYBE"}, path_params={"coverage_id": "cov-1"})
        (response,) = api.update_coverage()
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_sdk_validation_error_returns_400(self) -> None:
        api = _make_api(body={"id_number": "M"}, path_params={"coverage_id": "cov-1"})
        with patch.object(coverage_api, "CoverageEffect") as eff_cls:
            eff_cls.return_value.update.side_effect = _sdk_error(
                "Field 'coverage_id' must name an existing coverage."
            )
            (response,) = api.update_coverage()
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "coverage_id" in json.loads(response.content)["field_errors"]


@pytest.mark.parametrize(
    ("method", "effect_cls", "effect_method", "kwargs"),
    [
        (
            "remove_coverage",
            "CoverageEffect",
            "remove",
            {"path_params": {"coverage_id": "x"}},
        ),
        (
            "expire_coverage",
            "CoverageEffect",
            "expire",
            {
                "path_params": {"coverage_id": "x"},
                "body": {"coverage_end_date": "2026-12-31"},
            },
        ),
        (
            "remove_photo",
            "CoverageEffect",
            "remove_photo",
            {"path_params": {"coverage_id": "x", "side": "back"}},
        ),
        (
            "reorder",
            "CoverageReorder",
            "apply",
            {"body": {"patient_id": PATIENT_UUID, "ordering": [{"coverage_id": "x"}]}},
        ),
        (
            "delete_id_card",
            "PatientIdentificationCardEffect",
            "delete",
            {"path_params": {"card_id": "42"}},
        ),
    ],
)
def test_effect_validation_errors_return_400_not_500(
    method: str, effect_cls: str, effect_method: str, kwargs: dict
) -> None:
    """A bad or unknown id makes the SDK raise on the effect call; every
    endpoint turns that into a 400 instead of an unhandled 500."""
    api = _make_api(**kwargs)
    with patch.object(coverage_api, effect_cls) as cls:
        getattr(cls.return_value, effect_method).side_effect = _sdk_error(
            "Field 'coverage_id' must name an existing coverage."
        )
        (response,) = getattr(api, method)()
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert json.loads(response.content)["field_errors"]


class TestRemoveCoverage:
    def test_remove_emits_remove_effect(self) -> None:
        api = _make_api(path_params={"coverage_id": "cov-1"})
        with patch.object(coverage_api, "CoverageEffect") as eff_cls:
            instance = eff_cls.return_value
            instance.remove.return_value = MagicMock(type=EffectType.REMOVE_COVERAGE)
            results = api.remove_coverage()
        assert eff_cls.call_args.kwargs["coverage_id"] == "cov-1"
        instance.remove.assert_called_once()
        assert results[-1].status_code == HTTPStatus.ACCEPTED


class TestExpireCoverage:
    def test_missing_end_date_returns_400(self) -> None:
        api = _make_api(body={}, path_params={"coverage_id": "cov-1"})
        (response,) = api.expire_coverage()
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_bad_date_returns_400(self) -> None:
        api = _make_api(
            body={"coverage_end_date": "not-a-date"},
            path_params={"coverage_id": "cov-1"},
        )
        (response,) = api.expire_coverage()
        assert response.status_code == HTTPStatus.BAD_REQUEST
        body = json.loads(response.content)
        # Plain words, not Python's "Invalid isoformat string" text.
        assert "isoformat" not in body["error"]
        assert "YYYY-MM-DD" in body["error"]
        assert body["field_errors"]["coverage_end_date"] == body["error"]

    def test_non_string_date_returns_plain_400(self) -> None:
        api = _make_api(
            body={"coverage_end_date": 20261231}, path_params={"coverage_id": "cov-1"}
        )
        (response,) = api.expire_coverage()
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "YYYY-MM-DD" in json.loads(response.content)["error"]

    def test_end_before_start_shows_server_reason(self) -> None:
        """The SDK's date-order reason is shown, not a generic failure."""
        reason = "The coverage start date must be on or before its end date."
        api = _make_api(
            body={"coverage_end_date": "2020-01-01"},
            path_params={"coverage_id": "cov-1"},
        )
        with patch.object(coverage_api, "CoverageEffect") as eff_cls:
            eff_cls.return_value.expire.side_effect = _sdk_error(reason)
            (response,) = api.expire_coverage()
        assert response.status_code == HTTPStatus.BAD_REQUEST
        body = json.loads(response.content)
        assert body["error"] == reason
        assert body["field_errors"] == {"coverage_end_date": reason}

    def test_expire_emits_effect(self) -> None:
        api = _make_api(
            body={"coverage_end_date": "2026-12-31"},
            path_params={"coverage_id": "cov-1"},
        )
        with patch.object(coverage_api, "CoverageEffect") as eff_cls:
            instance = eff_cls.return_value
            instance.expire.return_value = MagicMock(type=EffectType.EXPIRE_COVERAGE)
            results = api.expire_coverage()
        instance.expire.assert_called_once_with(coverage_end_date=date(2026, 12, 31))
        assert results[-1].status_code == HTTPStatus.ACCEPTED


class TestRemovePhoto:
    def test_invalid_side_returns_400(self) -> None:
        api = _make_api(path_params={"coverage_id": "cov-1", "side": "middle"})
        (response,) = api.remove_photo()
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_front_side_emits_effect(self) -> None:
        api = _make_api(path_params={"coverage_id": "cov-1", "side": "front"})
        with patch.object(coverage_api, "CoverageEffect") as eff_cls:
            instance = eff_cls.return_value
            instance.remove_photo.return_value = MagicMock(
                type=EffectType.REMOVE_COVERAGE_PHOTO
            )
            results = api.remove_photo()
        instance.remove_photo.assert_called_once_with(PhotoSide.FRONT)
        assert results[-1].status_code == HTTPStatus.ACCEPTED


class TestReorder:
    def test_missing_inputs_returns_400(self) -> None:
        api = _make_api(body={"ordering": []})
        (response,) = api.reorder()
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_reorder_emits_effect(self) -> None:
        api = _make_api(
            body={
                "patient_id": PATIENT_UUID,
                "ordering": [
                    {"coverage_id": "a", "coverage_rank": 1, "stack": "IN_USE"},
                    {"coverage_id": "b", "coverage_rank": 2, "stack": "IN_USE"},
                ],
            }
        )
        with patch.object(coverage_api, "CoverageReorder") as cls:
            instance = cls.return_value
            instance.apply.return_value = MagicMock(type=EffectType.REORDER_COVERAGE)
            results = api.reorder()
        cls.assert_called_once()
        kwargs = cls.call_args.kwargs
        assert kwargs["patient_id"] == PATIENT_UUID
        assert len(kwargs["ordering"]) == 2
        assert results[-1].status_code == HTTPStatus.ACCEPTED


class TestUploadCards:
    def test_missing_files_returns_400(self) -> None:
        api = _make_api(form_parts=[])
        (response,) = api.upload_cards()
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_ignores_non_file_fields(self) -> None:
        api = _make_api(form_parts=[StringFormPart("note", "hi")])
        (response,) = api.upload_cards()
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_any_failed_part_fails_the_upload(self) -> None:
        """A failed side must not be dropped silently while the other saves."""
        api = _make_api(
            form_parts=[
                _stored("front", key="plugin-uploads/x/front.jpg"),
                _stored("back", error="s3_upload_failed"),
            ]
        )
        (response,) = api.upload_cards()
        assert response.status_code == HTTPStatus.BAD_GATEWAY
        body = json.loads(response.content)
        assert body["failures"] == {"back": "s3_upload_failed"}
        assert "keys" not in body

    def test_returns_keys_for_coverage_parts(self) -> None:
        """Legacy coverage flow uses 'front'/'back' field names."""
        api = _make_api(
            form_parts=[
                _stored("front", key="plugin-uploads/x/front.jpg"),
                _stored("back", key="plugin-uploads/x/back.jpg"),
            ]
        )
        (response,) = api.upload_cards()
        body = json.loads(response.content)
        assert body["keys"] == {
            "front": "plugin-uploads/x/front.jpg",
            "back": "plugin-uploads/x/back.jpg",
        }
        assert body["front_key"] == "plugin-uploads/x/front.jpg"
        assert body["back_key"] == "plugin-uploads/x/back.jpg"

    def test_returns_keys_for_arbitrary_field_name(self) -> None:
        """ID card flow sends a single 'image' part; endpoint accepts any name."""
        api = _make_api(
            form_parts=[_stored("image", key="plugin-uploads/x/license.jpg")]
        )
        (response,) = api.upload_cards()
        body = json.loads(response.content)
        assert body["keys"] == {"image": "plugin-uploads/x/license.jpg"}
        assert body["front_key"] is None
        assert body["back_key"] is None


class TestIdCardEndpoints:
    def test_data_missing_patient_id_returns_400(self) -> None:
        api = _make_api(query_params={})
        (response,) = api.id_cards_data()
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_data_unknown_patient_returns_404(self) -> None:
        api = _make_api(query_params={"patient_id": PATIENT_UUID})
        with patch.object(coverage_api, "Patient") as patient_cls:
            patient_cls.DoesNotExist = Exception
            patient_cls.objects.get.side_effect = patient_cls.DoesNotExist
            (response,) = api.id_cards_data()
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_data_lists_cards(self) -> None:
        api = _make_api(query_params={"patient_id": PATIENT_UUID})
        card = SimpleNamespace(
            dbid=42, title=None, active=True, image_url="https://img"
        )
        with (
            patch.object(coverage_api, "Patient") as patient_cls,
            patch.object(coverage_api, "PatientIdentificationCard") as card_cls,
        ):
            patient_cls.objects.get.return_value = SimpleNamespace(id=PATIENT_UUID)
            card_cls.objects.filter.return_value.order_by.return_value = [card]
            (response,) = api.id_cards_data()
        body = json.loads(response.content)
        assert body["id_cards"] == [
            {"id": 42, "title": "", "active": True, "image_url": "https://img"}
        ]

    def test_create_id_card_sdk_error_returns_400(self) -> None:
        api = _make_api(
            body={"patient_id": PATIENT_UUID, "image_upload_key": "elsewhere/x.jpg"}
        )
        with patch.object(coverage_api, "PatientIdentificationCardEffect") as eff_cls:
            eff_cls.return_value.create.side_effect = _sdk_error(
                "Field 'image_upload_key' must start with 'plugin-uploads/'."
            )
            (response,) = api.create_id_card()
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "image_upload_key" in json.loads(response.content)["field_errors"]

    def test_update_id_card_sdk_error_returns_400(self) -> None:
        api = _make_api(body={"active": False}, path_params={"card_id": "42"})
        with patch.object(coverage_api, "PatientIdentificationCardEffect") as eff_cls:
            eff_cls.return_value.update.side_effect = _sdk_error(
                "Field 'card_id' is unknown."
            )
            (response,) = api.update_id_card()
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_create_id_card_missing_image_returns_400(self) -> None:
        api = _make_api(body={"patient_id": PATIENT_UUID, "title": "Driver license"})
        (response,) = api.create_id_card()
        assert response.status_code == HTTPStatus.BAD_REQUEST
        body = json.loads(response.content)
        assert body["field_errors"].get("image")

    def test_create_id_card_missing_patient_returns_400(self) -> None:
        api = _make_api(body={"image_upload_key": "plugin-uploads/x/license.jpg"})
        (response,) = api.create_id_card()
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_create_id_card_emits_effect(self) -> None:
        api = _make_api(
            body={
                "patient_id": PATIENT_UUID,
                "image_upload_key": "plugin-uploads/x/license.jpg",
                "title": "Driver license",
                "active": True,
            }
        )
        with patch.object(coverage_api, "PatientIdentificationCardEffect") as eff_cls:
            instance = eff_cls.return_value
            instance.create.return_value = MagicMock(
                type=EffectType.CREATE_PATIENT_IDENTIFICATION_CARD
            )
            results = api.create_id_card()
        eff_cls.assert_called_once()
        kwargs = eff_cls.call_args.kwargs
        assert kwargs["patient_id"] == PATIENT_UUID
        assert kwargs["image_upload_key"] == "plugin-uploads/x/license.jpg"
        assert kwargs["title"] == "Driver license"
        assert results[-1].status_code == HTTPStatus.ACCEPTED

    def test_update_id_card_bad_id_returns_400(self) -> None:
        api = _make_api(body={"title": "x"}, path_params={"card_id": "not-a-number"})
        (response,) = api.update_id_card()
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_id_card_with_new_image(self) -> None:
        api = _make_api(
            body={
                "image_upload_key": "plugin-uploads/x/renewed.jpg",
                "title": "Renewed",
            },
            path_params={"card_id": "42"},
        )
        with patch.object(coverage_api, "PatientIdentificationCardEffect") as eff_cls:
            instance = eff_cls.return_value
            instance.update.return_value = MagicMock(
                type=EffectType.UPDATE_PATIENT_IDENTIFICATION_CARD
            )
            results = api.update_id_card()
        kwargs = eff_cls.call_args.kwargs
        assert kwargs["card_id"] == 42
        assert kwargs["image_upload_key"] == "plugin-uploads/x/renewed.jpg"
        assert kwargs["title"] == "Renewed"
        assert results[-1].status_code == HTTPStatus.ACCEPTED

    def test_delete_id_card_emits_effect(self) -> None:
        api = _make_api(path_params={"card_id": "42"})
        with patch.object(coverage_api, "PatientIdentificationCardEffect") as eff_cls:
            instance = eff_cls.return_value
            instance.delete.return_value = MagicMock(
                type=EffectType.DELETE_PATIENT_IDENTIFICATION_CARD
            )
            results = api.delete_id_card()
        kwargs = eff_cls.call_args.kwargs
        assert kwargs["card_id"] == 42
        instance.delete.assert_called_once()
        assert results[-1].status_code == HTTPStatus.ACCEPTED

    def test_delete_id_card_bad_id_returns_400(self) -> None:
        api = _make_api(path_params={"card_id": "not-a-number"})
        (response,) = api.delete_id_card()
        assert response.status_code == HTTPStatus.BAD_REQUEST
