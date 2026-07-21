from sleep_screening.scoring.base import PatientContext
from sleep_screening.scoring import stopbang


def _all_no():
    return {
        "SLEEP_STOPBANG_S1": 0.0,
        "SLEEP_STOPBANG_S2": 0.0,
        "SLEEP_STOPBANG_S3": 0.0,
        "SLEEP_STOPBANG_S4": 0.0,
        "SLEEP_STOPBANG_NECK": 0.0,
    }


def test_low_band_all_no_female_young():
    r = stopbang.score(_all_no(), PatientContext(age=30, sex="F", bmi=22.0))
    assert r.score == 0.0
    assert r.band == "Low"
    assert r.abnormal is False
    assert r.high_risk is False


def test_high_band_total_ge_5():
    resp = {
        "SLEEP_STOPBANG_S1": 1.0,
        "SLEEP_STOPBANG_S2": 1.0,
        "SLEEP_STOPBANG_S3": 1.0,
        "SLEEP_STOPBANG_S4": 1.0,
        "SLEEP_STOPBANG_NECK": 1.0,
    }
    r = stopbang.score(resp, PatientContext(age=60, sex="M", bmi=40.0))
    assert r.band == "High"
    assert r.high_risk is True


def test_intermediate_band_3():
    resp = {
        "SLEEP_STOPBANG_S1": 1.0,
        "SLEEP_STOPBANG_S2": 1.0,
        "SLEEP_STOPBANG_S3": 0.0,
        "SLEEP_STOPBANG_S4": 0.0,
        "SLEEP_STOPBANG_NECK": 0.0,
    }
    r = stopbang.score(resp, PatientContext(age=60, sex="F", bmi=22.0))
    assert r.score == 3.0
    assert r.band == "Intermediate"


def test_missing_bmi_omits_point_and_notes_it():
    r = stopbang.score(_all_no(), PatientContext(age=60, sex="M", bmi=None))
    # age>50 (+1) + male (+1) = 2, no BMI point
    assert r.score == 2.0
    assert "BMI unavailable" in r.narrative


def test_high_risk_override_two_stop_and_male():
    # STOP count 2 (snore + tired), male -> override to High even though total < 5
    resp = {
        "SLEEP_STOPBANG_S1": 1.0,
        "SLEEP_STOPBANG_S2": 1.0,
        "SLEEP_STOPBANG_S3": 0.0,
        "SLEEP_STOPBANG_S4": 0.0,
        "SLEEP_STOPBANG_NECK": 0.0,
    }
    r = stopbang.score(resp, PatientContext(age=30, sex="M", bmi=22.0))
    assert r.band == "High"
    assert r.high_risk is True
    assert "override" in r.narrative


def test_incomplete_marks_provisional():
    resp = {"SLEEP_STOPBANG_S1": 1.0}  # missing items
    r = stopbang.score(resp, PatientContext(age=60, sex="M", bmi=40.0))
    assert r.complete is False
    assert "provisional" in r.narrative
