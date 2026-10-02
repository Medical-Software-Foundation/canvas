"""Queryset filters and sorting for the patient panel table.

Pure query-builders over the Django ORM. No dependency on the SimpleAPI
instance: request-derived values (query params, excluded note types) are
passed in explicitly.
"""

from datetime import datetime
from typing import Any

import arrow
from django.db.models import (
    Case,
    Count,
    Exists,
    F,
    IntegerField,
    Max,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce

from canvas_sdk.v1.data import Patient
from canvas_sdk.v1.data.allergy_intolerance import AllergyIntolerance
from canvas_sdk.v1.data.care_team import CareTeamMembership, CareTeamMembershipStatus
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.coverage import Coverage, CoverageStack
from canvas_sdk.v1.data.medication import Medication
from canvas_sdk.v1.data.note import Note, NoteStates
from canvas_sdk.v1.data.patient import (
    PatientFacilityAddress,
    PatientMetadata as PatientMetadataRecord,
    PatientPhoto,
)
from canvas_sdk.v1.data.protocol_current import ProtocolCurrent
from canvas_sdk.v1.data.protocol_result import ProtocolResultStatus
from canvas_sdk.v1.data.referral import Referral
from canvas_sdk.v1.data.task import Task, TaskStatus

from patient_panel.models import PatientPanelStats


def _facility_name_subq() -> Any:
    return PatientFacilityAddress.objects.filter(patient=OuterRef("pk")).values("facility__name")[:1]


def _room_number_subq() -> Any:
    return PatientFacilityAddress.objects.filter(patient=OuterRef("pk")).values("room_number")[:1]


def _tasks_subq() -> Any:
    return (
        Task.objects.filter(patient=OuterRef("pk"))
        .values("patient")
        .annotate(
            open=Count(Case(When(status=TaskStatus.OPEN, then=1), output_field=IntegerField())),
            total=Count("id"),
        )
    )


def _gaps_subq() -> Any:
    return (
        ProtocolCurrent.objects.filter(
            patient=OuterRef("pk"),
            status__in=[
                ProtocolResultStatus.STATUS_DUE,
                ProtocolResultStatus.STATUS_SATISFIED,
                ProtocolResultStatus.STATUS_PENDING,
            ],
        )
        .values("patient")
        .annotate(
            due=Count(
                Case(When(status=ProtocolResultStatus.STATUS_DUE, then=1), output_field=IntegerField())
            ),
            total=Count("id"),
        )
    )


def _next_visit_subq() -> Any:
    return (
        Note.objects.filter(patient=OuterRef("pk"), datetime_of_service__gt=arrow.utcnow().datetime)
        .exclude(Q(current_state__state=NoteStates.DELETED) | Q(current_state__state=NoteStates.CANCELLED))
        .order_by("datetime_of_service")
        .values("datetime_of_service")[:1]
    )


def _last_visit_subq(excluded_note_types: tuple[str, ...]) -> Any:
    """Most recent billable, non-future, non-excluded, non-deleted visit.
    Replaces the Python get_last_visit() loop over prefetched notes.
    """
    return (
        Note.objects.filter(
            patient=OuterRef("pk"),
            note_type_version__is_billable=True,
            datetime_of_service__lte=arrow.utcnow().datetime,
        )
        .exclude(note_type__in=excluded_note_types)
        .exclude(Q(current_state__state=NoteStates.DELETED) | Q(current_state__state=NoteStates.CANCELLED))
        .order_by("-datetime_of_service")
        .values("datetime_of_service")[:1]
    )


def _conditions_count_subq() -> Any:
    return (
        Condition.objects.filter(
            patient=OuterRef("pk"),
            committer_id__isnull=False,
            entered_in_error_id__isnull=True,
            clinical_status="active",
        )
        .values("patient")
        .annotate(c=Count("id"))
        .values("c")
    )


def _medications_count_subq() -> Any:
    return (
        Medication.objects.filter(
            patient=OuterRef("pk"),
            committer_id__isnull=False,
            entered_in_error_id__isnull=True,
            status="active",
        )
        .values("patient")
        .annotate(c=Count("id"))
        .values("c")
    )


def _allergies_count_subq() -> Any:
    return (
        AllergyIntolerance.objects.filter(patient=OuterRef("pk"), deleted=False)
        .values("patient")
        .annotate(c=Count("id"))
        .values("c")
    )


def _referrals_count_subq() -> Any:
    return (
        Referral.objects.filter(patient=OuterRef("pk"), deleted=False)
        .values("patient")
        .annotate(c=Count("id"))
        .values("c")
    )


def build_spine_queryset() -> Any:
    """Lean Patient queryset for filtering/sorting/counting — NO decoration
    subqueries, NO prefetch. The page's decoration is attached separately to
    just the returned PKs (see build_decoration_queryset)."""
    return Patient.objects.all()


def build_base_queryset(
    excluded_note_types: tuple[str, ...] = (),
    *,
    include_visit_annotations: bool = True,
) -> Any:
    """Build the base Patient queryset for the table: prefetches + the column
    count/value annotations (facility, room, tasks, gaps, next visit, last
    visit, and the conditions/medications/allergies/referrals counts).

    Subqueries replace per-row N+1 .count()/.filter() calls. Count-filter
    semantics mirror the corresponding SDK managers (Condition.active(),
    Medication.active(), AllergyIntolerance, Referral).

    `last_visit_ann` collapses what used to be a full `notes` prefetch graph
    (notes + provider + roles + type + state) feeding a Python loop into a
    single correlated subquery. The old approach loaded EVERY note for every
    patient on the page; on instances where patients have thousands of notes
    that pulled tens of thousands of rows per page, hung /table, and starved
    the shared DB connection pool. `excluded_note_types` drops non-encounter
    note types (message/letter/data/ccda) from the "last visit" computation.

    `include_visit_annotations=False` omits the `next_visit_ann`/`last_visit_ann`
    subqueries. Each joins the `current_note_state` derived relation, which
    forces a full scan + disk-spilling DISTINCT-ON of the ~250k-row
    notestatechangeevent table RE-EXECUTED once per page row (the dominant
    /table cost: ~1s per patient, ~20s/page; it also inflates plan cost enough
    to trip Postgres JIT). When PatientPanelStats is in use the caller sources
    those two values from the precomputed stats row instead (see
    load_visit_stats) and sets them as attributes on the page instances.
    """
    patients_query = Patient.objects.select_related("default_provider").prefetch_related(
        "addresses",
        "telecom",
        "metadata",
        # Ordered so `patient.photo_url` (→ photos.first()) reads the prefetch
        # cache instead of issuing one query per row.
        Prefetch("photos", queryset=PatientPhoto.objects.order_by("pk")),
        Prefetch(
            "coverages",
            queryset=Coverage.objects.filter(stack=CoverageStack.IN_USE).select_related("issuer"),
        ),
        Prefetch(
            "care_team_memberships",
            queryset=CareTeamMembership.objects.filter(
                status=CareTeamMembershipStatus.ACTIVE,
            )
            .select_related("staff", "role")
            .prefetch_related("staff__photos")
            .order_by("created"),
        ),
    )
    patients_query = patients_query.annotate(
        facility_name_ann=Subquery(_facility_name_subq()),
        room_number_ann=Subquery(_room_number_subq()),
        tasks_open_count=Coalesce(Subquery(_tasks_subq().values("open")), Value(0)),
        tasks_all_count=Coalesce(Subquery(_tasks_subq().values("total")), Value(0)),
        gaps_due_count=Coalesce(Subquery(_gaps_subq().values("due")), Value(0)),
        gaps_total_count=Coalesce(Subquery(_gaps_subq().values("total")), Value(0)),
        conditions_count_ann=Coalesce(Subquery(_conditions_count_subq()), Value(0)),
        medications_count_ann=Coalesce(Subquery(_medications_count_subq()), Value(0)),
        allergies_count_ann=Coalesce(Subquery(_allergies_count_subq()), Value(0)),
        referrals_count_ann=Coalesce(Subquery(_referrals_count_subq()), Value(0)),
    )
    if include_visit_annotations:
        patients_query = patients_query.annotate(
            next_visit_ann=Subquery(_next_visit_subq()),
            last_visit_ann=Subquery(_last_visit_subq(excluded_note_types)),
        )
    return patients_query


# Decoration is exactly the old base queryset; alias for intent at call sites.
build_decoration_queryset = build_base_queryset


# {patient_uuid_str: (last_visit_dt, next_visit_dt)}. Plain assignment (not an
# annotated `: TypeAlias`) — the Canvas sandbox forbids importing TypeAlias from
# typing, and a bare alias is still recognized as one by type checkers.
VisitStatsMap = dict[str, tuple[datetime | None, datetime | None]]


def load_visit_stats(patient_ids: list[str]) -> VisitStatsMap:
    """Read precomputed last/next-visit datetimes from PatientPanelStats for a
    page of patients, keyed by patient UUID string.

    Replaces the per-request `last_visit_ann`/`next_visit_ann` correlated
    subqueries (see build_base_queryset) with a single indexed lookup. The
    stats row is maintained by the same exclusion logic offline
    (stats_recompute.compute_stat_values), so this is value-equivalent, not an
    approximation. Patients without a stats row are absent from the map; the
    caller defaults them to (None, None)."""
    rows = PatientPanelStats.objects.filter(patient__id__in=patient_ids).values_list(
        "patient__id", "last_visit_dt", "next_visit_dt"
    )
    return {str(pid): (last, nxt) for pid, last, nxt in rows}


# Built-in sort key → real indexed PatientPanelStats column. Query is rooted on
# PatientPanelStats (forward JOIN to patient); ORDER BY hits a real indexed
# column so Postgres can drive it with the index under LIMIT.
STATS_SORT_FIELDS: dict[str, str] = {
    "last_visit": "last_visit_dt",
    "next_visit": "next_visit_dt",
    "room": "room_number",
    "gaps": "gaps_due_count",
    "tasks": "tasks_open_count",
}


def apply_stats_sort(qs: Any, sort_by: str, sort_dir: str) -> Any:
    """Order a PATIENT-rooted queryset by a precomputed stats column.

    Implemented as a correlated Subquery annotation (`_stats_sort`) — NOT a SQL
    JOIN and NOT a reverse-relation traversal. The reverse accessor
    `panel_stats` is not registered on the queryable Patient model
    (CustomModel→SDK-model reverse relations raise FieldError) and
    FilteredRelation is sandbox-blocked, so the value is looked up per row via
    the unique `patient_id` index. The effect is LEFT-JOIN-EQUIVALENT: a patient
    with no stats row yields NULL, so it is KEPT and sorted as NULL rather than
    dropped — so a cold/empty stats table degrades to "no stats yet", never to
    missing patients.

    PERF NOTE: this is an ORDER-BY-over-correlated-subquery shape (the same shape
    as the slow live path), but each per-row subquery is a single unique-index
    probe (sub-ms), not the live path's note-state dedup — so it is cheap.
    Confirmed on a real Postgres instance: ~12 ms at 8k patients (single
    unique-index probe per row, no JIT) vs ~37 s for the live note-state path.
    Fall back to a PatientPanelStats-rooted explicit LEFT JOIN only if a future
    plan shows ms-per-loop or JIT.

    NULLs sort last in both directions EXCEPT last_visit ASC, where NULL
    (no-visit) surfaces first — matching apply_sorting's "no visit = most
    overdue" semantics.

    Caller MUST root `qs` on Patient and pass a `sort_by` present in
    STATS_SORT_FIELDS (callers gate on `sort_by in STATS_SORT_FIELDS`)."""
    col = STATS_SORT_FIELDS[sort_by]
    stat_value = Subquery(
        PatientPanelStats.objects.filter(patient_id=OuterRef("dbid")).values(col)[:1]
    )
    qs = qs.annotate(_stats_sort=stat_value)
    field = F("_stats_sort")
    if sort_by == "last_visit" and sort_dir != "desc":
        ordering = field.asc(nulls_first=True)
    elif sort_dir == "desc":
        ordering = field.desc(nulls_last=True)
    else:
        ordering = field.asc(nulls_last=True)
    return qs.order_by(ordering, "last_name")


def annotate_sort_key(qs: Any, sort_by: str, excluded_note_types: tuple[str, ...]) -> Any:
    """Annotate ONLY the one column needed to satisfy `sort_by`. Name/metadata/
    empty sorts add nothing (name uses real columns; metadata-ordinal adds its
    own subquery in sort_by_metadata_ordinal).

    Contract: every built-in sort_by value that apply_sorting orders by an
    annotation (last_visit_ann, next_visit_ann, room_number_ann, gaps_due_count,
    tasks_open_count) MUST have a matching branch here; omitting one causes
    apply_sorting to ORDER BY a missing annotation and raises FieldError."""
    if sort_by == "last_visit":
        return qs.annotate(last_visit_ann=Subquery(_last_visit_subq(excluded_note_types)))
    if sort_by == "next_visit":
        return qs.annotate(next_visit_ann=Subquery(_next_visit_subq()))
    if sort_by == "room":
        return qs.annotate(room_number_ann=Subquery(_room_number_subq()))
    if sort_by == "gaps":
        return qs.annotate(gaps_due_count=Coalesce(Subquery(_gaps_subq().values("due")), Value(0)))
    if sort_by == "tasks":
        return qs.annotate(tasks_open_count=Coalesce(Subquery(_tasks_subq().values("open")), Value(0)))
    return qs


def apply_patient_filters(
    patients_query: Any,
    *,
    staff_ids: list[str] | None = None,
    patient_search: str | None = None,
    insurances: list[str] | None = None,
    flagged_only: bool = False,
    protocols: list[str] | None = None,
    patient_ref: str = "pk",
    field_prefix: str = "",
) -> Any:
    """Apply common patient filters to a queryset.

    `patient_ref` controls the OuterRef key used in Exists subqueries
    (default ``"pk"`` for Patient-rooted querysets; pass ``"patient_id"``
    when the queryset is rooted on PatientPanelStats).
    `field_prefix` is prepended to direct field lookups in the
    ``patient_search`` clause (default ``""``; pass ``"patient__"`` when
    rooted on PatientPanelStats so the traversal resolves correctly).
    """
    if staff_ids:
        active_care_team_subquery = CareTeamMembership.objects.filter(
            patient_id=OuterRef(patient_ref),
            staff__id__in=staff_ids,
            status=CareTeamMembershipStatus.ACTIVE,
        )
        patients_query = patients_query.filter(Exists(active_care_team_subquery))

    if patient_search:
        patients_query = patients_query.filter(
            Q(
                *[
                    Q(**{f"{field_prefix}first_name__icontains": chunk})
                    | Q(**{f"{field_prefix}last_name__icontains": chunk})
                    | Q(**{f"{field_prefix}nickname__icontains": chunk})
                    for chunk in patient_search.split()
                ]
            )
        )

    if insurances:
        patients_query = patients_query.filter(
            Exists(
                Coverage.objects.filter(
                    patient_id=OuterRef(patient_ref),
                    stack=CoverageStack.IN_USE,
                    issuer__name__in=insurances,
                )
            )
        )

    if flagged_only:
        today_str = arrow.now().format("YYYY-MM-DD")
        patients_query = patients_query.filter(
            Exists(
                PatientMetadataRecord.objects.filter(
                    patient_id=OuterRef(patient_ref),
                    key="daily_flag",
                    value__startswith=today_str,
                )
            )
        )

    if protocols:
        patients_query = patients_query.filter(
            Exists(
                ProtocolCurrent.objects.filter(
                    patient_id=OuterRef(patient_ref),
                    title__in=protocols,
                    status=ProtocolResultStatus.STATUS_DUE,
                )
            )
        )

    return patients_query


def decorate_columns_with_filter_state(
    columns: list[dict[str, Any]],
    selected: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Return only filterable metadata columns, each annotated with
    `selected_values` (csv string) and the resolved option list.

    Option resolution:
      - `filter_options` if explicitly configured;
      - else `sort_order` (re-use the ordinal list when both apply);
      - else an empty list (UI may then degrade to a text input or hide).
    """
    decorated: list[dict[str, Any]] = []
    for col in columns:
        if col.get("type") != "metadata" or not col.get("filterable"):
            continue
        key = col.get("key", "")
        if not key:
            continue
        options = col.get("filter_options") or col.get("sort_order") or []
        decorated.append({
            **col,
            "filter_options_resolved": list(options),
            "selected_values": ",".join(selected.get(key, [])),
        })
    return decorated


def read_metadata_filter_params(
    query_params: Any, columns: list[dict[str, Any]]
) -> dict[str, list[str]]:
    """Parse `metadata_<key>` query params for filterable metadata cols.

    `query_params` is any object exposing `.get(key, default)`. Returns
    {key: [v1, v2, ...]} containing only entries whose column is declared
    filterable. Empty / missing params are skipped.
    """
    result: dict[str, list[str]] = {}
    for col in columns:
        if col.get("type") != "metadata" or not col.get("filterable"):
            continue
        key = col.get("key", "")
        if not key:
            continue
        raw = query_params.get(f"metadata_{key}", "").strip()
        if not raw:
            continue
        values = [v.strip() for v in raw.split(",") if v.strip()]
        if values:
            result[key] = values
    return result


def apply_metadata_filters(
    patients_query: Any,
    selected: dict[str, list[str]],
    columns: list[dict[str, Any]],
    patient_ref: str = "pk",
) -> Any:
    """Restrict the queryset to patients whose metadata matches `selected`.

    `selected` maps metadata key → list of acceptable values. Only keys that
    correspond to a metadata column with `filterable: true` are honored —
    anything else is silently dropped to avoid open-ended filtering on
    arbitrary keys.

    `patient_ref` controls the OuterRef key used in Exists subqueries
    (default ``"pk"`` for Patient-rooted querysets; pass ``"patient_id"``
    when the queryset is rooted on PatientPanelStats).
    """
    if not selected:
        return patients_query

    filterable_keys = {
        col["key"]
        for col in columns
        if col.get("type") == "metadata" and col.get("filterable") and col.get("key")
    }

    for key, values in selected.items():
        if key not in filterable_keys or not values:
            continue
        patients_query = patients_query.filter(
            Exists(
                PatientMetadataRecord.objects.filter(
                    patient_id=OuterRef(patient_ref),
                    key=key,
                    value__in=values,
                )
            )
        )
    return patients_query


def find_sortable_metadata_column(
    sort_by: str, columns: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the metadata column entry matching sort_by, or None.

    A metadata column is sortable here only when it declares a non-empty
    `sort_order` list. Without that list there is no ordinal mapping.
    """
    if not sort_by:
        return None
    for col in columns:
        if col.get("type") != "metadata":
            continue
        sort_key = col.get("sort_key") or col.get("key")
        if sort_key != sort_by:
            continue
        order = col.get("sort_order")
        if isinstance(order, list) and order:
            return col
    return None


def sort_by_metadata_ordinal(
    patients_query: Any, col: dict[str, Any], sort_dir: str
) -> Any:
    """Order rows by the index of their metadata value in col[sort_order].

    Computes each patient's ordinal with a single ``Max(Case(...))`` aggregate
    over the reverse ``metadata`` relation, which Django emits as ONE
    ``LEFT OUTER JOIN`` + ``GROUP BY`` — not a correlated subquery and not the
    sandbox-blocked ``FilteredRelation``. The ``Case`` returns the ordinal only
    for the join row whose ``key`` matches (``default=None``), so every other
    metadata row contributes NULL and ``Max`` collapses the group to just the
    risk row's ordinal — or NULL when the patient has no value for ``key``.

    Why an aggregate join and not a correlated ``Subquery``: an earlier
    ``Subquery`` form was inlined once per ``Case`` branch (``len(sort_order)+1``
    correlated subqueries) and evaluated for EVERY patient row in the
    population with no LIMIT pushdown — the per-row-subquery pattern
    PatientPanelStats was built to kill for built-in sorts. At scale it
    saturated the DB pool and 502'd the whole instance. Metadata sorts can't
    move to PatientPanelStats (config-driven; CustomModel DDL is append-only),
    so the set-based join is the fix that stays within allowed imports.

    Direction is folded into the ordinal (desc inverts known ranks) so both
    directions order ``ASC NULLS LAST``: known values first in the requested
    order, then key-present-but-unrecognized values (``sentinel``), then
    patients missing the key (NULL). Relies on the one-value-per-(patient, key)
    invariant of the metadata store.
    """
    key = col["key"]
    sort_order: list[str] = list(col["sort_order"])
    n = len(sort_order)
    sentinel = n  # key present but value not in sort_order — after all known

    if sort_dir == "desc":
        ranks = {val: (n - 1 - idx) for idx, val in enumerate(sort_order)}
    else:
        ranks = {val: idx for idx, val in enumerate(sort_order)}

    whens = [
        When(Q(metadata__key=key, metadata__value=val), then=Value(rank))
        for val, rank in ranks.items()
    ]
    # Matching key with an unrecognized value → sentinel. Non-matching join
    # rows fall through to default=None so Max ignores them.
    whens.append(When(Q(metadata__key=key), then=Value(sentinel)))
    case_expr = Case(*whens, default=None, output_field=IntegerField())

    annotated = patients_query.annotate(_meta_sort_index=Max(case_expr))
    return annotated.order_by(
        F("_meta_sort_index").asc(nulls_last=True),
        "last_name",
    )


def apply_sorting(
    patients_query: Any,
    sort_by: str,
    sort_dir: str,
    columns: list[dict[str, Any]] | None = None,
) -> Any:
    """Apply sorting to the patient queryset.

    Built-in sort keys (patient, last_visit, room, gaps, tasks, etc.) are
    handled below. For metadata columns with a `sort_order` list, order rows
    by the index of their metadata value in that list. Unknown or missing
    values sort last in either direction. The last_visit sort reuses the
    `last_visit_ann` annotation from build_base_queryset (which already drops
    non-encounter note types), so no per-sort note subquery is built here.
    """
    if not sort_by:
        return patients_query

    meta_col = find_sortable_metadata_column(sort_by, columns or [])
    if meta_col is not None:
        return sort_by_metadata_ordinal(patients_query, meta_col, sort_dir)

    if sort_by == "patient":
        if sort_dir == "desc":
            patients_query = patients_query.order_by(
                F("last_name").desc(nulls_last=True),
                F("first_name").desc(nulls_last=True),
            )
        else:
            patients_query = patients_query.order_by(
                F("last_name").asc(nulls_last=True),
                F("first_name").asc(nulls_last=True),
            )
    elif sort_by == "last_visit":
        # Reuse the last_visit_ann annotation from build_base_queryset.
        # Treat "no visit" as most-overdue: surface them at the top of
        # asc (oldest-first) and at the bottom of desc (recent-first).
        if sort_dir == "desc":
            patients_query = patients_query.order_by(
                F("last_visit_ann").desc(nulls_last=True), "last_name"
            )
        else:
            patients_query = patients_query.order_by(
                F("last_visit_ann").asc(nulls_first=True), "last_name"
            )
    elif sort_by == "room":
        if sort_dir == "desc":
            patients_query = patients_query.order_by(
                F("room_number_ann").desc(nulls_last=True), "last_name"
            )
        else:
            patients_query = patients_query.order_by(
                F("room_number_ann").asc(nulls_last=True), "last_name"
            )
    elif sort_by == "gaps":
        if sort_dir == "desc":
            patients_query = patients_query.order_by(
                F("gaps_due_count").desc(nulls_last=True), "last_name"
            )
        else:
            patients_query = patients_query.order_by(
                F("gaps_due_count").asc(nulls_last=True), "last_name"
            )
    elif sort_by == "tasks":
        if sort_dir == "desc":
            patients_query = patients_query.order_by(
                F("tasks_open_count").desc(nulls_last=True), "last_name"
            )
        else:
            patients_query = patients_query.order_by(
                F("tasks_open_count").asc(nulls_last=True), "last_name"
            )
    elif sort_by == "next_visit":
        if sort_dir == "desc":
            patients_query = patients_query.order_by(
                F("next_visit_ann").desc(nulls_last=True), "last_name"
            )
        else:
            patients_query = patients_query.order_by(
                F("next_visit_ann").asc(nulls_last=True), "last_name"
            )
    return patients_query
