"""Tests for rule normalization, filtering, and loading/saving the config store."""

import json
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from questionnaire_followup.services.config_store import (
    COMPARATORS,
    DEFAULT_COMPARATOR,
    DEFAULTS_CURRENT_AS_OF,
    MAX_RULES,
    active_rules,
    describe_rule,
    inactive_reason,
    load_config,
    new_rule,
    normalize_document,
    normalize_rule,
    save_config,
)

MODULE = "questionnaire_followup.services.config_store"
FIND_ROW = [call.objects.filter(key="active"), call.objects.filter().first()]
SEEDED_PAIRS = [
    ("Depression (PHQ-2 → PHQ-9)", "55758-7", "44249-1", 3, False),
    ("Anxiety (GAD-2 → GAD-7)", "69736-7", "69737-5", 3, False),
]


def _pairs(doc: dict) -> list[tuple]:
    """The parts of each rule that are stable across seeds (ids are random)."""
    return [
        (r["name"], r["trigger_code"], r["followup_code"], r["threshold"], r["enabled"])
        for r in doc["rules"]
    ]


def test_normalize_rule_fills_missing_fields() -> None:
    """A rule saved by an older page still arrives complete."""
    rule = normalize_rule({"name": "Depression"})

    assert rule["name"] == "Depression"
    assert rule["enabled"] is False
    assert rule["comparator"] == "at_least"
    assert rule["threshold"] == 3
    assert rule["threshold_max"] == 3
    assert rule["trigger_lookback_days"] == 30
    assert rule["suppression_days"] == 90
    assert rule["id"]


def test_a_rule_saved_before_comparators_existed_still_means_at_least() -> None:
    """The stored documents already on instances carry no comparator at all.

    Reading a missing one as anything but "at least" would change what every
    rule a practice has already configured actually does.
    """
    rule = normalize_rule({"name": "Depression", "threshold": 3})

    assert rule["comparator"] == DEFAULT_COMPARATOR == "at_least"


def test_normalize_rule_reads_a_one_number_rule_as_a_single_point_range() -> None:
    """Converting an old rule to a range must not silently span everything above it."""
    rule = normalize_rule({"threshold": 7})

    assert (rule["threshold"], rule["threshold_max"]) == (7, 7)


def test_normalize_rule_keeps_a_comparator_it_does_not_recognize() -> None:
    """A document written by a NEWER version is left alone, not reinterpreted.

    Mapping it onto a comparator this version does understand could invert the
    rule ("at most" read as "at least"); active_rules leaves it inert instead.
    """
    rule = normalize_rule({"comparator": "sometime_soon"})

    assert rule["comparator"] == "sometime_soon"


def test_normalize_rule_coerces_form_strings_to_ints() -> None:
    """Numbers arrive from the form as strings and must not stay strings."""
    rule = normalize_rule(
        {"threshold": "5", "trigger_lookback_days": "14", "suppression_days": "0"}
    )

    assert rule["threshold"] == 5
    assert rule["trigger_lookback_days"] == 14
    assert rule["suppression_days"] == 0


def test_normalize_rule_coerces_both_ends_of_a_range() -> None:
    """The second number arrives from the form as a string too."""
    rule = normalize_rule({"comparator": "between", "threshold": "10", "threshold_max": "14"})

    assert (rule["threshold"], rule["threshold_max"]) == (10, 14)


def test_normalize_rule_leaves_a_backwards_range_backwards() -> None:
    """A range typed the wrong way round is not quietly swapped.

    The editor flags it and the handler refuses to fire it; correcting it here
    would point the pairing at a severity band nobody chose.
    """
    rule = normalize_rule({"comparator": "between", "threshold": 14, "threshold_max": 10})

    assert (rule["threshold"], rule["threshold_max"]) == (14, 10)


def test_normalize_rule_rejects_unusable_numbers() -> None:
    """Garbage in a number field falls back to the default rather than crashing."""
    rule = normalize_rule({"threshold": "", "trigger_lookback_days": 0, "suppression_days": -5})

    assert rule["threshold"] == 3
    assert rule["trigger_lookback_days"] == 1  # a zero-day lookback would never match
    assert rule["suppression_days"] == 0  # negative clamps to "no suppression"


def test_normalize_document_drops_non_rule_entries() -> None:
    """A malformed rules list does not take the whole document down with it."""
    doc = normalize_document({"rules": [{"name": "ok"}, "not a rule", None]})

    assert len(doc["rules"]) == 1
    assert doc["rules"][0]["name"] == "ok"


