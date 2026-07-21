from sleep_screening.scoring.base import InstrumentResult, PatientContext, present


def test_present_true_when_all_codes_answered():
    assert present({"A": 1.0, "B": 0.0}, ["A", "B"]) is True


def test_present_false_when_a_code_missing():
    assert present({"A": 1.0}, ["A", "B"]) is False


def test_patient_context_is_male_from_m_prefix():
    assert PatientContext(sex="M").is_male is True
    assert PatientContext(sex="Female").is_male is False
    assert PatientContext(sex=None).is_male is False


def test_instrument_result_defaults():
    r = InstrumentResult(
        code="X", name="X", score=1.0, band="Low",
        abnormal=False, narrative="n", complete=True,
    )
    assert r.high_risk is False
    assert r.subscores == {}
