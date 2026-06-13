"""EHIExportClient — extends the Canvas SDK FHIR client for the EHI bulk export.

The native :class:`canvas_sdk.clients.canvas_fhir.CanvasFhir` client handles the
OAuth2 client-credentials grant and token caching for us, and derives the fumage
base URL from ``CUSTOMER_IDENTIFIER`` — but it only exposes standard CRUD verbs
(``search``/``read``/``create``/``update``) that return parsed JSON.  The EHI
export is a FHIR *Bulk Data* operation and needs three things the CRUD verbs
cannot do:

    * a GET to the custom ``/Patient/<id>/$export`` operation with the
      ``Prefer: respond-async`` header,
    * access to the ``Content-Location`` / ``X-Progress`` response headers,
    * reading raw NDJSON response bodies (not JSON).

So we subclass ``CanvasFhir`` to reuse its auth/token plumbing and base URL, and
add just the bulk-export methods on top.  The flow per patient is::

    1. GET  {fumage}/Patient/<id>/$export   (Prefer: respond-async)  -> job id
    2. GET  {fumage}/bulkstatus/<job id>                             -> status / output
    3. GET  <output url>   (one file per resource type)              -> NDJSON
"""

from __future__ import annotations

import json
import time
from http import HTTPStatus
from typing import Any

from canvas_sdk.clients.canvas_fhir import CanvasFhir
from canvas_sdk.utils.http import Http
from logger import log

# bulkstatus job status values returned by :meth:`EHIExportClient.get_status`.
STATUS_IN_PROGRESS = "in-progress"
STATUS_COMPLETE = "complete"
STATUS_ERROR = "error"

# Transient server-side statuses worth retrying when downloading export files.
# 503 ("No server is available") in particular is a load-balancer hint to retry.
_RETRYABLE_STATUSES = frozenset({500, 502, 503, 504})
_DOWNLOAD_ATTEMPTS = 4
_BACKOFF_SECONDS = (0.75, 1.5, 3.0)  # sleep between attempts; len == _DOWNLOAD_ATTEMPTS - 1


class EHIExportError(Exception):
    """Raised when the EHI export API returns an unexpected response."""


class EHIConfigError(EHIExportError):
    """Raised when the plugin is missing required configuration (credentials)."""


