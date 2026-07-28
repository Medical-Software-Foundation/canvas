import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch
from uuid import uuid4

NOTE_UUID_1 = str(uuid4())
NOTE_UUID_2 = str(uuid4())


def _parse_response(resp):
    """Parse a JSONResponse's content bytes into a dict."""
    return json.loads(resp.content.decode("utf-8"))


class TestGetAppointments:
    @patch("surescripts_med_history.protocols.bulk_api.Appointment")
    def test_requires_date_params(self, mock_appt):
        from surescripts_med_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {"date_from": "", "date_to": ""}
        results = handler.get_appointments()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("surescripts_med_history.protocols.bulk_api.Appointment")
    def test_returns_appointments(self, mock_appt_cls):
        patient = MagicMock()
        patient.id = "p1"
        patient.first_name = "Jane"
        patient.last_name = "Doe"
        provider = MagicMock()
        provider.id = "prov1"
        provider.first_name = "Dr"
        provider.last_name = "Smith"

        from datetime import datetime

        appt = MagicMock()
        appt.patient = patient
        appt.provider = provider
        appt.start_time = datetime(2026, 4, 1, 10, 30)

        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.only.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.iterator.return_value = iter([appt])

        from surescripts_med_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {
            "date_from": "2026-04-01",
            "date_to": "2026-04-07",
            "provider_ids": "",
        }
        results = handler.get_appointments()
        data = _parse_response(results[0])
        assert len(data["appointments"]) == 1
        assert data["appointments"][0]["patient_name"] == "Jane Doe"

    @patch("surescripts_med_history.protocols.bulk_api.Appointment")
    def test_excludes_providers_without_spi(self, mock_appt_cls):
        """The /appointments list must mirror the SPI gate applied at request
        time — otherwise the user can select patients that get silently
        skipped on submit."""
        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.only.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.iterator.return_value = iter([])

        from surescripts_med_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {
            "date_from": "2026-04-01",
            "date_to": "2026-04-07",
            "provider_ids": "",
        }
        handler.get_appointments()

        # Verify the SPI gate is applied via .filter(provider__spi_number__gt="").
        filter_calls = mock_qs.filter.call_args_list
        spi_filtered = any(
            call.kwargs.get("provider__spi_number__gt") == "" for call in filter_calls
        )
        assert (
            spi_filtered
        ), "expected .filter(provider__spi_number__gt='') on the queryset"

    @patch("surescripts_med_history.protocols.bulk_api.Appointment")
    def test_drops_providers_with_blank_spi_in_python_too(self, mock_appt_cls):
        """Belt-and-suspenders: even if the queryset filter somehow lets a
        provider through, the Python loop must drop them."""
        from datetime import datetime

        prov_blank = MagicMock(id="prov-blank")
        prov_blank.spi_number = ""
        prov_ok = MagicMock(id="prov-ok")
        prov_ok.spi_number = "9999999"

        appt_blank = MagicMock(
            patient=MagicMock(id="p1", first_name="A", last_name="One"),
            provider=prov_blank,
            start_time=datetime(2026, 4, 1, 10, 0),
        )
        appt_ok = MagicMock(
            patient=MagicMock(id="p2", first_name="B", last_name="Two"),
            provider=prov_ok,
            start_time=datetime(2026, 4, 2, 10, 0),
        )

        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.only.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.iterator.return_value = iter([appt_blank, appt_ok])

        from surescripts_med_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {
            "date_from": "2026-04-01",
            "date_to": "2026-04-07",
            "provider_ids": "",
        }
        results = handler.get_appointments()
        data = _parse_response(results[0])
        ids = [a["patient_id"] for a in data["appointments"]]
        assert "p1" not in ids
        assert "p2" in ids

    @patch("surescripts_med_history.protocols.bulk_api.Appointment")
    def test_deduplicates_by_patient(self, mock_appt_cls):
        patient = MagicMock()
        patient.id = "p1"
        patient.first_name = "Jane"
        patient.last_name = "Doe"
        provider = MagicMock()
        provider.id = "prov1"
        provider.first_name = "Dr"
        provider.last_name = "Smith"

        from datetime import datetime

        appt1 = MagicMock(patient=patient, provider=provider)
        appt1.start_time = datetime(2026, 4, 1, 10, 0)
        appt2 = MagicMock(patient=patient, provider=provider)
        appt2.start_time = datetime(2026, 4, 3, 14, 0)

        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.only.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.iterator.return_value = iter([appt1, appt2])

        from surescripts_med_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {
            "date_from": "2026-04-01",
            "date_to": "2026-04-07",
            "provider_ids": "",
        }
        results = handler.get_appointments()
        data = _parse_response(results[0])
        assert len(data["appointments"]) == 1


