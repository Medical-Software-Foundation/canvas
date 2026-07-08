from unittest.mock import MagicMock, call, patch

from canvas_sdk.v1.data.staff import Staff

from external_calendar_busy_blocks.calendars.admin_lookup import get_admin_calendar_id

MODULE = "external_calendar_busy_blocks.calendars.admin_lookup"


def test_existing_calendar_returns_id_and_no_effects() -> None:
    mock_staff = MagicMock(full_name="Jane Doe")
    mock_cal = MagicMock(id="cal-uuid-123")
    with (
        patch(f"{MODULE}.Staff.objects") as mock_staff_objects,
        patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects,
        patch(f"{MODULE}.CalendarEffect") as MockCalEffect,
    ):
        mock_staff_objects.get.return_value = mock_staff
        mock_cal_objects.for_calendar_name.return_value.first.return_value = mock_cal
        cal_id, effects = get_admin_calendar_id("p1")

    assert cal_id == "cal-uuid-123"
    assert effects == []
    MockCalEffect.assert_not_called()
    assert mock_staff_objects.mock_calls == [call.get(id="p1")]
    _, kwargs = mock_cal_objects.for_calendar_name.call_args
    assert kwargs["provider_name"] == "Jane Doe"
    assert str(kwargs["calendar_type"]) == "Admin"
    assert kwargs["location"] is None


def test_creates_calendar_when_missing() -> None:
    mock_staff = MagicMock(full_name="Jane Doe")
    with (
        patch(f"{MODULE}.Staff.objects") as mock_staff_objects,
        patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects,
        patch(f"{MODULE}.CalendarEffect") as MockCalEffect,
        patch(f"{MODULE}.uuid.uuid4", return_value="new-cal-id"),
    ):
        mock_staff_objects.get.return_value = mock_staff
        mock_cal_objects.for_calendar_name.return_value.first.return_value = None
        MockCalEffect.return_value.create.return_value = "CREATE_EFFECT"
        cal_id, effects = get_admin_calendar_id("p1")

    assert cal_id == "new-cal-id"
    assert effects == ["CREATE_EFFECT"]
    _, kwargs = MockCalEffect.call_args
    assert kwargs["id"] == "new-cal-id"
    assert kwargs["provider"] == "p1"
    assert str(kwargs["type"]) == "Admin"
    assert kwargs["location"] is None


def test_stringifies_uuid_id() -> None:
    import uuid

    cal_uuid = uuid.uuid4()
    mock_staff = MagicMock(full_name="Amanda Peterson")
    with (
        patch(f"{MODULE}.Staff.objects") as mock_staff_objects,
        patch(f"{MODULE}.CalendarModel.objects") as mock_cal_objects,
        patch(f"{MODULE}.CalendarEffect"),
    ):
        mock_staff_objects.get.return_value = mock_staff
        mock_cal_objects.for_calendar_name.return_value.first.return_value = MagicMock(id=cal_uuid)
        cal_id, effects = get_admin_calendar_id("p1")

    assert cal_id == str(cal_uuid)
    assert isinstance(cal_id, str)


def test_returns_empty_when_staff_missing() -> None:
    with (
        patch(f"{MODULE}.Staff.objects") as mock_staff_objects,
        patch(f"{MODULE}.CalendarEffect") as MockCalEffect,
    ):
        mock_staff_objects.get.side_effect = Staff.DoesNotExist
        cal_id, effects = get_admin_calendar_id("nope")

    assert cal_id == ""
    assert effects == []
    MockCalEffect.assert_not_called()


def test_returns_empty_when_name_blank() -> None:
    with (
        patch(f"{MODULE}.Staff.objects") as mock_staff_objects,
        patch(f"{MODULE}.CalendarEffect") as MockCalEffect,
    ):
        mock_staff_objects.get.return_value = MagicMock(full_name="")
        cal_id, effects = get_admin_calendar_id("p1")

    assert cal_id == ""
    assert effects == []
    MockCalEffect.assert_not_called()
