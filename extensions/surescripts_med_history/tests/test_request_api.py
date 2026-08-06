from http import HTTPStatus
from unittest.mock import MagicMock, patch


class _FakeDoesNotExist(Exception):
    pass


def _make_handler(headers=None, body=None):
    """Build a MedHistoryRequestApi handler with controllable headers/body."""
    from surescripts_med_history.protocols.view import MedHistoryRequestApi

    handler = MedHistoryRequestApi(event=MagicMock())
    handler.request = MagicMock()
    handler.request.headers = headers or {}
    handler.request.json.return_value = body or {}
    return handler


class TestRequestMedHistory:
    @patch("surescripts_med_history.protocols.view.Staff")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_requires_patient_id(self, mock_patient_cls, mock_staff_cls):
        handler = _make_handler(body={})
        results = handler.request_med_history()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("surescripts_med_history.protocols.view.Staff")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_returns_404_when_patient_not_found(self, mock_patient_cls, mock_staff_cls):
        mock_patient_cls.DoesNotExist = _FakeDoesNotExist
        mock_patient_cls.objects.select_related.return_value.get.side_effect = (
            _FakeDoesNotExist("not found")
        )
        mock_staff_cls.DoesNotExist = _FakeDoesNotExist
        mock_staff_cls.objects.get.side_effect = _FakeDoesNotExist("no staff")

        handler = _make_handler(body={"patient_id": "missing"})
        results = handler.request_med_history()
        assert results[0].status_code == HTTPStatus.NOT_FOUND

    @patch("surescripts_med_history.protocols.view.Staff")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_returns_400_when_no_default_provider(
        self, mock_patient_cls, mock_staff_cls
    ):
        patient = MagicMock()
        patient.default_provider = None
        mock_patient_cls.objects.select_related.return_value.get.return_value = patient
        mock_staff_cls.DoesNotExist = _FakeDoesNotExist
        mock_staff_cls.objects.get.side_effect = _FakeDoesNotExist("no staff")

        handler = _make_handler(body={"patient_id": "p1"})
        results = handler.request_med_history()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("surescripts_med_history.protocols.view.Staff")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_returns_400_when_default_provider_has_no_spi(
        self, mock_patient_cls, mock_staff_cls
    ):
        patient = MagicMock()
        patient.default_provider = MagicMock(id="prov-1")
        patient.default_provider.spi_number = ""
        mock_patient_cls.objects.select_related.return_value.get.return_value = patient
        mock_staff_cls.DoesNotExist = _FakeDoesNotExist
        mock_staff_cls.objects.get.side_effect = _FakeDoesNotExist("no staff")

        handler = _make_handler(body={"patient_id": "p1"})
        results = handler.request_med_history()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("surescripts_med_history.protocols.view.Note")
    @patch("surescripts_med_history.protocols.view.Staff")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_returns_200_via_default_provider(
        self, mock_patient_cls, mock_staff_cls, mock_note_cls
    ):
        patient = MagicMock()
        patient.default_provider = MagicMock(id="prov-1")
        patient.default_provider.spi_number = "1234567"
        mock_patient_cls.objects.select_related.return_value.get.return_value = patient
        # Logged-in user has no SPI (e.g. care manager) — fall through to default provider
        mock_staff_cls.DoesNotExist = _FakeDoesNotExist
        non_provider = MagicMock(id="user-1")
        non_provider.spi_number = ""
        mock_staff_cls.objects.get.return_value = non_provider
        # No open note → metadata effects are not appended
        mock_note_qs = MagicMock()
        mock_note_cls.objects.filter.return_value = mock_note_qs
        mock_note_qs.filter.return_value = mock_note_qs
        mock_note_qs.order_by.return_value = mock_note_qs
        mock_note_qs.first.return_value = None

        handler = _make_handler(
            headers={"canvas-logged-in-user-id": "user-1"},
            body={"patient_id": "p1"},
        )
        results = handler.request_med_history()
        assert results[0].status_code == HTTPStatus.OK
        # 1 JSONResponse + 2 surescripts effects (eligibility + med history),
        # no note → no metadata
        assert len(results) == 3

    @patch("surescripts_med_history.protocols.view.Note")
    @patch("surescripts_med_history.protocols.view.Staff")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_returns_200_via_logged_in_provider_without_default(
        self, mock_patient_cls, mock_staff_cls, mock_note_cls
    ):
        # Logged-in staff has SPI — should not need patient.default_provider at all.
        mock_staff_cls.DoesNotExist = _FakeDoesNotExist
        provider = MagicMock(id="prov-2")
        provider.spi_number = "9999999"
        mock_staff_cls.objects.get.return_value = provider
        mock_note_qs = MagicMock()
        mock_note_cls.objects.filter.return_value = mock_note_qs
        mock_note_qs.filter.return_value = mock_note_qs
        mock_note_qs.order_by.return_value = mock_note_qs
        mock_note_qs.first.return_value = None

        handler = _make_handler(
            headers={"canvas-logged-in-user-id": "prov-2"},
            body={"patient_id": "p1"},
        )
        results = handler.request_med_history()

        assert results[0].status_code == HTTPStatus.OK
        # 1 JSONResponse + eligibility + med history effects
        assert len(results) == 3
        # Patient lookup should be skipped on the logged-in-provider path
        mock_patient_cls.objects.select_related.return_value.get.assert_not_called()

    @patch("surescripts_med_history.protocols.view.request_metadata_effects")
    @patch("surescripts_med_history.protocols.view.Note")
    @patch("surescripts_med_history.protocols.view.Staff")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_stamps_metadata_when_open_note_exists(
        self,
        mock_patient_cls,
        mock_staff_cls,
        mock_note_cls,
        mock_metadata,
    ):
        from uuid import uuid4

        mock_metadata.return_value = ["meta-status", "meta-at"]
        mock_staff_cls.DoesNotExist = _FakeDoesNotExist
        provider = MagicMock(id="prov-2")
        provider.spi_number = "9999999"
        mock_staff_cls.objects.get.return_value = provider

        note_id = uuid4()
        note = MagicMock(id=note_id)
        mock_note_qs = MagicMock()
        mock_note_cls.objects.filter.return_value = mock_note_qs
        mock_note_qs.filter.return_value = mock_note_qs
        mock_note_qs.order_by.return_value = mock_note_qs
        mock_note_qs.first.return_value = note

        handler = _make_handler(
            headers={"canvas-logged-in-user-id": "prov-2"},
            body={"patient_id": "p1"},
        )
        results = handler.request_med_history()

        # 1 JSONResponse + 2 surescripts effects + 2 metadata calls × 2 effects
        assert len(results) == 7
        assert mock_metadata.call_count == 2
        mock_metadata.assert_any_call(str(note_id), "eligibility")
        mock_metadata.assert_any_call(str(note_id), "med_history")

    @patch("surescripts_med_history.protocols.view.Note")
    @patch("surescripts_med_history.protocols.view.Staff")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_explicit_staff_id_used_when_provider_has_spi(
        self, mock_patient_cls, mock_staff_cls, mock_note_cls
    ):
        # A provider chosen from the dropdown is used directly, regardless of
        # the logged-in user or the patient's default provider.
        mock_staff_cls.DoesNotExist = _FakeDoesNotExist
        chosen = MagicMock(id="prov-9")
        chosen.spi_number = "5555555"
        mock_staff_cls.objects.get.return_value = chosen
        mock_note_qs = MagicMock()
        mock_note_cls.objects.filter.return_value = mock_note_qs
        mock_note_qs.filter.return_value = mock_note_qs
        mock_note_qs.order_by.return_value = mock_note_qs
        mock_note_qs.first.return_value = None

        handler = _make_handler(body={"patient_id": "p1", "staff_id": "prov-9"})
        results = handler.request_med_history()

        assert results[0].status_code == HTTPStatus.OK
        assert len(results) == 3
        mock_staff_cls.objects.get.assert_called_once_with(id="prov-9")
        # No fallback to patient lookup when an explicit provider is given
        mock_patient_cls.objects.select_related.return_value.get.assert_not_called()

    @patch("surescripts_med_history.protocols.view.Staff")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_explicit_staff_id_without_spi_returns_400(
        self, mock_patient_cls, mock_staff_cls
    ):
        mock_staff_cls.DoesNotExist = _FakeDoesNotExist
        chosen = MagicMock(id="prov-9")
        chosen.spi_number = ""
        mock_staff_cls.objects.get.return_value = chosen

        handler = _make_handler(body={"patient_id": "p1", "staff_id": "prov-9"})
        results = handler.request_med_history()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("surescripts_med_history.protocols.view.Staff")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_explicit_staff_id_not_found_returns_404(
        self, mock_patient_cls, mock_staff_cls
    ):
        mock_staff_cls.DoesNotExist = _FakeDoesNotExist
        mock_staff_cls.objects.get.side_effect = _FakeDoesNotExist("no staff")

        handler = _make_handler(body={"patient_id": "p1", "staff_id": "ghost"})
        results = handler.request_med_history()
        assert results[0].status_code == HTTPStatus.NOT_FOUND


