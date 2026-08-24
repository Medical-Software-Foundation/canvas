"""Sending resources to a patient, and reading back what they have."""

from unittest.mock import MagicMock

import pytest

from patient_resources.constants import MAX_SHARE_BATCH, PORTAL_MAX_RESOURCES, STATUS_ACTIVE
from patient_resources.models import PatientResource, PatientResourceShare
from patient_resources.services import shares


@pytest.fixture(autouse=True)
def _reset_managers():
    PatientResource.objects.reset_mock()
    PatientResourceShare.objects.reset_mock()
    PatientResourceShare.objects.bulk_create.side_effect = lambda rows: rows
    yield


def _resource(dbid, title="Managing diabetes", url="https://example.org/d", label="Diabetes"):
    resource = MagicMock()
    resource.dbid = dbid
    resource.title = title
    resource.url = url
    resource.label = label
    resource.status = STATUS_ACTIVE
    return resource


def _catalog(*resources):
    PatientResource.objects.filter.return_value = list(resources)


def _already_shared(*resource_dbids):
    PatientResourceShare.objects.filter.return_value.values_list.return_value = list(resource_dbids)


# --- share_resources ------------------------------------------------------


def test_empty_request_writes_nothing():
    result = shares.share_resources(patient=MagicMock(dbid=55), resource_dbids=[], staff_dbid=1)
    assert result == shares.ShareResult(created=[], already_shared=0, skipped_unavailable=0)
    PatientResourceShare.objects.bulk_create.assert_not_called()


def test_snapshot_is_taken_at_share_time():
    """This is what the patient sees from now on, whatever the catalog does later."""
    _catalog(_resource(12))
    _already_shared()
    shares.share_resources(patient=MagicMock(dbid=55), resource_dbids=[12], staff_dbid=101)

    row = PatientResourceShare.objects.bulk_create.call_args.args[0][0]
    assert row.title_at_share == "Managing diabetes"
    assert row.url_at_share == "https://example.org/d"
    assert row.label_at_share == "Diabetes"
    assert row.patient_id == 55
    assert row.resource_id == 12
    assert row.shared_by_id == 101


def test_shared_at_is_set_explicitly_and_is_timezone_aware():
    """bulk_create cannot report an auto_now_add value back, and the response needs it."""
    _catalog(_resource(12))
    _already_shared()
    shares.share_resources(patient=MagicMock(dbid=55), resource_dbids=[12], staff_dbid=1)

    row = PatientResourceShare.objects.bulk_create.call_args.args[0][0]
    assert row.shared_at is not None
    assert row.shared_at.tzinfo is not None


def test_curator_is_never_a_placeholder():
    """A share attributed to "unknown" looks like an audit trail and is not one."""
    _catalog(_resource(12))
    _already_shared()
    shares.share_resources(patient=MagicMock(dbid=55), resource_dbids=[12], staff_dbid=None)
    row = PatientResourceShare.objects.bulk_create.call_args.args[0][0]
    assert row.shared_by_id is None


def test_already_shared_resources_are_counted_not_recreated():
    _catalog(_resource(12), _resource(15))
    _already_shared(12)
    result = shares.share_resources(
        patient=MagicMock(dbid=55), resource_dbids=[12, 15], staff_dbid=1
    )
    assert result.already_shared == 1
    assert len(result.created) == 1
    assert PatientResourceShare.objects.bulk_create.call_args.args[0][0].resource_id == 15


def test_a_fully_repeated_send_writes_nothing():
    _catalog(_resource(12))
    _already_shared(12)
    result = shares.share_resources(patient=MagicMock(dbid=55), resource_dbids=[12], staff_dbid=1)
    assert result.already_shared == 1
    assert result.created == []
    PatientResourceShare.objects.bulk_create.assert_not_called()


def test_unknown_and_archived_ids_are_reported_as_unavailable():
    """Silently dropping them would let a provider believe a send landed."""
    _catalog(_resource(12))
    _already_shared()
    result = shares.share_resources(
        patient=MagicMock(dbid=55), resource_dbids=[12, 99, 100], staff_dbid=1
    )
    assert result.skipped_unavailable == 2
    assert len(result.created) == 1


