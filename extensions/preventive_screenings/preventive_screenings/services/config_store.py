"""Load / save / seed the preventive screening rules (custom_data).

The config is one JSON document in a single ScreeningConfig row. On first load
(no row yet) it is seeded with the national-default screenings, then persisted,
so the admin page opens populated rather than blank.

The seeded screenings ship DISABLED on purpose, stamped with the date they were
current. They encode published national guidance, which a practice may well not
follow - the geriatrics practice in the requirements explicitly does not - and
an instance may record completions under codes these value sets do not carry. A
screening that looks configured and silently never fires, or one that fires on
the wrong patients, is worse than one that is visibly off. An admin reviews each
one and turns it on.

Normalization runs on read as well as write, so a document written by an older
version of the admin page can never hand the handler a missing key or a
string-typed age.
"""

import json
from typing import Any
from uuid import uuid4

from logger import log

from preventive_screenings.models import ScreeningConfig
from preventive_screenings.services.catalog import (
    ORDER_COMMANDS,
    SOURCE_PROCEDURE,
    SOURCES,
    VALUE_SETS,
)

_CONFIG_KEY = "active"

# When the shipped defaults were last checked against published guidance. Shown
# in the admin page so a practice reviews them rather than assuming they track
# the latest recommendation.
DEFAULTS_CURRENT_AS_OF = "2026-09-18"

# Rule defaults, applied to any field the stored document is missing.
DEFAULT_GRACE_DAYS = 90
DEFAULT_INTERVAL_QUANTITY = 1
DEFAULT_INTERVAL_UNIT = "years"

INTERVAL_UNITS = ("months", "years")
SEX_CHOICES = ("any", "female", "male")

# Every chart open reads the whole screening set, so it is capped: a runaway
# config would slow every chart in the practice, not just the admin page. Far
# above what a practice tracks in practice.
MAX_SCREENINGS = 40
MAX_SIGNALS_PER_SCREENING = 6
MAX_CODES_PER_SIGNAL = 25

# Free text is capped as well as counted, because counting alone does not bound
# what a run costs. The name is a card's title, a signal's label and the order
# text are in its body, and handlers.sweep sizes each run against
# WORST_CARD_BYTES - a constant measured from realistic cards. A 400-character
# name already doubles a card, and the overrun is silent in the worst way: the
# effects list is dropped whole *after* those patients were recorded as
# reviewed, so their cards stay wrong until the next cycle with nothing shown to
# the admin. Capping in normalize rather than at the endpoint means it holds
# however the document arrived.
MAX_TEXT_CHARS = 200
MAX_CODE_CHARS = 64
# ⚠️ `guidance` is currently WRITE-ONCE-AT-SEED, READ-NEVER. An earlier comment
# here called it "the editor's note to the next admin", which cannot be true:
# **the admin page has no input for it.** The six shipped seeds hardcode a
# sentence each, every screening a practice creates gets "", and nothing can
# ever change either. It also reaches no clinical surface - not the card, not
# the record panel.
#
# It survives a round trip (the editor POSTs the whole screening object back
# untouched), so the seeded text is intact and nothing is lost by leaving this
# alone. But it is dead data until something both writes and reads it, and the
# cap below is the only part of it currently doing any work.
MAX_GUIDANCE_CHARS = 2000


def _completion(
    value_set_key: str,
    interval_quantity: int,
    interval_unit: str = "years",
    **overrides: Any,
) -> dict[str, Any]:
    """Build a completion signal keyed to a catalog entry."""
    entry = VALUE_SETS[value_set_key]
    signal: dict[str, Any] = {
        "value_set_key": value_set_key,
        "source": entry.source,
        "codes": [],
        "label": "",
        "interval_quantity": interval_quantity,
        "interval_unit": interval_unit,
    }
    signal.update(overrides)
    return signal


def _exclusion(value_set_key: str) -> dict[str, Any]:
    """Build an exclusion keyed to a catalog entry."""
    entry = VALUE_SETS[value_set_key]
    return {
        "value_set_key": value_set_key,
        "source": entry.source,
        "codes": [],
        "label": "",
    }


