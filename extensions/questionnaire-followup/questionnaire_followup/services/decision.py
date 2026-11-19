"""Decide which follow-up forms a patient currently owes, and optionally say why not.

The portal handler and the admin diagnostic both call :func:`owed_forms`, so what
the diagnostic reports is what the handler actually did. There is no second
implementation of the rules to drift out of step with the first.

Pass a ``trace`` to collect one entry per rule naming the gate that stopped it.
The handler passes nothing, so explaining costs the portal's hot path a few
``is None`` checks and no extra queries: every value a trace entry reads is
already loaded by the query that gate just ran.

The gates run in order, batched across rules rather than repeated per rule, and
each one only runs for the rules the previous one kept:

    screen found -> inside the lookback -> score fires the comparator ->
    both codes resolve -> not already answered

See CLAUDE.md, "How it runs", for the query budget this order exists to protect.
"""

from datetime import datetime, timedelta
from typing import Any

from canvas_sdk.v1.data import CurrentNoteStateEvent, Note, Questionnaire
from canvas_sdk.v1.data.questionnaire import Interview
from django.db.models import F, Max

from questionnaire_followup.services.config_store import describe_rule
from questionnaire_followup.services.questionnaires import resolve_codes
from questionnaire_followup.services.scoring import matches, needs_score, score_interviews

# A rule, the screen that triggered it, and the follow-up questionnaire it owes.
Owed = tuple[dict[str, Any], Interview, Questionnaire]

# One entry per rule considered: what it is, and how far it got.
Trace = list[dict[str, Any]]

# Why a rule produced nothing, or that it produced something. Stable strings, so
# a caller can branch on the outcome without parsing the sentence beside it.
OUTCOME_OWED = "owed"
OUTCOME_NO_SCREEN = "no_screen"
OUTCOME_SCREEN_TOO_OLD = "screen_too_old"
OUTCOME_SCORE_DID_NOT_FIRE = "score_did_not_fire"
OUTCOME_CODE_NOT_FOUND = "code_not_found"
OUTCOME_ALREADY_ANSWERED = "already_answered"


def _when(moment: datetime) -> str:
    """Format a timestamp for a human reading a trace."""
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def _record(
    trace: Trace | None, rule: dict[str, Any], outcome: str, detail: str
) -> None:
    """Append one rule's result to the trace, if anyone asked for one."""
    if trace is None:
        return
    trace.append(
        {
            "rule_id": rule.get("id", ""),
            "rule": rule.get("name", ""),
            "trigger_code": rule.get("trigger_code", ""),
            "followup_code": rule.get("followup_code", ""),
            "condition": describe_rule(rule),
            "outcome": outcome,
            "detail": detail,
        }
    )


def owed_forms(
    rules: list[dict[str, Any]],
    patient_id: str,
    now: datetime,
    trace: Trace | None = None,
) -> list[Owed]:
    """Every rule whose follow-up this patient currently owes, in configured order."""
    screens = latest_screens(rules, patient_id, now)

    candidates: list[tuple[dict[str, Any], Interview]] = []
    for rule in rules:
        # The latest screen per code serves every rule on that code: if it falls
        # outside one rule's lookback, no older screen can fall inside it.
        screen = screens.get(rule["trigger_code"])
        lookback = rule["trigger_lookback_days"]
        if screen is None:
            _record(
                trace,
                rule,
                OUTCOME_NO_SCREEN,
                f"no committed response to {rule['trigger_code']} on this patient's chart "
                f"in the last {lookback} days",
            )
            continue
        if screen.created < now - timedelta(days=lookback):
            _record(
                trace,
                rule,
                OUTCOME_SCREEN_TOO_OLD,
                f"the most recent {rule['trigger_code']} was {_when(screen.created)}, "
                f"outside this rule's {lookback}-day lookback",
            )
            continue
        candidates.append((rule, screen))
    if not candidates:
        return []

    # Only rules whose comparator reads a score are scored; one that pairs on
    # completion alone never runs this query.
    scores = score_interviews(
        [(screen, rule["trigger_code"]) for rule, screen in candidates if needs_score(rule)]
    )

    triggered: list[tuple[dict[str, Any], Interview]] = []
    for rule, screen in candidates:
        score = scores.get((screen.pk, rule["trigger_code"]))
        if not matches(score, rule):
            scored = (
                "did not score (no numeric answers recorded)"
                if score is None
                else f"scored {score}"
            )
            _record(
                trace,
                rule,
                OUTCOME_SCORE_DID_NOT_FIRE,
                f"the {rule['trigger_code']} from {_when(screen.created)} {scored}, "
                f"which does not satisfy '{describe_rule(rule)}'",
            )
            continue
        triggered.append((rule, screen))
    if not triggered:
        return []

    questionnaires = resolve_codes(
        {code for rule, _ in triggered for code in (rule["trigger_code"], rule["followup_code"])}
    )

    resolved: list[Owed] = []
    for rule, screen in triggered:
        # A pairing pointing at a code this instance does not have does nothing
        # rather than guessing at a substitute. The editor flags these too, so the
        # silence is visible before a patient is ever involved.
        missing = [
            code
            for code in (rule["trigger_code"], rule["followup_code"])
            if code not in questionnaires
        ]
        if missing:
            _record(
                trace,
                rule,
                OUTCOME_CODE_NOT_FOUND,
                "this instance has no single active questionnaire coded "
                + ", ".join(missing),
            )
            continue
        resolved.append((rule, screen, questionnaires[rule["followup_code"]]))
    if not resolved:
        return []

    answered = latest_followups(resolved, patient_id, now)

    owed: list[Owed] = []
    for rule, screen, followup in resolved:
        latest = answered.get(rule["followup_code"])
        # The None check is redundant with already_answered, which returns False
        # for None - it is here so the detail below can read `latest` as a date.
        if latest is not None and already_answered(rule, screen, latest, now):
            reason = (
                "since that screen, so the pairing is done"
                if latest >= screen.created
                else f"within this rule's {rule['suppression_days']}-day re-ask window"
            )
            _record(
                trace,
                rule,
                OUTCOME_ALREADY_ANSWERED,
                f"{rule['followup_code']} was answered {_when(latest)}, {reason}",
            )
            continue
        _record(
            trace,
            rule,
            OUTCOME_OWED,
            f"{followup.name} is owed, from a {rule['trigger_code']} on "
            f"{_when(screen.created)}",
        )
        owed.append((rule, screen, followup))
    return owed