class EHIExportClient(CanvasFhir):
    """Canvas FHIR client with the EHI bulk-export operations added.

    Construction (inherited from ``CanvasFhir``) mints and caches an OAuth token
    and sets ``self._base_url`` to ``https://fumage-<instance>.canvasmedical.com``.
    """

    def start_export(self, patient_id: str) -> str:
        """Kick off a patient EHI export and return the bulkstatus job id.

        Canvas responds ``202 Accepted`` with a ``Content-Location`` header that
        points at the polling URL ``{fumage}/bulkstatus/<job id>``.
        """
        url = f"{self._base_url}/Patient/{patient_id}/$export"
        headers = {**self._get_headers(), "Prefer": "respond-async"}
        response = Http().get(url, headers=headers)

        if response.status_code != HTTPStatus.ACCEPTED:
            raise EHIExportError(
                f"$export for patient {patient_id} returned "
                f"{response.status_code} (expected 202): {response.text[:500]}"
            )

        job_id = self._job_id_from_content_location(response.headers.get("Content-Location", ""))
        if not job_id:
            raise EHIExportError(
                f"$export for patient {patient_id} returned no usable "
                "Content-Location header"
            )
        log.info("EHI export: started job %s for patient %s", job_id, patient_id)
        return job_id

    @staticmethod
    def _job_id_from_content_location(content_location: str) -> str:
        """Extract the bulkstatus job id from a Content-Location header value."""
        if not content_location:
            return ""
        marker = "/bulkstatus/"
        if marker in content_location:
            return content_location.split(marker, 1)[1].strip("/").split("?")[0]
        # Fall back to the last path segment if the URL shape ever changes.
        return content_location.rstrip("/").split("/")[-1].split("?")[0]

    def get_status(self, job_id: str) -> dict[str, Any]:
        """Poll a bulkstatus job once.

        Returns a dict shaped like::

            {"status": "in-progress" | "complete" | "error",
             "progress": "<free text>",
             "output":   [{"type": "Patient", "url": "..."}, ...]}

        ``output`` is only populated when ``status`` is ``complete``.
        """
        url = f"{self._base_url}/bulkstatus/{job_id}"
        response = Http().get(url, headers=self._get_headers())

        if response.status_code == HTTPStatus.ACCEPTED:
            return {
                "status": STATUS_IN_PROGRESS,
                "progress": response.headers.get("X-Progress", "in progress"),
                "output": [],
            }

        if response.status_code == HTTPStatus.OK:
            body = response.json()
            return {
                "status": STATUS_COMPLETE,
                "progress": "complete",
                "output": body.get("output", []),
                "errors": body.get("error", []),
            }

        return {
            "status": STATUS_ERROR,
            "progress": f"unexpected status {response.status_code}: {response.text[:500]}",
            "output": [],
        }

    def fetch_ndjson_resources(self, output_url: str) -> list[dict[str, Any]]:
        """Download one NDJSON output file and parse it into a list of resources.

        Retries transient 5xx responses (the data-integration download service can
        briefly return 503) with a short backoff before giving up.
        """
        response = self._get_with_retry(output_url)
        if not response.ok:
            raise EHIExportError(
                f"failed to download export file {output_url}: "
                f"{response.status_code} {response.text[:200]}"
            )
        resources: list[dict[str, Any]] = []
        for raw_line in response.text.splitlines():
            line = raw_line.strip()
            if line:
                resources.append(json.loads(line))
        return resources

    def _get_with_retry(self, url: str) -> Any:
        """GET ``url`` with the auth headers, retrying transient 5xx responses.

        Returns the final response object (which may still be a failure — the
        caller is responsible for checking ``.ok``).
        """
        response = None
        for attempt in range(_DOWNLOAD_ATTEMPTS):
            response = Http().get(url, headers=self._get_headers())
            if response.ok or response.status_code not in _RETRYABLE_STATUSES:
                return response
            if attempt < len(_BACKOFF_SECONDS):
                log.warning(
                    "EHI export: %s returned %s, retrying (attempt %d/%d)",
                    url,
                    response.status_code,
                    attempt + 1,
                    _DOWNLOAD_ATTEMPTS,
                )
                time.sleep(_BACKOFF_SECONDS[attempt])
        return response

    def build_patient_bundle(self, patient_id: str, output: list[dict[str, Any]]) -> dict[str, Any]:
        """Merge every NDJSON output file for a patient into one grouped JSON doc.

        The bulkstatus ``output`` array lists one file per resource type; this
        downloads each, then groups the resources by their ``resourceType`` into::

            "entry": {
                "Appointment": {"total": 5, "entry": [<resource>, ...]},
                "Patient":     {"total": 1, "entry": [<resource>]},
                ...
            }

        Resources are grouped by their own ``resourceType`` (falling back to the
        file's declared ``type``) so the grouping is authoritative even if a file
        contains mixed types. Types are emitted in sorted order for stable output.
        """
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in output:
            file_url = item.get("url")
            if not file_url:
                continue
            declared_type = item.get("type") or ""
            for resource in self.fetch_ndjson_resources(file_url):
                resource_type = resource.get("resourceType") or declared_type or "Unknown"
                grouped.setdefault(resource_type, []).append(resource)

        entry = {
            resource_type: {"total": len(resources), "entry": resources}
            for resource_type, resources in sorted(grouped.items())
        }
        total = sum(len(resources) for resources in grouped.values())

        return {
            "resourceType": "Bundle",
            "type": "collection",
            "id": f"ehi-export-{patient_id}",
            "meta": {"extension": [{"url": "patient", "valueString": patient_id}]},
            "total": total,
            "entry": entry,
        }