# The shipped defaults. Ages, sexes and intervals follow published national
# guidance as of DEFAULTS_CURRENT_AS_OF; the exclusions are the anatomical ones,
# where the screening is not merely low-value but impossible.
#
# These deliberately do NOT match the instance's own native protocols, and that
# was checked rather than assumed (2026-09-20, against the supplied source of
# all 15). The native ones are CMS eCQM **v6** - they import
# `canvas_workflow_kit.value_set.v2018` and cite USPSTF 2008 - so their ages are
# the 2017 reporting-year specs, since superseded: CMS130v6 screens colorectal
# from 50 where USPSTF moved to 45 in 2021, and CMS125v6 starts breast at 51,
# which is not a clinical age at all but a denominator artifact of measuring a
# 27-month lookback. Copying either would have shipped older guidance than we
# already had. What the comparison did produce is below: modalities and
# exclusions the native rules accept and these seeds had missed.
#
# Bone density is deliberately expressed with explicit CPT codes rather than a
# catalog value set: the SDK ships no DXA screening set, and it doubles as the
# worked example of a screening that is not a quality measure at all, which is
# the thing a practice most needs to see before writing their own.
# Every seed carries an explicit id, and they must never change.
#
# The id is the card's key (services/cards.card_key), so an id that moves orphans
# every card already written under the old one - and nothing deletes a protocol
# card, so those stay on the chart forever. Without these, `new_screening`
# assigns `uuid4().hex`, and because `load_config` returns the seeded document
# *without saving it*, a fresh install would mint new ids on every single read:
# new card keys every write, and a config_stamp that differs every tick, which
# makes the sweep believe the rules changed and requeue the whole panel every
# five minutes forever.
_SEED_SCREENINGS: list[dict[str, Any]] = [
    {
        "id": "seed-mammogram",
        "name": "Mammogram",
        "sex": "female",
        "min_age": 40,
        "max_age": 74,
        "completions": [_completion("mammography", 2)],
        "exclusions": [
            _exclusion("bilateral_mastectomy"),
            _exclusion("history_bilateral_mastectomy"),
        ],
        "order_command": "imaging_order",
        "order_button": "Order mammogram",
        # **CPT, not LOINC, and that is the whole difference.** An imaging order
        # resolves its code against the practice's imaging catalog, which is
        # keyed on CPT. This seed carried LOINC 24606-6 and the staged order
        # arrived with every field empty for five deploys; the bone-density seed
        # below carried CPT 77080 all along and pre-filled correctly. Confirmed
        # on a real chart 2026-09-22 - same command, same plugin, different
        # code system, opposite result.
        "order_code": "77067",
        "order_comment": "Screening mammogram",
        "guidance": "Biennial screening mammography for women aged 40 to 74.",
    },
    {
        "id": "seed-colorectal",
        "name": "Colorectal cancer screening",
        "sex": "any",
        "min_age": 45,
        "max_age": 75,
        # Modality-dependent intervals: a colonoscopy covers ten years, a stool
        # test only one. The screening is satisfied until the latest of these
        # runs out, so a patient is not chased for a FIT the year after a
        # clear colonoscopy.
        #
        # The last two came from the instance's own CMS130v6, which accepts
        # them and this seed did not. A modality we do not know about can only
        # ever make a screened patient read as overdue, so adding one is safe
        # in the direction that matters.
        "completions": [
            _completion("colonoscopy", 10),
            _completion("flexible_sigmoidoscopy", 5),
            _completion("ct_colonography", 5),
            _completion("sdna_fit_test", 3),
            _completion("fobt", 1),
        ],
        # Colorectal cancer itself is an exclusion in CMS130v6 and was missing
        # here: a patient already diagnosed is under surveillance, not
        # screening, and a "due" card on their chart is exactly the wrong-patient
        # recommendation the brief warns about.
        "exclusions": [_exclusion("total_colectomy"), _exclusion("colorectal_cancer")],
        "order_command": "refer",
        "order_button": "Refer for colonoscopy",
        "order_code": "",
        "order_comment": "Screening colonoscopy",
        "guidance": "Screening for colorectal cancer in adults aged 45 to 75, by colonoscopy "
        "every 10 years, CT colonography or sigmoidoscopy every 5, sDNA-FIT every 3, "
        "or a stool test annually.",
    },
    {
        "id": "seed-cervical",
        "name": "Cervical cancer screening",
        "sex": "female",
        "min_age": 21,
        "max_age": 65,
        "completions": [_completion("pap_test", 3), _completion("hpv_test", 5)],
        "exclusions": [_exclusion("absence_of_cervix"), _exclusion("hysterectomy_no_cervix")],
        "order_command": "lab_order",
        "order_button": "Order cervical cytology",
        "order_code": "10524-7",
        "order_comment": "Cervical cytology screening",
        "guidance": "Cytology every 3 years for women 21 to 65, or HPV testing every 5 years.",
    },
    {
        "id": "seed-falls",
        "name": "Falls risk screening",
        "sex": "any",
        "min_age": 65,
        "max_age": 0,
        "completions": [_completion("falls_screening", 1)],
        "exclusions": [],
        "order_command": "perform",
        "order_button": "Record falls screening",
        "order_code": "",
        "order_comment": "Annual falls risk screening",
        "guidance": "Annual falls risk screening for community-dwelling adults 65 and over.",
    },
    {
        "id": "seed-tobacco",
        "name": "Tobacco use screening",
        "sex": "any",
        "min_age": 18,
        "max_age": 0,
        "completions": [_completion("tobacco_use_screening", 1)],
        "exclusions": [],
        "order_command": "perform",
        "order_button": "Record tobacco screening",
        "order_code": "",
        "order_comment": "Annual tobacco use screening",
        "guidance": "Annual tobacco use screening for all adults.",
    },
    {
        "id": "seed-bone-density",
        "name": "Bone density (DXA)",
        "sex": "female",
        "min_age": 65,
        "max_age": 0,
        "completions": [
            {
                "value_set_key": "",
                "source": SOURCE_PROCEDURE,
                "codes": ["77080", "77081"],
                "label": "DXA bone density scan",
                "interval_quantity": 2,
                "interval_unit": "years",
            }
        ],
        "exclusions": [],
        "order_command": "imaging_order",
        "order_button": "Order DXA scan",
        "order_code": "77080",
        "order_comment": "Screening DXA bone density",
        "guidance": "Bone density screening for women 65 and over. Uses explicit CPT codes: "
        "no national value set for screening DXA ships with the SDK.",
    },
]


