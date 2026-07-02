from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from typing import Any, NamedTuple

from requests import RequestException  # type: ignore[import-untyped]

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from logger import log
from canvas_sdk.effects.note.appointment import Appointment as AppointmentEffect
from canvas_sdk.v1.data.appointment import Appointment as AppointmentModel
from canvas_sdk.v1.data.note import NoteType
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.practicelocation import PracticeLocation
from canvas_sdk.v1.data.staff import Staff

from scheduling_modal_with_recurring_support.services.availability import (
    _fhir_to_local_hhmm,
    aggregate_by_candidate_time,
    aggregate_by_first_date,
    analyse_recurrence,
    iter_free_slots,
    lookup_window,
)
from scheduling_modal_with_recurring_support.services.capacity import bust_filled_pct
from scheduling_modal_with_recurring_support.services.oauth import acquire_token
from scheduling_modal_with_recurring_support.services.provider_filter import (
    licensed_providers_for_state,
    providers_covering_series_by_first_date,
    providers_ranked_by_series_availability,
)
from scheduling_modal_with_recurring_support.services.recurrence import (
    MAX_OCCURRENCES,
    RecurrenceRule,
    RecurrenceValidationError,
    from_legacy_cadence,
    parse_recurrence,
)

CANDIDATE_FIRST_DATES_WINDOW_CAP_DAYS = 90
FREE_SLOTS_DEFAULT_LIMIT = 25
FREE_SLOTS_MAX_LIMIT = 100
AVAILABILITY_WINDOW_CAP_DAYS = 21

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


HARDCODED_DEFAULT_DURATION_MINUTES = 60
MIN_DURATION_MINUTES = 5
MAX_DURATION_MINUTES = 240


def _resolve_default_duration_minutes(secrets: dict[str, str]) -> int:
    raw = (secrets.get("DEFAULT_APPOINTMENT_DURATION_MINUTES") or "").strip()
    if not raw:
        return HARDCODED_DEFAULT_DURATION_MINUTES
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return HARDCODED_DEFAULT_DURATION_MINUTES
    if n < MIN_DURATION_MINUTES or n > MAX_DURATION_MINUTES:
        return HARDCODED_DEFAULT_DURATION_MINUTES
    return n


