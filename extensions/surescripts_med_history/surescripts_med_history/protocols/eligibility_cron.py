from canvas_sdk.effects import Effect
from canvas_sdk.effects.surescripts import SendSurescriptsEligibilityRequestEffect
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus

import arrow
from logger import log

from surescripts_med_history.protocols.cadence import SECRET_NAME, parse_days
from surescripts_med_history.protocols.note_metadata import request_metadata_effects


class EligibilityCronTask(CronTask):
    """Send Surescripts eligibility requests for patients with upcoming appointments.

    The pre-appointment lead times are configurable via the `pre_appointment_days`
    plugin secret (comma-separated non-negative day offsets, default "1,7" =
    T+1 and T+7). `0` is allowed and targets today's appointments.
    """

    SCHEDULE = "0 8 * * *"  # 12:00am PT / 8:00 UTC

    def execute(self) -> list[Effect]:
        now = arrow.now()
        days = parse_days(self.secrets.get(SECRET_NAME))
        target_dates = [now.shift(days=d).date() for d in days]
        log.info(
            "EligibilityCronTask running for appointment dates %s (offsets %s)"
            % (target_dates, days)
        )

        appointments = (
            Appointment.objects.filter(
                start_time__date__in=target_dates,
            )
            .exclude(
                status__in=[
                    AppointmentProgressStatus.CANCELLED,
                    AppointmentProgressStatus.NOSHOWED,
                ]
            )
            .select_related("patient", "provider", "note")
            # Only the fields used below — one target date can cover every
            # appointment in the org, and the offsets are configurable.
            .only(
                "patient__id",
                "provider__id",
                "provider__spi_number",
                "note__id",
            )
        )

        effects = []
        seen_patient_ids: set[str] = set()
        warned_providers: set[str] = set()
        skipped_no_spi = 0

        # Streamed so a large appointment day doesn't sit in memory at once.
        for appt in appointments.iterator(chunk_size=200):
            if appt.patient is None or appt.provider is None:
                continue
            provider_id = str(appt.provider.id)
            if not appt.provider.spi_number:
                if provider_id not in warned_providers:
                    warned_providers.add(provider_id)
                    log.warning(
                        "Skipping Surescripts eligibility: provider %s has no SPI number"
                        % provider_id
                    )
                skipped_no_spi = skipped_no_spi + 1
                continue
            patient_id = str(appt.patient.id)
            if patient_id in seen_patient_ids:
                continue
            seen_patient_ids.add(patient_id)
            log.info("Sending eligibility request for patient %s" % patient_id)
            effects.append(
                SendSurescriptsEligibilityRequestEffect(
                    patient_id=patient_id,
                    staff_id=provider_id,
                ).apply()
            )
            note_id = str(appt.note.id) if appt.note is not None else ""
            effects.extend(request_metadata_effects(note_id, "eligibility"))

        if skipped_no_spi:
            log.info(
                "EligibilityCronTask skipped %s appointments across %s provider(s) lacking SPI"
                % (skipped_no_spi, len(warned_providers))
            )

        return effects
