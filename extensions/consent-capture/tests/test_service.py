"""Tests for consent_capture/service.py."""

import hashlib
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


RECORDED = (
    "accepted",
    "accepted_via_patient_portal",
    "rejected",
    "rejected_via_patient_portal",
)

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
    # rows are (system, code, effective_date, expired_date[, state[, rejection
    # reason]]), newest-first. A row without a state is an accepted consent.
    rows = [r if len(r) >= 5 else tuple(r) + ("accepted",) for r in rows]
    (
        mock_pc.objects.filter.return_value.values_list.return_value.order_by.return_value
    ) = [r if len(r) == 6 else tuple(r) + (None,) for r in rows]


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
                    "status": "active", "effective_date": "2026-01-02", "expired_date": "", "reason": ""},
                ("INTERNAL", "verbal"): {
                    "status": "expired", "effective_date": "2026-01-02", "expired_date": "2000-01-01", "reason": ""},
            }
            # Queries all of the patient's recorded consents (pairs filtered in Python).
            assert mock_pc.objects.filter.mock_calls[0] == call(
                patient__id="p1",
                state__in=RECORDED,
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
        # Fingerprint of the text shown, sent back when recording.
        assert items[0]["statement_sha256"] == hashlib.sha256(b"Read.").hexdigest()
        assert items[0]["questions_sha256"] == hashlib.sha256(b"q1\t\tOK?").hexdigest()
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
        # rows are (id, code, system, display, effective_date, expired_date[, state
        # [, rejection reason]]), newest-first. A row without a state is an accepted
        # consent; one without a reason has none.
        rows = [r if len(r) >= 7 else tuple(r) + ("accepted",) for r in rows]
        (
            mock_pc.objects.filter.return_value.values_list.return_value.order_by.return_value
        ) = [r if len(r) == 8 else tuple(r) + (None,) for r in rows]

    def _stub_details(self, mock_ccd, rows):
        # rows are (system, code, effective_date, obtained_by_name, method,
        # consented_by, capacity_statement, pages[, signed_on_device, signed_with
        # [, reason_display]]).
        rows = [r if len(r) >= 10 else tuple(r) + (False, "") for r in rows]
        mock_ccd.objects.filter.return_value.values_list.return_value = [
            r if len(r) == 11 else tuple(r) + ("",) for r in rows
        ]

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
                "pages": 0, "signature": "", "reason": "", "ineligible": False,
            }
            assert mock_pc.objects.filter.mock_calls[0] == call(
                patient__id="p1",
                state__in=RECORDED,
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
    ADMIN = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"

    def test_empty_list_denies_everyone(self):
        # Fails closed: an unset allow-list must not open the admin surface.
        assert is_consent_admin(self.ADMIN, "") is False
        assert is_consent_admin(self.ADMIN, None) is False

    def test_no_staff_id_denied(self):
        assert is_consent_admin("", self.ADMIN) is False

    def test_matches_by_staff_id(self):
        assert is_consent_admin(self.ADMIN, "%s, other-id" % self.ADMIN) is True

    def test_id_match_ignores_case_dashes_and_separators(self):
        dashed = "0F1E2D3C-4B5A-6978-8796-A5B4C3D2E1F0"
        assert is_consent_admin(self.ADMIN, "someone; %s\nother" % dashed) is True
        assert is_consent_admin(dashed, self.ADMIN) is True

    def test_non_match_denied(self):
        assert is_consent_admin(self.ADMIN, "s2\ns3") is False

    def test_staff_named_root_is_not_admin(self):
        # Names play no part: a staff member named "Root" isn't treated as root.
        assert is_consent_admin("s1", "") is False
        assert is_consent_admin("s1", "root") is False

    def test_staff_sharing_an_admins_name_is_not_admin(self):
        assert is_consent_admin("s2", "Jane Doe") is False

    def test_canvas_support_needs_its_id_listed(self):
        assert is_consent_admin(self.ADMIN, "") is False
        assert is_consent_admin(self.ADMIN, "canvas support") is False
        assert is_consent_admin(self.ADMIN, self.ADMIN) is True


# --------------------------------------------------------------------------- #
# Declined consents count as asked and answered
# --------------------------------------------------------------------------- #
class TestDeclinedConsents:
    def test_declined_pair_reads_declined(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc:
            _stub_pair_rows(mock_pc, [
                ("s", "c", EFF, None, "rejected"),
                ("s", "p", EFF, None, "rejected_via_patient_portal"),
            ])
            result = accepted_status_pairs("p1", [("s", "c"), ("s", "p")])
            assert result[("s", "c")]["status"] == "declined"
            assert result[("s", "p")]["status"] == "declined"

    def test_lapsed_decline_is_expired(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc:
            _stub_pair_rows(mock_pc, [("s", "c", EFF, PAST, "rejected")])
            assert accepted_status_pairs("p1", [("s", "c")])[("s", "c")]["status"] == "expired"

    def test_newest_record_wins_decline_over_older_accept(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc:
            _stub_pair_rows(mock_pc, [
                ("s", "c", EFF, None, "rejected"),
                ("s", "c", EFF_OLD, None, "accepted"),
            ])
            assert accepted_status_pairs("p1", [("s", "c")])[("s", "c")]["status"] == "declined"

    def test_combined_status_prefers_active_then_declined_then_expired(self):
        fresh = {
            ("s", "a"): {"status": "expired"},
            ("s", "b"): {"status": "declined"},
            ("s", "c"): {"status": "active"},
        }
        assert service._combined_status(fresh, [("s", "a"), ("s", "b")])["status"] == "declined"
        assert service._combined_status(fresh, [("s", "a"), ("s", "b"), ("s", "c")])["status"] == "active"
        assert service._combined_status(fresh, [("s", "a")])["status"] == "expired"
        assert service._combined_status(fresh, [("s", "z")]) == {}

    def test_picker_item_status_declined(self):
        d = MagicMock(code="c", system="s", display="C", verbiage="", method_enabled=True,
                      obtained_by_enabled=True, capacity_enabled=False, method_options=[],
                      questions=[], required=True, allow_device_signature=True)
        item = service._picker_item(d, {"status": "declined", "effective_date": "2026-01-02"}, True)
        assert item["status"] == "declined"
        assert item["on_file"] is False
        assert item["allow_device_signature"] is True

    def test_picker_item_allow_device_signature_unset_is_off(self):
        d = MagicMock(code="c", system="s", display="C", verbiage="", method_enabled=True,
                      obtained_by_enabled=True, capacity_enabled=False, method_options=[],
                      questions=[], required=False, allow_device_signature=None)
        assert service._picker_item(d, {}, True)["allow_device_signature"] is False

    def test_declined_required_is_not_incomplete(self):
        items = [{"required": True, "on_file": False, "status": "declined"}]
        with patch(f"{MODULE}.picker_items", return_value=items):
            assert has_incomplete_required("p1") is False

    def test_consent_records_lists_declined(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc, patch(
            f"{MODULE}.ConsentCaptureDetail"
        ) as mock_ccd:
            mock_pc.objects.filter.return_value.values_list.return_value.order_by.return_value = [
                (7, "c", "s", "C", EFF, None, "rejected", "Refused"),
            ]
            mock_ccd.objects.filter.return_value.values_list.return_value = []
            out = consent_records("p1")
            assert out[0]["status"] == "declined"
            assert out[0]["on_file"] is False
            # The reason comes from Canvas, so a profile-tab decline shows it too.
            assert out[0]["reason"] == "Refused"
            assert out[0]["ineligible"] is False

    def test_patients_with_active_pair_counts_declines(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc:
            qs = mock_pc.objects.filter.return_value.values_list.return_value.order_by.return_value
            qs.iterator.return_value = [("p1", EFF, None)]
            now = datetime.now(timezone.utc)
            assert service._patients_with_active_consent_pair("s", "c", now) == {"p1"}
            assert mock_pc.objects.filter.mock_calls[0] == call(
                category__system="s", category__code="c", state__in=RECORDED
            )


class TestSignatureDetail:
    def test_label_for_each_kind(self):
        assert service.signature_label(True, "finger") == "Signed on this device (finger or stylus)"
        assert service.signature_label(True, "mouse") == "Signed on this device (mouse or trackpad)"
        assert service.signature_label(True, "typed") == "Signed on this device (typed)"
        assert service.signature_label(True, "") == "Signed on this device"

    def test_blank_when_not_signed_on_device(self):
        assert service.signature_label(False, "finger") == ""
        assert service.signature_label(None, "") == ""

    def test_consent_records_carries_signed_with(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc, patch(
            f"{MODULE}.ConsentCaptureDetail"
        ) as mock_ccd:
            mock_pc.objects.filter.return_value.values_list.return_value.order_by.return_value = [
                (1, "c", "s", "C", EFF, None, "accepted", None),
            ]
            mock_ccd.objects.filter.return_value.values_list.return_value = [
                ("s", "c", "2026-01-02", "Sam", "Written", "Patient", "", 1, True, "mouse", ""),
            ]
            out = consent_records("p1")
            assert out[0]["signature"] == "Signed on this device (mouse or trackpad)"
            assert out[0]["method"] == "Written"


# --------------------------------------------------------------------------- #
# Practice settings
# --------------------------------------------------------------------------- #
class TestPracticeSettings:
    def test_defaults_when_never_saved(self, _no_saved_practice_settings):
        assert service.practice_settings() == {
            "reuse_signature": False,
            "accept_finger": True,
            "accept_mouse": True,
            "accept_typed": False,
            "ask_printed_name": False,
        }
        assert _no_saved_practice_settings.filter.mock_calls[0] == call(key="practice")

    def test_saved_row_overrides_and_none_keeps_default(self, _no_saved_practice_settings):
        _no_saved_practice_settings.filter.return_value.values.return_value.first.return_value = {
            "reuse_signature": True,
            "accept_finger": False,
            "accept_mouse": None,   # column added later, unset on this row
            "accept_typed": True,
            "ask_printed_name": True,
        }
        assert service.practice_settings() == {
            "reuse_signature": True,
            "accept_finger": False,
            "accept_mouse": True,
            "accept_typed": True,
            "ask_printed_name": True,
        }

    def test_clean_requires_one_accepted_signature(self):
        values, error = service.clean_practice_settings(
            {"accept_finger": False, "accept_mouse": False, "accept_typed": False}
        )
        assert values is None
        assert error == "Select at least one accepted signature."

    def test_clean_fills_missing_with_defaults(self):
        values, error = service.clean_practice_settings({"accept_typed": True})
        assert error is None
        assert values == {
            "reuse_signature": False,
            "accept_finger": True,
            "accept_mouse": True,
            "accept_typed": True,
            "ask_printed_name": False,
        }

    def test_clean_non_dict(self):
        values, error = service.clean_practice_settings("nope")
        assert error is None and values["accept_finger"] is True

    def test_save_updates_existing_row(self, _no_saved_practice_settings):
        _no_saved_practice_settings.filter.return_value.update.return_value = 1
        values = dict(service.PRACTICE_DEFAULTS, reuse_signature=True)
        service.save_practice_settings(values)
        assert call(key="practice") in _no_saved_practice_settings.filter.mock_calls
        assert _no_saved_practice_settings.filter.return_value.update.mock_calls == [call(**values)]
        assert _no_saved_practice_settings.create.mock_calls == []

    def test_save_creates_row_first_time(self, _no_saved_practice_settings):
        _no_saved_practice_settings.filter.return_value.update.return_value = 0
        values = dict(service.PRACTICE_DEFAULTS)
        service.save_practice_settings(values)
        assert _no_saved_practice_settings.create.mock_calls == [call(key="practice", **values)]



class TestReviewFixesService:
    def test_same_day_records_ordered_by_created(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc:
            _stub_pair_rows(mock_pc, [("s", "c", EFF, None, "accepted")])
            accepted_status_pairs("p1", [("s", "c")])
            mock_pc.objects.filter.return_value.values_list.return_value.order_by.assert_called_once_with(
                "-effective_date", "-created"
            )

    def test_newer_same_day_accept_wins_over_decline(self):
        # Rows arrive in -effective_date, -created order: the later accept is first.
        with patch(f"{MODULE}.PatientConsent") as mock_pc:
            _stub_pair_rows(mock_pc, [("s", "c", EFF, None, "accepted"), ("s", "c", EFF, None, "rejected")])
            assert accepted_status_pairs("p1", [("s", "c")])[("s", "c")]["status"] == "active"

    def test_is_required_and_due(self):
        assert service.is_required_and_due({"required": True, "on_file": False, "status": "needed"}) is True
        assert service.is_required_and_due({"required": True, "on_file": False, "status": "expired"}) is True
        assert service.is_required_and_due({"required": True, "on_file": True, "status": "on_file"}) is False
        assert service.is_required_and_due({"required": True, "on_file": False, "status": "declined"}) is False
        assert service.is_required_and_due({"required": False, "on_file": False, "status": "needed"}) is False

    def test_practice_settings_only_true_turns_on(self):
        values, error = service.clean_practice_settings({"accept_typed": "false", "reuse_signature": 1, "ask_printed_name": True})
        assert error is None
        assert values["accept_typed"] is False
        assert values["reuse_signature"] is False
        assert values["ask_printed_name"] is True
        assert values["accept_finger"] is True   # missing -> default


class TestExpirationDateFor:
    """Mirrors Canvas's expiration rules for the done screen."""

    def _rule(self, rule):
        mock_pcc = MagicMock()
        mock_pcc.objects.filter.return_value.values_list.return_value.first.return_value = rule
        return patch("consent_capture.service.PatientConsentCoding", mock_pcc)

    def test_in_one_year(self):
        with self._rule("in_one_year") as mock_pcc:
            assert service.expiration_date_for("INTERNAL", "rpm", "2026-11-06") == "2027-11-06"
        assert mock_pcc.objects.filter.mock_calls[0] == call(system="INTERNAL", code="rpm")

    def test_leap_day_moves_to_feb_28(self):
        with self._rule("in_one_year"):
            assert service.expiration_date_for("INTERNAL", "rpm", "2028-02-29") == "2029-02-28"

    def test_end_of_year(self):
        with self._rule("end_of_year"):
            assert service.expiration_date_for("INTERNAL", "x", "2026-03-15") == "2026-12-31"

    def test_never_and_missing_coding(self):
        with self._rule("never"):
            assert service.expiration_date_for("INTERNAL", "x", "2026-03-15") == ""
        with self._rule(None):
            assert service.expiration_date_for("INTERNAL", "x", "2026-03-15") == ""

    def test_enum_rule_value(self):
        class Rule:
            value = "in_one_year"

        with self._rule(Rule()):
            assert service.expiration_date_for("INTERNAL", "x", "2026-01-31") == "2027-01-31"

    def test_bad_date(self):
        with self._rule("in_one_year"):
            assert service.expiration_date_for("INTERNAL", "x", "") == ""


class TestDeclineOptions:
    """Reasons staff can choose, and the Ineligible coding, from Canvas's
    rejection codings and the practice's saved choice."""

    CODINGS = [
        {"system": "INTERNAL", "code": "ineligible", "display": "Ineligible"},
        {"system": "INTERNAL", "code": "REJECT_VIA_PORTAL", "display": "Rejected via Patient Portal"},
        {"system": "INTERNAL", "code": "refused", "display": "Refused"},
    ]

    def _saved(self, row):
        mock_ps = MagicMock()
        mock_ps.objects.filter.return_value.values_list.return_value.first.return_value = row
        return patch("consent_capture.service.ConsentPracticeSettings", mock_ps)

    def test_rejection_codings_reads_displayed_codings(self):
        mock = MagicMock()
        mock.objects.filter.return_value.values_list.return_value.order_by.return_value = [
            ("INTERNAL", "refused", "Refused"), ("Sys", "", None), ("Sys", "", "Unable to consent"),
        ]
        with patch("consent_capture.service.PatientConsentRejectionCoding", mock):
            out = service.rejection_codings()
        assert mock.objects.filter.mock_calls[0] == call(user_selected=True)
        # A coding with neither a code nor a name can't be referenced, so it's left out.
        assert out == [
            {"system": "INTERNAL", "code": "refused", "display": "Refused"},
            {"system": "Sys", "code": "", "display": "Unable to consent"},
        ]

    def test_defaults_leave_out_the_portal_coding(self):
        with patch("consent_capture.service.rejection_codings", return_value=self.CODINGS), self._saved(None):
            out = service.decline_options()
        assert [r["code"] for r in out["reasons"]] == ["refused"]
        assert out["ineligible"]["code"] == "ineligible"
        flags = {c["code"]: (c["chosen"], c["ineligible"]) for c in out["codings"]}
        assert flags == {"ineligible": (True, True), "REJECT_VIA_PORTAL": (False, False), "refused": (True, False)}

    def test_saved_choice_wins(self):
        saved = (True, [{"system": "INTERNAL", "code": "REJECT_VIA_PORTAL"}])
        with patch("consent_capture.service.rejection_codings", return_value=self.CODINGS), self._saved(saved):
            out = service.decline_options()
        assert [r["code"] for r in out["reasons"]] == ["REJECT_VIA_PORTAL"]
        assert out["ineligible"] is None  # Ineligible exists but isn't chosen

    def test_ineligible_found_by_name_ignoring_capitals(self):
        codings = [{"system": "S", "code": "x1", "display": " INELIGIBLE "}]
        with patch("consent_capture.service.rejection_codings", return_value=codings), self._saved(None):
            out = service.decline_options()
        assert out["ineligible"]["code"] == "x1"
        assert out["reasons"] == []

    def test_allowed_reasons_add_ineligible_only_when_the_consent_allows_it(self):
        refused = {"system": "S", "code": "r", "display": "Refused"}
        inel = {"system": "S", "code": "i", "display": "Ineligible"}
        options = {"reasons": [refused], "ineligible": inel}
        allows, doesnt = MagicMock(allow_ineligible=True), MagicMock(allow_ineligible=False)
        assert service.allowed_decline_reasons(allows, options) == [refused, inel]
        assert service.allowed_decline_reasons(doesnt, options) == [refused]
        assert service.allowed_decline_reasons(allows, {"reasons": [], "ineligible": None}) == []

    def test_clean_decline_reasons(self):
        with patch("consent_capture.service.rejection_codings", return_value=self.CODINGS):
            assert service.clean_decline_reasons("nope") is None
            assert service.clean_decline_reasons([
                {"system": "INTERNAL", "code": "refused"}, {"system": "INTERNAL", "code": "refused"},
                {"system": "X", "code": "gone"}, "junk",
            ]) == [{"system": "INTERNAL", "code": "refused", "display": "Refused"}]

    def test_blank_code_codings_stay_separate(self):
        codings = [
            {"system": "INTERNAL", "code": "", "display": "Ineligible"},
            {"system": "INTERNAL", "code": "", "display": "Unable to consent"},
        ]
        saved = (True, [{"system": "INTERNAL", "code": "", "display": "Unable to consent"}])
        with patch("consent_capture.service.rejection_codings", return_value=codings), self._saved(saved):
            out = service.decline_options()
            cleaned = service.clean_decline_reasons([{"system": "INTERNAL", "code": "", "display": "Ineligible"}])
        assert [r["display"] for r in out["reasons"]] == ["Unable to consent"]
        assert out["ineligible"] is None  # same system and blank code, but not chosen
        assert cleaned == [{"system": "INTERNAL", "code": "", "display": "Ineligible"}]

    def test_reason_key_ignores_the_name_when_there_is_a_code(self):
        assert service.reason_key("S", "r", "Refused") == service.reason_key("S", "r", "Renamed")
        assert service.reason_key("S", "", "A") != service.reason_key("S", "", "B")

    def test_save_decline_reasons_upserts(self):
        mock_ps = MagicMock()
        mock_ps.objects.filter.return_value.update.return_value = 0
        with patch("consent_capture.service.ConsentPracticeSettings", mock_ps):
            service.save_decline_reasons([{"system": "S", "code": "r"}])
        assert mock_ps.objects.create.mock_calls == [
            call(key="practice", decline_reasons_set=True, decline_reasons=[{"system": "S", "code": "r"}])
        ]

    def test_ineligible_record_flagged(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc, patch(f"{MODULE}.ConsentCaptureDetail") as mock_ccd:
            mock_pc.objects.filter.return_value.values_list.return_value.order_by.return_value = [
                (7, "ccm", "s", "CCM", EFF, None, "rejected", "Ineligible"),
            ]
            mock_ccd.objects.filter.return_value.values_list.return_value = []
            out = consent_records("p1")
        assert out[0]["ineligible"] is True and out[0]["reason"] == "Ineligible"


class TestPickerItemIneligibleAfterReload:
    """The list's tag comes from the saved decline, not only from this session."""

    def _defn(self):
        return MagicMock(code="ccm", system="S", display="CCM", verbiage="Text.", method_enabled=True,
                         obtained_by_enabled=True, capacity_enabled=False, method_options=["Verbal"],
                         questions=[], required=True, allow_device_signature=False, allow_ineligible=True)

    def test_saved_ineligible_decline_is_flagged(self):
        item = service._picker_item(self._defn(), {"status": "declined", "reason": "Ineligible"}, True)
        assert item["status"] == "declined"
        assert item["ineligible"] is True and item["reason"] == "Ineligible"

    def test_other_decline_reason_is_not_ineligible(self):
        item = service._picker_item(self._defn(), {"status": "declined", "reason": "Refused"}, True)
        assert item["ineligible"] is False and item["reason"] == "Refused"

    def test_accepted_consent_has_no_reason(self):
        item = service._picker_item(self._defn(), {"status": "active", "reason": ""}, True)
        assert item["ineligible"] is False and item["reason"] == ""

    def test_status_pairs_carry_the_reason(self):
        with patch(f"{MODULE}.PatientConsent") as mock_pc:
            _stub_pair_rows(mock_pc, [("S", "ccm", EFF, None, "rejected", "Ineligible")])
            out = accepted_status_pairs("p1", [("S", "ccm")])
        assert out[("S", "ccm")]["status"] == "declined"
        assert out[("S", "ccm")]["reason"] == "Ineligible"
