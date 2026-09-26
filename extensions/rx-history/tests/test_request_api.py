import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch


class _FakeDoesNotExist(Exception):
    pass


class TestRequestMedHistory:
    @patch("rx_history.protocols.view.Patient")
    def test_requires_patient_id(self, mock_patient_cls):
        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {}
        results = handler.request_med_history()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("rx_history.protocols.view.Patient")
    def test_returns_404_when_patient_not_found(self, mock_patient_cls):
        mock_patient_cls.DoesNotExist = _FakeDoesNotExist
        mock_patient_cls.objects.select_related.return_value.get.side_effect = (
            _FakeDoesNotExist("not found")
        )

        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"patient_id": "missing"}
        results = handler.request_med_history()
        assert results[0].status_code == HTTPStatus.NOT_FOUND

    @patch("rx_history.protocols.view.Patient")
    def test_returns_400_when_no_default_provider(self, mock_patient_cls):
        patient = MagicMock()
        patient.default_provider = None
        mock_patient_cls.objects.select_related.return_value.get.return_value = patient

        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"patient_id": "p1"}
        results = handler.request_med_history()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("rx_history.protocols.view.has_care_event_within", return_value=True)
    @patch("rx_history.protocols.view.Patient")
    def test_returns_200_and_effect_on_success(self, mock_patient_cls, mock_gate):
        patient = MagicMock()
        patient.default_provider = MagicMock(id="prov-1")
        mock_patient_cls.objects.select_related.return_value.get.return_value = patient

        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"patient_id": "p1"}
        results = handler.request_med_history()
        assert results[0].status_code == HTTPStatus.OK
        assert len(results) == 2


class TestRequestMedHistoryCareEventGuard:
    @patch("rx_history.protocols.view.has_care_event_within", return_value=False)
    @patch("rx_history.protocols.view.Patient")
    def test_refuses_without_care_event(self, mock_patient_cls, mock_gate):
        patient = MagicMock()
        patient.default_provider = MagicMock(id="prov-1")
        mock_patient_cls.objects.select_related.return_value.get.return_value = patient

        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"patient_id": "p1"}
        results = handler.request_med_history()

        assert results[0].status_code == HTTPStatus.FORBIDDEN
        body = json.loads(results[0].content.decode("utf-8"))
        assert body["error"] == "no_care_event"
        assert body["window_days"] == 7
        assert len(results) == 1
        mock_gate.assert_called_once_with("p1")

    @patch("rx_history.protocols.view.has_care_event_within", return_value=True)
    @patch("rx_history.protocols.view.Patient")
    def test_allows_with_care_event(self, mock_patient_cls, mock_gate):
        patient = MagicMock()
        patient.default_provider = MagicMock(id="prov-1")
        mock_patient_cls.objects.select_related.return_value.get.return_value = patient

        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"patient_id": "p1"}
        results = handler.request_med_history()

        assert results[0].status_code == HTTPStatus.OK
        assert len(results) == 2
        mock_gate.assert_called_once_with("p1")


