"""Tests for the protocol cards the provider actually reads.

The requirement these guard is "overdue must look different from merely due, so
the team can triage at a glance". There is no OVERDUE status in the SDK, so the
distinction lives in the title, in the sign of ``due_in``, and in the order the
cards come back.
"""

import json
from datetime import date
from typing import Any

from canvas_sdk.effects.protocol_card import ProtocolCard

from preventive_screenings.services.cards import (
    build_card,
    order_filter,
    build_narrative,
    build_not_applicable_card,
    build_retired_card,
    build_title,
    card_key,
    describe_rule,
)
from preventive_screenings.services.screenings import (
    STATE_DUE,
    STATE_ORDERED,
    STATE_OVERDUE,
    STATE_SATISFIED,
    ScreeningStatus,
)

PATIENT = "patient-uuid"


def screening(**over: Any) -> dict:
    out: dict[str, Any] = {
        "id": "s1",
        "enabled": True,
        "name": "Mammogram",
        "sex": "female",
        "min_age": 40,
        "max_age": 74,
        "grace_days": 90,
        "completions": [
            {"value_set_key": "mammography", "source": "imaging_report", "codes": [],
             "label": "", "interval_quantity": 2, "interval_unit": "years"}
        ],
        "exclusions": [],
        "order_command": "imaging_order",
        "order_button": "Order mammogram",
        "order_code": "24606-6",
        "order_comment": "Screening mammogram",
        "guidance": "",
    }
    out.update(over)
    return out


def status(state: str, **over: Any) -> ScreeningStatus:
    values: dict[str, Any] = {
        "state": state,
        "due_date": date(2025, 3, 15),
        "last_completed": date(2023, 3, 12),
        "due_in": -553,
    }
    values.update(over)
    return ScreeningStatus(**values)


# --- the overdue treatment ---------------------------------------------------


def test_an_overdue_card_says_so_in_its_title_and_by_how_much() -> None:
    """The title is the one field certain to render, so the state lives there."""
    assert build_title(screening(), status(STATE_OVERDUE)) == "Mammogram — OVERDUE by 1 year"


def test_a_due_card_is_marked_due_without_the_alarm() -> None:
    assert build_title(screening(), status(STATE_DUE, due_in=-10)) == "Mammogram — due"


def test_a_satisfied_card_is_just_the_screening_name() -> None:
    assert build_title(screening(), status(STATE_SATISFIED, due_in=200)) == "Mammogram"


def test_due_in_is_negative_once_past_due() -> None:
    """Negative due_in is the native protocols' own convention for overdue, and
    is what Canvas sorts on."""
    card = build_card(PATIENT, screening(), status(STATE_OVERDUE))

    assert card.due_in == -553
    assert card.status == ProtocolCard.Status.DUE


def test_a_satisfied_screening_is_stated_as_satisfied_not_omitted() -> None:
    """Cards persist under their key, so a screening that has been done must be
    actively restated - otherwise a stale OVERDUE card stays on the chart."""
    card = build_card(PATIENT, screening(), status(STATE_SATISFIED, due_in=200))

    assert card.status == ProtocolCard.Status.SATISFIED
    assert card.recommendations == []


def test_a_screening_that_does_not_apply_is_stated_as_not_applicable() -> None:
    card = build_not_applicable_card(PATIENT, screening())

    assert card.status == ProtocolCard.Status.NOT_APPLICABLE
    assert card.key == card_key(screening())
    assert card.narrative == "Does not apply to this patient."


def test_the_card_key_is_stable_per_screening() -> None:
    """The key is the card's identity in the chart. If it moved between chart
    opens, every reload would stack another copy."""
    assert card_key(screening()) == "preventive_screening:s1"
    assert card_key(screening(name="Renamed")) == "preventive_screening:s1"


# --- the narrative -----------------------------------------------------------


def test_the_narrative_leads_with_the_last_completed_date() -> None:
    """"We also need to see the last completed date, not only when it's due."""
    narrative = build_narrative(screening(), status(STATE_OVERDUE))

    assert narrative.startswith("Last completed 12 Mar 2023.")
    assert "Was due 15 Mar 2025 — overdue by 1 year." in narrative


