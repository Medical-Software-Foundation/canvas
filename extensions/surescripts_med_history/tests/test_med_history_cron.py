from datetime import date
from unittest.mock import MagicMock, patch

import arrow


class TestMedHistoryCronTaskNoAppointments:
    @patch("surescripts_med_history.protocols.med_history_cron.arrow")
    @patch("surescripts_med_history.protocols.med_history_cron.Appointment")
    def test_returns_empty_when_no_appointments(self, mock_appt_cls, mock_arrow):
        mock_arrow.now.return_value = arrow.get("2026-03-30")
        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.only.return_value = mock_qs
        mock_qs.iterator.return_value = iter([])

        from surescripts_med_history.protocols.med_history_cron import (
            MedHistoryCronTask,
        )

        handler = MedHistoryCronTask(event=MagicMock())
        effects = handler.execute()
        assert effects == []


class TestMedHistoryCronTaskDualDateRange:
    @patch("surescripts_med_history.protocols.med_history_cron.arrow")
    @patch("surescripts_med_history.protocols.med_history_cron.Appointment")
    def test_queries_t7_and_t1(self, mock_appt_cls, mock_arrow):
        mock_arrow.now.return_value = arrow.get("2026-03-30")
        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.only.return_value = mock_qs
        mock_qs.iterator.return_value = iter([])

        from surescripts_med_history.protocols.med_history_cron import (
            MedHistoryCronTask,
        )

        handler = MedHistoryCronTask(event=MagicMock())
        handler.execute()

        call_kwargs = mock_appt_cls.objects.filter.call_args[1]
        assert date(2026, 4, 6) in call_kwargs["start_time__date__in"]
        assert date(2026, 3, 31) in call_kwargs["start_time__date__in"]

    @patch("surescripts_med_history.protocols.med_history_cron.arrow")
    @patch("surescripts_med_history.protocols.med_history_cron.Appointment")
    def test_honors_pre_appointment_days_secret(self, mock_appt_cls, mock_arrow):
        mock_arrow.now.return_value = arrow.get("2026-03-30")
        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.only.return_value = mock_qs
        mock_qs.iterator.return_value = iter([])

        from surescripts_med_history.protocols.med_history_cron import (
            MedHistoryCronTask,
        )

        handler = MedHistoryCronTask(
            event=MagicMock(), secrets={"pre_appointment_days": "0,3"}
        )
        handler.execute()

        call_kwargs = mock_appt_cls.objects.filter.call_args[1]
        assert date(2026, 3, 30) in call_kwargs["start_time__date__in"]
        assert date(2026, 4, 2) in call_kwargs["start_time__date__in"]
        assert date(2026, 4, 6) not in call_kwargs["start_time__date__in"]

    @patch("surescripts_med_history.protocols.med_history_cron.arrow")
    @patch("surescripts_med_history.protocols.med_history_cron.Appointment")
    def test_schedule_is_11_utc(self, mock_appt_cls, mock_arrow):
        from surescripts_med_history.protocols.med_history_cron import (
            MedHistoryCronTask,
        )

        assert "0 11" in MedHistoryCronTask.SCHEDULE

    @patch("surescripts_med_history.protocols.med_history_cron.arrow")
    @patch("surescripts_med_history.protocols.med_history_cron.Appointment")
    def test_deduplicates_patients_across_dates(self, mock_appt_cls, mock_arrow):
        mock_arrow.now.return_value = arrow.get("2026-03-30")

        patient = MagicMock()
        patient.id = "patient-1"
        provider = MagicMock()
        provider.id = "provider-1"
        provider.spi_number = "1234567"

        appt1 = MagicMock(patient=patient, provider=provider, note=None)
        appt2 = MagicMock(patient=patient, provider=provider, note=None)

        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.only.return_value = mock_qs
        mock_qs.iterator.return_value = iter([appt1, appt2])

        from surescripts_med_history.protocols.med_history_cron import (
            MedHistoryCronTask,
        )

        handler = MedHistoryCronTask(event=MagicMock())
        effects = handler.execute()
        assert len(effects) == 1

    @patch("surescripts_med_history.protocols.med_history_cron.arrow")
    @patch("surescripts_med_history.protocols.med_history_cron.Appointment")
    def test_skips_appointments_without_patient_or_provider(
        self, mock_appt_cls, mock_arrow
    ):
        mock_arrow.now.return_value = arrow.get("2026-03-30")

        appt_no_patient = MagicMock(patient=None, provider=MagicMock())
        appt_no_provider = MagicMock(patient=MagicMock(), provider=None)

        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.only.return_value = mock_qs
        mock_qs.iterator.return_value = iter([appt_no_patient, appt_no_provider])

        from surescripts_med_history.protocols.med_history_cron import (
            MedHistoryCronTask,
        )

        handler = MedHistoryCronTask(event=MagicMock())
        effects = handler.execute()
        assert effects == []

    @patch("surescripts_med_history.protocols.med_history_cron.arrow")
    @patch("surescripts_med_history.protocols.med_history_cron.Appointment")
    def test_skips_providers_without_spi(self, mock_appt_cls, mock_arrow):
        mock_arrow.now.return_value = arrow.get("2026-03-30")

        prov_with_spi = MagicMock(id="prov-spi")
        prov_with_spi.spi_number = "1234567"
        prov_no_spi = MagicMock(id="prov-no-spi")
        prov_no_spi.spi_number = ""

        appt_ok = MagicMock(
            patient=MagicMock(id="p1"), provider=prov_with_spi, note=None
        )
        appt_skip = MagicMock(
            patient=MagicMock(id="p2"), provider=prov_no_spi, note=None
        )

        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.only.return_value = mock_qs
        mock_qs.iterator.return_value = iter([appt_ok, appt_skip])

        from surescripts_med_history.protocols.med_history_cron import (
            MedHistoryCronTask,
        )

        handler = MedHistoryCronTask(event=MagicMock())
        effects = handler.execute()
        assert len(effects) == 1
