"""Tests for CandidSubmitAPI: delayed claim submission via SimpleAPI."""

from unittest.mock import MagicMock, patch

import requests
from canvas_sdk.v1.data.claim import ClaimQueues

from candid.api.submit import CandidSubmitAPI, _standalone_service_line

from tests.conftest import MOCK_SECRETS


def _build_handler(claim: MagicMock | None, body: dict | None = None) -> CandidSubmitAPI:
    handler = CandidSubmitAPI.__new__(CandidSubmitAPI)
    handler.secrets = MOCK_SECRETS
    handler.environment = {"INSTALLATION_TIME_ZONE": "US/Central"}
    handler.request = MagicMock()
    handler.request.json.return_value = (
        {"claim_id": "claim-1"} if body is None else body
    )
    return handler


def _claim_in_submission_queue() -> MagicMock:
    claim = MagicMock()
    claim.id = "claim-1"
    claim.current_queue.queue_sort_ordering = ClaimQueues.QUEUED_FOR_SUBMISSION
    claim.current_queue.name = "QueuedForSubmission"
    return claim


# ---------------------------------------------------------------------------
# Grace-period skip
# ---------------------------------------------------------------------------


def test_submit_skips_when_claim_no_longer_in_submission_queue() -> None:
    """If the claim moved out of QueuedForSubmission during the grace period, return []."""
    claim = MagicMock()
    claim.id = "claim-1"
    claim.current_queue.queue_sort_ordering = ClaimQueues.NEEDS_CODING_REVIEW
    claim.current_queue.name = "NeedsCodingReview"

    with (
        patch("candid.api.submit.Claim") as MockClaim,
        patch("candid.api.submit.CandidClient") as MC,
        patch("candid.api.submit.build_split_payloads") as mock_build,
    ):
        MockClaim.objects.filter.return_value.first.return_value = claim
        handler = _build_handler(claim)

        result = handler.post()

        assert result == []
        # Should never reach the build/submit code path
        mock_build.assert_not_called()
        MC.from_secrets.assert_not_called()


def test_submit_returns_empty_when_claim_not_found() -> None:
    with (
        patch("candid.api.submit.Claim") as MockClaim,
        patch("candid.api.submit.CandidClient") as MC,
    ):
        MockClaim.objects.filter.return_value.first.return_value = None
        handler = _build_handler(None)

        result = handler.post()

        assert result == []
        MC.from_secrets.assert_not_called()


def test_submit_returns_empty_when_claim_id_missing() -> None:
    with patch("candid.api.submit.CandidClient") as MC:
        handler = _build_handler(None, body={})

        result = handler.post()

        assert result == []
        MC.from_secrets.assert_not_called()


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def test_submit_validation_errors_route_to_failure_handler() -> None:
    """build_split_payloads returning errors → handle_submit_failure (no Candid call)."""
    claim = _claim_in_submission_queue()

    with (
        patch("candid.api.submit.Claim") as MockClaim,
        patch("candid.api.submit.CandidClient") as MC,
        patch("candid.api.submit.build_split_payloads") as mock_build,
        patch("candid.api.submit.handle_submit_failure") as mock_failure,
        patch("candid.api.submit.handle_submit_success") as mock_success,
        patch("candid.api.submit.notify_claim_updated"),
    ):
        MockClaim.objects.filter.return_value.first.return_value = claim
        mock_build.return_value = [({}, ["Patient is missing", "DOB is missing"])]
        mock_failure.return_value = ["failure-effect"]

        handler = _build_handler(claim)
        result = handler.post()

        assert result[0] == "failure-effect"
        mock_failure.assert_called_once()
        message = mock_failure.call_args[0][1]
        assert "Patient is missing" in message
        assert "DOB is missing" in message
        mock_success.assert_not_called()
        # No Candid HTTP call should be made
        MC.from_secrets.assert_not_called()


# ---------------------------------------------------------------------------
# Successful submission
# ---------------------------------------------------------------------------


