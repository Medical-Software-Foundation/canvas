"""Phase E tests: print template rendering."""

from typing import Any

from nutrition_charting.applications.print_template import (
    _format_date,
    _format_datetime,
    render_print_html,
)


def _payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "patient": {"full_name": "Test Patient", "age": 42, "sex_at_birth": "F",
                    "birth_date": "1984-05-04", "mrn": "100200300"},
        "note": {"note_type_name": "Nutrition Initial",
                 "provider_name": "Test Provider", "provider_npi": "1234567890",
                 "datetime_of_service": "2026-05-04 10:00"},
        "visit_type": "initial",
        "chart": {"missing": False, "pmh": [], "allergies": [],
                  "medications": [], "labs": []},
        "anthropometrics": {"height": "67", "weight": "165", "bmi": "25.8",
                            "ubw": "", "ibw": ""},
        "questionnaires": {
            "social_diet_history": [{"label": "Appetite", "text": "good"}],
            "dietary_intake": [],
            "nfpe": [],
            "nutrition_diagnosis_pes": [
                {"label": "Problem", "text": "Inadequate energy intake"},
            ],
        },
        "estimated_requirements": {"calories": "1800", "protein": "75",
                                   "carbohydrates": "225", "fluid": "2000"},
        "intervention": {
            "educational_materials": ["DASH diet", "Low-FODMAP"],
            "counseling_narrative": "Discussed portion control.",
        },
        "monitoring": {"goals": ["Drink 64oz water/day", "Walk 30 min/day"],
                       "follow_up_date": "2026-06-15", "follow_up_comment": "Recheck A1c"},
        "coordination": {"referrals": ["Refer to GI"],
                         "recommended_labs": ["A1c / HbA1c", "Lipid panel"],
                         "recommended_supplementation": "Vitamin D 2000 IU",
                         "monitor_team_meeting": {"checked": True, "comment": "BG control"}},
        "practice": {"name": "Test Practice", "address": "123 Main St",
                     "phone": "555-1212", "fax": "555-3434"},
    }
    base.update(overrides)
    return base


def test_render_includes_note_type_and_practice_in_header() -> None:
    html = render_print_html(_payload())
    # Home-app pattern: note type appears as the uppercase header-top tag
    # plus in the document <title>; practice name shows in the right-side
    # practice-info block.
    assert "NUTRITION INITIAL" in html
    assert "Test Practice" in html
    assert "123 Main St" in html
    assert "555-1212" in html
    assert "555-3434" in html


def test_render_uses_followup_label_when_visit_type_is_follow_up() -> None:
    """Follow-up notes default to a "Nutrition Follow-up" note type label
    when the note record itself doesn't supply one."""
    payload = _payload(visit_type="follow_up")
    payload["note"] = {**payload["note"], "note_type_name": ""}
    html = render_print_html(payload)
    assert "Follow-up" in html


def test_render_includes_patient_demographics_in_header() -> None:
    html = render_print_html(_payload())
    # Home-app pattern: patient name as the big <h1>-style block, DOB in a
    # bordered badge. Both the .patient-name container and .dob-badge must
    # carry the values.
    assert "Test Patient" in html
    assert 'class="patient-name">Test Patient' in html
    assert 'class="dob-badge"' in html
    # The DOB is reformatted to m/d/y by the template's _format_date helper.
    assert "5/4/84" in html


def test_render_includes_seen_by_provider() -> None:
    html = render_print_html(_payload())
    # Home-app pattern: "Seen by <strong>{provider}</strong> at {practice}"
    assert "Seen by" in html
    assert "Test Provider" in html


def test_render_includes_estimated_requirements_table() -> None:
    html = render_print_html(_payload())
    assert "1800" in html and "kcal/day" in html
    assert "75" in html and "g/day" in html


def test_render_lists_educational_materials_and_goals() -> None:
    html = render_print_html(_payload())
    assert "DASH diet" in html
    assert "Low-FODMAP" in html
    assert "Drink 64oz water/day" in html
    assert "Walk 30 min/day" in html


def test_render_includes_referrals_and_recommended_labs() -> None:
    html = render_print_html(_payload())
    assert "Refer to GI" in html
    assert "A1c / HbA1c" in html
    assert "Lipid panel" in html


def test_render_shows_monitor_team_meeting_yes_with_comment() -> None:
    html = render_print_html(_payload())
    assert "Yes" in html
    assert "BG control" in html


def test_render_suppresses_monitor_block_when_unchecked_and_no_comment() -> None:
    """Empty team-meeting state shouldn't surface a "No" line on every print —
    suppress the whole block when the dietician didn't check the box and
    didn't leave a comment."""
    payload = _payload()
    payload["coordination"]["monitor_team_meeting"] = {"checked": False, "comment": ""}
    html = render_print_html(payload)
    assert "Monitor at next team meeting" not in html
    assert "Monitor at Team Meeting" not in html


def test_render_shows_monitor_block_when_comment_only() -> None:
    """If the dietician left a comment, render the block with the No status
    so the comment isn't orphaned."""
    payload = _payload()
    payload["coordination"]["monitor_team_meeting"] = {
        "checked": False, "comment": "discuss at next meeting",
    }
    html = render_print_html(payload)
    assert "Monitor at next team meeting:</strong> No" in html
    assert "discuss at next meeting" in html


def test_render_auto_prints_on_load() -> None:
    """Home-app pattern: the print dialog fires on window.load so the
    dietician doesn't have to hunt for a Print button."""
    html = render_print_html(_payload())
    assert "window.print()" in html
    assert 'addEventListener("load"' in html
    assert "@media print" in html


