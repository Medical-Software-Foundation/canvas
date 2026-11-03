import json
from unittest.mock import patch

import pytest

from auto_fax.services.config import (
    MODE_DRY_RUN,
    MODE_LIVE,
    MODE_OFF,
    RECIPIENT_CARE_TEAM_ROLE,
    RECIPIENT_FACILITY,
    RECIPIENT_FIXED,
    CoverSheet,
    Rule,
    load_config,
)

PCP = "446050000"


def _rule(**overrides):
    rule = {
        "name": "Visit notes to PCP",
        "note_type_codes": ["office_visit"],
        "recipients": [{"type": "care_team_role", "role_codes": [PCP]}],
    }
    rule.update(overrides)
    return rule


def _secrets(rules=None, mode="live", test_number=""):
    return {
        "AUTO_FAX_MODE": mode,
        "AUTO_FAX_RULES": json.dumps(rules) if rules is not None else "",
        "AUTO_FAX_TEST_FAX_NUMBER": test_number,
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("live", MODE_LIVE),
        (" DRY_RUN ", MODE_DRY_RUN),
        ("off", MODE_OFF),
        ("", MODE_OFF),
        (None, MODE_OFF),
    ],
)
def test_mode(raw, expected):
    assert load_config({"AUTO_FAX_MODE": raw}).mode == expected


def test_unknown_mode_is_off_and_logged():
    with patch("auto_fax.services.config.log") as log:
        config = load_config({"AUTO_FAX_MODE": "yes please"})
    assert config.mode == MODE_OFF
    assert config.errors == (
        "AUTO_FAX_MODE 'yes please' is not one of ['dry_run', 'live', 'off']; treating as off",
    )
    log.warning.assert_called_once_with(f"[auto_fax] config: {config.errors[0]}")


def test_empty_secrets_mean_off_with_no_rules():
    config = load_config({})
    assert config.mode == MODE_OFF
    assert config.rules == ()
    assert config.test_fax_digits is None
    assert config.errors == ()


def test_full_rule_parses():
    config = load_config(
        _secrets(
            [
                _rule(
                    trigger_states=["LKD", "RLK"],
                    location_ids=["loc-1"],
                    cover_sheet={"subject": "Visit note", "comment": "Please file."},
                    recipients=[
                        {"type": "care_team_role", "role_codes": [PCP, "3842006"]},
                        {"type": "facility"},
                        {
                            "type": "fixed",
                            "name": "Records office",
                            "fax": "(555) 234-0100",
                        },
                    ],
                )
            ]
        )
    )
    assert config.errors == ()
    (rule,) = config.rules
    assert rule.name == "Visit notes to PCP"
    assert rule.note_type_codes == frozenset({"office_visit"})
    assert rule.trigger_states == frozenset({"LKD", "RLK"})
    assert rule.location_ids == frozenset({"loc-1"})
    assert rule.cover_sheet == CoverSheet(subject="Visit note", comment="Please file.")
    care_team, facility, fixed = rule.recipients
    assert (
        care_team.type == RECIPIENT_CARE_TEAM_ROLE
        and care_team.role_codes == frozenset({PCP, "3842006"})
    )
    assert facility.type == RECIPIENT_FACILITY
    assert (
        fixed.type == RECIPIENT_FIXED
        and fixed.name == "Records office"
        and fixed.fax_digits == "5552340100"
    )


def test_defaults_trigger_on_lock_only():
    (rule,) = load_config(_secrets([_rule()])).rules
    assert rule.trigger_states == frozenset({"LKD"})
    assert rule.cover_sheet is None
    assert rule.location_ids == frozenset()


def test_string_values_are_accepted_as_one_item_lists():
    (rule,) = load_config(
        _secrets([_rule(note_type_codes="*", trigger_states="SGN")])
    ).rules
    assert rule.note_type_codes == frozenset({"*"})
    assert rule.trigger_states == frozenset({"SGN"})


def test_disabled_rule_is_skipped_silently():
    config = load_config(_secrets([_rule(enabled=False), _rule(name="second")]))
    assert [rule.name for rule in config.rules] == ["second"]
    assert config.errors == ()


def test_unnamed_rule_gets_a_positional_name():
    rule = _rule()
    del rule["name"]
    (parsed,) = load_config(_secrets([rule])).rules
    assert parsed.name == "rule 1"


