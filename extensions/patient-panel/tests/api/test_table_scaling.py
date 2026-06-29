"""Integration tests for /table two-phase spine→ids→decorate refactor.

These tests exercise the real ORM (no mocks/patches of canvas_sdk) and
serve as a regression contract for the scalability refactor.
"""

__is_plugin__ = True

import arrow
from canvas_sdk.test_utils.factories import PatientFactory

from tests._helpers import build_api
from tests.factories import PatientPanelStatsFactory


def _render(**qp: str) -> str:
    api = build_api(query_params=qp, headers={"canvas-logged-in-user-id": ""})
    content: str = api.get_table()[0].content.decode()
    return content


def test_table_lists_all_patients_unsorted() -> None:
    PatientFactory.create(first_name="Aaa", last_name="Alpha")
    PatientFactory.create(first_name="Bbb", last_name="Bravo")
    html = _render(no_auto_filter="1", page_size="50")
    assert "Alpha" in html and "Bravo" in html


def test_table_name_sort_orders_rows() -> None:
    PatientFactory.create(first_name="Z", last_name="Zeta")
    PatientFactory.create(first_name="A", last_name="Alpha")
    html = _render(no_auto_filter="1", page_size="50", sort_by="patient", sort_dir="asc")
    assert html.index("Alpha") < html.index("Zeta")


def test_table_count_reflects_filtered_total() -> None:
    for i in range(3):
        PatientFactory.create(first_name=f"P{i}", last_name="Smith")
    PatientFactory.create(first_name="Q", last_name="Jones")
    html = _render(no_auto_filter="1", page_size="50", patient_search="Smith")
    assert "Jones" not in html
    assert "P0" in html
    assert "P1" in html
    assert "P2" in html


def test_table_last_visit_sort_runs_and_orders() -> None:
    PatientFactory.create(last_name="Recent")
    PatientFactory.create(last_name="Never")
    html = _render(no_auto_filter="1", page_size="50", sort_by="last_visit", sort_dir="desc")
    assert "Recent" in html and "Never" in html


def test_table_second_page_excludes_first_page_rows() -> None:
    for i in range(15):
        PatientFactory.create(last_name=f"Paginate{i:02d}")
    page1 = _render(no_auto_filter="1", page_size="10", sort_by="patient", sort_dir="asc")
    page2 = build_api(
        query_params={
            "no_auto_filter": "1",
            "page_size": "10",
            "page": "2",
            "sort_by": "patient",
            "sort_dir": "asc",
        },
        headers={"canvas-logged-in-user-id": ""},
    ).get_table()[0].content.decode()
    assert "Paginate00" in page1 and "Paginate00" not in page2
    assert "Paginate14" in page2


def _render_stats(**qp: str) -> str:
    # Stats sort/decoration is now the only behavior (no flag); alias of _render
    # kept for readability at the stats-specific call sites.
    api = build_api(
        query_params=qp,
        headers={"canvas-logged-in-user-id": ""},
    )
    content: str = api.get_table()[0].content.decode()
    return content


def test_table_stats_sort_orders_by_indexed_column() -> None:
    p_new = PatientFactory.create(last_name="Newer")
    p_old = PatientFactory.create(last_name="Older")
    PatientPanelStatsFactory.create(patient=p_new, last_visit_dt=arrow.get("2024-01-01").datetime)
    PatientPanelStatsFactory.create(patient=p_old, last_visit_dt=arrow.get("2019-01-01").datetime)
    html = _render_stats(no_auto_filter="1", page_size="50", sort_by="last_visit", sort_dir="desc")
    assert html.index("Newer") < html.index("Older")


def test_stats_sort_uses_precomputed_values_not_live_notes() -> None:
    # PROTECTION REGRESSION GUARD (an incident took the instance down when the
    # live correlated-subquery sort was reachable): stats-field sorts MUST order
    # by the precomputed PatientPanelStats values, never by live per-row
    # note-state subqueries (the ~37s instance-killer). Proven by disagreement:
    # neither patient has any Notes, so a LIVE last_visit would be NULL for both
    # → name tiebreak → "Aaa" first. Their stats rows say otherwise, so the
    # (always-on) stats sort puts "Zzz" (stats 2024) before "Aaa" (stats 2019)
    # on desc. If any live last/next-visit sorting is ever reintroduced, this
    # flips and fails.
    z = PatientFactory.create(last_name="Zzz")
    a = PatientFactory.create(last_name="Aaa")
    PatientPanelStatsFactory.create(patient=z, last_visit_dt=arrow.get("2024-01-01").datetime)
    PatientPanelStatsFactory.create(patient=a, last_visit_dt=arrow.get("2019-01-01").datetime)
    html = _render(no_auto_filter="1", page_size="50", sort_by="last_visit", sort_dir="desc")
    assert html.index("Zzz") < html.index("Aaa")  # stats order, not the live name-tiebreak order


def test_table_stats_sort_includes_patient_without_stats_row() -> None:
    # The stats-sorted spine now roots on Patient and sorts via a correlated
    # Subquery annotation (LEFT-JOIN-equivalent): a patient with no stats row is
    # NOT dropped — it sorts as NULL (no-visit) and still renders, keeping the
    # panel correct against a cold/incomplete stats table.
    p_has = PatientFactory.create(last_name="Hasrow")
    PatientFactory.create(last_name="Norow")  # deliberately no stats row
    PatientPanelStatsFactory.create(patient=p_has, last_visit_dt=arrow.get("2024-01-01").datetime)
    html = _render_stats(no_auto_filter="1", page_size="50", sort_by="last_visit", sort_dir="asc")
    assert "Hasrow" in html
    assert "Norow" in html  # no-stats-row patient still present (sorts as NULL)


def test_table_stats_sort_respects_patient_search_filter() -> None:
    # Exercises the parameterized (patient__-prefixed) filters on the stats path.
    p1 = PatientFactory.create(first_name="Findme", last_name="Smith")
    p2 = PatientFactory.create(first_name="Other", last_name="Jones")
    PatientPanelStatsFactory.create(patient=p1, last_visit_dt=arrow.get("2024-01-01").datetime)
    PatientPanelStatsFactory.create(patient=p2, last_visit_dt=arrow.get("2023-01-01").datetime)
    html = _render_stats(
        no_auto_filter="1",
        page_size="50",
        sort_by="last_visit",
        sort_dir="desc",
        patient_search="Smith",
    )
    assert "Findme" in html
    assert "Other" not in html


def test_decoration_sources_visits_from_stats_when_enabled() -> None:
    # last/next-visit display must come from the precomputed PatientPanelStats
    # row, NOT a per-request note-state subquery (the 20s decoration hotspot).
    # The patient has NO notes, so a live subquery would render an empty
    # last_visit; the stats row carries a real date. Sort by "patient" keeps
    # Part 1 on the name spine, isolating the decoration behavior.
    patient = PatientFactory.create(first_name="Stat", last_name="Source")
    PatientPanelStatsFactory.create(
        patient=patient,
        last_visit_dt=arrow.get("2024-03-15").datetime,
    )
    html = _render_stats(no_auto_filter="1", page_size="50", sort_by="patient", sort_dir="asc")
    assert "Source" in html
    assert "03.15.2024" in html
