import json
from datetime import datetime, timezone
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates import render_to_string
from canvas_sdk.utils.http import ontologies_http
from canvas_sdk.v1.data.medication import Medication
from canvas_sdk.v1.data.medication_history import MedicationHistoryMedication
from canvas_sdk.v1.data.medication_statement import MedicationStatement  # noqa: F401
from canvas_sdk.v1.data.note import Note, NoteStates
from canvas_sdk.v1.data.patient import Patient

from rx_history.protocols.dismissal_store import get_dismissed_keys

from logger import log

# Stable per process lifetime. Rotates on redeploy when the module reloads.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

RXNORM_SYSTEM = "http://www.nlm.nih.gov/research/umls/rxnorm"
NDC_SYSTEM = "http://hl7.org/fhir/sid/ndc"

_OPEN_NOTE_STATES = [
    NoteStates.NEW,
    NoteStates.PUSHED,
    NoteStates.UNLOCKED,
    NoteStates.RESTORED,
    NoteStates.UNDELETED,
]


def _get_system_uri(system: Any) -> str:
    """Extract system URI string. Handles plain strings and {'uri': '...'} proxy objects."""
    s = str(system)
    if RXNORM_SYSTEM in s:
        return RXNORM_SYSTEM
    if NDC_SYSTEM in s:
        return NDC_SYSTEM
    return s


def _normalize_rxnorm(code: str | None) -> str:
    """Return just the numeric RxNorm CUI, stripping any trailing term type.

    Surescripts codings arrive as "1014571 SCD" or "1660196 SBD". The CUI is
    always the first whitespace separated token. Active medications coming
    from FDB carry the bare CUI. Normalize both sides to the CUI so exact
    match comparisons agree.
    """
    if not code:
        return ""
    token = code.strip().split()[0]
    return token if token.isdigit() else code


def _build_active_code_sets(
    active_meds: list,
) -> tuple[set[str], set[str], list[str]]:
    """Build RxNorm codes, NDC codes, and description list from active Canvas medications."""
    rxnorm_codes: set[str] = set()
    ndc_codes: set[str] = set()
    descriptions: list[str] = []

    for med in active_meds:
        for coding in med.codings.all():
            sys_uri = _get_system_uri(coding.system)
            if sys_uri == RXNORM_SYSTEM and coding.code:
                normalized = _normalize_rxnorm(coding.code)
                if normalized:
                    rxnorm_codes.add(normalized)
            elif sys_uri == NDC_SYSTEM and coding.code:
                ndc_codes.add("".join(c for c in coding.code if c.isdigit()))
            if coding.display and len(coding.display) > 10:
                descriptions.append(coding.display.lower())
        if med.national_drug_code:
            ndc_codes.add("".join(c for c in med.national_drug_code if c.isdigit()))
        if (
            med.clinical_quantity_description
            and len(med.clinical_quantity_description) > 10
        ):
            descriptions.append(med.clinical_quantity_description.lower())
        if (
            med.quantity_qualifier_description
            and len(med.quantity_qualifier_description) > 10
        ):
            descriptions.append(med.quantity_qualifier_description.lower())

    return rxnorm_codes, ndc_codes, descriptions


def _ndc_to_rxnorm(ndc_code: str) -> str:
    """Look up RxNorm code for an NDC via FDB. Returns empty string on failure."""
    try:
        resp = ontologies_http.get_json("/fdb/ndc-to-medication/%s/" % ndc_code)
        result = resp.json()
        if isinstance(result, dict):
            rxcui = result.get("rxnorm_rxcui", "") or ""
            return str(rxcui) if rxcui else ""
    except Exception:
        pass
    return ""


def _is_matched(
    history_med: MedicationHistoryMedication,
    active_rxnorm_codes: set[str],
    active_ndc_codes: set[str],
    active_descriptions: list[str],
) -> tuple:
    """Return (matched: bool, match_method: str) for a Surescripts medication."""
    for coding in history_med.codings.all():
        sys_uri = _get_system_uri(coding.system)
        if sys_uri == RXNORM_SYSTEM and coding.code:
            if _normalize_rxnorm(coding.code) in active_rxnorm_codes:
                return True, "rxnorm"
        if (
            sys_uri == NDC_SYSTEM
            and coding.code
            and "".join(c for c in coding.code if c.isdigit()) in active_ndc_codes
        ):
            return True, "ndc"

    drug_desc = history_med.drug_description.lower()
    if drug_desc:
        for desc in active_descriptions:
            if drug_desc in desc or desc in drug_desc:
                return True, "description"

    # NDC→RxNorm cross-reference: look up the Surescripts NDC in FDB to get its RxNorm
    for coding in history_med.codings.all():
        sys_uri = _get_system_uri(coding.system)
        if sys_uri == NDC_SYSTEM and coding.code:
            resolved_rxnorm = _ndc_to_rxnorm(coding.code)
            if resolved_rxnorm and resolved_rxnorm in active_rxnorm_codes:
                return True, "ndc_rxnorm_xref:%s->%s" % (coding.code, resolved_rxnorm)

    return False, ""