class TestAddMedication:
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_requires_patient_id_and_drug_description(self, mock_patient_cls):
        from surescripts_med_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {"patient_id": "p1"}
        results = handler.add_medication()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("surescripts_med_history.protocols.view.Patient")
    def test_returns_404_when_patient_not_found(self, mock_patient_cls):
        mock_patient_cls.DoesNotExist = _FakeDoesNotExist
        mock_patient_cls.objects.get.side_effect = _FakeDoesNotExist("not found")

        from surescripts_med_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_id": "missing",
            "drug_description": "Drug A",
        }
        results = handler.add_medication()
        assert results[0].status_code == HTTPStatus.NOT_FOUND

    @patch("surescripts_med_history.protocols.view.Note")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_returns_422_when_no_open_note(self, mock_patient_cls, mock_note_cls):
        mock_patient_cls.objects.get.return_value = MagicMock()
        mock_note_qs = MagicMock()
        mock_note_cls.objects.filter.return_value = mock_note_qs
        mock_note_qs.filter.return_value = mock_note_qs
        mock_note_qs.order_by.return_value = mock_note_qs
        mock_note_qs.first.return_value = None

        from surescripts_med_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_id": "p1",
            "drug_description": "Drug A",
        }
        results = handler.add_medication()
        assert results[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    @patch("surescripts_med_history.protocols.view._lookup_fdb_code")
    @patch("surescripts_med_history.protocols.view.Note")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_returns_422_when_fdb_lookup_fails(
        self, mock_patient_cls, mock_note_cls, mock_lookup
    ):
        mock_patient_cls.objects.get.return_value = MagicMock()
        note = MagicMock(id="note-1")
        mock_note_qs = MagicMock()
        mock_note_cls.objects.filter.return_value = mock_note_qs
        mock_note_qs.filter.return_value = mock_note_qs
        mock_note_qs.order_by.return_value = mock_note_qs
        mock_note_qs.first.return_value = note
        mock_lookup.return_value = None

        from surescripts_med_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock())
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_id": "p1",
            "drug_description": "Drug A",
        }
        results = handler.add_medication()
        assert results[0].status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    @patch("surescripts_med_history.protocols.view.MedicationStatementCommand")
    @patch("surescripts_med_history.protocols.view._lookup_fdb_code")
    @patch("surescripts_med_history.protocols.view.Note")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_returns_200_and_originates_command_on_success(
        self, mock_patient_cls, mock_note_cls, mock_lookup, mock_cmd_cls
    ):
        mock_cmd = self._run_add(
            mock_patient_cls, mock_note_cls, mock_lookup, mock_cmd_cls
        )[1]
        mock_cmd_cls.assert_called_once_with(
            note_uuid="note-1",
            fdb_code="98765",
            sig="Take 1 daily",
        )
        mock_cmd.originate.assert_called_once_with()

    @patch("surescripts_med_history.protocols.view.MedicationStatementCommand")
    @patch("surescripts_med_history.protocols.view._lookup_fdb_code")
    @patch("surescripts_med_history.protocols.view.Note")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_stamps_data_source_metadata(
        self, mock_patient_cls, mock_note_cls, mock_lookup, mock_cmd_cls
    ):
        _, mock_cmd = self._run_add(
            mock_patient_cls, mock_note_cls, mock_lookup, mock_cmd_cls
        )
        mock_cmd.upsert_metadata.assert_called_once_with(
            key="data_source", value="surescripts"
        )
        # A caller-set uuid is required for metadata (and commit) to attach to
        # the command originated in the same response.
        assert mock_cmd.command_uuid

    @patch("surescripts_med_history.protocols.view.MedicationStatementCommand")
    @patch("surescripts_med_history.protocols.view._lookup_fdb_code")
    @patch("surescripts_med_history.protocols.view.Note")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_does_not_commit_by_default(
        self, mock_patient_cls, mock_note_cls, mock_lookup, mock_cmd_cls
    ):
        results, mock_cmd = self._run_add(
            mock_patient_cls, mock_note_cls, mock_lookup, mock_cmd_cls
        )
        mock_cmd.commit.assert_not_called()
        # response + originate + metadata
        assert len(results) == 3

    @patch("surescripts_med_history.protocols.view.MedicationStatementCommand")
    @patch("surescripts_med_history.protocols.view._lookup_fdb_code")
    @patch("surescripts_med_history.protocols.view.Note")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_commits_when_secret_enabled(
        self, mock_patient_cls, mock_note_cls, mock_lookup, mock_cmd_cls
    ):
        results, mock_cmd = self._run_add(
            mock_patient_cls,
            mock_note_cls,
            mock_lookup,
            mock_cmd_cls,
            secrets={"commit_medication_statements": "true"},
        )
        mock_cmd.commit.assert_called_once_with()
        # response + originate + metadata + commit
        assert len(results) == 4

    @patch("surescripts_med_history.protocols.view.MedicationStatementCommand")
    @patch("surescripts_med_history.protocols.view._lookup_fdb_code")
    @patch("surescripts_med_history.protocols.view.Note")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_does_not_commit_when_secret_disabled(
        self, mock_patient_cls, mock_note_cls, mock_lookup, mock_cmd_cls
    ):
        _, mock_cmd = self._run_add(
            mock_patient_cls,
            mock_note_cls,
            mock_lookup,
            mock_cmd_cls,
            secrets={"commit_medication_statements": "false"},
        )
        mock_cmd.commit.assert_not_called()

    @staticmethod
    def _run_add(
        mock_patient_cls, mock_note_cls, mock_lookup, mock_cmd_cls, secrets=None
    ):
        """Drive a successful add_medication call; return (results, command)."""
        mock_patient_cls.objects.get.return_value = MagicMock()
        note = MagicMock()
        note.id = "note-1"
        mock_note_qs = MagicMock()
        mock_note_cls.objects.filter.return_value = mock_note_qs
        mock_note_qs.filter.return_value = mock_note_qs
        mock_note_qs.order_by.return_value = mock_note_qs
        mock_note_qs.first.return_value = note
        mock_lookup.return_value = 98765

        mock_cmd = MagicMock()
        mock_cmd_cls.return_value = mock_cmd

        from surescripts_med_history.protocols.view import MedHistoryRequestApi

        handler = MedHistoryRequestApi(event=MagicMock(), secrets=secrets)
        handler.request = MagicMock()
        handler.request.json.return_value = {
            "patient_id": "p1",
            "drug_description": "Drug A",
            "sig": "Take 1 daily",
            "rxnorm_rxcui": "866083",
        }
        results = handler.add_medication()
        assert results[0].status_code == HTTPStatus.OK
        return results, mock_cmd


