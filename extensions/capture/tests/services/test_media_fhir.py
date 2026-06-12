"""Tests for the media_fhir service (clinical image → note Media)."""

import base64
from unittest.mock import patch

from capture.services.media_fhir import build_media_payload, create_media

IMG = b"\xff\xd8\xff\xe0 fake jpeg bytes"


def test_build_media_payload_shape() -> None:
    payload = build_media_payload(
        patient_id="pat-1",
        encounter_id="enc-9",
        image_bytes=IMG,
        content_type="image/jpeg",
        title="Left forearm",
    )
    assert payload["resourceType"] == "Media"
    assert payload["status"] == "completed"
    assert payload["subject"]["reference"] == "Patient/pat-1"
    assert payload["encounter"]["reference"] == "Encounter/enc-9"
    assert payload["content"]["contentType"] == "image/jpeg"
    assert payload["content"]["title"] == "Left forearm"
    assert payload["content"]["data"] == base64.b64encode(IMG).decode("ascii")


def test_build_media_payload_defaults_title() -> None:
    payload = build_media_payload("p", "e", IMG, "image/png", "")
    assert payload["content"]["title"] == "Clinical photo"


def _patched():
    return (
        patch("capture.services.media_fhir.CanvasFhir"),
        patch("capture.services.media_fhir.Http"),
    )


def test_create_media_posts_and_reads_location() -> None:
    cf, ht = _patched()
    with cf as MockClient, ht as MockHttp:
        client = MockClient.return_value
        client._base_url = "https://fumage-x.canvasmedical.com"
        client._get_headers.return_value = {"Authorization": "Bearer t"}
        resp = MockHttp.return_value.post.return_value
        resp.raise_for_status.return_value = None
        resp.headers = {
            "Location": "https://fumage-x.canvasmedical.com/Media/media-42/_history/1"
        }

        result = create_media(
            client_id="cid", client_secret="secret",
            patient_id="pat-3", encounter_id="enc-3",
            image_bytes=IMG, content_type="image/jpeg", title="photo",
        )

        MockClient.assert_called_once_with("cid", "secret")
        args, kwargs = MockHttp.return_value.post.call_args
        assert args[0].endswith("/Media")
        assert kwargs["headers"] == {"Authorization": "Bearer t"}
        assert kwargs["json"]["resourceType"] == "Media"
        assert result == "media-42"


def test_create_media_location_fallbacks() -> None:
    cf, ht = _patched()
    with cf as MockClient, ht as MockHttp:
        client = MockClient.return_value
        client._base_url = "https://fumage-x.canvasmedical.com"
        client._get_headers.return_value = {}
        resp = MockHttp.return_value.post.return_value
        resp.raise_for_status.return_value = None
        # Location without a "Media" segment → last segment
        resp.headers = {"Location": "https://fumage-x.canvasmedical.com/other/zzz"}
        assert create_media("c", "s", "p", "e", IMG, "image/jpeg", "t") == "zzz"
        # No Location header → empty string
        resp.headers = {}
        assert create_media("c", "s", "p", "e", IMG, "image/jpeg", "t") == ""


def test_create_media_raises_with_body_on_error() -> None:
    cf, ht = _patched()
    with cf as MockClient, ht as MockHttp:
        client = MockClient.return_value
        client._base_url = "https://fumage-x.canvasmedical.com"
        client._get_headers.return_value = {}
        resp = MockHttp.return_value.post.return_value
        resp.raise_for_status.side_effect = Exception("422")
        resp.text = "OperationOutcome: bad encounter"

        try:
            create_media("c", "s", "p", "e", IMG, "image/jpeg", "t")
            raise AssertionError("expected RuntimeError")
        except RuntimeError as exc:
            assert "body=" in str(exc)
