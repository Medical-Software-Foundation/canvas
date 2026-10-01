"""Tests for patient_panel.services.patient_query.

Real Patient/PatientMetadata records via the ORM — no canvas_sdk mocking.
"""

__is_plugin__ = True

import arrow
import pytest

from canvas_sdk.test_utils.factories import NoteFactory, PatientFactory
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.patient import PatientMetadata as PatientMetadataRecord

from patient_panel.services.patient_query import (
    annotate_sort_key,
    apply_metadata_filters,
    apply_patient_filters,
    apply_sorting,
    apply_stats_sort,
    build_base_queryset,
    build_decoration_queryset,
    build_spine_queryset,
    STATS_SORT_FIELDS,
)


pytestmark = pytest.mark.django_db


def _seed(key: str, value: str | None) -> Patient:
    p = PatientFactory.create()
    if value is not None:
        PatientMetadataRecord.objects.create(patient=p, key=key, value=value)
    return p


# ── metadata filters ──────────────────────────────────────────────────────

COL_RISK = {
    "type": "metadata",
    "key": "risk_score",
    "label": "Risk Score",
    "filterable": True,
    "filter_options": ["Low", "Medium", "High"],
}
COL_SERVICES = {
    "type": "metadata",
    "key": "services",
    "label": "Services",
    "filterable": True,
}


def _filtered_ids(filters: dict[str, list[str]], columns: list[dict]) -> set:
    qs = apply_metadata_filters(Patient.objects.all(), filters, columns).distinct()
    return {p.id for p in qs}


class TestMetadataFilters:
    def test_empty_filters_returns_all(self) -> None:
        a = _seed("risk_score", "Low")
        b = _seed("risk_score", "High")
        assert _filtered_ids({}, [COL_RISK]) == {a.id, b.id}

    def test_single_value_filter(self) -> None:
        low = _seed("risk_score", "Low")
        _seed("risk_score", "High")
        assert _filtered_ids({"risk_score": ["Low"]}, [COL_RISK]) == {low.id}

    def test_multi_value_filter_is_or(self) -> None:
        low = _seed("risk_score", "Low")
        med = _seed("risk_score", "Medium")
        _seed("risk_score", "High")
        assert _filtered_ids({"risk_score": ["Low", "Medium"]}, [COL_RISK]) == {low.id, med.id}

    def test_two_metadata_filters_combine_as_and(self) -> None:
        a = _seed("risk_score", "Low")
        PatientMetadataRecord.objects.create(patient=a, key="services", value="PCP")
        b = _seed("risk_score", "Low")
        PatientMetadataRecord.objects.create(patient=b, key="services", value="Wellness")
        c = _seed("risk_score", "High")
        PatientMetadataRecord.objects.create(patient=c, key="services", value="PCP")
        ids = _filtered_ids(
            {"risk_score": ["Low"], "services": ["PCP"]},
            [COL_RISK, COL_SERVICES],
        )
        assert ids == {a.id}

    def test_unknown_filter_key_is_ignored(self) -> None:
        a = _seed("risk_score", "Low")
        b = _seed("risk_score", "High")
        assert _filtered_ids({"bogus": ["whatever"]}, [COL_RISK]) == {a.id, b.id}

    def test_non_filterable_column_is_ignored(self) -> None:
        a = _seed("risk_score", "Low")
        b = _seed("risk_score", "High")
        non_filterable = {**COL_RISK, "filterable": False}
        assert _filtered_ids({"risk_score": ["Low"]}, [non_filterable]) == {a.id, b.id}


# ── ordinal sort ──────────────────────────────────────────────────────────

RISK_COLUMN = {
    "type": "metadata",
    "key": "risk_score",
    "label": "Risk Score",
    "sortable": True,
    "sort_key": "risk_score",
    "sort_order": ["Low", "Medium", "High"],
}


def _ordered_ids(sort_dir: str, columns: tuple[dict[str, object], ...] = (RISK_COLUMN,)) -> list[object]:
    qs = apply_sorting(
        Patient.objects.all(),
        sort_by="risk_score",
        sort_dir=sort_dir,
        columns=list(columns),
    ).distinct()
    return [p.id for p in qs]


def _seed_risk(value: str | None) -> Patient:
    return _seed("risk_score", value)


