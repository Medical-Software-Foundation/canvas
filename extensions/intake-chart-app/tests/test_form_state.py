"""Tests for the form_state module — AttributeHub-backed draft persistence."""
from __future__ import annotations

from intake_chart_app.data import form_state


def test_get_section_returns_empty_dict_when_missing(fake_hubs, note_uuid):
    assert form_state.get_section(note_uuid, "vitals") == {}


def test_set_section_then_get_returns_payload(fake_hubs, note_uuid):
    payload = {"systolic": 120, "diastolic": 80}
    form_state.set_section(note_uuid, "vitals", payload)
    assert form_state.get_section(note_uuid, "vitals") == payload


def test_section_state_is_isolated_per_note(fake_hubs):
    form_state.set_section("note-A", "vitals", {"systolic": 120})
    form_state.set_section("note-B", "vitals", {"systolic": 140})
    assert form_state.get_section("note-A", "vitals") == {"systolic": 120}
    assert form_state.get_section("note-B", "vitals") == {"systolic": 140}


def test_section_state_is_isolated_per_section(fake_hubs, note_uuid):
    form_state.set_section(note_uuid, "vitals", {"a": 1})
    form_state.set_section(note_uuid, "problems", {"b": 2})
    assert form_state.get_section(note_uuid, "vitals") == {"a": 1}
    assert form_state.get_section(note_uuid, "problems") == {"b": 2}


def test_originated_command_returns_none_when_missing(fake_hubs, note_uuid):
    assert form_state.get_originated_command(note_uuid, "vitals") is None


def test_originated_command_round_trip(fake_hubs, note_uuid):
    form_state.set_originated_command(note_uuid, "vitals", "cmd-uuid-1")
    assert form_state.get_originated_command(note_uuid, "vitals") == "cmd-uuid-1"


def test_clear_originated_command_drops_value(fake_hubs, note_uuid):
    form_state.set_originated_command(note_uuid, "vitals", "cmd-1")
    form_state.clear_originated_command(note_uuid, "vitals")
    assert form_state.get_originated_command(note_uuid, "vitals") is None


def test_clear_originated_command_is_safe_when_unset(fake_hubs, note_uuid):
    # Should not raise when no hub or attribute exists yet.
    form_state.clear_originated_command(note_uuid, "vitals")
    assert form_state.get_originated_command(note_uuid, "vitals") is None


def test_multi_command_map_defaults_to_empty(fake_hubs, note_uuid):
    assert form_state.get_multi_command_map(note_uuid, "problems") == {}


def test_multi_command_map_round_trip(fake_hubs, note_uuid):
    mapping = {"condition:abc": "cmd-1", "condition:def": "cmd-2"}
    form_state.set_multi_command_map(note_uuid, "problems", mapping)
    assert form_state.get_multi_command_map(note_uuid, "problems") == mapping


def test_multi_command_map_round_trip_coerces_str(fake_hubs, note_uuid):
    """Values flowing through AttributeHub may round-trip as plain types; the
    contract says we always read them back as ``dict[str, str]``."""
    form_state.set_multi_command_map(note_uuid, "problems", {"row-1": "cmd-1"})
    out = form_state.get_multi_command_map(note_uuid, "problems")
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in out.items())


def test_writes_use_namespace_canvas_intake_chart_app(fake_hubs, note_uuid):
    """The Python-side ``NAMESPACE`` constant must match the manifest's
    ``custom_data.namespace`` — the runtime only auto-generates the
    namespace_read_write_access_key for the manifest-declared namespace,
    so any mismatch causes every AttributeHub call to target an
    unauthorized namespace in production."""
    form_state.set_section(note_uuid, "vitals", {"x": 1})
    form_state.set_originated_command(note_uuid, "vitals", "cmd-1")
    form_state.set_multi_command_map(note_uuid, "problems", {"r": "cmd-2"})
    # Resolve the snapshot's pending writes so the namespace_auth path
    # would actually trigger on a real runtime.
    snap = form_state.FormStateSnapshot(note_uuid)
    snap.set_originated_command("vitals", "cmd-flush-1")
    snap.flush()
    keys = list(fake_hubs._hubs.keys())
    assert keys, "expected at least one AttributeHub written"
    assert all(t == "canvas__intake_chart_app" for (t, _id) in keys)


