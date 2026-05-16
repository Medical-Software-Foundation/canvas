"""Questionnaire lookup helpers for the Exam tab.

ROS and PE sections need a `Questionnaire` row to bind to. Canvas
instances differ on what they have configured — some ship "Brief ROS"
and "Standard ROS" defaults, others have practice-authored
questionnaires. We:

1. If a code-pinning secret (`ros-questionnaire-code` /
   `pe-questionnaire-code`) is set, look up by exact code first.
2. Otherwise filter by a name-pattern heuristic per kind, scoped to
   active questionnaires that can originate in charting.
"""
from __future__ import annotations

import uuid
from typing import Any, Literal

from canvas_sdk.v1.data import Questionnaire
from django.db.models import Q
from logger import log

Kind = Literal["ros", "pe"]

_NAME_PATTERNS: dict[str, Q] = {
    # ROS: "Brief ROS", "Standard ROS", "Review of Systems"
    "ros": Q(name__icontains="review of systems") | Q(name__icontains="ros"),
    # PE: any name containing "physical" or "exam" (substring), or "PE" as
    # a whole word. The `__iregex` `\ype\y` (Postgres word-boundary syntax)
    # catches "Brief PE" and "Standard PE" while not matching unrelated
    # substrings like "spec" or "speech".
    "pe": (
        Q(name__icontains="physical")
        | Q(name__icontains="exam")
        | Q(name__iregex=r"\ype\y")
    ),
}

# Canvas Questionnaire.status is a 2-char code: "AC" = active. The earlier
# `status="active"` matched zero rows on every instance.
ACTIVE_STATUS = "AC"


def find_questionnaires(kind: str, secret_code: str | None) -> list[Questionnaire]:
    """Return candidate questionnaire rows for an Exam-tab section.

    `kind` is "ros" or "pe". `secret_code` (from plugin secrets) pins a
    specific row by `code` when set; if no match, falls through to the
    name-heuristic.
    """
    if kind not in _NAME_PATTERNS:
        return []

    if secret_code:
        pinned = Questionnaire.objects.filter(
            code=secret_code,
            status=ACTIVE_STATUS,
        ).first()
        if pinned:
            return [pinned]
        log.info(
            f"[questionnaires] secret_code={secret_code!r} for kind={kind!r} "
            f"not found; falling back to name heuristic"
        )

    pattern = _NAME_PATTERNS[kind]
    return list(
        Questionnaire.objects.filter(
            pattern,
            status=ACTIVE_STATUS,
        ).order_by("name")
    )


def get_questionnaire_detail(questionnaire_id: str) -> dict[str, Any] | None:
    """Load a questionnaire's metadata + question list for client rendering.

    Returns None for both not-found and invalid-format IDs so the caller
    can map both to a clean 404 instead of leaking a 500.

    ``Questionnaire.id`` is a ``UUIDField``; passing a non-UUID string
    raises ``django.core.exceptions.ValidationError`` *before* the query
    runs (UUIDField validates first). Without that exception caught, it
    escaped the handler, SimpleAPI converted it to a 500 with an empty
    body, and Django's exception-formatting pipeline allocated ~48 MB
    rendering the traceback. We CANNOT import ``ValidationError`` —
    Canvas's plugin sandbox blocks ``django.core.exceptions``. Instead
    pre-validate via ``uuid.UUID()`` (which Python ships natively); a
    bad string raises ``ValueError`` and we bail with None before the
    ORM call.

    The ``prefetch_related`` call collapses the N+1 on the success path:
    a 50-question questionnaire with 10 options each goes from ~601
    round trips (1 + 50 + 50 + 500) to 4 (Questionnaire, questions,
    response_option_sets, options), with per-request RSS dropping by
    roughly the same factor.
    """
    try:
        uuid.UUID(questionnaire_id)
    except (ValueError, TypeError, AttributeError):
        return None
    try:
        q = (
            Questionnaire.objects
            .prefetch_related("questions__response_option_set__options")
            .get(id=questionnaire_id)
        )
    except Questionnaire.DoesNotExist:
        return None

    questions: list[dict[str, Any]] = []
    for question in q.questions.all():
        ros = question.response_option_set
        options: list[dict[str, str]] = []
        q_type = ""
        if ros:
            q_type = ros.type or ""
            options = [
                {"name": o.name or "", "code": o.code or "", "value": str(o.value or "")}
                for o in ros.options.all()
            ]
        questions.append({
            "id": question.pk,
            "label": question.name or "",
            "code_system": question.code_system or "",
            "code": question.code or "",
            "type": q_type,
            "options": options,
        })

    return {
        "id": str(q.id),
        "name": q.name or "",
        "code": q.code or "",
        "code_system": q.code_system or "",
        "questions": questions,
    }
