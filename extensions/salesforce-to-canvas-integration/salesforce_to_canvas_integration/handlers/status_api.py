"""Status + admin endpoints used by the admin application.

* ``GET /status``         — JSON status payload (inbound events bucketed into
                            needs action, applied, and skipped, connection
                            state, field mapping).
* ``GET /admin``          — HTML admin page launched in a modal by the
                            :class:`SalesforceAdminApp`.
* ``POST /disconnect``    — clear stored OAuth tokens (admin action).
"""

from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import (
    SessionCredentials,
    SimpleAPI,
    StaffSessionAuthMixin,
    api,
)
from canvas_sdk.templates import render_to_string
from canvas_sdk.utils.http import Http
from canvas_sdk.v1.data.patient import Patient
from logger import log

from salesforce_to_canvas_integration.models import (
    IncomingPatientRecord,
    ResolutionAuditEntry,
    StaffProxy,
)
from salesforce_to_canvas_integration.models.field_mapping_settings import (
    PROFILE_CUSTOM,
    PROFILE_SECRET,
    VALID_PROFILES,
    FieldMappingState,
    load_field_mapping_state,
    save_field_mapping,
)
from salesforce_to_canvas_integration.models.sync_settings import (
    load_sync_settings,
    save_sync_settings,
)
from salesforce_to_canvas_integration.services.canvas_fhir_client import (
    CanvasFhirAuthError,
    CanvasFhirClient,
    CanvasFhirError,
    CanvasFhirNotConfiguredError,
    build_canvas_fhir_client,
)
from salesforce_to_canvas_integration.services.config import (
    DEFAULT_FIELD_MAPPING,
    ConfigError,
    PluginConfig,
    canvas_fhir_configured,
    field_mapping_secret,
    load_config,
    secret_field_mapping_set,
)
from salesforce_to_canvas_integration.services.effect_builder import (
    build_create_patient_effect,
    build_mapped_patient_from_form,
    build_tag_deleted_effect,
    build_update_patient_effect,
)
from salesforce_to_canvas_integration.services.field_mapping import (
    MappedPatient,
    MappingError,
    PromotePrefill,
    build_promote_prefill,
    map_record,
)
from salesforce_to_canvas_integration.services.patient_link import (
    SALESFORCE_IDENTIFIER_SYSTEM,
    find_duplicate_patients,
    find_linked_patient_id,
)
from salesforce_to_canvas_integration.services.patient_snapshot import (
    canvas_demographics_by_id as _canvas_demographics_by_id,
    format_date as _format_date,
    patient_demographics as _patient_demographics,
)
from salesforce_to_canvas_integration.services.resolution import (
    ResolutionActor,
    append_decision,
    write_resolution,
)
from salesforce_to_canvas_integration.services.salesforce_links import (
    build_salesforce_record_url,
)
from salesforce_to_canvas_integration.services.storage import TokenStore
from salesforce_to_canvas_integration.services.sync_rules import (
    DELETE_ACTIONS,
    REQUIRED_FIELD_CHOICES,
    SyncSettings,
)
from salesforce_to_canvas_integration.templates import (
    render_admin_page,
    render_no_access_page,
    render_not_configured_page,
)

# Status the inbound capture lands with, see journal cnv-909/059.
_STATUS_NEW = "new"
_STATUS_ACCEPTED = "accepted"
_STATUS_DISMISSED = "dismissed"

# Statuses a resolution route may act on. Story two of the audit redesign makes
# skip reversible, so a dismissed row is actionable again, it can be reopened or
# amended and accepted directly. An accepted row stays blocked here, replaying an
# applied event is a later story. See journal cnv-909/089 and cnv-909/090.
_ACTIONABLE_STATUSES = (_STATUS_NEW, _STATUS_DISMISSED)

# Step two of cnv-909/074 lands the modify action alongside create. Step three
# adds the delete action. Each audit route filters to its action so the
# orchestration paths stay independent.
_ACTION_CREATE = "create"
_ACTION_MODIFY = "modify"
_ACTION_DELETE = "delete"

# The two Salesforce side events, the only thing the rep actually set on the
# Canvas Sync field. A delete arrival is a Delete, every create or modify
# arrival is a Sync, since create and modify are derived verbs of what the
# plugin will do here, not events. The verb lives on the action button, the
# event is the audit fact the Activity ledger keeps. See journal cnv-938/017 018.
_EVENT_SYNC = "Sync"
_EVENT_DELETE = "Delete"


def _event_label(stored_action: str) -> str:
    """The Salesforce side event a stored row represents, Sync or Delete.

    Two events ride the wire, matching the two Canvas Sync field values. A
    delete arrival is a Delete, a create or modify arrival is a Sync. Create and
    modify are derived verbs, what the plugin will do to Canvas, not events, so
    they both fold to the one Sync event the rep actually set. See journal
    cnv-938/017 018.
    """
    return _EVENT_DELETE if stored_action == _ACTION_DELETE else _EVENT_SYNC

# Rows the activity endpoint returns in one page. The Activity tab loads the
# newest page, then a Load more button asks for the next page with a keyset
# cursor, so the operator can read the whole ledger. Search and sorting are a
# later read side story. See journal cnv-928/005.
_ACTIVITY_LIMIT = 200

# Decision log action_taken values that wrote demographics to the Canvas chart.
# The activity ledger fills the Applied column from the event's resolved typed
# columns only for these, the other resolutions changed no demographics so their
# Applied column stays empty. See journal cnv-909/104.
_DEMOGRAPHIC_APPLY_ACTIONS = frozenset(
    {
        "created",
        "modify_applied",
        "promoted_to_create",
    }
)

# Decision log action_taken values that actually changed the Canvas chart. The
# gap banner anchor is the most recent event resolved through one of these.
# Skip, reopen, dismiss, and create_superseded changed nothing in Canvas, so
# they are never anchors. See journal cnv-909/088 The Gap Banner and Decisions
# Locked, and 092 story six.
_CANVAS_CHANGING_ACTIONS = frozenset(
    {
        "created",
        "matched",
        "modify_applied",
        "promoted_to_create",
        "tag_deleted",
        "unlink",
        "mark_inactive",
    }
)

# The two kinds of line in the Activity feed. An arrival is an inbound Salesforce
# event keyed by its received time, a decision is an operator resolution keyed by
# its decision time. The rank orders the two when they share a timestamp so the
# merged feed has one strict total order, decision ahead of arrival. See journal
# cnv-928/014 and 015.
_KIND_RECEIVED = "received"
_KIND_DECISION = "decision"
_KIND_RANK = {_KIND_RECEIVED: 0, _KIND_DECISION: 1}

# Sort key fallback so a row with a missing timestamp sorts oldest rather than
# raising on a None comparison. Both feed timestamps are non null in practice.
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _effective_action(stored_action: str, linked: bool) -> str:
    """The action a row means right now, derived from the live patient link.

    Capture stamps the action once, when the sync arrives. A sync for an
    unlinked Salesforce id lands as a create, honestly, because there is no
    patient yet. The link can appear later though, when an operator approves
    the first row or another row creates the patient, and from that moment
    every pending row for the id is really a modify of the linked patient, not
    a second create. Deriving the action from the live link at read and apply
    time keeps the stored row as the immutable arrival record while the console
    always routes on what the row means now. A stored create with a link reads
    as a modify, everything else passes through, a stored modify keeps its own
    promote path and a delete its own state logic. See journal cnv-938/015 016.
    """
    if stored_action == _ACTION_CREATE and linked:
        return _ACTION_MODIFY
    return stored_action


def _record_view(
    row: IncomingPatientRecord,
    field_mapping: dict[str, dict[str, str]],
    skip_decision: dict[str, Any] | None = None,
    linked: bool | None = None,
    instance_url: str = "",
    patient_id: str = "",
) -> dict[str, Any]:
    """Serialize the newest event row for an external id into the admin payload.

    The raw Salesforce payload is mapped through the configured field map so the
    admin table can show the full demographic set, not only the four typed
    columns. A malformed map degrades to the typed columns plus the raw payload,
    so the audit trail stays faithful even when the mapping is wrong.

    ``skip_decision`` carries the latest skip note, skipper name, and skip time
    for a skipped row, so the Details modal can name why the record was skipped.
    It is attached only on the skipped branch of ``_bucket_records``, pending
    rows pass None and stay untouched. See journal cnv-928/012.

    ``linked`` lets the caller pass a precomputed live link result so the
    bucketing path can reuse its memoized lookup. When None we resolve it here.
    See journal cnv-938/016.

    ``instance_url`` and ``patient_id`` feed the Salesforce record link and the
    patient chart link the inline expanded row shows, the same pair the Synced
    and Activity serializers carry. With no instance url the link field falls
    to an empty string and the client renders no link. See journal cnv-941/012.
    """
    mapped_fields: dict[str, Any] = {}
    metadata: dict[str, str] = {}
    telecom: dict[str, str] = {}
    try:
        mapped = map_record(row.raw_payload or {}, field_mapping)
        mapped_fields = mapped.canvas_fields
        metadata = mapped.metadata
        telecom = mapped.telecom
    except MappingError:
        pass
    # Whether a Canvas patient is linked to this Salesforce id right now. The
    # flag lights up the Apply update, Review and edit, and Tag deleted actions
    # in the table, surfaces an Unlinked warning otherwise, and drives the
    # effective action. A create row whose id is linked is no longer a create,
    # it is a modify of that patient, so we serialize the effective action and
    # keep the stored label under arrival_action. See journal cnv-938/015 016.
    if linked is None:
        patient_id = find_linked_patient_id(row.external_id) or ""
        linked = bool(patient_id)
    return {
        "event_id": row.pk,
        "external_id": row.external_id,
        # The live linked Canvas patient and the Salesforce record link, what
        # the expanded row's links bar opens. See journal cnv-941/012.
        "patient_id": patient_id,
        "salesforce_url": _salesforce_record_url(
            instance_url, row.source_object or "", row.external_id
        ),
        "source_object": row.source_object,
        "action": _effective_action(row.action, linked),
        "arrival_action": row.action,
        # The Salesforce side event, Sync or Delete, derived from the stored
        # arrival action. The verb (Create, Modify, Delete) lives on the action
        # button and is derived from the live link client side. See cnv-938/017.
        "event": _event_label(row.action),
        "first_name": row.first_name,
        "last_name": row.last_name,
        "email": row.email,
        "phone": row.phone,
        "status": row.status,
        "canvas_patient_id": row.canvas_patient_id,
        "received_at": row.received_at.isoformat() if row.received_at else None,
        "actioned_at": row.actioned_at.isoformat() if row.actioned_at else None,
        "mapped": mapped_fields,
        "metadata": metadata,
        "telecom": telecom,
        "raw_payload": row.raw_payload,
        "linked": linked,
        # Why the deliberate sync evaluator held this row for manual action, the
        # short stable reason strings from services.sync_rules. Empty on a row
        # the evaluator auto applied and on rows captured before the evaluator
        # wired in. The Details modal lists them so a held row says why. See
        # journal cnv-938/032 and 038.
        "hold_reasons": list(row.hold_reasons or []),
        # The latest skip reason, skipper, and skip time, present only on a
        # skipped row. The Details modal banner reads off these. See journal
        # cnv-928/012.
        "skip_reason": (skip_decision or {}).get("note", ""),
        "skipped_by": (skip_decision or {}).get("staff_name", ""),
        "skipped_at": (skip_decision or {}).get("created_at"),
    }


