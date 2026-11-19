from unittest.mock import MagicMock, call, patch

from doxy_in_chart.protocols.doxy_in_chart import DoxyMeTelehealthLaunchActionButton


class TestDoxyMeTelehealthLaunchActionButtonClassAttributes:
    """Tests for class-level attributes."""

    def test_button_title(self):
        assert DoxyMeTelehealthLaunchActionButton.BUTTON_TITLE == "Launch Meeting"

    def test_button_key(self):
        assert DoxyMeTelehealthLaunchActionButton.BUTTON_KEY == "LAUNCH_MEETING"


class TestGetDoxyLink:
    """Tests for get_doxy_link method."""

    def test_returns_doxy_meeting_link_from_appointment(self):
        """Telehealth appointment with doxy.me meeting link returns the link."""
        mock_note = MagicMock()
        mock_appointment = MagicMock()
        mock_appointment.note_type.is_telehealth = True
        mock_appointment.meeting_link = "https://doxy.me/dr-smith"
        mock_appointment.provider.personal_meeting_room_link = "https://doxy.me/room-smith"

        with patch("doxy_in_chart.protocols.doxy_in_chart.Note") as mock_note_cls, \
             patch("doxy_in_chart.protocols.doxy_in_chart.Appointment") as mock_appt_cls:
            mock_note_cls.objects.get.return_value = mock_note
            mock_appt_cls.objects.filter.return_value.order_by.return_value.first.return_value = mock_appointment

            handler = DoxyMeTelehealthLaunchActionButton()
            result = handler.get_doxy_link(42)

            assert mock_note_cls.mock_calls == [call.objects.get(dbid=42)]
            assert mock_appt_cls.mock_calls == [
                call.objects.filter(note=mock_note),
                call.objects.filter().order_by("-dbid"),
                call.objects.filter().order_by().first(),
                call.objects.filter().order_by().first().__bool__(),
            ]
            # note_type.is_telehealth and meeting_link are set as real values,
            # so only __bool__() from `if appointment and` is recorded
            assert mock_appointment.mock_calls == [call.__bool__()]
            assert mock_note.mock_calls == []

            assert result == "https://doxy.me/dr-smith"

    def test_returns_provider_room_link_when_meeting_link_falsy(self):
        """Falls back to provider personal meeting room link when meeting_link is falsy."""
        mock_note = MagicMock()
        mock_appointment = MagicMock()
        mock_appointment.note_type.is_telehealth = True
        mock_appointment.meeting_link = ""
        mock_appointment.provider.personal_meeting_room_link = "https://doxy.me/room-smith"

        with patch("doxy_in_chart.protocols.doxy_in_chart.Note") as mock_note_cls, \
             patch("doxy_in_chart.protocols.doxy_in_chart.Appointment") as mock_appt_cls:
            mock_note_cls.objects.get.return_value = mock_note
            mock_appt_cls.objects.filter.return_value.order_by.return_value.first.return_value = mock_appointment

            handler = DoxyMeTelehealthLaunchActionButton()
            result = handler.get_doxy_link(42)

            assert mock_note_cls.mock_calls == [call.objects.get(dbid=42)]
            assert mock_appt_cls.mock_calls == [
                call.objects.filter(note=mock_note),
                call.objects.filter().order_by("-dbid"),
                call.objects.filter().order_by().first(),
                call.objects.filter().order_by().first().__bool__(),
            ]
            assert mock_appointment.mock_calls == [call.__bool__()]
            assert mock_note.mock_calls == []

            assert result == "https://doxy.me/room-smith"

    def test_returns_none_when_no_appointment(self):
        """Returns None when no appointment is found for the note."""
        mock_note = MagicMock()

        with patch("doxy_in_chart.protocols.doxy_in_chart.Note") as mock_note_cls, \
             patch("doxy_in_chart.protocols.doxy_in_chart.Appointment") as mock_appt_cls:
            mock_note_cls.objects.get.return_value = mock_note
            mock_appt_cls.objects.filter.return_value.order_by.return_value.first.return_value = None

            handler = DoxyMeTelehealthLaunchActionButton()
            result = handler.get_doxy_link(42)

            assert mock_note_cls.mock_calls == [call.objects.get(dbid=42)]
            assert mock_appt_cls.mock_calls == [
                call.objects.filter(note=mock_note),
                call.objects.filter().order_by("-dbid"),
                call.objects.filter().order_by().first(),
            ]
            assert mock_note.mock_calls == []

            assert result is None

    def test_returns_none_when_not_telehealth(self):
        """Returns None when appointment is not telehealth."""
        mock_note = MagicMock()
        mock_appointment = MagicMock()
        mock_appointment.note_type.is_telehealth = False

        with patch("doxy_in_chart.protocols.doxy_in_chart.Note") as mock_note_cls, \
             patch("doxy_in_chart.protocols.doxy_in_chart.Appointment") as mock_appt_cls:
            mock_note_cls.objects.get.return_value = mock_note
            mock_appt_cls.objects.filter.return_value.order_by.return_value.first.return_value = mock_appointment

            handler = DoxyMeTelehealthLaunchActionButton()
            result = handler.get_doxy_link(42)

            assert mock_note_cls.mock_calls == [call.objects.get(dbid=42)]
            assert mock_appt_cls.mock_calls == [
                call.objects.filter(note=mock_note),
                call.objects.filter().order_by("-dbid"),
                call.objects.filter().order_by().first(),
                call.objects.filter().order_by().first().__bool__(),
            ]
            assert mock_appointment.mock_calls == [call.__bool__()]
            assert mock_note.mock_calls == []

            assert result is None

    def test_returns_none_when_link_not_doxy(self):
        """Returns None when meeting link is not a doxy.me URL."""
        mock_note = MagicMock()
        mock_appointment = MagicMock()
        mock_appointment.note_type.is_telehealth = True
        mock_appointment.meeting_link = "https://zoom.us/j/123456"
        mock_appointment.provider.personal_meeting_room_link = ""

        with patch("doxy_in_chart.protocols.doxy_in_chart.Note") as mock_note_cls, \
             patch("doxy_in_chart.protocols.doxy_in_chart.Appointment") as mock_appt_cls:
            mock_note_cls.objects.get.return_value = mock_note
            mock_appt_cls.objects.filter.return_value.order_by.return_value.first.return_value = mock_appointment

            handler = DoxyMeTelehealthLaunchActionButton()
            result = handler.get_doxy_link(42)

            assert mock_note_cls.mock_calls == [call.objects.get(dbid=42)]
            assert mock_appt_cls.mock_calls == [
                call.objects.filter(note=mock_note),
                call.objects.filter().order_by("-dbid"),
                call.objects.filter().order_by().first(),
                call.objects.filter().order_by().first().__bool__(),
            ]
            assert mock_note.mock_calls == []

            assert result is None

    def test_returns_none_when_both_links_falsy(self):
        """Returns None when both meeting_link and provider room link are falsy."""
        mock_note = MagicMock()
        mock_appointment = MagicMock()
        mock_appointment.note_type.is_telehealth = True
        mock_appointment.meeting_link = ""
        mock_appointment.provider.personal_meeting_room_link = ""

        with patch("doxy_in_chart.protocols.doxy_in_chart.Note") as mock_note_cls, \
             patch("doxy_in_chart.protocols.doxy_in_chart.Appointment") as mock_appt_cls:
            mock_note_cls.objects.get.return_value = mock_note
            mock_appt_cls.objects.filter.return_value.order_by.return_value.first.return_value = mock_appointment

            handler = DoxyMeTelehealthLaunchActionButton()
            result = handler.get_doxy_link(42)

            assert mock_note_cls.mock_calls == [call.objects.get(dbid=42)]
            assert mock_appt_cls.mock_calls == [
                call.objects.filter(note=mock_note),
                call.objects.filter().order_by("-dbid"),
                call.objects.filter().order_by().first(),
                call.objects.filter().order_by().first().__bool__(),
            ]
            assert mock_note.mock_calls == []

            assert result is None


