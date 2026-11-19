import json
from datetime import datetime
from unittest.mock import MagicMock, patch

from surescripts_med_history.protocols.action_button import (
    _build_active_code_sets,
    _build_history_item,
    _group_history_items,
    _is_matched,
    _request_status,
    RXNORM_SYSTEM,
    NDC_SYSTEM,
)


def _make_coding(system, code, display=""):
    c = MagicMock()
    c.system = system
    c.code = code
    c.display = display
    return c


def _make_med(codings, ndc=None, clin_desc=None, qty_desc=None):
    med = MagicMock()
    med.codings.all.return_value = codings
    med.national_drug_code = ndc
    med.clinical_quantity_description = clin_desc
    med.quantity_qualifier_description = qty_desc
    return med


def _make_history_med(
    drug_description="Test Drug",
    codings=None,
    last_fill_date=None,
    written_date=None,
    strength_value="10",
    strength_unit_of_measure="mg",
    strength_form="tablet",
    prescriber_first_name="Jane",
    prescriber_last_name="Doe",
    pharmacy_name="CVS",
    source_description="Pharmacy",
    source_type="Fill",
    sig="",
    created=None,
):
    med = MagicMock()
    med.drug_description = drug_description
    med.codings.all.return_value = codings or []
    med.last_fill_date = last_fill_date
    med.written_date = written_date
    med.strength_value = strength_value
    med.strength_unit_of_measure = strength_unit_of_measure
    med.strength_form = strength_form
    med.prescriber_first_name = prescriber_first_name
    med.prescriber_last_name = prescriber_last_name
    med.pharmacy_name = pharmacy_name
    med.source_description = source_description
    med.source_type = source_type
    med.sig = sig
    med.created = created
    return med


class TestBuildActiveCodeSets:
    def test_extracts_rxnorm_codes(self):
        coding = _make_coding(RXNORM_SYSTEM, "12345")
        med = _make_med([coding])
        rxnorm, ndc, descs = _build_active_code_sets([med])
        assert "12345" in rxnorm

    def test_extracts_ndc_codes_strips_dashes(self):
        coding = _make_coding(NDC_SYSTEM, "0093-0054-01")
        med = _make_med([coding])
        rxnorm, ndc, descs = _build_active_code_sets([med])
        assert "0093005401" in ndc

    def test_extracts_ndc_from_national_drug_code_field(self):
        med = _make_med([], ndc="12345-678-90")
        rxnorm, ndc, descs = _build_active_code_sets([med])
        assert "1234567890" in ndc

    def test_extracts_descriptions_over_10_chars(self):
        coding = _make_coding(RXNORM_SYSTEM, "123", display="Buspirone HCl 10mg tablet")
        med = _make_med([coding], clin_desc="buspirone hydrochloride")
        rxnorm, ndc, descs = _build_active_code_sets([med])
        assert "buspirone hcl 10mg tablet" in descs
        assert "buspirone hydrochloride" in descs

    def test_ignores_short_descriptions(self):
        coding = _make_coding(RXNORM_SYSTEM, "123", display="Short")
        med = _make_med([coding])
        rxnorm, ndc, descs = _build_active_code_sets([med])
        assert len(descs) == 0


class TestIsMatched:
    def test_matches_by_rxnorm(self):
        coding = _make_coding(RXNORM_SYSTEM, "866083")
        med = _make_history_med(codings=[coding])
        matched, method = _is_matched(med, {"866083"}, set(), [])
        assert matched is True
        assert method == "rxnorm"

    def test_matches_by_ndc(self):
        coding = _make_coding(NDC_SYSTEM, "0093-0054-01")
        med = _make_history_med(codings=[coding])
        matched, method = _is_matched(med, set(), {"0093005401"}, [])
        assert matched is True
        assert method == "ndc"

    def test_matches_by_description_substring(self):
        med = _make_history_med(drug_description="buspirone HCl 10 mg")
        matched, method = _is_matched(
            med, set(), set(), ["buspirone hcl 10 mg tablet oral"]
        )
        assert matched is True
        assert method == "description"

    def test_no_match(self):
        med = _make_history_med(drug_description="unknown drug", codings=[])
        matched, method = _is_matched(med, set(), set(), [])
        assert matched is False
        assert method == ""

    def test_description_match_is_case_insensitive(self):
        med = _make_history_med(drug_description="Buspirone HCl")
        matched, _ = _is_matched(med, set(), set(), ["buspirone hcl 10 mg tablet"])
        assert matched is True