def test_only_active_resources_are_fetched():
    _catalog()
    shares.share_resources(patient=MagicMock(dbid=55), resource_dbids=[12], staff_dbid=1)
    assert PatientResource.objects.filter.call_args.kwargs["status"] == STATUS_ACTIVE


def test_batch_is_capped_in_the_service_not_only_the_ui():
    """A direct API client bypasses the picker entirely."""
    over_cap = list(range(MAX_SHARE_BATCH + 10))
    _catalog(*[_resource(dbid) for dbid in over_cap])
    _already_shared()
    shares.share_resources(patient=MagicMock(dbid=55), resource_dbids=over_cap, staff_dbid=1)
    requested = PatientResource.objects.filter.call_args.kwargs["dbid__in"]
    assert len(requested) == MAX_SHARE_BATCH


def test_one_send_is_three_reads_and_one_write():
    """The N+1 rule, asserted rather than reviewed.

    Two filters on the catalog/share tables plus one bulk_create, for a full
    batch -- not one query per resource.
    """
    batch = list(range(MAX_SHARE_BATCH))
    _catalog(*[_resource(dbid) for dbid in batch])
    _already_shared()
    shares.share_resources(patient=MagicMock(dbid=55), resource_dbids=batch, staff_dbid=1)

    assert PatientResource.objects.filter.call_count == 1
    assert PatientResourceShare.objects.filter.call_count == 1
    assert PatientResourceShare.objects.bulk_create.call_count == 1


# --- reads ----------------------------------------------------------------


def test_patient_list_is_scoped_filtered_and_ordered():
    shares.live_shares_for_patient(55)
    assert PatientResourceShare.objects.filter.call_args.kwargs == {
        "patient__dbid": 55,
        "revoked_at__isnull": True,
        "resource__status": STATUS_ACTIVE,
    }
    order_by = PatientResourceShare.objects.filter.return_value.select_related.return_value.order_by
    assert order_by.call_args.args == ("-shared_at", "-dbid")


def test_patient_list_is_capped():
    shares.live_shares_for_patient(55)
    sliced = (
        PatientResourceShare.objects.filter.return_value.select_related.return_value.order_by.return_value
    )
    assert sliced.__getitem__.call_args.args[0] == slice(None, PORTAL_MAX_RESOURCES)


def test_withdrawn_list_is_scoped_to_revoked_rows():
    shares.revoked_shares_for_patient(55)
    assert PatientResourceShare.objects.filter.call_args.kwargs == {
        "patient__dbid": 55,
        "revoked_at__isnull": False,
    }


def test_already_shared_lookup_is_one_query_for_the_whole_page():
    _already_shared(12, 15)
    assert shares.shared_resource_dbids(55, [12, 15, 19]) == {12, 15}
    assert PatientResourceShare.objects.filter.call_count == 1


def test_already_shared_lookup_short_circuits_on_an_empty_page():
    assert shares.shared_resource_dbids(55, []) == set()
    PatientResourceShare.objects.filter.assert_not_called()


# --- lifecycle ------------------------------------------------------------


def test_revoking_stamps_every_live_share_of_that_resource():
    PatientResourceShare.objects.filter.return_value.update.return_value = 500
    assert shares.revoke_resource_shares(resource_dbid=12, reason="Broken link") == 500
    assert PatientResourceShare.objects.filter.call_args.kwargs == {
        "resource__dbid": 12,
        "revoked_at__isnull": True,
    }
    update = PatientResourceShare.objects.filter.return_value.update.call_args.kwargs
    assert update["revoked_reason"] == "Broken link"
    assert update["revoked_at"] is not None


def test_revoking_without_a_reason_stores_empty_not_none():
    PatientResourceShare.objects.filter.return_value.update.return_value = 1
    shares.revoke_resource_shares(resource_dbid=12)
    assert PatientResourceShare.objects.filter.return_value.update.call_args.kwargs[
        "revoked_reason"
    ] == ""


