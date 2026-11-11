"""Tests for replies from a phone number that more than one chart carries.

Family members often share one number. A reply must land on the chart the
plugin texted, not whichever chart the lookup returns first:

- several charts, sent-SMS rows exist -> the chart most recently texted there
- exactly one chart has a reminded upcoming appointment -> that chart
- several charts, no sent rows -> the first match, as before
- one chart -> returned with no extra query, as before
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from appointment_reminders.handlers.twilio_inbound_api import TwilioInboundAPI
from appointment_reminders.services.config import CampaignConfig
from appointment_reminders.services.twilio_inbound import parse_form_body

_MOD = "appointment_reminders.handlers.twilio_inbound_api"
_URL = "https://example.canvasmedical.com/plugin-io/api/appointment_reminders/twilio/inbound"
_TOKEN = "auth-tok"
_NUMBER = "+14155551234"


class _FakeClaims:
    def claim(self, scope, key):
        return True


@pytest.fixture(autouse=True)
def _mock_claims_and_config():
    with patch(f"{_MOD}.claim_store", return_value=_FakeClaims()), patch(
        f"{_MOD}.load_config", return_value=CampaignConfig()
    ):
        yield


def _bare_api() -> TwilioInboundAPI:
    return TwilioInboundAPI.__new__(TwilioInboundAPI)


def _signed_api(body: str) -> TwilioInboundAPI:
    api = _bare_api()
    api.request = MagicMock()
    api.request.body = body
    api.secrets = {"twilio-auth-token": _TOKEN, "twilio-inbound-webhook-url": _URL}
    data = _URL
    params = parse_form_body(body)
    for key in sorted(params):
        data += key + params[key]
    sig = base64.b64encode(
        hmac.new(_TOKEN.encode(), data.encode(), hashlib.sha1).digest()
    ).decode()
    headers = {"X-Twilio-Signature": sig}
    api.request.headers = MagicMock()
    api.request.headers.get = MagicMock(side_effect=lambda k, d=None: headers.get(k, d))
    return api


def _chart(pid: str, dbid: int, value: str = "4155551234") -> MagicMock:
    contact = MagicMock()
    contact.system = "phone"
    contact.value = value
    patient = MagicMock()
    patient.id = pid
    patient.dbid = dbid
    patient.telecom.all.return_value = [contact]
    return patient


def _ago(hours: int) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


def _wire(mock_patient, mock_delivery, mock_appt, charts, sent, upcoming=()):
    """Point the mocked ORM at ``charts`` (lookup order), ``sent`` rows
    (newest first, as the query orders them) and the ``upcoming`` appointment
    ids among those rows."""
    (mock_patient.objects.filter.return_value
        .prefetch_related.return_value
        .distinct.return_value) = charts
    (mock_delivery.objects.filter.return_value
        .order_by.return_value
        .values_list.return_value) = sent
    mock_appt.objects.filter.return_value.values_list.return_value = list(upcoming)


def _resolve(charts, sent, upcoming=()):
    api = _bare_api()
    with patch(f"{_MOD}.Patient") as mp, \
         patch(f"{_MOD}.NotificationDelivery") as md, \
         patch(f"{_MOD}.AppointmentModel") as ma:
        _wire(mp, md, ma, charts, sent, upcoming)
        return api._resolve_patient(_NUMBER), md


def test_shared_number_goes_to_the_chart_most_recently_texted() -> None:
    first, second = _chart("pat-a", 1), _chart("pat-b", 2)
    # Lookup returns pat-a first; we last texted pat-b.
    sent = [
        (2, "appt-b", "reminder", _ago(2)),
        (1, "appt-a", "reminder", _ago(30)),
    ]
    chosen, md = _resolve([first, second], sent, upcoming=["appt-a", "appt-b"])
    assert chosen is second
    kwargs = md.objects.filter.call_args.kwargs
    assert kwargs["recipient"] == _NUMBER
    assert sorted(kwargs["patient_id__in"]) == [1, 2]
    assert kwargs["channel"] == "sms" and kwargs["status"] == "accepted"


def test_shared_number_prefers_the_only_chart_with_a_reminded_upcoming_visit() -> None:
    first, second = _chart("pat-a", 1), _chart("pat-b", 2)
    # pat-a was texted most recently, but about a visit that is over (no-show
    # notice); only pat-b's reminder is about an appointment still upcoming.
    sent = [
        (1, "appt-a", "no_show", _ago(1)),
        (2, "appt-b", "reminder", _ago(20)),
    ]
    chosen, _ = _resolve([first, second], sent, upcoming=["appt-b"])
    assert chosen is second


def test_shared_number_ignores_reminders_older_than_the_confirm_window() -> None:
    first, second = _chart("pat-a", 1), _chart("pat-b", 2)
    sent = [
        (1, "", "direct", _ago(1)),
        (2, "appt-b", "reminder", _ago(24 * 365)),
    ]
    chosen, _ = _resolve([first, second], sent, upcoming=["appt-b"])
    assert chosen is first  # most recent text wins; the stale reminder does not


def test_shared_number_without_sent_records_keeps_the_old_first_match() -> None:
    first, second = _chart("pat-a", 1), _chart("pat-b", 2)
    with patch(f"{_MOD}.load_config") as mock_load:
        chosen, _ = _resolve([first, second], sent=[])
    assert chosen is first
    mock_load.assert_not_called()


def test_single_chart_is_unchanged_and_reads_no_sent_records() -> None:
    only = _chart("pat-a", 1)
    chosen, md = _resolve([only], sent=[(9, "x", "reminder", _ago(1))])
    assert chosen is only
    md.objects.filter.assert_not_called()


def test_non_matching_charts_are_not_candidates() -> None:
    """A suffix hit whose number normalizes differently is not a sharer."""
    other = _chart("pat-x", 9, value="+449995551234")
    only = _chart("pat-a", 1)
    chosen, md = _resolve([other, only], sent=[])
    assert chosen is only
    md.objects.filter.assert_not_called()


def test_y_confirm_confirms_the_texted_charts_appointment() -> None:
    first, second = _chart("pat-a", 1), _chart("pat-b", 2)
    appts = {"pat-a": MagicMock(id="appt-a"), "pat-b": MagicMock(id="appt-b")}
    sent = [
        (2, "appt-b", "reminder", _ago(2)),
        (1, "appt-a", "reminder", _ago(30)),
    ]
    api = _signed_api("Body=Y&From=%2B14155551234&MessageSid=SM1")
    with patch(f"{_MOD}.Patient") as mp, \
         patch(f"{_MOD}.NotificationDelivery") as md, \
         patch(f"{_MOD}.AppointmentModel") as ma, \
         patch.object(api, "_nearest_upcoming_appointment",
                      side_effect=lambda p: appts[p.id]), \
         patch(f"{_MOD}.Appointment") as mock_effect, \
         patch(f"{_MOD}.log_inbound_response") as mock_log:
        _wire(mp, md, ma, [first, second], sent, upcoming=["appt-a", "appt-b"])
        md.objects.filter.return_value.exists.return_value = True
        api.inbound()

    mock_effect.assert_called_once_with(instance_id="appt-b")
    assert mock_log.call_args.kwargs["patient_id"] == "pat-b"
    assert mock_log.call_args.kwargs["status"] == "confirmed"


def test_other_reply_task_lands_on_the_texted_chart() -> None:
    first, second = _chart("pat-a", 1), _chart("pat-b", 2)
    sent = [(2, "appt-b", "reminder", _ago(2))]
    api = _signed_api("Body=running+late&From=%2B14155551234&MessageSid=SM2")
    with patch(f"{_MOD}.Patient") as mp, \
         patch(f"{_MOD}.NotificationDelivery") as md, \
         patch(f"{_MOD}.AppointmentModel") as ma, \
         patch(f"{_MOD}.load_config",
               return_value=CampaignConfig(other_reply_task_enabled=True)), \
         patch.object(api, "_nearest_upcoming_appointment", return_value=None), \
         patch.object(api, "_decline_task_due", return_value=None), \
         patch(f"{_MOD}.AddTask") as mock_task, \
         patch(f"{_MOD}.log_inbound_response"):
        _wire(mp, md, ma, [first, second], sent, upcoming=["appt-b"])
        api.inbound()

    assert mock_task.call_args.kwargs["patient_id"] == "pat-b"