class TestBuildHistoryItem:
    def test_builds_item_with_all_fields(self):
        coding_rxnorm = _make_coding(RXNORM_SYSTEM, "866083")
        coding_ndc = _make_coding(NDC_SYSTEM, "00930054")
        med = _make_history_med(
            drug_description="buspirone HCl 10 mg",
            codings=[coding_rxnorm, coding_ndc],
            last_fill_date=datetime(2023, 1, 25),
            written_date=datetime(2023, 1, 15),
            pharmacy_name="CVS Pharmacy",
            source_description="Pharmacy",
            source_type="Fill",
        )
        item = _build_history_item(med, is_match=True)
        assert item["drug_description"] == "buspirone HCl 10 mg"
        assert item["is_match"] is True
        assert "866083" in item["rxnorm_codes"]
        assert "00930054" in item["ndc_codes"]
        assert item["pharmacy_name"] == "CVS Pharmacy"
        assert item["source_description"] == "Pharmacy"
        assert item["source_type"] == "Fill"
        assert "Jan 25, 2023" in item["last_fill_date"]
        assert "Jan 15, 2023" in item["written_date"]

    def test_handles_null_dates(self):
        med = _make_history_med(last_fill_date=None, written_date=None, codings=[])
        item = _build_history_item(med, is_match=False)
        assert item["last_fill_date"] == ""
        assert item["written_date"] == ""


class TestGroupHistoryItems:
    def test_groups_by_ndc_merges_claim_and_fill(self):
        items = [
            {
                "drug_description": "DRUG TAB 4MG",
                "strength": "4.000",
                "is_match": False,
                "rxnorm_codes": [],
                "ndc_codes": ["12345"],
                "sig": "",
                "last_fill_date": "Jan 2023",
                "last_fill_date_sort": "2023-01",
                "written_date": "",
                "prescriber": "",
                "pharmacy_name": "CVS",
                "source_description": "CVS Caremark",
                "source_type": "Claim",
            },
            {
                "drug_description": "DRUG 4MG TABLETS",
                "strength": "",
                "is_match": False,
                "rxnorm_codes": [],
                "ndc_codes": ["12345"],
                "sig": "Take 1 daily",
                "last_fill_date": "Jan 2023",
                "last_fill_date_sort": "2023-01",
                "written_date": "Jan 2023",
                "prescriber": "Dr. Smith",
                "pharmacy_name": "CVS",
                "source_description": "CVS",
                "source_type": "Fill",
            },
        ]
        groups = _group_history_items(items)
        assert len(groups) == 1
        assert len(groups[0]["fills"]) == 2
        assert groups[0]["drug_description"] == "DRUG TAB 4MG"
        assert groups[0]["sig"] == "Take 1 daily"

    def test_claim_description_preferred_even_if_fill_comes_first(self):
        items = [
            {
                "drug_description": "DRUG 4MG TABLETS",
                "strength": "",
                "is_match": False,
                "rxnorm_codes": [],
                "ndc_codes": ["12345"],
                "sig": "Take 1 daily",
                "last_fill_date": "Jan 2023",
                "last_fill_date_sort": "2023-01",
                "written_date": "",
                "prescriber": "",
                "pharmacy_name": "",
                "source_description": "",
                "source_type": "Fill",
            },
            {
                "drug_description": "DRUG TAB 4MG",
                "strength": "4.000",
                "is_match": False,
                "rxnorm_codes": [],
                "ndc_codes": ["12345"],
                "sig": "",
                "last_fill_date": "Jan 2023",
                "last_fill_date_sort": "2023-01",
                "written_date": "",
                "prescriber": "",
                "pharmacy_name": "",
                "source_description": "",
                "source_type": "Claim",
            },
        ]
        groups = _group_history_items(items)
        assert groups[0]["drug_description"] == "DRUG TAB 4MG"

    def test_falls_back_to_drug_description_when_no_ndc(self):
        items = [
            {
                "drug_description": "Drug A",
                "strength": "",
                "is_match": False,
                "rxnorm_codes": [],
                "ndc_codes": [],
                "sig": "",
                "last_fill_date": "Jan 2023",
                "last_fill_date_sort": "2023-01",
                "written_date": "",
                "prescriber": "",
                "pharmacy_name": "",
                "source_description": "",
                "source_type": "",
            },
            {
                "drug_description": "Drug B",
                "strength": "",
                "is_match": False,
                "rxnorm_codes": [],
                "ndc_codes": [],
                "sig": "",
                "last_fill_date": "Feb 2023",
                "last_fill_date_sort": "2023-02",
                "written_date": "",
                "prescriber": "",
                "pharmacy_name": "",
                "source_description": "",
                "source_type": "",
            },
        ]
        groups = _group_history_items(items)
        assert len(groups) == 2

    def test_group_is_matched_if_any_fill_matches(self):
        items = [
            {
                "drug_description": "Drug A",
                "strength": "10 mg",
                "is_match": False,
                "rxnorm_codes": [],
                "ndc_codes": [],
                "sig": "",
                "last_fill_date": "",
                "last_fill_date_sort": "",
                "written_date": "",
                "prescriber": "",
                "pharmacy_name": "",
                "source_description": "",
                "source_type": "",
            },
            {
                "drug_description": "Drug A",
                "strength": "10 mg",
                "is_match": True,
                "rxnorm_codes": [],
                "ndc_codes": [],
                "sig": "",
                "last_fill_date": "",
                "last_fill_date_sort": "",
                "written_date": "",
                "prescriber": "",
                "pharmacy_name": "",
                "source_description": "",
                "source_type": "",
            },
        ]
        groups = _group_history_items(items)
        assert groups[0]["is_match"] is True

    def test_sorts_by_latest_fill_date_desc(self):
        items = [
            {
                "drug_description": "Old Drug",
                "strength": "",
                "is_match": False,
                "rxnorm_codes": [],
                "ndc_codes": [],
                "sig": "",
                "last_fill_date": "Jan 2022",
                "last_fill_date_sort": "2022-01",
                "written_date": "",
                "prescriber": "",
                "pharmacy_name": "",
                "source_description": "",
                "source_type": "",
            },
            {
                "drug_description": "New Drug",
                "strength": "",
                "is_match": False,
                "rxnorm_codes": [],
                "ndc_codes": [],
                "sig": "",
                "last_fill_date": "Mar 2023",
                "last_fill_date_sort": "2023-03",
                "written_date": "",
                "prescriber": "",
                "pharmacy_name": "",
                "source_description": "",
                "source_type": "",
            },
        ]
        groups = _group_history_items(items)
        assert groups[0]["drug_description"] == "New Drug"
        assert groups[1]["drug_description"] == "Old Drug"

    def test_merges_codes_across_fills(self):
        items = [
            {
                "drug_description": "Drug A",
                "strength": "",
                "is_match": False,
                "rxnorm_codes": ["111"],
                "ndc_codes": ["AAA"],
                "sig": "",
                "last_fill_date": "",
                "last_fill_date_sort": "",
                "written_date": "",
                "prescriber": "",
                "pharmacy_name": "",
                "source_description": "",
                "source_type": "",
            },
            {
                "drug_description": "Drug A",
                "strength": "",
                "is_match": False,
                "rxnorm_codes": ["222"],
                "ndc_codes": ["AAA"],
                "sig": "",
                "last_fill_date": "",
                "last_fill_date_sort": "",
                "written_date": "",
                "prescriber": "",
                "pharmacy_name": "",
                "source_description": "",
                "source_type": "",
            },
        ]
        groups = _group_history_items(items)
        assert "111" in groups[0]["rxnorm_codes"]
        assert "222" in groups[0]["rxnorm_codes"]
        assert groups[0]["ndc_codes"].count("AAA") == 1

    def test_unique_fill_count_deduplicates_same_date(self):
        items = [
            {
                "drug_description": "DRUG TAB",
                "strength": "",
                "is_match": False,
                "rxnorm_codes": [],
                "ndc_codes": ["12345"],
                "sig": "",
                "last_fill_date": "Jan 15, 2023",
                "last_fill_date_sort": "2023-01-15",
                "written_date": "",
                "prescriber": "",
                "pharmacy_name": "",
                "source_description": "",
                "source_type": "Claim",
            },
            {
                "drug_description": "DRUG TABLETS",
                "strength": "",
                "is_match": False,
                "rxnorm_codes": [],
                "ndc_codes": ["12345"],
                "sig": "",
                "last_fill_date": "Jan 15, 2023",
                "last_fill_date_sort": "2023-01-15",
                "written_date": "",
                "prescriber": "",
                "pharmacy_name": "",
                "source_description": "",
                "source_type": "Fill",
            },
        ]
        groups = _group_history_items(items)
        assert groups[0]["unique_fill_count"] == 1


