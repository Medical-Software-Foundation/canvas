"""Shared fixtures: fake claims and a recording ClaimEffect stand-in."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest

HELPERS = "mark_note_as_cash_pay.helpers.cash_pay"

ENABLED = {
    "CASH_PAY_ENABLED": "true",
    "CASH_PAY_QUEUE_NAME": "CashPay",
    "CASH_PAY_LABEL_NAME": "Cash Pay",
}


def make_claim(queue: str | None, labeled: bool, claim_id: str = "claim-1") -> Any:
    """A claim whose ``labels.filter(...).exists()`` reports ``labeled``."""
    claim = MagicMock()
    claim.id = claim_id
    claim.current_queue = SimpleNamespace(name=queue) if queue else None
    claim.labels.filter.return_value.exists.return_value = labeled
    return claim


class RecordingClaimEffect:
    """Records each ClaimEffect call as (method, claim_id, args) tuples."""

    calls: ClassVar[list[tuple[str, str, Any]]] = []

    def __init__(self, claim_id: str) -> None:
        self.claim_id = claim_id

    def _rec(self, name: str, arg: Any) -> tuple[str, Any]:
        RecordingClaimEffect.calls.append((name, self.claim_id, arg))
        return (name, arg)

    def add_labels(self, labels: list[str]) -> Any:
        return self._rec("add_labels", labels)

    def remove_labels(self, labels: list[str]) -> Any:
        return self._rec("remove_labels", labels)

    def move_to_queue(self, queue: str) -> Any:
        return self._rec("move_to_queue", queue)

    def add_comment(self, comment: str) -> Any:
        return self._rec("add_comment", comment)


@pytest.fixture
def claim_effect():
    RecordingClaimEffect.calls = []
    with patch(f"{HELPERS}.ClaimEffect", RecordingClaimEffect):
        yield RecordingClaimEffect


@pytest.fixture
def queue_exists():
    """Patch ClaimQueue so ``filter(name=...).exists()`` returns the set value."""
    with patch(f"{HELPERS}.ClaimQueue") as cq:
        cq.objects.filter.return_value.exists.return_value = True
        yield cq


def methods(effects: list[Any]) -> list[str]:
    return [e[0] for e in effects]
