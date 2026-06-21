"""Tests for the inspector companion-app routes added to AccessOperationsApi:
static serving (/, /main.js, /styles.css), /state, and /poll.
"""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from unittest.mock import MagicMock, patch


def _make_handler(secrets=None, request_body=None, query_params=None):
    from cms_access_fhir_client.api.operations_api import AccessOperationsApi

    handler = AccessOperationsApi.__new__(AccessOperationsApi)
    handler.secrets = secrets or {}
    mock_request = MagicMock()
    mock_request.json.return_value = request_body or {}
    mock_request.query_params.get = lambda key, default=None: (query_params or {}).get(key, default)
    handler.request = mock_request
    return handler


def _make_alignment(track="eCKM", status="aligned", submission_state="", submission_status_url="", poll_attempts=0):
    a = MagicMock()
    a.dbid = 7
    a.track = track
    a.status = status
    a.status_message = ""
    a.submission_state = submission_state
    a.submission_op = ""
    a.alignment_id = "align-x"
    a.poll_attempts = poll_attempts
    a.submission_status_url = submission_status_url
    a.report_result = ""
    a.report_result_at = None
    a.updated_at = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)
    return a


class TestStateRoute:
    def test_requires_patient_id(self):
        handler = _make_handler(query_params={})
        effects = handler.state()
        assert effects[0].status_code == HTTPStatus.BAD_REQUEST

    def test_returns_serialized_alignments(self):
        handler = _make_handler(query_params={"patient_id": "p-1"})
        qs = MagicMock()
        qs.order_by.return_value = [_make_alignment(track="CKM", status="pending")]
        with patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment") as MA:
            MA.objects.filter.return_value = qs
            effects = handler.state()
        body = json.loads(effects[0].content)
        assert body["alignments"][0]["track"] == "CKM"
        assert body["alignments"][0]["status"] == "pending"

    def test_skips_blank_track_orphans_and_dedupes_to_latest_per_track(self):
        handler = _make_handler(query_params={"patient_id": "p-1"})
        # Newest-first: a current CKM=aligned, a superseded older CKM=error, an
        # eCKM=eligible, and a blank-track orphan error row.
        rows = [
            _make_alignment(track="CKM", status="aligned"),
            _make_alignment(track="eCKM", status="eligible"),
            _make_alignment(track="CKM", status="error"),
            _make_alignment(track="", status="error"),
        ]
        qs = MagicMock()
        qs.order_by.return_value = rows
        with patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment") as MA:
            MA.objects.filter.return_value = qs
            effects = handler.state()
        body = json.loads(effects[0].content)
        tracks = [(a["track"], a["status"]) for a in body["alignments"]]
        # One row per track (latest CKM=aligned wins), eCKM kept, blank-track orphan dropped.
        assert tracks == [("CKM", "aligned"), ("eCKM", "eligible")]


class TestPollRoute:
    def test_requires_patient_id(self):
        handler = _make_handler(request_body={})
        effects = handler.poll()
        assert effects[0].status_code == HTTPStatus.BAD_REQUEST

    def test_404_when_no_in_progress_submission(self):
        handler = _make_handler(request_body={"patient_id": "p-1"})
        qs = MagicMock()
        qs.order_by.return_value.first.return_value = None
        with patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment") as MA:
            MA.objects.filter.return_value = qs
            effects = handler.poll()
        assert effects[0].status_code == HTTPStatus.NOT_FOUND

    def test_polls_and_returns_exchange(self):
        handler = _make_handler(request_body={"patient_id": "p-1"})
        alignment = _make_alignment(
            status="pending",
            submission_state="in-progress",
            submission_status_url="https://cms.test/submission-status/sub-1",
        )
        qs = MagicMock()
        qs.order_by.return_value.first.return_value = alignment

        def fake_poll(secrets, url, debug=None):
            if debug is not None:
                debug.append({"request": {"method": "GET", "url": url}, "response": {"status_code": 200}})
            return 200, {"resourceType": "Parameters"}

        with (
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment") as MA,
            patch("cms_access_fhir_client.api.operations_api.poll_submission_status", side_effect=fake_poll),
            patch("cms_access_fhir_client.api.operations_api._apply_poll_result"),
        ):
            MA.objects.filter.return_value = qs
            effects = handler.poll()

        assert effects[0].status_code == HTTPStatus.OK
        body = json.loads(effects[0].content)
        assert body["exchange"]["request"]["method"] == "GET"
        assert alignment.save.called


