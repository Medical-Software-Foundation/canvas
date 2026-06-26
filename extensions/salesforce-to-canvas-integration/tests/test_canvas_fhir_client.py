"""Tests for the Canvas FHIR client used by the Mark inactive audit route.

Covers token caching plus refresh, 401 retry on GET and PUT, and the read
modify write shape of :meth:`CanvasFhirClient.mark_patient_inactive`.
"""

from typing import Any

import pytest

from salesforce_to_canvas_integration.services.canvas_fhir_client import (
    CanvasFhirAuthError,
    CanvasFhirClient,
    CanvasFhirError,
    CanvasFhirNotConfiguredError,
    build_canvas_fhir_client,
)


_FUMAGE_BASE = "https://fumage-example.canvasmedical.com"
_EXPECTED_TOKEN_URL = "https://example.canvasmedical.com/auth/token/"


class FakeResponse:
    """Mirror of ``tests/test_sf_client.FakeResponse`` for the Canvas FHIR API."""

    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any] | None = None,
        *,
        text: str | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        if text is not None:
            self.text = text
        elif payload is None:
            self.text = ""
        else:
            self.text = str(payload)

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


class FakeHttp:
    """Records calls and returns scripted responses."""

    def __init__(self) -> None:
        self.gets: list[tuple[str, dict[str, str]]] = []
        self.posts: list[tuple[str, dict[str, str]]] = []
        self.puts: list[tuple[str, dict[str, Any]]] = []
        self.get_responses: list[FakeResponse] = []
        self.post_responses: list[FakeResponse] = []
        self.put_responses: list[FakeResponse] = []

    def get(
        self, url: str, headers: dict[str, str] | None = None, **kw: Any
    ) -> FakeResponse:
        self.gets.append((url, dict(headers or {})))
        return self.get_responses.pop(0)

    def post(
        self,
        url: str,
        data: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kw: Any,
    ) -> FakeResponse:
        self.posts.append((url, dict(data or {})))
        return self.post_responses.pop(0)

    def put(
        self,
        url: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kw: Any,
    ) -> FakeResponse:
        self.puts.append((url, dict(json or {})))
        return self.put_responses.pop(0)


def _token_response(access: str = "tok-1", expires_in: int = 3600) -> FakeResponse:
    return FakeResponse(
        200,
        {"access_token": access, "expires_in": expires_in, "token_type": "Bearer"},
    )


def _patient_body(
    patient_id: str = "pat-1",
    active: bool = True,
    **extras: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "resourceType": "Patient",
        "id": patient_id,
        "active": active,
        "name": [{"family": "Doe", "given": ["Jane"]}],
        "telecom": [{"system": "phone", "value": "555-0100"}],
        "address": [{"line": ["1 Main St"], "city": "Springfield"}],
        "identifier": [{"system": "salesforce", "value": "SFID-1"}],
    }
    body.update(extras)
    return body


def _client(http: FakeHttp) -> CanvasFhirClient:
    return CanvasFhirClient(
        http=http,
        fumage_base_url=_FUMAGE_BASE,
        client_id="cid",
        client_secret="csec",
    )


def test_token_url_strips_fumage_prefix() -> None:
    http = FakeHttp()
    http.post_responses.append(_token_response())
    http.get_responses.append(FakeResponse(200, _patient_body()))
    client = _client(http)

    client.get_patient("pat-1")

    assert http.posts[0][0] == _EXPECTED_TOKEN_URL
    assert http.posts[0][1]["grant_type"] == "client_credentials"
    assert http.posts[0][1]["client_id"] == "cid"
    assert http.posts[0][1]["client_secret"] == "csec"


def test_token_url_uses_instance_override_when_set() -> None:
    # When the instance url is configured the token endpoint is built from it
    # directly, not derived from the fumage base. See journal cnv-928/002.
    http = FakeHttp()
    http.post_responses.append(_token_response())
    http.get_responses.append(FakeResponse(200, _patient_body()))
    client = CanvasFhirClient(
        http=http,
        fumage_base_url="http://host.docker.internal:8888",
        client_id="cid",
        client_secret="csec",
        instance_url="http://localhost:8000",
    )

    client.get_patient("pat-1")

    assert http.posts[0][0] == "http://localhost:8000/auth/token/"


