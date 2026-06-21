"""Tests for the ACCESSOperationLog audit helper."""
from unittest.mock import MagicMock, patch

from cms_access_fhir_client.models import ACCESSOperationLog
from cms_access_fhir_client.operation_log import record_operation_event


class TestRecordOperationEvent:
    def test_creates_row_and_derives_result_system_from_op(self):
        patient = MagicMock()
        with patch.object(ACCESSOperationLog, "objects") as objects:
            record_operation_event(
                patient=patient,
                track="CKM",
                operation="align",
                phase=ACCESSOperationLog.PHASE_RESULT,
                result_code="aligned",
                http_status=200,
            )
        objects.create.assert_called_once()
        kwargs = objects.create.call_args.kwargs
        assert kwargs["operation"] == "align"
        assert kwargs["result_code"] == "aligned"
        # result_system is filled in from the operation when not passed explicitly.
        assert kwargs["result_system"] == ACCESSOperationLog.SYSTEM_ALIGNMENT
        assert kwargs["track"] == "CKM"
        assert kwargs["http_status"] == 200

    def test_explicit_result_system_is_preserved(self):
        with patch.object(ACCESSOperationLog, "objects") as objects:
            record_operation_event(
                patient=MagicMock(),
                track="eCKM",
                operation="unalign",
                phase=ACCESSOperationLog.PHASE_RESULT,
                result_code="patient-not-aligned",
                result_system=ACCESSOperationLog.SYSTEM_UNALIGNMENT,
            )
        assert objects.create.call_args.kwargs["result_system"] == ACCESSOperationLog.SYSTEM_UNALIGNMENT

    def test_swallows_db_errors(self):
        """Audit logging must never break the actual operation."""
        with patch.object(ACCESSOperationLog, "objects") as objects:
            objects.create.side_effect = RuntimeError("db unavailable")
            # Should not raise.
            record_operation_event(
                patient=MagicMock(),
                track="CKM",
                operation="align",
                phase=ACCESSOperationLog.PHASE_SUBMITTED,
            )