class TestReportDataRoute:
    def test_rejects_unknown_track(self):
        handler = _make_handler(request_body={"patient_id": "p-1", "track": "XYZ", "report_type": "baseline"})
        effects = handler.submit_report()
        assert effects[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert "Unknown track" in json.loads(effects[0].content)["error"]

    def test_requires_report_type(self):
        handler = _make_handler(request_body={"patient_id": "p-1", "track": "CKM"})
        effects = handler.submit_report()
        assert effects[0].status_code == HTTPStatus.BAD_REQUEST

    def test_conflict_when_unalign_in_progress(self):
        """report-data must not hijack the submission slot of an in-flight unalign —
        returns 409 so a pending unalignment (OM v0.9.11 p.70) isn't lost."""
        handler = _make_handler(
            secrets={"ACCESS_PARTICIPANT_ID": "ACCES12345"},
            request_body={"patient_id": "p-1", "track": "CKM", "report_type": "baseline"},
        )
        in_flight = MagicMock()
        in_flight.submission_state = "in-progress"
        in_flight.submission_op = "unalign"

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as MP,
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment") as MA,
        ):
            MP.get.return_value = MagicMock()
            MA.SUB_STATE_IN_PROGRESS = "in-progress"
            MA.SUB_OP_REPORT_DATA = "report-data"
            MA.objects.filter.return_value.first.return_value = in_flight
            effects = handler.submit_report()

        assert effects[0].status_code == HTTPStatus.CONFLICT
        assert "in progress" in json.loads(effects[0].content)["error"]

    def test_submits_and_returns_exchange_and_measures(self):
        handler = _make_handler(
            secrets={"ACCESS_PARTICIPANT_ID": "ACCES12345"},
            request_body={"patient_id": "p-1", "track": "CKM", "report_type": "baseline"},
        )
        coverage = MagicMock()
        coverage.id_number = "1EG4TE5MK73"
        coverage.issuer = MagicMock()
        coverage.issuer.payer_id = "00831"
        coverage.dbid = 31
        coverage.issuer.name = "IL Medicare Part B"

        def fake_submit(secrets, *, payer_id, track, report_type, data_bundle, debug=None):
            if debug is not None:
                debug.append({"request": {"method": "POST", "url": ".../$report-data"}, "response": {"status_code": 202}})
            return 202, "https://cms.test/submission-status/rd-1", {}

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as MP,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=coverage),
            patch("cms_access_fhir_client.api.operations_api._build_patient_resource", return_value={"resourceType": "Patient", "id": "p-1"}),
            patch("cms_access_fhir_client.api.operations_api._gather_measures", return_value={"4548-4": {"value": 6.5, "unit": "%"}}),
            patch("cms_access_fhir_client.api.operations_api.submit_report_data", side_effect=fake_submit),
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment") as MA,
        ):
            MP.get.return_value = MagicMock()
            MA.objects.get_or_create.return_value = (MagicMock(), True)
            MA.STATUS_PENDING = "pending"
            MA.SUB_STATE_IN_PROGRESS = "in-progress"
            MA.SUB_OP_REPORT_DATA = "report-data"
            effects = handler.submit_report()

        assert effects[0].status_code == HTTPStatus.ACCEPTED
        body = json.loads(effects[0].content)
        assert body["content_location"] == "https://cms.test/submission-status/rd-1"
        assert body["elements_found"] == ["4548-4"]
        assert body["exchange"]["request"]["method"] == "POST"

    def test_bh_track_routes_through_questionnaire_responses(self):
        handler = _make_handler(
            secrets={"ACCESS_PARTICIPANT_ID": "ACCES12345"},
            request_body={"patient_id": "p-1", "track": "BH", "report_type": "baseline"},
        )
        coverage = MagicMock()
        coverage.id_number = "1EG4TE5MK73"
        coverage.issuer = MagicMock()
        coverage.issuer.payer_id = "00831"

        def fake_submit(secrets, *, payer_id, track, report_type, data_bundle, debug=None):
            # BH bundle must reference QuestionnaireResponses, not Observations.
            types = {e["resource"]["resourceType"] for e in data_bundle["entry"]}
            assert "QuestionnaireResponse" in types
            if debug is not None:
                debug.append({"request": {"method": "POST", "url": ".../$report-data"}, "response": {"status_code": 202}})
            return 202, "https://cms.test/submission-status/bh-1", {}

        with (
            patch("cms_access_fhir_client.api.operations_api.CustomPatient.objects") as MP,
            patch("cms_access_fhir_client.api.operations_api.get_active_medicare_part_b_coverage", return_value=coverage),
            patch("cms_access_fhir_client.api.operations_api._build_patient_resource", return_value={"resourceType": "Patient", "id": "p-1"}),
            patch("cms_access_fhir_client.api.operations_api._gather_questionnaire_responses",
                  return_value={"44249-1": {"narrative": "PHQ-9", "items": []}}) as gather,
            patch("cms_access_fhir_client.api.operations_api._gather_measures") as gather_obs,
            patch("cms_access_fhir_client.api.operations_api.submit_report_data", side_effect=fake_submit),
            patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment") as MA,
        ):
            MP.get.return_value = MagicMock()
            MA.objects.filter.return_value.first.return_value = None
            MA.objects.get_or_create.return_value = (MagicMock(), True)
            MA.STATUS_PENDING = "pending"
            MA.SUB_STATE_IN_PROGRESS = "in-progress"
            MA.SUB_OP_REPORT_DATA = "report-data"
            effects = handler.submit_report()

        assert effects[0].status_code == HTTPStatus.ACCEPTED
        body = json.loads(effects[0].content)
        assert body["elements_found"] == ["44249-1"]
        gather.assert_called_once()
        gather_obs.assert_not_called()  # BH must not use the Observation path


