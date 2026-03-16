"""Tests for S3 client upload functionality."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from patient_csv_loader.apps.s3_client import (
    _get_signing_key,
    _sha256,
    upload_csv_to_s3,
)


class TestSha256:
    def test_empty_string(self) -> None:
        result = _sha256(b"")
        assert result == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_known_hash(self) -> None:
        result = _sha256(b"hello")
        assert result == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


class TestGetSigningKey:
    def test_returns_bytes(self) -> None:
        key = _get_signing_key("wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", "20230101", "us-east-1", "s3")
        assert isinstance(key, bytes)
        assert len(key) == 32  # SHA-256 produces 32 bytes


class TestUploadCsvToS3:
    @patch("patient_csv_loader.apps.s3_client.Http")
    def test_successful_upload(self, mock_http_class: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.ok = True
        mock_http = MagicMock()
        mock_http.put.return_value = mock_response
        mock_http_class.return_value = mock_http

        result = upload_csv_to_s3(
            csv_content="first_name,last_name\nJane,Doe",
            filename="patients.csv",
            bucket="my-bucket",
            access_key_id="AKIAIOSFODNN7EXAMPLE",
            secret_access_key="wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        )

        assert result is True
        mock_http.put.assert_called_once()
        call_args = mock_http.put.call_args
        assert "my-bucket.s3.us-east-1.amazonaws.com" in call_args[0][0]
        assert "patient-csv-uploads" in call_args[0][0]
        assert "patients.csv" in call_args[0][0]
        assert "Authorization" in call_args[1]["headers"]
        assert call_args[1]["data"] == b"first_name,last_name\nJane,Doe"

    @patch("patient_csv_loader.apps.s3_client.Http")
    def test_failed_upload_returns_false(self, mock_http_class: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 403
        mock_response.text = "Access Denied"
        mock_http = MagicMock()
        mock_http.put.return_value = mock_response
        mock_http_class.return_value = mock_http

        result = upload_csv_to_s3(
            csv_content="data",
            filename="test.csv",
            bucket="my-bucket",
            access_key_id="AKID",
            secret_access_key="SECRET",
        )

        assert result is False

    @patch("patient_csv_loader.apps.s3_client.Http")
    def test_exception_returns_false(self, mock_http_class: MagicMock) -> None:
        mock_http = MagicMock()
        mock_http.put.side_effect = Exception("Connection timeout")
        mock_http_class.return_value = mock_http

        result = upload_csv_to_s3(
            csv_content="data",
            filename="test.csv",
            bucket="my-bucket",
            access_key_id="AKID",
            secret_access_key="SECRET",
        )

        assert result is False

    @patch("patient_csv_loader.apps.s3_client.Http")
    def test_custom_region(self, mock_http_class: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.ok = True
        mock_http = MagicMock()
        mock_http.put.return_value = mock_response
        mock_http_class.return_value = mock_http

        upload_csv_to_s3(
            csv_content="data",
            filename="test.csv",
            bucket="my-bucket",
            access_key_id="AKID",
            secret_access_key="SECRET",
            region="eu-west-1",
        )

        call_url = mock_http.put.call_args[0][0]
        assert "my-bucket.s3.eu-west-1.amazonaws.com" in call_url

    @patch("patient_csv_loader.apps.s3_client.Http")
    def test_filename_spaces_replaced(self, mock_http_class: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.ok = True
        mock_http = MagicMock()
        mock_http.put.return_value = mock_response
        mock_http_class.return_value = mock_http

        upload_csv_to_s3(
            csv_content="data",
            filename="my patients file.csv",
            bucket="my-bucket",
            access_key_id="AKID",
            secret_access_key="SECRET",
        )

        call_url = mock_http.put.call_args[0][0]
        assert " " not in call_url
        assert "my_patients_file.csv" in call_url

    @patch("patient_csv_loader.apps.s3_client.Http")
    def test_authorization_header_format(self, mock_http_class: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.ok = True
        mock_http = MagicMock()
        mock_http.put.return_value = mock_response
        mock_http_class.return_value = mock_http

        upload_csv_to_s3(
            csv_content="data",
            filename="test.csv",
            bucket="my-bucket",
            access_key_id="AKIAIOSFODNN7EXAMPLE",
            secret_access_key="wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        )

        headers = mock_http.put.call_args[1]["headers"]
        auth = headers["Authorization"]
        assert auth.startswith("AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/")
        assert "SignedHeaders=" in auth
        assert "Signature=" in auth
        assert "x-amz-content-sha256" in headers
        assert "x-amz-date" in headers
