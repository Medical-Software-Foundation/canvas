from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from auto_fax.services.config import CoverSheet, RecipientSpec, Rule
from auto_fax.services.delivery import (
    CANVAS_BOT_STAFF_ID,
    already_faxed,
    cover_kwargs,
    destination,
    sendable,
    skip_already_faxed,
    today_for,
)
from auto_fax.services.recipients import Recipient

MODULE = "auto_fax.services.delivery"


def _rule(cover=None):
    return Rule(
        name="r",
        note_type_codes=frozenset({"*"}),
        trigger_states=frozenset({"LKD"}),
        recipients=(RecipientSpec(type="facility"),),
        cover_sheet=cover,
    )


def _recipient(digits="5552340111", problem=None):
    return Recipient(_rule(), "facility", "Oak House", digits, problem=problem)


class _FrozenDatetime(datetime):
    """01:00 UTC on 4 Nov 2026, which is still the evening of 3 Nov in the US."""

    @classmethod
    def now(cls, tz=None):
        moment = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)
        return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        (
            SimpleNamespace(last_known_timezone=ZoneInfo("America/New_York")),
            date(2026, 11, 3),
        ),
        (SimpleNamespace(last_known_timezone=None), date(2026, 11, 4)),
        (None, date(2026, 11, 4)),
    ],
)
def test_today_is_the_providers_date_not_utc(provider, expected):
    with patch(f"{MODULE}.datetime", _FrozenDatetime):
        assert today_for(provider) == expected


def test_sendable_drops_problems_and_duplicate_numbers():
    good = _recipient()
    with patch(f"{MODULE}.log") as log:
        result = sendable(
            [good, _recipient(), _recipient(None, problem="no fax")], "lab order 1"
        )
    assert result == [good]
    log.warning.assert_called_once_with(
        "[auto_fax] lab order 1 rule 'r': skipped facility: no fax"
    )


def test_destination_prefers_the_test_number():
    assert destination(_recipient(), "5559990000") == "5559990000"
    assert destination(_recipient(), None) == "5552340111"


def test_already_faxed_filters_plugin_faxes_and_drops_failures():
    events = MagicMock()
    values = events.filter.return_value.exclude.return_value.values_list
    values.return_value = ["+15552340111", None, ""]
    assert already_faxed(events) == {"+15552340111"}
    events.filter.assert_called_once_with(
        event_type="FAXED", originator__staff__id=CANVAS_BOT_STAFF_ID
    )
    events.filter.return_value.exclude.assert_called_once_with(delivered_by_fax=False)


def test_skip_already_faxed_compares_the_dialed_number():
    other = Recipient(_rule(), "facility", "Elm", "5552340122")
    assert skip_already_faxed([_recipient(), other], None, {"+15552340111"}) == [other]
    # With a test number every fax goes there, so one prior test fax skips all.
    assert (
        skip_already_faxed([_recipient(), other], "5559990000", {"+15559990000"}) == []
    )


def test_cover_kwargs():
    assert cover_kwargs(_rule(), "loc-1", "x") == {}
    rule = _rule(CoverSheet(subject="S", comment="C"))
    assert cover_kwargs(rule, "loc-1", "x") == {
        "include_coversheet": True,
        "subject": "S",
        "comment": "C",
        "location_id": "loc-1",
    }
    with patch(f"{MODULE}.log") as log:
        assert cover_kwargs(rule, None, "referral order 7") == {}
    log.warning.assert_called_once_with(
        "[auto_fax] referral order 7 has no practice location; sending rule 'r' without its coversheet"
    )