class TestGatherQuestionnaireResponsesLookup:
    """The lookup code for each instrument: LOINC when one exists, else the ACCESS section
    code — so WHODAS/PGIC/QuickDASH are discoverable and never silently skipped.
    """

    def test_bh_looks_up_loinc_and_access_coded_instruments(self):
        from cms_access_fhir_client.api import operations_api

        with patch.object(operations_api, "_latest_interview_response", return_value=None) as latest:
            operations_api._gather_questionnaire_responses("p-1", "BH")

        # second positional arg is the lookup code passed per instrument
        codes = {call.args[1] for call in latest.call_args_list}
        assert "44249-1" in codes  # PHQ-9 (LOINC)
        assert "69737-5" in codes  # GAD-7 (LOINC)
        assert "WHODAS" in codes   # no LOINC → falls back to the ACCESS section code
        assert "PGIC" in codes

    def test_access_coded_instrument_is_gathered_when_found(self):
        from cms_access_fhir_client.api import operations_api

        # Only the WHODAS-coded questionnaire exists in this Canvas instance.
        def fake_latest(patient_id, code, title):
            if code == "WHODAS":
                return {"narrative": "WHODAS 2.0", "items": []}
            return None

        with patch.object(operations_api, "_latest_interview_response", side_effect=fake_latest):
            responses = operations_api._gather_questionnaire_responses("p-1", "BH")

        assert "WHODAS" in responses  # keyed by section code, no longer skipped
        assert responses["WHODAS"]["narrative"] == "WHODAS 2.0"

    def test_msk_quickdash_uses_section_code(self):
        from cms_access_fhir_client.api import operations_api

        with patch.object(operations_api, "_latest_interview_response", return_value=None) as latest:
            operations_api._gather_questionnaire_responses("p-1", "MSK")

        codes = {call.args[1] for call in latest.call_args_list}
        assert "QuickDASH" in codes  # no LOINC → ACCESS section code
        assert "97908-8" in codes    # Oswestry kept on its LOINC (clients code it correctly)


