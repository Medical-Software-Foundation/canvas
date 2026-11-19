"""Tests for the claim-timeline WebSocket authentication."""

from unittest.mock import MagicMock

import pytest

from candid.api.websocket import CandidTimelineWebSocket


def _socket(user):
    handler = CandidTimelineWebSocket.__new__(CandidTimelineWebSocket)
    handler.websocket = MagicMock()
    handler.websocket.logged_in_user = user
    return handler


def test_staff_user_is_accepted():
    assert _socket({"id": "staff-1", "type": "Staff"}).authenticate() is True


@pytest.mark.parametrize(
    "user",
    [None, {}, {"id": "pat-1", "type": "Patient"}, {"id": "x", "type": "staff"}],
)
def test_non_staff_or_anonymous_is_rejected(user):
    assert _socket(user).authenticate() is False
