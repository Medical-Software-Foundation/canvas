"""Tests for practitioner_bulk_loader.utils.csv_parser."""

import pytest

from practitioner_bulk_loader.utils.csv_parser import (
    DEFAULT_NPI,
    build_fhir_practitioner,
    build_qualification,
    build_username,
    diff_licenses,
    parse_csv,
    validate_csv_headers,
)
from practitioner_bulk_loader.utils.validation import canonicalize_license_type

# ---------------------------------------------------------------------------
# Helper: build properly-aligned CSV rows (21 columns total)
# Per FHIR mapping: col 21 is "Primary" (legacy "License Primary" also accepted).
# The default _HEADER here uses the legacy name to prove back-compat keeps working
# — all existing parse tests exercise the back-compat path.
# ---------------------------------------------------------------------------
_HEADER = (
    "First Name,Last Name,Role,Primary Practice Location,Email,Phone,Fax,NPI,DOB,"
    "Address Line 1,Address Line 2,City,State,Zip,"
    "License Type,License Name,License State,License Number,"
    "License Issue Date,License Expiration Date,License Primary"
)

_HEADER_NEW = _HEADER.replace(",License Primary", ",Primary")


def _row(first_name="", last_name="", role="", location="", email="",
         phone="", fax="", npi="", dob="",
         addr1="", addr2="", city="", state="", zip_="",
         lic_type="", lic_name="", lic_state="", lic_number="",
         issue_date="", exp_date="", primary=""):
    return (
        f"{first_name},{last_name},{role},{location},{email},"
        f"{phone},{fax},{npi},{dob},"
        f"{addr1},{addr2},{city},{state},{zip_},"
        f"{lic_type},{lic_name},{lic_state},{lic_number},"
        f"{issue_date},{exp_date},{primary}"
    )


def _csv(*rows):
    return _HEADER + "\n" + "\n".join(rows) + "\n"


# ---------------------------------------------------------------------------
# Canonical test fixtures
# ---------------------------------------------------------------------------

MINIMAL_CSV = _csv(
    _row(first_name="Jane", last_name="Smith", role="MD",
         location="Main Clinic", email="jane.smith@example.com",
         phone="5555550100", dob="1980-03-15"),
)

TWO_PRACTITIONER_CSV = _csv(
    _row(first_name="Jane", last_name="Smith", role="MD",
         location="Main Clinic", email="jane.smith@example.com",
         phone="5555550100", dob="1980-03-15"),
    _row(first_name="John", last_name="Doe", role="RN",
         location="West Clinic", email="john.doe@example.com",
         phone="5555550200", dob="1985-06-20"),
)

MULTI_LICENSE_CSV = _csv(
    _row(first_name="Jane", last_name="Smith", role="MD",
         location="Main Clinic", email="jane.smith@example.com",
         phone="5555550100", dob="1980-03-15",
         lic_type="State license", lic_name="NY Medical Board", lic_state="NY",
         lic_number="MD12345", issue_date="2020-01-01", exp_date="2026-01-01",
         primary="TRUE"),
    _row(email="jane.smith@example.com",
         lic_type="DEA", lic_number="AS1234567",
         issue_date="2021-06-01", exp_date="2027-06-01", primary="FALSE"),
)

CASE_INSENSITIVE_EMAIL_CSV = _csv(
    _row(first_name="Jane", last_name="Smith", role="MD",
         email="Jane.Smith@Example.COM", phone="5555550100", dob="1980-03-15",
         lic_type="State license", lic_name="NY Board", lic_state="NY",
         lic_number="MD001", issue_date="2020-01-01", exp_date="2026-01-01",
         primary="TRUE"),
    _row(email="jane.smith@example.com",
         lic_type="DEA", lic_number="DEA001",
         issue_date="2021-01-01", exp_date="2027-01-01", primary="FALSE"),
)

CONTINUATION_CONFLICT_CSV = _csv(
    _row(first_name="Jane", last_name="Smith", role="MD",
         location="Main Clinic", email="jane.smith@example.com",
         phone="5555550100", dob="1980-03-15",
         lic_type="State license", lic_name="NY Board", lic_state="NY",
         lic_number="MD001", issue_date="2020-01-01", exp_date="2026-01-01",
         primary="TRUE"),
    _row(location="DIFFERENT CLINIC", email="jane.smith@example.com",
         lic_type="DEA", lic_number="DEA001",
         issue_date="2021-01-01", exp_date="2027-01-01", primary="FALSE"),
)

CSV_WITH_ADDRESS = _csv(
    _row(first_name="Jane", last_name="Smith", role="MD",
         email="jane.smith@example.com", phone="5555550100",
         fax="5555550101", npi="1234567890", dob="1980-03-15",
         addr1="123 Main St", addr2="Suite 200", city="New York",
         state="NY", zip_="10001"),
)


# ---------------------------------------------------------------------------
# parse_csv
# ---------------------------------------------------------------------------

