"""Tests for loading, saving, seeding and normalizing the screening config.

Mocked rather than database-backed: ScreeningConfig is a CustomModel, and custom
data tables do not exist in the test database. Verify the real table on an
instance with `canvas namespace inspect canvas_medical__preventive_screenings`.
"""

import json
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from preventive_screenings.services.catalog import VALUE_SETS
from preventive_screenings.services.config_store import (
    DEFAULTS_CURRENT_AS_OF,
    _SEED_SCREENINGS,
    MAX_CODE_CHARS,
    MAX_CODES_PER_SIGNAL,
    MAX_GUIDANCE_CHARS,
    MAX_SCREENINGS,
    MAX_SIGNALS_PER_SCREENING,
    MAX_TEXT_CHARS,
    active_screenings,
    carded_screenings,
    load_config,
    new_screening,
    normalize_document,
    normalize_screening,
    save_config,
)
from preventive_screenings.services.sweep_store import config_stamp

MODEL = "preventive_screenings.services.config_store.ScreeningConfig"


@pytest.fixture
def seeded() -> dict[str, Any]:
    """The shipped default document, as a fresh install would produce it."""
    with patch(MODEL) as model:
        model.objects.filter.return_value.first.return_value = None
        return load_config()


def a_signal(**over: Any) -> dict:
    out: dict[str, Any] = {
        "value_set_key": "mammography",
        "source": "imaging_report",
        "codes": [],
        "label": "",
        "interval_quantity": 2,
        "interval_unit": "years",
    }
    out.update(over)
    return out


# --- the shipped defaults ----------------------------------------------------


def test_the_seeded_screenings_all_ship_switched_off() -> None:
    """Defaults encode national guidance a practice may not follow, and may point
    at codes this instance does not use. Visibly off beats silently wrong."""
    with patch(MODEL) as model:
        model.objects.filter.return_value.first.return_value = None
        doc = load_config()

    assert doc["screenings"], "expected shipped defaults"
    assert all(not s["enabled"] for s in doc["screenings"])
    assert doc["defaults_reviewed"] is False
    assert doc["defaults_current_as_of"] == DEFAULTS_CURRENT_AS_OF


def test_the_seeded_screenings_cover_what_the_practice_asked_for() -> None:
    with patch(MODEL) as model:
        model.objects.filter.return_value.first.return_value = None
        names = [s["name"] for s in load_config()["screenings"]]

    assert names == [
        "Mammogram",
        "Colorectal cancer screening",
        "Cervical cancer screening",
        "Falls risk screening",
        "Tobacco use screening",
        "Bone density (DXA)",
    ]


def test_every_seeded_screening_survives_normalization() -> None:
    """A seed whose signals get dropped as unusable would ship broken."""
    with patch(MODEL) as model:
        model.objects.filter.return_value.first.return_value = None
        doc = load_config()

    for screening in doc["screenings"]:
        assert screening["completions"], f"{screening['name']} lost its completion signals"


def test_colorectal_screening_ships_with_modality_specific_intervals(
    seeded: dict[str, Any],
) -> None:
    """A colonoscopy covers ten years where a stool test covers one; collapsing
    them to one interval would chase patients who are covered.

    The five modalities are the ones the instance's own CMS130v6 accepts,
    checked against its source on 2026-09-20. A missing modality is not a
    cosmetic gap: a patient screened by it reads as never screened.
    """
    colorectal = next(s for s in seeded["screenings"] if s["name"].startswith("Colorectal"))

    intervals = {(c["value_set_key"], c["interval_quantity"]) for c in colorectal["completions"]}
    assert intervals == {
        ("colonoscopy", 10),
        ("flexible_sigmoidoscopy", 5),
        ("ct_colonography", 5),
        ("sdna_fit_test", 3),
        ("fobt", 1),
    }


