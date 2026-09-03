import json
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import arrow
from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient import Patient as PatientEffect
from canvas_sdk.effects.patient_metadata import PatientMetadata
from canvas_sdk.effects.simple_api import HTMLResponse, PlainTextResponse, Response
from canvas_sdk.effects.task import AddTaskComment
from canvas_sdk.handlers.simple_api import SimpleAPI, api
from canvas_sdk.handlers.simple_api.security import StaffSessionAuthMixin
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Patient
from canvas_sdk.v1.data.care_team import CareTeamMembership, CareTeamMembershipStatus
from canvas_sdk.v1.data.patient import (
    PatientFacilityAddress,
)
from canvas_sdk.v1.data.patient import (
    PatientMetadata as PatientMetadataRecord,
)
from canvas_sdk.v1.data.staff import Staff
from canvas_sdk.v1.data.task import Task
from django.db.models import (
    Exists,
    OuterRef,
)
from logger import log

from patient_panel.services.columns import (
    enrich_columns_for_render,
    get_all_org_columns,
    get_editable_metadata_field,
    get_effective_columns,
    get_flag_color_labels,
    get_panel_config,
    get_user_column_prefs,
    is_valid_metadata_value,
)
from patient_panel.services.details import (
    get_allergies_details,
    get_conditions_details,
    get_gaps_details,
    get_medications_details,
    get_open_tasks,
    get_referrals_details,
    get_task_comments,
)
from patient_panel.services.formatting import format_local
from patient_panel.services.lookups import (
    get_facilities,
    get_protocol_titles,
    get_staff,
    get_unique_insurances,
)
from patient_panel.services.observations import (
    load_observations_batch,
    load_vitals_batch,
)
from patient_panel.services.pagination import (
    build_page_numbers,
    create_paginated_url_multi,
)
from patient_panel.services.patient_query import (
    annotate_sort_key,
    apply_metadata_filters,
    apply_patient_filters,
    apply_sorting,
    apply_stats_sort,
    build_decoration_queryset,
    build_spine_queryset,
    decorate_columns_with_filter_state,
    load_visit_stats,
    read_metadata_filter_params,
    STATS_SORT_FIELDS,
)
from patient_panel.services.serialization import process_patient
from patient_panel.services.stats_recompute import reconcile_all_stats

# Module-load timestamp used as a cache-bust token on every static-asset URL
# referenced by the dashboard's HTML shell. Changes on every deploy/restart
# so browsers fetch fresh CSS/JS.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


def _is_uuid(value: str) -> bool:
    """Return True if `value` parses as a UUID — guards UUID-typed filters."""
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


