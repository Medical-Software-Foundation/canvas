"""Shared constants: entry statuses, match preferences, and config defaults.

Statuses and priority labels come from the plugin specification. They are plain
strings rather than ``CharField(choices=...)`` because the plugin DDL pipeline
maps every text column to ``text`` regardless of choices, so the enum would not
be enforced at the database level anyway. Validation happens in
``services/transitions.py``.
"""

from typing import Any
from urllib.parse import quote

from scheduling_waitlist import CACHE_BUST

PLUGIN_NAME = "scheduling_waitlist"
API_BASE = f"/plugin-io/api/{PLUGIN_NAME}"

# The roster page. Lives here rather than in the application module so the chart
# banner can link to it without services importing from applications.
ROSTER_URL = f"{API_BASE}/app/?v={CACHE_BUST}"

# The query parameter naming the patient an add form is for.
ADD_FOR_PATIENT_PARAM = "patient"

# What the freed slot already told us, so the scheduler does not re-enter it.
# Keys rather than names: the form matches them against its own dropdowns.
PREFILL_SERVICE_PARAM = "service"
PREFILL_PROVIDER_PARAM = "provider"
PREFILL_LOCATION_PARAM = "location"


def add_form_url(
    patient_id: str,
    *,
    note_type_dbid: Any = None,
    provider_dbid: Any = None,
    location_dbid: Any = None,
) -> str:
    """The compact add form for one named patient.

    A page of its own rather than the roster with a parameter: the chart button
    opens a dialog, and the roster is a full-width page that sizes itself as one.
    Both post to the same endpoint, so there is still one set of validation rules.

    The optional keys pre-select the form's dropdowns. They come from the
    cancelled appointment when the button was clicked there, and are absent when
    it was clicked on a chart header, where there is no slot to copy.

    Encoded rather than interpolated: these are external input, and an unescaped
    value would silently truncate the query string.
    """
    params = [
        f"{ADD_FOR_PATIENT_PARAM}={quote(str(patient_id), safe='')}",
        f"v={CACHE_BUST}",
    ]
    # Only what was actually known. A blank parameter would be indistinguishable
    # from a deliberate "any provider", and would pre-select the wrong thing.
    for name, value in (
        (PREFILL_SERVICE_PARAM, note_type_dbid),
        (PREFILL_PROVIDER_PARAM, provider_dbid),
        (PREFILL_LOCATION_PARAM, location_dbid),
    ):
        if value not in (None, ""):
            params.append(f"{name}={quote(str(value), safe='')}")

    return f"{API_BASE}/app/add?" + "&".join(params)



# --- entry statuses ---------------------------------------------------------
STATUS_WAITING = "waiting"
STATUS_OFFERED = "offered"
STATUS_SCHEDULED = "scheduled"
STATUS_REMOVED = "removed"
STATUS_EXPIRED = "expired"

ALL_STATUSES = (
    STATUS_WAITING,
    STATUS_OFFERED,
    STATUS_SCHEDULED,
    STATUS_REMOVED,
    STATUS_EXPIRED,
)

# An offered entry is still matchable: "we told them about a slot" is not the
# same as "they booked it", so they stay in the running for the next opening.
MATCHABLE_STATUSES = (STATUS_WAITING, STATUS_OFFERED)

TERMINAL_STATUSES = (STATUS_SCHEDULED, STATUS_REMOVED, STATUS_EXPIRED)

# Leaving one of these requires an explicit reason, because something automated
# put the entry there and a human is overriding it.
AUTOMATED_STATUSES = (STATUS_SCHEDULED, STATUS_EXPIRED)

# --- provider / location preference -----------------------------------------
# "Any" is stored as a positive value rather than inferred from a NULL foreign
# key. The plugin DDL pipeline emits no NOT NULL constraints, so a NULL column
# is ambiguous between "will see anyone" and "never filled in" — and reading
# NULL as "any" would make a malformed row match every open slot. Storing the
# intent explicitly means a malformed row matches nothing instead.
PREFERENCE_SPECIFIC = "specific"
PREFERENCE_ANY = "any"
PREFERENCES = (PREFERENCE_SPECIFIC, PREFERENCE_ANY)

