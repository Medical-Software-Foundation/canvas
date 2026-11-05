"""Tests for the namespace backed settings store.

These run against the real PolicySetting model rather than a mock, because the
store's job is entirely the query and field shape underneath it. pytest-canvas
gives every test writable database access with no marker needed, and that
covers the shared Canvas SDK tables, which Django already knows how to create
because they belong to an installed app.

PolicySetting is different. It is a Canvas CustomModel, registered under this
plugin's own app label rather than under any package Django already treats as
an installed app, so ordinary test database setup never creates its table. On
a real instance that table appears when the plugin runner loads the plugin and
generates migrations for its declared namespace, a step plain pytest does not
run. The fixture below reaches for the same real Django schema machinery the
model already uses, asking its schema editor to create exactly the table the
model class describes, once, before any test in this file touches the store.
This is real ORM plumbing, the same call Django's own migrations issue under
the hood, not a mock of the store or the model.
"""

from typing import Any

import pytest
from django.db import connection

from attendance_policy_tracker.canvas.settings_store import NamespaceSettingsStore
from attendance_policy_tracker.models.policy_setting import PolicySetting


@pytest.fixture(scope="session", autouse=True)
def _policy_setting_table(django_db_setup: None, django_db_blocker: Any) -> None:
    """Create the PolicySetting table once for this test session.

    See the module docstring for why this step is needed at all. It runs once
    per session, before any test's own transaction opens, using the database
    blocker pytest-django hands out for exactly this kind of one time setup.
    """
    with django_db_blocker.unblock():
        existing = connection.introspection.table_names()
        if PolicySetting._meta.db_table in existing:
            return
        with connection.schema_editor() as editor:
            editor.create_model(PolicySetting)


def _stored_value(key: str) -> str:
    """The raw value column for one row, read straight from the model."""
    return f"{PolicySetting.objects.get(key=key).value}"


class TestReadWithNothingStored:
    def test_an_empty_namespace_reads_as_an_empty_dict(self) -> None:
        store = NamespaceSettingsStore()

        assert store.read() == {}


class TestWriteCreatesANewRow:
    def test_a_name_not_yet_stored_is_created(self) -> None:
        store = NamespaceSettingsStore()

        store.write({"warning_threshold": "3"})

        assert PolicySetting.objects.filter(key="warning_threshold").count() == 1
        assert _stored_value("warning_threshold") == "3"

    def test_the_created_row_is_visible_through_read(self) -> None:
        store = NamespaceSettingsStore()

        store.write({"warning_threshold": "3"})

        assert store.read() == {"warning_threshold": "3"}


class TestWriteUpdatesAnExistingRow:
    def test_a_name_already_stored_is_updated_in_place(self) -> None:
        store = NamespaceSettingsStore()
        store.write({"warning_threshold": "3"})

        store.write({"warning_threshold": "5"})

        assert PolicySetting.objects.filter(key="warning_threshold").count() == 1
        assert _stored_value("warning_threshold") == "5"

    def test_the_update_is_visible_through_read(self) -> None:
        store = NamespaceSettingsStore()
        store.write({"warning_threshold": "3"})

        store.write({"warning_threshold": "5"})

        assert store.read() == {"warning_threshold": "5"}


class TestAnEmptyValueDeletesTheRow:
    def test_an_empty_value_for_a_stored_name_removes_its_row(self) -> None:
        store = NamespaceSettingsStore()
        store.write({"warning_threshold": "3"})

        store.write({"warning_threshold": ""})

        assert PolicySetting.objects.filter(key="warning_threshold").count() == 0
        assert store.read() == {}

    def test_a_whitespace_only_value_for_a_stored_name_also_removes_its_row(
        self,
    ) -> None:
        store = NamespaceSettingsStore()
        store.write({"warning_threshold": "3"})

        store.write({"warning_threshold": "   "})

        assert PolicySetting.objects.filter(key="warning_threshold").count() == 0
        assert store.read() == {}

    def test_an_empty_value_for_a_name_never_stored_creates_no_row(self) -> None:
        store = NamespaceSettingsStore()

        store.write({"warning_threshold": ""})

        assert PolicySetting.objects.filter(key="warning_threshold").count() == 0
        assert store.read() == {}


class TestABatchMixesEveryBranch:
    def test_a_single_write_can_create_update_and_delete_together(self) -> None:
        store = NamespaceSettingsStore()
        store.write({"warning_threshold": "3", "discharge_after_days": "30"})

        store.write(
            {
                "warning_threshold": "5",  # update
                "discharge_after_days": "",  # delete
                "grace_period_minutes": "10",  # create
            }
        )

        assert store.read() == {
            "warning_threshold": "5",
            "grace_period_minutes": "10",
        }


class TestValuesAreReturnedAsText:
    def test_a_numeric_looking_value_round_trips_as_a_string(self) -> None:
        store = NamespaceSettingsStore()

        store.write({"warning_threshold": "3"})

        value = store.read()["warning_threshold"]
        assert value == "3"
        assert isinstance(value, str)

    def test_a_non_string_value_is_stored_as_its_text_form(self) -> None:
        store = NamespaceSettingsStore()

        store.write({"warning_threshold": 3})  # type: ignore[dict-item]

        value = store.read()["warning_threshold"]
        assert value == "3"
        assert isinstance(value, str)
