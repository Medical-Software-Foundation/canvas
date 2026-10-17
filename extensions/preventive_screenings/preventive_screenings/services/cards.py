"""Turn a resolved screening into the protocol card a provider actually reads.

The SDK's ProtocolCard has no OVERDUE status - the enum is DUE, SATISFIED,
NOT_APPLICABLE, PENDING, NOT_RELEVANT - so urgency is carried by the three
fields that are ours to write:

* **the title**, which states the overdue state in words and by how much;
* **``due_in``**, negative once past due, which is the native protocols' own
  convention and is what Canvas sorts on;
* **the order**, overdue cards first, so the top of the chart is the triage list.

A card is emitted for every enabled screening, including ones that do not apply
and ones already satisfied. That is deliberate: protocol cards persist under
their key, so a screening that goes quiet must be actively restated as satisfied
or not-applicable. Emitting only the due ones would leave a stale "OVERDUE"
card on the chart of a patient who had the test last week.
"""

from datetime import date
from typing import Any

from canvas_sdk.effects.protocol_card import ProtocolCard

from preventive_screenings.services.catalog import ORDER_COMMANDS, VALUE_SETS
from preventive_screenings.services.screenings import (
    STATE_DUE,
    STATE_ORDERED,
    STATE_OVERDUE,
    ScreeningStatus,
    describe_interval,
    describe_overdue,
)

# Cards are keyed per screening per patient, and the key is the card's identity
# in the chart: it must stay stable across chart opens or every reload stacks a
# duplicate. The screening's id is stable for the life of the rule.
KEY_PREFIX = "preventive_screening"


def card_key(screening: dict) -> str:
    """The stable identity of this screening's card."""
    return f"{KEY_PREFIX}:{screening['id']}"


def _human_date(value: date) -> str:
    """A date as a clinician writes it: 12 Mar 2023."""
    return f"{value.day} {value:%b %Y}"


def _signal_label(signal: dict) -> str:
    """What to call a completion signal in a sentence."""
    entry = VALUE_SETS.get(signal["value_set_key"])
    if entry:
        return entry.label.lower()
    return signal["label"].lower() or "a recorded result"


def describe_rule(screening: dict) -> str:
    """The screening rule as one sentence, the way the admin page states it.

    The same words appear on the card and in the editor on purpose: it is how a
    non-developer checks that the plugin is doing what they meant.
    """
    who = {"female": "women", "male": "men"}.get(screening["sex"], "patients")
    min_age = screening["min_age"]
    max_age = screening["max_age"]
    ages = f"aged {min_age} to {max_age}" if max_age else f"aged {min_age} and over"

    parts = [
        f"{describe_interval(s['interval_quantity'], s['interval_unit'])} after "
        f"{_signal_label(s)}"
        for s in screening["completions"]
    ]
    if len(parts) == 1:
        covers = parts[0]
    else:
        covers = f"{', '.join(parts[:-1])}, or {parts[-1]}"
    return f"Practice rule: {who} {ages} — due {covers}."


def build_narrative(screening: dict, status: ScreeningStatus) -> str:
    """The card's body: what was last done, when it was due, and the rule."""
    if status.last_completed and status.attested:
        # Said so rather than shown. A provider reading "last completed" has to
        # be able to tell a result in the chart from a colleague's statement
        # that one exists somewhere else, because the two carry different
        # weight when they are deciding whether to re-screen.
        history = f"Marked complete {_human_date(status.last_completed)} by staff."
    elif status.last_completed:
        history = f"Last completed {_human_date(status.last_completed)}."
    else:
        history = "No qualifying result on record."

    if status.state == STATE_ORDERED and status.ordered_on is not None:
        # Still says when it was due, because that is what makes the order
        # legible - "ordered 1 Oct" means something different for a screening
        # that came due last week than for one two years overdue.
        timing = (
            f"Ordered {_human_date(status.ordered_on)}, awaiting result. "
            f"Was due {_human_date(status.due_date)}."
        )
    elif status.state == STATE_OVERDUE:
        timing = (
            f"Was due {_human_date(status.due_date)} — "
            f"overdue by {describe_overdue(-status.due_in)}."
        )
    elif status.state == STATE_DUE:
        timing = f"Due since {_human_date(status.due_date)}."
    else:
        timing = f"Next due {_human_date(status.due_date)}."

    return f"{history} {timing} {describe_rule(screening)}"


def build_title(screening: dict, status: ScreeningStatus, *, snoozed: bool = False) -> str:
    """The card's headline, which is where overdue has to be unmistakable.

    Unless the provider has snoozed it. Canvas collapses a snoozed card to a
    stub that shows only this title, so a deferred screening kept shouting
    ``OVERDUE by 15 years`` at the person who had just deferred it. Snoozing
    replaces the due/overdue half of the title and leaves the name, so the card
    still says which screening it is.
    """
    name: str = screening["name"]
    if snoozed and status.state in (STATE_DUE, STATE_OVERDUE):
        return f"{name} — Snoozed"
    if status.state == STATE_ORDERED:
        return f"{name} — ordered, awaiting result"
    if status.state == STATE_OVERDUE:
        return f"{name} — OVERDUE by {describe_overdue(-status.due_in)}"
    if status.state == STATE_DUE:
        return f"{name} — due"
    return name


