"""Per-note draft state for the Intake form, backed by AttributeHub.

Each note has its own AttributeHub keyed by ``(NAMESPACE, note_uuid)``. Section
drafts are stored as ``section:<section_id>`` attributes; the originated
single-section ``command_uuid`` lives at ``command:<section_id>``; the
multi-row reconciliation map lives at ``multi_commands:<section_id>``.

All blank ``note_uuid`` / ``section_id`` inputs short-circuit to no-ops to keep
malformed callers from polluting storage with phantom rows.
"""
from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data import AttributeHub

# This constant MUST equal ``custom_data.namespace`` in CANVAS_MANIFEST.json.
# The Canvas plugin runtime auto-generates ``namespace_read_write_access_key``
# only for the manifest-declared namespace and at namespace-creation time, so
# any mismatch ships fine through unit tests (the fake hub ignores
# authorization) but breaks every AttributeHub round-trip in production —
# drafts don't persist, the snapshot flush invariant is undermined, and
# commit retries emit duplicate ORIGINATE_* effects because earlier UUIDs
# are unreadable. ``tests/test_form_state.py::test_namespace_constant_matches_manifest``
# pins this invariant.
NAMESPACE = "canvas__intake_chart_app"
SECTION_PREFIX = "section:"
COMMAND_PREFIX = "command:"
MULTI_COMMAND_PREFIX = "multi_commands:"
# Per-(note, section_id) flag recording that a ChartSectionReview POST
# already landed for this section on this note. Read by
# ``_commit_multi_section`` to skip re-staging the side-channel POST on
# repeat commits (the home-app endpoint is not idempotent — a re-POST
# produces a duplicate "Reviewed:" card on the chart).
REVIEWED_PREFIX = "reviewed:"


def _get_or_create_hub(note_uuid: str) -> AttributeHub:
    hub, _ = AttributeHub.objects.get_or_create(type=NAMESPACE, id=note_uuid)
    return hub


def _existing_hub(note_uuid: str) -> AttributeHub | None:
    return AttributeHub.objects.filter(type=NAMESPACE, id=note_uuid).first()


def get_section(note_uuid: str, section_id: str) -> dict[str, Any]:
    """Return the saved draft for ``section_id`` on this note, or ``{}``."""
    if not note_uuid or not section_id:
        return {}
    hub = _existing_hub(note_uuid)
    if hub is None:
        return {}
    value = hub.get_attribute(f"{SECTION_PREFIX}{section_id}")
    return value if isinstance(value, dict) else {}


def get_all_section_drafts(note_uuid: str) -> dict[str, dict[str, Any]]:
    """Return every section's saved draft for this note as ``{section_id: data}``.

    ``hub.custom_attributes.all()`` materialises every attribute on the hub
    in a single query; the form-state endpoint previously called
    ``hub.get_attribute(...)`` once per known section, which fanned out to
    one lookup per section on every tab open. Filtering by SECTION_PREFIX in
    Python keeps the section-id list out of the database side and means new
    sections work without a code change here.
    """
    if not note_uuid:
        return {}
    hub = _existing_hub(note_uuid)
    if hub is None:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for attr in hub.custom_attributes.all():
        name = getattr(attr, "name", "") or ""
        if not name.startswith(SECTION_PREFIX):
            continue
        value = getattr(attr, "value", None)
        if not isinstance(value, dict) or not value:
            continue
        section_id = name[len(SECTION_PREFIX):]
        if section_id:
            out[section_id] = value
    return out


def set_section(note_uuid: str, section_id: str, data: dict[str, Any]) -> None:
    """Persist a section's draft payload."""
    if not note_uuid or not section_id:
        return
    hub = _get_or_create_hub(note_uuid)
    hub.set_attribute(f"{SECTION_PREFIX}{section_id}", data)


def get_originated_command(note_uuid: str, section_id: str) -> str | None:
    """Return the command_uuid recorded for a single-command section, or None."""
    if not note_uuid or not section_id:
        return None
    hub = _existing_hub(note_uuid)
    if hub is None:
        return None
    value = hub.get_attribute(f"{COMMAND_PREFIX}{section_id}")
    if not value:
        return None
    return str(value)


def set_originated_command(
    note_uuid: str, section_id: str, command_uuid: str
) -> None:
    if not note_uuid or not section_id or not command_uuid:
        return
    hub = _get_or_create_hub(note_uuid)
    hub.set_attribute(f"{COMMAND_PREFIX}{section_id}", command_uuid)


