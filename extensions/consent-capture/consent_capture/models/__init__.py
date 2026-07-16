"""Custom data model for consent definitions.

Each ``ConsentDefinition`` row is one consent the practice can collect (e.g.
"Universal", "RPM", "GUIDE"). The set of definitions is what turns the plugin
from single-consent into multi-consent: the chart button lists every active
definition, and the admin UI (Consent Settings) manages them at runtime.

Expiration is intentionally NOT modeled here — it is configured alongside the
Patient Consent Coding in the Canvas Django admin, not by this plugin.
"""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    BooleanField,
    DateTimeField,
    Index,
    IntegerField,
    JSONField,
    TextField,
    UniqueConstraint,
)


class ConsentDefinition(CustomModel):
    # Coding — must match a Patient Consent Coding configured in Canvas admin.
    code = TextField(default="")
    system = TextField(default="INTERNAL")
    display = TextField(default="")

    # The verbiage the provider reads to the patient. Multi-paragraph; parsed
    # into paragraphs by ``constants.parse_statement``.
    verbiage = TextField(default="")

    # Which of the standard questions apply to this consent.
    method_enabled = BooleanField(default=True)
    obtained_by_enabled = BooleanField(default=True)
    capacity_enabled = BooleanField(default=True)

    # Which of the fixed methods this consent supports, a subset of
    # constants.METHOD_OPTIONS (["Verbal", "Electronic", "Written"]). Empty falls
    # back to all three.
    method_options = JSONField(default=list)

    # Capacity-statement templates, filled at capture time. ``[Patient name]`` is
    # replaced with the patient's name; ``[Name]`` with the representative's name.
    capacity_patient_template = TextField(default="")
    capacity_representative_template = TextField(default="")

    # Ordered list of questions the provider answers during capture. Each item is
    # {id, prompt, type (yes_no|acknowledge|text), required, affirm}. See
    # ``consent_capture.questions``. Nullable "Add Field" — existing rows read as [].
    questions = JSONField(default=list)

    # Other codings that count as this consent already being on file (e.g. an older
    # "written" or "verbal" variant of the same consent). Each item is
    # {system, code, display}. If any is on file for the patient, this consent is
    # treated as on file — so the patient is not prompted to complete an equivalent.
    # The consent's own coding always counts; matching is by the (system, code) pair
    # and tolerates an empty code. See ``consent_capture.constants.normalize_satisfied_by``.
    satisfied_by = JSONField(default=list)

    # Whether the patient is prompted to complete this consent (shown under
    # "Due now" in the capture modal). When False the consent is available ad hoc
    # (shown under "Optional"). Defaults to optional.
    required = BooleanField(default=False)

    active = BooleanField(default=True)
    sort_order = IntegerField(default=100)

    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["system", "code"], name="uniq_consent_system_code"),
        ]
        indexes = [
            Index(fields=["active", "sort_order"]),
        ]


class ConsentCaptureDetail(CustomModel):
    """The capture details for one recorded consent, stored by the plugin because
    Canvas has no settable "obtainer" field on a FHIR Consent (consents created via
    the FHIR API are stamped with the service account, not the logged-in staff).

    Written at capture time from the session-authoritative data, and joined back into
    the "On File" history (see ``service.consent_records``) so compliance can see who
    obtained/uploaded each consent and how — including written consents, whose only
    attachment is the uploaded signed document.

    Keyed by ``(patient_id, system, code, effective_date)`` — the same natural key the
    On File list exposes per record — so re-recording the same consent on the same day
    upserts rather than duplicates. ``effective_date`` is the ISO ``YYYY-MM-DD`` the
    plugin sends as ``provision.period.start`` (matches ``PatientConsent.effective_date``).
    """

    patient_id = TextField(default="")
    system = TextField(default="")
    code = TextField(default="")
    effective_date = TextField(default="")

    # Who obtained it: the logged-in staff (session), not the FHIR service account.
    obtained_by_id = TextField(default="")
    obtained_by_name = TextField(default="")

    method = TextField(default="")             # Verbal | Electronic | Written | Other | ""
    consented_by = TextField(default="")       # "Patient" | "Name (Relationship)"
    capacity_statement = TextField(default="")
    pages = IntegerField(default=0)            # page count of the attached PDF (0 = unknown)

    obtained_at = DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["patient_id", "system", "code", "effective_date"],
                name="uniq_consent_capture_detail",
            ),
        ]
        indexes = [
            Index(fields=["patient_id"]),
        ]
