"""TEMPORARY diagnostic endpoints. Delete once the 500 is understood.

Authenticated by API key rather than a staff session, so it can be driven from a
terminal. The staff-session routes can only be exercised from a signed-in
browser, which made every diagnostic step a round trip through a human.

Returns no patient data: a boolean and a row count. Remove this module, its
manifest entry and the `simpleapi-api-key` variable when the investigation ends.
"""

from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, api
from canvas_sdk.handlers.simple_api.security import APIKeyAuthMixin


class DiagnosticAPI(APIKeyAuthMixin, SimpleAPI):
    """A ladder of probes, each adding one thing to the one before it."""

    PREFIX = "/diag"

    @api.get("/ping")
    def ping(self) -> list[Response | Effect]:
        """Reached the handler. No imports beyond the SDK, no database."""
        return [JSONResponse({"ok": True, "probe": "handler_only"})]

    @api.get("/core")
    def core(self) -> list[Response | Effect]:
        """One query against a core Canvas model."""
        from canvas_sdk.v1.data import Staff

        return [JSONResponse({"ok": True, "probe": "core_model", "staff": Staff.objects.count()})]

    @api.get("/custom")
    def custom(self) -> list[Response | Effect]:
        """One query against this plugin's own custom_data table."""
        from patient_resources.models import PatientResource

        return [
            JSONResponse(
                {"ok": True, "probe": "custom_data", "rows": PatientResource.objects.count()}
            )
        ]

    @api.get("/config")
    def config(self) -> list[Response | Effect]:
        """Parses the plugin configuration. No database."""
        from patient_resources.services.config import PatientResourcesConfig

        parsed = PatientResourcesConfig.from_secrets(getattr(self, "secrets", None))
        return [
            JSONResponse(
                {
                    "ok": True,
                    "probe": "config",
                    "domains": list(parsed.admin_role_domains),
                    "staff_ids_configured": bool(parsed.admin_staff_ids),
                }
            )
        ]

    @api.get("/razor")
    def razor(self) -> list[Response | Effect]:
        """The same function reached two ways. Keeps the broken style on purpose."""
        results: dict[str, Any] = {}

        def run(name: str, fn: Any) -> None:
            try:
                results[name] = repr(fn())
            except BaseException as exc:  # noqa: BLE001 - diagnostic
                results[name] = f"{exc.__class__.__name__}: {exc}"

        def via_module_attribute() -> Any:
            from patient_resources.services import catalog

            return catalog.list_resources(limit=1, offset=0)[1]

        def via_direct_import() -> Any:
            from patient_resources.services.catalog import list_resources

            return list_resources(limit=1, offset=0)[1]

        run("module_attribute", via_module_attribute)
        run("direct_import", via_direct_import)
        return [JSONResponse({"ok": True, "probe": "razor", "results": results})]

    @api.get("/step")
    def step(self) -> list[Response | Effect]:
        """Rebuild the failing query one operation at a time, reporting the first failure.

        Each step is wrapped and its exception returned in the payload. A broad
        ``except`` is wrong in production code and right here: the whole purpose
        is to see the error, and the empty 500 the platform returns instead tells
        us nothing.
        """
        from patient_resources.constants import STATUS_ACTIVE
        from patient_resources.models import PatientResource

        results: dict[str, Any] = {}

        def run(name: str, fn: Any) -> None:
            try:
                results[name] = repr(fn())
            except BaseException as exc:  # noqa: BLE001 - diagnostic
                results[name] = f"{exc.__class__.__name__}: {exc}"

        run("1_all_count", lambda: PatientResource.objects.all().count())
        run("2_filter_count", lambda: PatientResource.objects.all().filter(status=STATUS_ACTIVE).count())
        run(
            "3_order_count",
            lambda: PatientResource.objects.all()
            .filter(status=STATUS_ACTIVE)
            .order_by("title", "dbid")
            .count(),
        )
        run(
            "4_slice_list",
            lambda: list(
                PatientResource.objects.all()
                .filter(status=STATUS_ACTIVE)
                .order_by("title", "dbid")[0:50]
            ),
        )
        run("5_build_queryset", lambda: _build_queryset_count())
        run("6_list_resources", lambda: _list_resources())

        return [JSONResponse({"ok": True, "probe": "step", "results": results})]

    @api.get("/listing")
    def listing(self) -> list[Response | Effect]:
        """The exact call the failing route makes: search, page, and count."""
        from patient_resources.services.catalog import list_resources

        rows, total = list_resources(limit=50, offset=0)
        payload: dict[str, Any] = {"ok": True, "probe": "catalog_listing", "total": total}
        payload["returned"] = len(rows)
        return [JSONResponse(payload)]


def _build_queryset_count() -> int:
    from patient_resources.services.catalog import build_queryset

    return int(build_queryset().count())


def _list_resources() -> str:
    from patient_resources.services.catalog import list_resources

    rows, total = list_resources(limit=50, offset=0)
    return f"rows={len(rows)} total={total}"
