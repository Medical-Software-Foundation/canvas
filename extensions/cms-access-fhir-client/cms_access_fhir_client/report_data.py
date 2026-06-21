"""Builders for the ACCESS ``$report-data`` document Bundle (IG/OM v0.9.11).

$report-data submits an ``ACCESSDataReportingBundle`` (a FHIR ``document`` Bundle)
whose first entry is an ``ACCESSDataReportingComposition``. The Composition has a
single top-level track section (keyed by ACCESSTrackCS) whose subsections carry the
required data elements, each referencing a resource in the bundle:

- **CKM / eCKM** — subsections are LOINC-coded clinical measures, each referencing an
  ``Observation`` (structured vitals + labs from Canvas Observations).
- **MSK / BH** — subsections are PROM instruments, each referencing a
  ``QuestionnaireResponse`` built from a Canvas ``Interview``. Instrument section codes
  follow the OM v0.9.11 Composition examples (LOINC where one exists, otherwise the
  ACCESSReportDataCompositionSectionCS code, e.g. ``WHODAS`` / ``PGIC`` / ``QuickDASH``).

Per OM v0.9.11 the server returns ``incomplete-data`` (with an OperationOutcome naming
the missing element) if a required element is absent, so a submission with only the data
available in Canvas is still a valid, informative test. The top-level track section is
always emitted (a missing track section is a 400); individual subsections are emitted
only when the underlying Observation/QuestionnaireResponse is available.

NOTE: most MSK instruments (and BH's WHODAS/PGIC) are copyrighted PROMs that CMS does not
ship — the participant must build/license them as Canvas Questionnaires. This module
defines the full required instrument set per the OM so each populates automatically once
the matching Canvas Questionnaire exists and a patient completes it.
"""

_BUNDLE_ID_SYSTEM = "https://www.canvasmedical.com/access/data-bundle-id"
_SD = "https://dsacms.github.io/cmmi-access-model/StructureDefinition"
_TRACK_CS = "https://dsacms.github.io/cmmi-access-model/CodeSystem/ACCESSTrackCS"
_LOINC = "http://loinc.org"
_US_CORE = "http://hl7.org/fhir/us/core/StructureDefinition"
_OBS_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"
_UCUM = "http://unitsofmeasure.org"

BUNDLE_PROFILE = f"{_SD}/access-data-reporting-bundle"
COMPOSITION_PROFILE = f"{_SD}/access-data-reporting-composition"
_PATIENT_PROFILE = f"{_US_CORE}/us-core-patient|6.1.0"
_PRACTITIONER_PROFILE = f"{_US_CORE}/us-core-practitioner|6.1.0"
_ORGANIZATION_PROFILE = f"{_US_CORE}/us-core-organization|6.1.0"

# Composition document type (OM uses LOINC 74465-6 "Questionnaire response Document").
_COMPOSITION_TYPE = {"coding": [{"system": _LOINC, "code": "74465-6", "display": "Questionnaire response Document"}]}

# ACCESS section CodeSystem — identifies instruments CMS reports without a LOINC.
_SECTION_CS = "https://dsacms.github.io/cmmi-access-model/CodeSystem/ACCESSReportDataCompositionSectionCS"
_QR_PROFILE = f"{_US_CORE}/us-core-questionnaireresponse|6.1.0"
# US Core QuestionnaireResponse requires a `questionnaire` canonical. We don't have the
# patient's source Questionnaire URL, so use a stable per-instrument canonical (the OM
# examples likewise use placeholder Questionnaire canonicals).
_QUESTIONNAIRE_CANONICAL_BASE = "https://www.canvasmedical.com/access/Questionnaire"
_ORDINAL_EXT = "http://hl7.org/fhir/StructureDefinition/ordinalValue"

# Required measures per track: (loinc, title, us-core profile, category, ucum_unit).
# eCKM == CKM minus eGFR + uACR (OM "Track-Specific Sections").
_CKM_MEASURES = [
    ("85354-9", "Blood Pressure", f"{_US_CORE}/us-core-blood-pressure|6.1.0", "vital-signs", "mm[Hg]"),
    ("29463-7", "Body Weight", f"{_US_CORE}/us-core-body-weight|6.1.0", "vital-signs", "kg"),
    ("39156-5", "BMI", f"{_US_CORE}/us-core-bmi|6.1.0", "vital-signs", "kg/m2"),
    ("8280-0", "Waist Circumference", f"{_US_CORE}/us-core-simple-observation|6.1.0", "vital-signs", "cm"),
    ("4548-4", "HbA1c", f"{_US_CORE}/us-core-observation-clinical-result|6.1.0", "laboratory", "%"),
    ("98979-8", "eGFR", f"{_US_CORE}/us-core-observation-clinical-result|6.1.0", "laboratory", "mL/min/{1.73_m2}"),
    ("14959-1", "uACR", f"{_US_CORE}/us-core-observation-clinical-result|6.1.0", "laboratory", "mg/g"),
    ("18262-6", "LDL Cholesterol", f"{_US_CORE}/us-core-observation-clinical-result|6.1.0", "laboratory", "mg/dL"),
]
_ECKM_MEASURES = [m for m in _CKM_MEASURES if m[0] not in ("98979-8", "14959-1")]

