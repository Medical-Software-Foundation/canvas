"""Smoke tests for group_therapy.api.modal.build_modal_html (config-driven).

The modal is a large f-string template; these guard against breakage and confirm
the config-driven wiring (fetches /template, renders sections + live questionnaire
controls dynamically) is present.
"""

from group_therapy.api.modal import build_modal_html


def _build(**overrides):
    kwargs = {"logged_in_staff_id": "s1", "logged_in_name": "Dr. A"}
    kwargs.update(overrides)
    return build_modal_html(**kwargs)


def test_modal_returns_html_document():
    html = _build()
    assert html.startswith("<!DOCTYPE html>")
    assert "Group Therapy Session" in html


def test_modal_uses_canvas_brand():
    html = _build()
    assert "family=Lato" in html
    assert "#2185D0" in html       # Canvas blue
    assert "#0096b9" not in html   # off-brand teal absent
    assert "#13133D" not in html   # off-brand navy absent


def test_modal_escapes_admin_scope_key_in_callbacks():
    # admin-set section labels (scopeKey) flow into onclick/oninput callbacks and
    # must be JS-string-escaped to prevent XSS
    html = _build()
    assert "function jsq(" in html
    assert "jsq(scopeKey)" in html
    assert "'\"+scopeKey+\"'" not in html  # never concatenated raw into a callback


def test_modal_is_config_driven():
    html = _build()
    assert "/sessions?date=" in html
    assert "/template?rfv=" in html          # resolves the configured template per session
    assert "renderSharedForm" in html
    assert "qControlsHtml" in html           # live questionnaire renderer
    assert "attendeeQuestionnaires" in html  # collects answers into {code, answers}
    assert "/patients/search" not in html


def test_modal_renders_questionnaire_control_kinds():
    html = _build()
    assert "qRadio" in html      # radio questions
    assert "qCheck" in html      # checkbox questions
    assert "patientSectionHtml" in html


def test_modal_renders_options_sections():
    html = _build()
    assert "optionsHtml" in html   # structured multiple-choice sections
    assert "optionPick" in html


def test_modal_overlay_has_open_chart_links():
    html = _build()
    assert "ov-link" in html
    assert "Open chart" in html


def test_modal_has_no_billing_or_picklist_injection():
    # billing + picklists are config-driven now; not injected into the modal
    html = _build()
    assert 'id="billing-mode"' not in html


def test_modal_injects_identity():
    html = _build(logged_in_staff_id="staff-42", logged_in_name="Aide Jane")
    assert "staff-42" in html
    assert "Aide Jane" in html


def test_modal_escapes_staff_name_attribute():
    # a staff name with a quote/markup must not break out of the hidden input
    html = _build(logged_in_name='Ev"><script>alert(1)</script>')
    assert '<script>alert(1)' not in html
    assert "Ev&quot;&gt;&lt;script&gt;" in html


def test_modal_has_audit_dupe_and_badge():
    html = _build()
    assert 'id="audit-banner"' in html
    assert 'id="dupe-banner"' in html
    assert "badge-done" in html
    assert ">Documented<" in html


def test_modal_locks_after_documenting():
    html = _build()
    assert "formLocked" in html
    assert "Document another session" in html
    assert "closeOverlay" in html


def test_modal_wires_close_via_message_channel():
    # closeOverlay -> closeModal must signal the host over the INIT_CHANNEL port
    html = _build()
    assert "function closeModal()" in html
    assert "INIT_CHANNEL" in html
    assert "'CLOSE_MODAL'" in html
