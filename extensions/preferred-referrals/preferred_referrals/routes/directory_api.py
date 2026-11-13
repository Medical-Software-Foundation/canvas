"""Directory page, CSV import, activation, and the referral report.

Any signed-in staff member can view the directory and the report. Changing the
directory (import, deactivate, reactivate) needs the caller's staff id in
``ADMIN_STAFF_IDS``, and an unset list denies everyone.
"""

import uuid
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.service_provider import ServiceProvider as ServiceProviderEffect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, api
from canvas_sdk.handlers.simple_api.security import StaffSessionAuthMixin
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.referral import Referral
from django.db.models import Count
from logger import log

from preferred_referrals import CACHE_BUST
from preferred_referrals.directory import (
    MAX_IMPORT_ROWS,
    import_effects,
    preferred_providers,
    serialize_provider,
)

# Canvas strips this header from client requests and sets it from the session.
SESSION_ID_HEADER = "canvas-logged-in-user-id"

DEFAULT_REPORT_DAYS = 90
MAX_REPORT_DAYS = 365
MAX_LISTED_PROVIDERS = 1000


def _normalize_id(value: Any) -> str:
    return str(value or "").strip().replace("-", "").lower()


def _parse_uuid(value: Any) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _report_days(raw: Any) -> int:
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_REPORT_DAYS
    return max(1, min(days, MAX_REPORT_DAYS))


def _error(message: str, status: HTTPStatus) -> list[Response | Effect]:
    return [JSONResponse({"error": message}, status_code=status)]


class DirectoryAPI(StaffSessionAuthMixin, SimpleAPI):
    """Routes under ``/plugin-io/api/preferred_referrals/``."""

    def _staff_id(self) -> str:
        headers = getattr(self.request, "headers", None) or {}
        return str(headers.get(SESSION_ID_HEADER, "") or "")

    def _is_admin(self) -> bool:
        """True only for a listed staff id. An unset list denies everyone."""
        raw = (self.secrets.get("ADMIN_STAFF_IDS") or "").strip()
        if not raw:
            log.warning("ADMIN_STAFF_IDS is not set; directory changes are denied")
            return False
        admins = {_normalize_id(item) for item in raw.split(",") if item.strip()}
        caller = _normalize_id(self._staff_id())
        return bool(caller) and caller in admins

    # --- page ---------------------------------------------------------------

    @api.get("/app/")
    def page(self) -> list[Response | Effect]:
        """The directory and report page."""
        html = render_to_string(
            "templates/directory.html",
            {
                "cache_bust": CACHE_BUST,
                "is_admin": self._is_admin(),
                "max_import_rows": MAX_IMPORT_ROWS,
            },
        )
        return [HTMLResponse(html)]

    # --- directory ----------------------------------------------------------

    @api.get("/providers")
    def list_providers(self) -> list[Response | Effect]:
        """Every preferred provider, active first, with all-time referral counts."""
        providers = list(
            preferred_providers().order_by(
                "-is_active", "first_name", "last_name", "dbid"
            )[:MAX_LISTED_PROVIDERS]
        )
        counts = {
            row["service_provider_id"]: row["n"]
            for row in Referral.objects.committed()
            .filter(service_provider__is_customer_managed=True)
            .values("service_provider_id")
            .annotate(n=Count("dbid"))
        }
        return [
            JSONResponse(
                {
                    "providers": [
                        serialize_provider(provider, counts.get(provider.dbid, 0))
                        for provider in providers
                    ],
                    "truncated": len(providers) >= MAX_LISTED_PROVIDERS,
                    "is_admin": self._is_admin(),
                }
            )
        ]

    @api.post("/providers/import")
    def import_providers(self) -> list[Response | Effect]:
        """Create or update providers from parsed CSV rows: ``{"rows": [{...}]}``."""
        if not self._is_admin():
            return _error("Only directory admins can import.", HTTPStatus.FORBIDDEN)
        try:
            body = self.request.json()
        except ValueError:
            return _error("Body must be JSON.", HTTPStatus.BAD_REQUEST)
        rows = body.get("rows") if isinstance(body, dict) else None
        if not isinstance(rows, list) or not rows:
            return _error("Send at least one row.", HTTPStatus.BAD_REQUEST)
        if len(rows) > MAX_IMPORT_ROWS:
            return _error(
                f"Send at most {MAX_IMPORT_ROWS} rows per request.",
                HTTPStatus.BAD_REQUEST,
            )

        effects, errors = import_effects(rows)
        log.info(
            "Preferred referrals import: %s saved, %s rejected",
            len(effects),
            len(errors),
        )
        return [
            *effects,
            JSONResponse({"saved": len(effects), "errors": errors}),
        ]

    @api.post("/providers/<provider_id>/deactivate")
    def deactivate(self) -> list[Response | Effect]:
        """Retire a provider. It stays on past referrals; it leaves the search."""
        return self._set_active(active=False)

    @api.post("/providers/<provider_id>/reactivate")
    def reactivate(self) -> list[Response | Effect]:
        """Bring a retired provider back into the search."""
        return self._set_active(active=True)

    def _set_active(self, *, active: bool) -> list[Response | Effect]:
        if not self._is_admin():
            return _error(
                "Only directory admins can change providers.", HTTPStatus.FORBIDDEN
            )
        provider_id = _parse_uuid(self.request.path_params.get("provider_id"))
        if provider_id is None:
            return _error("Unknown provider.", HTTPStatus.NOT_FOUND)
        # Only our own providers: the shared directory's rows are not ours to retire.
        provider = preferred_providers().filter(id=provider_id).only("id").first()
        if provider is None:
            return _error("Unknown provider.", HTTPStatus.NOT_FOUND)

        if active:
            effect = ServiceProviderEffect(id=provider_id, is_active=True).update()
        else:
            effect = ServiceProviderEffect(id=provider_id).deactivate()
        return [effect, JSONResponse({"id": provider_id, "is_active": active})]

    # --- report -------------------------------------------------------------

    @api.get("/report")
    def report(self) -> list[Response | Effect]:
        """Committed referrals in the window: how many went to preferred providers."""
        days = _report_days(self.request.query_params.get("days"))
        since = datetime.now(UTC) - timedelta(days=days)
        window = Referral.objects.committed().filter(date_referred__gte=since)
        preferred = window.filter(service_provider__is_customer_managed=True)

        total = window.count()
        to_preferred = preferred.count()
        by_provider = list(
            preferred.values(
                "service_provider_id",
                "service_provider__first_name",
                "service_provider__last_name",
                "service_provider__specialty",
            )
            .annotate(n=Count("dbid"))
            .order_by("-n")[:50]
        )
        return [
            JSONResponse(
                {
                    "days": days,
                    "total": total,
                    "to_preferred": to_preferred,
                    "to_other": total - to_preferred,
                    "preferred_share": round(to_preferred / total, 3)
                    if total
                    else None,
                    # No consult report back yet: the native Outstanding Referrals
                    # queue tracks these one by one; this is the count.
                    "awaiting_report": window.filter(reports__isnull=True).count(),
                    "by_provider": [
                        {
                            "name": " ".join(
                                part
                                for part in (
                                    row["service_provider__first_name"],
                                    row["service_provider__last_name"],
                                )
                                if part
                            ),
                            "specialty": row["service_provider__specialty"] or "",
                            "referrals": row["n"],
                        }
                        for row in by_provider
                    ],
                }
            )
        ]
