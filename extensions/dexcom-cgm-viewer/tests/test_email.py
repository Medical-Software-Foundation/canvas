"""SendGrid magic-link email helper."""

from unittest.mock import MagicMock, patch

import pytest

from dexcom_cgm_viewer.services.email import (
    EmailDeliveryError,
    patient_email_address,
    send_magic_link_email,
)


def _mock_response(status_code: int, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


def _mock_patient_with_contacts(contacts: list[dict]) -> MagicMock:
    """Build a mock Patient whose ``telecom`` queryset behaves like Django's."""
    rows = [MagicMock(**c) for c in contacts]

    def filter_(system: str) -> MagicMock:
        filtered = [r for r in rows if r.system == system]
        ordered = sorted(filtered, key=lambda r: r.rank)
        qs = MagicMock()
        qs.order_by.return_value.first.return_value = ordered[0] if ordered else None
        return qs

    patient = MagicMock()
    patient.telecom.filter.side_effect = filter_
    return patient


def test_patient_email_returns_lowest_rank_email() -> None:
    patient = _mock_patient_with_contacts([
        {"system": "phone", "value": "555-1212", "rank": 1},
        {"system": "email", "value": "primary@example.com", "rank": 1},
        {"system": "email", "value": "backup@example.com", "rank": 2},
    ])
    assert patient_email_address(patient) == "primary@example.com"


def test_patient_email_returns_none_when_no_email() -> None:
    patient = _mock_patient_with_contacts([
        {"system": "phone", "value": "555-1212", "rank": 1},
    ])
    assert patient_email_address(patient) is None


def test_patient_email_strips_whitespace_and_treats_blank_as_none() -> None:
    patient = _mock_patient_with_contacts([
        {"system": "email", "value": "  ", "rank": 1},
    ])
    assert patient_email_address(patient) is None


def test_send_magic_link_email_posts_with_bearer_and_payload() -> None:
    http = MagicMock()
    http.post.return_value = _mock_response(202)
    result = send_magic_link_email(
        api_key="SG.test-key",
        from_email="noreply@example.com",
        to_email="patient@example.com",
        patient_first_name="Alex",
        link="https://canvas-host.example/plugin-io/api/dexcom_cgm_viewer/connect?token=abc",
        http=http,
    )
    assert result is True
    args, kwargs = http.post.call_args
    # canvas_sdk.utils.http.Http joins the path against the base URL itself.
    assert args[0] == "/v3/mail/send"
    assert kwargs["headers"]["Authorization"] == "Bearer SG.test-key"
    # SDK Http serializes via ``json=``; assert against the dict directly.
    body = kwargs["json"]
    assert body["personalizations"][0]["to"][0]["email"] == "patient@example.com"
    assert body["from"]["email"] == "noreply@example.com"
    text_part = next(c["value"] for c in body["content"] if c["type"] == "text/plain")
    html_part = next(c["value"] for c in body["content"] if c["type"] == "text/html")
    assert "Alex" in text_part
    assert "Connect Dexcom" in html_part


def test_send_magic_link_email_defaults_to_sdk_http_when_unset() -> None:
    """When the caller omits ``http=``, the helper constructs an SDK
    ``canvas_sdk.utils.http.Http`` scoped to SendGrid (REVIEW.md §8)."""
    fake_http = MagicMock()
    fake_http.post.return_value = _mock_response(202)
    with patch("dexcom_cgm_viewer.services.email.Http", return_value=fake_http) as MockHttp:
        send_magic_link_email(
            api_key="k", from_email="from@x", to_email="to@y",
            patient_first_name="Pat", link="https://canvas/connect",
        )
    MockHttp.assert_called_once_with("https://api.sendgrid.com")
    assert fake_http.post.call_args.args[0] == "/v3/mail/send"


def test_send_magic_link_email_validates_inputs() -> None:
    with pytest.raises(ValueError):
        send_magic_link_email(
            api_key="", from_email="x", to_email="y",
            patient_first_name="z", link="https://a/b",
        )
    with pytest.raises(ValueError):
        send_magic_link_email(
            api_key="k", from_email="", to_email="y",
            patient_first_name="z", link="https://a/b",
        )
    with pytest.raises(ValueError):
        send_magic_link_email(
            api_key="k", from_email="x", to_email="",
            patient_first_name="z", link="https://a/b",
        )
    with pytest.raises(ValueError):
        send_magic_link_email(
            api_key="k", from_email="x", to_email="y",
            patient_first_name="z", link="",
        )


def test_send_magic_link_email_falls_back_to_default_greeting() -> None:
    http = MagicMock()
    http.post.return_value = _mock_response(202)
    send_magic_link_email(
        api_key="k", from_email="from@x", to_email="to@y",
        patient_first_name="   ", link="https://canvas/connect",
        http=http,
    )
    body = http.post.call_args.kwargs["json"]
    text_part = next(c["value"] for c in body["content"] if c["type"] == "text/plain")
    assert "Hi there" in text_part


def test_send_magic_link_email_raises_on_4xx_with_details() -> None:
    http = MagicMock()
    http.post.return_value = _mock_response(400, text='{"errors":["unverified sender"]}')
    with pytest.raises(EmailDeliveryError) as excinfo:
        send_magic_link_email(
            api_key="k", from_email="from@x", to_email="to@y",
            patient_first_name="Sam", link="https://canvas/connect",
            http=http,
        )
    assert excinfo.value.status_code == 400
    assert "unverified" in excinfo.value.body
