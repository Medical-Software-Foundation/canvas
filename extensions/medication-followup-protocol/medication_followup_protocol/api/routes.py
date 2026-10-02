"""Where the plugin's own pages live, in one place.

Every surface composes its address from these rather than writing the prefix out, so the
plugin name and the API prefix appear once each.
"""

import datetime

#: The manifest name, which is what the platform mounts the API under.
PLUGIN_NAME = "medication_followup_protocol"

#: The SimpleAPI prefix, without the leading slash in the composed address.
PREFIX = "/programme"

#: One value for the life of this deployed build, computed once at import rather than
#: per request, so every address this module hands out stays the same for as long as
#: the process does and only changes on the next deploy.
_CACHE_BUST = str(int(datetime.datetime.now(datetime.timezone.utc).timestamp()))


def page(path: str) -> str:
    """The address of one of this plugin's pages.

    An empty path returns the bare prefix, the one every template builds every other
    address on top of, both server side for the design system's own assets and client
    side for every fetch call a page makes, so it carries no version of its own. A
    version query in the middle of an address would break everything a caller appends
    after it, and a prefix is exactly what every empty path call exists to be.

    A path that names something carries the build's version instead, joined with an
    ampersand when the path already carries a query string of its own and with a
    question mark otherwise, so every page address this helper hands to
    LaunchModalEffect busts the browser's cache on each deploy with no caller having
    to remember to add that itself, this one included.
    """
    address = f"/plugin-io/api/{PLUGIN_NAME}{PREFIX}{path}"
    if not path:
        return address
    separator = "&" if "?" in path else "?"
    return f"{address}{separator}v={_CACHE_BUST}"