def _parse_request_duration_minutes(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n < MIN_DURATION_MINUTES or n > MAX_DURATION_MINUTES:
        return default
    return n


def _now() -> datetime:
    """Return current UTC datetime. Extracted for test mockability."""
    return datetime.now(timezone.utc)


def _today() -> date:
    """Return current local date. Extracted for test mockability."""
    return date.today()


class SchedulingAPI(StaffSessionAuthMixin, SimpleAPI):
    PREFIX = "/scheduling"

    # ---- Static assets ----

    @api.get("/canvas-plugin-ui.css")
    def canvas_plugin_ui_css(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/canvas-plugin-ui.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/canvas-plugin-ui.js")
    def canvas_plugin_ui_js(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/canvas-plugin-ui.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
            )
        ]

    # ---- Main UI ----

    @api.get("/ui")
    def scheduling_ui(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient_id", "")
        today_iso = _today().isoformat()

        patient_state = ""
        patient_full_name = ""
        if patient_id:
            result = _resolve_patient_state(patient_id)
            patient_state = result.state
            patient_obj = Patient.objects.filter(id=patient_id).first()
            if patient_obj:
                patient_full_name = f"{patient_obj.first_name} {patient_obj.last_name}".strip()

        content = render_to_string(
            "templates/scheduling_modal.html",
            {
                "patient_id": patient_id,
                "patient_state": patient_state,
                "patient_full_name": patient_full_name,
                "needs_patient_selection": not patient_id,
                "today_iso": today_iso,
                "cache_bust": _CACHE_BUST,
            },
        )
        return [HTMLResponse(content, status_code=HTTPStatus.OK)]

    # ---- Data endpoints ----

    @api.get("/providers")
    def providers(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient_id", "")
        result = _resolve_patient_state(patient_id)

        # When the patient lookup itself failed (no patient_id, patient not found),
        # surface that as a 400. Missing state is recoverable and falls through to
        # the unfiltered provider list with a state_missing flag.
        if not result.state and not patient_id:
            return [
                JSONResponse(
                    {"error": result.error},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        if not result.state and result.not_found:
            return [
                JSONResponse(
                    {"error": result.error},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        # Session state override. When the patient has no state on file the modal
        # lets the scheduler pick one for this booking only, passed here as the
        # `state` query param. It drives the license filter for this request and is
        # never persisted. An invalid value is ignored so it cannot wedge the flow.
        override = self.request.query_params.get("state", "").strip().upper()
        if len(override) != 2 or not override.isalpha():
            override = ""
        effective_state = override or result.state

        state_missing = not effective_state

        # Date aware ranking inputs. When the caller passes a start_date the
        # provider list is ranked by the real series each provider can take on
        # the projected occurrence dates, the one availability basis, rather
        # than by the seven day load proxy. Absent these the endpoint
        # keeps its original load ranking so the current flow is unchanged.
        ranked_rule: RecurrenceRule | None = None
        ranked_start_date: date | None = None
        ranked_tz = 0
        ranked_duration = _resolve_default_duration_minutes(self.secrets)
        start_date_str = self.request.query_params.get("start_date", "")
        if start_date_str:
            # The canonical recurrence rule is preferred when present, passed as
            # a JSON encoded query param so custom cadences with weekdays and
            # intervals rank date aware too, the same rule shape the agnostic
            # /candidate-first-dates branch already takes in its POST body.
            # cadence plus occurrences stays as the legacy fallback for the
            # named presets and the existing callers.
            recurrence_param = self.request.query_params.get("recurrence", "")
            cadence = self.request.query_params.get("cadence", "weekly")
            occurrences_str = self.request.query_params.get("occurrences", "1")
            try:
                ranked_start_date = date.fromisoformat(start_date_str)
                if recurrence_param:
                    ranked_rule = parse_recurrence(json.loads(recurrence_param))
                else:
                    occurrences = min(int(occurrences_str), MAX_OCCURRENCES)
                    ranked_rule = from_legacy_cadence(cadence, occurrences)
                ranked_tz = int(self.request.query_params.get("tz_offset", 0))
            except (ValueError, TypeError, RecurrenceValidationError):
                return [
                    JSONResponse(
                        {"error": "We could not read those inputs. Refresh the modal."},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]
            ranked_duration = _parse_request_duration_minutes(
                self.request.query_params.get("duration_minutes"),
                ranked_duration,
            )
            if ranked_start_date < _today():
                return [
                    JSONResponse(
                        {"error": "Pick a start date in the future."},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]

        fhir_base_url = self.secrets.get("CANVAS_FHIR_BASE_URL", "")
        instance_url = self.secrets.get("CANVAS_INSTANCE_URL", fhir_base_url)
        client_id = self.secrets.get("CANVAS_OAUTH_CLIENT_ID", "")
        client_secret = self.secrets.get("CANVAS_OAUTH_CLIENT_SECRET", "")

        try:
            token = acquire_token(instance_url, client_id, client_secret)

            if ranked_rule is not None and ranked_start_date is not None:
                ranked = providers_ranked_by_series_availability(
                    effective_state,
                    rule=ranked_rule,
                    start_date=ranked_start_date,
                    fhir_base_url=fhir_base_url,
                    access_token=token.access_token,
                    tz_offset_minutes=ranked_tz,
                    duration_minutes=ranked_duration,
                    now=_now(),
                )
                ranked_body: dict[str, Any] = {
                    "state": effective_state,
                    "ranking_basis": "series",
                    "providers": [
                        {
                            "id": p.id,
                            "full_name": p.full_name,
                            "npi_number": p.npi_number,
                            "series_available_count": p.series_available_count,
                            "series_total_count": p.series_total_count,
                            "best_hhmm": p.best_hhmm,
                            "has_capacity": p.has_capacity,
                            "tier": p.tier,
                        }
                        for p in ranked
                    ],
                    "state_missing": state_missing,
                }
                if state_missing:
                    ranked_body["message"] = result.error
                return [JSONResponse(ranked_body, status_code=HTTPStatus.OK)]

            location = PracticeLocation.objects.filter(active=True).first()
            location_id = str(location.id) if location else ""

            provider_list = licensed_providers_for_state(
                effective_state,
                fhir_base_url=fhir_base_url,
                access_token=token.access_token,
                location_id=location_id,
            )
        except (RuntimeError, ValueError, RequestException) as exc:
            return [_backend_error_response(exc)]

        body: dict[str, Any] = {
            "state": effective_state,
            "ranking_basis": "load",
            "providers": [
                {
                    "id": p.id,
                    "full_name": p.full_name,
                    "npi_number": p.npi_number,
                    "pct_filled": p.pct_filled,
                    "filled_count": p.filled_count,
                    "free_count": p.free_count,
                    "total_count": p.total_count,
                    "has_capacity": p.has_capacity,
                    "appointments_last_30_days": p.appointments_last_30_days,
                    "upcoming_7_days": p.upcoming_7_days,
                    "tier": p.tier,
                }
                for p in provider_list
            ],
            "state_missing": state_missing,
        }
        if state_missing:
            body["message"] = result.error

        return [
            JSONResponse(
                body,
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/patients")
    def patients(self) -> list[Response | Effect]:
        query = self.request.query_params.get("q", "").strip()
        if len(query) < 2:
            return [JSONResponse({"patients": []}, status_code=HTTPStatus.OK)]

        from django.db.models import Q

        results = Patient.objects.filter(
            Q(first_name__icontains=query) | Q(last_name__icontains=query),
            active=True,
        ).prefetch_related("addresses")[:20]

        return [
            JSONResponse(
                {
                    "patients": [
                        {
                            "id": str(p.id),
                            "full_name": f"{p.first_name} {p.last_name}",
                            "birth_date": p.birth_date.isoformat() if p.birth_date else "",
                            "state_code": _state_code_for_patient(p),
                        }
                        for p in results
                    ]
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/note-types")
    def note_types(self) -> list[Response | Effect]:
        scheduleable_types = NoteType.objects.filter(
            category="encounter",
            is_scheduleable=True,
        )
        default_duration = _resolve_default_duration_minutes(self.secrets)
        return [
            JSONResponse(
                {
                    "note_types": [
                        {
                            "id": str(nt.id),
                            "name": nt.name,
                        }
                        for nt in scheduleable_types
                    ],
                    "default_duration_minutes": default_duration,
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/availability")
    def availability(self) -> list[Response | Effect]:
        qp = self.request.query_params
        provider_id = qp.get("provider_id", "")
        cadence = qp.get("cadence", "weekly")
        start_date_str = qp.get("start_date", "")
        occurrences_str = qp.get("occurrences", "12")

        if not provider_id or not start_date_str:
            return [
                JSONResponse(
                    {"error": "Pick a provider and a start date before continuing."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        staff = Staff.objects.filter(id=provider_id).first()
        if not staff:
            return [
                JSONResponse(
                    {"error": "That provider is no longer available. Pick another."},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        try:
            start_date = date.fromisoformat(start_date_str)
            occurrences = min(int(occurrences_str), MAX_OCCURRENCES)
            rule = from_legacy_cadence(cadence, occurrences)
        except (ValueError, TypeError, RecurrenceValidationError):
            return [
                JSONResponse(
                    {"error": "We could not read those inputs. Refresh the modal."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if start_date < _today():
            return [
                JSONResponse(
                    {"error": "Pick a start date in the future."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        fhir_base_url = self.secrets.get("CANVAS_FHIR_BASE_URL", "")
        instance_url = self.secrets.get("CANVAS_INSTANCE_URL", fhir_base_url)
        client_id = self.secrets.get("CANVAS_OAUTH_CLIENT_ID", "")
        client_secret = self.secrets.get("CANVAS_OAUTH_CLIENT_SECRET", "")

        try:
            token = acquire_token(instance_url, client_id, client_secret)

            analysis = analyse_recurrence(
                fhir_base_url=fhir_base_url,
                access_token=token.access_token,
                provider_id=str(staff.id),
                rule=rule,
                start_date=start_date,
                now=_now(),
            )
        except (RuntimeError, ValueError, RequestException) as exc:
            return [_backend_error_response(exc)]

        return [
            JSONResponse(
                {
                    "slots": [
                        {
                            "occurrence_date": s.occurrence_date.isoformat(),
                            "available_times": [
                                {"start": t.start, "end": t.end}
                                for t in s.available_times
                            ],
                            "is_available": s.is_available,
                        }
                        for s in analysis.slots
                    ],
                    "available_count": analysis.available_count,
                    "total_count": analysis.total_count,
                    "availability_pct": analysis.availability_pct,
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/available-times")
    def available_times(self) -> list[Response | Effect]:
        """Return FHIR-sourced available time slots for a provider on a single date."""
        qp = self.request.query_params
        provider_id = qp.get("provider_id", "")
        date_str = qp.get("date", "")
        try:
            tz_offset_minutes = int(qp.get("tz_offset", 0))
        except (TypeError, ValueError):
            return [
                JSONResponse(
                    {"error": "We could not read your time zone. Refresh the modal."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if not provider_id or not date_str:
            return [
                JSONResponse(
                    {"error": "Pick a provider and a date before continuing."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        staff = Staff.objects.filter(id=provider_id).first()
        if not staff:
            return [
                JSONResponse(
                    {"error": "That provider is no longer available. Pick another."},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            return [
                JSONResponse(
                    {"error": "That date is not valid. Pick a date from the calendar."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        fhir_base_url = self.secrets.get("CANVAS_FHIR_BASE_URL", "")
        instance_url = self.secrets.get("CANVAS_INSTANCE_URL", fhir_base_url)
        client_id = self.secrets.get("CANVAS_OAUTH_CLIENT_ID", "")
        client_secret = self.secrets.get("CANVAS_OAUTH_CLIENT_SECRET", "")

        from scheduling_modal_with_recurring_support.services.availability import (
            _check_slot,
            _resolve_schedule_id,
        )

        try:
            token = acquire_token(instance_url, client_id, client_secret)

            schedule_id = _resolve_schedule_id(
                fhir_base_url, token.access_token, str(staff.id)
            )

            slot_avail = _check_slot(
                fhir_base_url, token.access_token, schedule_id, target_date
            )
        except (RuntimeError, ValueError, RequestException) as exc:
            return [_backend_error_response(exc)]

        client_tz = timezone(timedelta(minutes=-tz_offset_minutes))
        times: list[dict[str, str]] = []
        for t in slot_avail.available_times:
            local_hhmm = _fhir_to_local_hhmm(t.start, client_tz)
            times.append({"hhmm": local_hhmm, "start": t.start, "end": t.end})

        return [
            JSONResponse(
                {"date": date_str, "times": times},
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/candidate-times")
    def candidate_times(self) -> list[Response | Effect]:
        """Return per candidate start time aggregated availability across the recurrence."""
        qp = self.request.query_params
        provider_id = qp.get("provider_id", "")
        cadence = qp.get("cadence", "weekly")
        start_date_str = qp.get("start_date", "")
        occurrences_str = qp.get("occurrences", "1")
        try:
            tz_offset_minutes = int(qp.get("tz_offset", 0))
        except (TypeError, ValueError):
            return [
                JSONResponse(
                    {"error": "We could not read your time zone. Refresh the modal."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if not provider_id or not start_date_str:
            return [
                JSONResponse(
                    {"error": "Pick a provider and a start date before continuing."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        staff = Staff.objects.filter(id=provider_id).first()
        if not staff:
            return [
                JSONResponse(
                    {"error": "That provider is no longer available. Pick another."},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        try:
            start_date = date.fromisoformat(start_date_str)
            occurrences = min(int(occurrences_str), MAX_OCCURRENCES)
            rule = from_legacy_cadence(cadence, occurrences)
        except (ValueError, TypeError, RecurrenceValidationError):
            return [
                JSONResponse(
                    {"error": "We could not read those inputs. Refresh the modal."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if start_date < _today():
            return [
                JSONResponse(
                    {"error": "Pick a start date in the future."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        fhir_base_url = self.secrets.get("CANVAS_FHIR_BASE_URL", "")
        instance_url = self.secrets.get("CANVAS_INSTANCE_URL", fhir_base_url)
        client_id = self.secrets.get("CANVAS_OAUTH_CLIENT_ID", "")
        client_secret = self.secrets.get("CANVAS_OAUTH_CLIENT_SECRET", "")

        try:
            token = acquire_token(instance_url, client_id, client_secret)

            aggregates = aggregate_by_candidate_time(
                fhir_base_url=fhir_base_url,
                access_token=token.access_token,
                provider_id=str(staff.id),
                rule=rule,
                start_date=start_date,
                tz_offset_minutes=tz_offset_minutes,
                now=_now(),
            )
        except (RuntimeError, ValueError, RequestException) as exc:
            return [_backend_error_response(exc)]

        return [
            JSONResponse(
                {
                    "date": start_date_str,
                    "candidate_times": [
                        {
                            "hhmm": a.hhmm,
                            "available_count": a.available_count,
                            "total_count": a.total_count,
                            "availability_pct": a.availability_pct,
                        }
                        for a in aggregates
                    ],
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/candidate-first-dates")
    def candidate_first_dates(self) -> list[Response | Effect]:
        """Return per candidate first date scores across a search window.

        Body carries the recurrence rule (canonical flat shape under
        `recurrence`, or legacy `cadence` plus `occurrences` during the
        transitional release), the search window bounds, and an optional
        timezone offset. Each candidate first date in the window is scored
        by how many of its projected occurrences land on free slots.
        """
        body: dict[str, Any] = self.request.json()
        provider_id = body.get("provider_id", "")
        patient_id = body.get("patient_id", "")
        window_start_str = body.get("search_window_start", "")
        window_end_str = body.get("search_window_end", "")

        # The endpoint serves two bases for the calendar badge. The original
        # per provider basis scores one provider's series across the window.
        # The provider agnostic basis, the when before who direction, counts
        # how many candidate providers can cover the full series from each
        # day. A provider_id selects the first, a
        # patient_id with no provider_id selects the second. The agnostic
        # branch is dormant until the Phase 3 reorder wires the frontend to
        # call the calendar before a provider is chosen.
        if not window_start_str or not window_end_str or (
            not provider_id and not patient_id
        ):
            return [
                JSONResponse(
                    {"error": "Pick a provider and a date range before continuing."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        # Resolve identity before validating the window, so a stale provider or
        # an unknown patient surfaces as a 404 rather than being masked by a
        # window error. The per provider branch needs the staff row, the
        # agnostic branch needs the patient state for the license filter.
        staff = None
        patient_state: PatientStateResult | None = None
        if provider_id:
            staff = Staff.objects.filter(id=provider_id).first()
            if not staff:
                return [
                    JSONResponse(
                        {"error": "That provider is no longer available. Pick another."},
                        status_code=HTTPStatus.NOT_FOUND,
                    )
                ]
        else:
            patient_state = _resolve_patient_state(patient_id)
            if not patient_state.state and patient_state.not_found:
                return [
                    JSONResponse(
                        {"error": patient_state.error},
                        status_code=HTTPStatus.NOT_FOUND,
                    )
                ]

        try:
            window_start = date.fromisoformat(window_start_str)
            window_end = date.fromisoformat(window_end_str)
            rule = _resolve_recurrence_rule(body)
        except (ValueError, TypeError, RecurrenceValidationError):
            return [
                JSONResponse(
                    {"error": "We could not read those inputs. Refresh the modal."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        today = _today()
        if window_start < today:
            return [
                JSONResponse(
                    {"error": "Pick a start date in the future."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        if window_end < window_start:
            return [
                JSONResponse(
                    {"error": "The end date must be on or after the start date."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        if (window_end - window_start).days + 1 > CANDIDATE_FIRST_DATES_WINDOW_CAP_DAYS:
            return [
                JSONResponse(
                    {"error": f"Pick a range of {CANDIDATE_FIRST_DATES_WINDOW_CAP_DAYS} days or less."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        fhir_base_url = self.secrets.get("CANVAS_FHIR_BASE_URL", "")
        instance_url = self.secrets.get("CANVAS_INSTANCE_URL", fhir_base_url)
        client_id = self.secrets.get("CANVAS_OAUTH_CLIENT_ID", "")
        client_secret = self.secrets.get("CANVAS_OAUTH_CLIENT_SECRET", "")

        tenant_default = _resolve_default_duration_minutes(self.secrets)
        duration_minutes = _parse_request_duration_minutes(
            body.get("duration_minutes"),
            tenant_default,
        )

        # Provider agnostic basis. With no provider chosen yet the calendar
        # badge counts how many candidate providers can cover the full series
        # from each day, the when before who direction. State resolution
        # mirrors /providers, a two letter override drives the license filter
        # for this request only, a missing state falls through to the
        # unfiltered candidate set with a state_missing flag.
        if staff is None and patient_state is not None:
            override = body.get("state", "").strip().upper()
            if len(override) != 2 or not override.isalpha():
                override = ""
            effective_state = override or patient_state.state
            state_missing = not effective_state
            tz_offset_minutes = int(body.get("tz_offset", 0) or 0)

            try:
                token = acquire_token(instance_url, client_id, client_secret)

                coverage = providers_covering_series_by_first_date(
                    effective_state,
                    rule=rule,
                    window_start=window_start,
                    window_end=window_end,
                    fhir_base_url=fhir_base_url,
                    access_token=token.access_token,
                    tz_offset_minutes=tz_offset_minutes,
                    duration_minutes=duration_minutes,
                    now=_now(),
                )
            except (RuntimeError, ValueError, RequestException) as exc:
                return [_backend_error_response(exc)]

            agnostic_body: dict[str, Any] = {
                "basis": "series_coverage",
                "state": effective_state,
                "state_missing": state_missing,
                "candidates": [
                    {
                        "first_date": c.first_date.isoformat(),
                        "covering_count": c.covering_count,
                        "candidate_count": c.candidate_count,
                    }
                    for c in coverage
                ],
                "search_window": {
                    "start": window_start.isoformat(),
                    "end": window_end.isoformat(),
                },
            }
            if state_missing:
                agnostic_body["message"] = patient_state.error

            return [JSONResponse(agnostic_body, status_code=HTTPStatus.OK)]

        assert staff is not None  # narrowed by the identity resolution above

        tz_offset_minutes = int(body.get("tz_offset", 0) or 0)

        try:
            token = acquire_token(instance_url, client_id, client_secret)

            aggregates = aggregate_by_first_date(
                fhir_base_url=fhir_base_url,
                access_token=token.access_token,
                provider_id=str(staff.id),
                rule=rule,
                window_start=window_start,
                window_end=window_end,
                duration_minutes=duration_minutes,
                tz_offset_minutes=tz_offset_minutes,
                now=_now(),
            )
        except (RuntimeError, ValueError, RequestException) as exc:
            return [_backend_error_response(exc)]

        return [
            JSONResponse(
                {
                    "basis": "single_provider",
                    "candidates": [
                        {
                            "first_date": a.first_date.isoformat(),
                            "available_count": a.available_count,
                            "total_count": a.total_count,
                            "availability_pct": a.availability_pct,
                            "occurrence_dates": [d.isoformat() for d in a.occurrence_dates],
                        }
                        for a in aggregates
                    ],
                    "search_window": {
                        "start": window_start.isoformat(),
                        "end": window_end.isoformat(),
                    },
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/free-slots")
    def free_slots(self) -> list[Response | Effect]:
        """Return upcoming free slots for the provider across a date span.

        Used by the single visit case where the user picks a slot directly
        rather than picking a date first. Slots are returned in start-time
        order, grouped client side by date for the list UI. The endpoint
        passes `limit + 1` to the iterator so it can detect truncation.
        """
        qp = self.request.query_params
        provider_id = qp.get("provider_id", "")
        window_start_str = qp.get("search_window_start", "")
        window_end_str = qp.get("search_window_end", "")
        try:
            tz_offset_minutes = int(qp.get("tz_offset", 0))
        except (TypeError, ValueError):
            return [
                JSONResponse(
                    {"error": "We could not read your time zone. Refresh the modal."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            limit_raw = int(qp.get("limit", FREE_SLOTS_DEFAULT_LIMIT))
        except (TypeError, ValueError):
            return [
                JSONResponse(
                    {"error": "We could not read the result limit. Refresh the modal."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        limit = max(1, min(limit_raw, FREE_SLOTS_MAX_LIMIT))

        if not provider_id or not window_start_str or not window_end_str:
            return [
                JSONResponse(
                    {"error": "Pick a provider and a date range before continuing."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        staff = Staff.objects.filter(id=provider_id).first()
        if not staff:
            return [
                JSONResponse(
                    {"error": "That provider is no longer available. Pick another."},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        try:
            window_start = date.fromisoformat(window_start_str)
            window_end = date.fromisoformat(window_end_str)
        except ValueError:
            return [
                JSONResponse(
                    {"error": "We could not read those inputs. Refresh the modal."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        today = _today()
        if window_start < today:
            return [
                JSONResponse(
                    {"error": "Pick a start date in the future."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        if window_end < window_start:
            return [
                JSONResponse(
                    {"error": "The end date must be on or after the start date."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        if (window_end - window_start).days + 1 > CANDIDATE_FIRST_DATES_WINDOW_CAP_DAYS:
            return [
                JSONResponse(
                    {"error": f"Pick a range of {CANDIDATE_FIRST_DATES_WINDOW_CAP_DAYS} days or less."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        fhir_base_url = self.secrets.get("CANVAS_FHIR_BASE_URL", "")
        instance_url = self.secrets.get("CANVAS_INSTANCE_URL", fhir_base_url)
        client_id = self.secrets.get("CANVAS_OAUTH_CLIENT_ID", "")
        client_secret = self.secrets.get("CANVAS_OAUTH_CLIENT_SECRET", "")

        client_tz = timezone(timedelta(minutes=-tz_offset_minutes))

        try:
            token = acquire_token(instance_url, client_id, client_secret)

            # Pull limit + 1 from the iterator so the endpoint can detect when
            # truncation hides at least one more slot. The response trims to
            # limit before serialising.
            collected = list(
                iter_free_slots(
                    fhir_base_url=fhir_base_url,
                    access_token=token.access_token,
                    provider_id=str(staff.id),
                    window_start=window_start,
                    window_end=window_end,
                    limit=limit + 1,
                )
            )
        except (RuntimeError, ValueError, RequestException) as exc:
            return [_backend_error_response(exc)]

        truncated = len(collected) > limit
        slots_out: list[dict[str, str]] = []
        for free in collected[:limit]:
            local_hhmm = _fhir_to_local_hhmm(free.start, client_tz)
            slot_date = free.start.split("T", 1)[0]
            slots_out.append(
                {
                    "date": slot_date,
                    "hhmm": local_hhmm,
                    "start": free.start,
                    "end": free.end,
                }
            )

        return [
            JSONResponse(
                {
                    "slots": slots_out,
                    "search_window": {
                        "start": window_start.isoformat(),
                        "end": window_end.isoformat(),
                    },
                    "truncated": truncated,
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/availability-window")
    def availability_window(self) -> list[Response | Effect]:
        """Return a Fumage Slot bundle bucketed by local date for a window.

        Backs the per row date combobox in the scheduling modal. One round
        trip covers up to twenty one days so the row level pickers do not
        each fan out a separate per day Slot lookup.
        """
        qp = self.request.query_params
        provider_id = qp.get("provider_id", "")
        window_start_str = qp.get("window_start", "")
        window_end_str = qp.get("window_end", "")
        try:
            tz_offset_minutes = int(qp.get("tz_offset", 0))
        except (TypeError, ValueError):
            return [
                JSONResponse(
                    {"error": "We could not read your time zone. Refresh the modal."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if not provider_id or not window_start_str or not window_end_str:
            return [
                JSONResponse(
                    {"error": "Pick a provider and a date range before continuing."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        staff = Staff.objects.filter(id=provider_id).first()
        if not staff:
            return [
                JSONResponse(
                    {"error": "That provider is no longer available. Pick another."},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        try:
            window_start = date.fromisoformat(window_start_str)
            window_end = date.fromisoformat(window_end_str)
        except ValueError:
            return [
                JSONResponse(
                    {"error": "We could not read those inputs. Refresh the modal."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if window_end < window_start:
            return [
                JSONResponse(
                    {"error": "The end date must be on or after the start date."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        if (window_end - window_start).days + 1 > AVAILABILITY_WINDOW_CAP_DAYS:
            return [
                JSONResponse(
                    {"error": f"Pick a range of {AVAILABILITY_WINDOW_CAP_DAYS} days or less."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        today = _today()
        if window_start < today:
            window_start = today
        if window_end < window_start:
            return [
                JSONResponse(
                    {
                        "window": {
                            "start": window_start.isoformat(),
                            "end": window_end.isoformat(),
                        },
                        "by_date": {},
                    },
                    status_code=HTTPStatus.OK,
                )
            ]

        fhir_base_url = self.secrets.get("CANVAS_FHIR_BASE_URL", "")
        instance_url = self.secrets.get("CANVAS_INSTANCE_URL", fhir_base_url)
        client_id = self.secrets.get("CANVAS_OAUTH_CLIENT_ID", "")
        client_secret = self.secrets.get("CANVAS_OAUTH_CLIENT_SECRET", "")

        tenant_default = _resolve_default_duration_minutes(self.secrets)
        duration_minutes = _parse_request_duration_minutes(
            qp.get("duration_minutes"),
            tenant_default,
        )

        try:
            token = acquire_token(instance_url, client_id, client_secret)

            bucketed = lookup_window(
                fhir_base_url=fhir_base_url,
                access_token=token.access_token,
                provider_id=str(staff.id),
                window_start=window_start,
                window_end=window_end,
                tz_offset_minutes=tz_offset_minutes,
                duration_minutes=duration_minutes,
            )
        except (RuntimeError, ValueError, RequestException) as exc:
            return [_backend_error_response(exc)]

        # Alongside the free slots, fetch the provider's booked times across the
        # same window so a moved occurrence can tell an already taken time
        # (provider already booked) from a closed one (outside hours). Bucket by
        # local date and hhmm so the frontend compares against its row time
        # directly. FHIR returns only free slots, so this DB read is the only
        # source of the booked signal for the row date picker.
        client_tz = timezone(timedelta(minutes=-tz_offset_minutes))
        range_start = datetime.combine(
            window_start, datetime.min.time(), tzinfo=client_tz
        ).astimezone(timezone.utc)
        range_end = datetime.combine(
            window_end + timedelta(days=1), datetime.min.time(), tzinfo=client_tz
        ).astimezone(timezone.utc)
        booked_by_date: dict[str, list[str]] = {}
        for booked_start in (
            AppointmentModel.objects.filter(
                provider__id=str(staff.id),
                start_time__gte=range_start,
                start_time__lt=range_end,
            )
            .exclude(status__in=["cancelled", "entered_in_error"])
            .values_list("start_time", flat=True)
        ):
            local_dt = booked_start.astimezone(client_tz)
            date_key = local_dt.date().isoformat()
            booked_by_date.setdefault(date_key, []).append(local_dt.strftime("%H:%M"))

        return [
            JSONResponse(
                {
                    "window": {
                        "start": window_start.isoformat(),
                        "end": window_end.isoformat(),
                    },
                    "by_date": bucketed,
                    "booked_by_date": booked_by_date,
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/check-slots")
    def check_slots(self) -> list[Response | Effect]:
        """Check whether each requested slot is free. Return per-slot availability with alternatives."""
        body: dict[str, Any] = self.request.json()
        provider_id = body.get("provider_id", "")
        slots: list[dict[str, str]] = body.get("slots", [])
        try:
            tz_offset_minutes = int(body.get("tz_offset", 0))
        except (TypeError, ValueError):
            return [
                JSONResponse(
                    {"error": "We could not read your time zone. Refresh the modal."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if not provider_id or not slots:
            return [
                JSONResponse(
                    {"error": "Pick a provider and at least one slot before checking."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        staff = Staff.objects.filter(id=provider_id).first()
        if not staff:
            return [
                JSONResponse(
                    {"error": "That provider is no longer available. Pick another."},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        fhir_base_url = self.secrets.get("CANVAS_FHIR_BASE_URL", "")
        instance_url = self.secrets.get("CANVAS_INSTANCE_URL", fhir_base_url)
        client_id = self.secrets.get("CANVAS_OAUTH_CLIENT_ID", "")
        client_secret = self.secrets.get("CANVAS_OAUTH_CLIENT_SECRET", "")

        from scheduling_modal_with_recurring_support.services.availability import (
            SlotAvailability,
            _prefill_memo_for_range,
            _resolve_schedule_id,
        )

        try:
            token = acquire_token(instance_url, client_id, client_secret)

            schedule_id = _resolve_schedule_id(
                fhir_base_url, token.access_token, str(staff.id)
            )
        except (RuntimeError, ValueError, RequestException) as exc:
            return [_backend_error_response(exc)]

        client_tz = timezone(timedelta(minutes=-tz_offset_minutes))

        # Collect the union of slot dates so the FHIR availability lookup runs
        # in one prefilled bundle rather than per slot. A twelve occurrence
        # recurrence used to cost twelve sequential FHIR round trips. This
        # collapses to one bundle that covers the spanning date range.
        unique_dates: set[date] = set()
        for slot in slots:
            slot_date_str = slot.get("date", "")
            try:
                unique_dates.add(date.fromisoformat(slot_date_str))
            except ValueError:
                continue

        tenant_default = _resolve_default_duration_minutes(self.secrets)
        duration_minutes = _parse_request_duration_minutes(
            body.get("duration_minutes"),
            tenant_default,
        )

        memo: dict[date, SlotAvailability] = {}
        if unique_dates:
            try:
                _prefill_memo_for_range(
                    memo,
                    fhir_base_url,
                    token.access_token,
                    schedule_id,
                    unique_dates,
                    duration_minutes,
                    tz_offset_minutes,
                )
            except (RuntimeError, ValueError, RequestException) as exc:
                return [_backend_error_response(exc)]

        # Pass 1: read each slot from the prefilled memo and build the results
        # list. For every slot we also stash its UTC datetime, whether FHIR
        # offered it free, and the other free times on that day, so a single DB
        # query in pass 2 can mark any requested time as booked, free or not.
        # A time FHIR never offered that the DB shows as taken is the ordinary
        # already booked case a recurrence hits when an occurrence lands on a
        # full day, which used to read as outside hours.
        results: list[dict[str, Any]] = []
        slot_meta: list[tuple[int, "datetime | None", bool, list[dict[str, str]]]] = []

        for slot in slots:
            slot_date_str = slot.get("date", "")
            slot_time_str = slot.get("start_time", "")
            try:
                slot_date = date.fromisoformat(slot_date_str)
            except ValueError:
                results.append({
                    "date": slot_date_str,
                    "start_time": slot_time_str,
                    "is_free": False,
                    "reason": "outside_hours",
                    "available_times": [],
                })
                continue

            slot_avail = memo.get(slot_date) or SlotAvailability(
                occurrence_date=slot_date,
                available_times=[],
                is_available=False,
            )

            is_fhir_free = False
            if slot_avail.is_available:
                for t in slot_avail.available_times:
                    if _fhir_to_local_hhmm(t.start, client_tz) == slot_time_str:
                        is_fhir_free = True
                        break

            other_times = [
                {"start": t.start, "end": t.end}
                for t in slot_avail.available_times
                if _fhir_to_local_hhmm(t.start, client_tz) != slot_time_str
            ]

            # The full free list for the day, the committed time included. A free
            # row returns this so its times paint from the first response instead
            # of an empty list deferred to a second lookup. An outside hours row
            # has no committed time among the free slots, so this equals
            # other_times for it.
            all_free_times = [
                {"start": t.start, "end": t.end}
                for t in slot_avail.available_times
            ]

            utc_dt: datetime | None = None
            try:
                user_dt = datetime.combine(
                    slot_date,
                    datetime.strptime(slot_time_str, "%H:%M").time(),
                    tzinfo=client_tz,
                )
                utc_dt = user_dt.astimezone(timezone.utc)
            except ValueError:
                utc_dt = None

            slot_meta.append((len(results), utc_dt, is_fhir_free, other_times))
            results.append({
                "date": slot_date_str,
                "start_time": slot_time_str,
                "is_free": is_fhir_free,
                "reason": "free" if is_fhir_free else "outside_hours",
                "available_times": all_free_times,
            })

        # Pass 2: one DB query over every requested time, free or not, finds the
        # times that are actually booked. A booked time reads booked and never
        # free. This catches both the race where FHIR offered a slot the DB
        # shows taken and the ordinary occurrence that landed on a full day
        # where FHIR offered nothing.
        candidate_times = [utc for _, utc, _, _ in slot_meta if utc is not None]
        if candidate_times:
            booked = set(
                AppointmentModel.objects.filter(
                    provider__id=provider_id,
                    start_time__in=candidate_times,
                )
                .exclude(status__in=["cancelled", "entered_in_error"])
                .values_list("start_time", flat=True)
            )
            for idx, utc_dt, _is_fhir_free, other_times in slot_meta:
                if utc_dt is not None and utc_dt in booked:
                    results[idx]["is_free"] = False
                    results[idx]["reason"] = "booked"
                    results[idx]["available_times"] = other_times

        free_count = sum(1 for r in results if r["is_free"])
        return [
            JSONResponse(
                {
                    "results": results,
                    "free_count": free_count,
                    "total_count": len(results),
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/book")
    def book(self) -> list[Response | Effect]:
        body: dict[str, Any] = self.request.json()
        now = _now()
        result = _validate_booking_request(body, now, self.secrets)
        if isinstance(result, JSONResponse):
            return [result]
        _staff, location_id, parsed_datetimes, duration_minutes = result

        patient_id = body.get("patient_id", "")
        provider_id = body.get("provider_id", "")
        note_type_id = body.get("note_type_id", "")

        effects: list[Effect] = []
        for dt in parsed_datetimes:
            appointment = AppointmentEffect(
                appointment_note_type_id=note_type_id,
                patient_id=patient_id,
                provider_id=provider_id,
                start_time=dt,
                duration_minutes=duration_minutes,
                practice_location_id=location_id,
            )
            effects.append(appointment.create())

        bust_filled_pct(provider_id)

        return [
            JSONResponse(
                {"booked": len(effects), "status": "ok"},
                status_code=HTTPStatus.CREATED,
            ),
            *effects,
        ]

    @api.post("/book/validate")
    def validate_booking(self) -> list[Response | Effect]:
        body: dict[str, Any] = self.request.json()
        now = _now()
        result = _validate_booking_request(body, now, self.secrets)
        if isinstance(result, JSONResponse):
            return [result]
        _, _, parsed, _ = result
        return [
            JSONResponse(
                {"ok": True, "checked": len(parsed)},
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/book/verify")
    def verify_booking(self) -> list[Response | Effect]:
        """Read appointments back after a book to confirm the effects landed.

        /book returns 201 with the effect list before Canvas interprets the
        effects, so a downstream effect rejection never reaches the modal. This
        endpoint reads the appointments back from the database so the
        completion paths can confirm each requested time actually persisted
        before showing success. It reuses the booked detection from
        /check-slots, one AppointmentModel query filtered by provider and
        start_time__in over the parsed UTC datetimes, excluding cancelled and
        entered_in_error. Returns the requested times split into present and
        missing. An unparseable pair is reported missing rather than dropped.
        """
        body: dict[str, Any] = self.request.json()
        provider_id = body.get("provider_id", "")
        appointments: list[dict[str, str]] = body.get("appointments", [])
        try:
            tz_offset_minutes = int(body.get("tz_offset", 0))
        except (TypeError, ValueError):
            return [
                JSONResponse(
                    {"error": "We could not read your time zone. Refresh the modal."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if not provider_id or not appointments:
            return [
                JSONResponse(
                    {"error": "Pick a provider and at least one appointment to verify."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        client_tz = timezone(timedelta(minutes=-tz_offset_minutes))

        # Parse each requested appointment to its UTC datetime, keeping the
        # client's own date and start_time so the response matches back to rows
        # exactly. A pair that does not parse is paired with None and falls into
        # missing below.
        parsed: list[tuple[dict[str, str], "datetime | None"]] = []
        for appt in appointments:
            appt_date_str = appt.get("date", "")
            appt_time_str = appt.get("start_time", "")
            try:
                appt_date = date.fromisoformat(appt_date_str)
                appt_time = datetime.strptime(appt_time_str, "%H:%M").time()
            except ValueError:
                parsed.append((appt, None))
                continue
            local_dt = datetime.combine(appt_date, appt_time, tzinfo=client_tz)
            parsed.append((appt, local_dt.astimezone(timezone.utc)))

        candidate_times = [dt for _, dt in parsed if dt is not None]
        booked: set[datetime] = set()
        if candidate_times:
            booked = set(
                AppointmentModel.objects.filter(
                    provider__id=provider_id,
                    start_time__in=candidate_times,
                )
                .exclude(status__in=["cancelled", "entered_in_error"])
                .values_list("start_time", flat=True)
            )

        present: list[dict[str, str]] = []
        missing: list[dict[str, str]] = []
        for appt, dt in parsed:
            entry = {
                "date": appt.get("date", ""),
                "start_time": appt.get("start_time", ""),
            }
            if dt is not None and dt in booked:
                present.append(entry)
            else:
                missing.append(entry)

        return [
            JSONResponse(
                {
                    "present": present,
                    "missing": missing,
                    "all_present": len(missing) == 0,
                },
                status_code=HTTPStatus.OK,
            )
        ]


# ---- Booking helpers ----


def _validate_booking_request(
    body: dict[str, Any],
    now: datetime,
    secrets: dict[str, str],
) -> "JSONResponse | tuple[Any, str, list[datetime], int]":
    patient_id = body.get("patient_id", "")
    provider_id = body.get("provider_id", "")
    note_type_id = body.get("note_type_id", "")
    appointments: list[dict[str, str]] = body.get("appointments", [])
    try:
        tz_offset_minutes = int(body.get("tz_offset", 0))
    except (TypeError, ValueError):
        return JSONResponse(
            {"error": "We could not read your time zone. Refresh the modal."},
            status_code=HTTPStatus.BAD_REQUEST,
        )

    if not patient_id or not provider_id or not note_type_id:
        return JSONResponse(
            {"error": "Pick a patient, a provider, and a note type before booking."},
            status_code=HTTPStatus.BAD_REQUEST,
        )

    if not appointments:
        return JSONResponse(
            {"error": "At least one appointment is required."},
            status_code=HTTPStatus.BAD_REQUEST,
        )

    staff = Staff.objects.filter(id=provider_id).first()
    if not staff:
        return JSONResponse(
            {"error": "That provider is no longer available. Pick another."},
            status_code=HTTPStatus.NOT_FOUND,
        )

    # Pre flight NPI guard. CREATE_APPOINTMENT requires the provider's NPI, and
    # an effect rejected for a blank NPI is invisible to the modal because the
    # effect interpreter runs after /book has already returned 201. Reject the
    # book upfront so the silent failure becomes a clear blocked book. Both
    # /book and /book/validate run through here, so this surfaces on the
    # existing error paths with no extra frontend wiring.
    if not (staff.npi_number or "").strip():
        return JSONResponse(
            {
                "error": "This provider has no NPI on file, so appointments "
                "cannot be created. Ask your administrator to add the "
                "provider's NPI, then pick the provider again.",
            },
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    location = PracticeLocation.objects.filter(active=True).first()
    location_id = str(location.id) if location else ""

    client_tz = timezone(timedelta(minutes=-tz_offset_minutes))
    parsed_datetimes: list[datetime] = []
    for i, appt in enumerate(appointments):
        appt_date_str = appt.get("date", "")
        appt_time_str = appt.get("start_time", "")
        if not appt_date_str or not appt_time_str:
            return JSONResponse(
                {"error": f"Appointment #{i + 1} is missing a date or time."},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        try:
            appt_date = date.fromisoformat(appt_date_str)
        except ValueError:
            return JSONResponse(
                {"error": f"Appointment #{i + 1} has an invalid date. Pick another date."},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        try:
            appt_time = datetime.strptime(appt_time_str, "%H:%M").time()
        except ValueError:
            return JSONResponse(
                {"error": f"Appointment #{i + 1} has an invalid time. Pick another time."},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        local_dt = datetime.combine(appt_date, appt_time, tzinfo=client_tz)
        dt = local_dt.astimezone(timezone.utc)
        if dt < now:
            return JSONResponse(
                {"error": f"Appointment #{i + 1} is in the past. Pick a future date and time."},
                status_code=HTTPStatus.BAD_REQUEST,
            )
        parsed_datetimes.append(dt)

    # Conflicts echo the client's own date and start_time values so the
    # frontend can match them back to rows exactly, and format them in the
    # browser's wall clock rather than receiving UTC strings.
    conflicts: list[dict[str, str]] = []
    if parsed_datetimes:
        range_start = min(parsed_datetimes)
        range_end = max(parsed_datetimes) + timedelta(minutes=1)
        booked_starts = set(
            AppointmentModel.objects.filter(
                provider__id=provider_id,
                start_time__gte=range_start,
                start_time__lt=range_end,
            )
            .exclude(status__in=["cancelled", "entered_in_error"])
            .values_list("start_time", flat=True)
        )
        conflicts = [
            {"date": appt.get("date", ""), "start_time": appt.get("start_time", "")}
            for appt, dt in zip(appointments, parsed_datetimes)
            if dt in booked_starts
        ]

    if conflicts:
        return JSONResponse(
            {
                "error": "Some times were just booked by someone else. Refresh availability and pick again.",
                "conflicts": conflicts,
            },
            status_code=HTTPStatus.CONFLICT,
        )

    tenant_default = _resolve_default_duration_minutes(secrets)
    duration_minutes = _parse_request_duration_minutes(
        body.get("duration_minutes"),
        tenant_default,
    )
    return (staff, location_id, parsed_datetimes, duration_minutes)


# ---- Helpers ----


def _resolve_recurrence_rule(body: dict[str, Any]) -> RecurrenceRule:
    """Pick the canonical recurrence rule from a request body.

    Prefers the new `recurrence` object when present. Falls back to the
    legacy `cadence` plus `occurrences` shape for the transitional release.
    Raises RecurrenceValidationError when neither is supplied or either
    fails validation.
    """
    if "recurrence" in body and body["recurrence"] is not None:
        return parse_recurrence(body["recurrence"])

    cadence = body.get("cadence")
    if cadence is None:
        raise RecurrenceValidationError(
            "request must carry recurrence (preferred) or cadence plus occurrences."
        )
    occurrences = body.get("occurrences", 1)
    if isinstance(occurrences, str):
        try:
            occurrences = int(occurrences)
        except ValueError as exc:
            raise RecurrenceValidationError(
                f"occurrences must be an integer, got {occurrences!r}"
            ) from exc
    return from_legacy_cadence(cadence, occurrences)


class PatientStateResult(NamedTuple):
    state: str
    error: str
    # True when the patient lookup itself failed. Routing in /providers uses
    # this flag to choose a 404 response without inspecting the error string.
    not_found: bool = False


def _state_code_for_patient(patient: Patient) -> str:
    """Resolve a patient's licensure state from the chart address.

    Prefers the home use address, then falls back to the first address on file,
    returning its two letter state code. Returns an empty string when no address
    carries a state. Reads `patient.addresses.all()` so a caller that
    prefetched the relation, like the patient search, pays no extra query per
    patient. Shared by the search result rows and `_resolve_patient_state`.
    """
    addresses = list(patient.addresses.all())
    home = next((a for a in addresses if a.use == "home"), None)
    if home and home.state_code:
        return home.state_code
    first_address = addresses[0] if addresses else None
    if first_address and first_address.state_code:
        return first_address.state_code
    return ""


def _resolve_patient_state(patient_id: str) -> PatientStateResult:
    if not patient_id:
        return PatientStateResult(
            state="",
            error="We could not identify the patient. Reopen the modal from the patient chart.",
        )
    patient = Patient.objects.filter(id=patient_id).first()
    if not patient:
        return PatientStateResult(
            state="",
            error="We could not find that patient. Reopen the modal and try again.",
            not_found=True,
        )
    state_code = _state_code_for_patient(patient)
    if state_code:
        return PatientStateResult(state=state_code, error="")
    return PatientStateResult(
        state="",
        error="This patient has no state on file. Pick a state to use, or continue without matching by license.",
    )


def _backend_error_response(exc: Exception) -> Response:
    """Translate OAuth and FHIR helper exceptions into a structured response.

    Logs the underlying detail through `log` for engineering, returns operator
    copy through the wire. Surfaces the missing FHIR Schedule case as 422 so
    the operator sees a configuration message instead of a generic backend
    failure.
    """
    log.error(f"scheduling backend error: {exc.__class__.__name__}: {exc}")
    if isinstance(exc, ValueError) and "No FHIR Schedule found for provider" in str(exc):
        return JSONResponse(
            {
                "error": "That provider is not configured for scheduling yet. Ask your administrator to set up working hours.",
            },
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    return JSONResponse(
        {
            "error": "We could not reach the scheduling backend. Try again in a moment, or contact your administrator if this keeps happening.",
        },
        status_code=HTTPStatus.BAD_GATEWAY,
    )