def test_normalize_document_caps_the_number_of_rules() -> None:
    """A document past the cap keeps its first MAX_RULES rules, in order."""
    doc = normalize_document({"rules": [{"name": f"Rule {i}"} for i in range(MAX_RULES + 5)]})

    assert MAX_RULES == 50
    assert [r["name"] for r in doc["rules"]] == [f"Rule {i}" for i in range(MAX_RULES)]


def test_active_rules_skips_disabled_and_unaddressed() -> None:
    """Only rules that are on and name both questionnaires can fire."""
    doc = {
        "rules": [
            new_rule(enabled=True, trigger_code="a", followup_code="b"),
            new_rule(enabled=False, trigger_code="a", followup_code="b"),
            new_rule(enabled=True, trigger_code="a", followup_code=""),
            new_rule(enabled=True, trigger_code="", followup_code="b"),
        ]
    }

    assert len(active_rules(doc)) == 1


def test_active_rules_skips_a_score_rule_this_version_cannot_read() -> None:
    """A config from a newer version leaves the unreadable rules inert, not inverted."""
    doc = {
        "rules": [
            new_rule(enabled=True, trigger_code="a", followup_code="b", name="known"),
            new_rule(enabled=True, trigger_code="a", followup_code="b", comparator="sometime_soon"),
        ]
    }

    assert [rule["name"] for rule in active_rules(doc)] == ["known"]


def test_every_comparator_the_editor_offers_can_actually_fire() -> None:
    """The dropdown and the filter are built from one list and cannot drift apart."""
    doc = {
        "rules": [
            new_rule(enabled=True, trigger_code="a", followup_code="b", comparator=comparator)
            for comparator in COMPARATORS
        ]
    }

    assert len(active_rules(doc)) == len(COMPARATORS) == 4


# --------------------------------------------------------------------------- #
#  load_config
# --------------------------------------------------------------------------- #


def test_load_config_returns_the_stored_document_normalized() -> None:
    """A stored document comes back with defaults filled and numbers coerced."""
    row = MagicMock()
    row.payload = json.dumps(
        {
            "defaults_reviewed": True,
            "rules": [
                {
                    "id": "r1",
                    "enabled": True,
                    "name": "Depression",
                    "trigger_code": "55758-7",
                    "followup_code": "44249-1",
                    "threshold": "4",
                }
            ],
        }
    )

    with patch(f"{MODULE}.FollowUpConfig") as mock_config, patch(f"{MODULE}.log") as mock_log:
        mock_config.objects.filter.return_value.first.return_value = row

        result = load_config()

        # read only, nothing written back
        assert mock_config.mock_calls == [*FIND_ROW, call.objects.filter().first().__bool__()]
        assert mock_log.mock_calls == []
        assert row.mock_calls == [call.__bool__()]
        assert result == {
            "version": 1,
            "defaults_current_as_of": DEFAULTS_CURRENT_AS_OF,
            "defaults_reviewed": True,
            "rules": [
                {
                    "id": "r1",
                    "enabled": True,
                    "name": "Depression",
                    "trigger_code": "55758-7",
                    "followup_code": "44249-1",
                    "comparator": "at_least",
                    "threshold": 4,
                    "threshold_max": 4,
                    "trigger_lookback_days": 30,
                    "suppression_days": 90,
                }
            ],
        }


def test_load_config_seeds_and_persists_disabled_defaults_on_first_use() -> None:
    """With no stored row, the standard pairs are saved switched off.

    No seeded name resolves here, so the published panel codes stay in place - the
    behaviour on an instance that carries none of these questionnaires.
    """
    with (
        patch(f"{MODULE}.FollowUpConfig") as mock_config,
        patch(f"{MODULE}.resolve_names") as mock_resolve_names,
        patch(f"{MODULE}.log") as mock_log,
    ):
        mock_config.objects.filter.return_value.first.return_value = None
        mock_resolve_names.return_value = {}

        result = load_config()

        assert mock_resolve_names.mock_calls == [call({"PHQ-2", "PHQ-9", "GAD-2", "GAD-7"})]
        assert mock_config.mock_calls == [
            *FIND_ROW,
            *FIND_ROW,
            call.objects.create(key="active", payload=json.dumps(result)),
        ]
        assert mock_log.mock_calls == []
        assert result["defaults_reviewed"] is False
        assert result["defaults_current_as_of"] == DEFAULTS_CURRENT_AS_OF
        assert _pairs(result) == SEEDED_PAIRS