class TestMedHistoryActionButtonRendering:
    @patch(
        "surescripts_med_history.protocols.action_button._spi_provider_choices",
        return_value=[],
    )
    @patch(
        "surescripts_med_history.protocols.action_button._last_requested_display",
        return_value="",
    )
    @patch(
        "surescripts_med_history.protocols.action_button._request_status",
        return_value={
            "state": "no_data",
            "detail": "",
            "last_response_at": "",
            "response_provider": "",
        },
    )
    @patch("surescripts_med_history.protocols.action_button.MedicationDismissal")
    @patch("surescripts_med_history.protocols.action_button.render_to_string")
    @patch("surescripts_med_history.protocols.action_button.Medication")
    @patch(
        "surescripts_med_history.protocols.action_button.MedicationHistoryMedication"
    )
    @patch("surescripts_med_history.protocols.action_button.Patient")
    def test_renders_grouped_items_and_last_pulled(
        self,
        mock_patient_cls,
        mock_hist_cls,
        mock_med_cls,
        mock_render,
        mock_dismissal_cls,
        mock_status,
        mock_last_req,
        mock_providers,
    ):
        patient = MagicMock()
        patient.default_provider = MagicMock()
        mock_patient_cls.objects.select_related.return_value.get.return_value = patient

        history_med = _make_history_med(
            drug_description="Test Drug",
            codings=[_make_coding(RXNORM_SYSTEM, "123")],
            last_fill_date=datetime(2023, 1, 25),
            created=datetime(2026, 3, 28, 10, 30),
        )
        mock_hist_qs = MagicMock()
        mock_hist_cls.objects.filter.return_value = mock_hist_qs
        mock_hist_qs.prefetch_related.return_value = mock_hist_qs
        mock_hist_qs.order_by.return_value = mock_hist_qs
        mock_hist_qs.__getitem__ = MagicMock(return_value=[history_med])

        mock_active_qs = MagicMock()
        mock_med_cls.objects.active.return_value = mock_active_qs
        mock_active_qs.filter.return_value = mock_active_qs
        mock_active_qs.prefetch_related.return_value = iter([])

        mock_dismissal_cls.objects.filter.return_value = []

        mock_render.return_value = "<html>test</html>"

        from surescripts_med_history.protocols.action_button import (
            MedHistoryActionButton,
        )

        handler = MedHistoryActionButton(
            event=MagicMock(target=MagicMock(id="patient-1"))
        )
        effects = handler.handle()

        assert len(effects) == 1
        ctx = mock_render.call_args[0][1]
        assert "grouped_items_json" in ctx
        assert "last_pulled" in ctx
        # ISO so the browser can render it in the viewer's timezone.
        assert ctx["last_pulled"].startswith("2026-03-28T10:30")

        groups = json.loads(ctx["grouped_items_json"])
        assert len(groups) == 1
        assert groups[0]["drug_description"] == "Test Drug"
        assert len(groups[0]["fills"]) == 1

    @patch("surescripts_med_history.protocols.action_button.Patient")
    def test_returns_empty_when_no_patient_id(self, mock_patient_cls):
        from surescripts_med_history.protocols.action_button import (
            MedHistoryActionButton,
        )

        handler = MedHistoryActionButton(event=MagicMock(target=MagicMock(id="")))
        effects = handler.handle()
        assert effects == []

    @patch(
        "surescripts_med_history.protocols.action_button.MedicationHistoryMedication"
    )
    @patch("surescripts_med_history.protocols.action_button.Patient")
    def test_returns_empty_when_patient_not_found(
        self, mock_patient_cls, mock_hist_cls
    ):
        class _FakeDoesNotExist(Exception):
            pass

        mock_patient_cls.DoesNotExist = _FakeDoesNotExist
        mock_patient_cls.objects.select_related.return_value.get.side_effect = (
            _FakeDoesNotExist("not found")
        )

        from surescripts_med_history.protocols.action_button import (
            MedHistoryActionButton,
        )

        handler = MedHistoryActionButton(
            event=MagicMock(target=MagicMock(id="missing"))
        )
        effects = handler.handle()
        assert effects == []

    @patch(
        "surescripts_med_history.protocols.action_button._spi_provider_choices",
        return_value=[],
    )
    @patch(
        "surescripts_med_history.protocols.action_button._last_requested_display",
        return_value="",
    )
    @patch(
        "surescripts_med_history.protocols.action_button._request_status",
        return_value={
            "state": "no_data",
            "detail": "",
            "last_response_at": "",
            "response_provider": "",
        },
    )
    @patch("surescripts_med_history.protocols.action_button.MedicationDismissal")
    @patch("surescripts_med_history.protocols.action_button.render_to_string")
    @patch("surescripts_med_history.protocols.action_button.Medication")
    @patch(
        "surescripts_med_history.protocols.action_button.MedicationHistoryMedication"
    )
    @patch("surescripts_med_history.protocols.action_button.Patient")
    def test_last_pulled_empty_when_no_history(
        self,
        mock_patient_cls,
        mock_hist_cls,
        mock_med_cls,
        mock_render,
        mock_dismissal_cls,
        mock_status,
        mock_last_req,
        mock_providers,
    ):
        patient = MagicMock()
        patient.default_provider = MagicMock()
        mock_patient_cls.objects.select_related.return_value.get.return_value = patient

        mock_hist_qs = MagicMock()
        mock_hist_cls.objects.filter.return_value = mock_hist_qs
        mock_hist_qs.prefetch_related.return_value = mock_hist_qs
        mock_hist_qs.order_by.return_value = mock_hist_qs
        mock_hist_qs.__getitem__ = MagicMock(return_value=[])

        mock_active_qs = MagicMock()
        mock_med_cls.objects.active.return_value = mock_active_qs
        mock_active_qs.filter.return_value = mock_active_qs
        mock_active_qs.prefetch_related.return_value = iter([])

        mock_dismissal_cls.objects.filter.return_value = []

        mock_render.return_value = "<html>test</html>"

        from surescripts_med_history.protocols.action_button import (
            MedHistoryActionButton,
        )

        handler = MedHistoryActionButton(
            event=MagicMock(target=MagicMock(id="patient-1"))
        )
        handler.handle()

        ctx = mock_render.call_args[0][1]
        assert ctx["last_pulled"] == ""

    def _setup_minimal(self, mock_patient_cls, mock_hist_cls, mock_med_cls, mock_dismissal_cls):
        patient = MagicMock()
        patient.default_provider = None  # no default provider on this patient
        mock_patient_cls.objects.select_related.return_value.get.return_value = patient
        mock_hist_qs = MagicMock()
        mock_hist_cls.objects.filter.return_value = mock_hist_qs
        mock_hist_qs.prefetch_related.return_value = mock_hist_qs
        mock_hist_qs.order_by.return_value = mock_hist_qs
        mock_hist_qs.__getitem__ = MagicMock(return_value=[])
        mock_active_qs = MagicMock()
        mock_med_cls.objects.active.return_value = mock_active_qs
        mock_active_qs.filter.return_value = mock_active_qs
        mock_active_qs.prefetch_related.return_value = iter([])
        mock_dismissal_cls.objects.filter.return_value = []

    @patch(
        "surescripts_med_history.protocols.action_button._last_requested_display",
        return_value="",
    )
    @patch(
        "surescripts_med_history.protocols.action_button._request_status",
        return_value={"state": "no_data", "detail": "", "last_response_at": "", "response_provider": ""},
    )
    @patch(
        "surescripts_med_history.protocols.action_button._spi_provider_choices",
        return_value=[{"id": "s1", "name": "Doe, Ann"}],
    )
    @patch("surescripts_med_history.protocols.action_button.MedicationDismissal")
    @patch("surescripts_med_history.protocols.action_button.render_to_string")
    @patch("surescripts_med_history.protocols.action_button.Medication")
    @patch("surescripts_med_history.protocols.action_button.MedicationHistoryMedication")
    @patch("surescripts_med_history.protocols.action_button.Patient")
    def test_can_request_true_when_spi_providers_exist(
        self, mock_patient_cls, mock_hist_cls, mock_med_cls, mock_render, mock_dismissal_cls,
        mock_providers, mock_status, mock_last_req,
    ):
        # Neither logged-in user nor default provider has an SPI, but providers
        # exist — the dropdown should still be available.
        self._setup_minimal(mock_patient_cls, mock_hist_cls, mock_med_cls, mock_dismissal_cls)
        mock_render.return_value = "<html></html>"

        from surescripts_med_history.protocols.action_button import MedHistoryActionButton

        MedHistoryActionButton(event=MagicMock(target=MagicMock(id="p1"))).handle()
        ctx = mock_render.call_args[0][1]
        assert ctx["can_request"] is True
        assert ctx["default_staff_id"] == "s1"  # falls back to first provider
        # Logged-in user has no SPI here → picker is shown so they can choose.
        assert ctx["show_provider_select"] is True

    @patch("surescripts_med_history.protocols.action_button.Staff")
    @patch(
        "surescripts_med_history.protocols.action_button._last_requested_display",
        return_value="",
    )
    @patch(
        "surescripts_med_history.protocols.action_button._request_status",
        return_value={"state": "no_data", "detail": "", "last_response_at": "", "response_provider": ""},
    )
    @patch(
        "surescripts_med_history.protocols.action_button._spi_provider_choices",
        return_value=[{"id": "prov-uuid", "name": "Best, Wayne"}],
    )
    @patch("surescripts_med_history.protocols.action_button.MedicationDismissal")
    @patch("surescripts_med_history.protocols.action_button.render_to_string")
    @patch("surescripts_med_history.protocols.action_button.Medication")
    @patch("surescripts_med_history.protocols.action_button.MedicationHistoryMedication")
    @patch("surescripts_med_history.protocols.action_button.Patient")
    def test_picker_hidden_and_defaults_to_logged_in_spi_provider(
        self, mock_patient_cls, mock_hist_cls, mock_med_cls, mock_render, mock_dismissal_cls,
        mock_providers, mock_status, mock_last_req, mock_staff_cls,
    ):
        self._setup_minimal(mock_patient_cls, mock_hist_cls, mock_med_cls, mock_dismissal_cls)
        mock_render.return_value = "<html></html>"
        # Logged-in actor IS an SPI-registered provider.
        mock_staff_cls.DoesNotExist = Exception
        spi_staff = MagicMock(id="prov-uuid")
        spi_staff.spi_number = "999"
        mock_staff_cls.objects.get.return_value = spi_staff

        from surescripts_med_history.protocols.action_button import MedHistoryActionButton

        event = MagicMock()
        event.target.id = "p1"
        event.actor.id = "5"  # int-castable → actor SPI lookup runs
        MedHistoryActionButton(event=event).handle()

        ctx = mock_render.call_args[0][1]
        assert ctx["can_request"] is True
        assert ctx["show_provider_select"] is False  # prescriber requests as self
        assert ctx["default_staff_id"] == "prov-uuid"

    @patch(
        "surescripts_med_history.protocols.action_button._last_requested_display",
        return_value="",
    )
    @patch(
        "surescripts_med_history.protocols.action_button._request_status",
        return_value={"state": "no_data", "detail": "", "last_response_at": "", "response_provider": ""},
    )
    @patch(
        "surescripts_med_history.protocols.action_button._spi_provider_choices",
        return_value=[],
    )
    @patch("surescripts_med_history.protocols.action_button.MedicationDismissal")
    @patch("surescripts_med_history.protocols.action_button.render_to_string")
    @patch("surescripts_med_history.protocols.action_button.Medication")
    @patch("surescripts_med_history.protocols.action_button.MedicationHistoryMedication")
    @patch("surescripts_med_history.protocols.action_button.Patient")
    def test_can_request_false_when_no_spi_providers(
        self, mock_patient_cls, mock_hist_cls, mock_med_cls, mock_render, mock_dismissal_cls,
        mock_providers, mock_status, mock_last_req,
    ):
        self._setup_minimal(mock_patient_cls, mock_hist_cls, mock_med_cls, mock_dismissal_cls)
        mock_render.return_value = "<html></html>"

        from surescripts_med_history.protocols.action_button import MedHistoryActionButton

        MedHistoryActionButton(event=MagicMock(target=MagicMock(id="p1"))).handle()
        ctx = mock_render.call_args[0][1]
        assert ctx["can_request"] is False


