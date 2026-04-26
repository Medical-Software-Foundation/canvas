from __future__ import annotations

from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api

from staff_directory.data.nucc_seeder import ensure_nucc_seed
from staff_directory.services.nucc import search_nucc, serialize_nucc


class NuccAPI(StaffSessionAuthMixin, SimpleAPI):
    """Typeahead lookup for NUCC taxonomy codes."""

    PREFIX = "/nucc"

    @api.get("/search")
    def search(self) -> list[Response | Effect]:
        ensure_nucc_seed()

        params = self.request.query_params
        query = params.get("q", "")
        try:
            limit = int(params.get("limit", "25"))
        except (TypeError, ValueError):
            limit = 25

        results = search_nucc(query, limit=limit)
        return [
            JSONResponse(
                {
                    "results": [serialize_nucc(r) for r in results],
                    "count": len(results),
                },
                status_code=HTTPStatus.OK,
            )
        ]
