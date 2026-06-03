"""Chart Search API handler."""
from __future__ import annotations

import re
from datetime import date as _date_cls
from datetime import timedelta

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin
from logger import log
from chart_command_search.searchers import (
    ALL_CATEGORY_LIMIT,
    CATEGORY_SEARCHERS,
    MAX_RESULTS,
    Result,
)

_UUID_RE = re.compile(
    r"(?i)^[0-9a-f]{32}$|^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


class ChartSearchAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """Unified chart search endpoint, scoped to a specific patient."""

    PATH = "/search"

    def get(self) -> list[Response | Effect]:
        params = self.request.query_params
        patient_id = str(params.get("patient_id", ""))
        q = str(params.get("q", "")).strip()
        category_raw = str(params.get("category", "all")).strip().lower()
        status = str(params.get("status", "all")).strip().lower()
        date_from = str(params.get("date_from", "")).strip()
        date_to = str(params.get("date_to", "")).strip()
        provider_id = str(params.get("provider_id", "")).strip()

        if not patient_id:
            return [JSONResponse({"error": "patient_id is required"}, status_code=400)]
        if not _UUID_RE.match(patient_id):
            return [JSONResponse({"error": "Invalid patient_id"}, status_code=400)]

        if date_to:
            try:
                date_to = str(_date_cls.fromisoformat(date_to) + timedelta(days=1))
            except ValueError:
                pass

        filter_kwargs = {
            "date_from": date_from,
            "date_to": date_to,
            "provider_id": provider_id,
        }

        if category_raw == "all":
            categories = list(CATEGORY_SEARCHERS.keys())
        else:
            categories = [c.strip() for c in category_raw.split(",") if c.strip()]

        search_errors: list[str] = []
        results: list[Result] = []
        is_multi = len(categories) != 1
        for cat_name in categories:
            if cat_name not in CATEGORY_SEARCHERS:
                search_errors.append(f"Unknown category: {cat_name}")
                continue
            try:
                cat_results = CATEGORY_SEARCHERS[cat_name](
                    patient_id, q, status, **filter_kwargs
                )
                if is_multi:
                    results.extend(cat_results[:ALL_CATEGORY_LIMIT])
                else:
                    results.extend(cat_results)
            except Exception as exc:
                log.error("search category=%s failed: %s", cat_name, exc)
                search_errors.append(f"{cat_name}: {str(exc)}")

        if is_multi:
            results.sort(key=lambda r: r.get("date", ""), reverse=True)
            results = results[:MAX_RESULTS]

        payload = {"results": results, "count": len(results)}
        if search_errors:
            payload["search_errors"] = search_errors
        user_id = self.request.headers.get("canvas-logged-in-user-id", "")
        log.info(
            "api_request endpoint=/search patient_id=%s user=%s query=%s results=%d",
            patient_id, user_id, q[:100], len(results),
        )
        return [JSONResponse(payload)]
