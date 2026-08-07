"""Finding the team that receives slot-opened tasks."""

from unittest.mock import MagicMock, patch

from scheduling_waitlist.services.team_resolver import resolve_team_id

MODULE = "scheduling_waitlist.services.team_resolver"

DASHED = "0f8f0f9e-1c2b-4a5d-8e7f-0a1b2c3d4e5f"


def _team(team_id=DASHED):
    team = MagicMock()
    team.id = team_id
    return team


class TestResolveTeamId:
    def test_an_unset_setting_resolves_to_nothing(self):
        # The caller must then decline to raise the task: a task with no team is
        # a task nobody opens.
        assert resolve_team_id("") == ""
        assert resolve_team_id(None) == ""

    def test_whitespace_only_resolves_to_nothing(self):
        assert resolve_team_id("   ") == ""

    def test_a_matching_identifier_is_returned(self):
        with patch(f"{MODULE}.Team") as team_model:
            team_model.objects.filter.return_value.first.return_value = _team()

            assert resolve_team_id(DASHED) == DASHED

    def test_an_undashed_identifier_also_matches(self):
        with patch(f"{MODULE}.Team") as team_model:
            team_model.objects.filter.return_value.first.return_value = _team()

            resolve_team_id(DASHED.replace("-", ""))

        queried = team_model.objects.filter.call_args.kwargs["id__in"]
        assert DASHED in queried

    def test_a_team_name_is_accepted_as_a_fallback(self):
        # An administrator filling in a setting is far likelier to have the name
        # to hand than an identifier.
        with patch(f"{MODULE}.Team") as team_model:
            by_id = MagicMock()
            by_id.first.return_value = None
            by_name = MagicMock()
            by_name.first.return_value = _team()
            team_model.objects.filter.side_effect = [by_id, by_name]

            assert resolve_team_id("Front Desk") == DASHED

    def test_the_name_lookup_is_exact(self):
        with patch(f"{MODULE}.Team") as team_model:
            by_id = MagicMock()
            by_id.first.return_value = None
            by_name = MagicMock()
            by_name.first.return_value = _team()
            team_model.objects.filter.side_effect = [by_id, by_name]

            resolve_team_id("Front Desk")

        assert team_model.objects.filter.call_args.kwargs == {"name": "Front Desk"}

    def test_nothing_matching_resolves_to_nothing(self):
        with patch(f"{MODULE}.Team") as team_model:
            missing = MagicMock()
            missing.first.return_value = None
            team_model.objects.filter.return_value = missing

            assert resolve_team_id("Nobody") == ""