def _is_matched_layered(
    history_med: MedicationHistoryMedication,
    committed_rxnorm: set[str],
    committed_ndc: set[str],
    committed_desc: list[str],
    staged_rxnorm: set[str],
    staged_ndc: set[str],
    staged_desc: list[str],
) -> tuple:
    """Match against committed set first, then staged. Returns (matched, method, is_staged).

    Committed matches always win when both sets agree so the UI stays honest about
    what is finalized vs. what is still in an open note. The method string is the
    same shape the legacy single-source cascade produced, so existing downstream
    code keeps working.
    """
    matched, method = _is_matched(
        history_med, committed_rxnorm, committed_ndc, committed_desc
    )
    if matched:
        return True, method, False
    matched, method = _is_matched(
        history_med, staged_rxnorm, staged_ndc, staged_desc
    )
    if matched:
        return True, method, True
    return False, "", False


def _build_history_item(
    med: MedicationHistoryMedication,
    is_match: bool,
    match_method: str = "",
    is_staged: bool = False,
) -> dict[str, Any]:
    """Build a single history item dict from a MedicationHistoryMedication."""
    rxnorm_codes = []
    ndc_codes = []
    for c in med.codings.all():
        sys_uri = _get_system_uri(c.system)
        if sys_uri == RXNORM_SYSTEM and c.code:
            rxnorm_codes.append(c.code)
        elif sys_uri == NDC_SYSTEM and c.code:
            ndc_codes.append(c.code)

    return {
        "drug_description": med.drug_description,
        "strength": (
            "%s %s %s"
            % (med.strength_value, med.strength_unit_of_measure, med.strength_form)
        ).strip(),
        "last_fill_date": (
            med.last_fill_date.strftime("%b %d, %Y") if med.last_fill_date else ""
        ),
        "last_fill_date_sort": (
            med.last_fill_date.isoformat() if med.last_fill_date else ""
        ),
        "written_date": (
            med.written_date.strftime("%b %d, %Y") if med.written_date else ""
        ),
        "prescriber": (
            "%s %s" % (med.prescriber_first_name, med.prescriber_last_name)
        ).strip(),
        "pharmacy_name": med.pharmacy_name or "",
        "source_description": med.source_description or "",
        "source_type": med.source_type or "",
        "sig": med.sig,
        "is_match": is_match,
        "match_method": match_method,
        "is_staged": is_staged,
        "rxnorm_codes": rxnorm_codes,
        "ndc_codes": ndc_codes,
    }


def _get_group_key(item: dict[str, Any]) -> str:
    """Get grouping key. First NDC code if available, otherwise drug_description."""
    if item["ndc_codes"]:
        return "ndc:%s" % item["ndc_codes"][0]
    return "desc:%s" % item["drug_description"]