class TestStaleDismissalCleanup:
    """Regression: MedicationDismissal is a CustomModel keyed by `dbid`, not
    `id`. Using `id__in=` on the queryset raises FieldError at runtime."""

    @patch(
        "surescripts_med_history.protocols.action_button._spi_provider_choices",
        return_value=[],
    )
    @patch(
        "surescripts_med_history.protocols.action_button._last_requested_display",
        return_value="",
    )
    @patch(
        "surescripts_med_history.protocols.action_button._request_status",
        return_value={
            "state": "no_data",
            "detail": "",
            "last_response_at": "",
            "response_provider": "",
        },
    )
    @patch("surescripts_med_history.protocols.action_button.MedicationDismissal")
    @patch("surescripts_med_history.protocols.action_button.render_to_string")
    @patch("surescripts_med_history.protocols.action_button.Medication")
    @patch(
        "surescripts_med_history.protocols.action_button.MedicationHistoryMedication"
    )
    @patch("surescripts_med_history.protocols.action_button.Patient")
    def test_clears_dismissal_when_history_now_matches_active_med(
        self,
        mock_patient_cls,
        mock_hist_cls,
        mock_med_cls,
        mock_render,
        mock_dismissal_cls,
        mock_status,
        mock_last_req,
        mock_providers,
    ):
        patient = MagicMock()
        patient.dbid = 42
        patient.default_provider = MagicMock()
        mock_patient_cls.objects.select_related.return_value.get.return_value = patient

        # History med and active med share an RxNorm code -> is_match=True,
        # which marks the existing dismissal stale.
        history_med = _make_history_med(
            drug_description="Aspirin 81mg",
            codings=[_make_coding(RXNORM_SYSTEM, "243670")],
            last_fill_date=datetime(2026, 4, 1),
        )
        mock_hist_qs = MagicMock()
        mock_hist_cls.objects.filter.return_value = mock_hist_qs
        mock_hist_qs.prefetch_related.return_value = mock_hist_qs
        mock_hist_qs.order_by.return_value = mock_hist_qs
        mock_hist_qs.__getitem__ = MagicMock(return_value=[history_med])

        active_med = _make_med([_make_coding(RXNORM_SYSTEM, "243670")])
        mock_active_qs = MagicMock()
        mock_med_cls.objects.active.return_value = mock_active_qs
        mock_active_qs.filter.return_value = mock_active_qs
        mock_active_qs.prefetch_related.return_value = iter([active_med])

        dismissal = MagicMock()
        dismissal.group_key = "desc:Aspirin 81mg"
        dismissal.dbid = 99
        dismissal.dismissed_at = datetime(2026, 3, 1)

        dismissals_qs = MagicMock()
        dismissals_qs.__iter__ = lambda self: iter([dismissal])
        delete_qs = MagicMock()
        mock_dismissal_cls.objects.filter.side_effect = [dismissals_qs, delete_qs]

        mock_render.return_value = "<html>test</html>"

        from surescripts_med_history.protocols.action_button import (
            MedHistoryActionButton,
        )

        handler = MedHistoryActionButton(
            event=MagicMock(target=MagicMock(id="patient-1"))
        )
        handler.handle()

        calls = mock_dismissal_cls.objects.filter.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs == {"patient_id": 42}
        # The regression: must be dbid__in, never id__in
        assert calls[1].kwargs == {"dbid__in": [99]}
        delete_qs.delete.assert_called_once()

    @patch(
        "surescripts_med_history.protocols.action_button._spi_provider_choices",
        return_value=[],
    )
    @patch(
        "surescripts_med_history.protocols.action_button._last_requested_display",
        return_value="",
    )
    @patch(
        "surescripts_med_history.protocols.action_button._request_status",
        return_value={
            "state": "no_data",
            "detail": "",
            "last_response_at": "",
            "response_provider": "",
        },
    )
    @patch("surescripts_med_history.protocols.action_button.MedicationDismissal")
    @patch("surescripts_med_history.protocols.action_button.render_to_string")
    @patch("surescripts_med_history.protocols.action_button.Medication")
    @patch(
        "surescripts_med_history.protocols.action_button.MedicationHistoryMedication"
    )
    @patch("surescripts_med_history.protocols.action_button.Patient")
    def test_keeps_dismissal_when_no_match_and_no_newer_fill(
        self,
        mock_patient_cls,
        mock_hist_cls,
        mock_med_cls,
        mock_render,
        mock_dismissal_cls,
        mock_status,
        mock_last_req,
        mock_providers,
    ):
        patient = MagicMock()
        patient.dbid = 42
        patient.default_provider = MagicMock()
        mock_patient_cls.objects.select_related.return_value.get.return_value = patient

        # History med doesn't match any active med — dismissal stays.
        history_med = _make_history_med(
            drug_description="Metformin 500mg",
            codings=[_make_coding(RXNORM_SYSTEM, "860975")],
            last_fill_date=datetime(2026, 1, 15),
        )
        mock_hist_qs = MagicMock()
        mock_hist_cls.objects.filter.return_value = mock_hist_qs
        mock_hist_qs.prefetch_related.return_value = mock_hist_qs
        mock_hist_qs.order_by.return_value = mock_hist_qs
        mock_hist_qs.__getitem__ = MagicMock(return_value=[history_med])

        mock_active_qs = MagicMock()
        mock_med_cls.objects.active.return_value = mock_active_qs
        mock_active_qs.filter.return_value = mock_active_qs
        mock_active_qs.prefetch_related.return_value = iter([])

        # Dismissed AFTER the latest fill -> no auto-clear.
        dismissal = MagicMock()
        dismissal.group_key = "desc:Metformin 500mg"
        dismissal.dbid = 7
        dismissal.dismissed_at = datetime(2026, 3, 1)
        dismissal.dismissed_by = "Anna Smith"

        dismissals_qs = MagicMock()
        dismissals_qs.__iter__ = lambda self: iter([dismissal])
        mock_dismissal_cls.objects.filter.return_value = dismissals_qs

        mock_render.return_value = "<html>test</html>"

        from surescripts_med_history.protocols.action_button import (
            MedHistoryActionButton,
        )

        handler = MedHistoryActionButton(
            event=MagicMock(target=MagicMock(id="patient-1"))
        )
        handler.handle()

        # Only the initial fetch — no delete pass.
        assert mock_dismissal_cls.objects.filter.call_count == 1


