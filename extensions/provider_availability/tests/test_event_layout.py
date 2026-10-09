"""Install rebuilds every provider's calendar events only when EVENT_LAYOUT_VERSION changes.

So a change to the code that draws events has to be a decision: does it alter
the events themselves (bump the version, so installs rebuild them), or not
(leave it)? This fails whenever that code changes until the lock is updated,
which forces the question. Comments and docstrings do not count as changes.
"""

import ast
import hashlib
import json
from pathlib import Path

from provider_availability.engine.event_sync import EVENT_LAYOUT_VERSION

PACKAGE = Path(__file__).parent.parent / "provider_availability"
# The modules that decide what events look like and which calendars they land on.
DRAWING_CODE = ["engine/event_sync.py", "engine/admin_calendar.py"]
LOCK = Path(__file__).parent / "event_layout_lock.json"


def _without_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            first = body[0].value if body and isinstance(body[0], ast.Expr) else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                node.body = body[1:] or [ast.Pass()]
    return tree


def drawing_code_fingerprint() -> str:
    digest = hashlib.sha256()
    for rel in DRAWING_CODE:
        tree = _without_docstrings(ast.parse((PACKAGE / rel).read_text()))
        digest.update(rel.encode())
        digest.update(ast.dump(tree).encode())
    return digest.hexdigest()


def test_event_layout_lock_matches_the_drawing_code():
    lock = json.loads(LOCK.read_text())
    current = {"event_layout_version": EVENT_LAYOUT_VERSION, "drawing_code": drawing_code_fingerprint()}
    assert lock == current, (
        "The event-drawing code changed. If the events it draws are different (titles, times, "
        "recurrence, calendars), bump EVENT_LAYOUT_VERSION in engine/event_sync.py so installs "
        "rebuild them. Either way, set tests/event_layout_lock.json to:\n" + json.dumps(current, indent=2)
    )


def test_comments_and_docstrings_do_not_change_the_fingerprint():
    a = ast.dump(_without_docstrings(ast.parse('def f():\n    """Doc."""\n    return 1  # note\n')))
    b = ast.dump(_without_docstrings(ast.parse("def f():\n    return 1\n")))
    c = ast.dump(_without_docstrings(ast.parse("def f():\n    return 2\n")))
    assert a == b and a != c
