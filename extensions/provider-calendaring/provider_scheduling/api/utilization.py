from datetime import datetime, timedelta, timezone
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin
from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from canvas_sdk.v1.data.calendar import Event
from canvas_sdk.v1.data.staff import Staff


class UtilizationAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """API endpoint to retrieve utilization metrics."""

    PATH = "/utilization"

    def get(self) -> list[Response | Effect]:
        """Get utilization metrics for a provider within a lookback period."""
        provider_id = self.request.query_params.get("provider_id")
        lookback_period = self.request.query_params.get("lookback_period", "week")

        # Calculate the date range based on lookback period
        now = datetime.now(timezone.utc)
        if lookback_period == "day":
            start_date = now - timedelta(days=1)
        elif lookback_period == "month":
            start_date = now - timedelta(days=30)
        else:  # week
            start_date = now - timedelta(days=7)

        # Get the provider
        try:
            provider = Staff.objects.get(id=provider_id)
        except Staff.DoesNotExist:
            return [
                JSONResponse(
                    {"error": "Provider not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        provider_name = provider.full_name

        # Query calendar events for this provider
        # Calendar title format: "{provider_name}: {calendar_type}: {location}" or "{provider_name}: {calendar_type}"
        # Calendar types: "Clinic" (available time), "Admin" (administrative time)

        # Get available time from Clinic calendar events
        clinic_events = Event.objects.filter(
            calendar__title__startswith=f"{provider_name}: Clinic",
            starts_at__gte=start_date,
            starts_at__lte=now,
            is_cancelled=False,
        )

        available_minutes = 0
        for event in clinic_events:
            duration = event.ends_at - event.starts_at
            available_minutes += duration.total_seconds() / 60

        # Get administrative time from Admin calendar events
        admin_events = Event.objects.filter(
            calendar__title__startswith=f"{provider_name}: Admin",
            starts_at__gte=start_date,
            starts_at__lte=now,
            is_cancelled=False,
        )

        administrative_minutes = 0
        for event in admin_events:
            duration = event.ends_at - event.starts_at
            administrative_minutes += duration.total_seconds() / 60

        # Get booked time from appointments
        # Exclude cancelled and no-showed appointments
        excluded_statuses = [
            AppointmentProgressStatus.CANCELLED,
            AppointmentProgressStatus.NOSHOWED,
        ]

        appointments = Appointment.objects.filter(
            provider_id=provider.dbid,
            start_time__gte=start_date,
            start_time__lte=now,
        ).exclude(status__in=excluded_statuses)

        booked_minutes = sum(apt.duration_minutes or 0 for apt in appointments)

        # Calculate unbooked time (available - booked, but not less than 0)
        unbooked_minutes = max(0, available_minutes - booked_minutes)

        metrics = {
            "providerId": provider_id,
            "lookbackPeriod": lookback_period,
            "startDate": start_date.isoformat(),
            "endDate": now.isoformat(),
            "availableMinutes": int(available_minutes),
            "bookedMinutes": int(booked_minutes),
            "unbookedMinutes": int(unbooked_minutes),
            "administrativeMinutes": int(administrative_minutes),
        }

        return [JSONResponse(metrics, status_code=HTTPStatus.OK)]