def test_namespace_constant_matches_manifest():
    """Regression: the Python ``NAMESPACE`` constant must equal the
    ``custom_data.namespace`` declaration in CANVAS_MANIFEST.json. A
    mismatch ships fine through the unit-test fake (which ignores
    namespace authorization) but breaks every AttributeHub round-trip
    on a real Canvas instance — drafts don't persist, the snapshot
    flush invariant is undermined, and commit retries emit duplicate
    ORIGINATE_* effects because earlier UUIDs are unreadable."""
    import json
    from pathlib import Path
    manifest = json.loads(
        (Path(__file__).resolve().parents[1]
         / "intake_chart_app" / "CANVAS_MANIFEST.json").read_text()
    )
    declared = manifest["custom_data"]["namespace"]
    assert form_state.NAMESPACE == declared, (
        f"form_state.NAMESPACE ({form_state.NAMESPACE!r}) does not match "
        f"CANVAS_MANIFEST.json custom_data.namespace ({declared!r}). "
        f"The runtime auto-generates namespace_read_write_access_key only "
        f"for the manifest-declared namespace; a code-side override "
        f"targets an unauthorized namespace in production."
    )


def test_blank_note_uuid_is_no_op(fake_hubs):
    """Defensive: blank note_uuid must not pollute storage."""
    form_state.set_section("", "vitals", {"x": 1})
    form_state.set_originated_command("", "vitals", "cmd-1")
    form_state.set_multi_command_map("", "problems", {"r": "cmd-2"})
    assert fake_hubs._hubs == {}
    assert form_state.get_section("", "vitals") == {}
    assert form_state.get_originated_command("", "vitals") is None
    assert form_state.get_multi_command_map("", "problems") == {}


# ---------------------------------------------------------------------------
# FormStateSnapshot — request-scoped read-through cache used by IntakeAPI.commit
# to avoid re-fetching the same AttributeHub row 20× per commit.
# ---------------------------------------------------------------------------


def test_snapshot_loads_existing_attributes_at_construction(fake_hubs, note_uuid):
    """A snapshot built after writes should read every stored attribute
    without further hub lookups."""
    form_state.set_section(note_uuid, "vitals", {"systolic": 120})
    form_state.set_originated_command(note_uuid, "vitals", "cmd-1")
    form_state.set_multi_command_map(note_uuid, "problems", {"r1": "cmd-2"})

    snap = form_state.FormStateSnapshot(note_uuid)

    assert snap.get_section("vitals") == {"systolic": 120}
    assert snap.get_originated_command("vitals") == "cmd-1"
    assert snap.get_multi_command_map("problems") == {"r1": "cmd-2"}


def test_snapshot_set_originated_command_visible_in_session_only_until_flush(
    fake_hubs, note_uuid
):
    """``set_*`` stages the write so in-session reads see it, but the
    AttributeHub is untouched until ``flush()`` runs. The all-or-nothing
    commit semantics require this — if commit() aborts before flush,
    earlier sections' UUIDs must not be durable."""
    snap = form_state.FormStateSnapshot(note_uuid)
    snap.set_originated_command("vitals", "cmd-99")

    # In-session read sees the staged value.
    assert snap.get_originated_command("vitals") == "cmd-99"
    # New snapshot reads from the hub — sees nothing yet.
    snap2 = form_state.FormStateSnapshot(note_uuid)
    assert snap2.get_originated_command("vitals") is None
    assert form_state.get_originated_command(note_uuid, "vitals") is None

    # Flush persists the staged write.
    snap.flush()
    snap3 = form_state.FormStateSnapshot(note_uuid)
    assert snap3.get_originated_command("vitals") == "cmd-99"
    assert form_state.get_originated_command(note_uuid, "vitals") == "cmd-99"