class TestLookupFdbCode:
    @patch("surescripts_med_history.protocols.view.ontologies_http")
    def test_rxnorm_lookup_returns_fdb_code(self, mock_http):
        resp = MagicMock()
        resp.json.return_value = [{"med_medication_id": 12345}]
        mock_http.get_json.return_value = resp

        from surescripts_med_history.protocols.view import _lookup_fdb_code

        result = _lookup_fdb_code("Drug A", rxnorm_rxcui="866083")
        assert result == 12345

    @patch("surescripts_med_history.protocols.view.ontologies_http")
    def test_falls_back_to_text_search(self, mock_http):
        rxnorm_resp = MagicMock()
        rxnorm_resp.json.return_value = []
        text_resp = MagicMock()
        text_resp.json.return_value = {"results": [{"med_medication_id": 67890}]}
        mock_http.get_json.side_effect = [rxnorm_resp, text_resp]

        from surescripts_med_history.protocols.view import _lookup_fdb_code

        result = _lookup_fdb_code("Drug A", rxnorm_rxcui="999")
        assert result == 67890

    @patch("surescripts_med_history.protocols.view.ontologies_http")
    def test_returns_none_on_failure(self, mock_http):
        import requests

        mock_http.get_json.side_effect = requests.ConnectionError("network error")

        from surescripts_med_history.protocols.view import _lookup_fdb_code

        result = _lookup_fdb_code("Drug A")
        assert result is None

    @patch("surescripts_med_history.protocols.view.ontologies_http")
    def test_returns_none_when_text_search_body_is_not_json(self, mock_http):
        # JsonOnlyResponse.json() returns None for a non-JSON body (e.g. a 5xx
        # HTML error page) rather than raising.
        text_resp = MagicMock()
        text_resp.json.return_value = None
        mock_http.get_json.return_value = text_resp

        from surescripts_med_history.protocols.view import _lookup_fdb_code

        result = _lookup_fdb_code("Drug A")
        assert result is None


