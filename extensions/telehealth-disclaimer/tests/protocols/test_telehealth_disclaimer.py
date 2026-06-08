"""Tests for the TelehealthDisclaimer protocol handler."""

from unittest.mock import MagicMock, call, patch

from telehealth_disclaimer.protocols.telehealth_disclaimer import DEFAULT_DISCLAIMER_TEXT

MODULE = "telehealth_disclaimer.protocols.telehealth_disclaimer"


def _patches():
    """Patch every external dependency the handler touches at module scope."""
    return (
        patch(f"{MODULE}.Note"),
        patch(f"{MODULE}.CustomCommand"),
        patch(f"{MODULE}.render_to_string"),
        patch(f"{MODULE}.uuid"),
        patch(f"{MODULE}.log"),
    )


class TestGuardClauses:
    """compute() returns no effects and touches nothing when gates fail."""

    def test_state_not_new_returns_no_effects(self, handler):
        handler.event.context = {"state": "LOCKED", "note_id": "note-123"}
        p_note, p_cmd, p_render, p_uuid, p_log = _patches()
        with p_note as mock_note, p_cmd as mock_cmd, p_render as mock_render, \
                p_uuid as mock_uuid, p_log as mock_log:
            effects = handler.compute()

            # Gate failed before any dependency was used.
            assert mock_note.mock_calls == []
            assert mock_cmd.mock_calls == []
            assert mock_render.mock_calls == []
            assert mock_uuid.mock_calls == []
            assert mock_log.mock_calls == []
            assert handler.event.mock_calls == []

        assert effects == []

    def test_missing_note_id_returns_no_effects(self, handler):
        handler.event.context = {"state": "NEW"}
        p_note, p_cmd, p_render, p_uuid, p_log = _patches()
        with p_note as mock_note, p_cmd as mock_cmd, p_render as mock_render, \
                p_uuid as mock_uuid, p_log as mock_log:
            effects = handler.compute()

            assert mock_note.mock_calls == []
            assert mock_cmd.mock_calls == []
            assert mock_render.mock_calls == []
            assert mock_uuid.mock_calls == []
            assert mock_log.mock_calls == []
            assert handler.event.mock_calls == []

        assert effects == []

    def test_note_id_empty_string_returns_no_effects(self, handler):
        handler.event.context = {"state": "NEW", "note_id": ""}
        p_note, p_cmd, p_render, p_uuid, p_log = _patches()
        with p_note as mock_note, p_cmd as mock_cmd, p_render as mock_render, \
                p_uuid as mock_uuid, p_log as mock_log:
            effects = handler.compute()

            assert mock_note.mock_calls == []
            assert mock_cmd.mock_calls == []
            assert mock_render.mock_calls == []
            assert mock_uuid.mock_calls == []
            assert mock_log.mock_calls == []
            assert handler.event.mock_calls == []

        assert effects == []

    def test_null_note_type_version_returns_no_effects(self, handler):
        handler.event.context = {"state": "NEW", "note_id": "note-123"}

        mock_note_obj = MagicMock()
        mock_note_obj.note_type_version = None

        p_note, p_cmd, p_render, p_uuid, p_log = _patches()
        with p_note as mock_note, p_cmd as mock_cmd, p_render as mock_render, \
                p_uuid as mock_uuid, p_log as mock_log:
            mock_note.objects.select_related.return_value.get.return_value = mock_note_obj

            effects = handler.compute()

            # Note fetched, but the null note_type_version gate stopped it before is_telehealth.
            assert mock_note.mock_calls == [
                call.objects.select_related("note_type_version"),
                call.objects.select_related().get(id="note-123"),
            ]
            assert mock_note_obj.mock_calls == []
            assert mock_cmd.mock_calls == []
            assert mock_render.mock_calls == []
            assert mock_uuid.mock_calls == []
            assert mock_log.mock_calls == []
            assert handler.event.mock_calls == []

        assert effects == []

    def test_non_telehealth_note_returns_no_effects(self, handler):
        handler.event.context = {"state": "NEW", "note_id": "note-123"}

        mock_note_obj = MagicMock()
        mock_note_obj.note_type_version.is_telehealth = False

        p_note, p_cmd, p_render, p_uuid, p_log = _patches()
        with p_note as mock_note, p_cmd as mock_cmd, p_render as mock_render, \
                p_uuid as mock_uuid, p_log as mock_log:
            mock_note.objects.select_related.return_value.get.return_value = mock_note_obj

            effects = handler.compute()

            # The note was fetched, but the telehealth gate stopped it there.
            assert mock_note.mock_calls == [
                call.objects.select_related("note_type_version"),
                call.objects.select_related().get(id="note-123"),
            ]
            assert mock_note_obj.mock_calls == []
            assert mock_cmd.mock_calls == []
            assert mock_render.mock_calls == []
            assert mock_uuid.mock_calls == []
            assert mock_log.mock_calls == []
            assert handler.event.mock_calls == []

        assert effects == []

    def test_missing_note_returns_no_effects(self, handler):
        handler.event.context = {"state": "NEW", "note_id": "missing-note"}

        class _DoesNotExist(Exception):
            pass

        p_note, p_cmd, p_render, p_uuid, p_log = _patches()
        with p_note as mock_note, p_cmd as mock_cmd, p_render as mock_render, \
                p_uuid as mock_uuid, p_log as mock_log:
            mock_note.DoesNotExist = _DoesNotExist
            mock_note.objects.select_related.return_value.get.side_effect = _DoesNotExist()

            effects = handler.compute()

            # Lookup was attempted, raised DoesNotExist, and was swallowed.
            assert mock_note.mock_calls == [
                call.objects.select_related("note_type_version"),
                call.objects.select_related().get(id="missing-note"),
            ]
            assert mock_cmd.mock_calls == []
            assert mock_render.mock_calls == []
            assert mock_uuid.mock_calls == []
            assert mock_log.mock_calls == []
            assert handler.event.mock_calls == []

        assert effects == []


