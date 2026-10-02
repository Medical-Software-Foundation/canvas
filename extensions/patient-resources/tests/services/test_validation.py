"""Link and field validation.

The URL cases are the security-relevant half of this plugin: these strings are
rendered as anchors on a page a patient opens.
"""

import pytest

from patient_resources.constants import (
    LABEL_MAX_CHARS,
    NOTE_MAX_CHARS,
    TITLE_MAX_CHARS,
    URL_MAX_CHARS,
)
from patient_resources.services.validation import (
    is_safe_href,
    normalize_resource,
    note_length_error,
    validate_resource,
)


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "  javascript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD4=",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
        "blob:https://example.org/abc",
    ],
)
def test_dangerous_schemes_are_rejected(url):
    assert is_safe_href(url) is False


def test_protocol_relative_url_is_rejected():
    """The patient-tags version this started from lets these through.

    It splits on the first slash, finds no colon in the empty leading segment and
    treats the value as a relative path. A browser navigates offsite.
    """
    assert is_safe_href("//evil.example/handout") is False


@pytest.mark.parametrize("url", ["/patients/1", "./handout.pdf", "handouts/diabetes"])
def test_relative_paths_are_rejected(url):
    """A public patient resource resolving against the portal origin is a bug."""
    assert is_safe_href(url) is False


def test_url_with_credentials_in_authority_is_rejected():
    """Such a link can display one host and reach another."""
    assert is_safe_href("https://trusted.example@evil.example/x") is False


@pytest.mark.parametrize("url", ["http://example.org/a", "https://example.org/a?b=c#d"])
def test_absolute_http_urls_are_accepted(url):
    assert is_safe_href(url) is True


def test_scheme_without_host_is_rejected():
    assert is_safe_href("https://") is False


@pytest.mark.parametrize("url", ["https://exa\nmple.org", "https://example.org/\tx"])
def test_control_characters_are_rejected(url):
    assert is_safe_href(url) is False


@pytest.mark.parametrize("value", [None, 42, b"https://example.org", []])
def test_non_strings_are_rejected_without_raising(value):
    assert is_safe_href(value) is False


def test_overlong_url_is_rejected():
    assert is_safe_href("https://example.org/" + "a" * URL_MAX_CHARS) is False


# --- validate_resource -----------------------------------------------------


def test_valid_resource_has_no_errors():
    assert validate_resource("Managing diabetes", "https://example.org/d", "Diabetes") == {}


def test_label_is_optional():
    assert validate_resource("Title", "https://example.org/d", "") == {}


@pytest.mark.parametrize("title", ["", "   ", None])
def test_title_is_required(title):
    assert "title" in validate_resource(title, "https://example.org/d", "")


@pytest.mark.parametrize("url", ["", "   ", None])
def test_url_is_required(url):
    assert "url" in validate_resource("Title", url, "")


def test_unsafe_url_reports_against_the_url_field():
    errors = validate_resource("Title", "javascript:alert(1)", "")
    assert set(errors) == {"url"}
    assert "http" in errors["url"]


def test_each_length_cap_reports_against_its_own_field():
    errors = validate_resource(
        "t" * (TITLE_MAX_CHARS + 1),
        "https://example.org/" + "a" * URL_MAX_CHARS,
        "l" * (LABEL_MAX_CHARS + 1),
        "n" * (NOTE_MAX_CHARS + 1),
    )
    assert set(errors) == {"title", "url", "label", "default_note"}


def test_a_note_within_the_cap_passes():
    assert validate_resource("Title", "https://example.org/d", "", "n" * NOTE_MAX_CHARS) == {}


def test_the_note_is_optional():
    assert validate_resource("Title", "https://example.org/d", "") == {}


def test_validate_resource_never_raises_on_odd_input():
    assert validate_resource(object(), object(), object(), object()) != {}


# --- note_length_error -----------------------------------------------------
# The send endpoint reuses this, so the default and the copy a sender edits are
# held to one limit rather than two that can drift.


def test_note_length_error_is_none_within_the_cap():
    assert note_length_error("n" * NOTE_MAX_CHARS) is None


def test_note_length_error_names_the_cap():
    message = note_length_error("n" * (NOTE_MAX_CHARS + 1))
    assert message is not None
    assert str(NOTE_MAX_CHARS) in message


def test_note_length_error_tolerates_none():
    assert note_length_error(None) is None


# --- normalize_resource ----------------------------------------------------


def test_normalize_trims_but_does_not_repair():
    assert normalize_resource(
        "  Title  ", "  https://example.org/a  ", "  Care  ", "  Read this first.  "
    ) == {
        "title": "Title",
        "url": "https://example.org/a",
        "label": "Care",
        "default_note": "Read this first.",
    }
