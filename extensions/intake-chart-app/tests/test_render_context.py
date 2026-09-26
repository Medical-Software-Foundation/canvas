"""Unit tests for the intake template's context-builder helpers."""
from __future__ import annotations

from intake_chart_app.applications.render_context import (
    build_intake_context,
    summarise_allergy,
    summarise_medication,
    summarise_problem,
)


def test_summarise_problem_with_code():
    row = {"id": "u1", "display": "Diabetes mellitus", "code": "E11"}
    assert summarise_problem(row) == "Diabetes mellitus (E11)"


def test_summarise_problem_without_code():
    row = {"id": "u1", "display": "Diabetes mellitus", "code": ""}
    assert summarise_problem(row) == "Diabetes mellitus"


def test_summarise_allergy_with_severity():
    row = {"id": "u1", "allergen": "Penicillin", "severity": "moderate"}
    assert summarise_allergy(row) == "Penicillin — moderate"


def test_summarise_medication_with_sig():
    row = {"id": "u1", "display": "Lisinopril 10mg", "sig": "1 daily"}
    assert summarise_medication(row) == "Lisinopril 10mg — 1 daily"


def test_build_intake_context_problem_rows_have_prefixed_ids():
    chart = {
        "active_conditions": [{"id": "u1", "display": "DM", "code": "E11"}],
        "active_allergies": [],
        "active_medications": [],
        "prior_medical_history": [],
        "prior_surgical_history": [],
        "prior_family_history": [],
        "prior_social_history": None,
    }
    ctx = build_intake_context(
        note_uuid="n1",
        patient_id="p1",
        note_type_name="Office Visit",
        chart=chart,
    )
    rows = ctx["problems_rows"]
    assert len(rows) == 1
    assert rows[0]["row_id"] == "condition:u1"
    assert rows[0]["label"] == "DM (E11)"


def test_render_to_string_smoke():
    """Render the real template against a minimal context and assert the
    structural anchors are present (data-multi-section attrs, the
    intake-config script tag, the vitals form id, the commit button id, the
    note-type pill). A typo in any template that hides a section or breaks
    a JS-keyed anchor gets caught here.

    Bypasses ``canvas_sdk.templates.render_to_string`` (which is gated by a
    ``@plugin_context`` decorator that raises outside a plugin frame) by
    replicating its internal Django-engine wiring against the on-disk
    plugin directory. Mirrors what ``canvas_sdk/templates/utils.py`` does
    at runtime.
    """
    from pathlib import Path

    from django.template.backends.django import get_installed_libraries
    from django.template.engine import Engine

    plugin_dir = Path(__file__).resolve().parent.parent / "intake_chart_app"
    template_path = plugin_dir / "templates" / "intake.html"
    assert template_path.exists(), f"missing template at {template_path}"

    engine = Engine(dirs=[str(plugin_dir)], libraries=get_installed_libraries())

    context = build_intake_context(
        note_uuid="abc-123",
        patient_id="patient-9",
        note_type_name="Office Visit",
        chart={
            "active_conditions": [],
            "active_allergies": [],
            "active_medications": [],
            "prior_medical_history": [],
            "prior_surgical_history": [],
            "prior_family_history": [],
            "prior_social_history": None,
        },
    )
    html = engine.render_to_string(str(template_path), context=context)

    assert 'data-multi-section="problems"' in html
    assert 'data-multi-section="allergies"' in html
    assert 'data-multi-section="medications"' in html
    assert 'data-multi-section="medical_history"' in html
    assert 'data-multi-section="surgical_history"' in html
    assert 'data-multi-section="family_history"' in html
    # ATOD Social History single-command section.
    assert 'id="section-social-history"' in html
    assert 'data-section="social_history"' in html
    assert 'id="form-social_history"' in html
    # The legacy read-only anchor is gone.
    assert 'id="section-prefill-social-history"' not in html
    # The new partial's heading shows the section title.
    assert "Past Medical History" in html
    assert "Surgical" in html and "Procedure History" in html
    assert "Family History" in html
    assert 'id="form-vitals"' in html
    # Per-section Add button labels (specific to each section so the MA
    # reads exactly what they're about to add — not a generic "+ Add").
    assert ">Add diagnosis<" in html
    assert ">Add allergy<" in html
    assert ">Add medication<" in html
    assert ">Add condition<" in html
    assert ">Add procedure<" in html
    assert ">Add family member<" in html
    # The legacy generic label is gone.
    assert "+ Add to draft" not in html
    # Save Draft buttons are removed everywhere (auto-save replaces them).
    assert "Save Draft" not in html
    assert "data-save-section" not in html
    assert "data-save-multi" not in html
    assert 'id="commit-btn"' in html
    assert 'id="intake-config"' in html
    # |json_script renders the dict as JSON; check both spacing variants.
    assert '"note_uuid": "abc-123"' in html or '"note_uuid":"abc-123"' in html
    assert "Office Visit" in html


