from datetime import date
from unittest.mock import MagicMock, patch

import arrow


class TestEligibilityCronTaskNoAppointments:
    @patch("rx_history.protocols.eligibility_cron.arrow")
    @patch("rx_history.protocols.eligibility_cron.Appointment")
    def test_returns_empty_when_no_appointments(self, mock_appt_cls, mock_arrow):
        mock_arrow.now.return_value = arrow.get("2026-03-30")
        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = iter([])

        from rx_history.protocols.eligibility_cron import (
            EligibilityCronTask,
        )

        handler = EligibilityCronTask(event=MagicMock())
        effects = handler.execute()
        assert effects == []


class TestEligibilityCronTaskDualDateRange:
    @patch("rx_history.protocols.eligibility_cron.arrow")
    @patch("rx_history.protocols.eligibility_cron.Appointment")
    def test_queries_t7_and_t1(self, mock_appt_cls, mock_arrow):
        mock_arrow.now.return_value = arrow.get("2026-03-30")
        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = iter([])

        from rx_history.protocols.eligibility_cron import (
            EligibilityCronTask,
        )

        handler = EligibilityCronTask(event=MagicMock())
        handler.execute()

        call_kwargs = mock_appt_cls.objects.filter.call_args[1]
        assert date(2026, 4, 6) in call_kwargs["start_time__date__in"]
        assert date(2026, 3, 31) in call_kwargs["start_time__date__in"]

    @patch("rx_history.protocols.eligibility_cron.arrow")
    @patch("rx_history.protocols.eligibility_cron.Appointment")
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

        from rx_history.protocols.eligibility_cron import (
            EligibilityCronTask,
        )

        handler = EligibilityCronTask(event=MagicMock())
        effects = handler.execute()
        assert len(effects) == 1

    @patch("rx_history.protocols.eligibility_cron.arrow")
    @patch("rx_history.protocols.eligibility_cron.Appointment")
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

        from rx_history.protocols.eligibility_cron import (
            EligibilityCronTask,
        )

        handler = EligibilityCronTask(event=MagicMock())
        effects = handler.execute()
        assert effects == []

    @patch("rx_history.protocols.eligibility_cron.arrow")
    @patch("rx_history.protocols.eligibility_cron.Appointment")
    def test_multiple_patients_get_separate_effects(self, mock_appt_cls, mock_arrow):
        mock_arrow.now.return_value = arrow.get("2026-03-30")

        p1, p2 = MagicMock(id="p1"), MagicMock(id="p2")
        prov = MagicMock(id="prov-1")
        appt1 = MagicMock(patient=p1, provider=prov)
        appt2 = MagicMock(patient=p2, provider=prov)

        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = iter([appt1, appt2])

        from rx_history.protocols.eligibility_cron import (
            EligibilityCronTask,
        )

        handler = EligibilityCronTask(event=MagicMock())
        effects = handler.execute()
        assert len(effects) == 2


class TestEligibilityCronTaskObservability:
    @patch("rx_history.protocols.eligibility_cron.log")
    @patch("rx_history.protocols.eligibility_cron.arrow")
    @patch("rx_history.protocols.eligibility_cron.Appointment")
    def test_logs_outcome_with_zero_appointments(
        self, mock_appt_cls, mock_arrow, mock_log
    ):
        mock_arrow.now.return_value = arrow.get("2026-03-30")
        mock_arrow.utcnow.return_value = arrow.get("2026-03-30")
        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = iter([])

        from rx_history.protocols.eligibility_cron import (
            EligibilityCronTask,
        )

        handler = EligibilityCronTask(event=MagicMock())
        effects = handler.execute()

        assert effects == []
        info_messages = [call.args[0] for call in mock_log.info.call_args_list]
        assert any("EligibilityCronTask probe." in m for m in info_messages)
        assert any(
            "EligibilityCronTask outcome. effects=0 unique_patients=0" in m
            for m in info_messages
        )

    @patch("rx_history.protocols.eligibility_cron.log")
    @patch(
        "rx_history.protocols.eligibility_cron.SendSurescriptsEligibilityRequestEffect"
    )
    @patch("rx_history.protocols.eligibility_cron.arrow")
    @patch("rx_history.protocols.eligibility_cron.Appointment")
    def test_emits_partial_on_mid_iteration_failure(
        self, mock_appt_cls, mock_arrow, mock_effect_cls, mock_log
    ):
        mock_arrow.now.return_value = arrow.get("2026-03-30")
        mock_arrow.utcnow.return_value = arrow.get("2026-03-30")

        p1, p2, p3 = MagicMock(id="p1"), MagicMock(id="p2"), MagicMock(id="p3")
        prov = MagicMock(id="prov-1")
        appts = [
            MagicMock(patient=p1, provider=prov),
            MagicMock(patient=p2, provider=prov),
            MagicMock(patient=p3, provider=prov),
        ]

        mock_qs = MagicMock()
        mock_appt_cls.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.select_related.return_value = iter(appts)

        first_effect = MagicMock()
        first_effect.apply.return_value = "eligibility-effect-1"
        mock_effect_cls.side_effect = [first_effect, RuntimeError("boom"), MagicMock()]

        from rx_history.protocols.eligibility_cron import (
            EligibilityCronTask,
        )

        handler = EligibilityCronTask(event=MagicMock())
        effects = handler.execute()

        assert effects == ["eligibility-effect-1"]
        error_messages = [call.args[0] for call in mock_log.error.call_args_list]
        assert any(
            "EligibilityCronTask failed mid iteration. partial_effects=1" in m
            for m in error_messages
        )
        info_messages = [call.args[0] for call in mock_log.info.call_args_list]
        assert any(
            "EligibilityCronTask outcome. effects=1 unique_patients=2" in m
            for m in info_messages
        )
