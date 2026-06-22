import datetime
from typing import Iterable
from zoneinfo import ZoneInfo

from django.db.models import Max

from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.appointment import ScheduleEvent, Appointment
from canvas_sdk.v1.data import Appointment as AppointmentModel, AppointmentMetadata
from canvas_sdk.v1.data.facility import Facility
from canvas_sdk.v1.data.note import NoteTypeCategories
from logger import log

from facility_recurring_scheduler.utils.constants import (
    FIELD_FACILITY_KEY,
    FIELD_RECURRENCE_KEY,
    TARGET_HORIZON_DAYS,
    RecurrenceEnum,
)
from facility_recurring_scheduler.utils.recurrence import calculate_recurrence_date
from facility_recurring_scheduler.utils.timezone_helper import get_timezone_for_location

MAX_ITERATIONS = 365


class RecurrenceExtender(CronTask):
    """CronTask that runs daily to maintain a 3-month horizon of scheduled events.

    For each recurring event series (both appointments and schedule events),
    this task ensures there are always approximately 3 months (90 days) of
    future events scheduled. It calculates how many events are needed to
    reach the target horizon and creates them.

    Note: Description is NOT set on child events. The FacilityRename handler
    will update the description after each event is created.
    """

    SCHEDULE = "0 0 * * *"  # Daily at midnight

    def _get_active_recurring_parents(self) -> list[AppointmentModel]:
        """Find all parent recurring events (both appointments and schedule events).

        Uses select_related to prefetch note_type, location, and provider FKs
        to avoid N+1 queries when accessing these in the processing loop.
        """
        parent_ids_with_recurrence = AppointmentMetadata.objects.filter(
            key=FIELD_RECURRENCE_KEY
        ).exclude(
            value=RecurrenceEnum.NONE.value
        ).values_list("appointment_id", flat=True)

        return list(
            AppointmentModel.objects.filter(
                id__in=parent_ids_with_recurrence,
                parent_appointment_id__isnull=True,
            ).exclude(
                # Only a cancelled parent stops a series. A no-show is a real
                # occurrence (the patient simply didn't attend) and must not
                # affect recurring behavior.
                status__in=["cancelled"]
            ).select_related(
                "note_type", "location", "provider", "patient"
            )
        )

    def _create_child_schedule_event(
        self,
        parent: AppointmentModel,
        start_time: datetime.datetime,
    ) -> ScheduleEvent:
        """Create a child schedule event without description.

        FacilityRename will handle setting the description via .update().
        """
        patient_id = str(parent.patient.id) if parent.patient else None

        return ScheduleEvent(
            patient_id=patient_id,
            parent_appointment_id=str(parent.id),
            start_time=start_time,
            duration_minutes=parent.duration_minutes,
            practice_location_id=str(parent.location.id),
            provider_id=str(parent.provider.id),
            note_type_id=str(parent.note_type.id),
        )

    def _create_child_appointment(
        self,
        parent: AppointmentModel,
        start_time: datetime.datetime,
    ) -> Appointment:
        """Create a child appointment for regular recurring appointments."""
        patient_id = str(parent.patient.id) if parent.patient else None

        return Appointment(
            patient_id=patient_id,
            parent_appointment_id=str(parent.id),
            start_time=start_time,
            duration_minutes=parent.duration_minutes,
            provider_id=str(parent.provider.id),
            practice_location_id=str(parent.location.id),
            meeting_link=parent.meeting_link,
            appointment_note_type_id=str(parent.note_type.id),
        )

    @staticmethod
    def _months_between(
        anchor: datetime.datetime,
        later: datetime.datetime,
        local_tz: ZoneInfo,
    ) -> int:
        """Whole calendar months from `anchor` to `later`, in local time (>= 0)."""
        utc_tz = ZoneInfo("UTC")
        a = (anchor if anchor.tzinfo else anchor.replace(tzinfo=utc_tz)).astimezone(local_tz)
        b = (later if later.tzinfo else later.replace(tzinfo=utc_tz)).astimezone(local_tz)
        return max(0, (b.year - a.year) * 12 + (b.month - a.month))

    def _create_events_to_horizon(
        self,
        parent: AppointmentModel,
        last_date: datetime.datetime,
        target_date: datetime.datetime,
        recurrence: str,
        is_schedule_event: bool,
        local_tz: ZoneInfo | None = None,
    ) -> list[Effect]:
        """Create new occurrences after last_date up to and including target_date.

        Interval patterns (daily/weekly/every-N-weeks) are anchored on last_date,
        the latest existing child — translation-invariant, so this is exact and
        efficient. Monthly is anchored on the parent's original start_time instead
        so the ordinal-weekday pattern (e.g. "3rd Tuesday") stays stable and never
        drifts; we jump straight to the occurrence index near last_date via
        _months_between rather than iterating from the parent's start.

        ``local_tz`` may be supplied by batch callers that already resolved the
        timezone; when omitted it is resolved per-parent (one lookup).
        """
        effects: list[Effect] = []
        if local_tz is None:
            local_tz = get_timezone_for_location(parent)
        now = datetime.datetime.now(datetime.timezone.utc)

        if recurrence == RecurrenceEnum.MONTHLY.value:
            anchor = parent.start_time
            count = self._months_between(anchor, last_date, local_tz)
        else:
            anchor = last_date
            count = 0

        iterations = 0
        while iterations < MAX_ITERATIONS:
            iterations += 1
            count += 1
            try:
                occurrence = calculate_recurrence_date(anchor, count, recurrence, local_tz)
            except ValueError:
                log.warning(f"RecurrenceExtender: unknown recurrence type {recurrence!r} for parent {parent.id}")
                return effects

            if occurrence > target_date:
                break

            # Skip occurrences that already exist (<= last_date) or are in the past
            if occurrence <= last_date or occurrence < now:
                continue

            if is_schedule_event:
                child = self._create_child_schedule_event(parent, occurrence)
            else:
                child = self._create_child_appointment(parent, occurrence)

            effects.append(child.create())

        if iterations >= MAX_ITERATIONS:
            log.warning(f"Hit max iterations ({MAX_ITERATIONS}) for parent {parent.id}, breaking")

        return effects

    def _batch_get_recurrence_patterns(
        self, parent_ids: list[str]
    ) -> dict[str, str]:
        """Batch fetch recurrence patterns for multiple parents in a single query."""
        metadata = AppointmentMetadata.objects.filter(
            appointment_id__in=parent_ids,
            key=FIELD_RECURRENCE_KEY
        ).values_list("appointment_id", "value")

        return {str(appt_id): value for appt_id, value in metadata}

    def _batch_get_latest_children(
        self, parent_ids: list[str]
    ) -> dict[str, datetime.datetime]:
        """Batch fetch latest child start times for multiple parents in a single query."""
        # Use aggregation to get max start_time grouped by parent_appointment_id
        # Exclude only cancelled children. A no-show is still a real occurrence,
        # so it stays in the aggregation and continues to anchor the series.
        latest_children = AppointmentModel.objects.filter(
            parent_appointment_id__in=parent_ids
        ).exclude(
            status__in=["cancelled"]
        ).values("parent_appointment_id").annotate(
            latest_start=Max("start_time")
        )

        return {
            str(item["parent_appointment_id"]): item["latest_start"]
            for item in latest_children
        }

    def _batch_get_facility_names(self, parent_ids: list[str]) -> dict[str, str]:
        """Batch fetch the selected facility name for each parent (single query).

        A read failure here propagates rather than being swallowed: degrading to
        an empty map would silently resolve every facility series to the default
        timezone (and bake in wrong occurrence times), which is worse than the
        run failing loudly and retrying. Mirrors the other batch helpers, which
        also let DB errors surface.
        """
        return {
            str(appt_id): value
            for appt_id, value in AppointmentMetadata.objects.filter(
                appointment_id__in=parent_ids, key=FIELD_FACILITY_KEY
            ).values_list("appointment_id", "value")
            if value
        }

    def _batch_get_facility_states(
        self, facility_names: Iterable[str | None]
    ) -> dict[str, str | None]:
        """Batch fetch state codes for a set of facility names (single query).

        Like _batch_get_facility_names, a query failure propagates rather than
        silently degrading every facility series to the default timezone.
        """
        names = {name for name in facility_names if name}
        if not names:
            return {}
        return {
            name: state_code
            for name, state_code in Facility.objects.filter(
                name__in=names, active=True
            ).values_list("name", "state_code")
        }

    def execute(self) -> list[Effect]:
        """Main execution method called by the cron scheduler.

        Optimized to use batch queries instead of N+1 patterns:
        - Batch fetches all recurrence patterns in one query
        - Batch fetches all latest child times using aggregation
        - Uses select_related for FK access (note_type, location, provider)
        """
        effects = []
        now = datetime.datetime.now(datetime.timezone.utc)
        target_date = now + datetime.timedelta(days=TARGET_HORIZON_DAYS)

        parent_events = self._get_active_recurring_parents()
        if not parent_events:
            log.info("RecurrenceExtender: no active recurring parents found")
            return []

        # Batch fetch recurrence patterns, latest children, and facility/timezone data
        parent_ids = [str(p.id) for p in parent_events]
        recurrence_map = self._batch_get_recurrence_patterns(parent_ids)
        latest_child_map = self._batch_get_latest_children(parent_ids)
        facility_name_map = self._batch_get_facility_names(parent_ids)
        facility_state_by_name = self._batch_get_facility_states(facility_name_map.values())

        log.info(f"RecurrenceExtender: processing {len(parent_events)} parent events")

        for parent in parent_events:
            try:
                parent_id = str(parent.id)
                recurrence = recurrence_map.get(parent_id)

                if not recurrence or recurrence == RecurrenceEnum.NONE.value:
                    continue

                is_schedule_event = (
                    parent.note_type.category == NoteTypeCategories.SCHEDULE_EVENT
                )

                # Extend from the latest active child. If a series has no active
                # children, every occurrence was cancelled (the parent itself is
                # still active, or it would have been excluded upstream) — do NOT
                # regenerate events the user deliberately cancelled.
                last_date = latest_child_map.get(parent_id)
                if last_date is None:
                    log.info(f"RecurrenceExtender: parent {parent_id} has no active children, skipping (not regenerating cancelled series)")
                    continue

                if last_date < target_date:
                    local_tz = get_timezone_for_location(
                        parent,
                        facility_name=facility_name_map.get(parent_id),
                        facility_state_by_name=facility_state_by_name,
                    )
                    new_effects = self._create_events_to_horizon(
                        parent, last_date, target_date, recurrence, is_schedule_event, local_tz
                    )
                    log.info(f"RecurrenceExtender: extended parent {parent_id} with {len(new_effects)} events")
                    effects.extend(new_effects)
            except Exception as exc:
                log.exception(f"RecurrenceExtender: error processing parent {parent.id}, skipping: {exc}")
                continue

        log.info(f"RecurrenceExtender: finished with {len(effects)} total new events")
        return effects