def test_colorectal_screening_excludes_patients_already_diagnosed(
    seeded: dict[str, Any],
) -> None:
    """Someone with colorectal cancer is under surveillance, not screening. A
    "due" card on their chart is the wrong-patient recommendation the brief
    calls the highest-stakes failure, and CMS130v6 excludes them too."""
    colorectal = next(s for s in seeded["screenings"] if s["name"].startswith("Colorectal"))

    keys = {e["value_set_key"] for e in colorectal["exclusions"]}
    assert keys == {"total_colectomy", "colorectal_cancer"}


def test_bone_density_ships_as_the_worked_custom_code_example(seeded: dict[str, Any]) -> None:
    """The SDK ships no screening DXA value set, and a practice needs to see one
    screening built from plain codes before writing their own."""
    bone = next(s for s in seeded["screenings"] if s["name"].startswith("Bone density"))

    assert bone["completions"][0]["value_set_key"] == ""
    assert bone["completions"][0]["codes"] == ["77080", "77081"]
    assert bone["completions"][0]["label"] == "DXA bone density scan"


def test_the_seed_is_persisted_so_the_editor_opens_populated() -> None:
    with patch(MODEL) as model:
        model.objects.filter.return_value.first.return_value = None
        load_config()

    assert model.mock_calls == [
        call.objects.filter(key="active"),
        call.objects.filter().first(),
        call.objects.filter(key="active"),
        call.objects.filter().first(),
        call.objects.create(key="active", payload=model.objects.create.call_args.kwargs["payload"]),
    ]


# --- loading -----------------------------------------------------------------


def test_a_stored_document_is_returned_normalized() -> None:
    stored = {"version": 1, "screenings": [{"name": "Custom", "min_age": "50"}]}
    row = MagicMock(payload=json.dumps(stored))

    with patch(MODEL) as model:
        model.objects.filter.return_value.first.return_value = row
        doc = load_config()

    assert doc["screenings"][0]["name"] == "Custom"
    assert doc["screenings"][0]["min_age"] == 50  # coerced from the string


def test_an_unreadable_config_degrades_to_the_disabled_defaults() -> None:
    """This runs on every chart open. A config failure must not break the chart."""
    with patch(MODEL) as model:
        model.objects.filter.side_effect = RuntimeError("no such table")
        doc = load_config()

    assert [s["name"] for s in doc["screenings"]][0] == "Mammogram"
    assert all(not s["enabled"] for s in doc["screenings"])


def test_a_corrupt_payload_degrades_to_the_defaults() -> None:
    row = MagicMock(payload="{not json")

    with patch(MODEL) as model:
        model.objects.filter.return_value.first.return_value = row
        doc = load_config()

    assert doc["screenings"][0]["name"] == "Mammogram"


def test_an_empty_payload_reseeds() -> None:
    row = MagicMock(payload="")

    with patch(MODEL) as model:
        model.objects.filter.return_value.first.return_value = row
        doc = load_config()

    assert len(doc["screenings"]) == 6


# --- saving ------------------------------------------------------------------


def test_saving_updates_an_existing_row() -> None:
    row = MagicMock(payload="{}")

    with patch(MODEL) as model:
        model.objects.filter.return_value.first.return_value = row
        assert save_config({"screenings": []}) is True

    assert json.loads(row.payload) == {
        "version": 1,
        "defaults_current_as_of": DEFAULTS_CURRENT_AS_OF,
        "defaults_reviewed": False,
        "screenings": [],
    }
    # `__bool__` is the `if row:` check that chose update over create.
    assert row.mock_calls == [call.__bool__(), call.save()]


def test_saving_creates_a_row_when_none_exists() -> None:
    with patch(MODEL) as model:
        model.objects.filter.return_value.first.return_value = None
        assert save_config({"screenings": []}) is True

    assert model.objects.create.call_args.kwargs["key"] == "active"


def test_saving_reports_failure_rather_than_raising() -> None:
    """The caller turns this into a message the admin can act on."""
    with patch(MODEL) as model:
        model.objects.filter.side_effect = RuntimeError("namespace missing")
        assert save_config({"screenings": []}) is False


# --- normalization -----------------------------------------------------------