def clear_originated_command(note_uuid: str, section_id: str) -> None:
    if not note_uuid or not section_id:
        return
    hub = _existing_hub(note_uuid)
    if hub is None:
        return
    hub.custom_attributes.filter(name=f"{COMMAND_PREFIX}{section_id}").delete()


def get_multi_command_map(
    note_uuid: str, section_id: str
) -> dict[str, str]:
    """Return ``{row_id: command_uuid}`` for a multi-command section, or ``{}``.

    Round-trip coerces keys + values to ``str`` since AttributeHub only
    guarantees JSON-shaped values, not their inner types.
    """
    if not note_uuid or not section_id:
        return {}
    hub = _existing_hub(note_uuid)
    if hub is None:
        return {}
    raw = hub.get_attribute(f"{MULTI_COMMAND_PREFIX}{section_id}")
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if k and v}


def set_multi_command_map(
    note_uuid: str, section_id: str, mapping: dict[str, str]
) -> None:
    if not note_uuid or not section_id:
        return
    hub = _get_or_create_hub(note_uuid)
    hub.set_attribute(
        f"{MULTI_COMMAND_PREFIX}{section_id}",
        {str(k): str(v) for k, v in (mapping or {}).items() if k and v},
    )


class FormStateSnapshot:
    """One-shot, in-memory cache of a single note's AttributeHub state.

    Build once at the start of a commit request, then pass into every per-
    section helper. Replaces ~20 redundant ``AttributeHub.objects.filter(...)
    .first()`` lookups (one per ``get_*``/``set_*`` call in
    ``data/form_state.py``) with a single hub fetch + one
    ``hub.custom_attributes.all()`` materialisation.

    The hub is fetched read-only at construction time (``.filter().first()``)
    so opening the commit endpoint doesn't materialise a row for a note
    that has no drafts yet.

    **Writes are buffered.** ``set_originated_command`` /
    ``set_multi_command_map`` stage values in an in-memory pending dict
    so within-request reads see the staged value, but no
    ``hub.set_attribute(...)`` call is issued until ``flush()`` runs.
    This makes the all-or-nothing commit semantics structurally sound: if
    ``commit()`` aborts mid-flight (one section's validator raises), the
    earlier sections' UUID writes never land, so the retry sees a clean
    slate instead of an ``existing_uuid`` pointing at a command that was
    never originated. ``commit()`` calls ``flush()`` only after the
    failures gate passes; all other call paths (tests, future helpers)
    must call ``flush()`` themselves to persist staged writes.

    **Review-POST side-channel is also buffered.** ``stage_review`` records
    a section_id whose all-confirmed rows merit a ``ChartSectionReview``
    POST against the home-app; ``commit()`` dispatches the staged
    section_ids only after the failures gate passes. Same all-or-nothing
    rationale: the home-app endpoint is not idempotent, so an earlier
    section's review POST landing while a later section's validator
    fails would leave orphaned "Reviewed:" cards on the chart and
    duplicate them on retry.

    Plain class (not ``@dataclass``) — Canvas's RestrictedPython sandbox
    barfs on dataclass decoration at module-load time.
    """

    def __init__(self, note_uuid: str) -> None:
        self.note_uuid: str = note_uuid
        self._hub: AttributeHub | None = None
        self._attrs: dict[str, Any] = {}
        # Pending writes staged by set_* and persisted by flush(). Keys
        # are AttributeHub attribute names (already-prefixed); values are
        # the JSON-serialisable payload.
        self._pending: dict[str, Any] = {}
        # Section_ids staged by stage_review() for the ChartSectionReview
        # side-channel POST. Dispatched only after commit() passes its
        # failures gate, alongside flush().
        self._pending_reviews: list[str] = []
        if not note_uuid:
            return
        existing = _existing_hub(note_uuid)
        if existing is None:
            # No hub yet — leave self._hub None and lazily create at
            # flush() time so reads don't insert an empty row.
            return
        self._hub = existing
        # ``custom_attributes.all()`` materialises every attribute on the
        # hub row in one query — the only reason this class exists.
        for attr in self._hub.custom_attributes.all():
            name = getattr(attr, "name", "") or ""
            if name:
                self._attrs[name] = getattr(attr, "value", None)

    def _ensure_hub(self) -> AttributeHub | None:
        """Return the hub, materialising it via ``get_or_create`` on first
        flush. Returns ``None`` when the snapshot was built with a blank
        note_uuid (defensive no-op path)."""
        if self._hub is not None:
            return self._hub
        if not self.note_uuid:
            return None
        self._hub = _get_or_create_hub(self.note_uuid)
        return self._hub

    def get_section(self, section_id: str) -> dict[str, Any]:
        if not section_id:
            return {}
        value = self._attrs.get(f"{SECTION_PREFIX}{section_id}")
        return value if isinstance(value, dict) else {}

    def get_originated_command(self, section_id: str) -> str | None:
        if not section_id:
            return None
        value = self._attrs.get(f"{COMMAND_PREFIX}{section_id}")
        return str(value) if value else None

    def set_originated_command(self, section_id: str, command_uuid: str) -> None:
        """Stage a write of the originated command UUID. Use ``flush()``
        to persist; without ``flush()``, the staged value is visible to
        in-session reads but never reaches AttributeHub."""
        if not section_id or not command_uuid:
            return
        if not self.note_uuid:
            return
        key = f"{COMMAND_PREFIX}{section_id}"
        self._attrs[key] = command_uuid
        self._pending[key] = command_uuid

    def get_multi_command_map(self, section_id: str) -> dict[str, str]:
        if not section_id:
            return {}
        raw = self._attrs.get(f"{MULTI_COMMAND_PREFIX}{section_id}")
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items() if k and v}

    def set_multi_command_map(
        self, section_id: str, mapping: dict[str, str]
    ) -> None:
        """Stage a write of the row-to-command-uuid map. Use ``flush()``
        to persist."""
        if not section_id:
            return
        if not self.note_uuid:
            return
        key = f"{MULTI_COMMAND_PREFIX}{section_id}"
        cleaned = {str(k): str(v) for k, v in (mapping or {}).items() if k and v}
        self._attrs[key] = cleaned
        self._pending[key] = cleaned

    def has_pending_writes(self) -> bool:
        """``True`` when there are staged writes waiting for ``flush()``."""
        return bool(self._pending)

    def flush(self) -> None:
        """Persist every staged write to the underlying AttributeHub in
        one batch, then clear the pending buffer. Safe to call when
        nothing is pending. ``commit()`` calls this only after its
        all-or-nothing failures gate has passed."""
        if not self._pending:
            return
        hub = self._ensure_hub()
        if hub is None:
            # Blank note_uuid path — staged values are discarded.
            self._pending.clear()
            return
        for key, value in self._pending.items():
            hub.set_attribute(key, value)
        self._pending.clear()

    def stage_review(self, section_id: str) -> None:
        """Stage a ``ChartSectionReview`` POST for ``section_id``. The
        actual HTTP call only fires when ``commit()`` dispatches the
        pending list after its failures gate; if commit aborts, no
        review POST goes out. Idempotent within a single snapshot
        (re-staging the same section_id is a no-op)."""
        if not section_id:
            return
        if section_id in self._pending_reviews:
            return
        self._pending_reviews.append(section_id)

    @property
    def pending_review_section_ids(self) -> tuple[str, ...]:
        """Section_ids that ``commit()`` should dispatch review POSTs for
        after the failures gate passes. Returned in stage order."""
        return tuple(self._pending_reviews)

    def clear_pending_reviews(self) -> None:
        """Drop the staged review list. ``commit()`` calls this after
        dispatching so a retry doesn't double-send."""
        self._pending_reviews.clear()

    def is_section_reviewed(self, section_id: str) -> bool:
        """Return ``True`` when a ChartSectionReview POST for
        ``section_id`` already landed for this note on a prior commit.

        Stored as a persistent AttributeHub flag (``reviewed:<section_id>``)
        because the home-app endpoint is not idempotent — without the
        flag, every successive commit on the same note would re-POST and
        produce a fresh "Reviewed:" card on the chart, cluttering the
        Commands tab and confusing the audit trail."""
        if not section_id:
            return False
        return bool(self._attrs.get(f"{REVIEWED_PREFIX}{section_id}"))

    def mark_section_reviewed(self, section_id: str) -> None:
        """Stage the persistent flag that ``is_section_reviewed`` reads.
        Use ``flush()`` to persist. Called by ``_dispatch_pending_reviews``
        ONLY when the underlying POST returned 2xx — a failed POST
        leaves the flag unset so the next commit retries."""
        if not section_id or not self.note_uuid:
            return
        key = f"{REVIEWED_PREFIX}{section_id}"
        self._attrs[key] = "1"
        self._pending[key] = "1"
