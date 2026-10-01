from types import SimpleNamespace

from failed_fax_dashboard.services.sources import walk


def test_walk_follows_the_chain() -> None:
    obj = SimpleNamespace(note=SimpleNamespace(patient="p"))

    assert walk(obj, ("note", "patient")) == "p"


def test_walk_stops_at_a_missing_link() -> None:
    obj = SimpleNamespace(note=None)

    assert walk(obj, ("note", "patient")) is None


def test_walk_without_a_path_returns_none() -> None:
    assert walk(SimpleNamespace(), None) is None
