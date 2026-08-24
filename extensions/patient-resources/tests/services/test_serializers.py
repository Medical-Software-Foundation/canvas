"""JSON projection.

Every column can be None on a row this plugin did not write, because the DDL
emits no NOT NULL and no defaults. These tests are mostly about that.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from patient_resources.constants import STATUS_ACTIVE, STATUS_ARCHIVED
from patient_resources.services import serializers

WHEN = datetime(2026, 8, 20, 14, 3, 11, tzinfo=timezone.utc)


def _resource(**overrides):
    resource = MagicMock()
    resource.dbid = 12
    resource.title = "Managing diabetes"
    resource.url = "https://example.org/d"
    resource.label = "Diabetes"
    resource.status = STATUS_ACTIVE
    resource.created_at = WHEN
    resource.updated_at = WHEN
    for key, value in overrides.items():
        setattr(resource, key, value)
    return resource


def _share(**overrides):
    share = MagicMock()
    share.resource_id = 12
    share.title_at_share = "Managing diabetes"
    share.url_at_share = "https://example.org/d"
    share.label_at_share = "Diabetes"
    share.shared_at = WHEN
    share.revoked_at = None
    # Explicitly absent unless a test supplies one. Left as a MagicMock, the
    # live-title lookup would find a mock attribute and stringify it.
    share.resource = None
    for key, value in overrides.items():
        setattr(share, key, value)
    return share


# --- resources ------------------------------------------------------------


def test_resource_serializes_its_fields():
    data = serializers.serialize_resource(_resource())
    assert data["id"] == 12
    assert data["title"] == "Managing diabetes"
    assert data["url"] == "https://example.org/d"
    assert data["label"] == "Diabetes"
    assert data["is_active"] is True


def test_archived_resource_is_flagged_inactive():
    data = serializers.serialize_resource(_resource(status=STATUS_ARCHIVED))
    assert data["is_active"] is False


def test_null_status_is_not_active():
    """A malformed row is hidden rather than published to patients."""
    assert serializers.serialize_resource(_resource(status=None))["is_active"] is False


def test_shared_flag_is_omitted_unless_asked_for():
    assert "shared" not in serializers.serialize_resource(_resource())
    assert serializers.serialize_resource(_resource(), shared=True)["shared"] is True


def test_every_null_column_serializes_without_raising():
    data = serializers.serialize_resource(
        _resource(title=None, url=None, label=None, status=None, created_at=None, updated_at=None)
    )
    assert data["title"] == ""
    assert data["url"] == ""
    assert data["created_at"] is None


def test_a_stored_unsafe_url_is_dropped_at_serialize_time():
    """Storage is not a trust boundary: a row may predate a validator fix."""
    assert serializers.serialize_resource(_resource(url="javascript:alert(1)"))["url"] == ""


# --- shares ---------------------------------------------------------------


def test_patient_view_shows_a_corrected_title():
    """Correcting a typo has to reach the patients who already have it.

    Safe because the link is frozen once a resource has been shared, so a title
    edit can only redescribe the same resource.
    """
    share = _share()
    share.resource = _resource(title="Managing type 2 diabetes", label="Endocrine")
    data = serializers.serialize_share_for_patient(share)
    assert data["title"] == "Managing type 2 diabetes"
    assert data["label"] == "Endocrine"


def test_the_patient_keeps_the_link_they_were_given():
    """The URL is immutable once shared, so snapshot and catalog agree -- and the
    snapshot still works when the catalog row is missing.
    """
    share = _share()
    share.resource = _resource(url="https://example.org/other")
    assert serializers.serialize_share_for_patient(share)["url"] == "https://example.org/d"


def test_a_share_whose_resource_is_gone_falls_back_to_the_snapshot():
    """That foreign key is nullable, so the payload cannot assume a row."""
    data = serializers.serialize_share_for_patient(_share())
    assert data["title"] == "Managing diabetes"
    assert data["label"] == "Diabetes"


def test_an_empty_label_on_the_live_row_is_respected():
    """No label is a real state, not a missing value to fall back from."""
    share = _share()
    share.resource = _resource(label="")
    assert serializers.serialize_share_for_patient(share)["label"] == ""


def test_a_withdrawn_notice_keeps_the_name_the_patient_was_given():
    """Its resource may since have been edited or removed, and it is not openable
    anyway, so the snapshot is the more useful record.
    """
    share = _share(revoked_at=WHEN, title_at_share="Old handout")
    share.resource = _resource(title="Something else entirely")
    assert serializers.serialize_withdrawn_share(share)["title"] == "Old handout"


def test_patient_view_emits_utc_iso_for_client_side_formatting():
    data = serializers.serialize_share_for_patient(_share())
    assert data["shared_at"] == "2026-08-20T14:03:11+00:00"


def test_null_timestamp_stays_null_rather_than_the_string_none():
    """"None oz" in a patient's portal is the failure this prevents."""
    assert serializers.serialize_share_for_patient(_share(shared_at=None))["shared_at"] is None


def test_share_with_an_unsafe_snapshot_url_renders_no_link():
    data = serializers.serialize_share_for_patient(_share(url_at_share="javascript:alert(1)"))
    assert data["url"] == ""


def test_share_with_null_snapshot_columns_serializes():
    data = serializers.serialize_share_for_patient(
        _share(title_at_share=None, url_at_share=None, label_at_share=None)
    )
    assert data == {"title": "", "label": "", "url": "", "shared_at": "2026-08-20T14:03:11+00:00"}


def test_staff_view_carries_the_resource_id_for_picker_marking():
    assert serializers.serialize_share_for_staff(_share())["resource_id"] == 12


def test_withdrawn_share_is_named_and_dated_but_not_linkable():
    """A patient should see that something was withdrawn, not just fewer items."""
    data = serializers.serialize_withdrawn_share(_share(revoked_at=WHEN))
    assert data["title"] == "Managing diabetes"
    assert data["revoked_at"] == "2026-08-20T14:03:11+00:00"
    assert "url" not in data


def test_non_datetime_timestamp_degrades_to_text():
    assert serializers.serialize_share_for_patient(_share(shared_at="2026-08-20"))[
        "shared_at"
    ] == "2026-08-20"