def test_seeding_points_the_defaults_at_this_instance_s_codes() -> None:
    """The published panel codes are a guess; what the instance loaded is the answer.

    On the first real instance checked, PHQ-2 was 58120-7 and GAD-2 was a SNOMED
    code, so both shipped pairings were inert as delivered. Seeding by name fixes
    exactly that, and the rules still arrive switched off for review.
    """
    instance_codes = {
        "PHQ-2": "58120-7",
        "PHQ-9": "44249-1",
        "GAD-2": "836551000000102",
        "GAD-7": "69737-5",
    }
    with (
        patch(f"{MODULE}.FollowUpConfig") as mock_config,
        patch(f"{MODULE}.resolve_names") as mock_resolve_names,
        patch(f"{MODULE}.log") as mock_log,
    ):
        mock_config.objects.filter.return_value.first.return_value = None
        mock_resolve_names.return_value = instance_codes

        result = load_config()

        assert _pairs(result) == [
            ("Depression (PHQ-2 → PHQ-9)", "58120-7", "44249-1", 3, False),
            ("Anxiety (GAD-2 → GAD-7)", "836551000000102", "69737-5", 3, False),
        ]
        # Only the two that differ are reported; PHQ-9 and GAD-7 already matched.
        assert mock_log.mock_calls == [
            call.info(
                "questionnaire_followup seeded the default pairings with this instance's "
                "codes: PHQ-2 55758-7 -> 58120-7; GAD-2 69736-7 -> 836551000000102"
            )
        ]


def test_a_name_that_does_not_resolve_keeps_its_published_code() -> None:
    """Per side, not all-or-nothing: one unknown instrument must not strand the other."""
    with (
        patch(f"{MODULE}.FollowUpConfig") as mock_config,
        patch(f"{MODULE}.resolve_names") as mock_resolve_names,
        patch(f"{MODULE}.log"),
    ):
        mock_config.objects.filter.return_value.first.return_value = None
        mock_resolve_names.return_value = {"PHQ-2": "58120-7"}

        result = load_config()

        assert _pairs(result) == [
            ("Depression (PHQ-2 → PHQ-9)", "58120-7", "44249-1", 3, False),
            ("Anxiety (GAD-2 → GAD-7)", "69736-7", "69737-5", 3, False),
        ]


def test_a_broken_config_store_does_not_go_looking_up_questionnaires() -> None:
    """The degraded path runs on EVERY portal load, so it must not add a query.

    Seeding happens once; a plugin whose custom_data is unavailable returns
    defaults on every single request, and must not pay for a lookup each time.
    """
    with (
        patch(f"{MODULE}.FollowUpConfig") as mock_config,
        patch(f"{MODULE}.resolve_names") as mock_resolve_names,
        patch(f"{MODULE}.log") as mock_log,
    ):
        mock_config.objects.filter.side_effect = RuntimeError("no such table")

        result = load_config()

        assert mock_resolve_names.mock_calls == []
        assert _pairs(result) == SEEDED_PAIRS
        assert mock_log.mock_calls == [
            call.warning("questionnaire_followup config load failed, using defaults: no such table")
        ]


def test_load_config_does_not_overwrite_a_corrupt_document() -> None:
    """An unreadable stored document falls back to defaults but is left in place."""
    row = MagicMock()
    row.payload = "{not json"

    with patch(f"{MODULE}.FollowUpConfig") as mock_config, patch(f"{MODULE}.log") as mock_log:
        mock_config.objects.filter.return_value.first.return_value = row

        result = load_config()

        assert mock_config.mock_calls == [*FIND_ROW, call.objects.filter().first().__bool__()]
        assert mock_log.mock_calls == [
            call.warning(
                "questionnaire_followup config load failed, using defaults: "
                "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"
            )
        ]
        assert row.mock_calls == [call.__bool__()]  # never saved over
        assert _pairs(result) == SEEDED_PAIRS


def test_load_config_falls_back_to_defaults_when_custom_data_is_unavailable() -> None:
    """A missing namespace or table degrades to the disabled defaults, not an error."""
    with patch(f"{MODULE}.FollowUpConfig") as mock_config, patch(f"{MODULE}.log") as mock_log:
        mock_config.objects.filter.side_effect = Exception("relation does not exist")

        result = load_config()

        assert mock_config.mock_calls == [call.objects.filter(key="active")]
        assert mock_log.mock_calls == [
            call.warning(
                "questionnaire_followup config load failed, using defaults: relation does not exist"
            )
        ]
        assert _pairs(result) == SEEDED_PAIRS


# --------------------------------------------------------------------------- #
#  save_config
# --------------------------------------------------------------------------- #


