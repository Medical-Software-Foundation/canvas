import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch


def _parse_response(resp):
    """Parse a JSONResponse's content bytes into a dict."""
    return json.loads(resp.content.decode("utf-8"))


class TestGetAppointments:
    @patch("rx_history.protocols.bulk_api.Appointment")
    def test_requires_date_params(self, mock_appt):
        from rx_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {"date_from": "", "date_to": ""}
        results = handler.get_appointments()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("rx_history.protocols.bulk_api.Appointment")
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
        mock_qs.filter.return_value = mock_qs
        mock_qs.order_by.return_value = [appt]

        from rx_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {
            "date_from": "2026-04-01",
            "date_to": "2026-04-07",
            "provider_id": "",
        }
        results = handler.get_appointments()
        data = _parse_response(results[0])
        assert len(data["appointments"]) == 1
        assert data["appointments"][0]["patient_name"] == "Jane Doe"

    @patch("rx_history.protocols.bulk_api.Appointment")
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
        mock_qs.filter.return_value = mock_qs
        mock_qs.order_by.return_value = [appt1, appt2]

        from rx_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {
            "date_from": "2026-04-01",
            "date_to": "2026-04-07",
            "provider_id": "",
        }
        results = handler.get_appointments()
        data = _parse_response(results[0])
        assert len(data["appointments"]) == 1


class TestSendEligibility:
    @patch("rx_history.protocols.bulk_api.Appointment")
    def test_requires_patient_ids(self, mock_appt):
        from rx_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"patient_ids": []}
        results = handler.send_eligibility()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("rx_history.protocols.bulk_api.partition_by_care_event")
    @patch(
        "rx_history.protocols.bulk_api.BulkRequestsApi._get_patient_provider_map"
    )
    def test_sends_effects(self, mock_map, mock_partition):
        mock_partition.return_value = (["p1", "p2"], [])
        mock_map.return_value = {"p1": "prov1", "p2": "prov2"}

        from rx_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_ids": ["p1", "p2"],
            "date_from": "2026-04-01",
            "date_to": "2026-04-07",
            "provider_id": "",
        }
        results = handler.send_eligibility()
        data = _parse_response(results[0])
        assert data["status"] == "ok"
        assert data["sent"] == 2
        assert data["skipped"] == []
        assert len(results) == 3  # 1 JSONResponse + 2 effects


class TestPage:
    @patch("rx_history.protocols.bulk_api.render_to_string")
    @patch("rx_history.protocols.bulk_api.Staff")
    def test_filters_providers_by_prescriber_role(
        self, mock_staff_cls, mock_render
    ):
        """Only prescriber roles (Physician, NP, PA) are passed to the template; others are dropped."""
        physician = MagicMock(
            id="s1", first_name="Alice", last_name="Nguyen"
        )
        physician.top_clinical_role = MagicMock(name="role")
        physician.top_clinical_role.name = "Physician"

        nurse = MagicMock(id="s2", first_name="Bob", last_name="Lee")
        nurse.top_clinical_role = MagicMock()
        nurse.top_clinical_role.name = "Registered Nurse"

        no_role = MagicMock(id="s3", first_name="Jan", last_name="Smith")
        no_role.top_clinical_role = None

        blank_name = MagicMock(
            id="s4", first_name="", last_name=""
        )
        blank_name.top_clinical_role = MagicMock()
        blank_name.top_clinical_role.name = "Physician Assistant"

        mock_staff_cls.objects.all.return_value.prefetch_related.return_value = [
            physician,
            nurse,
            no_role,
            blank_name,
        ]
        mock_render.return_value = "<html>page</html>"

        from rx_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        results = handler.page()

        assert len(results) == 1
        call_kwargs = mock_render.call_args
        template_name = call_kwargs.args[0]
        context = call_kwargs.args[1]
        assert template_name == "templates/bulk_requests.html"
        providers = json.loads(context["providers_json"])
        assert providers == [{"id": "s1", "name": "Alice Nguyen"}]

    @patch("rx_history.protocols.bulk_api.render_to_string")
    @patch("rx_history.protocols.bulk_api.Staff")
    def test_tolerates_staff_query_error(self, mock_staff_cls, mock_render):
        """A Staff.objects.all() blow up should not crash the page; an empty provider list is sent."""
        mock_staff_cls.objects.all.side_effect = RuntimeError("db down")
        mock_render.return_value = "<html>page</html>"

        from rx_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        results = handler.page()

        assert len(results) == 1
        context = mock_render.call_args.args[1]
        assert json.loads(context["providers_json"]) == []


