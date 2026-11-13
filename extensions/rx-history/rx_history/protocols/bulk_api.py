import json
from datetime import datetime, timezone
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.effects.surescripts import (
    SendSurescriptsEligibilityRequestEffect,
    SendSurescriptsMedicationHistoryRequestEffect,
)
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from canvas_sdk.v1.data.staff import Staff

from rx_history.protocols._care_event import (
    CARE_EVENT_WINDOW_DAYS,
    partition_by_care_event,
)

from logger import log

# Stable per process lifetime. Rotates on redeploy when the module reloads.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class BulkRequestsApi(StaffSessionAuthMixin, SimpleAPI):
    """API endpoints for bulk Surescripts eligibility and med history requests."""

    PREFIX = "/bulk"

    @api.get("/page")
    def page(self) -> list[Response | Effect]:
        """Serve the full-page HTML."""
        # Build provider list for the filter dropdown (licensed prescribers only)
        prescriber_roles = {"Physician", "Nurse Practitioner", "Physician Assistant"}
        providers = []
        try:
            # top_clinical_role is a cached_property that reads self.roles.all(),
            # so we prefetch the reverse relation to avoid one extra query per staff row.
            for staff in Staff.objects.all().prefetch_related("roles"):
                role = getattr(staff, "top_clinical_role", None)
                if not role or getattr(role, "name", "") not in prescriber_roles:
                    continue
                first = getattr(staff, "first_name", "") or ""
                last = getattr(staff, "last_name", "") or ""
                name = ("%s %s" % (first, last)).strip()
                if not name:
                    continue
                providers.append({"id": str(staff.id), "name": name})
        except Exception as e:
            log.warning("BulkRequestsApi: error loading providers: %s" % e)

        html = render_to_string(
            "templates/bulk_requests.html",
            {"providers_json": json.dumps(providers), "cache_bust": _CACHE_BUST},
        )
        return [HTMLResponse(html)]

    @api.get("/appointments")
    def get_appointments(self) -> list[Response | Effect]:
        """Return appointments filtered by date range and optional provider."""
        date_from = self.request.query_params.get("date_from", "")
        date_to = self.request.query_params.get("date_to", "")
        provider_id = self.request.query_params.get("provider_id", "")

        if not date_from or not date_to:
            return [
                JSONResponse(
                    {"error": "date_from and date_to are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        qs = (
            Appointment.objects.filter(
                start_time__date__gte=date_from,
                start_time__date__lte=date_to,
            )
            .exclude(
                status__in=[
                    AppointmentProgressStatus.CANCELLED,
                    AppointmentProgressStatus.NOSHOWED,
                ]
            )
            .select_related("patient", "provider")
        )

        if provider_id:
            qs = qs.filter(provider__id=provider_id)

        # Deduplicate by patient, keep earliest appointment per patient
        seen = {}
        for appt in qs.order_by("start_time"):
            if appt.patient is None or appt.provider is None:
                continue
            pid = str(appt.patient.id)
            if pid in seen:
                continue

            patient_name = ""
            first = getattr(appt.patient, "first_name", "") or ""
            last = getattr(appt.patient, "last_name", "") or ""
            if first or last:
                patient_name = ("%s %s" % (first, last)).strip()

            provider_name = ""
            prov_first = getattr(appt.provider, "first_name", "") or ""
            prov_last = getattr(appt.provider, "last_name", "") or ""
            if prov_first or prov_last:
                provider_name = ("%s %s" % (prov_first, prov_last)).strip()

            seen[pid] = {
                "patient_id": pid,
                "patient_name": patient_name or pid,
                "provider_id": str(appt.provider.id),
                "provider_name": provider_name,
                "appointment_date": appt.start_time.strftime("%b %d, %Y"),
                "appointment_time": appt.start_time.strftime("%I:%M %p"),
            }

        results = list(seen.values())
        log.info(
            "BulkRequestsApi: %s unique patients for %s to %s"
            % (len(results), date_from, date_to)
        )
        return [JSONResponse({"appointments": results})]

    @api.post("/eligibility")
    def send_eligibility(self) -> list[Response | Effect]:
        """Send eligibility requests for selected patients."""
        body = self.request.json()
        patient_ids = body.get("patient_ids", [])

        if not patient_ids:
            return [
                JSONResponse(
                    {"error": "patient_ids is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        allowed_ids, blocked_ids = partition_by_care_event(patient_ids)

        date_from = body.get("date_from", "")
        date_to = body.get("date_to", "")
        provider_id = body.get("provider_id", "")

        patient_provider = self._get_patient_provider_map(
            allowed_ids, date_from, date_to, provider_id
        )

        effects = []
        skipped = [
            {"patient_id": pid, "reason": "no_care_event"} for pid in blocked_ids
        ]
        sent = 0
        for pid in allowed_ids:
            staff_id = patient_provider.get(pid)
            if not staff_id:
                skipped.append({"patient_id": pid, "reason": "no_provider"})
                log.warning("Bulk eligibility. no provider for patient %s" % pid)
                continue
            effects.append(
                SendSurescriptsEligibilityRequestEffect(
                    patient_id=pid,
                    staff_id=staff_id,
                ).apply()
            )
            sent = sent + 1

        log.info(
            "Bulk eligibility. sent=%s skipped=%s window_days=%s"
            % (sent, len(skipped), CARE_EVENT_WINDOW_DAYS)
        )
        return [
            JSONResponse({"status": "ok", "sent": sent, "skipped": skipped})
        ] + effects

    @api.post("/med-history")
    def send_med_history(self) -> list[Response | Effect]:
        """Send medication history requests for selected patients."""
        body = self.request.json()
        patient_ids = body.get("patient_ids", [])

        if not patient_ids:
            return [
                JSONResponse(
                    {"error": "patient_ids is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        allowed_ids, blocked_ids = partition_by_care_event(patient_ids)

        date_from = body.get("date_from", "")
        date_to = body.get("date_to", "")
        provider_id = body.get("provider_id", "")

        patient_provider = self._get_patient_provider_map(
            allowed_ids, date_from, date_to, provider_id
        )

        effects = []
        skipped = [
            {"patient_id": pid, "reason": "no_care_event"} for pid in blocked_ids
        ]
        sent = 0
        for pid in allowed_ids:
            staff_id = patient_provider.get(pid)
            if not staff_id:
                skipped.append({"patient_id": pid, "reason": "no_provider"})
                log.warning("Bulk med history. no provider for patient %s" % pid)
                continue
            effects.append(
                SendSurescriptsMedicationHistoryRequestEffect(
                    patient_id=pid,
                    staff_id=staff_id,
                ).apply()
            )
            sent = sent + 1

        log.info(
            "Bulk med history. sent=%s skipped=%s window_days=%s"
            % (sent, len(skipped), CARE_EVENT_WINDOW_DAYS)
        )
        return [
            JSONResponse({"status": "ok", "sent": sent, "skipped": skipped})
        ] + effects

    @staticmethod
    def _get_patient_provider_map(
        patient_ids: list[str],
        date_from: str,
        date_to: str,
        provider_id: str,
    ) -> dict[str, str]:
        """Build a {patient_id: provider_id} map from appointment data."""
        result: dict[str, str] = {}
        qs = (
            Appointment.objects.filter(
                patient__id__in=patient_ids,
            )
            .exclude(
                status__in=[
                    AppointmentProgressStatus.CANCELLED,
                    AppointmentProgressStatus.NOSHOWED,
                ]
            )
            .select_related("patient", "provider")
        )

        if date_from and date_to:
            qs = qs.filter(
                start_time__date__gte=date_from,
                start_time__date__lte=date_to,
            )
        if provider_id:
            qs = qs.filter(provider__id=provider_id)

        for appt in qs.order_by("start_time"):
            if appt.patient is None or appt.provider is None:
                continue
            pid = str(appt.patient.id)
            if pid not in result:
                result[pid] = str(appt.provider.id)

        return result
