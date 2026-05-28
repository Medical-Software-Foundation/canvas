"""End-to-end smoke tests for the deployed `assistant` plugin.

These hit the live /chat endpoint and exercise the full Claude tool-use loop,
so each test takes 5-60 seconds and consumes real Anthropic API tokens. Run
after a fresh `canvas install` to catch regressions in tool selection,
multi-turn behavior, and the iteration budget.

Environment variables:
    HOST       Canvas subdomain (default: general-primary-care-trial).
    STAFF_ID   When set, exercises the "my schedule" case. Skipped otherwise.

Auth: these tests don't carry a Canvas staff session, so the deployed plugin
must have ``AUTH_ENABLED = False`` for them to pass. The session-scoped
``_chat_reachable`` fixture probes /chat once at the start of the run and
skips the entire module if it sees a 401, with a message pointing at the
flag. Flip ``AUTH_ENABLED`` back to True before the next production deploy.

Usage:
    cd example-plugins/assistant
    uv run pytest tests/test_smoke.py -v
    HOST=other-subdomain uv run pytest tests/test_smoke.py -v
    STAFF_ID=<your-id> uv run pytest tests/test_smoke.py -v -k my_schedule
"""

from __future__ import annotations

import os
import re
import warnings
from collections.abc import Iterator
from typing import Any

import pytest
import requests

HOST = os.environ.get("HOST", "general-primary-care-trial")
CHAT_URL = f"https://{HOST}.canvasmedical.com/plugin-io/api/assistant/chat"
STAFF_ID = os.environ.get("STAFF_ID")

# Generous — Claude tool-use loops with web_search can take ~30-60s.
CHAT_TIMEOUT = 90


@pytest.fixture(scope="session", autouse=True)
def _chat_reachable() -> Iterator[None]:
    """Probe /chat once before tests run; skip the suite on 401 (auth on)."""
    try:
        resp = requests.post(CHAT_URL, json={}, timeout=15)
    except requests.RequestException as exc:
        pytest.skip(f"{CHAT_URL} unreachable: {exc}")
    if resp.status_code == 401:
        pytest.skip(
            f"{CHAT_URL} returned 401 — set AUTH_ENABLED=False in "
            "handlers/assistant.py and redeploy before smoke testing "
            "(or carry a Canvas staff session, not supported here)."
        )
    yield


def _post_chat(body: dict[str, Any], timeout: int = CHAT_TIMEOUT) -> requests.Response:
    """POST to /chat with a sensible timeout. Caller asserts on status/body."""
    return requests.post(CHAT_URL, json=body, timeout=timeout)


def _trace_tools(payload: dict[str, Any]) -> list[str]:
    """Return the list of tool names from the response trace, in call order."""
    return [entry.get("tool") for entry in payload.get("trace", []) if entry.get("tool")]


def _assert_used(payload: dict[str, Any], tool: str) -> None:
    """Assert the trace recorded at least one call to `tool`, with context."""
    used = _trace_tools(payload)
    assert tool in used, f"expected {tool!r} in trace, got {used!r}"


# ---- Cases ---------------------------------------------------------------


def test_missing_question_returns_400() -> None:
    """Empty body returns 400 with a specific error message."""
    resp = _post_chat({}, timeout=15)
    assert resp.status_code == 400, f"got {resp.status_code}: {resp.text[:200]}"
    assert resp.json().get("error") == "missing 'question'"


def test_simple_count_uses_count_patients() -> None:
    """"how many patients" should use count_patients and answer with a number."""
    resp = _post_chat({"question": "how many patients do I have?"})
    assert resp.status_code == 200, resp.text[:500]
    payload = resp.json()
    _assert_used(payload, "count_patients")
    answer = payload["answer"]
    assert re.search(r"\d+", answer), f"answer has no number: {answer!r}"


def test_birthday_lookup_uses_find_patients() -> None:
    """Patient lookup by name and date extraction from the result."""
    resp = _post_chat({"question": "what is Reagans birthday?"})
    assert resp.status_code == 200, resp.text[:500]
    payload = resp.json()
    _assert_used(payload, "find_patients")
    # Accept ISO (1989-09-23) or prose ("September 23, 1989") — model picks.
    assert re.search(r"(19|20)\d{2}", payload["answer"]), (
        f"answer has no year: {payload['answer']!r}"
    )


def test_composition_chains_find_patients_then_appointments() -> None:
    """A two-step question should call both find_patients and find_appointments."""
    resp = _post_chat({"question": "what is Reagan Demo's most recent appointment?"})
    assert resp.status_code == 200, resp.text[:500]
    payload = resp.json()
    _assert_used(payload, "find_patients")
    _assert_used(payload, "find_appointments")


@pytest.mark.skipif(
    not STAFF_ID,
    reason="set STAFF_ID env var to exercise the 'my schedule' case",
)
def test_my_schedule_uses_find_appointments() -> None:
    """With staff_id, 'my appointments today' resolves via find_appointments."""
    resp = _post_chat(
        {"question": "what appointments do I have today?", "staff_id": STAFF_ID}
    )
    assert resp.status_code == 200, resp.text[:500]
    payload = resp.json()
    # get_today is preferred but not required — the model may infer the date
    # from the message-framing context.
    _assert_used(payload, "find_appointments")


def test_out_of_scope_question_is_declined_gracefully() -> None:
    """Weather queries should produce a refusal, not a hallucinated answer."""
    resp = _post_chat({"question": "what is the weather in Tokyo today?"})
    assert resp.status_code == 200, resp.text[:500]
    answer = resp.json()["answer"]
    assert re.search(r"don't|cannot|unable|can't|do not have|not able", answer), (
        f"expected a refusal-style answer, got: {answer!r}"
    )


def test_multi_turn_preserves_context() -> None:
    """Turn-2 follow-up uses the turn-1 message history to answer without re-lookup.

    Soft assertion on context preservation: if turn-2 re-calls find_patients
    we emit a warning rather than failing — the model is free to choose,
    and prompt tuning may change this behavior. The hard assertion is just
    that turn-2 still produces an answer with the expected shape (a year).
    """
    resp1 = _post_chat({"question": "look up the patient Reagan Demo and tell me her MRN"})
    assert resp1.status_code == 200, resp1.text[:500]
    payload1 = resp1.json()
    _assert_used(payload1, "find_patients")

    resp2 = _post_chat({"question": "and her birthday?", "messages": payload1["messages"]})
    assert resp2.status_code == 200, resp2.text[:500]
    payload2 = resp2.json()
    assert re.search(r"(19|20)\d{2}", payload2["answer"]), (
        f"turn-2 answer has no year: {payload2['answer']!r}"
    )

    if "find_patients" in _trace_tools(payload2):
        warnings.warn(
            "turn-2 re-called find_patients — context preservation weaker than hoped",
            stacklevel=2,
        )


def test_iteration_budget_under_5() -> None:
    """A simple count should finish in fewer than 5 loop iterations."""
    resp = _post_chat({"question": "how many active patients exist?"})
    assert resp.status_code == 200, resp.text[:500]
    iterations = resp.json().get("iterations", 999)
    assert iterations < 5, f"iterations={iterations} (expected <5)"
