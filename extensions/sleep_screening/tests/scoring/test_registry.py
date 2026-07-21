from sleep_screening.scoring import registry


def test_get_scorer_returns_callable_for_known_code():
    fn = registry.get_scorer("SLEEP_ESS")
    assert callable(fn)


def test_get_scorer_none_for_unknown():
    assert registry.get_scorer("NOPE") is None


def test_all_three_codes_registered():
    assert set(registry.QUESTIONNAIRE_CODES) == {
        "SLEEP_STOPBANG",
        "SLEEP_ESS",
        "SLEEP_ISI",
    }
