import json
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

from logger import log

from surescripts_med_history.protocols.audit import logged_in_user_id, staff_label
from surescripts_med_history.protocols.note_metadata import request_metadata_effects


class BulkRequestsApi(StaffSessionAuthMixin, SimpleAPI):
    """API endpoints for bulk Surescripts eligibility and med history requests."""

    PREFIX = "/bulk"

    @api.get("/page")
    def page(self) -> list[Response | Effect]:
        """Serve the full-page HTML."""
        # Only active providers registered with Surescripts (non-empty SPI) can
        # legally originate eligibility / med history requests, so the bulk
        # provider filter excludes the rest. Listed "Last, First" for
        # natural alphabetical scanning.
        providers = []
        staff_qs = (
            Staff.objects.filter(active=True)
            .exclude(spi_number="")
            .order_by("last_name", "first_name")
        )
        for staff in staff_qs:
            first = getattr(staff, "first_name", "") or ""
            last = getattr(staff, "last_name", "") or ""
            if not first and not last:
                continue
            if last and first:
                name = "%s, %s" % (last, first)
            else:
                name = (last or first).strip()
            providers.append({"id": str(staff.id), "name": name})

        html = render_to_string(
            "templates/bulk_requests.html",
            {"providers_json": json.dumps(providers)},
        )
        return [HTMLResponse(html)]

    @api.get("/appointments")
    def get_appointments(self) -> list[Response | Effect]:
        """Return appointments filtered by date range and optional providers."""
        date_from = self.request.query_params.get("date_from", "")
        date_to = self.request.query_params.get("date_to", "")
        # Comma-separated provider ids; empty string = all providers
        provider_ids_raw = self.request.query_params.get("provider_ids", "")
        provider_ids = [p for p in provider_ids_raw.split(",") if p.strip()]

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
            # Patients whose provider has no SPI can't be requested anyway
            # (the bulk endpoints skip them), so don't list them here.
            # __gt="" handles both NULL providers (no FK) and empty SPI in
            # one filter; .exclude(spi_number="") would let NULL through.
            .filter(provider__spi_number__gt="")
            .select_related("patient", "provider")
            # Only the fields the response is built from — the date range is
            # user-chosen and can span a year of appointments.
            .only(
                "start_time",
                "patient__id",
                "patient__first_name",
                "patient__last_name",
                "provider__id",
                "provider__first_name",
                "provider__last_name",
                "provider__spi_number",
            )
        )

        if provider_ids:
            qs = qs.filter(provider__id__in=provider_ids)

        # Deduplicate by patient — keep earliest appointment per patient.
        # Streamed rather than materialized so a wide date range doesn't pull
        # every appointment into memory at once.
        seen = {}
        for appt in qs.order_by("start_time").iterator(chunk_size=200):
            if appt.patient is None or appt.provider is None:
                continue
            # Defensive: filter() above should already enforce this, but
            # guard in Python in case of any data drift between FK and SPI.
            if not getattr(appt.provider, "spi_number", ""):
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
                "appointment_date": appt.start_time.strftime("%m/%d/%Y"),
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

        date_from = body.get("date_from", "")
        date_to = body.get("date_to", "")
        # Required so we don't fall back to "all-time" appointments and
        # attach the request to a long-departed provider's SPI.
        if not date_from or not date_to:
            return [
                JSONResponse(
                    {"error": "date_from and date_to are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        effects = []
        provider_ids = body.get("provider_ids", []) or []

        # Build patient→provider map from appointments
        patient_provider, skipped_no_spi = self._get_patient_provider_map(
            patient_ids, date_from, date_to, provider_ids
        )

        count = 0
        for pid in patient_ids:
            entry = patient_provider.get(pid)
            if not entry:
                log.warning("Bulk eligibility: no provider for patient %s" % pid)
                continue
            staff_id = entry["provider_id"]
            effects.append(
                SendSurescriptsEligibilityRequestEffect(
                    patient_id=pid,
                    staff_id=staff_id,
                ).apply()
            )
            effects.extend(
                request_metadata_effects(entry.get("note_id", ""), "eligibility")
            )
            count = count + 1

        log.info(
            "Surescripts request: initiator %s sent %s bulk eligibility requests "
            "on behalf of the appointment providers, skipped %s for missing SPI"
            % (self._initiator_label(), count, skipped_no_spi)
        )
        return [
            JSONResponse(
                {"status": "ok", "count": count, "skipped_no_spi": skipped_no_spi}
            )
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

        date_from = body.get("date_from", "")
        date_to = body.get("date_to", "")
        # Required so we don't fall back to "all-time" appointments and
        # attach the request to a long-departed provider's SPI.
        if not date_from or not date_to:
            return [
                JSONResponse(
                    {"error": "date_from and date_to are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        provider_ids = body.get("provider_ids", []) or []

        patient_provider, skipped_no_spi = self._get_patient_provider_map(
            patient_ids, date_from, date_to, provider_ids
        )

        effects = []
        count = 0
        for pid in patient_ids:
            entry = patient_provider.get(pid)
            if not entry:
                log.warning("Bulk med history: no provider for patient %s" % pid)
                continue
            staff_id = entry["provider_id"]
            effects.append(
                SendSurescriptsMedicationHistoryRequestEffect(
                    patient_id=pid,
                    staff_id=staff_id,
                ).apply()
            )
            effects.extend(
                request_metadata_effects(entry.get("note_id", ""), "med_history")
            )
            count = count + 1

        log.info(
            "Surescripts request: initiator %s sent %s bulk med history requests "
            "on behalf of the appointment providers, skipped %s for missing SPI"
            % (self._initiator_label(), count, skipped_no_spi)
        )
        return [
            JSONResponse(
                {"status": "ok", "count": count, "skipped_no_spi": skipped_no_spi}
            )
        ] + effects

    def _initiator_label(self) -> str:
        """The staff member who triggered the bulk run, for the audit log.

        Bulk requests run under whichever provider owns each appointment, so
        the initiator is never implied by the effects themselves.
        """
        user_id = logged_in_user_id(self.request)
        staff = None
        if user_id:
            try:
                staff = Staff.objects.get(id=user_id)
            except Staff.DoesNotExist:
                staff = None
        return staff_label(staff, user_id)

    @staticmethod
    def _get_patient_provider_map(patient_ids, date_from, date_to, provider_ids):
        """Build a {patient_id: {"provider_id", "note_id"}} map from appointment data.

        Returns (map, skipped_no_spi) — patients are only included when their
        appointment provider has a non-empty spi_number, since Surescripts
        rejects requests from staff who aren't registered with an SPI. The
        note_id is captured so the caller can stamp request metadata on the
        appointment's note (None if the appointment has no associated note).

        provider_ids: optional list of staff ids to scope the lookup; empty
        list means "any provider".
        """
        result: dict[str, dict] = {}
        skipped_patient_ids: set[str] = set()
        warned_providers: set[str] = set()

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
            .select_related("patient", "provider", "note")
            .only(
                "start_time",
                "patient__id",
                "provider__id",
                "provider__spi_number",
                "note__id",
            )
        )

        if date_from and date_to:
            qs = qs.filter(
                start_time__date__gte=date_from,
                start_time__date__lte=date_to,
            )
        if provider_ids:
            qs = qs.filter(provider__id__in=provider_ids)

        for appt in qs.order_by("start_time").iterator(chunk_size=200):
            if appt.patient is None or appt.provider is None:
                continue
            pid = str(appt.patient.id)
            if pid in result:
                continue
            if not appt.provider.spi_number:
                prov_id = str(appt.provider.id)
                if prov_id not in warned_providers:
                    warned_providers.add(prov_id)
                    log.warning(
                        "Bulk request: skipping provider %s — no SPI number" % prov_id
                    )
                skipped_patient_ids.add(pid)
                continue
            result[pid] = {
                "provider_id": str(appt.provider.id),
                "note_id": str(appt.note.id) if appt.note is not None else "",
            }

        skipped_no_spi = len(skipped_patient_ids - set(result.keys()))
        return result, skipped_no_spi
