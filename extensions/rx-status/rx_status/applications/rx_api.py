import json
import uuid
from datetime import datetime, timedelta
from http import HTTPStatus

from django.db.models import Q

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin, SimpleAPI, api
from canvas_sdk.v1.data.prescription import Prescription
from canvas_sdk.v1.data.staff import Staff
from canvas_sdk.v1.data.task import TaskLabel
from canvas_sdk.v1.data.team import Team

from logger import log

CACHE_RULES_KEY = "rx_status_notification_rules"

GENERIC_ERROR_BODY = {"error": "An internal error occurred"}

VALID_STATUSES = {
    "open",
    "pending",
    "ultimately-accepted",
    "error",
    "cancel-requested",
    "canceled",
    "cancel-denied",
    "received",
    "signed",
    "inqueue",
    "transmitted",
    "delivered",
}
VALID_DURATION_UNITS = {"h", "d"}
TASK_TITLE_MAX_LENGTH = 255


class RxApi(StaffSessionAuthMixin, SimpleAPI):
    """API for prescription status data and notification rule management."""

    @api.get("/prescriptions")
    def list_prescriptions(self) -> list[Response | Effect]:
        try:
            query_params = self.request.query_params
            page = int(query_params.get("page", 1))
            page_size = int(query_params.get("page_size", 50))

            prescriptions = (
                Prescription.objects.all()
                .select_related("patient", "prescriber", "medication", "note")
                .order_by("-written_date")
            )
            prescriptions = self._apply_filters(prescriptions, query_params)

            total = prescriptions.count()
            start = (page - 1) * page_size
            end = start + page_size
            page_qs = prescriptions[start:end]

            results = [self._serialize_prescription(rx) for rx in page_qs]
            total_pages = max(1, (total + page_size - 1) // page_size)

            return [
                JSONResponse(
                    {
                        "results": results,
                        "total": total,
                        "page": page,
                        "page_size": page_size,
                        "total_pages": total_pages,
                    },
                    status_code=HTTPStatus.OK,
                )
            ]

        except Exception as e:
            log.error(f"RxApi list_prescriptions error: {e}")
            return [
                JSONResponse(
                    GENERIC_ERROR_BODY,
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

    def _apply_filters(self, qs, query_params):
        status_filter = query_params.get("status")
        if status_filter:
            qs = qs.filter(status__in=status_filter.split(","))

        prescriber_filter = query_params.get("prescriber")
        if prescriber_filter:
            parts = prescriber_filter.rsplit(" ", 1)
            if len(parts) == 2:
                qs = qs.filter(
                    prescriber__first_name=parts[0],
                    prescriber__last_name=parts[1],
                )

        patient_search = query_params.get("patient")
        if patient_search:
            search = patient_search.strip()
            parts = search.split()
            if len(parts) >= 2:
                qs = qs.filter(
                    patient__first_name__icontains=parts[0],
                    patient__last_name__icontains=parts[-1],
                )
            else:
                qs = qs.filter(
                    Q(patient__first_name__icontains=search)
                    | Q(patient__last_name__icontains=search)
                )

        qs = self._apply_type_filter(qs, query_params.get("type"))

        date_from = query_params.get("date_from")
        if date_from:
            qs = qs.filter(written_date__gte=date_from)

        date_to = query_params.get("date_to")
        if date_to:
            try:
                end_date = datetime.strptime(date_to, "%Y-%m-%d").date() + timedelta(days=1)
                qs = qs.filter(written_date__lt=end_date)
            except ValueError:
                pass

        return qs

    def _apply_type_filter(self, qs, type_filter):
        if not type_filter:
            return qs
        if type_filter == "Refill":
            return qs.filter(is_refill=True, response_type__isnull=True)
        if type_filter == "Approve Refill":
            return qs.filter(is_refill=True, response_type__in=["A", "C"])
        if type_filter == "Deny Refill":
            return qs.filter(is_refill=True, response_type__in=["D", "N"])
        if type_filter == "Adjustment":
            return qs.filter(is_adjustment=True)
        if type_filter == "New Rx":
            return qs.filter(is_refill=False, is_adjustment=False)
        return qs

    def _serialize_prescription(self, rx):
        patient_name = ""
        patient_id = ""
        if rx.patient:
            patient_name = f"{rx.patient.first_name} {rx.patient.last_name}".strip()
            patient_id = str(rx.patient.id)

        prescriber_name = ""
        if rx.prescriber:
            prescriber_name = (
                f"{rx.prescriber.first_name} {rx.prescriber.last_name}".strip()
            )

        med_name = ""
        if rx.medication:
            coding = rx.medication.codings.first()
            if coding:
                med_name = coding.display or ""
            if not med_name:
                med_name = str(rx.medication)
        if not med_name and getattr(rx, "compound_medication", None):
            med_name = str(rx.compound_medication)

        status = str(rx.status) if rx.status else "unknown"

        response_code = str(rx.response_type) if rx.response_type else ""
        rx_type = "New Rx"
        if rx.is_refill:
            if response_code in ("D", "N"):
                rx_type = "Deny Refill"
            elif response_code in ("A", "C"):
                rx_type = "Approve Refill"
            else:
                rx_type = "Refill"
        elif rx.is_adjustment:
            rx_type = "Adjustment"

        written = rx.written_date.strftime("%Y-%m-%d") if rx.written_date else ""

        return {
            "patient_name": patient_name,
            "patient_id": patient_id,
            "med_name": med_name,
            "pharmacy": rx.pharmacy_name or "",
            "status": status,
            "rx_type": rx_type,
            "prescriber": prescriber_name,
            "written": written,
            "error_message": getattr(rx, "error_message", None) or "",
            "note_dbid": rx.note.dbid if rx.note else None,
        }

    @api.get("/filters")
    def get_filters(self) -> list[Response | Effect]:
        try:
            prescriber_rows = (
                Prescription.objects.exclude(prescriber__isnull=True)
                .values_list("prescriber__first_name", "prescriber__last_name")
                .distinct()
            )
            prescribers = sorted(
                {
                    f"{first or ''} {last or ''}".strip()
                    for first, last in prescriber_rows
                    if (first or last)
                }
            )

            status_rows = (
                Prescription.objects.exclude(status__isnull=True)
                .values_list("status", flat=True)
                .distinct()
            )
            statuses = sorted({str(s) for s in status_rows if s})

            return [
                JSONResponse(
                    {
                        "prescribers": prescribers,
                        "statuses": statuses,
                        "types": [
                            "New Rx",
                            "Refill",
                            "Approve Refill",
                            "Deny Refill",
                            "Adjustment",
                        ],
                    },
                    status_code=HTTPStatus.OK,
                )
            ]

        except Exception as e:
            log.error(f"RxApi get_filters error: {e}")
            return [
                JSONResponse(
                    GENERIC_ERROR_BODY,
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

    # --- Notification Rules ---

    @api.get("/rules")
    def list_rules(self) -> list[Response | Effect]:
        try:
            cache = get_cache()
            rules = cache.get(CACHE_RULES_KEY) or []
            if isinstance(rules, str):
                rules = json.loads(rules)
            return [JSONResponse({"rules": rules}, status_code=HTTPStatus.OK)]
        except Exception as e:
            log.error(f"RxApi list_rules error: {e}")
            return [
                JSONResponse(
                    GENERIC_ERROR_BODY, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
                )
            ]

    @api.post("/rules")
    def create_rule(self) -> list[Response | Effect]:
        try:
            try:
                body = json.loads(self.request.body)
            except json.JSONDecodeError:
                return [
                    JSONResponse(
                        {"error": "Invalid JSON body"},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]
            if not isinstance(body, dict):
                return [
                    JSONResponse(
                        {"error": "Request body must be a JSON object"},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]

            validation_error = self._validate_rule_body(body)
            if validation_error:
                return [
                    JSONResponse(
                        {"error": validation_error},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]

            cache = get_cache()
            rules = cache.get(CACHE_RULES_KEY) or []
            if isinstance(rules, str):
                rules = json.loads(rules)

            rule = {
                "id": str(uuid.uuid4()),
                "status": body["status"],
                "duration_value": int(body.get("duration_value", 0) or 0),
                "duration_unit": body.get("duration_unit", "h") or "h",
                "task_title": body["task_title"],
                "assignee_type": body.get("assignee_type", "") or "",
                "assignee_id": body.get("assignee_id", "") or "",
                "assignee_name": body.get("assignee_name", "") or "",
                "label": body.get("label", "") or "",
            }
            rules = [*rules, rule]
            cache.set(CACHE_RULES_KEY, rules)
            return [JSONResponse({"rule": rule}, status_code=HTTPStatus.CREATED)]
        except Exception as e:
            log.error(f"RxApi create_rule error: {e}")
            return [
                JSONResponse(
                    GENERIC_ERROR_BODY, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
                )
            ]

    def _validate_rule_body(self, body):
        status = body.get("status")
        if not status or status not in VALID_STATUSES:
            return "Invalid or missing 'status'"

        task_title = body.get("task_title")
        if not isinstance(task_title, str) or not task_title.strip():
            return "'task_title' is required"
        if len(task_title) > TASK_TITLE_MAX_LENGTH:
            return f"'task_title' must be {TASK_TITLE_MAX_LENGTH} characters or fewer"

        duration_value = body.get("duration_value", 0)
        try:
            duration_int = int(duration_value or 0)
        except (TypeError, ValueError):
            return "'duration_value' must be an integer"
        if duration_int < 0:
            return "'duration_value' must be zero or greater"

        duration_unit = body.get("duration_unit", "h") or "h"
        if duration_unit not in VALID_DURATION_UNITS:
            return "'duration_unit' must be 'h' or 'd'"

        return None

    @api.delete("/rules/<rule_id>")
    def delete_rule(self) -> list[Response | Effect]:
        try:
            rule_id = self.request.path_params["rule_id"]
            cache = get_cache()
            rules = cache.get(CACHE_RULES_KEY) or []
            if isinstance(rules, str):
                rules = json.loads(rules)
            rules = [r for r in rules if r.get("id") != rule_id]
            cache.set(CACHE_RULES_KEY, rules)
            return [JSONResponse({"deleted": rule_id}, status_code=HTTPStatus.OK)]
        except Exception as e:
            log.error(f"RxApi delete_rule error: {e}")
            return [
                JSONResponse(
                    GENERIC_ERROR_BODY, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
                )
            ]

    @api.get("/me")
    def get_current_user(self) -> list[Response | Effect]:
        try:
            user_id = self.request.headers.get("canvas-logged-in-user-id")
            if not user_id:
                return [
                    JSONResponse(
                        {"name": "", "is_prescriber": False}, status_code=HTTPStatus.OK
                    )
                ]
            staff = Staff.objects.get(id=user_id)
            name = f"{staff.first_name} {staff.last_name}".strip()
            is_prescriber = Prescription.objects.filter(prescriber_id=staff.id).exists()
            return [
                JSONResponse(
                    {"name": name, "is_prescriber": is_prescriber},
                    status_code=HTTPStatus.OK,
                )
            ]
        except Staff.DoesNotExist:
            return [
                JSONResponse(
                    {"name": "", "is_prescriber": False}, status_code=HTTPStatus.OK
                )
            ]
        except Exception as e:
            log.error(f"RxApi get_current_user error: {e}")
            return [
                JSONResponse(
                    GENERIC_ERROR_BODY, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
                )
            ]

    # --- Lookup data for rule config ---

    @api.get("/staff")
    def list_staff(self) -> list[Response | Effect]:
        try:
            staff = Staff.objects.filter(active=True).order_by(
                "last_name", "first_name"
            )
            results = [
                {"id": str(s.id), "name": f"{s.first_name} {s.last_name}".strip()}
                for s in staff
            ]
            return [JSONResponse({"staff": results}, status_code=HTTPStatus.OK)]
        except Exception as e:
            log.error(f"RxApi list_staff error: {e}")
            return [
                JSONResponse(
                    GENERIC_ERROR_BODY, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
                )
            ]

    @api.get("/teams")
    def list_teams(self) -> list[Response | Effect]:
        try:
            teams = Team.objects.all().order_by("name")
            results = [{"id": str(t.id), "name": t.name} for t in teams]
            return [JSONResponse({"teams": results}, status_code=HTTPStatus.OK)]
        except Exception as e:
            log.error(f"RxApi list_teams error: {e}")
            return [
                JSONResponse(
                    GENERIC_ERROR_BODY, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
                )
            ]

    @api.get("/labels")
    def list_labels(self) -> list[Response | Effect]:
        try:
            labels = TaskLabel.objects.filter(active=True).order_by("name")
            results = [
                {
                    "id": str(l.id),
                    "name": l.name,
                    "color": str(l.color) if l.color else "",
                }
                for l in labels
            ]
            return [JSONResponse({"labels": results}, status_code=HTTPStatus.OK)]
        except Exception as e:
            log.error(f"RxApi list_labels error: {e}")
            return [
                JSONResponse(
                    GENERIC_ERROR_BODY, status_code=HTTPStatus.INTERNAL_SERVER_ERROR
                )
            ]
