from unittest.mock import MagicMock, call, patch

import pytest

from rx_error_notification.rx_error_handler import RxErrorNotificationHandler


@pytest.fixture
def mock_event():
    event = MagicMock()
    event.target = "rx-uuid-123"
    event.context = {"patient": {"id": "patient-uuid-456"}}
    return event


@pytest.fixture
def mock_patient():
    patient = MagicMock()
    patient.id = "patient-uuid-456"
    patient.first_name = "Jane"
    patient.last_name = "Smith"
    return patient


@pytest.fixture
def mock_prescriber():
    prescriber = MagicMock()
    prescriber.id = "staff-uuid-789"
    return prescriber


@pytest.fixture
def mock_medication():
    medication = MagicMock()
    mock_coding = MagicMock()
    mock_coding.display = "Amoxicillin 500mg Capsule"
    medication.codings.first.return_value = mock_coding
    return medication


@pytest.fixture
def mock_prescription(mock_patient, mock_prescriber, mock_medication):
    rx = MagicMock()
    rx.patient = mock_patient
    rx.prescriber = mock_prescriber
    rx.medication = mock_medication
    rx.sig_original_input = "Take 1 capsule by mouth three times daily"
    rx.dose_quantity = 1.0
    rx.dispense_quantity = 30.0
    rx.count_of_refills_allowed = 2
    rx.pharmacy_name = "CVS Pharmacy #1234"
    rx.error_message = "Pharmacy rejected - insurance not on file"
    return rx


def _create_handler(mock_event):
    handler = RxErrorNotificationHandler()
    handler.event = mock_event
    return handler


