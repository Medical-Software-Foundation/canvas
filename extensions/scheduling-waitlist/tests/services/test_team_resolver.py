"""Finding the team that receives slot-opened tasks."""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from scheduling_waitlist.services.team_resolver import resolve_team_id

MODULE = "scheduling_waitlist.services.team_resolver"

DASHED = "0f8f0f9e-1c2b-4a5d-8e7f-0a1b2c3d4e5f"


def _team(team_id=DASHED):
    team = MagicMock()
    team.id = team_id
    return team


class _TeamModel:
    """A double that rejects non-identifiers the way a UUID column does.

    A plain MagicMock accepts anything, which is why a real bug shipped: the
    resolver put a team *name* into ``id__in``, the database raised rather than
    missing, the handler died, and the name lookup below it was never reached.
    The suite passed throughout. So this double raises instead.
    """

    def __init__(self, by_id=None, by_name=None):
        self._by_id = by_id
        self._by_name = by_name
        self.calls: list[dict] = []

    @property
    def objects(self):
        return self

    def filter(self, **kwargs):
        self.calls.append(kwargs)
        if "id__in" in kwargs:
            for value in kwargs["id__in"]:
                # Mirrors the column: a non-identifier is an error, not a miss.
                uuid.UUID(str(value))
            return MagicMock(first=MagicMock(return_value=self._by_id))
        return MagicMock(first=MagicMock(return_value=self._by_name))

    @property
    def id_lookups(self) -> list[dict]:
        return [call for call in self.calls if "id__in" in call]

    @property
    def name_lookups(self) -> list[dict]:
        return [call for call in self.calls if "name" in call]


class TestUnset:
    def test_an_unset_setting_resolves_to_nothing(self):
        # The caller must then decline to raise the task: a task with no team is
        # a task nobody opens.
        assert resolve_team_id("") == ""
        assert resolve_team_id(None) == ""

    def test_whitespace_only_resolves_to_nothing(self):
        assert resolve_team_id("   ") == ""


class TestByIdentifier:
    def test_a_matching_identifier_is_returned(self):
        model = _TeamModel(by_id=_team())
        with patch(f"{MODULE}.Team", model):
            assert resolve_team_id(DASHED) == DASHED

    def test_an_undashed_identifier_also_matches(self):
        model = _TeamModel(by_id=_team())
        with patch(f"{MODULE}.Team", model):
            resolve_team_id(DASHED.replace("-", ""))

        # Normalised, so the column sees the canonical form either way.
        assert DASHED in model.id_lookups[0]["id__in"]

    def test_only_identifiers_ever_reach_the_identifier_column(self):
        model = _TeamModel(by_id=_team())
        with patch(f"{MODULE}.Team", model):
            resolve_team_id(DASHED)

        for value in model.id_lookups[0]["id__in"]:
            uuid.UUID(str(value))

    def test_a_matching_identifier_needs_no_name_lookup(self):
        model = _TeamModel(by_id=_team())
        with patch(f"{MODULE}.Team", model):
            resolve_team_id(DASHED)

        assert model.name_lookups == []


class TestByName:
    """The path that never worked: a name used to be fed to the UUID column."""

    def test_a_team_name_is_accepted(self):
        # An administrator filling in a setting is far likelier to have the name
        # to hand than an identifier.
        model = _TeamModel(by_name=_team())
        with patch(f"{MODULE}.Team", model):
            assert resolve_team_id("All Responsibilities") == DASHED

    def test_a_name_never_touches_the_identifier_column(self):
        # The regression itself. Without this the double would raise.
        model = _TeamModel(by_name=_team())
        with patch(f"{MODULE}.Team", model):
            resolve_team_id("All Responsibilities")

        assert model.id_lookups == []
        assert model.name_lookups == [{"name": "All Responsibilities"}]

    def test_the_name_lookup_is_exact(self):
        model = _TeamModel(by_name=_team())
        with patch(f"{MODULE}.Team", model):
            resolve_team_id("Front Desk")

        assert model.name_lookups == [{"name": "Front Desk"}]

    def test_a_name_that_looks_faintly_like_an_identifier_is_still_a_name(self):
        # Dashes alone do not make it one.
        model = _TeamModel(by_name=_team())
        with patch(f"{MODULE}.Team", model):
            assert resolve_team_id("front-desk-team") == DASHED

        assert model.id_lookups == []


class TestNoMatch:
    def test_an_unknown_name_resolves_to_nothing_without_raising(self):
        model = _TeamModel()
        with patch(f"{MODULE}.Team", model):
            assert resolve_team_id("Nobody") == ""

    def test_an_unknown_identifier_falls_through_to_the_name_lookup(self):
        model = _TeamModel()
        with patch(f"{MODULE}.Team", model):
            assert resolve_team_id(DASHED) == ""

        assert model.id_lookups and model.name_lookups


class TestTheDoubleItself:
    def test_it_rejects_a_non_identifier_the_way_the_column_does(self):
        # Otherwise every test above proves nothing.
        model = _TeamModel()

        with pytest.raises(ValueError):
            model.objects.filter(id__in={"All Responsibilities"})
