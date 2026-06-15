from questionnaire_scoring_dashboard.services.notes_select import choose_notes


def _n(nid, dos, title):
    return {"id": nid, "dos": dos, "title": title}


def test_choose_notes_sorts_desc_by_dos_and_flags_default():
    rows = [
        _n("a", "2026-01-30T10:00:00+00:00", "Telehealth"),
        _n("b", "2026-02-14T09:00:00+00:00", "Office Visit"),  # future-dated, scheduled
        _n("c", "2026-01-12T08:00:00+00:00", "Intake"),
    ]
    out = choose_notes(rows)
    assert [r["id"] for r in out] == ["b", "a", "c"]
    assert out[0]["default"] is True
    assert out[1]["default"] is False
    assert "label" in out[0]
    assert "Office Visit" in out[0]["label"]


def test_choose_notes_missing_title_uses_fallback():
    out = choose_notes([{"id": "x", "dos": "2026-01-01T00:00:00+00:00", "title": ""}])
    assert "Note" in out[0]["label"]


def test_choose_notes_empty():
    assert choose_notes([]) == []
