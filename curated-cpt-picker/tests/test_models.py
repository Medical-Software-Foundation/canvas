"""Tests for the CuratedCptCode custom data model.

Covers field defaults, save/round-trip, and ordering behavior.
"""

from curated_cpt_picker.models.curated_cpt_code import CuratedCptCode


def test_can_create_and_retrieve_curated_entry() -> None:
    entry = CuratedCptCode.objects.create(
        cpt_code="99213",
        description="Established patient, 15 min",
    )
    assert entry.pk is not None

    fetched = CuratedCptCode.objects.get(pk=entry.pk)
    assert fetched.cpt_code == "99213"
    assert fetched.description == "Established patient, 15 min"


def test_default_field_values() -> None:
    entry = CuratedCptCode.objects.create(
        cpt_code="99214",
        description="Established patient, 25 min",
    )
    assert entry.default_units == 1
    assert entry.modifiers == []
    assert entry.display_order == 0
    assert entry.enabled is True
    assert entry.created_at is not None
    assert entry.updated_at is not None


def test_ordering_by_display_order_then_cpt() -> None:
    CuratedCptCode.objects.create(cpt_code="99214", description="B", display_order=10)
    CuratedCptCode.objects.create(cpt_code="99213", description="A", display_order=5)
    CuratedCptCode.objects.create(cpt_code="99215", description="C", display_order=10)

    cpts = [e.cpt_code for e in CuratedCptCode.objects.all()]
    # display_order=5 first, then both display_order=10 (tied) sorted by cpt_code
    assert cpts == ["99213", "99214", "99215"]


def test_modifiers_persisted_as_json_list() -> None:
    entry = CuratedCptCode.objects.create(
        cpt_code="99213",
        description="With modifier",
        modifiers=[
            {"code": "25", "system": "http://www.ama-assn.org/go/cpt"},
            {"code": "59", "system": "http://www.ama-assn.org/go/cpt"},
        ],
    )
    fetched = CuratedCptCode.objects.get(pk=entry.pk)
    assert len(fetched.modifiers) == 2
    assert fetched.modifiers[0]["code"] == "25"
    assert fetched.modifiers[1]["code"] == "59"


def test_soft_disable_via_enabled_flag() -> None:
    entry = CuratedCptCode.objects.create(
        cpt_code="99213",
        description="Soft disable test",
        enabled=False,
    )
    assert entry.enabled is False
    # The entry still exists; the picker filters by enabled=True so disabled
    # entries stay in the table but become invisible to providers.
    assert CuratedCptCode.objects.filter(enabled=False).count() == 1
    assert CuratedCptCode.objects.filter(enabled=True).count() == 0