def test_render_includes_print_and_close_buttons() -> None:
    """A sticky toolbar above the document header lets the dietician
    re-fire the print dialog after cancelling, or dismiss the modal
    without printing. The toolbar must hide itself on the printed page."""
    html = render_print_html(_payload())
    # Buttons present
    assert 'id="nc-print-btn"' in html
    assert 'id="nc-close-btn"' in html
    # Hidden in print
    assert ".toolbar {" in html and "display: none" in html
    # Close uses Canvas's INIT_CHANNEL message-port handshake to ask the
    # host to dismiss the modal cleanly.
    assert "INIT_CHANNEL" in html
    assert "CLOSE_MODAL" in html


def test_render_escapes_html_in_user_data() -> None:
    payload = _payload()
    payload["intervention"]["counseling_narrative"] = "<script>alert(1)</script>"
    payload["monitoring"]["goals"] = ["<img src=x onerror=alert(1)>"]
    html = render_print_html(payload)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_render_handles_empty_payload_gracefully() -> None:
    """Even with no saved data, the template should still produce a valid
    document with header chrome + footer; ADIME sections are entirely
    suppressed when their content blocks are empty (mirrors home-app's
    pattern of only rendering populated cards)."""
    html = render_print_html({
        "patient": {}, "note": {}, "visit_type": "initial",
        "chart": {"missing": True}, "anthropometrics": {},
        "questionnaires": {}, "estimated_requirements": {},
        "intervention": {}, "monitoring": {}, "coordination": {},
    })
    # Document still renders with the header/footer chrome.
    assert "<title>" in html
    assert "Initial" in html  # default note type when no record
    assert "patient-name" in html
    assert "screen-footer" in html
    # No populated content cards.
    assert 'class="content-block"' not in html


def test_render_does_not_print_none_for_missing_fields() -> None:
    """Defensive: missing optional fields should never surface as the
    string "None" in the document body."""
    payload = _payload()
    payload["patient"]["age"] = None
    payload["note"]["provider_npi"] = ""
    html = render_print_html(payload)
    assert "None" not in html.split("<title>")[0]  # not in head
    assert ">None<" not in html


# ---- MRN ----

def test_render_includes_mrn_in_screen_footer_and_print_running_footer() -> None:
    html = render_print_html(_payload())
    # On-screen footer uses "MRN: 100200300"
    assert "MRN: 100200300" in html
    # Print's @page running footer uses "MRN 100200300" (no colon, comma-list style)
    assert "MRN 100200300" in html


def test_render_omits_mrn_when_blank() -> None:
    payload = _payload()
    payload["patient"]["mrn"] = ""
    html = render_print_html(payload)
    # Should still render — MRN is optional. No "None" should leak through.
    assert "None" not in html.split("<title>")[0]


# ---- Date/time formatting ----

def test_format_datetime_strips_microseconds_and_timezone_noise() -> None:
    """Django emits "2026-05-04 17:30:47.864722+00:00" from DateTimeField
    str(). The dietician saw that raw timestamp on the print and called it
    excessive. Format should be `m/d/yyyy h:MM AM/PM`."""
    out = _format_datetime("2026-05-04 17:30:47.864722+00:00")
    assert ".864722" not in out
    assert "+00:00" not in out
    assert "5/4/2026" in out
    assert "5:30 PM" in out


def test_format_datetime_drops_time_component_at_midnight() -> None:
    """A pure date (e.g. just the appointment day) shouldn't print 12:00 AM."""
    assert _format_datetime("2026-05-04 00:00:00") == "5/4/2026"
    assert _format_datetime("2026-05-04") == "5/4/2026"


def test_format_datetime_returns_blank_for_unparseable_input() -> None:
    assert _format_datetime("") == ""
    assert _format_datetime(None) == ""
    assert _format_datetime("not a date") == ""


def test_format_date_renders_short_year() -> None:
    assert _format_date("1984-05-04") == "5/4/84"


def test_render_renders_date_of_service_short_form() -> None:
    payload = _payload()
    payload["note"]["datetime_of_service"] = "2026-05-04 17:30:47.864722+00:00"
    html = render_print_html(payload)
    assert "5/4/2026 5:30 PM" in html
    assert ".864722" not in html
    assert "+00:00" not in html


# ---- Configurable practice secrets ----

def test_render_omits_practice_block_when_secrets_unset() -> None:
    """When the customer hasn't configured practice-name / -address / -phone /
    -fax secrets, the right-side practice block degrades cleanly — no empty
    "P:  F:" labels surface."""
    payload = _payload()
    payload["practice"] = {"name": "", "address": "", "phone": "", "fax": ""}
    html = render_print_html(payload)
    # The "Seen by ... at <practice>" suffix is dropped when name is blank
    assert "at </span>" not in html
    # No empty P:/F: contact line
    assert "<strong>P:</strong>  &nbsp;" not in html


def test_render_omits_seen_by_practice_suffix_when_only_name_missing() -> None:
    payload = _payload()
    payload["practice"]["name"] = ""
    html = render_print_html(payload)
    # The provider strong tag still appears, but no " at <practice>" suffix
    assert "Test Provider</strong>" in html
    assert "Test Provider</strong> at " not in html


def test_render_includes_only_phone_when_fax_missing() -> None:
    payload = _payload()
    payload["practice"]["fax"] = ""
    html = render_print_html(payload)
    assert "<strong>P:</strong> 555-1212" in html
    assert "<strong>F:</strong>" not in html