"""Tests for the provider-facing picker SimpleAPI.

Verifies:
  - GET /picker filters curated codes against the CDM at modal-open time
  - Empty-state message renders when no codes are currently valid
  - POST /apply emits AddBillingLineItem effects for selected entries
  - POST /apply re-validates against CDM to handle race conditions
  - POST /apply rejects malformed input with 4xx
"""

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.v1.data import ChargeDescriptionMaster

from curated_cpt_picker.models.curated_cpt_code import CuratedCptCode
from curated_cpt_picker.protocols import picker_api as picker_api_module
from curated_cpt_picker.protocols.picker_api import PickerAPI


TODAY = date.today()


@pytest.fixture(autouse=True)
def stub_template_renderer(monkeypatch):
    """render_to_string requires a real plugin runtime. Swap it for a tiny
    renderer that emits enough HTML for the assertions in this module to work.
    """
    def fake_render(template_path: str, context: dict) -> str:
        codes = context.get("codes") or []
        if not codes:
            return "<html><body><p>No curated codes are currently available.</p></body></html>"
        parts = ["<html><body><ul>"]
        for c in codes:
            parts.append(
                f"<li data-id='{c['id']}'>"
                f"<span class='code'>{c['cpt_code']}</span>"
                f"<span class='desc'>{c['description']}</span>"
                f"</li>"
            )
        parts.append("</ul><button id='apply-btn'>Add selected</button></body></html>")
        return "".join(parts)

    monkeypatch.setattr(picker_api_module, "render_to_string", fake_render)


def _make_request(method: str = "GET", query: dict | None = None, body: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        method=method,
        query_params=query or {},
        headers={},
        json=lambda: body or {},
    )


def _make_handler(request: SimpleNamespace) -> PickerAPI:
    handler = PickerAPI.__new__(PickerAPI)
    handler.request = request  # type: ignore[attr-defined]
    handler.secrets = {}  # type: ignore[attr-defined]
    return handler


@pytest.fixture
def active_cdm_codes() -> None:
    """Two codes active in CDM, one expired."""
    ChargeDescriptionMaster.objects.create(
        cpt_code="99213", name="Office 15 min", short_name="Office 15", charge_amount=0,
        effective_date=TODAY - timedelta(days=365), end_date=None,
    )
    ChargeDescriptionMaster.objects.create(
        cpt_code="99214", name="Office 25 min", short_name="Office 25", charge_amount=0,
        effective_date=TODAY - timedelta(days=365), end_date=None,
    )
    ChargeDescriptionMaster.objects.create(
        cpt_code="99499", name="Retired", short_name="Retired", charge_amount=0,
        effective_date=TODAY - timedelta(days=400), end_date=TODAY - timedelta(days=30),
    )


def test_picker_filters_codes_to_currently_valid_cdm(active_cdm_codes) -> None:
    """Curated entries with no active CDM row should be hidden from the modal."""
    CuratedCptCode.objects.create(cpt_code="99213", description="Office 15 min", display_order=1)
    CuratedCptCode.objects.create(cpt_code="99499", description="Retired (stale)", display_order=2)
    CuratedCptCode.objects.create(cpt_code="00000", description="Never in CDM", display_order=3)

    handler = _make_handler(_make_request(query={"note_id": "note-abc"}))
    responses = handler.render_picker()

    assert len(responses) == 1
    body = responses[0].content.decode("utf-8")
    # Active code present
    assert "99213" in body
    assert "Office 15 min" in body
    # Stale and missing codes filtered out
    assert "99499" not in body
    assert "00000" not in body


def test_picker_skips_disabled_entries(active_cdm_codes) -> None:
    CuratedCptCode.objects.create(cpt_code="99213", description="Visible", enabled=True)
    CuratedCptCode.objects.create(cpt_code="99214", description="Hidden", enabled=False)

    handler = _make_handler(_make_request(query={"note_id": "note-abc"}))
    body = handler.render_picker()[0].content.decode("utf-8")

    assert "Visible" in body
    assert "Hidden" not in body


def test_picker_renders_empty_state_when_no_codes_valid() -> None:
    """When every curated entry is invalid, the modal shows the empty-state
    message instead of an empty list of checkboxes."""
    CuratedCptCode.objects.create(cpt_code="00000", description="Never in CDM")

    handler = _make_handler(_make_request(query={"note_id": "note-abc"}))
    body = handler.render_picker()[0].content.decode("utf-8")

    assert "No curated codes are currently available" in body
    assert "Add selected" not in body  # primary action button absent


