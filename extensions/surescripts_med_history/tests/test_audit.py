from unittest.mock import MagicMock, patch

from surescripts_med_history.protocols.audit import logged_in_user_id, staff_label


class TestStaffLabel:
    def test_formats_name_and_id(self):
        staff = MagicMock(id="abc-123", first_name="Ann", last_name="Doe")
        assert staff_label(staff) == "Ann Doe (abc-123)"

    def test_unnamed_staff_still_carries_the_id(self):
        staff = MagicMock(id="abc-123", first_name="", last_name="")
        assert staff_label(staff) == "unnamed (abc-123)"

    def test_unresolved_staff_falls_back_to_the_session_id(self):
        assert staff_label(None, "session-9") == "unknown (session-9)"

    def test_unresolved_staff_without_id(self):
        assert staff_label(None) == "unknown"


class TestLoggedInUserId:
    def test_reads_the_canvas_session_header(self):
        request = MagicMock()
        request.headers = {"canvas-logged-in-user-id": "staff-1"}
        assert logged_in_user_id(request) == "staff-1"

    def test_missing_header_is_empty(self):
        request = MagicMock()
        request.headers = {}
        assert logged_in_user_id(request) == ""


class TestRequestAuditLogging:
    """The initiator is only recorded in the log stream, so assert on it."""

    @staticmethod
    def _handler(body, logged_in):
        from surescripts_med_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.headers = {"canvas-logged-in-user-id": logged_in}
        handler.request.json.return_value = body
        return handler

    @patch("surescripts_med_history.protocols.view.log")
    @patch("surescripts_med_history.protocols.view.Note")
    @patch("surescripts_med_history.protocols.view.Patient")
    @patch("surescripts_med_history.protocols.view.Staff")
    def test_on_behalf_of_logs_initiator_and_selected_provider(
        self, mock_staff_cls, mock_patient_cls, mock_note_cls, mock_log
    ):
        care_manager = MagicMock(id="cm-1", first_name="Cara", last_name="Manager")
        care_manager.spi_number = ""
        prescriber = MagicMock(id="dr-9", first_name="Dee", last_name="Prescriber")
        prescriber.spi_number = "SPI123"

        def get(**kwargs):
            return prescriber if kwargs.get("id") == "dr-9" else care_manager

        mock_staff_cls.objects.get.side_effect = get
        mock_note_cls.objects.filter.return_value.filter.return_value.order_by.return_value.first.return_value = None

        handler = self._handler({"patient_id": "p1", "staff_id": "dr-9"}, "cm-1")
        handler.request_med_history()

        line = mock_log.info.call_args[0][0]
        assert "Surescripts request:" in line
        assert "initiator Cara Manager (cm-1)" in line
        assert "on behalf of selected provider Dee Prescriber (dr-9)" in line

    @patch("surescripts_med_history.protocols.view.log")
    @patch("surescripts_med_history.protocols.view.Note")
    @patch("surescripts_med_history.protocols.view.Patient")
    @patch("surescripts_med_history.protocols.view.Staff")
    def test_self_request_is_labeled_as_themselves(
        self, mock_staff_cls, mock_patient_cls, mock_note_cls, mock_log
    ):
        prescriber = MagicMock(id="dr-9", first_name="Dee", last_name="Prescriber")
        prescriber.spi_number = "SPI123"
        mock_staff_cls.objects.get.return_value = prescriber
        mock_note_cls.objects.filter.return_value.filter.return_value.order_by.return_value.first.return_value = None

        handler = self._handler({"patient_id": "p1"}, "dr-9")
        handler.request_med_history()

        line = mock_log.info.call_args[0][0]
        assert "initiator Dee Prescriber (dr-9)" in line
        assert "as themselves" in line

    @patch("surescripts_med_history.protocols.view.log")
    @patch("surescripts_med_history.protocols.view.Note")
    @patch("surescripts_med_history.protocols.view.Patient")
    @patch("surescripts_med_history.protocols.view.Staff")
    def test_unresolvable_session_still_logs_the_id(
        self, mock_staff_cls, mock_patient_cls, mock_note_cls, mock_log
    ):
        class DoesNotExist(Exception):
            pass

        prescriber = MagicMock(id="dr-9", first_name="Dee", last_name="Prescriber")
        prescriber.spi_number = "SPI123"
        mock_staff_cls.DoesNotExist = DoesNotExist

        def get(**kwargs):
            if kwargs.get("id") == "dr-9":
                return prescriber
            raise DoesNotExist("gone")

        mock_staff_cls.objects.get.side_effect = get
        mock_note_cls.objects.filter.return_value.filter.return_value.order_by.return_value.first.return_value = None

        handler = self._handler({"patient_id": "p1", "staff_id": "dr-9"}, "ghost-1")
        handler.request_med_history()

        line = mock_log.info.call_args[0][0]
        assert "initiator unknown (ghost-1)" in line