class PatientPanelAPI(StaffSessionAuthMixin, SimpleAPI):
    """API for the patient panel dashboard application.

    Access model: org-wide staff access. `StaffSessionAuthMixin` authenticates
    that the caller is a logged-in staff member; there is intentionally NO
    per-patient authorization. The dashboard's purpose is panel/care-coordination
    across the whole patient population (staff filter by care team as a
    convenience, not a permission boundary), so every authenticated staff member
    may read and write any patient's panel data (photo, clinical caption, flags,
    tasks/comments, configured metadata). If an instance needs patient-scoped
    access control, it must be added here (e.g. gate the `<patient_id>` endpoints
    on CareTeamMembership) — that is a deliberate product change, not the default.
    """

    BASE_PATH = "/plugin-io/api/patient_panel"
    PREFIX = "/app"

    DEFAULT_PAGE_SIZE = 10
    DEFAULT_HIGHLIGHT_THRESHOLD_DAYS_GREEN = 1
    DEFAULT_HIGHLIGHT_THRESHOLD_DAYS_YELLOW = 3
    DEFAULT_HIGHLIGHT_THRESHOLD_DAYS_RED = 7
    DEFAULT_AVATAR = "https://d3hn0m4rbsz438.cloudfront.net/avatar1.png"

    VALID_FLAG_COLORS = ("green", "yellow", "red", "")

    # Note types that are NOT an encounter — excluded from "last visit"
    # (messages, letters, C-CDA/data imports).
    LAST_VISIT_EXCLUDED_NOTE_TYPES = ("message", "letter", "data", "ccda")

    # staff_id → resolved display timezone. Sandbox forbids instance-dict
    # mutation, so we cache at class level via whole-dict replacement.
    # Bounded by staff count per instance.
    _display_tz_cache: dict[str, str] = {}


    # ── Static file endpoints ─────────────────────────────────────────

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        """Serve the main dashboard page."""
        context = {
            **self._current_logged_staff,
            "cache_bust": _CACHE_BUST,
            # Per-user key for client-side filter persistence (see scripts.js).
            "staff_id": self.request.headers.get("canvas-logged-in-user-id", ""),
        }
        return [
            HTMLResponse(
                render_to_string("static/index.html", context),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/styles.css")
    def get_css(self) -> list[Response | Effect]:
        """Serve the contents of a CSS file."""
        return [
            Response(
                render_to_string("static/styles.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    @api.get("/scripts.js")
    def get_scripts(self) -> list[Response | Effect]:
        """Serve the contents of a JavaScript file."""
        return [
            Response(
                render_to_string("static/scripts.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    # ── Patient table ─────────────────────────────────────────────────

    @api.get("/table")
    def get_table(self) -> list[Response | Effect]:
        """Serve the contents of a table with pagination."""
        # `page` is user-controllable; a non-numeric value would raise on
        # int() and a non-positive value would produce a negative queryset
        # slice (Django rejects negative indexing). Default to 1 on both.
        page_param = self.request.query_params.get("page", "1").strip()
        page = int(page_param) if page_param.isdigit() else 1
        page = max(page, 1)
        page_size_param = self.request.query_params.get("page_size", "").strip()
        page_size = int(page_size_param) if page_size_param.isdigit() else self._page_size
        if page_size not in (1, 10, 50, 100):
            page_size = self._page_size
        patient_search = self.request.query_params.get("patient_search", "").strip()

        facility_ids_param = self.request.query_params.get("facility_ids", "").strip()
        selected_facility_ids = (
            [f.strip() for f in facility_ids_param.split(",") if f.strip()]
            if facility_ids_param
            else []
        )

        protocols_param = self.request.query_params.get("protocols", "").strip()
        selected_protocols = (
            [p.strip() for p in protocols_param.split(",") if p.strip()]
            if protocols_param
            else []
        )

        # Filter-dropdown lookups scan population-sized tables and run on every
        # table render; cache them for a short TTL (see services.lookups).
        dropdown_cache = get_cache()
        staff = get_staff(dropdown_cache)
        staff_ids_param = self.request.query_params.get("staff_ids", "").strip()
        selected_staff_ids = (
            [s.strip() for s in staff_ids_param.split(",") if s.strip()]
            if staff_ids_param
            else []
        )

        no_auto_filter = self.request.query_params.get("no_auto_filter", "").strip() == "1"

        if not staff_ids_param and not no_auto_filter:
            logged_in_user_id = self.request.headers.get("canvas-logged-in-user-id")
            # Validate the header looks like a UUID before querying — Django's
            # UUIDField filter raises ValidationError on malformed input, which
            # the previous broad except: pass silently swallowed.
            if logged_in_user_id and _is_uuid(logged_in_user_id):
                logged_in_staff = (
                    Staff.objects.filter(id=logged_in_user_id).values("id").first()
                )
                if logged_in_staff:
                    has_care_team_patients = CareTeamMembership.objects.filter(
                        staff__id=logged_in_staff["id"],
                        status=CareTeamMembershipStatus.ACTIVE,
                    ).exists()
                    if has_care_team_patients:
                        selected_staff_ids = [str(logged_in_staff["id"])]

        insurances_param = self.request.query_params.get("insurances", "").strip()
        selected_insurances = (
            [i.strip() for i in insurances_param.split(",") if i.strip()]
            if insurances_param
            else []
        )
        insurances = get_unique_insurances(dropdown_cache)

        flagged_only = self.request.query_params.get("flagged_only", "").strip() == "1"
        sort_by = self.request.query_params.get("sort_by", "").strip()
        sort_dir = self.request.query_params.get("sort_dir", "asc").strip()
        render_config = self._render_config()
        offset = (page - 1) * page_size

        # Columns drive metadata sort/filter; compute before filtering.
        staff_id_for_columns = self.request.headers.get("canvas-logged-in-user-id", "")
        columns_for_sort = (
            get_effective_columns(self.secrets, get_cache(), staff_id_for_columns)
            if staff_id_for_columns
            else get_panel_config(self.secrets)
        )
        selected_metadata_filters = read_metadata_filter_params(
            self.request.query_params, columns_for_sort
        )

        # PROTECTION (do NOT regress — do NOT reintroduce a flag/condition here):
        # the indexed-stats SORT is used for every stats-accelerated field
        # UNCONDITIONALLY. The legacy live correlated-subquery sort over the full
        # patient population is an instance-killer (last_visit/next_visit ≈ 37 s →
        # gateway timeout + Postgres JIT storm) and must be UNREACHABLE from a
        # sort click. The stats sort is safe even when the table is empty/cold
        # (LEFT-JOIN-equivalent: ~13 ms, patients sort as NULL, none dropped), so
        # there is never a reason to fall back to the live sort for these fields.
        stats_sort = sort_by in STATS_SORT_FIELDS

        # ── Phase 1: lean Patient-rooted spine (filter + count + sort + paginate).
        # Roots on Patient so total_count is the full filtered population and no
        # patient is ever dropped. Stats fields sort via a correlated Subquery
        # over PatientPanelStats keyed on the unique patient_id (sub-ms probe;
        # LEFT-JOIN-equivalent). Non-stats fields (name, metadata) use the cheap
        # apply_sorting path — which no longer handles last/next-visit at all.
        spine = build_spine_queryset()
        if selected_facility_ids:
            spine = spine.filter(
                Exists(
                    PatientFacilityAddress.objects.filter(
                        patient=OuterRef("pk"),
                        facility__id__in=selected_facility_ids,
                    )
                )
            )
        spine = apply_patient_filters(
            spine,
            staff_ids=selected_staff_ids,
            patient_search=patient_search,
            insurances=selected_insurances,
            flagged_only=flagged_only,
            protocols=selected_protocols,
        )
        spine = apply_metadata_filters(spine, selected_metadata_filters, columns_for_sort)

        # COUNT on the lean, un-annotated spine → cheap COUNT(*) over the full
        # filtered population (identical for both sort paths).
        total_count = spine.count()

        if stats_sort:
            spine = apply_stats_sort(spine, sort_by, sort_dir)
        else:
            spine = annotate_sort_key(spine, sort_by, self.LAST_VISIT_EXCLUDED_NOTE_TYPES)
            spine = apply_sorting(spine, sort_by, sort_dir, columns_for_sort)
        page_ids = list(spine[offset : offset + page_size].values_list("id", flat=True))

        # ── Phase 2: decorate ONLY the page's patients ─────────────────
        if page_ids:
            # last/next-visit cell values come from the precomputed
            # PatientPanelStats rows (load_visit_stats), never live per-row
            # note-state subqueries (which rescan the ~250k-row note-state
            # relation per page row — ~20s/page, trips Postgres JIT).
            decoration = build_decoration_queryset(
                self.LAST_VISIT_EXCLUDED_NOTE_TYPES,
                include_visit_annotations=False,
            ).filter(id__in=page_ids)
            order = {pid: i for i, pid in enumerate(page_ids)}
            patients_page = sorted(decoration, key=lambda p: order[p.id])
            visit_stats = load_visit_stats(page_ids)
            for patient in patients_page:
                last_dt, next_dt = visit_stats.get(str(patient.id), (None, None))
                patient.last_visit_ann = last_dt
                patient.next_visit_ann = next_dt
        else:
            patients_page = []

        # Collect LOINC codes and vital names from observation columns
        loinc_codes = [c["loinc"] for c in columns_for_sort if c.get("type") == "observation" and c.get("loinc")]
        vital_names = [c["vital_name"] for c in columns_for_sort if c.get("type") == "observation" and c.get("vital_name")]
        patient_ids = [str(p.id) for p in patients_page]
        try:
            obs_data = load_observations_batch(patient_ids, loinc_codes) if loinc_codes else {}
        except Exception:
            log.exception("Failed to load observations batch")
            obs_data = {}
        try:
            vitals_data = load_vitals_batch(patient_ids, vital_names) if vital_names else {}
        except Exception:
            log.exception("Failed to load vitals batch")
            vitals_data = {}

        # Controller-owned state injected into the row serializer: class
        # constants, the tz-bound formatter, and the ORM/cache readers that
        # stay on the class.
        serialize_ctx = {
            "base_path": self.BASE_PATH,
            "prefix": self.PREFIX,
            "cache_bust": _CACHE_BUST,
            "format_local": self._format_local,
            "get_care_team": self._get_all_care_team_members,
        }

        # Attach inline-edit descriptors to metadata columns that are safe to
        # edit in place (METADATA_FIELDS editable, flat value, not tags). Done
        # once per request, not per row. Does NOT touch the spine query, so the
        # sort/paginate optimization is unaffected.
        # NOTE: pass the RAW secrets (self.secrets), not the derived
        # `_render_config()` dict — the latter omits METADATA_FIELDS, which
        # get_editable_metadata_field needs (same source the edit endpoint uses).
        render_columns = enrich_columns_for_render(columns_for_sort, self.secrets)

        processed_patients = []
        for patient in patients_page:
            # Degrade a single bad row (e.g. missing birth_date, malformed
            # metadata JSON) instead of 500-ing the entire table render.
            try:
                processed_patients.append(
                    process_patient(
                        patient, render_config, render_columns, obs_data, vitals_data, serialize_ctx
                    )
                )
            except Exception:
                log.exception(
                    "Failed to process patient %s for table render",
                    getattr(patient, "id", "?"),
                )

        total_pages = (total_count + page_size - 1) // page_size
        has_next = page < total_pages
        has_previous = page > 1

        pagination_args = dict(
            facility_ids=selected_facility_ids,
            protocols=selected_protocols,
            patient_search=patient_search,
            staff_ids=selected_staff_ids,
            insurances=selected_insurances,
            sort_by=sort_by,
            sort_dir=sort_dir,
            flagged_only=flagged_only,
            page_size=page_size,
            metadata_filters=selected_metadata_filters,
        )

        previous_page = (
            create_paginated_url_multi(
                self.BASE_PATH, self.PREFIX, "table", page - 1, **pagination_args
            )
            if has_previous
            else None
        )
        next_page = (
            create_paginated_url_multi(
                self.BASE_PATH, self.PREFIX, "table", page + 1, **pagination_args
            )
            if has_next
            else None
        )

        page_numbers = build_page_numbers(
            self.BASE_PATH, self.PREFIX, page, total_pages, pagination_args
        )

        flag_labels = get_flag_color_labels(self.secrets)
        # Decorate filterable metadata columns with their currently-selected
        # values so the template can render the dropdown with state.
        columns_with_filters = decorate_columns_with_filter_state(
            columns_for_sort, selected_metadata_filters
        )
        context = {
            "patients": processed_patients,
            "columns": render_columns,
            "filterable_metadata_columns": columns_with_filters,
            "staff": staff,
            "facilities": get_facilities(dropdown_cache),
            "protocol_titles": get_protocol_titles(dropdown_cache),
            "selected_facility_ids": ",".join(selected_facility_ids),
            "selected_protocols": ",".join(selected_protocols),
            "patient_search": patient_search,
            "insurances": insurances,
            "selected_staff_ids": ",".join(selected_staff_ids),
            "selected_insurances": ",".join(selected_insurances),
            "sort_by": sort_by,
            "sort_dir": sort_dir,
            "page_size": page_size,
            "flag_labels": flag_labels,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "has_next": has_next,
                "has_previous": has_previous,
                "next_page": next_page,
                "previous_page": previous_page,
                "page_numbers": page_numbers,
            },
        }

        return [
            Response(
                render_to_string("static/table.html", context).encode(),
                status_code=HTTPStatus.OK,
            )
        ]

    # ── Tasks ─────────────────────────────────────────────────────────

    @api.get("/<patient_id>/tasks")
    def get_tasks(self) -> list[Response | Effect]:
        """Serves the open tasks details for a given patient."""
        patient_id = self.request.path_params["patient_id"]
        context = {
            "patient_id": patient_id,
            "tasks": get_open_tasks(patient_id),
        }
        return [
            Response(
                render_to_string("static/tasks.html", context).encode(),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/tasks/<task_id>/comments")
    def get_task_comments(self) -> list[Response | Effect]:
        """Get comments for a specific task."""
        task_id = self.request.path_params["task_id"]
        comments = get_task_comments(task_id, format_local=self._format_local)
        context = {"task_id": task_id, "comments": comments}
        return [
            Response(
                render_to_string("static/comments.html", context).encode(),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/tasks/<task_id>/comment")
    def post_task_comment(self) -> list[Response | Effect]:
        """Posts a comment to a task."""
        task_id = self.request.path_params["task_id"]
        if not _is_uuid(task_id):
            return [PlainTextResponse("Task not found", status_code=HTTPStatus.NOT_FOUND)]
        try:
            task = Task.objects.get(id=task_id)
        except Task.DoesNotExist:
            return [PlainTextResponse("Task not found", status_code=HTTPStatus.NOT_FOUND)]

        form_data = self.request.form_data()
        comment_content = form_data.get("comment_content")
        if not comment_content:
            return [
                PlainTextResponse(
                    "Comment content is required",
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        comment = str(comment_content.value).strip()
        author = Staff.objects.get(id=self.request.headers["canvas-logged-in-user-id"])
        add_task_comment = AddTaskComment(task_id=task.id, body=comment, author_id=author.id)

        return [
            Response(status_code=HTTPStatus.OK),
            add_task_comment.apply(),
        ]

    # ── Care gaps ─────────────────────────────────────────────────────

    @api.get("/<patient_id>/gaps")
    def get_gaps(self) -> list[Response | Effect]:
        """Serves the gaps in care details for a given patient."""
        patient_id = self.request.path_params["patient_id"]
        context = {
            "patient_id": patient_id,
            "gaps": get_gaps_details(patient_id),
        }
        return [
            Response(
                render_to_string("static/gaps.html", context).encode(),
                status_code=HTTPStatus.OK,
            )
        ]

    # ── Conditions ────────────────────────────────────────────────────

    @api.get("/<patient_id>/conditions")
    def get_conditions(self) -> list[Response | Effect]:
        """Serve the active conditions accordion for a given patient."""
        patient_id = self.request.path_params["patient_id"]
        context = {
            "patient_id": patient_id,
            "conditions": get_conditions_details(patient_id, format_local=self._format_local),
        }
        return [
            Response(
                render_to_string("static/conditions.html", context).encode(),
                status_code=HTTPStatus.OK,
            )
        ]

    # ── Medications ───────────────────────────────────────────────────

    @api.get("/<patient_id>/medications")
    def get_medications(self) -> list[Response | Effect]:
        """Serve the active medications accordion for a given patient."""
        patient_id = self.request.path_params["patient_id"]
        context = {
            "patient_id": patient_id,
            "medications": get_medications_details(patient_id, format_local=self._format_local),
        }
        return [
            Response(
                render_to_string("static/medications.html", context).encode(),
                status_code=HTTPStatus.OK,
            )
        ]

    # ── Allergies ─────────────────────────────────────────────────────

    @api.get("/<patient_id>/allergies")
    def get_allergies(self) -> list[Response | Effect]:
        """Serve the allergies accordion for a given patient."""
        patient_id = self.request.path_params["patient_id"]
        context = {
            "patient_id": patient_id,
            "allergies": get_allergies_details(patient_id, format_local=self._format_local),
        }
        return [
            Response(
                render_to_string("static/allergies.html", context).encode(),
                status_code=HTTPStatus.OK,
            )
        ]

    # ── Referrals ─────────────────────────────────────────────────────

    @api.get("/<patient_id>/referrals")
    def get_referrals(self) -> list[Response | Effect]:
        """Serve the referrals accordion for a given patient."""
        patient_id = self.request.path_params["patient_id"]
        context = {
            "patient_id": patient_id,
            "referrals": get_referrals_details(patient_id, format_local=self._format_local),
        }
        return [
            Response(
                render_to_string("static/referrals.html", context).encode(),
                status_code=HTTPStatus.OK,
            )
        ]

    # ── Clinical notes ────────────────────────────────────────────────

    @api.get("/<patient_id>/clinical-note/edit")
    def get_clinical_notes(self) -> list[Response | Effect]:
        """Serves the clinical note edit form for a given patient."""
        patient_id = self.request.path_params["patient_id"]
        if not _is_uuid(patient_id):
            return [PlainTextResponse("Patient not found", status_code=HTTPStatus.NOT_FOUND)]
        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            return [PlainTextResponse("Patient not found", status_code=HTTPStatus.NOT_FOUND)]
        context = {"patient_id": patient_id, "clinical_note": patient.clinical_note}
        return [
            Response(
                render_to_string("static/clinical_note_edit.html", context).encode(),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/<patient_id>/clinical-note/save")
    def save_clinical_notes(self) -> list[Response | Effect]:
        """Save clinical note for a patient. Allows empty notes to clear."""
        patient_id = self.request.path_params["patient_id"]
        if not _is_uuid(patient_id):
            return [PlainTextResponse("invalid patient", status_code=HTTPStatus.BAD_REQUEST)]
        form_data = self.request.form_data()
        admin_note = form_data.get("clinical_note")
        note = str(admin_note.value).strip() if admin_note else ""
        context = {"patient_id": patient_id, "clinical_note": note}
        return [
            PatientEffect(patient_id=patient_id, clinical_note=note).update(),
            Response(
                render_to_string("static/clinical_note.html", context).encode(),
                status_code=HTTPStatus.OK,
            ),
        ]

    @api.get("/<patient_id>/clinical-note/view")
    def view_clinical_notes(self) -> list[Response | Effect]:
        """Serves the clinical note display for a given patient."""
        patient_id = self.request.path_params["patient_id"]
        if not _is_uuid(patient_id):
            return [PlainTextResponse("Patient not found", status_code=HTTPStatus.NOT_FOUND)]
        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            return [PlainTextResponse("Patient not found", status_code=HTTPStatus.NOT_FOUND)]
        context = {"patient_id": patient_id, "clinical_note": patient.clinical_note}
        return [
            Response(
                render_to_string("static/clinical_note.html", context).encode(),
                status_code=HTTPStatus.OK,
            )
        ]

    # Patient photos are read directly from the DB via `patient.photo_url`
    # (see services.serialization) — no per-row endpoint or FHIR round-trip.

    # ── Flags ────────────────────────────────────────────────────────

    @api.post("/<patient_id>/flag")
    def set_flag(self) -> list[Response | Effect]:
        """Set flag color for a patient."""
        patient_id = self.request.path_params["patient_id"]
        if not _is_uuid(patient_id):
            return [Response(content=b"invalid patient", status_code=HTTPStatus.BAD_REQUEST)]
        today_str = arrow.now().format("YYYY-MM-DD")

        form_data = self.request.form_data()
        color_field = form_data.get("color")
        color = str(color_field.value).strip() if color_field else ""

        if color not in self.VALID_FLAG_COLORS:
            color = ""

        new_value = f"{today_str}:{color}" if color else ""

        metadata = PatientMetadata(patient_id=patient_id, key="daily_flag")
        return [
            metadata.upsert(new_value),
            Response(content=b"OK", status_code=HTTPStatus.OK),
        ]

    @api.post("/flags/clear-all")
    def clear_all_flags(self) -> list[Response | Effect]:
        """Clear all active daily flags."""
        today_str = arrow.now().format("YYYY-MM-DD")

        # `PatientMetadataRecord.patient_id` is the integer `dbid` FK, not
        # the UUID. Traverse via `patient__id` so the JOIN only selects the
        # UUID column without materialising the full Patient model.
        flagged_patient_uuids = (
            PatientMetadataRecord.objects.filter(
                key="daily_flag",
                value__startswith=today_str,
            )
            .values_list("patient__id", flat=True)
            .iterator(chunk_size=100)
        )

        effects: list[Response | Effect] = [
            Response(content=b"OK", status_code=HTTPStatus.OK),
        ]

        for patient_uuid in flagged_patient_uuids:
            metadata = PatientMetadata(
                patient_id=str(patient_uuid),
                key="daily_flag",
            )
            effects.append(metadata.upsert(""))

        return effects

    # ── Inline metadata edit ─────────────────────────────────────────

    @api.post("/<patient_id>/metadata/<key>")
    def update_metadata(self) -> list[Response | Effect]:
        """Upsert a single patient metadata value.

        Allowed only when METADATA_FIELDS declares `key` with
        `editable: true`. For SELECT inputs, the submitted value must be
        one of the configured `options` (empty string is always allowed
        and clears the field).
        """
        patient_id = self.request.path_params["patient_id"]
        key = self.request.path_params["key"]

        if not _is_uuid(patient_id):
            return [Response(
                content=b'{"error": "invalid patient"}',
                status_code=HTTPStatus.BAD_REQUEST,
                content_type="application/json",
            )]

        field_config = get_editable_metadata_field(self.secrets, key)
        if field_config is None:
            return [Response(
                content=b'{"error": "forbidden"}',
                status_code=HTTPStatus.FORBIDDEN,
                content_type="application/json",
            )]

        form = self.request.form_data()
        value_field = form.get("value")
        value = str(value_field.value) if value_field else ""

        if not is_valid_metadata_value(field_config, value):
            return [Response(
                content=b'{"error": "invalid value"}',
                status_code=HTTPStatus.BAD_REQUEST,
                content_type="application/json",
            )]

        metadata = PatientMetadata(patient_id=patient_id, key=key)
        return [
            metadata.upsert(value),
            Response(content=b"OK", status_code=HTTPStatus.OK),
        ]

    # ── Column preferences ───────────────────────────────────────────

    @api.get("/preferences")
    def get_preferences(self) -> list[Response | Effect]:
        """Return all org columns with per-user visibility flags."""
        staff_id = self.request.headers.get("canvas-logged-in-user-id")
        if not staff_id:
            return [Response(
                content=b'{"error": "unauthorized"}',
                status_code=HTTPStatus.UNAUTHORIZED,
                content_type="application/json",
            )]

        cache = get_cache()
        org_columns = get_all_org_columns(self.secrets)
        user_prefs = get_user_column_prefs(cache, staff_id)

        result = []
        for col in org_columns:
            visible = (
                user_prefs.get(col["key"], col.get("visible", True))
                if user_prefs
                else col.get("visible", True)
            )
            result.append({
                "key": col["key"],
                "label": col.get("label", col["key"]),
                "type": col.get("type", "built-in"),
                "visible": visible,
            })

        return [Response(
            content=json.dumps(result).encode(),
            status_code=HTTPStatus.OK,
            content_type="application/json",
        )]

    @api.post("/preferences")
    def save_preferences(self) -> list[Response | Effect]:
        """Save per-user column visibility preferences to cache."""
        staff_id = self.request.headers.get("canvas-logged-in-user-id")
        if not staff_id:
            return [Response(
                content=b'{"error": "unauthorized"}',
                status_code=HTTPStatus.UNAUTHORIZED,
                content_type="application/json",
            )]

        form_data = self.request.form_data()
        columns_field = form_data.get("columns")
        if not columns_field:
            return [Response(
                content=b'{"error": "missing columns"}',
                status_code=HTTPStatus.BAD_REQUEST,
                content_type="application/json",
            )]

        try:
            prefs = json.loads(str(columns_field.value))
        except (json.JSONDecodeError, TypeError):
            return [Response(
                content=b'{"error": "invalid json"}',
                status_code=HTTPStatus.BAD_REQUEST,
                content_type="application/json",
            )]

        if not isinstance(prefs, dict) or not all(isinstance(v, bool) for v in prefs.values()):
            return [Response(
                content=b'{"error": "invalid format, expected {key: bool}"}',
                status_code=HTTPStatus.BAD_REQUEST,
                content_type="application/json",
            )]

        cache = get_cache()
        cache.set(f"column_prefs_{staff_id}", json.dumps(prefs))

        return [Response(
            content=b'{"status": "saved"}',
            status_code=HTTPStatus.OK,
            content_type="application/json",
        )]

    @api.post("/preferences/reset")
    def reset_preferences(self) -> list[Response | Effect]:
        """Reset per-user preferences to org defaults."""
        staff_id = self.request.headers.get("canvas-logged-in-user-id")
        if not staff_id:
            return [Response(
                content=b'{"error": "unauthorized"}',
                status_code=HTTPStatus.UNAUTHORIZED,
                content_type="application/json",
            )]

        cache = get_cache()
        cache.delete(f"column_prefs_{staff_id}")

        return [Response(
            content=b'{"status": "reset"}',
            status_code=HTTPStatus.OK,
            content_type="application/json",
        )]

    # ── Stats maintenance ─────────────────────────────────────────────

    @api.post("/stats/backfill")
    def backfill_stats(self) -> list[Response | Effect]:
        """Recompute PatientPanelStats for every patient (idempotent, set-based).

        Ops/maintenance endpoint: populate the table immediately after deploy
        (instead of waiting for the reconcile cron), and repair drift on demand.
        Inherits the plugin's org-wide StaffSessionAuthMixin auth (consistent with the
        dashboard's documented access model); the operation is non-destructive
        (it upserts correct values) and runs synchronously (~seconds at 35k)."""
        staff_id = self.request.headers.get("canvas-logged-in-user-id", "")
        count = reconcile_all_stats()
        log.info("[panel_stats] manual backfill by staff=%s upserted %s rows", staff_id, count)
        return [
            Response(
                content=json.dumps({"status": "ok", "patients": count}).encode(),
                status_code=HTTPStatus.OK,
                content_type="application/json",
            )
        ]

    # ── Private helpers ───────────────────────────────────────────────


    def _render_config(self) -> dict[str, Any]:
        """Parsed, typed display config for the row serializer.

        NOT the raw secret bag — this derives a handful of secrets into typed
        values (int page_size, int highlight_* thresholds, dict
        insurances_logos) so the per-row serializer doesn't re-parse strings.
        It deliberately carries ONLY those keys; anything needing a raw secret
        (METADATA_FIELDS, PANEL_CONFIG, FHIR creds, …) must read `self.secrets`.
        """
        page_size_raw = self.secrets.get("PAGE_SIZE")
        highlight_green = self.secrets.get("HIGHLIGHT_THRESHOLD_DAYS_GREEN")
        highlight_yellow = self.secrets.get("HIGHLIGHT_THRESHOLD_DAYS_YELLOW")
        highlight_red = self.secrets.get("HIGHLIGHT_THRESHOLD_DAYS_RED")
        insurances_logos_raw = self.secrets.get("INSURANCES", "{}")

        try:
            page_size_str = page_size_raw.strip('"\'') if page_size_raw else None
            page_size = int(page_size_str) if page_size_str else self.DEFAULT_PAGE_SIZE
        except (ValueError, AttributeError):
            page_size = self.DEFAULT_PAGE_SIZE

        try:
            insurances_logos = (
                json.loads(insurances_logos_raw)
                if isinstance(insurances_logos_raw, str)
                else insurances_logos_raw
            )
            if not isinstance(insurances_logos, dict):
                insurances_logos = {}
        except (json.JSONDecodeError, TypeError):
            insurances_logos = {}

        def _parse_threshold(val: Any, default: int) -> int:
            try:
                return int(val) if val else default
            except ValueError:
                return default

        return {
            "page_size": page_size,
            "highlight_green": _parse_threshold(
                highlight_green, self.DEFAULT_HIGHLIGHT_THRESHOLD_DAYS_GREEN
            ),
            "highlight_yellow": _parse_threshold(
                highlight_yellow, self.DEFAULT_HIGHLIGHT_THRESHOLD_DAYS_YELLOW
            ),
            "highlight_red": _parse_threshold(
                highlight_red, self.DEFAULT_HIGHLIGHT_THRESHOLD_DAYS_RED
            ),
            "insurances_logos": insurances_logos,
        }

    def _display_tz(self) -> str:
        """Resolve the display timezone for date formatting.

        Priority: logged-in staff `last_known_timezone` → `INSTANCE_TIMEZONE`
        secret → UTC. Cached at class level keyed by staff_id; entries
        survive across requests on the same worker (acceptable: a staff
        member's timezone setting is stable within a session).
        """
        staff_id = self.request.headers.get("canvas-logged-in-user-id") or ""
        cached = PatientPanelAPI._display_tz_cache.get(staff_id)
        if cached is not None:
            return cached

        tz = ""
        if staff_id:
            staff_tz = (
                Staff.objects.filter(id=staff_id)
                .values_list("last_known_timezone", flat=True)
                .first()
            )
            if staff_tz:
                tz = str(staff_tz)

        if not tz:
            secret_tz = self.secrets.get("INSTANCE_TIMEZONE")
            if isinstance(secret_tz, str) and secret_tz.strip():
                tz = secret_tz.strip()

        if not tz:
            tz = "UTC"

        # Whole-dict replacement — sandbox forbids dict item assignment via
        # instance __dict__, but class-attribute reassignment is allowed.
        PatientPanelAPI._display_tz_cache = {
            **PatientPanelAPI._display_tz_cache,
            staff_id: tz,
        }
        return tz

    def _format_local(self, dt: Any, fmt: str) -> str:
        """Format a datetime in the resolved display timezone.

        Thin glue: resolves the tz (class-cached) and delegates the actual
        formatting to services.formatting so date-dependent service functions
        can receive this bound callable.
        """
        return format_local(dt, fmt, self._display_tz())

    @property
    def _current_logged_staff(self) -> dict:
        """Get the currently logged staff member."""
        logged_in_user = Staff.objects.values("first_name", "last_name").get(
            id=self.request.headers["canvas-logged-in-user-id"]
        )
        return {
            "first_name": logged_in_user["first_name"],
            "last_name": logged_in_user["last_name"],
        }

    @property
    def _page_size(self) -> int:
        """Get the page size for pagination."""
        return int(self._render_config().get("page_size", self.DEFAULT_PAGE_SIZE))

    _STAFF_PHOTO_CACHE_TTL_SECONDS = 24 * 3600  # 24 hours

    def _get_all_care_team_members(self, patient: Any) -> list[dict[str, Any]]:
        """Get all active care team members for a patient with photo URLs.

        Staff photos come from canvas_sdk_data_api_staffphoto_001 via the
        Staff.photos reverse FK (prefetched at the patients query level).
        Resolved URLs are cached by staff_id for `_STAFF_PHOTO_CACHE_TTL_SECONDS`
        so repeated table renders skip re-iterating the prefetched relation.
        """
        cache = get_cache()
        members = []
        for membership in patient.care_team_memberships.all():
            if membership.staff:
                staff = membership.staff
                first_name = staff.first_name or ""
                last_name = staff.last_name or ""
                # Cache staff photo URL by staff_id — photos change rarely.
                cache_key = f"staff_photo_url_{staff.id}"
                photo_url = cache.get(cache_key)
                if photo_url is None:
                    photo = next(iter(staff.photos.all()), None)
                    photo_url = photo.url if photo and photo.url else self.DEFAULT_AVATAR
                    cache.set(
                        cache_key,
                        photo_url,
                        timeout_seconds=self._STAFF_PHOTO_CACHE_TTL_SECONDS,
                    )
                members.append(
                    {
                        "id": str(staff.id),
                        "first_name": first_name,
                        "last_name": last_name,
                        "initials": f"{first_name[:1]}{last_name[:1]}".upper(),
                        "name": (
                            staff.credentialed_name
                            if hasattr(staff, "credentialed_name") and staff.credentialed_name
                            else f"{first_name} {last_name}"
                        ),
                        "role": membership.role.display if membership.role else None,
                        "photo_url": photo_url,
                    }
                )
        return members

