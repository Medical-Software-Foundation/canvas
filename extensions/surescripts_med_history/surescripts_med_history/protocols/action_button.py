import json

import requests
from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates import render_to_string
from canvas_sdk.utils.http import ontologies_http
from canvas_sdk.v1.data.medication import Medication
from canvas_sdk.v1.data.medication_history import (
    MedicationHistoryMedication,
    MedicationHistoryResponse,
    MedicationHistoryResponseStatus,
)
from canvas_sdk.v1.data.note import NoteMetadata
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.staff import Staff

from logger import log

from surescripts_med_history.models import MedicationDismissal
from surescripts_med_history.protocols.mock_data import mock_history_items
from surescripts_med_history.protocols.settings import MOCK_SECRET_NAME, parse_mock

RXNORM_SYSTEM = "http://www.nlm.nih.gov/research/umls/rxnorm"
NDC_SYSTEM = "http://hl7.org/fhir/sid/ndc"


def _get_system_uri(system) -> str:
    """Extract system URI string — handles plain strings and {'uri': '...'} proxy objects."""
    s = str(system)
    if RXNORM_SYSTEM in s:
        return RXNORM_SYSTEM
    if NDC_SYSTEM in s:
        return NDC_SYSTEM
    return s


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
                rxnorm_codes.add(coding.code)
            elif sys_uri == NDC_SYSTEM and coding.code:
                ndc_codes.add(coding.code.replace("-", ""))
            if coding.display and len(coding.display) > 10:
                descriptions.append(coding.display.lower())
        if med.national_drug_code:
            ndc_codes.add(med.national_drug_code.replace("-", ""))
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


def _ndc_to_rxnorm(ndc_code: str, cache: dict | None = None) -> str:
    """Look up RxNorm code for an NDC via FDB. Returns empty string when the
    HTTP call fails or the response has no RxNorm cui — any other error
    (e.g. an unexpected response shape) bubbles up so it surfaces in Sentry.

    `cache` memoizes results (misses included) for the life of one payload
    build. A drug with several fills produces several history rows carrying
    the same NDC, so without it the same lookup is repeated per row.
    """
    if cache is not None and ndc_code in cache:
        return cache[ndc_code]

    rxnorm = ""
    try:
        resp = ontologies_http.get_json("/fdb/ndc-to-medication/%s/" % ndc_code)
    except requests.RequestException as e:
        log.warning("FDB NDC->RxNorm lookup failed for %s: %s" % (ndc_code, e))
    else:
        result = resp.json()
        if isinstance(result, dict):
            rxcui = result.get("rxnorm_rxcui", "") or ""
            rxnorm = str(rxcui) if rxcui else ""

    if cache is not None:
        cache[ndc_code] = rxnorm
    return rxnorm


def _is_matched(
    history_med: MedicationHistoryMedication,
    active_rxnorm_codes: set[str],
    active_ndc_codes: set[str],
    active_descriptions: list[str],
    xref_cache: dict | None = None,
) -> tuple:
    """Return (matched: bool, match_method: str) for a Surescripts medication.

    `xref_cache` is threaded into the FDB NDC→RxNorm lookups so one payload
    build resolves each distinct NDC at most once.
    """
    for coding in history_med.codings.all():
        sys_uri = _get_system_uri(coding.system)
        if sys_uri == RXNORM_SYSTEM and coding.code in active_rxnorm_codes:
            return True, "rxnorm"
        if (
            sys_uri == NDC_SYSTEM
            and coding.code
            and coding.code.replace("-", "") in active_ndc_codes
        ):
            return True, "ndc"

    drug_desc = history_med.drug_description.lower()
    if drug_desc:
        for desc in active_descriptions:
            if drug_desc in desc:
                return True, "description"

    # NDC→RxNorm cross-reference: look up the Surescripts NDC in FDB to get its
    # RxNorm. Each lookup is a blocking HTTP round trip, so skip the whole pass
    # when the patient has no active RxNorm codes — nothing it resolves could
    # match, and that's exactly the case (few/no active meds) where the most
    # rows fall through to here.
    if active_rxnorm_codes:
        for coding in history_med.codings.all():
            sys_uri = _get_system_uri(coding.system)
            if sys_uri == NDC_SYSTEM and coding.code:
                resolved_rxnorm = _ndc_to_rxnorm(coding.code, xref_cache)
                if resolved_rxnorm and resolved_rxnorm in active_rxnorm_codes:
                    return True, "ndc_rxnorm_xref:%s->%s" % (
                        coding.code,
                        resolved_rxnorm,
                    )

    return False, ""


