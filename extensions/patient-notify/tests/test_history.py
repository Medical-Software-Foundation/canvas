"""Tests for notification history logging."""
import json

from pytest_mock import MockerFixture

from patient_notify.services.delivery import DeliveryResult
from patient_notify.services.history import CACHE_TTL, get_patient_log, log_delivery_to_cache


def test_log_delivery_success(mocker: MockerFixture) -> None:
    """Test logging a successful delivery with channel info."""
    mock_cache = mocker.Mock()
    mock_cache.get.return_value = "[]"
    mocker.patch("patient_notify.services.history.get_cache", return_value=mock_cache)

    results = [DeliveryResult(success=True, channel="sms", message_id="SM123")]
    log_delivery_to_cache("appt-1", "patient-1", "confirmation", results)

    assert mock_cache.set.call_count == 2

    patient_call = [c for c in mock_cache.set.call_args_list if "cr:log:patient-1" in str(c)][0]
    entries = json.loads(patient_call[0][1])
    assert len(entries) == 1
    assert entries[0]["status"] == "delivered"
    assert entries[0]["channel"] == "sms"
    assert entries[0]["error"] is None


def test_log_delivery_failure(mocker: MockerFixture) -> None:
    """Test logging a failed delivery with error info."""
    mock_cache = mocker.Mock()
    mock_cache.get.return_value = "[]"
    mocker.patch("patient_notify.services.history.get_cache", return_value=mock_cache)

    results = [DeliveryResult(success=False, channel="email", error="timeout")]
    log_delivery_to_cache("appt-1", "patient-1", "reminder", results)

    patient_call = [c for c in mock_cache.set.call_args_list if "cr:log:patient-1" in str(c)][0]
    entries = json.loads(patient_call[0][1])
    assert entries[0]["status"] == "failed"
    assert entries[0]["channel"] == "email"
    assert entries[0]["error"] == "timeout"


def test_log_delivery_multiple_results(mocker: MockerFixture) -> None:
    """Test logging multiple delivery results creates multiple entries."""
    mock_cache = mocker.Mock()
    mock_cache.get.return_value = "[]"
    mocker.patch("patient_notify.services.history.get_cache", return_value=mock_cache)

    results = [
        DeliveryResult(success=True, channel="sms", message_id="SM123"),
        DeliveryResult(success=True, channel="email", message_id="msg-abc"),
    ]
    log_delivery_to_cache("appt-1", "patient-1", "confirmation", results)

    patient_call = [c for c in mock_cache.set.call_args_list if "cr:log:patient-1" in str(c)][0]
    entries = json.loads(patient_call[0][1])
    assert len(entries) == 2
    assert entries[0]["channel"] == "sms"
    assert entries[1]["channel"] == "email"


def test_log_delivery_truncates_patient_log(mocker: MockerFixture) -> None:
    """Test patient log keeps only last 100 entries."""
    mock_cache = mocker.Mock()
    existing = json.dumps([{"i": i} for i in range(100)])
    mock_cache.get.return_value = existing
    mocker.patch("patient_notify.services.history.get_cache", return_value=mock_cache)

    results = [DeliveryResult(success=True, channel="portal")]
    log_delivery_to_cache("appt-1", "patient-1", "noshow", results)

    patient_call = [c for c in mock_cache.set.call_args_list if "cr:log:patient-1" in str(c)][0]
    entries = json.loads(patient_call[0][1])
    assert len(entries) == 100


def test_log_delivery_updates_global_log(mocker: MockerFixture) -> None:
    """Test that global log is also updated."""
    mock_cache = mocker.Mock()
    mock_cache.get.return_value = "[]"
    mocker.patch("patient_notify.services.history.get_cache", return_value=mock_cache)

    results = [DeliveryResult(success=True, channel="task")]
    log_delivery_to_cache("appt-1", "patient-1", "cancellation", results)

    global_call = [c for c in mock_cache.set.call_args_list if "cr:global_log" in str(c)][0]
    entries = json.loads(global_call[0][1])
    assert len(entries) == 1
    assert entries[0]["campaign_type"] == "cancellation"
    assert entries[0]["channel"] == "task"


def test_log_delivery_uses_correct_ttl(mocker: MockerFixture) -> None:
    """Test that cache entries use 14-day TTL."""
    mock_cache = mocker.Mock()
    mock_cache.get.return_value = "[]"
    mocker.patch("patient_notify.services.history.get_cache", return_value=mock_cache)

    results = [DeliveryResult(success=True, channel="sms")]
    log_delivery_to_cache("appt-1", "patient-1", "test", results)

    for call in mock_cache.set.call_args_list:
        assert call[1]["timeout_seconds"] == CACHE_TTL


def test_log_delivery_empty_results_skips(mocker: MockerFixture) -> None:
    """Test that empty results list does not write to cache."""
    mock_cache = mocker.Mock()
    mocker.patch("patient_notify.services.history.get_cache", return_value=mock_cache)

    log_delivery_to_cache("appt-1", "patient-1", "test", [])

    mock_cache.set.assert_not_called()


def test_log_delivery_includes_error_code(mocker: MockerFixture) -> None:
    """Test that error_code from DeliveryResult is included in log entries."""
    mock_cache = mocker.Mock()
    mock_cache.get.return_value = "[]"
    mocker.patch("patient_notify.services.history.get_cache", return_value=mock_cache)

    results = [DeliveryResult(success=False, channel="sms", error="opted out", error_code=21610)]
    log_delivery_to_cache("appt-1", "patient-1", "confirmation", results)

    patient_call = [c for c in mock_cache.set.call_args_list if "cr:log:patient-1" in str(c)][0]
    entries = json.loads(patient_call[0][1])
    assert entries[0]["error_code"] == 21610


def test_log_delivery_error_code_none_when_absent(mocker: MockerFixture) -> None:
    """Test error_code is None when not set on DeliveryResult."""
    mock_cache = mocker.Mock()
    mock_cache.get.return_value = "[]"
    mocker.patch("patient_notify.services.history.get_cache", return_value=mock_cache)

    results = [DeliveryResult(success=True, channel="sms")]
    log_delivery_to_cache("appt-1", "patient-1", "confirmation", results)

    patient_call = [c for c in mock_cache.set.call_args_list if "cr:log:patient-1" in str(c)][0]
    entries = json.loads(patient_call[0][1])
    assert entries[0]["error_code"] is None


def test_get_patient_log(mocker: MockerFixture) -> None:
    """Test get_patient_log reads and parses cache entries."""
    mock_cache = mocker.Mock()
    mock_cache.get.return_value = json.dumps([{"channel": "sms", "status": "delivered"}])
    mocker.patch("patient_notify.services.history.get_cache", return_value=mock_cache)

    entries = get_patient_log("patient-1")

    assert len(entries) == 1
    assert entries[0]["channel"] == "sms"
    mock_cache.get.assert_called_once_with("cr:log:patient-1", default="[]")
