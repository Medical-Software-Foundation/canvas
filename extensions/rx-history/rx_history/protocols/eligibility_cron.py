from canvas_sdk.effects import Effect
from canvas_sdk.effects.surescripts import SendSurescriptsEligibilityRequestEffect
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus

import arrow
from logger import log


class EligibilityCronTask(CronTask):
    """Send Surescripts eligibility requests for patients with appointments 6 days from now."""

    SCHEDULE = "0 8 * * *"  # 12:00am PT / 8:00 UTC

    def execute(self) -> list[Effect]:
        now = arrow.now()
        target_far = now.shift(days=7).date()
        target_near = now.shift(days=1).date()

        log.info(
            "EligibilityCronTask probe. utc_now=%s local_now=%s target_near=%s target_far=%s"
            % (arrow.utcnow().isoformat(), now.isoformat(), target_near, target_far)
        )

        appointments = (
            Appointment.objects.filter(
                start_time__date__in=[target_far, target_near],
            )
            .exclude(
                status__in=[
                    AppointmentProgressStatus.CANCELLED,
                    AppointmentProgressStatus.NOSHOWED,
                ]
            )
            .select_related("patient", "provider")
        )

        effects = []
        seen_patient_ids: set[str] = set()

        try:
            for appt in appointments:
                if appt.patient is None or appt.provider is None:
                    continue
                patient_id = str(appt.patient.id)
                if patient_id in seen_patient_ids:
                    continue
                seen_patient_ids.add(patient_id)
                log.info("Sending eligibility request for patient %s" % patient_id)
                effects.append(
                    SendSurescriptsEligibilityRequestEffect(
                        patient_id=patient_id,
                        staff_id=str(appt.provider.id),
                    ).apply()
                )
        except Exception as e:
            log.error(
                "EligibilityCronTask failed mid iteration. partial_effects=%s error=%s"
                % (len(effects), e)
            )

        log.info(
            "EligibilityCronTask outcome. effects=%s unique_patients=%s"
            % (len(effects), len(seen_patient_ids))
        )
        return effects
