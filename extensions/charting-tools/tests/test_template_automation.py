from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from canvas_generated.messages.effects_pb2 import EffectType
from canvas_sdk.events import EventType

from charting_tools.handlers.template_automation import NoteTemplateAutomation, button_key
from charting_tools.settings import SCRIBE_PROMPT_METADATA_KEY
from tests.conftest import make_event, make_note, make_template, payload

MODULE = "charting_tools.handlers.template_automation"
INSERTION = "charting_tools.insertion"


def _handler(event: SimpleNamespace, secrets: dict | None = None) -> NoteTemplateAutomation:
    return NoteTemplateAutomation(event=event, secrets=secrets or {})


def _patch_template(mocker: MagicMock, template: SimpleNamespace | None) -> MagicMock:
    query = mocker.patch(f"{MODULE}.NoteTemplate.objects.filter")
    query.return_value.exclude.return_value.first.return_value = template
    return query


def _patch_note(mocker: MagicMock, note: SimpleNamespace | None) -> None:
    mocker.patch(f"{MODULE}.Note.objects.defer").return_value.filter.return_value.first.return_value = note


def _fields(command_payload: dict) -> dict:
    """Command data minus the identifiers the SDK always includes."""
    return {k: v for k, v in command_payload["data"].items() if k not in ("note_uuid", "command_uuid")}


def _click(**context: object) -> SimpleNamespace:
    return make_event(
        EventType.ACTION_BUTTON_CLICKED, key=button_key("tmpl1"), note_id=42, **context
    )


class TestShow:
    def test_one_entry_per_active_template(self, mocker: MagicMock) -> None:
        query = mocker.patch(f"{MODULE}.NoteTemplate.objects.filter")
        query.return_value.exclude.return_value.only.return_value.order_by.return_value = [
            make_template(template_id="t1", name="Annual visit"),
            make_template(template_id="t2", name="Diabetes follow-up"),
        ]
        effects = _handler(make_event(EventType.SHOW_NOTE_BODY_AUTOMATION_BUTTON, note_id=42)).compute()

        query.assert_called_once_with(active=True)
        query.return_value.exclude.assert_called_once_with(show_in_menu=False)
        assert [e.type for e in effects] == [EffectType.SHOW_ACTION_BUTTON] * 2
        assert [payload(e)["data"]["key"] for e in effects] == [
            "CHARTING_TOOLS__t1",
            "CHARTING_TOOLS__t2",
        ]
        assert [payload(e)["data"]["title"] for e in effects] == [
            "Annual visit",
            "Diabetes follow-up",
        ]

    def test_nothing_outside_a_note(self, mocker: MagicMock) -> None:
        query = mocker.patch(f"{MODULE}.NoteTemplate.objects.filter")
        effects = _handler(make_event(EventType.SHOW_NOTE_BODY_AUTOMATION_BUTTON, note_id=None)).compute()
        assert effects == []
        query.assert_not_called()


