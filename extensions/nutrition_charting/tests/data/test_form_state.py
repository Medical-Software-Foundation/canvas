"""Phase B tests for AttributeHub-backed form-state persistence."""

from unittest.mock import MagicMock, patch

from nutrition_charting.data import form_state


def _hub_with_attrs(attrs: list[tuple[str, object]]) -> MagicMock:
    hub = MagicMock()
    rendered = []
    for name, value in attrs:
        attr = MagicMock()
        attr.name = name
        attr.value = value
        rendered.append(attr)
    hub.custom_attributes.all.return_value = rendered
    return hub


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_get_form_state_returns_empty_when_no_hub(mock_hub_cls: MagicMock) -> None:
    mock_hub_cls.objects.filter.return_value.first.return_value = None

    out = form_state.get_form_state("note-1")

    assert out == {"sections": {}, "visit_type": ""}
    mock_hub_cls.objects.filter.assert_called_once_with(
        type="canvas__nutrition_charting", id="note-1",
    )


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_get_form_state_separates_sections_from_metadata(mock_hub_cls: MagicMock) -> None:
    hub = _hub_with_attrs([
        ("section:medical_chart_review", {"height": "67", "weight": "165"}),
        ("section:dietary_intake", {"breakfast": "eggs"}),
        ("visit_type", "follow_up"),
        ("unrelated_attr", "ignored"),
    ])
    mock_hub_cls.objects.filter.return_value.first.return_value = hub

    out = form_state.get_form_state("note-1")

    assert out["visit_type"] == "follow_up"
    assert out["sections"]["medical_chart_review"] == {"height": "67", "weight": "165"}
    assert out["sections"]["dietary_intake"] == {"breakfast": "eggs"}
    assert "unrelated_attr" not in out["sections"]


def test_get_form_state_blank_note_uuid_returns_empty() -> None:
    assert form_state.get_form_state("") == {"sections": {}, "visit_type": ""}


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_save_section_creates_or_reuses_hub(mock_hub_cls: MagicMock) -> None:
    hub = MagicMock()
    mock_hub_cls.objects.get_or_create.return_value = (hub, True)

    form_state.save_section("note-1", "medical_chart_review", {"height": "70"})

    mock_hub_cls.objects.get_or_create.assert_called_once_with(
        type="canvas__nutrition_charting", id="note-1",
    )
    hub.set_attribute.assert_called_once_with(
        "section:medical_chart_review", {"height": "70"},
    )


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_save_section_skips_when_inputs_missing(mock_hub_cls: MagicMock) -> None:
    form_state.save_section("", "medical_chart_review", {})
    form_state.save_section("note-1", "", {})
    mock_hub_cls.objects.get_or_create.assert_not_called()


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_save_section_with_visit_type_writes_both_in_one_hub_fetch(
    mock_hub_cls: MagicMock,
) -> None:
    """The save_section endpoint passes visit_type via this kwarg so the
    hub get_or_create only fires once per save (the previous flow
    triggered a separate `_save_visit_type` call, doubling the fetch)."""
    hub = MagicMock()
    mock_hub_cls.objects.get_or_create.return_value = (hub, False)

    form_state.save_section(
        "note-1", "medical_chart_review", {"height": "70"},
        visit_type="follow_up",
    )

    # Only one hub fetch
    mock_hub_cls.objects.get_or_create.assert_called_once_with(
        type="canvas__nutrition_charting", id="note-1",
    )
    # Both attributes written through the same hub
    set_calls = hub.set_attribute.call_args_list
    assert ("section:medical_chart_review", {"height": "70"}) in [
        c.args for c in set_calls
    ]
    assert ("visit_type", "follow_up") in [c.args for c in set_calls]


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_save_section_ignores_unknown_visit_type(mock_hub_cls: MagicMock) -> None:
    hub = MagicMock()
    mock_hub_cls.objects.get_or_create.return_value = (hub, False)

    form_state.save_section(
        "note-1", "medical_chart_review", {}, visit_type="bogus",
    )

    # Section was still written, but the bogus visit_type was silently dropped.
    set_calls = [c.args for c in hub.set_attribute.call_args_list]
    assert ("section:medical_chart_review", {}) in set_calls
    assert not any(c[0] == "visit_type" for c in set_calls)


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_save_visit_type_persists_known_values(mock_hub_cls: MagicMock) -> None:
    hub = MagicMock()
    mock_hub_cls.objects.get_or_create.return_value = (hub, False)

    form_state.save_visit_type("note-1", "follow_up")

    hub.set_attribute.assert_called_once_with("visit_type", "follow_up")


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_save_visit_type_ignores_unknown_values(mock_hub_cls: MagicMock) -> None:
    form_state.save_visit_type("note-1", "bogus")
    form_state.save_visit_type("", "initial")
    mock_hub_cls.objects.get_or_create.assert_not_called()


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_record_originated_command_stashes_uuid(mock_hub_cls: MagicMock) -> None:
    hub = MagicMock()
    mock_hub_cls.objects.get_or_create.return_value = (hub, False)

    form_state.record_originated_command("note-1", "social_diet_history", "cmd-uuid-9")

    hub.set_attribute.assert_called_once_with(
        "command:social_diet_history", "cmd-uuid-9",
    )


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_record_originated_command_skips_when_inputs_missing(mock_hub_cls: MagicMock) -> None:
    form_state.record_originated_command("", "x", "uuid")
    form_state.record_originated_command("note-1", "", "uuid")
    form_state.record_originated_command("note-1", "x", "")
    mock_hub_cls.objects.get_or_create.assert_not_called()


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_get_originated_command_returns_stashed_uuid(mock_hub_cls: MagicMock) -> None:
    hub = MagicMock()
    hub.get_attribute.return_value = "cmd-uuid-9"
    mock_hub_cls.objects.filter.return_value.first.return_value = hub

    out = form_state.get_originated_command("note-1", "social_diet_history")

    assert out == "cmd-uuid-9"
    hub.get_attribute.assert_called_once_with("command:social_diet_history")


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_get_originated_command_returns_none_when_unsaved(mock_hub_cls: MagicMock) -> None:
    mock_hub_cls.objects.filter.return_value.first.return_value = None
    assert form_state.get_originated_command("note-1", "social_diet_history") is None


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_get_originated_command_returns_none_when_attribute_missing(mock_hub_cls: MagicMock) -> None:
    hub = MagicMock()
    hub.get_attribute.return_value = None
    mock_hub_cls.objects.filter.return_value.first.return_value = hub

    assert form_state.get_originated_command("note-1", "social_diet_history") is None