class TestDismiss:
    @patch("surescripts_med_history.protocols.view.MedicationDismissal")
    @patch("surescripts_med_history.protocols.view.Staff")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_requires_patient_id_and_group_key(
        self, mock_patient_cls, mock_staff_cls, mock_dismissal_cls
    ):
        handler = _make_handler(body={})
        results = handler.dismiss()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST
        mock_dismissal_cls.objects.update_or_create.assert_not_called()

    @patch("surescripts_med_history.protocols.view.MedicationDismissal")
    @patch("surescripts_med_history.protocols.view.Staff")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_returns_404_when_patient_missing(
        self, mock_patient_cls, mock_staff_cls, mock_dismissal_cls
    ):
        mock_patient_cls.DoesNotExist = _FakeDoesNotExist
        mock_patient_cls.objects.values_list.return_value.get.side_effect = (
            _FakeDoesNotExist("nope")
        )

        handler = _make_handler(body={"patient_id": "p1", "group_key": "ndc:abc"})
        results = handler.dismiss()
        assert results[0].status_code == HTTPStatus.NOT_FOUND
        mock_dismissal_cls.objects.update_or_create.assert_not_called()

    @patch("surescripts_med_history.protocols.view.MedicationDismissal")
    @patch("surescripts_med_history.protocols.view.Staff")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_creates_dismissal_with_logged_in_staff(
        self, mock_patient_cls, mock_staff_cls, mock_dismissal_cls
    ):
        mock_patient_cls.DoesNotExist = _FakeDoesNotExist
        mock_patient_cls.objects.values_list.return_value.get.return_value = 42

        mock_staff_cls.DoesNotExist = _FakeDoesNotExist
        staff = MagicMock(id="staff-uuid", first_name="Anna", last_name="Smith")
        mock_staff_cls.objects.get.return_value = staff

        handler = _make_handler(
            headers={"canvas-logged-in-user-id": "staff-uuid"},
            body={
                "patient_id": "p1",
                "group_key": "ndc:001312477-35",
                "drug_description": "Aspirin 81mg",
            },
        )
        results = handler.dismiss()
        assert results[0].status_code == HTTPStatus.OK

        kwargs = mock_dismissal_cls.objects.update_or_create.call_args.kwargs
        assert kwargs["patient_id"] == 42
        assert kwargs["group_key"] == "ndc:001312477-35"
        defaults = kwargs["defaults"]
        assert defaults["drug_description"] == "Aspirin 81mg"
        assert defaults["dismissed_by_id"] == "staff-uuid"
        assert defaults["dismissed_by"] == "Anna Smith"

    @patch("surescripts_med_history.protocols.view.MedicationDismissal")
    @patch("surescripts_med_history.protocols.view.Staff")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_creates_dismissal_without_logged_in_staff(
        self, mock_patient_cls, mock_staff_cls, mock_dismissal_cls
    ):
        # Header missing → no staff lookup; dismissal still created with empty
        # dismissed_by fields
        mock_patient_cls.DoesNotExist = _FakeDoesNotExist
        mock_patient_cls.objects.values_list.return_value.get.return_value = 42
        mock_staff_cls.DoesNotExist = _FakeDoesNotExist

        handler = _make_handler(body={"patient_id": "p1", "group_key": "ndc:abc"})
        results = handler.dismiss()
        assert results[0].status_code == HTTPStatus.OK
        defaults = mock_dismissal_cls.objects.update_or_create.call_args.kwargs[
            "defaults"
        ]
        assert defaults["dismissed_by_id"] == ""
        assert defaults["dismissed_by"] == ""