def _set_latest_response(mock_response_cls, response):
    """Wire the MedicationHistoryResponse query chain to return `response`."""
    (
        mock_response_cls.objects.filter.return_value.select_related.return_value.order_by.return_value.first.return_value
    ) = response


def _make_response(status="approved", reason="", reason_code="", created=None, staff=None):
    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    resp.reason_code = reason_code
    resp.created = created
    resp.staff = staff
    return resp


class TestRequestStatus:
    @patch("surescripts_med_history.protocols.action_button.MedicationHistoryResponse")
    def test_not_matched_uses_reason_text(self, mock_response_cls):
        staff = MagicMock(first_name="Al", last_name="Doe")
        resp = _make_response(
            status="denied",
            reason="Subscriber/Insured Not Found",
            reason_code="75",
            created=datetime(2026, 6, 1, 9, 30),
            staff=staff,
        )
        _set_latest_response(mock_response_cls, resp)

        out = _request_status(MagicMock(), has_history=False)
        assert out["state"] == "not_matched"
        assert out["detail"] == "Subscriber/Insured Not Found"
        assert out["response_provider"] == "Al Doe"
        # ISO so the browser can render it in the viewer's timezone.
        assert out["last_response_at"].startswith("2026-06-01T09:30")

    @patch("surescripts_med_history.protocols.action_button.MedicationHistoryResponse")
    def test_not_matched_falls_back_to_reason_code_label(self, mock_response_cls):
        resp = _make_response(status="denied", reason="", reason_code="75")
        _set_latest_response(mock_response_cls, resp)

        out = _request_status(MagicMock(), has_history=False)
        assert out["state"] == "not_matched"
        assert out["detail"] == "Patient could not be matched in Surescripts"

    @patch("surescripts_med_history.protocols.action_button.MedicationHistoryResponse")
    def test_matched_when_history_present(self, mock_response_cls):
        _set_latest_response(mock_response_cls, _make_response(status="approved"))
        out = _request_status(MagicMock(), has_history=True)
        assert out["state"] == "matched"

    @patch("surescripts_med_history.protocols.action_button.MedicationHistoryResponse")
    def test_matched_empty_when_response_but_no_history(self, mock_response_cls):
        _set_latest_response(mock_response_cls, _make_response(status="approved"))
        out = _request_status(MagicMock(), has_history=False)
        assert out["state"] == "matched_empty"

    @patch("surescripts_med_history.protocols.action_button.MedicationHistoryResponse")
    def test_no_data_when_no_response_and_no_history(self, mock_response_cls):
        _set_latest_response(mock_response_cls, None)
        out = _request_status(MagicMock(), has_history=False)
        assert out["state"] == "no_data"

    @patch("surescripts_med_history.protocols.action_button.MedicationHistoryResponse")
    def test_matched_when_history_present_but_no_response_row(self, mock_response_cls):
        # Older data: meds on file but no response record persisted.
        _set_latest_response(mock_response_cls, None)
        out = _request_status(MagicMock(), has_history=True)
        assert out["state"] == "matched"


