"""Bundled catalog of common imaging studies for the Exam tab's Imaging
card dropdown.

Labels are verbatim copies of the chart's CPT-typeahead entries so the
chart can string-match each `image_code` back to its internal catalog
and render the staged Imaging command's `Image:` row cleanly. Format:

    "MODALITY, body part, view count, orientation; (CPT: NNNNN)"

with the semicolon immediately before "(CPT:" and a single space after.
When the entry includes a procedural qualifier (e.g. "with apical
lordotic procedure"), the qualifier follows the semicolon:

    "XRAY, chest, 2 views, frontal and lateral; with apical lordotic procedure (CPT: 71021)"

If a label here doesn't render on the chart, the chart's catalog
phrasing has drifted; update the catalog string to match what the
chart's own typeahead shows.
"""
from __future__ import annotations

from typing import TypedDict


class ImagingCode(TypedDict):
    code: str
    label: str


_CATALOG: list[ImagingCode] = [
    # ----- X-Ray: Chest -----
    {"code": "71045", "label": "XRAY, chest, 1 view; (CPT: 71045)"},
    {"code": "71046", "label": "XRAY, chest, 2 views, frontal and lateral; (CPT: 71046)"},
    {"code": "71047", "label": "XRAY, chest, 3 views; (CPT: 71047)"},
    {"code": "71048", "label": "XRAY, chest, 4 or more views; (CPT: 71048)"},
    # ----- X-Ray: Abdomen -----
    {"code": "74018", "label": "XRAY, abdomen, 1 view; (CPT: 74018)"},
    {"code": "74019", "label": "XRAY, abdomen, 2 views; (CPT: 74019)"},
    {"code": "74021", "label": "XRAY, abdomen, 3 or more views; (CPT: 74021)"},
    # ----- X-Ray: Spine -----
    {"code": "72040", "label": "XRAY, cervical spine, 2 or 3 views; (CPT: 72040)"},
    {"code": "72050", "label": "XRAY, cervical spine, 4 or 5 views; (CPT: 72050)"},
    {"code": "72100", "label": "XRAY, lumbar spine, 2 or 3 views; (CPT: 72100)"},
    {"code": "72110", "label": "XRAY, lumbar spine, minimum 4 views; (CPT: 72110)"},
    # ----- X-Ray: Extremities -----
    {"code": "73560", "label": "XRAY, knee, 1 or 2 views; (CPT: 73560)"},
    {"code": "73562", "label": "XRAY, knee, 3 views; (CPT: 73562)"},
    {"code": "73564", "label": "XRAY, knee, 4 or more views; (CPT: 73564)"},
    {"code": "73600", "label": "XRAY, ankle, 2 views; (CPT: 73600)"},
    {"code": "73610", "label": "XRAY, ankle, complete, minimum 3 views; (CPT: 73610)"},
    {"code": "73620", "label": "XRAY, foot, 2 views; (CPT: 73620)"},
    {"code": "73630", "label": "XRAY, foot, complete, minimum 3 views; (CPT: 73630)"},
    {"code": "73120", "label": "XRAY, hand, 2 views; (CPT: 73120)"},
    {"code": "73130", "label": "XRAY, hand, minimum 3 views; (CPT: 73130)"},
    {"code": "73030", "label": "XRAY, shoulder, complete, minimum 2 views; (CPT: 73030)"},
    # ----- CT -----
    {"code": "70450", "label": "CT, head or brain, without contrast; (CPT: 70450)"},
    {"code": "70460", "label": "CT, head or brain, with contrast; (CPT: 70460)"},
    {"code": "70470", "label": "CT, head or brain, without and with contrast; (CPT: 70470)"},
    {"code": "71250", "label": "CT, thorax, without contrast; (CPT: 71250)"},
    {"code": "71260", "label": "CT, thorax, with contrast; (CPT: 71260)"},
    {"code": "74150", "label": "CT, abdomen, without contrast; (CPT: 74150)"},
    {"code": "74160", "label": "CT, abdomen, with contrast; (CPT: 74160)"},
    {"code": "74176", "label": "CT, abdomen and pelvis, without contrast; (CPT: 74176)"},
    {"code": "74177", "label": "CT, abdomen and pelvis, with contrast; (CPT: 74177)"},
    # ----- MRI -----
    {"code": "70551", "label": "MRI, brain, without contrast; (CPT: 70551)"},
    {"code": "70552", "label": "MRI, brain, with contrast; (CPT: 70552)"},
    {"code": "70553", "label": "MRI, brain, without and with contrast; (CPT: 70553)"},
    {"code": "72141", "label": "MRI, cervical spine, without contrast; (CPT: 72141)"},
    {"code": "72148", "label": "MRI, lumbar spine, without contrast; (CPT: 72148)"},
    {"code": "73721", "label": "MRI, lower extremity joint, without contrast; (CPT: 73721)"},
    # ----- Ultrasound -----
    {"code": "76700", "label": "Ultrasound, abdomen, complete; (CPT: 76700)"},
    {"code": "76705", "label": "Ultrasound, abdomen, limited; (CPT: 76705)"},
    {"code": "76770", "label": "Ultrasound, retroperitoneal, complete; (CPT: 76770)"},
    {"code": "76830", "label": "Ultrasound, transvaginal; (CPT: 76830)"},
    {"code": "93880", "label": "Duplex scan, extracranial arteries, complete bilateral; (CPT: 93880)"},
    # ----- Other -----
    {"code": "77067", "label": "Screening mammography, bilateral; (CPT: 77067)"},
    {"code": "77066", "label": "Diagnostic mammography, bilateral; (CPT: 77066)"},
    {"code": "77080", "label": "DEXA, axial skeleton; (CPT: 77080)"},
    {"code": "93306", "label": "Echocardiography, transthoracic, complete with Doppler; (CPT: 93306)"},
]


def get_imaging_codes(secret_value: str | None = None) -> list[ImagingCode]:
    """Return the catalog the Imaging card's dropdown renders.

    When the `exam-imaging-codes` plugin secret is set, every non-empty
    line is treated as one catalog entry — the admin pastes strings
    copied directly from the chart's own CPT typeahead so each entry
    matches the chart's catalog character-for-character. Falls back to
    the bundled defaults (best-effort guesses) when the secret is unset.
    """
    if secret_value and secret_value.strip():
        labels = [
            line.strip() for line in secret_value.splitlines() if line.strip()
        ]
        return [{"code": "", "label": label} for label in labels]
    return list(_CATALOG)
