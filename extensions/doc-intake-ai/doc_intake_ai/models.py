"""Data models for document processing."""

from dataclasses import dataclass, field
from typing import Any

from canvas_sdk.v1.data import Patient, Staff
from logger import log
from pydantic import BaseModel


class DocumentExtraction(BaseModel):
    """Data extracted from document by Extend AI."""

    model_config = {"extra": "allow"}

    document_type: str | None = None
    loinc_codes: list[str] | str | None = None
    snomed_codes: list[str] | str | None = None
    test_names: list[str] | str | None = None
    study_names: list[str] | str | None = None
    modality: str | None = None
    body_part: str | None = None

    patient_id: str | None = None
    patient_first_name: str | None = None
    patient_last_name: str | None = None
    patient_name: str | None = None
    date_of_birth: str | None = None

    practitioner_npi: str | None = None
    practitioner_first_name: str | None = None
    practitioner_last_name: str | None = None
    practitioner_name: str | None = None


@dataclass
class CategorizationResult:
    """Result of document categorization."""

    document_type: dict[str, Any] | None = None
    extraction: DocumentExtraction = field(default_factory=DocumentExtraction)
    metadata: dict[str, Any] | None = None
    confidence: float | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class PatientMatch:
    """Result of patient matching."""

    patient: Patient | None = None
    error: str | None = None

    @property
    def found(self) -> bool:
        return self.patient is not None


@dataclass
class ReviewerMatch:
    """Result of reviewer matching."""

    reviewer: Staff | None = None
    auto_assigned: bool = False

    @property
    def found(self) -> bool:
        return self.reviewer is not None


def _is_enabled(raw: str | None) -> bool:
    """Return True only when the value is the string 'true' (case-insensitive)."""
    return raw is not None and raw.strip().lower() == "true"


class FeatureConfig(BaseModel):
    """Toggleable processing capabilities and channel filters.

    Capability fields control whether the corresponding pipeline step runs.
    All default to False so capabilities must be explicitly enabled.

    Channel fields control which intake channels trigger AI processing.
    Fax defaults to True (primary production use case). All others default
    to False and must be explicitly enabled.
    """

    classify: bool = False
    match_patient: bool = False
    assign_reviewer: bool = False
    prefill_templates: bool = False

    channel_fax: bool = True
    channel_document_upload: bool = False
    channel_integration_engine: bool = False
    channel_patient_portal: bool = False

    _CHANNEL_MAP: dict[str, str] = {
        "FAX": "channel_fax",
        "DOCUMENT_UPLOAD": "channel_document_upload",
        "FROM_INTEGRATION_ENGINE": "channel_integration_engine",
        "FROM_PATIENT_PORTAL": "channel_patient_portal",
    }

    def is_channel_enabled(self, channel: str) -> bool:
        """Check whether a given intake channel is enabled for processing.

        Unknown or empty channel values return True to avoid silently
        dropping documents from unexpected sources.
        """
        field_name = self._CHANNEL_MAP.get(channel.upper() if channel else "")
        if field_name is None:
            return True
        return bool(getattr(self, field_name))

    @classmethod
    def from_secrets(cls, secrets: dict[str, str | None]) -> "FeatureConfig":
        """Build config from individual ENABLE_* secret values.

        Each secret accepts "true" (case-insensitive) to enable.
        Empty, missing, or any other value means disabled.

        Fax channel is special: it defaults to True, so an empty or
        missing secret preserves the default. Only an explicit value
        overrides it.
        """
        raw_fax = secrets.get("ENABLE_CHANNEL_FAX")
        channel_fax = _is_enabled(raw_fax) if raw_fax and raw_fax.strip() else True

        return cls(
            classify=_is_enabled(secrets.get("ENABLE_CLASSIFY")),
            match_patient=_is_enabled(secrets.get("ENABLE_MATCH_PATIENT")),
            assign_reviewer=_is_enabled(secrets.get("ENABLE_ASSIGN_REVIEWER")),
            prefill_templates=_is_enabled(secrets.get("ENABLE_PREFILL_TEMPLATES")),
            channel_fax=channel_fax,
            channel_document_upload=_is_enabled(secrets.get("ENABLE_CHANNEL_DOCUMENT_UPLOAD")),
            channel_integration_engine=_is_enabled(secrets.get("ENABLE_CHANNEL_INTEGRATION_ENGINE")),
            channel_patient_portal=_is_enabled(secrets.get("ENABLE_CHANNEL_PATIENT_PORTAL")),
        )
