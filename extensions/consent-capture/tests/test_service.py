"""Tests for consent_capture/service.py."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

from consent_capture import service
from consent_capture.service import (
    accepted_codes,
    accepted_status,
    accepted_status_pairs,
    active_definitions,
    consent_records,
    definition_by_code,
    has_incomplete_required,
    is_consent_admin,
    is_eligible_patient,
    patients_missing_required,
    picker_items,
)

MODULE = "consent_capture.service"


class TestActiveDefinitions:
    def test_filters_active_and_orders(self):
        with patch(f"{MODULE}.ConsentDefinition") as mock_cd:
            mock_cd.objects.filter.return_value.order_by.return_value = ["a", "b"]
            assert active_definitions() == ["a", "b"]
            assert mock_cd.objects.filter.mock_calls[0] == call(active=True)


class TestDefinitionByCode:
    def test_empty_code_returns_none(self):
        assert definition_by_code("") is None

    def test_looks_up_with_system(self):
        with patch(f"{MODULE}.ConsentDefinition") as mock_cd:
            mock_cd.objects.filter.return_value.order_by.return_value.first.return_value = "defn"
            assert definition_by_code("universal", "http://loinc.org") == "defn"
            assert mock_cd.objects.filter.mock_calls[0] == call(
                code="universal", active=True, system="http://loinc.org"
            )

    def test_looks_up_without_system(self):
        with patch(f"{MODULE}.ConsentDefinition") as mock_cd:
            mock_cd.objects.filter.return_value.order_by.return_value.first.return_value = "defn"
            assert definition_by_code("universal") == "defn"
            assert mock_cd.objects.filter.mock_calls[0] == call(code="universal", active=True)


def _stub_consent_rows(mock_pc, rows):
    # rows are (code, effective_date, expired_date), newest-first (as the ORM returns).
    (
        mock_pc.objects.filter.return_value.values_list.return_value.order_by.return_value
    ) = rows


EFF = datetime(2026, 1, 2, tzinfo=timezone.utc)
EFF_OLD = datetime(2020, 1, 1, tzinfo=timezone.utc)
FUTURE = datetime(2999, 1, 1, tzinfo=timezone.utc)
PAST = datetime(2000, 1, 1, tzinfo=timezone.utc)


class TestAcceptedStatus:
    def test_empty_inputs_return_empty_map(self):
        assert accepted_status("", ["a"]) == {}
        assert accepted_status("p1", []) == {}

    def test_classifies_active_and_expired_with_dates(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc:
            _stub_consent_rows(mock_pc, [
                ("never", EFF, None),        # never expires -> active
                ("future", EFF, FUTURE),     # expires later -> active
                ("lapsed", EFF, PAST),       # expired -> expired
            ])
            assert accepted_status("p1", ["never", "future", "lapsed"]) == {
                "never": {"status": "active", "effective_date": "2026-01-02", "expired_date": ""},
                "future": {"status": "active", "effective_date": "2026-01-02", "expired_date": "2999-01-01"},
                "lapsed": {"status": "expired", "effective_date": "2026-01-02", "expired_date": "2000-01-01"},
            }
            assert mock_pc.objects.filter.mock_calls[0] == call(
                patient__id="p1",
                category__code__in=["never", "future", "lapsed"],
                state__in=("accepted", "accepted_via_patient_portal"),
            )
            mock_pc.objects.filter.return_value.values_list.assert_called_once_with(
                "category__code", "effective_date", "expired_date"
            )

    def test_most_recent_row_wins_per_code(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc:
            # Rows arrive newest-first; the first per code is authoritative.
            _stub_consent_rows(mock_pc, [
                ("c1", EFF, None),       # newest: active -> wins
                ("c1", EFF_OLD, PAST),   # older, ignored
            ])
            assert accepted_status("p1", ["c1"])["c1"] == {
                "status": "active", "effective_date": "2026-01-02", "expired_date": "",
            }

    def test_boundary_expiry_just_passed_is_expired(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc:
            just_passed = datetime.now(timezone.utc) - timedelta(seconds=5)
            _stub_consent_rows(mock_pc, [("c1", EFF, just_passed)])
            assert accepted_status("p1", ["c1"])["c1"]["status"] == "expired"

    def test_date_typed_expiry_does_not_raise(self):
        # Canvas may store expired_date as a plain date, not a datetime. Comparing
        # date > datetime raises TypeError; the classification must survive it.
        with patch(f"{MODULE}.PatientConsent") as mock_pc:
            _stub_consent_rows(mock_pc, [
                ("past", EFF, date(2000, 1, 1)),     # date in the past -> expired
                ("future", EFF, date(2999, 1, 1)),   # date in the future -> active
            ])
            result = accepted_status("p1", ["past", "future"])
            assert result["past"]["status"] == "expired"
            assert result["future"]["status"] == "active"

    def test_naive_datetime_expiry_treated_as_utc(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc:
            _stub_consent_rows(mock_pc, [("c1", EFF, datetime(2000, 1, 1))])  # naive
            assert accepted_status("p1", ["c1"])["c1"]["status"] == "expired"


class TestAcceptedCodes:
    def test_empty_inputs_return_empty_set(self):
        assert accepted_codes("", ["a"]) == set()
        assert accepted_codes("p1", []) == set()

    def test_returns_only_active_codes(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc:
            _stub_consent_rows(mock_pc, [
                ("universal", EFF, None),
                ("rpm", EFF, FUTURE),
                ("guide", EFF, PAST),  # expired -> excluded
            ])
            assert accepted_codes("p1", ["universal", "rpm", "guide"]) == {"universal", "rpm"}


def _stub_pair_rows(mock_pc, rows):
    # rows are (system, code, effective_date, expired_date), newest-first.
    (
        mock_pc.objects.filter.return_value.values_list.return_value.order_by.return_value
    ) = rows


class TestAcceptedStatusPairs:
    def test_empty_inputs_return_empty_map(self):
        assert accepted_status_pairs("", [("s", "c")]) == {}
        assert accepted_status_pairs("p1", []) == {}

    def test_matches_by_pair_and_tolerates_empty_code(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc:
            _stub_pair_rows(mock_pc, [
                ("Universal_Written_Consent", "", EFF, None),   # empty code, active
                ("INTERNAL", "verbal", EFF, PAST),              # expired
                ("OTHER", "unwanted", EFF, None),               # not requested -> ignored
            ])
            result = accepted_status_pairs("p1", [
                ("Universal_Written_Consent", ""), ("INTERNAL", "verbal"),
            ])
            assert result == {
                ("Universal_Written_Consent", ""): {
                    "status": "active", "effective_date": "2026-01-02", "expired_date": ""},
                ("INTERNAL", "verbal"): {
                    "status": "expired", "effective_date": "2026-01-02", "expired_date": "2000-01-01"},
            }
            # Queries all of the patient's accepted consents (pairs filtered in Python).
            assert mock_pc.objects.filter.mock_calls[0] == call(
                patient__id="p1",
                state__in=("accepted", "accepted_via_patient_portal"),
            )

    def test_most_recent_row_wins_per_pair(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc:
            _stub_pair_rows(mock_pc, [
                ("s", "c", EFF, None),       # newest -> wins
                ("s", "c", EFF_OLD, PAST),   # older -> ignored
            ])
            assert accepted_status_pairs("p1", [("s", "c")])[("s", "c")]["status"] == "active"


class TestPickerItems:
    def test_builds_items_with_status(self):
        d1 = MagicMock(code="universal", system="http://loinc.org", display="Universal",
                       verbiage="Read.", method_enabled=True, obtained_by_enabled=True,
                       capacity_enabled=True, method_options=["Verbal"], required=True,
                       questions=[{"id": "q1", "prompt": "OK?"}], satisfied_by=[])
        d2 = MagicMock(code="rpm", system="http://loinc.org", display="",
                       verbiage="", method_enabled=False, obtained_by_enabled=True,
                       capacity_enabled=False, method_options=[], required=False,
                       questions=[], satisfied_by=[])
        d3 = MagicMock(code="rpm-old", system="http://loinc.org", display="RPM (old)",
                       verbiage="", method_enabled=True, obtained_by_enabled=True,
                       capacity_enabled=True, method_options=["Electronic Form"], required=True,
                       questions=[], satisfied_by=[])
        # accepted_status_pairs is now keyed by the (system, code) pair.
        freshness = {
            ("http://loinc.org", "universal"): {"status": "active", "effective_date": "2026-01-02", "expired_date": "2027-01-02"},
            ("http://loinc.org", "rpm-old"): {"status": "expired", "effective_date": "2020-01-01", "expired_date": "2021-01-01"},
        }
        with patch(f"{MODULE}.active_definitions", return_value=[d1, d2, d3]), patch(
            f"{MODULE}.accepted_status_pairs", return_value=freshness
        ), patch(
            f"{MODULE}.parse_statement", side_effect=lambda v: [v] if v else []
        ):
            items = picker_items("p1")

        assert items[0]["code"] == "universal"
        assert all(it["active"] is True for it in items)  # active definitions are recordable
        assert items[0]["display"] == "Universal"
        assert items[0]["paragraphs"] == ["Read."]
        assert items[0]["questions"] == [{"id": "q1", "prompt": "OK?"}]
        assert items[0]["method_options"] == ["Verbal"]         # normalized subset
        assert items[0]["required"] is True
        assert items[1]["method_options"] == ["Verbal", "Electronic", "Written", "Other"]  # default fallback
        assert items[1]["required"] is False
        # legacy "Electronic Form" is normalized to the canonical "Electronic"
        assert items[2]["method_options"] == ["Electronic"]
        # active -> on file, with the recorded dates surfaced for the completed card
        assert items[0]["on_file"] is True and items[0]["status"] == "on_file"
        assert items[0]["effective_date"] == "2026-01-02" and items[0]["expiration_date"] == "2027-01-02"
        # never recorded -> needed (falls back to code for display); no dates
        assert items[1]["display"] == "rpm"
        assert items[1]["method_enabled"] is False
        assert items[1]["on_file"] is False and items[1]["status"] == "needed"
        assert items[1]["effective_date"] == "" and items[1]["expiration_date"] == ""
        # accepted but lapsed -> expired (still not on file, so still prompts)
        assert items[2]["on_file"] is False and items[2]["status"] == "expired"

    def test_picker_items_are_definitions_only(self):
        # picker_items now drives only the action rows: one item per active
        # definition. On File history is built separately (consent_records), so
        # picker_items no longer reads inactive definitions or recorded consents.
        d = MagicMock(code="universal", system="s", display="Universal", verbiage="",
                      method_enabled=True, obtained_by_enabled=True, capacity_enabled=True,
                      method_options=[], required=True, questions=[], satisfied_by=[])
        with patch(f"{MODULE}.active_definitions", return_value=[d]) as mock_active, patch(
            f"{MODULE}.accepted_status_pairs", return_value={}
        ), patch(f"{MODULE}.PatientConsent") as mock_pc, patch(
            f"{MODULE}.parse_statement", side_effect=lambda v: [v] if v else []
        ):
            items = picker_items("p1")
        assert [it["code"] for it in items] == ["universal"]
        assert items[0]["active"] is True and items[0]["required"] is True
        assert "managed" not in items[0]          # flag dropped with the split
        mock_active.assert_called_once()
        mock_pc.objects.filter.assert_not_called()  # records are not read here


class TestHasIncompleteRequired:
    def test_true_when_a_required_consent_is_not_on_file(self):
        items = [
            {"required": True, "on_file": False},   # needed/expired required -> triggers
            {"required": False, "on_file": False},
        ]
        with patch(f"{MODULE}.picker_items", return_value=items):
            assert has_incomplete_required("p1") is True

    def test_false_when_required_are_on_file(self):
        items = [
            {"required": True, "on_file": True},
            {"required": False, "on_file": False},  # optional missing does not count
        ]
        with patch(f"{MODULE}.picker_items", return_value=items):
            assert has_incomplete_required("p1") is False

    def test_false_when_no_consents(self):
        with patch(f"{MODULE}.picker_items", return_value=[]):
            assert has_incomplete_required("p1") is False


class TestIsEligiblePatient:
    def test_empty_id_is_false(self):
        assert is_eligible_patient("") is False

    def test_active_non_deceased_is_true(self):
        with patch(f"{MODULE}.Patient") as mp:
            mp.objects.filter.return_value.exclude.return_value.exists.return_value = True
            assert is_eligible_patient("p1") is True
            # Filters to active, then excludes deceased (True), so living/unset stay.
            assert mp.objects.filter.mock_calls[0] == call(id="p1", active=True)
            assert mp.objects.filter.return_value.exclude.mock_calls[0] == call(deceased=True)

    def test_inactive_deceased_or_missing_is_false(self):
        with patch(f"{MODULE}.Patient") as mp:
            mp.objects.filter.return_value.exclude.return_value.exists.return_value = False
            assert is_eligible_patient("p1") is False


class TestPatientsMissingRequired:
    def _defn(self, code, required, system="s", satisfied_by=None):
        return MagicMock(code=code, system=system, required=required,
                         satisfied_by=satisfied_by or [])

    def test_empty_when_no_required_consents(self):
        defs = [self._defn("o", False)]  # only an optional consent
        with patch(f"{MODULE}.active_definitions", return_value=defs), patch(
            f"{MODULE}.Patient"
        ) as mp:
            assert patients_missing_required() == set()
            mp.objects.filter.assert_not_called()  # no patient query when nothing required

    def test_empty_when_no_active_patients(self):
        defs = [self._defn("u", True)]
        with patch(f"{MODULE}.active_definitions", return_value=defs), patch(
            f"{MODULE}.Patient"
        ) as mp, patch(f"{MODULE}.PatientConsent"):
            mp.objects.filter.return_value.exclude.return_value.values_list.return_value.iterator.return_value = []
            assert patients_missing_required() == set()

    def test_needy_is_active_minus_those_with_all_required(self):
        defs = [self._defn("u", True), self._defn("r", True), self._defn("o", False)]
        # Most-recent accepted rows per code (newest-first per patient).
        rows = {
            "u": [("p1", EFF, None), ("p2", EFF, None)],   # p1, p2 active
            "r": [("p1", EFF, None), ("p2", EFF, PAST)],   # p1 active, p2 expired
        }

        def filter_side_effect(**kwargs):
            chain = MagicMock()
            chain.values_list.return_value.order_by.return_value.iterator.return_value = rows[kwargs["category__code"]]
            return chain

        with patch(f"{MODULE}.active_definitions", return_value=defs), patch(
            f"{MODULE}.Patient"
        ) as mp, patch(f"{MODULE}.PatientConsent") as mpc:
            mp.objects.filter.return_value.exclude.return_value.values_list.return_value.iterator.return_value = ["p1", "p2", "p3"]
            mpc.objects.filter.side_effect = filter_side_effect
            result = patients_missing_required()

        # Eligible patients (active, non-deceased) are p1, p2, p3.
        # Only p1 has an active consent for BOTH required codes.
        # p2 has "u" but "r" expired; p3 has neither -> both missing.
        assert result == {"p2", "p3"}


class TestEquivalence:
    """A consent is treated as on file when any of its equivalents is on file, so the
    patient isn't prompted to complete a consent they've effectively already given."""

    def _defn(self, code, system, required, satisfied_by):
        return MagicMock(code=code, system=system, display=code, verbiage="",
                         method_enabled=True, obtained_by_enabled=True, capacity_enabled=True,
                         method_options=[], required=required, questions=[],
                         satisfied_by=satisfied_by)

    def test_picker_item_on_file_via_equivalent(self):
        # Generic "universal-verbal" isn't on file, but its equivalent (code-less
        # "Universal_Written_Consent") is -> the generic reads as on file.
        d = self._defn(
            "universal-verbal", "INTERNAL", True,
            [{"system": "Universal_Written_Consent", "code": "", "display": "Written"}],
        )
        freshness = {
            ("Universal_Written_Consent", ""): {
                "status": "active", "effective_date": "2026-01-02", "expired_date": ""},
        }
        with patch(f"{MODULE}.active_definitions", return_value=[d]), patch(
            f"{MODULE}.accepted_status_pairs", return_value=freshness
        ) as mock_asp, patch(f"{MODULE}.parse_statement", side_effect=lambda v: [v] if v else []):
            items = picker_items("p1")
        assert items[0]["on_file"] is True and items[0]["status"] == "on_file"
        # The on-file lookup was asked about BOTH the own pair and the equivalent.
        requested = set(mock_asp.call_args[0][1])
        assert ("INTERNAL", "universal-verbal") in requested
        assert ("Universal_Written_Consent", "") in requested

    def test_has_incomplete_required_false_when_satisfied_by_equivalent(self):
        d = self._defn(
            "universal-verbal", "INTERNAL", True,
            [{"system": "Universal_Written_Consent", "code": ""}],
        )
        freshness = {("Universal_Written_Consent", ""): {"status": "active",
                     "effective_date": "2026-01-02", "expired_date": ""}}
        with patch(f"{MODULE}.active_definitions", return_value=[d]), patch(
            f"{MODULE}.accepted_status_pairs", return_value=freshness
        ), patch(f"{MODULE}.parse_statement", side_effect=lambda v: [v] if v else []):
            assert has_incomplete_required("p1") is False

    def test_patients_missing_required_excludes_equivalent_holders(self):
        # One required consent whose own coding nobody has, but p1 has the equivalent.
        d = self._defn(
            "universal-verbal", "INTERNAL", True,
            [{"system": "Universal_Written_Consent", "code": ""}],
        )
        holders = {
            ("INTERNAL", "universal-verbal"): [],                       # nobody
            ("Universal_Written_Consent", ""): [("p1", EFF, None)],     # p1 satisfied via equivalent
        }

        def filter_side_effect(**kwargs):
            chain = MagicMock()
            key = (kwargs["category__system"], kwargs["category__code"])
            chain.values_list.return_value.order_by.return_value.iterator.return_value = holders[key]
            return chain

        with patch(f"{MODULE}.active_definitions", return_value=[d]), patch(
            f"{MODULE}.Patient"
        ) as mp, patch(f"{MODULE}.PatientConsent") as mpc:
            mp.objects.filter.return_value.exclude.return_value.values_list.return_value.iterator.return_value = ["p1", "p2"]
            mpc.objects.filter.side_effect = filter_side_effect
            result = patients_missing_required()
        assert result == {"p2"}  # p1 satisfied via the equivalent


class TestConsentRecords:
    def test_empty_patient_returns_empty(self):
        assert consent_records("") == []

    def _stub_rows(self, mock_pc, rows):
        # rows are (id, code, system, display, effective_date, expired_date), newest-first.
        (
            mock_pc.objects.filter.return_value.values_list.return_value.order_by.return_value
        ) = rows

    def _stub_details(self, mock_ccd, rows):
        # rows are (system, code, effective_date, obtained_by_name, method,
        # consented_by, capacity_statement, pages).
        mock_ccd.objects.filter.return_value.values_list.return_value = rows

    def test_returns_one_entry_per_record_not_deduped(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc, patch(
            f"{MODULE}.ConsentCaptureDetail"
        ) as mock_ccd:
            self._stub_rows(mock_pc, [
                (1, "universal", "s", "Universal", EFF, None),        # active
                (2, "universal", "s", "Universal", EFF_OLD, PAST),    # older, expired — kept!
                (3, "verbal", "s", "Verbal", EFF, PAST),              # expired
                (4, "", "", "No id", EFF, None),                      # no identity -> skipped
            ])
            self._stub_details(mock_ccd, [])                          # no stored detail
            out = consent_records("p1")
            assert [r["id"] for r in out] == ["1", "2", "3"]          # #4 skipped
            assert out[0] == {
                "id": "1", "code": "universal", "system": "s", "display": "Universal",
                "status": "active", "on_file": True,
                "effective_date": "2026-01-02", "expiration_date": "",
                "obtained_by": "", "method": "", "consented_by": "", "capacity_statement": "",
                "pages": 0,
            }
            assert mock_pc.objects.filter.mock_calls[0] == call(
                patient__id="p1",
                state__in=("accepted", "accepted_via_patient_portal"),
            )

    def test_empty_code_record_kept_when_system_present(self):
        # A coding whose identity is carried in `system` alone (empty code) must still
        # appear under On File — matches the (system, code) pair identity.
        with patch(f"{MODULE}.PatientConsent") as mock_pc, patch(
            f"{MODULE}.ConsentCaptureDetail"
        ) as mock_ccd:
            self._stub_rows(mock_pc, [
                (7, "", "Universal_Written_Consent", "Universal Written", EFF, None),
            ])
            self._stub_details(mock_ccd, [])
            out = consent_records("p1")
            assert len(out) == 1
            assert out[0]["code"] == "" and out[0]["system"] == "Universal_Written_Consent"
            assert out[0]["display"] == "Universal Written"

    def test_attaches_capture_detail(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc, patch(
            f"{MODULE}.ConsentCaptureDetail"
        ) as mock_ccd:
            self._stub_rows(mock_pc, [(1, "universal", "s", "Universal", EFF, None)])
            self._stub_details(mock_ccd, [
                ("s", "universal", "2026-01-02", "Jane Nurse", "Written", "Patient", "Has capacity.", 3),
            ])
            out = consent_records("p1")
            assert out[0]["obtained_by"] == "Jane Nurse"
            assert out[0]["method"] == "Written"
            assert out[0]["consented_by"] == "Patient"
            assert out[0]["capacity_statement"] == "Has capacity."
            assert out[0]["pages"] == 3
            assert mock_ccd.objects.filter.mock_calls[0] == call(patient_id="p1")

    def test_detail_blank_when_no_match(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc, patch(
            f"{MODULE}.ConsentCaptureDetail"
        ) as mock_ccd:
            self._stub_rows(mock_pc, [(1, "universal", "s", "Universal", EFF, None)])
            # A detail for a different date -> no match, fields stay blank.
            self._stub_details(mock_ccd, [
                ("s", "universal", "1999-01-01", "Someone", "Verbal", "Patient", "", 1),
            ])
            out = consent_records("p1")
            assert out[0]["obtained_by"] == "" and out[0]["method"] == ""
            assert out[0]["pages"] == 0

    def test_date_typed_expiry_does_not_raise(self):
        # Regression: a plain date expiry must not crash the record sweep
        # (date > datetime raises TypeError), which would break the picker modal.
        with patch(f"{MODULE}.PatientConsent") as mock_pc, patch(
            f"{MODULE}.ConsentCaptureDetail"
        ) as mock_ccd:
            self._stub_rows(mock_pc, [
                (1, "verbal", "s", "Verbal", EFF, date(2000, 1, 1)),   # expired
                (2, "treat", "s", "Treat", EFF, date(2999, 1, 1)),     # active
            ])
            self._stub_details(mock_ccd, [])
            out = {r["code"]: r["status"] for r in consent_records("p1")}
            assert out == {"verbal": "expired", "treat": "active"}


class TestIsConsentAdmin:
    def _stub_staff(self, mock_staff, first, last):
        (
            mock_staff.objects.filter.return_value.values_list.return_value.first.return_value
        ) = (first, last) if first is not None else None

    def test_empty_list_denies_non_root(self):
        # Fails closed: an unset allow-list must not open the admin surface.
        with patch(f"{MODULE}.Staff") as mock_staff:
            self._stub_staff(mock_staff, "Jane", "Doe")
            assert is_consent_admin("s1", "") is False
            assert is_consent_admin("s1", None) is False

    def test_empty_list_still_allows_root(self):
        with patch(f"{MODULE}.Staff") as mock_staff:
            self._stub_staff(mock_staff, "Canvas", "Support")
            assert is_consent_admin("s1", "") is True

    def test_configured_but_no_staff_id_denied(self):
        assert is_consent_admin("", "Jane Doe") is False

    def test_matches_by_staff_id(self):
        with patch(f"{MODULE}.Staff") as mock_staff:
            self._stub_staff(mock_staff, "Jane", "Doe")
            assert is_consent_admin("staff-123", "staff-123, other-id") is True

    def test_matches_by_full_name_case_insensitive(self):
        with patch(f"{MODULE}.Staff") as mock_staff:
            self._stub_staff(mock_staff, "Jane", "Doe")
            assert is_consent_admin("s1", "JANE DOE; someone@x") is True

    def test_non_match_denied(self):
        with patch(f"{MODULE}.Staff") as mock_staff:
            self._stub_staff(mock_staff, "Jane", "Doe")
            assert is_consent_admin("s1", "someone else\nadmin@x") is False

    def test_no_staff_row_denied(self):
        with patch(f"{MODULE}.Staff") as mock_staff:
            self._stub_staff(mock_staff, None, None)
            assert is_consent_admin("s1", "s2") is False

    def test_row_without_name_matches_by_id_only(self):
        with patch(f"{MODULE}.Staff") as mock_staff:
            self._stub_staff(mock_staff, "", "")  # nameless row -> match by id
            assert is_consent_admin("staff-9", "staff-9") is True

    def test_root_canvas_support_always_allowed(self):
        with patch(f"{MODULE}.Staff") as mock_staff:
            self._stub_staff(mock_staff, "Canvas", "Support")  # root, not in the list
            assert is_consent_admin("s1", "only-admin@example.com") is True

    def test_root_literal_name_always_allowed(self):
        with patch(f"{MODULE}.Staff") as mock_staff:
            self._stub_staff(mock_staff, "root", "")
            assert is_consent_admin("s1", "only-admin@example.com") is True

    def test_root_by_id_always_allowed(self):
        with patch(f"{MODULE}.Staff") as mock_staff:
            self._stub_staff(mock_staff, "Jane", "Doe")
            assert is_consent_admin("root", "someone-else") is True