def test_get_originated_command_blank_inputs_return_none() -> None:
    assert form_state.get_originated_command("", "x") is None
    assert form_state.get_originated_command("n", "") is None


# ---- Phase D pass 2: clear_originated_command ----

@patch("nutrition_charting.data.form_state.AttributeHub")
def test_clear_originated_command_deletes_attribute_when_hub_exists(
    mock_hub_cls: MagicMock,
) -> None:
    hub = MagicMock()
    mock_hub_cls.objects.filter.return_value.first.return_value = hub

    form_state.clear_originated_command("note-1", "monitor_team_meeting")

    hub.custom_attributes.filter.assert_called_once_with(
        name="command:monitor_team_meeting",
    )
    hub.custom_attributes.filter.return_value.delete.assert_called_once()


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_clear_originated_command_noop_when_no_hub(mock_hub_cls: MagicMock) -> None:
    mock_hub_cls.objects.filter.return_value.first.return_value = None
    # Should not raise.
    form_state.clear_originated_command("note-1", "monitor_team_meeting")


def test_clear_originated_command_noop_for_blank_inputs() -> None:
    # Should not raise even when nothing to clear.
    form_state.clear_originated_command("", "x")
    form_state.clear_originated_command("n", "")


# ---- Phase D pass 2: multi-command map storage ----

@patch("nutrition_charting.data.form_state.AttributeHub")
def test_get_multi_command_map_returns_stashed_dict(mock_hub_cls: MagicMock) -> None:
    hub = MagicMock()
    hub.get_attribute.return_value = {
        "goal:abc": "cmd-uuid-1",
        "goal:def": "cmd-uuid-2",
    }
    mock_hub_cls.objects.filter.return_value.first.return_value = hub

    out = form_state.get_multi_command_map("note-1", "goals")

    hub.get_attribute.assert_called_once_with("multi_commands:goals")
    assert out == {"goal:abc": "cmd-uuid-1", "goal:def": "cmd-uuid-2"}


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_get_multi_command_map_returns_empty_when_no_hub(mock_hub_cls: MagicMock) -> None:
    mock_hub_cls.objects.filter.return_value.first.return_value = None
    assert form_state.get_multi_command_map("note-1", "goals") == {}


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_get_multi_command_map_returns_empty_when_attribute_not_dict(
    mock_hub_cls: MagicMock,
) -> None:
    hub = MagicMock()
    hub.get_attribute.return_value = "not a dict"
    mock_hub_cls.objects.filter.return_value.first.return_value = hub
    assert form_state.get_multi_command_map("note-1", "goals") == {}


def test_get_multi_command_map_blank_inputs_return_empty() -> None:
    assert form_state.get_multi_command_map("", "goals") == {}
    assert form_state.get_multi_command_map("n", "") == {}


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_save_multi_command_map_persists_dict(mock_hub_cls: MagicMock) -> None:
    hub = MagicMock()
    mock_hub_cls.objects.get_or_create.return_value = (hub, False)

    form_state.save_multi_command_map(
        "note-1", "goals", {"goal:abc": "cmd-1", "goal:def": "cmd-2"},
    )

    hub.set_attribute.assert_called_once_with(
        "multi_commands:goals",
        {"goal:abc": "cmd-1", "goal:def": "cmd-2"},
    )


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_save_multi_command_map_persists_empty_dict(mock_hub_cls: MagicMock) -> None:
    """Even with no rows we still write the (now-empty) map so a subsequent
    save can correctly diff against it."""
    hub = MagicMock()
    mock_hub_cls.objects.get_or_create.return_value = (hub, False)

    form_state.save_multi_command_map("note-1", "goals", {})

    hub.set_attribute.assert_called_once_with("multi_commands:goals", {})


@patch("nutrition_charting.data.form_state.AttributeHub")
def test_save_multi_command_map_skips_blank_inputs(mock_hub_cls: MagicMock) -> None:
    form_state.save_multi_command_map("", "goals", {"a": "b"})
    form_state.save_multi_command_map("n", "", {"a": "b"})
    mock_hub_cls.objects.get_or_create.assert_not_called()