def test_apply_emits_billing_line_items_for_selected_entries(active_cdm_codes) -> None:
    e1 = CuratedCptCode.objects.create(
        cpt_code="99213",
        description="Office 15 min",
        default_units=1,
        modifiers=[{"code": "25", "system": "http://www.ama-assn.org/go/cpt"}],
    )
    e2 = CuratedCptCode.objects.create(
        cpt_code="99214", description="Office 25 min", default_units=2,
    )

    handler = _make_handler(_make_request(
        method="POST",
        body={"note_id": "note-abc", "selected_ids": [str(e1.pk), str(e2.pk)]},
    ))
    results = handler.apply_codes()

    billing_effects = [r for r in results if hasattr(r, "type") and r.type == EffectType.ADD_BILLING_LINE_ITEM]
    assert len(billing_effects) == 2

    # AddBillingLineItem payload shape: {"note_id": ..., "data": {cpt, units, modifiers, ...}}
    payloads = [json.loads(e.payload) for e in billing_effects]
    cpts_to_units = {p["data"]["cpt"]: p["data"]["units"] for p in payloads}
    assert cpts_to_units == {"99213": 1, "99214": 2}

    e1_payload = next(p for p in payloads if p["data"]["cpt"] == "99213")
    assert e1_payload["data"]["modifiers"] == [{"code": "25", "system": "http://www.ama-assn.org/go/cpt"}]
    assert all(p["note_id"] == "note-abc" for p in payloads)


def test_apply_skips_entries_that_became_invalid_since_modal_opened(active_cdm_codes) -> None:
    """Race condition: modal showed the code, but CDM changed before apply.
    The apply endpoint re-validates and skips."""
    active = CuratedCptCode.objects.create(cpt_code="99213", description="Still active")
    stale = CuratedCptCode.objects.create(cpt_code="99499", description="Now stale")

    handler = _make_handler(_make_request(
        method="POST",
        body={"note_id": "note-abc", "selected_ids": [str(active.pk), str(stale.pk)]},
    ))
    results = handler.apply_codes()

    billing_effects = [r for r in results if hasattr(r, "type") and r.type == EffectType.ADD_BILLING_LINE_ITEM]
    assert len(billing_effects) == 1
    payload = json.loads(billing_effects[0].payload)
    assert payload["data"]["cpt"] == "99213"
    assert payload["note_id"] == "note-abc"

    json_responses = [r for r in results if not hasattr(r, "type")]
    assert len(json_responses) == 1
    body = json.loads(json_responses[0].content)
    assert body["added"] == ["99213"]
    assert body["skipped"] == ["99499"]


def test_apply_rejects_missing_note_id() -> None:
    """Per CLAUDE.md 'fail explicitly on missing required data' — don't write
    'unknown' or empty strings to the billing system."""
    handler = _make_handler(_make_request(
        method="POST",
        body={"selected_ids": ["abc"]},
    ))
    results = handler.apply_codes()
    assert len(results) == 1
    assert results[0].status_code == 400


def test_apply_rejects_empty_selection() -> None:
    handler = _make_handler(_make_request(
        method="POST",
        body={"note_id": "note-abc", "selected_ids": []},
    ))
    results = handler.apply_codes()
    assert len(results) == 1
    assert results[0].status_code == 400


# --- New `selected: [{id, units, modifiers}]` payload shape ---

def test_apply_uses_provider_overrides_for_units_and_modifiers(active_cdm_codes) -> None:
    """When the picker UI lets the provider tweak units/modifiers per row,
    those overrides flow through to AddBillingLineItem — not the admin defaults."""
    entry = CuratedCptCode.objects.create(
        cpt_code="99213",
        description="Office visit",
        default_units=1,
        modifiers=[{"code": "25", "system": "http://www.ama-assn.org/go/cpt"}],
    )

    handler = _make_handler(_make_request(
        method="POST",
        body={
            "note_id": "note-abc",
            "selected": [{
                "id": str(entry.pk),
                "units": 3,
                "modifiers": [
                    {"code": "59", "system": "http://www.ama-assn.org/go/cpt"},
                ],
            }],
        },
    ))
    results = handler.apply_codes()

    billing = [r for r in results if hasattr(r, "type") and r.type == EffectType.ADD_BILLING_LINE_ITEM]
    assert len(billing) == 1
    data = json.loads(billing[0].payload)["data"]
    assert data["units"] == 3
    assert data["modifiers"] == [{"code": "59", "system": "http://www.ama-assn.org/go/cpt"}]


def test_apply_falls_back_to_curated_defaults_when_overrides_missing(active_cdm_codes) -> None:
    """If a row in `selected` omits units/modifiers (or sends garbage), apply
    falls back to the admin-curated defaults rather than rejecting."""
    entry = CuratedCptCode.objects.create(
        cpt_code="99213",
        description="Office visit",
        default_units=2,
        modifiers=[{"code": "25", "system": "http://www.ama-assn.org/go/cpt"}],
    )

    handler = _make_handler(_make_request(
        method="POST",
        body={
            "note_id": "note-abc",
            "selected": [{"id": str(entry.pk), "units": 0, "modifiers": "not-a-list"}],
        },
    ))
    results = handler.apply_codes()

    billing = [r for r in results if hasattr(r, "type") and r.type == EffectType.ADD_BILLING_LINE_ITEM]
    data = json.loads(billing[0].payload)["data"]
    assert data["units"] == 2  # curated default
    assert data["modifiers"] == [{"code": "25", "system": "http://www.ama-assn.org/go/cpt"}]
