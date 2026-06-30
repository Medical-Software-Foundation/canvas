ENVIRONMENT_DOMAINS = {
    "production": "paytheory.com",
    "sandbox": "paytheorystudy.com",
    "lab": "paytheorylab.com",
}

DEFAULT_ENVIRONMENT = "production"
# Canvas's PayTheory integration is provisioned under the "canvas" partner prefix;
# URLs resolve to https://canvas.sdk.<domain> / https://api.canvas.<domain>. The
# generic "start" prefix does not resolve for Canvas merchants. Override via the
# "paytheory_partner" secret only if your merchant is provisioned elsewhere.
DEFAULT_PARTNER = "canvas"


def get_domain(environment: str) -> str:
    """Return the base domain for the given environment."""
    return ENVIRONMENT_DOMAINS.get(environment, ENVIRONMENT_DOMAINS[DEFAULT_ENVIRONMENT])


def get_sdk_url(partner: str, environment: str) -> str:
    """Return the PayTheory JS SDK URL for the given partner and environment."""
    domain = get_domain(environment)
    return f"https://{partner}.sdk.{domain}/index.js"


def get_api_url(partner: str, environment: str) -> str:
    """Return the PayTheory GraphQL API URL for the given partner and environment."""
    domain = get_domain(environment)
    return f"https://api.{partner}.{domain}/graphql"


def get_token_service_url(partner: str, environment: str) -> str:
    """Return the PayTheory token service URL for the given partner and environment."""
    domain = get_domain(environment)
    return f"https://{partner}.{domain}/pt-token-service/"


def get_tags_static_url(partner: str, environment: str) -> str:
    """Return the PayTheory tags static URL for the given partner and environment."""
    domain = get_domain(environment)
    return f"https://{partner}.tags.static.{domain}"
