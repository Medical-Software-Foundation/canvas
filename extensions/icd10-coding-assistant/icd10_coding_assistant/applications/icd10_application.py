"""Patient-specific Application for the ICD-10 Coding Assistant.

Appears as a tab icon on the patient chart. The notification badge shows how many
active conditions are missing an ICD-10 code so clinicians see the signal at a
glance without opening the app.
"""

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from logger import log

from icd10_coding_assistant.utils import get_conditions_missing_icd10

# Short TTL: badge should be roughly current without hammering the DB on every
# chart navigation.  60 s is cheap and still feels responsive.
_BADGE_CACHE_TTL_SECONDS = 60


class ICD10CodingApplication(Application):
    """Patient-specific Application: ICD-10 Coding Assistant.

    Opens a centered modal served by ICD10FrontendAPI. The notification badge
    reflects the number of active conditions still missing an ICD-10 code for the
    currently viewed patient.
    """

    def on_open(self) -> Effect:
        """Launch the ICD-10 coding UI in a centered modal.

        Uses DEFAULT_MODAL rather than the right chart pane so the multi-column
        approval table has room and is not clipped.
        """
        patient_id: str = self.event.context["patient"]["id"]
        log.info(
            f"[ICD-10 Coding] Opening ICD-10 coding assistant for patient {patient_id}"
        )
        return LaunchModalEffect(
            url=f"/plugin-io/api/icd10_coding_assistant/ui/icd10-coding?patient_id={patient_id}",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()

    def compute_notification_badge(self) -> int | None:
        """Return the count of conditions missing ICD-10 for the badge icon.

        Returns None (no badge) when all conditions are coded. Cached briefly
        to avoid a DB hit on every chart navigation.
        """
        patient_id: str | None = self.event.context.get("patient", {}).get("id")
        if not patient_id:
            return None

        cache = get_cache()
        cache_key = f"icd10_badge_{patient_id}"

        def _count() -> int:
            return len(get_conditions_missing_icd10(patient_id))

        count: int = cache.get_or_set(
            cache_key, _count, timeout_seconds=_BADGE_CACHE_TTL_SECONDS
        )
        return count if count > 0 else None
