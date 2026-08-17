"""Shared constants: entry statuses, match preferences, and config defaults.

Statuses and priority labels come from the plugin specification. They are plain
strings rather than ``CharField(choices=...)`` because the plugin DDL pipeline
maps every text column to ``text`` regardless of choices, so the enum would not
be enforced at the database level anyway. Validation happens in
``services/transitions.py``.
"""

from scheduling_waitlist import CACHE_BUST

PLUGIN_NAME = "scheduling_waitlist"
API_BASE = f"/plugin-io/api/{PLUGIN_NAME}"

# The roster page. Lives here rather than in the application module so the chart
# banner can link to it without services importing from applications.
ROSTER_URL = f"{API_BASE}/app/?v={CACHE_BUST}"

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

# --- housekeeping -----------------------------------------------------------
SLOT_NOTIFICATION_RETENTION_DAYS = 90
MAX_ENTRIES_EXPIRED_PER_RUN = 2000
# Refreshing a banner costs a query per patient, so the nightly sweep refreshes
# at most this many and logs the rest as skipped. A stale banner is corrected by
# the next write to that patient's entries, or by the following run.
MAX_BANNER_REFRESH_PER_RUN = 200