def test_submit_success_for_single_payload() -> None:
    claim = _claim_in_submission_queue()
    payload = {"external_id": "canvas:claim-1"}

    with (
        patch("candid.api.submit.Claim") as MockClaim,
        patch("candid.api.submit.CandidClient") as MC,
        patch("candid.api.submit.build_split_payloads") as mock_build,
        patch("candid.api.submit.handle_submit_success") as mock_success,
        patch("candid.api.submit.handle_submit_failure") as mock_failure,
        patch("candid.api.submit.notify_claim_updated"),
    ):
        MockClaim.objects.filter.return_value.first.return_value = claim
        mock_build.return_value = [(payload, [])]
        client = MC.from_secrets.return_value
        client.submit_claim.return_value = (True, "encounter-1")
        mock_success.return_value = ["success-effect"]

        handler = _build_handler(claim)
        result = handler.post()

        assert result[0] == "success-effect"
        client.submit_claim.assert_called_once_with(payload)
        encounter_records = mock_success.call_args[0][1]
        assert len(encounter_records) == 1
        assert encounter_records[0]["candid_encounter_id"] == "encounter-1"
        assert encounter_records[0]["split"] == 1
        mock_failure.assert_not_called()


def test_submit_success_for_multiple_splits() -> None:
    """All splits succeed → handle_submit_success with N encounter records."""
    claim = _claim_in_submission_queue()
    payloads = [
        ({"external_id": "canvas:claim-1-1"}, []),
        ({"external_id": "canvas:claim-1-2"}, []),
        ({"external_id": "canvas:claim-1-3"}, []),
    ]

    with (
        patch("candid.api.submit.Claim") as MockClaim,
        patch("candid.api.submit.CandidClient") as MC,
        patch("candid.api.submit.build_split_payloads") as mock_build,
        patch("candid.api.submit.handle_submit_success") as mock_success,
        patch("candid.api.submit.notify_claim_updated"),
    ):
        MockClaim.objects.filter.return_value.first.return_value = claim
        mock_build.return_value = payloads
        client = MC.from_secrets.return_value
        client.submit_claim.side_effect = [
            (True, "enc-a"),
            (True, "enc-b"),
            (True, "enc-c"),
        ]
        mock_success.return_value = []

        handler = _build_handler(claim)
        handler.post()

        assert client.submit_claim.call_count == 3
        encounter_records = mock_success.call_args[0][1]
        assert [r["candid_encounter_id"] for r in encounter_records] == [
            "enc-a", "enc-b", "enc-c"
        ]
        assert mock_success.call_args[0][3] == 3  # total_splits


def test_submit_aborts_on_mid_split_failure() -> None:
    """If split 2 of 3 is rejected by Candid, handler short-circuits to failure."""
    claim = _claim_in_submission_queue()
    payloads = [
        ({"external_id": "canvas:claim-1-1"}, []),
        ({"external_id": "canvas:claim-1-2"}, []),
        ({"external_id": "canvas:claim-1-3"}, []),
    ]

    with (
        patch("candid.api.submit.Claim") as MockClaim,
        patch("candid.api.submit.CandidClient") as MC,
        patch("candid.api.submit.build_split_payloads") as mock_build,
        patch("candid.api.submit.handle_submit_failure") as mock_failure,
        patch("candid.api.submit.handle_submit_success") as mock_success,
        patch("candid.api.submit.notify_claim_updated"),
    ):
        MockClaim.objects.filter.return_value.first.return_value = claim
        mock_build.return_value = payloads
        client = MC.from_secrets.return_value
        client.submit_claim.side_effect = [
            (True, "enc-a"),
            (False, "<400 ValidationError> patient.zip missing"),
            (True, "enc-c"),  # should never be reached
        ]
        mock_failure.return_value = ["failure-effect"]

        handler = _build_handler(claim)
        result = handler.post()

        assert result[0] == "failure-effect"
        # Stopped after the second submit
        assert client.submit_claim.call_count == 2
        mock_success.assert_not_called()
        message = mock_failure.call_args[0][1]
        assert "split 2/3" in message
        assert "patient.zip missing" in message