class TestAddMedication:
    @patch("rx_history.protocols.view.Patient")
    def test_requires_patient_id_and_drug_description(self, mock_patient_cls):
        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"patient_id": "p1"}
        results = handler.add_medication()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("rx_history.protocols.view.Patient")
    def test_returns_404_when_patient_not_found(self, mock_patient_cls):
        mock_patient_cls.DoesNotExist = _FakeDoesNotExist
        mock_patient_cls.objects.get.side_effect = _FakeDoesNotExist("not found")

        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_id": "missing",
            "drug_description": "Drug A",
        }
        results = handler.add_medication()
        assert results[0].status_code == HTTPStatus.NOT_FOUND

    @patch("rx_history.protocols.view.Note")
    @patch("rx_history.protocols.view.Patient")
    def test_returns_422_when_no_open_note(self, mock_patient_cls, mock_note_cls):
        mock_patient_cls.objects.get.return_value = MagicMock()
        mock_note_qs = MagicMock()
        mock_note_cls.objects.filter.return_value = mock_note_qs
        mock_note_qs.filter.return_value = mock_note_qs
        mock_note_qs.order_by.return_value = mock_note_qs
        mock_note_qs.first.return_value = None

        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_id": "p1",
            "drug_description": "Drug A",
        }
        results = handler.add_medication()
        assert results[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    @patch("rx_history.protocols.view._lookup_fdb_code")
    @patch("rx_history.protocols.view.Note")
    @patch("rx_history.protocols.view.Patient")
    def test_returns_422_when_fdb_lookup_fails(
        self, mock_patient_cls, mock_note_cls, mock_lookup
    ):
        mock_patient_cls.objects.get.return_value = MagicMock()
        note = MagicMock(id="note-1")
        mock_note_qs = MagicMock()
        mock_note_cls.objects.filter.return_value = mock_note_qs
        mock_note_qs.filter.return_value = mock_note_qs
        mock_note_qs.order_by.return_value = mock_note_qs
        mock_note_qs.first.return_value = note
        mock_lookup.return_value = None

        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_id": "p1",
            "drug_description": "Drug A",
        }
        results = handler.add_medication()
        assert results[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    @patch("rx_history.protocols.view.MedicationStatementCommand")
    @patch("rx_history.protocols.view._lookup_fdb_code")
    @patch("rx_history.protocols.view.Note")
    @patch("rx_history.protocols.view.Patient")
    def test_returns_200_and_originates_command_on_success(
        self, mock_patient_cls, mock_note_cls, mock_lookup, mock_cmd_cls
    ):
        mock_patient_cls.objects.get.return_value = MagicMock()
        note = MagicMock(id="note-1")
        mock_note_qs = MagicMock()
        mock_note_cls.objects.filter.return_value = mock_note_qs
        mock_note_qs.filter.return_value = mock_note_qs
        mock_note_qs.order_by.return_value = mock_note_qs
        mock_note_qs.first.return_value = note
        mock_lookup.return_value = 98765

        mock_cmd = MagicMock()
        mock_cmd_cls.return_value = mock_cmd

        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_id": "p1",
            "drug_description": "Drug A",
            "sig": "Take 1 daily",
            "rxnorm_rxcui": "866083",
        }
        results = handler.add_medication()
        assert results[0].status_code == HTTPStatus.OK
        assert len(results) == 2
        mock_cmd_cls.assert_called_once_with(
            note_uuid=str(note.id),
            fdb_code="98765",
            sig="Take 1 daily",
        )


