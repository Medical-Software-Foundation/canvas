import json
import re
import uuid
from datetime import date, datetime, timezone
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import (
    APIKeyAuthMixin,
    SimpleAPIRoute,
    StaffSessionAuthMixin,
)
from logger import log

from chart_command_search.models.feedback import CustomStaff, SearchFeedback

_UUID_RE = re.compile(
    r"(?i)^[0-9a-f]{32}$|^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_VALID_RATINGS = frozenset({"up", "down"})
_MAX_QUERY_LENGTH = 5000
_MAX_COMMENT_LENGTH = 2000
_MAX_SUMMARY_LENGTH = 10000
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200
_AUDIT_PREFIX = "AI SEARCH FEEDBACK"


def _serialize_feedback(fb: SearchFeedback) -> dict[str, Any]:
    """Serialize a SearchFeedback record for API response."""
    staff_id = ""
    staff_name = ""
    try:
        staff_obj = fb.staff
        if staff_obj:
            staff_id = str(staff_obj.id)
            first = getattr(staff_obj, "first_name", "") or ""
            last = getattr(staff_obj, "last_name", "") or ""
            staff_name = f"{first} {last}".strip()
    except Exception:
        pass

    created_at = ""
    if fb.created_at:
        try:
            created_at = fb.created_at.isoformat()
        except Exception:
            created_at = str(fb.created_at)

    return {
        "feedback_id": fb.feedback_id or "",
        "patient_id": fb.patient_id or "",
        "staff_id": staff_id,
        "staff_name": staff_name,
        "query": fb.query or "",
        "answer_summary": fb.answer_summary or "",
        "answer_key_findings": fb.answer_key_findings or [],
        "rating": fb.rating or "",
        "comment": fb.comment or "",
        "created_at": created_at,
    }


class FeedbackSubmitAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """POST /feedback — staff submits a thumbs up/down rating for an AI response."""

    PATH = "/feedback"

    def post(self) -> list[Response | Effect]:
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, TypeError):
            return [JSONResponse({"error": "Invalid JSON body"}, status_code=HTTPStatus.BAD_REQUEST)]

        patient_id = str(body.get("patient_id", "")).strip()
        query = str(body.get("query", "")).strip()
        answer_summary = str(body.get("answer_summary", "")).strip()
        answer_key_findings = body.get("answer_key_findings", [])
        rating = str(body.get("rating", "")).strip().lower()
        comment = str(body.get("comment", "")).strip()

        if not patient_id or not _UUID_RE.match(patient_id):
            return [JSONResponse({"error": "Valid patient_id is required"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not query:
            return [JSONResponse({"error": "query is required"}, status_code=HTTPStatus.BAD_REQUEST)]
        if len(query) > _MAX_QUERY_LENGTH:
            return [JSONResponse({"error": "query exceeds maximum length"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not answer_summary:
            return [JSONResponse({"error": "answer_summary is required"}, status_code=HTTPStatus.BAD_REQUEST)]
        if len(answer_summary) > _MAX_SUMMARY_LENGTH:
            answer_summary = answer_summary[:_MAX_SUMMARY_LENGTH]
        if rating not in _VALID_RATINGS:
            return [JSONResponse({"error": "rating must be 'up' or 'down'"}, status_code=HTTPStatus.BAD_REQUEST)]
        if len(comment) > _MAX_COMMENT_LENGTH:
            comment = comment[:_MAX_COMMENT_LENGTH]
        if not isinstance(answer_key_findings, list):
            answer_key_findings = []

        staff_user_id = self.request.headers.get("canvas-logged-in-user-id", "")
        if not staff_user_id:
            return [JSONResponse({"error": "Unable to identify current user"}, status_code=HTTPStatus.UNAUTHORIZED)]

        try:
            staff_obj = CustomStaff.objects.get(id=staff_user_id)
        except CustomStaff.DoesNotExist:
            return [JSONResponse({"error": "Staff user not found"}, status_code=HTTPStatus.NOT_FOUND)]
        except Exception as exc:
            log.error("%s staff_lookup_failed user=%s error=%s", _AUDIT_PREFIX, staff_user_id, exc)
            return [JSONResponse({"error": "Failed to resolve staff user"}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)]

        feedback_id = str(uuid.uuid4())

        try:
            SearchFeedback.objects.create(
                feedback_id=feedback_id,
                patient_id=patient_id,
                staff=staff_obj,
                query=query,
                answer_summary=answer_summary,
                answer_key_findings=answer_key_findings,
                rating=rating,
                comment=comment,
            )
        except Exception as exc:
            log.error(
                "%s create_failed feedback_id=%s patient=%s user=%s error=%s",
                _AUDIT_PREFIX, feedback_id, patient_id, staff_user_id, exc,
            )
            return [JSONResponse({"error": "Failed to store feedback"}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)]

        log.info(
            "%s created feedback_id=%s patient=%s user=%s rating=%s",
            _AUDIT_PREFIX, feedback_id, patient_id, staff_user_id, rating,
        )

        return [JSONResponse({"feedback_id": feedback_id, "status": "created"}, status_code=HTTPStatus.CREATED)]


class FeedbackQueryAPI(APIKeyAuthMixin, SimpleAPIRoute):
    """GET /feedback-export — external services retrieve feedback records and stats."""

    PATH = "/feedback-export"
    API_KEY_SECRET_NAME = "FEEDBACK_API_KEY"

    def get(self) -> list[Response | Effect]:
        params = self.request.query_params
        mode = params.get("mode", "list").strip().lower()

        qs = SearchFeedback.objects.all()

        patient_id = params.get("patient_id", "").strip()
        if patient_id:
            if not _UUID_RE.match(patient_id):
                return [JSONResponse({"error": "Invalid patient_id"}, status_code=HTTPStatus.BAD_REQUEST)]
            qs = qs.filter(patient_id=patient_id)

        staff_id = params.get("staff_id", "").strip()
        if staff_id:
            try:
                staff_obj = CustomStaff.objects.get(id=staff_id)
                qs = qs.filter(staff=staff_obj)
            except CustomStaff.DoesNotExist:
                return [JSONResponse({"results": [], "count": 0, "total": 0})]
            except Exception:
                pass

        rating_filter = params.get("rating", "").strip().lower()
        if rating_filter and rating_filter in _VALID_RATINGS:
            qs = qs.filter(rating=rating_filter)

        from_date = params.get("from_date", "").strip()
        if from_date:
            try:
                d = date.fromisoformat(from_date)
                qs = qs.filter(created_at__gte=datetime(d.year, d.month, d.day, tzinfo=timezone.utc))
            except ValueError:
                return [JSONResponse({"error": "Invalid from_date format (use YYYY-MM-DD)"}, status_code=HTTPStatus.BAD_REQUEST)]

        to_date = params.get("to_date", "").strip()
        if to_date:
            try:
                d = date.fromisoformat(to_date)
                qs = qs.filter(
                    created_at__lte=datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc),
                )
            except ValueError:
                return [JSONResponse({"error": "Invalid to_date format (use YYYY-MM-DD)"}, status_code=HTTPStatus.BAD_REQUEST)]

        if mode == "stats":
            return self._stats_response(qs, params)

        return self._list_response(qs, params)

    def _stats_response(
        self, qs: Any, params: Any,
    ) -> list[Response | Effect]:
        from django.db.models import Case, Count, When

        counts = qs.aggregate(
            total=Count("id"),
            up_count=Count(Case(When(rating="up", then=1))),
            down_count=Count(Case(When(rating="down", then=1))),
        )
        total = counts["total"]
        up_count = counts["up_count"]
        down_count = counts["down_count"]

        up_pct = round((up_count / total) * 100, 1) if total > 0 else 0.0
        down_pct = round((down_count / total) * 100, 1) if total > 0 else 0.0

        filters_applied: dict[str, str] = {}
        for key in ("patient_id", "staff_id", "rating", "from_date", "to_date"):
            val = params.get(key, "").strip()
            if val:
                filters_applied[key] = val

        return [JSONResponse({
            "total": total,
            "thumbs_up": up_count,
            "thumbs_down": down_count,
            "thumbs_up_pct": up_pct,
            "thumbs_down_pct": down_pct,
            "filters_applied": filters_applied,
        })]

    def _list_response(
        self, qs: Any, params: Any,
    ) -> list[Response | Effect]:
        try:
            limit = min(int(params.get("limit", _DEFAULT_LIMIT)), _MAX_LIMIT)
        except (ValueError, TypeError):
            limit = _DEFAULT_LIMIT
        if limit < 1:
            limit = _DEFAULT_LIMIT

        try:
            offset = max(int(params.get("offset", 0)), 0)
        except (ValueError, TypeError):
            offset = 0

        total = qs.count()
        records = qs.select_related("staff").order_by("-created_at")[offset : offset + limit]

        results = [_serialize_feedback(fb) for fb in records]

        return [JSONResponse({
            "results": results,
            "count": len(results),
            "total": total,
        })]