@pytest.mark.parametrize(
    ("rule", "error"),
    [
        ("not a dict", "rule 1: a rule must be an object"),
        (
            _rule(note_type_codes=[]),
            "rule 'Visit notes to PCP': note_type_codes is required (use [\"*\"] for every note type)",
        ),
        (
            _rule(note_type_codes=5),
            "rule 'Visit notes to PCP': note_type_codes is required (use [\"*\"] for every note type)",
        ),
        (
            _rule(trigger_states=["DLT"]),
            "rule 'Visit notes to PCP': trigger_states must be from ['LKD', 'RLK', 'SGN']",
        ),
        (
            _rule(trigger_states=[]),
            "rule 'Visit notes to PCP': trigger_states must be from ['LKD', 'RLK', 'SGN']",
        ),
        (
            _rule(recipients=[]),
            "rule 'Visit notes to PCP': recipients must be a non-empty list",
        ),
        (
            _rule(recipients="facility"),
            "rule 'Visit notes to PCP': recipients must be a non-empty list",
        ),
        (
            _rule(recipients=["facility"]),
            "rule 'Visit notes to PCP' recipient 1: a recipient must be an object",
        ),
        (
            _rule(recipients=[{"type": "pharmacy"}]),
            "rule 'Visit notes to PCP' recipient 1: unknown recipient type 'pharmacy'",
        ),
        (
            _rule(recipients=[{"type": "care_team_role", "role_codes": []}]),
            "rule 'Visit notes to PCP' recipient 1: care_team_role needs at least one role code",
        ),
        (
            _rule(recipients=[{"type": "fixed", "name": "X", "fax": "123"}]),
            "rule 'Visit notes to PCP' recipient 1: fixed needs a name and a valid US fax number",
        ),
        (
            _rule(recipients=[{"type": "fixed", "fax": "5552340100"}]),
            "rule 'Visit notes to PCP' recipient 1: fixed needs a name and a valid US fax number",
        ),
        (
            _rule(cover_sheet="hello"),
            "rule 'Visit notes to PCP': cover_sheet must be an object",
        ),
        (
            _rule(cover_sheet={"subject": "only a subject"}),
            "rule 'Visit notes to PCP': cover_sheet needs a subject and a comment",
        ),
    ],
)
def test_bad_rule_is_dropped_with_a_reason(rule, error):
    config = load_config(_secrets([rule]))
    assert config.rules == ()
    assert config.errors == (error,)


def test_one_bad_recipient_drops_the_whole_rule():
    rule = _rule(recipients=[{"type": "facility"}, {"type": "nope"}])
    config = load_config(_secrets([rule]))
    assert config.rules == ()


def test_bad_rule_does_not_affect_good_rule():
    config = load_config(
        _secrets([_rule(name="bad", recipients=[]), _rule(name="good")])
    )
    assert [rule.name for rule in config.rules] == ["good"]
    assert len(config.errors) == 1


def test_invalid_json_is_logged_and_ignored():
    config = load_config({"AUTO_FAX_MODE": "live", "AUTO_FAX_RULES": "[{"})
    assert config.rules == ()
    assert config.mode == MODE_LIVE
    assert config.errors[0].startswith("AUTO_FAX_RULES is not valid JSON:")


def test_rules_must_be_a_list():
    config = load_config(
        {"AUTO_FAX_MODE": "live", "AUTO_FAX_RULES": json.dumps(_rule())}
    )
    assert config.rules == ()
    assert config.errors == ("AUTO_FAX_RULES must be a JSON list of rules",)


def test_cover_sheet_is_trimmed_to_length():
    (rule,) = load_config(
        _secrets([_rule(cover_sheet={"subject": "s" * 300, "comment": "c" * 900})])
    ).rules
    assert rule.cover_sheet is not None
    assert len(rule.cover_sheet.subject) == 100
    assert len(rule.cover_sheet.comment) == 500


def test_test_fax_number_is_normalized():
    config = load_config(_secrets([_rule()], test_number="+1 (555) 234-0199"))
    assert config.test_fax_digits == "5552340199"
    assert config.mode == MODE_LIVE


def test_unreadable_test_fax_number_turns_the_plugin_off():
    config = load_config(_secrets([_rule()], test_number="call me"))
    assert config.mode == MODE_OFF
    assert config.test_fax_digits is None
    assert config.errors == (
        "AUTO_FAX_TEST_FAX_NUMBER is not a valid US fax number; treating as off",
    )


class TestRuleMatches:
    def _rule(self, codes, locations=()):
        return Rule(
            name="r",
            note_type_codes=frozenset(codes),
            trigger_states=frozenset({"LKD"}),
            recipients=(),
            location_ids=frozenset(locations),
        )

    def test_matches_listed_note_type(self):
        assert self._rule(["office_visit"]).matches("office_visit", None)

    def test_rejects_other_note_type(self):
        assert not self._rule(["office_visit"]).matches("telehealth", None)

    def test_rejects_note_without_a_type(self):
        assert not self._rule(["office_visit"]).matches(None, None)

    def test_star_matches_any_note_type(self):
        assert self._rule(["*"]).matches("anything", None)
        assert self._rule(["*"]).matches(None, None)

    def test_location_filter(self):
        rule = self._rule(["*"], ["loc-1"])
        assert rule.matches("x", "loc-1")
        assert not rule.matches("x", "loc-2")
        assert not rule.matches("x", None)