class TestGetAppointmentsExtras:
    @patch("rx_history.protocols.bulk_api.Appointment")
    def test_skips_appointments_missing_patient_or_provider(self, mock_appt_cls):
        """Appointments with no patient or no provider are skipped."""
        from datetime import datetime

        good_patient = MagicMock(id="p1", first_name="Jane", last_name="Doe")
        good_provider = MagicMock(
            id="prov1", first_name="Dr", last_name="Smith"
        )

        good = MagicMock(patient=good_patient, provider=good_provider)
        good.start_time = datetime(2026, 4, 1, 10, 0)

        no_patient = MagicMock(patient=None, provider=good_provider)
        no_patient.start_time = datetime(2026, 4, 1, 11, 0)

        no_provider = MagicMock(patient=good_patient, provider=None)
        no_provider.start_time = datetime(2026, 4, 1, 12, 0)

        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.order_by.return_value = [no_patient, no_provider, good]

        from rx_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.query_params = {
            "date_from": "2026-04-01",
            "date_to": "2026-04-07",
            "provider_id": "prov1",
        }
        results = handler.get_appointments()
        data = _parse_response(results[0])
        assert len(data["appointments"]) == 1
        assert data["appointments"][0]["patient_id"] == "p1"


class TestSendEligibilityNoProvider:
    @patch("rx_history.protocols.bulk_api.partition_by_care_event")
    @patch(
        "rx_history.protocols.bulk_api.BulkRequestsApi._get_patient_provider_map"
    )
    def test_skips_patients_without_mapped_provider(
        self, mock_map, mock_partition
    ):
        """Patients allowed by care event but without a mapped provider land in skipped with reason no_provider."""
        mock_partition.return_value = (["p1", "p2"], [])
        mock_map.return_value = {"p1": "prov1"}  # p2 has no mapped provider

        from rx_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_ids": ["p1", "p2"],
            "date_from": "",
            "date_to": "",
            "provider_id": "",
        }
        results = handler.send_eligibility()
        data = _parse_response(results[0])

        assert data["sent"] == 1
        assert {"patient_id": "p2", "reason": "no_provider"} in data["skipped"]


class TestSendMedHistoryExtras:
    def test_requires_patient_ids(self):
        from rx_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"patient_ids": []}
        results = handler.send_med_history()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("rx_history.protocols.bulk_api.partition_by_care_event")
    @patch(
        "rx_history.protocols.bulk_api.BulkRequestsApi._get_patient_provider_map"
    )
    def test_skips_patients_without_mapped_provider(
        self, mock_map, mock_partition
    ):
        mock_partition.return_value = (["p1", "p2"], [])
        mock_map.return_value = {"p1": "prov1"}

        from rx_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_ids": ["p1", "p2"],
            "date_from": "",
            "date_to": "",
            "provider_id": "",
        }
        results = handler.send_med_history()
        data = _parse_response(results[0])

        assert data["sent"] == 1
        assert {"patient_id": "p2", "reason": "no_provider"} in data["skipped"]


class TestGetPatientProviderMap:
    @patch("rx_history.protocols.bulk_api.Appointment")
    def test_builds_map_of_first_provider_per_patient(self, mock_appt_cls):
        """Map picks the earliest appointment's provider per patient, respecting filters."""
        from datetime import datetime

        p1 = MagicMock(id="p1")
        p2 = MagicMock(id="p2")
        prov_a = MagicMock(id="provA")
        prov_b = MagicMock(id="provB")

        appt1 = MagicMock(patient=p1, provider=prov_a)
        appt1.start_time = datetime(2026, 4, 1, 9, 0)
        appt2 = MagicMock(patient=p1, provider=prov_b)  # later duplicate
        appt2.start_time = datetime(2026, 4, 2, 9, 0)
        appt3 = MagicMock(patient=p2, provider=prov_b)
        appt3.start_time = datetime(2026, 4, 3, 9, 0)
        bad_a = MagicMock(patient=None, provider=prov_a)
        bad_a.start_time = datetime(2026, 4, 4, 9, 0)
        bad_b = MagicMock(patient=p1, provider=None)
        bad_b.start_time = datetime(2026, 4, 5, 9, 0)

        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.order_by.return_value = [appt1, appt2, appt3, bad_a, bad_b]

        from rx_history.protocols.bulk_api import BulkRequestsApi

        mapping = BulkRequestsApi._get_patient_provider_map(
            ["p1", "p2"], "2026-04-01", "2026-04-07", "provA"
        )
        assert mapping == {"p1": "provA", "p2": "provB"}

    @patch("rx_history.protocols.bulk_api.Appointment")
    def test_handles_empty_date_and_provider_filters(self, mock_appt_cls):
        """When date_from, date_to, or provider_id are blank, the extra filters are skipped."""
        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.order_by.return_value = []

        from rx_history.protocols.bulk_api import BulkRequestsApi

        mapping = BulkRequestsApi._get_patient_provider_map(
            ["p1"], "", "", ""
        )
        assert mapping == {}
        # filter is only called once in the initial queryset build
        assert mock_appt_cls.objects.filter.call_count == 1
        mock_qs.filter.assert_not_called()


