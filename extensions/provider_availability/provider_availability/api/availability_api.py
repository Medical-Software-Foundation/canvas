"""REST API for querying provider availability and managing rules."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from http import HTTPStatus

from logger import log

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from provider_availability.engine.calculator import (
    calculate_available_slots,
    get_available_slots_for_provider,
)
from provider_availability.engine.event_sync import (
    build_block_event_effects,
    build_delete_block_effects,
    build_delete_effects,
    build_delete_recurring_block_effects,
    build_lead_time_block_effects,
    build_recurring_block_sync_effects,
    sync_provider_availability,
)
from provider_availability.engine.lookups import (
    get_active_locations,
    get_active_providers,
    get_scheduleable_visit_types,
)
from provider_availability.engine.models import (
    AdminBlock,
    BookingInterval,
    BufferTime,
    DateOverride,
    ProviderAvailabilityRule,
    RecurringBlock,
    TimeWindow,
)
from provider_availability.engine.overlap import check_rule_overlap
from provider_availability.engine.storage import (
    delete_block,
    delete_recurring_block,
    delete_rule_by_id,
    delete_rules_for_provider,
    get_all_blocks,
    get_all_rules,
    get_all_recurring_blocks,
    get_allowed_staff,
    get_block_by_id,
    get_blocks_by_group,
    get_blocks_for_provider,
    get_all_provider_timezones,
    get_practice_timezone,
    get_provider_timezone,
    get_recurring_block_by_id,
    get_recurring_blocks_by_group,
    get_recurring_blocks_for_provider,
    get_rule_by_id,
    get_rules_by_group,
    get_rules_for_provider,
    save_block,
    save_recurring_block,
    save_rule,
    set_practice_timezone,
    set_provider_timezone,
)
from provider_availability.engine.tz_utils import COMMON_TIMEZONES
from provider_availability.engine.provider_resolver import (
    get_provider_displays,
    resolve_provider_id,
    search_providers,
)
from provider_availability.templates.admin_ui import render_admin_page

ACCESS_DENIED_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Access Denied</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600&display=swap" rel="stylesheet">
<style>
body { font-family: 'DM Sans', sans-serif; display: flex; align-items: center;
  justify-content: center; min-height: 100vh; margin: 0; background: #EFF5F7; color: #2c4155; }
.card { background: #fff; border-radius: 14px; padding: 48px; text-align: center;
  box-shadow: 0 4px 16px rgba(13,32,60,0.10); max-width: 420px; }
h1 { font-size: 22px; color: #7C5CFC; margin-bottom: 8px; }
p { font-size: 15px; color: #5e7a8a; }
</style>
</head>
<body>
<div class="card">
  <h1>Access Denied</h1>
  <p>You are not authorized to access the Provider Availability admin panel.
  Contact your administrator to request access.</p>
</div>
</body>
</html>"""


def _enrich_rules(rules: list[ProviderAvailabilityRule]) -> list[dict]:
    """Convert rules to dicts and attach provider_name / provider_npi."""
    if not rules:
        return []
    provider_ids = list({r.provider_id for r in rules})
    displays = get_provider_displays(provider_ids)

    # Build location/visit-type name lookups
    try:
        locations = {loc["id"]: loc["name"] for loc in get_active_locations()}
    except Exception:
        locations = {}
    try:
        visit_types = {vt["id"]: vt["name"] for vt in get_scheduleable_visit_types()}
    except Exception:
        visit_types = {}

    enriched: list[dict] = []
    for r in rules:
        d = r.to_dict()
        info = displays.get(r.provider_id, {})
        d["provider_name"] = info.get("name", "")
        d["provider_npi"] = info.get("npi_number", "")
        d["location_names"] = [locations.get(lid, lid) for lid in r.location_ids]
        d["visit_type_names"] = [visit_types.get(vt, vt) for vt in r.visit_types]
        enriched.append(d)
    return enriched


def _enrich_blocks(blocks: list[AdminBlock], displays: dict) -> list[dict]:
    """Convert blocks to dicts with provider_name."""
    enriched: list[dict] = []
    for b in blocks:
        d = b.to_dict()
        info = displays.get(b.provider_id, {})
        d["provider_name"] = info.get("name", "")
        enriched.append(d)
    return enriched


def _enrich_recurring_blocks(blocks: list[RecurringBlock], displays: dict) -> list[dict]:
    """Convert recurring blocks to dicts with provider_name."""
    enriched: list[dict] = []
    for b in blocks:
        d = b.to_dict()
        info = displays.get(b.provider_id, {})
        d["provider_name"] = info.get("name", "")
        enriched.append(d)
    return enriched


_VALID_RECURRENCE_FREQUENCIES = ("weekly", "daily")


def _validate_recurrence_payload(body: dict) -> str | None:
    """Validate recurrence_frequency / recurrence_interval / time_windows.

    Returns an error message string, or None if the payload is valid.
    Default frequency is "weekly", default interval is 1 — both backward-compat.
    """
    freq = body.get("recurrence_frequency", "weekly")
    if freq not in _VALID_RECURRENCE_FREQUENCIES:
        return f"recurrence_frequency must be one of {_VALID_RECURRENCE_FREQUENCIES}"
    interval = body.get("recurrence_interval", 1)
    try:
        interval = int(interval)
    except (TypeError, ValueError):
        return "recurrence_interval must be an integer"
    if interval < 1:
        return "recurrence_interval must be >= 1"
    body["recurrence_interval"] = interval

    if freq == "daily":
        time_windows = body.get("time_windows") or []
        if not time_windows:
            return "time_windows is required when recurrence_frequency is 'daily'"
        for w in time_windows:
            if w.get("start", "") >= w.get("end", ""):
                return f"Start time must be before end time ({w.get('start')} >= {w.get('end')})"
    return None


def _check_write_access(request: object, secrets: dict | None = None) -> list[Response] | None:
    """Return an error response list if the user is not authorized for writes, else None.

    Checks the ``allowed-staff-keys`` plugin secret first (comma-separated staff UUIDs).
    Falls back to cache-based ``get_allowed_staff()`` for backward compat.
    Empty / missing secret = allow everyone (bootstrap behaviour).
    """
    staff_id = str(getattr(request, "staff_id", None) or "")

    # Prefer secret-based access control
    secret_val = (secrets or {}).get("allowed-staff-keys", "")
    if secret_val:
        allowed_keys = [k.strip() for k in secret_val.split(",") if k.strip()]
        if staff_id and staff_id in allowed_keys:
            return None
        return [
            JSONResponse(
                {"error": "Access denied. You are not authorized to modify availability rules."},
                status_code=HTTPStatus.FORBIDDEN,
            )
        ]

    # Fallback: cache-based list (backward compat during migration)
    allowed = get_allowed_staff()
    if not allowed:
        return None  # empty list = allow everyone (bootstrap)
    if staff_id and staff_id in allowed:
        return None
    return [
        JSONResponse(
            {"error": "Access denied. You are not authorized to modify availability rules."},
            status_code=HTTPStatus.FORBIDDEN,
        )
    ]


