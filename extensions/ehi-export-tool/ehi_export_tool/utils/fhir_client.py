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

    def _fetch_text(self, output_url: str) -> str:
        """Download one NDJSON output file as raw text.

        Retries transient 5xx responses (the data-integration download service can
        briefly return 503) with a short backoff before giving up.
        """
        response = self._get_with_retry(output_url)
        if not response.ok:
            raise EHIExportError(
                f"failed to download export file {output_url}: "
                f"{response.status_code} {response.text[:200]}"
            )
        return response.text

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

    def build_patient_ndjson(self, output: list[dict[str, Any]]) -> str:
        """Concatenate a patient's bulk-export output files into one NDJSON string.

        ``$export`` produces one NDJSON file per resource type. Concatenating them
        (one FHIR resource per line) is valid Bulk Data output and keeps a patient
        to a single ``.ndjson`` file. No JSON parsing is needed — the raw lines are
        already NDJSON; we just join non-empty lines.
        """
        lines: list[str] = []
        for item in output:
            file_url = item.get("url")
            if not file_url:
                continue
            for raw_line in self._fetch_text(file_url).splitlines():
                line = raw_line.strip()
                if line:
                    lines.append(line)
        return "\n".join(lines)

    # ── C-CDA export (synchronous, XML) ──────────────────────────────────────

    @property
    def _emr_base_url(self) -> str:
        """The main EMR API host, derived from the fumage base URL.

        ``CanvasFhir`` sets ``self._base_url`` to
        ``https://fumage-<instance>.canvasmedical.com``; the C-CDA endpoint lives
        on the EMR host ``https://<instance>.canvasmedical.com`` (same OAuth
        token). Dropping the ``fumage-`` prefix converts one to the other.
        """
        return self._base_url.replace("fumage-", "", 1)

    def fetch_ccda(
        self,
        patient_key: str,
        document_type: str,
        start_date: str = "",
        end_date: str = "",
    ) -> str:
        """Fetch one patient's C-CDA document as XML text.

        ``GET {emr}/api/data-export/ccda/<patient_key>?document=<type>`` is
        synchronous and returns the XML document directly. ``document_type`` is
        ``continuity`` or ``referral``; ``start_date``/``end_date`` are optional
        ``YYYY-MM-DD`` bounds. Retries transient 5xx like the NDJSON download.
        """
        from urllib.parse import urlencode

        params = {"document": document_type}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        url = f"{self._emr_base_url}/api/data-export/ccda/{patient_key}?{urlencode(params)}"
        response = self._get_with_retry(url)
        if not response.ok:
            raise EHIExportError(
                f"C-CDA export for patient {patient_key} returned "
                f"{response.status_code}: {response.text[:200]}"
            )
        return response.text