def _compute_event_gap(
    current: IncomingPatientRecord,
    record_events: list[IncomingPatientRecord],
    canvas_changing_event_ids: set[int],
    skip_actor_by_event_id: dict[int, str],
) -> dict[str, Any]:
    """Count the unresolved events between ``current`` and its anchor.

    The anchor is the most recent event for the same record that changed the
    Canvas chart, resolved through one of ``_CANVAS_CHANGING_ACTIONS``. The gap
    is every event captured after the anchor and before ``current`` that is
    still unresolved, skipped or pending. A record that never changed Canvas has
    no anchor, so the whole unresolved history before ``current`` counts, which
    yields the one skipped creation case for free.

    ``older_than_last_applied`` is the warn but allow signal from journal
    cnv-909/089 question two. It is true when ``current`` is older than the most
    recent Canvas changing event for the record, so applying it would replay an
    older event over a newer change. ``events`` drives the banner tooltip,
    ordered oldest first, each carrying the action, the date, and the operator
    who last touched it, empty for a still pending event. The helper is pure so
    it unit tests on SQLite without the Postgres only status query. See journal
    cnv-909/088 The Gap Banner and Decisions Locked, and 092 story six.
    """
    current_received = current.received_at

    # The most recent Canvas changing event across the whole record timeline
    # drives the older than last applied signal, regardless of where current
    # sits. The anchor for the gap is the most recent Canvas changing event
    # captured strictly before current.
    last_applied_received: datetime | None = None
    anchor_received: datetime | None = None
    for event in record_events:
        if event.pk not in canvas_changing_event_ids:
            continue
        received = event.received_at
        if last_applied_received is None or received > last_applied_received:
            last_applied_received = received
        if received < current_received and (
            anchor_received is None or received > anchor_received
        ):
            anchor_received = received

    older_than_last_applied = (
        last_applied_received is not None and current_received < last_applied_received
    )

    gap_rows = [
        event
        for event in record_events
        if event.pk != current.pk
        and event.received_at < current_received
        and (anchor_received is None or event.received_at > anchor_received)
        and event.status in (_STATUS_NEW, _STATUS_DISMISSED)
    ]
    gap_rows.sort(key=lambda event: (event.received_at, event.pk))

    events_view: list[dict[str, Any]] = []
    for event in gap_rows:
        who = (
            skip_actor_by_event_id.get(event.pk, "")
            if event.status == _STATUS_DISMISSED
            else ""
        )
        events_view.append(
            {
                "event_id": event.pk,
                "action": event.action,
                "received_at": (
                    event.received_at.isoformat() if event.received_at else None
                ),
                "status": event.status,
                "who": who,
            }
        )

    return {
        "count": len(events_view),
        "has_anchor": anchor_received is not None,
        "older_than_last_applied": older_than_last_applied,
        "events": events_view,
    }


