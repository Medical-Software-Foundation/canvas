"""Shared fixtures for patient_panel tests.

This project follows the rule that tests must NOT mock or patch canvas_sdk
methods. Everything uses real Django models (canvas_sdk.test_utils.factories),
real cache (canvas_sdk.caching), and real request-like objects (see
`tests/_helpers.py`). The DB transaction is provided by pytest-canvas'
autouse `transaction` fixture which depends on pytest-django's `db` fixture.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Callable

import pytest

# Make the plugin importable as both `patient_panel.*` and the top-level
# `api.*` / `handlers.*` shorthand the panel uses internally.
parent_dir = Path(__file__).parent.parent
patient_panel_dir = parent_dir / "patient_panel"
sys.path.insert(0, str(parent_dir.parent))  # repo root for `tests._helpers`
sys.path.insert(0, str(parent_dir))
sys.path.insert(0, str(patient_panel_dir))

# Typed `Any`: this is a dynamically-extended stand-in module whose attributes
# (handlers, api, ...) are assigned below at runtime, so a static module type
# can't model it.
patient_panel: Any = types.ModuleType("patient_panel")
# Give the fake root package a real __path__ so the import machinery can
# resolve genuine on-disk subpackages (e.g. patient_panel.services.*) via the
# normal path finder, without per-module sys.modules shadowing.
patient_panel.__path__ = [str(patient_panel_dir)]
sys.modules["patient_panel"] = patient_panel
patient_panel.handlers = types.ModuleType("patient_panel.handlers")
sys.modules["patient_panel.handlers"] = patient_panel.handlers

from handlers import flag_cleanup, panel_button, panel_stats_sync, panel_stats_reconcile  # noqa: E402

patient_panel.handlers.flag_cleanup = flag_cleanup
patient_panel.handlers.panel_button = panel_button
patient_panel.handlers.panel_stats_sync = panel_stats_sync
patient_panel.handlers.panel_stats_reconcile = panel_stats_reconcile
sys.modules["patient_panel.handlers.flag_cleanup"] = flag_cleanup
sys.modules["patient_panel.handlers.panel_button"] = panel_button
sys.modules["patient_panel.handlers.panel_stats_sync"] = panel_stats_sync
sys.modules["patient_panel.handlers.panel_stats_reconcile"] = panel_stats_reconcile

# Register `api.panel_api` and `handlers.*` so canvas_sdk's plugin-context
# detection sees them under the real plugin name. This is config — we
# declare what the plugin name is — not mocking of any canvas_sdk method.
import canvas_sdk.utils.plugins  # noqa: E402

canvas_sdk.utils.plugins.PLUGIN_DIRECTORY = str(parent_dir)

from api import panel_api as _panel_api_module  # noqa: E402

_panel_api_module.__is_plugin__ = True
_panel_api_module.__name__ = "patient_panel.api.panel_api"
sys.modules["patient_panel.api"] = types.ModuleType("patient_panel.api")
sys.modules["patient_panel.api.panel_api"] = _panel_api_module
patient_panel.api = sys.modules["patient_panel.api"]
patient_panel.api.panel_api = _panel_api_module

# Same for handlers — they're called via the panel_api path so this is
# mostly for symmetry / direct handler tests.
flag_cleanup.__is_plugin__ = True
flag_cleanup.__name__ = "patient_panel.handlers.flag_cleanup"
panel_button.__is_plugin__ = True
panel_button.__name__ = "patient_panel.handlers.panel_button"
panel_stats_sync.__is_plugin__ = True
panel_stats_sync.__name__ = "patient_panel.handlers.panel_stats_sync"
panel_stats_reconcile.__is_plugin__ = True
panel_stats_reconcile.__name__ = "patient_panel.handlers.panel_stats_reconcile"

from tests._helpers import build_api  # noqa: E402, F401  (re-export)


@pytest.fixture(autouse=True)
def _reset_class_caches() -> None:
    """Reset PatientPanelAPI class-level caches between tests.

    The sandbox forbids per-instance dict mutation, so the production code
    memoizes at the class level. Tests must clear those caches to stay
    isolated from each other.
    """
    _panel_api_module.PatientPanelAPI._display_tz_cache = {}
    _panel_api_module.PatientPanelAPI._fhir_token_cache = {}

    # The dropdown lookups (services.lookups) cache population-wide filter
    # options under fixed global keys. Clear them so cached facilities/staff/
    # insurances/protocols from one test never leak into the next. Routed
    # through tests._helpers.cache_delete so get_cache() resolves the plugin
    # context (it cannot be called directly from conftest).
    from tests._helpers import cache_delete
    from patient_panel.services import lookups

    for key in (
        lookups._FACILITIES_KEY,
        lookups._PROTOCOL_TITLES_KEY,
        lookups._STAFF_KEY,
        lookups._INSURANCES_KEY,
    ):
        cache_delete(key)


@pytest.fixture
def make_api() -> Callable[..., Any]:
    """Factory fixture returning a fresh PatientPanelAPI per call."""
    return build_api


@pytest.fixture
def default_secrets() -> dict[str, Any]:
    return {
        "PAGE_SIZE": "10",
        "HIGHLIGHT_THRESHOLD_DAYS_GREEN": "1",
        "HIGHLIGHT_THRESHOLD_DAYS_YELLOW": "3",
        "HIGHLIGHT_THRESHOLD_DAYS_RED": "7",
        "INSURANCES": "{}",
    }


from django.db import connection  # noqa: E402
from patient_panel.models import PatientPanelStats  # noqa: E402

CUSTOM_MODELS = [PatientPanelStats]


def _make_columns_nullable(model: Any) -> list[tuple[Any, bool]]:
    originals = []
    for field in model._meta.local_fields:
        originals.append((field, field.null))
        field.null = True
    return originals


@pytest.fixture(autouse=True, scope="session")
def _custom_model_tables(django_db_setup: Any, django_db_blocker: Any) -> Any:
    with django_db_blocker.unblock():
        with connection.schema_editor() as editor:
            for model in CUSTOM_MODELS:
                saved = _make_columns_nullable(model)
                try:
                    editor.create_model(model)
                except Exception:
                    pass
                finally:
                    for field, original_null in saved:
                        field.null = original_null
    yield
