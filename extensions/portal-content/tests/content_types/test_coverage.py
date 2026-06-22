"""Tests for SDK Coverage-backed insurance listing."""

from datetime import date
from unittest.mock import MagicMock, patch

from portal_content.content_types import coverage


def _coverage(**kwargs):
    cov = MagicMock(**{k: v for k, v in kwargs.items() if k != "issuer_name"})
    issuer = MagicMock()
    issuer.name = kwargs.get("issuer_name")  # set explicitly: MagicMock(name=...) is reserved
    cov.issuer = issuer if kwargs.get("issuer_name") is not None else None
    return cov


@patch("portal_content.content_types.coverage.Coverage")
def test_list_coverages_maps_fields_and_filters_in_use_active(cov_model):
    cov = _coverage(
        issuer_name="Aetna",
        id_number="MEM123",
        group="GRP9",
        plan_type="ppo_plan",
        coverage_rank=1,
        coverage_start_date=date(2026, 1, 1),
        coverage_end_date=None,
    )
    cov_model.objects.filter.return_value.select_related.return_value.order_by.return_value = [cov]

    result = coverage.list_coverages("patient-1")

    assert result == [
        {
            "payer_name": "Aetna",
            "member_id": "MEM123",
            "group_number": "GRP9",
            "plan_type": "Ppo Plan",
            "rank": "Primary",
            "start_date": "January 01, 2026",
            "end_date": None,
        }
    ]
    cov_model.objects.filter.assert_called_once_with(
        patient__id="patient-1", stack="IN_USE", state="active"
    )


@patch("portal_content.content_types.coverage.Coverage")
def test_list_coverages_handles_missing_issuer_and_rank_and_plan(cov_model):
    cov = _coverage(
        issuer_name=None,
        id_number=None,
        group=None,
        plan_type=None,
        coverage_rank=7,
        coverage_start_date=None,
        coverage_end_date=date(2026, 12, 31),
    )
    cov_model.objects.filter.return_value.select_related.return_value.order_by.return_value = [cov]

    result = coverage.list_coverages("p")

    assert result[0]["payer_name"] is None
    assert result[0]["plan_type"] is None
    assert result[0]["rank"] is None  # 7 not in RANK_LABELS
    assert result[0]["start_date"] is None
    assert result[0]["end_date"] == "December 31, 2026"


@patch("portal_content.content_types.coverage.Coverage")
def test_list_coverages_empty(cov_model):
    cov_model.objects.filter.return_value.select_related.return_value.order_by.return_value = []
    assert coverage.list_coverages("p") == []
