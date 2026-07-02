"""Staff-session API for bulk availability import from a CSV file.

Three endpoints power the upload UI:
- ``GET  /csv/template``  download a CSV template
- ``POST /csv/validate``  parse + validate an uploaded CSV, resolve names to
  IDs, run overlap checks, and return a preview (per-row errors + records)
- ``POST /csv/commit``    persist the previewed records and sync calendar events

Validation checks each ``staff_key`` against the set of active staff and
resolves location and visit-type names to Canvas IDs, in three batched lookups
(one per entity type) to avoid N+1 queries. Committing reuses the same
``save_*`` + calendar-sync path as the manual admin UI.
"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from logger import log

from provider_availability.api.availability_api import _check_write_access
from provider_availability.engine.csv_import import (
    build_records,
    generate_template_csv,
    parse_csv,
)
from provider_availability.engine.event_sync import (
    build_block_event_effects,
    build_lead_time_block_effects,
    build_recurring_block_sync_effects,
    sync_provider_availability,
)
from provider_availability.engine.lookups import (
    get_active_locations,
    get_active_staff_ids,
    get_scheduleable_visit_types,
)
from provider_availability.engine.models import (
    AdminBlock,
    ProviderAvailabilityRule,
    RecurringBlock,
)
from provider_availability.engine.overlap import check_rule_overlap
from provider_availability.engine.storage import (
    get_rules_for_provider,
    save_block,
    save_recurring_block,
    save_rule,
)


def _build_name_map(entries: list[dict]) -> dict[str, str]:
    """Lowercased name -> id for a list of {id, name} lookup dicts."""
    result: dict[str, str] = {}
    for e in entries:
        name = (e.get("name") or "").strip().lower()
        if name:
            result[name] = e["id"]
    return result


class CSVImportAPI(StaffSessionAuthMixin, SimpleAPI):
    """Bulk availability import endpoints."""

    PREFIX = "/csv"

    @api.get("/template")
    def download_template(self) -> list[Response | Effect]:
        """Return the CSV template as a downloadable file."""
        content = generate_template_csv()
        return [
            Response(
                content.encode("utf-8"),
                status_code=HTTPStatus.OK,
                headers={
                    "Content-Type": "text/csv",
                    "Content-Disposition": 'attachment; filename="availability_template.csv"',
                },
                content_type="text/csv",
            )
        ]

    @api.post("/validate")
    def validate_upload(self) -> list[Response | Effect]:
        """Parse and validate an uploaded CSV, returning a preview of records."""
        form_data = self.request.form_data()
        file_part = form_data.get("file")
        if file_part is None or not file_part.is_file():
            return [
                JSONResponse(
                    {"error": "No CSV file provided. Upload a file with field name 'file'."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        content = file_part.content.decode("utf-8-sig")
        parsed = parse_csv(content)

        valid_staff_ids = get_active_staff_ids()
        location_map = _build_name_map(get_active_locations())
        visit_type_map = _build_name_map(get_scheduleable_visit_types())

        records, resolution_errors = build_records(
            parsed.valid_rows, valid_staff_ids, location_map, visit_type_map
        )

        ok_records: list[dict] = []
        overlap_errors: list[dict] = []
        for rec in records:
            if rec["kind"] == "rule":
                rule = ProviderAvailabilityRule.from_dict(rec)
                conflict = check_rule_overlap(rule)
                if conflict:
                    overlap_errors.append(
                        {"row_number": min(rec["source_rows"]), "errors": [conflict]}
                    )
                    continue
            ok_records.append(rec)

        errors = self._collect_errors(parsed.error_rows, resolution_errors, overlap_errors)

        rule_count = sum(1 for r in ok_records if r["kind"] == "rule")
        block_count = sum(1 for r in ok_records if r["kind"] == "block")
        rblock_count = sum(1 for r in ok_records if r["kind"] == "rblock")

        log.info(
            "csv validate: %d rows, %d records (%d rule / %d block / %d rblock), %d errors",
            parsed.total_rows, len(ok_records), rule_count, block_count, rblock_count, len(errors),
        )

        return [
            JSONResponse(
                {
                    "total_rows": parsed.total_rows,
                    "record_count": len(ok_records),
                    "rule_count": rule_count,
                    "block_count": block_count,
                    "rblock_count": rblock_count,
                    "error_count": len(errors),
                    "errors": errors,
                    "records": ok_records,
                }
            )
        ]

    @api.post("/commit")
    def commit_records(self) -> list[Response | Effect]:
        """Persist previewed records and return calendar-sync effects."""
        denied = _check_write_access(self.request, self.secrets)
        if denied:
            return denied

        body = self.request.json()
        records = body.get("records", [])
        if not records:
            return [
                JSONResponse(
                    {"error": "No records provided."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        effects: list[Effect] = []
        providers_touched: set[str] = set()
        created = {"rule": 0, "block": 0, "rblock": 0}
        now = datetime.now(UTC).isoformat()

        for rec in records:
            kind = rec.get("kind")
            if kind == "rule":
                rec["updated_at"] = now
                rule = ProviderAvailabilityRule.from_dict(rec)
                save_rule(rule)
                providers_touched.add(rule.provider_id)
                created["rule"] = created["rule"] + 1
            elif kind == "block":
                block = AdminBlock.from_dict(rec)
                save_block(block)
                effects.extend(build_block_event_effects(block))
                created["block"] = created["block"] + 1
            elif kind == "rblock":
                rblock = RecurringBlock.from_dict(rec)
                save_recurring_block(rblock)
                effects.extend(build_recurring_block_sync_effects(rblock))
                created["rblock"] = created["rblock"] + 1

        # Sync each touched provider's availability once, then refresh lead-time blocks.
        for pid in providers_touched:
            effects.extend(sync_provider_availability(pid))
            for r in get_rules_for_provider(pid):
                if r.is_active and r.booking_interval.min_lead_hours > 0:
                    effects.extend(build_lead_time_block_effects(r))

        log.info(
            "csv commit: %d rules, %d blocks, %d recurring blocks",
            created["rule"], created["block"], created["rblock"],
        )

        return [
            *effects,
            JSONResponse(
                {
                    "message": "Import complete",
                    "created_rules": created["rule"],
                    "created_blocks": created["block"],
                    "created_recurring_blocks": created["rblock"],
                }
            ),
        ]

    @staticmethod
    def _collect_errors(
        structural: list,
        resolution: list,
        overlap: list[dict],
    ) -> list[dict]:
        """Merge the three error sources into one row-sorted list."""
        merged: list[dict] = []
        for e in structural:
            merged.append(
                {"row_number": e.row_number, "errors": e.errors, "data": e.raw_data}
            )
        for e in resolution:
            merged.append(
                {"row_number": e.row_number, "errors": e.errors, "data": e.raw_data}
            )
        merged.extend(overlap)
        merged.sort(key=lambda item: item["row_number"])
        return merged
