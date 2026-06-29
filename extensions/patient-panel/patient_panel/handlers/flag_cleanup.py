import arrow
from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_metadata import PatientMetadata as PatientMetadataEffect
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.patient import PatientMetadata as PatientMetadataRecord


class WeeklyFlagCleanup(CronTask):
    """Weekly cleanup of stale daily_flag metadata records."""

    SCHEDULE = "0 8 * * 1"  # Every Monday at 8:00 AM UTC

    def execute(self) -> list[Effect]:
        today_str = arrow.now().format("YYYY-MM-DD")
        # `PatientMetadataRecord.patient_id` is the integer dbid FK; the
        # effect API wants the UUID, so traverse via `patient__id`. The JOIN
        # only selects the UUID column instead of materialising full Patient
        # models. `.iterator(chunk_size=100)` bounds memory if the stale-flag
        # set grows over time.
        stale_patient_uuids = (
            PatientMetadataRecord.objects.filter(key="daily_flag")
            .exclude(value__startswith=today_str)
            .exclude(value="")
            .values_list("patient__id", flat=True)
            .iterator(chunk_size=100)
        )

        effects: list[Effect] = []
        for patient_uuid in stale_patient_uuids:
            metadata = PatientMetadataEffect(
                patient_id=str(patient_uuid),
                key="daily_flag",
            )
            effects.append(metadata.upsert(""))
        return effects
