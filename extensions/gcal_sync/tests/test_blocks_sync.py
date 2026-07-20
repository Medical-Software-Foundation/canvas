"""Tests for the admin-block sweep: title exclusion, inbound-block suppression, upsert/delete, sweep."""

from datetime import datetime, timezone
from types import SimpleNamespace

from gcal_sync.blocks import BlockSync, block_snapshot, excluded_block_titles, sync_all_blocks

SA = {"GOOGLE_SERVICE_ACCOUNT_JSON": '{"client_email": "svc@x.iam", "private_key": "KEY"}'}


def _bs(secrets=None):
    return BlockSync(secrets or SA, client_factory=lambda c: SimpleNamespace())


def test_excluded_block_titles_default_and_custom():
    assert excluded_block_titles({}) == {"Buffer", "Lead Time"}
    assert excluded_block_titles({"EXCLUDED_BLOCK_TITLES": "PTO, Out"}) == {"PTO", "Out"}


def test_block_snapshot_computes_duration():
    event = SimpleNamespace(
        id="ev1",
        title="Lunch",
        starts_at=datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 22, 12, 30, tzinfo=timezone.utc),
    )
    snap = block_snapshot(event)
    assert snap["duration_minutes"] == 30
    assert snap["visit_type"] == "Lunch"


def test_current_blocks_excludes_buffer_titles(mocker):
    bs = _bs()
    staff = mocker.patch("gcal_sync.blocks.Staff")
    staff.objects.filter.return_value.first.return_value = SimpleNamespace(full_name="Joe Ryan")
    cal = mocker.patch("gcal_sync.blocks.Calendar")
    cal.objects.filter.return_value.values_list.return_value = [169]
    ev = mocker.patch("gcal_sync.blocks.Event")
    ev.objects.filter.return_value = [
        SimpleNamespace(id="ev1", title="Lunch"),   # real block -> keep
        SimpleNamespace(id="ev2", title="Buffer"),  # auto-generated artifact -> excluded
    ]
    result = bs._current_blocks("14")
    assert set(result) == {"ev1"}


def test_current_blocks_empty_without_admin_calendar(mocker):
    bs = _bs()
    staff = mocker.patch("gcal_sync.blocks.Staff")
    staff.objects.filter.return_value.first.return_value = SimpleNamespace(full_name="Joe Ryan")
    cal = mocker.patch("gcal_sync.blocks.Calendar")
    cal.objects.filter.return_value.values_list.return_value = []
    assert bs._current_blocks("14") == {}


def test_upsert_inserts_new_block(mocker):
    bs = _bs()
    cem = mocker.patch("gcal_sync.blocks.CalendarEventMapping")
    mocker.patch("gcal_sync.blocks.build_event_body", return_value={})
    mocker.patch("gcal_sync.blocks.content_hash", return_value="h1")
    client = SimpleNamespace(insert_event=mocker.Mock(return_value={"id": "g1"}))
    event = SimpleNamespace(
        id="ev1", title="Lunch",
        starts_at=datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 22, 12, 30, tzinfo=timezone.utc),
    )
    stats = {"pushed": 0, "deleted": 0}
    # Empty cache = "no mapping for this block yet" -> insert path.
    bs._upsert(client, "cal", "ev1", event, stats, {})
    client.insert_event.assert_called_once()
    cem.objects.create.assert_called_once()
    assert stats["pushed"] == 1


def test_upsert_skips_unchanged(mocker):
    bs = _bs()
    mocker.patch("gcal_sync.blocks.build_event_body", return_value={})
    mocker.patch("gcal_sync.blocks.content_hash", return_value="h1")  # same hash
    client = SimpleNamespace(patch_event=mocker.Mock())
    event = SimpleNamespace(
        id="ev1", title="Lunch",
        starts_at=datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 22, 12, 30, tzinfo=timezone.utc),
    )
    existing = SimpleNamespace(
        last_pushed_hash="h1", google_calendar_id="cal", google_event_id="g1"
    )
    stats = {"pushed": 0, "deleted": 0}
    # Prefetched mapping with matching hash -> no Google call.
    bs._upsert(client, "cal", "ev1", event, stats, {"ev1": existing})
    client.patch_event.assert_not_called()  # unchanged -> no Google call
    assert stats["pushed"] == 0


def test_delete_removed_drops_orphans(mocker):
    bs = _bs()
    cem = mocker.patch("gcal_sync.blocks.CalendarEventMapping")
    orphan = SimpleNamespace(canvas_event_id="gone", google_event_id="g9", delete=mocker.Mock())
    cem.objects.filter.return_value = [orphan]
    client = SimpleNamespace(delete_event=mocker.Mock())
    stats = {"pushed": 0, "deleted": 0}
    bs._delete_removed(client, "cal", current_ids={"ev1"}, stats=stats)
    client.delete_event.assert_called_once_with("cal", "g9")
    orphan.delete.assert_called_once()
    assert stats["deleted"] == 1


def test_sync_provider_upserts_then_deletes(mocker):
    bs = _bs()
    mocker.patch.object(bs, "_current_blocks", return_value={"ev1": SimpleNamespace(id="ev1")})
    cem = mocker.patch("gcal_sync.blocks.CalendarEventMapping")
    cem.objects.filter.return_value = []
    up = mocker.patch.object(bs, "_upsert")
    rm = mocker.patch.object(bs, "_delete_removed")
    bs.sync_provider("14", "cal")
    up.assert_called_once()
    rm.assert_called_once()


def test_sync_provider_prefetches_mappings_in_one_query(mocker):
    # N+1 fix: sync_provider loads all block mappings up front (one query keyed by canvas_event_id)
    # and hands each _upsert the shared cache, instead of each _upsert querying per block.
    bs = _bs()
    mocker.patch.object(
        bs,
        "_current_blocks",
        return_value={"ev1": SimpleNamespace(id="ev1"), "ev2": SimpleNamespace(id="ev2")},
    )
    existing = SimpleNamespace(canvas_event_id="ev1")
    cem = mocker.patch("gcal_sync.blocks.CalendarEventMapping")
    cem.objects.filter.return_value = [existing]
    upsert = mocker.patch.object(bs, "_upsert")
    mocker.patch.object(bs, "_delete_removed")

    bs.sync_provider("14", "cal")

    cem.objects.filter.assert_called_once_with(canvas_event_id__in=["ev1", "ev2"])
    # Every _upsert call receives the same prefetched cache; no per-block query.
    for call in upsert.call_args_list:
        assert call.args[-1] == {"ev1": existing}


def test_sync_all_blocks_aggregates(mocker):
    inst = mocker.patch("gcal_sync.blocks.BlockSync").return_value
    inst.sync_provider.return_value = {"pushed": 2, "deleted": 1}
    totals = sync_all_blocks(
        SA, [SimpleNamespace(canvas_staff_id="14", google_calendar_id="c1")]
    )
    assert totals == {"pushed": 2, "deleted": 1}
