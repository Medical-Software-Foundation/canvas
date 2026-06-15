from questionnaire_scoring_dashboard.commands.scoring_trend import ScoringTrendCommand


def test_schema_key_is_set():
    assert ScoringTrendCommand.Meta.schema_key == "scoringTrend"


def test_command_builds_and_originates():
    cmd = ScoringTrendCommand(content="<b>x</b>", print_content="x")
    cmd.command_uuid = "cmd-1"
    cmd.note_uuid = "note-1"
    effect = cmd.originate()
    assert "scoringTrend" in str(effect.payload)
    assert "note-1" in str(effect.payload)
