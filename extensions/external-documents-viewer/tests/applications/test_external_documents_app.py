import json
from typing import Any
from unittest.mock import MagicMock, call, patch

from external_documents_viewer.applications.external_documents_app import ExternalDocumentsViewerApp


class TestExternalDocumentsViewerApp:
    """Tests for the ExternalDocumentsViewerApp Application handler."""

    def _make_handler(
        self,
        patient_id: str,
        secrets: dict[str, str],
    ) -> ExternalDocumentsViewerApp:
        handler = ExternalDocumentsViewerApp.__new__(ExternalDocumentsViewerApp)
        handler.event = MagicMock()
        handler.event.context = {"patient": {"id": patient_id}}
        handler.secrets = secrets
        return handler

    def test_on_open_success(
        self,
        mock_patient: MagicMock,
        mock_secrets: dict[str, str],
        sample_documents: list[dict[str, Any]],
    ) -> None:
        """on_open with valid patient and index should render documents in right chart pane."""
        secrets = {**mock_secrets, "S3_PREFIX": "legacy_emr_documents"}
        handler = self._make_handler("patient-uuid-123", secrets)

        s3_content = json.dumps({"documents": sample_documents}).encode()
        mock_s3_obj = MagicMock()
        mock_s3_obj.content = s3_content

        mock_s3_instance = MagicMock()
        mock_s3_instance.is_ready.return_value = True
        mock_s3_instance.access_s3_object.return_value = mock_s3_obj
        presigned_urls = [
            "https://bucket.s3.amazonaws.com/signed-annual",
            "https://bucket.s3.amazonaws.com/signed-mri",
            "https://bucket.s3.amazonaws.com/signed-refill",
        ]
        mock_s3_instance.generate_presigned_url.side_effect = presigned_urls

        with patch(
            "external_documents_viewer.applications.external_documents_app.Patient"
        ) as mock_patient_cls:
            mock_patient_cls.objects.get.return_value = mock_patient
            mock_patient_cls.DoesNotExist = Exception
            with patch(
                "external_documents_viewer.applications.external_documents_app.S3"
            ) as mock_s3_class:
                with patch(
                    "external_documents_viewer.applications.external_documents_app.S3Credentials"
                ) as mock_creds_class:
                    mock_creds_instance = MagicMock()
                    mock_creds_class.return_value = mock_creds_instance
                    mock_s3_class.return_value = mock_s3_instance
                    with patch(
                        "external_documents_viewer.applications.external_documents_app.render_to_string"
                    ) as mock_render:
                        mock_render.return_value = "<html>docs</html>"
                        with patch(
                            "external_documents_viewer.applications.external_documents_app.LaunchModalEffect"
                        ) as mock_modal:
                            mock_effect = MagicMock()
                            mock_modal.return_value = mock_effect
                            mock_effect.apply.return_value = mock_effect

                            result = handler.on_open()

                            assert mock_patient_cls.mock_calls == [
                                call.objects.get(id="patient-uuid-123"),
                                call.objects.get().__bool__(),
                            ]
                            assert mock_creds_class.mock_calls == [
                                call(
                                    key="test-access-key",
                                    secret="test-secret-key",
                                    region="us-west-2",
                                    bucket="test-bucket",
                                )
                            ]
                            prefix = "legacy_emr_documents"
                            assert mock_s3_class.mock_calls == [
                                call(mock_creds_instance),
                                call().is_ready(),
                                call().access_s3_object(
                                    f"{prefix}/patient-indices/patient-uuid-123.json"
                                ),
                                call().generate_presigned_url(
                                    f"{prefix}/PATIENT_DIR/annual_physical.pdf",
                                    expiration=3600,
                                ),
                                call().generate_presigned_url(
                                    f"{prefix}/PATIENT_DIR/mri_scan.pdf",
                                    expiration=3600,
                                ),
                                call().generate_presigned_url(
                                    f"{prefix}/PATIENT_DIR/refill_request.pdf",
                                    expiration=3600,
                                ),
                            ]
                            assert mock_creds_instance.mock_calls == []
                            assert mock_s3_instance.mock_calls == [
                                call.is_ready(),
                                call.access_s3_object(
                                    f"{prefix}/patient-indices/patient-uuid-123.json"
                                ),
                                call.generate_presigned_url(
                                    f"{prefix}/PATIENT_DIR/annual_physical.pdf",
                                    expiration=3600,
                                ),
                                call.generate_presigned_url(
                                    f"{prefix}/PATIENT_DIR/mri_scan.pdf",
                                    expiration=3600,
                                ),
                                call.generate_presigned_url(
                                    f"{prefix}/PATIENT_DIR/refill_request.pdf",
                                    expiration=3600,
                                ),
                            ]
                            assert mock_s3_obj.mock_calls == []

                            expected_docs = [
                                {**sample_documents[0], "url": presigned_urls[0]},
                                {**sample_documents[1], "url": presigned_urls[1]},
                                {**sample_documents[2], "url": presigned_urls[2]},
                            ]
                            assert mock_render.mock_calls == [
                                call(
                                    "templates/document_viewer.html",
                                    {
                                        "patient": mock_patient,
                                        "documents": expected_docs,
                                        "error": None,
                                        "notice": None,
                                    },
                                )
                            ]
                            assert mock_modal.mock_calls == [
                                call(
                                    content="<html>docs</html>",
                                    target=mock_modal.TargetType.RIGHT_CHART_PANE,
                                    title="External Documents",
                                ),
                                call().apply(),
                            ]
                            assert mock_effect.mock_calls == [call.apply()]
                            assert mock_patient.mock_calls == [call.__bool__()]
                            assert result is mock_effect

    def test_on_open_missing_patient_context(self, mock_secrets: dict[str, str]) -> None:
        """on_open should show a notice (not raise) when context has no patient."""
        handler = ExternalDocumentsViewerApp.__new__(ExternalDocumentsViewerApp)
        handler.event = MagicMock()
        handler.event.context = {}
        handler.secrets = mock_secrets

        with patch(
            "external_documents_viewer.applications.external_documents_app.Patient"
        ) as mock_patient_cls:
            with patch(
                "external_documents_viewer.applications.external_documents_app.render_to_string"
            ) as mock_render:
                mock_render.return_value = "<html>notice</html>"
                with patch(
                    "external_documents_viewer.applications.external_documents_app.LaunchModalEffect"
                ) as mock_modal:
                    mock_effect = MagicMock()
                    mock_modal.return_value = mock_effect
                    mock_effect.apply.return_value = mock_effect

                    result = handler.on_open()

                    # Patient lookup must never be attempted without an id.
                    assert mock_patient_cls.mock_calls == []
                    assert mock_render.mock_calls == [
                        call(
                            "templates/document_viewer.html",
                            {
                                "patient": None,
                                "documents": [],
                                "error": None,
                                "notice": "No external documents available. Contact your administrator for assistance.",
                            },
                        )
                    ]
                    assert mock_modal.mock_calls == [
                        call(
                            content="<html>notice</html>",
                            target=mock_modal.TargetType.RIGHT_CHART_PANE,
                            title="External Documents",
                        ),
                        call().apply(),
                    ]
                    assert mock_effect.mock_calls == [call.apply()]
                    assert result is mock_effect

    def test_on_open_patient_not_found(self, mock_secrets: dict[str, str]) -> None:
        """on_open should show notice when patient is not found."""
        handler = self._make_handler("missing-patient", mock_secrets)

        with patch(
            "external_documents_viewer.applications.external_documents_app.Patient"
        ) as mock_patient_cls:
            mock_patient_cls.DoesNotExist = Exception
            mock_patient_cls.objects.get.side_effect = Exception("not found")
            with patch(
                "external_documents_viewer.applications.external_documents_app.render_to_string"
            ) as mock_render:
                mock_render.return_value = "<html>notice</html>"
                with patch(
                    "external_documents_viewer.applications.external_documents_app.LaunchModalEffect"
                ) as mock_modal:
                    mock_effect = MagicMock()
                    mock_modal.return_value = mock_effect
                    mock_effect.apply.return_value = mock_effect

                    result = handler.on_open()

                    assert mock_patient_cls.mock_calls == [
                        call.objects.get(id="missing-patient")
                    ]
                    assert mock_render.mock_calls == [
                        call(
                            "templates/document_viewer.html",
                            {
                                "patient": None,
                                "documents": [],
                                "error": None,
                                "notice": "No external documents available. Contact your administrator for assistance.",
                            },
                        )
                    ]
                    assert mock_modal.mock_calls == [
                        call(
                            content="<html>notice</html>",
                            target=mock_modal.TargetType.RIGHT_CHART_PANE,
                            title="External Documents",
                        ),
                        call().apply(),
                    ]
                    assert mock_effect.mock_calls == [call.apply()]
                    assert result is mock_effect

    def test_on_open_s3_not_ready(
        self, mock_patient: MagicMock, mock_secrets: dict[str, str]
    ) -> None:
        """on_open should show error when S3 client is not ready."""
        handler = self._make_handler("patient-uuid-123", mock_secrets)

        mock_s3_instance = MagicMock()
        mock_s3_instance.is_ready.return_value = False

        with patch(
            "external_documents_viewer.applications.external_documents_app.Patient"
        ) as mock_patient_cls:
            mock_patient_cls.objects.get.return_value = mock_patient
            mock_patient_cls.DoesNotExist = Exception
            with patch(
                "external_documents_viewer.applications.external_documents_app.S3"
            ) as mock_s3_class:
                with patch(
                    "external_documents_viewer.applications.external_documents_app.S3Credentials"
                ) as mock_creds_class:
                    mock_creds_class.return_value = MagicMock()
                    mock_s3_class.return_value = mock_s3_instance
                    with patch(
                        "external_documents_viewer.applications.external_documents_app.render_to_string"
                    ) as mock_render:
                        mock_render.return_value = "<html>error</html>"
                        with patch(
                            "external_documents_viewer.applications.external_documents_app.LaunchModalEffect"
                        ) as mock_modal:
                            mock_effect = MagicMock()
                            mock_modal.return_value = mock_effect
                            mock_effect.apply.return_value = mock_effect

                            result = handler.on_open()

                            assert mock_patient_cls.mock_calls == [
                                call.objects.get(id="patient-uuid-123"),
                                call.objects.get().__bool__(),
                            ]
                            assert mock_s3_instance.mock_calls == [call.is_ready()]
                            assert mock_render.mock_calls == [
                                call(
                                    "templates/document_viewer.html",
                                    {
                                        "patient": mock_patient,
                                        "documents": [],
                                        "error": "Unable to connect to the document storage service. Please try again later.",
                                        "notice": None,
                                    },
                                )
                            ]
                            assert mock_modal.mock_calls == [
                                call(
                                    content="<html>error</html>",
                                    target=mock_modal.TargetType.RIGHT_CHART_PANE,
                                    title="External Documents",
                                ),
                                call().apply(),
                            ]
                            assert mock_effect.mock_calls == [call.apply()]
                            assert mock_patient.mock_calls == [call.__bool__()]
                            assert result is mock_effect

    def test_on_open_s3_fetch_exception(
        self, mock_patient: MagicMock, mock_secrets: dict[str, str]
    ) -> None:
        """on_open should show notice when S3 fetch fails (e.g., missing index file)."""
        handler = self._make_handler("patient-uuid-123", mock_secrets)

        mock_s3_instance = MagicMock()
        mock_s3_instance.is_ready.return_value = True
        mock_s3_instance.access_s3_object.side_effect = Exception("NoSuchKey")

        with patch(
            "external_documents_viewer.applications.external_documents_app.Patient"
        ) as mock_patient_cls:
            mock_patient_cls.objects.get.return_value = mock_patient
            mock_patient_cls.DoesNotExist = Exception
            with patch(
                "external_documents_viewer.applications.external_documents_app.S3"
            ) as mock_s3_class:
                with patch(
                    "external_documents_viewer.applications.external_documents_app.S3Credentials"
                ) as mock_creds_class:
                    mock_creds_class.return_value = MagicMock()
                    mock_s3_class.return_value = mock_s3_instance
                    with patch(
                        "external_documents_viewer.applications.external_documents_app.render_to_string"
                    ) as mock_render:
                        mock_render.return_value = "<html>notice</html>"
                        with patch(
                            "external_documents_viewer.applications.external_documents_app.LaunchModalEffect"
                        ) as mock_modal:
                            mock_effect = MagicMock()
                            mock_modal.return_value = mock_effect
                            mock_effect.apply.return_value = mock_effect

                            result = handler.on_open()

                            assert mock_patient_cls.mock_calls == [
                                call.objects.get(id="patient-uuid-123"),
                                call.objects.get().__bool__(),
                            ]
                            assert mock_s3_instance.mock_calls == [
                                call.is_ready(),
                                call.access_s3_object(
                                    "patient-indices/patient-uuid-123.json"
                                ),
                            ]
                            assert mock_render.mock_calls == [
                                call(
                                    "templates/document_viewer.html",
                                    {
                                        "patient": mock_patient,
                                        "documents": [],
                                        "error": None,
                                        "notice": "No external documents available. Contact your administrator for assistance.",
                                    },
                                )
                            ]
                            assert mock_modal.mock_calls == [
                                call(
                                    content="<html>notice</html>",
                                    target=mock_modal.TargetType.RIGHT_CHART_PANE,
                                    title="External Documents",
                                ),
                                call().apply(),
                            ]
                            assert mock_effect.mock_calls == [call.apply()]
                            assert mock_patient.mock_calls == [call.__bool__()]
                            assert result is mock_effect