def _coerce_int(value: Any, fallback: int) -> int:
    """Read an int out of whatever the form sent, falling back on anything unusable."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_choice(value: Any, choices: tuple[str, ...], fallback: str) -> str:
    """Keep a stored value inside its allowed set."""
    text = str(value or "").strip()
    return text if text in choices else fallback


def _coerce_text(value: Any, limit: int) -> str:
    """Read a free-text field, trimmed and capped. See the cap constants above."""
    return str(value or "").strip()[:limit]


def _coerce_codes(value: Any) -> list[str]:
    """Read a signal's custom codes, dropping blanks and capping count and length."""
    if not isinstance(value, list):
        return []
    codes = [
        str(code).strip()[:MAX_CODE_CHARS] for code in value if str(code or "").strip()
    ]
    return codes[:MAX_CODES_PER_SIGNAL]


def _normalize_signal(raw: dict[str, Any], *, with_interval: bool) -> dict[str, Any] | None:
    """Normalize one completion signal or exclusion, or drop it if unusable.

    A signal naming a catalog entry takes its source from the catalog rather
    than from the document, so the two can never disagree. A signal that names
    neither a known value set nor any code matches nothing, and is dropped
    rather than left to silently never fire.
    """
    value_set_key = str(raw.get("value_set_key") or "").strip()
    codes = _coerce_codes(raw.get("codes"))
    entry = VALUE_SETS.get(value_set_key)

    if entry:
        source = entry.source
    elif codes:
        value_set_key = ""  # an unknown key with codes falls back to the codes
        source = _coerce_choice(raw.get("source"), tuple(SOURCES), SOURCE_PROCEDURE)
    else:
        return None

    signal: dict[str, Any] = {
        "value_set_key": value_set_key,
        "source": source,
        "codes": codes,
        "label": _coerce_text(raw.get("label"), MAX_TEXT_CHARS),
    }
    if with_interval:
        signal["interval_quantity"] = max(
            1, _coerce_int(raw.get("interval_quantity"), DEFAULT_INTERVAL_QUANTITY)
        )
        signal["interval_unit"] = _coerce_choice(
            raw.get("interval_unit"), INTERVAL_UNITS, DEFAULT_INTERVAL_UNIT
        )
    return signal


