"""Test helpers — real (non-mock) request and API builders.

This module is named with a leading underscore so pytest does not collect it
as a test file. Import via `from tests._helpers import build_api`.

This module is *registered as part of the plugin* (`__is_plugin__ = True`
and a `patient_panel.*` `__name__`) so cache reads/writes routed through
its helpers use the same plugin-prefix as the panel code under test.
"""

from __future__ import annotations

from typing import Any

# Make canvas_sdk's plugin-context detector treat this module's frame as
# part of the patient_panel plugin. Tests can call `cache_set`/`cache_get`
# below and the resulting plugin_name will match what the panel uses.
__is_plugin__ = True
__name__ = "patient_panel._helpers"


class FakeQueryParams:
    """Drop-in for SimpleAPI's query_params — same `.get(key, default)`."""

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self._mapping: dict[str, str] = dict(mapping or {})

    def get(self, key: str, default: str = "") -> str:
        return self._mapping.get(key, default)


class FakeFormField:
    """Drop-in for multipart field type returned by `form_data().get(name)`."""

    def __init__(self, value: Any) -> None:
        self.value = value


class FakeFormData:
    def __init__(self, mapping: dict[str, Any] | None = None) -> None:
        self._mapping: dict[str, Any] = dict(mapping or {})

    def get(
        self, key: str, default: FakeFormField | None = None
    ) -> FakeFormField | None:
        if key not in self._mapping:
            return default
        return FakeFormField(self._mapping[key])


class FakeRequest:
    """Minimal real request object exposing the SimpleAPI surface the panel
    actually touches. Not a MagicMock — a plain Python class.
    """

    def __init__(
        self,
        *,
        headers: dict[str, str] | None = None,
        path_params: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
        form_data: dict[str, Any] | None = None,
    ) -> None:
        self.headers: dict[str, str] = dict(headers or {})
        self.path_params: dict[str, str] = dict(path_params or {})
        self.query_params = FakeQueryParams(query_params)
        self._form_data = FakeFormData(form_data)

    def form_data(self) -> FakeFormData:
        return self._form_data


def build_api(
    *,
    secrets: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    path_params: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
    form_data: dict[str, Any] | None = None,
) -> Any:
    """Instantiate a PatientPanelAPI without running its SDK __init__.

    Sets `secrets` (dict) and `request` (FakeRequest) on the instance. The
    methods exercised in tests are the panel's own — no canvas_sdk methods
    are mocked.
    """
    from api.panel_api import PatientPanelAPI

    api = PatientPanelAPI.__new__(PatientPanelAPI)
    api.secrets = dict(secrets or {})
    api.request = FakeRequest(
        headers=headers,
        path_params=path_params,
        query_params=query_params,
        form_data=form_data,
    )
    PatientPanelAPI._fhir_token_cache = {}
    return api


# ── Plugin-prefixed cache helpers ─────────────────────────────────────────
# Tests calling these go through this module's frame, so canvas_sdk's
# plugin_context wrapper resolves plugin_name to "patient_panel" — same
# prefix the production code uses.

def plugin_cache() -> Any:
    """Return a cache object whose prefix resolves to the patient_panel plugin.

    Because this module's __name__ is "patient_panel._helpers", get_cache()'s
    plugin_context resolves the same prefix the production code uses. Pass the
    returned object into service functions that take a `cache` parameter.
    """
    from canvas_sdk.caching.plugins import get_cache
    return get_cache()


def cache_set(key: str, value: Any, timeout_seconds: int | None = None) -> None:
    from canvas_sdk.caching.plugins import get_cache
    get_cache().set(key, value, timeout_seconds=timeout_seconds)


def cache_get(key: str, default: Any = None) -> Any:
    from canvas_sdk.caching.plugins import get_cache
    return get_cache().get(key, default)


def cache_delete(key: str) -> None:
    from canvas_sdk.caching.plugins import get_cache
    get_cache().delete(key)
