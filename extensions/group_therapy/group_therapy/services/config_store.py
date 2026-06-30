"""Load / save / seed the group therapy templates config (custom_data).

The config is one JSON document in a single GroupTherapyConfig row. On first
load (no row yet) it is seeded with a single portable Group Therapy template,
then persisted, so the admin page opens populated rather than blank.
"""

import json

from logger import log

from group_therapy.models import GroupTherapyConfig

_CONFIG_KEY = "active"
# Per-participant is the clinical norm for group therapy (CPT 90853 is billed
# for each patient's attendance); admins can switch to single-claim "group"
# billing in Setup if their payer model needs it.
_DEFAULT_BILLING_MODE = "per_participant"
_GROUP_RFV = ["Group_Therapy"]
_GROUP_CPT = "90853"

# Portable, code-free seed: a single Group Therapy template whose structured
# sections are free text / multiple-choice / diagnosis / billing - no
# instance-specific questionnaire or exam codes. An admin can add templates, map
# sections to this instance's questionnaire codes, or change RFV/CPT in the Setup
# page after install.
_GROUP_THERAPY_SECTIONS = [
    {"label": "How session was conducted", "scope": "shared", "type": "options",
     "multi": False, "choices": ["In person", "Virtual", "Hybrid"]},
    {"label": "Group name", "scope": "shared", "type": "free_text"},
    {"label": "Session topic / theme", "scope": "shared", "type": "free_text"},
    {"label": "Therapeutic interventions", "scope": "shared", "type": "free_text"},
    {"label": "Group dynamic and process", "scope": "shared", "type": "options", "multi": True,
     "choices": ["Engaged", "Collaborative", "Supportive", "Guarded", "Hesitant", "Passive"]},
    {"label": "Patient participation level", "scope": "per_patient", "type": "options", "multi": True,
     "choices": ["Engaged", "Moderate", "Withdrawn", "Disruptive"]},
    {"label": "Patient contribution", "scope": "per_patient", "type": "free_text"},
    {"label": "Intervention and response", "scope": "per_patient", "type": "free_text"},
    {"label": "Risk assessment", "scope": "per_patient", "type": "free_text"},
    {"label": "Assessment", "scope": "per_patient", "type": "free_text"},
    {"label": "Diagnosis", "scope": "per_patient", "type": "diagnosis"},
    {"label": "Plan", "scope": "per_patient", "type": "free_text"},
    {"label": "Billing", "scope": "per_patient", "type": "billing"},
]


def _default_document() -> dict:
    """Build the seed config (literal defaults; the admin owns these after seed)."""
    return {
        "billing_mode": _DEFAULT_BILLING_MODE,
        "templates": [
            {
                "name": "Group Therapy",
                "rfv_codes": list(_GROUP_RFV),
                "cpt_code": _GROUP_CPT,
                "sections": [dict(s) for s in _GROUP_THERAPY_SECTIONS],
            },
        ],
    }


def load_config() -> dict:
    """Return the stored config, or the default (pre-admin) templates when none
    exists or custom_data is unavailable.

    Never raises - documentation must keep working with the default templates even
    if the config row, table, or namespace is not set up. Broad catch is
    deliberate: any failure to read config degrades to the defaults rather than
    breaking the documentation flow.
    """
    try:
        row = GroupTherapyConfig.objects.filter(key=_CONFIG_KEY).first()
        if row and row.payload:
            return json.loads(row.payload)
    except Exception as exc:  # missing namespace/table or bad payload -> defaults
        log.warning(f"group_therapy config load failed, using defaults: {exc}")
    doc = _default_document()
    save_config(doc)  # best-effort seed; never raises
    return doc


def group_rfv_codes(doc: dict) -> list:
    """All RFV codes across the configured templates - drives session discovery."""
    codes = []
    for t in doc.get("templates", []):
        for c in t.get("rfv_codes", []):
            if c and c not in codes:
                codes.append(c)
    return codes


def billing_cpt_codes(doc: dict) -> list:
    """Every CPT code configured across the templates (therapy + screening).

    The billing linker matches a note's billing line item against this set so it
    links the assessment regardless of which template's CPT (e.g. 90853 therapy
    vs 90832 screening) was billed.
    """
    codes = []
    for t in doc.get("templates", []):
        c = t.get("cpt_code")
        if c and c not in codes:
            codes.append(c)
    return codes


def save_config(doc: dict) -> bool:
    """Persist the config document; return False (best-effort) if custom_data is
    unavailable. Broad catch is deliberate - a missing namespace/table must not
    crash the request; the caller decides how to report it."""
    try:
        row = GroupTherapyConfig.objects.filter(key=_CONFIG_KEY).first()
        if row:
            row.payload = json.dumps(doc)
            row.save()
        else:
            GroupTherapyConfig.objects.create(key=_CONFIG_KEY, payload=json.dumps(doc))
        return True
    except Exception as exc:  # custom_data namespace/table not ready
        log.warning(f"group_therapy config save failed (custom_data unavailable?): {exc}")
        return False


def template_for_codes(doc: dict, codes: list) -> dict | None:
    """Return the first template whose rfv_codes intersect the session's codes."""
    wanted = {c for c in (codes or []) if c}
    for template in doc.get("templates", []):
        if wanted & {c for c in template.get("rfv_codes", []) if c}:
            return template
    return None