def latest_screens(
    rules: list[dict[str, Any]], patient_id: str, now: datetime
) -> dict[str, Interview]:
    """The patient's most recent committed screen per trigger code.

    Bounded by the longest lookback among the rules, so a screen from years ago
    does not start assigning long questionnaires today.
    """
    cutoff = now - timedelta(days=max(rule["trigger_lookback_days"] for rule in rules))
    interviews = (
        Interview.objects.for_patient(patient_id)
        .committed()
        .filter(
            questionnaires__code__in={rule["trigger_code"] for rule in rules},
            created__gte=cutoff,
        )
        .annotate(matched_code=F("questionnaires__code"))
        .only("dbid", "id", "created", "note_id")
        .order_by("-created")
    )
    latest: dict[str, Interview] = {}
    for interview in interviews:
        latest.setdefault(interview.matched_code, interview)
    return latest


def latest_followups(
    owed: list[Owed], patient_id: str, now: datetime
) -> dict[str, datetime]:
    """When the patient last answered each follow-up, as far back as any rule looks.

    An answer only counts if it came after the rule's screen or inside its re-ask
    window, so nothing older than the earliest such moment is read.
    """
    since = min(counts_from(rule, screen, now) for rule, screen, _ in owed)
    answers = (
        Interview.objects.for_patient(patient_id)
        .committed()
        .filter(
            questionnaires__code__in={rule["followup_code"] for rule, _, _ in owed},
            created__gte=since,
        )
        .values("questionnaires__code")
        .annotate(latest=Max("created"))
        .order_by()
    )
    return {row["questionnaires__code"]: row["latest"] for row in answers}


def counts_from(rule: dict[str, Any], screen: Interview, now: datetime) -> datetime:
    """The earliest follow-up answer that would still settle this rule."""
    screened: datetime = screen.created
    suppression_days = rule["suppression_days"]
    if not suppression_days:
        return screened
    return min(screened, now - timedelta(days=suppression_days))


def already_answered(
    rule: dict[str, Any], screen: Interview, latest_followup: datetime | None, now: datetime
) -> bool:
    """Whether this patient is owed nothing further for this pairing.

    Two separate reasons to stay quiet, and both matter: the patient has answered
    the long form since this screen (the pairing is done), or they answered it
    recently enough that a fresh screen should not ask again yet.
    """
    if latest_followup is None:
        return False
    if latest_followup >= screen.created:
        return True
    suppression_days = rule["suppression_days"]
    return bool(suppression_days) and latest_followup >= now - timedelta(days=suppression_days)


def editable_note_ids(note_dbids: set[int]) -> dict[int, str]:
    """Map each screening note that still accepts commands to its UUID.

    The follow-up joins the note the short form was answered in, so the screen and
    its follow-up read as one encounter - the "before the visit ends" case. A
    locked or signed note is left out, and the resulting None asks Canvas to
    create a note instead.

    Reads the state and, for editable notes, the UUID alone. Loading the Note
    itself would pull its body and other large columns on every portal page load
    until the patient answers.
    """
    wanted = {dbid for dbid in note_dbids if dbid}
    if not wanted:
        return {}
    editable = [
        state.note_id
        for state in CurrentNoteStateEvent.objects.filter(note_id__in=wanted).only(
            "dbid", "note", "state"
        )
        if state.editable()
    ]
    if not editable:
        return {}
    return {
        dbid: str(uuid)
        for dbid, uuid in Note.objects.filter(dbid__in=editable).values_list("dbid", "id")
    }
