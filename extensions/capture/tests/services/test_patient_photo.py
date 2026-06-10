"""Tests for the patient_photo service (read-modify-write Patient.photo)."""

import base64
from unittest.mock import patch

from capture.services.patient_photo import update_patient_photo

PNG = b"\x89PNG\r\n\x1a\n fake png bytes"


def _patched():
    return (
        patch("capture.services.patient_photo.CanvasFhir"),
        patch("capture.services.patient_photo.Http"),
    )


def test_update_patient_photo_read_modify_write() -> None:
    cf, ht = _patched()
    with cf as MockClient, ht as MockHttp:
        client = MockClient.return_value
        client._base_url = "https://fumage-x.canvasmedical.com"
        client._get_headers.return_value = {"Authorization": "Bearer t"}
        client.read.return_value = {
            "resourceType": "Patient", "id": "pat-1", "name": [{"family": "Doe"}],
        }
        MockHttp.return_value.put.return_value.raise_for_status.return_value = None

        result = update_patient_photo("c", "s", "pat-1", PNG, "image/png")

        client.read.assert_called_once_with("Patient", "pat-1")
        args, kwargs = MockHttp.return_value.put.call_args
        assert args[0].endswith("/Patient/pat-1")
        body = kwargs["json"]
        assert body["name"] == [{"family": "Doe"}]  # other fields preserved
        assert body["photo"][0]["contentType"] == "image/png"
        assert body["photo"][0]["data"] == base64.b64encode(PNG).decode("ascii")
        assert result == "pat-1"


def test_update_patient_photo_unexpected_read() -> None:
    cf, ht = _patched()
    with cf as MockClient, ht:
        MockClient.return_value.read.return_value = {"resourceType": "OperationOutcome"}
        try:
            update_patient_photo("c", "s", "p", PNG, "image/png")
            raise AssertionError("expected RuntimeError")
        except RuntimeError as exc:
            assert "Unexpected Patient read" in str(exc)


def test_update_patient_photo_put_error() -> None:
    cf, ht = _patched()
    with cf as MockClient, ht as MockHttp:
        client = MockClient.return_value
        client._base_url = "https://fumage-x.canvasmedical.com"
        client._get_headers.return_value = {}
        client.read.return_value = {"resourceType": "Patient", "id": "p"}
        put_resp = MockHttp.return_value.put.return_value
        put_resp.raise_for_status.side_effect = Exception("400")
        put_resp.text = "bad photo"
        try:
            update_patient_photo("c", "s", "p", PNG, "image/png")
            raise AssertionError("expected RuntimeError")
        except RuntimeError as exc:
            assert "body=" in str(exc)
