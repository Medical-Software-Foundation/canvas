"""Tests for the SyncSettingsRecord singleton and its defaults overlay loader.

These hit the Django ORM, so they rely on the autouse transaction(db) fixture
the pytest-canvas plugin provides, no django_db marker needed. The loader
contract is that it always returns a full SyncSettings, falling back to the
services.sync_rules code defaults for a missing row, a missing key, or a value
that fails its type or membership check.
"""

from __future__ import annotations

from salesforce_to_canvas_integration.models.sync_settings import (
    SINGLETON_KEY,
    SyncSettingsRecord,
    load_sync_settings,
)
from salesforce_to_canvas_integration.services.sync_rules import (
    DELETE_ACTION_TAG_DELETED,
    SyncSettings,
)


def _store(data: dict[str, object]) -> SyncSettingsRecord:
    row: SyncSettingsRecord = SyncSettingsRecord.objects.create(
        singleton_key=SINGLETON_KEY, data=data
    )
    return row


def test_record_round_trips_json_data() -> None:
    """The single data column survives a write and read as a nested dict."""
    payload = {"auto_create": False, "required_fields": ["last_name", "email"]}
    row = _store(payload)

    fetched = SyncSettingsRecord.objects.get(dbid=row.dbid)
    assert fetched.data == payload
    assert fetched.updated_at is not None


def test_loader_returns_full_defaults_when_no_row() -> None:
    """A missing settings row yields a settings object built entirely from defaults."""
    assert load_sync_settings() == SyncSettings()


def test_loader_returns_defaults_when_data_not_a_dict() -> None:
    """A row whose payload is not a dict degrades to defaults rather than raising."""
    SyncSettingsRecord.objects.create(singleton_key=SINGLETON_KEY, data=[])

    assert load_sync_settings() == SyncSettings()


def test_loader_overlays_every_stored_value() -> None:
    """A fully populated row overrides every default."""
    _store(
        {
            "auto_create": False,
            "auto_modify": False,
            "auto_delete": True,
            "delete_action": DELETE_ACTION_TAG_DELETED,
            "required_fields": ["first_name", "last_name"],
            "address_group_integrity": False,
            "validity_checks": False,
        }
    )

    loaded = load_sync_settings()
    assert loaded == SyncSettings(
        auto_create=False,
        auto_modify=False,
        auto_delete=True,
        delete_action=DELETE_ACTION_TAG_DELETED,
        required_fields=("first_name", "last_name"),
        address_group_integrity=False,
        validity_checks=False,
    )


def test_loader_fills_missing_keys_from_defaults() -> None:
    """A partial row keeps its stored keys and defaults the rest."""
    _store({"auto_create": False})

    loaded = load_sync_settings()
    defaults = SyncSettings()
    assert loaded.auto_create is False
    assert loaded.auto_modify == defaults.auto_modify
    assert loaded.auto_delete == defaults.auto_delete
    assert loaded.delete_action == defaults.delete_action
    assert loaded.required_fields == defaults.required_fields
    assert loaded.address_group_integrity == defaults.address_group_integrity
    assert loaded.validity_checks == defaults.validity_checks


def test_loader_rejects_wrong_typed_bool() -> None:
    """A non bool stored under a bool key falls back rather than coercing."""
    _store({"auto_create": "yes", "auto_delete": 1})

    loaded = load_sync_settings()
    defaults = SyncSettings()
    assert loaded.auto_create == defaults.auto_create
    assert loaded.auto_delete == defaults.auto_delete


def test_loader_rejects_unknown_delete_action() -> None:
    """A delete_action outside the known set falls back to the default action."""
    _store({"delete_action": "incinerate"})

    assert load_sync_settings().delete_action == SyncSettings().delete_action


def test_loader_accepts_known_delete_action() -> None:
    _store({"delete_action": DELETE_ACTION_TAG_DELETED})

    assert load_sync_settings().delete_action == DELETE_ACTION_TAG_DELETED


def test_loader_required_fields_preserves_order_and_drops_blanks() -> None:
    """A valid string list is taken as is, with blank entries dropped."""
    _store({"required_fields": ["last_name", "  ", "date_of_birth"]})

    assert load_sync_settings().required_fields == ("last_name", "date_of_birth")


def test_loader_rejects_non_string_required_fields() -> None:
    """A list with a non string entry is rejected whole, falling back to defaults."""
    _store({"required_fields": ["last_name", 7]})

    assert load_sync_settings().required_fields == SyncSettings().required_fields


def test_loader_rejects_empty_required_fields() -> None:
    """An empty or all blank required list falls back to defaults, the safe choice.

    More required fields only ever hold more rows for manual review, never auto
    apply something that would otherwise gate, so defaulting on empty is safe.
    """
    _store({"required_fields": []})

    assert load_sync_settings().required_fields == SyncSettings().required_fields


def test_loader_reads_the_most_recently_stamped_row() -> None:
    """If more than one row exists the loader takes the newest by updated_at."""
    older = _store({"auto_create": True})
    newer = _store({"auto_create": False})
    # auto_now stamps on create in insertion order, and the -dbid tiebreak makes
    # the newest deterministic even when two stamps collide under SQLite.
    assert older.dbid < newer.dbid
    assert load_sync_settings().auto_create is False
