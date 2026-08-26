"""Names, URLs and limits shared across the plugin.

Deliberately free of imports from the rest of the package so any module can
depend on it without creating a cycle.
"""

from urllib.parse import quote

from patient_resources import CACHE_BUST

PLUGIN_NAME = "patient_resources"

# Must match the installed directory name. The plugin runner derives a plugin's
# name from the folder it was installed from (`name = path.name`) and, for
# SimpleAPI events, keeps only handlers whose plugin name matches the name in the
# URL -- returning 404 when that leaves none. Installing the container directory
# `patient-resources/` instead of `patient_resources/` therefore 404s every route
# while the manifest still validates. That is the failure that made the
# order-sets plugin look unfixable.
API_BASE = f"/plugin-io/api/{PLUGIN_NAME}"

# Absolute, not relative. A relative "library.css" resolves against whether the
# page URL happened to end in a slash, which is a silent 404 waiting to happen.
STAFF_ASSET_BASE = f"{API_BASE}/app"
PORTAL_ASSET_BASE = f"{API_BASE}/portal"

LIBRARY_URL = f"{STAFF_ASSET_BASE}/?v={CACHE_BUST}"
PORTAL_URL = f"{PORTAL_ASSET_BASE}/?v={CACHE_BUST}"


def picker_url(patient_id: str) -> str:
    """Build the chart-picker URL for one patient.

    The patient key is the only thing carried in the URL -- no name, nothing
    else identifiable in the document -- and it is percent-encoded rather than
    interpolated raw.
    """
    return f"{STAFF_ASSET_BASE}/picker?patient={quote(patient_id, safe='')}&v={CACHE_BUST}"


# --- Resource lifecycle -----------------------------------------------------
# Plain strings rather than a Django `choices` list: the plugin DDL pipeline maps
# every text column to `text` regardless of choices, so choices would suggest an
# enforcement that does not exist. Validation lives in the service layer.
STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"
RESOURCE_STATUSES = (STATUS_ACTIVE, STATUS_ARCHIVED)

# The single list of what an admin may change on an existing resource. Pinned to
# the assignments in services/catalog.py by a test: the RestrictedPython sandbox
# blocks setattr, so the fields cannot be applied in a loop and the two places
# can silently drift.
EDITABLE_FIELDS = ("title", "url", "label", "default_note")

# --- Admin gating ----------------------------------------------------------
# StaffRole.domain values. A closed three-value vocabulary that means the same
# thing on every instance, unlike instance-specific role internal_codes -- which
# is what makes a shipped default meaningful here.
ROLE_DOMAIN_ADMINISTRATIVE = "ADM"
ROLE_DOMAIN_CLINICAL = "CLI"
ROLE_DOMAIN_HYBRID = "HYB"
KNOWN_ROLE_DOMAINS = (
    ROLE_DOMAIN_ADMINISTRATIVE,
    ROLE_DOMAIN_CLINICAL,
    ROLE_DOMAIN_HYBRID,
)
DEFAULT_ADMIN_ROLE_DOMAINS = (ROLE_DOMAIN_ADMINISTRATIVE,)

# Set the admin-role-domains variable to this to switch curation off for
# everybody. Needed because the platform delivers an unset variable as an
# empty string, so blank cannot mean "off" without breaking fresh installs.
DISABLE_SENTINEL = "NONE"

SECRET_ADMIN_ROLE_DOMAINS = "PATIENT_RESOURCES_ADMIN_ROLE_DOMAINS"
SECRET_ADMIN_STAFF_IDS = "PATIENT_RESOURCES_ADMIN_STAFF_IDS"

# --- Session ---------------------------------------------------------------
# Canvas strips these headers if a client sends them and sets them only for a
# live session, so they are the only trustworthy identity in the request.
# `canvas-logged-in-user-id` means a Staff key on a staff route and a Patient key
# on a portal route; the type header is the discriminator.
SESSION_ID_HEADER = "canvas-logged-in-user-id"
SESSION_TYPE_HEADER = "canvas-logged-in-user-type"
SESSION_TYPE_STAFF = "Staff"
SESSION_TYPE_PATIENT = "Patient"

# --- Limits ----------------------------------------------------------------
TITLE_MAX_CHARS = 200
URL_MAX_CHARS = 2000
LABEL_MAX_CHARS = 100

# The patient-facing note. Long enough for a few sentences of instruction --
# "read the section on evening doses before Thursday" -- and short enough that
# the portal card stays a card. One limit for both the library default and the
# per-patient copy, because the picker starts from the default and the two must
# not disagree about what fits.
NOTE_MAX_CHARS = 1000

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
MIN_SEARCH_LENGTH = 2

# Enforced in the API, not just the UI: a direct API client bypasses the picker.
MAX_SHARE_BATCH = 25
PORTAL_MAX_RESOURCES = 200

# --- Link safety -----------------------------------------------------------
ALLOWED_URL_SCHEMES = ("http", "https")