class TestEnabledTracks:
    """ACCESS_ENABLED_TRACKS gates which tracks the inspector shows and operates on."""

    def test_blank_or_unset_enables_all(self):
        from cms_access_fhir_client.api.operations_api import _enabled_tracks
        assert _enabled_tracks({}) == ["eCKM", "CKM", "MSK", "BH"]
        assert _enabled_tracks({"ACCESS_ENABLED_TRACKS": "   "}) == ["eCKM", "CKM", "MSK", "BH"]

    def test_restricts_to_listed_tracks_case_insensitive_and_ordered(self):
        from cms_access_fhir_client.api.operations_api import _enabled_tracks
        # case-insensitive + whitespace tolerant; canonical display order preserved (not input order)
        assert _enabled_tracks({"ACCESS_ENABLED_TRACKS": "bh, ckm"}) == ["CKM", "BH"]

    def test_unknown_names_yield_empty(self):
        from cms_access_fhir_client.api.operations_api import _enabled_tracks
        assert _enabled_tracks({"ACCESS_ENABLED_TRACKS": "XYZ"}) == []

    def test_state_reports_enabled_tracks(self):
        handler = _make_handler(
            secrets={"ACCESS_ENABLED_TRACKS": "CKM,BH"}, query_params={"patient_id": "p-1"}
        )
        qs = MagicMock()
        qs.order_by.return_value = []
        with patch("cms_access_fhir_client.api.operations_api.ACCESSAlignment") as MA:
            MA.objects.filter.return_value = qs
            effects = handler.state()
        body = json.loads(effects[0].content)
        assert body["enabled_tracks"] == ["CKM", "BH"]

    def test_eligibility_rejects_disabled_track(self):
        handler = _make_handler(
            secrets={"ACCESS_ENABLED_TRACKS": "CKM"},
            request_body={"patient_id": "p-1", "track": "BH"},
        )
        effects = handler.submit_eligibility()
        assert effects[0].status_code == HTTPStatus.FORBIDDEN
        assert "not enabled" in json.loads(effects[0].content)["error"]


class TestRegressionFixes:
    """Guards for two bugs caught in review (Cerberus + local)."""

    def test_latest_interview_response_defaults_answer_system_to_loinc(self):
        # Regression: a questionnaire answer whose question has no code_system must default
        # answer_system to LOINC, not raise NameError on an undefined _LOINC (op_api:255).
        # Existing tests mock _latest_interview_response, so the real body was never exercised.
        from cms_access_fhir_client.api import operations_api

        question = MagicMock()
        question.code = "q1"
        question.name = "Question 1"
        question.code_system = None  # the trigger
        option = MagicMock()
        option.code = "LA1"
        option.name = "Answer"
        option.value = "1"
        option.ordering = 1
        resp = MagicMock()
        resp.question = question
        resp.response_option = option
        resp.response_option_value = None
        interview = MagicMock()
        interview.created = datetime(2026, 6, 21, 10, 0, 0, tzinfo=timezone.utc)
        interview.interview_responses.filter.return_value.select_related.return_value = [resp]

        with patch.object(operations_api, "Interview") as MI:
            MI.objects.filter.return_value.order_by.return_value.first.return_value = interview
            data = operations_api._latest_interview_response("p-1", "44249-1", "PHQ-9")

        assert data["items"][0]["answer_system"] == "http://loinc.org"

    def test_build_patient_resource_requires_nonblank_mbi(self):
        # Regression: never send an empty MBI to CMS — must raise (routes turn it into a 422).
        import pytest
        from datetime import date as _date
        from cms_access_fhir_client.api.operations_api import _build_patient_resource

        patient = MagicMock()
        patient.id = "p-1"
        patient.birth_date = _date(1960, 4, 4)
        patient.first_name = "Y"
        patient.last_name = "X"
        with pytest.raises(ValueError, match="Medicare Beneficiary Identifier"):
            _build_patient_resource(patient, mbi="")
        with pytest.raises(ValueError, match="Medicare Beneficiary Identifier"):
            _build_patient_resource(patient, mbi="   ")
