from datetime import datetime, timezone
from hmac import compare_digest
from uuid import uuid4

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Calendar, CalendarType, Event
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import APIKeyCredentials, SimpleAPI
from canvas_sdk.handlers.simple_api.api import post
from canvas_sdk.v1.data.calendar import Calendar as CalendarModel
from canvas_sdk.v1.data.staff import Staff
from logger import log

from open_availability.protocols.open_availability import (
    create_availability_event,
    get_calendar_description,
    get_schedulable_roles,
    is_staff_schedulable,
)


class ProvisionAvailabilityAPI(SimpleAPI):
    """API endpoint for manually triggering open availability provisioning."""

    PREFIX = "/provision-availability"

    def authenticate(self, credentials: APIKeyCredentials) -> bool:
        """Validate the API key from the Authorization header against the plugin secret."""
        api_key = self.secrets.get("simpleapi-api-key", "")
        if not api_key:
            return False
        return compare_digest(credentials.key.encode(), api_key.encode())

    def _provision_staff(self, force: bool = False) -> list[Response | Effect]:
        """Provision availability calendars for all active schedulable staff.

        When force=True, ends all existing active events before creating new ones.
        This allows admins to update availability windows for already-provisioned users.
        """
        schedulable_roles = get_schedulable_roles(self.secrets)
        effects: list[Response | Effect] = []
        created = 0
        skipped = 0
        ended = 0
        errored = 0
        skipped_staff: list[str] = []
        errored_staff: list[str] = []

        active_staff = Staff.objects.filter(active=True)
        mode = "force" if force else "normal"
        log.info(
            f"[ProvisionAPI] Checking {active_staff.count()} active staff "
            f"for open availability (mode={mode})"
        )

        for staff in active_staff:
            if not is_staff_schedulable(staff, schedulable_roles):
                continue

            try:
                calendar_description = get_calendar_description(staff.id)

                existing_calendar = CalendarModel.objects.filter(
                    description=calendar_description
                ).first()

                if existing_calendar:
                    now = datetime.now(timezone.utc)
                    active_events = existing_calendar.events.filter(
                        title="Available",
                        recurrence_ends_at__gt=now,
                    )

                    if active_events.exists():
                        if not force:
                            log.info(
                                f"[ProvisionAPI] Skipping {staff.full_name} "
                                f"({staff.id}) - already has active availability"
                            )
                            skipped_staff.append(
                                f"{staff.full_name} ({staff.id})"
                            )
                            skipped += 1
                            continue

                        # Force mode: end all active events first
                        for event in active_events:
                            log.info(
                                f"[ProvisionAPI] Force ending event {event.id} "
                                f"for {staff.full_name}"
                            )
                            effects.append(
                                Event(
                                    event_id=str(event.id),
                                    title=event.title,
                                    starts_at=event.starts_at,
                                    ends_at=event.ends_at,
                                    recurrence_ends_at=now,
                                ).update()
                            )
                            ended += 1

                    calendar_id = str(existing_calendar.id)
                    log.info(
                        f"[ProvisionAPI] Calendar exists for {staff.full_name}, "
                        f"creating new availability event"
                    )
                else:
                    calendar_id = str(uuid4())
                    log.info(
                        f"[ProvisionAPI] Creating calendar and availability "
                        f"for staff: {staff.full_name}"
                    )

                    calendar_effect = Calendar(
                        id=calendar_id,
                        provider=str(staff.id),
                        type=CalendarType.Clinic,
                        description=calendar_description,
                    ).create()
                    effects.append(calendar_effect)

                effects.append(create_availability_event(calendar_id, self.secrets))
                created += 1
            except Exception:
                log.exception(
                    f"[ProvisionAPI] Failed to create availability for staff "
                    f"{staff.id} ({staff.full_name}). Continuing."
                )
                errored_staff.append(f"{staff.full_name} ({staff.id})")
                errored += 1

        log.info(
            f"[ProvisionAPI] Provisioning complete (mode={mode}). "
            f"Created: {created}, Skipped: {skipped}, "
            f"Ended: {ended}, Errors: {errored}"
        )
        if skipped_staff:
            log.info(
                f"[ProvisionAPI] Skipped staff: {', '.join(skipped_staff)}"
            )
        if errored_staff:
            log.info(
                f"[ProvisionAPI] Errored staff: {', '.join(errored_staff)}"
            )

        effects.append(
            JSONResponse(
                content={
                    "created": created,
                    "skipped": skipped,
                    "ended": ended,
                    "errored": errored,
                    "errored_staff": errored_staff,
                }
            )
        )
        return effects

    @post("/run")
    def run_provisioning(self) -> list[Response | Effect]:
        """Provision availability - skips staff with existing active events."""
        return self._provision_staff(force=False)

    @post("/force-run")
    def force_provisioning(self) -> list[Response | Effect]:
        """Force provision - ends existing events and creates new ones for all staff."""
        return self._provision_staff(force=True)
