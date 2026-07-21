from sleep_screening import sleep_codes


def test_default_codes_when_no_secret():
    assert sleep_codes.load_codes({}) == sleep_codes.DEFAULT_CODES


def test_default_codes_when_secret_blank():
    assert sleep_codes.load_codes({"SLEEP_DX_CODES": ""}) == sleep_codes.DEFAULT_CODES


def test_valid_secret_override():
    raw = '[{"code": "G47.00", "display": "Insomnia"}]'
    codes = sleep_codes.load_codes({"SLEEP_DX_CODES": raw})
    assert codes == [{"code": "G47.00", "display": "Insomnia"}]


def test_invalid_json_falls_back_to_default():
    codes = sleep_codes.load_codes({"SLEEP_DX_CODES": "not json{"})
    assert codes == sleep_codes.DEFAULT_CODES


def test_non_list_json_falls_back():
    codes = sleep_codes.load_codes({"SLEEP_DX_CODES": '{"code": "x"}'})
    assert codes == sleep_codes.DEFAULT_CODES


def test_malformed_items_dropped_then_fallback_if_empty():
    codes = sleep_codes.load_codes({"SLEEP_DX_CODES": '[{"nope": 1}]'})
    assert codes == sleep_codes.DEFAULT_CODES


def test_preselect_for_known_instrument():
    assert sleep_codes.preselect_for("SLEEP_STOPBANG") == ["R06.83", "G47.30"]
    assert sleep_codes.preselect_for("SLEEP_ESS") == ["R40.0"]
    assert sleep_codes.preselect_for("SLEEP_ISI") == ["G47.00"]


def test_preselect_for_unknown_is_empty():
    assert sleep_codes.preselect_for("NOPE") == []
