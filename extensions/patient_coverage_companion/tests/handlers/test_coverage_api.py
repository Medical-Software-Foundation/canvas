"""Tests for the CoverageAPI SimpleAPI handler."""

import json
from datetime import date
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from canvas_generated.messages.effects_pb2 import EffectType

from patient_coverage_companion.handlers import coverage_api
from patient_coverage_companion.handlers.coverage_api import (
    CoverageAPI,
    _build_effect_fields,
    _parse_date,
)

STAFF_UUID = "00000000-0000-0000-0000-000000000001"
PATIENT_UUID = "00000000-0000-0000-0000-0000000000aa"


def _make_api(
    query_params: dict | None = None,
    body: dict | None = None,
    form_data: list | None = None,
    headers: dict | None = None,
) -> CoverageAPI:
    """Build a CoverageAPI instance with a stubbed request — no auth flow,
    matches the pattern used by the reference companion plugin tests."""
    api = CoverageAPI.__new__(CoverageAPI)
    api.request = SimpleNamespace(
        headers=headers or {"canvas-logged-in-user-id": STAFF_UUID},
        query_params=query_params or {},
        json=lambda: body,
        form_data=lambda: form_data or [],
    )
    return api


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


class TestPayersSearch:
    def test_short_query_returns_empty(self) -> None:
        api = _make_api(query_params={"q": "a"})
        (response,) = api.payers_search()
        body = json.loads(response.content)
        assert body == {"results": []}


# ---------- coverage CRUD endpoints ----------


class TestCreateCoverage:
    def test_missing_patient_id_returns_400(self) -> None:
        api = _make_api(body={"issuer_id": "x"})
        (response,) = api.create_coverage()
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_create_emits_create_effect(self) -> None:
        """A valid create body produces a CREATE_COVERAGE effect plus a 202
        JSON acknowledgement."""
        api = _make_api(
            body={
                "patient_id": PATIENT_UUID,
                "issuer_id": "issuer-uuid",
                "coverage_rank": 1,
                "plan_type": "commercial",
                "id_number": "MEM-1",
                "patient_relationship_to_subscriber": "18",
            }
        )
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


class TestUpdateCoverage:
    def test_update_with_image_only(self) -> None:
        api = _make_api(
            body={
                "card_image_back_upload_key": "plugin-uploads/x/y-back.jpg",
            }
        )
        with patch.object(coverage_api, "CoverageEffect") as eff_cls:
            instance = eff_cls.return_value
            instance.update.return_value = MagicMock(
                type=EffectType.UPDATE_COVERAGE, payload=""
            )
            results = api.update_coverage("cov-1")
        assert len(results) == 2
        eff_cls.assert_called_once()
        kwargs = eff_cls.call_args.kwargs
        assert kwargs["coverage_id"] == "cov-1"
        assert kwargs["card_image_back_upload_key"] == "plugin-uploads/x/y-back.jpg"
        # No clobbering: plan / id_number / etc. not in kwargs
        assert "plan" not in kwargs
        assert "id_number" not in kwargs


class TestRemoveCoverage:
    def test_remove_emits_remove_effect(self) -> None:
        api = _make_api()
        with patch.object(coverage_api, "CoverageEffect") as eff_cls:
            instance = eff_cls.return_value
            instance.remove.return_value = MagicMock(type=EffectType.REMOVE_COVERAGE)
            results = api.remove_coverage("cov-1")
        assert eff_cls.call_args.kwargs["coverage_id"] == "cov-1"
        instance.remove.assert_called_once()
        assert results[-1].status_code == HTTPStatus.ACCEPTED


class TestExpireCoverage:
    def test_missing_end_date_returns_400(self) -> None:
        api = _make_api(body={})
        (response,) = api.expire_coverage("cov-1")
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_bad_date_returns_400(self) -> None:
        api = _make_api(body={"coverage_end_date": "not-a-date"})
        (response,) = api.expire_coverage("cov-1")
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_expire_emits_effect(self) -> None:
        api = _make_api(body={"coverage_end_date": "2026-12-31"})
        with patch.object(coverage_api, "CoverageEffect") as eff_cls:
            instance = eff_cls.return_value
            instance.expire.return_value = MagicMock(type=EffectType.EXPIRE_COVERAGE)
            results = api.expire_coverage("cov-1")
        instance.expire.assert_called_once_with(coverage_end_date=date(2026, 12, 31))
        assert results[-1].status_code == HTTPStatus.ACCEPTED


class TestRemovePhoto:
    def test_invalid_side_returns_400(self) -> None:
        api = _make_api()
        (response,) = api.remove_photo("cov-1", "middle")
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_front_side_emits_effect(self) -> None:
        api = _make_api()
        with patch.object(coverage_api, "CoverageEffect") as eff_cls:
            instance = eff_cls.return_value
            instance.remove_photo.return_value = MagicMock(
                type=EffectType.REMOVE_COVERAGE_PHOTO
            )
            results = api.remove_photo("cov-1", "front")
        instance.remove_photo.assert_called_once_with("FRONT")
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
        api = _make_api(form_data=[])
        (response,) = api.upload_cards()
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_returns_keys_for_supplied_parts(self) -> None:
        front_part = SimpleNamespace(name="front", key="plugin-uploads/x/front.jpg")
        back_part = SimpleNamespace(name="back", key="plugin-uploads/x/back.jpg")
        api = _make_api(form_data=[front_part, back_part])
        (response,) = api.upload_cards()
        body = json.loads(response.content)
        assert body == {
            "front_key": "plugin-uploads/x/front.jpg",
            "back_key": "plugin-uploads/x/back.jpg",
        }