class TestSpiProviderChoices:
    @patch("surescripts_med_history.protocols.action_button.Staff")
    def test_filters_active_and_spi_and_formats_names(self, mock_staff_cls):
        from surescripts_med_history.protocols.action_button import (
            _spi_provider_choices,
        )

        s1 = MagicMock(id="a", first_name="Ann", last_name="Doe")
        s2 = MagicMock(id="b", first_name="", last_name="")  # no name → skipped
        (
            mock_staff_cls.objects.filter.return_value.exclude.return_value.order_by.return_value
        ) = [s1, s2]

        out = _spi_provider_choices()

        mock_staff_cls.objects.filter.assert_called_once_with(active=True)
        mock_staff_cls.objects.filter.return_value.exclude.assert_called_once_with(
            spi_number=""
        )
        assert out == [{"id": "a", "name": "Doe, Ann"}]


class TestNdcRxnormXref:
    """The NDC→RxNorm cross-reference is a blocking FDB HTTP call per row, so
    it must be cached across rows and skipped when it can't possibly match."""

    @staticmethod
    def _fills(ndc, count):
        return [
            _make_history_med(
                drug_description="Drug %s" % ndc,
                codings=[_make_coding(NDC_SYSTEM, ndc)],
            )
            for _ in range(count)
        ]

    @patch("surescripts_med_history.protocols.action_button.ontologies_http")
    def test_distinct_ndcs_looked_up_once_each(self, mock_http):
        from surescripts_med_history.protocols.action_button import _is_matched

        resp = MagicMock()
        resp.json.return_value = {"rxnorm_rxcui": "999"}
        mock_http.get_json.return_value = resp

        # Three drugs, four fills each — twelve rows, three distinct NDCs.
        meds = self._fills("111", 4) + self._fills("222", 4) + self._fills("333", 4)
        cache = {}
        for med in meds:
            _is_matched(med, {"unrelated"}, set(), [], cache)

        assert mock_http.get_json.call_count == 3
        assert set(cache) == {"111", "222", "333"}

    @patch("surescripts_med_history.protocols.action_button.ontologies_http")
    def test_misses_are_cached_and_not_retried(self, mock_http):
        from surescripts_med_history.protocols.action_button import _is_matched

        resp = MagicMock()
        resp.json.return_value = {}  # no rxnorm_rxcui
        mock_http.get_json.return_value = resp

        cache = {}
        for med in self._fills("111", 5):
            _is_matched(med, {"unrelated"}, set(), [], cache)

        assert mock_http.get_json.call_count == 1
        assert cache == {"111": ""}

    @patch("surescripts_med_history.protocols.action_button.ontologies_http")
    def test_skipped_entirely_when_no_active_rxnorm_codes(self, mock_http):
        """No active RxNorm codes means no resolved code could ever match —
        the common case on a chart with few active meds."""
        from surescripts_med_history.protocols.action_button import _is_matched

        for med in self._fills("111", 5):
            matched, method = _is_matched(med, set(), set(), [], {})
            assert (matched, method) == (False, "")

        mock_http.get_json.assert_not_called()

    @patch("surescripts_med_history.protocols.action_button.ontologies_http")
    def test_still_matches_through_the_xref(self, mock_http):
        from surescripts_med_history.protocols.action_button import _is_matched

        resp = MagicMock()
        resp.json.return_value = {"rxnorm_rxcui": "866083"}
        mock_http.get_json.return_value = resp

        med = _make_history_med(codings=[_make_coding(NDC_SYSTEM, "111")])
        matched, method = _is_matched(med, {"866083"}, set(), [], {})

        assert matched
        assert method == "ndc_rxnorm_xref:111->866083"
