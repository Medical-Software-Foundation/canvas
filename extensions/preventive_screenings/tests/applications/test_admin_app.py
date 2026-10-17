"""Tests for the app-drawer entry point.

Checks the class against what the manifest tells Canvas, which is drift that
would otherwise only surface as a broken icon on the instance.
"""

import json
import re
import re
from pathlib import Path
from typing import Any

from canvas_sdk.effects.launch_modal import LaunchModalEffect

from preventive_screenings.api.routes import ScreeningAdminAPI
from preventive_screenings.applications.admin_app import ScreeningAdminApplication


def opened() -> dict:
    """The launch effect's data block."""
    effect = ScreeningAdminApplication(event=None).on_open()
    payload: dict = json.loads(effect.payload)["data"]
    return payload


def test_opening_the_app_launches_the_editor_as_a_page() -> None:
    assert opened()["target"] == LaunchModalEffect.TargetType.PAGE.value


def test_the_launched_url_is_a_registered_route() -> None:
    """A typo here is an app-drawer icon that opens nothing."""
    url = opened()["url"]
    path = url.split("?")[0].removeprefix("/plugin-io/api/preventive_screenings")
    registered = {
        pattern.pattern
        for routes in ScreeningAdminAPI._ROUTES.values()
        for pattern, _handler in routes
    }

    assert path in registered


def test_the_url_is_cache_busted_so_redeploys_are_not_served_stale() -> None:
    assert re.search(r"\?v=\d+$", opened()["url"])


def test_the_manifest_points_at_this_class(manifest: dict[str, Any]) -> None:
    application = manifest["components"]["applications"][0]

    assert application["class"] == (
        "preventive_screenings.applications.admin_app:ScreeningAdminApplication"
    )
    assert application["scope"] == "global"


def test_the_manifest_declares_the_custom_data_namespace(manifest: dict[str, Any]) -> None:
    """Without this the CustomModel table is never created and every save fails."""
    assert manifest["custom_data"] == {
        "namespace": "canvas_medical__preventive_screenings",
        "access": "read_write",
    }


def test_the_manifest_declares_the_admin_variable_defaulting_to_empty(
    manifest: dict[str, Any],
) -> None:
    """Access fails closed, and a shipped default key would be a back door in
    every practice that installs this."""
    variables = {variable["name"]: variable for variable in manifest["variables"]}

    assert variables["ADMIN_STAFF_KEYS"]["default"] == ""


# Nothing that is only true of the instance this plugin was built against may
# ship: another practice installs this and gets a blank slate.
#
# **Patterns rather than literal names, deliberately.** This list used to name
# the build instance and the GitHub account that built it - which meant the
# test guarding against publishing those published them itself, into the one
# repository it existed to keep them out of. These catch the durable classes
# instead, so the guard works in any copy of this plugin and names nobody.
INSTANCE_SPECIFIC = (
    # A specific Canvas instance. Documentation links are not one.
    #
    # The left-hand lookbehind is load-bearing: with only the lookahead, a
    # rejected "docs.canvasmedical.com" still matches one character along, at
    # "ocs.canvasmedical.com". Anchoring to a non-word character kills that.
    re.compile(r"(?<![\w.-])(?!docs\.|www\.)[a-z0-9-]+\.canvasmedical\.com", re.I),
    # Credentials, or the names of the places they live.
    re.compile(r"client_secret|root_password|BEGIN [A-Z ]*PRIVATE KEY"),
    # A developer's machine.
    re.compile(r"/Users/|/home/[a-z]"),
    # A real staff key written into source rather than set per instance.
    re.compile(r"ADMIN_STAFF_KEYS\s*[=:]\s*[\"\'][^\"\']+"),
)

# Checked by hand before a public release as well, against the specific
# instance name and account that built this - those cannot be patterns, and
# writing them here is what the comment above warns about. See CLAUDE.md.


def test_the_manifest_ships_no_instance_specific_data(manifest: dict[str, Any]) -> None:
    """Another practice installs this and gets a blank slate: no staff keys, no
    hostnames, nothing from the instance it was built against."""
    text = json.dumps(manifest)

    for pattern in INSTANCE_SPECIFIC:
        assert not pattern.search(text), f"manifest leaks {pattern.pattern}"


def test_the_source_ships_no_instance_specific_data() -> None:
    """The manifest was never the only thing that ships.

    A measurement taken on the build instance is worth recording; the
    instance's name is not, and a comment naming it goes straight into the
    public plugins repo with everything else.

    **Scans the tests too, not just the package.** A real screening id copied
    off the build instance sat in `tests/services/test_completion.py` for
    weeks, because this only ever looked at `preventive_screenings/` - and the
    tests ship with everything else.
    """
    container = Path(__file__).resolve().parents[2]
    mine = Path(__file__).resolve()
    offenders = [
        f"{path.relative_to(container)}: {pattern.pattern}"
        for folder in ("preventive_screenings", "tests")
        for path in sorted((container / folder).rglob("*"))
        # Dot-directories never ship: `canvas install` drops any path with a
        # component starting with "." (verified in the CLI, 0.226.1), which is
        # what keeps the CPA workflow artifacts - a full session transcript -
        # out of the package and out of git.
        if not any(part.startswith(".") for part in path.parts)
        and path.suffix in {".py", ".md", ".json"}
        and path.resolve() != mine
        for pattern in INSTANCE_SPECIFIC
        if pattern.search(path.read_text())
    ]

    assert not offenders, "source ships instance-specific data: " + ", ".join(offenders)