TRACK_MEASURES = {"CKM": _CKM_MEASURES, "eCKM": _ECKM_MEASURES}
# BP components: systolic / diastolic LOINC.
_BP_COMPONENTS = [("8480-6", "Systolic blood pressure"), ("8462-4", "Diastolic blood pressure")]

# PROM instruments per questionnaire-based track, from the OM v0.9.11 Composition examples
# (MSK p.97-101, BH p.149-151). Each tuple:
#   (section_code, section_system, title, lookup_code)
# section_code/system identify the subsection (LOINC, or ACCESSReportDataCompositionSectionCS
# for instruments CMS has no LOINC for). lookup_code is the LOINC used to find the matching
# Canvas Questionnaire; None means CMS uses an ACCESS code with no LOINC equivalent, so there
# is no automatic Canvas lookup (the questionnaire must be coded to be discoverable).
_BH_INSTRUMENTS = [
    ("44249-1", _LOINC, "Depression (PHQ-9)", "44249-1"),
    ("69737-5", _LOINC, "Anxiety (GAD-7)", "69737-5"),
    ("WHODAS", _SECTION_CS, "Overall Function (WHODAS 2.0)", None),
    ("PGIC", _SECTION_CS, "Patient's Global Impression of Change", None),
]
_MSK_INSTRUMENTS = [
    ("76804-4", _LOINC, "PROMIS Physical Function Short Form 6b", "76804-4"),
    ("91722-9", _LOINC, "PROMIS Physical Function CAT", "91722-9"),
    ("90973-9", _LOINC, "PROMIS Pain Interference Short Form 6a", "90973-9"),
    ("89923-7", _LOINC, "PROMIS Pain Interference CAT", "89923-7"),
    ("97908-8", _LOINC, "Oswestry Disability Index", "97908-8"),
    ("82226-2", _LOINC, "Neck Disability Index", "82226-2"),
    ("82324-5", _LOINC, "KOOS JR", "82324-5"),
    ("82316-1", _LOINC, "HOOS JR", "82316-1"),
    ("72514-3", _LOINC, "PROMIS Pain Intensity NRS", "72514-3"),
    ("QuickDASH", _SECTION_CS, "QuickDASH", None),
    ("PGIC", _SECTION_CS, "Patient's Global Impression of Change", None),
]
TRACK_INSTRUMENTS = {"BH": _BH_INSTRUMENTS, "MSK": _MSK_INSTRUMENTS}

OBSERVATION_TRACKS = set(TRACK_MEASURES)        # CKM, eCKM — Observation-based
QUESTIONNAIRE_TRACKS = set(TRACK_INSTRUMENTS)   # BH, MSK — QuestionnaireResponse-based

# reportType code → display.
REPORT_TYPE_DISPLAY = {
    "baseline": "Baseline Data Report",
    "quarterly": "Quarterly Data Report",
    "end-of-period": "End-of-Period Data Report",
}


def supported_track(track: str) -> bool:
    """True if $report-data is implemented for this track (all four ACCESS tracks)."""
    return track in OBSERVATION_TRACKS or track in QUESTIONNAIRE_TRACKS


def is_questionnaire_track(track: str) -> bool:
    """True if the track reports PROM QuestionnaireResponses (MSK/BH) rather than Observations."""
    return track in QUESTIONNAIRE_TRACKS


