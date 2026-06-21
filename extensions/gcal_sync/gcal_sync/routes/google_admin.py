"""Admin API for the Google Calendar sync (global-scope companion to ``GoogleCalendarAdmin``).

Lets an authorized admin map each Canvas provider to their Workspace calendar email, view sync
health, and trigger an on-demand reconcile. Admin access is gated by ``ADMIN_STAFF_IDS`` and **fails
closed** — an unset/empty list denies everyone (CLAUDE.md), as does a logged-in staff id not on it.

Configuration (mapping changes, on-demand reconcile) lives here in a global-scope app rather than in
any patient/note context, per the admin-separation pattern.
"""

from html import escape
from http import HTTPStatus
from typing import Callable

from requests import RequestException

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.staff import Staff, StaffRole
from logger import log

from gcal_sync.channels import ChannelConfigError, ChannelManager
from gcal_sync.google.auth import GoogleAuthError
from gcal_sync.google.client import GoogleApiError
from gcal_sync.models import CalendarSyncState, StaffCalendarMapping, WatchChannel
from gcal_sync.reconcile import (
    reconcile_all,
    reconcile_provider,
    reimport_provider,
    reset_inbound_for_provider,
)


def parse_provider_emails(csv_text: str) -> list[str]:
    """Extract email addresses from the first column of a pasted CSV.

    Tolerates a header row and blank lines; only the first column is read (the provider list format
    is ``Email,FirstName,LastName``). Emails contain no commas, so a naive split is safe.
    """
    emails = []
    for line in csv_text.splitlines():
        first = line.split(",")[0].strip()
        if "@" in first and first.lower() != "email":
            emails.append(first)
    return emails