class TestParseCsv:
    def test_single_practitioner(self):
        practitioners, warnings = parse_csv(MINIMAL_CSV)
        assert len(practitioners) == 1
        p = practitioners[0]
        assert p["first_name"] == "Jane"
        assert p["last_name"] == "Smith"
        assert p["role"] == "MD"
        assert p["email"] == "jane.smith@example.com"
        assert p["phone"] == "5555550100"
        assert p["dob"] == "1980-03-15"
        assert p["primary_practice_location"] == "Main Clinic"
        assert warnings == []

    def test_two_practitioners(self):
        practitioners, _ = parse_csv(TWO_PRACTITIONER_CSV)
        assert len(practitioners) == 2
        emails = {p["email"] for p in practitioners}
        assert "jane.smith@example.com" in emails
        assert "john.doe@example.com" in emails

    def test_multi_license_grouping(self):
        practitioners, _ = parse_csv(MULTI_LICENSE_CSV)
        # Two CSV rows for same email -> one practitioner with two licenses
        assert len(practitioners) == 1
        p = practitioners[0]
        assert len(p["licenses"]) == 2

    def test_license_fields_populated(self):
        practitioners, _ = parse_csv(MULTI_LICENSE_CSV)
        p = practitioners[0]
        first_lic = p["licenses"][0]
        assert first_lic["type"] == "State license"
        assert first_lic["name"] == "NY Medical Board"
        assert first_lic["license_state"] == "NY"
        assert first_lic["number"] == "MD12345"
        assert first_lic["issue_date"] == "2020-01-01"
        assert first_lic["expiration_date"] == "2026-01-01"
        assert first_lic["primary_raw"] == "TRUE"
        assert first_lic["is_primary"] is True

    def test_email_grouping_is_case_insensitive(self):
        practitioners, _ = parse_csv(CASE_INSENSITIVE_EMAIL_CSV)
        # Both rows have the same email (different case) -> one practitioner with 2 licenses
        assert len(practitioners) == 1
        assert len(practitioners[0]["licenses"]) == 2

    def test_continuation_conflict_produces_warning(self):
        practitioners, warnings = parse_csv(CONTINUATION_CONFLICT_CSV)
        assert len(practitioners) == 1
        assert len(warnings) > 0
        # Should warn about differing Primary Practice Location
        assert any("Practice Location" in w["message"] or
                   "practice_location" in w["message"].lower()
                   for w in warnings)

    def testsource_row_number_assigned(self):
        practitioners, _ = parse_csv(TWO_PRACTITIONER_CSV)
        row_numbers = {p["source_row_number"] for p in practitioners}
        assert 2 in row_numbers  # First data row is row 2

    def test_blank_email_continuation_row_forward_fills(self):
        """A license-only continuation row with a blank Email must be
        grouped with the preceding practitioner, not treated as an orphan.

        This is the shape real customer CSVs come in (e.g. a customer's bulk loader
        export): one row with full demographics, then N rows with only
        license columns populated.
        """
        csv_text = _csv(
            _row(first_name="Jane", last_name="Smith", role="MD",
                 location="Main Clinic", email="jane.smith@example.com",
                 phone="5555550100", dob="1980-03-15",
                 lic_type="State license", lic_name="NY Board", lic_state="NY",
                 lic_number="NY001", issue_date="2020-01-01", exp_date="2026-01-01",
                 primary="TRUE"),
            _row(lic_type="State license", lic_name="CA Board", lic_state="CA",
                 lic_number="CA001", issue_date="2021-01-01", exp_date="2027-01-01",
                 primary="FALSE"),  # email intentionally blank
            _row(lic_type="DEA", lic_number="DEA001",
                 issue_date="2022-01-01", exp_date="2028-01-01",
                 primary="FALSE"),  # email also blank
        )
        practitioners, _ = parse_csv(csv_text)
        assert len(practitioners) == 1
        p = practitioners[0]
        assert p["email"] == "jane.smith@example.com"
        assert len(p["licenses"]) == 3
        license_numbers = {lic["number"] for lic in p["licenses"]}
        assert license_numbers == {"NY001", "CA001", "DEA001"}

    def test_blank_email_with_populated_name_is_orphan_not_continuation(self):
        """Regression: a row with First/Last populated but Email blank must
        NOT be silently merged into the previous practitioner's group.

        Real-world failure (Lykos Medical CSV, ~29 staff): a typo'd blank
        Email cell on a new practitioner caused that practitioner's licenses
        to attach to the previous practitioner's record. Rule 14 emitted a
        demographic-mismatch warning but warnings don't gate the import.

        Fix routes the orphan to Rule 1 (Email required) as a hard error.
        """
        csv_text = _csv(
            _row(first_name="Jane", last_name="Smith", role="MD",
                 location="Main Clinic", email="jane.smith@example.com",
                 phone="5555550100", dob="1980-03-15",
                 lic_type="State license", lic_name="NY Board", lic_state="NY",
                 lic_number="NY001", issue_date="2020-01-01", exp_date="2026-01-01",
                 primary="TRUE"),
            _row(first_name="John", last_name="Doe", role="RN",  # email intentionally blank
                 phone="5555550200", dob="1985-06-20",
                 lic_type="State license", lic_name="CA Board", lic_state="CA",
                 lic_number="CA999", issue_date="2021-01-01", exp_date="2027-01-01",
                 primary="TRUE"),
        )
        practitioners, _ = parse_csv(csv_text)
        # Two separate groups, not one merged practitioner
        assert len(practitioners) == 2
        # John's CA999 license must NOT have attached to Jane
        jane = next(p for p in practitioners if p["email"] == "jane.smith@example.com")
        assert {lic["number"] for lic in jane["licenses"]} == {"NY001"}
        # John's row exists as a separate (orphan) practitioner with blank email
        john = next(p for p in practitioners if p["last_name"] == "Doe")
        assert john["email"] == ""
        assert {lic["number"] for lic in john["licenses"]} == {"CA999"}

    def test_blank_email_on_first_data_row_is_orphan(self):
        """If the very first data row has no email, there's nothing to
        forward-fill from; the row falls into a synthetic group so
        required-field validation can flag it."""
        csv_text = _csv(
            _row(lic_type="DEA", lic_number="DEA001"),  # no email, no demographics
            _row(first_name="Jane", last_name="Smith", role="MD",
                 email="jane.smith@example.com", phone="5555550100", dob="1980-03-15"),
        )
        practitioners, _ = parse_csv(csv_text)
        # Two groups: one orphan (row 2), one real practitioner (row 3)
        assert len(practitioners) == 2
        assert any(not p["email"].strip() for p in practitioners)

    def test_zero_width_chars_stripped_from_dates(self):
        """Dates copy-pasted from Word/Google Docs sometimes carry zero-width
        spaces (U+200B) between digits. The value looks correct to a human
        but fails date validation. Strip these before anything else sees them."""
        dirty_date = "1​2​/​0​1​/​2​0​2​5"
        csv_text = _csv(
            _row(first_name="Jane", last_name="Smith", role="MD",
                 email="jane@x.com", phone="5555550100", dob="03-15-1980",
                 lic_type="DEA", lic_number="D001",
                 issue_date=dirty_date, exp_date="06-01-2027"),
        )
        practitioners, _ = parse_csv(csv_text)
        assert len(practitioners) == 1
        p = practitioners[0]
        # The stored value should be stripped to "12/01/2025" — no invisibles.
        assert "​" not in p["licenses"][0]["issue_date"]
        assert p["licenses"][0]["issue_date"] == "12/01/2025"

    def test_primary_header_is_canonical(self):
        """'Primary' (without the 'License' prefix) is the canonical header."""
        csv_text = (
            _HEADER_NEW + "\n"
            "Jane,Smith,MD,,jane@x.com,5555550100,,,03-15-1980,,,,,,DEA,,,D001,01-01-2020,01-01-2026,YES\n"
        )
        practitioners, _ = parse_csv(csv_text)
        assert len(practitioners) == 1
        lic = practitioners[0]["licenses"][0]
        assert lic["primary_raw"] == "YES"
        assert lic["is_primary"] is True

    def test_legacy_license_primary_header_still_works(self):
        """The old 'License Primary' header is accepted for back-compat with
        templates generated by earlier plugin versions."""
        csv_text = (
            _HEADER + "\n"  # uses "License Primary"
            "Jane,Smith,MD,,jane@x.com,5555550100,,,03-15-1980,,,,,,DEA,,,D001,01-01-2020,01-01-2026,TRUE\n"
        )
        practitioners, _ = parse_csv(csv_text)
        lic = practitioners[0]["licenses"][0]
        assert lic["is_primary"] is True

    @pytest.mark.parametrize("value,expected", [
        ("TRUE", True), ("true", True), ("True", True),
        ("YES", True), ("yes", True), ("Yes", True),
        ("FALSE", False), ("false", False),
        ("NO", False), ("no", False), ("No", False),
        ("", False),  # blank = False
    ])
    def test_primary_value_variants(self, value, expected):
        csv_text = (
            _HEADER_NEW + "\n"
            f"Jane,Smith,MD,,jane@x.com,5555550100,,,03-15-1980,,,,,,DEA,,,D001,01-01-2020,01-01-2026,{value}\n"
        )
        practitioners, _ = parse_csv(csv_text)
        assert practitioners[0]["licenses"][0]["is_primary"] is expected

    def test_forward_fill_resets_when_new_email_appears(self):
        """A new non-blank Email starts a new group — continuation rows
        below it must not leak into the previous practitioner."""
        csv_text = _csv(
            _row(first_name="Jane", last_name="Smith", role="MD",
                 email="jane@x.com", phone="5555550100", dob="1980-03-15",
                 lic_type="DEA", lic_number="J-DEA"),
            _row(lic_type="State license", lic_number="J-STATE"),  # continues Jane
            _row(first_name="Bob", last_name="Jones", role="RN",
                 email="bob@x.com", phone="5555550200", dob="1985-06-20",
                 lic_type="DEA", lic_number="B-DEA"),
            _row(lic_type="State license", lic_number="B-STATE"),  # continues Bob
        )
        practitioners, _ = parse_csv(csv_text)
        assert len(practitioners) == 2
        by_email = {p["email"]: p for p in practitioners}
        assert {lic["number"] for lic in by_email["jane@x.com"]["licenses"]} == {"J-DEA", "J-STATE"}
        assert {lic["number"] for lic in by_email["bob@x.com"]["licenses"]} == {"B-DEA", "B-STATE"}

    def test_no_licenses_in_row(self):
        practitioners, _ = parse_csv(MINIMAL_CSV)
        p = practitioners[0]
        assert p["licenses"] == []

    def test_address_fields_parsed(self):
        practitioners, _ = parse_csv(CSV_WITH_ADDRESS)
        p = practitioners[0]
        assert p["address_line1"] == "123 Main St"
        assert p["address_line2"] == "Suite 200"
        assert p["city"] == "New York"
        assert p["state"] == "NY"
        assert p["zip"] == "10001"
        assert p["fax"] == "5555550101"
        assert p["npi"] == "1234567890"

    def test_blank_npi_defaults_to_sentinel(self):
        """A row with no NPI should have DEFAULT_NPI filled in."""
        csv = _csv(
            _row(first_name="Jane", last_name="Smith", role="MD",
                 email="jane.smith@example.com", phone="5555550100", dob="1980-03-15",
                 npi=""),  # blank NPI
        )
        practitioners, _ = parse_csv(csv)
        p = practitioners[0]
        assert p["npi"] == DEFAULT_NPI

    def test_whitespace_npi_defaults_to_sentinel(self):
        """A whitespace-only NPI should also be replaced by DEFAULT_NPI."""
        # Inject whitespace-only value via raw CSV construction
        csv_text = (
            _HEADER + "\n"
            "Jane,Smith,MD,,jane.smith@example.com,5555550100,,,1980-03-15,,,,,,,,,,,\n"
        )
        practitioners, _ = parse_csv(csv_text)
        p = practitioners[0]
        assert p["npi"] == DEFAULT_NPI

    def test_provided_npi_is_not_overwritten(self):
        """A non-blank NPI should pass through unchanged."""
        csv = _csv(
            _row(first_name="Jane", last_name="Smith", role="MD",
                 email="jane.smith@example.com", phone="5555550100", dob="1980-03-15",
                 npi="9876543210"),
        )
        practitioners, _ = parse_csv(csv)
        p = practitioners[0]
        assert p["npi"] == "9876543210"

    def test_default_npi_constant_value(self):
        """The sentinel constant must equal the known placeholder value."""
        assert DEFAULT_NPI == "1111155556"


