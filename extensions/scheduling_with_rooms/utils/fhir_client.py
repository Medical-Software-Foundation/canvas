"""FHIR API client with OAuth2 token management and Schedule/Slot helpers."""

import datetime
from typing import Any
from urllib.parse import quote, urlencode

from canvas_sdk.utils import Http
from logger import log


class FHIRClient:
    """Canvas FHIR API client with OAuth2 token caching.

    Uses plugin secrets for credentials and the Canvas SDK Http client for all
    outbound requests.  Tokens are cached on the instance until expiry.
    """

    def __init__(self, secrets: dict[str, str]) -> None:
        self._base_url: str = secrets["FHIR_BASE_URL"].rstrip("/")
        # Auth endpoint lives on the EMR host, not the fumage FHIR host.
        # e.g. fumage-instance.canvasmedical.com -> instance.canvasmedical.com
        self._auth_base_url: str = self._base_url.replace("://fumage-", "://")
        self._client_id: str = secrets["FHIR_CLIENT_ID"]
        self._client_secret: str = secrets["FHIR_CLIENT_SECRET"]
        self._token: str | None = None
        self._token_expires_at: datetime.datetime | None = None
        self._http = Http()

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _is_token_valid(self) -> bool:
        """Return True if the cached token exists and is not about to expire."""
        if self._token is None or self._token_expires_at is None:
            return False
        # Treat the token as invalid if it expires within the next 30 seconds.
        return datetime.datetime.utcnow() < (
            self._token_expires_at - datetime.timedelta(seconds=30)
        )

    def _fetch_token(self) -> None:
        """Request a new OAuth2 bearer token using client_credentials grant."""
        token_url = f"{self._auth_base_url}/auth/token/"
        response = self._http.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        response.raise_for_status()
        data = response.json()
        self._token = data["access_token"]
        expires_in: int = int(data.get("expires_in", 3600))
        self._token_expires_at = datetime.datetime.utcnow() + datetime.timedelta(
            seconds=expires_in
        )
        log.info("FHIR token acquired, expires in %d seconds", expires_in)

    def _get_token(self) -> str:
        """Return a valid bearer token, fetching a new one if necessary."""
        if not self._is_token_valid():
            self._fetch_token()
        return self._token  # type: ignore[return-value]

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_token()}"}

    # ------------------------------------------------------------------
    # Generic FHIR helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fhir_quote(
        string: str,
        safe: str = "",
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        """URL-encode preserving commas for FHIR OR-search syntax."""
        return quote(string, safe=safe + ",", encoding=encoding, errors=errors)

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        """Perform an authenticated GET and return the parsed JSON body."""
        url = f"{self._base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params, quote_via=self._fhir_quote)}"  # type: ignore[arg-type]
        response = self._http.get(url, headers=self._auth_headers())
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    # ------------------------------------------------------------------
    # Patient helpers
    # ------------------------------------------------------------------

    _TZ_EXTENSION_URL = "http://hl7.org/fhir/StructureDefinition/tz-code"

    def _extract_tz(self, patient_resource: dict[str, Any]) -> str:
        """Extract timezone from a FHIR Patient resource's tz-code extension."""
        for ext in patient_resource.get("extension", []):
            if ext.get("url", "") == self._TZ_EXTENSION_URL:
                return str(ext.get("valueCode", ""))
        return ""

    def get_patient_timezone(self, patient_id: str) -> str:
        """Return the patient's timezone from the FHIR Patient resource.

        Looks for the hl7 tz-code extension on the Patient resource.
        Returns an IANA timezone string (e.g. "America/New_York") or "".
        """
        try:
            patient = self._get(f"/Patient/{patient_id}")
        except Exception as exc:
            log.warning("get_patient_timezone: FHIR read failed for %s: %s", patient_id, exc)
            return ""

        return self._extract_tz(patient)

    def get_patient_timezones(self, patient_ids: list[str]) -> dict[str, str]:
        """Fetch timezones for multiple patients.

        Makes individual FHIR reads per patient because the Canvas FHIR API
        does not reliably support comma-separated ``_id`` search.

        Returns a dict mapping patient_id -> IANA timezone string.
        Only includes patients that have a tz-code extension.
        """
        if not patient_ids:
            return {}

        result: dict[str, str] = {}
        for pid in patient_ids:
            tz = self.get_patient_timezone(pid)
            if tz:
                result[pid] = tz

        log.info(
            "get_patient_timezones: queried %d patients, %d have timezones",
            len(patient_ids),
            len(result),
        )
        return result

    # ------------------------------------------------------------------
    # Schedule resource helpers
    # ------------------------------------------------------------------

    def get_schedules(self) -> list[dict[str, Any]]:
        """Return all Schedule entries from the FHIR API.

        Each entry has the shape returned by the Canvas FHIR Schedule endpoint.
        The ``id`` field encodes ``Location.<loc_id>-Staff.<staff_id>``.
        """
        bundle = self._get("/Schedule")
        entries = bundle.get("entry", [])
        resources = [entry["resource"] for entry in entries if "resource" in entry]
        log.info(
            "FHIR /Schedule returned %d entries, IDs: %s",
            len(resources),
            [r.get("id", "?") for r in resources[:10]],
        )
        return resources

    def get_staff_ids_for_location(self, location_id: str) -> set[str]:
        """Return the set of staff IDs that have a Schedule for the given location."""
        prefix = f"Location.{location_id}-Staff."
        staff_ids: set[str] = set()
        for schedule in self.get_schedules():
            schedule_id: str = schedule.get("id", "")
            if schedule_id.startswith(prefix):
                # Extract staff ID from "Location.<loc_id>-Staff.<staff_id>"
                staff_part = schedule_id[len(prefix):]
                if staff_part:
                    staff_ids.add(staff_part)
        return staff_ids

    # ------------------------------------------------------------------
    # Slot resource helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Appointment resource helpers
    # ------------------------------------------------------------------

    def get_provider_appointments(
        self,
        provider_id: str,
        date: str,
    ) -> list[dict[str, Any]]:
        """Return FHIR Appointment resources for a provider on a date.

        Used to detect schedule events and other bookings that may not appear
        in the Canvas SDK Appointment data model (e.g. ScheduleEvent records).

        Raises the underlying exception on failure so callers can fall back
        to the DB-based blocking lookup. Returning an empty list on failure
        would silently treat the provider as fully open.
        """
        bundle = self._get(
            "/Appointment",
            params={"practitioner": f"Practitioner/{provider_id}", "date": date},
        )

        entries = bundle.get("entry", [])
        resources = [entry["resource"] for entry in entries if "resource" in entry]
        log.info(
            "FHIR /Appointment: provider=%s, date=%s, %d results, statuses=%s",
            provider_id,
            date,
            len(resources),
            [r.get("status", "?") for r in resources],
        )
        return resources

    def get_patient_appointments(
        self,
        patient_id: str,
        date: str,
    ) -> list[dict[str, Any]]:
        """Return FHIR Appointment resources for a patient on a date.

        Used by the cascade handler to find RR staff ScheduleEvents associated
        with a cancelled/rescheduled appointment.
        """
        try:
            bundle = self._get(
                "/Appointment",
                params={"patient": f"Patient/{patient_id}", "date": date},
            )
        except Exception as exc:
            log.warning(
                "get_patient_appointments: FHIR search failed for patient %s on %s: %s",
                patient_id,
                date,
                exc,
            )
            return []

        entries = bundle.get("entry", [])
        resources = [entry["resource"] for entry in entries if "resource" in entry]
        log.info(
            "FHIR /Appointment: patient=%s, date=%s, %d results",
            patient_id,
            date,
            len(resources),
        )
        return resources

    # ------------------------------------------------------------------
    # Slot resource helpers
    # ------------------------------------------------------------------

    def get_slots(
        self,
        location_id: str,
        staff_id: str,
        date: str,
        duration_minutes: int,
    ) -> list[dict[str, Any]]:
        """Return available FHIR Slot entries for a provider at a location on a date.

        Args:
            location_id: Canvas practice location ID.
            staff_id: Canvas staff ID.
            date: Date string in YYYY-MM-DD format.
            duration_minutes: Appointment duration to filter by.

        Returns:
            List of FHIR Slot resource dicts.
        """
        schedule_id = f"Location.{location_id}-Staff.{staff_id}"
        # Build start/end window for the full day.
        start_of_day = f"{date}T00:00:00"
        end_of_day = f"{date}T23:59:59"
        params = {
            "schedule": schedule_id,
            "start": start_of_day,
            "end": end_of_day,
            "duration": str(duration_minutes),
            "status": "free",
        }
        bundle = self._get("/Slot", params=params)
        entries = bundle.get("entry", [])
        return [entry["resource"] for entry in entries if "resource" in entry]