def test_token_url_falls_back_to_derivation_when_instance_url_empty() -> None:
    # An empty instance url keeps the production fumage prefix derivation so the
    # shipped behavior is unchanged.
    http = FakeHttp()
    http.post_responses.append(_token_response())
    http.get_responses.append(FakeResponse(200, _patient_body()))
    client = CanvasFhirClient(
        http=http,
        fumage_base_url=_FUMAGE_BASE,
        client_id="cid",
        client_secret="csec",
        instance_url="",
    )

    client.get_patient("pat-1")

    assert http.posts[0][0] == _EXPECTED_TOKEN_URL


def test_token_is_reused_across_calls_within_cache_window() -> None:
    http = FakeHttp()
    http.post_responses.append(_token_response(access="tok-cached"))
    http.get_responses.append(FakeResponse(200, _patient_body()))
    http.put_responses.append(FakeResponse(200, _patient_body(active=False)))
    client = _client(http)

    client.mark_patient_inactive("pat-1")

    # One token POST drives both the GET and the PUT.
    assert len(http.posts) == 1
    assert http.gets[0][1]["Authorization"] == "Bearer tok-cached"
    assert http.puts[0][1]["active"] is False


def test_get_patient_retries_once_after_401_then_succeeds() -> None:
    http = FakeHttp()
    http.post_responses.append(_token_response(access="tok-old"))
    http.post_responses.append(_token_response(access="tok-new"))
    http.get_responses.append(FakeResponse(401, text="expired"))
    http.get_responses.append(FakeResponse(200, _patient_body()))
    client = _client(http)

    body = client.get_patient("pat-1")

    assert body["id"] == "pat-1"
    assert len(http.posts) == 2
    assert http.gets[0][1]["Authorization"] == "Bearer tok-old"
    assert http.gets[1][1]["Authorization"] == "Bearer tok-new"


def test_get_patient_raises_auth_error_when_retried_request_still_401() -> None:
    http = FakeHttp()
    http.post_responses.append(_token_response(access="tok-old"))
    http.post_responses.append(_token_response(access="tok-new"))
    http.get_responses.append(FakeResponse(401, text="expired"))
    http.get_responses.append(FakeResponse(401, text="still bad"))
    client = _client(http)

    with pytest.raises(CanvasFhirAuthError):
        client.get_patient("pat-1")


def test_token_endpoint_failure_raises_auth_error() -> None:
    http = FakeHttp()
    http.post_responses.append(FakeResponse(401, text="bad creds"))
    client = _client(http)

    with pytest.raises(CanvasFhirAuthError):
        client.get_patient("pat-1")


def test_mark_patient_inactive_preserves_every_other_body_field() -> None:
    original = _patient_body(
        patient_id="pat-7",
        active=True,
        gender="female",
        birthDate="1990-01-02",
    )
    http = FakeHttp()
    http.post_responses.append(_token_response())
    http.get_responses.append(FakeResponse(200, original))
    http.put_responses.append(FakeResponse(200, {}))
    client = _client(http)

    client.mark_patient_inactive("pat-7")

    put_url, put_body = http.puts[0]
    assert put_url.endswith("/Patient/pat-7")
    assert put_body["active"] is False
    for key in (
        "resourceType",
        "id",
        "name",
        "telecom",
        "address",
        "identifier",
        "gender",
        "birthDate",
    ):
        assert put_body[key] == original[key], f"{key} mutated by mark_inactive"


def test_get_patient_non_2xx_raises_canvas_fhir_error() -> None:
    http = FakeHttp()
    http.post_responses.append(_token_response())
    http.get_responses.append(FakeResponse(500, text="boom"))
    client = _client(http)

    with pytest.raises(CanvasFhirError) as info:
        client.get_patient("pat-1")
    assert "500" in str(info.value)
    assert not isinstance(info.value, CanvasFhirAuthError)


def test_put_patient_non_2xx_raises_canvas_fhir_error() -> None:
    http = FakeHttp()
    http.post_responses.append(_token_response())
    http.get_responses.append(FakeResponse(200, _patient_body()))
    http.put_responses.append(FakeResponse(422, text="missing required field"))
    client = _client(http)

    with pytest.raises(CanvasFhirError) as info:
        client.mark_patient_inactive("pat-1")
    assert "422" in str(info.value)
    assert not isinstance(info.value, CanvasFhirAuthError)