# ---------------------------------------------------------------------------
# build_qualification
# ---------------------------------------------------------------------------

class TestBuildQualification:
    def test_qualification_structure(self):
        lic = {
            "type": "State license",
            "name": "NY Medical Board",
            "license_state": "NY",
            "number": "MD12345",
            "issue_date": "2020-01-01",
            "expiration_date": "2026-01-01",
            "primary_raw": "TRUE",
            "is_primary": True,
        }
        qual = build_qualification(lic)

        assert qual["identifier"][0]["system"] == (
            "http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-url"
        )
        assert qual["identifier"][0]["value"] == "MD12345"
        # "State license" CSV alias is normalised to the canonical "STATE"
        # which is what Canvas's API actually accepts on code.text.
        assert qual["code"]["text"] == "STATE"
        assert qual["period"]["start"] == "2020-01-01"
        assert qual["period"]["end"] == "2026-01-01"
        assert qual["issuer"]["display"] == "NY Medical Board"

        # Canvas stores qualification-level data on issuer.extension, not at
        # the qualification's top-level extension.
        exts = {e["url"]: e for e in qual["issuer"]["extension"]}
        assert exts["http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-short-name"]["valueString"] == "NY Medical Board"
        assert exts["http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-state"]["valueString"] == "NY"
        assert exts["http://schemas.canvasmedical.com/fhir/extensions/license-primary"]["valueBoolean"] is True
        assert "extension" not in qual, "qualification should not have top-level extension"

    def test_issuer_extension_slot_0_is_short_name_even_when_license_name_blank(self):
        """Canvas requires issuer.extension[0].url to be .../issuing-authority-short-name
        with a non-empty valueString. When License Name is blank (legitimate for
        non-Other license types), fall back to ``"{License Type} {License State}"``
        — e.g. "STATE NY" — so the resulting label distinguishes between
        multiple state licenses on the same practitioner."""
        lic = {
            "type": "State license",
            "name": "",  # blank — as it is on real customer CSVs with no License Name column
            "license_state": "NY",
            "number": "MD12345",
            "issue_date": "",
            "expiration_date": "",
            "primary_raw": "FALSE",
            "is_primary": False,
        }
        qual = build_qualification(lic)
        first = qual["issuer"]["extension"][0]
        assert first["url"] == "http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-short-name"
        assert first["valueString"] == "STATE NY"
        assert qual["issuer"]["display"] == "STATE NY"

    def test_blank_license_name_no_state_falls_back_to_just_type(self):
        """For non-state license types (DEA, CLIA, TAXONOMY) where there's
        no License State to combine with, the fallback is just the License
        Type alone — "STATE NY" with no state would be misleading."""
        lic = {
            "type": "DEA",
            "name": "",
            "license_state": "",
            "number": "DEA001",
            "issue_date": "",
            "expiration_date": "",
            "primary_raw": "FALSE",
            "is_primary": False,
        }
        qual = build_qualification(lic)
        assert qual["issuer"]["display"] == "DEA"
        assert qual["issuer"]["extension"][0]["valueString"] == "DEA"

    def test_no_dates_omits_period_keys(self):
        lic = {"type": "DEA", "name": "", "license_state": "", "number": "DEA001",
               "issue_date": "", "expiration_date": "", "primary_raw": "FALSE", "is_primary": False}
        qual = build_qualification(lic)
        assert "start" not in qual["period"]
        assert "end" not in qual["period"]

    def test_mm_dd_yyyy_dates_normalised_to_iso_for_fhir(self):
        """MM-DD-YYYY and MM/DD/YYYY license dates must be converted to ISO
        YYYY-MM-DD before being sent to Fumage — Canvas expects FHIR dates."""
        lic = {
            "type": "State license", "name": "NY Board", "license_state": "NY",
            "number": "MD001",
            "issue_date": "01-01-2020",       # dashes
            "expiration_date": "12/31/2025",  # slashes
            "primary_raw": "TRUE", "is_primary": True,
        }
        qual = build_qualification(lic)
        assert qual["period"]["start"] == "2020-01-01"
        assert qual["period"]["end"] == "2025-12-31"

    def test_lowercase_type_normalised_to_all_caps(self):
        """User-typed 'state license' (lowercase) normalises to Canvas's
        canonical 'STATE' for the FHIR code.text."""
        lic = {
            "type": "state license",
            "name": "NY Board",
            "license_state": "NY",
            "number": "MD001",
            "issue_date": "",
            "expiration_date": "",
            "primary_raw": "TRUE",
            "is_primary": True,
        }
        qual = build_qualification(lic)
        assert qual["code"]["text"] == "STATE"

    def test_other_normalised_to_all_caps(self):
        """All casings of the Other alias map to the canonical 'OTHER'."""
        lic = {
            "type": "Other",
            "name": "Custom Board",
            "license_state": "",
            "number": "C001",
            "issue_date": "",
            "expiration_date": "",
            "primary_raw": "FALSE",
            "is_primary": False,
        }
        qual = build_qualification(lic)
        assert qual["code"]["text"] == "OTHER"


