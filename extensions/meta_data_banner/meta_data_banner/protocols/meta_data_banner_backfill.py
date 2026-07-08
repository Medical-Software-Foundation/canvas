from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.patient import Patient

from logger import log
from meta_data_banner.banner import banner_effect_for_patient

# dbid we last processed during the current sweep, or CURSOR_DONE when the
# panel is fully reconciled and the task is dormant. Cursor-based (dbid > N)
# rather than offset-based so patients added/removed between runs don't shift
# the window.
CURSOR_KEY = "meta_data_banner:backfill_cursor"
CURSOR_DONE = "done"

# The BANNER_TEMPLATE value the current/last sweep was based on. When the live
# secret differs from this, the template changed (or the plugin is freshly
# installed) and a new full sweep is started.
TEMPLATE_KEY = "meta_data_banner:backfill_template"

# Patients reconciled per run. Bounds both the query and the number of effects
# returned from a single invocation.
PAGE_SIZE = 500


class MetaDataBannerBackfill(CronTask):
    """One-time-per-change backfill of metadata banners across the panel.

    Real-time per-patient updates are handled by MetaDataBanner as metadata is
    written, so it keeps the panel current on its own. This task exists only to
    cover the two things the event path can't:

      1. Initial backfill of existing patients right after install.
      2. Re-rendering everyone if BANNER_TEMPLATE ever changes (which a bare
         secret edit does NOT signal via PLUGIN_UPDATED, so a cron is the only
         reliable trigger).

    It sweeps the active-patient panel once in bounded pages, then goes
    **dormant** — each subsequent tick is a single cache read that returns
    immediately without querying patients. It only wakes again if the template
    changes. This avoids both the all-at-once scan of a plugin-lifecycle batch
    and the round-the-clock churn of an always-on sweep.
    """

    # Every 5 minutes. During an active sweep at PAGE_SIZE=500 this covers, for
    # example, a 30k-patient panel in ~5 hours; while dormant each tick is a
    # no-op cache check.
    SCHEDULE = "*/5 * * * *"

    def execute(self) -> list[Effect]:
        template = self.secrets.get("BANNER_TEMPLATE", "")
        if not template:
            return []

        cache = get_cache()

        if cache.get(TEMPLATE_KEY) != template:
            # First run, or the template changed: (re)start a full sweep from
            # the beginning. Persist both keys now so a crash mid-run resumes
            # the sweep rather than falling through to the dormant branch.
            cache.set(TEMPLATE_KEY, template)
            cache.set(CURSOR_KEY, 0)
            cursor = 0
        else:
            cursor = cache.get(CURSOR_KEY, CURSOR_DONE)
            if cursor == CURSOR_DONE:
                # Dormant: the whole panel is reconciled for this template.
                # Refresh the template key so the dormant state doesn't expire
                # (14-day cache TTL) and trigger a spurious full re-sweep.
                cache.set(TEMPLATE_KEY, template)
                return []

        patients = list(
            Patient.objects.filter(active=True, dbid__gt=cursor)
            .order_by("dbid")
            .prefetch_related("metadata")[:PAGE_SIZE]
        )

        if not patients:
            cache.set(CURSOR_KEY, CURSOR_DONE)
            return []

        effects = [banner_effect_for_patient(patient, template) for patient in patients]

        if len(patients) < PAGE_SIZE:
            # Final (partial) page — sweep complete, go dormant.
            cache.set(CURSOR_KEY, CURSOR_DONE)
            next_cursor = CURSOR_DONE
        else:
            next_cursor = patients[-1].dbid
            cache.set(CURSOR_KEY, next_cursor)

        log.info(
            f"[meta_data_banner] Backfill: reconciled {len(effects)} patients "
            f"(from dbid {cursor}, next {next_cursor})"
        )
        return effects
