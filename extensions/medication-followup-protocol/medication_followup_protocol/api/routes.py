"""Where the plugin's own pages live, in one place.

Every surface composes its address from these rather than writing the prefix out, so the
plugin name and the API prefix appear once each.
"""

#: The manifest name, which is what the platform mounts the API under.
PLUGIN_NAME = "medication_followup_protocol"

#: The SimpleAPI prefix, without the leading slash in the composed address.
PREFIX = "/programme"


def page(path: str) -> str:
    """The address of one of this plugin's pages."""
    return f"/plugin-io/api/{PLUGIN_NAME}{PREFIX}{path}"
