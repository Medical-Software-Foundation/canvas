"""Tests for the field mapping profile singleton and its resolver.

These hit the Django ORM, so they rely on the autouse transaction(db) fixture the
pytest-canvas plugin provides, no django_db marker needed. The loader contract is
that it always returns a usable state, resolving an unset or stale pointer against
whether the field map secret is present, and sanitizing corrupt Custom rows. See
journal cnv-941/049.
"""

from __future__ import annotations

from datetime import datetime, timezone

from salesforce_to_canvas_integration.models.field_mapping_settings import (
    PROFILE_CUSTOM,
    PROFILE_DEFAULT,
    PROFILE_SECRET,
    SINGLETON_KEY,
    FieldMappingRecord,
    load_field_mapping_state,
    save_field_mapping,
)

_SECRET = {"SF_FIELD_MAPPING_JSON": '{"FirstName": {"target": "first_name"}}'}
_NO_SECRET: dict[str, str] = {}


def _now() -> datetime:
    return datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)


def test_no_row_no_secret_resolves_to_default() -> None:
    state = load_field_mapping_state(_NO_SECRET)
    assert state.profile == PROFILE_DEFAULT
    assert state.custom == ()


def test_no_row_with_secret_resolves_to_secret() -> None:
    assert load_field_mapping_state(_SECRET).profile == PROFILE_SECRET


def test_stored_custom_profile_and_rows_honored() -> None:
    save_field_mapping(
        profile=PROFILE_CUSTOM,
        custom_mapping=[
            {"salesforce_field": "Contact_First__c", "canvas_target": "first_name"},
            {"salesforce_field": "", "canvas_target": "email"},
        ],
        now=_now(),
    )
    state = load_field_mapping_state(_NO_SECRET)
    assert state.profile == PROFILE_CUSTOM
    assert state.custom == (("Contact_First__c", "first_name"), ("", "email"))


def test_stale_secret_pointer_without_secret_falls_to_default() -> None:
    save_field_mapping(profile=PROFILE_SECRET, custom_mapping=[], now=_now())
    # With no secret present the stored Secret pointer cannot stand.
    assert load_field_mapping_state(_NO_SECRET).profile == PROFILE_DEFAULT
    # The same row resolves to Secret again once the secret is back.
    assert load_field_mapping_state(_SECRET).profile == PROFILE_SECRET


def test_invalid_stored_profile_resolves_against_secret() -> None:
    FieldMappingRecord.objects.create(
        singleton_key=SINGLETON_KEY, profile="bogus", custom_mapping=[]
    )
    assert load_field_mapping_state(_NO_SECRET).profile == PROFILE_DEFAULT
    assert load_field_mapping_state(_SECRET).profile == PROFILE_SECRET


def test_corrupt_custom_rows_are_sanitized() -> None:
    FieldMappingRecord.objects.create(
        singleton_key=SINGLETON_KEY,
        profile=PROFILE_CUSTOM,
        custom_mapping=[
            "nope",
            {"canvas_target": ""},
            {"salesforce_field": "X"},
            {"salesforce_field": 5, "canvas_target": "email"},
            {"salesforce_field": "Y", "canvas_target": "phone"},
        ],
    )
    state = load_field_mapping_state(_NO_SECRET)
    # Only rows with a non empty string target survive, a non string Salesforce
    # field coerces to empty, the do not sync marker.
    assert state.custom == (("", "email"), ("Y", "phone"))


def test_non_list_custom_storage_yields_empty() -> None:
    FieldMappingRecord.objects.create(
        singleton_key=SINGLETON_KEY, profile=PROFILE_CUSTOM, custom_mapping={"bad": 1}
    )
    assert load_field_mapping_state(_NO_SECRET).custom == ()


def test_save_upserts_a_single_row() -> None:
    save_field_mapping(profile=PROFILE_CUSTOM, custom_mapping=[], now=_now())
    save_field_mapping(
        profile=PROFILE_DEFAULT,
        custom_mapping=[{"salesforce_field": "A", "canvas_target": "first_name"}],
        now=_now(),
    )
    assert FieldMappingRecord.objects.filter(singleton_key=SINGLETON_KEY).count() == 1
    state = load_field_mapping_state(_NO_SECRET)
    assert state.profile == PROFILE_DEFAULT
    assert state.custom == (("A", "first_name"),)
