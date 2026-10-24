"""Tests for the pairing editor page and the access-denied page."""

import json
import re
from typing import Any

import pytest

from questionnaire_followup.api.admin_page import ACCESS_DENIED_HTML, build_admin_html
from questionnaire_followup.api.routes import FollowUpAdminAPI
from questionnaire_followup.services.config_store import COMPARATOR_LABELS, MAX_RULES

_FETCH = re.compile(r"fetch\(BASE \+ '(?P<path>[^']+)'(?:,\s*\{\s*method:\s*'(?P<method>[A-Z]+)')?")


def test_editor_is_a_complete_html_document() -> None:
    """The editor is served whole, not as a fragment."""
    html = build_admin_html()

    assert html.startswith("<!DOCTYPE html>")
    assert html.rstrip().endswith("</html>")
    assert "<title>Questionnaire Follow-Up</title>" in html


def test_editor_calls_this_plugins_api(manifest: dict[str, Any]) -> None:
    """The page's API base is built from the plugin name Canvas routes on."""
    assert f"const BASE = '/plugin-io/api/{manifest['name']}';" in build_admin_html()


def test_every_endpoint_the_editor_calls_is_registered() -> None:
    """Each fetch in the page reaches a route that exists, with the right method."""
    calls = {
        (match.group("method") or "GET", match.group("path"))
        for match in _FETCH.finditer(build_admin_html())
    }
    registered = {
        (method, pattern.pattern)
        for method, routes in FollowUpAdminAPI._ROUTES.items()
        for pattern, _handler in routes
    }

    assert calls == {
        ("GET", "/admin/config"),
        ("GET", "/admin/questionnaires"),
        ("POST", "/admin/config"),
    }
    assert calls <= registered


def test_access_denied_page_explains_how_to_get_access() -> None:
    """A refused user is told which setting grants access."""
    assert ACCESS_DENIED_HTML.startswith("<!DOCTYPE html>")
    assert "Access restricted" in ACCESS_DENIED_HTML
    assert "ADMIN_STAFF_KEYS" in ACCESS_DENIED_HTML


def test_access_denied_page_carries_none_of_the_editor() -> None:
    """The refusal page has no script, so it cannot load or save the config."""
    assert "<script" not in ACCESS_DENIED_HTML
    assert "/admin/config" not in ACCESS_DENIED_HTML


@pytest.mark.parametrize(
    "page",
    [pytest.param(build_admin_html(), id="editor"), pytest.param(ACCESS_DENIED_HTML, id="denied")],
)
def test_pages_load_nothing_from_outside_canvas(page: str) -> None:
    """Opening an admin page inside the EMR makes no request to a third party."""
    assert "http://" not in page
    assert "https://" not in page
    assert "@import" not in page


def test_editor_icons_are_inline_not_an_icon_font() -> None:
    """With no icon font loaded, a leftover ligature span would render as a bare word."""
    assert "material-icons" not in build_admin_html()


def test_editor_enforces_the_same_rule_cap_as_the_server() -> None:
    """The page's limit is filled in from the store, so the two cannot drift apart."""
    html = build_admin_html()

    assert f"const MAX_RULES = {MAX_RULES};" in html


def test_editor_offers_exactly_the_score_rules_the_server_accepts() -> None:
    """The dropdown is built from the store's vocabulary, not a second copy of it."""
    html = build_admin_html()

    assert f"const COMPARATOR_LABELS = {json.dumps(COMPARATOR_LABELS)};" in html
    for label in COMPARATOR_LABELS.values():
        assert label in html


def test_editor_has_no_unsubstituted_placeholders() -> None:
    """A placeholder that reached the browser would be a syntax error in the page."""
    assert not re.findall(r"__[A-Z_]+__", build_admin_html())


def test_editor_asks_for_the_lookback_in_the_agreed_wording() -> None:
    """The sentence reads "within the last N days", not the older phrasing."""
    html = build_admin_html()

    assert "within the last" in html
    assert "on a screen from the last" not in html
