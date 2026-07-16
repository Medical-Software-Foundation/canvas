"""Pure helpers for building Canvas FHIR payloads (no SDK imports).

Kept separate from the handler so the payload shape can be unit-tested without a
live Canvas environment.
"""


def _attachment_filename(display, code, today):
    """Build a download filename ending in .pdf.

    Canvas uses ``sourceAttachment.title`` as the stored file's name (its docs
    example sends ``"UploadTest.pdf"``), so the ``.pdf`` extension MUST be part of
    the title — otherwise the download has no extension and opens as plain text.
    """
    label = (display or code or "Consent").strip() or "Consent"
    # Keep it filename-friendly: spaces -> underscores, drop characters that make
    # for awkward filenames.
    safe = "".join(
        ch if (ch.isalnum() or ch in " -_") else "" for ch in label
    ).strip()
    safe = "_".join(safe.split()) or "Consent"
    return "%s_%s.pdf" % (safe, today)


def build_consent_payload(
    system,
    code,
    display,
    patient_id,
    today,
    pdf_base64="",
):
    """Build the FHIR Consent create payload.

    ``today`` is an ISO ``YYYY-MM-DD`` string used for the effective date
    (``provision.period.start``). No ``period.end`` is set, so the consent never
    expires. Canvas records the accepted/issued datetime automatically.

    ``pdf_base64`` is the generated documentation PDF. When it is empty (e.g. a
    "Written" consent, where the provider uploads the signed document themselves)
    the ``sourceAttachment`` is omitted and the Consent is recorded without one.
    """
    coding = {"system": system, "code": code}
    if display:
        coding["display"] = display

    payload = {
        "resourceType": "Consent",
        "status": "active",
        "scope": {},
        "category": [{"coding": [coding]}],
        "patient": {
            "reference": "Patient/%s" % patient_id,
            "type": "Patient",
        },
        "provision": {"period": {"start": today}},
    }
    if pdf_base64:
        payload["sourceAttachment"] = {
            "title": _attachment_filename(display, code, today),
            "contentType": "application/pdf",
            "data": pdf_base64,
        }
    return payload