def test_missing_fields_are_filled_in() -> None:
    """A document written by an older editor must never hand the handler a
    missing key."""
    screening = normalize_screening({})

    assert set(screening) == set(new_screening())
    assert screening["name"] == "Untitled screening"
    assert screening["sex"] == "any"


@pytest.mark.parametrize("value", ["nonsense", "", None, "Female"])
def test_an_unknown_sex_falls_back_to_any(value: Any) -> None:
    """Falling back to a sex-specific value on bad input could show a screening
    to the wrong patients; "any" is decided by the age rule alone."""
    assert normalize_screening({"sex": value})["sex"] == "any"


@pytest.mark.parametrize("value", ["nonsense", None, ""])
def test_an_unknown_interval_unit_falls_back_to_years(value: Any) -> None:
    screening = normalize_screening({"completions": [a_signal(interval_unit=value)]})

    assert screening["completions"][0]["interval_unit"] == "years"


def test_negative_ages_and_grace_periods_are_clamped() -> None:
    screening = normalize_screening({"min_age": -5, "max_age": -1, "grace_days": -30})

    assert (screening["min_age"], screening["max_age"], screening["grace_days"]) == (0, 0, 0)


def test_an_interval_of_zero_is_raised_to_one() -> None:
    """A zero interval would make the screening due again the instant it is done."""
    screening = normalize_screening({"completions": [a_signal(interval_quantity=0)]})

    assert screening["completions"][0]["interval_quantity"] == 1


def test_a_catalog_signal_takes_its_source_from_the_catalog() -> None:
    """The stored source can never disagree with the value set it names."""
    screening = normalize_screening(
        {"completions": [a_signal(value_set_key="colonoscopy", source="imaging_report")]}
    )

    assert screening["completions"][0]["source"] == "procedure"


def test_a_signal_with_neither_value_set_nor_codes_is_dropped() -> None:
    """It matches nothing, so leaving it in would be a rule that silently never
    fires. Dropping it makes the gap visible in the editor."""
    screening = normalize_screening({"completions": [a_signal(value_set_key="", codes=[])]})

    assert screening["completions"] == []


def test_an_unknown_value_set_key_with_codes_falls_back_to_the_codes() -> None:
    screening = normalize_screening(
        {"completions": [a_signal(value_set_key="retired", codes=["77080"], source="procedure")]}
    )

    assert screening["completions"][0] == {
        "value_set_key": "",
        "source": "procedure",
        "codes": ["77080"],
        "label": "",
        "interval_quantity": 2,
        "interval_unit": "years",
    }


def test_blank_codes_are_dropped_and_the_rest_trimmed() -> None:
    screening = normalize_screening(
        {"completions": [a_signal(value_set_key="", codes=[" 77080 ", "", None, "77081"])]}
    )

    assert screening["completions"][0]["codes"] == ["77080", "77081"]


def test_an_unknown_order_command_is_cleared() -> None:
    """Better no button than one pointing at a command that does not exist."""
    assert normalize_screening({"order_command": "telepathy"})["order_command"] == ""


def test_exclusions_carry_no_interval() -> None:
    """An exclusion is a yes/no, not something that expires."""
    screening = normalize_screening({"exclusions": [a_signal(value_set_key="total_colectomy")]})

    assert set(screening["exclusions"][0]) == {"value_set_key", "source", "codes", "label"}


# --- the caps ----------------------------------------------------------------


def test_screenings_past_the_cap_are_dropped() -> None:
    """Every chart open reads the whole set, so a runaway config would slow every
    chart in the practice."""
    doc = normalize_document({"screenings": [{"name": f"S{i}"} for i in range(MAX_SCREENINGS + 5)]})

    assert len(doc["screenings"]) == MAX_SCREENINGS


def test_signals_past_the_cap_are_dropped() -> None:
    screening = normalize_screening(
        {"completions": [a_signal() for _ in range(MAX_SIGNALS_PER_SCREENING + 3)]}
    )

    assert len(screening["completions"]) == MAX_SIGNALS_PER_SCREENING