# ---------------------------------------------------------------------------
# build_fhir_practitioner
# ---------------------------------------------------------------------------

class TestBuildFhirPractitioner:
    def _minimal_prac(self):
        return {
            "first_name": "Jane",
            "last_name": "Smith",
            "role": "MD",
            "email": "jane@example.com",
            "phone": "5555550100",
            "dob": "1980-03-15",
            "fax": "",
            "npi": "",
            "address_line1": "",
            "address_line2": "",
            "city": "",
            "state": "",
            "zip": "",
            "primary_practice_location": "",
            "licenses": [],
        }

    def test_basic_structure(self):
        resource = build_fhir_practitioner(self._minimal_prac(), {})
        assert resource["resourceType"] == "Practitioner"
        assert resource["name"][0]["use"] == "usual"
        assert resource["name"][0]["given"] == ["Jane"]
        assert resource["name"][0]["family"] == "Smith"
        assert resource["birthDate"] == "1980-03-15"

    def test_birthdate_mm_dd_yyyy_normalised_to_iso(self):
        """DOB in MM-DD-YYYY form must be converted to ISO for FHIR."""
        prac = self._minimal_prac()
        prac["dob"] = "03-15-1980"
        resource = build_fhir_practitioner(prac, {})
        assert resource["birthDate"] == "1980-03-15"

    def test_username_extension_omitted_by_default(self):
        """Without an override, the extension is left out so Canvas can
        auto-generate ``firstlast``. The API handler retries with an
        explicit override only after a username-collision 422."""
        resource = build_fhir_practitioner(self._minimal_prac(), {})
        username_exts = [
            e for e in resource["extension"]
            if e.get("url") == "http://schemas.canvasmedical.com/fhir/extensions/practitioner-user-username"
        ]
        assert username_exts == []

    def test_username_override_emits_extension_verbatim(self):
        """Caller supplies a sanitised username (e.g. from build_username());
        it lands in the resource as-is."""
        resource = build_fhir_practitioner(
            self._minimal_prac(), {}, username_override="maria.garcia"
        )
        username_exts = [
            e for e in resource["extension"]
            if e.get("url") == "http://schemas.canvasmedical.com/fhir/extensions/practitioner-user-username"
        ]
        assert len(username_exts) == 1
        assert username_exts[0]["valueString"] == "maria.garcia"

    def test_telecom_phone_and_email(self):
        resource = build_fhir_practitioner(self._minimal_prac(), {})
        systems = {t["system"] for t in resource["telecom"]}
        assert "phone" in systems
        assert "email" in systems

    def test_role_extension(self):
        resource = build_fhir_practitioner(self._minimal_prac(), {})
        role_ext = next(
            (e for e in resource["extension"]
             if e["url"] == "http://schemas.canvasmedical.com/fhir/extensions/roles"),
            None,
        )
        assert role_ext is not None
        assert role_ext["extension"][0]["valueCoding"]["code"] == "MD"

    def test_fax_added_when_present(self):
        prac = self._minimal_prac()
        prac["fax"] = "5555550199"
        resource = build_fhir_practitioner(prac, {})
        fax_entries = [t for t in resource["telecom"] if t["system"] == "fax"]
        assert len(fax_entries) == 1
        assert fax_entries[0]["value"] == "5555550199"

    def test_npi_identifier_when_present(self):
        prac = self._minimal_prac()
        prac["npi"] = "1234567890"
        resource = build_fhir_practitioner(prac, {})
        assert resource["identifier"][0]["system"] == "http://hl7.org/fhir/sid/us-npi"
        assert resource["identifier"][0]["value"] == "1234567890"

    def test_location_extension_added_when_found(self):
        prac = self._minimal_prac()
        prac["primary_practice_location"] = "Main Clinic"
        loc_map = {"main clinic": "Location/abc123"}
        resource = build_fhir_practitioner(prac, loc_map)
        loc_ext = next(
            (e for e in resource["extension"]
             if "primary-practice-location" in e["url"]),
            None,
        )
        assert loc_ext is not None
        assert loc_ext["valueReference"]["reference"] == "Location/abc123"

    def test_location_extension_absent_when_not_found(self):
        prac = self._minimal_prac()
        prac["primary_practice_location"] = "Unknown Clinic"
        resource = build_fhir_practitioner(prac, {})
        loc_ext = next(
            (e for e in resource["extension"]
             if "primary-practice-location" in e["url"]),
            None,
        )
        assert loc_ext is None

    def test_address_fields(self):
        prac = self._minimal_prac()
        prac.update({
            "address_line1": "123 Main St",
            "address_line2": "Suite 200",
            "city": "New York",
            "state": "NY",
            "zip": "10001",
        })
        resource = build_fhir_practitioner(prac, {})
        assert "address" in resource
        addr = resource["address"][0]
        assert addr["use"] == "work"
        assert addr["type"] == "both"
        assert addr["country"] == "US"
        assert "123 Main St" in addr["line"]
        assert addr["city"] == "New York"
        assert addr["state"] == "NY"
        assert addr["postalCode"] == "10001"

    def test_address_country_defaults_to_us_when_only_partial_address(self):
        prac = self._minimal_prac()
        prac.update({"city": "New York"})
        resource = build_fhir_practitioner(prac, {})
        addr = resource["address"][0]
        assert addr["country"] == "US"

    def test_qualifications_from_licenses(self):
        prac = self._minimal_prac()
        prac["licenses"] = [{
            "type": "State license", "name": "Board", "license_state": "NY",
            "number": "MD001", "issue_date": "2020-01-01",
            "expiration_date": "2026-01-01", "primary_raw": "TRUE", "is_primary": True,
        }]
        resource = build_fhir_practitioner(prac, {})
        assert "qualification" in resource
        assert len(resource["qualification"]) == 1

    def test_no_address_when_all_empty(self):
        resource = build_fhir_practitioner(self._minimal_prac(), {})
        assert "address" not in resource

    def test_default_npi_appears_in_fhir_identifier(self):
        """When npi=DEFAULT_NPI the identifier block should still be emitted."""
        prac = self._minimal_prac()
        prac["npi"] = DEFAULT_NPI
        resource = build_fhir_practitioner(prac, {})
        assert "identifier" in resource
        assert resource["identifier"][0]["value"] == DEFAULT_NPI


