"""Rule model: JSON round-trips through TextField accessors."""

import pytest

from note_protocol_automation.models.rule import Rule


@pytest.mark.django_db
def test_predicates_and_commands_round_trip() -> None:
    """set_predicates/set_commands serialize; the typed getters parse back."""
    rule = Rule(name="Annual Physical", note_type_id="nt-1", enabled=True, match="all", priority=0)
    rule.set_predicates([{"signal": "age", "operator": ">=", "value": 18}])
    rule.set_commands(["diagnose", "plan"])
    rule.save()

    fetched = Rule.objects.get(dbid=rule.dbid)
    assert fetched.predicate_list() == [{"signal": "age", "operator": ">=", "value": 18}]
    assert fetched.command_list() == ["diagnose", "plan"]


@pytest.mark.django_db
def test_empty_json_fields_default_to_lists() -> None:
    """A rule saved without predicates/commands reads back as empty lists, not errors."""
    rule = Rule.objects.create(
        name="empty", note_type_id="nt-2", enabled=True, match="all", priority=0
    )
    assert rule.predicate_list() == []
    assert rule.command_list() == []
