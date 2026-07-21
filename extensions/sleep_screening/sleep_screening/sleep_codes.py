"""Curated common sleep-medicine ICD-10 codes offered in the diagnosis picker.

The default list ships with the plugin. An instance may override it via the
`SLEEP_DX_CODES` secret, a JSON array of {"code": ..., "display": ...} objects.
Screen-driven codes are pre-checked in the UI (see PRESELECT_BY_INSTRUMENT); the
provider can select any code from the menu. All selected codes are staged as
DiagnoseCommands for clinician review, never auto-committed.
"""

from json import loads

from logger import log

# Provisional / symptom / unspecified codes are used for screen-positive results;
# confirmed-disorder codes (e.g. G47.33) are offered but not pre-selected, since
# ICD-10-CM outpatient rules forbid coding a suspected condition as confirmed.
DEFAULT_CODES = [
    {"code": "G47.30", "display": "Sleep apnea, unspecified"},
    {"code": "G47.33", "display": "Obstructive sleep apnea (adult) (pediatric)"},
    {"code": "G47.31", "display": "Primary central sleep apnea"},
    {"code": "R06.83", "display": "Snoring"},
    {"code": "R40.0", "display": "Somnolence"},
    {"code": "G47.00", "display": "Insomnia, unspecified"},
    {"code": "G47.01", "display": "Insomnia due to medical condition"},
    {"code": "F51.01", "display": "Primary insomnia"},
    {"code": "G47.10", "display": "Hypersomnia, unspecified"},
    {"code": "G47.9", "display": "Sleep disorder, unspecified"},
]

# Instrument code -> provisional ICD-10 codes pre-checked when that screen is positive.
PRESELECT_BY_INSTRUMENT = {
    "SLEEP_STOPBANG": ["R06.83", "G47.30"],
    "SLEEP_ESS": ["R40.0"],
    "SLEEP_ISI": ["G47.00"],
}


def load_codes(secrets: dict) -> list[dict]:
    """Return the code menu: the secret override if valid, else the default list.

    Fails safe: any parse/shape problem logs and falls back to DEFAULT_CODES."""
    raw = secrets.get("SLEEP_DX_CODES", "") if secrets else ""
    if not raw:
        return DEFAULT_CODES
    try:
        parsed = loads(raw)
    except (ValueError, TypeError) as exc:
        log.info("sleep_screening: SLEEP_DX_CODES not valid JSON, using defaults: " + str(exc))
        return DEFAULT_CODES
    if not isinstance(parsed, list):
        log.info("sleep_screening: SLEEP_DX_CODES is not a list, using defaults")
        return DEFAULT_CODES
    codes = []
    for item in parsed:
        if isinstance(item, dict) and item.get("code") and item.get("display"):
            codes.append({"code": str(item["code"]), "display": str(item["display"])})
    return codes if codes else DEFAULT_CODES


def preselect_for(instrument_code: str) -> list[str]:
    return PRESELECT_BY_INSTRUMENT.get(instrument_code, [])
