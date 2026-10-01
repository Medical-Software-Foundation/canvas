"""Staff-authenticated endpoints for the consent_capture plugin.

Two SimpleAPI handlers:

- ``ConsentApi`` (``/consent``) — the capture endpoint the picker's "Accept"
  button calls. It resolves the selected ``ConsentDefinition`` by code
  (authoritative — the browser never supplies the verbiage), builds a
  documentation PDF, and creates a FHIR Consent.
- ``ConsentAdminApi`` (``/admin``) — CRUD over ``ConsentDefinition`` for the
  Consent Settings admin UI.
"""

import base64
import re
from datetime import datetime, timezone
from http import HTTPStatus

# Matches an ISO calendar date (YYYY-MM-DD) sent by the browser.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

import json

from canvas_sdk.clients.canvas_fhir import CanvasFhir
from canvas_sdk.effects import Effect
from canvas_sdk.effects.action_button import ReloadPatientActionButtonsEffect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.utils.http import Http
from canvas_sdk.v1.data import (
    BannerAlert,
    Patient,
    PatientConsent,
    PatientConsentCoding,
    Staff,
)

from logger import log

from consent_capture.banner import add_banner_effect, remove_banner_effect
from consent_capture.constants import (
    ACCEPTED_STATES,
    BANNER_KEY,
    banners_enabled,
    DEFAULT_CAPACITY_PATIENT,
    DEFAULT_CAPACITY_REPRESENTATIVE,
    MAX_DOCUMENT_BYTES,
    METHOD_OPTIONS,
    PDF_MAGIC,
    method_generates_pdf,
    normalize_method_options,
    normalize_satisfied_by,
    parse_statement,
    render_capacity,
)
from consent_capture.fhir import build_consent_payload
from consent_capture.models import ConsentCaptureDetail, ConsentDefinition
from consent_capture.pdf import generate_consent_pdf_base64, pdf_page_count
from consent_capture.questions import evaluate_answers, normalize_questions
from consent_capture.service import (
    definition_by_code,
    is_consent_admin,
    patients_missing_required,
)


def _clean_time(value):
    """Sanitize a browser-supplied local time like '2:32 PM' for display."""
    if not value:
        return ""
    allowed = set("0123456789: APMapm")
    cleaned = "".join(ch for ch in value.strip() if ch in allowed).strip()
    return cleaned[:12]


def _clean_tz(value):
    """Sanitize a browser-supplied timezone label like 'PDT' or 'GMT+2'."""
    if not value:
        return ""
    allowed = set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-:/_ "
    )
    cleaned = "".join(ch for ch in str(value).strip() if ch in allowed).strip()
    return cleaned[:16]


def _clean_text(value, limit=80):
    """Trim free text and drop control characters for safe display."""
    if not value:
        return ""
    cleaned = "".join(ch for ch in str(value) if ch == " " or ch.isprintable())
    return cleaned.strip()[:limit]


def _representative_name(body):
    """The cleaned representative name from the request body (may be empty)."""
    return _clean_text(body.get("representative_name"))


def _consented_by(body):
    """Return (label, error). label is who consented, e.g. 'Patient' or
    'Jane Doe (Daughter)'. error is a user-facing string or None."""
    who = (body.get("consent_by") or "patient").strip().lower()
    if who != "representative":
        return "Patient", None
    name = _representative_name(body)
    if not name:
        return None, "Please enter the representative's name."
    relationship = _clean_text(body.get("representative_relationship"), limit=60)
    if relationship:
        return "%s (%s)" % (name, relationship), None
    return name, None


def _clean_method(value, allowed):
    """Return the method if it is one of the ``allowed`` options, else ''."""
    method = _clean_text(value, limit=40)
    return method if method in (allowed or []) else ""


def _clean_document_pdf(raw):
    """Validate a browser-supplied consent document (base64 PDF).

    The picker assembles the uploaded/captured pages into a single PDF client-side
    (pdf-lib) and sends it as base64 (optionally with a ``data:...;base64,`` prefix).
    Returns ``(clean_base64, error)``: the re-encoded base64 on success, or an empty
    string and a user-facing message on failure."""
    if not raw or not isinstance(raw, str):
        return "", "Add the signed consent document before recording."
    payload = raw.split(",", 1)[1] if raw.startswith("data:") else raw
    try:
        data = base64.b64decode(payload, validate=True)
    except Exception:  # noqa: BLE001 - any decode failure is a bad upload
        return "", "That document couldn't be read. Please try again."
    if not data.startswith(PDF_MAGIC):
        return "", "The consent document must be a PDF."
    if len(data) > MAX_DOCUMENT_BYTES:
        return "", "That document is too large. Please keep it under 10 MB."
    return base64.b64encode(data).decode("ascii"), None


