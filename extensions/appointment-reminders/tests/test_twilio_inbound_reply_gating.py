"""Tests for the confirm window and the other-reply follow-up task.

Two rules on the inbound SMS webhook:

1. A confirm reply (Y/YES/1/C) confirms the nearest upcoming appointment only
   when an appointment SMS for that appointment was accepted within
   ``confirm_reply_window_days``. The number is shared with other traffic
   (portal invites, staff texts), and a YES to one of those used to confirm
   whatever appointment was next.
2. With ``other_reply_task_enabled``, a reply the plugin could not act on opens
   a follow-up task instead of only being logged. STOP and decline are unchanged.

Unlike test_twilio_inbound_handler.py, nothing here defaults the recent-reminder
check to True: each test states whether a reminder went out.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.db.models.query import QuerySet

from appointment_reminders.handlers.twilio_inbound_api import TwilioInboundAPI
from appointment_reminders.services.config import (
    DEFAULT_CONFIRM_REPLY_WINDOW_DAYS,
    CampaignConfig,
)
from appointment_reminders.services.twilio_inbound import parse_form_body

_MOD = "appointment_reminders.handlers.twilio_inbound_api"
_URL = "https://example.canvasmedical.com/plugin-io/api/appointment_reminders/twilio/inbound"
_TOKEN = "auth-tok"
_FROM = "%2B14155551234"


class _FakeClaims:
    def __init__(self) -> None:
        self.held: set[tuple[str, str]] = set()

    def claim(self, scope, key):
        if (scope, key) in self.held:
            return False
        self.held.add((scope, key))
        return True


@pytest.fixture(autouse=True)
def _mock_claims():
    with patch(f"{_MOD}.claim_store", return_value=_FakeClaims()):
        yield


def _api(body: str) -> TwilioInboundAPI:
    """A handler with a validly signed request, so the gate is exercised."""
    api = TwilioInboundAPI.__new__(TwilioInboundAPI)
    api.request = MagicMock()
    api.request.body = body
    api.request.form_data.return_value = {}
    api.secrets = {"twilio-auth-token": _TOKEN, "twilio-inbound-webhook-url": _URL}
    api.environment = {"INSTALLATION_TIME_ZONE": "America/New_York"}
    data = _URL
    params = parse_form_body(body)
    for key in sorted(params):
        data += key + params[key]
    signature = base64.b64encode(
        hmac.new(_TOKEN.encode(), data.encode("utf-8"), hashlib.sha1).digest()
    ).decode()
    headers = {"X-Twilio-Signature": signature}
    api.request.headers = MagicMock()
    api.request.headers.get = MagicMock(side_effect=lambda k, d=None: headers.get(k, d))
    return api


def _patient() -> MagicMock:
    patient = MagicMock()
    patient.id = "pat-1"
    patient.dbid = 42
    return patient


def _appt() -> MagicMock:
    appointment = MagicMock()
    appointment.id = "appt-1"
    return appointment


def _config(**overrides) -> CampaignConfig:
    return CampaignConfig(**overrides)


def _run(
    body: str,
    *,
    reminder_sent: bool,
    config: CampaignConfig | None = None,
    appointment: MagicMock | None = None,
    consent_effect: MagicMock | None = None,
):
    """Drive inbound() and return the mocks a test asserts on."""
    api = _api(f"Body={body}&From={_FROM}")
    mocks: dict = {}
    with (
        patch.object(api, "_resolve_patient", return_value=_patient()),
        patch.object(
            api,
            "_nearest_upcoming_appointment",
            return_value=_appt() if appointment is None else appointment,
        ),
        patch.object(
            api, "_appointment_sms_sent_recently", return_value=reminder_sent
        ) as mocks["recent"],
        patch(f"{_MOD}.load_config", return_value=config or _config()) as mocks["load"],
        patch(f"{_MOD}.Team") as mocks["team"],
        patch(f"{_MOD}.Appointment") as mocks["appt"],
        patch(f"{_MOD}.AddTask") as mocks["task"],
        patch(f"{_MOD}.sms_consent_effect", return_value=consent_effect) as mocks[
            "consent"
        ],
        patch(f"{_MOD}.log_inbound_response") as mocks["log"],
    ):
        mocks["team"].objects.filter.return_value.exists.return_value = True
        mocks["result"] = api.inbound()
    mocks["status"] = mocks["log"].call_args.kwargs["status"]
    return mocks


# ---- fix 1: confirm window ----


@pytest.mark.parametrize("token", ["Y", "YES", "1", "C"])
def test_confirm_with_a_recent_reminder_confirms(token: str) -> None:
    m = _run(token, reminder_sent=True, consent_effect=MagicMock())
    m["appt"].assert_called_once_with(instance_id="appt-1")
    m["appt"].return_value.update.assert_called_once()
    assert m["status"].endswith("confirmed")
    m["task"].assert_not_called()


@pytest.mark.parametrize("token", ["Y", "1", "C"])
def test_confirm_without_a_recent_reminder_does_not_confirm(token: str) -> None:
    m = _run(token, reminder_sent=False)
    m["appt"].assert_not_called()
    assert m["status"] == "unrecognized"


def test_confirm_window_comes_from_config() -> None:
    m = _run("Y", reminder_sent=True, config=_config(confirm_reply_window_days=9))
    _patient_arg, appointment, window = m["recent"].call_args.args
    assert window == 9
    assert appointment.id == "appt-1"


def test_yes_to_a_portal_invite_does_not_confirm_the_next_appointment() -> None:
    """Portal invites go out from the same number and are not logged here.

    A patient who has an upcoming appointment but whose only recent text was a
    portal invite replies YES. That YES is still Twilio's opt-in keyword, so
    consent is restored, but the appointment must stay unconfirmed and, with
    the setting on, staff get a task to read the reply.
    """
    m = _run(
        "YES",
        reminder_sent=False,
        config=_config(other_reply_task_enabled=True),
        consent_effect=MagicMock(),
    )
    m["appt"].assert_not_called()
    assert m["consent"].call_args.kwargs["has_consent"] is True
    assert m["status"] == "opted_in+unrecognized"
    m["task"].assert_called_once()


def test_yes_without_reminder_and_setting_off_logs_only() -> None:
    m = _run("YES", reminder_sent=False, consent_effect=MagicMock())
    m["appt"].assert_not_called()
    m["task"].assert_not_called()
    assert m["status"] == "opted_in+unrecognized"


def test_confirm_with_no_upcoming_appointment_skips_the_reminder_query() -> None:
    api = _api(f"Body=Y&From={_FROM}")
    with (
        patch.object(api, "_resolve_patient", return_value=_patient()),
        patch.object(api, "_nearest_upcoming_appointment", return_value=None),
        patch.object(api, "_appointment_sms_sent_recently") as mock_recent,
        patch(f"{_MOD}.load_config", return_value=_config()),
        patch(f"{_MOD}.Appointment") as mock_appt,
        patch(f"{_MOD}.log_inbound_response") as mock_log,
    ):
        api.inbound()
    mock_recent.assert_not_called()
    mock_appt.assert_not_called()
    assert mock_log.call_args.kwargs["status"] == "unrecognized"


# ---- the recent-reminder query itself ----


def _captured_exists_queryset(api: TwilioInboundAPI, window_days: int):
    """Build the real queryset and capture it at .exists() without a database."""
    captured: dict = {}

    def fake_exists(qs):
        captured["qs"] = qs
        return True

    with patch.object(QuerySet, "exists", fake_exists):
        result = api._appointment_sms_sent_recently(_patient(), _appt(), window_days)
    return result, captured["qs"]


def test_recent_reminder_query_is_one_join_free_exists() -> None:
    api = TwilioInboundAPI.__new__(TwilioInboundAPI)
    result, qs = _captured_exists_queryset(api, 4)
    sql = str(qs.query)
    assert result is True
    assert " JOIN " not in sql  # patient_id is the FK column; no join to patient
    where = sql.split(" WHERE ")[1]
    for column in (
        "patient_id",
        "appointment_id",
        "campaign_type",
        "channel",
        "status",
        "created_at",
    ):
        assert column in where


def test_recent_reminder_query_filters_on_the_right_values() -> None:
    api = TwilioInboundAPI.__new__(TwilioInboundAPI)
    before = datetime.now(UTC)
    _, qs = _captured_exists_queryset(api, 4)
    lookups = {
        child.lhs.target.attname + "__" + child.lookup_name: child.rhs
        for child in qs.query.where.children
    }
    assert lookups["patient_id__exact"] == 42
    assert lookups["appointment_id__exact"] == "appt-1"
    assert sorted(lookups["campaign_type__in"]) == [
        "confirmation",
        "reminder",
        "telehealth",
    ]
    assert lookups["channel__exact"] == "sms"
    assert lookups["status__exact"] == "accepted"
    cutoff = lookups["created_at__gte"]
    assert (
        before - timedelta(days=4, seconds=5)
        < cutoff
        <= before - timedelta(days=4) + timedelta(seconds=5)
    )


# ---- fix 2: other-reply task ----


def test_other_reply_with_setting_off_logs_only() -> None:
    m = _run("can%20I%20call%20you", reminder_sent=False)
    m["task"].assert_not_called()
    assert m["status"] == "unrecognized"
    assert len(m["result"]) == 1  # the 200 only


def test_other_reply_with_setting_on_opens_a_task_for_the_configured_team() -> None:
    m = _run(
        "can%20I%20call%20you",
        reminder_sent=False,
        config=_config(
            other_reply_task_enabled=True,
            other_reply_task_team_id="team-other",
            decline_task_team_id="team-decline",
            decline_task_due_days=1,
        ),
    )
    m["task"].assert_called_once()
    kwargs = m["task"].call_args.kwargs
    assert kwargs["patient_id"] == "pat-1"
    assert kwargs["team_id"] == "team-other"
    assert kwargs["labels"] == ["sms-reply"]
    assert '"can I call you"' in kwargs["title"]
    assert kwargs["due"] is not None and kwargs["due"] > datetime.now(UTC)
    m["team"].objects.filter.assert_called_once_with(id="team-other")
    assert m["status"] == "unrecognized"
    assert len(m["result"]) == 2  # task + 200


def test_other_reply_task_is_unassigned_when_its_team_is_gone() -> None:
    api = TwilioInboundAPI.__new__(TwilioInboundAPI)
    with patch(f"{_MOD}.Team") as mock_team, patch(f"{_MOD}.AddTask") as mock_task:
        mock_team.objects.filter.return_value.exists.return_value = False
        api._other_reply_task(
            _patient(), "hello", _config(other_reply_task_team_id="gone")
        )
    assert mock_task.call_args.kwargs["team_id"] is None


def test_other_reply_task_title_quotes_a_long_reply_truncated() -> None:
    api = TwilioInboundAPI.__new__(TwilioInboundAPI)
    with patch(f"{_MOD}.AddTask") as mock_task:
        api._other_reply_task(_patient(), "word " * 100, _config())
    title = mock_task.call_args.kwargs["title"]
    assert "…" in title
    assert len(title) < 200


def test_stop_is_unchanged_with_the_setting_on() -> None:
    m = _run(
        "STOP",
        reminder_sent=False,
        config=_config(other_reply_task_enabled=True),
        consent_effect=MagicMock(),
    )
    assert m["consent"].call_args.kwargs["has_consent"] is False
    m["task"].assert_not_called()
    m["appt"].assert_not_called()
    m["load"].assert_not_called()  # STOP stays free of a config read
    assert m["status"] == "opted_out"


@pytest.mark.parametrize("keyword", ["CANCEL", "START"])
def test_bare_consent_keywords_do_not_open_a_task(keyword: str) -> None:
    m = _run(
        keyword,
        reminder_sent=False,
        config=_config(other_reply_task_enabled=True),
        consent_effect=MagicMock(),
    )
    m["task"].assert_not_called()
    m["appt"].assert_not_called()


def test_decline_is_unchanged_with_the_setting_on() -> None:
    m = _run(
        "N",
        reminder_sent=False,
        config=_config(other_reply_task_enabled=True, decline_task_team_id="team-d"),
    )
    m["task"].assert_called_once()  # the decline task, not a second one
    kwargs = m["task"].call_args.kwargs
    assert kwargs["labels"] == ["appointment-decline"]
    assert kwargs["team_id"] == "team-d"
    m["recent"].assert_not_called()  # decline is not gated on the window
    assert m["status"] == "declined"


def test_confirmed_reply_does_not_open_a_task_with_the_setting_on() -> None:
    m = _run("Y", reminder_sent=True, config=_config(other_reply_task_enabled=True))
    m["task"].assert_not_called()
    assert m["status"] == "confirmed"


# ---- config parsing ----


def test_new_settings_default_off_and_round_trip() -> None:
    config = CampaignConfig()
    assert config.other_reply_task_enabled is False
    assert config.other_reply_task_team_id == ""
    assert config.confirm_reply_window_days == DEFAULT_CONFIRM_REPLY_WINDOW_DAYS == 4
    loaded = CampaignConfig.from_dict(
        {
            "other_reply_task_enabled": True,
            "other_reply_task_team_id": "team-other",
            "confirm_reply_window_days": 7,
        }
    )
    assert CampaignConfig.from_dict(loaded.to_dict()) == loaded
    assert loaded.confirm_reply_window_days == 7


@pytest.mark.parametrize("raw", [0, -2, "", None, "abc"])
def test_bad_confirm_window_falls_back_to_the_default(raw) -> None:
    config = CampaignConfig.from_dict({"confirm_reply_window_days": raw})
    assert config.confirm_reply_window_days == DEFAULT_CONFIRM_REPLY_WINDOW_DAYS


def test_confirm_window_accepts_a_numeric_string() -> None:
    assert (
        CampaignConfig.from_dict(
            {"confirm_reply_window_days": "6"}
        ).confirm_reply_window_days
        == 6
    )
