import json
from datetime import datetime
from unittest.mock import MagicMock, patch

from rx_history.protocols.action_button import (
    _build_active_code_sets,
    _build_history_item,
    _group_history_items,
    _is_matched,
    _is_matched_layered,
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

    def test_ndc_strips_non_digit_chars(self):
        """NDC codes with spaces or other non-digit chars should normalize to digits only."""
        coding = _make_coding(NDC_SYSTEM, "0093 0054/01")
        med = _make_med([coding], ndc="1234 5678 90")
        rxnorm, ndc, descs = _build_active_code_sets([med])
        assert "0093005401" in ndc
        assert "1234567890" in ndc

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

    def test_description_match_bidirectional(self):
        """Active desc shorter than history desc should still match."""
        med = _make_history_med(drug_description="buspirone HCl 10 mg oral tablet")
        matched, method = _is_matched(med, set(), set(), ["buspirone hcl 10 mg"])
        assert matched is True
        assert method == "description"

    def test_ndc_match_strips_non_digit_chars(self):
        """NDC with spaces or slashes should still match after normalization."""
        coding = _make_coding(NDC_SYSTEM, "0093 0054 01")
        med = _make_history_med(codings=[coding])
        matched, method = _is_matched(med, set(), {"0093005401"}, [])
        assert matched is True
        assert method == "ndc"


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


class TestDismissedItemFiltering:
    @patch("rx_history.protocols.action_button.Note")
    @patch("rx_history.protocols.action_button.get_dismissed_keys")
    @patch("rx_history.protocols.action_button.render_to_string")
    @patch("rx_history.protocols.action_button.Medication")
    @patch("rx_history.protocols.action_button.MedicationHistoryMedication")
    @patch("rx_history.protocols.action_button.Patient")
    def test_dismissed_items_filtered_from_grouped_items(
        self,
        mock_patient_cls,
        mock_hist_cls,
        mock_med_cls,
        mock_render,
        mock_get_dismissed_keys,
        mock_note_cls,
    ):
        patient = MagicMock()
        patient.default_provider = MagicMock()
        mock_patient_cls.objects.select_related.return_value.get.return_value = patient

        dismissed_med = _make_history_med(
            drug_description="Old Tamiflu",
            codings=[],
            last_fill_date=datetime(2024, 1, 10),
        )
        active_med = _make_history_med(
            drug_description="Current Drug",
            codings=[],
            last_fill_date=datetime(2025, 3, 15),
        )
        mock_hist_qs = MagicMock()
        mock_hist_cls.objects.filter.return_value = mock_hist_qs
        mock_hist_qs.prefetch_related.return_value = mock_hist_qs
        mock_hist_qs.order_by.return_value = mock_hist_qs
        mock_hist_qs.__getitem__ = MagicMock(
            return_value=[dismissed_med, active_med]
        )

        mock_active_qs = MagicMock()
        mock_med_cls.objects.active.return_value = mock_active_qs
        mock_active_qs.filter.return_value = mock_active_qs
        mock_active_qs.prefetch_related.return_value = iter([])

        mock_render.return_value = "<html>test</html>"

        # Only "Old Tamiflu" (with its formatted latest_fill_date) is dismissed.
        mock_get_dismissed_keys.return_value = {
            ("Old Tamiflu", "", "Jan 10, 2024"),
        }

        mock_note_qs = MagicMock()
        mock_note_cls.objects.filter.return_value = mock_note_qs
        mock_note_qs.filter.return_value = mock_note_qs
        mock_note_qs.select_related.return_value = mock_note_qs
        mock_note_qs.order_by.return_value = mock_note_qs
        mock_note_qs.__iter__ = MagicMock(return_value=iter([]))

        from rx_history.protocols.action_button import MedHistoryActionButton

        handler = MedHistoryActionButton(
            event=MagicMock(target=MagicMock(id="patient-1"))
        )
        handler.handle()

        ctx = mock_render.call_args[0][1]
        groups = json.loads(ctx["grouped_items_json"])
        dismissed = json.loads(ctx["dismissed_items_json"])

        assert len(groups) == 1
        assert groups[0]["drug_description"] == "Current Drug"
        assert len(dismissed) == 1
        assert dismissed[0]["drug_description"] == "Old Tamiflu"
        assert ctx["dismissed_count"] == 1

    @patch("rx_history.protocols.action_button.Note")
    @patch("rx_history.protocols.action_button.get_dismissed_keys")
    @patch("rx_history.protocols.action_button.render_to_string")
    @patch("rx_history.protocols.action_button.Medication")
    @patch("rx_history.protocols.action_button.MedicationHistoryMedication")
    @patch("rx_history.protocols.action_button.Patient")
    def test_matched_items_never_dismissed(
        self,
        mock_patient_cls,
        mock_hist_cls,
        mock_med_cls,
        mock_render,
        mock_get_dismissed_keys,
        mock_note_cls,
    ):
        """Matched items stay in grouped_items even if the group key is in the dismissed set."""
        patient = MagicMock()
        patient.default_provider = MagicMock()
        mock_patient_cls.objects.select_related.return_value.get.return_value = patient

        matched_med = _make_history_med(
            drug_description="Matched Drug",
            codings=[_make_coding(RXNORM_SYSTEM, "999")],
            last_fill_date=datetime(2025, 3, 15),
        )
        mock_hist_qs = MagicMock()
        mock_hist_cls.objects.filter.return_value = mock_hist_qs
        mock_hist_qs.prefetch_related.return_value = mock_hist_qs
        mock_hist_qs.order_by.return_value = mock_hist_qs
        mock_hist_qs.__getitem__ = MagicMock(return_value=[matched_med])

        active_coding = _make_coding(RXNORM_SYSTEM, "999")
        active_med = _make_med([active_coding])
        mock_active_qs = MagicMock()
        mock_med_cls.objects.active.return_value = mock_active_qs
        mock_active_qs.filter.return_value = mock_active_qs
        mock_active_qs.prefetch_related.return_value = iter([active_med])

        mock_render.return_value = "<html>test</html>"

        # Every possible key is "dismissed". Matched items must still bypass the filter.
        class _AlwaysContains:
            def __contains__(self, _key):
                return True

        mock_get_dismissed_keys.return_value = _AlwaysContains()

        mock_note_qs = MagicMock()
        mock_note_cls.objects.filter.return_value = mock_note_qs
        mock_note_qs.filter.return_value = mock_note_qs
        mock_note_qs.select_related.return_value = mock_note_qs
        mock_note_qs.order_by.return_value = mock_note_qs
        mock_note_qs.__iter__ = MagicMock(return_value=iter([]))

        from rx_history.protocols.action_button import MedHistoryActionButton

        handler = MedHistoryActionButton(
            event=MagicMock(target=MagicMock(id="patient-1"))
        )
        handler.handle()

        ctx = mock_render.call_args[0][1]
        groups = json.loads(ctx["grouped_items_json"])
        dismissed = json.loads(ctx["dismissed_items_json"])

        assert len(groups) == 1
        assert groups[0]["drug_description"] == "Matched Drug"
        assert len(dismissed) == 0


class TestOpenNotesContext:
    @patch("rx_history.protocols.action_button.Note")
    @patch("rx_history.protocols.action_button.get_dismissed_keys", return_value=set())
    @patch("rx_history.protocols.action_button.render_to_string")
    @patch("rx_history.protocols.action_button.Medication")
    @patch("rx_history.protocols.action_button.MedicationHistoryMedication")
    @patch("rx_history.protocols.action_button.Patient")
    def test_open_notes_json_passed_to_context(
        self,
        mock_patient_cls,
        mock_hist_cls,
        mock_med_cls,
        mock_render,
        _mock_dismissed,
        mock_note_cls,
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

        note1 = MagicMock()
        note1.id = "note-aaa"
        note1.datetime_of_service = datetime(2026, 4, 17, 10, 0)
        note1.title = ""
        note1.note_type_version = MagicMock()
        note1.note_type_version.name = "Office Visit"
        note1.note_type = "office"
        note2 = MagicMock()
        note2.id = "note-bbb"
        note2.datetime_of_service = datetime(2026, 4, 16, 9, 0)
        note2.title = "Follow-up"
        note2.note_type_version = MagicMock()
        note2.note_type_version.name = "Office Visit"
        note2.note_type = "office"

        mock_note_qs = MagicMock()
        mock_note_cls.objects.filter.return_value = mock_note_qs
        mock_note_qs.filter.return_value = mock_note_qs
        mock_note_qs.select_related.return_value = mock_note_qs
        mock_note_qs.order_by.return_value = mock_note_qs
        mock_note_qs.__iter__ = MagicMock(return_value=iter([note1, note2]))

        mock_render.return_value = "<html>test</html>"

        from rx_history.protocols.action_button import MedHistoryActionButton

        handler = MedHistoryActionButton(
            event=MagicMock(target=MagicMock(id="patient-1"))
        )
        handler.handle()

        ctx = mock_render.call_args[0][1]
        assert "open_notes_json" in ctx
        notes = json.loads(ctx["open_notes_json"])
        assert len(notes) == 2
        assert notes[0]["id"] == "note-aaa"
        assert notes[1]["id"] == "note-bbb"
        # Server emits ISO timestamps and type names; browser formats dates in local tz
        assert notes[0]["datetime_iso"].startswith("2026-04-17")
        assert notes[1]["type_name"] == "Follow-up"


class TestMedHistoryActionButtonRendering:
    @patch("rx_history.protocols.action_button.Note")
    @patch("rx_history.protocols.action_button.get_dismissed_keys", return_value=set())
    @patch("rx_history.protocols.action_button.render_to_string")
    @patch("rx_history.protocols.action_button.Medication")
    @patch(
        "rx_history.protocols.action_button.MedicationHistoryMedication"
    )
    @patch("rx_history.protocols.action_button.Patient")
    def test_renders_grouped_items_and_last_pulled(
        self, mock_patient_cls, mock_hist_cls, mock_med_cls, mock_render, _mock_dismissed, mock_note_cls
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

        mock_note_qs = MagicMock()
        mock_note_cls.objects.filter.return_value = mock_note_qs
        mock_note_qs.filter.return_value = mock_note_qs
        mock_note_qs.select_related.return_value = mock_note_qs
        mock_note_qs.order_by.return_value = mock_note_qs
        mock_note_qs.__iter__ = MagicMock(return_value=iter([]))

        mock_render.return_value = "<html>test</html>"

        from rx_history.protocols.action_button import (
            MedHistoryActionButton,
        )

        handler = MedHistoryActionButton(
            event=MagicMock(target=MagicMock(id="patient-1"))
        )
        effects = handler.handle()

        assert len(effects) == 1
        ctx = mock_render.call_args[0][1]
        assert "grouped_items_json" in ctx
        assert "last_pulled_iso" in ctx
        # ISO timestamp of the most recent record; browser formats in local tz
        assert ctx["last_pulled_iso"].startswith("2026-03-28")

        groups = json.loads(ctx["grouped_items_json"])
        assert len(groups) == 1
        assert groups[0]["drug_description"] == "Test Drug"
        assert len(groups[0]["fills"]) == 1

    @patch("rx_history.protocols.action_button.Patient")
    def test_returns_empty_when_no_patient_id(self, mock_patient_cls):
        from rx_history.protocols.action_button import (
            MedHistoryActionButton,
        )

        handler = MedHistoryActionButton(event=MagicMock(target=MagicMock(id="")))
        effects = handler.handle()
        assert effects == []

    @patch(
        "rx_history.protocols.action_button.MedicationHistoryMedication"
    )
    @patch("rx_history.protocols.action_button.Patient")
    def test_returns_empty_when_patient_not_found(
        self, mock_patient_cls, mock_hist_cls
    ):
        class _FakeDoesNotExist(Exception):
            pass

        mock_patient_cls.DoesNotExist = _FakeDoesNotExist
        mock_patient_cls.objects.select_related.return_value.get.side_effect = (
            _FakeDoesNotExist("not found")
        )

        from rx_history.protocols.action_button import (
            MedHistoryActionButton,
        )

        handler = MedHistoryActionButton(
            event=MagicMock(target=MagicMock(id="missing"))
        )
        effects = handler.handle()
        assert effects == []

    @patch("rx_history.protocols.action_button.Note")
    @patch("rx_history.protocols.action_button.get_dismissed_keys", return_value=set())
    @patch("rx_history.protocols.action_button.render_to_string")
    @patch("rx_history.protocols.action_button.Medication")
    @patch(
        "rx_history.protocols.action_button.MedicationHistoryMedication"
    )
    @patch("rx_history.protocols.action_button.Patient")
    def test_last_pulled_empty_when_no_history(
        self, mock_patient_cls, mock_hist_cls, mock_med_cls, mock_render, _mock_dismissed, mock_note_cls
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

        mock_note_qs = MagicMock()
        mock_note_cls.objects.filter.return_value = mock_note_qs
        mock_note_qs.filter.return_value = mock_note_qs
        mock_note_qs.select_related.return_value = mock_note_qs
        mock_note_qs.order_by.return_value = mock_note_qs
        mock_note_qs.__iter__ = MagicMock(return_value=iter([]))

        mock_render.return_value = "<html>test</html>"

        from rx_history.protocols.action_button import (
            MedHistoryActionButton,
        )

        handler = MedHistoryActionButton(
            event=MagicMock(target=MagicMock(id="patient-1"))
        )
        handler.handle()

        ctx = mock_render.call_args[0][1]
        assert ctx["last_pulled_iso"] == ""


class TestIsMatchedLayered:
    def test_committed_match_wins_over_staged(self):
        """Same RxNorm in both sets resolves against committed, is_staged is False."""
        coding = _make_coding(RXNORM_SYSTEM, "314076")
        med = _make_history_med(codings=[coding])
        matched, method, is_staged = _is_matched_layered(
            med,
            {"314076"}, set(), [],
            {"314076"}, set(), [],
        )
        assert matched is True
        assert method == "rxnorm"
        assert is_staged is False

    def test_staged_match_when_committed_empty(self):
        """Only staged set has the code. Match fires with is_staged True."""
        coding = _make_coding(RXNORM_SYSTEM, "314076")
        med = _make_history_med(codings=[coding])
        matched, method, is_staged = _is_matched_layered(
            med,
            set(), set(), [],
            {"314076"}, set(), [],
        )
        assert matched is True
        assert method == "rxnorm"
        assert is_staged is True

    def test_no_match_returns_false_and_not_staged(self):
        """Neither set matches. is_match False, is_staged False."""
        med = _make_history_med(drug_description="unknown", codings=[])
        matched, method, is_staged = _is_matched_layered(
            med,
            set(), set(), [],
            set(), set(), [],
        )
        assert matched is False
        assert method == ""
        assert is_staged is False


class TestBuildHistoryItemStaged:
    def test_is_staged_defaults_to_false(self):
        med = _make_history_med(codings=[])
        item = _build_history_item(med, is_match=False)
        assert item["is_staged"] is False

    def test_is_staged_propagates_when_true(self):
        coding = _make_coding(RXNORM_SYSTEM, "314076")
        med = _make_history_med(codings=[coding])
        item = _build_history_item(
            med, is_match=True, match_method="rxnorm", is_staged=True
        )
        assert item["is_match"] is True
        assert item["is_staged"] is True
        assert item["match_method"] == "rxnorm"


class TestGroupHistoryItemsStaged:
    def test_group_inherits_is_staged_from_single_item(self):
        items = [
            {
                "drug_description": "Lisinopril 10mg",
                "strength": "",
                "is_match": True,
                "match_method": "rxnorm",
                "is_staged": True,
                "rxnorm_codes": ["314076"],
                "ndc_codes": [],
                "sig": "",
                "last_fill_date": "Mar 18, 2026",
                "last_fill_date_sort": "2026-03-18",
                "written_date": "",
                "prescriber": "",
                "pharmacy_name": "",
                "source_description": "",
                "source_type": "Fill",
            }
        ]
        groups = _group_history_items(items)
        assert groups[0]["is_match"] is True
        assert groups[0]["is_staged"] is True

    def test_committed_fill_overrides_staged_fill_in_group(self):
        """Two fills for the same NDC. One committed match, one staged.
        The group should end up is_staged=False because committed wins."""
        items = [
            {
                "drug_description": "Lisinopril 10mg",
                "strength": "",
                "is_match": True,
                "match_method": "rxnorm",
                "is_staged": True,
                "rxnorm_codes": ["314076"],
                "ndc_codes": ["00093-7339-01"],
                "sig": "",
                "last_fill_date": "Mar 18, 2026",
                "last_fill_date_sort": "2026-03-18",
                "written_date": "",
                "prescriber": "",
                "pharmacy_name": "",
                "source_description": "",
                "source_type": "Fill",
            },
            {
                "drug_description": "Lisinopril 10mg",
                "strength": "",
                "is_match": True,
                "match_method": "rxnorm",
                "is_staged": False,
                "rxnorm_codes": ["314076"],
                "ndc_codes": ["00093-7339-01"],
                "sig": "",
                "last_fill_date": "Feb 18, 2026",
                "last_fill_date_sort": "2026-02-18",
                "written_date": "",
                "prescriber": "",
                "pharmacy_name": "",
                "source_description": "",
                "source_type": "Fill",
            },
        ]
        groups = _group_history_items(items)
        assert len(groups) == 1
        assert groups[0]["is_match"] is True
        assert groups[0]["is_staged"] is False

    def test_unmatched_group_is_not_staged(self):
        items = [
            {
                "drug_description": "Unknown",
                "strength": "",
                "is_match": False,
                "match_method": "",
                "is_staged": False,
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
            }
        ]
        groups = _group_history_items(items)
        assert groups[0]["is_match"] is False
        assert groups[0]["is_staged"] is False