def _group_history_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group history items by NDC or drug_description. Claim descriptions preferred for header."""
    groups_dict: dict[str, dict[str, Any]] = {}
    group_order: list[str] = []

    for item in items:
        key = _get_group_key(item)
        is_claim = (
            item["source_type"].lower() == "claim" if item["source_type"] else False
        )

        if key not in groups_dict:
            groups_dict[key] = {
                "drug_description": item["drug_description"],
                "strength": item["strength"],
                "is_match": item["is_match"],
                "match_method": item.get("match_method", ""),
                "is_staged": item.get("is_staged", False),
                "rxnorm_codes": list(item["rxnorm_codes"]),
                "ndc_codes": list(item["ndc_codes"]),
                "sig": item["sig"],
                "latest_fill_date": item["last_fill_date"],
                "latest_fill_date_sort": item["last_fill_date_sort"],
                "has_claim_desc": is_claim,
                "fills": [],
            }
            group_order.append(key)

        group = groups_dict[key]

        if item["is_match"]:
            group["is_match"] = True
            if not group["match_method"]:
                group["match_method"] = item.get("match_method", "")
            # Committed always wins. A staged match only stands if no fill has
            # produced a committed match yet.
            if not item.get("is_staged", False):
                group["is_staged"] = False
            elif group.get("match_method", "") == item.get("match_method", ""):
                group["is_staged"] = True

        # Prefer claim description for the group header (better FDB match)
        if is_claim and not group["has_claim_desc"]:
            group["drug_description"] = item["drug_description"]
            group["strength"] = item["strength"]
            group["has_claim_desc"] = True

        # Capture sig from fill records (claims usually lack sig)
        if not is_claim and item["sig"] and not group["sig"]:
            group["sig"] = item["sig"]

        # Merge codes from all fills
        for code in item["rxnorm_codes"]:
            if code not in group["rxnorm_codes"]:
                group["rxnorm_codes"].append(code)
        for code in item["ndc_codes"]:
            if code not in group["ndc_codes"]:
                group["ndc_codes"].append(code)

        # Track latest fill date
        if item["last_fill_date_sort"] > group["latest_fill_date_sort"]:
            group["latest_fill_date"] = item["last_fill_date"]
            group["latest_fill_date_sort"] = item["last_fill_date_sort"]

        group["fills"].append(
            {
                "drug_description": item["drug_description"],
                "last_fill_date": item["last_fill_date"],
                "last_fill_date_sort": item["last_fill_date_sort"],
                "written_date": item["written_date"],
                "prescriber": item["prescriber"],
                "pharmacy_name": item["pharmacy_name"],
                "source_description": item["source_description"],
                "source_type": item["source_type"],
            }
        )

    # Compute unique fill count (claim+fill on same date = 1 fill)
    for key in group_order:
        g = groups_dict[key]
        seen_dates: set[str] = set()
        for fill in g["fills"]:
            if fill["last_fill_date_sort"]:
                seen_dates.add(fill["last_fill_date_sort"])
        g["unique_fill_count"] = len(seen_dates) if seen_dates else len(g["fills"])

    # Sort by latest fill date descending
    result = []
    for key in group_order:
        g = groups_dict[key]
        del g["has_claim_desc"]
        result.append(g)
    result.sort(key=lambda g: g["latest_fill_date_sort"], reverse=True)
    return result


def build_modal_context(patient: Patient) -> dict:
    """Build the rx history modal payload for both the server render and the
    JSON refresh endpoint. Single source of truth for the matching, grouping,
    and filtering logic that produces the groups the panel displays."""
    history_meds = list(
        MedicationHistoryMedication.objects.filter(patient=patient)
        .prefetch_related("codings")
        .order_by("-last_fill_date")[:100]
    )

    # Committed active medications. Authoritative set from the chart.
    active_meds = list(
        Medication.objects.active()
        .filter(patient=patient)
        .prefetch_related("codings")
    )

    # Staged medications. Stated in a currently-open note but not yet committed.
    # Notes discarded by the provider leave _OPEN_NOTE_STATES, so their meds
    # fall out of this set automatically and never become ghosts. We also drop
    # medications whose linking MedicationStatement was deleted or marked
    # entered_in_error, so removing a med from an open note un-matches it.
    staged_meds = list(
        Medication.objects.filter(
            patient=patient,
            status="active",
            deleted=False,
            entered_in_error_id__isnull=True,
            committer_id__isnull=True,
            medication_statements__note__current_state__state__in=_OPEN_NOTE_STATES,
            medication_statements__deleted=False,
            medication_statements__entered_in_error_id__isnull=True,
        )
        .prefetch_related("codings")
        .distinct()
    )

    (
        committed_rxnorm,
        committed_ndc,
        committed_desc,
    ) = _build_active_code_sets(active_meds)
    (
        staged_rxnorm,
        staged_ndc,
        staged_desc,
    ) = _build_active_code_sets(staged_meds)

    rxnorm_codes = committed_rxnorm | staged_rxnorm
    ndc_codes = committed_ndc | staged_ndc
    descriptions = committed_desc + staged_desc

    active_meds_summary = []
    for med in active_meds:
        med_desc = ""
        med_rxnorm = []
        med_ndc = []
        for coding in med.codings.all():
            sys_uri = _get_system_uri(coding.system)
            if coding.display and not med_desc:
                med_desc = coding.display
            if sys_uri == RXNORM_SYSTEM and coding.code:
                med_rxnorm.append(coding.code)
            elif sys_uri == NDC_SYSTEM and coding.code:
                med_ndc.append(coding.code)
        if med.national_drug_code and med.national_drug_code not in med_ndc:
            med_ndc.append(med.national_drug_code)
        active_meds_summary.append(
            {
                "description": med_desc or "Unknown",
                "rxnorm_codes": med_rxnorm,
                "ndc_codes": med_ndc,
            }
        )

    history_items = []
    for med in history_meds:
        is_match, match_method, is_staged = _is_matched_layered(
            med,
            committed_rxnorm,
            committed_ndc,
            committed_desc,
            staged_rxnorm,
            staged_ndc,
            staged_desc,
        )
        history_items.append(
            _build_history_item(med, is_match, match_method, is_staged)
        )

    grouped_items = _group_history_items(history_items)

    dismissed_items = []
    active_items = []
    patient_id = str(patient.id)
    dismissed_keys = get_dismissed_keys(patient_id)
    for group in grouped_items:
        key = (
            group["drug_description"],
            (group["ndc_codes"] or [""])[0] or "",
            group.get("latest_fill_date", "") or "",
        )
        if not group["is_match"] and key in dismissed_keys:
            dismissed_items.append(group)
        else:
            active_items.append(group)

    last_pulled_iso = ""
    if history_meds:
        latest_created = None
        for med in history_meds:
            if med.created and (
                latest_created is None or med.created > latest_created
            ):
                latest_created = med.created
        if latest_created:
            last_pulled_iso = latest_created.isoformat()

    open_notes = list(
        Note.objects.filter(patient=patient)
        .filter(current_state__state__in=_OPEN_NOTE_STATES)
        .select_related("note_type_version")
        .order_by("-datetime_of_service")
    )
    open_notes_list = []
    for note in open_notes:
        datetime_iso = (
            note.datetime_of_service.isoformat()
            if note.datetime_of_service
            else ""
        )
        type_name = ""
        if note.title:
            type_name = note.title
        elif note.note_type_version and note.note_type_version.name:
            type_name = note.note_type_version.name
        elif note.note_type:
            type_name = note.note_type.replace("_", " ").title()
        open_notes_list.append(
            {
                "id": str(note.id),
                "datetime_iso": datetime_iso,
                "type_name": type_name,
            }
        )

    return {
        "grouped_items": active_items,
        "dismissed_items": dismissed_items,
        "dismissed_count": len(dismissed_items),
        "active_rxnorm": list(rxnorm_codes),
        "active_ndc": list(ndc_codes),
        "active_descriptions": descriptions,
        "active_meds": active_meds_summary,
        "open_notes": open_notes_list,
        "last_pulled_iso": last_pulled_iso,
    }


class MedHistoryActionButton(ActionButton):
    """Action button in the chart medications section that opens the medication history modal."""

    BUTTON_TITLE = "Rx History"
    BUTTON_KEY = "med_history_action"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_SUMMARY_MEDICATIONS_SECTION

    def handle(self) -> list[Effect]:
        patient_id = self.event.target.id
        if not patient_id:
            log.warning("MedHistoryActionButton: no patient_id in event target")
            return []

        try:
            patient = Patient.objects.select_related("default_provider").get(
                id=patient_id
            )
        except Patient.DoesNotExist:
            log.warning("MedHistoryActionButton: patient %s not found" % patient_id)
            return []

        has_default_provider = patient.default_provider is not None
        ctx = build_modal_context(patient)

        html = render_to_string(
            "templates/med_history.html",
            {
                "has_default_provider": has_default_provider,
                "patient_id": patient_id,
                "grouped_items_json": json.dumps(ctx["grouped_items"]),
                "dismissed_items_json": json.dumps(ctx["dismissed_items"]),
                "dismissed_count": ctx["dismissed_count"],
                "active_rxnorm_json": json.dumps(ctx["active_rxnorm"]),
                "active_ndc_json": json.dumps(ctx["active_ndc"]),
                "active_descriptions_json": json.dumps(ctx["active_descriptions"]),
                "active_meds_json": json.dumps(ctx["active_meds"]),
                "open_notes_json": json.dumps(ctx["open_notes"]),
                "open_notes": ctx["open_notes"],
                "multiple_open_notes": len(ctx["open_notes"]) >= 2,
                "single_open_note": len(ctx["open_notes"]) == 1,
                "last_pulled_iso": ctx["last_pulled_iso"],
                "cache_bust": _CACHE_BUST,
            },
        )

        return [
            LaunchModalEffect(
                content=html,
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE,
                title="Medication History",
            ).apply()
        ]