def _normalize_signals(raw: Any, *, with_interval: bool) -> list[dict[str, Any]]:
    """Normalize a list of signals, dropping unusable ones and capping the count."""
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if isinstance(item, dict):
            signal = _normalize_signal(item, with_interval=with_interval)
            if signal:
                out.append(signal)
    return out[:MAX_SIGNALS_PER_SCREENING]


def new_screening(**overrides: Any) -> dict[str, Any]:
    """Build a screening with every field populated, so callers never see a missing key."""
    screening: dict[str, Any] = {
        "id": uuid4().hex,
        "enabled": False,
        # Whether this screening also writes a protocol card onto the chart.
        #
        # **Off by default, which is a change of emphasis rather than a default
        # value.** The chart-side record app computes live, shows every
        # screening including the satisfied ones Canvas will not render a card
        # for, and is where a provider can act. A protocol card is stored state
        # that needs a sweep, a fingerprint and a retraction path to stay
        # truthful. Practices that want the card at the top of the chart switch
        # it on per screening; the rest get the app and none of the machinery.
        "protocol_card": False,
        "name": "New screening",
        "sex": "any",
        "min_age": 18,
        # 0 means "no upper limit"; a screening that stops at an age sets it.
        "max_age": 0,
        "grace_days": DEFAULT_GRACE_DAYS,
        "completions": [],
        "exclusions": [],
        "order_command": "",
        "order_button": "",
        "order_code": "",
        "order_comment": "",
        "guidance": "",
    }
    screening.update(overrides)
    return screening


def normalize_screening(raw: dict[str, Any], position: int | None = None) -> dict[str, Any]:
    """Fill in defaults and coerce types for one stored screening.

    ``position`` is the screening's index in the document, used only to invent a
    *stable* id for a screening that arrived without one - a hand-edited or
    migrated document. Normalizing is a read-path operation that runs on every
    chart change and every sweep tick, so a random id here would give the same
    screening a different card key every time it was read.
    """
    order_command = str(raw.get("order_command") or "").strip()
    fallback = uuid4().hex if position is None else f"screening-{position}"
    return new_screening(
        id=str(raw.get("id") or fallback),
        enabled=bool(raw.get("enabled", False)),
        # Absent means off, which is what makes a document saved by an older
        # version of the editor arrive with its cards switched off. That is
        # deliberate and it is not silent: the sweep retracts those cards the
        # same way it retracts a screening that was switched off, so they are
        # taken back off the chart rather than left behind to go stale.
        protocol_card=bool(raw.get("protocol_card", False)),
        name=_coerce_text(raw.get("name"), MAX_TEXT_CHARS) or "Untitled screening",
        sex=_coerce_choice(raw.get("sex"), SEX_CHOICES, "any"),
        min_age=max(0, _coerce_int(raw.get("min_age"), 0)),
        max_age=max(0, _coerce_int(raw.get("max_age"), 0)),
        grace_days=max(0, _coerce_int(raw.get("grace_days"), DEFAULT_GRACE_DAYS)),
        completions=_normalize_signals(raw.get("completions"), with_interval=True),
        exclusions=_normalize_signals(raw.get("exclusions"), with_interval=False),
        order_command=order_command if order_command in ORDER_COMMANDS else "",
        order_button=_coerce_text(raw.get("order_button"), MAX_TEXT_CHARS),
        order_code=_coerce_text(raw.get("order_code"), MAX_CODE_CHARS),
        order_comment=_coerce_text(raw.get("order_comment"), MAX_TEXT_CHARS),
        guidance=_coerce_text(raw.get("guidance"), MAX_GUIDANCE_CHARS),
    )


