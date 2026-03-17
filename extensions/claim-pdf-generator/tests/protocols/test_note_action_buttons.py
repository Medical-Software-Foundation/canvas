"""Tests for claim_pdf_generator.protocols.note_action_buttons."""

from unittest.mock import MagicMock, call, patch

import pytest

from claim_pdf_generator.protocols.note_action_buttons import (
    HcfaButton,
    SuperbillButton,
    _generate_pdf_modal_html,
    _get_claim_for_note,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def superbill_handler() -> SuperbillButton:
    handler = SuperbillButton.__new__(SuperbillButton)
    handler.event = MagicMock()
    handler.event.context = {"note_id": "note-abc", "key": "GENERATE_SUPERBILL"}
    handler.secrets = {"timezone": "US/Eastern"}
    return handler


@pytest.fixture
def hcfa_handler() -> HcfaButton:
    handler = HcfaButton.__new__(HcfaButton)
    handler.event = MagicMock()
    handler.event.context = {"note_id": "note-abc", "key": "GENERATE_HCFA"}
    handler.secrets = {"timezone": "US/Eastern"}
    return handler


# ---------------------------------------------------------------------------
# _get_claim_for_note
# ---------------------------------------------------------------------------


def test_get_claim_for_note_found() -> None:
    """Returns the first active claim linked to the given note."""
    mock_claim = MagicMock()
    with patch(
        "claim_pdf_generator.protocols.note_action_buttons.Claim"
    ) as mock_claim_cls:
        mock_claim_cls.objects.filter.return_value.first.return_value = (
            mock_claim
        )

        result = _get_claim_for_note("note-abc")

    assert result is mock_claim
    assert mock_claim_cls.mock_calls == [
        call.objects.filter(note__dbid="note-abc"),
        call.objects.filter().first(),
    ]


def test_get_claim_for_note_not_found() -> None:
    """Returns None when no active claim is linked to the note."""
    with patch(
        "claim_pdf_generator.protocols.note_action_buttons.Claim"
    ) as mock_claim_cls:
        mock_claim_cls.objects.filter.return_value.first.return_value = None

        result = _get_claim_for_note("note-missing")

    assert result is None
    assert mock_claim_cls.mock_calls == [
        call.objects.filter(note__dbid="note-missing"),
        call.objects.filter().first(),
    ]


# ---------------------------------------------------------------------------
# _generate_pdf_modal_html
# ---------------------------------------------------------------------------


def test_generate_pdf_modal_html_claim_not_found() -> None:
    """Returns an error HTML snippet when the claim does not exist."""
    with patch(
        "claim_pdf_generator.protocols.note_action_buttons.Claim"
    ) as mock_claim_cls:
        mock_claim_cls.objects.filter.return_value.first.return_value = None

        result = _generate_pdf_modal_html("bad-id", "superbill", "superbill.html")

    assert "error" in result
    assert "bad-id" in result
    assert mock_claim_cls.mock_calls == [
        call.objects.filter(id="bad-id"),
        call.objects.filter().first(),
    ]


def test_generate_pdf_modal_html_pdf_failure() -> None:
    """Returns an error HTML snippet when pdf_generator returns None."""
    mock_claim = MagicMock()
    mock_claim.id = "claim-xyz"

    with patch(
        "claim_pdf_generator.protocols.note_action_buttons.Claim"
    ) as mock_claim_cls, patch(
        "claim_pdf_generator.protocols.note_action_buttons._build_claim_context"
    ) as mock_ctx, patch(
        "claim_pdf_generator.protocols.note_action_buttons._render_claim_template"
    ) as mock_render, patch(
        "claim_pdf_generator.protocols.note_action_buttons.pdf_generator"
    ) as mock_pdf_gen, patch(
        "claim_pdf_generator.protocols.note_action_buttons.log"
    ) as mock_log:
        mock_claim_cls.objects.filter.return_value.first.return_value = mock_claim
        mock_ctx.return_value = {}
        mock_render.return_value = "<html/>"
        mock_pdf_gen.from_html.return_value = None

        result = _generate_pdf_modal_html("claim-xyz", "superbill", "superbill.html")

    assert "error" in result.lower() or "failed" in result.lower()
    mock_pdf_gen.from_html.assert_called_once_with(content="<html/>")
    mock_log.error.assert_called_with(
        "[NoteActionButton] PDF generation failed for claim claim-xyz"
    )


def test_generate_pdf_modal_html_success_superbill() -> None:
    """Returns HTML with an iframe embedding the PDF when generation succeeds."""
    mock_claim = MagicMock()
    mock_claim.id = "claim-xyz"

    pdf_resp = MagicMock()
    pdf_resp.url = "https://s3.example.com/superbill.pdf"

    with patch(
        "claim_pdf_generator.protocols.note_action_buttons.Claim"
    ) as mock_claim_cls, patch(
        "claim_pdf_generator.protocols.note_action_buttons._build_claim_context"
    ) as mock_ctx, patch(
        "claim_pdf_generator.protocols.note_action_buttons._render_claim_template"
    ) as mock_render, patch(
        "claim_pdf_generator.protocols.note_action_buttons.pdf_generator"
    ) as mock_pdf_gen, patch(
        "claim_pdf_generator.protocols.note_action_buttons.log"
    ):
        mock_claim_cls.objects.filter.return_value.first.return_value = mock_claim
        mock_ctx.return_value = {}
        mock_render.return_value = "<html/>"
        mock_pdf_gen.from_html.return_value = pdf_resp

        result = _generate_pdf_modal_html("claim-xyz", "superbill", "superbill.html")

    assert "https://s3.example.com/superbill.pdf" in result
    assert "<iframe" in result


def test_generate_pdf_modal_html_success_hcfa() -> None:
    """Returns HTML with an iframe embedding the PDF (HCFA)."""
    mock_claim = MagicMock()
    mock_claim.id = "claim-xyz"

    pdf_resp = MagicMock()
    pdf_resp.url = "https://s3.example.com/hcfa.pdf"

    with patch(
        "claim_pdf_generator.protocols.note_action_buttons.Claim"
    ) as mock_claim_cls, patch(
        "claim_pdf_generator.protocols.note_action_buttons._build_claim_context"
    ) as mock_ctx, patch(
        "claim_pdf_generator.protocols.note_action_buttons._render_claim_template"
    ) as mock_render, patch(
        "claim_pdf_generator.protocols.note_action_buttons.pdf_generator"
    ) as mock_pdf_gen, patch(
        "claim_pdf_generator.protocols.note_action_buttons.log"
    ) as mock_log:
        mock_claim_cls.objects.filter.return_value.first.return_value = mock_claim
        mock_ctx.return_value = {}
        mock_render.return_value = "<html/>"
        mock_pdf_gen.from_html.return_value = pdf_resp

        result = _generate_pdf_modal_html("claim-xyz", "hcfa", "hcfa.html")

    assert "https://s3.example.com/hcfa.pdf" in result
    assert "<iframe" in result


# ---------------------------------------------------------------------------
# SuperbillButton.visible()
# ---------------------------------------------------------------------------


def test_superbill_visible_true_when_claim_exists(superbill_handler: SuperbillButton) -> None:
    """visible() returns True when the note has an active claim."""
    with patch(
        "claim_pdf_generator.protocols.note_action_buttons.Claim"
    ) as mock_claim_cls:
        mock_claim_cls.objects.filter.return_value.exists.return_value = True

        result = superbill_handler.visible()

    assert result is True
    assert mock_claim_cls.mock_calls == [
        call.objects.filter(note__dbid="note-abc"),
        call.objects.filter().exists(),
    ]


def test_superbill_visible_false_when_no_claim(superbill_handler: SuperbillButton) -> None:
    """visible() returns False when no active claim exists for the note."""
    with patch(
        "claim_pdf_generator.protocols.note_action_buttons.Claim"
    ) as mock_claim_cls:
        mock_claim_cls.objects.filter.return_value.exists.return_value = False

        result = superbill_handler.visible()

    assert result is False
    assert mock_claim_cls.mock_calls == [
        call.objects.filter(note__dbid="note-abc"),
        call.objects.filter().exists(),
    ]


def test_superbill_visible_false_when_no_note_id(superbill_handler: SuperbillButton) -> None:
    """visible() returns False when note_id is absent from context."""
    superbill_handler.event.context = {}

    with patch(
        "claim_pdf_generator.protocols.note_action_buttons.Claim"
    ) as mock_claim_cls:
        result = superbill_handler.visible()

    assert result is False
    assert mock_claim_cls.mock_calls == []


# ---------------------------------------------------------------------------
# HcfaButton.visible()
# ---------------------------------------------------------------------------


def test_hcfa_visible_true_when_claim_exists(hcfa_handler: HcfaButton) -> None:
    """HcfaButton.visible() returns True when the note has an active claim."""
    with patch(
        "claim_pdf_generator.protocols.note_action_buttons.Claim"
    ) as mock_claim_cls:
        mock_claim_cls.objects.filter.return_value.exists.return_value = True

        result = hcfa_handler.visible()

    assert result is True
    assert mock_claim_cls.mock_calls == [
        call.objects.filter(note__dbid="note-abc"),
        call.objects.filter().exists(),
    ]


def test_hcfa_visible_false_when_no_note_id(hcfa_handler: HcfaButton) -> None:
    """HcfaButton.visible() returns False when note_id is absent from context."""
    hcfa_handler.event.context = {}

    with patch(
        "claim_pdf_generator.protocols.note_action_buttons.Claim"
    ) as mock_claim_cls:
        result = hcfa_handler.visible()

    assert result is False
    assert mock_claim_cls.mock_calls == []


# ---------------------------------------------------------------------------
# SuperbillButton.handle()
# ---------------------------------------------------------------------------


def test_superbill_handle_no_claim(superbill_handler: SuperbillButton) -> None:
    """handle() returns an error modal when no claim is linked to the note."""
    with patch(
        "claim_pdf_generator.protocols.note_action_buttons._get_claim_for_note"
    ) as mock_get_claim, patch(
        "claim_pdf_generator.protocols.note_action_buttons.log"
    ) as mock_log:
        mock_get_claim.return_value = None

        effects = superbill_handler.handle()

    assert len(effects) == 1
    assert mock_get_claim.mock_calls == [call("note-abc")]
    assert mock_log.mock_calls == [
        call.warning("[SuperbillButton] No claim found for note note-abc")
    ]


def test_superbill_handle_with_claim(superbill_handler: SuperbillButton) -> None:
    """handle() returns a LaunchModalEffect with the PDF link on success."""
    mock_claim = MagicMock()
    mock_claim.id = "claim-xyz"

    with patch(
        "claim_pdf_generator.protocols.note_action_buttons._get_claim_for_note"
    ) as mock_get_claim, patch(
        "claim_pdf_generator.protocols.note_action_buttons._generate_pdf_modal_html"
    ) as mock_html, patch(
        "claim_pdf_generator.protocols.note_action_buttons.log"
    ) as mock_log:
        mock_get_claim.return_value = mock_claim
        mock_html.return_value = "<p>PDF ready</p>"

        effects = superbill_handler.handle()

    assert len(effects) == 1
    # _get_claim_for_note returns a MagicMock, so `if not claim:` calls __bool__()
    assert mock_get_claim.mock_calls == [call("note-abc"), call().__bool__()]
    assert mock_html.mock_calls == [
        call(claim_id="claim-xyz", form_type="superbill", template="superbill.html", tz_name="US/Eastern")
    ]
    assert mock_log.mock_calls == []


# ---------------------------------------------------------------------------
# HcfaButton.handle()
# ---------------------------------------------------------------------------


def test_hcfa_handle_no_claim(hcfa_handler: HcfaButton) -> None:
    """handle() returns an error modal when no claim is linked to the note."""
    with patch(
        "claim_pdf_generator.protocols.note_action_buttons._get_claim_for_note"
    ) as mock_get_claim, patch(
        "claim_pdf_generator.protocols.note_action_buttons.log"
    ) as mock_log:
        mock_get_claim.return_value = None

        effects = hcfa_handler.handle()

    assert len(effects) == 1
    assert mock_get_claim.mock_calls == [call("note-abc")]
    assert mock_log.mock_calls == [
        call.warning("[HcfaButton] No claim found for note note-abc")
    ]


def test_hcfa_handle_with_claim(hcfa_handler: HcfaButton) -> None:
    """handle() returns a LaunchModalEffect with the PDF link on success."""
    mock_claim = MagicMock()
    mock_claim.id = "claim-hcfa-001"

    with patch(
        "claim_pdf_generator.protocols.note_action_buttons._get_claim_for_note"
    ) as mock_get_claim, patch(
        "claim_pdf_generator.protocols.note_action_buttons._generate_pdf_modal_html"
    ) as mock_html, patch(
        "claim_pdf_generator.protocols.note_action_buttons.log"
    ) as mock_log:
        mock_get_claim.return_value = mock_claim
        mock_html.return_value = "<p>HCFA PDF ready</p>"

        effects = hcfa_handler.handle()

    assert len(effects) == 1
    # _get_claim_for_note returns a MagicMock, so `if not claim:` calls __bool__()
    assert mock_get_claim.mock_calls == [call("note-abc"), call().__bool__()]
    assert mock_html.mock_calls == [
        call(claim_id="claim-hcfa-001", form_type="hcfa", template="hcfa.html", tz_name="US/Eastern")
    ]
    assert mock_log.mock_calls == []


# ---------------------------------------------------------------------------
# Handler constants
# ---------------------------------------------------------------------------


def test_superbill_button_constants() -> None:
    """SuperbillButton has the expected class-level constants."""
    from canvas_sdk.handlers.action_button import ActionButton

    assert SuperbillButton.BUTTON_TITLE == "Superbill"
    assert SuperbillButton.BUTTON_KEY == "GENERATE_SUPERBILL"
    assert SuperbillButton.BUTTON_LOCATION == ActionButton.ButtonLocation.NOTE_HEADER
    assert SuperbillButton.PRIORITY == 10


def test_hcfa_button_constants() -> None:
    """HcfaButton has the expected class-level constants."""
    from canvas_sdk.handlers.action_button import ActionButton

    assert HcfaButton.BUTTON_TITLE == "CMS-1500"
    assert HcfaButton.BUTTON_KEY == "GENERATE_HCFA"
    assert HcfaButton.BUTTON_LOCATION == ActionButton.ButtonLocation.NOTE_HEADER
    assert HcfaButton.PRIORITY == 11