def _order_value(entry: Any, screening: dict) -> Any:
    """The code for the command's own field, in the shape that field takes."""
    if not entry.code_field:
        return None
    code = screening["order_code"]
    if not code:
        return None
    return [code] if entry.code_is_list else code


# The value-set system names Canvas's own protocols send, which are not the
# names the modern SDK uses. Every native protocol goes through
# `canvas_workflow_kit`, whose value sets key `values` by these, and whose
# `command_filter` passes the key through untouched. The SDK's v2022/v2026 sets
# use the right-hand spellings instead, so a filter built from them names a
# system no working protocol has ever sent.
_LEGACY_SYSTEM_NAMES = {
    "LOINC": "loinc",
    "CPT": "cpt",
    "SNOMEDCT": "snomedct",
    "ICD10CM": "icd10cm",
    "ICD10PCS": "icd10pcs",
    "HCPCSLEVELII": "hcpcs",
    "CVX": "cvx",
    "RXNORM": "rxnorm",
}


def order_filter(screening: dict) -> dict | None:
    """The search filter that tells Canvas which catalog item to pre-select.

    **This is how a protocol card actually pre-fills a command**, and it is not
    what setting field values does. Traced out of `canvas_workflow_kit`, the
    legacy framework the instance's own native protocols are written in, whose
    `Recommendation.command_filter` builds exactly this:

        {"type": "imagingOrder",
         "filter": {"coding": [{"system": "LOINC", "code": ["24606-6", ...]}]}}

    Its docstring calls it "a search filter by value set system codes ... like a
    search for a particular vaccine or lab or medicine" - so the UI is being
    told what to *look up*, not what to set. That explains why passing
    `image_code`, then `image`, then a structured `Coding` all staged an empty
    command: none of them is a filter. `_BaseCommand.coding_filter` is the
    modern SDK's vestige of this - typed `Coding`, documented as "the coding
    filter used for command insertion in protocol cards" - but nothing
    overrides it and `recommendation_context` never emits it.

    The system is the value set's **name**, not its URL, because that is what the
    legacy kit sends - it reads `value_set.values` directly. And it is that
    kit's spelling, not the modern SDK's: native protocols send ``loinc`` and
    ``hcpcs`` where the SDK's own value sets say ``LOINC`` and ``HCPCSLEVELII``.
    A filter naming a system no working protocol has ever sent matches
    nothing.

    Built from the screening's first completion signal - what counts as having
    done it is what you would order - plus the configured order code, so an
    admin's explicit choice is always in the filter.
    """
    completions = screening["completions"]
    signal = completions[0] if completions else None

    by_system: dict[str, list[str]] = {}
    if signal:
        entry = VALUE_SETS.get(signal["value_set_key"])
        if entry is not None:
            for name, codes in entry.value_set.values.items():
                system = _LEGACY_SYSTEM_NAMES.get(name, name.lower())
                by_system.setdefault(system, []).extend(sorted(codes))
        else:
            # A screening carrying its own codes - the non-quality-measure case
            # the client asked for. There is no terminology to name them in, so
            # they go under a bare system, which is all we honestly know.
            by_system.setdefault("", []).extend(signal["codes"])

    code = screening["order_code"]
    if code and not any(code in codes for codes in by_system.values()):
        # Only when the value set does not already carry it. Checking every
        # system rather than the chosen one matters now that a value set can
        # span several: a LOINC order code against a set carrying LOINC, CPT
        # and HCPCS was being appended a second time under a bare system,
        # which claims a terminology we do not know rather than the one we do.
        #
        # Otherwise: under the value set's system when there is exactly one,
        # since the admin's code is in the same terminology as what it orders.
        # With several, or none, there is no system we can honestly claim.
        system = next(iter(by_system)) if len(by_system) == 1 else ""
        by_system.setdefault(system, []).append(code)

    # A system whose code list came out empty is not a filter, it is a search
    # for everything - drop it rather than send it.
    coding = [
        {"system": system, "code": codes} for system, codes in by_system.items() if codes
    ]
    return {"coding": coding} if coding else None