def test_submit_handles_exception_during_submit_call() -> None:
    """If submit_claim raises, handler routes to handle_submit_failure."""
    claim = _claim_in_submission_queue()

    with (
        patch("candid.api.submit.Claim") as MockClaim,
        patch("candid.api.submit.CandidClient") as MC,
        patch("candid.api.submit.build_split_payloads") as mock_build,
        patch("candid.api.submit.handle_submit_failure") as mock_failure,
        patch("candid.api.submit.notify_claim_updated"),
    ):
        MockClaim.objects.filter.return_value.first.return_value = claim
        mock_build.return_value = [({"external_id": "canvas:claim-1"}, [])]
        client = MC.from_secrets.return_value
        client.submit_claim.side_effect = RuntimeError("network down")
        mock_failure.return_value = ["failure-effect"]

        handler = _build_handler(claim)
        result = handler.post()

        assert result[0] == "failure-effect"
        message = mock_failure.call_args[0][1]
        assert "network down" in message


# ---------------------------------------------------------------------------
# Resubmission: replace service lines on duplicate external_id
# ---------------------------------------------------------------------------


def test_resubmit_deletes_old_and_creates_new_service_lines() -> None:
    """On EncounterExternalIdUniquenessError, PATCH the encounter, then delete
    every existing service line and POST the current ones to /service-lines/v2
    in note order, mapping diagnosis_pointers to the encounter's diagnosis_ids."""
    claim = _claim_in_submission_queue()
    payload = {
        "external_id": "canvas:claim-1",
        "diagnoses": [
            {"code": "E11.9", "code_type": "ABK"},
            {"code": "I10", "code_type": "ABF"},
        ],
        "service_lines": [
            {
                "procedure_code": "G0019",
                "units": "UN",
                "quantity": "1",
                "charge_amount_cents": "6000",
                "diagnosis_pointers": [0],
            },
            {
                "procedure_code": "G0022",
                "units": "UN",
                "quantity": "1",
                "charge_amount_cents": "3000",
                "diagnosis_pointers": [0, 1],
            },
        ],
    }

    with (
        patch("candid.api.submit.Claim") as MockClaim,
        patch("candid.api.submit.CandidClient") as MC,
        patch("candid.api.submit.build_split_payloads") as mock_build,
        patch("candid.api.submit.handle_submit_success") as mock_success,
        patch("candid.api.submit.handle_submit_failure") as mock_failure,
        patch("candid.api.submit.notify_claim_updated"),
    ):
        MockClaim.objects.filter.return_value.first.return_value = claim
        mock_build.return_value = [(payload, [])]
        client = MC.from_secrets.return_value
        client.submit_claim.return_value = (
            False,
            "<422 EncounterExternalIdUniquenessError>",
        )
        client.find_encounter_by_external_id.return_value = "enc-1"
        client.update_claim.return_value = (True, "enc-1")
        client.get_encounter.return_value = {
            "claims": [
                {
                    "claim_id": "candid-claim-1",
                    "diagnoses": [
                        {"diagnosis_id": "dx-e11", "code": "E11.9"},
                        {"diagnosis_id": "dx-i10", "code": "I10"},
                    ],
                    "service_lines": [
                        {"service_line_id": "old-sl-1"},
                        {"service_line_id": "old-sl-2"},
                    ],
                }
            ]
        }
        client.delete_service_line.return_value = (True, "ok")
        client.create_service_line.return_value = (True, "new-sl")
        mock_success.return_value = ["success-effect"]

        handler = _build_handler(claim)
        result = handler.post()

        assert result[0] == "success-effect"
        mock_failure.assert_not_called()
        # Every existing line deleted
        deleted = sorted(c.args[0] for c in client.delete_service_line.call_args_list)
        assert deleted == ["old-sl-1", "old-sl-2"]
        # New lines created in note order, each carrying the Candid claim_id
        created = [c.args[0] for c in client.create_service_line.call_args_list]
        assert [c["procedure_code"] for c in created] == ["G0019", "G0022"]
        assert all(c["claim_id"] == "candid-claim-1" for c in created)
        # diagnosis_pointers translated to Candid diagnosis_ids; charge coerced to int
        assert created[0]["diagnosis_id_zero"] == "dx-e11"
        assert "diagnosis_id_one" not in created[0]
        assert created[0]["charge_amount_cents"] == 6000
        assert created[1]["diagnosis_id_zero"] == "dx-e11"
        assert created[1]["diagnosis_id_one"] == "dx-i10"
        # the encounter-only integer pointers never reach the standalone endpoint
        assert all("diagnosis_pointers" not in c for c in created)