class TestMetadataOrdinalSort:
    def test_ascending_orders_by_sort_order_index(self) -> None:
        high = _seed_risk("High")
        low = _seed_risk("Low")
        medium = _seed_risk("Medium")
        assert _ordered_ids("asc") == [low.id, medium.id, high.id]

    def test_descending_reverses(self) -> None:
        high = _seed_risk("High")
        low = _seed_risk("Low")
        medium = _seed_risk("Medium")
        assert _ordered_ids("desc") == [high.id, medium.id, low.id]

    def test_missing_value_sorts_last_in_asc(self) -> None:
        present = _seed_risk("Medium")
        absent = _seed_risk(None)
        ordered = _ordered_ids("asc")
        assert ordered.index(present.id) < ordered.index(absent.id)

    def test_unknown_value_sorts_last_in_asc(self) -> None:
        present = _seed_risk("Low")
        bogus = _seed_risk("Unranked")
        ordered = _ordered_ids("asc")
        assert ordered.index(present.id) < ordered.index(bogus.id)

    def test_sort_key_not_matching_metadata_column_is_noop(self) -> None:
        _seed_risk("Low")
        _seed_risk("High")
        qs = apply_sorting(
            Patient.objects.all(), sort_by="risk_score", sort_dir="asc", columns=[]
        ).distinct()
        assert qs.count() == 2

    def test_ordinal_sort_uses_a_single_join_not_correlated_subquery(self) -> None:
        # Regression guard: a prior implementation re-evaluated a correlated
        # subquery against patientmetadata once per CASE branch for every
        # patient row, which 502'd the instance at scale. The fix must stay a
        # single set-based LEFT JOIN + GROUP BY — never a per-row subquery.
        for direction in ("asc", "desc"):
            sql = str(
                apply_sorting(
                    Patient.objects.all(),
                    sort_by="risk_score",
                    sort_dir=direction,
                    columns=[RISK_COLUMN],
                ).query
            ).lower()
            assert sql.count(" join ") == 1, direction
            assert "left outer join" in sql, direction
            assert "group by" in sql, direction
            # A correlated subquery would add a second SELECT; the join form
            # is a single flat SELECT.
            assert sql.count("select") == 1, direction


EXCLUDED_NOTE_TYPES = ("message", "letter", "data", "ccda")