def _order_command(screening: dict) -> dict | None:
    """The command this screening offers to stage, pre-filled with its code.

    Returns the recommendation's context dictionary rather than the command
    object, because the code has to be sent under two names.

    ``recommendation_context`` builds its payload from the command's ``values``,
    which keys by the **Python** field name - ``image_code``. The Commands API
    calls that field ``image``. So a staged imaging order arrived carrying a key
    Canvas does not recognise, and opened with every field blank: the button
    worked, the pre-fill did not. The same mismatch affects the lab order
    (``tests_order_codes`` / ``tests``) and perform (``cpt_code`` / ``perform``).

    Both spellings are sent. Canvas already ignores the one it does not know -
    that is precisely how this went unnoticed - so carrying both costs nothing
    and does not depend on being right about which it reads.

    Only the code is set either way. The provider completes and signs the staged
    command, so nothing is ordered by the plugin - the requirement that nothing
    happens automatically, met by construction rather than by convention.
    """
    entry = ORDER_COMMANDS.get(screening["order_command"])
    if entry is None:
        return None

    value: Any = _order_value(entry, screening)
    if value is not None:
        command = entry.command(**{entry.code_field: value})
    else:
        command = entry.command()

    context: dict = command.recommendation_context()
    if value is not None and entry.code_api_field:
        context["context"][entry.code_api_field] = value

    # The filter goes beside `type` inside the command object, which is where
    # the legacy kit puts it: its command dict is {"type": ..., "filter": ...}.
    found = order_filter(screening)
    if found is not None:
        context["command"]["filter"] = found
    return context


def build_card(
    patient_id: str,
    screening: dict,
    status: ScreeningStatus,
    *,
    snoozed: bool = False,
) -> ProtocolCard:
    """Build the protocol card for one screening, in one of its three states.

    ``snoozed`` only quiets the title. The narrative, ``due_in`` and the order
    recommendation are left alone deliberately: Canvas shows none of them on a
    snoozed stub, so changing them would buy nothing, and they have to be
    correct the moment the snooze expires and the full card comes back.
    """
    if status.state in (STATE_DUE, STATE_OVERDUE):
        card_status = ProtocolCard.Status.DUE
    elif status.state == STATE_ORDERED:
        # The one use the SDK's PENDING status actually has: the work is in
        # flight, so it is neither due nor satisfied. Whether Canvas renders a
        # PENDING card is unverified - SATISFIED and NOT_APPLICABLE are both
        # quiet - and either answer is acceptable here, because a screening
        # that has been ordered does not need a prompt.
        card_status = ProtocolCard.Status.PENDING
    else:
        card_status = ProtocolCard.Status.SATISFIED

    card = ProtocolCard(
        patient_id=patient_id,
        key=card_key(screening),
        title=build_title(screening, status, snoozed=snoozed),
        narrative=build_narrative(screening, status),
        status=card_status,
        due_in=status.due_in,
        # Lets a provider use the native Snooze Protocol command on our cards,
        # for the patient who is declining or deferring this one screening.
        can_be_snoozed=True,
    )

    # No order button on a screening already waiting for a result - offering to
    # order it again is how you get two mammograms booked.
    command = _order_command(screening)
    if command is not None and status.state in (STATE_DUE, STATE_OVERDUE):
        card.add_recommendation(
            title=screening["order_comment"] or screening["name"],
            button=screening["order_button"] or "Order",
            commands=[command],
        )
    return card


def build_retired_card(patient_id: str, screening_id: str) -> ProtocolCard:
    """Retract a card the practice no longer wants on the chart.

    There is no effect that deletes a protocol card - the SDK offers
    ADD_OR_UPDATE_PROTOCOL_CARD and nothing else, where banner alerts get a
    REMOVE. So a card can only be retracted by overwriting it, and a card that
    stops being written would otherwise leave its last state - very possibly
    "OVERDUE" - on every chart it ever reached, permanently.

    **Two different things end up here**, and the wording has to be true of
    both: a screening the practice deleted or switched off, and one it still
    tracks but has switched the protocol card off for. Only the id survives the
    first, so this says as little as possible rather than inventing a name for
    a rule that may no longer exist - and it points at the record app, which is
    where the screening still lives in the second case.

    Canvas renders no NOT_APPLICABLE card at all (confirmed on a chart
    2026-09-22), so in practice this text is what makes the card *disappear*
    rather than something a provider reads.
    """
    return ProtocolCard(
        patient_id=patient_id,
        key=f"{KEY_PREFIX}:{screening_id}",
        title="Screening no longer shown here",
        narrative=(
            "This practice no longer shows this screening as a protocol card. "
            "Open the screening record beside the chart for this patient's "
            "current screening status."
        ),
        status=ProtocolCard.Status.NOT_APPLICABLE,
    )


def build_not_applicable_card(
    patient_id: str, screening: dict, *, attested: bool = False
) -> ProtocolCard:
    """A card stating this screening does not apply to this patient.

    Emitted rather than omitted so that a screening which stops applying - the
    patient ages out, a mastectomy is recorded, or a staff member says it does
    not apply - visibly clears instead of leaving its last state on the chart.

    ``attested`` distinguishes a person's judgement from the rule's. The rule
    not applying is a fact about the configuration; somebody deciding it does
    not apply is a fact about this patient, and only the second is something
    another clinician might want to revisit.
    """
    return ProtocolCard(
        patient_id=patient_id,
        key=card_key(screening),
        title=screening["name"],
        narrative=(
            "Marked not applicable to this patient by staff."
            if attested
            else "Does not apply to this patient."
        ),
        status=ProtocolCard.Status.NOT_APPLICABLE,
    )