def _bucket_records(
    rows: Any,
    field_mapping: dict[str, dict[str, str]],
    canvas_changing_event_ids: set[int] | None = None,
    skip_actor_by_event_id: dict[int, str] | None = None,
    skip_decision_by_event_id: dict[int, dict[str, Any]] | None = None,
    instance_url: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split every captured event into needs action and skipped.

    The Records screen is the actionable surface, so it carries only the two
    buckets that still have an action to take, needs action and skipped. Needs
    action collapses to one row per contact, the newest pending event across
    every action, since a one directional sync makes the latest Salesforce state
    the truth and every older pending event is history rather than a separate
    decision. A newest delete with no linked Canvas patient drops out entirely,
    it has nothing to act on. Skipped still lists one item per skipped event.
    Applied events have no action left, so they no longer ride here, the full
    applied story lives in the Activity ledger which joins the event log with the
    decision log. Each bucket is newest event first. Pulled out of ``status`` so
    the selection is unit testable without the query that feeds it. See journal
    cnv-909/092 story four, 104, and cnv-938/022.

    When ``canvas_changing_event_ids`` is supplied, story six attaches a ``gap``
    object to each pending row so the resolve and promote forms can show the gap
    banner and the warn but allow heads up without a second round trip. Omitting
    it keeps the pre story six shape for the existing helper tests. See journal
    cnv-909/092 story six.

    When ``skip_decision_by_event_id`` is supplied, each skipped row carries the
    latest skip note, skipper name, and skip time so the Details modal can name
    why it was skipped. Pending rows pass None and stay untouched. See journal
    cnv-928/012.
    """
    pending: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    ordered = sorted(rows, key=lambda r: r.received_at, reverse=True)

    events_by_external: dict[str, list[IncomingPatientRecord]] = {}
    for row in ordered:
        events_by_external.setdefault(row.external_id, []).append(row)

    # The linked patient lookup hits the database, so memoize it per external id.
    # A record can have more than one delete row, and we never want to pay the
    # lookup twice for the same id. The memo keeps the patient id itself, the
    # expanded row links bar needs it for the chart link. See journal cnv-941/012.
    linked_by_external: dict[str, str] = {}

    def _linked_patient_id(external_id: str) -> str:
        if external_id not in linked_by_external:
            linked_by_external[external_id] = (
                find_linked_patient_id(external_id) or ""
            )
        return linked_by_external[external_id]

    def _patient_linked(external_id: str) -> bool:
        return bool(_linked_patient_id(external_id))

    # One actionable row per contact. The newest pending row across every action
    # is the only live decision, because a one directional Salesforce sync means
    # the latest Salesforce state is the truth. Every older pending event is
    # history the operator reads in the Details overridden chain, not a row they
    # act on, and create or modify and delete are one lane here, the newest of
    # any action wins. ``ordered`` is newest first, so the first pending row seen
    # per Salesforce id is the newest. See journal cnv-938/022.
    newest_pending_pk: dict[str, int] = {}
    for row in ordered:
        if row.status != _STATUS_NEW:
            continue
        if row.external_id not in newest_pending_pk:
            newest_pending_pk[row.external_id] = row.pk

    for row in ordered:
        if row.status == _STATUS_NEW:
            # An older pending event is superseded by a newer arrival. It is not
            # a row, it rides inside the newest row's overridden history and the
            # Activity ledger. See journal cnv-938/022.
            if newest_pending_pk.get(row.external_id) != row.pk:
                continue
            is_delete = row.action == _ACTION_DELETE
            patient_linked = _patient_linked(row.external_id)
            # A delete as the newest event with no linked Canvas patient has
            # nothing to delete, so it is not an actionable row. The arrival still
            # lives in the Activity ledger, it just leaves the Records surface.
            # See journal cnv-938/022.
            if is_delete and not patient_linked:
                continue
            view = _record_view(
                row,
                field_mapping,
                linked=patient_linked,
                instance_url=instance_url,
                patient_id=_linked_patient_id(row.external_id),
            )
            if canvas_changing_event_ids is not None:
                view["gap"] = _compute_event_gap(
                    row,
                    events_by_external.get(row.external_id, []),
                    canvas_changing_event_ids,
                    skip_actor_by_event_id or {},
                )
            # Every emitted row is the live decision for its contact, so it is
            # always actionable. The inert superseded and no patient delete states
            # left the list with the collapse, an emitted delete always has a
            # linked patient. See journal cnv-938/022.
            view["actionable"] = True
            view["supersede_reason"] = ""
            pending.append(view)
        elif row.status == _STATUS_DISMISSED:
            skip_decision = (skip_decision_by_event_id or {}).get(row.pk)
            skipped.append(
                _record_view(
                    row,
                    field_mapping,
                    skip_decision,
                    linked=_patient_linked(row.external_id),
                    instance_url=instance_url,
                    patient_id=_linked_patient_id(row.external_id),
                )
            )
    return pending, skipped


def _demographics_full(
    canvas_fields: dict[str, Any],
    telecom: dict[str, str],
    *,
    first_name: str,
    last_name: str,
    email: str,
    phone: str,
) -> dict[str, str]:
    """Pack the full demographic set the Activity Details comparison table shows.

    The name, email, and phone come from the caller, the stored Canvas columns on
    the applied side or the mapped payload on the received side. The date of
    birth, sex at birth, mobile, and address come from the mapped payload, since
    those four are not persisted as discrete columns, so on the applied side they
    mirror what the mapped payload wrote. The client formats the name and address
    from these parts with the same helpers the Records details modal uses. See
    journal cnv-928/023.
    """
    return {
        "first_name": str(first_name or ""),
        "last_name": str(last_name or ""),
        "date_of_birth": str(canvas_fields.get("date_of_birth") or ""),
        "sex_at_birth": str(canvas_fields.get("sex_at_birth") or ""),
        "email": str(email or ""),
        "phone": str(phone or ""),
        "mobile": str(telecom.get("mobile") or ""),
        "address_line_1": str(canvas_fields.get("address_line_1") or ""),
        "address_line_2": str(canvas_fields.get("address_line_2") or ""),
        "city": str(canvas_fields.get("city") or ""),
        "state": str(canvas_fields.get("state") or ""),
        "postal_code": str(canvas_fields.get("postal_code") or ""),
        "country": str(canvas_fields.get("country") or ""),
    }


def _latest_salesforce_demographics(
    external_id: str, field_mapping: dict[str, dict[str, str]]
) -> dict[str, str]:
    """Snapshot the latest Salesforce data the plugin holds for one record.

    Feeds the Salesforce column of the Synced Details comparison. Reads the
    newest captured event for the record and maps it through the field mapping,
    so the column shows the freshest payload Salesforce sent. Returns an empty
    snapshot when no event was ever captured. See journal cnv-928/026.
    """
    event = (
        IncomingPatientRecord.objects.filter(external_id=external_id)
        .order_by("-received_at", "-pk")
        .first()
    )
    if event is None:
        return {}
    mapped = _safe_map_record(event.raw_payload, field_mapping)
    cf = mapped.canvas_fields
    return _demographics_full(
        cf,
        mapped.telecom,
        first_name=str(cf.get("first_name") or event.first_name or ""),
        last_name=str(cf.get("last_name") or event.last_name or ""),
        email=str(cf.get("email") or event.email or ""),
        phone=str(cf.get("phone") or event.phone or ""),
    )


def _activity_view(
    entry: ResolutionAuditEntry,
    event: IncomingPatientRecord | None,
    field_mapping: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Serialize one decision joined with its event for the activity ledger.

    The decision log says who acted, when, and what, the event log carries the
    values. Joining them gives the ledger a Received column, the demographics the
    event arrived with, mapped from the immutable raw payload, and an Applied
    column, what the resolution actually wrote to Canvas. Applied is filled only
    for the demographic writing resolutions, the others leave it empty since they
    changed no demographics. Ordered by the decision time upstream, so the newest
    action sits first and the topmost applied row is the live value. See journal
    cnv-909/104.
    """
    received: dict[str, str] | None = None
    applied: dict[str, str] | None = None
    if event is not None:
        mapped = _safe_map_record(event.raw_payload, field_mapping)
        cf = mapped.canvas_fields
        telecom = mapped.telecom
        received = _demographics_full(
            cf,
            telecom,
            first_name=str(cf.get("first_name") or event.first_name or ""),
            last_name=str(cf.get("last_name") or event.last_name or ""),
            email=str(cf.get("email") or event.email or ""),
            phone=str(cf.get("phone") or event.phone or ""),
        )
        if entry.action_taken in _DEMOGRAPHIC_APPLY_ACTIONS:
            applied = _demographics_full(
                cf,
                telecom,
                first_name=event.first_name or "",
                last_name=event.last_name or "",
                email=event.email or "",
                phone=event.phone or "",
            )
    return {
        # The row dbid, carried so the Load more cursor can key on it as the
        # created_at tiebreaker. See journal cnv-928/005.
        "id": entry.pk,
        "external_id": entry.external_id,
        "action": entry.action,
        "action_taken": entry.action_taken,
        "staff_name": entry.staff_name,
        "staff_key": entry.staff_key,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "note": entry.note,
        "result_patient_id": entry.result_patient_id,
        "event_id": entry.event_id,
        "received": received,
        "applied": applied,
        # The chart snapshot taken before a modify apply wrote, in the compare
        # shape. Present only on an applied modify, the one resolution that had a
        # patient before it. None elsewhere, so the client reads it as the Was in
        # Canvas column only when it exists. See journal cnv-928/037.
        "canvas_before": entry.canvas_before or None,
    }


def _arrival_feed_item(
    event: IncomingPatientRecord,
    field_mapping: dict[str, dict[str, str]],
    instance_url: str = "",
) -> tuple[tuple[datetime, int, int], dict[str, Any]]:
    """Build one arrival line for the Activity feed from an inbound event.

    The widened Activity feed records every inbound Salesforce event when it
    arrived, alongside the decisions on it, so the ledger reads as the full
    story. An arrival fills the Received column from the mapped payload and
    leaves the decision side empty, it carries an arrived marker rather than a
    resolution. The item also carries the Salesforce record link so the row can
    show the quiet link Synced shows. Returns the sort key paired with the
    serialized item. See journal cnv-928/014, 015, and 030.
    """
    mapped = _safe_map_record(event.raw_payload, field_mapping)
    cf = mapped.canvas_fields
    received = _demographics_full(
        cf,
        mapped.telecom,
        first_name=str(cf.get("first_name") or event.first_name or ""),
        last_name=str(cf.get("last_name") or event.last_name or ""),
        email=str(cf.get("email") or event.email or ""),
        phone=str(cf.get("phone") or event.phone or ""),
    )
    ts = event.received_at
    item = {
        "kind": _KIND_RECEIVED,
        "id": event.pk,
        "event_id": event.pk,
        "ts": ts.isoformat() if ts else None,
        "external_id": event.external_id,
        "action": event.action,
        # The Sync or Delete event the arrival carried, the audit fact the
        # Activity Event column shows. See journal cnv-938/017 018.
        "event": _event_label(event.action),
        "action_taken": "",
        "staff_name": "",
        "received": received,
        "applied": None,
        # An arrival changed nothing in Canvas, so it has no chart before.
        "canvas_before": None,
        "result_patient_id": "",
        "note": "",
        "salesforce_url": _salesforce_record_url(
            instance_url, event.source_object or "", event.external_id
        ),
    }
    return (ts or _EPOCH, _KIND_RANK[_KIND_RECEIVED], event.pk), item


def _decision_feed_item(
    entry: ResolutionAuditEntry,
    event: IncomingPatientRecord | None,
    field_mapping: dict[str, dict[str, str]],
    instance_url: str = "",
) -> tuple[tuple[datetime, int, int], dict[str, Any]]:
    """Build one decision line for the Activity feed from a resolution.

    Wraps the existing :func:`_activity_view` join and tags it with the feed
    kind and a single ``ts`` field so the client renders arrivals and decisions
    through one row builder. The Salesforce record link is built from the joined
    event source object, or a bare instance url redirect when the event log was
    cleared. Returns the sort key paired with the item. See journal cnv-928/015
    and 030.
    """
    view = _activity_view(entry, event, field_mapping)
    view["kind"] = _KIND_DECISION
    view["ts"] = view.get("created_at")
    # The Sync or Delete event behind this decision, from the row's stored
    # action. The outcome stays on action_taken. See journal cnv-938/017 018.
    view["event"] = _event_label(entry.action)
    view["salesforce_url"] = _salesforce_record_url(
        instance_url,
        event.source_object if event is not None else "",
        entry.external_id,
    )
    ts = entry.created_at
    return (ts or _EPOCH, _KIND_RANK[_KIND_DECISION], entry.pk), view


def _salesforce_record_url(
    instance_url: str, source_object: str, external_id: str
) -> str:
    """Build the Salesforce Lightning record URL for a contact, or an empty string.

    The instance url is what Salesforce hands us on connect, the source object is
    Contact or Lead, the external id is the Salesforce record id. With no instance
    url or no external id there is nothing to link, so the row renders a dash
    rather than a dead link. See journal cnv-928/014.
    """
    return build_salesforce_record_url(
        instance_url, external_id, source_object or "Contact"
    )


def _last_applied_by_external_id(
    external_ids: set[str],
) -> dict[str, dict[str, Any]]:
    """Map each contact to its most recent applied decision.

    The Last synced clock is the time of the most recent decision that wrote
    demographics to the chart, created, modify_applied, or promoted_to_create,
    not the arrival time of the newest event. Ordered oldest first so the most
    recent applied decision wins on overwrite, the same idiom as the skip actor
    map. Also carries the acting staff name for the Synced Details modal. See
    journal cnv-928/014.
    """
    applied: dict[str, dict[str, Any]] = {}
    if not external_ids:
        return applied
    for entry in (
        ResolutionAuditEntry.objects.filter(
            action_taken__in=_DEMOGRAPHIC_APPLY_ACTIONS,
            external_id__in=external_ids,
        )
        .order_by("created_at", "dbid")
        .values("external_id", "staff_name", "created_at")
    ):
        ext = entry.get("external_id")
        if not ext:
            continue
        created_at = entry.get("created_at")
        applied[str(ext)] = {
            "staff_name": str(entry.get("staff_name") or ""),
            "created_at": created_at.isoformat() if created_at else None,
        }
    return applied


def _synced_view(
    external_id: str,
    patient_id: str,
    newest_event: IncomingPatientRecord | None,
    last_applied: dict[str, Any] | None,
    field_mapping: dict[str, dict[str, str]],
    instance_url: str,
    canvas: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Serialize one Synced registry row, keyed by the Salesforce contact.

    One row per linked contact. The demographic columns come from the linked
    Canvas patient, the source of truth for who the person is, so a row keeps its
    data even after the captured event log is cleared. The newest event is a
    fallback for any field the chart left empty, and still the source of the
    Salesforce record link and source object. Last synced and the acting staff
    come from the most recent applied decision. See journal cnv-928/014, 015,
    and 068.
    """
    canvas = canvas or {}
    event_first = event_last = event_phone = event_dob = event_sex = ""
    source_object = ""
    if newest_event is not None:
        mapped = _safe_map_record(newest_event.raw_payload, field_mapping).canvas_fields
        event_first = str(mapped.get("first_name") or newest_event.first_name or "")
        event_last = str(mapped.get("last_name") or newest_event.last_name or "")
        event_phone = str(mapped.get("phone") or newest_event.phone or "")
        event_dob = str(mapped.get("date_of_birth") or "")
        event_sex = str(mapped.get("sex_at_birth") or "")
        source_object = newest_event.source_object or ""
    first_name = str(canvas.get("first_name") or event_first)
    last_name = str(canvas.get("last_name") or event_last)
    phone = str(canvas.get("phone") or event_phone)
    date_of_birth = str(canvas.get("date_of_birth") or event_dob)
    sex_at_birth = str(canvas.get("sex_at_birth") or event_sex)
    last_synced_at: str | None = None
    last_acted_by = ""
    if last_applied is not None:
        last_synced_at = last_applied.get("created_at")
        last_acted_by = str(last_applied.get("staff_name") or "")
    return {
        "external_id": external_id,
        "patient_id": patient_id,
        "first_name": first_name,
        "last_name": last_name,
        "date_of_birth": date_of_birth,
        "sex_at_birth": sex_at_birth,
        "phone": phone,
        "source_object": source_object,
        "salesforce_url": _salesforce_record_url(
            instance_url, source_object, external_id
        ),
        "last_synced_at": last_synced_at,
        "last_acted_by": last_acted_by,
    }


def _trail_for_external_id(
    external_id: str, field_mapping: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    """Build the merged event and decision trail for one Salesforce record.

    Every captured event and every decision for the record, merged into one list
    ordered newest first, so the Details modal reads as a single timeline of what
    arrived from Salesforce and what was done with it. A received item carries the
    demographics the event arrived with, a decision item carries who acted and
    what they did. See journal cnv-909/104.
    """
    trail: list[dict[str, Any]] = []
    events = IncomingPatientRecord.objects.filter(external_id=external_id).order_by(
        "received_at", "pk"
    )
    for event in events:
        mapped = _safe_map_record(event.raw_payload, field_mapping).canvas_fields
        name = f"{mapped.get('first_name') or ''} {mapped.get('last_name') or ''}"
        trail.append(
            {
                "kind": "received",
                "ts": event.received_at.isoformat() if event.received_at else None,
                "action": event.action,
                "status": event.status,
                "name": name.strip(),
                "email": str(mapped.get("email") or event.email or ""),
                "phone": str(mapped.get("phone") or event.phone or ""),
                # The event id and its raw payload let the Activity Details modal
                # show the clicked event's payload under a Raw Salesforce payload
                # accordion. See journal cnv-928/030.
                "event_id": event.pk,
                "raw_payload": event.raw_payload,
            }
        )
    decisions = ResolutionAuditEntry.objects.filter(external_id=external_id).order_by(
        "created_at", "dbid"
    )
    for decision in decisions:
        trail.append(
            {
                "kind": "decision",
                "ts": (
                    decision.created_at.isoformat() if decision.created_at else None
                ),
                "action": decision.action,
                "action_taken": decision.action_taken,
                "staff_name": decision.staff_name,
                "note": decision.note,
                "result_patient_id": decision.result_patient_id,
            }
        )
    trail.sort(key=lambda item: (item["ts"] or ""), reverse=True)
    return trail


class SalesforceAdminPage(StaffSessionAuthMixin, SimpleAPI):
    """Serve the admin console HTML to any logged in staff, then gate inside.

    The console's data and control endpoints stay locked to the admin allowlist
    on :class:`SalesforceStatusAPI`. This page only needs a valid staff session,
    so a staff member who is not on the allowlist reaches a styled explanation
    instead of the raw framework 401 JSON. There are three outcomes. When the
    secrets are missing or malformed the config cannot load, so the page reports
    that the integration is not configured rather than implying a permission
    problem. When the config loads and the staff key is on the allowlist the
    full console renders. Otherwise the staff sees a no access page that names
    their staff id so an administrator can grant access. A non admin never
    triggers the console's data fetches, so the locked endpoints are never
    reached on this path.
    """

    @api.get("/admin")
    def admin_page(self) -> list[Response | Effect]:
        staff_key = str(self.request.headers.get("canvas-logged-in-user-id") or "")

        # no-store keeps the browser from ever reusing a cached copy of this
        # page. The response carried no cache headers before, so an iframe
        # reload could serve stale HTML from the memory cache and pair it with
        # an equally stale bundle, an old broken build kept rendering after a
        # fresh install and even after the user emptied caches with the Canvas
        # tab still open. See journal cnv-941/022.
        no_store = {"Cache-Control": "no-store"}

        try:
            config = load_config(self.secrets)
        except ConfigError as exc:
            # The secrets are missing or malformed, so the allowlist can never
            # be checked. Tell the viewer the integration is not configured
            # rather than implying a permission problem.
            log.warning("Salesforce admin console not configured: %s", exc)
            html = render_not_configured_page()
            return [
                HTMLResponse(
                    content=html, status_code=HTTPStatus.OK, headers=no_store
                ).apply()
            ]

        if staff_key in config.admin_staff_ids:
            html = render_admin_page(
                plugin_name="salesforce_to_canvas_integration",
                secret_field_mapping_available=secret_field_mapping_set(self.secrets),
            )
        else:
            log.info(
                "Salesforce admin console access denied for staff %s",
                staff_key or "<none>",
            )
            html = render_no_access_page(staff_id=staff_key)
        return [
            HTMLResponse(
                content=html, status_code=HTTPStatus.OK, headers=no_store
            ).apply()
        ]


class SalesforceStatusAPI(StaffSessionAuthMixin, SimpleAPI):
    """Admin-only status + control endpoints for the Salesforce plugin."""

    def authenticate(self, credentials: SessionCredentials) -> bool:
        if not super().authenticate(credentials):
            return False
        staff_id = str(credentials.logged_in_user.get("id") or "")
        try:
            config = load_config(self.secrets)
        except ConfigError as exc:
            log.warning("Status endpoint denied: %s", exc)
            return False
        return staff_id in config.admin_staff_ids

    @api.get("/status")
    def status(self) -> list[Response | Effect]:
        tokens = TokenStore(get_cache()).load()

        # The map the Records buckets read follows the active field mapping
        # profile, the same resolver every other read path shares, so a Custom or
        # Secret profile shows through here too. The field mapping table itself
        # moved to its own /field-mapping surface. See journal cnv-941/049.
        field_mapping = _load_field_mapping(self.secrets)

        # The table is append only, so every webhook is its own immutable event
        # row. ``_bucket_records`` splits the live events into the two actionable
        # buckets the Records screen shows, needs action and skipped, one item per
        # event so a skipped create and a newer pending modify both stay visible.
        # Applied events have no action left, so they leave the Records screen and
        # land in the Activity ledger instead. See journal cnv-909/092 story four
        # and 104.
        #
        # Two-phase load to avoid a full table scan. Phase 1 finds which
        # external_ids have actionable rows (small in steady state). Phase 2
        # loads full history only for those contacts so _compute_event_gap can
        # still find the anchor event across all statuses.
        _actionable = list(
            IncomingPatientRecord.objects.filter(
                status__in=[_STATUS_NEW, _STATUS_DISMISSED]
            ).order_by("-received_at")
        )
        _actionable_external_ids = {row.external_id for row in _actionable}
        if _actionable_external_ids:
            all_events = list(
                IncomingPatientRecord.objects.filter(
                    external_id__in=_actionable_external_ids
                ).order_by("-received_at")
            )
        else:
            all_events = _actionable
        canvas_changing_event_ids = _canvas_changing_event_ids()
        skip_actor_by_event_id = _skip_actor_by_event_id()
        skip_decision_by_event_id = _skip_decision_by_event_id()
        # Live token wins, the SF_INSTANCE_URL secret is the disconnected
        # fallback, the same derivation the activity and synced endpoints use.
        # Feeds the Salesforce record link each row carries for its expanded
        # detail links bar. See journal cnv-941/012.
        instance_url = (tokens.instance_url if tokens else "") or (
            self.secrets.get("SF_INSTANCE_URL") or ""
        ).strip().rstrip("/")
        pending, skipped = _bucket_records(
            all_events,
            field_mapping,
            canvas_changing_event_ids,
            skip_actor_by_event_id,
            skip_decision_by_event_id,
            instance_url,
        )

        body: dict[str, Any] = {
            "connection": {
                "connected": tokens is not None,
                "instance_url": tokens.instance_url if tokens else None,
                "sf_username": tokens.sf_username if tokens else None,
                "expires_at": tokens.expires_at if tokens else None,
            },
            "pending": pending,
            "skipped": skipped,
            "config_error": None,
        }
        return [JSONResponse(content=body, status_code=HTTPStatus.OK).apply()]

    @api.get("/activity")
    def activity(self) -> list[Response | Effect]:
        """Return one page of the full Activity feed newest first for the tab.

        The feed merges two append only logs into one chronological stream, every
        inbound Salesforce event when it arrived and every operator decision on
        it, so the ledger reads as the whole story of what arrived, when, what was
        done, by whom, and why. An arrival fills the Received column and carries an
        arrived marker, a decision joins its event for the Received and Applied
        columns. Ordered by timestamp newest first, with a kind then id tiebreaker
        so the two logs interleave under one strict total order. See journal
        cnv-928/014 and 015.

        The Load more button sends the last row's cursor, its timestamp, kind, and
        id, back to fetch the next page. The cursor is keyset across both tables.
        Each table is over fetched by one past the page limit and the merge is
        sliced to the limit, the standard merge bound, so a new row arriving at the
        top between two reads never repeats or skips a row at the boundary. See
        journal cnv-928/005 and 015.
        """
        field_mapping = _load_field_mapping(self.secrets)
        tokens = TokenStore(get_cache()).load()
        # Live token wins, the SF_INSTANCE_URL secret is the disconnected fallback,
        # the same derivation the Synced endpoint uses for its record link.
        instance_url = (tokens.instance_url if tokens else "") or (
            self.secrets.get("SF_INSTANCE_URL") or ""
        ).strip().rstrip("/")
        cursor = self._activity_cursor()
        limit = _ACTIVITY_LIMIT

        decisions_query = ResolutionAuditEntry.objects.order_by("-created_at", "-dbid")
        events_query = IncomingPatientRecord.objects.order_by("-received_at", "-pk")
        if cursor is not None:
            cursor_at, _cursor_kind, _cursor_id = cursor
            decisions_query = decisions_query.filter(created_at__lte=cursor_at)
            events_query = events_query.filter(received_at__lte=cursor_at)
        decisions = list(decisions_query[: limit + 1])
        events = list(events_query[: limit + 1])

        decision_event_ids = {
            row.event_id for row in decisions if row.event_id is not None
        }
        joined_events = {
            event.pk: event
            for event in IncomingPatientRecord.objects.filter(
                pk__in=decision_event_ids
            )
        }

        keyed: list[tuple[tuple[datetime, int, int], dict[str, Any]]] = [
            _decision_feed_item(
                row, joined_events.get(row.event_id), field_mapping, instance_url
            )
            for row in decisions
        ]
        keyed += [
            _arrival_feed_item(event, field_mapping, instance_url) for event in events
        ]

        if cursor is not None:
            cursor_at, cursor_kind, cursor_id = cursor
            cursor_key = (cursor_at, _KIND_RANK[cursor_kind], cursor_id)
            keyed = [pair for pair in keyed if pair[0] < cursor_key]
        keyed.sort(key=lambda pair: pair[0], reverse=True)
        has_more = len(keyed) > limit
        entries = [item for _key, item in keyed[:limit]]

        # Resolve the linked Canvas patient for the page's contacts in one query,
        # the same salesforce identifier link the Synced registry reads. The row
        # shows a patient chart link only when a patient exists, so a skip or an
        # arrival with no patient renders a dash. See journal cnv-928/030.
        page_external_ids = {e["external_id"] for e in entries if e.get("external_id")}
        patient_by_external: dict[str, str] = {}
        if page_external_ids:
            for value, pid in Patient.objects.filter(
                external_identifiers__system=SALESFORCE_IDENTIFIER_SYSTEM,
                external_identifiers__value__in=page_external_ids,
            ).values_list("external_identifiers__value", "id"):
                if value is not None and pid is not None:
                    patient_by_external[str(value)] = str(pid)
        for item in entries:
            item["patient_id"] = patient_by_external.get(
                str(item.get("external_id") or ""), ""
            )

        next_cursor: dict[str, Any] | None = None
        if has_more and entries:
            last = entries[-1]
            next_cursor = {
                "ts": last["ts"],
                "kind": last["kind"],
                "id": last["id"],
            }
        body: dict[str, Any] = {
            "entries": entries,
            "limit": limit,
            "has_more": has_more,
            "next_cursor": next_cursor,
        }
        return [JSONResponse(content=body, status_code=HTTPStatus.OK).apply()]

    @api.get("/synced")
    def synced(self) -> list[Response | Effect]:
        """Return one row per Salesforce contact linked to a Canvas patient.

        The contact keyed registry. The linked set is the Salesforce external
        identifier on a Canvas patient, the same link :func:`find_linked_patient_id`
        reads, so a contact appears once it has a patient and drops off on an
        unlink. Each row carries the latest demographics we hold from the newest
        event, a Salesforce record link, the Canvas patient id the client builds
        the chart link from, and a Last synced time, the most recent applied
        decision for the contact. Sorted by Last synced newest first, contacts with
        no applied decision sort last. See journal cnv-928/014 and 015.
        """
        field_mapping = _load_field_mapping(self.secrets)
        tokens = TokenStore(get_cache()).load()
        # Live token wins, the SF_INSTANCE_URL secret is the disconnected fallback.
        instance_url = (tokens.instance_url if tokens else "") or (
            self.secrets.get("SF_INSTANCE_URL") or ""
        ).strip().rstrip("/")

        patient_by_external: dict[str, str] = {}
        for value, patient_id in Patient.objects.filter(
            external_identifiers__system=SALESFORCE_IDENTIFIER_SYSTEM
        ).values_list("external_identifiers__value", "id"):
            if value is None or patient_id is None:
                continue
            patient_by_external[str(value)] = str(patient_id)

        external_ids = set(patient_by_external)
        # The demographics render from the linked Canvas patient, so fetch the
        # patients once with their contact points and addresses prefetched, keyed
        # by id, and snapshot each. See journal cnv-928/026.
        canvas_by_patient: dict[str, dict[str, str]] = {}
        patient_ids = set(patient_by_external.values())
        if patient_ids:
            for patient in Patient.objects.filter(id__in=patient_ids).prefetch_related(
                "telecom", "addresses"
            ):
                canvas_by_patient[str(patient.id)] = _patient_demographics(patient)
        newest_by_external: dict[str, IncomingPatientRecord] = {}
        if external_ids:
            # Ascending so the last write per external id is the newest event.
            for event in IncomingPatientRecord.objects.filter(
                external_id__in=external_ids
            ).order_by("received_at", "pk"):
                newest_by_external[event.external_id] = event
        last_applied = _last_applied_by_external_id(external_ids)

        rows = [
            _synced_view(
                external_id,
                patient_id,
                newest_by_external.get(external_id),
                last_applied.get(external_id),
                field_mapping,
                instance_url,
                canvas_by_patient.get(patient_id),
            )
            for external_id, patient_id in patient_by_external.items()
        ]
        # Newest applied first, contacts with no applied decision last. A row with
        # a last synced time sorts ahead of one without, and ISO strings compare
        # chronologically so a plain string sort is correct.
        rows.sort(
            key=lambda row: (row["last_synced_at"] is not None, row["last_synced_at"] or ""),
            reverse=True,
        )
        body: dict[str, Any] = {"synced": rows}
        return [JSONResponse(content=body, status_code=HTTPStatus.OK).apply()]

    @api.get("/records/<external_id>/trail")
    def record_trail(self) -> list[Response | Effect]:
        """Return the full event and decision trail for one Salesforce record.

        Feeds both Details modals. Merges every captured event with every
        decision for the record into one timeline ordered newest first, so the
        operator sees what arrived from Salesforce and what was done with it in
        one place. Also carries a Canvas snapshot, the linked patient as it
        stands now, and a Salesforce snapshot, the latest captured event, so the
        Synced Details modal can show a Canvas versus Salesforce demographics
        comparison. See journal cnv-909/104 and cnv-928/026.
        """
        external_id = str(self.request.path_params.get("external_id") or "").strip()
        if not external_id:
            return _json_error("external_id is required", HTTPStatus.BAD_REQUEST)
        field_mapping = _load_field_mapping(self.secrets)
        trail = _trail_for_external_id(external_id, field_mapping)
        body: dict[str, Any] = {
            "external_id": external_id,
            "trail": trail,
            "canvas": _canvas_demographics_by_id(find_linked_patient_id(external_id)),
            "salesforce": _latest_salesforce_demographics(external_id, field_mapping),
        }
        return [JSONResponse(content=body, status_code=HTTPStatus.OK).apply()]

    @api.get("/canvas-plugin-ui.css")
    def plugin_ui_css(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/canvas-plugin-ui.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
                headers={"Cache-Control": "no-cache"},
            ).apply()
        ]

    @api.get("/canvas-plugin-ui.js")
    def plugin_ui_js(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/canvas-plugin-ui.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
                headers={"Cache-Control": "no-cache"},
            ).apply()
        ]

    @api.post("/disconnect")
    def disconnect(self) -> list[Response | Effect]:
        TokenStore(get_cache()).clear()
        return [JSONResponse(content={"status": "disconnected"}, status_code=HTTPStatus.OK).apply()]

    @api.get("/settings")
    def get_settings(self) -> list[Response | Effect]:
        """Return the persisted sync automation settings for the Settings form.

        Reads the singleton through :func:`load_sync_settings`, so a missing or
        partial row always yields the full code defaults rather than an empty
        object. Admin gated by the class :meth:`authenticate`, the same gate the
        existing admin actions inherit. The payload also carries the option
        catalog the form renders from, the delete actions and the required field
        choices, so the route and the form share one vocabulary. See journal
        cnv-938/038.
        """
        return [
            JSONResponse(
                content=_settings_payload(load_sync_settings()),
                status_code=HTTPStatus.OK,
            ).apply()
        ]

    @api.put("/settings")
    def put_settings(self) -> list[Response | Effect]:
        """Validate and persist the sync automation settings from the form.

        Rejects a malformed shape and an empty or unknown required set with a
        clear 400 so the operator sees why the save was refused. On success
        upserts the
        singleton through :func:`save_sync_settings` and echoes the stored
        overlay, which is exactly what the next read returns. Admin gated by the
        class :meth:`authenticate`. See journal cnv-938/038.
        """
        body = _parse_json_object(self.request)
        if body is None:
            return _json_error(
                "Request body must be a JSON object", HTTPStatus.BAD_REQUEST
            )
        data, error = _validate_settings_payload(body)
        if error is not None:
            return _json_error(error, HTTPStatus.BAD_REQUEST)
        assert data is not None
        settings = save_sync_settings(data, now=datetime.now(timezone.utc))
        return [
            JSONResponse(
                content=_settings_payload(settings),
                status_code=HTTPStatus.OK,
            ).apply()
        ]

    @api.get("/field-mapping")
    def get_field_mapping(self) -> list[Response | Effect]:
        """Return the active field mapping profile and all three profiles.

        Feeds the Settings field mapping editor. Default and Secret are read only
        mirrors of their source, so they can never drift, Secret is null when no
        secret is set. Custom is the one editable profile, seeded from the
        defaults when never saved. Admin gated by the class :meth:`authenticate`.
        See journal cnv-941/049.
        """
        return [
            JSONResponse(
                content=_field_mapping_payload(self.secrets),
                status_code=HTTPStatus.OK,
            ).apply()
        ]

    @api.put("/field-mapping")
    def put_field_mapping(self) -> list[Response | Effect]:
        """Persist the active profile and, when sent, the Custom rows.

        The body carries the chosen ``active`` profile and an optional ``custom``
        list of rows. When ``custom`` is omitted the stored rows are kept, the
        case where the operator only switches the active profile. A bad shape, an
        unknown Canvas target, or selecting Secret with no secret set each return
        a clear 400. On success echoes exactly what the next GET returns. Admin
        gated by the class :meth:`authenticate`. See journal cnv-941/049 and 050.
        """
        body = _parse_json_object(self.request)
        if body is None:
            return _json_error(
                "Request body must be a JSON object", HTTPStatus.BAD_REQUEST
            )
        result, error = _validate_field_mapping_payload(body, self.secrets)
        if error is not None:
            return _json_error(error, HTTPStatus.BAD_REQUEST)
        assert result is not None
        profile, custom_rows = result
        if custom_rows is None:
            # No custom key sent, preserve the stored rows so switching the active
            # pointer never wipes an edited Custom map.
            state = load_field_mapping_state(self.secrets)
            custom_rows = [
                {"salesforce_field": sf, "canvas_target": target}
                for sf, target in state.custom
            ]
        save_field_mapping(
            profile=profile,
            custom_mapping=custom_rows,
            now=datetime.now(timezone.utc),
        )
        return [
            JSONResponse(
                content=_field_mapping_payload(self.secrets),
                status_code=HTTPStatus.OK,
            ).apply()
        ]

    @api.get("/records/duplicate-check")
    def duplicate_check(self) -> list[Response | Effect]:
        """Surface existing Canvas Patients that share last name and birth date.

        The audit modal posts here while the reviewer types to drive the Quick
        Add style duplicate warning. The match shape mirrors the home app
        ``DuplicatePatientWarning`` lookup, case insensitive last name plus an
        exact birth date. Results are capped so a wide collision can never
        blow the JSON payload.
        """
        params = self.request.query_params
        last_name = str(params.get("last_name") or "").strip()
        birth_raw = str(params.get("birth_date") or "").strip()
        if not last_name:
            return _json_error("last_name is required", HTTPStatus.BAD_REQUEST)
        if not birth_raw:
            return _json_error("birth_date is required", HTTPStatus.BAD_REQUEST)
        try:
            birth_date = datetime.strptime(birth_raw, "%Y-%m-%d").date()
        except ValueError:
            return _json_error(
                "birth_date must be YYYY-MM-DD", HTTPStatus.BAD_REQUEST
            )

        rows = find_duplicate_patients(last_name=last_name, birth_date=birth_date)
        matches: list[dict[str, str]] = []
        for row in rows:
            matches.append(
                {
                    "id": str(row.get("id") or ""),
                    "first_name": str(row.get("first_name") or ""),
                    "last_name": str(row.get("last_name") or ""),
                    "birth_date": _format_date(row.get("birth_date")),
                }
            )
        return [
            JSONResponse(
                content={"matches": matches},
                status_code=HTTPStatus.OK,
            ).apply()
        ]

    @api.get("/records/<external_id>/linked-patient")
    def linked_patient(self) -> list[Response | Effect]:
        """Return the Canvas patient id linked to a Salesforce record, if any.

        The Add and open flow lands a patient through an asynchronous
        ``Patient.create()`` effect, so the new patient id is not known when the
        accept response returns. The client polls this route until the
        Salesforce external identifier resolves to a patient, then opens the
        chart. Returns an empty string while the effect has not landed yet.
        """
        external_id = str(self.request.path_params.get("external_id") or "").strip()
        patient_id = find_linked_patient_id(external_id)
        return [
            JSONResponse(
                content={"patient_id": patient_id or ""},
                status_code=HTTPStatus.OK,
            ).apply()
        ]

    @api.get("/records/<external_id>/canvas-current")
    def canvas_current(self) -> list[Response | Effect]:
        """Return the linked Canvas patient demographics for a record, if any.

        The Records Details modal and the Review and edit form open this for a
        linked modify so they can show the current chart against the incoming
        values, the now versus will be comparison at the decision point. Reads
        the live patient, so it reflects the chart as it stands, not a stored
        snapshot. Returns an empty snapshot when the record links to no patient,
        which the client reads as no comparison to draw. See journal cnv-928/037.
        """
        external_id = str(self.request.path_params.get("external_id") or "").strip()
        patient_id = find_linked_patient_id(external_id)
        return [
            JSONResponse(
                content={
                    "patient_id": patient_id or "",
                    "canvas": _canvas_demographics_by_id(patient_id),
                },
                status_code=HTTPStatus.OK,
            ).apply()
        ]

    @api.post("/records/<external_id>/accept")
    def accept_record(self) -> list[Response | Effect]:
        """Convert a pending Salesforce capture into a Canvas Patient.

        The reviewer's edited form fields drive the demographics. Metadata and
        telecom not present on the form ride through from the captured row.

        Refused when a Canvas patient already exists for the record. A linked
        id can never spawn a second patient, the pending rows are modifies of
        the linked patient and must apply as updates. This makes the create
        path unreachable for a linked id at the API layer, not only hidden in
        the table. See journal cnv-938/016.
        """
        external_id = str(self.request.path_params.get("external_id") or "").strip()
        if find_linked_patient_id(external_id) is not None:
            return _json_error(
                "A Canvas patient already exists for this record. "
                "Apply it as an update instead.",
                HTTPStatus.CONFLICT,
            )
        row = self._target_row(external_id, _ACTION_CREATE)
        if row is None:
            return _json_error("Record not found", HTTPStatus.NOT_FOUND)
        if row.status not in _ACTIONABLE_STATUSES:
            return _json_error(
                f"Record is already {row.status}", HTTPStatus.CONFLICT
            )
        # An older create cannot spawn the patient once a newer change is
        # waiting, the newest row is the one to act on. See cnv-938/017 018.
        superseded = self._superseded_conflict(row)
        if superseded is not None:
            return superseded

        body = _parse_json_object(self.request)
        if body is None:
            return _json_error("Request body must be a JSON object", HTTPStatus.BAD_REQUEST)

        original = _record_view(row, _load_field_mapping(self.secrets))
        mapped = build_mapped_patient_from_form(
            form=body,
            metadata=original["metadata"],
            telecom=original["telecom"],
        )
        if not mapped.has_required():
            return _json_error(
                "Last name is required to create a Canvas patient",
                HTTPStatus.BAD_REQUEST,
            )

        effect = build_create_patient_effect(mapped=mapped, sf_record_id=external_id)

        actioned_by_id = self._resolve_and_log(
            row,
            status=_STATUS_ACCEPTED,
            action_taken="created",
            extra_fields={
                "first_name": str(mapped.canvas_fields.get("first_name") or ""),
                "last_name": str(mapped.canvas_fields.get("last_name") or ""),
                "email": str(mapped.canvas_fields.get("email") or ""),
                "phone": str(mapped.canvas_fields.get("phone") or ""),
            },
        )

        log.info(
            "Salesforce audit accepted record=%s staff_dbid=%s",
            external_id,
            actioned_by_id,
        )
        return [
            JSONResponse(
                content={"status": _STATUS_ACCEPTED, "external_id": external_id},
                status_code=HTTPStatus.OK,
            ).apply(),
            effect,
        ]

    @api.get("/records/<external_id>/promote-prefill")
    def promote_prefill(self) -> list[Response | Effect]:
        """Return the gap filled create form values for promoting a modify.

        Story five. When a modify arrives for a record with no Canvas patient,
        the operator can promote it into a create. The form is seeded from this
        payload, the incoming modify winning every field it populates and the
        freshest prior event filling only the fields the modify left blank, so a
        field the modify changed is never clobbered. ``create_to_close`` carries
        the context for the warning banner when a create for the same record was
        skipped or is still open, because promoting will create the patient and
        close that create. See journal cnv-909/088 and 092 story five.
        """
        external_id = str(self.request.path_params.get("external_id") or "").strip()
        row = self._target_row(external_id, _ACTION_MODIFY)
        if row is None:
            return _json_error("Record not found", HTTPStatus.NOT_FOUND)

        prefill = self._promote_prefill_for_row(row)
        body: dict[str, Any] = {
            "mapped": prefill.mapped.canvas_fields,
            "telecom": prefill.mapped.telecom,
            "metadata": prefill.mapped.metadata,
            "gap_filled": list(prefill.gap_filled),
            "changed": list(prefill.changed),
            "create_to_close": self._open_create_summary(external_id),
        }
        return [JSONResponse(content=body, status_code=HTTPStatus.OK).apply()]

    @api.post("/records/<external_id>/promote")
    def promote_record(self) -> list[Response | Effect]:
        """Promote an unlinked modify into a Canvas Patient create.

        The reviewer's edited form fields drive the demographics, with metadata
        and telecom riding through from the gap filled prefill so values not on
        the form still land. The Salesforce external id is preserved on the new
        patient exactly as the create accept route does. Any still open create
        for the same record is closed in the same step so a later accept cannot
        spawn a duplicate patient, and that closure is its own decision entry so
        the history reflects it. Refused when a Canvas patient already exists for
        the record, that is the Apply update path, not promote. See journal
        cnv-909/088 and 092 story five.
        """
        external_id = str(self.request.path_params.get("external_id") or "").strip()
        row = self._target_row(external_id, _ACTION_MODIFY)
        guard = self._guard_actionable_row(row)
        if guard is not None:
            return guard
        assert row is not None

        if find_linked_patient_id(external_id) is not None:
            return _json_error(
                "A Canvas patient already exists for this record. "
                "Use Apply update instead.",
                HTTPStatus.CONFLICT,
            )

        body = _parse_json_object(self.request)
        if body is None:
            return _json_error(
                "Request body must be a JSON object", HTTPStatus.BAD_REQUEST
            )

        prefill = self._promote_prefill_for_row(row)
        mapped = build_mapped_patient_from_form(
            form=body,
            metadata=prefill.mapped.metadata,
            telecom=prefill.mapped.telecom,
        )
        if not mapped.has_required():
            return _json_error(
                "Last name is required to create a Canvas patient",
                HTTPStatus.BAD_REQUEST,
            )

        effect = build_create_patient_effect(mapped=mapped, sf_record_id=external_id)

        actioned_by_id = self._resolve_and_log(
            row,
            status=_STATUS_ACCEPTED,
            action_taken="promoted_to_create",
            extra_fields={
                "first_name": str(mapped.canvas_fields.get("first_name") or ""),
                "last_name": str(mapped.canvas_fields.get("last_name") or ""),
                "email": str(mapped.canvas_fields.get("email") or ""),
                "phone": str(mapped.canvas_fields.get("phone") or ""),
            },
        )
        closed = self._supersede_open_creates(external_id)

        log.info(
            "Salesforce audit promoted modify record=%s closed_creates=%s staff_dbid=%s",
            external_id,
            closed,
            actioned_by_id,
        )
        return [
            JSONResponse(
                content={"status": _STATUS_ACCEPTED, "external_id": external_id},
                status_code=HTTPStatus.OK,
            ).apply(),
            effect,
        ]

    @api.post("/records/<external_id>/skip")
    def skip_record(self) -> list[Response | Effect]:
        """Mark the newest pending audit row as skipped without changing Canvas.

        Dispatches on whichever row is on top for the external id, create or
        modify, so the table's newest-per-record bucketing matches the skip
        target the operator clicked on.
        """
        external_id = str(self.request.path_params.get("external_id") or "").strip()
        row = self._target_row(external_id, None)
        if row is None:
            return _json_error("Record not found", HTTPStatus.NOT_FOUND)
        if row.status != _STATUS_NEW:
            return _json_error(
                f"Record is already {row.status}", HTTPStatus.CONFLICT
            )

        # The skip reason is optional. A missing or malformed body degrades to an
        # empty note, so the existing no body callers and tests keep passing.
        body = _parse_json_object(self.request)
        note = str((body or {}).get("note") or "").strip()

        actioned_by_id = self._resolve_and_log(
            row,
            status=_STATUS_DISMISSED,
            action_taken="skipped",
            note=note,
        )
        log.info(
            "Salesforce audit skipped record=%s action=%s staff_dbid=%s",
            external_id,
            row.action,
            actioned_by_id,
        )
        return [
            JSONResponse(
                content={"status": "skipped", "external_id": external_id},
                status_code=HTTPStatus.OK,
            ).apply()
        ]

    @api.post("/records/<external_id>/reopen")
    def reopen_record(self) -> list[Response | Effect]:
        """Return a skipped row to needs action without changing Canvas.

        Story two of the audit redesign makes skip reversible. A dismissed row
        flips back to ``new`` so it can be acted on again, and the reopen itself
        is logged as its own decision entry, so reversing a skip is part of the
        permanent history rather than an erasure. The row resolution stamp is
        cleared because the row is pending again, but the log still records who
        reopened it and when. Only a dismissed row can be reopened. See journal
        cnv-909/090.
        """
        external_id = str(self.request.path_params.get("external_id") or "").strip()
        row = self._target_row(external_id, None)
        if row is None:
            return _json_error("Record not found", HTTPStatus.NOT_FOUND)
        if row.status != _STATUS_DISMISSED:
            return _json_error(
                f"Record is {row.status}, only a skipped record can be reopened",
                HTTPStatus.CONFLICT,
            )

        staff_key, actioned_by_id, staff_name = self._resolve_acting_staff()
        IncomingPatientRecord.objects.filter(pk=row.pk).update(
            status=_STATUS_NEW,
            actioned_at=None,
            actioned_by_id=None,
        )
        self._append_decision(
            row,
            action_taken="reopened",
            staff_key=staff_key,
            staff_name=staff_name,
        )
        log.info(
            "Salesforce audit reopened record=%s action=%s staff_dbid=%s",
            external_id,
            row.action,
            actioned_by_id,
        )
        return [
            JSONResponse(
                content={"status": "reopened", "external_id": external_id},
                status_code=HTTPStatus.OK,
            ).apply()
        ]

    @api.post("/records/<external_id>/apply-update")
    def apply_update(self) -> list[Response | Effect]:
        """Run a delta apply update against the linked Canvas patient.

        The captured Salesforce payload drives the demographics. No form
        editing happens here, the operator clicked Apply update on the audit
        row and expects the inbound payload to flow straight through.
        """
        external_id = str(self.request.path_params.get("external_id") or "").strip()
        row = self._target_row(external_id, _ACTION_MODIFY)
        guard = self._guard_actionable_row(row)
        if guard is not None:
            return guard
        assert row is not None  # _guard_actionable_row enforces non None on success path

        try:
            mapped = map_record(
                row.raw_payload or {}, _load_field_mapping(self.secrets)
            )
        except MappingError as exc:
            return _json_error(str(exc), HTTPStatus.BAD_REQUEST)

        return self._apply_modify_update(row, mapped)

    @api.post("/records/<external_id>/review-and-update")
    def review_and_update(self) -> list[Response | Effect]:
        """Run a delta apply update using the reviewer's edited form fields.

        The form mirrors the create audit modal but in modify mode. Empty form
        fields stay out of the update so the operator can clear an edit
        without forcing it onto Canvas.
        """
        external_id = str(self.request.path_params.get("external_id") or "").strip()
        row = self._target_row(external_id, _ACTION_MODIFY)
        guard = self._guard_actionable_row(row)
        if guard is not None:
            return guard
        assert row is not None

        body = _parse_json_object(self.request)
        if body is None:
            return _json_error(
                "Request body must be a JSON object", HTTPStatus.BAD_REQUEST
            )

        original = _record_view(row, _load_field_mapping(self.secrets))
        mapped = build_mapped_patient_from_form(
            form=body,
            metadata=original["metadata"],
            telecom=original["telecom"],
        )
        return self._apply_modify_update(row, mapped)

    @api.post("/records/<external_id>/tag-deleted")
    def tag_deleted(self) -> list[Response | Effect]:
        """Write the salesforce_deleted_at metadata tag on the linked patient.

        Resolves the latest delete row for the external id, finds the Canvas
        patient that carries the Salesforce external identifier, builds the
        tag effect, and flips the row to ``accepted``. The Canvas patient
        stays active, only the metadata key lands. See journal cnv-909/075
        Q1 for the delta apply contract and cnv-909/074 for the four delete
        resolution options shipped across steps three through five.
        """
        external_id = str(self.request.path_params.get("external_id") or "").strip()
        row = self._target_row(external_id, _ACTION_DELETE)
        guard = self._guard_actionable_row(row)
        if guard is not None:
            return guard
        assert row is not None

        canvas_patient_id = find_linked_patient_id(row.external_id)
        if canvas_patient_id is None:
            return _json_error(
                "No Canvas patient is linked to this Salesforce record. "
                "Run the matching create row first.",
                HTTPStatus.CONFLICT,
            )

        effect = build_tag_deleted_effect(
            canvas_patient_id=canvas_patient_id,
            deleted_at=row.received_at,
        )

        actioned_by_id = self._resolve_and_log(
            row,
            status=_STATUS_ACCEPTED,
            action_taken="tag_deleted",
            result_patient_id=canvas_patient_id,
        )

        log.info(
            "Salesforce audit tagged delete record=%s patient=%s staff_dbid=%s",
            row.external_id,
            canvas_patient_id,
            actioned_by_id,
        )
        return [
            JSONResponse(
                content={
                    "status": _STATUS_ACCEPTED,
                    "external_id": row.external_id,
                    "canvas_patient_id": canvas_patient_id,
                },
                status_code=HTTPStatus.OK,
            ).apply(),
            effect,
        ]

    @api.post("/records/<external_id>/mark-inactive")
    def mark_inactive(self) -> list[Response | Effect]:
        """Flip the linked Canvas patient's ``active`` flag to false via FHIR.

        The Canvas FHIR Patient endpoint only documents GET and PUT, so the
        helper read-modify-writes the patient body, see journal cnv-909/082 for
        the shape and the open question corrections to cnv-909/074. On any
        failure path the row stays at ``new`` so the operator can retry.
        """
        external_id = str(self.request.path_params.get("external_id") or "").strip()
        row = self._target_row(external_id, _ACTION_DELETE)
        guard = self._guard_actionable_row(row)
        if guard is not None:
            return guard
        assert row is not None

        canvas_patient_id = find_linked_patient_id(row.external_id)
        if canvas_patient_id is None:
            return _json_error(
                "No Canvas patient is linked to this Salesforce record. "
                "Run the matching create row first.",
                HTTPStatus.CONFLICT,
            )

        try:
            config = load_config(self.secrets)
        except ConfigError as exc:
            return _json_error(str(exc), HTTPStatus.SERVICE_UNAVAILABLE)

        if not canvas_fhir_configured(config):
            return _json_error(
                "Canvas FHIR is not configured. Set CANVAS_API_CLIENT_ID, "
                "CANVAS_API_CLIENT_SECRET, and FUMAGE_BASE_URL on the plugin.",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        try:
            client = self._build_canvas_fhir_client(config)
            client.mark_patient_inactive(canvas_patient_id)
        except CanvasFhirNotConfiguredError as exc:
            return _json_error(str(exc), HTTPStatus.SERVICE_UNAVAILABLE)
        except (CanvasFhirAuthError, CanvasFhirError) as exc:
            log.warning(
                "Salesforce audit mark inactive failed record=%s patient=%s err=%s",
                row.external_id,
                canvas_patient_id,
                exc,
            )
            return _json_error(str(exc), HTTPStatus.BAD_GATEWAY)

        actioned_by_id = self._resolve_and_log(
            row,
            status=_STATUS_ACCEPTED,
            action_taken="mark_inactive",
            result_patient_id=canvas_patient_id,
        )

        log.info(
            "Salesforce audit mark inactive record=%s patient=%s staff_dbid=%s",
            row.external_id,
            canvas_patient_id,
            actioned_by_id,
        )
        return [
            JSONResponse(
                content={
                    "status": _STATUS_ACCEPTED,
                    "external_id": row.external_id,
                    "canvas_patient_id": canvas_patient_id,
                },
                status_code=HTTPStatus.OK,
            ).apply()
        ]

    @api.post("/records/<external_id>/unlink-only")
    def unlink_only(self) -> list[Response | Effect]:
        """Drop the Salesforce external identifier from the linked patient.

        The Canvas patient stays fully active, only the integration link to
        Salesforce is broken. Reversible. See decision cnv-909/075 Q2 for the
        no-confirm direct fire shape and cnv-909/074 for the four delete
        resolution options. On any failure path the row stays at ``new`` so
        the operator can retry.
        """
        external_id = str(self.request.path_params.get("external_id") or "").strip()
        row = self._target_row(external_id, _ACTION_DELETE)
        guard = self._guard_actionable_row(row)
        if guard is not None:
            return guard
        assert row is not None

        canvas_patient_id = find_linked_patient_id(row.external_id)
        if canvas_patient_id is None:
            return _json_error(
                "No Canvas patient is linked to this Salesforce record. "
                "Run the matching create row first.",
                HTTPStatus.CONFLICT,
            )

        try:
            config = load_config(self.secrets)
        except ConfigError as exc:
            return _json_error(str(exc), HTTPStatus.SERVICE_UNAVAILABLE)

        if not canvas_fhir_configured(config):
            return _json_error(
                "Canvas FHIR is not configured. Set CANVAS_API_CLIENT_ID, "
                "CANVAS_API_CLIENT_SECRET, and FUMAGE_BASE_URL on the plugin.",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        try:
            client = self._build_canvas_fhir_client(config)
            client.remove_salesforce_identifier(canvas_patient_id, row.external_id)
        except CanvasFhirNotConfiguredError as exc:
            return _json_error(str(exc), HTTPStatus.SERVICE_UNAVAILABLE)
        except (CanvasFhirAuthError, CanvasFhirError) as exc:
            log.warning(
                "Salesforce audit unlink only failed record=%s patient=%s err=%s",
                row.external_id,
                canvas_patient_id,
                exc,
            )
            return _json_error(str(exc), HTTPStatus.BAD_GATEWAY)

        actioned_by_id = self._resolve_and_log(
            row,
            status=_STATUS_ACCEPTED,
            action_taken="unlink",
            result_patient_id=canvas_patient_id,
        )

        log.info(
            "Salesforce audit unlink only record=%s patient=%s staff_dbid=%s",
            row.external_id,
            canvas_patient_id,
            actioned_by_id,
        )
        return [
            JSONResponse(
                content={
                    "status": _STATUS_ACCEPTED,
                    "external_id": row.external_id,
                    "canvas_patient_id": canvas_patient_id,
                },
                status_code=HTTPStatus.OK,
            ).apply()
        ]

    def _build_canvas_fhir_client(self, config: PluginConfig) -> CanvasFhirClient:
        """Construct the Canvas FHIR client used by the mark inactive route.

        Pulled into a seam so tests can swap a fake client without monkey
        patching the SDK ``Http`` import.
        """
        return build_canvas_fhir_client(
            http=Http(),
            fumage_base_url=config.fumage_base_url,
            client_id=config.canvas_api_client_id,
            client_secret=config.canvas_api_client_secret,
            # Optional token host override threaded from secrets. See cnv-928/002.
            instance_url=config.canvas_instance_url,
        )

    def _guard_actionable_row(
        self, row: IncomingPatientRecord | None
    ) -> list[Response | Effect] | None:
        """Validate the row state common to the modify and delete resolutions.

        A new or a dismissed row is actionable, story two makes skip reversible
        so a skipped modify or delete can be amended and applied directly. An
        accepted row stays blocked here, and a row a newer pending change has
        superseded is refused so a stale row can never apply over fresher
        Salesforce truth. See journal cnv-909/090 and cnv-938/017 018.
        """
        if row is None:
            return _json_error("Record not found", HTTPStatus.NOT_FOUND)
        if row.status not in _ACTIONABLE_STATUSES:
            return _json_error(
                f"Record is already {row.status}", HTTPStatus.CONFLICT
            )
        return self._superseded_conflict(row)

    def _newest_pending_for_record(
        self, row: IncomingPatientRecord
    ) -> IncomingPatientRecord | None:
        """The newest pending row for this row's Salesforce id, any action.

        The Records surface collapses each contact to a single actionable row,
        the newest pending event regardless of action, because a one directional
        sync means the latest Salesforce state is the truth. Create or modify and
        delete are one lane, so the newest pending row of any action is the live
        one and every older pending row is superseded. See journal cnv-938/022.
        """
        newest: IncomingPatientRecord | None = (
            IncomingPatientRecord.objects.filter(
                external_id=row.external_id, status=_STATUS_NEW
            )
            .order_by("-received_at", "-pk")
            .first()
        )
        return newest

    def _superseded_conflict(
        self, row: IncomingPatientRecord
    ) -> list[Response | Effect] | None:
        """Refuse a resolution on a row a newer pending change has superseded.

        The newest pending row per Salesforce id carries the current Salesforce
        truth, so acting on an older one would push data Salesforce has moved
        past. Returns a 409 naming the newer change when this row is not the
        newest pending row for the contact, else None. The guard is server side
        so the collapsed single row in the table is defense in depth, not the
        only gate, an older event id posted directly is still refused. Skip and
        reopen never call this, the queue can always be cleared. See journal
        cnv-938/017 018 022.
        """
        newest = self._newest_pending_for_record(row)
        if newest is None or newest.pk == row.pk:
            return None
        when = newest.received_at.isoformat() if newest.received_at else ""
        tail = f" received {when}" if when else ""
        return _json_error(
            f"A newer change for this contact is waiting{tail}. "
            "Act on the newest row instead.",
            HTTPStatus.CONFLICT,
        )

    def _apply_modify_update(
        self, row: IncomingPatientRecord, mapped: MappedPatient
    ) -> list[Response | Effect]:
        """Resolve the linked Canvas patient and write the update effect.

        Returns 409 with a clear message when no Canvas patient carries the
        Salesforce external identifier yet. Otherwise builds the delta apply
        effect, flips the row to ``accepted``, and returns the effect alongside
        the JSON ack.
        """
        canvas_patient_id = find_linked_patient_id(row.external_id)
        if canvas_patient_id is None:
            return _json_error(
                "No Canvas patient is linked to this Salesforce record. "
                "Run the matching create row first.",
                HTTPStatus.CONFLICT,
            )

        # Snapshot the chart as it stands before the update effect lands, so the
        # Activity Details table can show what was in Canvas against what this
        # apply wrote. The effect is applied by the runtime after this response,
        # so this synchronous read still sees the pre write state. Only the modify
        # apply has a prior patient to snapshot, a create and a promote do not.
        # See journal cnv-928/037.
        canvas_before = _canvas_demographics_by_id(canvas_patient_id)

        effect = build_update_patient_effect(
            canvas_patient_id=canvas_patient_id, mapped=mapped
        )

        # Mirror the typed columns the create accept route writes so the acted
        # table renders the reviewer's edited values rather than the original
        # capture. Absent keys leave the captured columns alone, matching the
        # delta apply contract.
        extra_fields: dict[str, Any] = {}
        for column in ("first_name", "last_name", "email", "phone"):
            if column in mapped.canvas_fields:
                extra_fields[column] = str(mapped.canvas_fields[column])
        actioned_by_id = self._resolve_and_log(
            row,
            status=_STATUS_ACCEPTED,
            action_taken="modify_applied",
            extra_fields=extra_fields,
            result_patient_id=canvas_patient_id,
            canvas_before=canvas_before,
        )

        log.info(
            "Salesforce audit applied modify record=%s patient=%s staff_dbid=%s",
            row.external_id,
            canvas_patient_id,
            actioned_by_id,
        )
        return [
            JSONResponse(
                content={
                    "status": _STATUS_ACCEPTED,
                    "external_id": row.external_id,
                    "canvas_patient_id": canvas_patient_id,
                },
                status_code=HTTPStatus.OK,
            ).apply(),
            effect,
        ]

    def _resolve_and_log(
        self,
        row: IncomingPatientRecord,
        *,
        status: str,
        action_taken: str,
        extra_fields: dict[str, Any] | None = None,
        note: str = "",
        result_patient_id: str = "",
        canvas_before: dict[str, Any] | None = None,
    ) -> int | None:
        """Resolve a row and append one decision log entry in the same step.

        Every operator resolution routes through here so the
        ``IncomingPatientRecord.status`` cache and the append only
        ``ResolutionAuditEntry`` log can never drift. The status update carries
        the resolution slot plus any per path typed columns in ``extra_fields``,
        and the log entry captures who acted, when, and what. ``canvas_before``
        is the chart snapshot a modify apply took before it wrote, threaded to
        the log entry, empty for every other resolution. See journal cnv-909/089
        and cnv-928/037. Returns the acting staff dbid so callers can log it.

        Delegates the two writes to the shared :func:`write_resolution` so the
        automatic apply path in the webhook resolves a row exactly the same way,
        the only difference being the actor. See journal cnv-938/033.
        """
        staff_key, actioned_by_id, staff_name = self._resolve_acting_staff()
        write_resolution(
            row,
            status=status,
            action_taken=action_taken,
            actor=ResolutionActor(
                staff_key=staff_key,
                staff_dbid=actioned_by_id,
                staff_name=staff_name,
            ),
            now=datetime.now(timezone.utc),
            extra_fields=extra_fields,
            note=note,
            result_patient_id=result_patient_id,
            canvas_before=canvas_before,
        )
        return actioned_by_id

    def _resolve_acting_staff(self) -> tuple[str, int | None, str]:
        """Pull the acting staff from the session header.

        Returns the raw session key, the StaffProxy dbid for the row foreign
        key, and the display name for the decision log, all tolerant of a
        missing or unknown key.
        """
        staff_key = str(self.request.headers.get("canvas-logged-in-user-id") or "")
        dbid, name = _resolve_staff(staff_key or None)
        return staff_key, dbid, name

    def _append_decision(
        self,
        row: IncomingPatientRecord,
        *,
        action_taken: str,
        staff_key: str,
        staff_name: str,
        note: str = "",
        result_patient_id: str = "",
        canvas_before: dict[str, Any] | None = None,
    ) -> None:
        """Write one append only decision log entry for a row transition.

        Split out from :meth:`_resolve_and_log` so a transition that clears the
        row resolution stamp rather than setting it, such as reopen, can still
        record who acted and when. ``canvas_before`` carries the chart snapshot a
        modify apply took before it wrote, empty for every other transition. See
        journal cnv-909/090 and cnv-928/037.
        """
        append_decision(
            row,
            action_taken=action_taken,
            actor=ResolutionActor(staff_key=staff_key, staff_name=staff_name),
            note=note,
            result_patient_id=result_patient_id,
            canvas_before=canvas_before,
        )

    def _event_id_param(self) -> int | None:
        """Read the optional ``event_id`` query param as an int, else None.

        Story four lets a resolution route act on the exact event the operator
        clicked rather than the newest of its action, since the per event queue
        can now show more than one live event for a record. A missing or non
        integer value yields None so the caller falls back to the prior newest
        of action behavior. Tolerant of the mocked request used in tests, where
        the query params object is not a real mapping.
        """
        try:
            raw = self.request.query_params.get("event_id")
        except Exception:
            return None
        if raw is None:
            return None
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return None

    def _activity_cursor(self) -> tuple[datetime, str, int] | None:
        """Read the optional Load more cursor for the Activity feed.

        The Load more button sends the last loaded row's timestamp as ``before``
        in isoformat, its kind as ``before_kind``, and its id as ``before_id``.
        Returns the triple when the time and id parse, else None so the read
        serves the newest page. A missing or unknown kind defaults to decision so
        an older client that sends only the time and id still pages. Tolerant of
        the mocked request used in tests, where query params is not a real
        mapping, and of a malformed value, which falls back to the first page. See
        journal cnv-928/005 and 015.
        """
        try:
            raw_at = self.request.query_params.get("before")
            raw_kind = self.request.query_params.get("before_kind")
            raw_id = self.request.query_params.get("before_id")
        except Exception:
            return None
        if raw_at is None or raw_id is None:
            return None
        try:
            before_at = datetime.fromisoformat(str(raw_at).strip())
            before_id = int(str(raw_id).strip())
        except (TypeError, ValueError):
            return None
        kind = str(raw_kind).strip() if raw_kind is not None else _KIND_DECISION
        if kind not in _KIND_RANK:
            kind = _KIND_DECISION
        return before_at, kind, before_id

    def _target_row(
        self, external_id: str, action: str | None
    ) -> IncomingPatientRecord | None:
        """Resolve the event a resolution route should act on.

        Prefers the explicit ``event_id`` query param so the per event queue
        acts on the exact row the operator clicked. A provided event id that
        does not exist, points at another Salesforce record, or carries a
        different action than the route expects is treated as not found, so a
        stale or crafted id can never cross records or actions. With no event
        id the lookup falls back to the newest row of the given action for the
        external id, the pre per event behavior, which keeps every existing
        caller and test unchanged. See journal cnv-909/092 story four.

        The action match is on the effective action, not the stored label, so a
        create row whose Salesforce id is now linked routes through the modify
        resolutions and is refused by the create route. See journal
        cnv-938/016.
        """
        event_id = self._event_id_param()
        if event_id is not None:
            row: IncomingPatientRecord | None = (
                IncomingPatientRecord.objects.filter(pk=event_id).first()
            )
            if row is None or row.external_id != external_id:
                return None
            if action is not None and self._effective_action_for_row(row) != action:
                return None
            return row
        if action is None:
            return self._latest_row_any_action(external_id)
        return self._latest_row(external_id, action)

    def _effective_action_for_row(self, row: IncomingPatientRecord) -> str:
        """Effective action for a stored row, resolved against the live link.

        One link lookup, then the shared derivation. Used by the resolution
        routing so a linked create row is treated as the modify it now is. See
        journal cnv-938/016.
        """
        linked = find_linked_patient_id(row.external_id) is not None
        return _effective_action(row.action, linked)

    def _latest_row(
        self, external_id: str, action: str
    ) -> IncomingPatientRecord | None:
        if not external_id:
            return None
        row: IncomingPatientRecord | None = (
            IncomingPatientRecord.objects.filter(
                external_id=external_id, action=action
            )
            .order_by("-received_at")
            .first()
        )
        return row

    def _latest_row_any_action(
        self, external_id: str
    ) -> IncomingPatientRecord | None:
        """Return the newest row across actions for an external id."""
        if not external_id:
            return None
        row: IncomingPatientRecord | None = (
            IncomingPatientRecord.objects.filter(external_id=external_id)
            .order_by("-received_at")
            .first()
        )
        return row

    def _freshest_prior_event(
        self, row: IncomingPatientRecord
    ) -> IncomingPatientRecord | None:
        """Return the newest event for the same record captured before ``row``.

        Any action counts, create or modify, so the comparison is always against
        the freshest prior snapshot, per the payload contract in journal
        cnv-909/088. The primary key breaks a tie when two events share a
        timestamp, which the auto timestamp can produce in a fast test.
        """
        prior: IncomingPatientRecord | None = (
            IncomingPatientRecord.objects.filter(
                external_id=row.external_id, received_at__lt=row.received_at
            )
            .exclude(pk=row.pk)
            .order_by("-received_at", "-pk")
            .first()
        )
        return prior

    def _promote_prefill_for_row(self, row: IncomingPatientRecord) -> PromotePrefill:
        """Build the gap filled promote prefill for a modify row.

        Maps the modify payload and its freshest prior event through the
        configured field map, then merges them with the incoming modify winning
        and the prior event filling only the blanks. A malformed map for either
        side degrades to an empty mapped record rather than failing the form.
        """
        field_mapping = _load_field_mapping(self.secrets)
        incoming = _safe_map_record(row.raw_payload, field_mapping)
        prior_row = self._freshest_prior_event(row)
        prior = (
            _safe_map_record(prior_row.raw_payload, field_mapping)
            if prior_row is not None
            else None
        )
        return build_promote_prefill(incoming, prior)

    def _open_create_summary(self, external_id: str) -> dict[str, Any]:
        """Describe a still open create for the record, for the warning banner.

        A create is open when it sits in ``_ACTIONABLE_STATUSES``, either skipped
        or still awaiting review, so promoting the modify will close it. Returns
        ``{"exists": False}`` when there is none. When the create was skipped the
        summary carries who skipped it and when, pulled from the decision log so
        the banner can name the operator who made the call.
        """
        create_row = (
            IncomingPatientRecord.objects.filter(
                external_id=external_id,
                action=_ACTION_CREATE,
                status__in=_ACTIONABLE_STATUSES,
            )
            .order_by("-received_at", "-pk")
            .first()
        )
        if create_row is None:
            return {"exists": False}

        who = ""
        when: str | None = (
            create_row.actioned_at.isoformat() if create_row.actioned_at else None
        )
        if create_row.status == _STATUS_DISMISSED:
            entry = (
                ResolutionAuditEntry.objects.filter(
                    event_id=create_row.pk, action_taken="skipped"
                )
                .order_by("-created_at")
                .first()
            )
            if entry is not None:
                who = entry.staff_name
                if entry.created_at:
                    when = entry.created_at.isoformat()
        return {
            "exists": True,
            "event_id": create_row.pk,
            "status": create_row.status,
            "when": when,
            "who": who,
        }

    def _supersede_open_creates(self, external_id: str) -> int:
        """Close any still open create for the record after a promote.

        Promoting a modify creates the patient, so a create left open, skipped or
        awaiting review, would spawn a duplicate if accepted later. Each open
        create is flipped to accepted and gets a ``create_superseded`` decision
        entry, so it leaves the live queue, cannot be reopened, and the history
        records that a later promote closed it. Returns how many were closed.
        """
        creates = list(
            IncomingPatientRecord.objects.filter(
                external_id=external_id,
                action=_ACTION_CREATE,
                status__in=_ACTIONABLE_STATUSES,
            )
        )
        if not creates:
            return 0
        actioned_at = datetime.now(timezone.utc)
        staff_key, actioned_by_id, staff_name = self._resolve_acting_staff()
        for create_row in creates:
            IncomingPatientRecord.objects.filter(pk=create_row.pk).update(
                status=_STATUS_ACCEPTED,
                actioned_at=actioned_at,
                actioned_by_id=actioned_by_id,
            )
            self._append_decision(
                create_row,
                action_taken="create_superseded",
                staff_key=staff_key,
                staff_name=staff_name,
                note="Closed by promoting a later modify into the create.",
            )
        return len(creates)


def _json_error(message: str, status_code: HTTPStatus) -> list[Response | Effect]:
    """Build the JSON error response shape the audit modal expects."""
    return [
        JSONResponse(
            content={"error": message},
            status_code=status_code,
        ).apply()
    ]


def _parse_json_object(request: Any) -> dict[str, Any] | None:
    """Decode the request body as a JSON object, or return None on failure."""
    try:
        body = request.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    return body


def _mapping_to_rows(
    mapping: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    """Flatten a config shaped map into ordered Salesforce, target row dicts."""
    return [
        {"salesforce_field": sf_name, "canvas_target": spec.get("target", "")}
        for sf_name, spec in mapping.items()
    ]


def _rows_to_mapping(
    rows: tuple[tuple[str, str], ...],
) -> dict[str, dict[str, str]]:
    """Build a config shaped map from Custom rows, skipping empty Salesforce cells.

    An emptied Salesforce field is the operator's do not sync marker for that
    target, so the row is dropped from the map the sync reads while it stays in
    storage for the table to keep showing. The last write wins on the rare chance
    two rows name the same Salesforce field, the same single target per field the
    config shape has always implied.
    """
    mapping: dict[str, dict[str, str]] = {}
    for sf_field, target in rows:
        if sf_field and target:
            mapping[sf_field] = {"target": target}
    return mapping


def _secret_mapping_or_none(secrets: dict[str, str]) -> dict[str, dict[str, str]] | None:
    """Parse the Secret map, treating a malformed secret as absent."""
    try:
        return field_mapping_secret(secrets)
    except ConfigError:
        return None


def _load_field_mapping(secrets: dict[str, str]) -> dict[str, dict[str, str]]:
    """Resolve the active field mapping profile into the map the sync reads.

    The single resolver every read path shares. Reads the active profile pointer
    from custom data, then returns the Default constant, the parsed Secret with a
    Default fallback, or the Custom rows converted to the config shape with empty
    Salesforce cells skipped. Any malformed or missing source falls back to the
    Default constant so the sync always has a usable map. See journal cnv-941/049.
    """
    state = load_field_mapping_state(secrets)
    if state.profile == PROFILE_CUSTOM:
        return _rows_to_mapping(state.custom)
    if state.profile == PROFILE_SECRET:
        return _secret_mapping_or_none(secrets) or DEFAULT_FIELD_MAPPING
    return DEFAULT_FIELD_MAPPING


def _settings_payload(settings: SyncSettings) -> dict[str, Any]:
    """Serialize the settings plus the form's option catalog into one payload.

    The settings block mirrors the :class:`SyncSettings` dataclass field for
    field, with the required tuple flattened to a list for JSON. The options
    block carries the delete actions and the required field choices straight
    from the ``sync_rules`` constants, so the form renders exactly the options
    the PUT route will accept and the two can never drift. See journal
    cnv-938/038.
    """
    return {
        "settings": {
            "auto_create": settings.auto_create,
            "auto_modify": settings.auto_modify,
            "auto_delete": settings.auto_delete,
            "delete_action": settings.delete_action,
            "required_fields": list(settings.required_fields),
            "address_group_integrity": settings.address_group_integrity,
            "validity_checks": settings.validity_checks,
        },
        "options": {
            "delete_actions": list(DELETE_ACTIONS),
            "required_field_choices": list(REQUIRED_FIELD_CHOICES),
        },
    }


def _validate_settings_payload(
    body: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate a settings PUT body into a clean data blob, or name the error.

    Returns ``(data, None)`` on success or ``(None, message)`` on the first
    failure, the message operator facing so the route returns it verbatim in the
    400. The five toggles must be real bools, the delete action must be one of
    the known actions, and the required set must be a non empty list drawn from
    the field choices. Leans on the ``sync_rules`` constants so the route and the
    evaluator share one vocabulary and a misconfigured set can never reach the
    evaluator. See journal cnv-938/038.
    """
    bools: dict[str, Any] = {}
    for key in (
        "auto_create",
        "auto_modify",
        "auto_delete",
        "address_group_integrity",
        "validity_checks",
    ):
        value = body.get(key)
        if not isinstance(value, bool):
            return None, f"{_humanize_setting(key)} must be true or false"
        bools[key] = value

    delete_action = body.get("delete_action")
    if delete_action not in DELETE_ACTIONS:
        allowed = ", ".join(DELETE_ACTIONS)
        return None, f"delete_action must be one of {allowed}"

    required_raw = body.get("required_fields")
    if not isinstance(required_raw, list) or not all(
        isinstance(item, str) for item in required_raw
    ):
        return None, "required_fields must be a list of field names"
    # Preserve order while dropping blanks and duplicates, mirroring the loader.
    required = tuple(dict.fromkeys(item for item in required_raw if item.strip()))
    if not required:
        return None, "required_fields must name at least one field"
    unknown = [item for item in required if item not in REQUIRED_FIELD_CHOICES]
    if unknown:
        return None, f"unknown required field: {unknown[0]}"

    data: dict[str, Any] = dict(bools)
    data["delete_action"] = delete_action
    data["required_fields"] = list(required)
    return data, None


def _humanize_setting(name: str) -> str:
    """Render a setting or field key as spaced words for an operator message."""
    return name.replace("_", " ")


def _canvas_target_catalog(secrets: dict[str, str]) -> tuple[str, ...]:
    """The Canvas targets a profile may carry, defaults plus any the secret adds.

    Ordered, defaults first then any extra targets the secret introduces, so the
    PUT validator accepts exactly the targets the three profiles can show and no
    others. A malformed secret contributes nothing.
    """
    targets: list[str] = []
    seen: set[str] = set()
    sources: list[dict[str, dict[str, str]]] = [DEFAULT_FIELD_MAPPING]
    secret_map = _secret_mapping_or_none(secrets)
    if secret_map is not None:
        sources.append(secret_map)
    for source in sources:
        for spec in source.values():
            target = spec.get("target", "")
            if target and target not in seen:
                seen.add(target)
                targets.append(target)
    return tuple(targets)


def _custom_rows_for_payload(state: FieldMappingState) -> list[dict[str, str]]:
    """The Custom profile rows for the GET payload, seeded from defaults if empty.

    Custom starts from the built in defaults so the operator edits a real mapping
    rather than a blank table, then their saved rows take over.
    """
    if state.custom:
        return [
            {"salesforce_field": sf, "canvas_target": target}
            for sf, target in state.custom
        ]
    return _mapping_to_rows(DEFAULT_FIELD_MAPPING)


def _field_mapping_payload(secrets: dict[str, str]) -> dict[str, Any]:
    """Serialize the active pointer and all three profiles for the editor.

    Default and Secret are read only mirrors, Secret null when no secret is set.
    Custom is the editable profile, seeded from defaults when never saved. The
    Salesforce field is the only editable cell, so the editable flag rides the
    payload rather than being inferred in the page.
    """
    state = load_field_mapping_state(secrets)
    secret_map = _secret_mapping_or_none(secrets)
    return {
        "active": state.profile,
        "secret_available": secret_map is not None,
        "profiles": {
            "default": _mapping_to_rows(DEFAULT_FIELD_MAPPING),
            "secret": _mapping_to_rows(secret_map) if secret_map is not None else None,
            "custom": _custom_rows_for_payload(state),
        },
    }


def _validate_field_mapping_payload(
    body: dict[str, Any], secrets: dict[str, str]
) -> tuple[tuple[str, list[dict[str, str]] | None] | None, str | None]:
    """Validate a field mapping PUT body into ``(profile, custom_rows)`` or an error.

    ``custom_rows`` is ``None`` when the body carries no ``custom`` key, which
    means leave the stored Custom rows as they are, the case when the operator
    only switches the active profile. The profile must be one of the three, and
    Secret is rejected when no secret is set. Each custom row must name a known
    Canvas target, the Salesforce field may be empty, an empty field being the do
    not sync marker. See journal cnv-941/049 and 050.
    """
    profile = body.get("active")
    if profile not in VALID_PROFILES:
        return None, "active must be default, secret, or custom"
    if profile == PROFILE_SECRET and not secret_field_mapping_set(secrets):
        return None, "the Secret profile is not available, no field map secret is set"

    raw_custom = body.get("custom")
    if raw_custom is None:
        return (profile, None), None
    if not isinstance(raw_custom, list):
        return None, "custom must be a list of mapping rows"

    catalog = set(_canvas_target_catalog(secrets))
    rows: list[dict[str, str]] = []
    for item in raw_custom:
        if not isinstance(item, dict):
            return None, "each custom row must be an object"
        target = item.get("canvas_target")
        if not isinstance(target, str) or target not in catalog:
            return None, f"unknown Canvas target: {target!r}"
        sf_field = item.get("salesforce_field")
        if sf_field is None:
            sf_field = ""
        if not isinstance(sf_field, str):
            return None, "salesforce_field must be a string"
        rows.append(
            {"salesforce_field": sf_field.strip(), "canvas_target": target}
        )
    return (profile, rows), None


def _canvas_changing_event_ids() -> set[int]:
    """Event ids whose decision log carries a Canvas changing resolution.

    One query feeds the gap banner anchor for every pending row, see
    ``_compute_event_gap``. An event qualifies once any of its decision entries
    is a Canvas changing action, so a reopened then reapplied event still counts
    as an anchor. See journal cnv-909/092 story six.
    """
    return {
        int(event_id)
        for event_id in ResolutionAuditEntry.objects.filter(
            action_taken__in=_CANVAS_CHANGING_ACTIONS
        ).values_list("event_id", flat=True)
        if event_id is not None
    }


def _skip_actor_by_event_id() -> dict[int, str]:
    """Map each skipped event to the name of the operator who last skipped it.

    Drives the who last touched it line in the gap tooltip for skipped events.
    Ordered oldest first so the most recent skip wins when an event was skipped,
    reopened, and skipped again. See journal cnv-909/088 The Gap Banner.
    """
    actor: dict[int, str] = {}
    for entry in (
        ResolutionAuditEntry.objects.filter(action_taken="skipped")
        .order_by("created_at")
        .values("event_id", "staff_name")
    ):
        event_id = entry.get("event_id")
        if event_id is None:
            continue
        actor[int(event_id)] = str(entry.get("staff_name") or "")
    return actor


def _skip_decision_by_event_id() -> dict[int, dict[str, Any]]:
    """Map each skipped event to its latest skip decision.

    Returns the skip note, the skipper name, and the skip time per event id, so
    the skipped row Details modal can surface why the record was skipped. Ordered
    oldest first so the most recent skip wins when an event was skipped, reopened,
    and skipped again, mirroring ``_skip_actor_by_event_id``. See journal
    cnv-928/012.
    """
    decision: dict[int, dict[str, Any]] = {}
    for entry in (
        ResolutionAuditEntry.objects.filter(action_taken="skipped")
        .order_by("created_at")
        .values("event_id", "staff_name", "note", "created_at")
    ):
        event_id = entry.get("event_id")
        if event_id is None:
            continue
        created_at = entry.get("created_at")
        decision[int(event_id)] = {
            "note": str(entry.get("note") or ""),
            "staff_name": str(entry.get("staff_name") or ""),
            "created_at": created_at.isoformat() if created_at else None,
        }
    return decision


def _safe_map_record(
    raw_payload: dict[str, Any] | None, field_mapping: dict[str, dict[str, str]]
) -> MappedPatient:
    """Map a raw payload, degrading to an empty record on a malformed map.

    The promote prefill must never fail the form because of a bad mapping, so a
    :class:`MappingError` yields an empty mapped record rather than propagating.
    """
    try:
        return map_record(raw_payload or {}, field_mapping)
    except MappingError:
        return MappedPatient(canvas_fields={}, metadata={}, telecom={})


def _resolve_staff(staff_key: str | None) -> tuple[int | None, str]:
    """Map the session header staff key to the dbid and a display name.

    The session header carries the 32 char hex Staff.key. The Canvas SDK Staff
    model exposes that hex as ``id`` (with db_column="key") and uses the
    integer ``dbid`` as its primary key. The audit row foreign key targets the
    integer dbid, so we look up by the hex and project to the dbid. We also
    capture the staff name at write time so the decision log stays readable
    later even if the staff record changes. A missing key or unknown lookup is
    tolerated so the audit decision still records, just without an actioned_by
    linkage or a name. See journal cnv-909/019 and cnv-909/089.
    """
    if not staff_key:
        return None, ""
    record = (
        StaffProxy.objects.filter(id=staff_key)
        .values("dbid", "first_name", "last_name")
        .first()
    )
    if record is None:
        return None, ""
    dbid: int | None = record.get("dbid")
    name = f"{record.get('first_name') or ''} {record.get('last_name') or ''}".strip()
    return dbid, name