def _build_history_item(med, is_match, match_method=""):
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
        "rxnorm_codes": rxnorm_codes,
        "ndc_codes": ndc_codes,
    }


def _get_group_key(item):
    """Get grouping key: first NDC code if available, otherwise drug_description."""
    if item["ndc_codes"]:
        return "ndc:" + item["ndc_codes"][0]
    return "desc:" + item["drug_description"]


def _group_history_items(items):
    """Group history items by NDC (or drug_description). Claim descriptions preferred for header."""
    groups_dict = {}
    group_order = []

    for item in items:
        key = _get_group_key(item)
        is_claim = (
            item["source_type"].lower() == "claim" if item["source_type"] else False
        )

        if key not in groups_dict:
            groups_dict[key] = {
                "group_key": key,
                "drug_description": item["drug_description"],
                "strength": item["strength"],
                "is_match": item["is_match"],
                "match_method": item.get("match_method", ""),
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


# Friendly labels for the AAA reject codes Surescripts returns on a denied
# medication-history response. The raw `reason` text is preferred when present;
# these are the fallback when only a code is available.
_REASON_CODE_LABELS = {
    "75": "Patient could not be matched in Surescripts",
    "42": "Surescripts was temporarily unavailable — please resubmit",
    "41": "Surescripts access is restricted for this request",
    "79": "Invalid participant identification",
}


def _spi_provider_choices() -> list[dict]:
    """SPI-registered active providers as ``[{"id", "name"}]`` sorted "Last, First".

    Only active providers with a non-empty ``spi_number`` can legally originate a
    Surescripts request, so the modal's provider dropdown is limited to them
    (mirrors the bulk requests app's provider filter).
    """
    choices = []
    for staff in (
        Staff.objects.filter(active=True)
        .exclude(spi_number="")
        .order_by("last_name", "first_name")
    ):
        first = getattr(staff, "first_name", "") or ""
        last = getattr(staff, "last_name", "") or ""
        if not first and not last:
            continue
        name = "%s, %s" % (last, first) if (last and first) else (last or first).strip()
        choices.append({"id": str(staff.id), "name": name})
    return choices


def _last_requested_display(patient) -> str:
    """Most recent Surescripts request time, from the note metadata we stamp.

    The eligibility/med-history ``_at`` values are stored as ISO-8601 strings,
    which sort lexicographically in chronological order, so the max is the most
    recent. Returns the raw ISO-8601 string (with UTC offset) so the browser can
    render it in the viewer's local timezone; "" when nothing has been requested.
    """
    return (
        NoteMetadata.objects.filter(
            note__patient=patient,
            key__in=["surescripts_eligibility_at", "surescripts_med_history_at"],
        )
        .order_by("-value")
        .values_list("value", flat=True)
        .first()
        or ""
    )


def _request_status(patient, has_history: bool) -> dict:
    """Summarize the latest med-history response for the modal status banner.

    Returns a dict with:
      - ``state``: matched | matched_empty | not_matched | no_data
      - ``detail``: human-readable reason when not matched
      - ``last_response_at``: when Surescripts last responded
      - ``response_provider``: provider the response ran under

    Surescripts does not expose an eligibility-response data model, so the
    med-history response (which is gated on eligibility) is the closest
    structured signal for whether the patient was matched.
    """
    latest = (
        MedicationHistoryResponse.objects.filter(patient=patient)
        .select_related("staff")
        .order_by("-created")
        .first()
    )

    last_response_at = ""
    response_provider = ""
    if latest is not None:
        if latest.created:
            # ISO with UTC offset → browser renders it in the viewer's timezone.
            last_response_at = latest.created.isoformat()
        staff = getattr(latest, "staff", None)
        if staff is not None:
            response_provider = (
                "%s %s"
                % (
                    getattr(staff, "first_name", "") or "",
                    getattr(staff, "last_name", "") or "",
                )
            ).strip()

    if (
        latest is not None
        and latest.status == MedicationHistoryResponseStatus.STATUS_DENIED
    ):
        detail = (latest.reason or "").strip() or _REASON_CODE_LABELS.get(
            latest.reason_code, "Patient could not be matched in Surescripts"
        )
        state = "not_matched"
    elif has_history:
        state = "matched"
        detail = ""
    elif latest is not None:
        # An approved (or otherwise non-denied) response with no medications.
        state = "matched_empty"
        detail = ""
    else:
        state = "no_data"
        detail = ""

    return {
        "state": state,
        "detail": detail,
        "last_response_at": last_response_at,
        "response_provider": response_provider,
    }


def build_history_payload(patient, include_mock: bool = False) -> tuple[dict, list]:
    """Build the medication-history modal data for a patient.

    Returns ``(payload, stale_dismissal_ids)``. The payload is the JSON-able
    data the modal renders (grouped history, active meds, status, timestamps);
    ``stale_dismissal_ids`` are dismissals the caller may delete (auto-cleared
    because the med is now matched or a newer fill arrived). Kept caller-side so
    this stays a pure read — the action button deletes them, the refresh GET
    endpoint ignores them.

    ``include_mock`` (driven by the ``mock_history_data`` secret) appends fake
    history rows so the workflow can be demoed without real Surescripts data.
    They go through the same matching/grouping/dismissal path as real rows and
    are flagged ``is_mock`` so the modal can label them.
    """
    history_meds = list(
        MedicationHistoryMedication.objects.filter(patient=patient)
        .prefetch_related("codings")
        .order_by("-last_fill_date")[:100]
    )

    active_meds = list(
        Medication.objects.active().filter(patient=patient).prefetch_related("codings")
    )

    rxnorm_codes, ndc_codes, descriptions = _build_active_code_sets(active_meds)

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

    # Shared across every row so each distinct NDC costs at most one FDB call
    # per payload build (fills of the same drug repeat their NDC).
    xref_cache: dict[str, str] = {}

    history_items = []
    for med in history_meds:
        is_match, match_method = _is_matched(
            med, rxnorm_codes, ndc_codes, descriptions, xref_cache
        )
        history_items.append(_build_history_item(med, is_match, match_method))

    mock_group_keys: set[str] = set()
    if include_mock:
        mock_items = mock_history_items(rxnorm_codes, ndc_codes, descriptions)
        history_items.extend(mock_items)
        mock_group_keys = {_get_group_key(item) for item in mock_items}
        log.info(
            "Surescripts mock history enabled: injected %s test rows for patient %s"
            % (len(mock_items), patient.id)
        )

    grouped_items = _group_history_items(history_items)
    for group in grouped_items:
        group["is_mock"] = group["group_key"] in mock_group_keys

    # Apply dismissals. A dismissal is auto-cleared when the med is now matched
    # against an active med, or a fill arrives dated after the dismissal.
    dismissals_by_key = {
        dis.group_key: dis
        for dis in MedicationDismissal.objects.filter(patient_id=patient.dbid)
    }

    stale_dismissal_ids = []
    for group in grouped_items:
        group["dismissed"] = False
        dis = dismissals_by_key.get(group["group_key"])
        if dis is None:
            continue
        if group["is_match"]:
            stale_dismissal_ids.append(dis.dbid)
            continue
        # Normalize both sides to YYYY-MM-DD so a fill recorded on the same
        # calendar day as the dismissal doesn't lexicographically beat the
        # date-only dismissed_at string and silently clear the dismissal.
        last_fill_date_iso = (group.get("latest_fill_date_sort") or "")[:10]
        dismissed_date_iso = (
            dis.dismissed_at.date().isoformat() if dis.dismissed_at else ""
        )
        if (
            last_fill_date_iso
            and dismissed_date_iso
            and last_fill_date_iso > dismissed_date_iso
        ):
            stale_dismissal_ids.append(dis.dbid)
            continue
        group["dismissed"] = True
        group["dismissed_at"] = (
            dis.dismissed_at.strftime("%b %d, %Y") if dis.dismissed_at else ""
        )
        group["dismissed_by"] = dis.dismissed_by or ""

    # Most recent record's created time — when the data last arrived.
    last_pulled = ""
    if history_meds:
        latest_created = None
        for med in history_meds:
            if med.created and (latest_created is None or med.created > latest_created):
                latest_created = med.created
        if latest_created:
            # ISO with UTC offset → browser renders it in the viewer's timezone.
            last_pulled = latest_created.isoformat()

    # Mock rows count as history for the banner — otherwise a mock-only demo
    # shows "no data" above a list of medications.
    status = _request_status(patient, has_history=bool(history_items))
    status["last_requested"] = _last_requested_display(patient)
    status["last_pulled"] = last_pulled

    payload = {
        "grouped_items": grouped_items,
        "active_meds": active_meds_summary,
        "last_pulled": last_pulled,
        "status": status,
    }
    return payload, stale_dismissal_ids


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

        # The modal lets the user pick any SPI-registered provider to run the
        # request under, so the request is possible whenever at least one such
        # provider exists — not only when the logged-in user or the patient's
        # default provider has an SPI.
        providers = _spi_provider_choices()
        can_request = bool(providers)

        # Pre-select the most natural provider: the logged-in staff if they have
        # an SPI, else the patient's default provider (if SPI), else the first
        # available — but the user can change it.
        actor_staff_id = ""
        actor = getattr(self.event, "actor", None)
        actor_id_str = str(getattr(actor, "id", "") or "")
        if actor_id_str:
            try:
                staff = Staff.objects.get(user__dbid=int(actor_id_str))
                if staff.spi_number:
                    actor_staff_id = str(staff.id)
            except (ValueError, Staff.DoesNotExist) as e:
                log.warning("MedHistoryActionButton: actor SPI lookup failed: %s" % e)

        default_provider_has_spi = bool(
            patient.default_provider
            and getattr(patient.default_provider, "spi_number", "")
        )
        if actor_staff_id:
            default_staff_id = actor_staff_id
        elif default_provider_has_spi:
            default_staff_id = str(patient.default_provider.id)
        elif providers:
            default_staff_id = providers[0]["id"]
        else:
            default_staff_id = ""

        # An SPI-registered prescriber requests as themselves — no need to pick.
        # The picker is only for users without an SPI (e.g. care managers), who
        # must choose a provider to run the request under. When hidden, the
        # request sends no staff_id and the endpoint defaults to the logged-in
        # provider.
        show_provider_select = can_request and not actor_staff_id

        payload, stale_dismissal_ids = build_history_payload(
            patient, include_mock=parse_mock(self.secrets.get(MOCK_SECRET_NAME))
        )
        if stale_dismissal_ids:
            MedicationDismissal.objects.filter(dbid__in=stale_dismissal_ids).delete()

        html = render_to_string(
            "templates/med_history.html",
            {
                "can_request": can_request,
                "patient_id": patient_id,
                "grouped_items_json": json.dumps(payload["grouped_items"]),
                "active_meds_json": json.dumps(payload["active_meds"]),
                "last_pulled": payload["last_pulled"],
                "status_json": json.dumps(payload["status"]),
                "providers_json": json.dumps(providers),
                "default_staff_id": default_staff_id,
                "show_provider_select": show_provider_select,
            },
        )

        return [
            LaunchModalEffect(
                content=html,
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE,
                title="Medication History",
            ).apply()
        ]
