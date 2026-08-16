import pytest

from surescripts_med_history.protocols.settings import (
    DEFAULT_COMMIT,
    DEFAULT_MOCK,
    parse_commit,
    parse_mock,
)


class TestParseCommit:
    def test_default_is_uncommitted(self):
        assert DEFAULT_COMMIT is False
        assert parse_commit(None) is False
        assert parse_commit("") is False
        assert parse_commit("   ") is False

    @pytest.mark.parametrize(
        "raw", ["true", "TRUE", " Yes ", "y", "1", "on", "committed", "commit", True]
    )
    def test_truthy_values(self, raw):
        assert parse_commit(raw) is True

    @pytest.mark.parametrize(
        "raw", ["false", "No", "n", "0", "off", "uncommitted", "staged", False]
    )
    def test_falsy_values(self, raw):
        assert parse_commit(raw) is False

    def test_unrecognized_value_falls_back_to_default(self):
        assert parse_commit("maybe") is DEFAULT_COMMIT


class TestParseMock:
    def test_default_is_off(self):
        assert DEFAULT_MOCK is False
        assert parse_mock(None) is False
        assert parse_mock("") is False

    @pytest.mark.parametrize("raw", ["true", "TRUE", "Yes", "1", "on", True])
    def test_truthy_values(self, raw):
        assert parse_mock(raw) is True

    @pytest.mark.parametrize("raw", ["false", "no", "0", "off", False])
    def test_falsy_values(self, raw):
        assert parse_mock(raw) is False

    def test_unrecognized_value_falls_back_to_off(self):
        assert parse_mock("sometimes") is False
