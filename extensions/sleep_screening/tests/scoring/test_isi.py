from sleep_screening.scoring.base import PatientContext
from sleep_screening.scoring import isi


def _items(vals):
    return {"SLEEP_ISI_Q" + str(i + 1): float(v) for i, v in enumerate(vals)}


def test_none_band_0_7():
    r = isi.score(_items([1, 1, 1, 1, 0, 0, 0]), PatientContext())
    assert r.score == 4.0
    assert r.band == "None"
    assert r.abnormal is False


def test_subthreshold_8_14():
    r = isi.score(_items([2, 2, 2, 2, 2, 0, 0]), PatientContext())
    assert r.score == 10.0
    assert r.band == "Subthreshold"
    assert r.abnormal is False


def test_moderate_15_21_is_abnormal():
    r = isi.score(_items([3, 3, 3, 3, 3, 0, 0]), PatientContext())
    assert r.score == 15.0
    assert r.band == "Moderate"
    assert r.abnormal is True


def test_severe_22_28():
    r = isi.score(_items([4, 4, 4, 4, 4, 1, 1]), PatientContext())
    assert r.score == 22.0
    assert r.band == "Severe"
    assert r.abnormal is True


def test_incomplete_provisional():
    r = isi.score({"SLEEP_ISI_Q1": 4.0}, PatientContext())
    assert r.complete is False
    assert "provisional" in r.narrative