# ---------------------------------------------------------------------------
# diff_licenses
# ---------------------------------------------------------------------------

class TestDiffLicenses:
    def _make_existing_qual(self, code_text, number, start=None, end=None):
        qual = {
            "code": {"text": code_text},
            "identifier": [
                {
                    "system": "http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-url",
                    "value": number,
                }
            ],
        }
        if start or end:
            period = {}
            if start:
                period["start"] = start
            if end:
                period["end"] = end
            qual["period"] = period
        return qual

    def test_no_existing_returns_all_incoming(self):
        incoming = [
            {"type": "STATE", "number": "MD001", "name": "", "license_state": "NY",
             "issue_date": "", "expiration_date": "", "primary_raw": "TRUE", "is_primary": True},
        ]
        new, renewals = diff_licenses([], incoming)
        assert len(new) == 1
        assert renewals == []

    def test_exact_match_with_same_dates_excluded_from_both_buckets(self):
        existing = [self._make_existing_qual(
            "STATE", "MD001", start="2020-01-01", end="2026-01-01")]
        incoming = [
            {"type": "STATE", "number": "MD001", "name": "", "license_state": "",
             "issue_date": "2020-01-01", "expiration_date": "2026-01-01",
             "primary_raw": "TRUE", "is_primary": True},
        ]
        new, renewals = diff_licenses(existing, incoming)
        assert new == []
        assert renewals == []

    def test_match_with_different_expiration_returns_renewal(self):
        """Same type+number but a newer expiration → renewal bucket so the
        admin can update Canvas's stored period instead of creating a
        duplicate qualification."""
        existing_qual = self._make_existing_qual(
            "STATE", "MD001", start="2020-01-01", end="2026-01-01")
        existing = [existing_qual]
        incoming = [
            {"type": "STATE", "number": "MD001", "name": "", "license_state": "",
             "issue_date": "2020-01-01", "expiration_date": "2028-01-01",
             "primary_raw": "TRUE", "is_primary": True},
        ]
        new, renewals = diff_licenses(existing, incoming)
        assert new == []
        assert len(renewals) == 1
        incoming_lic, target_qual = renewals[0]
        assert incoming_lic["expiration_date"] == "2028-01-01"
        assert target_qual is existing_qual  # reference the original for in-place update

    def test_match_with_different_issue_date_returns_renewal(self):
        existing = [self._make_existing_qual(
            "STATE", "MD001", start="2020-01-01", end="2026-01-01")]
        incoming = [
            {"type": "STATE", "number": "MD001", "name": "", "license_state": "",
             "issue_date": "2020-06-01", "expiration_date": "2026-01-01",
             "primary_raw": "TRUE", "is_primary": True},
        ]
        new, renewals = diff_licenses(existing, incoming)
        assert len(renewals) == 1

    def test_csv_blank_dates_do_not_force_renewal(self):
        """A CSV row that omits dates shouldn't blow away Canvas's existing
        dates by being flagged as a renewal."""
        existing = [self._make_existing_qual(
            "STATE", "MD001", start="2020-01-01", end="2026-01-01")]
        incoming = [
            {"type": "STATE", "number": "MD001", "name": "", "license_state": "",
             "issue_date": "", "expiration_date": "",
             "primary_raw": "TRUE", "is_primary": True},
        ]
        new, renewals = diff_licenses(existing, incoming)
        assert renewals == []
        assert new == []

    def test_renewal_recognises_mm_dd_yyyy_csv_dates(self):
        """CSV may carry MM-DD-YYYY; canonicalise before comparing."""
        existing = [self._make_existing_qual(
            "STATE", "MD001", start="2020-01-01", end="2026-01-01")]
        incoming = [
            {"type": "STATE", "number": "MD001", "name": "", "license_state": "",
             "issue_date": "01-01-2020", "expiration_date": "01-01-2028",
             "primary_raw": "TRUE", "is_primary": True},
        ]
        new, renewals = diff_licenses(existing, incoming)
        assert len(renewals) == 1

    def test_different_number_included_as_new(self):
        existing = [self._make_existing_qual("STATE", "MD001")]
        incoming = [
            {"type": "STATE", "number": "MD002", "name": "", "license_state": "",
             "issue_date": "", "expiration_date": "", "primary_raw": "TRUE", "is_primary": True},
        ]
        new, renewals = diff_licenses(existing, incoming)
        assert len(new) == 1
        assert new[0]["number"] == "MD002"
        assert renewals == []

    def test_different_type_included_as_new(self):
        existing = [self._make_existing_qual("STATE", "MD001")]
        incoming = [
            {"type": "DEA", "number": "MD001", "name": "", "license_state": "",
             "issue_date": "", "expiration_date": "", "primary_raw": "FALSE", "is_primary": False},
        ]
        new, renewals = diff_licenses(existing, incoming)
        assert len(new) == 1
        assert renewals == []

    def test_mixed_new_renewal_and_unchanged(self):
        existing = [
            self._make_existing_qual("STATE", "MD001", start="2020-01-01", end="2026-01-01"),
            self._make_existing_qual("DEA",   "DEA1",  start="2021-01-01", end="2027-01-01"),
        ]
        incoming = [
            # unchanged — same dates, no action
            {"type": "STATE", "number": "MD001", "name": "", "license_state": "",
             "issue_date": "2020-01-01", "expiration_date": "2026-01-01",
             "primary_raw": "TRUE", "is_primary": True},
            # renewal — same type+number, different expiration
            {"type": "DEA", "number": "DEA1", "name": "", "license_state": "",
             "issue_date": "2021-01-01", "expiration_date": "2029-01-01",
             "primary_raw": "FALSE", "is_primary": False},
            # new — number not on file
            {"type": "PTAN", "number": "PT-99", "name": "", "license_state": "",
             "issue_date": "2022-01-01", "expiration_date": "2028-01-01",
             "primary_raw": "FALSE", "is_primary": False},
        ]
        new, renewals = diff_licenses(existing, incoming)
        assert len(new) == 1
        assert new[0]["number"] == "PT-99"
        assert len(renewals) == 1
        assert renewals[0][0]["number"] == "DEA1"

    def test_canvas_license_fallback_matches_incoming_other(self):
        """Canvas downgrades incoming OTHER/SPI to ``code.text="License"`` on
        storage. When a CSV is re-uploaded, the diff must still recognise
        that license as already-present even though the type label changed."""
        existing = [{
            "code": {"text": "License"},
            "identifier": [{
                "system": "http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-url",
                "value": "MA00123",
            }],
        }]
        incoming = [{"type": "OTHER", "number": "MA00123"}]
        new, renewals = diff_licenses(existing, incoming)
        assert new == []
        assert renewals == []

    def test_canvas_license_fallback_matches_incoming_spi(self):
        existing = [{
            "code": {"text": "License"},
            "identifier": [{
                "system": "http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-url",
                "value": "SPI-999",
            }],
        }]
        incoming = [{"type": "SPI", "number": "SPI-999"}]
        new, renewals = diff_licenses(existing, incoming)
        assert new == []
        assert renewals == []

    def test_canvas_license_fallback_does_not_collide_across_numbers(self):
        existing = [{
            "code": {"text": "License"},
            "identifier": [{
                "system": "http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-url",
                "value": "OLD-1",
            }],
        }]
        incoming = [{"type": "OTHER", "number": "NEW-2"}]
        new, renewals = diff_licenses(existing, incoming)
        assert len(new) == 1
        assert renewals == []