class AvailabilityAPI(StaffSessionAuthMixin, SimpleAPI):
    """API endpoints for availability queries and rule management."""

    PREFIX = "/api"

    # ── Dropdown endpoints ─────────────────────────────────────────────

    @api.get("/providers/list")
    def list_providers(self) -> list[Response | Effect]:
        """Return all active providers for dropdown population."""
        log.info("list_providers endpoint called")
        try:
            providers = get_active_providers()
            log.info("list_providers returning %d providers", len(providers))
        except Exception:
            log.exception("list_providers failed")
            providers = []
        return [JSONResponse({"providers": providers, "count": len(providers)})]

    @api.get("/locations")
    def list_locations(self) -> list[Response | Effect]:
        """Return all active practice locations for dropdown population."""
        log.info("list_locations endpoint called")
        try:
            locations = get_active_locations()
            log.info("list_locations returning %d locations", len(locations))
        except Exception:
            log.exception("list_locations failed")
            locations = []
        return [JSONResponse({"locations": locations, "count": len(locations)})]

    @api.get("/visit-types")
    def list_visit_types(self) -> list[Response | Effect]:
        """Return scheduleable visit types for dropdown population."""
        log.info("list_visit_types endpoint called")
        try:
            visit_types = get_scheduleable_visit_types()
            log.info("list_visit_types returning %d types", len(visit_types))
        except Exception:
            log.exception("list_visit_types failed")
            visit_types = []
        return [JSONResponse({"visit_types": visit_types, "count": len(visit_types)})]

    # ── Provider search ────────────────────────────────────────────────

    @api.get("/providers/search")
    def search_providers_endpoint(self) -> list[Response | Effect]:
        """Search for providers by name or NPI prefix."""
        params = self.request.query_params
        query = params.get("q", "").strip()
        if not query:
            return [
                JSONResponse(
                    {"error": "q query parameter is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        active_only = params.get("active_only", "true").lower() != "false"
        results = search_providers(query, active_only=active_only)
        return [JSONResponse({"providers": results, "count": len(results)})]

    # ── Overview endpoint ──────────────────────────────────────────────

    @api.get("/overview")
    def get_overview(self) -> list[Response | Effect]:
        """Return all rules + blocks + recurring blocks grouped by provider."""
        rules = get_all_rules()
        blocks = get_all_blocks()
        recurring_blocks = get_all_recurring_blocks()

        # Collect all provider IDs
        provider_ids = set()
        for r in rules:
            provider_ids.add(r.provider_id)
        for b in blocks:
            provider_ids.add(b.provider_id)
        for rb in recurring_blocks:
            provider_ids.add(rb.provider_id)

        displays = get_provider_displays(list(provider_ids)) if provider_ids else {}

        # Build location/visit-type name lookups for rules
        try:
            locations = {loc["id"]: loc["name"] for loc in get_active_locations()}
        except Exception:
            locations = {}
        try:
            visit_types = {vt["id"]: vt["name"] for vt in get_scheduleable_visit_types()}
        except Exception:
            visit_types = {}

        # Group by provider
        provider_tzs = get_all_provider_timezones()
        practice_tz_name = get_practice_timezone()
        providers: dict[str, dict] = {}
        for pid in provider_ids:
            info = displays.get(pid, {})
            providers[pid] = {
                "provider_id": pid,
                "provider_name": info.get("name", ""),
                "provider_timezone": provider_tzs.get(pid) or practice_tz_name,
                "provider_timezone_explicit": pid in provider_tzs,
                "rules": [],
                "blocks": [],
                "recurring_blocks": [],
            }

        for r in rules:
            d = r.to_dict()
            d["location_names"] = [locations.get(lid, lid) for lid in r.location_ids]
            d["visit_type_names"] = [visit_types.get(vt, vt) for vt in r.visit_types]
            providers[r.provider_id]["rules"].append(d)

        for b in blocks:
            providers[b.provider_id]["blocks"].append(b.to_dict())

        for rb in recurring_blocks:
            providers[rb.provider_id]["recurring_blocks"].append(rb.to_dict())

        # Sort providers alphabetically by name
        sorted_providers = sorted(
            providers.values(),
            key=lambda p: p["provider_name"].lower() if p["provider_name"] else "zzz",
        )

        return [JSONResponse({"providers": sorted_providers})]

    # ── Availability queries ───────────────────────────────────────────

    @api.get("/available-slots")
    def get_available_slots(self) -> list[Response | Effect]:
        """Get available time slots for a provider."""
        params = self.request.query_params
        raw_provider_id = params.get("provider_id", "")
        provider_npi = params.get("provider_npi", "")
        start_str = params.get("start_date", "")
        end_str = params.get("end_date", "")

        if not start_str or not end_str:
            return [
                JSONResponse(
                    {"error": "start_date and end_date are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            provider_id = resolve_provider_id(raw_provider_id, provider_npi)
        except ValueError as exc:
            return [
                JSONResponse(
                    {"error": str(exc)},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        start_date = date.fromisoformat(start_str)
        end_date = date.fromisoformat(end_str)

        location_id = params.get("location_id", "")
        visit_type = params.get("visit_type", "")

        rules = get_rules_for_provider(provider_id)
        log.info(
            "available-slots: provider=%s, dates=%s to %s, rules=%d",
            provider_id, start_str, end_str, len(rules),
        )
        if not rules:
            return [JSONResponse({"slots": [], "count": 0})]

        slots = get_available_slots_for_provider(
            rules, start_date, end_date, location_id, visit_type
        )
        log.info("available-slots: returning %d slots", len(slots))

        return [
            JSONResponse(
                {
                    "slots": [s.to_dict() for s in slots],
                    "count": len(slots),
                    "provider_id": provider_id,
                    "start_date": start_str,
                    "end_date": end_str,
                }
            )
        ]

    @api.get("/available-providers")
    def get_available_providers(self) -> list[Response | Effect]:
        """Get providers available during a time range."""
        params = self.request.query_params
        start_str = params.get("start_date", "")
        end_str = params.get("end_date", "")

        if not start_str or not end_str:
            return [
                JSONResponse(
                    {"error": "start_date and end_date are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        start_date = date.fromisoformat(start_str)
        end_date = date.fromisoformat(end_str)
        location_id = params.get("location_id", "")
        visit_type = params.get("visit_type", "")

        all_rules = get_all_rules()

        # Group by provider
        providers_with_slots: dict[str, int] = {}
        for rule in all_rules:
            if location_id:
                if rule.location_ids and location_id not in rule.location_ids:
                    continue
            if visit_type:
                if rule.visit_types and visit_type not in rule.visit_types:
                    continue

            slots = calculate_available_slots(rule, start_date, end_date)
            if slots:
                pid = rule.provider_id
                providers_with_slots[pid] = providers_with_slots.get(pid, 0) + len(slots)

        providers = [
            {"provider_id": pid, "available_slot_count": count}
            for pid, count in providers_with_slots.items()
        ]

        return [
            JSONResponse(
                {
                    "providers": providers,
                    "count": len(providers),
                    "start_date": start_str,
                    "end_date": end_str,
                }
            )
        ]

    # ── Rule CRUD ──────────────────────────────────────────────────────

    @api.get("/rules")
    def list_rules(self) -> list[Response | Effect]:
        """List all rules, optionally filtered by provider or location."""
        params = self.request.query_params
        raw_provider_id = params.get("provider_id", "")
        provider_npi = params.get("provider_npi", "")
        location_id = params.get("location_id", "")

        provider_id = ""
        if raw_provider_id or provider_npi:
            try:
                provider_id = resolve_provider_id(raw_provider_id, provider_npi)
            except ValueError as exc:
                return [
                    JSONResponse(
                        {"error": str(exc)},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]

        if provider_id:
            rules = get_rules_for_provider(provider_id)
        else:
            rules = get_all_rules()

        if location_id:
            rules = [r for r in rules if not r.location_ids or location_id in r.location_ids]

        log.info("list_rules: returning %d rules", len(rules))
        return [
            JSONResponse(
                {
                    "rules": _enrich_rules(rules),
                    "count": len(rules),
                }
            )
        ]

    @api.get("/rules/<provider_id>")
    def get_provider_rules(self) -> list[Response | Effect]:
        """Get all rules for a specific provider."""
        provider_id = self.request.path_params["provider_id"]
        rules = get_rules_for_provider(provider_id)

        return [
            JSONResponse(
                {
                    "rules": _enrich_rules(rules),
                    "count": len(rules),
                    "provider_id": provider_id,
                }
            )
        ]

    @api.post("/rules")
    def create_or_update_rule(self) -> list[Response | Effect]:
        """Create or update a rule for a provider."""
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        body = self.request.json()

        raw_provider_id = body.get("provider_id", "")
        provider_npi = body.get("provider_npi", "")

        if not raw_provider_id and not provider_npi:
            return [
                JSONResponse(
                    {"error": "provider_id or provider_npi is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            provider_id = resolve_provider_id(raw_provider_id, provider_npi)
        except ValueError as exc:
            return [
                JSONResponse(
                    {"error": str(exc)},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        body["provider_id"] = provider_id
        body.pop("provider_npi", None)
        body["updated_at"] = datetime.now(UTC).isoformat()

        # Accept both old single-value and new list formats
        if "location_ids" not in body and "location_id" in body:
            loc = body.pop("location_id", "")
            body["location_ids"] = [loc] if loc else []
        if "visit_types" not in body and "visit_type" in body:
            vt = body.pop("visit_type", "")
            body["visit_types"] = [vt] if vt else []

        # Validate start < end for each time window
        for day, windows in body.get("weekly_schedule", {}).items():
            for w in windows:
                if w.get("start", "") >= w.get("end", ""):
                    return [
                        JSONResponse(
                            {"error": f"Start time must be before end time ({day}: {w.get('start')} >= {w.get('end')})"},
                            status_code=HTTPStatus.BAD_REQUEST,
                        )
                    ]

        rec_err = _validate_recurrence_payload(body)
        if rec_err:
            return [JSONResponse({"error": rec_err}, status_code=HTTPStatus.BAD_REQUEST)]

        rule = ProviderAvailabilityRule.from_dict(body)

        # Check for overlapping availability
        overlap_msg = check_rule_overlap(rule, exclude_rule_id=rule.id if body.get("id") else "")
        if overlap_msg:
            return [
                JSONResponse(
                    {"error": overlap_msg},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        save_rule(rule)

        sync_effects = sync_provider_availability(provider_id)
        if rule.is_active and rule.booking_interval.min_lead_hours > 0:
            sync_effects.extend(build_lead_time_block_effects(rule))

        return [
            *sync_effects,
            JSONResponse(
                {"message": "Rule saved", "rule": rule.to_dict()},
                status_code=HTTPStatus.CREATED,
            ),
        ]

    @api.put("/rules")
    def update_rule_group(self) -> list[Response | Effect]:
        """Update a rule, optionally applying to all group members."""
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        body = self.request.json()
        apply_to_group = body.pop("apply_to_group", False)
        rule_id = body.get("id", "")
        provider_id = body.get("provider_id", "")

        if not rule_id or not provider_id:
            return [
                JSONResponse(
                    {"error": "id and provider_id are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        body["updated_at"] = datetime.now(UTC).isoformat()

        # Preserve date_overrides and timezone from existing rule when not in payload
        existing = get_rule_by_id(provider_id, rule_id)
        if existing:
            if "date_overrides" not in body:
                body["date_overrides"] = [o.to_dict() for o in existing.date_overrides]
            if "timezone" not in body or body["timezone"] is None:
                body["timezone"] = existing.timezone

        rec_err = _validate_recurrence_payload(body)
        if rec_err:
            return [JSONResponse({"error": rec_err}, status_code=HTTPStatus.BAD_REQUEST)]

        rule = ProviderAvailabilityRule.from_dict(body)

        # Check for overlapping availability (exclude the rule being edited)
        overlap_msg = check_rule_overlap(rule, exclude_rule_id=rule.id)
        if overlap_msg:
            return [
                JSONResponse(
                    {"error": overlap_msg},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        save_rule(rule)

        updated_count = 1
        # Collect all provider IDs that need re-sync
        providers_to_sync = {rule.provider_id}

        if apply_to_group and rule.group_id:
            group_rules = get_rules_by_group(rule.group_id)
            for gr in group_rules:
                if gr.id == rule.id:
                    continue
                # Apply same schedule/settings to group member
                gr.weekly_schedule = rule.weekly_schedule
                gr.buffer_minutes = rule.buffer_minutes
                gr.booking_interval = rule.booking_interval
                gr.is_active = rule.is_active
                gr.effective_start = rule.effective_start
                gr.effective_end = rule.effective_end
                gr.location_ids = rule.location_ids
                gr.visit_types = rule.visit_types
                gr.reason = rule.reason
                gr.updated_at = rule.updated_at
                gr.recurrence_frequency = rule.recurrence_frequency
                gr.recurrence_interval = rule.recurrence_interval
                gr.time_windows = list(rule.time_windows)
                save_rule(gr)
                providers_to_sync.add(gr.provider_id)
                updated_count += 1

        all_effects: list[Effect] = []
        for pid in providers_to_sync:
            all_effects.extend(sync_provider_availability(pid))
            has_lead_time = False
            for r in get_rules_for_provider(pid):
                if r.is_active and r.booking_interval.min_lead_hours > 0:
                    all_effects.extend(build_lead_time_block_effects(r))
                    has_lead_time = True
            if not has_lead_time:
                from provider_availability.engine.admin_calendar import get_admin_calendars
                from canvas_sdk.v1.data.calendar import Event as EventModel
                from canvas_sdk.effects.calendar import Event as EventEffect
                for cal in get_admin_calendars(pid):
                    for evt in EventModel.objects.filter(
                        calendar__id=cal.id, title="Lead Time", is_cancelled=False
                    ):
                        all_effects.append(EventEffect(event_id=str(evt.id)).delete())

        return [
            *all_effects,
            JSONResponse(
                {"message": f"Updated {updated_count} rule(s)", "rule": rule.to_dict()},
            ),
        ]

    @api.delete("/rules/<provider_id>/<rule_id>")
    def delete_rule(self) -> list[Response | Effect]:
        """Delete a specific rule by provider ID and rule UUID."""
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        provider_id = self.request.path_params["provider_id"]
        rule_id = self.request.path_params["rule_id"]

        delete_rule_by_id(provider_id, rule_id)
        event_effects = sync_provider_availability(provider_id)

        # Refresh lead time blocks for remaining rules, or clean up orphans
        remaining = get_rules_for_provider(provider_id)
        has_lead_time = False
        for r in remaining:
            if r.is_active and r.booking_interval.min_lead_hours > 0:
                event_effects.extend(build_lead_time_block_effects(r))
                has_lead_time = True
        if not has_lead_time:
            from provider_availability.engine.admin_calendar import get_admin_calendars
            from canvas_sdk.v1.data.calendar import Event as EventModel
            from canvas_sdk.effects.calendar import Event as EventEffect
            for cal in get_admin_calendars(provider_id):
                for evt in EventModel.objects.filter(
                    calendar__id=cal.id, title="Lead Time", is_cancelled=False
                ):
                    event_effects.append(EventEffect(event_id=str(evt.id)).delete())

        return [
            *event_effects,
            JSONResponse(
                {
                    "message": "Rule deleted",
                    "provider_id": provider_id,
                    "rule_id": rule_id,
                }
            ),
        ]

    @api.delete("/rules/<provider_id>")
    def delete_provider_rules(self) -> list[Response | Effect]:
        """Delete all rules for a provider."""
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        provider_id = self.request.path_params["provider_id"]

        event_effects = build_delete_effects(provider_id)

        count = delete_rules_for_provider(provider_id)

        return [
            *event_effects,
            JSONResponse(
                {
                    "message": f"Deleted {count} rules for provider {provider_id}",
                    "deleted_count": count,
                }
            ),
        ]

    # ── Date Override CRUD ─────────────────────────────────────────────

    @api.get("/rules/<provider_id>/<rule_id>/overrides")
    def list_overrides(self) -> list[Response | Effect]:
        """List date overrides for a rule."""
        provider_id = self.request.path_params["provider_id"]
        rule_id = self.request.path_params["rule_id"]
        rule = get_rule_by_id(provider_id, rule_id)
        if not rule:
            return [JSONResponse({"error": "Rule not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse({"overrides": [o.to_dict() for o in rule.date_overrides]})]

    @api.post("/rules/<provider_id>/<rule_id>/overrides")
    def add_override(self) -> list[Response | Effect]:
        """Add or replace a date override on a rule."""
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        provider_id = self.request.path_params["provider_id"]
        rule_id = self.request.path_params["rule_id"]
        rule = get_rule_by_id(provider_id, rule_id)
        if not rule:
            return [JSONResponse({"error": "Rule not found"}, status_code=HTTPStatus.NOT_FOUND)]
        body = self.request.json()
        # Validate time windows
        windows = body.get("time_windows", [])
        if not windows:
            return [JSONResponse(
                {"error": "At least one time window is required"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        for w in windows:
            if w.get("start", "") >= w.get("end", ""):
                return [JSONResponse(
                    {"error": "Invalid time window: start must be before end"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )]
        override = DateOverride.from_dict(body)
        # Validate override date falls on a scheduled weekday
        day_names = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        weekday_name = day_names[override.date.weekday()]
        if weekday_name not in rule.weekly_schedule:
            return [JSONResponse(
                {"error": f"No hours scheduled on {weekday_name.title()}s — override not applicable"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        # Replace existing override for the same date
        rule.date_overrides = [o for o in rule.date_overrides if o.date != override.date]
        rule.date_overrides.append(override)
        save_rule(rule)
        effects = sync_provider_availability(provider_id)
        # Refresh lead time blocks (they now respect override windows)
        for r in get_rules_for_provider(provider_id):
            if r.is_active and r.booking_interval.min_lead_hours > 0:
                effects.extend(build_lead_time_block_effects(r))
        # Re-sync recurring blocks so they skip override dates
        for rb in get_all_recurring_blocks():
            if rb.provider_id == provider_id and rb.is_active:
                effects.extend(build_recurring_block_sync_effects(rb))
        return [*effects, JSONResponse({"message": "Override saved"})]

    @api.delete("/rules/<provider_id>/<rule_id>/overrides/<override_date>")
    def remove_override(self) -> list[Response | Effect]:
        """Remove a date override from a rule."""
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        provider_id = self.request.path_params["provider_id"]
        rule_id = self.request.path_params["rule_id"]
        rule = get_rule_by_id(provider_id, rule_id)
        if not rule:
            return [JSONResponse({"error": "Rule not found"}, status_code=HTTPStatus.NOT_FOUND)]
        override_date = date.fromisoformat(self.request.path_params["override_date"])
        rule.date_overrides = [o for o in rule.date_overrides if o.date != override_date]
        save_rule(rule)
        effects = sync_provider_availability(provider_id)
        # Refresh lead time blocks (override removed, revert to weekly schedule)
        for r in get_rules_for_provider(provider_id):
            if r.is_active and r.booking_interval.min_lead_hours > 0:
                effects.extend(build_lead_time_block_effects(r))
        # Re-sync recurring blocks so they restore events for removed override date
        for rb in get_all_recurring_blocks():
            if rb.provider_id == provider_id and rb.is_active:
                effects.extend(build_recurring_block_sync_effects(rb))
        return [*effects, JSONResponse({"message": "Override removed"})]

    # ── Admin Block CRUD ───────────────────────────────────────────────

    @api.get("/blocks/<provider_id>")
    def list_blocks(self) -> list[Response | Effect]:
        """List admin blocks for a provider."""
        provider_id = self.request.path_params["provider_id"]
        blocks = get_blocks_for_provider(provider_id)
        return [
            JSONResponse(
                {
                    "blocks": [b.to_dict() for b in blocks],
                    "count": len(blocks),
                    "provider_id": provider_id,
                }
            )
        ]

    @api.post("/blocks")
    def create_block(self) -> list[Response | Effect]:
        """Create one or more admin blocks.

        Three accepted payload shapes:
        - Single timed block:  { provider_id, start, end, ... }
        - Single all-day block: { provider_id, dates: ["YYYY-MM-DD"], all_day: true, ... }
        - Multi-date all-day batch: { provider_id, dates: [...], all_day: true, ... }
          → creates one AdminBlock per date, sharing a fresh group_id.
        """
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        body = self.request.json()

        provider_id = body.get("provider_id", "")
        if not provider_id:
            return [
                JSONResponse(
                    {"error": "provider_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        all_day = bool(body.get("all_day", False))
        dates_payload = body.get("dates") or []
        reason = body.get("reason", "")
        location_ids = body.get("location_ids", [])
        existing_group_id = body.get("group_id")

        # Multi-date / all-day path
        if dates_payload:
            try:
                parsed_dates = sorted({date.fromisoformat(d) for d in dates_payload})
            except (TypeError, ValueError):
                return [
                    JSONResponse(
                        {"error": "dates must be a list of YYYY-MM-DD strings"},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]
            if not all_day:
                # Per-date timed block requires start/end times
                start_str = body.get("start", "")
                end_str = body.get("end", "")
                if not start_str or not end_str:
                    return [
                        JSONResponse(
                            {"error": "start and end are required when all_day=false"},
                            status_code=HTTPStatus.BAD_REQUEST,
                        )
                    ]

            # Use a shared group_id when fanning out to multiple dates so the
            # frontend can manage them as a unit.
            group_id = existing_group_id
            if len(parsed_dates) > 1 and not group_id:
                import uuid as _uuid
                group_id = str(_uuid.uuid4())

            created_blocks: list[AdminBlock] = []
            event_effects: list[Effect] = []
            for d in parsed_dates:
                if all_day:
                    start_dt = datetime.combine(d, datetime.min.time())
                    end_dt = datetime.combine(d + timedelta(days=1), datetime.min.time())
                else:
                    # parse start/end as time-of-day applied to this date
                    start_dt = datetime.fromisoformat(f"{d.isoformat()}T{body['start'][-8:] if 'T' in body['start'] else body['start']}")
                    end_dt = datetime.fromisoformat(f"{d.isoformat()}T{body['end'][-8:] if 'T' in body['end'] else body['end']}")
                if start_dt >= end_dt:
                    return [
                        JSONResponse(
                            {"error": f"Start must be before end for date {d.isoformat()}"},
                            status_code=HTTPStatus.BAD_REQUEST,
                        )
                    ]
                block = AdminBlock(
                    provider_id=provider_id,
                    start=start_dt,
                    end=end_dt,
                    reason=reason,
                    location_ids=location_ids,
                    group_id=group_id,
                    all_day=all_day,
                )
                save_block(block)
                created_blocks.append(block)
                event_effects.extend(build_block_event_effects(block))

            return [
                *event_effects,
                JSONResponse(
                    {
                        "message": f"Created {len(created_blocks)} block(s)",
                        "blocks": [b.to_dict() for b in created_blocks],
                        "group_id": group_id,
                    },
                    status_code=HTTPStatus.CREATED,
                ),
            ]

        # Legacy single-block path
        start_str = body.get("start", "")
        end_str = body.get("end", "")

        if not start_str or not end_str:
            return [
                JSONResponse(
                    {"error": "provider_id, start, and end are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)

        if start_dt >= end_dt:
            return [
                JSONResponse(
                    {"error": "Start time must be before end time"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        block = AdminBlock(
            provider_id=provider_id,
            start=start_dt,
            end=end_dt,
            reason=reason,
            location_ids=location_ids,
            group_id=existing_group_id,
            all_day=all_day,
        )
        save_block(block)

        event_effects = []

        # If converting from a recurring block, delete old events BEFORE creating
        # the new single event — avoids same-time collision on the calendar.
        replace_rb_id = body.get("replace_recurring_block_id")
        if replace_rb_id:
            old_rb = get_recurring_block_by_id(provider_id, replace_rb_id)
            if old_rb:
                event_effects.extend(build_delete_recurring_block_effects(provider_id, old_rb))
            delete_recurring_block(provider_id, replace_rb_id)

        event_effects.extend(build_block_event_effects(block))

        return [
            *event_effects,
            JSONResponse(
                {"message": "Block created", "block": block.to_dict()},
                status_code=HTTPStatus.CREATED,
            ),
        ]

    @api.put("/blocks")
    def update_block(self) -> list[Response | Effect]:
        """Update an existing admin block."""
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        body = self.request.json()
        block_id = body.get("id", "")
        provider_id = body.get("provider_id", "")
        start_str = body.get("start", "")
        end_str = body.get("end", "")

        if not block_id or not provider_id or not start_str or not end_str:
            return [
                JSONResponse(
                    {"error": "id, provider_id, start, and end are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)

        if start_dt >= end_dt:
            return [
                JSONResponse(
                    {"error": "Start time must be before end time"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        # Delete old calendar event
        old_block = get_block_by_id(provider_id, block_id)
        delete_effects: list[Effect] = []
        if old_block:
            delete_effects = build_delete_block_effects(provider_id, old_block)

        block = AdminBlock(
            id=block_id,
            provider_id=provider_id,
            start=start_dt,
            end=end_dt,
            reason=body.get("reason", ""),
            location_ids=body.get("location_ids", []),
            group_id=body.get("group_id"),
            all_day=bool(body.get("all_day", False)),
        )
        save_block(block)

        create_effects = build_block_event_effects(block)

        all_effects = delete_effects + create_effects

        updated_count = 1
        apply_to_group = body.get("apply_to_group", False)
        if apply_to_group and block.group_id:
            group_blocks = get_blocks_by_group(block.group_id)
            for gb in group_blocks:
                if gb.id == block.id:
                    continue
                old_effects = build_delete_block_effects(gb.provider_id, gb)
                all_effects.extend(old_effects)
                gb.start = block.start
                gb.end = block.end
                gb.reason = block.reason
                save_block(gb)
                all_effects.extend(build_block_event_effects(gb))
                updated_count += 1

        return [
            *all_effects,
            JSONResponse(
                {"message": f"Updated {updated_count} block(s)", "block": block.to_dict()},
            ),
        ]

    @api.delete("/blocks/<provider_id>/<block_id>")
    def delete_block_endpoint(self) -> list[Response | Effect]:
        """Delete a specific admin block.

        Pass ?apply_to_group=true to also delete every other AdminBlock that
        shares the same group_id (multi-date holiday batches).
        """
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        provider_id = self.request.path_params["provider_id"]
        block_id = self.request.path_params["block_id"]

        query = getattr(self.request, "query_params", {}) or {}
        apply_to_group_raw = query.get("apply_to_group", "")
        apply_to_group = str(apply_to_group_raw).lower() in ("true", "1", "yes")

        # Look up the block before deleting so we can target the right calendar event
        blocks = get_blocks_for_provider(provider_id)
        target_block = next((b for b in blocks if b.id == block_id), None)

        event_effects = build_delete_block_effects(provider_id, target_block)
        delete_block(provider_id, block_id)
        deleted_count = 1

        if apply_to_group and target_block and target_block.group_id:
            group_blocks = get_blocks_by_group(target_block.group_id)
            for gb in group_blocks:
                if gb.id == block_id:
                    continue
                event_effects.extend(build_delete_block_effects(gb.provider_id, gb))
                delete_block(gb.provider_id, gb.id)
                deleted_count += 1

        message = "Block deleted" if deleted_count == 1 else f"Deleted {deleted_count} block(s)"
        return [
            *event_effects,
            JSONResponse(
                {
                    "message": message,
                    "provider_id": provider_id,
                    "block_id": block_id,
                    "deleted_count": deleted_count,
                }
            ),
        ]

    # ── Recurring Block CRUD ──────────────────────────────────────────

    @api.get("/recurring-blocks/<provider_id>")
    def list_recurring_blocks(self) -> list[Response | Effect]:
        """List recurring blocks for a provider."""
        provider_id = self.request.path_params["provider_id"]
        blocks = get_recurring_blocks_for_provider(provider_id)
        return [
            JSONResponse(
                {
                    "blocks": [b.to_dict() for b in blocks],
                    "count": len(blocks),
                    "provider_id": provider_id,
                }
            )
        ]

    @api.post("/recurring-blocks")
    def create_recurring_block(self) -> list[Response | Effect]:
        """Create a new recurring weekly block."""
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        body = self.request.json()

        provider_id = body.get("provider_id", "")
        weekly_schedule = body.get("weekly_schedule", {})
        is_daily = body.get("recurrence_frequency", "weekly") == "daily"

        if not provider_id:
            return [
                JSONResponse(
                    {"error": "provider_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if not is_daily and not weekly_schedule:
            return [
                JSONResponse(
                    {"error": "weekly_schedule is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        # Validate start < end for each time window
        for day, windows in weekly_schedule.items():
            for w in windows:
                if w.get("start", "") >= w.get("end", ""):
                    return [
                        JSONResponse(
                            {"error": f"Start time must be before end time ({day}: {w.get('start')} >= {w.get('end')})"},
                            status_code=HTTPStatus.BAD_REQUEST,
                        )
                    ]

        rec_err = _validate_recurrence_payload(body)
        if rec_err:
            return [JSONResponse({"error": rec_err}, status_code=HTTPStatus.BAD_REQUEST)]

        block = RecurringBlock.from_dict(body)
        save_recurring_block(block)

        event_effects: list[Effect] = []

        # If converting from a single block, delete old events BEFORE creating
        # new recurring ones — otherwise the old event collides with the new
        # recurring event on the same day/time and Canvas cancels that occurrence.
        replace_b_id = body.get("replace_block_id")
        if replace_b_id:
            old_block = get_block_by_id(provider_id, replace_b_id)
            if old_block:
                event_effects.extend(build_delete_block_effects(provider_id, old_block))
            delete_block(provider_id, replace_b_id)

        event_effects.extend(build_recurring_block_sync_effects(block))

        return [
            *event_effects,
            JSONResponse(
                {"message": "Recurring block created", "block": block.to_dict()},
                status_code=HTTPStatus.CREATED,
            ),
        ]

    @api.put("/recurring-blocks")
    def update_recurring_block(self) -> list[Response | Effect]:
        """Update an existing recurring block."""
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        body = self.request.json()
        block_id = body.get("id", "")
        provider_id = body.get("provider_id", "")

        if not block_id or not provider_id:
            return [
                JSONResponse(
                    {"error": "id and provider_id are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        weekly_schedule = body.get("weekly_schedule", {})
        is_daily = body.get("recurrence_frequency", "weekly") == "daily"
        if not is_daily and not weekly_schedule:
            return [
                JSONResponse(
                    {"error": "weekly_schedule is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        rec_err = _validate_recurrence_payload(body)
        if rec_err:
            return [JSONResponse({"error": rec_err}, status_code=HTTPStatus.BAD_REQUEST)]

        block = RecurringBlock.from_dict(body)
        save_recurring_block(block)
        all_effects: list[Effect] = list(build_recurring_block_sync_effects(block))

        updated_count = 1
        apply_to_group = body.get("apply_to_group", False)
        if apply_to_group and block.group_id:
            group_blocks = get_recurring_blocks_by_group(block.group_id)
            for gb in group_blocks:
                if gb.id == block.id:
                    continue
                gb.weekly_schedule = block.weekly_schedule
                gb.reason = block.reason
                gb.effective_start = block.effective_start
                gb.effective_end = block.effective_end
                gb.is_active = block.is_active
                gb.recurrence_frequency = block.recurrence_frequency
                gb.recurrence_interval = block.recurrence_interval
                gb.time_windows = list(block.time_windows)
                save_recurring_block(gb)
                all_effects.extend(build_recurring_block_sync_effects(gb))
                updated_count += 1

        return [
            *all_effects,
            JSONResponse(
                {"message": f"Updated {updated_count} recurring block(s)", "block": block.to_dict()},
            ),
        ]

    @api.delete("/recurring-blocks/<provider_id>/<block_id>")
    def delete_recurring_block_endpoint(self) -> list[Response | Effect]:
        """Delete a specific recurring block."""
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        provider_id = self.request.path_params["provider_id"]
        block_id = self.request.path_params["block_id"]

        # Try to look up the block for stored event ID deletion
        existing_block = get_recurring_block_by_id(provider_id, block_id)
        event_effects = build_delete_recurring_block_effects(provider_id, existing_block)
        delete_recurring_block(provider_id, block_id)

        return [
            *event_effects,
            JSONResponse(
                {"message": "Recurring block deleted", "provider_id": provider_id, "block_id": block_id}
            ),
        ]

    # ── Timezone endpoints ────────────────────────────────────────────

    @api.get("/timezone")
    def get_timezone(self) -> list[Response | Effect]:
        """Return the current practice timezone and available options."""
        return [
            JSONResponse({
                "timezone": get_practice_timezone(),
                "available": COMMON_TIMEZONES,
            })
        ]

    @api.put("/timezone")
    def set_timezone(self) -> list[Response | Effect]:
        """Set the practice timezone and re-sync all rules and recurring blocks."""
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
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
        log.info("set_timezone: changed to %s", tz_name)

        return [
            JSONResponse({
                "message": f"Timezone set to {tz_name}",
                "timezone": tz_name,
            }),
        ]

    # ── Per-provider timezone ─────────────────────────────────────────

    @api.get("/provider-timezone")
    def get_provider_tz(self) -> list[Response | Effect]:
        """Return a provider's effective timezone."""
        params = self.request.query_params
        provider_id = params.get("provider_id", "")
        if not provider_id:
            return [JSONResponse({"error": "provider_id is required"}, status_code=HTTPStatus.BAD_REQUEST)]
        explicit = get_provider_timezone(provider_id)
        return [JSONResponse({
            "provider_id": provider_id,
            "timezone": explicit or get_practice_timezone(),
            "explicit": explicit is not None,
        })]

    @api.get("/provider-timezones/all")
    def get_all_provider_tzs(self) -> list[Response | Effect]:
        """Return all explicitly-set provider timezones."""
        tzs = get_all_provider_timezones()
        return [JSONResponse({"timezones": tzs})]

    @api.put("/provider-timezone")
    def set_provider_tz(self) -> list[Response | Effect]:
        """Set a provider's timezone."""
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        body = self.request.json()
        provider_id = body.get("provider_id", "")
        tz_name = body.get("timezone", "")
        if not provider_id:
            return [JSONResponse({"error": "provider_id is required"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not tz_name or tz_name not in COMMON_TIMEZONES:
            return [JSONResponse(
                {"error": f"Invalid timezone. Choose from: {', '.join(COMMON_TIMEZONES)}"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        set_provider_timezone(provider_id, tz_name)
        # Re-sync this provider's calendar events with the new timezone
        effects: list[Effect] = list(sync_provider_availability(provider_id))
        for rb in get_all_recurring_blocks():
            if rb.provider_id == provider_id:
                effects.extend(build_recurring_block_sync_effects(rb))
        log.info("set_provider_tz: provider %s → %s, %d sync effects", provider_id, tz_name, len(effects))
        return [*effects, JSONResponse({
            "message": f"Provider timezone set to {tz_name}",
            "provider_id": provider_id,
            "timezone": tz_name,
        })]

    @api.put("/provider-timezones/bulk")
    def set_provider_tz_bulk(self) -> list[Response | Effect]:
        """Set the same timezone for multiple providers at once."""
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        body = self.request.json()
        provider_ids = body.get("provider_ids", [])
        tz_name = body.get("timezone", "")
        if not provider_ids:
            return [JSONResponse({"error": "provider_ids is required"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not tz_name or tz_name not in COMMON_TIMEZONES:
            return [JSONResponse(
                {"error": f"Invalid timezone. Choose from: {', '.join(COMMON_TIMEZONES)}"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        effects: list[Effect] = []
        for pid in provider_ids:
            set_provider_timezone(pid, tz_name)
            effects.extend(sync_provider_availability(pid))
        for rb in get_all_recurring_blocks():
            if rb.provider_id in provider_ids:
                effects.extend(build_recurring_block_sync_effects(rb))
        log.info("set_provider_tz_bulk: %d providers → %s, %d sync effects", len(provider_ids), tz_name, len(effects))
        return [*effects, JSONResponse({
            "message": f"Timezone set to {tz_name} for {len(provider_ids)} providers",
            "timezone": tz_name,
            "count": len(provider_ids),
        })]

    # ── Admin UI serving ──────────────────────────────────────────────

    @api.get("/availability-admin")
    def get_admin_ui(self) -> list[Response | Effect]:
        """Serve the main admin UI page with pre-rendered data."""
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return [HTMLResponse(ACCESS_DENIED_HTML, status_code=HTTPStatus.FORBIDDEN)]

        # Pre-render all initial data so the page doesn't need fetch()
        preloaded = self._build_preloaded_data()
        html = render_admin_page(preloaded)
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    def _build_preloaded_data(self) -> dict:
        """Gather all data needed for the initial page render."""
        try:
            providers = get_active_providers()
        except Exception:
            providers = []
        try:
            locations = get_active_locations()
        except Exception:
            locations = []
        try:
            visit_types = get_scheduleable_visit_types()
        except Exception:
            visit_types = []

        tz = get_practice_timezone()

        # Build overview (same logic as get_overview endpoint)
        rules = get_all_rules()
        blocks = get_all_blocks()
        recurring_blocks = get_all_recurring_blocks()

        provider_ids = set()
        for r in rules:
            provider_ids.add(r.provider_id)
        for b in blocks:
            provider_ids.add(b.provider_id)
        for rb in recurring_blocks:
            provider_ids.add(rb.provider_id)

        displays = get_provider_displays(list(provider_ids)) if provider_ids else {}

        loc_map = {loc["id"]: loc["name"] for loc in locations}
        vt_map = {vt["id"]: vt["name"] for vt in visit_types}

        provider_tzs = get_all_provider_timezones()
        overview: dict[str, dict] = {}
        for pid in provider_ids:
            info = displays.get(pid, {})
            overview[pid] = {
                "provider_id": pid,
                "provider_name": info.get("name", ""),
                "provider_timezone": provider_tzs.get(pid) or tz,
                "provider_timezone_explicit": pid in provider_tzs,
                "rules": [],
                "blocks": [],
                "recurring_blocks": [],
            }

        for r in rules:
            d = r.to_dict()
            d["location_names"] = [loc_map.get(lid, lid) for lid in r.location_ids]
            d["visit_type_names"] = [vt_map.get(vt, vt) for vt in r.visit_types]
            overview[r.provider_id]["rules"].append(d)

        for b in blocks:
            overview[b.provider_id]["blocks"].append(b.to_dict())

        for rb in recurring_blocks:
            overview[rb.provider_id]["recurring_blocks"].append(rb.to_dict())

        sorted_overview = sorted(
            overview.values(),
            key=lambda p: p["provider_name"].lower() if p["provider_name"] else "zzz",
        )

        return {
            "providers": {"providers": providers, "count": len(providers)},
            "locations": {"locations": locations, "count": len(locations)},
            "visit_types": {"visit_types": visit_types, "count": len(visit_types)},
            "timezone": {"timezone": tz, "available": COMMON_TIMEZONES},
            "overview": {"providers": sorted_overview},
        }

    @api.post("/form-action")
    def handle_form_action(self) -> list[Response | Effect]:
        """Handle form-encoded write operations when fetch() is blocked by CSP.

        Accepts form fields: _method, _path, _body (JSON string).
        Dispatches to write handler, then returns admin page with fresh data.
        """
        form = self.request.form_data()
        method = form.get("_method").value.upper() if form.get("_method") else "POST"
        path = form.get("_path").value if form.get("_path") else ""
        body_str = form.get("_body").value if form.get("_body") else "{}"

        try:
            body = json.loads(body_str)
        except Exception:
            body = {}

        log.info("form-action: method=%s path=%s", method, path)

        write_effects = self._dispatch_write(method, path, body)

        # Return the admin page with fresh pre-rendered data
        preloaded = self._build_preloaded_data()

        # Extract flash message from write result
        flash = ""
        for fx in write_effects:
            if hasattr(fx, "content") and hasattr(fx, "status_code"):
                try:
                    msg_data = json.loads(getattr(fx, "content", b"{}"))
                    if "message" in msg_data:
                        flash = msg_data["message"]
                    elif "error" in msg_data:
                        flash = "Error: " + msg_data["error"]
                except Exception:
                    pass
        if flash:
            preloaded["flash"] = flash

        html = render_admin_page(preloaded)
        non_response_effects = [fx for fx in write_effects if not hasattr(fx, "status_code")]
        return [*non_response_effects, HTMLResponse(html, status_code=HTTPStatus.OK)]

    def _dispatch_write(self, method: str, path: str, body: dict) -> list[Response | Effect]:
        """Route a form-submitted write to the correct handler logic."""
        try:
            return self._do_dispatch(method, path, body)
        except Exception:
            log.exception("form-action dispatch error: %s %s", method, path)
            return [JSONResponse({"error": "Server error"}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)]

    def _do_dispatch(self, method: str, path: str, body: dict) -> list[Response | Effect]:
        """Internal dispatcher for form-action writes."""
        p = path.lstrip("/")

        if method == "POST" and p == "rules":
            return self._form_create_rule(body)
        if method == "PUT" and p == "rules":
            return self._form_update_rule(body)
        # Override routes: rules/<pid>/<rid>/overrides[/<date>]
        if p.startswith("rules/") and "/overrides" in p:
            parts = p.split("/")
            if method == "POST" and len(parts) == 4 and parts[3] == "overrides":
                return self._form_add_override(parts[1], parts[2], body)
            if method == "DELETE" and len(parts) == 5 and parts[3] == "overrides":
                return self._form_remove_override(parts[1], parts[2], parts[4])
        if method == "DELETE" and p.startswith("rules/"):
            parts = p.split("/")
            if len(parts) == 3:
                return self._form_delete_rule(parts[1], parts[2])
            if len(parts) == 2:
                return self._form_delete_provider_rules(parts[1])
        if method == "POST" and p == "blocks":
            return self._form_create_block(body)
        if method == "PUT" and p == "blocks":
            return self._form_update_block(body)
        if method == "DELETE" and p.startswith("blocks/"):
            parts = p.split("/")
            if len(parts) == 3:
                return self._form_delete_block(parts[1], parts[2])
        if method == "POST" and p == "recurring-blocks":
            return self._form_create_recurring_block(body)
        if method == "PUT" and p == "recurring-blocks":
            return self._form_update_recurring_block(body)
        if method == "DELETE" and p.startswith("recurring-blocks/"):
            parts = p.split("/")
            if len(parts) == 3:
                return self._form_delete_recurring_block(parts[1], parts[2])
        if method == "PUT" and p == "timezone":
            return self._form_set_timezone(body)
        if method == "PUT" and p == "provider-timezone":
            return self._form_set_provider_timezone(body)
        if method == "PUT" and p == "provider-timezones/bulk":
            return self._form_set_provider_tz_bulk(body)
        return [JSONResponse({"error": f"Unknown: {method} /{p}"}, status_code=HTTPStatus.BAD_REQUEST)]

    def _form_create_rule(self, body: dict) -> list[Response | Effect]:
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        provider_id = body.get("provider_id", "")
        if not provider_id:
            return [JSONResponse({"error": "provider_id required"}, status_code=HTTPStatus.BAD_REQUEST)]
        body["updated_at"] = datetime.now(UTC).isoformat()
        if "location_ids" not in body and "location_id" in body:
            body["location_ids"] = [body.pop("location_id")] if body.get("location_id") else []
        if "visit_types" not in body and "visit_type" in body:
            body["visit_types"] = [body.pop("visit_type")] if body.get("visit_type") else []
        for day, windows in body.get("weekly_schedule", {}).items():
            for w in windows:
                if w.get("start", "") >= w.get("end", ""):
                    return [JSONResponse({"error": f"Invalid time window ({day})"}, status_code=HTTPStatus.BAD_REQUEST)]
        rule = ProviderAvailabilityRule.from_dict(body)
        overlap_msg = check_rule_overlap(rule, exclude_rule_id=rule.id if body.get("id") else "")
        if overlap_msg:
            return [JSONResponse({"error": overlap_msg}, status_code=HTTPStatus.BAD_REQUEST)]
        save_rule(rule)
        effects = sync_provider_availability(provider_id)
        if rule.is_active and rule.booking_interval.min_lead_hours > 0:
            effects.extend(build_lead_time_block_effects(rule))
        return [*effects, JSONResponse({"message": "Rule saved"})]

    def _form_update_rule(self, body: dict) -> list[Response | Effect]:
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        apply_to_group = body.pop("apply_to_group", False)
        rule_id = body.get("id", "")
        provider_id = body.get("provider_id", "")
        if not rule_id or not provider_id:
            return [JSONResponse({"error": "id and provider_id required"}, status_code=HTTPStatus.BAD_REQUEST)]
        body["updated_at"] = datetime.now(UTC).isoformat()

        # Preserve date_overrides and timezone from existing rule when not in payload
        existing = get_rule_by_id(provider_id, rule_id)
        if existing:
            if "date_overrides" not in body:
                body["date_overrides"] = [o.to_dict() for o in existing.date_overrides]
            if "timezone" not in body or body["timezone"] is None:
                body["timezone"] = existing.timezone

        rule = ProviderAvailabilityRule.from_dict(body)
        overlap_msg = check_rule_overlap(rule, exclude_rule_id=rule.id)
        if overlap_msg:
            return [JSONResponse({"error": overlap_msg}, status_code=HTTPStatus.BAD_REQUEST)]
        save_rule(rule)
        providers_to_sync = {rule.provider_id}
        count = 1
        if apply_to_group and rule.group_id:
            for gr in get_rules_by_group(rule.group_id):
                if gr.id == rule.id:
                    continue
                gr.weekly_schedule = rule.weekly_schedule
                gr.buffer_minutes = rule.buffer_minutes
                gr.booking_interval = rule.booking_interval
                gr.is_active = rule.is_active
                gr.effective_start = rule.effective_start
                gr.effective_end = rule.effective_end
                gr.location_ids = rule.location_ids
                gr.visit_types = rule.visit_types
                gr.reason = rule.reason
                gr.updated_at = rule.updated_at
                save_rule(gr)
                providers_to_sync.add(gr.provider_id)
                count += 1
        effects: list[Effect] = []
        for pid in providers_to_sync:
            effects.extend(sync_provider_availability(pid))
            for r in get_rules_for_provider(pid):
                if r.is_active and r.booking_interval.min_lead_hours > 0:
                    effects.extend(build_lead_time_block_effects(r))
        return [*effects, JSONResponse({"message": f"Updated {count} rule(s)"})]

    def _form_delete_rule(self, provider_id: str, rule_id: str) -> list[Response | Effect]:
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        delete_rule_by_id(provider_id, rule_id)
        # Re-sync availability for remaining rules
        effects = sync_provider_availability(provider_id)
        # Refresh lead time blocks for remaining rules, or clean up if none left
        remaining = get_rules_for_provider(provider_id)
        has_lead_time = False
        for r in remaining:
            if r.is_active and r.booking_interval.min_lead_hours > 0:
                effects.extend(build_lead_time_block_effects(r))
                has_lead_time = True
        if not has_lead_time:
            # Delete orphaned lead time events for this provider
            from provider_availability.engine.admin_calendar import get_admin_calendars
            from canvas_sdk.v1.data.calendar import Event as EventModel
            from canvas_sdk.effects.calendar import Event as EventEffect
            for cal in get_admin_calendars(provider_id):
                for evt in EventModel.objects.filter(
                    calendar__id=cal.id, title="Lead Time", is_cancelled=False
                ):
                    effects.append(EventEffect(event_id=str(evt.id)).delete())
        return [*effects, JSONResponse({"message": "Rule deleted"})]

    def _form_delete_provider_rules(self, provider_id: str) -> list[Response | Effect]:
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        effects = build_delete_effects(provider_id)
        count = delete_rules_for_provider(provider_id)
        return [*effects, JSONResponse({"message": f"Deleted {count} rules"})]

    def _form_add_override(self, provider_id: str, rule_id: str, body: dict) -> list[Response | Effect]:
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        rule = get_rule_by_id(provider_id, rule_id)
        if not rule:
            return [JSONResponse({"error": "Rule not found"}, status_code=HTTPStatus.NOT_FOUND)]
        windows = body.get("time_windows", [])
        if not windows:
            return [JSONResponse(
                {"error": "At least one time window is required"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        for w in windows:
            if w.get("start", "") >= w.get("end", ""):
                return [JSONResponse(
                    {"error": "Invalid time window: start must be before end"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )]
        override = DateOverride.from_dict(body)
        # Validate override date falls on a scheduled weekday
        day_names = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        weekday_name = day_names[override.date.weekday()]
        if weekday_name not in rule.weekly_schedule:
            return [JSONResponse(
                {"error": f"No hours scheduled on {weekday_name.title()}s — override not applicable"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        rule.date_overrides = [o for o in rule.date_overrides if o.date != override.date]
        rule.date_overrides.append(override)
        save_rule(rule)
        return [*sync_provider_availability(provider_id), JSONResponse({"message": "Override saved"})]

    def _form_remove_override(self, provider_id: str, rule_id: str, date_str: str) -> list[Response | Effect]:
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        rule = get_rule_by_id(provider_id, rule_id)
        if not rule:
            return [JSONResponse({"error": "Rule not found"}, status_code=HTTPStatus.NOT_FOUND)]
        override_date = date.fromisoformat(date_str)
        rule.date_overrides = [o for o in rule.date_overrides if o.date != override_date]
        save_rule(rule)
        return [*sync_provider_availability(provider_id), JSONResponse({"message": "Override removed"})]

    def _form_create_block(self, body: dict) -> list[Response | Effect]:
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        provider_id = body.get("provider_id", "")
        start_str = body.get("start", "")
        end_str = body.get("end", "")
        if not provider_id or not start_str or not end_str:
            return [JSONResponse({"error": "provider_id, start, end required"}, status_code=HTTPStatus.BAD_REQUEST)]
        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)
        if start_dt >= end_dt:
            return [JSONResponse({"error": "Start must be before end"}, status_code=HTTPStatus.BAD_REQUEST)]
        block = AdminBlock(
            provider_id=provider_id, start=start_dt, end=end_dt,
            reason=body.get("reason", ""), location_ids=body.get("location_ids", []),
            group_id=body.get("group_id"),
        )
        save_block(block)
        effects: list = []
        replace_rb_id = body.get("replace_recurring_block_id")
        if replace_rb_id:
            old_rb = get_recurring_block_by_id(provider_id, replace_rb_id)
            if old_rb:
                effects.extend(build_delete_recurring_block_effects(provider_id, old_rb))
            delete_recurring_block(provider_id, replace_rb_id)
        effects.extend(build_block_event_effects(block))
        return [*effects, JSONResponse({"message": "Block created"})]

    def _form_update_block(self, body: dict) -> list[Response | Effect]:
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        block_id = body.get("id", "")
        provider_id = body.get("provider_id", "")
        start_str = body.get("start", "")
        end_str = body.get("end", "")
        if not block_id or not provider_id or not start_str or not end_str:
            return [JSONResponse({"error": "id, provider_id, start, end required"}, status_code=HTTPStatus.BAD_REQUEST)]
        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)
        if start_dt >= end_dt:
            return [JSONResponse({"error": "Start must be before end"}, status_code=HTTPStatus.BAD_REQUEST)]
        old_block = get_block_by_id(provider_id, block_id)
        del_fx: list[Effect] = build_delete_block_effects(provider_id, old_block) if old_block else []
        block = AdminBlock(
            id=block_id, provider_id=provider_id, start=start_dt, end=end_dt,
            reason=body.get("reason", ""), location_ids=body.get("location_ids", []),
            group_id=body.get("group_id"),
        )
        save_block(block)
        all_fx = del_fx + list(build_block_event_effects(block))
        count = 1
        if body.get("apply_to_group") and block.group_id:
            for gb in get_blocks_by_group(block.group_id):
                if gb.id == block.id:
                    continue
                all_fx.extend(build_delete_block_effects(gb.provider_id, gb))
                gb.start = block.start
                gb.end = block.end
                gb.reason = block.reason
                save_block(gb)
                all_fx.extend(build_block_event_effects(gb))
                count += 1
        return [*all_fx, JSONResponse({"message": f"Updated {count} block(s)"})]

    def _form_delete_block(self, provider_id: str, block_id: str) -> list[Response | Effect]:
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        blocks = get_blocks_for_provider(provider_id)
        target = next((b for b in blocks if b.id == block_id), None)
        effects = build_delete_block_effects(provider_id, target)
        delete_block(provider_id, block_id)
        return [*effects, JSONResponse({"message": "Block deleted"})]

    def _form_create_recurring_block(self, body: dict) -> list[Response | Effect]:
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        provider_id = body.get("provider_id", "")
        weekly_schedule = body.get("weekly_schedule", {})
        if not provider_id:
            return [JSONResponse({"error": "provider_id required"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not weekly_schedule:
            return [JSONResponse({"error": "weekly_schedule required"}, status_code=HTTPStatus.BAD_REQUEST)]
        for day, windows in weekly_schedule.items():
            for w in windows:
                if w.get("start", "") >= w.get("end", ""):
                    return [JSONResponse({"error": f"Invalid time ({day})"}, status_code=HTTPStatus.BAD_REQUEST)]
        block = RecurringBlock.from_dict(body)
        save_recurring_block(block)
        effects: list = []
        replace_b_id = body.get("replace_block_id")
        if replace_b_id:
            old_block = get_block_by_id(provider_id, replace_b_id)
            if old_block:
                effects.extend(build_delete_block_effects(provider_id, old_block))
            delete_block(provider_id, replace_b_id)
        effects.extend(build_recurring_block_sync_effects(block))
        return [*effects, JSONResponse({"message": "Recurring block created"})]

    def _form_update_recurring_block(self, body: dict) -> list[Response | Effect]:
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        block_id = body.get("id", "")
        provider_id = body.get("provider_id", "")
        if not block_id or not provider_id:
            return [JSONResponse({"error": "id and provider_id required"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not body.get("weekly_schedule"):
            return [JSONResponse({"error": "weekly_schedule required"}, status_code=HTTPStatus.BAD_REQUEST)]
        block = RecurringBlock.from_dict(body)
        save_recurring_block(block)
        all_fx: list[Effect] = list(build_recurring_block_sync_effects(block))
        count = 1
        if body.get("apply_to_group") and block.group_id:
            for gb in get_recurring_blocks_by_group(block.group_id):
                if gb.id == block.id:
                    continue
                gb.weekly_schedule = block.weekly_schedule
                gb.reason = block.reason
                gb.effective_start = block.effective_start
                gb.effective_end = block.effective_end
                gb.is_active = block.is_active
                save_recurring_block(gb)
                all_fx.extend(build_recurring_block_sync_effects(gb))
                count += 1
        return [*all_fx, JSONResponse({"message": f"Updated {count} recurring block(s)"})]

    def _form_delete_recurring_block(self, provider_id: str, block_id: str) -> list[Response | Effect]:
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        existing = get_recurring_block_by_id(provider_id, block_id)
        effects = build_delete_recurring_block_effects(provider_id, existing)
        delete_recurring_block(provider_id, block_id)
        return [*effects, JSONResponse({"message": "Recurring block deleted"})]

    def _form_set_timezone(self, body: dict) -> list[Response | Effect]:
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        tz_name = body.get("timezone", "")
        if not tz_name or tz_name not in COMMON_TIMEZONES:
            return [JSONResponse({"error": "Invalid timezone"}, status_code=HTTPStatus.BAD_REQUEST)]
        set_practice_timezone(tz_name)
        all_fx: list[Effect] = []
        synced: set[str] = set()
        for rule in get_all_rules():
            if rule.provider_id not in synced:
                all_fx.extend(sync_provider_availability(rule.provider_id))
                synced.add(rule.provider_id)
        for rb in get_all_recurring_blocks():
            all_fx.extend(build_recurring_block_sync_effects(rb))
        return [*all_fx, JSONResponse({"message": f"Timezone set to {tz_name}"})]

    def _form_set_provider_timezone(self, body: dict) -> list[Response | Effect]:
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        provider_id = body.get("provider_id", "")
        tz_name = body.get("timezone", "")
        if not provider_id:
            return [JSONResponse({"error": "provider_id required"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not tz_name or tz_name not in COMMON_TIMEZONES:
            return [JSONResponse({"error": "Invalid timezone"}, status_code=HTTPStatus.BAD_REQUEST)]
        set_provider_timezone(provider_id, tz_name)
        # Re-sync this provider's calendar events with the new timezone
        all_fx: list[Effect] = list(sync_provider_availability(provider_id))
        for rb in get_all_recurring_blocks():
            if rb.provider_id == provider_id:
                all_fx.extend(build_recurring_block_sync_effects(rb))
        log.info("form_set_provider_tz: provider %s → %s", provider_id, tz_name)
        return [*all_fx, JSONResponse({"message": f"Provider timezone set to {tz_name}"})]

    def _form_set_provider_tz_bulk(self, body: dict) -> list[Response | Effect]:
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied
        provider_ids = body.get("provider_ids", [])
        tz_name = body.get("timezone", "")
        if not provider_ids:
            return [JSONResponse({"error": "provider_ids required"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not tz_name or tz_name not in COMMON_TIMEZONES:
            return [JSONResponse({"error": "Invalid timezone"}, status_code=HTTPStatus.BAD_REQUEST)]
        all_fx: list[Effect] = []
        for pid in provider_ids:
            set_provider_timezone(pid, tz_name)
            all_fx.extend(sync_provider_availability(pid))
        for rb in get_all_recurring_blocks():
            if rb.provider_id in provider_ids:
                all_fx.extend(build_recurring_block_sync_effects(rb))
        log.info("form_set_provider_tz_bulk: %d providers → %s", len(provider_ids), tz_name)
        return [*all_fx, JSONResponse({"message": f"Timezone set to {tz_name} for {len(provider_ids)} providers"})]

    # ── Static assets ────────────────────────────────────────────────

    @api.get("/admin.css")
    def get_admin_css(self) -> list[Response | Effect]:
        """Serve the admin UI stylesheet."""
        return [
            Response(
                render_to_string("static/css/admin.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    @api.get("/admin.js")
    def get_admin_js(self) -> list[Response | Effect]:
        """Serve the admin UI JavaScript."""
        return [
            Response(
                render_to_string("static/js/admin.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    @api.get("/tokens.css")
    def get_tokens_css(self) -> list[Response | Effect]:
        """Serve the Canvas design system tokens."""
        return [
            Response(
                render_to_string("static/tokens.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/typography.css")
    def get_typography_css(self) -> list[Response | Effect]:
        """Serve the Canvas design system typography."""
        return [
            Response(
                render_to_string("static/typography.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/canvas-components.js")
    def get_canvas_components(self) -> list[Response | Effect]:
        """Serve the Canvas design system web components."""
        return [
            Response(
                render_to_string("static/canvas-components.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
            )
        ]
