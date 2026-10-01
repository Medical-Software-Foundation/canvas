from pathlib import Path

import yaml

from sleep_screening.scoring import ess, isi, stopbang

QDIR = Path(__file__).resolve().parent.parent / "sleep_screening" / "questionnaires"


def _load(name):
    with open(QDIR / name) as fh:
        return yaml.safe_load(fh)


def test_ess_has_eight_items_matching_scorer_codes():
    data = _load("ess.yaml")
    assert data["code"] == "SLEEP_ESS"
    codes = [q["code"] for q in data["questions"]]
    assert codes == ess.ITEMS
    for q in data["questions"]:
        values = sorted(int(r["value"]) for r in q["responses"])
        assert values == [0, 1, 2, 3]


def test_isi_has_seven_items_valued_0_4():
    data = _load("isi.yaml")
    assert data["code"] == "SLEEP_ISI"
    assert [q["code"] for q in data["questions"]] == isi.ITEMS
    for q in data["questions"]:
        values = sorted(int(r["value"]) for r in q["responses"])
        assert values == [0, 1, 2, 3, 4]


def test_stopbang_items_are_yes_no_valued_0_1():
    data = _load("stopbang.yaml")
    assert data["code"] == "SLEEP_STOPBANG"
    codes = [q["code"] for q in data["questions"]]
    assert codes == stopbang.STOP_ITEMS + [stopbang.NECK_ITEM]
    for q in data["questions"]:
        values = sorted(int(r["value"]) for r in q["responses"])
        assert values == [0, 1]


def test_all_response_codes_unique_within_each_form():
    for name in ("ess.yaml", "isi.yaml", "stopbang.yaml"):
        data = _load(name)
        codes = [r["code"] for q in data["questions"] for r in q["responses"]]
        assert len(codes) == len(set(codes)), name
