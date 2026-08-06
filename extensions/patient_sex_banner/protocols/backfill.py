from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.patient import Patient

from logger import log
from patient_sex_banner.banner import BINARY_SEXES, add_banner_effect

from canvas_sdk.caching.plugins import get_cache

# Highest patient dbid reconciled so far, or CURSOR_DONE once the whole panel is
# swept. Cursor-based (dbid > N) rather than offset-based so patients added or
# removed between runs never shift the window.
CURSOR_KEY = "sex-banner:backfill_cursor"
CURSOR_DONE = "done"

# Patients reconciled per run. Bounds both the query and the number of effects
# returned per invocation, so a backfill never becomes an all-at-once scan.
PAGE_SIZE = 500


class BackfillBanners(CronTask):
    """One-time paged backfill of the sex banner across existing patients.

    The event handler keeps new and edited patients current, but it cannot
    retro-fit patients that already existed when the plugin was installed. This
    task sweeps the active panel once in bounded pages — adding the banner to
    anyone whose sex at birth is not Male or Female — then goes dormant. Each
    subsequent tick is a single cache read that returns immediately.
    """

    # Every 5 minutes. At PAGE_SIZE=500 an active sweep covers, e.g., a
    # 30k-patient panel in a few hours; while dormant each tick is a no-op.
    SCHEDULE = "*/5 * * * *"

    def execute(self) -> list[Effect]:
        cache = get_cache()
        cursor = cache.get(CURSOR_KEY, 0)

        if cursor == CURSOR_DONE:
            # Dormant: the whole panel is reconciled. Refresh the marker so the
            # cache TTL does not lapse and trigger a spurious full re-sweep.
            cache.set(CURSOR_KEY, CURSOR_DONE)
            return []

        patients = list(
            Patient.objects.filter(active=True, dbid__gt=cursor)
            .exclude(sex_at_birth__in=list(BINARY_SEXES))
            .order_by("dbid")[:PAGE_SIZE]
        )

        if not patients:
            cache.set(CURSOR_KEY, CURSOR_DONE)
            return []

        effects = [add_banner_effect(patient) for patient in patients]

        if len(patients) < PAGE_SIZE:
            cache.set(CURSOR_KEY, CURSOR_DONE)
        else:
            cache.set(CURSOR_KEY, patients[-1].dbid)

        log.info(
            f"[patient_sex_banner] Backfill reconciled {len(effects)} patients "
            f"(through dbid {patients[-1].dbid})"
        )
        return effects
