from http import HTTPStatus

from canvas_sdk.effects.simple_api import HTMLResponse, PlainTextResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.staff import Staff

from external_calendar_busy_blocks.auth import canonical_staff_id, is_admin
from external_calendar_busy_blocks.data.models import ImportedEvent, StaffCalendarFeed


class ConfigPage(StaffSessionAuthMixin, SimpleAPI):
    """GET /pages/config — renders the connect/disconnect HTML page."""

    @api.get("/pages/config")
    def render(self) -> list[Response]:
        staff_id = canonical_staff_id(self.request.headers)
        feed = StaffCalendarFeed.objects.filter(staff_id=staff_id).first() if staff_id else None

        admin = is_admin(staff_id, self.secrets)
        staff_options: list[dict] = []
        if admin:
            active_staff = [
                s
                for s in Staff.objects.filter(active=True).order_by("last_name", "first_name")
                if (s.full_name or "").strip()
            ]
            staff_ids = [s.id for s in active_staff]
            # One bulk query for every provider's current feed (no per-row query).
            feeds_by_staff = {
                f.staff_id: f
                for f in StaffCalendarFeed.objects.filter(staff_id__in=staff_ids)
            }
            # One bulk query for imported-event counts per provider. values_list
            # avoids pulling full rows; tally in Python (no Count/Counter import).
            event_counts: dict[str, int] = {}
            for sid in ImportedEvent.objects.filter(staff_id__in=staff_ids).values_list(
                "staff_id", flat=True
            ):
                event_counts[sid] = event_counts.get(sid, 0) + 1
            for s in active_staff:
                f = feeds_by_staff.get(s.id)
                staff_options.append(
                    {
                        "id": s.id,
                        "name": s.full_name,
                        "connected": bool(f and f.is_active),
                        "last_sync_at": str(f.last_sync_at) if f and f.last_sync_at else None,
                        "last_error": f.last_error if f else None,
                        "event_count": event_counts.get(s.id, 0),
                    }
                )

        html = render_to_string(
            "templates/config.html",
            {
                "feed": feed,
                "connected": feed is not None and feed.is_active,
                "is_admin": admin,
                "staff_options": staff_options,
                "post_url": "/plugin-io/api/external_calendar_busy_blocks/feeds",
                "delete_url": "/plugin-io/api/external_calendar_busy_blocks/feeds/delete",
                "status_url": "/plugin-io/api/external_calendar_busy_blocks/feeds/status",
            },
        )
        # render_to_string is typed `str | None`. The current SDK raises
        # FileNotFoundError on a missing template rather than returning None,
        # but guard against the declared contract so a None can never reach
        # HTMLResponse (whose content.encode() would raise) — return an
        # explicit 500 instead.
        if html is None:
            return [PlainTextResponse(
                "Unable to render the configuration page.",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )]
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]
