"""Narrow-catch primitives for DB-class exceptions across plugin routes.

The Canvas plugin sandbox blocks ``from django.db import DatabaseError``
(verified 2026-05-21), so the natural ``except DatabaseError:`` pattern
isn't available. Instead we filter exceptions by class name against the
``DB_EXCEPTION_NAMES`` frozenset and swallow only the DB-class transients;
non-DB exceptions (``AttributeError``, ``KeyError``, ``TypeError`` from
programming bugs) propagate to Sentry as 500s.

``DB_EXCEPTION_NAMES`` covers Django's full ``django.db.utils``
exception hierarchy: every subclass of ``DatabaseError`` (incl.
``InternalError`` and ``ProgrammingError`` — both can fire on transient
cursor/connection failures per PEP 249) plus the sibling
``InterfaceError``. The list is symmetric with what ``except DatabaseError``
would have caught had the sandbox allowed it.

``swallow_db_read`` is the standard wrapper for ORM-read calls in route
handlers: a DB transient logs via ``log.exception`` (paging Sentry) and
returns ``default``; the route can then degrade to empty/default data
rather than 500-ing. Used pervasively across ``exam_api`` and
``exam_search_api`` to keep error handling uniform.
"""
from __future__ import annotations

from typing import Any, Callable, TypeVar

from logger import log

DB_EXCEPTION_NAMES = frozenset({
    "DatabaseError", "OperationalError", "IntegrityError",
    "InterfaceError", "DataError", "NotSupportedError",
    "InternalError", "ProgrammingError",
})

T = TypeVar("T")


def swallow_db_read(operation: str, fn: Callable[[], T], default: Any) -> T:
    """Run ``fn()``; on DB-class transient, log + return ``default``.

    Programming bugs (``AttributeError``, ``KeyError``, ``TypeError``,
    etc.) propagate to the SimpleAPI outer catch as 500s + Sentry —
    only the DB exception classes listed in ``DB_EXCEPTION_NAMES`` are
    swallowed here. ``log.exception`` pages on-call so transient blips
    are observable even when the user sees a graceful degraded response.

    ``operation`` is a short human-readable label (e.g.
    ``"/exam/state get_draft"``) used in the log message; choose names
    that identify both the route and the helper being called.

    ``default`` is typed ``Any`` so callers can pass empty literals
    (``[]``, ``({}, False)``, ``None``) without mypy narrowing the
    ``T`` TypeVar from the default's type — the return type stays
    pinned to whatever ``fn`` returns, which is what callers want.
    """
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — narrowed via DB_EXCEPTION_NAMES
        if exc.__class__.__name__ not in DB_EXCEPTION_NAMES:
            raise
        log.exception(
            f"[exam_chart_app] {operation} failed (DB transient swallowed)"
        )
        return default  # type: ignore[no-any-return]