def test_the_narrative_says_plainly_when_nothing_is_on_record() -> None:
    narrative = build_narrative(screening(), status(STATE_DUE, last_completed=None, due_in=-3))

    assert narrative.startswith("No qualifying result on record.")
    assert "Due since 15 Mar 2025." in narrative


def test_a_satisfied_narrative_gives_the_next_due_date() -> None:
    narrative = build_narrative(screening(), status(STATE_SATISFIED, due_in=200))

    assert "Next due 15 Mar 2025." in narrative


def test_the_rule_reads_as_a_sentence() -> None:
    """The same words appear in the editor, which is how a non-developer checks
    the plugin is doing what they meant."""
    assert describe_rule(screening()) == (
        "Practice rule: women aged 40 to 74 — due 2 years after mammogram."
    )


def test_a_rule_with_no_upper_age_says_and_over() -> None:
    rule = screening(name="Falls", sex="any", min_age=65, max_age=0,
                     completions=[{"value_set_key": "falls_screening", "source": "questionnaire",
                                   "codes": [], "label": "", "interval_quantity": 1,
                                   "interval_unit": "years"}])

    assert describe_rule(rule) == (
        "Practice rule: patients aged 65 and over — due 1 year after falls risk screening."
    )


def test_a_multi_signal_rule_lists_every_way_it_can_be_done() -> None:
    rule = screening(
        sex="any", min_age=45, max_age=75,
        completions=[
            {"value_set_key": "colonoscopy", "source": "procedure", "codes": [], "label": "",
             "interval_quantity": 10, "interval_unit": "years"},
            {"value_set_key": "flexible_sigmoidoscopy", "source": "procedure", "codes": [],
             "label": "", "interval_quantity": 5, "interval_unit": "years"},
            {"value_set_key": "fobt", "source": "lab_result", "codes": [], "label": "",
             "interval_quantity": 1, "interval_unit": "years"},
        ],
    )

    assert describe_rule(rule) == (
        "Practice rule: patients aged 45 to 75 — due 10 years after colonoscopy, "
        "5 years after flexible sigmoidoscopy, or 1 year after fobt / fit stool test."
    )


def test_a_custom_signal_is_named_by_its_own_label() -> None:
    """A screening that is not a quality measure still reads as a sentence."""
    rule = screening(
        name="Bone density",
        completions=[{"value_set_key": "", "source": "procedure", "codes": ["77080"],
                      "label": "DXA bone density scan", "interval_quantity": 2,
                      "interval_unit": "years"}],
    )

    assert "2 years after dxa bone density scan" in describe_rule(rule)


# --- the order ---------------------------------------------------------------


def test_a_due_card_offers_the_configured_order_prefilled() -> None:
    """One click stages the command; the provider signs it. Nothing is ordered
    by the plugin."""
    card = build_card(PATIENT, screening(), status(STATE_OVERDUE))

    assert len(card.recommendations) == 1
    recommendation = card.recommendations[0]
    assert recommendation.button == "Order mammogram"
    assert recommendation.title == "Screening mammogram"
    context = recommendation.values["commands"][0]
    assert context["command"]["type"] == "imagingOrder"
    assert context["context"]["image_code"] == "24606-6"
    assert context["context"]["effect_type"] == "ORIGINATE_IMAGING_ORDER_COMMAND"
    # And the search filter, which is what actually pre-fills the command.
    by_system = {c["system"]: c["code"] for c in context["command"]["filter"]["coding"]}
    assert "24606-6" in by_system["loinc"]


def test_a_list_valued_code_field_is_wrapped() -> None:
    """A lab order takes a list of codes where an imaging order takes one."""
    rule = screening(order_command="lab_order", order_code="10524-7")

    card = build_card(PATIENT, rule, status(STATE_DUE, due_in=-1))

    context = card.recommendations[0].values["commands"][0]
    assert context["context"]["tests_order_codes"] == ["10524-7"]


def test_a_command_that_takes_no_code_is_still_offered() -> None:
    """A referral has no code field, so the provider picks in the staged command
    rather than being handed a wrong one."""
    rule = screening(order_command="refer", order_code="ignored", order_button="Refer")

    card = build_card(PATIENT, rule, status(STATE_DUE, due_in=-1))

    context = card.recommendations[0].values["commands"][0]
    assert context["command"]["type"] == "refer"
    assert "ignored" not in str(context["context"]), "no code invented for the field"
    # The filter still carries it: a referral takes no code field, but Canvas
    # can still be told what to search for.
    assert "ignored" in str(context["command"]["filter"])


