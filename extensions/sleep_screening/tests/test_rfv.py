from unittest.mock import MagicMock, patch

from sleep_screening import rfv


def _cmd(coding, state="committed"):
    c = MagicMock()
    c.data = {"coding": coding}
    c.state = state
    return c


def test_matches_dict_coding_value():
    with patch("sleep_screening.rfv.Command") as Cmd:
        Cmd.objects.filter.return_value = [_cmd({"value": "sleep-intake"})]
        assert rfv.note_matches_trigger(123, "sleep-intake") is True


def test_matches_dict_coding_code_key():
    with patch("sleep_screening.rfv.Command") as Cmd:
        Cmd.objects.filter.return_value = [_cmd({"code": "sleep-intake"})]
        assert rfv.note_matches_trigger(123, "sleep-intake") is True


def test_matches_list_coding():
    with patch("sleep_screening.rfv.Command") as Cmd:
        Cmd.objects.filter.return_value = [
            _cmd([{"system": "INTERNAL", "code": "sleep-intake"}])
        ]
        assert rfv.note_matches_trigger(123, "sleep-intake") is True


def test_no_match_when_value_differs():
    with patch("sleep_screening.rfv.Command") as Cmd:
        Cmd.objects.filter.return_value = [_cmd({"value": "annual-visit"})]
        assert rfv.note_matches_trigger(123, "sleep-intake") is False


def test_no_match_when_no_rfv_commands():
    with patch("sleep_screening.rfv.Command") as Cmd:
        Cmd.objects.filter.return_value = []
        assert rfv.note_matches_trigger(123, "sleep-intake") is False


def test_none_dbid_returns_false_without_query():
    with patch("sleep_screening.rfv.Command") as Cmd:
        assert rfv.note_matches_trigger(None, "sleep-intake") is False
        Cmd.objects.filter.assert_not_called()


def test_malformed_coding_does_not_raise():
    bad = MagicMock()
    bad.data = {}
    bad.state = "committed"
    with patch("sleep_screening.rfv.Command") as Cmd:
        Cmd.objects.filter.return_value = [bad]
        assert rfv.note_matches_trigger(123, "sleep-intake") is False


def test_read_failure_fails_closed():
    with patch("sleep_screening.rfv.Command") as Cmd:
        Cmd.objects.filter.side_effect = ValueError("bad id")
        assert rfv.note_matches_trigger(123, "sleep-intake") is False


def test_coding_values_helper_dict_and_list():
    assert rfv._coding_values({"coding": {"value": "x"}}) == ["x"]
    assert rfv._coding_values({"coding": [{"code": "y"}, {"value": "z"}]}) == ["y", "z"]
    assert rfv._coding_values({}) == []