def test_codes_past_the_cap_are_dropped() -> None:
    screening = normalize_screening(
        {"completions": [a_signal(value_set_key="", codes=[str(i) for i in range(MAX_CODES_PER_SIGNAL + 9)])]}
    )

    assert len(screening["completions"][0]["codes"]) == MAX_CODES_PER_SIGNAL


# --- stable identity ---------------------------------------------------------


def test_every_seeded_screening_has_an_explicit_stable_id() -> None:
    """The id is the card's key. `new_screening` would otherwise mint a uuid4,
    and `load_config` returns the seeded document *without saving it*, so a
    fresh install would invent new ids - and so new card keys - on every read."""
    ids = [seed.get("id") for seed in _SEED_SCREENINGS]

    assert all(ids), "a seed is missing an explicit id"
    assert len(set(ids)) == len(ids), "two seeds share an id, so they share a card"


def test_the_seeded_document_is_identical_every_time_it_is_loaded() -> None:
    """**The guard on the whole class of bug.** An unstable seeded document has
    two separate consequences, and both are silent:

    * the card key moves, so every write orphans the cards written before it,
      and nothing deletes a protocol card;
    * `config_stamp` differs every tick, so the sweep believes the rules changed
      and requeues the entire panel every five minutes, forever.
    """
    with patch(MODEL) as model:
        model.objects.filter.return_value.first.return_value = None
        first, second = load_config(), load_config()

    assert first == second
    assert config_stamp(first) == config_stamp(second)


def test_a_stored_document_reloads_to_the_same_ids() -> None:
    """The ordinary case: whatever was saved comes back unchanged."""
    doc = normalize_document({"screenings": [{"id": "abc", "name": "Mammogram"}]})

    assert config_stamp(normalize_document(doc)) == config_stamp(normalize_document(doc))


def test_a_document_that_arrived_without_ids_still_normalizes_the_same_way() -> None:
    """A hand-edited or migrated document has no ids to keep. Inventing a random
    one on a read path would give the same screening a new card key on every
    chart change and every sweep tick, so the fallback is positional."""
    raw = {"screenings": [{"name": "First"}, {"name": "Second"}]}

    once, twice = normalize_document(raw), normalize_document(raw)

    assert [s["id"] for s in once["screenings"]] == [s["id"] for s in twice["screenings"]]
    assert once["screenings"][0]["id"] != once["screenings"][1]["id"]


def test_a_brand_new_screening_still_gets_a_unique_id() -> None:
    """Positional fallback must not make two separately-created screenings
    collide - `new_screening` is called with no position and stays random."""
    assert new_screening()["id"] != new_screening()["id"]


def test_free_text_is_capped_not_only_counted() -> None:
    """Counting the screenings does not bound what a run costs.

    Every field below reaches a protocol card, and handlers.sweep sizes each
    run against WORST_CARD_BYTES. Uncapped, a single long name is enough to
    overrun the effect budget - and that failure is silent, because the run's
    cards are discarded after the patients in it were marked reviewed.
    """
    screening = normalize_screening(
        {
            "name": "N" * 5_000,
            "order_button": "B" * 5_000,
            "order_code": "O" * 5_000,
            "order_comment": "M" * 5_000,
            "guidance": "G" * 50_000,
            "completions": [a_signal(value_set_key="", label="L" * 5_000, codes=["C" * 5_000])],
        }
    )

    assert len(screening["name"]) == MAX_TEXT_CHARS
    assert len(screening["order_button"]) == MAX_TEXT_CHARS
    assert len(screening["order_comment"]) == MAX_TEXT_CHARS
    assert len(screening["order_code"]) == MAX_CODE_CHARS
    assert len(screening["guidance"]) == MAX_GUIDANCE_CHARS
    assert len(screening["completions"][0]["label"]) == MAX_TEXT_CHARS
    assert len(screening["completions"][0]["codes"][0]) == MAX_CODE_CHARS


def test_the_caps_hold_for_a_document_that_arrived_any_other_way() -> None:
    """The save endpoint is not the only way in - a document written by an
    older version, or restored from a backup, is normalized on load."""
    doc = normalize_document({"screenings": [{"name": "N" * 9_000}]})

    assert len(doc["screenings"][0]["name"]) == MAX_TEXT_CHARS