class TestTelehealthNote:
    """compute() originates the disclaimer command for a telehealth note."""

    def _run_and_assert(self, handler, expected_text):
        """Drive compute() for a telehealth note and verify all mocks + the rendered text."""
        handler.event.context = {"state": "NEW", "note_id": "note-123"}

        mock_note_obj = MagicMock()
        mock_note_obj.id = "note-123"
        mock_note_obj.note_type_version.is_telehealth = True

        p_note, p_cmd, p_render, p_uuid, p_log = _patches()
        with p_note as mock_note, p_cmd as mock_cmd, p_render as mock_render, \
                p_uuid as mock_uuid, p_log as mock_log:
            mock_note.objects.select_related.return_value.get.return_value = mock_note_obj
            mock_uuid.uuid4.return_value = "generated-uuid"

            effects = handler.compute()

            # Note lookup
            assert mock_note.mock_calls == [
                call.objects.select_related("note_type_version"),
                call.objects.select_related().get(id="note-123"),
            ]
            # Templates rendered for screen + print, each with the resolved disclaimer text
            assert mock_render.mock_calls == [
                call("templates/disclaimer.html", {"disclaimer_text": expected_text}),
                call("templates/disclaimer_print.html", {"disclaimer_text": expected_text}),
            ]
            # Command constructed with rendered content, then originated
            assert mock_cmd.mock_calls == [
                call(
                    schema_key="telehealthDisclaimer",
                    content=mock_render.return_value,
                    print_content=mock_render.return_value,
                ),
                call().originate(),
            ]
            # Command identifiers were assigned (not method calls, so not in mock_calls)
            command = mock_cmd.return_value
            assert command.note_uuid == "note-123"
            assert command.command_uuid == "generated-uuid"

            assert mock_uuid.mock_calls == [call.uuid4()]
            assert mock_log.mock_calls == [
                call.info("Telehealth note detected (note-123), inserting disclaimer")
            ]
            assert mock_note_obj.mock_calls == []
            assert handler.event.mock_calls == []

        # The single returned effect is the originated command's effect.
        assert effects == [mock_cmd.return_value.originate.return_value]

    def test_uses_default_text_when_secret_unset(self, handler):
        handler.secrets = {}
        self._run_and_assert(handler, DEFAULT_DISCLAIMER_TEXT)

    def test_uses_custom_text_when_secret_set(self, handler):
        handler.secrets = {"TELEHEALTH_DISCLAIMER_TEXT": "Custom org telehealth attestation."}
        self._run_and_assert(handler, "Custom org telehealth attestation.")

    def test_blank_secret_falls_back_to_default_text(self, handler):
        handler.secrets = {"TELEHEALTH_DISCLAIMER_TEXT": "   "}
        self._run_and_assert(handler, DEFAULT_DISCLAIMER_TEXT)