def test_no_order_command_means_no_button() -> None:
    """A recommendation with no way to act on it is better than a wrong one."""
    card = build_card(PATIENT, screening(order_command=""), status(STATE_OVERDUE))

    assert card.recommendations == []


def test_the_button_falls_back_to_something_sensible() -> None:
    rule = screening(order_button="", order_comment="")

    card = build_card(PATIENT, rule, status(STATE_OVERDUE))

    assert card.recommendations[0].button == "Order"
    assert card.recommendations[0].title == "Mammogram"


def test_cards_can_be_snoozed() -> None:
    """Ties into the native Snooze Protocol command for the patient who is
    deferring this one screening."""
    assert build_card(PATIENT, screening(), status(STATE_OVERDUE)).can_be_snoozed is True


# --- the snoozed title -------------------------------------------------------


def test_a_snoozed_overdue_card_stops_shouting() -> None:
    """Found at UAT 2026-09-20: Canvas collapses a snoozed card to a stub that
    shows only the title, and our title is where overdue lives - so a screening
    a provider had just deferred went on reading "OVERDUE by 15 years" at them.
    """
    rule = screening(name="Mammogram")
    status = ScreeningStatus(STATE_OVERDUE, date(2011, 1, 1), None, -5_400)

    assert build_title(rule, status) == "Mammogram — OVERDUE by 14 years"
    assert build_title(rule, status, snoozed=True) == "Mammogram — Snoozed"


def test_a_snoozed_due_card_stops_shouting() -> None:
    rule = screening(name="Mammogram")
    status = ScreeningStatus(STATE_DUE, date(2026, 1, 1), None, -10)

    assert build_title(rule, status) == "Mammogram — due"
    assert build_title(rule, status, snoozed=True) == "Mammogram — Snoozed"


def test_snoozing_keeps_the_screening_name() -> None:
    """The stub shows the title and nothing else, so dropping the name would
    leave a card that does not say which screening it is."""
    title = build_title(
        screening(name="Colorectal cancer screening"),
        ScreeningStatus(STATE_OVERDUE, date(2020, 1, 1), None, -900),
        snoozed=True,
    )

    assert title.startswith("Colorectal cancer screening")
    assert "OVERDUE" not in title


def test_a_satisfied_card_has_nothing_to_quieten() -> None:
    """Only the due/overdue half of the title is replaced. A satisfied card is
    already just the name, so snoozing it changes nothing."""
    rule = screening(name="Mammogram")
    status = ScreeningStatus(STATE_SATISFIED, date(2027, 1, 1), date(2025, 1, 1), 300)

    assert build_title(rule, status, snoozed=True) == "Mammogram"


def test_a_snoozed_card_keeps_its_narrative_and_due_in() -> None:
    """Only the title is quietened. Canvas shows neither of these on a stub, and
    both have to be right the moment the snooze expires and the card returns."""
    rule = screening(name="Mammogram")
    status = ScreeningStatus(STATE_OVERDUE, date(2020, 1, 1), None, -900)

    loud = json.loads(build_card(PATIENT, rule, status).apply().payload)["data"]
    quiet = json.loads(
        build_card(PATIENT, rule, status, snoozed=True).apply().payload
    )["data"]

    assert quiet["narrative"] == loud["narrative"]
    assert quiet["due_in"] == loud["due_in"] == -900
    assert quiet["title"] != loud["title"]


# --- the staged order ---------------------------------------------------------


def test_the_order_code_is_sent_under_both_names() -> None:
    """The Commands API calls this field `image`; the SDK's recommendation
    payload keys it `image_code`. Canvas ignores the key it does not know - that
    is exactly how a blank staged order went unnoticed - so both are sent and it
    does not matter which one it reads."""
    rule = screening(name="Mammogram", order_command="imaging_order", order_code="24606-6")
    card = build_card(PATIENT, rule, ScreeningStatus(STATE_OVERDUE, date(2020, 1, 1), None, -900))
    context = json.loads(card.apply().payload)["data"]["recommendations"][0]["commands"][0]

    assert context["command"]["type"] == "imagingOrder"
    assert context["context"]["image"] == "24606-6", "the name the API uses"
    assert context["context"]["image_code"] == "24606-6", "the name the SDK emits"
    assert context["context"]["effect_type"] == "ORIGINATE_IMAGING_ORDER_COMMAND"


