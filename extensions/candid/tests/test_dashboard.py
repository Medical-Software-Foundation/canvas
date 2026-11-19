"""Tests for the dashboard API's claim listing: paging, error filtering, serialization."""

import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

from candid.api.dashboard import (
    PAGE_SIZE,
    CandidDashboardAPI,
    _get_filter_options,
    _is_error_or_denied,
    _serialize_claim,
)
from candid.effect_helpers import (
    META_CLAIM_STATUS,
    META_LAST_SYNC,
    META_SUBMISSION_ERROR,
    META_SUBMITTED_AT,
)


def _meta(key: str, value: str) -> MagicMock:
    m = MagicMock()
    m.key = key
    m.value = value
    return m


def _claim(
    claim_id: str = "claim-1",
    dbid: int = 1,
    status: str = "",
    error: str | None = None,
    patient: tuple[str | None, str | None] | None = ("Test", "Patient"),
    queue: str | None = "Filed Awaiting Response",
    submitted_at: str = "2026-01-15T00:00:00+00:00",
    last_sync: str = "",
) -> MagicMock:
    claim = MagicMock()
    claim.id = claim_id
    claim.dbid = dbid
    meta = [_meta(META_SUBMITTED_AT, submitted_at), _meta(META_CLAIM_STATUS, status)]
    if last_sync:
        meta.append(_meta(META_LAST_SYNC, last_sync))
    if error is not None:
        meta.append(_meta(META_SUBMISSION_ERROR, error))
    claim.metadata.all.return_value = meta
    if patient is None:
        claim.patient = None
    else:
        claim.patient.id = f"pat-{claim_id}"
        claim.patient.first_name, claim.patient.last_name = patient
    if queue is None:
        claim.current_queue = None
    else:
        claim.current_queue.display_name = queue
    return claim


def _handler(params: dict) -> CandidDashboardAPI:
    handler = CandidDashboardAPI.__new__(CandidDashboardAPI)
    handler.secrets = {}  # dashboard allow-list unset: everyone allowed
    handler.request = MagicMock()
    handler.request.headers.get.side_effect = lambda k, d=None: (
        "staff-1" if k == "canvas-logged-in-user-id" else d
    )
    handler.request.query_params.get.side_effect = lambda k, d="": params.get(k, d)
    return handler


def _base_qs(claims: list) -> MagicMock:
    qs = MagicMock()
    qs.__iter__.side_effect = lambda: iter(claims)
    qs.count.return_value = len(claims)
    qs.__getitem__.side_effect = lambda s: claims[s]
    return qs


def _run(params: dict, claims: list, filter_options: dict | None = None):
    handler = _handler(params)
    base_qs = _base_qs(claims)
    with (
        patch("candid.api.dashboard.Claim") as MockClaim,
        patch(
            "candid.api.dashboard._get_filter_options",
            return_value=filter_options or {"statuses": [], "queues": []},
        ) as mock_filters,
    ):
        (
            MockClaim.objects.filter.return_value.select_related.return_value.prefetch_related.return_value.distinct.return_value.order_by.return_value
        ) = base_qs
        effects = handler.get()
    assert effects[0].status_code == HTTPStatus.OK
    return json.loads(effects[0].content), base_qs, mock_filters


# --- GET /dashboard ---


def test_first_page_returns_claims_and_filter_options():
    claims = [_claim("c1", dbid=11, status="paid"), _claim("c2", dbid=12)]
    options = {"statuses": ["paid"], "queues": ["Filed Awaiting Response"]}

    body, base_qs, mock_filters = _run({}, claims, options)

    assert [c["id"] for c in body["claims"]] == ["c1", "c2"]
    assert body["page"] == 1
    assert body["page_size"] == PAGE_SIZE
    assert body["total"] == 2
    assert body["total_pages"] == 1
    assert body["filter_options"] == options
    mock_filters.assert_called_once_with(base_qs)


def test_paging_slices_queryset_by_page_size():
    claims = [_claim(f"c{i}", dbid=i) for i in range(PAGE_SIZE + 5)]

    body, _, _ = _run({"page": "2"}, claims)

    assert body["page"] == 2
    assert body["total"] == PAGE_SIZE + 5
    assert body["total_pages"] == 2
    assert [c["id"] for c in body["claims"]] == [f"c{i}" for i in range(PAGE_SIZE, PAGE_SIZE + 5)]


def test_invalid_page_falls_back_to_first_page():
    body, _, _ = _run({"page": "abc"}, [_claim("c1")])
    assert body["page"] == 1
    assert [c["id"] for c in body["claims"]] == ["c1"]


