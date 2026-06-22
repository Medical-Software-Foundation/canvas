"""Configuration and component-enabling logic for the portal content plugin.

All patient data is read through Canvas SDK data models (no FHIR API, no
credentials). Configuration is limited to which components are surfaced and,
for visits, which note types are eligible for an After Visit Summary.
"""

from __future__ import annotations

from logger import log

# Components that can be toggled via ENABLED_COMPONENTS.
VALID_COMPONENTS = {"imaging", "labs", "visits", "letters"}

# Default: all enabled.
DEFAULT_ENABLED = VALID_COMPONENTS.copy()


class ConfigurationError(Exception):
    """Raised when plugin configuration is invalid."""

    pass


def get_enabled_components(secrets: dict) -> set[str]:
    """Parse ENABLED_COMPONENTS and return the set of enabled components.

    If the secret is empty or missing, all components are enabled.
    """
    config_value = secrets.get("ENABLED_COMPONENTS", "")

    if not config_value or not config_value.strip():
        log.info("ENABLED_COMPONENTS not configured - all components enabled")
        return DEFAULT_ENABLED

    enabled = set()
    for component in config_value.split(","):
        component = component.strip().lower()
        if component in VALID_COMPONENTS:
            enabled.add(component)
        else:
            log.warning(f"Unknown component '{component}' in ENABLED_COMPONENTS - ignoring")

    if not enabled:
        log.warning("No valid components in ENABLED_COMPONENTS - enabling all")
        return DEFAULT_ENABLED

    log.info(f"Enabled components: {enabled}")
    return enabled


def is_component_enabled(component: str, secrets: dict) -> bool:
    """Return True if a specific component is enabled."""
    return component in get_enabled_components(secrets)


def hold_unreviewed_results(secrets: dict) -> bool:
    """If true, hold lab/imaging results from the portal until a provider reviews them."""
    value = (secrets.get("HOLD_UNREVIEWED_RESULTS") or "").strip().lower()
    return value in ("1", "true", "yes", "on")


def validate_visits_configuration(secrets: dict) -> None:
    """Validate visits-specific configuration (NOTE_TYPES).

    Call this only from visit endpoints. Fails closed: with no NOTE_TYPES
    configured, no visit notes are eligible for an After Visit Summary.
    """
    note_types = secrets.get("NOTE_TYPES", "")
    parsed = [nt.strip() for nt in note_types.split(",") if nt.strip()]
    if not parsed:
        raise ConfigurationError(
            "Visit notes require additional configuration. "
            "Please contact your administrator."
        )
