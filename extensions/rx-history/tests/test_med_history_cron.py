from datetime import date
from unittest.mock import MagicMock, patch

import arrow


class TestMedHistoryCronTaskNoAppointments:
    @patch("rx_history.protocols.med_history_cron.arrow")
    @patch("rx_history.protocols.med_history_cron.Appointment")
    def test_returns_empty_when_no_appointments(self, mock_appt_cls, mock_arrow):
        mock_arrow.now.return_value = arrow.get("2026-03-30")
        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = iter([])

        from rx_history.protocols.med_history_cron import (
            MedHistoryCronTask,
        )

        handler = MedHistoryCronTask(event=MagicMock())
        effects = handler.execute()
        assert effects == []


class TestMedHistoryCronTaskDualDateRange:
    @patch("rx_history.protocols.med_history_cron.arrow")
    @patch("rx_history.protocols.med_history_cron.Appointment")
    def test_queries_t7_and_t1(self, mock_appt_cls, mock_arrow):
        mock_arrow.now.return_value = arrow.get("2026-03-30")
        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = iter([])

        from rx_history.protocols.med_history_cron import (
            MedHistoryCronTask,
        )

        handler = MedHistoryCronTask(event=MagicMock())
        handler.execute()

        call_kwargs = mock_appt_cls.objects.filter.call_args[1]
        assert date(2026, 4, 6) in call_kwargs["start_time__date__in"]
        assert date(2026, 3, 31) in call_kwargs["start_time__date__in"]

    @patch("rx_history.protocols.med_history_cron.arrow")
    @patch("rx_history.protocols.med_history_cron.Appointment")
    def test_schedule_is_11_utc(self, mock_appt_cls, mock_arrow):
        from rx_history.protocols.med_history_cron import (
            MedHistoryCronTask,
        )

        assert "0 11" in MedHistoryCronTask.SCHEDULE

    @patch("rx_history.protocols.med_history_cron.arrow")
    @patch("rx_history.protocols.med_history_cron.Appointment")
    def test_deduplicates_patients_across_dates(self, mock_appt_cls, mock_arrow):
        mock_arrow.now.return_value = arrow.get("2026-03-30")

        patient = MagicMock()
        patient.id = "patient-1"
        provider = MagicMock()
        provider.id = "provider-1"

        appt1 = MagicMock(patient=patient, provider=provider)
        appt2 = MagicMock(patient=patient, provider=provider)

        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = iter([appt1, appt2])

        from rx_history.protocols.med_history_cron import (
            MedHistoryCronTask,
        )

        handler = MedHistoryCronTask(event=MagicMock())
        effects = handler.execute()
        assert len(effects) == 1

    @patch("rx_history.protocols.med_history_cron.arrow")
    @patch("rx_history.protocols.med_history_cron.Appointment")
    def test_skips_appointments_without_patient_or_provider(
        self, mock_appt_cls, mock_arrow
    ):
        mock_arrow.now.return_value = arrow.get("2026-03-30")

        appt_no_patient = MagicMock(patient=None, provider=MagicMock())
        appt_no_provider = MagicMock(patient=MagicMock(), provider=None)

        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = iter([appt_no_patient, appt_no_provider])

        from rx_history.protocols.med_history_cron import (
            MedHistoryCronTask,
        )

        handler = MedHistoryCronTask(event=MagicMock())
        effects = handler.execute()
        assert effects == []


class TestMedHistoryCronTaskObservability:
    @patch("rx_history.protocols.med_history_cron.log")
    @patch(
        "rx_history.protocols.med_history_cron.SendSurescriptsMedicationHistoryRequestEffect"
    )
    @patch("rx_history.protocols.med_history_cron.arrow")
    @patch("rx_history.protocols.med_history_cron.Appointment")
    def test_logs_outcome_with_one_appointment(
        self, mock_appt_cls, mock_arrow, mock_effect_cls, mock_log
    ):
        mock_arrow.now.return_value = arrow.get("2026-03-30")
        mock_arrow.utcnow.return_value = arrow.get("2026-03-30")

        patient = MagicMock(id="p1")
        provider = MagicMock(id="prov-1")
        appt = MagicMock(patient=patient, provider=provider)

        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = iter([appt])

        effect_instance = MagicMock()
        effect_instance.apply.return_value = "med-history-effect-1"
        mock_effect_cls.return_value = effect_instance

        from rx_history.protocols.med_history_cron import (
            MedHistoryCronTask,
        )

        handler = MedHistoryCronTask(event=MagicMock())
        effects = handler.execute()

        assert effects == ["med-history-effect-1"]
        info_messages = [call.args[0] for call in mock_log.info.call_args_list]
        assert any("MedHistoryCronTask probe." in m for m in info_messages)
        assert any(
            "MedHistoryCronTask outcome. effects=1 unique_patients=1" in m
            for m in info_messages
        )