def test_a_list_code_field_is_sent_as_a_list_under_both_names() -> None:
    """tests_order_codes takes a list, not a scalar. Sending a bare string under
    the API name would stage an order Canvas cannot read."""
    rule = screening(name="FIT", order_command="lab_order", order_code="10524-7")
    card = build_card(PATIENT, rule, ScreeningStatus(STATE_DUE, date(2026, 1, 1), None, -5))
    context = json.loads(card.apply().payload)["data"]["recommendations"][0]["commands"][0]

    assert context["context"]["tests"] == ["10524-7"]
    assert context["context"]["tests_order_codes"] == ["10524-7"]


def test_a_command_without_a_code_stages_empty_rather_than_wrong() -> None:
    """A referral takes no code. Better the provider picks than be handed one
    the rule invented."""
    rule = screening(name="Referral", order_command="refer", order_code="whatever")
    card = build_card(PATIENT, rule, ScreeningStatus(STATE_OVERDUE, date(2020, 1, 1), None, -900))
    context = json.loads(card.apply().payload)["data"]["recommendations"][0]["commands"][0]

    assert context["command"]["type"] == "refer"
    assert set(context["context"]) == {"effect_type"}, "no code invented for it"


# --- the search filter --------------------------------------------------------


def test_the_filter_carries_the_value_set_grouped_by_system() -> None:
    """**This is the shape that pre-fills a command.** Traced out of
    canvas_workflow_kit, whose Recommendation.command_filter builds
    {"type": ..., "filter": {"coding": [{"system": "LOINC", "code": [...]}]}} -
    a *search* filter, not field values. Setting field values, which is what
    this plugin did for four deploys, stages an empty command.

    The system is the value set's **name**, not its URL, because that is what
    the legacy kit sends - it reads `value_set.values` directly.
    """
    found = order_filter(screening())

    assert found is not None
    coding = found["coding"]
    systems = {c["system"] for c in coding}
    assert systems == {"loinc", "cpt", "hcpcs"}, (
        "the legacy kit's spellings, which is what every working native protocol "
        "sends - not the modern SDK's 'LOINC' / 'HCPCSLEVELII'"
    )
    assert "" not in systems, (
        "a bare system claims a terminology we cannot name. The order code is "
        "LOINC and the value set already carries it, so it belongs in that "
        "group - appending it again bare was a real regression when the "
        "mammography set grew from one system to three."
    )
    by_system = {c["system"]: c["code"] for c in coding}
    assert "24606-6" in by_system["loinc"], "the configured order code, under its own system"
    assert len(by_system["loinc"]) > 50, "and the whole value set behind it"
    assert "77067" in by_system["cpt"], "including the codes a Perform-recorded mammogram carries"


def test_the_configured_code_is_in_the_filter_even_without_a_value_set() -> None:
    """A screening carrying its own codes still gets a filter - that is the
    non-quality-measure case the client asked for."""
    rule = screening(
        order_code="77080",
        completions=[{"value_set_key": "", "source": "procedure", "codes": ["77080"],
                      "label": "DXA", "interval_quantity": 2, "interval_unit": "years"}],
    )

    found = order_filter(rule)

    assert found == {"coding": [{"system": "", "code": ["77080"]}]}


def test_a_screening_with_nothing_to_search_for_gets_no_filter() -> None:
    """Better no filter than an empty one: an empty search could match the whole
    catalog rather than nothing."""
    rule = screening(order_code="", completions=[])

    assert order_filter(rule) is None


def test_a_recommendation_with_nothing_to_search_for_carries_no_filter() -> None:
    """Nothing to tell Canvas to look up means no filter key at all, rather than
    an empty one - an empty search could match the whole catalog.

    `normalize_screening` drops a signal naming neither a value set nor codes,
    and `active_screenings` drops a screening with no completions, so this state
    cannot arrive from the editor. The check is kept because a card built from a
    document that reached the store another way must not raise."""
    rule = screening(
        order_command="refer",
        order_code="",
        completions=[{"value_set_key": "", "source": "imaging_report", "codes": [],
                      "label": "", "interval_quantity": 2, "interval_unit": "years"}],
    )

    card = build_card(PATIENT, rule, status(STATE_DUE, due_in=-1))
    context = card.recommendations[0].values["commands"][0]

    assert context["command"] == {"type": "refer"}, "no filter key at all"


