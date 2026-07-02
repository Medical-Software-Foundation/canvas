"""Local-dev fallback values for plugin secrets — TEMPLATE.

Copy this file to `secrets_local.py` and fill in real values to avoid
passing --secret flags on every `canvas install`.

`secrets_local.py` is gitignored — NEVER commit real credentials.

Lookup precedence (see settings.py):
    1. Canvas-supplied `self.secrets` (production).
    2. Values defined here.
"""

LKCAREEVOLVE_BASE_URL = "https://example-lkcareevolve.invalid"
LKCAREEVOLVE_API_KEY = "replace-with-ellkay-issued-basic-credential"
VANTA_LAB_PARTNER_NAME = "Vanta Diagnostics"
LOCATION_TO_ACCOUNT_MAP_JSON = (
    '{"00000000-0000-0000-0000-000000000000": "ACCT-001"}'
)
SENDING_FACILITY_NAME = "Your Facility Name"