def test_a_name_that_is_only_whitespace_still_gets_a_title() -> None:
    """Trimming to nothing must not leave a card with a blank headline."""
    assert normalize_screening({"name": "   "})["name"] == "Untitled screening"


@pytest.mark.parametrize("value", [None, "not a list", 42, {}])
def test_a_document_without_a_screening_list_normalizes_to_empty(value: Any) -> None:
    assert normalize_document({"screenings": value})["screenings"] == []


def test_non_dict_screenings_are_ignored() -> None:
    doc = normalize_document({"screenings": ["nope", None, {"name": "Real"}]})

    assert [s["name"] for s in doc["screenings"]] == ["Real"]


# --- active_screenings -------------------------------------------------------


def test_only_enabled_screenings_are_active() -> None:
    doc = {"screenings": [
        {"enabled": True, "completions": [a_signal()], "name": "On"},
        {"enabled": False, "completions": [a_signal()], "name": "Off"},
    ]}

    assert [s["name"] for s in active_screenings(doc)] == ["On"]


def test_a_screening_with_no_completion_signal_is_not_active() -> None:
    """It could never read as done, so it would sit on the chart forever."""
    doc = {"screenings": [{"enabled": True, "completions": [], "name": "Unmeasurable"}]}

    assert active_screenings(doc) == []


def test_an_empty_document_has_no_active_screenings() -> None:
    assert active_screenings({}) == []


@pytest.mark.parametrize("value", [None, "77080", 42, {"a": 1}])
def test_codes_that_are_not_a_list_are_ignored(value: Any) -> None:
    """A malformed codes field must not become a code, or the signal would match
    something nobody configured."""
    screening = normalize_screening({"completions": [a_signal(value_set_key="", codes=value)]})

    assert screening["completions"] == []


def test_an_unusable_signal_does_not_stop_the_ones_after_it() -> None:
    """Dropping one bad signal must not silently drop the rest of the screening."""
    screening = normalize_screening(
        {
            "completions": [
                a_signal(value_set_key="", codes=[]),  # unusable, dropped
                a_signal(value_set_key="mammography"),
                a_signal(value_set_key="", codes=[]),  # unusable, dropped
                a_signal(value_set_key="colonoscopy"),
            ]
        }
    )

    assert [c["value_set_key"] for c in screening["completions"]] == [
        "mammography",
        "colonoscopy",
    ]


def test_non_dict_signals_are_skipped_without_stopping_the_list() -> None:
    """A document hand-edited into the wrong shape loses the junk, not the rest."""
    screening = normalize_screening(
        {"completions": ["nope", None, 42, a_signal(value_set_key="mammography")]}
    )

    assert [c["value_set_key"] for c in screening["completions"]] == ["mammography"]


def test_an_imaging_order_code_is_cpt_because_that_is_what_the_catalog_indexes(
    seeded: dict[str, Any],
) -> None:
    """**Five deploys were spent on this, and the cause was the code system.**

    A protocol card's order button stages the command and Canvas resolves the
    code against the practice's catalog for that command. The imaging catalog is
    keyed on **CPT**. The mammogram seed carried LOINC `24606-6` and staged an
    empty order every time; the bone-density seed carried CPT `77080` and
    pre-filled correctly - same command, same plugin, opposite result, confirmed
    on a real chart 2026-09-22.

    CLAUDE.md recorded this as a platform gap that no plugin could work around,
    on the strength of a control test where Canvas's own protocol also staged an
    empty command. That control is consistent with this: the native protocol
    passes a LOINC value set too.

    A LOINC code is `NNNNN-N`; a CPT code is five characters and carries no
    hyphen. That is the cheapest reliable way to tell them apart.
    """
    for screening in seeded["screenings"]:
        if screening["order_command"] != "imaging_order":
            continue
        code = screening["order_code"]
        assert code, f"{screening['id']} offers an imaging order with no code to pre-fill"
        assert "-" not in code, (
            f"{screening['id']} orders imaging with {code!r}, which is a LOINC code. "
            "The imaging catalog is keyed on CPT, so this stages an empty order."
        )