def _full_name(first, last, fallback):
    name = ("%s %s" % (first or "", last or "")).strip()
    return name or fallback


def _resolve_patient(patient_id):
    """Return (full_name, date_of_birth_iso) or None if the patient isn't found."""
    row = (
        Patient.objects.filter(id=patient_id)
        .values_list("first_name", "last_name", "birth_date")
        .first()
    )
    if not row:
        return None
    name = _full_name(row[0], row[1], "(name unavailable)")
    dob = row[2].isoformat() if row[2] else ""
    return name, dob


def _resolve_staff(staff_id):
    if not staff_id:
        return "Unknown"
    row = (
        Staff.objects.filter(id=staff_id)
        .values_list("first_name", "last_name")
        .first()
    )
    if not row:
        return "Unknown"
    return _full_name(row[0], row[1], "Unknown")


def _error(message):
    return JSONResponse({"ok": False, "error": message}, status_code=HTTPStatus.OK)


def _store_capture_detail(
    patient_id,
    system,
    code,
    effective_date,
    obtained_by_id,
    obtained_by_name,
    method,
    consented_by,
    capacity_statement,
    pages=0,
):
    """Upsert the capture detail for a just-recorded consent, keyed by the natural key
    ``(patient_id, system, code, effective_date)``.

    Never raises: the consent is already recorded via FHIR by the time this runs, so a
    storage failure is logged and swallowed rather than failing the capture. Uses the
    queryset upsert pattern (``.filter(...).update(...)`` else ``.create(...)``) because
    per-field ``setattr`` is guarded in the plugin sandbox."""
    key = {
        "patient_id": patient_id or "",
        "system": system or "",
        "code": code or "",
        "effective_date": effective_date or "",
    }
    values = {
        "obtained_by_id": obtained_by_id or "",
        "obtained_by_name": obtained_by_name or "",
        "method": method or "",
        "consented_by": consented_by or "",
        "capacity_statement": capacity_statement or "",
        "pages": int(pages or 0),
    }
    try:
        updated = ConsentCaptureDetail.objects.filter(**key).update(**values)
        if not updated:
            ConsentCaptureDetail.objects.create(**dict(key, **values))
    except Exception as exc:  # noqa: BLE001 - must not fail an already-recorded consent
        log.error(
            "ConsentApi: failed to store capture detail for patient %s: %s"
            % (patient_id, exc)
        )


def _url_host(url):
    """Lower-cased host of a URL, or '' if it can't be parsed."""
    match = re.match(r"^https?://([^/]+)", url or "")
    return match.group(1).lower() if match else ""


def _is_trusted_fhir_host(url, customer_identifier):
    """Whether ``url`` points at this Canvas instance's own host.

    ``sourceAttachment.url`` on a Consent is only trustworthy if it lives on this
    instance. A Consent written via the FHIR API could set it to an attacker host;
    fetching that (and minting a token against its host) would send our FHIR client
    credentials off-instance. So restrict to the instance's own app/fumage host,
    derived from ``CUSTOMER_IDENTIFIER``. If that isn't available, require at least a
    Canvas-owned host rather than an arbitrary one."""
    host = _url_host(url)
    if not host:
        return False
    customer = (customer_identifier or "").strip().lower()
    if customer:
        return host in {
            "%s.canvasmedical.com" % customer,
            "fumage-%s.canvasmedical.com" % customer,
        }
    return host.endswith(".canvasmedical.com")


def _fhir_access_token(fumage_url, client_id, client_secret):
    """Mint an OAuth access token for the instance that hosts ``fumage_url``.

    The FHIR client authenticates internally, but the sandbox forbids reading its
    private token (attributes starting with ``_``). So to fetch an authenticated
    ``sourceAttachment`` URL we run the client-credentials flow ourselves against the
    instance token endpoint (the app host, i.e. the fumage host without ``fumage-``)."""
    match = re.match(r"^(https?://)([^/]+)", fumage_url or "")
    if not match or not client_id or not client_secret:
        return ""
    token_url = "%s%s/auth/token/" % (match.group(1), match.group(2).replace("fumage-", "", 1))
    resp = Http().post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    resp.raise_for_status()
    return (resp.json() or {}).get("access_token", "")