# ---------------------------------------------------------------------------
# build_username — sanitization for the practitioner-user-username extension
# ---------------------------------------------------------------------------

class TestBuildUsername:
    def test_basic_alphanumeric_names(self):
        assert build_username("Maria", "Garcia") == "maria.garcia"

    def test_lowercases_uppercase_input(self):
        assert build_username("JOHN", "DOE") == "john.doe"

    def test_strips_accents_via_unicode_normalization(self):
        """Non-ASCII accented chars decompose to their ASCII base via NFKD."""
        assert build_username("José", "García") == "jose.garcia"
        assert build_username("Mårten", "Müller") == "marten.muller"

    def test_drops_punctuation_and_spaces(self):
        """Hyphens, apostrophes, and spaces are stripped — they're not
        valid in the username slot Canvas uses."""
        assert build_username("Mary-Ann", "O'Brien") == "maryann.obrien"
        assert build_username("Mary Ann", "Smith") == "maryann.smith"

    def test_empty_first_or_last_returns_empty(self):
        """Caller should omit the extension entirely so Canvas can default."""
        assert build_username("", "Garcia") == ""
        assert build_username("Maria", "") == ""
        assert build_username("", "") == ""

    def test_all_non_ascii_returns_empty(self):
        """Nothing left after sanitization → empty so the extension is dropped."""
        assert build_username("李", "王") == ""

    def test_strips_emoji(self):
        assert build_username("Maria🎉", "Garcia") == "maria.garcia"


