"""Tests for patient_panel.services.fhir_photo (URL building + photo parsing).

Pure: a tiny fake HTTP client stands in for canvas_sdk Http at the boundary
(no canvas_sdk method is mocked).
"""

__is_plugin__ = True

import base64

from patient_panel.services.fhir_photo import (
    build_patient_fhir_url,
    build_token_url,
    parse_photo_response,
)


class TestBuildTokenUrl:
    def test_strips_fumage_prefix(self) -> None:
        assert build_token_url("https://fumage-foo.canvasmedical.com") == \
            "https://foo.canvasmedical.com/auth/token/"

    def test_plain_host_unchanged(self) -> None:
        assert build_token_url("https://foo.canvasmedical.com/") == \
            "https://foo.canvasmedical.com/auth/token/"

    def test_strips_quotes_and_trailing_slash(self) -> None:
        assert build_token_url("'https://foo.canvasmedical.com/'") == \
            "https://foo.canvasmedical.com/auth/token/"


class TestBuildPatientFhirUrl:
    def test_adds_fumage_prefix(self) -> None:
        assert build_patient_fhir_url("https://foo.canvasmedical.com", "p1") == \
            "https://fumage-foo.canvasmedical.com/Patient/p1"

    def test_keeps_existing_fumage(self) -> None:
        assert build_patient_fhir_url("https://fumage-foo.canvasmedical.com/", "p1") == \
            "https://fumage-foo.canvasmedical.com/Patient/p1"


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        content: bytes = b"",
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content


class _FakeHttp:
    def __init__(self, response: _FakeResponse | None) -> None:
        self._response = response
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    def get(self, url: str, headers: dict[str, str] | None = None) -> _FakeResponse | None:
        self.calls.append((url, headers))
        return self._response


class TestParsePhotoResponse:
    def test_empty_photo_array_returns_none(self) -> None:
        assert parse_photo_response({"photo": []}, "tok", _FakeHttp(None), "p1") is None

    def test_missing_photo_key_returns_none(self) -> None:
        assert parse_photo_response({}, "tok", _FakeHttp(None), "p1") is None

    def test_inline_base64(self) -> None:
        raw = b"\x89PNG image bytes"
        data = base64.b64encode(raw).decode()
        patient_data = {"photo": [{"data": data, "contentType": "image/png"}]}
        result = parse_photo_response(patient_data, "tok", _FakeHttp(None), "p1")
        assert result == ("image/png", raw)

    def test_inline_base64_defaults_content_type(self) -> None:
        data = base64.b64encode(b"x").decode()
        result = parse_photo_response({"photo": [{"data": data}]}, "tok", _FakeHttp(None), "p1")
        assert result is not None
        assert result[0] == "image/jpeg"

    def test_url_fetch_success(self) -> None:
        http = _FakeHttp(_FakeResponse(200, {"Content-Type": "image/gif"}, b"gifbytes"))
        patient_data = {"photo": [{"url": "https://s3/presigned"}]}
        result = parse_photo_response(patient_data, "tok", http, "p1")
        assert result == ("image/gif", b"gifbytes")
        # The Bearer token is sent to the fumage url (requests strips it on
        # the cross-host S3 redirect it then follows).
        assert http.calls[0][1] == {"Authorization": "Bearer tok"}

    def test_url_fetch_non_200_returns_none(self) -> None:
        http = _FakeHttp(_FakeResponse(403))
        result = parse_photo_response({"photo": [{"url": "https://s3/x"}]}, "tok", http, "p1")
        assert result is None

    def test_photo_without_data_or_url_returns_none(self) -> None:
        assert parse_photo_response({"photo": [{"foo": "bar"}]}, "tok", _FakeHttp(None), "p1") is None