class TestBuildBaseQuerysetAndBuiltinSort:
    def test_base_queryset_has_annotations(self) -> None:
        patient = PatientFactory.create()
        row = build_base_queryset().get(id=patient.id)
        # Count annotations default to 0; subquery annotations resolve to None.
        assert row.tasks_open_count == 0
        assert row.gaps_due_count == 0
        assert row.conditions_count_ann == 0
        assert hasattr(row, "room_number_ann")
        assert hasattr(row, "next_visit_ann")

    def test_base_queryset_does_not_prefetch_notes(self) -> None:
        """Perf regression guard: the table must NOT bulk-prefetch the notes
        graph. Last visit is now computed via the `last_visit_ann` subquery.
        Prefetching every note (+ provider/roles/type/state) for each patient
        on the page is what made /table hang and starve the DB on large
        instances where patients have thousands of notes.
        """
        # Lookups are a mix of plain strings and Prefetch objects; normalize
        # each to its target path string.
        paths = [
            getattr(lk, "prefetch_to", lk)
            for lk in build_base_queryset()._prefetch_related_lookups
        ]
        offenders = [p for p in paths if p == "notes" or p.startswith("notes__")]
        assert offenders == [], f"notes graph still prefetched: {offenders}"

    def test_base_queryset_annotates_last_visit(self) -> None:
        """`last_visit_ann` returns the datetime of the most recent billable,
        non-future, non-excluded, non-deleted visit — replacing the Python
        `get_last_visit` iteration over prefetched notes.
        """
        patient = PatientFactory.create()
        NoteFactory.create(
            patient=patient,
            datetime_of_service=arrow.utcnow().shift(days=-30).datetime,
        )
        newer = NoteFactory.create(
            patient=patient,
            datetime_of_service=arrow.utcnow().shift(days=-2).datetime,
        )
        row = build_base_queryset(EXCLUDED_NOTE_TYPES).get(id=patient.id)
        assert row.last_visit_ann is not None
        assert row.last_visit_ann == newer.datetime_of_service

    def test_base_queryset_last_visit_none_when_no_notes(self) -> None:
        patient = PatientFactory.create()
        row = build_base_queryset(EXCLUDED_NOTE_TYPES).get(id=patient.id)
        assert row.last_visit_ann is None

    def test_last_visit_ann_excludes_future_notes(self) -> None:
        """A scheduled future encounter must not count as the last visit
        (pins the `datetime_of_service__lte=now` clause)."""
        patient = PatientFactory.create()
        NoteFactory.create(
            patient=patient,
            datetime_of_service=arrow.utcnow().shift(days=+5).datetime,
        )
        row = build_base_queryset(EXCLUDED_NOTE_TYPES).get(id=patient.id)
        assert row.last_visit_ann is None

    def test_last_visit_ann_excludes_configured_note_types(self) -> None:
        """A past billable note whose note_type is in excluded_note_types is
        dropped; the same note counts when no types are excluded (pins the
        `note_type__in` exclude and proves it is the discriminating clause)."""
        patient = PatientFactory.create()
        NoteFactory.create(
            patient=patient,
            note_type="message",
            datetime_of_service=arrow.utcnow().shift(days=-3).datetime,
        )
        assert build_base_queryset(EXCLUDED_NOTE_TYPES).get(id=patient.id).last_visit_ann is None
        assert build_base_queryset(()).get(id=patient.id).last_visit_ann is not None

    def test_last_visit_ann_excludes_non_billable(self) -> None:
        """A non-billable note type is not a visit (pins
        `note_type_version__is_billable=True`)."""
        patient = PatientFactory.create()
        NoteFactory.create(
            patient=patient,
            note_type_version__is_billable=False,
            datetime_of_service=arrow.utcnow().shift(days=-3).datetime,
        )
        row = build_base_queryset(EXCLUDED_NOTE_TYPES).get(id=patient.id)
        assert row.last_visit_ann is None

    def test_last_visit_sort_treats_no_visit_as_most_overdue(self) -> None:
        """Ascending last_visit sort surfaces no-visit patients first
        (nulls_first) — they are the most overdue. Pins the asymmetric null
        ordering of the last_visit sort branch."""
        with_visit = PatientFactory.create(last_name="Aaa")
        NoteFactory.create(
            patient=with_visit,
            datetime_of_service=arrow.utcnow().shift(days=-3).datetime,
        )
        without_visit = PatientFactory.create(last_name="Zzz")
        ordered = [
            p.id
            for p in apply_sorting(
                build_base_queryset(EXCLUDED_NOTE_TYPES), "last_visit", "asc", columns=[]
            )
        ]
        assert ordered.index(without_visit.id) < ordered.index(with_visit.id)

    @pytest.mark.parametrize("sort_by", ["patient", "last_visit", "room", "gaps", "tasks", "next_visit"])
    @pytest.mark.parametrize("sort_dir", ["asc", "desc"])
    def test_builtin_sorts_execute(self, sort_by: str, sort_dir: str) -> None:
        PatientFactory.create()
        PatientFactory.create()
        qs = apply_sorting(
            build_base_queryset(EXCLUDED_NOTE_TYPES), sort_by, sort_dir, columns=[],
        )
        # Force evaluation — exercises the ORDER BY SQL for each branch.
        assert qs.count() == 2

    def test_unknown_sort_by_is_noop(self) -> None:
        PatientFactory.create()
        qs = apply_sorting(build_base_queryset(), "nonexistent", "asc", columns=[])
        assert qs.count() == 1

    def test_spine_queryset_has_no_decoration_annotations(self) -> None:
        PatientFactory.create()
        assert build_spine_queryset().query.annotations == {}

    def test_annotate_sort_key_adds_only_requested_annotation(self) -> None:
        qs = annotate_sort_key(build_spine_queryset(), "last_visit", ("message",))
        assert "last_visit_ann" in qs.query.annotations
        assert "tasks_open_count" not in qs.query.annotations

    def test_annotate_sort_key_noop_for_name_sort(self) -> None:
        qs = annotate_sort_key(build_spine_queryset(), "patient", ())
        assert qs.query.annotations == {}

    def test_decoration_queryset_equals_base(self) -> None:
        PatientFactory.create()
        assert hasattr(build_decoration_queryset(("message",)).first(), "last_visit_ann")

    def test_apply_patient_filters_combined(self) -> None:
        p = PatientFactory.create(first_name="Zoe", last_name="Zimmer")
        PatientFactory.create(first_name="Alan", last_name="Adams")
        qs = apply_patient_filters(build_base_queryset(), patient_search="Zoe")
        ids = {row.id for row in qs}
        assert p.id in ids


def test_build_base_queryset_annotations_present() -> None:
    PatientFactory.create()
    qs = build_base_queryset(("message", "letter", "data", "ccda"))
    row = qs.first()
    for ann in (
        "facility_name_ann", "room_number_ann", "tasks_open_count",
        "tasks_all_count", "gaps_due_count", "gaps_total_count",
        "next_visit_ann", "last_visit_ann", "conditions_count_ann",
        "medications_count_ann", "allergies_count_ann", "referrals_count_ann",
    ):
        assert hasattr(row, ann)