def test_build_intake_context_history_rows_have_prefixed_ids():
    chart = {
        "active_conditions": [],
        "active_allergies": [],
        "active_medications": [],
        "prior_medical_history": [
            {"id": "u-pmh-1", "summary": "Diabetes type 2 (since 2010)"},
        ],
        "prior_surgical_history": [
            {"id": "u-surg-1", "summary": "Appendectomy (2001)"},
        ],
        "prior_family_history": [
            {"id": "u-fam-1", "summary": "Mother — Rheumatoid arthritis"},
        ],
        "prior_social_history": None,
    }
    ctx = build_intake_context(
        note_uuid="n1", patient_id="p1", note_type_name="Office Visit", chart=chart,
    )
    assert ctx["medical_history_rows"][0]["row_id"] == "medical_history:u-pmh-1"
    assert "Diabetes" in ctx["medical_history_rows"][0]["label"]
    assert ctx["surgical_history_rows"][0]["row_id"] == "surgical_history:u-surg-1"
    assert ctx["family_history_rows"][0]["row_id"] == "family_history:u-fam-1"


def test_build_intake_context_history_add_fields_shapes():
    """The three new add-field configs flow through _field_dicts and carry
    the right kind_prefix so the template renders the matching widget."""
    ctx = build_intake_context(
        note_uuid="n", patient_id="p", note_type_name="X",
        chart={
            "active_conditions": [], "active_allergies": [], "active_medications": [],
            "prior_medical_history": [], "prior_surgical_history": [],
            "prior_family_history": [], "prior_social_history": None,
        },
    )
    # Narrative-style fields are single-line "text" inputs (not "textarea")
    # so the row-based add layout stays compact and the Add button sits
    # aligned with the field's vertical centre rather than
    # being pushed below a tall textarea.
    pmh = {f["id"]: f["kind_prefix"] for f in ctx["medical_history_add_fields"]}
    assert pmh == {
        "medical_history_code": "search",
        "approximate_start_date": "date",
        "approximate_end_date": "date",
        "comments": "text",
    }
    surg = {f["id"]: f["kind_prefix"] for f in ctx["surgical_history_add_fields"]}
    assert surg == {
        "surgical_history_code": "search",
        "approximate_date": "date",
        "comment": "text",
    }
    fam = {f["id"]: f["kind_prefix"] for f in ctx["family_history_add_fields"]}
    assert fam == {
        "relative": "select",
        "family_history_code": "search",
        "note": "text",
    }
    # All three history sections use the same ICD-10 search backend
    # (NLM Clinical Tables) for consistency. Picks submit as plain
    # "<display> (<code>)" free text because the SDK history commands only
    # accept SNOMED / UNSTRUCTURED Coding dicts.
    icd10_fields = [
        next(f for f in ctx["medical_history_add_fields"] if f["id"] == "medical_history_code"),
        next(f for f in ctx["surgical_history_add_fields"] if f["id"] == "surgical_history_code"),
        next(f for f in ctx["family_history_add_fields"] if f["id"] == "family_history_code"),
    ]
    for f in icd10_fields:
        assert f["search_kind"] == "icd10", f"{f['id']} should use ICD-10 search"