# ---------------------------------------------------------------------------
# _extract_license: Primary column alone must not create a phantom license
# ---------------------------------------------------------------------------

class TestPrimaryOnlyDoesNotCreatePhantomLicense:
    """Regression: a row where every license column is blank except
    ``Primary`` (a defensive ``FALSE`` / ``NO`` / ``TRUE`` / ``YES`` paste,
    or an Excel autofill of the Primary column down the whole sheet) used
    to produce a phantom license dict that survived validation and then
    failed Canvas FHIR with the opaque "License N: a required value is
    empty." The phantom is gone — a license dict is only kept when at
    least one of {type, name, license_state, number, issue_date,
    expiration_date} is populated."""

    def test_primary_false_alone_does_not_create_license(self):
        csv_text = _csv(_row(
            first_name="Jane", last_name="Smith", role="MD",
            location="Main Clinic", email="jane@x.com",
            phone="5555550100", dob="03-15-1980",
            # Every license column blank — only Primary set.
            primary="FALSE",
        ))
        practitioners, _ = parse_csv(csv_text)
        assert len(practitioners) == 1
        # No phantom license — empty list is correct.
        assert practitioners[0]["licenses"] == []

    @pytest.mark.parametrize("primary_value", ["TRUE", "YES", "FALSE", "NO"])
    def test_any_primary_value_alone_does_not_create_license(self, primary_value):
        csv_text = _csv(_row(
            first_name="Jane", last_name="Smith", role="MD",
            location="Main Clinic", email="jane@x.com",
            phone="5555550100", dob="03-15-1980",
            primary=primary_value,
        ))
        practitioners, _ = parse_csv(csv_text)
        assert practitioners[0]["licenses"] == []

    def test_primary_plus_one_identifying_field_keeps_license(self):
        """Sanity: a row with Primary AND one real license field still
        produces a license — the gate is "at least one identifying field",
        not "all blank except Primary."""
        csv_text = _csv(_row(
            first_name="Jane", last_name="Smith", role="MD",
            location="Main Clinic", email="jane@x.com",
            phone="5555550100", dob="03-15-1980",
            lic_type="DEA", primary="TRUE",
        ))
        practitioners, _ = parse_csv(csv_text)
        assert len(practitioners[0]["licenses"]) == 1
        assert practitioners[0]["licenses"][0]["type"] == "DEA"

    def test_continuation_row_with_only_primary_drops_phantom(self):
        """Real customer pattern: continuation row pastes Primary=FALSE
        on every row including ones with no real license. The continuation
        row contributes no license; only rows with identifying fields do."""
        csv_text = _csv(
            _row(
                first_name="Jane", last_name="Smith", role="MD",
                location="Main Clinic", email="jane@x.com",
                phone="5555550100", dob="03-15-1980",
                lic_type="DEA", lic_number="D001", primary="TRUE",
            ),
            # Continuation row — only Primary set, every other column blank
            _row(primary="FALSE"),
        )
        practitioners, _ = parse_csv(csv_text)
        assert len(practitioners) == 1
        # Exactly one license — the DEA from the first row. The Primary-only
        # continuation row added no phantom.
        assert len(practitioners[0]["licenses"]) == 1
        assert practitioners[0]["licenses"][0]["type"] == "DEA"


