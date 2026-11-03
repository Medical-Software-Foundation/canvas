"""Import validation, search matching and result merging."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from canvas_sdk.effects import EffectType

from preferred_referrals import directory
from preferred_referrals.directory import (
    MAX_SEARCH_MATCHES,
    PREFERRED_ANNOTATION,
    import_effects,
    matching_preferred,
    merge_results,
    serialize_provider,
    validate_row,
)


def _provider(
    dbid, first="Lakeside Cardiology", last="", specialty="Cardiology", **extra
):
    provider = MagicMock()
    provider.dbid = dbid
    provider.id = f"00000000-0000-0000-0000-{dbid:012d}"
    provider.first_name = first
    provider.last_name = last
    provider.specialty = specialty
    provider.practice_name = extra.get("practice_name", "")
    provider.business_address = extra.get("business_address", "1 Main St")
    provider.business_phone = extra.get("business_phone", "")
    provider.business_fax = extra.get("business_fax", "")
    provider.npi = extra.get("npi", "")
    provider.is_active = extra.get("is_active", True)
    text = f"{first} {last}".strip()
    provider.as_search_result.side_effect = lambda annotations=None: {
        "text": text,
        "value": dbid,
        "annotations": list(annotations or []),
        "extra": {"contact": {"service_provider_id": dbid}},
    }
    return provider


# --- matching ---------------------------------------------------------------


def test_empty_term_matches_nothing_and_queries_nothing():
    with patch.object(directory, "ServiceProvider") as model:
        assert matching_preferred("   ") == []
        assert matching_preferred(None) == []  # type: ignore[arg-type]
    model.objects.filter.assert_not_called()


def test_matching_queries_each_field_for_active_customer_managed_only():
    with patch.object(directory, "ServiceProvider") as model:
        chain = model.objects.filter.return_value.order_by.return_value
        chain.__getitem__.return_value = []
        matching_preferred(" cardio ")

    calls = model.objects.filter.call_args_list
    assert len(calls) == len(directory.SEARCHABLE_FIELDS)
    for call, field in zip(calls, directory.SEARCHABLE_FIELDS, strict=True):
        assert call.kwargs == {
            "is_customer_managed": True,
            "is_active": True,
            f"{field}__icontains": "cardio",
        }
    assert chain.__getitem__.call_args.args[0] == slice(None, MAX_SEARCH_MATCHES)


def test_matching_unions_fields_without_duplicates_and_caps():
    a, b = _provider(1), _provider(2)
    many = [_provider(100 + i) for i in range(MAX_SEARCH_MATCHES)]
    with patch.object(directory, "ServiceProvider") as model:
        chain = model.objects.filter.return_value.order_by.return_value
        chain.__getitem__.side_effect = [[a, b], [b], [], many]
        result = matching_preferred("x")
    assert result[:2] == [a, b]
    assert len(result) == MAX_SEARCH_MATCHES


# --- merging ----------------------------------------------------------------


def test_preferred_come_first_and_are_annotated():
    merged = merge_results([_provider(1)], [{"text": "Someone Else", "extra": {}}])
    assert merged[0]["value"] == 1
    assert merged[0]["annotations"] == [PREFERRED_ANNOTATION]
    assert merged[1]["text"] == "Someone Else"


def test_directory_rows_for_the_same_provider_are_dropped():
    directory_rows = [
        {"text": "Other", "extra": {"contact": {"service_provider_id": 1}}},
        {"text": "  lakeside cardiology ", "extra": None},
        {"text": "Keep Me"},
        {"text": None},
    ]
    merged = merge_results([_provider(1)], directory_rows)
    assert [row.get("text") for row in merged] == [
        "Lakeside Cardiology",
        "Keep Me",
        None,
    ]


def test_missing_directory_results_are_fine():
    assert len(merge_results([_provider(1)], None)) == 1  # type: ignore[arg-type]


# --- validation -------------------------------------------------------------


def _row(**overrides):
    row = {
        "first_name": "Lakeside Cardiology",
        "specialty": "Cardiology",
        "business_address": "1 Main St",
    }
    row.update(overrides)
    return row


def test_a_good_row_is_trimmed_and_drops_empty_optionals():
    fields, error = validate_row(
        _row(first_name="  Lakeside  ", last_name="", npi="1234567890")
    )
    assert error is None
    assert fields == {
        "first_name": "Lakeside",
        "specialty": "Cardiology",
        "business_address": "1 Main St",
        "npi": "1234567890",
    }


def test_non_object_rows_are_rejected():
    assert validate_row(["a", "b"]) == (None, "Row is not an object.")


def test_required_columns_are_reported_by_name():
    fields, error = validate_row({"first_name": "X", "specialty": None})
    assert fields is None
    assert error == "Missing specialty, business_address."


def test_overlong_fields_are_rejected():
    _, error = validate_row(_row(notes="x" * (directory.MAX_FIELD_LENGTH + 1)))
    assert error == "Too long: notes."


def test_bad_npi_is_rejected():
    for npi in ("12345", "12345678901", "abcdefghij"):
        _, error = validate_row(_row(npi=npi))
        assert error == "NPI must be exactly 10 digits."


def test_unknown_columns_are_ignored():
    fields, _ = validate_row(_row(favourite_colour="blue"))
    assert "favourite_colour" not in fields


# --- import effects -----------------------------------------------------------


def test_import_builds_one_create_per_good_row_and_numbers_errors():
    effects, errors = import_effects(
        [_row(), {"first_name": "x"}, _row(first_name="Hilltop Imaging")]
    )
    assert [EffectType.Name(effect.type) for effect in effects] == [
        "CREATE_SERVICE_PROVIDER",
        "CREATE_SERVICE_PROVIDER",
    ]
    assert json.loads(effects[1].payload)["data"]["first_name"] == "Hilltop Imaging"
    assert errors == [{"row": 2, "error": "Missing specialty, business_address."}]


def test_import_does_not_send_optional_fields_that_were_blank():
    effects, _ = import_effects([_row(last_name="", practice_name="Lakeside Group")])
    data = json.loads(effects[0].payload)["data"]
    assert data["practice_name"] == "Lakeside Group"
    assert "last_name" not in data


# --- serialization ------------------------------------------------------------


def test_serialize_provider_handles_blank_fields():
    provider = SimpleNamespace(
        id="abc",
        first_name="Lakeside",
        last_name=None,
        practice_name=None,
        specialty=None,
        business_address=None,
        business_phone=None,
        business_fax=None,
        npi=None,
        is_active=0,
    )
    assert serialize_provider(provider, 3) == {
        "id": "abc",
        "name": "Lakeside",
        "practice_name": "",
        "specialty": "",
        "business_address": "",
        "business_phone": "",
        "business_fax": "",
        "npi": "",
        "is_active": False,
        "referrals": 3,
    }


def test_preferred_providers_is_scoped_to_customer_managed():
    with patch.object(directory, "ServiceProvider") as model:
        directory.preferred_providers()
    model.objects.filter.assert_called_once_with(is_customer_managed=True)
