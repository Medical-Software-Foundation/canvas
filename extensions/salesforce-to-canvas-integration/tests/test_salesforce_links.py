"""Tests for the shared Salesforce record URL builder.

The builder is pure, so these run without a database. They also pin that the
admin Synced wrapper still produces the unchanged Lightning URL, so the chart
button and the Synced column cannot drift apart.
"""

from __future__ import annotations

from salesforce_to_canvas_integration.services.salesforce_links import (
    build_salesforce_record_url,
)

_INSTANCE = "https://example.my.salesforce.com"


def test_lightning_url_when_source_object_known() -> None:
    """A known source object yields the exact Lightning record URL."""
    url = build_salesforce_record_url(_INSTANCE, "003ABC", "Contact")

    assert url == f"{_INSTANCE}/lightning/r/Contact/003ABC/view"


def test_bare_redirect_when_no_source_object() -> None:
    """No source object falls back to the id prefix redirect."""
    url = build_salesforce_record_url(_INSTANCE, "003ABC")

    assert url == f"{_INSTANCE}/003ABC"


def test_trailing_slash_on_instance_is_normalized() -> None:
    """A trailing slash on the instance url never doubles in the path."""
    url = build_salesforce_record_url(_INSTANCE + "/", "003ABC", "Lead")

    assert url == f"{_INSTANCE}/lightning/r/Lead/003ABC/view"


def test_empty_when_instance_url_missing() -> None:
    """No instance url means no buildable link, so an empty string."""
    assert build_salesforce_record_url("", "003ABC", "Contact") == ""


def test_empty_when_external_id_missing() -> None:
    """No record id means no buildable link, so an empty string."""
    assert build_salesforce_record_url(_INSTANCE, "", "Contact") == ""


def test_synced_wrapper_output_is_unchanged() -> None:
    """The admin wrapper still defaults to Contact and matches the builder."""
    from salesforce_to_canvas_integration.handlers.status_api import (
        _salesforce_record_url,
    )

    with_object = _salesforce_record_url(_INSTANCE, "Lead", "00QXYZ")
    assert with_object == f"{_INSTANCE}/lightning/r/Lead/00QXYZ/view"

    # An empty source object keeps the historical Contact default.
    defaulted = _salesforce_record_url(_INSTANCE, "", "003ABC")
    assert defaulted == f"{_INSTANCE}/lightning/r/Contact/003ABC/view"

    assert _salesforce_record_url("", "Contact", "003ABC") == ""


def test_no_banned_characters_in_source() -> None:
    """No em dash, en dash, or curly quotes in the builder module source."""
    from pathlib import Path

    import salesforce_to_canvas_integration.services.salesforce_links as mod

    text = Path(mod.__file__).read_text(encoding="utf-8")
    for ch in ("—", "–", "“", "”", "‘", "’"):
        assert ch not in text