class ConsentApi(StaffSessionAuthMixin, SimpleAPI):
    PREFIX = "/consent"

    @api.post("/collect")
    def collect(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        patient_id = body.get("patient_id")

        # Authoritative identity of the collector: the logged-in staff session.
        staff_id = self.request.headers.get("canvas-logged-in-user-id", "")

        code = _clean_text(body.get("consent_code"), limit=120)
        system_hint = _clean_text(body.get("consent_system"), limit=200)
        client_id = self.secrets.get("CANVAS_FHIR_CLIENT_ID", "")
        client_secret = self.secrets.get("CANVAS_FHIR_CLIENT_SECRET", "")

        if not patient_id:
            return [_error("No patient was identified for this consent.")]
        if not code:
            return [_error("No consent was selected.")]

        definition = definition_by_code(code, system_hint)
        if definition is None:
            return [
                _error(
                    "That consent isn't configured. Please refresh, or ask your "
                    "administrator to set it up in Consent Settings."
                )
            ]

        if not client_id or not client_secret:
            return [
                _error(
                    "This plugin isn't fully configured yet — the Canvas FHIR "
                    "credentials are missing. Please contact your administrator."
                )
            ]

        patient = _resolve_patient(patient_id)
        if patient is None:
            return [_error("We couldn't find this patient's record.")]
        patient_name, patient_dob = patient

        staff_name = _resolve_staff(staff_id)

        # Who is giving consent: the patient or an authorized representative.
        consented_by, who_error = _consented_by(body)
        if who_error:
            return [_error(who_error)]

        # Method — required when the consent uses it. Validated against the
        # consent's own configured options (falling back to the default set).
        method = ""
        if definition.method_enabled:
            allowed = normalize_method_options(definition.method_options) or list(METHOD_OPTIONS)
            method = _clean_method(body.get("method"), allowed)
            if not method:
                return [_error("Please select how the consent was obtained.")]

        # Capacity statement, filled from the definition's templates.
        capacity_statement = ""
        if definition.capacity_enabled:
            who = (body.get("consent_by") or "patient").strip().lower()
            if who == "representative":
                capacity_statement = render_capacity(
                    definition.capacity_representative_template,
                    representative_name=_representative_name(body),
                )
            else:
                capacity_statement = render_capacity(
                    definition.capacity_patient_template,
                    patient_name=patient_name,
                )

        # When capacity applies, the provider must have affirmed the attestation in the
        # modal (the Yes/No question). Keyed on the capacity toggle — the modal shows the
        # attestation whenever capacity is enabled — so recording is blocked unless it is
        # confirmed, regardless of the recorded statement's wording.
        if definition.capacity_enabled and not body.get("capacity_confirmed"):
            return [_error("Consent cannot be recorded unless capacity is confirmed.")]

        # Evaluate the consent's questions — but only for methods that generate a PDF.
        # "Written" consents don't surface the questions in the modal (the signed
        # document is the record), so they aren't asked or evaluated here either. A
        # required-but-missing answer or an unaffirmed affirmation blocks recording;
        # the responses are printed on the generated PDF (verbal/electronic).
        responses: list = []
        if method_generates_pdf(method):
            answers = body.get("answers") or {}
            answers_ok, answers_error, responses = evaluate_answers(
                definition.questions or [], answers
            )
            if not answers_ok:
                log.info(
                    "ConsentApi: consent %s not recorded for patient %s (%s)"
                    % (definition.code, patient_id, answers_error)
                )
                return [_error(answers_error)]

        # Use the end user's LOCAL calendar date (sent by the browser) so the
        # consent date reflects the user's day, not UTC. Fall back to server UTC.
        local_date = (body.get("local_date") or "").strip()
        if _DATE_RE.match(local_date):
            today = local_date
        else:
            today = datetime.now(timezone.utc).date().isoformat()

        # Local wall-clock time plus the browser's timezone label (e.g. "PDT"),
        # so the footer timestamp is unambiguous.
        local_time = _clean_time(body.get("local_time"))
        local_tz = _clean_tz(body.get("local_tz"))
        time_display = ("%s %s" % (local_time, local_tz)).strip() if local_time else ""

        title = definition.display or definition.code

        # "Written" consents are signed on paper / an external document: the provider
        # uploads or camera-captures it in the picker, which assembles the pages into a
        # single PDF. We attach that document instead of generating one. Every other
        # method (and no method) gets an auto-generated PDF.
        make_pdf = method_generates_pdf(method)
        if make_pdf:
            pdf_b64 = generate_consent_pdf_base64(
                title=title,
                patient_name=patient_name,
                patient_dob=patient_dob,
                staff_name=staff_name,
                date=today,
                statement_paragraphs=parse_statement(definition.verbiage),
                time=time_display,
                consented_by=consented_by,
                method=method,
                capacity_statement=capacity_statement,
                responses=responses,
            )
        else:
            pdf_b64, doc_error = _clean_document_pdf(body.get("document_pdf"))
            if doc_error:
                return [_error(doc_error)]

        # Page count of the attached PDF, for the "PDF · N pages" detail. Best-effort:
        # 0 when it can't be read (a compressed PDF hides its page objects).
        try:
            doc_pages = pdf_page_count(base64.b64decode(pdf_b64)) if pdf_b64 else 0
        except Exception:  # noqa: BLE001 - never fail capture over a page count
            doc_pages = 0

        payload = build_consent_payload(
            system=definition.system,
            code=definition.code,
            display=definition.display,
            patient_id=patient_id,
            pdf_base64=pdf_b64,
            today=today,
        )

        try:
            client = CanvasFhir(client_id, client_secret)
            client.create("Consent", payload)
        except Exception as exc:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            # Canvas returns 201 with an empty body on a successful Consent
            # create, which makes the client's JSON parse raise a ValueError even
            # though the write succeeded. Treat 2xx (or an empty-body parse error
            # with no HTTP response) as success.
            if status is not None and status < 400:
                log.info(
                    "ConsentApi: consent created (HTTP %s, empty body) for "
                    "patient %s" % (status, patient_id)
                )
            elif status is None and isinstance(exc, ValueError):
                log.info(
                    "ConsentApi: consent created (empty response body) for "
                    "patient %s" % patient_id
                )
            else:
                detail = getattr(response, "text", str(exc))
                log.error(
                    "ConsentApi: FHIR Consent create failed (HTTP %s) for "
                    "patient %s: %s" % (status, patient_id, detail)
                )
                return [
                    _error(
                        "We couldn't save the consent. If this keeps happening, "
                        "please contact your administrator."
                    )
                ]

        log.info(
            "ConsentApi: recorded consent %s for patient %s, collected by %s"
            % (definition.code, patient_id, staff_name)
        )

        # Persist the capture detail (who obtained it, method, who consented,
        # capacity) so it can be shown under "On File" — Canvas has no settable
        # obtainer field on a FHIR Consent. Must not fail the capture: the consent
        # is already recorded.
        _store_capture_detail(
            patient_id=patient_id,
            system=definition.system,
            code=definition.code,
            effective_date=today,
            obtained_by_id=str(staff_id or ""),
            obtained_by_name=staff_name,
            method=method,
            consented_by=consented_by,
            capacity_statement=capacity_statement,
            pages=doc_pages,
        )

        # Recolor the chart-header "Consents" button live: recording this consent may
        # clear the patient's last required consent, so the red button should turn
        # neutral gray without a page reload. Best-effort — the consent is already
        # recorded, so a reload failure must not fail the capture.
        effects: list[Effect] = []
        try:
            effects.append(ReloadPatientActionButtonsEffect(id=str(patient_id)).apply())
        except Exception as exc:  # noqa: BLE001 - never fail an already-recorded consent
            log.warning(
                "ConsentApi: button reload skipped for patient %s: %s" % (patient_id, exc)
            )

        return [
            JSONResponse(
                {
                    "ok": True,
                    "preview": {
                        "code": definition.code,
                        "title": title,
                        "patient_name": patient_name,
                        "patient_dob": patient_dob,
                        "consented_by": consented_by,
                        "method": method,
                        "collected_by": staff_name,
                        "capacity_statement": capacity_statement,
                        "date": today,
                        "time": time_display,
                        "pdf": bool(pdf_b64),
                        "pages": doc_pages,
                    },
                },
                status_code=HTTPStatus.OK,
            )
        ] + effects

    @api.get("/document")
    def document(self) -> list[Response | Effect]:
        """Return the PDF attached to a patient's most recent accepted consent for a
        coding, so the picker's completed cards can open it. Located via the ORM
        (most recent by effective date), then read from FHIR for its
        ``sourceAttachment`` (base64 PDF) — returned as JSON for the browser to view."""
        params = self.request.query_params
        patient_id = _clean_text(params.get("patient_id"), limit=100)
        record_id = _clean_text(params.get("consent_id"), limit=100)
        code = _clean_text(params.get("code"), limit=120)
        system = _clean_text(params.get("system"), limit=200)
        if not patient_id or not (record_id or code):
            return [_error("Missing consent reference.")]

        if record_id:
            # A specific recorded consent (an On File history row). Confirm it
            # belongs to this patient before serving it (guards against loading
            # another patient's consent by id).
            consent_id = (
                PatientConsent.objects.filter(
                    id=record_id, patient__id=patient_id, state__in=ACCEPTED_STATES
                )
                .values_list("id", flat=True)
                .first()
            )
        else:
            # No specific record: fall back to the most recent for this coding.
            query = PatientConsent.objects.filter(
                patient__id=patient_id, category__code=code, state__in=ACCEPTED_STATES
            )
            if system:
                query = query.filter(category__system=system)
            consent_id = (
                query.order_by("-effective_date").values_list("id", flat=True).first()
            )
        if not consent_id:
            return [_error("No recorded consent was found for this patient.")]

        client_id = self.secrets.get("CANVAS_FHIR_CLIENT_ID", "")
        client_secret = self.secrets.get("CANVAS_FHIR_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            return [_error("This plugin isn't fully configured yet — contact your administrator.")]

        try:
            client = CanvasFhir(client_id, client_secret)
            # Use the client's own read(): it acquires/caches the OAuth token and
            # resolves the FHIR base URL. (A raw Http().get with client._get_headers()
            # runs before the token is fetched, so it 401s.)
            resource = client.read("Consent", consent_id) or {}
        except Exception as exc:  # noqa: BLE001 - surface a friendly message, log detail
            log.error("ConsentApi: failed to read Consent %s: %s" % (consent_id, exc))
            return [_error("We couldn't load the consent document.")]

        attachment = resource.get("sourceAttachment") or {}
        pdf_b64 = attachment.get("data") or ""
        source_url = attachment.get("url") or ""
        if not pdf_b64 and source_url:
            # Canvas returns the stored file behind a URL rather than inline base64.
            # When it's a FHIR Binary reference, read it via the public client (which
            # handles auth) — the sandbox blocks the client's private _get_headers(),
            # so we can't hand-roll an authenticated raw request.
            # A Binary reference is read by id via the SDK client, which always talks
            # to this instance — safe regardless of the URL's host.
            match = re.search(r"/Binary/([^/?#]+)", source_url)
            customer = (getattr(self, "environment", None) or {}).get("CUSTOMER_IDENTIFIER", "")
            try:
                if match:
                    binary = client.read("Binary", match.group(1)) or {}
                    pdf_b64 = binary.get("data") or ""
                if not pdf_b64 and _is_trusted_fhir_host(source_url, customer):
                    # A Canvas-hosted attachment URL on THIS instance — needs the OAuth
                    # bearer. Only fetched (and only tokened) for a trusted host, so a
                    # tampered Consent can't redirect our credentials elsewhere.
                    token = _fhir_access_token(source_url, client_id, client_secret)
                    headers = {"Authorization": "Bearer %s" % token} if token else {}
                    binresp = Http().get(source_url, headers=headers)
                    binresp.raise_for_status()
                    pdf_b64 = base64.b64encode(binresp.content).decode()
                elif not pdf_b64 and source_url:
                    log.warning(
                        "ConsentApi: refusing off-instance attachment URL for Consent %s (host=%s)"
                        % (consent_id, _url_host(source_url))
                    )
            except Exception as exc:  # noqa: BLE001
                log.error("ConsentApi: failed to fetch Consent %s document: %s" % (consent_id, exc))
        if not pdf_b64:
            # Log the actual shape (minus the data blob) so we can see where Canvas put the document.
            shape = {k: ("<%d chars>" % len(v or "") if k == "data" else v) for k, v in attachment.items()}
            log.warning(
                "ConsentApi: Consent %s returned no document. resource keys=%s; sourceAttachment=%s"
                % (consent_id, sorted(resource.keys()), shape)
            )
            return [_error("This consent doesn't have an attached document.")]
        return [
            JSONResponse(
                {"ok": True, "pdf_base64": pdf_b64, "filename": attachment.get("title") or "consent.pdf"},
                status_code=HTTPStatus.OK,
            )
        ]

    def _error(self, message):
        # Retained for backwards compatibility with earlier call sites/tests.
        return _error(message)


# --------------------------------------------------------------------------- #
# Admin CRUD over ConsentDefinition (Consent Settings UI).
# --------------------------------------------------------------------------- #

# Boolean workflow flags an admin may toggle through the API.
_BOOL_FIELDS = ("method_enabled", "obtained_by_enabled", "capacity_enabled", "required", "active")


# Human labels for the coding's expiration rule enum (shown read-only).
_EXPIRATION_LABELS = {
    "never": "Never",
    "in_one_year": "Expires one year after acceptance",
    "end_of_year": "Expires at end of year",
}


def _validated_satisfied_by(raw, system, code):
    """Clean and validate the equivalent-codings list submitted for a consent.

    Keeps only entries that (a) name a Patient Consent Coding that actually exists in
    Canvas admin and (b) are not the consent's own ``(system, code)`` — a consent
    can't be its own equivalent. Identity is the full pair (codes may be empty).
    ``display`` is re-derived authoritatively from the coding so the stored label
    stays current. Returns a cleaned ``[{system, code, display}]`` list."""
    entries = normalize_satisfied_by(raw)
    if not entries:
        return []
    coding_display = {
        (c.system or "", c.code or ""): (c.display or c.code or "")
        for c in PatientConsentCoding.objects.all()
    }
    own = (system, code)
    out = []
    for entry in entries:
        pair = (entry["system"], entry["code"])
        if pair == own or pair not in coding_display:
            continue
        out.append({"system": pair[0], "code": pair[1], "display": coding_display[pair]})
    return out


def serialize_definition(defn):
    """Serialize a ConsentDefinition for the admin UI."""
    return {
        "dbid": defn.dbid,
        "code": defn.code,
        "system": defn.system,
        "display": defn.display,
        "verbiage": defn.verbiage,
        "method_enabled": bool(defn.method_enabled),
        "obtained_by_enabled": bool(defn.obtained_by_enabled),
        "capacity_enabled": bool(defn.capacity_enabled),
        "method_options": normalize_method_options(defn.method_options),
        "capacity_patient_template": defn.capacity_patient_template,
        "capacity_representative_template": defn.capacity_representative_template,
        "questions": defn.questions or [],
        "satisfied_by": defn.satisfied_by or [],
        "required": bool(defn.required),
        "active": bool(defn.active),
        "sort_order": defn.sort_order,
    }


def serialize_coding(coding, configured=False):
    """Serialize a Patient Consent Coding (read-only identity + metadata)."""
    rule = coding.expiration_rule
    rule = getattr(rule, "value", rule)  # enum -> its string value if needed
    return {
        "code": coding.code,
        "system": coding.system,
        "display": coding.display or coding.code,
        "user_selected": bool(getattr(coding, "user_selected", False)),
        "expiration_rule": rule or "",
        "expiration_label": _EXPIRATION_LABELS.get(rule, rule or ""),
        "is_mandatory": bool(getattr(coding, "is_mandatory", False)),
        "is_proof_required": bool(getattr(coding, "is_proof_required", False)),
        "show_in_patient_portal": bool(getattr(coding, "show_in_patient_portal", False)),
        "summary": getattr(coding, "summary", "") or "",
        "configured": configured,
    }


def render_admin_page(_default_system=""):
    """Render the Consent Settings page HTML.

    Inlines the already-configured consent workflows. The available Patient
    Consent Codings are fetched by the page from
    ``/admin/codings`` (so this read stays on the SimpleAPI handler). Served by the
    URL-accessible ``/admin/settings`` page endpoint.
    """
    definitions = ConsentDefinition.objects.all().order_by("sort_order", "display")
    return render_to_string(
        "templates/admin.html",
        {
            "consents_json": json.dumps([serialize_definition(d) for d in definitions]),
            "method_options_json": json.dumps(list(METHOD_OPTIONS)),
            "default_capacity_patient": DEFAULT_CAPACITY_PATIENT,
            "default_capacity_representative": DEFAULT_CAPACITY_REPRESENTATIVE,
        },
    )


def render_banners_page():
    """Render the admin-only "Refresh consent banners" page."""
    return render_to_string("templates/banners.html", {})


def _banner_plan():
    """Return ``(needy, bannered)``: the set of active patients that should have a
    banner (missing a required consent) and the set that currently carry ours."""
    needy = patients_missing_required()
    bannered = set(
        BannerAlert.objects.filter(key=BANNER_KEY, status="active")
        .values_list("patient__id", flat=True)
        .iterator(chunk_size=1000)  # stream: could be many bannered patients
    )
    return needy, bannered


_NOT_AUTHORIZED_HTML = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width, initial-scale=1'>"
    "<title>Consent Settings</title></head>"
    "<body style=\"margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',"
    "Roboto,Helvetica,Arial,sans-serif;color:#1f2933;display:flex;align-items:center;"
    "justify-content:center;min-height:100vh;background:#fff;\">"
    "<div style='text-align:center;max-width:420px;padding:24px;'>"
    "<h1 style='font-size:20px;margin:0 0 8px;'>You don&rsquo;t have access</h1>"
    "<p style='color:#6b7280;font-size:14px;margin:0;'>Consent Settings is limited to "
    "authorized users. Ask your administrator to add you to the plugin&rsquo;s "
    "CONSENT_ADMIN_USERS list.</p></div></body></html>"
)


class ConsentAdminApi(StaffSessionAuthMixin, SimpleAPI):
    PREFIX = "/admin"

    def _is_admin(self) -> bool:
        """Whether the logged-in staff may use Consent Settings (CONSENT_ADMIN_USERS)."""
        staff_id = self.request.headers.get("canvas-logged-in-user-id", "")
        return is_consent_admin(staff_id, self.secrets.get("CONSENT_ADMIN_USERS", ""))

    def _banners_enabled(self) -> bool:
        """Whether the banner feature is on (CONSENT_BANNERS_ENABLED, default on).
        When off, the backfill treats *no* patient as needing a banner, so a refresh
        removes every banner the plugin placed and adds none."""
        return banners_enabled(self.secrets.get("CONSENT_BANNERS_ENABLED", ""))

    @api.get("/settings")
    def settings_page(self) -> list[Response | Effect]:
        """Serve the Consent Settings page at a stable URL
        (``/plugin-io/api/consent_capture/admin/settings``) so authorized staff can
        open it from the chart wrench or the plugin's admin description."""
        if not self._is_admin():
            return [HTMLResponse(_NOT_AUTHORIZED_HTML, status_code=HTTPStatus.FORBIDDEN)]
        html = render_admin_page(self.secrets.get("CONSENT_SYSTEM", ""))
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/banners")
    def banners_page(self) -> list[Response | Effect]:
        """Serve the admin-only banner backfill page. Same access as Settings."""
        if not self._is_admin():
            return [HTMLResponse(_NOT_AUTHORIZED_HTML, status_code=HTTPStatus.FORBIDDEN)]
        return [HTMLResponse(render_banners_page(), status_code=HTTPStatus.OK)]

    @api.post("/banners/preview")
    def banners_preview(self) -> list[Response | Effect]:
        """Dry run: report how many banners would be added/removed, no changes."""
        if not self._is_admin():
            return [_error("You don't have access to Consent Settings.")]
        needy, bannered = _banner_plan()
        if not self._banners_enabled():
            needy = set()  # feature off: nobody should carry a banner
        return [
            JSONResponse(
                {
                    "ok": True,
                    "add": len(needy - bannered),
                    "remove": len(bannered - needy),
                    "total": len(needy),
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/banners/refresh")
    def banners_refresh(self) -> list[Response | Effect]:
        """Reconcile chart banners across all active patients: add the banner to
        every patient missing a required consent (one keyed effect for all of them)
        and remove it from anyone who no longer needs it."""
        if not self._is_admin():
            return [_error("You don't have access to Consent Settings.")]
        staff_id = self.request.headers.get("canvas-logged-in-user-id", "")
        needy, bannered = _banner_plan()
        if not self._banners_enabled():
            needy = set()  # feature off: remove every banner, add none
        new_adds = needy - bannered
        stale = bannered - needy

        # One keyed AddBannerAlert per patient (the documented, reliable form;
        # patient_filter with id__in did not apply). Re-applying to already-bannered
        # patients is idempotent and refreshes their copy/placement.
        effects = [add_banner_effect(patient_id) for patient_id in sorted(needy)]
        effects += [remove_banner_effect(patient_id) for patient_id in sorted(stale)]

        log.info(
            "ConsentAdminApi: banner refresh by %s added %d, removed %d"
            % (staff_id or "unknown", len(new_adds), len(stale))
        )
        return [
            JSONResponse(
                {"ok": True, "added": len(new_adds), "removed": len(stale)},
                status_code=HTTPStatus.OK,
            )
        ] + effects

    @api.get("/consents")
    def list_consents(self) -> list[Response | Effect]:
        if not self._is_admin():
            return [_error("You don't have access to Consent Settings.")]
        definitions = ConsentDefinition.objects.all().order_by("sort_order", "display")
        return [
            JSONResponse(
                {"ok": True, "consents": [serialize_definition(d) for d in definitions]},
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/codings")
    def list_codings(self) -> list[Response | Effect]:
        """List every Patient Consent Coding in Canvas, flagged with whether the plugin
        already has a workflow configured for each.

        The full catalog is returned — the ``user_selected`` FHIR flag isn't a reliable
        discriminator here (Canvas sets it on any coding an admin adds, so it tends to
        be True for everything), so both the settings sidebar and the equivalent-consents
        picker draw from the complete set."""
        if not self._is_admin():
            return [_error("You don't have access to Consent Settings.")]
        configured = {
            (d.system, d.code)
            for d in ConsentDefinition.objects.all()
        }
        codings = list(PatientConsentCoding.objects.all().order_by("display"))
        return [
            JSONResponse(
                {
                    "ok": True,
                    "codings": [
                        serialize_coding(c, (c.system, c.code) in configured)
                        for c in codings
                    ],
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/consents")
    def upsert_consent(self) -> list[Response | Effect]:
        if not self._is_admin():
            return [_error("You don't have access to Consent Settings.")]
        body = self.request.json() or {}

        code = _clean_text(body.get("code"), limit=120)
        system = _clean_text(body.get("system"), limit=200)
        if not code or not system:
            return [_error("Choose a consent coding to configure.")]

        # The plugin only configures pre-existing codings — never invents one.
        coding = PatientConsentCoding.objects.filter(system=system, code=code).first()
        if coding is None:
            return [
                _error(
                    "That consent coding isn't configured in Canvas admin. "
                    "Choose an available coding."
                )
            ]

        values = {
            "code": code,
            "system": system,
            "display": coding.display or code,  # identity comes from the coding
            "verbiage": body.get("verbiage") or "",
            "capacity_patient_template": body.get("capacity_patient_template") or "",
            "capacity_representative_template": body.get(
                "capacity_representative_template"
            )
            or "",
            "method_options": normalize_method_options(body.get("method_options")),
            "questions": normalize_questions(body.get("questions")),
            "satisfied_by": _validated_satisfied_by(body.get("satisfied_by"), system, code),
        }
        for field in _BOOL_FIELDS:
            if field in body:
                values[field] = bool(body.get(field))
        raw_sort_order = body.get("sort_order")
        if raw_sort_order is not None:
            try:
                values["sort_order"] = int(raw_sort_order)
            except (TypeError, ValueError):
                pass

        # One workflow per coding: match on system+code (or an explicit dbid).
        defn = None
        dbid = body.get("dbid")
        if dbid:
            defn = ConsentDefinition.objects.filter(dbid=dbid).first()
            if defn is None:
                return [_error("That consent configuration no longer exists.")]
        else:
            defn = ConsentDefinition.objects.filter(system=system, code=code).first()

        if defn is None:
            defn = ConsentDefinition.objects.create(**values)
        else:
            # Use a queryset .update() rather than setattr/save: the plugin
            # sandbox guards attribute assignment on model instances
            # (``__guarded_setattr__``), so per-field setattr raises.
            ConsentDefinition.objects.filter(dbid=defn.dbid).update(**values)
            defn = ConsentDefinition.objects.filter(dbid=defn.dbid).first()

        log.info("ConsentAdminApi: saved consent workflow %s (%s)" % (code, defn.dbid))
        return [
            JSONResponse(
                {"ok": True, "consent": serialize_definition(defn)},
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/consents/delete")
    def delete_consent(self) -> list[Response | Effect]:
        if not self._is_admin():
            return [_error("You don't have access to Consent Settings.")]
        body = self.request.json() or {}
        dbid = body.get("dbid")
        if not dbid:
            return [_error("No consent was specified.")]
        deleted, _ = ConsentDefinition.objects.filter(dbid=dbid).delete()
        if not deleted:
            return [_error("That consent no longer exists.")]
        log.info("ConsentAdminApi: deleted consent definition %s" % dbid)
        return [JSONResponse({"ok": True}, status_code=HTTPStatus.OK)]
