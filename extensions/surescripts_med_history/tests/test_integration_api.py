import json
from datetime import datetime, timezone
from http import HTTPStatus
from unittest.mock import MagicMock, patch


class _FakeDoesNotExist(Exception):
    pass


def _make_handler(query_params=None, body=None):
    """Build a DismissalsIntegrationApi handler with controllable query/body."""
    from surescripts_med_history.protocols.integration_api import (
        DismissalsIntegrationApi,
    )

    handler = DismissalsIntegrationApi(event=MagicMock())
    handler.request = MagicMock()
    handler.request.query_params = query_params or {}
    handler.request.json.return_value = body or {}
    return handler


class TestListDismissals:
    @patch("surescripts_med_history.protocols.integration_api.MedicationDismissal")
    @patch("surescripts_med_history.protocols.integration_api.Patient")
    def test_requires_patient_id(self, mock_patient_cls, mock_dismissal_cls):
        handler = _make_handler(query_params={})
        results = handler.list_dismissals()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST
        mock_dismissal_cls.objects.filter.assert_not_called()

    @patch("surescripts_med_history.protocols.integration_api.MedicationDismissal")
    @patch("surescripts_med_history.protocols.integration_api.Patient")
    def test_returns_404_when_patient_missing(
        self, mock_patient_cls, mock_dismissal_cls
    ):
        mock_patient_cls.DoesNotExist = _FakeDoesNotExist
        mock_patient_cls.objects.values_list.return_value.get.side_effect = (
            _FakeDoesNotExist("nope")
        )

        handler = _make_handler(query_params={"patient_id": "missing"})
        results = handler.list_dismissals()
        assert results[0].status_code == HTTPStatus.NOT_FOUND
        mock_dismissal_cls.objects.filter.assert_not_called()

    @patch("surescripts_med_history.protocols.integration_api.MedicationDismissal")
    @patch("surescripts_med_history.protocols.integration_api.Patient")
    def test_returns_empty_list_with_200_when_no_dismissals(
        self, mock_patient_cls, mock_dismissal_cls
    ):
        mock_patient_cls.DoesNotExist = _FakeDoesNotExist
        mock_patient_cls.objects.values_list.return_value.get.return_value = 42
        mock_dismissal_cls.objects.filter.return_value.order_by.return_value = []

        handler = _make_handler(query_params={"patient_id": "p1"})
        results = handler.list_dismissals()

        assert results[0].status_code == HTTPStatus.OK
        payload = json.loads(results[0].content)
        assert payload == {"dismissals": []}

    @patch("surescripts_med_history.protocols.integration_api.MedicationDismissal")
    @patch("surescripts_med_history.protocols.integration_api.Patient")
    def test_serializes_dismissals(self, mock_patient_cls, mock_dismissal_cls):
        mock_patient_cls.DoesNotExist = _FakeDoesNotExist
        mock_patient_cls.objects.values_list.return_value.get.return_value = 42

        dismissed_at = datetime(2026, 5, 1, 14, 30, tzinfo=timezone.utc)
        d1 = MagicMock(
            group_key="ndc:001312477-35",
            drug_description="Aspirin 81mg",
            dismissed_by="Anna Smith",
            dismissed_by_id="staff-uuid",
            dismissed_at=dismissed_at,
        )
        d2 = MagicMock(
            group_key="desc:Metformin",
            drug_description="Metformin 500mg",
            dismissed_by="",
            dismissed_by_id="",
            dismissed_at=None,
        )
        mock_dismissal_cls.objects.filter.return_value.order_by.return_value = [d1, d2]

        handler = _make_handler(query_params={"patient_id": "p1"})
        results = handler.list_dismissals()

        assert results[0].status_code == HTTPStatus.OK
        payload = json.loads(results[0].content)
        assert payload == {
            "dismissals": [
                {
                    "group_key": "ndc:001312477-35",
                    "drug_description": "Aspirin 81mg",
                    "dismissed_by": "Anna Smith",
                    "dismissed_by_id": "staff-uuid",
                    "dismissed_at": dismissed_at.isoformat(),
                },
                {
                    "group_key": "desc:Metformin",
                    "drug_description": "Metformin 500mg",
                    "dismissed_by": "",
                    "dismissed_by_id": "",
                    "dismissed_at": "",
                },
            ]
        }
        mock_dismissal_cls.objects.filter.assert_called_once_with(patient_id=42)


