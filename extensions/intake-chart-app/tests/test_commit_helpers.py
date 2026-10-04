"""Tests for the IntakeAPI commit helpers (originate / edit dispatch)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from intake_chart_app.api.intake_api import (
    _all_rows_confirmed,
    _commit_single_section,
    _safe_canvas_origin,
)
from intake_chart_app.data import form_state
from intake_chart_app.data.single_command_sections import VitalsSection


def test_commit_skips_section_when_draft_empty(fake_hubs, note_uuid):
    section = VitalsSection()
    effects, error = _commit_single_section(
        note_uuid, section, form_state.FormStateSnapshot(note_uuid),
    )
    assert effects == []
    assert error is None


def test_commit_originates_when_no_existing_uuid(fake_hubs, note_uuid):
    section = VitalsSection()
    form_state.set_section(
        note_uuid,
        section.section_id,
        {"blood_pressure_systole": 120, "blood_pressure_diastole": 80},
    )
    snapshot = form_state.FormStateSnapshot(note_uuid)
    with patch(
        "intake_chart_app.api.intake_api.SINGLE_COMMAND_SECTIONS",
        [section],
    ), patch.object(section, "command_class") as MockCmd:
        instance = MockCmd.return_value
        instance.originate.return_value = MagicMock(name="originate-effect")
        effects, error = _commit_single_section(note_uuid, section, snapshot)

    assert error is None
    assert len(effects) == 1
    # First positional was a generated UUID; verify originate(), not edit().
    instance.originate.assert_called_once()
    instance.edit.assert_not_called()
    call_kwargs = MockCmd.call_args.kwargs
    assert call_kwargs["note_uuid"] == note_uuid
    assert call_kwargs["blood_pressure_systole"] == 120
    assert call_kwargs["blood_pressure_diastole"] == 80
    assert "command_uuid" in call_kwargs

    # Snapshot has staged the new UUID for the section (in-session view).
    assert snapshot.get_originated_command(section.section_id) == call_kwargs["command_uuid"]
    # But the hub is untouched until flush() (all-or-nothing semantics —
    # commit() flushes only after the failures gate passes).
    assert form_state.get_originated_command(note_uuid, section.section_id) is None
    snapshot.flush()
    assert (
        form_state.get_originated_command(note_uuid, section.section_id)
        == call_kwargs["command_uuid"]
    )


def test_commit_edits_when_existing_uuid_recorded(fake_hubs, note_uuid):
    section = VitalsSection()
    form_state.set_originated_command(note_uuid, section.section_id, "vitals-1")
    form_state.set_section(note_uuid, section.section_id, {"pulse": 70})

    with patch.object(section, "command_class") as MockCmd:
        instance = MockCmd.return_value
        instance.edit.return_value = MagicMock(name="edit-effect")
        effects, error = _commit_single_section(
            note_uuid, section, form_state.FormStateSnapshot(note_uuid),
        )

    assert error is None
    assert len(effects) == 1
    instance.edit.assert_called_once()
    instance.originate.assert_not_called()
    MockCmd.assert_called_once_with(
        note_uuid=note_uuid, command_uuid="vitals-1", pulse=70,
    )


def test_commit_returns_error_when_command_validation_fails(fake_hubs, note_uuid):
    section = VitalsSection()
    form_state.set_section(note_uuid, section.section_id, {"pulse": 70})

    with patch.object(section, "command_class") as MockCmd:
        MockCmd.side_effect = ValueError("pulse out of range")
        effects, error = _commit_single_section(
            note_uuid, section, form_state.FormStateSnapshot(note_uuid),
        )

    assert effects == []
    assert error == {"section": "vitals", "error": "pulse out of range"}
    # Failure must NOT record a command_uuid — re-commit should retry as originate.
    assert form_state.get_originated_command(note_uuid, section.section_id) is None


def test_commit_skips_section_when_build_kwargs_empty_after_coercion(
    fake_hubs, note_uuid,
):
    """Garbage-only draft (e.g. all empty strings) should skip emission."""
    section = VitalsSection()
    form_state.set_section(
        note_uuid, section.section_id,
        {"pulse": "", "height": None, "weight_lbs": "  "},
    )
    with patch.object(section, "command_class") as MockCmd:
        effects, error = _commit_single_section(
            note_uuid, section, form_state.FormStateSnapshot(note_uuid),
        )

    assert effects == []
    assert error is None
    MockCmd.assert_not_called()


# ---------------------------------------------------------------------------
# _all_rows_confirmed (drives the Mark-as-reviewed dispatch)
# ---------------------------------------------------------------------------


def test_all_rows_confirmed_true_for_default_action():
    rows = {"r1": {"action": "confirm"}, "r2": {"action": "confirm"}}
    assert _all_rows_confirmed(rows) is True


def test_all_rows_confirmed_true_when_action_missing():
    """Missing action defaults to confirm."""
    assert _all_rows_confirmed({"r1": {}}) is True
    assert _all_rows_confirmed({"r1": {"values": {"x": 1}}}) is True


def test_all_rows_confirmed_false_when_any_row_acts():
    assert _all_rows_confirmed({"r1": {"action": "confirm"}, "r2": {"action": "edit"}}) is False
    assert _all_rows_confirmed({"r1": {"action": "remove"}}) is False
    assert _all_rows_confirmed({"r1": {"action": "add"}}) is False


def test_all_rows_confirmed_case_insensitive():
    assert _all_rows_confirmed({"r1": {"action": "CONFIRM"}}) is True
    assert _all_rows_confirmed({"r1": {"action": "Edit"}}) is False


def test_all_rows_confirmed_handles_non_dict_row_payloads():
    """Defensive: if a row's payload isn't a dict, treat as confirm."""
    assert _all_rows_confirmed({"r1": "garbage"}) is True


# ---------------------------------------------------------------------------
# _safe_canvas_origin — Host-suffix allowlist for the cookie-bearing
# ChartSectionReview side-channel POST. Without this guard, a malicious
# Host header could redirect the staff session cookie to an attacker's
# server when the ``canvas-instance-origin`` secret is unset.
# ---------------------------------------------------------------------------


def test_safe_origin_prefers_secret_when_set():
    assert (
        _safe_canvas_origin("https://example.canvasmedical.com", "evil.com")
        == "https://example.canvasmedical.com"
    )


def test_safe_origin_strips_trailing_slash_from_secret():
    assert (
        _safe_canvas_origin("https://example.canvasmedical.com/", "")
        == "https://example.canvasmedical.com"
    )


def test_safe_origin_falls_back_to_host_when_canvas_suffix():
    assert (
        _safe_canvas_origin("", "tenant.canvasmedical.com")
        == "https://tenant.canvasmedical.com"
    )


def test_safe_origin_strips_port_only_for_suffix_check():
    """Port is irrelevant to suffix matching but should remain on the URL."""
    assert (
        _safe_canvas_origin("", "tenant.canvasmedical.com:443")
        == "https://tenant.canvasmedical.com:443"
    )


def test_safe_origin_rejects_non_canvas_host():
    """The whole point of the allowlist: a malicious Host must not steer
    the cookie POST off-instance."""
    assert _safe_canvas_origin("", "evil.com") == ""
    assert _safe_canvas_origin("", "canvasmedical.com.evil.com") == ""


def test_safe_origin_returns_empty_when_both_inputs_blank():
    assert _safe_canvas_origin("", "") == ""
    assert _safe_canvas_origin("   ", "  ") == ""


def test_safe_origin_rejects_ipv6_literal_host():
    """IPv6 literals (``[::1]:8080``) aren't Canvas instances; the urlsplit
    path peels the brackets correctly so a naive ``split(':')`` rule can't
    misclassify them."""
    assert _safe_canvas_origin("", "[::1]:8080") == ""
    assert _safe_canvas_origin("", "[2001:db8::1]") == ""


def test_safe_origin_rejects_unparseable_host():
    """Garbage Host header → empty origin (review POST skipped)."""
    assert _safe_canvas_origin("", "   :   ") == ""


# ---------------------------------------------------------------------------
# _commit_questionnaire_section
# ---------------------------------------------------------------------------


def _make_response_option(dbid: int, value: str, name: str) -> MagicMock:
    """Build a ResponseOption-shaped mock that matches a radio question's
    options list. add_response(option=...) tests by identity, so we return
    the same instance the section will pass through."""
    opt = MagicMock()
    opt.dbid = dbid
    opt.value = value
    opt.name = name
    return opt


def _make_radio_question(code: str, options: list) -> MagicMock:
    q = MagicMock()
    q.coding = {"code": code, "system": "INTERNAL"}
    q.options = options
    q.type = "SING"
    return q


def _make_text_question(code: str) -> MagicMock:
    q = MagicMock()
    q.coding = {"code": code, "system": "INTERNAL"}
    # A bundled TXT question carries a placeholder option (to satisfy the
    # YAML schema's responses ``minItems: 1``). Mirror that here so this
    # fixture exercises the type-based dispatch the reconciler does — a
    # presence-check on ``options`` would route TXT picks through the radio
    # branch and lose the answer.
    placeholder = MagicMock()
    placeholder.value = ""
    placeholder.name = "TXT"
    q.options = [placeholder]
    q.type = "TXT"
    return q


def test_commit_questionnaire_skips_when_draft_empty(fake_hubs, note_uuid):
    from intake_chart_app.api.intake_api import _commit_questionnaire_section
    from intake_chart_app.data.single_command_sections import SocialHistorySection

    section = SocialHistorySection()
    effects, error = _commit_questionnaire_section(
        note_uuid, section, form_state.FormStateSnapshot(note_uuid),
    )
    assert effects == []
    assert error is None


@patch("intake_chart_app.api.intake_api.Questionnaire")
def test_commit_questionnaire_skips_when_questionnaire_not_installed(
    MockQuestionnaire, fake_hubs, note_uuid,
):
    """If the bundled YAML's Questionnaire row isn't on this instance yet
    (or was deleted), the helper logs a warning and returns no effects."""
    from intake_chart_app.api.intake_api import _commit_questionnaire_section, _questionnaire_id_cache
    from intake_chart_app.data import form_state
    from intake_chart_app.data.single_command_sections import SocialHistorySection

    _questionnaire_id_cache.clear()
    section = SocialHistorySection()
    form_state.set_section(note_uuid, section.section_id, {"alcohol": "former"})
    MockQuestionnaire.objects.filter.return_value.order_by.return_value.first.return_value = None

    effects, error = _commit_questionnaire_section(
        note_uuid, section, form_state.FormStateSnapshot(note_uuid),
    )
    assert effects == []
    assert error is None


@patch("intake_chart_app.api.intake_api.Questionnaire")
def test_commit_questionnaire_originates_first_save(
    MockQuestionnaire, fake_hubs, note_uuid,
):
    """First save on a fresh note: originate() + edit(), with one
    add_response per filled answer. Returns TWO effects."""
    from intake_chart_app.api.intake_api import _commit_questionnaire_section, _questionnaire_id_cache
    from intake_chart_app.data import form_state
    from intake_chart_app.data.single_command_sections import SocialHistorySection

    _questionnaire_id_cache.clear()
    section = SocialHistorySection()
    form_state.set_section(note_uuid, section.section_id, {
        "alcohol": "former",
        "tobacco": "never",
        "drugs": "never",
        "details": "Stopped drinking in 2019.",
    })

    questionnaire_row = MagicMock(id="q-uuid-abc")
    MockQuestionnaire.objects.filter.return_value.order_by.return_value.first.return_value = (
        questionnaire_row
    )

    never_opt = _make_response_option(11, "never", "Never")
    former_opt = _make_response_option(12, "former", "Former")
    current_opt = _make_response_option(13, "current", "Current")
    alcohol_q = _make_radio_question(
        "INTAKE_ATOD_ALCOHOL", [never_opt, former_opt, current_opt],
    )
    tobacco_q = _make_radio_question(
        "INTAKE_ATOD_TOBACCO", [never_opt, former_opt, current_opt],
    )
    drugs_q = _make_radio_question(
        "INTAKE_ATOD_DRUGS", [never_opt, former_opt, current_opt],
    )
    details_q = _make_text_question("INTAKE_ATOD_DETAILS")

    snapshot = form_state.FormStateSnapshot(note_uuid)
    with patch.object(section, "command_class") as MockCmd:
        instance = MockCmd.return_value
        instance.questions = [alcohol_q, tobacco_q, drugs_q, details_q]
        instance.originate.return_value = MagicMock(name="originate-effect")
        instance.edit.return_value = MagicMock(name="edit-effect")
        effects, error = _commit_questionnaire_section(
            note_uuid, section, snapshot,
        )

    assert error is None
    assert len(effects) == 2
    instance.originate.assert_called_once()
    instance.edit.assert_called_once()
    alcohol_q.add_response.assert_called_once_with(option=former_opt)
    tobacco_q.add_response.assert_called_once_with(option=never_opt)
    drugs_q.add_response.assert_called_once_with(option=never_opt)
    details_q.add_response.assert_called_once_with(text="Stopped drinking in 2019.")
    call_kwargs = MockCmd.call_args.kwargs
    assert call_kwargs["questionnaire_id"] == "q-uuid-abc"
    assert call_kwargs["note_uuid"] == note_uuid
    # Snapshot has staged the UUID; hub is untouched until flush().
    assert snapshot.get_originated_command(section.section_id) == call_kwargs["command_uuid"]
    assert form_state.get_originated_command(note_uuid, section.section_id) is None
    snapshot.flush()
    assert (
        form_state.get_originated_command(note_uuid, section.section_id)
        == call_kwargs["command_uuid"]
    )


@patch("intake_chart_app.api.intake_api.Questionnaire")
def test_commit_questionnaire_subsequent_save_emits_edit_only(
    MockQuestionnaire, fake_hubs, note_uuid,
):
    """Second commit on the same note: skip originate(), just add_response +
    edit(). Returns ONE effect."""
    from intake_chart_app.api.intake_api import _commit_questionnaire_section, _questionnaire_id_cache
    from intake_chart_app.data import form_state
    from intake_chart_app.data.single_command_sections import SocialHistorySection

    _questionnaire_id_cache.clear()
    section = SocialHistorySection()
    form_state.set_originated_command(note_uuid, section.section_id, "existing-cmd-uuid")
    form_state.set_section(note_uuid, section.section_id, {"alcohol": "current"})

    questionnaire_row = MagicMock(id="q-uuid-abc")
    MockQuestionnaire.objects.filter.return_value.order_by.return_value.first.return_value = (
        questionnaire_row
    )

    current_opt = _make_response_option(13, "current", "Current")
    alcohol_q = _make_radio_question("INTAKE_ATOD_ALCOHOL", [current_opt])

    with patch.object(section, "command_class") as MockCmd:
        instance = MockCmd.return_value
        instance.questions = [alcohol_q]
        instance.edit.return_value = MagicMock(name="edit-effect")
        effects, error = _commit_questionnaire_section(
        note_uuid, section, form_state.FormStateSnapshot(note_uuid),
    )

    assert error is None
    assert len(effects) == 1
    instance.originate.assert_not_called()
    instance.edit.assert_called_once()
    call_kwargs = MockCmd.call_args.kwargs
    assert call_kwargs["command_uuid"] == "existing-cmd-uuid"


@patch("intake_chart_app.api.intake_api.Questionnaire")
def test_commit_questionnaire_logs_and_skips_per_question_failure(
    MockQuestionnaire, fake_hubs, note_uuid,
):
    """A per-question add_response failure (unknown radio value) is caught
    and logged so one malformed answer doesn't kill the whole section save."""
    from intake_chart_app.api.intake_api import _commit_questionnaire_section, _questionnaire_id_cache
    from intake_chart_app.data import form_state
    from intake_chart_app.data.single_command_sections import SocialHistorySection

    _questionnaire_id_cache.clear()
    section = SocialHistorySection()
    form_state.set_section(note_uuid, section.section_id, {
        "alcohol": "former", "tobacco": "garbage-value", "details": "ok",
    })

    questionnaire_row = MagicMock(id="q-uuid-abc")
    MockQuestionnaire.objects.filter.return_value.order_by.return_value.first.return_value = (
        questionnaire_row
    )

    never_opt = _make_response_option(11, "never", "Never")
    former_opt = _make_response_option(12, "former", "Former")
    alcohol_q = _make_radio_question("INTAKE_ATOD_ALCOHOL", [never_opt, former_opt])
    tobacco_q = _make_radio_question("INTAKE_ATOD_TOBACCO", [never_opt, former_opt])
    details_q = _make_text_question("INTAKE_ATOD_DETAILS")

    with patch.object(section, "command_class") as MockCmd:
        instance = MockCmd.return_value
        instance.questions = [alcohol_q, tobacco_q, details_q]
        instance.originate.return_value = MagicMock()
        instance.edit.return_value = MagicMock()
        effects, error = _commit_questionnaire_section(
        note_uuid, section, form_state.FormStateSnapshot(note_uuid),
    )

    assert error is None
    alcohol_q.add_response.assert_called_once_with(option=former_opt)
    details_q.add_response.assert_called_once_with(text="ok")
    tobacco_q.add_response.assert_not_called()
    assert len(effects) == 2


@patch("intake_chart_app.api.intake_api.Questionnaire")
def test_commit_questionnaire_validation_failure_returns_error(
    MockQuestionnaire, fake_hubs, note_uuid,
):
    """If the SDK command's constructor raises, the helper returns a failure
    dict so the all-or-nothing top-level commit can refuse to land any effects."""
    from intake_chart_app.api.intake_api import _commit_questionnaire_section, _questionnaire_id_cache
    from intake_chart_app.data import form_state
    from intake_chart_app.data.single_command_sections import SocialHistorySection

    _questionnaire_id_cache.clear()
    section = SocialHistorySection()
    form_state.set_section(note_uuid, section.section_id, {"alcohol": "former"})

    questionnaire_row = MagicMock(id="q-uuid-abc")
    MockQuestionnaire.objects.filter.return_value.order_by.return_value.first.return_value = (
        questionnaire_row
    )

    with patch.object(section, "command_class") as MockCmd:
        MockCmd.side_effect = ValueError("bad questionnaire id")
        effects, error = _commit_questionnaire_section(
        note_uuid, section, form_state.FormStateSnapshot(note_uuid),
    )

    assert effects == []
    assert error == {"section": "social_history", "error": "bad questionnaire id"}
