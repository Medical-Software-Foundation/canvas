"""Tests for the screening editor page.

These catch the drift that would otherwise only show up on the instance: the
page calling a route that is not registered, the caps disagreeing with the ones
enforced server-side, or a third-party request creeping back in.
"""

import re

from preventive_screenings.api.admin_page import ACCESS_DENIED_HTML, build_admin_html
from preventive_screenings.api.routes import ScreeningAdminAPI
from preventive_screenings.services.config_store import (
    MAX_CODES_PER_SIGNAL,
    MAX_SCREENINGS,
    MAX_SIGNALS_PER_SCREENING,
)

PAGE = build_admin_html()


def test_every_fetch_targets_a_registered_route() -> None:
    """A typo'd URL here is a page that silently cannot load or save."""
    registered = {
        pattern.pattern
        for routes in ScreeningAdminAPI._ROUTES.values()
        for pattern, _handler in routes
    }
    called = set(re.findall(r"fetch\(BASE \+ '([^']+)'", PAGE))

    assert called, "expected the page to call the API"
    assert called <= registered, f"page calls unregistered routes: {called - registered}"


def test_the_page_posts_json_so_the_csrf_check_passes() -> None:
    """The server refuses any other content type; the page has to send this one."""
    assert "'Content-Type': 'application/json'" in PAGE


def test_the_caps_shown_to_the_admin_match_the_ones_enforced() -> None:
    """An editor that lets you add a 41st screening only to have it silently
    dropped on save is worse than one that stops you."""
    assert f"const MAX_SCREENINGS = {MAX_SCREENINGS};" in PAGE
    assert f"const MAX_SIGNALS = {MAX_SIGNALS_PER_SCREENING};" in PAGE
    assert f"const MAX_CODES = {MAX_CODES_PER_SIGNAL};" in PAGE


def test_no_placeholder_survives_into_the_served_page() -> None:
    assert "__MAX_" not in PAGE


def test_pages_load_nothing_from_outside_canvas() -> None:
    """A page that reaches a third party on every open is a patient-data leak
    waiting to be found, and it fails the security review."""
    for page in (PAGE, ACCESS_DENIED_HTML):
        assert "http://" not in page
        assert "https://" not in page.replace('xmlns="http://www.w3.org/2000/svg"', "")
        assert "fonts.googleapis" not in page
        assert "//cdn" not in page


def test_the_page_escapes_what_it_renders() -> None:
    """Screening names and codes are admin-entered and go straight into markup."""
    assert "function esc(s)" in PAGE
    assert "split('<').join('&lt;')" in PAGE


def test_the_defaults_banner_says_they_are_defaults_and_when() -> None:
    """"If defaults ship, make it obvious they are defaults and when they were
    current, so the practice reviews rather than assumes."""
    assert "These screenings are shipped defaults" in PAGE
    assert 'id="defaults-date"' in PAGE


def test_the_access_denied_page_says_what_to_do_about_it() -> None:
    assert "Access restricted" in ACCESS_DENIED_HTML
    assert "ADMIN_STAFF_KEYS" in ACCESS_DENIED_HTML


def test_the_page_has_balanced_script_and_style_tags() -> None:
    for tag in ("script", "style", "html", "body"):
        assert PAGE.count(f"<{tag}") == PAGE.count(f"</{tag}>"), tag


def test_the_editor_states_each_screening_as_a_sentence() -> None:
    """It is how a non-developer verifies the rule says what they meant."""
    assert "function summarize(s)" in PAGE
    assert "class=\"summary\"" in PAGE


def test_the_editor_warns_about_rules_that_can_never_fire() -> None:
    assert "function warnings(s)" in PAGE
    assert "no completion signal" in PAGE or "Nothing counts as done" in PAGE


def test_the_editor_shows_which_codes_a_catalog_entry_matches() -> None:
    """**The answer to "why didn't that count?".**

    Until 2026-09-22 the page was sent only a key, a label and a source, so an
    admin picking "Mammogram" had no way to learn it meant 92 LOINC codes and
    nothing else - and no way to find out why a mammogram recorded with the
    Perform command never cleared the card, short of recording one and watching
    nothing happen. That is precisely the question the client asked us to stop
    needing a developer to answer.
    """
    assert "function vsWhat(key)" in PAGE
    assert "v.systems" in PAGE, "the codes themselves, grouped by terminology"
    assert "v.sources" in PAGE, "and every chart record they are looked for in"
    assert "Counts when any of" in PAGE


def test_the_codes_are_collapsed_rather_than_shouted() -> None:
    """A hundred codes inline on every signal row would bury the rule itself.
    It is the answer to a question, not something to read every time."""
    assert "<details class=\"vswhat\">" in PAGE


# --- the per-screening card toggle --------------------------------------------


def test_the_editor_offers_a_chart_card_toggle_per_screening() -> None:
    """Separate from On/Off because they answer different questions: On decides
    whether the practice tracks the screening, this decides whether it also
    pushes a card onto the chart summary."""
    assert 'data-field="protocol_card"' in PAGE
    assert "Chart card" in PAGE


def test_a_new_screening_starts_without_a_card() -> None:
    """The default the whole change rests on. A screening the admin adds is
    tracked and visible in the record app; the card is something they ask
    for."""
    assert "protocol_card: false" in PAGE


def test_the_card_toggle_is_disabled_while_the_screening_is_off() -> None:
    """A document saying "do not track this, and put it on every chart" is one
    `carded_screenings` reads as off anyway, so the form would be describing
    something the plugin does not do."""
    assert "(s.enabled ? '' : ' disabled')" in PAGE


def test_switching_a_screening_off_also_clears_its_card_toggle() -> None:
    assert "if (!owner.enabled) owner.protocol_card = false;" in PAGE


def test_the_sentence_says_where_the_screening_will_show_up() -> None:
    """It is the thing the Chart card box changes, and it is not obvious from
    the box alone."""
    assert "Shown as a protocol card on the chart" in PAGE
    assert "not as a protocol card" in PAGE


def test_the_missing_order_button_warning_only_fires_for_carded_screenings() -> None:
    """The one-click order button lives on the card, so a tracked screening
    without one is a complete configuration, not a mistake."""
    assert "if (s.protocol_card && !s.order_command)" in PAGE


def test_the_page_explains_the_two_surfaces() -> None:
    """An admin meeting this for the first time has to know that switching a
    card off does not stop the screening being tracked."""
    assert "screening record" in PAGE
    assert "mark" in PAGE and "not applicable" in PAGE


def test_the_code_disclosure_reads_as_english() -> None:
    """"Counts when any of 101 codes appears in a imaging report" reads as a
    bug in a page whose whole job is letting a non-developer check that the
    rule says what they meant."""
    assert "function article(word)" in PAGE
    assert "' appears in ' + article(whereText)" in PAGE
