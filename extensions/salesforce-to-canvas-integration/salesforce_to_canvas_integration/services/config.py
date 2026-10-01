"""Configuration helpers — read plugin secrets with sensible defaults."""

import json
from dataclasses import dataclass, field

DEFAULT_SOURCE_SOBJECT: str = "Contact"

DEFAULT_FIELD_MAPPING: dict[str, dict[str, str]] = {
    "FirstName": {"target": "first_name"},
    "LastName": {"target": "last_name"},
    "Birthdate": {"target": "date_of_birth"},
    "Email": {"target": "email"},
    "Phone": {"target": "phone"},
    "MobilePhone": {"target": "telecom.mobile"},
    "MailingStreet": {"target": "address_line_1"},
    "MailingCity": {"target": "city"},
    "MailingState": {"target": "state"},
    "MailingPostalCode": {"target": "postal_code"},
    "MailingCountry": {"target": "country"},
    "Gender": {"target": "sex_at_birth"},
    "Preferred_Language__c": {"target": "metadata.preferred_language"},
    "Referral_Source__c": {"target": "metadata.referral_source"},
    "MRN__c": {"target": "metadata.mrn"},
}


@dataclass(frozen=True)
class PluginConfig:
    """Strongly-typed view of the plugin's configurable secrets."""

    client_id: str
    client_secret: str
    login_url: str
    webhook_secret: str
    admin_staff_ids: frozenset[str]
    source_sobject: str = DEFAULT_SOURCE_SOBJECT
    field_mapping: dict[str, dict[str, str]] = field(
        default_factory=lambda: DEFAULT_FIELD_MAPPING
    )
    canvas_api_client_id: str = ""
    canvas_api_client_secret: str = ""
    fumage_base_url: str = ""
    # Optional override for the OAuth token host. See journal cnv-928/002. When
    # set, the FHIR client builds the token url from this instead of deriving it
    # from the fumage base, which lets local stacks split FHIR and auth by port.
    canvas_instance_url: str = ""
    # Optional fallback for the Salesforce org base url used to build record
    # links. The live OAuth token's instance_url is authoritative and takes
    # priority. This is read only when no token is present, which keeps the
    # Synced Salesforce column and the chart button link working while
    # disconnected and on local stacks where the plugin cache is not shared.
    salesforce_instance_url: str = ""


class ConfigError(ValueError):
    """Raised when plugin secrets are missing or malformed."""


def _required(secrets: dict[str, str], key: str) -> str:
    value = (secrets.get(key) or "").strip()
    if not value:
        raise ConfigError(f"{key} is not configured")
    return value


def _parse_csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _parse_mapping(raw: str) -> dict[str, dict[str, str]]:
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ConfigError("SF_FIELD_MAPPING_JSON must be a JSON object")
    result: dict[str, dict[str, str]] = {}
    for sf_field_name, spec in parsed.items():
        if not isinstance(spec, dict) or "target" not in spec:
            raise ConfigError(
                f"SF_FIELD_MAPPING_JSON entry for {sf_field_name!r} must contain a target"
            )
        result[str(sf_field_name)] = {str(k): str(v) for k, v in spec.items()}
    return result


def load_config(secrets: dict[str, str]) -> PluginConfig:
    """Build a :class:`PluginConfig` from a plugin's secrets dict."""
    raw_mapping = (secrets.get("SF_FIELD_MAPPING_JSON") or "").strip()
    field_mapping: dict[str, dict[str, str]] = (
        _parse_mapping(raw_mapping) if raw_mapping else DEFAULT_FIELD_MAPPING
    )

    return PluginConfig(
        client_id=_required(secrets, "SF_CLIENT_ID"),
        client_secret=_required(secrets, "SF_CLIENT_SECRET"),
        login_url=_required(secrets, "SF_LOGIN_URL").rstrip("/"),
        webhook_secret=_required(secrets, "SF_WEBHOOK_SECRET"),
        admin_staff_ids=frozenset(_parse_csv(_required(secrets, "SF_ADMIN_STAFF_IDS"))),
        source_sobject=(secrets.get("SF_SOURCE_SOBJECT") or DEFAULT_SOURCE_SOBJECT).strip()
        or DEFAULT_SOURCE_SOBJECT,
        field_mapping=field_mapping,
        canvas_api_client_id=(secrets.get("CANVAS_API_CLIENT_ID") or "").strip(),
        canvas_api_client_secret=(secrets.get("CANVAS_API_CLIENT_SECRET") or "").strip(),
        fumage_base_url=(secrets.get("FUMAGE_BASE_URL") or "").strip().rstrip("/"),
        canvas_instance_url=(secrets.get("CANVAS_INSTANCE_URL") or "").strip().rstrip("/"),
        salesforce_instance_url=(secrets.get("SF_INSTANCE_URL") or "").strip().rstrip("/"),
    )


def secret_field_mapping_set(secrets: dict[str, str]) -> bool:
    """Return True when the install set a non empty ``SF_FIELD_MAPPING_JSON``.

    The Secret field mapping profile is only selectable when this holds. Reading
    presence rather than the parsed value keeps the check cheap and never raises
    on a malformed secret.
    """
    return bool((secrets.get("SF_FIELD_MAPPING_JSON") or "").strip())


def field_mapping_secret(secrets: dict[str, str]) -> dict[str, dict[str, str]] | None:
    """Parse the ``SF_FIELD_MAPPING_JSON`` secret, or None when it is unset.

    Raises :class:`ConfigError` when the secret is set but malformed, the same
    error :func:`load_config` would raise, so callers that want a graceful
    fallback catch it. Avoids :func:`load_config` so an unrelated missing required
    secret never blocks resolving the field map.
    """
    raw = (secrets.get("SF_FIELD_MAPPING_JSON") or "").strip()
    if not raw:
        return None
    return _parse_mapping(raw)


def canvas_fhir_configured(config: PluginConfig) -> bool:
    """Return True when all three Canvas FHIR secrets carry non-empty values.

    The mark inactive route consults this predicate before constructing a
    :class:`CanvasFhirClient` so the operator sees a 503 with a clear message
    naming the missing secrets rather than a downstream auth failure.
    """
    return bool(
        config.canvas_api_client_id
        and config.canvas_api_client_secret
        and config.fumage_base_url
    )


__all__ = (
    "ConfigError",
    "DEFAULT_FIELD_MAPPING",
    "DEFAULT_SOURCE_SOBJECT",
    "PluginConfig",
    "canvas_fhir_configured",
    "field_mapping_secret",
    "load_config",
    "secret_field_mapping_set",
)