# ---------------------------------------------------------------------------
# Orphan row acts as a barrier — subsequent continuation rows don't leak
# back to the prior practitioner. Regression against the deeper layer of
# the Lykos misattribution pattern Kevin Carey reported.
# ---------------------------------------------------------------------------

class TestOrphanRowResetsContinuationContext:
    """A row with blank email + populated First/Last (an orphan)
    correctly fails Rule 1. The bug being protected against: any
    subsequent license-only continuation row (blank email + blank name)
    would silently inherit the PRIOR practitioner's email and attach its
    licenses to the wrong record. The orphan must reset the
    last-seen-email tracker so any continuation rows after it also
    become orphans rather than latching onto the prior group."""

    def test_continuation_after_orphan_does_not_attach_to_prior(self):
        csv_text = _csv(
            # Practitioner 1: Jane (full row)
            _row(
                first_name="Jane", last_name="Smith", role="MD",
                location="Main Clinic", email="jane@x.com",
                phone="5555550100", dob="03-15-1980",
                lic_type="DEA", lic_number="DEA-JANE", primary="TRUE",
            ),
            # Practitioner 2: Bob (orphan — blank email + populated name)
            _row(
                first_name="Bob", last_name="Orphan", role="MD",
                location="Main Clinic", email="",
                phone="5555550200", dob="04-20-1982",
                lic_type="DEA", lic_number="DEA-BOB", primary="TRUE",
            ),
            # License-only continuation row — blank email + blank name.
            # Pre-fix this attached to Jane; post-fix it becomes its own
            # orphan (synthetic key, fails Rule 1).
            _row(
                lic_type="STATE", lic_state="CA",
                lic_number="STATE-LEAKED", primary="FALSE",
            ),
        )
        practitioners, _ = parse_csv(csv_text)
        # Find Jane's group; it must NOT include STATE-LEAKED.
        jane = next(p for p in practitioners if p["email"] == "jane@x.com")
        jane_license_numbers = {lic["number"] for lic in jane["licenses"]}
        assert "STATE-LEAKED" not in jane_license_numbers, (
            "STATE license from the row AFTER Bob (the orphan) leaked "
            "back to Jane — orphan should have acted as a barrier."
        )
        assert "DEA-JANE" in jane_license_numbers
        # Bob is also an orphan (no email) — he'll fail Rule 1 too, but
        # he's parsed as a separate practitioner, not merged into Jane.
        non_jane = [p for p in practitioners if p["email"] != "jane@x.com"]
        for p in non_jane:
            assert "DEA-JANE" not in {lic["number"] for lic in p["licenses"]}

    def test_two_orphans_back_to_back_each_get_separate_groups(self):
        csv_text = _csv(
            _row(
                first_name="Jane", last_name="Smith", role="MD",
                location="Main Clinic", email="jane@x.com",
                phone="5555550100", dob="03-15-1980",
                lic_type="DEA", lic_number="DEA-JANE", primary="TRUE",
            ),
            _row(  # Orphan 1
                first_name="Bob", last_name="Orphan1", role="MD",
                phone="5555550200", dob="04-20-1982",
                location="Main Clinic", email="",
            ),
            _row(  # Orphan 2 — must not attach to Bob OR to Jane
                first_name="Cara", last_name="Orphan2", role="MD",
                phone="5555550300", dob="05-25-1983",
                location="Main Clinic", email="",
            ),
        )
        practitioners, _ = parse_csv(csv_text)
        # Jane's group stays clean
        jane = next(p for p in practitioners if p["email"] == "jane@x.com")
        assert jane["first_name"] == "Jane"
        # Bob and Cara each end up as separate (orphan) groups
        names = sorted(p["first_name"] for p in practitioners)
        assert names == ["Bob", "Cara", "Jane"]


# ---------------------------------------------------------------------------
# UTF-8 BOM in CSV headers — Windows Excel default save format adds one
# ---------------------------------------------------------------------------

class TestValidateCsvHeadersStripsBOM:
    """Excel for Windows' default ``CSV UTF-8 (Comma delimited)`` save
    format prefixes the file with a UTF-8 BOM (``\\ufeff``). Without
    stripping, the first header becomes ``"\\ufeffFirst Name"`` and the
    required-headers check emits the misleading "Required column 'First
    Name' is missing" while the admin is staring at a First Name column.
    """

    def test_bom_prefix_does_not_break_header_validation(self):
        csv_text = "﻿" + _HEADER + "\n"
        errors = validate_csv_headers(csv_text)
        # No "First Name is missing" error.
        assert not any(
            "first name" in e["message"].lower() and "missing" in e["message"].lower()
            for e in errors
        )

    def test_bom_prefixed_csv_parses_first_name_correctly(self):
        """End-to-end: BOM-prefixed CSV parses cleanly all the way through."""
        csv_text = "﻿" + _csv(_row(
            first_name="Ada", last_name="Lovelace", role="MD",
            location="Main Clinic", email="ada@x.com",
            phone="5555550100", dob="03-15-1980",
            lic_type="DEA", lic_number="DEA-A", primary="TRUE",
        ))
        practitioners, _ = parse_csv(csv_text)
        assert len(practitioners) == 1
        assert practitioners[0]["first_name"] == "Ada"
        assert practitioners[0]["last_name"] == "Lovelace"