def test_mark_viewed_takes_a_patient_and_never_a_share_id():
    """An endpoint accepting a share id is the shape of a cross-patient leak."""
    PatientResourceShare.objects.filter.return_value.update.return_value = 2
    assert shares.mark_viewed(55) == 2
    assert PatientResourceShare.objects.filter.call_args.kwargs == {
        "patient__dbid": 55,
        "first_viewed_at__isnull": True,
        "revoked_at__isnull": True,
    }


def test_unviewed_count_ignores_revoked_and_archived():
    PatientResourceShare.objects.filter.return_value.count.return_value = 3
    assert shares.unviewed_count(55) == 3
    kwargs = PatientResourceShare.objects.filter.call_args.kwargs
    assert kwargs["revoked_at__isnull"] is True
    assert kwargs["resource__status"] == STATUS_ACTIVE
    assert kwargs["first_viewed_at__isnull"] is True


# --- the page-wide has-shares lookup --------------------------------------


def test_resources_with_live_shares_is_one_query_for_the_page():
    PatientResourceShare.objects.filter.return_value.values_list.return_value.distinct.return_value = [
        12,
        19,
    ]
    assert shares.resources_with_live_shares([12, 15, 19]) == {12, 19}
    assert PatientResourceShare.objects.filter.call_count == 1


def test_resources_with_live_shares_short_circuits_on_an_empty_page():
    assert shares.resources_with_live_shares([]) == set()
    PatientResourceShare.objects.filter.assert_not_called()


def test_the_live_lookup_excludes_withdrawn_shares():
    """The question is what a patient holds now, not what they once received.

    Including withdrawn shares here is what made the library offer Withdraw on a
    resource with nothing left to withdraw.
    """
    PatientResourceShare.objects.filter.return_value.values_list.return_value.distinct.return_value = [12]
    shares.resources_with_live_shares([12])
    assert PatientResourceShare.objects.filter.call_args.kwargs["revoked_at__isnull"] is True


def test_withdrawn_lookup_finds_only_revoked_shares():
    PatientResourceShare.objects.filter.return_value.values_list.return_value.distinct.return_value = [12]
    assert shares.resources_with_withdrawn_shares([12, 15]) == {12}
    assert PatientResourceShare.objects.filter.call_args.kwargs == {
        "resource__dbid__in": [12, 15],
        "revoked_at__isnull": False,
    }


def test_withdrawn_lookup_short_circuits_on_an_empty_page():
    assert shares.resources_with_withdrawn_shares([]) == set()
    PatientResourceShare.objects.filter.assert_not_called()


def test_both_share_lookups_ask_for_distinct_rows():
    """One row per resource, not one per share.

    Without it a resource given to five hundred patients drags five hundred rows
    back to build a set of one.
    """
    for call in (shares.resources_with_live_shares, shares.resources_with_withdrawn_shares):
        PatientResourceShare.objects.reset_mock(side_effect=True, return_value=True)
        PatientResourceShare.objects.filter.return_value.values_list.return_value.distinct.return_value = []
        call([12])
        PatientResourceShare.objects.filter.return_value.values_list.return_value.distinct.assert_called_once()


def test_has_live_shares_asks_only_about_unrevoked_shares():
    """The server-side counterpart of the Withdraw control.

    A direct request must not be able to withdraw a resource whose every share
    was already taken back.
    """
    PatientResourceShare.objects.filter.return_value.exists.return_value = True
    assert shares.has_live_shares(MagicMock(dbid=12)) is True
    assert PatientResourceShare.objects.filter.call_args.kwargs == {
        "resource__dbid": 12,
        "revoked_at__isnull": True,
    }


def test_has_live_shares_is_false_when_everything_was_withdrawn():
    PatientResourceShare.objects.filter.return_value.exists.return_value = False
    assert shares.has_live_shares(MagicMock(dbid=12)) is False


def test_the_patient_list_fetches_the_resource_it_now_reads():
    """The payload takes title and label from the live row, so without this join
    every share would fetch its resource separately.
    """
    shares.live_shares_for_patient(55)
    PatientResourceShare.objects.filter.return_value.select_related.assert_called_once_with(
        "resource"
    )
