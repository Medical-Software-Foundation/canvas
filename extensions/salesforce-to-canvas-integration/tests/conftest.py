"""Shared pytest fixtures and helpers."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_django.plugin import DjangoDbBlocker


class FakeCache:
    """Tiny in-memory stand-in for :class:`canvas_sdk.caching.base.Cache`.

    Lives in conftest so tests can share it without cross-module imports.
    """

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    def get(self, key: str, default: Any | None = None) -> Any:
        return self.store.get(key, default)

    def set(self, key: str, value: Any, timeout_seconds: int | None = None) -> None:
        self.store[key] = value

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.fixture()
def fake_cache() -> FakeCache:
    return FakeCache()


@pytest.fixture(scope="session", autouse=True)
def create_plugin_custom_model_tables(
    django_db_setup: None, django_db_blocker: DjangoDbBlocker
) -> None:
    """Build SQLite tables for the plugin custom models.

    Custom models are managed under SQLite but ship no Django migrations, so
    pytest does not build their tables, and the bundled pytest canvas release
    does not either. This mirrors the table creation the Canvas plugin runner
    performs at install time using the same DDL helpers. It fires only under
    SQLite, so Postgres installs are unaffected.
    """
    from django.conf import settings

    if "sqlite3" not in settings.DATABASES["default"]["ENGINE"]:
        return

    import salesforce_to_canvas_integration.models  # noqa: F401  registers the models

    from django.apps import apps

    from plugin_runner.ddl import (
        execute_create_table_sql,
        generate_create_table_sql,
        should_create_table,
    )
    from plugin_runner.installation import register_plugin_app_config

    plugin_name = "salesforce_to_canvas_integration"
    with django_db_blocker.unblock():
        for model_class in apps.all_models.get(plugin_name, {}).values():
            if should_create_table(model_class, plugin_name):
                execute_create_table_sql(generate_create_table_sql(plugin_name, model_class))
        register_plugin_app_config(plugin_name)
