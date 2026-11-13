"""Stage a screening's order from the chart-side record app.

**Why this exists.** The one-click order used to live only on the protocol
card, as a recommendation Canvas renders a button for. Cards became opt-in and
off by default in 0.18.0, which quietly took the client's *"order it without
leaving the chart"* requirement with them: a practice that cards nothing had no
way to order from this plugin at all.

So the record panel stages the command itself. That is a different mechanism
from the card's, and worth being precise about, because the two fail
differently:

* **The card** passes a *search filter* through
  ``ProtocolCard.add_recommendation``. Canvas renders the button and runs the
  lookup. Nothing here is involved.
* **The panel** builds the command and calls ``originate()``, which returns an
  ``ORIGINATE_<X>_COMMAND`` effect that the route hands back with its response.
  That a ``SimpleAPI`` route may return an effect was measured on a real chart
  2026-10-06, and ``prescription_favorites`` - a plugin already shipped on this
  instance - does exactly this from its own patient-scoped app.

⚠️ **The pre-fill may need the same fix the card needed.** ``originate()``
sends ``data: self.values``, and ``values`` keys by the **Python** field name
(``image_code``) where the Commands API calls that field ``image`` - the SDK
only applies ``commands_api_name`` in ``command_schema()``, never on the way
out. That is the identical mismatch that staged five deploys' worth of empty
commands from cards. It is sent under both names here for the same reason
``services.cards`` does: Canvas ignores the key it does not know, so carrying
both costs nothing and does not depend on being right about which it reads.
"""

import json
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteStates
from logger import log

from preventive_screenings.services.catalog import ORDER_COMMANDS

# The note states that mean a note is open and can still take a command. Taken
# from `prescription_favorites`, which stages into the most recent open note
# the same way. A locked or deleted note cannot.
_OPEN_NOTE_STATES = (
    NoteStates.NEW,
    NoteStates.PUSHED,
    NoteStates.CONVERTED,
    NoteStates.UNLOCKED,
    NoteStates.RESTORED,
    NoteStates.UNDELETED,
)


def open_note_id(patient_id: str) -> str | None:
    """The most recently touched open note for this patient, or None.

    ``originate`` needs a note to put the command in, and this app is
    **patient-scoped, not note-scoped** - a provider can open the record beside
    a chart with no note open at all. There is no effect that creates one, so
    the honest answer when there is none is to say so and let them open one.
    (The card's button does not have this problem: Canvas opens a note for a
    protocol-card recommendation itself.)

    Selects the id column only. A ``Note`` carries its whole body, and
    hydrating the row to read one id is the mistake the database review caught
    on the chart-open path. The state filter is a subquery on
    ``CurrentNoteStateEvent``'s own ``note_id`` rather than a join onto the
    ``current_*`` view, which is the other half of that finding.
    """
    try:
        open_notes = CurrentNoteStateEvent.objects.filter(
            state__in=[state.value for state in _OPEN_NOTE_STATES]
        ).values_list("note_id", flat=True)
        found = (
            Note.objects.filter(dbid__in=open_notes, patient__id=patient_id)
            .order_by("-modified")
            .values_list("id", flat=True)
            .first()
        )
        return str(found) if found else None
    except Exception as exc:  # an unreadable note list must not 500 the panel
        log.warning(f"preventive_screenings: could not find an open note ({exc})")
        return None


def stage_order(screening: dict, note_uuid: str) -> Effect | None:
    """The effect that puts this screening's order, unsigned, in that note.

    ``None`` when the screening configures no order command - the practice can
    track a screening without offering to order it, and the panel leaves the
    button out rather than offering one that does nothing.

    **Unsigned, always.** ``originate`` defaults to ``commit=False`` and this
    does not override it, so the provider still completes and signs. That is
    the brief's "nothing is ordered automatically" met by construction rather
    than by convention, exactly as the card's version is.
    """
    entry = ORDER_COMMANDS.get(screening["order_command"])
    if entry is None:
        return None

    code = screening["order_code"]
    value: Any = None
    if entry.code_field and code:
        value = [code] if entry.code_is_list else code

    effect = _originate(entry, note_uuid, value)
    if effect is None and value is not None:
        # **Some commands refuse a bare code.** `LabOrderCommand` validates
        # "lab partner is required to find tests" before it will accept
        # `tests_order_codes` at all, because the tests are looked up in a
        # particular partner's compendium - and this plugin has no way to know
        # which partner a practice uses.
        #
        # An empty command of the right type is still most of the value: one
        # click to the right form, with the provider picking the test. That is
        # exactly what `refer` does by construction, since it has no code field
        # at all. Withholding the button instead would be worse.
        log.info(
            f"preventive_screenings: {screening['order_command']} would not take a "
            f"code, staging it empty for the provider to fill"
        )
        value = None
        effect = _originate(entry, note_uuid, None)

    if effect is None:
        log.warning(
            f"preventive_screenings: could not stage a {screening['order_command']}"
        )
        return None

    return _with_api_named_code(effect, entry.code_api_field, value)


def _originate(entry: Any, note_uuid: str, value: Any) -> Effect | None:
    """Build the command and turn it into an effect, or None if the SDK refuses.

    ⚠️ **Both steps together, because the SDK validates on ``originate``, not
    on construction.** ``LabOrderCommand(tests_order_codes=[...])`` builds
    perfectly happily and then refuses to originate without a lab partner. A
    fallback that only caught construction errors would have missed it
    entirely - which is the same shape as `canvas validate` loading a handler
    without invoking it, and it is how this plugin has shipped broken twice.
    """
    fields: dict[str, Any] = {"note_uuid": note_uuid}
    if value is not None and entry.code_field:
        fields[entry.code_field] = value
    try:
        found: Effect = entry.command(**fields).originate()
        return found
    except Exception:
        return None


def _with_api_named_code(effect: Effect, api_field: str | None, value: Any) -> Effect:
    """Repeat the code under the name the Commands API uses.

    See the module docstring: ``originate`` keys its payload by the Python
    field name, and the Commands API uses a different one for every command
    that takes a code. Rather than guess which Canvas reads, send both - it
    ignores the one it does not recognise, which is precisely how the card's
    version of this bug stayed invisible for five deploys.

    Rebuilding the payload rather than reaching into the command object,
    because ``values`` is derived from the model's own fields and there is no
    supported way to add a key to it.
    """
    if not api_field or value is None:
        return effect
    try:
        payload = json.loads(effect.payload)
        payload["data"][api_field] = value
        return Effect(type=effect.type, payload=json.dumps(payload))
    except (ValueError, KeyError, TypeError) as exc:  # pragma: no cover - defensive
        log.warning(f"preventive_screenings: could not add the API-named code ({exc})")
        return effect