def test_what_a_screening_orders_is_something_that_counts_as_having_done_it(
    seeded: dict[str, Any],
) -> None:
    """Otherwise the button orders one thing and the card waits for another, and
    the screening never clears however faithfully the provider acts on it."""
    for screening in seeded["screenings"]:
        code = screening["order_code"]
        if not code:
            continue
        accepted: set[str] = set()
        for signal in screening["completions"]:
            entry = VALUE_SETS.get(signal["value_set_key"])
            if entry:
                accepted |= {c for codes in entry.value_set.values.values() for c in codes}
            accepted |= set(signal["codes"])

        assert code in accepted, (
            f"{screening['id']} orders {code!r}, which none of its completion "
            "signals would recognise as having been done"
        )


# --- carded_screenings -------------------------------------------------------
#
# A protocol card is opt-in per screening and off by default. Everything that
# writes cards works from this list, so these tests are what stand between the
# default configuration and a plugin that cards everything it tracks.


def test_a_tracked_screening_is_not_carded_by_default() -> None:
    """The change Jess asked for, in one assertion. `enabled` says the practice
    tracks it; it does not say it goes on the chart summary."""
    doc = {"screenings": [new_screening(enabled=True, completions=[{"x": 1}])]}

    assert len(active_screenings(doc)) == 1
    assert carded_screenings(doc) == []


def test_a_screening_asked_for_a_card_gets_one() -> None:
    doc = {
        "screenings": [
            new_screening(name="Carded", enabled=True, protocol_card=True,
                          completions=[{"x": 1}]),
            new_screening(name="Not", enabled=True, completions=[{"x": 1}]),
        ]
    }

    assert [s["name"] for s in carded_screenings(doc)] == ["Carded"]


def test_a_screening_that_is_switched_off_is_never_carded() -> None:
    """Otherwise a saved document could say "do not track this, and put it on
    every chart", and the editor would be describing something the plugin does
    not do."""
    doc = {
        "screenings": [
            new_screening(enabled=False, protocol_card=True, completions=[{"x": 1}])
        ]
    }

    assert carded_screenings(doc) == []


def test_a_screening_with_nothing_counting_as_done_is_never_carded() -> None:
    """It could never read as satisfied, so its card would shout forever."""
    doc = {"screenings": [new_screening(enabled=True, protocol_card=True, completions=[])]}

    assert carded_screenings(doc) == []


def test_every_seeded_screening_ships_without_a_card() -> None:
    """The blank-slate requirement. A practice installing this gets the record
    app and no cards until they ask for them, screening by screening."""
    doc = normalize_document({"screenings": _SEED_SCREENINGS})

    assert [s["protocol_card"] for s in doc["screenings"]] == [False] * len(_SEED_SCREENINGS)


def test_a_document_saved_before_the_toggle_existed_arrives_with_cards_off() -> None:
    """Which is a real migration, not a hypothetical: every config already
    saved on an instance predates the field.

    This is deliberate and it is not silent - `handlers.sweep` retracts those
    cards rather than abandoning them, because nothing deletes a protocol card.
    """
    old = {"screenings": [{"id": "s1", "enabled": True, "completions": []}]}

    assert normalize_document(old)["screenings"][0]["protocol_card"] is False


def test_the_card_toggle_survives_a_round_trip() -> None:
    doc = normalize_document(
        {"screenings": [{"id": "s1", "enabled": True, "protocol_card": True}]}
    )

    assert doc["screenings"][0]["protocol_card"] is True


def test_turning_a_card_off_changes_the_config_stamp() -> None:
    """The stamp is how the sweep notices a rules change, and it is the only
    thing that triggers the retraction. A toggle the stamp could not see would
    leave the card on every chart it reached, permanently."""
    on = normalize_document({"screenings": [{"id": "s1", "protocol_card": True}]})
    off = normalize_document({"screenings": [{"id": "s1", "protocol_card": False}]})

    assert config_stamp(on) != config_stamp(off)