def test_atod_questionnaire_yaml_loads_and_has_expected_shape():
    """The bundled YAML must parse and expose the four expected question
    codes with their response options.

    Bypasses ``questionnaire_from_yaml`` (which is gated by
    ``@plugin_context`` and raises outside a plugin frame) and reads the
    on-disk YAML directly. The SDK's ``json_schema()`` helper references a
    schema file (``schemas/questionnaire.json``) that ships in
    canvas-plugins source but not in the installed wheel — so structural
    assertions here cover the same ground (codes, response types, option
    counts) without depending on a file that isn't reliably present."""
    from pathlib import Path

    import yaml

    yaml_path = (
        Path(__file__).resolve().parent.parent
        / "intake_chart_app" / "questionnaires" / "atod_intake.yaml"
    )
    assert yaml_path.exists(), f"missing YAML at {yaml_path}"

    config = yaml.load(yaml_path.read_text(), Loader=yaml.SafeLoader)

    assert config["code"] == "INTAKE_ATOD_V1"
    assert config["code_system"] == "INTERNAL"
    assert config["form_type"] == "SA"
    assert config["display_results_in_social_history_section"] is True
    assert config["can_originate_in_charting"] is True

    questions_by_code = {q["code"]: q for q in config["questions"]}
    assert set(questions_by_code) == {
        "INTAKE_ATOD_ALCOHOL",
        "INTAKE_ATOD_TOBACCO",
        "INTAKE_ATOD_DRUGS",
        "INTAKE_ATOD_DETAILS",
    }
    for code in ("INTAKE_ATOD_ALCOHOL", "INTAKE_ATOD_TOBACCO", "INTAKE_ATOD_DRUGS"):
        q = questions_by_code[code]
        assert q["responses_type"] == "SING"
        response_codes = {r["code"] for r in q["responses"]}
        assert response_codes == {"NEVER", "FORMER", "CURRENT"}
    details = questions_by_code["INTAKE_ATOD_DETAILS"]
    assert details["responses_type"] == "TXT"
    assert len(details["responses"]) >= 1


def test_build_intake_context_includes_atod_form_fields():
    """The four ATOD form fields flow through build_intake_context as
    ``atod_form_fields`` with the right shape: three radio configs (each
    with three options) plus one textarea."""
    from intake_chart_app.applications.render_context import build_intake_context

    ctx = build_intake_context(
        note_uuid="n", patient_id="p", note_type_name="X",
        chart={
            "active_conditions": [], "active_allergies": [], "active_medications": [],
            "prior_medical_history": [], "prior_surgical_history": [],
            "prior_family_history": [], "prior_social_history": None,
        },
    )
    fields_by_id = {f["id"]: f for f in ctx["atod_form_fields"]}
    assert set(fields_by_id) == {"alcohol", "tobacco", "drugs", "details"}
    for substance in ("alcohol", "tobacco", "drugs"):
        assert fields_by_id[substance]["kind"] == "radio"
        assert fields_by_id[substance]["question_code"] == (
            "INTAKE_ATOD_" + substance.upper()
        )
        assert [o["value"] for o in fields_by_id[substance]["options"]] == [
            "never", "former", "current",
        ]
    assert fields_by_id["details"]["kind"] == "textarea"
    assert fields_by_id["details"]["question_code"] == "INTAKE_ATOD_DETAILS"


def test_render_to_string_renders_atod_section_add_only():
    """The ATOD partial renders the four inputs (three radio groups + one
    textarea) and never shows a prior-summary block — the chart's Social
    History sidebar is the source of truth for previously-committed
    answers."""
    from pathlib import Path

    from django.template.backends.django import get_installed_libraries
    from django.template.engine import Engine

    from intake_chart_app.applications.render_context import build_intake_context

    plugin_dir = Path(__file__).resolve().parent.parent / "intake_chart_app"
    template_path = plugin_dir / "templates" / "intake.html"
    engine = Engine(dirs=[str(plugin_dir)], libraries=get_installed_libraries())

    context = build_intake_context(
        note_uuid="abc", patient_id="p", note_type_name="Office Visit",
        chart={
            "active_conditions": [], "active_allergies": [], "active_medications": [],
            "prior_medical_history": [], "prior_surgical_history": [],
            "prior_family_history": [],
        },
    )
    html = engine.render_to_string(str(template_path), context=context)

    assert 'id="section-social-history"' in html
    assert 'name="alcohol"' in html
    assert 'name="tobacco"' in html
    assert 'name="drugs"' in html
    assert 'name="details"' in html
    assert 'value="never"' in html
    assert 'value="former"' in html
    assert 'value="current"' in html
    # No prior-summary block ever — the partial is Add-only.
    assert "Last assessed" not in html
    assert "atod-prior-summary" not in html


def test_build_intake_context_drops_old_history_items_keys():
    """The old flat-string lists are gone — anchor for the regression."""
    ctx = build_intake_context(
        note_uuid="n", patient_id="p", note_type_name="X",
        chart={
            "active_conditions": [], "active_allergies": [], "active_medications": [],
            "prior_medical_history": [], "prior_surgical_history": [],
            "prior_family_history": [], "prior_social_history": None,
        },
    )
    assert "pmh_items" not in ctx
    assert "surgical_items" not in ctx
    assert "family_items" not in ctx
