"""Shared logic for Mark as cash pay.

The Cash Pay label on a claim is the source of truth. Marking a note adds the
label and, if the claim is waiting in the coding queue, moves it to the Cash Pay
queue. A labeled claim that later lands in the coding queue (for example when the
note is signed) is moved by ``RouteLabeledClaims``. Unmarking removes the label
and returns the claim to the coding queue if it is still in the Cash Pay queue.

The plugin is off unless ``CASH_PAY_ENABLED`` is ``true``. When on, the Cash Pay
queue named by ``CASH_PAY_QUEUE_NAME`` must already exist; the plugin never
creates a queue and never falls back to label-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any

import arrow
from canvas_sdk.effects import Effect
from canvas_sdk.effects.claim import ClaimEffect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.v1.data import Staff
from canvas_sdk.v1.data.claim import Claim, ClaimQueue, ClaimQueues
from canvas_sdk.v1.data.note import Note

# Built-in queue a claim lands in after its note is signed. Routing only fires
# from here, and unmarking returns the claim here.
CODING_QUEUE = ClaimQueues.NEEDS_CODING_REVIEW.label

ENABLED_SETTING = "CASH_PAY_ENABLED"
QUEUE_SETTING = "CASH_PAY_QUEUE_NAME"
LABEL_SETTING = "CASH_PAY_LABEL_NAME"
DEFAULT_LABEL_NAME = "Cash Pay"


@dataclass(frozen=True)
class Config:
    enabled: bool
    queue_name: str
    label_name: str


def get_config(secrets: Any) -> Config:
    """Read plugin variables. Anything other than an explicit ``true`` is off."""
    get = secrets.get if hasattr(secrets, "get") else (lambda _key: None)
    enabled = str(get(ENABLED_SETTING) or "").strip().lower() == "true"
    queue_name = str(get(QUEUE_SETTING) or "").strip()
    label_name = str(get(LABEL_SETTING) or "").strip() or DEFAULT_LABEL_NAME
    return Config(enabled=enabled, queue_name=queue_name, label_name=label_name)


def config_problem(cfg: Config) -> str | None:
    """Why the plugin can't act right now, or None when it can.

    One cheap ``exists()`` read. Called only on a click or a queue move, never
    on button-visibility checks.
    """
    if not cfg.queue_name:
        return f"{QUEUE_SETTING} is not set."
    if not ClaimQueue.objects.filter(name=cfg.queue_name).exists():
        return (
            f"The claim queue '{cfg.queue_name}' does not exist. "
            "An admin needs to create it, or fix the queue name in the plugin settings."
        )
    return None


def error_modal(message: str) -> Effect:
    """A visible message for the person who clicked, instead of a silent no-op."""
    return LaunchModalEffect(
        content=(
            '<div style="font-family:system-ui,sans-serif;padding:16px;line-height:1.5">'
            "<p><strong>Mark as cash pay could not run.</strong></p>"
            f"<p>{escape(message)}</p>"
            "<p>Nothing was changed on this claim.</p></div>"
        ),
        target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        title="Cash pay",
    ).apply()


def note_from_context(context: dict[str, Any]) -> Note | None:
    """Note-header events give the note's integer dbid; accept a UUID too."""
    note_id = (context or {}).get("note_id")
    if not note_id:
        return None
    qs = Note.objects.select_related("note_type_version")
    if str(note_id).isdigit():
        return qs.filter(dbid=int(note_id)).first()
    return qs.filter(id=note_id).first()


def note_is_billable(note: Note) -> bool:
    note_type = note.note_type_version
    return bool(note_type and note_type.is_billable)


def claim_for_note(note: Note) -> Claim | None:
    claim = note.get_claim()
    if claim is None:
        return None
    # Re-read with the queue joined so later checks cost no extra query.
    return Claim.objects.select_related("current_queue").filter(id=claim.id).first()


def claim_has_label(claim: Claim, label_name: str) -> bool:
    return claim.labels.filter(name__iexact=label_name).exists()


def current_queue_name(claim: Claim) -> str | None:
    queue = claim.current_queue
    return queue.name if queue else None


def actor_name(context: dict[str, Any]) -> str:
    """Name of the staff member who clicked, for the claim comment."""
    user = (context or {}).get("user") or {}
    staff_id = user.get("staff") or user.get("id")
    if staff_id:
        staff = (
            Staff.objects.filter(id=staff_id).values("first_name", "last_name").first()
        )
        if staff:
            name = " ".join(
                p for p in (staff["first_name"], staff["last_name"]) if p
            ).strip()
            if name:
                return name
    return "a staff member"


def _now() -> str:
    return arrow.utcnow().format("YYYY-MM-DD HH:mm") + " UTC"


def build_mark_effects(claim: Claim, cfg: Config, who: str) -> list[Effect]:
    """Label the claim; move it now if it is waiting in the coding queue."""
    effect = ClaimEffect(claim_id=str(claim.id))
    effects: list[Effect] = []
    if not claim_has_label(claim, cfg.label_name):
        effects.append(effect.add_labels([cfg.label_name]))

    queue = current_queue_name(claim)
    if queue == CODING_QUEUE:
        effects.append(effect.move_to_queue(cfg.queue_name))
        where = f"Moved to the '{cfg.queue_name}' queue."
    elif queue == cfg.queue_name:
        where = f"Already in the '{cfg.queue_name}' queue."
    elif queue in (
        ClaimQueues.APPOINTMENT.label,
        ClaimQueues.NEEDS_CLINICIAN_REVIEW.label,
    ):
        where = (
            f"It will move to the '{cfg.queue_name}' queue when it reaches "
            f"{CODING_QUEUE}."
        )
    else:
        # Past coding (queued, filed, adjudicated, balance, trash). Moving it
        # could disrupt a submission, so only the label is added.
        where = f"Left in its current queue ('{queue}') because it is past coding."

    effects.append(
        effect.add_comment(
            f"Marked as cash pay by {who} on {_now()}. "
            f"'{cfg.label_name}' label applied. {where}"
        )
    )
    return effects


def build_unmark_effects(claim: Claim, cfg: Config, who: str) -> list[Effect]:
    """Remove the label; return the claim to coding if it is in the Cash Pay queue."""
    effect = ClaimEffect(claim_id=str(claim.id))
    effects: list[Effect] = []
    if claim_has_label(claim, cfg.label_name):
        effects.append(effect.remove_labels([cfg.label_name]))
    moved = ""
    if current_queue_name(claim) == cfg.queue_name:
        effects.append(effect.move_to_queue(CODING_QUEUE))
        moved = f" Returned to {CODING_QUEUE}."
    effects.append(
        effect.add_comment(
            f"Unmarked as cash pay by {who} on {_now()}. "
            f"'{cfg.label_name}' label removed.{moved}"
        )
    )
    return effects


def build_route_effects(claim: Claim, cfg: Config) -> list[Effect]:
    """Move a labeled claim that has just entered the coding queue."""
    effect = ClaimEffect(claim_id=str(claim.id))
    return [
        effect.move_to_queue(cfg.queue_name),
        effect.add_comment(
            f"Moved to the '{cfg.queue_name}' queue automatically because it has the "
            f"'{cfg.label_name}' label. Use 'Unmark as cash pay' on the note to stop this."
        ),
    ]