def test_snapshot_set_multi_command_map_round_trips_through_hub_after_flush(
    fake_hubs, note_uuid
):
    """Same staging semantics for the multi-command map."""
    snap = form_state.FormStateSnapshot(note_uuid)
    snap.set_multi_command_map("problems", {"r1": "cmd-a", "r2": "cmd-b"})

    # In-session read sees the staged value.
    assert snap.get_multi_command_map("problems") == {
        "r1": "cmd-a", "r2": "cmd-b",
    }
    # Hub-side view is still empty.
    snap2 = form_state.FormStateSnapshot(note_uuid)
    assert snap2.get_multi_command_map("problems") == {}

    snap.flush()
    snap3 = form_state.FormStateSnapshot(note_uuid)
    assert snap3.get_multi_command_map("problems") == {
        "r1": "cmd-a", "r2": "cmd-b",
    }


def test_snapshot_pending_writes_dropped_when_flush_skipped(
    fake_hubs, note_uuid
):
    """All-or-nothing regression: if commit() aborts mid-flight and
    does NOT call flush(), the staged writes must never reach the hub."""
    snap = form_state.FormStateSnapshot(note_uuid)
    snap.set_originated_command("vitals", "vitals-uuid")
    snap.set_originated_command("social_history", "social-uuid")
    snap.set_multi_command_map("problems", {"r1": "cmd-1"})
    assert snap.has_pending_writes() is True

    # Snapshot goes out of scope without flush() being called — the
    # garbage collector drops self._pending; the hub never sees any
    # of these writes.
    del snap
    fresh = form_state.FormStateSnapshot(note_uuid)
    assert fresh.get_originated_command("vitals") is None
    assert fresh.get_originated_command("social_history") is None
    assert fresh.get_multi_command_map("problems") == {}


def test_snapshot_flush_is_idempotent_when_nothing_pending(
    fake_hubs, note_uuid
):
    """``flush()`` is a no-op when ``_pending`` is empty; calling it
    repeatedly after a real flush is safe."""
    snap = form_state.FormStateSnapshot(note_uuid)
    snap.flush()  # no-op
    snap.set_originated_command("vitals", "cmd-1")
    snap.flush()
    snap.flush()  # idempotent
    assert form_state.get_originated_command(note_uuid, "vitals") == "cmd-1"


def test_snapshot_returns_empty_for_missing_section(fake_hubs, note_uuid):
    snap = form_state.FormStateSnapshot(note_uuid)
    assert snap.get_section("vitals") == {}
    assert snap.get_originated_command("vitals") is None
    assert snap.get_multi_command_map("problems") == {}


def test_snapshot_with_blank_note_uuid_is_inert(fake_hubs):
    """Blank note_uuid → no hub created, no writes accepted."""
    snap = form_state.FormStateSnapshot("")
    snap.set_originated_command("vitals", "cmd-1")
    snap.set_multi_command_map("problems", {"r": "c"})
    assert fake_hubs._hubs == {}
    assert snap.get_section("vitals") == {}
    assert snap.get_originated_command("vitals") is None
    assert snap.get_multi_command_map("problems") == {}


def test_snapshot_get_methods_handle_blank_section_id(fake_hubs, note_uuid):
    """All `get_*(section_id)` methods short-circuit when section_id is empty."""
    snap = form_state.FormStateSnapshot(note_uuid)
    assert snap.get_section("") == {}
    assert snap.get_originated_command("") is None
    assert snap.get_multi_command_map("") == {}


def test_snapshot_set_methods_no_op_on_blank_inputs(fake_hubs, note_uuid):
    """Defensive: set_* must not write when section_id or command_uuid is blank."""
    snap = form_state.FormStateSnapshot(note_uuid)
    snap.set_originated_command("", "cmd-1")
    snap.set_originated_command("vitals", "")
    snap.set_multi_command_map("", {"r": "c"})
    # No attributes should have landed.
    assert snap.get_originated_command("vitals") is None
    assert snap.get_multi_command_map("problems") == {}


def test_snapshot_ignores_corrupted_multi_map_value(fake_hubs, note_uuid):
    """When the stored attribute isn't a dict, get_multi_command_map returns {}."""
    snap = form_state.FormStateSnapshot(note_uuid)
    snap._attrs[f"{form_state.MULTI_COMMAND_PREFIX}problems"] = "not-a-dict"
    assert snap.get_multi_command_map("problems") == {}