class TestRxErrorNotificationHandler:
    def test_responds_to_prescription_errored(self):
        assert RxErrorNotificationHandler.RESPONDS_TO == "PRESCRIPTION_ERRORED"

    def test_creates_task_with_comment(self, mock_event, mock_prescription):
        handler = _create_handler(mock_event)

        with patch(
            "rx_error_notification.rx_error_handler.Prescription.objects"
        ) as mock_objects, patch(
            "rx_error_notification.rx_error_handler.AddTask"
        ) as mock_add_task, patch(
            "rx_error_notification.rx_error_handler.AddTaskComment"
        ) as mock_add_comment, patch(
            "rx_error_notification.rx_error_handler.arrow"
        ) as mock_arrow, patch(
            "rx_error_notification.rx_error_handler.uuid4"
        ) as mock_uuid:
            mock_objects.select_related.return_value.get.return_value = (
                mock_prescription
            )
            mock_now = MagicMock()
            mock_arrow.utcnow.return_value.datetime = mock_now
            mock_uuid.return_value = "generated-task-uuid"

            mock_task_instance = MagicMock()
            mock_add_task.return_value = mock_task_instance

            mock_comment_instance = MagicMock()
            mock_add_comment.return_value = mock_comment_instance

            effects = handler.compute()

            # Verify Prescription.objects query chain
            assert mock_objects.mock_calls[:2] == [
                call.select_related("prescriber", "patient", "medication"),
                call.select_related().get(id="rx-uuid-123"),
            ]

            # Verify AddTask title has patient name and medication
            actual_task_call = mock_add_task.mock_calls[0]
            assert actual_task_call.kwargs["title"] == "RX ERROR Jane Smith - Amoxicillin 500mg Capsule"
            assert actual_task_call.kwargs["id"] == "generated-task-uuid"
            assert actual_task_call.kwargs["assignee_id"] == "staff-uuid-789"
            assert actual_task_call.kwargs["patient_id"] == "patient-uuid-456"
            assert actual_task_call.kwargs["due"] == mock_now
            assert actual_task_call.kwargs["labels"] == ["RX-ERROR"]

            # Verify AddTaskComment has prescription details
            comment_call = mock_add_comment.mock_calls[0]
            assert comment_call.kwargs["task_id"] == "generated-task-uuid"
            body = comment_call.kwargs["body"]
            assert "Medication: Amoxicillin 500mg Capsule" in body
            assert "Sig: Take 1 capsule by mouth three times daily" in body
            assert "Dose Quantity: 1.0" in body
            assert "Dispense Quantity: 30.0" in body
            assert "Refills: 2" in body
            assert "Pharmacy: CVS Pharmacy #1234" in body
            assert "Error: Pharmacy rejected - insurance not on file" in body

            # Verify two effects: task + comment
            assert len(effects) == 2
            assert effects[0] == mock_task_instance.apply()
            assert effects[1] == mock_comment_instance.apply()

    def test_prescription_not_found(self, mock_event):
        handler = _create_handler(mock_event)

        from canvas_sdk.v1.data.prescription import Prescription as RealPrescription

        with patch(
            "rx_error_notification.rx_error_handler.Prescription.objects"
        ) as mock_objects, patch(
            "rx_error_notification.rx_error_handler.Prescription.DoesNotExist",
            RealPrescription.DoesNotExist,
        ), patch(
            "rx_error_notification.rx_error_handler.log"
        ) as mock_log:
            mock_objects.select_related.return_value.get.side_effect = (
                RealPrescription.DoesNotExist("not found")
            )

            effects = handler.compute()

            assert mock_objects.mock_calls == [
                call.select_related("prescriber", "patient", "medication"),
                call.select_related().get(id="rx-uuid-123"),
            ]

            assert mock_log.mock_calls == [
                call.error("Prescription rx-uuid-123 not found")
            ]

            assert effects == []

    def test_missing_prescriber(self, mock_event, mock_patient):
        handler = _create_handler(mock_event)

        mock_rx = MagicMock()
        mock_rx.patient = mock_patient
        mock_rx.prescriber = None

        with patch(
            "rx_error_notification.rx_error_handler.Prescription.objects"
        ) as mock_objects, patch(
            "rx_error_notification.rx_error_handler.log"
        ) as mock_log:
            mock_objects.select_related.return_value.get.return_value = mock_rx

            effects = handler.compute()

            assert mock_objects.mock_calls[:2] == [
                call.select_related("prescriber", "patient", "medication"),
                call.select_related().get(id="rx-uuid-123"),
            ]

            assert mock_log.mock_calls == [
                call.warning(
                    "Prescription rx-uuid-123 missing patient or prescriber"
                )
            ]

            assert effects == []

    def test_missing_patient(self, mock_event, mock_prescriber):
        handler = _create_handler(mock_event)

        mock_rx = MagicMock()
        mock_rx.patient = None
        mock_rx.prescriber = mock_prescriber

        with patch(
            "rx_error_notification.rx_error_handler.Prescription.objects"
        ) as mock_objects, patch(
            "rx_error_notification.rx_error_handler.log"
        ) as mock_log:
            mock_objects.select_related.return_value.get.return_value = mock_rx

            effects = handler.compute()

            assert mock_objects.mock_calls[:2] == [
                call.select_related("prescriber", "patient", "medication"),
                call.select_related().get(id="rx-uuid-123"),
            ]

            assert mock_log.mock_calls == [
                call.warning(
                    "Prescription rx-uuid-123 missing patient or prescriber"
                )
            ]

            assert effects == []

    def test_missing_medication_uses_unknown(
        self, mock_event, mock_patient, mock_prescriber
    ):
        handler = _create_handler(mock_event)

        mock_rx = MagicMock()
        mock_rx.patient = mock_patient
        mock_rx.prescriber = mock_prescriber
        mock_rx.medication = None
        mock_rx.sig_original_input = None
        mock_rx.dose_quantity = None
        mock_rx.dispense_quantity = None
        mock_rx.count_of_refills_allowed = None
        mock_rx.pharmacy_name = None
        mock_rx.error_message = "Some error"

        with patch(
            "rx_error_notification.rx_error_handler.Prescription.objects"
        ) as mock_objects, patch(
            "rx_error_notification.rx_error_handler.AddTask"
        ) as mock_add_task, patch(
            "rx_error_notification.rx_error_handler.AddTaskComment"
        ) as mock_add_comment, patch(
            "rx_error_notification.rx_error_handler.arrow"
        ) as mock_arrow, patch(
            "rx_error_notification.rx_error_handler.uuid4"
        ) as mock_uuid:
            mock_objects.select_related.return_value.get.return_value = mock_rx
            mock_uuid.return_value = "generated-task-uuid"
            mock_task_instance = MagicMock()
            mock_add_task.return_value = mock_task_instance
            mock_comment_instance = MagicMock()
            mock_add_comment.return_value = mock_comment_instance

            effects = handler.compute()

            actual_call = mock_add_task.mock_calls[0]
            assert "Unknown Medication" in actual_call.kwargs["title"]

            comment_call = mock_add_comment.mock_calls[0]
            assert comment_call.kwargs["body"] == "Error: Some error"

            assert len(effects) == 2

    def test_no_error_message_still_creates_task(
        self, mock_event, mock_prescription
    ):
        handler = _create_handler(mock_event)
        mock_prescription.error_message = None

        with patch(
            "rx_error_notification.rx_error_handler.Prescription.objects"
        ) as mock_objects, patch(
            "rx_error_notification.rx_error_handler.AddTask"
        ) as mock_add_task, patch(
            "rx_error_notification.rx_error_handler.AddTaskComment"
        ) as mock_add_comment, patch(
            "rx_error_notification.rx_error_handler.arrow"
        ) as mock_arrow, patch(
            "rx_error_notification.rx_error_handler.uuid4"
        ) as mock_uuid:
            mock_objects.select_related.return_value.get.return_value = (
                mock_prescription
            )
            mock_uuid.return_value = "generated-task-uuid"
            mock_task_instance = MagicMock()
            mock_add_task.return_value = mock_task_instance
            mock_comment_instance = MagicMock()
            mock_add_comment.return_value = mock_comment_instance

            effects = handler.compute()

            comment_call = mock_add_comment.mock_calls[0]
            assert "Error:" not in comment_call.kwargs["body"]

            assert len(effects) == 2

    def test_generic_exception_returns_empty(self, mock_event):
        handler = _create_handler(mock_event)

        with patch(
            "rx_error_notification.rx_error_handler.Prescription.objects"
        ) as mock_objects, patch(
            "rx_error_notification.rx_error_handler.log"
        ) as mock_log:
            mock_objects.select_related.return_value.get.side_effect = (
                RuntimeError("DB connection lost")
            )

            effects = handler.compute()

            assert mock_log.mock_calls == [
                call.error(
                    "Error handling prescription error event: DB connection lost"
                )
            ]

            assert effects == []

    def test_medication_coding_display_used_for_name(
        self, mock_event, mock_patient, mock_prescriber
    ):
        handler = _create_handler(mock_event)

        mock_rx = MagicMock()
        mock_rx.patient = mock_patient
        mock_rx.prescriber = mock_prescriber
        mock_coding = MagicMock()
        mock_coding.display = "Lisinopril 10mg Tablet"
        mock_rx.medication.codings.first.return_value = mock_coding
        mock_rx.sig_original_input = None
        mock_rx.dose_quantity = None
        mock_rx.dispense_quantity = None
        mock_rx.count_of_refills_allowed = None
        mock_rx.pharmacy_name = None
        mock_rx.error_message = "Rejected"

        with patch(
            "rx_error_notification.rx_error_handler.Prescription.objects"
        ) as mock_objects, patch(
            "rx_error_notification.rx_error_handler.AddTask"
        ) as mock_add_task, patch(
            "rx_error_notification.rx_error_handler.AddTaskComment"
        ) as mock_add_comment, patch(
            "rx_error_notification.rx_error_handler.arrow"
        ) as mock_arrow, patch(
            "rx_error_notification.rx_error_handler.uuid4"
        ) as mock_uuid:
            mock_objects.select_related.return_value.get.return_value = mock_rx
            mock_uuid.return_value = "generated-task-uuid"
            mock_task_instance = MagicMock()
            mock_add_task.return_value = mock_task_instance
            mock_comment_instance = MagicMock()
            mock_add_comment.return_value = mock_comment_instance

            effects = handler.compute()

            actual_call = mock_add_task.mock_calls[0]
            assert actual_call.kwargs["title"] == "RX ERROR Jane Smith - Lisinopril 10mg Tablet"