def _make_history_handler(query_params=None):
    from surescripts_med_history.protocols.view import MedHistoryRequestApi

    handler = MedHistoryRequestApi(event=MagicMock())
    handler.request = MagicMock()
    handler.request.query_params = query_params or {}
    return handler


class TestHistory:
    @patch("surescripts_med_history.protocols.view.build_history_payload")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_requires_patient_id(self, mock_patient_cls, mock_build):
        handler = _make_history_handler(query_params={})
        results = handler.history()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST
        mock_build.assert_not_called()

    @patch("surescripts_med_history.protocols.view.build_history_payload")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_returns_404_when_patient_not_found(self, mock_patient_cls, mock_build):
        mock_patient_cls.DoesNotExist = _FakeDoesNotExist
        mock_patient_cls.objects.get.side_effect = _FakeDoesNotExist("nope")
        handler = _make_history_handler(query_params={"patient_id": "ghost"})
        results = handler.history()
        assert results[0].status_code == HTTPStatus.NOT_FOUND
        mock_build.assert_not_called()

    @patch("surescripts_med_history.protocols.view.build_history_payload")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_returns_payload(self, mock_patient_cls, mock_build):
        patient = MagicMock()
        mock_patient_cls.objects.get.return_value = patient
        mock_build.return_value = (
            {"grouped_items": [], "status": {"state": "no_data"}},
            [99],  # stale ids — the GET path must ignore them (read-only)
        )
        handler = _make_history_handler(query_params={"patient_id": "p1"})
        results = handler.history()
        assert results[0].status_code == HTTPStatus.OK
        mock_build.assert_called_once_with(patient, include_mock=False)

    @patch("surescripts_med_history.protocols.view.build_history_payload")
    @patch("surescripts_med_history.protocols.view.Patient")
    def test_passes_mock_flag_from_secret(self, mock_patient_cls, mock_build):
        patient = MagicMock()
        mock_patient_cls.objects.get.return_value = patient
        mock_build.return_value = ({"grouped_items": []}, [])
        handler = _make_history_handler(query_params={"patient_id": "p1"})
        handler.secrets = {"mock_history_data": "true"}
        handler.history()
        mock_build.assert_called_once_with(patient, include_mock=True)