# --- preferred time windows -------------------------------------------------
# Stored structured from day one so the optional matching filter can be turned
# on later without a data migration. Days use datetime.weekday(): 0 = Monday.
WEEKDAY_MIN = 0
WEEKDAY_MAX = 6

# --- config defaults --------------------------------------------------------
DEFAULT_PRIORITY_LABELS = ("High", "Medium", "Low")
DEFAULT_MAX_MATCHES_PER_TASK = 10
DEFAULT_MIN_LEAD_TIME_HOURS = 2
DEFAULT_URGENT_LEAD_HOURS = 48
DEFAULT_DISPLAY_TIMEZONE = "UTC"
DEFAULT_ENFORCE_TIME_WINDOWS = False

# --- chart banner -----------------------------------------------------------
# One stable key per patient, so re-emitting the banner replaces it rather than
# stacking a second copy on the chart.
BANNER_KEY = "scheduling_waitlist"
# Enforced by the SDK effect, which raises above this length.
BANNER_NARRATIVE_MAX = 90

# --- action button labels ----------------------------------------------------
# One vocabulary for both waitlist buttons. A chart header truncates at roughly
# twelve characters, which "Add to waitlist" never fitted -- it was rendering as
# "Add to wai…" long before anyone noticed, and beside a second button reading
# "Waitlist: a…" the two became impossible to tell apart.
#
# "On waitlist" is eleven and always fitted, so it stays as it is: reviewers
# named it as the thing they liked. Only the action label is shortened, and to a
# word that differs from the first character rather than the last -- "Waitlist"
# against "Waitlisted" would be two labels distinguished by their tails, which is
# the part truncation takes.
BUTTON_ADD_TITLE = "Waitlist"
BUTTON_LISTED_TITLE = "On waitlist"

# --- action button appearance -----------------------------------------------
# Each waitlist button does two jobs: it is an action ("Waitlist") when the
# patient is not listed, and a statement of fact ("Waitlisted") when they are.
# Drawn identically, the second reads as an action too -- reviewers reported the
# button as confusing for exactly that reason. Filling it only in the listed
# state makes the plain button mean "there is something to do here".
#
# Exactly seven characters each: the SDK's ShowButtonEffect validates the field
# as #RRGGBB and refuses colour names, three-digit shorthand and rgba().
LISTED_BUTTON_BACKGROUND = "#0b7285"
LISTED_BUTTON_TEXT = "#ffffff"

# --- patient search ---------------------------------------------------------
# Short enough that a two-letter surname still works, long enough that a single
# keystroke does not scan the whole patient table.
MIN_PATIENT_SEARCH_LENGTH = 2
MAX_PATIENT_SEARCH_RESULTS = 20

# --- field limits -----------------------------------------------------------
MAX_NOTE_LENGTH = 500
MAX_REASON_LENGTH = 200
MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 100

# --- next appointment -------------------------------------------------------
# How far back the roster looks for a visit the patient has already attended.
# The point of showing one is "this row may be stale", and a visit from last
# spring says nothing about a request made last week. It also bounds the query:
# without it, one roster page would read every appointment every waiting patient
# has ever had.
RECENT_VISIT_WINDOW_DAYS = 90

# --- housekeeping -----------------------------------------------------------
SLOT_NOTIFICATION_RETENTION_DAYS = 90
# Tasks closed per nightly run. A slot-opened task is dead work once its slot has
# started, and nothing else closes it, so the queue would otherwise grow without
# limit. Capped because each one is an effect.
MAX_TASKS_CLOSED_PER_RUN = 200
MAX_ENTRIES_EXPIRED_PER_RUN = 2000
# Refreshing a banner costs a query per patient, so the nightly sweep refreshes
# at most this many and logs the rest as skipped. A stale banner is corrected by
# the next write to that patient's entries, or by the following run.
MAX_BANNER_REFRESH_PER_RUN = 200