def _narrative(text: str) -> dict:
    return {"status": "generated", "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{text}</div>'}


def _observation_resource(
    obs_id: str, measure: tuple, value: dict, patient_ref: str, effective: str
) -> dict:
    """Build a US Core Observation for one measure.

    ``value`` is either {"components": {"8480-6": 120, "8462-4": 80}} for BP, or
    {"value": <num>, "unit": <ucum>} for a single quantity.
    """
    code, title, profile, category, default_unit = measure
    obs = {
        "resourceType": "Observation",
        "meta": {"profile": [profile]},
        "text": _narrative(title),
        "status": "final",
        "category": [{"coding": [{"system": _OBS_CATEGORY_SYSTEM, "code": category}]}],
        "code": {"coding": [{"system": _LOINC, "code": code, "display": title}]},
        "subject": {"reference": patient_ref},
        "effectiveDateTime": effective,
    }
    components = value.get("components")
    if components:
        obs["component"] = [
            {
                "code": {"coding": [{"system": _LOINC, "code": c_code, "display": c_title}]},
                "valueQuantity": {
                    "value": components[c_code],
                    "unit": default_unit,
                    "system": _UCUM,
                    "code": default_unit,
                },
            }
            for c_code, c_title in _BP_COMPONENTS
            if c_code in components
        ]
    else:
        unit = value.get("unit") or default_unit
        obs["valueQuantity"] = {
            "value": value["value"],
            "unit": unit,
            "system": _UCUM,
            "code": unit,
        }
    return obs


def _questionnaire_response_resource(
    qr_id: str, instrument: tuple, response: dict, patient_ref: str, authored: str
) -> dict:
    """Build a US Core QuestionnaireResponse for one PROM instrument.

    ``response`` carries the gathered Canvas Interview data:
      {"questionnaire": <canonical|None>, "narrative": <str>, "authored": <iso>,
       "items": [{"linkId", "text", "answer_code"/"answer_system"/"answer_display"/
                  "ordinal", or "answer_text"}]}
    """
    _code, _system, title, _lookup = instrument
    qr = {
        "resourceType": "QuestionnaireResponse",
        "id": qr_id,
        "meta": {"profile": [_QR_PROFILE]},
        "text": _narrative(response.get("narrative") or title),
        "status": "completed",
        "subject": {"reference": patient_ref},
        "authored": response.get("authored") or authored,
        "author": {"reference": patient_ref},
        # Required by US Core QuestionnaireResponse — always present.
        "questionnaire": response.get("questionnaire") or f"{_QUESTIONNAIRE_CANONICAL_BASE}/{_code}",
    }
    items = []
    for raw in response.get("items", []):
        item: dict = {"linkId": raw.get("linkId") or "item"}
        if raw.get("text"):
            item["text"] = raw["text"]
        if raw.get("answer_code"):
            coding = {"system": raw.get("answer_system") or _LOINC, "code": raw["answer_code"]}
            if raw.get("answer_display"):
                coding["display"] = raw["answer_display"]
            if raw.get("ordinal") is not None:
                coding["extension"] = [{"url": _ORDINAL_EXT, "valueDecimal": raw["ordinal"]}]
            item["answer"] = [{"valueCoding": coding}]
        elif raw.get("answer_text") is not None:
            item["answer"] = [{"valueString": raw["answer_text"]}]
        items.append(item)
    if items:
        qr["item"] = items
    return qr


def _questionnaire_resource(q_id: str, instrument: tuple, response: dict, canonical: str) -> dict:
    """Minimal Questionnaire embedded in the bundle so the QR's `questionnaire` canonical
    resolves within the document (CMS rejects an unresolvable canonical). Items mirror the
    QR's linkIds/answers so QR↔Questionnaire validation stays consistent.
    """
    _code, _system, title, _lookup = instrument
    items = []
    for raw in response.get("items", []):
        link = raw.get("linkId") or "item"
        text = raw.get("text") or link
        if raw.get("answer_code"):
            coding = {"system": raw.get("answer_system") or _LOINC, "code": raw["answer_code"]}
            if raw.get("answer_display"):
                coding["display"] = raw["answer_display"]
            items.append({"linkId": link, "text": text, "type": "choice", "answerOption": [{"valueCoding": coding}]})
        else:
            items.append({"linkId": link, "text": text, "type": "string"})
    q = {
        "resourceType": "Questionnaire",
        "id": q_id,
        "url": canonical,
        "status": "active",
        "name": "ACCESS" + "".join(ch for ch in _code if ch.isalnum()),
        "title": title,
    }
    if items:
        q["item"] = items
    return q


def build_data_bundle(
    *,
    track: str,
    patient_resource: dict,
    practitioner: dict,
    organization: dict,
    measures: dict | None = None,
    responses: dict | None = None,
    bundle_id: str,
    timestamp: str,
    base_url: str = "https://www.canvasmedical.com/access/fhir",
) -> dict:
    """Assemble the ACCESSDataReportingBundle (document Bundle).

    Observation tracks (CKM/eCKM) pass ``measures`` (measure LOINC → value dict).
    Questionnaire tracks (MSK/BH) pass ``responses`` (instrument section_code → response
    dict, see _questionnaire_response_resource). In both cases only the elements present
    get a resource + subsection; the rest are omitted (server reports incomplete-data).
    The top-level track section is always emitted.
    """
    measures = measures or {}
    responses = responses or {}
    base = base_url.rstrip("/")

    def _full(rtype: str, rid: str) -> str:
        return f"{base}/{rtype}/{rid}"

    # Use absolute fullUrls and make every Composition reference EXACTLY equal to the
    # referenced entry's fullUrl, so the bundle-internal references resolve unambiguously
    # (FHIR doc-Bundle constraint: all referenced resources must be in the Bundle).
    patient_ref = _full("Patient", patient_resource.get("id", "patient"))
    practitioner_ref = _full("Practitioner", practitioner.get("id", "practitioner"))
    organization_ref = _full("Organization", organization.get("id", "organization"))

    extra_resources: list[tuple[dict, str]] = []  # (resource, absolute fullUrl)
    subsections = []

    if track in QUESTIONNAIRE_TRACKS:
        for instrument in TRACK_INSTRUMENTS[track]:
            section_code, section_system, title, _lookup = instrument
            if section_code not in responses:
                continue
            resp_obj = responses[section_code]
            canonical = resp_obj.get("questionnaire") or f"{_QUESTIONNAIRE_CANONICAL_BASE}/{section_code}"
            resp_obj = dict(resp_obj, questionnaire=canonical)
            qr_id = f"qr-{section_code.replace('-', '').lower()}"
            q_id = f"q-{section_code.replace('-', '').lower()}"
            qr_full = _full("QuestionnaireResponse", qr_id)
            # Embed the Questionnaire (fullUrl == its canonical url) so the QR reference resolves.
            extra_resources.append((_questionnaire_resource(q_id, instrument, resp_obj, canonical), canonical))
            extra_resources.append(
                (_questionnaire_response_resource(qr_id, instrument, resp_obj, patient_ref, timestamp),
                 qr_full)
            )
            subsections.append(
                {
                    "title": title,
                    "code": {"coding": [{"system": section_system, "code": section_code, "display": title}]},
                    "text": _narrative(title),
                    "entry": [{"reference": qr_full}],
                }
            )
    else:
        for measure in TRACK_MEASURES[track]:
            code = measure[0]
            if code not in measures:
                continue
            obs_id = f"obs-{code.replace('-', '')}"
            obs_full = _full("Observation", obs_id)
            extra_resources.append(
                (_observation_resource(obs_id, measure, measures[code], patient_ref, timestamp),
                 obs_full)
            )
            subsections.append(
                {
                    "title": measure[1],
                    "code": {"coding": [{"system": _LOINC, "code": code, "display": measure[1]}]},
                    "text": _narrative(measure[1]),
                    "entry": [{"reference": obs_full}],
                }
            )

    composition = {
        "resourceType": "Composition",
        "meta": {"profile": [COMPOSITION_PROFILE]},
        "text": _narrative(f"ACCESS {track} data report"),
        "status": "final",
        "type": _COMPOSITION_TYPE,
        "subject": {"reference": patient_ref},
        "date": timestamp,
        "author": [{"reference": practitioner_ref}],
        "title": f"ACCESS {track} Track Data Report",
        "custodian": {"reference": organization_ref},
        "section": [
            {
                "title": f"Data reporting for {track} track",
                "code": {"coding": [{"system": _TRACK_CS, "code": track}]},
                "text": _narrative(f"{track} reporting"),
                "section": subsections,
            }
        ],
    }

    entries = [
        {"fullUrl": _full("Composition", "composition"), "resource": composition},
        {"fullUrl": patient_ref, "resource": patient_resource},
        {"fullUrl": practitioner_ref, "resource": practitioner},
        {"fullUrl": organization_ref, "resource": organization},
    ]
    for resource, full_url in extra_resources:
        entries.append({"fullUrl": full_url, "resource": resource})

    return {
        "resourceType": "Bundle",
        "meta": {"profile": [BUNDLE_PROFILE]},
        # FHIR bdl-9: a document Bundle's identifier MUST have both a system and a value.
        "identifier": {"system": _BUNDLE_ID_SYSTEM, "value": bundle_id},
        "type": "document",
        "timestamp": timestamp,
        "entry": entries,
    }


def build_practitioner(staff_id: str, first_name: str, last_name: str, npi: str | None) -> dict:
    """Minimal US Core Practitioner for the Composition author."""
    identifier = (
        [{"system": "http://hl7.org/fhir/sid/us-npi", "value": npi}]
        if npi
        else [{"system": "https://www.canvasmedical.com/staff", "value": staff_id or "unknown"}]
    )
    return {
        "resourceType": "Practitioner",
        "id": f"staff-{staff_id}" if staff_id else "practitioner",
        "meta": {"profile": [_PRACTITIONER_PROFILE]},
        "text": _narrative(f"{first_name} {last_name}".strip() or "Practitioner"),
        "identifier": identifier,
        "name": [{"family": last_name or "Unknown", "given": [first_name or "Unknown"]}],
    }


def build_organization(participant_id: str, name: str) -> dict:
    """Minimal US Core Organization for the Composition custodian."""
    return {
        "resourceType": "Organization",
        "id": f"org-{participant_id}",
        "meta": {"profile": [_ORGANIZATION_PROFILE]},
        "text": _narrative(name),
        "identifier": [{"system": "https://dsacms.github.io/cmmi-access-model/participant-id", "value": participant_id}],
        "active": True,
        "name": name,
    }