def test_save_config_updates_the_existing_row_with_the_normalized_document() -> None:
    """Saving over an existing row stores the normalized document, not the raw form."""
    row = MagicMock()

    with patch(f"{MODULE}.FollowUpConfig") as mock_config, patch(f"{MODULE}.log") as mock_log:
        mock_config.objects.filter.return_value.first.return_value = row

        result = save_config({"rules": [{"id": "r1", "name": "Depression", "threshold": "5"}]})

        assert mock_config.mock_calls == [
            *FIND_ROW,
            call.objects.filter().first().__bool__(),
            call.objects.filter().first().save(),
        ]
        assert mock_log.mock_calls == []
        assert row.mock_calls == [call.__bool__(), call.save()]
        assert json.loads(row.payload) == {
            "version": 1,
            "defaults_current_as_of": DEFAULTS_CURRENT_AS_OF,
            "defaults_reviewed": False,
            "rules": [
                {
                    "id": "r1",
                    "enabled": False,
                    "name": "Depression",
                    "trigger_code": "",
                    "followup_code": "",
                    "comparator": "at_least",
                    "threshold": 5,
                    "threshold_max": 5,
                    "trigger_lookback_days": 30,
                    "suppression_days": 90,
                }
            ],
        }
        assert result is True


def test_save_config_creates_the_row_when_none_exists() -> None:
    """The first save creates the single config row."""
    with patch(f"{MODULE}.FollowUpConfig") as mock_config, patch(f"{MODULE}.log") as mock_log:
        mock_config.objects.filter.return_value.first.return_value = None

        result = save_config({"rules": []})

        expected_payload = json.dumps(
            {
                "version": 1,
                "defaults_current_as_of": DEFAULTS_CURRENT_AS_OF,
                "defaults_reviewed": False,
                "rules": [],
            }
        )
        assert mock_config.mock_calls == [
            *FIND_ROW,
            call.objects.create(key="active", payload=expected_payload),
        ]
        assert mock_log.mock_calls == []
        assert result is True


def test_save_config_reports_failure_when_custom_data_is_unavailable() -> None:
    """A missing namespace or table is reported as a failed save, not raised."""
    with patch(f"{MODULE}.FollowUpConfig") as mock_config, patch(f"{MODULE}.log") as mock_log:
        mock_config.objects.filter.side_effect = Exception("relation does not exist")

        result = save_config({"rules": []})

        assert mock_config.mock_calls == [call.objects.filter(key="active")]
        assert mock_log.mock_calls == [
            call.warning(
                "questionnaire_followup config save failed (custom_data unavailable?): "
                "relation does not exist"
            )
        ]
        assert result is False


# --------------------------------------------------------------------------- #
#  The shared vocabulary: describe_rule / inactive_reason
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param(
            {"comparator": "at_least", "threshold": 3}, "scores at least 3", id="at-least"
        ),
        pytest.param({"comparator": "at_most", "threshold": 2}, "scores at most 2", id="at-most"),
        pytest.param(
            {"comparator": "between", "threshold": 10, "threshold_max": 14},
            "scores between 10 and 14",
            id="between-names-both-ends",
        ),
        pytest.param(
            {"comparator": "completed"}, "is completed", id="completed-mentions-no-number"
        ),
        pytest.param(
            {"comparator": "from_the_future"},
            "unrecognized score rule 'from_the_future'",
            id="a-comparator-this-version-cannot-read",
        ),
    ],
)
def test_describe_rule_reads_as_a_sentence(overrides: dict[str, Any], expected: str) -> None:
    """One phrasing of each comparator, shared by the editor, the trace and the diagnostic."""
    assert describe_rule(new_rule(**overrides)) == expected


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({"enabled": False}, "switched off", id="off"),
        pytest.param(
            {"enabled": True, "trigger_code": ""},
            "no trigger questionnaire chosen",
            id="no-trigger",
        ),
        pytest.param(
            {"enabled": True, "trigger_code": "a", "followup_code": ""},
            "no follow-up questionnaire chosen",
            id="no-followup",
        ),
        pytest.param(
            {"enabled": True, "trigger_code": "a", "followup_code": "b", "comparator": "nope"},
            "unrecognized score rule 'nope'",
            id="unreadable-comparator",
        ),
    ],
)
def test_inactive_reason_explains_a_rule_that_can_never_fire(
    overrides: dict[str, Any], expected: str
) -> None:
    """Each disqualifier gets a sentence, because these are what the diagnostic reports."""
    assert inactive_reason(new_rule(**overrides)) == expected


def test_a_live_rule_has_no_inactive_reason() -> None:
    """None is the signal that a rule reaches the handler at all."""
    live = new_rule(enabled=True, trigger_code="a", followup_code="b")

    assert inactive_reason(live) is None
    assert active_rules({"rules": [live]}) == [live]