def test_a_custom_code_screening_gets_a_filter_from_its_own_codes() -> None:
    """The non-quality-measure case: a practice's own codes are what it would
    search for, exactly as a value set's are."""
    rule = screening(
        order_code="",
        completions=[{"value_set_key": "", "source": "procedure", "codes": ["77080", "77081"],
                      "label": "DXA", "interval_quantity": 2, "interval_unit": "years"}],
    )

    assert order_filter(rule) == {"coding": [{"system": "", "code": ["77080", "77081"]}]}


# --- what a card says about a statement a person made ------------------------


def test_an_attested_completion_is_labelled_as_one_on_the_card() -> None:
    """A provider reading "last completed" has to be able to tell a result in
    the chart from a colleague's statement that one exists somewhere else."""
    narrative = build_narrative(
        screening(), status(STATE_SATISFIED, attested=True, due_in=200)
    )

    assert narrative.startswith("Marked complete 12 Mar 2023 by staff.")


def test_a_chart_result_is_not_labelled_as_a_statement() -> None:
    narrative = build_narrative(screening(), status(STATE_SATISFIED, due_in=200))

    assert narrative.startswith("Last completed 12 Mar 2023.")


def test_a_screening_marked_not_applicable_says_who_decided() -> None:
    """The rule not applying is a fact about the configuration; somebody
    deciding it does not apply is a fact about this patient, and only the
    second is something another clinician might want to revisit."""
    card = build_not_applicable_card(PATIENT, screening(), attested=True)

    assert card.status == ProtocolCard.Status.NOT_APPLICABLE
    assert card.narrative == "Marked not applicable to this patient by staff."


# --- retracting a card -------------------------------------------------------


def test_a_retracted_card_is_keyed_to_the_screening_it_replaces() -> None:
    """A retraction only works by overwriting the card under its own key -
    there is no effect that deletes one."""
    card = build_retired_card(PATIENT, "s1")

    assert card.key == card_key(screening())
    assert card.status == ProtocolCard.Status.NOT_APPLICABLE


def test_a_retraction_does_not_claim_the_screening_was_dropped() -> None:
    """**Two different things reach this card** and the wording has to be true
    of both: a screening the practice deleted, and one it still tracks with the
    card switched off. Saying "no longer tracked" would be false for the second,
    which is now the common case."""
    narrative = build_retired_card(PATIENT, "s1").narrative

    assert "no longer shows this screening as a protocol card" in narrative
    assert "record" in narrative.lower()


# --- ordered, awaiting result ------------------------------------------------


def test_an_ordered_screening_says_so_in_the_title() -> None:
    """The title is where urgency lives, so it is where "already handled" has
    to live too."""
    found = status(STATE_ORDERED, due_in=-400, ordered_on=date(2026, 10, 1))

    assert build_title(screening(), found) == "Mammogram — ordered, awaiting result"


def test_an_ordered_card_states_both_dates() -> None:
    """"Ordered 1 Oct" means something different for a screening that came due
    last week than for one two years overdue, so the card keeps both."""
    narrative = build_narrative(
        screening(), status(STATE_ORDERED, due_in=-400, ordered_on=date(2026, 10, 1))
    )

    assert "Ordered 1 Oct 2026, awaiting result." in narrative
    assert "Was due 15 Mar 2025." in narrative


def test_an_ordered_card_is_pending_rather_than_due() -> None:
    """The one use the SDK's PENDING status has: the work is in flight, so it
    is neither due nor satisfied."""
    card = build_card(
        PATIENT, screening(), status(STATE_ORDERED, due_in=-400, ordered_on=date(2026, 10, 1))
    )

    assert card.status == ProtocolCard.Status.PENDING


def test_an_ordered_card_does_not_offer_to_order_it_again() -> None:
    """Offering the button again is how two mammograms get booked."""
    card = build_card(
        PATIENT, screening(), status(STATE_ORDERED, due_in=-400, ordered_on=date(2026, 10, 1))
    )

    assert card.recommendations == []