class TestVisible:
    """Tests for visible method."""

    def test_visible_returns_true_when_doxy_link_exists(self, mock_event):
        """Returns True when get_doxy_link returns a link."""
        handler = DoxyMeTelehealthLaunchActionButton()
        handler.event = mock_event

        with patch.object(handler, "get_doxy_link", return_value="https://doxy.me/dr-smith") as mock_get_doxy:
            result = handler.visible()

            assert mock_get_doxy.mock_calls == [call(42)]
            assert result is True

    def test_visible_returns_false_when_no_doxy_link(self, mock_event):
        """Returns False when get_doxy_link returns None."""
        handler = DoxyMeTelehealthLaunchActionButton()
        handler.event = mock_event

        with patch.object(handler, "get_doxy_link", return_value=None) as mock_get_doxy:
            result = handler.visible()

            assert mock_get_doxy.mock_calls == [call(42)]
            assert result is False


class TestHandle:
    """Tests for handle method."""

    def test_handle_returns_launch_modal_effect(self, mock_event):
        """Returns a list with a LaunchModalEffect targeting the right chart pane."""
        handler = DoxyMeTelehealthLaunchActionButton()
        handler.event = mock_event

        mock_effect_instance = MagicMock()

        with patch("doxy_in_chart.protocols.doxy_in_chart.render_to_string", return_value="<html>rendered</html>") as mock_render, \
             patch("doxy_in_chart.protocols.doxy_in_chart.LaunchModalEffect") as mock_effect_cls:
            mock_effect_cls.return_value = mock_effect_instance
            mock_effect_cls.TargetType.RIGHT_CHART_PANE = "RIGHT_CHART_PANE"

            result = handler.handle()

            assert mock_render.mock_calls == [
                call("templates/meeting_template.html", {}),
            ]
            assert mock_effect_cls.mock_calls == [
                call(content="<html>rendered</html>", target="RIGHT_CHART_PANE"),
                call().apply(),
            ]
            assert mock_effect_instance.mock_calls == [call.apply()]

            assert result == [mock_effect_instance.apply()]
