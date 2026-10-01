from sleep_screening.scoring.base import PatientContext
from sleep_screening.scoring import ess


def _items(vals):
    return {"SLEEP_ESS_Q" + str(i + 1): float(v) for i, v in enumerate(vals)}


def test_normal_total_le_10():
    r = ess.score(_items([1, 1, 1, 1, 1, 1, 1, 1]), PatientContext())
    assert r.score == 8.0
    assert r.band == "Normal"
    assert r.abnormal is False


def test_excessive_total_gt_10():
    r = ess.score(_items([2, 2, 2, 2, 2, 1, 1, 1]), PatientContext())
    assert r.score == 13.0
    assert r.band == "Excessive daytime sleepiness"
    assert r.abnormal is True


def test_boundary_10_is_normal():
    r = ess.score(_items([2, 2, 2, 2, 1, 1, 0, 0]), PatientContext())
    assert r.score == 10.0
    assert r.band == "Normal"


def test_incomplete_provisional():
    r = ess.score({"SLEEP_ESS_Q1": 3.0}, PatientContext())
    assert r.complete is False
    assert "provisional" in r.narrative