class TestClick:
    def test_ignores_other_plugins_keys(self, mocker: MagicMock) -> None:
        query = mocker.patch(f"{MODULE}.NoteTemplate.objects.filter")
        event = make_event(EventType.ACTION_BUTTON_CLICKED, key="SOMEONE_ELSE", note_id=42)
        assert _handler(event).compute() == []
        query.assert_not_called()

    def test_inactive_or_missing_template_does_nothing(self, mocker: MagicMock) -> None:
        query = _patch_template(mocker, None)
        assert _handler(_click()).compute() == []
        query.assert_called_once_with(template_id="tmpl1", active=True)
        query.return_value.exclude.assert_called_once_with(show_in_menu=False)

    def test_originates_empty_commands_on_trigger_line(self, mocker: MagicMock) -> None:
        _patch_template(
            mocker,
            make_template(
                commands=[
                    {"schema_key": "reasonForVisit", "carry_forward": False, "scribe_prompt": ""},
                    {"schema_key": "hpi", "carry_forward": False, "scribe_prompt": ""},
                    {"schema_key": "plan", "carry_forward": False, "scribe_prompt": ""},
                ]
            ),
        )
        _patch_note(mocker, make_note())

        effects = _handler(_click()).compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.BATCH_ORIGINATE_COMMANDS
        data = payload(effects[0])["data"]
        assert data["replace_line"] is True
        assert [c["type"] for c in data["commands"]] == [
            "ORIGINATE_REASON_FOR_VISIT_COMMAND",
            "ORIGINATE_HPI_COMMAND",
            "ORIGINATE_PLAN_COMMAND",
        ]
        assert all(c["note"] == make_note().id for c in data["commands"])
        assert all(_fields(c) == {} for c in data["commands"])
        assert len({c["command"] for c in data["commands"]}) == 3

    def test_skips_unknown_command_types(self, mocker: MagicMock) -> None:
        _patch_template(mocker, make_template(commands=[{"schema_key": "retired"}, {"schema_key": "plan"}]))
        _patch_note(mocker, make_note())
        data = payload(_handler(_click()).compute()[0])["data"]
        assert [c["type"] for c in data["commands"]] == ["ORIGINATE_PLAN_COMMAND"]

    def test_carry_forward_prefills_from_prior_command(self, mocker: MagicMock) -> None:
        _patch_template(mocker, make_template(commands=[{"schema_key": "hpi", "carry_forward": True}]))
        _patch_note(mocker, make_note())
        find = mocker.patch(
            f"{INSERTION}.find_previous_command",
            return_value=SimpleNamespace(schema_key="hpi", data={"narrative": "Prior HPI"}, id="c0"),
        )

        data = payload(_handler(_click()).compute()[0])["data"]

        find.assert_called_once()
        assert _fields(data["commands"][0]) == {"narrative": "Prior HPI"}

    def test_carry_forward_without_prior_command_stays_empty(self, mocker: MagicMock) -> None:
        _patch_template(mocker, make_template(commands=[{"schema_key": "hpi", "carry_forward": True}]))
        _patch_note(mocker, make_note())
        mocker.patch(f"{INSERTION}.find_previous_command", return_value=None)
        data = payload(_handler(_click()).compute()[0])["data"]
        assert _fields(data["commands"][0]) == {}

    def test_carry_forward_bad_data_falls_back_to_empty(self, mocker: MagicMock) -> None:
        _patch_template(mocker, make_template(commands=[{"schema_key": "perform", "carry_forward": True}]))
        _patch_note(mocker, make_note())
        # "perform" is a string rather than the expected {"value": ...} dict.
        mocker.patch(
            f"{INSERTION}.find_previous_command",
            return_value=SimpleNamespace(
                schema_key="perform", data={"notes": "x", "perform": "99213"}, id="c0"
            ),
        )
        data = payload(_handler(_click()).compute()[0])["data"]
        assert data["commands"][0]["type"] == "ORIGINATE_PERFORM_COMMAND"
        assert _fields(data["commands"][0]) == {}

    def test_carry_forward_ignored_for_unsupported_command(self, mocker: MagicMock) -> None:
        _patch_template(mocker, make_template(commands=[{"schema_key": "prescribe", "carry_forward": True}]))
        _patch_note(mocker, make_note())
        find = mocker.patch(f"{INSERTION}.find_previous_command")
        _handler(_click()).compute()
        find.assert_not_called()

    @pytest.mark.parametrize("enabled", ["false", ""])
    def test_no_scribe_metadata_when_scribe_disabled(self, mocker: MagicMock, enabled: str) -> None:
        _patch_template(mocker, make_template(commands=[{"schema_key": "hpi", "scribe_prompt": "Focus on onset"}]))
        _patch_note(mocker, make_note())
        effects = _handler(_click(), secrets={"SCRIBE_ENABLED": enabled}).compute()
        assert [e.type for e in effects] == [EffectType.BATCH_ORIGINATE_COMMANDS]

    def test_scribe_prompts_written_as_command_metadata(self, mocker: MagicMock) -> None:
        _patch_template(
            mocker,
            make_template(
                commands=[
                    {"schema_key": "hpi", "scribe_prompt": "  Focus on onset and severity  "},
                    {"schema_key": "plan", "scribe_prompt": ""},
                ]
            ),
        )
        _patch_note(mocker, make_note())

        effects = _handler(_click(), secrets={"SCRIBE_ENABLED": "true"}).compute()

        assert effects[0].type == EffectType.BATCH_ORIGINATE_COMMANDS
        assert len(effects) == 2
        hpi_uuid = payload(effects[0])["data"]["commands"][0]["command"]
        metadata = payload(effects[1])["data"]
        assert metadata == {
            "command_id": hpi_uuid,
            "schema_key": "hpi",
            "key": SCRIBE_PROMPT_METADATA_KEY,
            "value": "Focus on onset and severity",
        }


