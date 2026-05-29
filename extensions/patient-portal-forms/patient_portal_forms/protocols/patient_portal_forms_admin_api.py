"""Admin endpoints for patient_portal_forms.

The migration endpoint walks all `portal_forms` rows in PatientMetadata
(the legacy storage) and writes equivalent QuestionnaireAssignment rows
under the `canvas__patient_portal_forms` namespace. It is idempotent.
"""

import json
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_metadata import PatientMetadata as PatientMetadataEffect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import (
    SimpleAPI,
    StaffSessionAuthMixin,
    api,
)
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.patient import PatientMetadata

from logger import log

from patient_portal_forms.services import QuestionnaireAssignmentService


LEGACY_METADATA_KEY = "portal_forms"
MIGRATION_ENABLE_SECRET = "ENABLE_MIGRATION_ADMIN"


class PatientPortalFormsAdminAPI(StaffSessionAuthMixin, SimpleAPI):
    """Staff-only admin endpoints, gated by `ENABLE_MIGRATION_ADMIN`.

    The migration is expected to be run exactly once per Canvas instance, so
    these endpoints fail closed unless an operator has explicitly enabled
    them via the `ENABLE_MIGRATION_ADMIN` secret. The menu entry for the
    admin app stays registered in the manifest, but clicking it lands on a
    "disabled" page until the secret is set.
    """

    def _migration_admin_enabled(self) -> bool:
        return bool(self.secrets.get(MIGRATION_ENABLE_SECRET, "").strip())

    def _disabled_html_response(self) -> "HTMLResponse":
        return HTMLResponse(
            render_to_string("templates/admin_disabled.html"),
            status_code=HTTPStatus.FORBIDDEN,
        )

    def _disabled_json_response(self) -> "JSONResponse":
        return JSONResponse(
            {"error": f"Migration admin is disabled — set {MIGRATION_ENABLE_SECRET} to enable."},
            status_code=HTTPStatus.FORBIDDEN,
        )

    @api.get("/admin")
    def admin_landing(self) -> list[Response | Effect]:
        if not self._migration_admin_enabled():
            return [self._disabled_html_response()]
        return [
            HTMLResponse(
                render_to_string("templates/admin_migration.html"),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/admin/migrate-metadata")
    def migrate_metadata(self) -> list[Response | Effect]:
        """Migrate all legacy `portal_forms` PatientMetadata into the new model.

        Runs synchronously and returns aggregated counts. Re-running is safe:
        rows already migrated are skipped via the unique constraint on
        (patient, questionnaire_name).
        """
        if not self._migration_admin_enabled():
            return [self._disabled_json_response()]

        # Stream the legacy metadata rows in chunks so a Canvas instance
        # with thousands of patients holding the key doesn't materialize
        # the full set into memory before the loop starts.
        rows = (
            PatientMetadata.objects.filter(key=LEGACY_METADATA_KEY)
            .values_list("patient__id", "value")
            .iterator(chunk_size=200)
        )

        patients_processed = 0
        total_created = 0
        total_skipped = 0
        all_errors: list[str] = []

        for patient_id, raw_value in rows:
            patients_processed += 1
            if not raw_value:
                continue
            try:
                payload = json.loads(raw_value)
            except ValueError as exc:
                all_errors.append(f"patient {patient_id}: invalid JSON ({exc})")
                continue

            result = QuestionnaireAssignmentService.migrate_from_metadata(
                str(patient_id), payload
            )
            total_created += result["created"]
            total_skipped += result["skipped"]
            all_errors.extend(result["errors"])

        log.info(
            f"[ppf migration] processed={patients_processed} "
            f"created={total_created} skipped={total_skipped} "
            f"errors={len(all_errors)}"
        )

        return [
            JSONResponse(
                {
                    "patients_processed": patients_processed,
                    "rows_created": total_created,
                    "rows_skipped": total_skipped,
                    "errors": all_errors,
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/admin/clear-legacy-metadata")
    def clear_legacy_metadata(self) -> list[Response | Effect]:
        """Clear the value of every legacy `portal_forms` PatientMetadata row.

        The SDK does not expose a delete effect for PatientMetadata (and
        plugins have no write access to the table via the ORM), so the most
        we can do is overwrite each row's value with an empty string. The
        row itself remains but is functionally inert — nothing reads it.

        Intended as a second step after `migrate-metadata` has run successfully
        and the operator has verified the new QuestionnaireAssignment rows.
        Idempotent — running again with already-emptied rows is a no-op
        in effect (the upserts just write an empty string a second time).
        """
        if not self._migration_admin_enabled():
            return [self._disabled_json_response()]

        patient_ids = list(
            PatientMetadata.objects.filter(key=LEGACY_METADATA_KEY)
            .exclude(value="")
            .values_list("patient__id", flat=True)
        )

        clear_effects = [
            PatientMetadataEffect(
                patient_id=str(pid), key=LEGACY_METADATA_KEY
            ).upsert("")
            for pid in patient_ids
        ]
        log.info(
            f"[ppf migration] clearing legacy metadata for {len(patient_ids)} patient(s)"
        )

        return [
            *clear_effects,
            JSONResponse(
                {"rows_cleared": len(patient_ids)},
                status_code=HTTPStatus.OK,
            ),
        ]
