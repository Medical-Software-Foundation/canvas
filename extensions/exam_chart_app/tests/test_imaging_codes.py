"""Unit tests for the imaging-codes catalog helper."""
from __future__ import annotations

from exam_chart_app.data.imaging_codes import get_imaging_codes


def test_default_catalog_returned_when_secret_unset():
    rows = get_imaging_codes(None)
    assert isinstance(rows, list)
    assert rows  # non-empty bundled catalog
    sample = rows[0]
    assert "code" in sample and "label" in sample


def test_default_catalog_returned_when_secret_blank():
    rows = get_imaging_codes("   ")
    assert isinstance(rows, list)
    assert rows


def test_secret_override_uses_each_non_empty_line_as_label():
    """Every line of the secret becomes one entry with empty code (chart's
    own catalog match is by exact label)."""
    secret = (
        "XRAY, chest, 2 views; (CPT: 71046)\n"
        "MRI, brain, without contrast; (CPT: 70551)\n"
        "\n"  # blank line skipped
        "   \n"  # whitespace-only line skipped
        "CT, abdomen and pelvis; (CPT: 74176)\n"
    )
    rows = get_imaging_codes(secret)
    assert rows == [
        {"code": "", "label": "XRAY, chest, 2 views; (CPT: 71046)"},
        {"code": "", "label": "MRI, brain, without contrast; (CPT: 70551)"},
        {"code": "", "label": "CT, abdomen and pelvis; (CPT: 74176)"},
    ]


def test_whitespace_only_secret_falls_back_to_default_catalog():
    """Secret containing only newlines/spaces is treated as unset."""
    default_rows = get_imaging_codes(None)
    assert get_imaging_codes("\n\n   \n") == default_rows