def test_build_base_queryset_omits_visit_annotations_when_disabled() -> None:
    # Perf contract: include_visit_annotations=False must drop the
    # next/last-visit subqueries (the per-page ~20s note-state-rescan hotspot).
    # The remaining cheap annotations stay so the rest of the row renders.
    PatientFactory.create()
    row = build_base_queryset(
        ("message", "letter", "data", "ccda"), include_visit_annotations=False
    ).first()
    assert not hasattr(row, "next_visit_ann")
    assert not hasattr(row, "last_visit_ann")
    assert hasattr(row, "facility_name_ann")
    assert hasattr(row, "tasks_open_count")


def test_load_visit_stats_keys_by_uuid() -> None:
    from patient_panel.services.patient_query import load_visit_stats
    from tests.factories import PatientPanelStatsFactory

    patient = PatientFactory.create()
    PatientPanelStatsFactory.create(
        patient=patient,
        last_visit_dt=arrow.get("2024-03-15").datetime,
        next_visit_dt=arrow.get("2024-04-20").datetime,
    )
    stats = load_visit_stats([str(patient.id)])
    last_dt, next_dt = stats[str(patient.id)]
    assert last_dt == arrow.get("2024-03-15").datetime
    assert next_dt == arrow.get("2024-04-20").datetime
    # Patient with no stats row is simply absent (caller defaults to None/None).
    assert load_visit_stats([str(PatientFactory.create().id)]) == {}


def test_stats_sort_fields_map_to_real_columns() -> None:
    assert STATS_SORT_FIELDS["last_visit"] == "last_visit_dt"
    assert STATS_SORT_FIELDS["tasks"] == "tasks_open_count"


def test_apply_stats_sort_orders_by_stats_column() -> None:
    # apply_stats_sort is now PATIENT-rooted (orders via the panel_stats reverse
    # relation); root on Patient and read patient dbids (== stats.patient_id).
    from tests.factories import PatientPanelStatsFactory

    older = PatientPanelStatsFactory.create(last_visit_dt=arrow.get("2020-01-01").datetime)
    newer = PatientPanelStatsFactory.create(last_visit_dt=arrow.get("2024-01-01").datetime)
    qs = apply_stats_sort(Patient.objects.all(), "last_visit", "desc")
    ids = list(qs.values_list("dbid", flat=True))
    assert ids.index(newer.patient_id) < ids.index(older.patient_id)


def test_apply_stats_sort_last_visit_asc_nulls_first() -> None:
    from tests.factories import PatientPanelStatsFactory

    has = PatientPanelStatsFactory.create(last_visit_dt=arrow.get("2024-01-01").datetime)
    none = PatientPanelStatsFactory.create(last_visit_dt=None)
    ids = list(apply_stats_sort(Patient.objects.all(), "last_visit", "asc").values_list("dbid", flat=True))
    assert ids.index(none.patient_id) < ids.index(has.patient_id)  # no-visit first on asc


def test_apply_stats_sort_emits_correlated_subquery_not_inner_join() -> None:
    # The load-bearing property of the perf fix is the SQL SHAPE: a single
    # correlated subquery over the stats table (LEFT-JOIN-equivalent), NOT an
    # INNER JOIN (which would drop stats-less patients) and NOT per-branch
    # inlining. Pin it so an annotation refactor can't silently regress it.
    from patient_panel.models import PatientPanelStats

    tbl = PatientPanelStats._meta.db_table.lower()
    sql = str(apply_stats_sort(Patient.objects.all(), "last_visit", "asc").query).lower()
    assert sql.count(tbl) == 1  # exactly one reference — the subquery, not a join
    assert f"join {tbl}" not in sql
    assert "order by" in sql


def test_apply_stats_sort_keeps_patient_without_stats_row() -> None:
    # Headline correctness: a Patient with NO stats row is retained and sorts as
    # NULL, instead of being dropped by the old PatientPanelStats INNER-JOIN root.
    from tests.factories import PatientPanelStatsFactory

    has = PatientPanelStatsFactory.create(last_visit_dt=arrow.get("2024-01-01").datetime)
    norow = PatientFactory.create()
    ids = list(apply_stats_sort(Patient.objects.all(), "last_visit", "desc").values_list("dbid", flat=True))
    assert norow.dbid in ids  # kept despite having no stats row
    assert has.patient_id in ids
