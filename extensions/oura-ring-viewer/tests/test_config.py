"""Tests for request validation and plugin configuration helpers."""

from typing import Any

import pytest

from oura_ring_viewer.services.config import (
    FETCH_SECRETS,
    LINK_SECRETS,
    OAUTH_SECRETS,
    build_client,
    clean_patient_id,
    config_problems,
    connect_url,
)

GOOD = {
    "OURA_CLIENT_ID": "cid",
    "OURA_CLIENT_SECRET": "sec",
    "OURA_REDIRECT_URI": "https://acme.canvasmedical.com/plugin-io/api/oura_ring_viewer/callback",
    "OURA_ENVIRONMENT": "sandbox",
    "OURA_MAGIC_LINK_SECRET": "m" * 40,
}


class TestPatientId:
    @pytest.mark.parametrize("raw", ["abc123", "a1b2-c3d4", "  e5f6  ", "x" * 64])
    def test_plausible_ids(self, raw: str) -> None:
        assert clean_patient_id(raw) == raw.strip()

    @pytest.mark.parametrize(
        "raw",
        [None, 123, "", "   ", "x" * 65, "abc def", '"><script>', "a/../b",
         "a\"b", "a'b", "a\\b", "ab\ncd", "١٢٣", "café"],
    )
    def test_anything_else_is_rejected(self, raw: Any) -> None:
        assert clean_patient_id(raw) is None


class TestConfigProblems:
    @pytest.mark.parametrize("required", [FETCH_SECRETS, LINK_SECRETS, OAUTH_SECRETS])
    def test_complete_configuration_has_no_problems(self, required: tuple[str, ...]) -> None:
        assert config_problems(GOOD, required) == []

    def test_reports_each_missing_setting(self) -> None:
        assert config_problems(None, LINK_SECRETS) == list(LINK_SECRETS)
        partial = {k: v for k, v in GOOD.items() if k != "OURA_CLIENT_SECRET"}
        assert config_problems(partial, FETCH_SECRETS) == ["OURA_CLIENT_SECRET"]

    def test_sync_does_not_need_the_signing_secret(self) -> None:
        settings = {k: v for k, v in GOOD.items() if k != "OURA_MAGIC_LINK_SECRET"}
        assert config_problems(settings, FETCH_SECRETS) == []

    def test_short_signing_secret_is_flagged(self) -> None:
        problems = config_problems({**GOOD, "OURA_MAGIC_LINK_SECRET": "short"}, LINK_SECRETS)
        assert len(problems) == 1 and "shorter than 32" in problems[0]

    @pytest.mark.parametrize(
        "uri",
        [
            "http://acme.canvasmedical.com/callback",
            "acme.canvasmedical.com/callback",
            "https://",
            "https://user:pass@evil.example/callback",
            "ftp://acme.canvasmedical.com/callback",
            "javascript://acme.canvasmedical.com/%0aalert(1)",
        ],
    )
    def test_unsafe_redirect_uri_is_flagged(self, uri: str) -> None:
        problems = config_problems({**GOOD, "OURA_REDIRECT_URI": uri}, LINK_SECRETS)
        assert len(problems) == 1 and "https" in problems[0]


class TestConnectUrl:
    def test_uses_the_callback_origin(self) -> None:
        assert connect_url(GOOD["OURA_REDIRECT_URI"], "a.b/c+d") == (
            "https://acme.canvasmedical.com/plugin-io/api/oura_ring_viewer/connect?token=a.b%2Fc%2Bd"
        )

    def test_keeps_an_explicit_port(self) -> None:
        url = connect_url("https://acme.example:8443/x", "t")
        assert url.startswith("https://acme.example:8443/plugin-io/")

    @pytest.mark.parametrize("uri", ["http://localhost:8000/cb", "http://127.0.0.1/cb"])
    def test_plain_http_is_allowed_only_for_local_development(self, uri: str) -> None:
        assert connect_url(uri, "t").startswith("http://")

    def test_refuses_an_unsafe_origin(self) -> None:
        with pytest.raises(ValueError):
            connect_url("http://acme.canvasmedical.com/cb", "t")


def test_build_client_respects_environment() -> None:
    assert build_client(GOOD).collection_path == "/v2/sandbox/usercollection"
    prod = build_client({**GOOD, "OURA_ENVIRONMENT": "production"})
    assert prod.collection_path == "/v2/usercollection"
