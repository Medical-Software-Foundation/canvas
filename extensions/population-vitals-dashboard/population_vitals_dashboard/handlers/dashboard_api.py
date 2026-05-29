"""DashboardAPI — SimpleAPI handler for the population vitals dashboard.

Routes (all under /plugin-io/api/population_vitals_dashboard/):
  GET /app/            — HTML shell
  GET /app/main.js     — vanilla JS client (Chart.js via CDN)
  GET /app/styles.css  — CSS
  GET /app/stats       — JSON aggregates
    query params:
      metric   — weight | bmi | height | systolic | diastolic
      min_age  — int, optional
      max_age  — int, optional
      sex      — F | M | O | UNK | all (default: all)
      start    — ISO date/datetime string, optional (default: 12 months ago)
      end      — ISO date/datetime string, optional (default: now)

Auth: StaffSessionAuthMixin — non-staff sessions are rejected at the mixin level.
"""

from datetime import UTC, datetime
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from logger import log

from population_vitals_dashboard.vitals_aggregation import (
    ALL_METRICS,
    get_default_date_window,
    get_stats,
)

# Cache-bust token — generated once at module load.
_CACHE_BUST = str(int(datetime.now(UTC).timestamp()))

_PREFIX = "population_vitals_dashboard"


class DashboardAPI(StaffSessionAuthMixin, SimpleAPI):
    """Staff-only HTTP API that serves the population vitals dashboard."""

    PREFIX = "/app"

    @api.get("/")
    def get_html(self) -> list[Response | Effect]:
        """Serve the HTML shell for the dashboard."""
        staff_id = self.request.headers.get("canvas-logged-in-user-id", "")
        log.info("DashboardAPI.get_html staff=%s", staff_id)
        content = render_to_string(
            "templates/index.html",
            {
                "cache_bust": _CACHE_BUST,
                "api_prefix": f"/plugin-io/api/{_PREFIX}",
            },
        )
        return [HTMLResponse(content, status_code=HTTPStatus.OK)]

    @api.get("/main.js")
    def get_js(self) -> list[Response | Effect]:
        """Serve the vanilla JS client."""
        content = render_to_string(
            "templates/main.js",
            {
                "cache_bust": _CACHE_BUST,
                "api_prefix": f"/plugin-io/api/{_PREFIX}",
            },
        )
        return [
            Response(
                content=content.encode("utf-8"),
                status_code=HTTPStatus.OK,
                headers={"Content-Type": "application/javascript; charset=utf-8"},
            )
        ]

    @api.get("/styles.css")
    def get_css(self) -> list[Response | Effect]:
        """Serve the dashboard CSS."""
        content = render_to_string("templates/styles.css", {})
        return [
            Response(
                content=content.encode("utf-8"),
                status_code=HTTPStatus.OK,
                headers={"Content-Type": "text/css; charset=utf-8"},
            )
        ]

    @api.get("/stats")
    def get_stats(self) -> list[Response | Effect]:
        """Return JSON aggregate statistics for the requested metric and cohort.

        Query parameters:
          metric   — required; one of weight | bmi | height | systolic | diastolic
          min_age  — optional int
          max_age  — optional int
          sex      — optional; F | M | O | UNK | all
          start    — optional ISO datetime string
          end      — optional ISO datetime string
        """
        params = self.request.query_params
        metric = params.get("metric", "").strip()

        if not metric:
            return [
                JSONResponse(
                    {"error": "metric parameter is required", "valid_metrics": sorted(ALL_METRICS)},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if metric not in ALL_METRICS:
            return [
                JSONResponse(
                    {
                        "error": f"unknown metric: {metric!r}",
                        "valid_metrics": sorted(ALL_METRICS),
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        # Parse optional age filters.
        min_age = _parse_optional_int(params.get("min_age"))
        max_age = _parse_optional_int(params.get("max_age"))

        # Parse sex filter.
        sex_raw = params.get("sex", "all").strip()
        sex: str | None = None if sex_raw.upper() == "ALL" or not sex_raw else sex_raw

        # Parse date window.
        default_start, default_end = get_default_date_window()
        start = _parse_optional_datetime(params.get("start")) or default_start
        end = _parse_optional_datetime(params.get("end")) or default_end

        if start >= end:
            return [
                JSONResponse(
                    {"error": "start must be before end"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        log.info(
            "DashboardAPI.get_stats metric=%s min_age=%s max_age=%s sex=%s start=%s end=%s",
            metric,
            min_age,
            max_age,
            sex,
            start.date(),
            end.date(),
        )

        result = get_stats(
            metric=metric,
            min_age=min_age,
            max_age=max_age,
            sex=sex,
            start=start,
            end=end,
            secrets=self.secrets,
        )

        if "error" in result:
            error_type = result["error"]
            if error_type == "cohort_too_small":
                return [
                    JSONResponse(
                        {
                            "error": "cohort_too_small",
                            "message": (
                                "The selected cohort is too small to display statistics. "
                                "Please broaden your filters."
                            ),
                        },
                        status_code=HTTPStatus.OK,
                    )
                ]
            if error_type == "no_data":
                return [
                    JSONResponse(
                        {
                            "error": "no_data",
                            "message": "No observations found for the selected filters.",
                            "cohort_count": result.get("cohort_count"),
                        },
                        status_code=HTTPStatus.OK,
                    )
                ]
            return [
                JSONResponse(
                    result,
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        return [JSONResponse(result, status_code=HTTPStatus.OK)]


# ---------- parsing helpers --------------------------------------------------


def _parse_optional_int(value: str | None) -> int | None:
    """Parse an optional integer query parameter. Returns None on invalid or missing input."""
    if not value or not value.strip():
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def _parse_optional_datetime(value: str | None) -> datetime | None:
    """Parse an optional ISO datetime/date string. Returns None on failure."""
    if not value or not value.strip():
        return None
    raw = value.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            continue
    return None