class TestAddMedicationNoteTargeting:
    @patch("rx_history.protocols.view.MedicationStatementCommand")
    @patch("rx_history.protocols.view._lookup_fdb_code")
    @patch("rx_history.protocols.view.Note")
    @patch("rx_history.protocols.view.Patient")
    def test_uses_provided_note_id(
        self, mock_patient_cls, mock_note_cls, mock_lookup, mock_cmd_cls
    ):
        mock_patient_cls.objects.get.return_value = MagicMock()
        note = MagicMock(id="specific-note")
        mock_note_qs = MagicMock()
        mock_note_cls.objects.filter.return_value = mock_note_qs
        mock_note_qs.filter.return_value = mock_note_qs
        mock_note_qs.first.return_value = note
        mock_lookup.return_value = 11111

        mock_cmd = MagicMock()
        mock_cmd_cls.return_value = mock_cmd

        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_id": "p1",
            "drug_description": "Drug A",
            "note_id": "specific-note",
        }
        results = handler.add_medication()
        assert results[0].status_code == HTTPStatus.OK
        mock_cmd_cls.assert_called_once_with(
            note_uuid=str(note.id),
            fdb_code="11111",
            sig=None,
        )

    @patch("rx_history.protocols.view.Note")
    @patch("rx_history.protocols.view.Patient")
    def test_returns_422_when_note_id_not_found(
        self, mock_patient_cls, mock_note_cls
    ):
        mock_patient_cls.objects.get.return_value = MagicMock()
        mock_note_qs = MagicMock()
        mock_note_cls.objects.filter.return_value = mock_note_qs
        mock_note_qs.filter.return_value = mock_note_qs
        mock_note_qs.first.return_value = None

        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_id": "p1",
            "drug_description": "Drug A",
            "note_id": "bad-note-id",
        }
        results = handler.add_medication()
        assert results[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    @patch("rx_history.protocols.view.MedicationStatementCommand")
    @patch("rx_history.protocols.view._lookup_fdb_code")
    @patch("rx_history.protocols.view.Note")
    @patch("rx_history.protocols.view.Patient")
    def test_falls_back_to_most_recent_when_no_note_id(
        self, mock_patient_cls, mock_note_cls, mock_lookup, mock_cmd_cls
    ):
        mock_patient_cls.objects.get.return_value = MagicMock()
        note = MagicMock(id="most-recent-note")
        mock_note_qs = MagicMock()
        mock_note_cls.objects.filter.return_value = mock_note_qs
        mock_note_qs.filter.return_value = mock_note_qs
        mock_note_qs.order_by.return_value = mock_note_qs
        mock_note_qs.first.return_value = note
        mock_lookup.return_value = 22222

        mock_cmd = MagicMock()
        mock_cmd_cls.return_value = mock_cmd

        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_id": "p1",
            "drug_description": "Drug A",
        }
        results = handler.add_medication()
        assert results[0].status_code == HTTPStatus.OK
        mock_cmd_cls.assert_called_once_with(
            note_uuid=str(note.id),
            fdb_code="22222",
            sig=None,
        )


class TestDismissMedication:
    def test_requires_patient_id_and_drug_description(self):
        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"patient_id": "p1"}
        results = handler.dismiss_medication()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("rx_history.protocols.view.dismiss")
    def test_returns_200_on_success(self, mock_dismiss):
        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_id": "p1",
            "drug_description": "Tamiflu 75mg",
            "ndc_code": "12345",
            "last_fill_date": "Jan 10, 2025",
        }
        handler.request.headers = {"canvas-logged-in-user-id": "staff-1"}
        results = handler.dismiss_medication()
        assert results[0].status_code == HTTPStatus.OK
        mock_dismiss.assert_called_once_with(
            "p1", "staff-1", "Tamiflu 75mg", "12345", "Jan 10, 2025"
        )

    def test_returns_401_when_staff_id_missing(self):
        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_id": "p1",
            "drug_description": "Tamiflu 75mg",
            "ndc_code": "12345",
            "last_fill_date": "Jan 10, 2025",
        }
        handler.request.headers = {}
        results = handler.dismiss_medication()
        assert results[0].status_code == HTTPStatus.UNAUTHORIZED


class TestUndoDismissMedication:
    def test_requires_patient_id_and_drug_description(self):
        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"patient_id": "p1"}
        results = handler.undo_dismiss_medication()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("rx_history.protocols.view.undo_dismissal")
    def test_returns_200_when_entry_removed(self, mock_undo):
        mock_undo.return_value = True
        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_id": "p1",
            "drug_description": "Tamiflu 75mg",
            "ndc_code": "12345",
            "last_fill_date": "Jan 10, 2025",
        }
        results = handler.undo_dismiss_medication()
        assert results[0].status_code == HTTPStatus.OK

    @patch("rx_history.protocols.view.undo_dismissal")
    def test_returns_404_when_not_found(self, mock_undo):
        mock_undo.return_value = False
        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_id": "p1",
            "drug_description": "Unknown Drug",
            "ndc_code": "",
            "last_fill_date": "",
        }
        results = handler.undo_dismiss_medication()
        assert results[0].status_code == HTTPStatus.NOT_FOUND