def normalize_document(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a config document with every screening normalized and every key present.

    Screenings past ``MAX_SCREENINGS`` are dropped. The save endpoint refuses
    such a document outright; this is the backstop for one that arrived any
    other way.
    """
    screenings = raw.get("screenings")
    return {
        "version": _coerce_int(raw.get("version"), 1),
        "defaults_current_as_of": str(
            raw.get("defaults_current_as_of") or DEFAULTS_CURRENT_AS_OF
        ),
        "defaults_reviewed": bool(raw.get("defaults_reviewed", False)),
        "screenings": [
            normalize_screening(s, position)
            for position, s in enumerate(s for s in screenings if isinstance(s, dict))
        ][:MAX_SCREENINGS]
        if isinstance(screenings, list)
        else [],
    }


def _default_document() -> dict[str, Any]:
    """Build the seed config (disabled defaults; the admin owns these after seed)."""
    return {
        "version": 1,
        "defaults_current_as_of": DEFAULTS_CURRENT_AS_OF,
        "defaults_reviewed": False,
        "screenings": [new_screening(**seed) for seed in _SEED_SCREENINGS],
    }


def load_config() -> dict[str, Any]:
    """Return the stored config, seeding and persisting the defaults on first use.

    Never raises. A failure to read config degrades to the (disabled) defaults
    rather than breaking the chart - the handler that calls this runs on every
    chart open.
    """
    try:
        row = ScreeningConfig.objects.filter(key=_CONFIG_KEY).first()
        if row and row.payload:
            return normalize_document(json.loads(row.payload))
    except Exception as exc:  # missing namespace/table or bad payload -> defaults
        log.warning(f"preventive_screenings config load failed, using defaults: {exc}")
        return _default_document()
    doc = _default_document()
    save_config(doc)  # best-effort seed; never raises
    return doc


def save_config(doc: dict[str, Any]) -> bool:
    """Persist the config document; return False if custom_data is unavailable.

    Broad catch is deliberate - a missing namespace/table must not crash the
    request; the caller decides how to report it.
    """
    try:
        payload = json.dumps(normalize_document(doc))
        row = ScreeningConfig.objects.filter(key=_CONFIG_KEY).first()
        if row:
            row.payload = payload
            row.save()
        else:
            ScreeningConfig.objects.create(key=_CONFIG_KEY, payload=payload)
        return True
    except Exception as exc:  # custom_data namespace/table not ready
        log.warning(
            f"preventive_screenings config save failed (custom_data unavailable?): {exc}"
        )
        return False


def active_screenings(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The screenings that are switched on and can actually be measured.

    A screening with no completion signal has no way to ever read as done, so
    it would sit on the card list permanently. It is treated as not configured.
    """
    return [
        screening
        for screening in doc.get("screenings", [])
        if screening.get("enabled") and screening.get("completions")
    ]


def carded_screenings(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The screenings that also put a protocol card on the chart.

    A subset of ``active_screenings``: a screening can be tracked without being
    carded, and that is the default. Everything that writes cards - the sweep
    and the chart-change handler - works from this list, so a practice that
    cards nothing runs none of the card machinery at all.

    The chart-side record app deliberately uses ``active_screenings`` instead.
    It computes live, so it costs nothing to keep current and has no reason to
    hide a screening the practice tracks just because the card is off.

    ⚠️ Switching a card **off** is not the same as never having had one.
    Nothing deletes a protocol card, so the last state - very possibly
    "OVERDUE" - stays on every chart it reached until something overwrites it.
    ``handlers.sweep`` is what does that: it compares this list against what it
    was carding before and retracts the difference. Any new caller that writes
    cards from somewhere else has to account for the same thing.
    """
    return [
        screening for screening in active_screenings(doc) if screening.get("protocol_card")
    ]