class TestCreateDismissal:
    @patch("surescripts_med_history.protocols.integration_api.MedicationDismissal")
    @patch("surescripts_med_history.protocols.integration_api.Patient")
    def test_requires_patient_id_and_group_key(
        self, mock_patient_cls, mock_dismissal_cls
    ):
        handler = _make_handler(
            body={"dismissed_by": "Bot", "dismissed_by_id": "bot-1"}
        )
        results = handler.create_dismissal()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST
        mock_dismissal_cls.objects.update_or_create.assert_not_called()

    @patch("surescripts_med_history.protocols.integration_api.MedicationDismissal")
    @patch("surescripts_med_history.protocols.integration_api.Patient")
    def test_requires_dismissed_by_and_id(
        self, mock_patient_cls, mock_dismissal_cls
    ):
        handler = _make_handler(
            body={"patient_id": "p1", "group_key": "ndc:abc"}
        )
        results = handler.create_dismissal()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST
        mock_dismissal_cls.objects.update_or_create.assert_not_called()

    @patch("surescripts_med_history.protocols.integration_api.MedicationDismissal")
    @patch("surescripts_med_history.protocols.integration_api.Patient")
    def test_returns_404_when_patient_missing(
        self, mock_patient_cls, mock_dismissal_cls
    ):
        mock_patient_cls.DoesNotExist = _FakeDoesNotExist
        mock_patient_cls.objects.values_list.return_value.get.side_effect = (
            _FakeDoesNotExist("nope")
        )

        handler = _make_handler(
            body={
                "patient_id": "p1",
                "group_key": "ndc:abc",
                "dismissed_by": "Bot",
                "dismissed_by_id": "bot-1",
            }
        )
        results = handler.create_dismissal()
        assert results[0].status_code == HTTPStatus.NOT_FOUND
        mock_dismissal_cls.objects.update_or_create.assert_not_called()

    @patch("surescripts_med_history.protocols.integration_api.MedicationDismissal")
    @patch("surescripts_med_history.protocols.integration_api.Patient")
    def test_creates_dismissal_with_supplied_attribution(
        self, mock_patient_cls, mock_dismissal_cls
    ):
        mock_patient_cls.DoesNotExist = _FakeDoesNotExist
        mock_patient_cls.objects.values_list.return_value.get.return_value = 42

        handler = _make_handler(
            body={
                "patient_id": "p1",
                "group_key": "ndc:001312477-35",
                "drug_description": "Aspirin 81mg",
                "dismissed_by": "Reconciler Bot",
                "dismissed_by_id": "plugin:med_reconciler",
            }
        )
        results = handler.create_dismissal()
        assert results[0].status_code == HTTPStatus.OK

        kwargs = mock_dismissal_cls.objects.update_or_create.call_args.kwargs
        assert kwargs["patient_id"] == 42
        assert kwargs["group_key"] == "ndc:001312477-35"
        defaults = kwargs["defaults"]
        assert defaults["drug_description"] == "Aspirin 81mg"
        assert defaults["dismissed_by"] == "Reconciler Bot"
        assert defaults["dismissed_by_id"] == "plugin:med_reconciler"

    @patch("surescripts_med_history.protocols.integration_api.MedicationDismissal")
    @patch("surescripts_med_history.protocols.integration_api.Patient")
    def test_drug_description_defaults_to_empty(
        self, mock_patient_cls, mock_dismissal_cls
    ):
        mock_patient_cls.DoesNotExist = _FakeDoesNotExist
        mock_patient_cls.objects.values_list.return_value.get.return_value = 42

        handler = _make_handler(
            body={
                "patient_id": "p1",
                "group_key": "desc:Unknown",
                "dismissed_by": "Bot",
                "dismissed_by_id": "bot-1",
            }
        )
        results = handler.create_dismissal()
        assert results[0].status_code == HTTPStatus.OK
        defaults = mock_dismissal_cls.objects.update_or_create.call_args.kwargs[
            "defaults"
        ]
        assert defaults["drug_description"] == ""
