"""Tests for ExportStorage — the S3 wrapper for prepared exports."""

from unittest.mock import MagicMock, patch

from ehi_export_tool.services.storage import ExportStorage

_S3 = "ehi_export_tool.services.storage.S3"

FULL = {"S3_ACCESS_KEY": "ak", "S3_SECRET_KEY": "sk", "S3_REGION": "us-east-1", "S3_BUCKET": "b"}


def test_is_configured() -> None:
    assert ExportStorage.is_configured(FULL) is True
    assert ExportStorage.is_configured({**FULL, "S3_BUCKET": ""}) is False
    assert ExportStorage.is_configured({}) is False


def test_from_secrets_returns_none_when_unconfigured() -> None:
    assert ExportStorage.from_secrets({"S3_ACCESS_KEY": "ak"}) is None


def test_from_secrets_builds_client_and_default_prefix() -> None:
    with patch(_S3) as MockS3:
        storage = ExportStorage.from_secrets(FULL)
    assert storage is not None
    MockS3.assert_called_once()
    # default prefix is ehi-exports
    assert storage.batch_prefix("b1") == "ehi-exports/b1/"


def test_custom_prefix_is_trimmed() -> None:
    with patch(_S3):
        storage = ExportStorage.from_secrets({**FULL, "S3_PREFIX": "/exports/ehi/"})
    assert storage.batch_prefix("b1") == "exports/ehi/b1/"


def test_patient_key_sanitizes_segments() -> None:
    with patch(_S3):
        storage = ExportStorage.from_secrets(FULL)
    key = storage.patient_key(batch_id="b 1", patient_id="p-1", patient_name="O'Brien, Ána")
    assert key.startswith("ehi-exports/b_1/")
    assert key.endswith(".ndjson")
    assert " " not in key and "'" not in key


def test_ccda_key_uses_xml_extension() -> None:
    with patch(_S3):
        storage = ExportStorage.from_secrets(FULL)
    key = storage.ccda_key(batch_id="b1", patient_id="p-1", patient_name="Lovelace, Ada")
    assert key.startswith("ehi-exports/b1/")
    assert key.endswith(".xml")


def test_upload_xml_uses_xml_content_type() -> None:
    client = MagicMock()
    client.upload_binary_to_s3.return_value = MagicMock(ok=True)
    storage = ExportStorage(client, "ehi-exports")
    assert storage.upload_xml("k.xml", "<x/>") is True
    args = client.upload_binary_to_s3.call_args[0]
    assert args[0] == "k.xml"
    assert args[2] == "application/xml"


def test_upload_ndjson_uses_ndjson_content_type_and_reports_success() -> None:
    client = MagicMock()
    client.upload_binary_to_s3.return_value = MagicMock(ok=True)
    storage = ExportStorage(client, "ehi-exports")
    assert storage.upload_ndjson("k.ndjson", '{"a": 1}') is True
    args = client.upload_binary_to_s3.call_args[0]
    assert args[0] == "k.ndjson"
    assert args[2] == "application/x-ndjson"


def test_upload_ndjson_returns_false_on_failure() -> None:
    client = MagicMock()
    client.upload_binary_to_s3.return_value = None  # not ready
    storage = ExportStorage(client, "ehi-exports")
    assert storage.upload_ndjson("k.ndjson", "{}") is False


def test_presigned_url_delegates_to_client() -> None:
    client = MagicMock()
    client.generate_presigned_url.return_value = "https://signed"
    storage = ExportStorage(client, "ehi-exports")
    assert storage.presigned_url("k.json") == "https://signed"