def test_zero_or_negative_page_clamps_to_first_page():
    body, _, _ = _run({"page": "-3"}, [_claim("c1")])
    assert body["page"] == 1


def test_errors_only_keeps_errored_and_denied_claims():
    claims = [
        _claim("ok", status="paid"),
        _claim("err", error=json.dumps({"error": "boom", "date": "2026-01-01"})),
        _claim("denied", status="Finalized_Denied"),
        _claim("cleared-error", error=""),
    ]

    body, base_qs, _ = _run({"errors_only": "true"}, claims)

    assert [c["id"] for c in body["claims"]] == ["err", "denied"]
    assert body["total"] == 2
    assert body["total_pages"] == 1
    # Filtering happens in Python over the full list, not via count()
    base_qs.count.assert_not_called()


def test_page_all_returns_everything_without_filter_options():
    claims = [_claim(f"c{i}") for i in range(PAGE_SIZE + 1)]

    body, _, mock_filters = _run({"page": "all"}, claims)

    assert len(body["claims"]) == PAGE_SIZE + 1
    assert body["page"] == 1
    assert body["page_size"] == PAGE_SIZE + 1
    assert body["total"] == PAGE_SIZE + 1
    assert body["total_pages"] == 1
    assert "filter_options" not in body
    mock_filters.assert_not_called()


def test_page_all_with_errors_only_filters():
    claims = [_claim("ok"), _claim("denied", status="rejected")]

    body, _, _ = _run({"page": "ALL", "errors_only": "1"}, claims)

    assert [c["id"] for c in body["claims"]] == ["denied"]
    assert body["total"] == 1


# --- _serialize_claim ---


def test_serialize_claim_full_fields():
    claim = _claim(
        "c1",
        dbid=42,
        status="denied",
        error=json.dumps({"error": "Missing NPI", "date": "2026-01-02"}),
        patient=("  Test ", " Patient "),
        last_sync="2026-01-20T00:00:00+00:00",
    )

    result = _serialize_claim(claim)

    assert result == {
        "id": "c1",
        "dbid": 42,
        "patient_name": "Test Patient",
        "patient_id": "pat-c1",
        "candid_status": "denied",
        "submitted_at": "2026-01-15T00:00:00+00:00",
        "last_sync_at": "2026-01-20T00:00:00+00:00",
        "current_queue": "Filed Awaiting Response",
        "has_error": True,
        "error_message": "Missing NPI",
        "is_denied": True,
    }


def test_serialize_claim_without_patient_or_queue():
    result = _serialize_claim(_claim("c1", patient=None, queue=None))
    assert result["patient_name"] == "(no patient)"
    assert result["patient_id"] == ""
    assert result["current_queue"] == ""
    assert result["has_error"] is False
    assert result["error_message"] is None
    assert result["is_denied"] is False


def test_serialize_claim_blank_patient_name():
    result = _serialize_claim(_claim("c1", patient=(None, "  ")))
    assert result["patient_name"] == "(unnamed)"


def test_serialize_claim_ignores_non_json_or_errorless_submission_error():
    raw = _serialize_claim(_claim("c1", error="plain text failure"))
    assert raw["has_error"] is False
    empty = _serialize_claim(_claim("c2", error=json.dumps({"error": ""})))
    assert empty["has_error"] is False


# --- _is_error_or_denied ---


def test_is_error_or_denied():
    assert _is_error_or_denied(_claim(error=json.dumps({"error": "x"}))) is True
    assert _is_error_or_denied(_claim(status="FAILED")) is True
    assert _is_error_or_denied(_claim(status="paid")) is False
    assert _is_error_or_denied(_claim(error="not json")) is False


# --- _get_filter_options ---


def test_get_filter_options_returns_sorted_distinct_values():
    base_qs = MagicMock()
    (
        base_qs.exclude.return_value.values_list.return_value.distinct.return_value
    ) = ["Patient Balance", None, "", "Filed Awaiting Response"]

    with patch("canvas_sdk.v1.data.claim.ClaimMetadata") as MockMeta:
        (
            MockMeta.objects.filter.return_value.exclude.return_value.values_list.return_value.distinct.return_value
        ) = ["paid", "denied", "paid"]
        options = _get_filter_options(base_qs)

    assert options == {
        "statuses": ["denied", "paid"],
        "queues": ["Filed Awaiting Response", "Patient Balance"],
    }
    MockMeta.objects.filter.assert_called_once_with(claim__in=base_qs, key=META_CLAIM_STATUS)
    MockMeta.objects.filter.return_value.exclude.assert_called_once_with(value="")
    base_qs.exclude.assert_called_once_with(current_queue__isnull=True)
