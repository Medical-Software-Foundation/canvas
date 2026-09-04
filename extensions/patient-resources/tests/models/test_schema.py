"""Field-declaration tests for the plugin-owned tables.

These are not busywork. The plugin DDL pipeline emits ``ADD COLUMN IF NOT
EXISTS`` and nothing else -- no DROP COLUMN, no ALTER TYPE, no RENAME -- so a
column declared wrong cannot be corrected after the first install. These
assertions are the only thing standing between a typo and a permanent one.
"""

from django.db.models import Q

from patient_resources.constants import STATUS_ACTIVE
from patient_resources.models import (
    PatientProxy,
    PatientResource,
    PatientResourceShare,
    StaffProxy,
)


def _field(model, name):
    return model.__dict__[name]


def _constraint(model, name):
    for constraint in model.Meta.constraints:
        if constraint.kwargs.get("name") == name:
            return constraint
    raise AssertionError(f"no constraint named {name!r} on {model.__name__}")


def _index_names(model):
    return {index.kwargs.get("name") for index in model.Meta.indexes}


# --- PatientResource -------------------------------------------------------


def test_resource_status_defaults_to_active():
    """A row this code creates is listable; anything else is not.

    The default matters because the DDL emits no column default: it applies only
    on our own create path. Readers treat any other value, including None, as
    not listable, so a malformed row is hidden rather than published to patients.
    """
    assert _field(PatientResource, "status").default == STATUS_ACTIVE


def test_resource_text_columns_declare_no_max_length_or_choices():
    """Neither is enforced by the DDL, so declaring them would be a lie.

    Length is checked in services/validation.py; the status vocabulary is checked
    in services/catalog.py.
    """
    for name in ("title", "url", "label", "default_note", "status"):
        kwargs = _field(PatientResource, name).kwargs
        assert "max_length" not in kwargs, name
        assert "choices" not in kwargs, name


def test_the_default_note_is_a_column_on_the_resource():
    """The library-level blurb the picker starts from. Never read by the portal."""
    assert _field(PatientResource, "default_note").default == ""


def test_resource_unique_constraint_is_scoped_to_active_rows():
    """Archiving a resource must free its title+label for reuse.

    An unconditional constraint would mean a mistyped resource, once archived,
    blocked the corrected version forever.
    """
    constraint = _constraint(PatientResource, "pr_resource_unique_live_title_label")
    assert constraint.kwargs["fields"] == ["title", "label"]
    condition = constraint.kwargs["condition"]
    assert isinstance(condition, Q)
    assert condition.leaves() == [{"status": STATUS_ACTIVE}]


def test_resource_indexes_cover_the_two_read_paths():
    assert _index_names(PatientResource) == {
        "pr_resource_status_title",
        "pr_resource_label",
    }


def test_resource_curator_keys_are_nullable():
    """The DDL emits no NOT NULL, so a null curator is representable regardless.

    Declaring it null=True keeps our own writes honest about that rather than
    implying an enforcement the database does not have.
    """
    assert _field(PatientResource, "created_by").null is True
    assert _field(PatientResource, "updated_by").null is True


# --- PatientResourceShare --------------------------------------------------


def test_share_snapshot_columns_exist_and_default_empty():
    """What was sent, as it was sent.

    ``url_at_share`` is what the patient opens and cannot change. The other two
    are history: the title is a fallback for a catalog row that goes missing, and
    the label is written but no longer read anywhere, since labels are internal.
    """
    for name in ("title_at_share", "url_at_share", "label_at_share"):
        assert _field(PatientResourceShare, name).default == ""


def test_the_patient_note_is_a_column_on_the_share_not_the_resource():
    """It was written for one patient, so it belongs to their row.

    Storing it on the catalog instead would mean editing the library's default
    silently rewrote what somebody said about a specific person.
    """
    assert _field(PatientResourceShare, "note").default == ""
    # And the catalog carries only a default, never the note itself.
    assert "note" not in PatientResource.__dict__


