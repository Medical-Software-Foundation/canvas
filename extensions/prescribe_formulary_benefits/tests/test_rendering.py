"""Tests for the custom-HTML rendering: escaping, None-guards, and benefit detail."""

from __future__ import annotations

from types import SimpleNamespace

from prescribe_formulary_benefits.rendering import (
    render_benefits,
    render_error,
    render_loading,
    render_no_active_coverage,
    render_no_coverage,
    render_rejected,
)


def _coverage(**kwargs):
    defaults = {
        "pbm_name": "PBMF",
        "payer_id": "P1",
        "formulary_status": "On-Formulary/Non-Preferred",
        "prior_authorization_required": False,
        "step_therapy_required": False,
        "quantity_limits": [],
        "copays": ["Tier 1 of 3"],
        "alternatives": [],
        "rejected": False,
        "reject_reason": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _alt(**kwargs):
    defaults = {
        "ndc": "00093512501",
        "description": "benazepril 10 mg tablet",
        "brand_or_generic": "Generic",
        "rx_or_otc": "Rx",
        "formulary_status": "Preferred Level 1",
        "copays": ["Tier 1 of 3"],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# --- transient / empty states ---------------------------------------------


def test_render_loading_mentions_medication() -> None:
    html = render_loading("Lisinopril 10 mg tablet")
    assert "Lisinopril 10 mg tablet" in html
    assert "Checking formulary coverage" in html


def test_render_error_shows_message() -> None:
    html = render_error("Lisinopril", "Pharmacy upstream error")
    assert "Pharmacy upstream error" in html
    assert "Lisinopril" in html


def test_render_escapes_user_facing_text() -> None:
    html = render_error("Drug <x>", "<script>alert(1)</script>")
    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;x&gt;" in html


def test_render_no_coverage() -> None:
    html = render_no_coverage("Amoxicillin")
    assert "No formulary coverage" in html
    assert "Amoxicillin" in html


def test_render_no_active_coverage() -> None:
    html = render_no_active_coverage("Amoxicillin")
    assert "No active pharmacy benefit" in html
    assert "Amoxicillin" in html


def test_render_rejected_lists_reasons() -> None:
    html = render_rejected("Amoxicillin", ["Patient not found", "Coverage expired"])
    assert "was rejected" in html
    assert "Patient not found" in html
    assert "Coverage expired" in html


def test_render_rejected_without_reasons_has_fallback() -> None:
    html = render_rejected("Amoxicillin", [])
    assert "Rejected by plan" in html


# --- benefits detail -------------------------------------------------------


def test_render_benefits_empty_falls_back_to_no_coverage() -> None:
    html = render_benefits("Amoxicillin", [])
    assert "No formulary coverage" in html


def test_render_benefits_renders_summary_cards() -> None:
    coverage = _coverage(
        formulary_status="On-Formulary/Non-Preferred",
        prior_authorization_required=False,
        step_therapy_required=False,
        copays=["Tier 1 of 3"],
    )
    html = render_benefits("Lisinopril 10 mg tablet", [coverage])

    # Header carries the PBM, and the three summary cards are present.
    assert "PBMF" in html
    assert "Formulary status" in html
    assert "On-Formulary/Non-Preferred" in html
    assert "Copay tier" in html
    assert "Tier 1 of 3" in html
    assert "Restrictions" in html
    assert "No PA" in html
    assert "No step therapy" in html


def test_render_benefits_preferred_status_is_green() -> None:
    html = render_benefits("Drug", [_coverage(formulary_status="Preferred Level 1")])
    assert 'class="status good"' in html
    assert "Preferred Level 1" in html


def test_render_benefits_non_preferred_status_stays_neutral() -> None:
    html = render_benefits("Drug", [_coverage(formulary_status="On-Formulary/Non-Preferred")])
    assert 'class="status good"' not in html
    assert 'class="status "' in html
    assert "On-Formulary/Non-Preferred" in html


def test_render_benefits_not_covered_status_is_red() -> None:
    html = render_benefits("Drug", [_coverage(formulary_status="Not Covered")])
    assert 'class="status bad"' in html


def test_render_benefits_unknown_status_is_neutral() -> None:
    html = render_benefits("Drug", [_coverage(formulary_status=None)])
    # Neutral (cream) status has no good/bad modifier.
    assert 'class="status "' in html
    assert "Unknown" in html


def test_render_benefits_alternatives_collapsed_by_default() -> None:
    html = render_benefits("Drug", [_coverage(alternatives=[_alt()])])
    assert '<details class="alts">' in html
    assert 'class="alts" open' not in html


def test_render_benefits_shows_restriction_warnings() -> None:
    coverage = _coverage(
        prior_authorization_required=True,
        step_therapy_required=True,
        quantity_limits=["30 units per 30 days"],
    )
    html = render_benefits("Drug", [coverage])
    assert "PA required" in html
    assert "Step therapy" in html
    assert "30 units per 30 days" in html


def test_render_benefits_alternatives_table_with_enriched_fields() -> None:
    coverage = _coverage(
        alternatives=[
            _alt(),
            _alt(
                ndc="00071052723",
                description="Accupril 5 mg tablet",
                brand_or_generic="Brand",
                formulary_status="Preferred Level 1",
                copays=["Tier 2 of 3", "Tier 3 of 3"],
            ),
        ]
    )
    html = render_benefits("Drug", [coverage])

    assert "Formulary alternatives" in html
    assert "(2)" in html
    assert "benazepril 10 mg tablet" in html
    assert "Accupril 5 mg tablet" in html
    assert "Generic" in html
    assert "Brand" in html
    assert "Preferred Level 1" in html
    # Multiple copay tiers each render as a chip.
    assert "Tier 2 of 3" in html
    assert "Tier 3 of 3" in html


def test_render_benefits_alternative_degrades_without_enriched_fields() -> None:
    # Minimal alternative (only ndc + description): no AttributeError, still lists the drug.
    alt = SimpleNamespace(ndc="00093104801", description="metformin 500 mg tablet")
    html = render_benefits("Drug", [_coverage(alternatives=[alt])])
    assert "metformin 500 mg tablet" in html
    assert "00093104801" in html


def test_render_benefits_no_alternatives_omits_section() -> None:
    html = render_benefits("Drug", [_coverage(alternatives=[])])
    assert "Formulary alternatives" not in html


def test_render_benefits_none_status_does_not_print_none() -> None:
    html = render_benefits("Drug", [_coverage(formulary_status=None)])
    assert "Unknown" in html
    assert ">None<" not in html


def test_render_benefits_rejected_coverage_shows_reason() -> None:
    coverage = _coverage(rejected=True, reject_reason="Not covered under this plan")
    html = render_benefits("Drug", [coverage])
    assert "Not covered under this plan" in html
