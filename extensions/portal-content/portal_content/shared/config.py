"""Configuration and component enabling logic for portal content plugin."""

from logger import log

# Valid component types
VALID_COMPONENTS = {"education", "imaging", "labs", "visits"}

# Components that require FHIR API access (CLIENT_ID and CLIENT_SECRET)
FHIR_REQUIRED_COMPONENTS = {"education", "imaging", "labs", "visits"}

# Default: all enabled
DEFAULT_ENABLED = VALID_COMPONENTS.copy()


class ConfigurationError(Exception):
    """Raised when plugin configuration is invalid."""

    pass


def get_enabled_components(secrets: dict) -> set[str]:
    """Parse ENABLED_COMPONENTS secret and return set of enabled components.

    Args:
        secrets: Plugin secrets dict

    Returns:
        Set of enabled component names. If secret is empty/missing, all are enabled.
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
    """Check if a specific component is enabled.

    Args:
        component: Component name (education, imaging, labs, visits)
        secrets: Plugin secrets dict

    Returns:
        True if component is enabled
    """
    return component in get_enabled_components(secrets)


def validate_configuration(secrets: dict) -> None:
    """Validate plugin configuration and raise errors for invalid states.

    This should be called early to detect configuration issues.

    Args:
        secrets: Plugin secrets dict

    Raises:
        ConfigurationError: If configuration is invalid
    """
    enabled = get_enabled_components(secrets)

    # Check if visits is enabled but NOTE_TYPES is not configured
    if "visits" in enabled:
        note_types = secrets.get("NOTE_TYPES", "")
        if not note_types or not note_types.strip():
            raise ConfigurationError(
                "visits component is enabled but NOTE_TYPES secret is not configured. "
                "Please configure NOTE_TYPES with a comma-separated list of note type codes "
                "(e.g., 'office-visit,telemedicine')."
            )

    # Check if any FHIR-requiring component is enabled but credentials are missing
    fhir_enabled = enabled & FHIR_REQUIRED_COMPONENTS
    if fhir_enabled:
        client_id = secrets.get("CLIENT_ID", "")
        client_secret = secrets.get("CLIENT_SECRET", "")

        if not client_id or not client_secret:
            missing = []
            if not client_id:
                missing.append("CLIENT_ID")
            if not client_secret:
                missing.append("CLIENT_SECRET")

            raise ConfigurationError(
                f"Components {fhir_enabled} require FHIR API access but {', '.join(missing)} "
                f"{'is' if len(missing) == 1 else 'are'} not configured. "
                "Please configure CLIENT_ID and CLIENT_SECRET secrets for FHIR API authentication."
            )

    log.info("Configuration validation passed")
