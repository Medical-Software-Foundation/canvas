"""Smoke tests for group_therapy.api.admin_modal.build_admin_html."""

from group_therapy.api.admin_modal import build_admin_html


def test_admin_returns_html_document():
    html = build_admin_html()
    assert html.startswith("<!DOCTYPE html>")
    assert "Group Therapy Setup" in html


def test_admin_is_form_based_not_json():
    html = build_admin_html()
    # form controls, fetched config, save via POST - no raw JSON editor
    assert "/admin/config" in html
    assert "/admin/questionnaires" in html
    assert "addTemplate" in html and "addSection" in html
    assert "moveSection" in html          # reorder
    assert "qOptions" in html             # questionnaire picker
    assert "<textarea" not in html        # no raw JSON textarea
    assert "JSON.parse" not in html       # admin never types JSON


def test_admin_offers_all_section_types():
    html = build_admin_html()
    for t in ["free_text", "options", "questionnaire", "diagnosis", "billing", "medications"]:
        assert t in html
    assert "Multiple choice" in html
    assert "Shared" in html and "Per patient" in html  # scope toggle


def test_admin_options_type_has_choices_editor():
    html = build_admin_html()
    assert "choices" in html              # editable choices for Multiple choice
    assert "Single" in html and "Multi" in html  # single/multi toggle


def test_admin_has_no_staff_access_field():
    # admin access is gated by the ADMIN_STAFF_KEYS plugin variable, not the UI
    html = build_admin_html()
    assert 'id="admin-staff"' not in html
    assert "setAdminStaff" not in html
    assert "admin_staff" not in html


def test_admin_uses_canvas_brand():
    html = build_admin_html()
    assert "family=Lato" in html
    assert "#2185D0" in html       # Canvas blue
    assert "#0096b9" not in html   # off-brand teal absent
    assert "#13133D" not in html   # off-brand navy absent
