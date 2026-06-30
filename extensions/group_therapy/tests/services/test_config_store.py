"""Tests for group_therapy.services.config_store."""

import json
from unittest.mock import MagicMock, patch

from group_therapy.services.config_store import (
    _default_document,
    billing_cpt_codes,
    group_rfv_codes,
    load_config,
    save_config,
    template_for_codes,
)

_STORE = "group_therapy.services.config_store.GroupTherapyConfig"


def test_default_document_has_one_group_therapy_template():
    doc = _default_document()
    assert doc["billing_mode"] == "per_participant"
    names = [t["name"] for t in doc["templates"]]
    assert names == ["Group Therapy"]
    tmpl = doc["templates"][0]
    assert tmpl["rfv_codes"] == ["Group_Therapy"]
    assert tmpl["cpt_code"] == "90853"


def test_default_document_seed_is_code_free():
    # portable reference seed: no instance-specific questionnaire/exam codes
    doc = _default_document()
    sections = doc["templates"][0]["sections"]
    assert all(s.get("type") != "questionnaire" for s in sections)
    assert all("code" not in s for s in sections)
    types = {s["label"]: s["type"] for s in sections}
    assert types["Diagnosis"] == "diagnosis"
    assert types["Billing"] == "billing"
    assert types["Plan"] == "free_text"
    assert types["Risk assessment"] == "free_text"


def test_default_document_seeds_multiple_choice_sections():
    sections = _default_document()["templates"][0]["sections"]
    gd = next(s for s in sections if s["label"] == "Group dynamic and process")
    assert gd["type"] == "options" and gd["multi"] is True and "Engaged" in gd["choices"]
    hc = next(s for s in sections if s["label"] == "How session was conducted")
    assert hc["type"] == "options" and hc["multi"] is False and "Virtual" in hc["choices"]




@patch(_STORE)
def test_load_config_returns_stored_payload(mock_model):
    row = MagicMock()
    row.payload = json.dumps({"billing_mode": "per_participant", "templates": []})
    mock_model.objects.filter.return_value.first.return_value = row
    assert load_config()["billing_mode"] == "per_participant"


@patch(_STORE)
def test_load_config_seeds_and_persists_when_empty(mock_model):
    mock_model.objects.filter.return_value.first.return_value = None
    doc = load_config()
    assert [t["name"] for t in doc["templates"]] == ["Group Therapy"]
    mock_model.objects.create.assert_called_once()  # seed persisted


@patch(_STORE)
def test_load_config_reseeds_on_invalid_payload(mock_model):
    row = MagicMock()
    row.payload = "{not valid json"
    mock_model.objects.filter.return_value.first.return_value = row
    doc = load_config()
    assert "templates" in doc


@patch(_STORE)
def test_load_config_degrades_on_read_error(mock_model):
    mock_model.objects.filter.side_effect = AttributeError("boom")
    doc = load_config()
    assert "templates" in doc  # still returns a usable seed


@patch(_STORE)
def test_save_config_updates_existing_row(mock_model):
    row = MagicMock()
    mock_model.objects.filter.return_value.first.return_value = row
    assert save_config({"templates": []}) is True
    assert json.loads(row.payload) == {"templates": []}
    row.save.assert_called_once()
    mock_model.objects.create.assert_not_called()


@patch(_STORE)
def test_save_config_creates_when_no_row(mock_model):
    mock_model.objects.filter.return_value.first.return_value = None
    assert save_config({"templates": []}) is True
    mock_model.objects.create.assert_called_once()


@patch(_STORE)
def test_save_config_returns_false_when_custom_data_unavailable(mock_model):
    # missing namespace/table -> best-effort, never raises
    mock_model.objects.filter.side_effect = Exception("relation does not exist")
    assert save_config({"templates": []}) is False


def test_default_document_has_no_admin_staff():
    # admin access is gated by the ADMIN_STAFF_KEYS plugin variable, not config
    assert "admin_staff" not in _default_document()


def test_group_rfv_codes_unions_template_codes():
    doc = {"templates": [
        {"rfv_codes": ["Group_Therapy", "x"]},
        {"rfv_codes": ["GROUP_SCREENING", "x"]},
    ]}
    assert group_rfv_codes(doc) == ["Group_Therapy", "x", "GROUP_SCREENING"]
    assert group_rfv_codes({}) == []


def test_billing_cpt_codes_collects_per_template_cpts():
    doc = {"templates": [
        {"cpt_code": "90853"},
        {"cpt_code": "90832"},
        {"cpt_code": "90853"},  # duplicate -> collapsed
        {"cpt_code": ""},       # blank -> skipped
        {},                     # missing -> skipped
    ]}
    assert billing_cpt_codes(doc) == ["90853", "90832"]
    assert billing_cpt_codes({}) == []


def test_template_for_codes_matches_and_misses():
    doc = {"templates": [
        {"name": "A", "rfv_codes": ["Group_Therapy"]},
        {"name": "B", "rfv_codes": ["GROUP_SCREENING"]},
    ]}
    assert template_for_codes(doc, ["GROUP_SCREENING"])["name"] == "B"
    assert template_for_codes(doc, ["Group_Therapy", "x"])["name"] == "A"
    assert template_for_codes(doc, ["unknown"]) is None
    assert template_for_codes(doc, []) is None
