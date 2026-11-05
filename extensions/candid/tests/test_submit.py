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
# Resubmission: reconcile service lines against the claim's line items
# ---------------------------------------------------------------------------


def test_resubmit_reconciles_service_lines() -> None:
    """On EncounterExternalIdUniquenessError, PATCH the encounter, then reconcile
    its service lines against the claim's current line items, keyed on
    external_id: matched lines are PATCHed in place, lines dropped from the
    claim are deleted, and lines new on the claim are POSTed.

    Note codes are dotless (E119, as Canvas stores them); Candid returns them
    dotted (E11.9) under the encounter-level diagnoses array — the mapping must
    bridge both."""
    claim = _claim_in_submission_queue()
    payload = {
        "external_id": "canvas:claim-1",
        "diagnoses": [
            {"code": "E119", "code_type": "ABK"},
            {"code": "I10", "code_type": "ABF"},
        ],
        "service_lines": [
            {
                "procedure_code": "G0019",
                "units": "UN",
                "quantity": "1",
                "charge_amount_cents": "6000",
                "external_id": "li-1",
                "diagnosis_pointers": [0],
            },
            {
                "procedure_code": "G0022",
                "units": "UN",
                "quantity": "1",
                "charge_amount_cents": "3000",
                "external_id": "li-2",
                "diagnosis_pointers": [0, 1],
            },
            {
                "procedure_code": "G0023",
                "units": "UN",
                "quantity": "1",
                "charge_amount_cents": "4500",
                "external_id": "li-3",
                "diagnosis_pointers": [1],
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
            "encounter_id": "enc-1",
            "diagnoses": [
                {"diagnosis_id": "dx-e11", "code": "E11.9"},
                {"diagnosis_id": "dx-i10", "code": "I10"},
            ],
            "claims": [
                {
                    "claim_id": "candid-claim-1",
                    "service_lines": [
                        {"service_line_id": "sl-1", "external_id": "li-1"},
                        {"service_line_id": "sl-2", "external_id": "li-2"},
                        {"service_line_id": "sl-old", "external_id": "li-old"},
                    ],
                }
            ],
        }
        client.update_service_line.return_value = (True, "ok")
        client.delete_service_line.return_value = (True, "ok")
        client.create_service_line.return_value = (True, "new-sl")
        mock_success.return_value = ["success-effect"]

        handler = _build_handler(claim)
        result = handler.post()

        assert result[0] == "success-effect"
        mock_failure.assert_not_called()

        # Lines still on the claim are PATCHed in place (matched by external_id),
        # never deleted + recreated.
        updates = {
            c.args[0]: c.args[1] for c in client.update_service_line.call_args_list
        }
        assert sorted(updates) == ["sl-1", "sl-2"]
        # update payload omits claim_id and external_id, maps diagnoses, coerces charge
        assert "claim_id" not in updates["sl-1"]
        assert "external_id" not in updates["sl-1"]
        assert updates["sl-1"]["procedure_code"] == "G0019"
        assert updates["sl-1"]["charge_amount_cents"] == 6000
        assert updates["sl-1"]["diagnosis_id_zero"] == "dx-e11"
        assert "diagnosis_id_one" not in updates["sl-1"]
        assert updates["sl-2"]["diagnosis_id_zero"] == "dx-e11"
        assert updates["sl-2"]["diagnosis_id_one"] == "dx-i10"

        # The line new on the claim is POSTed with claim_id + external_id.
        created = [c.args[0] for c in client.create_service_line.call_args_list]
        assert len(created) == 1
        assert created[0]["procedure_code"] == "G0023"
        assert created[0]["claim_id"] == "candid-claim-1"
        assert created[0]["external_id"] == "li-3"
        assert created[0]["diagnosis_id_zero"] == "dx-i10"

        # The line no longer on the claim is deleted; matched lines are not.
        deleted = [c.args[0] for c in client.delete_service_line.call_args_list]
        assert deleted == ["sl-old"]

        # The encounter-only integer pointers never reach the standalone endpoint.
        assert all(
            "diagnosis_pointers" not in p for p in [*updates.values(), *created]
        )

        # Every claim diagnosis already existed, so none is created; the
        # encounter's diagnosis list is set to the claim's, in rank order.
        client.create_diagnosis.assert_not_called()
        assert client.update_claim.call_args_list[-1].args == (
            "enc-1",
            {"diagnosis_ids": ["dx-e11", "dx-i10"]},
        )


def test_reconcile_service_lines_skips_when_encounter_has_no_claim_id() -> None:
    """If the fetched encounter has no claim_id, nothing is changed and an error is returned."""
    client = MagicMock()
    client.get_encounter.return_value = {"claims": [{"service_lines": []}]}

    errors = CandidSubmitAPI._reconcile_service_lines(
        client, "enc-1", {"service_lines": [{"procedure_code": "G0019"}]}
    )

    assert errors == ["encounter enc-1 has no claim_id"]

    client.update_service_line.assert_not_called()
    client.create_service_line.assert_not_called()
    client.delete_service_line.assert_not_called()


def test_reconcile_service_lines_handles_encounter_fetch_failure() -> None:
    """A failed encounter fetch makes no changes and returns an error."""
    client = MagicMock()
    client.get_encounter.side_effect = requests.RequestException("boom")

    errors = CandidSubmitAPI._reconcile_service_lines(
        client, "enc-1", {"service_lines": []}
    )

    assert len(errors) == 1
    assert "could not fetch encounter enc-1" in errors[0]

    client.update_service_line.assert_not_called()
    client.create_service_line.assert_not_called()
    client.delete_service_line.assert_not_called()


# PLUGIN-573: a CPT change plus a new diagnosis used to 422 the new line and
# then delete the old one, leaving the Candid encounter with no service lines.


def _cpt_change_payload() -> dict:
    """Claim after a CPT change (li-old removed, li-new added) and a new J449."""
    return {
        "external_id": "canvas:claim-1",
        "diagnoses": [
            {"code": "E119", "code_type": "ABK"},
            {"code": "J449", "code_type": "ABF"},
        ],
        "service_lines": [
            {
                "procedure_code": "99205",
                "units": "UN",
                "quantity": "1",
                "charge_amount_cents": "30000",
                "external_id": "li-new",
                "diagnosis_pointers": [0, 1],
            },
        ],
    }


def _cpt_change_client() -> MagicMock:
    """Encounter as first submitted: one G0423 line, only E11.9 on file."""
    client = MagicMock()
    client.get_encounter.return_value = {
        "encounter_id": "enc-1",
        "diagnoses": [{"diagnosis_id": "dx-e11", "code": "E11.9"}],
        "claims": [
            {
                "claim_id": "candid-claim-1",
                "service_lines": [
                    {"service_line_id": "sl-old", "external_id": "li-old"},
                ],
            }
        ],
    }
    client.create_diagnosis.return_value = (True, "dx-j449")
    client.create_service_line.return_value = (True, "sl-new")
    client.update_service_line.return_value = (True, "ok")
    client.delete_service_line.return_value = (True, "ok")
    client.update_claim.return_value = (True, "enc-1")
    return client


def test_reconcile_creates_new_diagnosis_and_links_it_before_replacing_line() -> None:
    client = _cpt_change_client()

    errors = CandidSubmitAPI._reconcile_service_lines(
        client, "enc-1", _cpt_change_payload()
    )

    assert errors == []
    client.create_diagnosis.assert_called_once_with("enc-1", "J449", "ABF")
    created = client.create_service_line.call_args.args[0]
    assert created["procedure_code"] == "99205"
    assert created["diagnosis_id_zero"] == "dx-e11"
    assert created["diagnosis_id_one"] == "dx-j449"
    client.delete_service_line.assert_called_once_with("sl-old")
    client.update_claim.assert_called_once_with(
        "enc-1", {"diagnosis_ids": ["dx-e11", "dx-j449"]}
    )


def test_reconcile_keeps_old_line_when_new_line_create_fails() -> None:
    client = _cpt_change_client()
    client.create_service_line.return_value = (
        False,
        (
            "<422 HttpRequestValidationError> diagnoses: Service lines must have "
            "at least one diagnosis code linked."
        ),
    )

    errors = CandidSubmitAPI._reconcile_service_lines(
        client, "enc-1", _cpt_change_payload()
    )

    assert len(errors) == 1
    assert errors[0].startswith("create 99205 line: <422")
    client.delete_service_line.assert_not_called()
    client.update_claim.assert_not_called()


def test_reconcile_keeps_old_line_on_409_external_id_conflict() -> None:
    client = _cpt_change_client()
    client.create_service_line.return_value = (False, "<409 EntityConflictError>")

    errors = CandidSubmitAPI._reconcile_service_lines(
        client, "enc-1", _cpt_change_payload()
    )

    assert errors == ["create 99205 line: <409 EntityConflictError>"]
    client.delete_service_line.assert_not_called()


def test_reconcile_skips_deletes_when_a_line_update_fails() -> None:
    client = _cpt_change_client()
    payload = _cpt_change_payload()
    # A second, persistent line that fails to update.
    payload["service_lines"].append(
        {"procedure_code": "93000", "external_id": "li-keep", "diagnosis_pointers": [0]}
    )
    client.get_encounter.return_value["claims"][0]["service_lines"].append(
        {"service_line_id": "sl-keep", "external_id": "li-keep"}
    )
    client.update_service_line.return_value = (False, "<422 Bad>")

    errors = CandidSubmitAPI._reconcile_service_lines(client, "enc-1", payload)

    assert errors == ["update 93000 line sl-keep: <422 Bad>"]
    client.delete_service_line.assert_not_called()


def test_reconcile_stops_before_touching_lines_when_diagnosis_create_fails() -> None:
    client = _cpt_change_client()
    client.create_diagnosis.return_value = (False, "<422 Bad code>")

    errors = CandidSubmitAPI._reconcile_service_lines(
        client, "enc-1", _cpt_change_payload()
    )

    assert errors == ["diagnosis J449: <422 Bad code>"]
    client.create_service_line.assert_not_called()
    client.update_service_line.assert_not_called()
    client.delete_service_line.assert_not_called()
    client.update_claim.assert_not_called()


def test_reconcile_treats_diagnosis_create_without_id_as_failure() -> None:
    client = _cpt_change_client()
    client.create_diagnosis.return_value = (True, "")

    errors = CandidSubmitAPI._reconcile_service_lines(
        client, "enc-1", _cpt_change_payload()
    )

    assert errors == ["diagnosis J449: Candid returned no diagnosis_id"]
    client.create_service_line.assert_not_called()
    client.delete_service_line.assert_not_called()


def test_reconcile_reports_delete_failure() -> None:
    client = _cpt_change_client()
    client.delete_service_line.return_value = (False, "<500 Oops>")

    errors = CandidSubmitAPI._reconcile_service_lines(
        client, "enc-1", _cpt_change_payload()
    )

    assert errors == ["delete line sl-old: <500 Oops>"]
    client.update_claim.assert_not_called()


def test_reconcile_reports_encounter_diagnosis_update_failure() -> None:
    client = _cpt_change_client()
    client.update_claim.return_value = (False, "<422 Bad ids>")

    errors = CandidSubmitAPI._reconcile_service_lines(
        client, "enc-1", _cpt_change_payload()
    )

    assert errors == ["update encounter diagnoses: <422 Bad ids>"]


def test_resubmit_routes_reconcile_failure_to_failure_handler() -> None:
    """A failed line create must fail the claim, not mark it submitted."""
    claim = _claim_in_submission_queue()

    with (
        patch("candid.api.submit.Claim") as MockClaim,
        patch("candid.api.submit.CandidClient") as MC,
        patch("candid.api.submit.build_split_payloads") as mock_build,
        patch("candid.api.submit.handle_submit_success") as mock_success,
        patch("candid.api.submit.handle_submit_failure") as mock_failure,
        patch("candid.api.submit.notify_claim_updated"),
    ):
        MockClaim.objects.filter.return_value.first.return_value = claim
        mock_build.return_value = [(_cpt_change_payload(), [])]
        client = _cpt_change_client()
        MC.from_secrets.return_value = client
        client.submit_claim.return_value = (
            False,
            "<422 EncounterExternalIdUniquenessError>",
        )
        client.find_encounter_by_external_id.return_value = "enc-1"
        client.create_service_line.return_value = (False, "<422 Rejected>")
        mock_failure.return_value = ["failure-effect"]

        result = _build_handler(claim).post()

        assert result[0] == "failure-effect"
        mock_success.assert_not_called()
        comment = mock_failure.call_args.args[1]
        assert comment.startswith("Candid service line update failed (claim):")
        assert "create 99205 line: <422 Rejected>" in comment
        client.delete_service_line.assert_not_called()


# Review follow-ups: stale diagnosis links, principal code_type, exceptions.


def _two_dx_payload(codes: list[str], pointers: list[int]) -> dict:
    """One persistent line (li-1) on a claim with the given ranked codes."""
    return {
        "external_id": "canvas:claim-1",
        "diagnoses": [
            {"code": c, "code_type": "ABK" if i == 0 else "ABF"}
            for i, c in enumerate(codes)
        ],
        "service_lines": [
            {
                "procedure_code": "99213",
                "external_id": "li-1",
                "diagnosis_pointers": pointers,
            }
        ],
    }


def _linked_line_client() -> MagicMock:
    """Encounter with E11.9 (ABK) and I10 (ABF), one line linked to both."""
    client = MagicMock()
    client.get_encounter.return_value = {
        "encounter_id": "enc-1",
        "diagnoses": [
            {"diagnosis_id": "dx-e11", "code": "E11.9", "code_type": "ABK"},
            {"diagnosis_id": "dx-i10", "code": "I10", "code_type": "ABF"},
        ],
        "claims": [
            {
                "claim_id": "candid-claim-1",
                "service_lines": [
                    {
                        "service_line_id": "sl-1",
                        "external_id": "li-1",
                        "diagnosis_id_zero": "dx-e11",
                        "diagnosis_id_one": "dx-i10",
                    }
                ],
            }
        ],
    }
    client.create_diagnosis.return_value = (True, "dx-new")
    client.update_diagnosis.return_value = (True, "ok")
    client.update_service_line.return_value = (True, "ok")
    client.create_service_line.return_value = (True, "sl-new")
    client.delete_service_line.return_value = (True, "ok")
    client.update_claim.return_value = (True, "enc-1")
    return client


def test_reconcile_clears_stale_diagnosis_slot_on_line_update() -> None:
    """Dropping I10 nulls diagnosis_id_one so the line stops linking it."""
    client = _linked_line_client()

    errors = CandidSubmitAPI._reconcile_service_lines(
        client, "enc-1", _two_dx_payload(["E119"], [0])
    )

    assert errors == []
    update = client.update_service_line.call_args.args[1]
    assert update["diagnosis_id_zero"] == "dx-e11"
    assert update["diagnosis_id_one"] is None
    # Slots the line never held aren't sent.
    assert "diagnosis_id_two" not in update
    client.update_claim.assert_called_once_with("enc-1", {"diagnosis_ids": ["dx-e11"]})


def test_reconcile_does_not_null_slots_when_links_unchanged() -> None:
    client = _linked_line_client()

    CandidSubmitAPI._reconcile_service_lines(
        client, "enc-1", _two_dx_payload(["E119", "I10"], [0, 1])
    )

    update = client.update_service_line.call_args.args[1]
    assert update["diagnosis_id_zero"] == "dx-e11"
    assert update["diagnosis_id_one"] == "dx-i10"
    assert None not in update.values()
    client.update_diagnosis.assert_not_called()


def test_reconcile_swaps_principal_when_rank_order_changes() -> None:
    """I10 moved to rank 1: demote E11.9 to ABF first, then promote I10 to ABK."""
    client = _linked_line_client()

    errors = CandidSubmitAPI._reconcile_service_lines(
        client, "enc-1", _two_dx_payload(["I10", "E119"], [0, 1])
    )

    assert errors == []
    assert [c.args for c in client.update_diagnosis.call_args_list] == [
        ("dx-e11", {"code_type": "ABF"}),
        ("dx-i10", {"code_type": "ABK"}),
    ]
    client.update_claim.assert_called_once_with(
        "enc-1", {"diagnosis_ids": ["dx-i10", "dx-e11"]}
    )


def test_reconcile_new_principal_is_created_as_abk_and_old_one_demoted() -> None:
    """A brand-new rank-1 code is created ABK (undotted, as Canvas stores it)."""
    client = _linked_line_client()

    errors = CandidSubmitAPI._reconcile_service_lines(
        client, "enc-1", _two_dx_payload(["J449", "E119"], [0, 1])
    )

    assert errors == []
    client.create_diagnosis.assert_called_once_with("enc-1", "J449", "ABK")
    # E11.9 demoted; I10 already ABF and dropped from the claim, left alone.
    client.update_diagnosis.assert_called_once_with("dx-e11", {"code_type": "ABF"})


def test_reconcile_stops_before_lines_when_principal_update_fails() -> None:
    client = _linked_line_client()
    client.update_diagnosis.return_value = (False, "<422 Bad>")

    errors = CandidSubmitAPI._reconcile_service_lines(
        client, "enc-1", _two_dx_payload(["I10", "E119"], [0, 1])
    )

    assert errors == ["set diagnosis dx-e11 to ABF: <422 Bad>"]
    # Promotion isn't attempted after a failed demotion, and no line is touched.
    client.update_diagnosis.assert_called_once()
    client.update_service_line.assert_not_called()
    client.delete_service_line.assert_not_called()
    client.update_claim.assert_not_called()


def test_reconcile_retry_after_partial_success_reuses_created_objects() -> None:
    """First attempt created J449 and the new line, then the delete failed.
    The retry sees both on the encounter: it creates nothing again, updates the
    new line in place, and finishes the delete."""
    client = _cpt_change_client()
    client.delete_service_line.return_value = (False, "<500 Oops>")

    first = CandidSubmitAPI._reconcile_service_lines(
        client, "enc-1", _cpt_change_payload()
    )
    assert first == ["delete line sl-old: <500 Oops>"]

    # Encounter state after the partial success.
    encounter = client.get_encounter.return_value
    encounter["diagnoses"].append(
        {"diagnosis_id": "dx-j449", "code": "J44.9", "code_type": "ABF"}
    )
    encounter["claims"][0]["service_lines"].append(
        {
            "service_line_id": "sl-new",
            "external_id": "li-new",
            "diagnosis_id_zero": "dx-e11",
            "diagnosis_id_one": "dx-j449",
        }
    )
    client.reset_mock()
    client.delete_service_line.return_value = (True, "ok")

    second = CandidSubmitAPI._reconcile_service_lines(
        client, "enc-1", _cpt_change_payload()
    )

    assert second == []
    client.create_diagnosis.assert_not_called()
    client.create_service_line.assert_not_called()
    client.update_service_line.assert_called_once()
    assert client.update_service_line.call_args.args[0] == "sl-new"
    client.delete_service_line.assert_called_once_with("sl-old")
    client.update_claim.assert_called_once_with(
        "enc-1", {"diagnosis_ids": ["dx-e11", "dx-j449"]}
    )


def _resubmit_with_reconcile_raising(exc: Exception) -> tuple[MagicMock, MagicMock]:
    claim = _claim_in_submission_queue()
    with (
        patch("candid.api.submit.Claim") as MockClaim,
        patch("candid.api.submit.CandidClient") as MC,
        patch("candid.api.submit.build_split_payloads") as mock_build,
        patch("candid.api.submit.handle_submit_success") as mock_success,
        patch("candid.api.submit.handle_submit_failure") as mock_failure,
        patch("candid.api.submit.notify_claim_updated"),
    ):
        MockClaim.objects.filter.return_value.first.return_value = claim
        mock_build.return_value = [(_cpt_change_payload(), [])]
        client = _cpt_change_client()
        MC.from_secrets.return_value = client
        client.submit_claim.return_value = (
            False,
            "<422 EncounterExternalIdUniquenessError>",
        )
        client.find_encounter_by_external_id.return_value = "enc-1"
        client.create_diagnosis.side_effect = exc
        mock_failure.return_value = ["failure-effect"]

        result = _build_handler(claim).post()

    assert result[0] == "failure-effect"
    return mock_success, mock_failure


def test_resubmit_routes_reconcile_runtime_error_to_failure_handler() -> None:
    """A token fetch RuntimeError mid-reconcile fails the claim with a comment."""
    mock_success, mock_failure = _resubmit_with_reconcile_raising(
        RuntimeError("Could not fetch Candid API token")
    )

    mock_success.assert_not_called()
    comment = mock_failure.call_args.args[1]
    assert comment.startswith("Candid service line update failed (claim):")
    assert "Could not fetch Candid API token" in comment


def test_resubmit_routes_reconcile_value_error_to_failure_handler() -> None:
    """A non-JSON Candid response (ValueError) also fails the claim."""
    mock_success, mock_failure = _resubmit_with_reconcile_raising(
        ValueError("Expecting value")
    )

    mock_success.assert_not_called()
    assert "Expecting value" in mock_failure.call_args.args[1]


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
    # map keys are normalized (dotless), as _reconcile_service_lines builds them
    code_to_diagnosis_id = {"E119": "dx-e11", "I10": "dx-i10"}

    result = _standalone_service_line(line, "claim-1", code_to_diagnosis_id, note_diagnoses)

    assert result["claim_id"] == "claim-1"
    assert result["procedure_code"] == "G0019"
    assert result["quantity"] == "2"
    assert result["charge_amount_cents"] == 6000
    assert result["modifiers"] == ["95"]
    # external_id is preserved so the line can be matched (and PATCHed in place)
    # on a later resubmit
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
    code_to_diagnosis_id = {"E119": "dx-e11"}  # Z0000 not on the encounter

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
