"""API endpoint for provisioning Clinic calendars and availability events."""

from __future__ import annotations

from http import HTTPStatus
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from uuid import uuid4

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Calendar as CalendarEffect
from canvas_sdk.effects.calendar import CalendarType, EventRecurrence
from canvas_sdk.effects.calendar import Event as EventEffect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import APIKeyCredentials, SimpleAPI
from canvas_sdk.handlers.simple_api.api import delete, get, post, put
from canvas_sdk.v1.data.calendar import Calendar as CalendarModel
from canvas_sdk.v1.data.staff import Staff
from logger import log

from provider_availability.engine.storage import (
    add_allowed_staff,
    get_allowed_staff,
    get_practice_timezone,
    remove_allowed_staff,
    set_allowed_staff,
    set_practice_timezone,
)
from provider_availability.engine.tz_utils import COMMON_TIMEZONES

SCHEDULABLE_ROLES = {"MD", "DO", "NP", "PA"}
AVAILABILITY_YEARS = 25


class ProvisionAPI(SimpleAPI):
    """API key-authenticated endpoint for provisioning provider calendars."""

    PREFIX = "/provision"

    def authenticate(self, credentials: APIKeyCredentials) -> bool:
        """Validate API key from the Authorization header."""
        api_key = self.secrets.get("simpleapi-api-key", "")
        if not api_key:
            return False
        return compare_digest(credentials.key.encode(), api_key.encode())

    @post("/run")
    def run_provisioning(self) -> list[Response | Effect]:
        """Create Clinic calendars and daily Available events for all active providers.

        Idempotent: skips providers that already have an active Available event.
        """
        effects: list[Effect] = []
        created = 0
        skipped = 0
        errored = 0

        active_staff = Staff.objects.filter(active=True)
        log.info("provision: checking %d active staff", active_staff.count())

        for staff in active_staff:
            role = staff.top_role_abbreviation
            if not role or role.upper() not in SCHEDULABLE_ROLES:
                continue

            try:
                staff_key = str(staff.id)
                existing_cal = CalendarModel.objects.filter(
                    description=staff_key
                ).first()

                if existing_cal:
                    now = datetime.now(UTC).replace(tzinfo=None)
                    active_event = existing_cal.events.filter(
                        title="Available",
                        recurrence_ends_at__gt=now,
                    ).first()
                    if active_event:
                        skipped += 1
                        continue
                    calendar_id = str(existing_cal.id)
                    log.info(
                        "provision: calendar exists for %s %s, creating event",
                        staff.first_name, staff.last_name,
                    )
                else:
                    calendar_id = str(uuid4())
                    cal_effect = CalendarEffect(
                        id=calendar_id,
                        provider=staff_key,
                        type=CalendarType.Clinic,
                        description=staff_key,
                    ).create()
                    effects.append(cal_effect)
                    log.info(
                        "provision: created calendar for %s %s",
                        staff.first_name, staff.last_name,
                    )

                # Daily recurring Available event: 08:00-03:59 UTC (~20 hrs)
                now_utc = datetime.now(UTC).replace(tzinfo=None)
                start_of_day = datetime(
                    now_utc.year, now_utc.month, now_utc.day, 8, 0
                )
                end_of_day = start_of_day + timedelta(hours=19, minutes=59)
                try:
                    recurrence_end = datetime(
                        now_utc.year + AVAILABILITY_YEARS,
                        now_utc.month, now_utc.day, 3, 59,
                    )
                except ValueError:
                    # Feb 29 + 25 years may land on a non-leap year
                    recurrence_end = datetime(
                        now_utc.year + AVAILABILITY_YEARS,
                        now_utc.month, now_utc.day - 1, 3, 59,
                    )

                event_effect = EventEffect(
                    calendar_id=calendar_id,
                    title="Available",
                    starts_at=start_of_day,
                    ends_at=end_of_day,
                    recurrence_frequency=EventRecurrence.Daily,
                    recurrence_interval=1,
                    recurrence_ends_at=recurrence_end,
                ).create()
                effects.append(event_effect)
                created += 1

            except Exception:
                log.exception(
                    "provision: failed for staff %s (%s %s)",
                    staff.id, staff.first_name, staff.last_name,
                )
                errored += 1

        log.info(
            "provision: complete. created=%d, skipped=%d, errored=%d",
            created, skipped, errored,
        )

        return [
            *effects,
            JSONResponse({
                "message": "Provisioning complete",
                "created": created,
                "skipped": skipped,
                "errored": errored,
            }),
        ]

    # ── Allowed staff management ──────────────────────────────────────

    @get("/allowed-staff")
    def list_allowed_staff(self) -> list[Response | Effect]:
        """Return the list of staff IDs allowed to access the admin UI."""
        ids = get_allowed_staff()
        return [JSONResponse({"allowed_staff": ids, "count": len(ids)})]

    @put("/allowed-staff")
    def replace_allowed_staff(self) -> list[Response | Effect]:
        """Replace the full allowed staff list."""
        body = self.request.json()
        ids = body.get("staff_ids", [])
        if not isinstance(ids, list):
            return [
                JSONResponse(
                    {"error": "staff_ids must be a list"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        set_allowed_staff([str(i) for i in ids])
        log.info("replace_allowed_staff: set %d staff IDs", len(ids))
        return [JSONResponse({"message": "Allowed staff list updated", "count": len(ids)})]

    @post("/allowed-staff")
    def add_allowed_staff_endpoint(self) -> list[Response | Effect]:
        """Add a single staff ID to the allowed list."""
        body = self.request.json()
        staff_id = body.get("staff_id", "")
        if not staff_id:
            return [
                JSONResponse(
                    {"error": "staff_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        add_allowed_staff(str(staff_id))
        log.info("add_allowed_staff: added %s", staff_id)
        return [
            JSONResponse(
                {"message": "Staff added", "staff_id": str(staff_id)},
                status_code=HTTPStatus.CREATED,
            )
        ]

    @delete("/allowed-staff/<staff_id>")
    def remove_allowed_staff_endpoint(self) -> list[Response | Effect]:
        """Remove a staff ID from the allowed list."""
        staff_id = self.request.path_params["staff_id"]
        remove_allowed_staff(str(staff_id))
        log.info("remove_allowed_staff: removed %s", staff_id)
        return [JSONResponse({"message": "Staff removed", "staff_id": staff_id})]

    # ── Timezone management ───────────────────────────────────────────

    @get("/timezone")
    def get_timezone(self) -> list[Response | Effect]:
        """Return the current practice timezone and available options."""
        return [
            JSONResponse({
                "timezone": get_practice_timezone(),
                "available": COMMON_TIMEZONES,
            })
        ]

    @put("/timezone")
    def set_timezone(self) -> list[Response | Effect]:
        """Set the practice timezone."""
        body = self.request.json()
        tz_name = body.get("timezone", "")
        if not tz_name or tz_name not in COMMON_TIMEZONES:
            return [
                JSONResponse(
                    {"error": f"Invalid timezone. Choose from: {', '.join(COMMON_TIMEZONES)}"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        set_practice_timezone(tz_name)
        log.info("provision set_timezone: changed to %s", tz_name)
        return [JSONResponse({"message": f"Timezone set to {tz_name}", "timezone": tz_name})]
