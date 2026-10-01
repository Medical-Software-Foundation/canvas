from surescripts_med_history.protocols.cadence import parse_days


class TestParseDays:
    def test_default_when_none(self):
        assert parse_days(None) == [1, 7]

    def test_default_when_empty_string(self):
        assert parse_days("") == [1, 7]

    def test_default_when_whitespace(self):
        assert parse_days("   ") == [1, 7]

    def test_single_offset(self):
        assert parse_days("3") == [3]

    def test_multiple_offsets(self):
        assert parse_days("1,7") == [1, 7]

    def test_strips_whitespace(self):
        assert parse_days(" 1 , 7 , 14 ") == [1, 7, 14]

    def test_zero_is_allowed(self):
        assert parse_days("0") == [0]

    def test_zero_mixed_with_others(self):
        assert parse_days("0,3,7") == [0, 3, 7]

    def test_deduplicates(self):
        assert parse_days("1,7,1,7") == [1, 7]

    def test_malformed_falls_back(self):
        assert parse_days("abc") == [1, 7]

    def test_mixed_malformed_falls_back(self):
        assert parse_days("1,abc,7") == [1, 7]

    def test_negative_falls_back(self):
        assert parse_days("-1,7") == [1, 7]

    def test_only_commas_falls_back(self):
        assert parse_days(",,,") == [1, 7]
