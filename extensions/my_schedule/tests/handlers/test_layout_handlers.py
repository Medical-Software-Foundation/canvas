"""Tests for the homepage, menu, panel and booking handlers."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.effects.panel_configuration import PanelConfiguration
from canvas_sdk.effects.provider_menu_configuration import ProviderMenuConfiguration

from my_schedule.handlers import booking_providers, hide_native_schedule, homepage
from my_schedule.handlers.booking_providers import BookOnlySelf
from my_schedule.handlers.hide_native_schedule import (
    HideAppointmentsPanelFilter,
    HideNativeScheduleMenu,
)
from my_schedule.handlers.homepage import APP_IDENTIFIER, MyScheduleHomepage

MANIFEST = Path(__file__).parents[2] / "my_schedule" / "CANVAS_MANIFEST.json"

MD = SimpleNamespace(
    id="md-key", roles=SimpleNamespace(all=lambda: [SimpleNamespace(internal_code="MD")])
)
CC = SimpleNamespace(
    id="cc-key", roles=SimpleNamespace(all=lambda: [SimpleNamespace(internal_code="CC")])
)


def _handler(cls, *, actor=None, context=None, secrets=None):
    handler = cls.__new__(cls)
    handler.event = SimpleNamespace(
        actor=SimpleNamespace(id=actor),
        context=context or {},
        target=SimpleNamespace(id=None),
    )
    handler.secrets = secrets or {}
    return handler


class TestHomepage:
    def test_restricted_staff_get_my_schedule(self) -> None:
        with (
            patch.object(homepage, "staff_by_user_dbid", return_value=MD) as lookup,
            patch.object(homepage, "DefaultHomepageEffect") as effect,
        ):
            effects = _handler(MyScheduleHomepage, actor="7").compute()
        lookup.assert_called_once_with("7")
        effect.assert_called_once_with(application_identifier=APP_IDENTIFIER)
        assert effects == [effect.return_value.apply.return_value]

    def test_app_identifier_matches_manifest(self) -> None:
        manifest = json.loads(MANIFEST.read_text())
        classes = [a["class"] for a in manifest["components"]["applications"]]
        assert APP_IDENTIFIER in classes

    @pytest.mark.parametrize("staff", [CC, None])
    def test_everyone_else_keeps_normal_homepage(self, staff) -> None:
        with patch.object(homepage, "staff_by_user_dbid", return_value=staff):
            assert _handler(MyScheduleHomepage, actor="7").compute() == []

    def test_exempt_staff_keep_normal_homepage(self) -> None:
        with patch.object(homepage, "staff_by_user_dbid", return_value=MD):
            handler = _handler(
                MyScheduleHomepage, actor="7", secrets={"EXEMPT_STAFF_IDS": "md-key"}
            )
            assert handler.compute() == []


class TestHideMenu:
    def test_restricted_staff_lose_only_schedule(self) -> None:
        with patch.object(hide_native_schedule, "staff_by_user_dbid", return_value=MD) as lookup:
            effects = _handler(
                HideNativeScheduleMenu, actor="7"
            ).compute()
        lookup.assert_called_once_with("7")
        items = json.loads(effects[0].payload)["data"]["items"]
        assert "schedule" not in items
        expected = {i.value for i in ProviderMenuConfiguration.Items} - {"schedule"}
        assert set(items) == expected

    def test_unrestricted_staff_unchanged(self) -> None:
        with patch.object(hide_native_schedule, "staff_by_user_dbid", return_value=CC):
            handler = _handler(HideNativeScheduleMenu, actor="8")
            assert handler.compute() == []

    def test_missing_actor_unchanged(self) -> None:
        with patch.object(hide_native_schedule, "staff_by_user_dbid", return_value=None) as lookup:
            assert _handler(HideNativeScheduleMenu).compute() == []
        lookup.assert_called_once_with(None)


class TestHidePanelFilter:
    def test_restricted_staff_lose_only_appointments(self) -> None:
        with patch.object(hide_native_schedule, "staff_by_user_dbid", return_value=MD):
            effects = _handler(
                HideAppointmentsPanelFilter, actor="7"
            ).compute()
        data = json.loads(effects[0].payload)["data"]
        expected = {s.value for s in PanelConfiguration.PanelGlobalSection} - {"appointment"}
        assert set(data["sections"]) == expected

    def test_patient_panel_is_left_alone(self) -> None:
        with patch.object(hide_native_schedule, "staff_by_user_dbid", return_value=MD) as lookup:
            handler = _handler(
                HideAppointmentsPanelFilter, actor="7"
            )
            handler.event.target = SimpleNamespace(id="patient-key")
            assert handler.compute() == []
        lookup.assert_not_called()

    def test_unrestricted_staff_unchanged(self) -> None:
        with patch.object(hide_native_schedule, "staff_by_user_dbid", return_value=CC):
            handler = _handler(
                HideAppointmentsPanelFilter, actor="8"
            )
            assert handler.compute() == []


PROVIDERS = [
    {"text": "Other Provider, MD", "value": "other-key", "selected": False},
    {"text": "Me, MD", "value": "md-key", "selected": True},
]


class TestBookOnlySelf:
    def test_restricted_staff_see_only_themselves(self) -> None:
        with patch.object(booking_providers, "staff_by_user_dbid", return_value=MD):
            effects = _handler(
                BookOnlySelf, actor="7", context={"providers": PROVIDERS}
            ).compute()
        assert effects[0].type == EffectType.APPOINTMENT__FORM__PROVIDERS__POST_SEARCH_RESULTS
        assert json.loads(effects[0].payload) == {"providers": [PROVIDERS[1]]}

    def test_restricted_staff_not_in_list_get_empty_list(self) -> None:
        with patch.object(booking_providers, "staff_by_user_dbid", return_value=MD):
            effects = _handler(
                BookOnlySelf, actor="7", context={"providers": [PROVIDERS[0]]}
            ).compute()
        assert json.loads(effects[0].payload) == {"providers": []}

    def test_unrestricted_staff_unchanged(self) -> None:
        with patch.object(booking_providers, "staff_by_user_dbid", return_value=CC):
            handler = _handler(BookOnlySelf, actor="7", context={"providers": PROVIDERS})
            assert handler.compute() == []

    def test_setting_off_leaves_list_alone(self) -> None:
        with patch.object(booking_providers, "staff_by_user_dbid", return_value=MD) as lookup:
            handler = _handler(
                BookOnlySelf,
                actor="7",
                context={"providers": PROVIDERS},
                secrets={"BOOK_ONLY_SELF": "no"},
            )
            assert handler.compute() == []
        lookup.assert_not_called()