class TestSendEligibility:
    @patch("surescripts_med_history.protocols.bulk_api.Appointment")
    def test_requires_patient_ids(self, mock_appt):
        from surescripts_med_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"patient_ids": []}
        results = handler.send_eligibility()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("surescripts_med_history.protocols.bulk_api.request_metadata_effects")
    @patch(
        "surescripts_med_history.protocols.bulk_api.BulkRequestsApi._get_patient_provider_map"
    )
    def test_sends_effects(self, mock_map, mock_metadata):
        # Two metadata effects per call (status + at) when note_id is set
        mock_metadata.side_effect = lambda note_id, _t: (
            ["meta-status", "meta-at"] if note_id else []
        )
        mock_map.return_value = (
            {
                "p1": {"provider_id": "prov1", "note_id": NOTE_UUID_1},
                "p2": {"provider_id": "prov2", "note_id": ""},
            },
            0,
        )

        from surescripts_med_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_ids": ["p1", "p2"],
            "date_from": "2026-04-01",
            "date_to": "2026-04-07",
            "provider_ids": [],
        }
        results = handler.send_eligibility()
        data = _parse_response(results[0])
        assert data["status"] == "ok"
        assert data["count"] == 2
        assert data["skipped_no_spi"] == 0
        # 1 JSONResponse + 2 eligibility effects + 2 metadata effects (status,
        # at) for the patient with a note. p2 has no note so no metadata.
        assert len(results) == 1 + 2 + 2
        # metadata helper called once per patient with the right request_type
        assert mock_metadata.call_count == 2
        for call in mock_metadata.call_args_list:
            assert call.args[1] == "eligibility"

    @patch(
        "surescripts_med_history.protocols.bulk_api.BulkRequestsApi._get_patient_provider_map"
    )
    def test_reports_skipped_no_spi(self, mock_map):
        # p2 was filtered out upstream because their provider had no SPI
        mock_map.return_value = (
            {"p1": {"provider_id": "prov1", "note_id": ""}},
            1,
        )

        from surescripts_med_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_ids": ["p1", "p2"],
            "date_from": "2026-04-01",
            "date_to": "2026-04-07",
            "provider_ids": [],
        }
        results = handler.send_eligibility()
        data = _parse_response(results[0])
        assert data["count"] == 1
        assert data["skipped_no_spi"] == 1
        # 1 JSONResponse + 1 effect for the patient whose provider had SPI
        assert len(results) == 2


class TestSendMedHistory:
    @patch("surescripts_med_history.protocols.bulk_api.request_metadata_effects")
    @patch(
        "surescripts_med_history.protocols.bulk_api.BulkRequestsApi._get_patient_provider_map"
    )
    def test_sends_effects(self, mock_map, mock_metadata):
        mock_metadata.return_value = ["meta-status", "meta-at"]
        mock_map.return_value = (
            {"p1": {"provider_id": "prov1", "note_id": NOTE_UUID_1}},
            0,
        )

        from surescripts_med_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_ids": ["p1"],
            "date_from": "2026-04-01",
            "date_to": "2026-04-07",
            "provider_ids": [],
        }
        results = handler.send_med_history()
        data = _parse_response(results[0])
        assert data["status"] == "ok"
        assert data["count"] == 1
        assert data["skipped_no_spi"] == 0
        # 1 JSONResponse + 1 med history effect + 2 metadata effects
        assert len(results) == 1 + 1 + 2
        mock_metadata.assert_called_once_with(NOTE_UUID_1, "med_history")

    @patch(
        "surescripts_med_history.protocols.bulk_api.BulkRequestsApi._get_patient_provider_map"
    )
    def test_reports_skipped_no_spi(self, mock_map):
        mock_map.return_value = ({}, 2)

        from surescripts_med_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_ids": ["p1", "p2"],
            "date_from": "2026-04-01",
            "date_to": "2026-04-07",
            "provider_ids": [],
        }
        results = handler.send_med_history()
        data = _parse_response(results[0])
        assert data["count"] == 0
        assert data["skipped_no_spi"] == 2


class TestPatientProviderMap:
    @patch("surescripts_med_history.protocols.bulk_api.Appointment")
    def test_excludes_providers_without_spi(self, mock_appt_cls):
        from datetime import datetime

        from surescripts_med_history.protocols.bulk_api import BulkRequestsApi

        prov_with_spi = MagicMock(id="prov-spi")
        prov_with_spi.spi_number = "1234567"
        prov_no_spi = MagicMock(id="prov-no-spi")
        prov_no_spi.spi_number = ""

        note = MagicMock(id="note-1")

        appt_ok = MagicMock(
            patient=MagicMock(id="p1"),
            provider=prov_with_spi,
            note=note,
            start_time=datetime(2026, 4, 1),
        )
        appt_skip = MagicMock(
            patient=MagicMock(id="p2"),
            provider=prov_no_spi,
            note=None,
            start_time=datetime(2026, 4, 2),
        )

        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.only.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.iterator.return_value = iter([appt_ok, appt_skip])

        result, skipped = BulkRequestsApi._get_patient_provider_map(
            ["p1", "p2"], "2026-04-01", "2026-04-07", []
        )

        assert result == {"p1": {"provider_id": "prov-spi", "note_id": "note-1"}}
        assert skipped == 1