class TestQuestionnaireCommands:
    @pytest.fixture(autouse=True)
    def _no_question_lookup(self, mocker: MagicMock) -> None:
        # Serializing a questionnaire command loads its questions from the database.
        from canvas_sdk.commands import QuestionnaireCommand

        mocker.patch.object(QuestionnaireCommand, "questions", new_callable=mocker.PropertyMock, return_value=[])

    def _template(self) -> SimpleNamespace:
        return make_template(
            commands=[
                {"schema_key": "questionnaire", "questionnaire": {"code_system": "LOINC", "code": "69737-5", "name": "GAD-7"}},
                {"schema_key": "exam", "questionnaire": {"code_system": "S", "code": "E1", "name": "Exam"}},
                {"schema_key": "plan"},
            ]
        )

    def test_originates_with_resolved_questionnaire(self, mocker: MagicMock) -> None:
        _patch_template(mocker, self._template())
        _patch_note(mocker, make_note())
        resolve = mocker.patch(
            f"{INSERTION}.resolve",
            return_value={
                ("QUES", "LOINC", "69737-5"): SimpleNamespace(id="gad7uuid"),
                ("EXAM", "S", "E1"): SimpleNamespace(id="examuuid"),
            },
        )

        data = payload(_handler(_click()).compute()[0])["data"]

        resolve.assert_called_once_with({("QUES", "LOINC", "69737-5"), ("EXAM", "S", "E1")})
        assert [c["type"] for c in data["commands"]] == [
            "ORIGINATE_QUESTIONNAIRE_COMMAND",
            "ORIGINATE_EXAM_COMMAND",
            "ORIGINATE_PLAN_COMMAND",
        ]
        assert data["commands"][0]["data"]["questionnaire_id"] == "gad7uuid"
        assert data["commands"][1]["data"]["questionnaire_id"] == "examuuid"
        # No answers are sent: Canvas only applies the questionnaire's own
        # carry-forward setting to a plugin command that arrives without answers.
        assert data["commands"][0]["data"]["questions"] == {}
        assert data["commands"][1]["data"]["questions"] == {}

    def test_carry_forward_flag_does_not_touch_questionnaire_commands(self, mocker: MagicMock) -> None:
        _patch_template(
            mocker,
            make_template(
                commands=[
                    {"schema_key": "ros", "carry_forward": True, "questionnaire": {"code_system": "S", "code": "R1"}}
                ]
            ),
        )
        _patch_note(mocker, make_note())
        mocker.patch(f"{INSERTION}.resolve", return_value={("ROS", "S", "R1"): SimpleNamespace(id="rosuuid")})
        find = mocker.patch(f"{INSERTION}.find_previous_command")

        data = payload(_handler(_click()).compute()[0])["data"]

        find.assert_not_called()
        assert data["commands"][0]["data"]["questions"] == {}

    def test_inactive_questionnaire_inserts_command_without_one(self, mocker: MagicMock) -> None:
        _patch_template(mocker, self._template())
        _patch_note(mocker, make_note())
        mocker.patch(f"{INSERTION}.resolve", return_value={("EXAM", "S", "E1"): SimpleNamespace(id="examuuid")})

        data = payload(_handler(_click()).compute()[0])["data"]

        assert data["commands"][0]["type"] == "ORIGINATE_QUESTIONNAIRE_COMMAND"
        assert "questionnaire_id" not in data["commands"][0]["data"]
        assert data["commands"][1]["data"]["questionnaire_id"] == "examuuid"
