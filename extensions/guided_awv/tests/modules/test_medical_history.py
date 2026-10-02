"""Tests for MedicalHistoryModule."""

from unittest.mock import MagicMock, patch, call

from guided_awv.modules.base import AWVType
from guided_awv.modules.medical_history import MedicalHistoryModule


def _mock_condition_filter(medical_results: list, surgical_results: list) -> MagicMock:
    """Create a Condition.objects mock that returns different results for two filter() calls."""
    mock_cond = MagicMock()

    medical_qs = MagicMock()
    medical_qs.select_related.return_value.values.return_value.order_by.return_value = medical_results

    surgical_qs = MagicMock()
    surgical_qs.select_related.return_value.values.return_value.order_by.return_value = surgical_results

    mock_cond.filter.side_effect = [medical_qs, surgical_qs]
    return mock_cond


class TestMedicalHistoryModule:
    """Tests for MedicalHistoryModule."""

    @patch("guided_awv.modules.medical_history.AllergyIntolerance.objects")
    @patch("guided_awv.modules.medical_history.MedicationStatement.objects")
    @patch("guided_awv.modules.medical_history.Condition.objects")
    def test_get_context_initial(
        self,
        mock_cond: MagicMock,
        mock_med: MagicMock,
        mock_allergy: MagicMock,
    ) -> None:
        """get_context returns conditions, medications, allergies for initial AWV."""
        medical_qs = MagicMock()
        medical_qs.select_related.return_value.values.return_value.order_by.return_value = [
            {"id": "c1", "codings__display": "Hypertension", "onset_date": "2020-01-01"},
        ]
        surgical_qs = MagicMock()
        surgical_qs.select_related.return_value.values.return_value.order_by.return_value = [
            {"id": "c2", "codings__display": "Knee Replacement", "onset_date": "2019-06-15", "resolution_date": "2019-06-15", "clinical_status": "resolved"},
        ]
        mock_cond.filter.side_effect = [medical_qs, surgical_qs]
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = [
            {"id": "m1", "medication__codings__display": "Lisinopril", "sig_original_input": "10mg daily"},
        ]
        mock_allergy.filter.return_value.values.return_value.order_by.return_value = [
            {"id": "a1", "codings__display": "Penicillin", "narrative": "Rash"},
        ]

        module = MedicalHistoryModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()

        assert context["is_initial"] is True
        assert context["medical_count"] == 1
        assert context["surgical_count"] == 1
        assert context["medication_count"] == 1
        assert context["allergy_count"] == 1

    @patch("guided_awv.modules.medical_history.AllergyIntolerance.objects")
    @patch("guided_awv.modules.medical_history.MedicationStatement.objects")
    @patch("guided_awv.modules.medical_history.Condition.objects")
    def test_get_context_subsequent(
        self,
        mock_cond: MagicMock,
        mock_med: MagicMock,
        mock_allergy: MagicMock,
    ) -> None:
        """get_context is_initial is False for subsequent AWV."""
        mock_cond.filter.side_effect = [
            MagicMock(**{"select_related.return_value.values.return_value.order_by.return_value": []}),
            MagicMock(**{"select_related.return_value.values.return_value.order_by.return_value": []}),
        ]
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = []
        mock_allergy.filter.return_value.values.return_value.order_by.return_value = []

        module = MedicalHistoryModule("note-1", "patient-1", AWVType.SUBSEQUENT)
        context = module.get_context()

        assert context["is_initial"] is False

    @patch("guided_awv.modules.medical_history.AllergyIntolerance.objects")
    @patch("guided_awv.modules.medical_history.MedicationStatement.objects")
    @patch("guided_awv.modules.medical_history.Condition.objects")
    def test_get_context_empty_lists(
        self,
        mock_cond: MagicMock,
        mock_med: MagicMock,
        mock_allergy: MagicMock,
    ) -> None:
        """get_context handles empty DB results gracefully."""
        mock_cond.filter.side_effect = [
            MagicMock(**{"select_related.return_value.values.return_value.order_by.return_value": []}),
            MagicMock(**{"select_related.return_value.values.return_value.order_by.return_value": []}),
        ]
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = []
        mock_allergy.filter.return_value.values.return_value.order_by.return_value = []

        module = MedicalHistoryModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()

        assert context["medical_count"] == 0
        assert context["surgical_count"] == 0
        assert context["medication_count"] == 0
        assert context["allergy_count"] == 0

    @patch("guided_awv.modules.medical_history.AllergyIntolerance.objects")
    @patch("guided_awv.modules.medical_history.MedicationStatement.objects")
    @patch("guided_awv.modules.medical_history.Condition.objects")
    def test_surgical_query_includes_all_statuses(
        self,
        mock_cond: MagicMock,
        mock_med: MagicMock,
        mock_allergy: MagicMock,
    ) -> None:
        """Surgical query does not filter by clinical_status (includes resolved surgeries)."""
        mock_cond.filter.side_effect = [
            MagicMock(**{"select_related.return_value.values.return_value.order_by.return_value": []}),
            MagicMock(**{"select_related.return_value.values.return_value.order_by.return_value": [
                {"id": "s1", "codings__display": "Appendectomy", "onset_date": "2015-03-01", "resolution_date": "2015-03-01", "clinical_status": "resolved"},
            ]}),
        ]
        mock_med.filter.return_value.select_related.return_value.values.return_value.order_by.return_value = []
        mock_allergy.filter.return_value.values.return_value.order_by.return_value = []

        module = MedicalHistoryModule("note-1", "patient-1", AWVType.INITIAL)
        context = module.get_context()

        assert context["surgical_count"] == 1
        assert context["surgical_conditions"][0]["codings__display"] == "Appendectomy"
        # Verify the surgical filter call does NOT include clinical_status
        surgical_call = mock_cond.filter.call_args_list[1]
        assert "clinical_status" not in surgical_call.kwargs

    def test_initial_title(self) -> None:
        """Initial AWV shows 'Complete Capture' in title."""
        module = MedicalHistoryModule("note-1", "patient-1", AWVType.INITIAL)
        assert "Complete Capture" in module.TITLE

    def test_subsequent_title(self) -> None:
        """Subsequent AWV shows 'Review & Update' in title."""
        module = MedicalHistoryModule("note-1", "patient-1", AWVType.SUBSEQUENT)
        assert "Review & Update" in module.TITLE