def test_factory_raises_not_configured_when_any_secret_is_empty() -> None:
    http = FakeHttp()
    with pytest.raises(CanvasFhirNotConfiguredError):
        build_canvas_fhir_client(
            http=http,
            fumage_base_url="",
            client_id="cid",
            client_secret="csec",
        )
    with pytest.raises(CanvasFhirNotConfiguredError):
        build_canvas_fhir_client(
            http=http,
            fumage_base_url=_FUMAGE_BASE,
            client_id="",
            client_secret="csec",
        )
    with pytest.raises(CanvasFhirNotConfiguredError):
        build_canvas_fhir_client(
            http=http,
            fumage_base_url=_FUMAGE_BASE,
            client_id="cid",
            client_secret="",
        )


def test_factory_builds_client_when_all_secrets_present() -> None:
    http = FakeHttp()
    client = build_canvas_fhir_client(
        http=http,
        fumage_base_url=_FUMAGE_BASE,
        client_id="cid",
        client_secret="csec",
    )
    assert isinstance(client, CanvasFhirClient)


def _patient_body_with_identifiers(
    patient_id: str,
    identifiers: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "resourceType": "Patient",
        "id": patient_id,
        "active": True,
        "name": [{"family": "Doe", "given": ["Jane"]}],
        "telecom": [{"system": "phone", "value": "555-0100"}],
        "address": [{"line": ["1 Main St"], "city": "Springfield"}],
        "identifier": identifiers,
    }


def test_remove_salesforce_identifier_drops_matching_entry_only() -> None:
    original_identifiers = [
        {"system": "MRN", "value": "MRN-99"},
        {"system": "salesforce", "value": "SF-1"},
        {"system": "salesforce", "value": "SF-OTHER"},
    ]
    http = FakeHttp()
    http.post_responses.append(_token_response())
    http.get_responses.append(
        FakeResponse(200, _patient_body_with_identifiers("pat-1", original_identifiers))
    )
    http.put_responses.append(FakeResponse(200, {}))
    client = _client(http)

    client.remove_salesforce_identifier("pat-1", "SF-1")

    put_url, put_body = http.puts[0]
    assert put_url.endswith("/Patient/pat-1")
    assert put_body["identifier"] == [
        {"system": "MRN", "value": "MRN-99"},
        {"system": "salesforce", "value": "SF-OTHER"},
    ]
    # Active stays untouched, every other field preserved.
    assert put_body["active"] is True
    assert put_body["name"][0]["family"] == "Doe"
    assert put_body["telecom"][0]["value"] == "555-0100"


def test_remove_salesforce_identifier_is_noop_when_id_not_present() -> None:
    original_identifiers = [{"system": "MRN", "value": "MRN-99"}]
    http = FakeHttp()
    http.post_responses.append(_token_response())
    http.get_responses.append(
        FakeResponse(200, _patient_body_with_identifiers("pat-1", original_identifiers))
    )
    http.put_responses.append(FakeResponse(200, {}))
    client = _client(http)

    client.remove_salesforce_identifier("pat-1", "SF-1")

    put_body = http.puts[0][1]
    assert put_body["identifier"] == [{"system": "MRN", "value": "MRN-99"}]


def test_remove_salesforce_identifier_handles_missing_identifier_field() -> None:
    body = {
        "resourceType": "Patient",
        "id": "pat-1",
        "active": True,
        "name": [{"family": "Doe"}],
    }
    http = FakeHttp()
    http.post_responses.append(_token_response())
    http.get_responses.append(FakeResponse(200, body))
    http.put_responses.append(FakeResponse(200, {}))
    client = _client(http)

    client.remove_salesforce_identifier("pat-1", "SF-1")

    put_body = http.puts[0][1]
    assert put_body["identifier"] == []
    assert put_body["name"] == [{"family": "Doe"}]


def test_remove_salesforce_identifier_surfaces_get_error() -> None:
    http = FakeHttp()
    http.post_responses.append(_token_response())
    http.get_responses.append(FakeResponse(500, text="boom"))
    client = _client(http)

    with pytest.raises(CanvasFhirError):
        client.remove_salesforce_identifier("pat-1", "SF-1")


def test_remove_salesforce_identifier_surfaces_put_error() -> None:
    http = FakeHttp()
    http.post_responses.append(_token_response())
    http.get_responses.append(
        FakeResponse(
            200,
            _patient_body_with_identifiers(
                "pat-1", [{"system": "salesforce", "value": "SF-1"}]
            ),
        )
    )
    http.put_responses.append(FakeResponse(422, text="missing required field"))
    client = _client(http)

    with pytest.raises(CanvasFhirError):
        client.remove_salesforce_identifier("pat-1", "SF-1")