def test_share_shared_at_is_nullable_and_not_auto_now_add():
    """Set explicitly by the service so bulk_create can echo it back.

    auto_now_add would make the value unobservable at write time, which the send
    response needs.
    """
    field = _field(PatientResourceShare, "shared_at")
    assert field.null is True
    assert field.auto_now_add is False


def test_share_resource_key_is_nullable():
    """A share whose catalog row vanished out of band must still be readable.

    Every reader has to tolerate ``share.resource is None``.
    """
    assert _field(PatientResourceShare, "resource").null is True


def test_share_lifecycle_columns_are_nullable():
    for name in ("revoked_at", "first_viewed_at"):
        assert _field(PatientResourceShare, name).null is True


def test_share_unique_constraint_is_scoped_to_live_shares():
    """A double click cannot duplicate a link in a patient's list.

    Scoped to live shares so that a deliberate re-send after a retraction is
    still possible.
    """
    constraint = _constraint(PatientResourceShare, "pr_share_unique_live_patient_resource")
    assert constraint.kwargs["fields"] == ["patient", "resource"]
    condition = constraint.kwargs["condition"]
    assert isinstance(condition, Q)
    assert condition.leaves() == [{"revoked_at__isnull": True}]


def test_share_indexes_are_composite_and_lead_with_patient():
    """Both must stay composite.

    A single-field index or constraint on a foreign key column raises at class
    definition time, because those columns are indexed automatically. Simplifying
    either of these to ``["patient"]`` would stop the plugin loading -- which the
    test suite would not otherwise notice.
    """
    by_name = {index.kwargs["name"]: index.kwargs["fields"] for index in PatientResourceShare.Meta.indexes}
    assert by_name == {
        "pr_share_patient_recent": ["patient", "-shared_at"],
        "pr_share_patient_unviewed": ["patient", "first_viewed_at"],
    }
    for fields in by_name.values():
        assert len(fields) > 1


# --- Wiring ----------------------------------------------------------------


def test_every_model_and_proxy_is_exported_from_the_package():
    """The schema generator imports from one place, so an unexported model has no table."""
    import patient_resources.models as models_pkg

    assert set(models_pkg.__all__) == {
        "PatientProxy",
        "PatientResource",
        "PatientResourceShare",
        "StaffProxy",
    }
    for name in models_pkg.__all__:
        assert getattr(models_pkg, name) is not None


def test_foreign_keys_point_at_proxies_not_sdk_models():
    """Plugin tables cannot foreign-key straight at an SDK model.

    They key at a proxy that subclasses it alongside ModelExtension.
    """
    assert _field(PatientResource, "created_by").args[0] is StaffProxy
    assert _field(PatientResourceShare, "patient").args[0] is PatientProxy
    assert _field(PatientResourceShare, "shared_by").args[0] is StaffProxy
    assert _field(PatientResourceShare, "resource").args[0] is PatientResource


def test_foreign_keys_key_on_dbid():
    """to_field="dbid" throughout: dbid is the primary key on plugin tables.

    Keying on a 32-char ``id`` column would also inherit the dashed/undashed
    matching problem that services/identity.py exists to solve.
    """
    for model, name in (
        (PatientResource, "created_by"),
        (PatientResource, "updated_by"),
        (PatientResourceShare, "patient"),
        (PatientResourceShare, "shared_by"),
        (PatientResourceShare, "resource"),
    ):
        assert _field(model, name).kwargs["to_field"] == "dbid", f"{model.__name__}.{name}"


def test_related_names_are_namespaced_per_model():
    """Two foreign keys from one model to one target need distinct related_names."""
    assert _field(PatientResource, "created_by").kwargs["related_name"] == "patient_resources_created"
    assert _field(PatientResource, "updated_by").kwargs["related_name"] == "patient_resources_updated"