def test_snapshot_ignores_corrupted_section_value(fake_hubs, note_uuid):
    """When the stored section attribute isn't a dict, get_section returns {}."""
    snap = form_state.FormStateSnapshot(note_uuid)
    snap._attrs[f"{form_state.SECTION_PREFIX}vitals"] = "garbage"
    assert snap.get_section("vitals") == {}


# ---------------------------------------------------------------------------
# get_all_section_drafts — bulk-read for the form-state GET endpoint.
# ---------------------------------------------------------------------------


def test_get_all_section_drafts_returns_empty_when_no_hub(fake_hubs, note_uuid):
    assert form_state.get_all_section_drafts(note_uuid) == {}


def test_get_all_section_drafts_returns_empty_when_blank_uuid(fake_hubs):
    assert form_state.get_all_section_drafts("") == {}


def test_get_all_section_drafts_filters_section_prefix(fake_hubs, note_uuid):
    form_state.set_section(note_uuid, "vitals", {"systolic": 120})
    form_state.set_section(note_uuid, "problems", {"rows": {"r1": {}}})
    form_state.set_originated_command(note_uuid, "vitals", "cmd-1")
    form_state.set_multi_command_map(note_uuid, "problems", {"r1": "cmd-2"})

    drafts = form_state.get_all_section_drafts(note_uuid)

    # Only section: prefixed attrs come back; command:/multi_commands: ignored.
    assert drafts == {
        "vitals": {"systolic": 120},
        "problems": {"rows": {"r1": {}}},
    }


def test_get_all_section_drafts_skips_non_dict_values(fake_hubs, note_uuid):
    """Defensive: a malformed section payload (not a dict) is dropped."""
    form_state.set_section(note_uuid, "vitals", {"systolic": 120})
    # Force-write a non-dict directly to the hub.
    hub = fake_hubs._hubs[(form_state.NAMESPACE, note_uuid)]
    hub.set_attribute(f"{form_state.SECTION_PREFIX}social_history", "bad-value")
    drafts = form_state.get_all_section_drafts(note_uuid)
    assert drafts == {"vitals": {"systolic": 120}}


def test_get_all_section_drafts_skips_empty_section_id(fake_hubs, note_uuid):
    """An attribute with name 'section:' (empty section_id) must be ignored."""
    form_state.set_section(note_uuid, "vitals", {"x": 1})
    hub = fake_hubs._hubs[(form_state.NAMESPACE, note_uuid)]
    hub.set_attribute(form_state.SECTION_PREFIX, {"y": 2})
    drafts = form_state.get_all_section_drafts(note_uuid)
    assert drafts == {"vitals": {"x": 1}}


# ---------------------------------------------------------------------------
# Defensive no-op branches in module-level helpers.
# ---------------------------------------------------------------------------


def test_clear_originated_command_no_op_for_blank_inputs(fake_hubs):
    """Blank note_uuid or section_id must not raise or create a hub."""
    form_state.clear_originated_command("", "vitals")
    form_state.clear_originated_command("note-1", "")
    assert fake_hubs._hubs == {}


def test_set_originated_command_no_op_for_blank_command_uuid(
    fake_hubs, note_uuid
):
    """Blank command_uuid is silently ignored — no hub write."""
    form_state.set_originated_command(note_uuid, "vitals", "")
    assert form_state.get_originated_command(note_uuid, "vitals") is None


def test_get_multi_command_map_returns_empty_when_value_not_dict(
    fake_hubs, note_uuid
):
    """If the stored attribute isn't a dict (e.g. corrupt write), default to {}."""
    form_state.set_section(note_uuid, "vitals", {"x": 1})  # creates the hub
    hub = fake_hubs._hubs[(form_state.NAMESPACE, note_uuid)]
    hub.set_attribute(f"{form_state.MULTI_COMMAND_PREFIX}problems", "garbage")
    assert form_state.get_multi_command_map(note_uuid, "problems") == {}
