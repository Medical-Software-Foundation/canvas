"""Test-suite-wide fixtures for exam_chart_app.

The autouse fixture below default-mocks the AttributeHub-touching
helpers reachable from ExamChartingAPI's route handlers. Without it,
finalize tests rely on the un-mocked behavior of
``set_narrative`` / ``mark_finalized`` / ``mark_ever_finalized`` —
which works today because the test environment's AttributeHub query
raises a DB-class exception that the narrow-catch swallows, but
that's fragile (a future canvas_sdk change to the failure mode
would break ~14 tests with confusing AttributeHub-related errors
rather than clear assertion failures).

Tests that need specific behavior for these helpers (DB-error
swallow, programming-bug propagation, narrative-flush assertions)
keep their explicit ``@patch`` decorators — those stack on top of
this fixture's defaults for the duration of the test.

``get_draft`` / ``set_draft`` are not auto-mocked because every
``save_state`` and ``get_state`` test that reaches them mocks them
explicitly (the behavior of those calls is part of what the tests
are asserting).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _default_post_gate_orm_mocks():
    """Default mocks for post-gate ORM writes in finalize().

    Each yields a MagicMock that the test can inspect if it wants,
    but most tests don't care — they just need these calls to not
    raise. Tests that explicitly ``@patch`` any of these functions
    will get the decorator's mock for the duration of the test; the
    fixture's mock is back in place after the decorator exits.
    """
    with patch("exam_chart_app.api.exam_api.set_narrative"), \
         patch("exam_chart_app.api.exam_api.mark_finalized"), \
         patch("exam_chart_app.api.exam_api.mark_ever_finalized"):
        yield