class TestSendMedHistory:
    @patch("rx_history.protocols.bulk_api.partition_by_care_event")
    @patch(
        "rx_history.protocols.bulk_api.BulkRequestsApi._get_patient_provider_map"
    )
    def test_sends_effects(self, mock_map, mock_partition):
        mock_partition.return_value = (["p1"], [])
        mock_map.return_value = {"p1": "prov1"}

        from rx_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_ids": ["p1"],
            "date_from": "2026-04-01",
            "date_to": "2026-04-07",
            "provider_id": "",
        }
        results = handler.send_med_history()
        data = _parse_response(results[0])
        assert data["status"] == "ok"
        assert data["sent"] == 1
        assert data["skipped"] == []
        assert len(results) == 2


class TestBulkCareEventGuard:
    @patch("rx_history.protocols.bulk_api.partition_by_care_event")
    @patch(
        "rx_history.protocols.bulk_api.BulkRequestsApi._get_patient_provider_map"
    )
    def test_eligibility_partitions_by_care_event(
        self, mock_map, mock_partition
    ):
        mock_partition.return_value = (["p1"], ["p2"])
        mock_map.return_value = {"p1": "prov1"}

        from rx_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_ids": ["p1", "p2"],
            "date_from": "",
            "date_to": "",
            "provider_id": "",
        }
        results = handler.send_eligibility()
        data = _parse_response(results[0])

        assert data["status"] == "ok"
        assert data["sent"] == 1
        assert {"patient_id": "p2", "reason": "no_care_event"} in data["skipped"]
        assert len(results) == 2  # 1 JSONResponse + 1 effect for p1
        mock_map.assert_called_once_with(["p1"], "", "", "")

    @patch("rx_history.protocols.bulk_api.partition_by_care_event")
    @patch(
        "rx_history.protocols.bulk_api.BulkRequestsApi._get_patient_provider_map"
    )
    def test_med_history_partitions_by_care_event(
        self, mock_map, mock_partition
    ):
        mock_partition.return_value = (["p1"], ["p2", "p3"])
        mock_map.return_value = {"p1": "prov1"}

        from rx_history.protocols.bulk_api import BulkRequestsApi

        handler = BulkRequestsApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_ids": ["p1", "p2", "p3"],
            "date_from": "",
            "date_to": "",
            "provider_id": "",
        }
        results = handler.send_med_history()
        data = _parse_response(results[0])

        assert data["sent"] == 1
        assert len(data["skipped"]) == 2
        reasons = {item["reason"] for item in data["skipped"]}
        assert reasons == {"no_care_event"}

    def test_partition_boundary_inclusive_at_seven_days(self):
        """Window is inclusive. Day 7 qualifies, day 8 does not."""
        from datetime import date as real_date, timedelta
        from unittest.mock import patch as _patch

        with _patch(
            "rx_history.protocols._care_event.Appointment"
        ) as mock_appt_cls:
            today = real_date.today()
            mock_qs = MagicMock()
            mock_appt_cls.objects.filter.return_value = mock_qs
            mock_qs.exclude.return_value = mock_qs
            mock_qs.values_list.return_value = ["p_day7"]

            from rx_history.protocols._care_event import (
                partition_by_care_event,
            )

            allowed, blocked = partition_by_care_event(["p_day7", "p_day8"])
            assert allowed == ["p_day7"]
            assert blocked == ["p_day8"]

            call_kwargs = mock_appt_cls.objects.filter.call_args.kwargs
            assert call_kwargs["start_time__date__gte"] == today
            assert call_kwargs["start_time__date__lte"] == today + timedelta(days=7)