def test_replace_service_lines_skips_when_encounter_has_no_claim_id() -> None:
    """If the fetched encounter has no claim_id, neither delete nor create runs."""
    client = MagicMock()
    client.get_encounter.return_value = {"claims": [{"service_lines": []}]}

    CandidSubmitAPI._replace_service_lines(
        client, "enc-1", {"service_lines": [{"procedure_code": "G0019"}]}
    )

    client.delete_service_line.assert_not_called()
    client.create_service_line.assert_not_called()


def test_replace_service_lines_handles_encounter_fetch_failure() -> None:
    """A failed encounter fetch is logged and swallowed — no delete/create."""
    client = MagicMock()
    client.get_encounter.side_effect = requests.RequestException("boom")

    CandidSubmitAPI._replace_service_lines(client, "enc-1", {"service_lines": []})

    client.delete_service_line.assert_not_called()
    client.create_service_line.assert_not_called()


def test_standalone_service_line_maps_pointers_and_coerces_charge() -> None:
    """diagnosis_pointers resolve to diagnosis_id_* via code; charge becomes int."""
    line = {
        "procedure_code": "G0019",
        "units": "UN",
        "quantity": "2",
        "charge_amount_cents": "6000",
        "modifiers": ["95"],
        "external_id": "li-1",
        "diagnosis_pointers": [1, 0],
    }
    note_diagnoses = [{"code": "E11.9"}, {"code": "I10"}]
    code_to_diagnosis_id = {"E11.9": "dx-e11", "I10": "dx-i10"}

    result = _standalone_service_line(line, "claim-1", code_to_diagnosis_id, note_diagnoses)

    assert result["claim_id"] == "claim-1"
    assert result["procedure_code"] == "G0019"
    assert result["quantity"] == "2"
    assert result["charge_amount_cents"] == 6000
    assert result["modifiers"] == ["95"]
    assert result["external_id"] == "li-1"
    # pointers [1, 0] -> codes [I10, E11.9] -> ids, in that order
    assert result["diagnosis_id_zero"] == "dx-i10"
    assert result["diagnosis_id_one"] == "dx-e11"
    assert "diagnosis_id_two" not in result
    assert "diagnosis_pointers" not in result


def test_standalone_service_line_skips_unmatched_diagnosis_codes() -> None:
    """A pointer whose code isn't on the encounter is dropped, not sent as null."""
    line = {"procedure_code": "G0022", "diagnosis_pointers": [0, 1]}
    note_diagnoses = [{"code": "E11.9"}, {"code": "Z00.00"}]
    code_to_diagnosis_id = {"E11.9": "dx-e11"}  # Z00.00 not on the encounter

    result = _standalone_service_line(line, "claim-1", code_to_diagnosis_id, note_diagnoses)

    assert result["diagnosis_id_zero"] == "dx-e11"
    assert "diagnosis_id_one" not in result
    # required fields still defaulted
    assert result["units"] == "UN"
    assert result["quantity"] == "1"


# ---------------------------------------------------------------------------
# authenticate: %2C-decoding mirrors the encoding in schedule_async_post
# ---------------------------------------------------------------------------


def test_authenticate_accepts_comma_encoded_authorization() -> None:
    """The sender %2C-encodes commas; authenticate decodes before comparison.

    Regression for canvas-plugins#1709 — see candid.effect_helpers.schedule_async_post.
    """
    handler = CandidSubmitAPI.__new__(CandidSubmitAPI)
    handler.secrets = {"CANDID_CLIENT_SECRET": "abc,def,ghi"}
    credentials = MagicMock()
    credentials.key = "abc%2Cdef%2Cghi"

    assert handler.authenticate(credentials) is True


def test_authenticate_rejects_mismatched_key() -> None:
    handler = CandidSubmitAPI.__new__(CandidSubmitAPI)
    handler.secrets = {"CANDID_CLIENT_SECRET": "abc,def,ghi"}
    credentials = MagicMock()
    credentials.key = "wrong"

    assert handler.authenticate(credentials) is False