class TestLookupFdbCode:
    @patch("rx_history.protocols.view.ontologies_http")
    def test_rxnorm_lookup_returns_fdb_code(self, mock_http):
        resp = MagicMock()
        resp.json.return_value = [{"med_medication_id": 12345}]
        mock_http.get_json.return_value = resp

        from rx_history.protocols.view import _lookup_fdb_code

        result = _lookup_fdb_code("Drug A", rxnorm_rxcui="866083")
        assert result == 12345

    @patch("rx_history.protocols.view.ontologies_http")
    def test_falls_back_to_text_search(self, mock_http):
        rxnorm_resp = MagicMock()
        rxnorm_resp.json.return_value = []
        text_resp = MagicMock()
        text_resp.json.return_value = {"results": [{"med_medication_id": 67890}]}
        mock_http.get_json.side_effect = [rxnorm_resp, text_resp]

        from rx_history.protocols.view import _lookup_fdb_code

        result = _lookup_fdb_code("Drug A", rxnorm_rxcui="999")
        assert result == 67890

    @patch("rx_history.protocols.view.ontologies_http")
    def test_returns_none_on_failure(self, mock_http):
        mock_http.get_json.side_effect = Exception("network error")

        from rx_history.protocols.view import _lookup_fdb_code

        result = _lookup_fdb_code("Drug A")
        assert result is None


class TestStateEndpoint:
    @patch("rx_history.protocols.view.Patient")
    def test_requires_patient_id(self, mock_patient_cls):
        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {}
        results = handler.state()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("rx_history.protocols.view.Patient")
    def test_returns_404_when_patient_not_found(self, mock_patient_cls):
        mock_patient_cls.DoesNotExist = _FakeDoesNotExist
        mock_patient_cls.objects.select_related.return_value.get.side_effect = (
            _FakeDoesNotExist("not found")
        )

        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"patient_id": "missing"}
        results = handler.state()
        assert results[0].status_code == HTTPStatus.NOT_FOUND

    @patch("rx_history.protocols.view.build_modal_context")
    @patch("rx_history.protocols.view.Patient")
    def test_returns_payload_shape(self, mock_patient_cls, mock_build):
        patient = MagicMock()
        mock_patient_cls.objects.select_related.return_value.get.return_value = patient
        mock_build.return_value = {
            "grouped_items": [{"drug_description": "Lisinopril", "is_match": True, "is_staged": False}],
            "dismissed_items": [],
            "dismissed_count": 0,
            "active_rxnorm": ["314076"],
            "active_ndc": [],
            "active_descriptions": ["lisinopril 10 mg tablet"],
            "active_meds": [{"description": "Lisinopril", "rxnorm_codes": ["314076"], "ndc_codes": []}],
            "open_notes": [],
            "last_pulled_iso": "2026-04-20T05:11:00+00:00",
        }

        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"patient_id": "p1"}
        results = handler.state()
        assert results[0].status_code == HTTPStatus.OK
        mock_build.assert_called_once_with(patient)

    @patch("rx_history.protocols.view.build_modal_context")
    @patch("rx_history.protocols.view.Patient")
    def test_passes_through_staged_flag(self, mock_patient_cls, mock_build):
        patient = MagicMock()
        mock_patient_cls.objects.select_related.return_value.get.return_value = patient
        mock_build.return_value = {
            "grouped_items": [
                {"drug_description": "Metformin", "is_match": True, "is_staged": True}
            ],
            "dismissed_items": [],
            "dismissed_count": 0,
            "active_rxnorm": [],
            "active_ndc": [],
            "active_descriptions": [],
            "active_meds": [],
            "open_notes": [],
            "last_pulled_iso": "",
        }

        from rx_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"patient_id": "p1"}
        results = handler.state()
        assert results[0].status_code == HTTPStatus.OK