class GoogleCalendarAdminAPI(SimpleAPI):
    """Mapping management, sync-health view, and manual reconcile for the Google sync.

    Authorization is enforced per-method by ``_is_admin()`` against the ``ADMIN_STAFF_IDS`` allow-list
    (fail-closed). We intentionally do NOT use ``StaffSessionAuthMixin`` here: on this instance the
    session-credential check rejected the app's modal-iframe request before any handler ran (the page
    rendered blank). The platform still injects the trusted ``canvas-logged-in-user-id`` header, which
    is what the allow-list checks — a stricter gate than "any staff" since only listed ids are allowed.
    """

    def authenticate(self, credentials: Credentials) -> bool:
        # Authorization is handled per-route by _is_admin() using the injected logged-in-user header.
        return True

    def _logged_in_staff_id(self) -> str:
        return str(self.request.headers.get("canvas-logged-in-user-id", ""))

    def _is_admin(self) -> bool:
        """True only when the caller is an explicitly-listed admin. Fails closed if unset."""
        raw = (self.secrets.get("ADMIN_STAFF_IDS") or "").strip()
        if not raw:
            log.warning("ADMIN_STAFF_IDS not configured; denying Google sync admin access")
            return False
        admin_ids = {item.strip() for item in raw.split(",") if item.strip()}
        return self._logged_in_staff_id() in admin_ids

    def _forbidden(self) -> list[Response | Effect]:
        return [JSONResponse({"error": "Not authorized"}, status_code=HTTPStatus.FORBIDDEN)]

    @staticmethod
    def _notice_html(title: str, body_html: str) -> str:
        """A minimal standalone page so the modal shows a readable message instead of rendering blank."""
        return (
            "<!DOCTYPE html><html><head><meta charset='UTF-8'>"
            "<style>body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;padding:24px;color:#1a1f2c}"
            "h2{font-size:16px;margin:0 0 8px}code,pre{background:#f3f4f6;padding:2px 5px;border-radius:4px;"
            "font-size:12px;white-space:pre-wrap;word-break:break-all}</style></head><body>"
            f"<h2>{title}</h2><div>{body_html}</div></body></html>"
        )

    @api.get("/google/admin")
    def index(self) -> list[Response | Effect]:
        # The admin app opens this in a modal iframe. Always answer with HTML (status 200) so a denial
        # or an error renders a readable message rather than a blank/JSON modal.
        if not self._is_admin():
            staff_id = self._logged_in_staff_id() or "(no staff id on request)"
            return [
                HTMLResponse(
                    self._notice_html(
                        "Not authorized",
                        f"Your staff id <code>{escape(staff_id)}</code> is not in the "
                        "<code>ADMIN_STAFF_IDS</code> secret. Add it (comma-separated for several) "
                        "and reopen this app.",
                    ),
                    status_code=HTTPStatus.OK,
                )
            ]
        try:
            html = render_to_string("templates/google_admin.html", self._page_context())
        except Exception as exc:
            # Surface setup problems (e.g. custom-data tables not yet created) instead of a blank 500.
            log.exception("Google Calendar admin page failed to render")
            return [
                HTMLResponse(
                    self._notice_html(
                        "Google Calendar Sync — setup incomplete",
                        "The admin page could not load. This usually means the plugin's custom-data "
                        "tables were not created (check that the manifest declares <code>custom_data</code> "
                        f"and reinstall).<br><br>Details:<pre>{escape(str(exc))}</pre>",
                    ),
                    status_code=HTTPStatus.OK,
                )
            ]
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.post("/google/admin/mapping")
    def save_mapping(self) -> list[Response | Effect]:
        if not self._is_admin():
            return self._forbidden()

        body = self.request.json()
        staff_id = (body.get("staff_id") or "").strip()
        calendar_email = (body.get("calendar_email") or "").strip()
        active = bool(body.get("active", True))
        if not staff_id:
            return [JSONResponse({"error": "staff_id is required"}, status_code=HTTPStatus.BAD_REQUEST)]
        if active and not calendar_email:
            return [
                JSONResponse(
                    {"error": "calendar_email is required to enable sync"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        mapping, _created = StaffCalendarMapping.objects.get_or_create(canvas_staff_id=staff_id)
        mapping.google_calendar_id = calendar_email
        mapping.active = active
        mapping.save()

        warning = self._open_channel_best_effort(calendar_email) if active else None
        return [JSONResponse({"status": "saved", "warning": warning}, status_code=HTTPStatus.OK)]

    @api.post("/google/admin/auto-map")
    def auto_map(self) -> list[Response | Effect]:
        """Map every schedulable provider to their own Staff-profile email in one action.

        "Schedulable provider" = an active staff member with a Provider role. Each gets an active
        mapping to their Workspace calendar (their Staff email). Providers without an email on file
        are skipped and reported so they can be handled via CSV import.
        """
        if not self._is_admin():
            return self._forbidden()

        created = 0
        skipped_no_email = []
        for provider in self._schedulable_providers():
            email = (provider.get("user__email") or "").strip()
            name = f"{provider.get('first_name', '')} {provider.get('last_name', '')}".strip()
            if not email:
                skipped_no_email.append(name or str(provider.get("id")))
                continue
            self._upsert_mapping(str(provider["id"]), email)
            created += 1

        return [
            JSONResponse(
                {"status": "ok", "mapped": created, "skipped_no_email": skipped_no_email},
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/google/admin/bulk-import")
    def bulk_import(self) -> list[Response | Effect]:
        """Map providers from a pasted CSV by matching the email column to Canvas staff emails.

        Fallback for providers the auto-map didn't cover (e.g. no Provider role, or a different
        calendar address than their Staff email). Unmatched emails are reported, not guessed.
        """
        if not self._is_admin():
            return self._forbidden()

        emails = parse_provider_emails(self.request.json().get("csv") or "")
        if not emails:
            return [JSONResponse({"error": "No emails found in CSV"}, status_code=HTTPStatus.BAD_REQUEST)]

        email_to_staff = {
            (row.get("user__email") or "").strip().lower(): str(row["id"])
            for row in Staff.objects.filter(active=True).values("id", "user__email")
            if row.get("user__email")
        }

        matched = 0
        unmatched = []
        for email in emails:
            staff_id = email_to_staff.get(email.lower())
            if staff_id is None:
                unmatched.append(email)
                continue
            self._upsert_mapping(staff_id, email)
            matched += 1

        return [
            JSONResponse(
                {"status": "ok", "matched": matched, "unmatched": unmatched},
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/google/admin/reconcile")
    def reconcile(self) -> list[Response | Effect]:
        if not self._is_admin():
            return self._forbidden()
        try:
            stats, effects = reconcile_all(self.secrets)
        except (GoogleApiError, GoogleAuthError, RequestException) as exc:
            log.error("Manual reconcile failed: %s", exc)
            return [
                JSONResponse({"error": "Reconcile failed"}, status_code=HTTPStatus.SERVICE_UNAVAILABLE)
            ]
        # Apply any inbound admin-hold effects alongside the JSON summary.
        return [*effects, JSONResponse({"status": "ok", **stats}, status_code=HTTPStatus.OK)]

    def _provider_action(
        self, action: Callable[[dict, StaffCalendarMapping], tuple[dict, list]]
    ) -> list[Response | Effect]:
        """Shared handler for the per-provider buttons (reconcile / re-import)."""
        if not self._is_admin():
            return self._forbidden()
        staff_id = (self.request.json().get("staff_id") or "").strip()
        mapping = StaffCalendarMapping.objects.filter(
            canvas_staff_id=staff_id, active=True
        ).first()
        if mapping is None:
            return [
                JSONResponse(
                    {"error": "Provider is not enrolled"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]
        try:
            stats, effects = action(self.secrets, mapping)
        except (GoogleApiError, GoogleAuthError, RequestException) as exc:
            log.error("Provider action failed for %s: %s", staff_id, exc)
            return [JSONResponse({"error": "Action failed"}, status_code=HTTPStatus.SERVICE_UNAVAILABLE)]
        return [*effects, JSONResponse({"status": "ok", **stats}, status_code=HTTPStatus.OK)]

    @api.post("/google/admin/reconcile-provider")
    def reconcile_one(self) -> list[Response | Effect]:
        """Reconcile a single provider (fast — never does all providers at once)."""
        return self._provider_action(reconcile_provider)

    @api.post("/google/admin/reimport-provider")
    def reimport_one(self) -> list[Response | Effect]:
        """Force a full re-pull of one provider's Google calendar (imports existing events as holds)."""
        return self._provider_action(reimport_provider)

    @api.post("/google/admin/purge-provider")
    def purge_one(self) -> list[Response | Effect]:
        """Cancel a provider's imported gcal-sync holds and clear their inbound mappings — no rebuild.

        The manual, admin-gated cleanup tool for when one provider's inbound sync goes wrong. Unlike
        Re-import (which resets *and* re-pulls), this only clears. It is intentional and per-provider:
        there is no automatic sweep. Works whether the provider is currently enabled or not, so a
        provider can be disabled and then purged.
        """
        if not self._is_admin():
            return self._forbidden()
        staff_id = (self.request.json().get("staff_id") or "").strip()
        mapping = StaffCalendarMapping.objects.filter(canvas_staff_id=staff_id).first()
        if mapping is None:
            return [
                JSONResponse(
                    {"error": "Provider has no calendar mapping"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]
        effects = reset_inbound_for_provider(mapping)
        return [
            *effects,
            JSONResponse({"status": "ok", "purged": len(effects)}, status_code=HTTPStatus.OK),
        ]

    @staticmethod
    def _schedulable_providers() -> list[dict]:
        """Active staff with a Provider role — the ones who can be booked on appointments."""
        return list(
            Staff.objects.filter(active=True, roles__role_type=StaffRole.RoleType.PROVIDER)
            .values("id", "first_name", "last_name", "user__email")
            .distinct()
            .order_by("last_name", "first_name")
        )

    @staticmethod
    def _upsert_mapping(staff_id: str, calendar_email: str) -> None:
        mapping, _created = StaffCalendarMapping.objects.get_or_create(canvas_staff_id=staff_id)
        mapping.google_calendar_id = calendar_email
        mapping.active = True
        mapping.save()

    def _open_channel_best_effort(self, calendar_email: str) -> str | None:
        """Open a watch channel for a newly-enabled calendar; return a warning string on failure."""
        try:
            ChannelManager(self.secrets).open_channel(calendar_email)
            return None
        except (ChannelConfigError, GoogleApiError, GoogleAuthError, RequestException) as exc:
            log.error("Could not open watch channel for %s: %s", calendar_email, exc)
            return f"Mapping saved, but the watch channel could not be opened: {exc}"

    def _page_context(self) -> dict:
        mappings = {m.canvas_staff_id: m for m in StaffCalendarMapping.objects.all()}
        channels = self._latest_channel_by_calendar()
        sync_states = {s.google_calendar_id: s for s in CalendarSyncState.objects.all()}

        providers = []
        staff_rows = (
            Staff.objects.filter(active=True)
            .values("id", "first_name", "last_name", "user__email")
            .order_by("last_name", "first_name")
        )
        for staff in staff_rows:
            staff_id = str(staff["id"])
            mapping = mappings.get(staff_id)
            calendar_id = mapping.google_calendar_id if mapping else (staff.get("user__email") or "")
            channel = channels.get(calendar_id) if calendar_id else None
            state = sync_states.get(calendar_id) if calendar_id else None
            providers.append(
                {
                    "staff_id": staff_id,
                    "name": f"{staff.get('first_name', '')} {staff.get('last_name', '')}".strip(),
                    "calendar_email": calendar_id,
                    "active": bool(mapping and mapping.active),
                    "mapped": mapping is not None,
                    "channel_expiration": channel.expiration if channel else None,
                    "needs_full_resync": bool(state and state.needs_full_resync),
                }
            )

        return {"providers": providers, "logged_in_staff_id": self._logged_in_staff_id()}

    @staticmethod
    def _latest_channel_by_calendar() -> dict:
        latest: dict = {}
        for channel in WatchChannel.objects.all().order_by("created_at"):
            latest[channel.google_calendar_id] = channel  # later rows overwrite -> newest wins
        return latest
