"""Tests for the catalog of code sets, sources and order commands.

The catalog is the contract between the admin page, the config store and the
completion queries. These tests hold the three in agreement, because a
disagreement shows up on the instance as a screening that silently never fires.
"""

from preventive_screenings.services import completion
from preventive_screenings.services.catalog import (
    ORDER_COMMANDS,
    SOURCES,
    VALUE_SETS,
    catalog_for_ui,
    value_set_for,
)


def test_every_catalog_source_can_actually_be_read() -> None:
    """A value set pointing at a source the completion module cannot query would
    be offered in the editor and then never match anything."""
    assert set(SOURCES) == set(completion._SPECS)


def test_every_value_set_names_a_known_source() -> None:
    for key, entry in VALUE_SETS.items():
        assert entry.source in SOURCES, f"{key} names unknown source {entry.source}"


def test_every_value_set_actually_carries_codes() -> None:
    """An empty value set would look configured and match nothing."""
    for key, entry in VALUE_SETS.items():
        assert entry.value_set.values, f"{key} resolves to an empty value set"


def test_every_order_command_field_exists_on_its_command() -> None:
    """A code written into a field the command does not have would be dropped
    silently, staging an empty order."""
    for key, entry in ORDER_COMMANDS.items():
        if entry.code_field:
            assert entry.code_field in entry.command.model_fields, (
                f"{key} writes to {entry.code_field}, which its command does not have"
            )


def test_every_code_field_carries_the_name_the_api_uses() -> None:
    """**The guard on a silently empty order.** A command's Python field name is
    not what the Commands API calls it - `image_code` is sent as `image`,
    `tests_order_codes` as `tests`, `cpt_code` as `perform`.

    `recommendation_context` keys by the Python name, so a staged order arrived
    with a key Canvas does not recognise and opened with every field blank. The
    button worked; nothing was pre-filled. Found on a real chart 2026-09-20.

    This reads the mapping back out of the SDK's own schema, so the catalog
    cannot drift from it as the SDK changes.
    """
    for key, entry in ORDER_COMMANDS.items():
        if not entry.code_field:
            assert entry.code_api_field is None, f"{key} has no code field to name"
            continue

        schema = entry.command.model_json_schema()["properties"][entry.code_field]
        expected = schema.get("commands_api_name", entry.code_field)

        assert entry.code_api_field == expected, (
            f"{key} sends {entry.code_field!r} to the API as {expected!r}, "
            f"but the catalog says {entry.code_api_field!r}"
        )


def test_value_set_for_resolves_a_known_key() -> None:
    assert value_set_for("mammography") is VALUE_SETS["mammography"].value_set


def test_value_set_for_returns_none_for_an_unknown_key() -> None:
    """A rule naming a key this version no longer ships is unmeasurable, not
    "never done"."""
    assert value_set_for("retired_key") is None
    assert value_set_for("") is None


def test_the_ui_catalog_carries_no_python_classes() -> None:
    """Only plain data crosses into the page; value-set classes never do.

    The strongest form of that is that the whole payload round-trips through
    JSON, which a class object cannot.
    """
    import json

    catalog = catalog_for_ui()

    assert json.loads(json.dumps(catalog)) == catalog

    assert set(catalog) == {"sources", "value_sets", "order_commands"}
    for entry in catalog["value_sets"]:
        assert set(entry) == {"key", "label", "source", "sources", "systems"}
        assert isinstance(entry["label"], str)
        assert entry["source"] in entry["sources"], "the primary source is one of the sources read"
        for system, codes in entry["systems"].items():
            assert isinstance(system, str)
            assert codes and all(isinstance(code, str) for code in codes)
    for entry in catalog["order_commands"]:
        assert set(entry) == {"key", "label", "takes_code"}
        assert isinstance(entry["takes_code"], bool)
    for entry in catalog["sources"]:
        assert set(entry) == {"key", "label"}


def test_the_ui_catalog_reports_which_commands_take_a_code() -> None:
    """The editor shows the code field only where it would be used."""
    by_key = {entry["key"]: entry for entry in catalog_for_ui()["order_commands"]}

    assert by_key["imaging_order"]["takes_code"] is True
    assert by_key["refer"]["takes_code"] is False
