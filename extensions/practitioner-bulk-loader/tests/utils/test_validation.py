"""Tests for practitioner_bulk_loader.utils.validation."""

import pytest

from practitioner_bulk_loader.utils.validation import (
    ValidationError,
    ValidationWarning,
    _is_valid_date,
    canonicalize_license_type,
    to_fhir_date,
    validate_continuation_row,
    validate_practitioner,
)


# ---------------------------------------------------------------------------
# to_fhir_date: normalise accepted formats to ISO for the FHIR API boundary
# ---------------------------------------------------------------------------

class TestToFhirDate:
    def test_mm_dd_yyyy_dashes(self):
        assert to_fhir_date("03-15-1980") == "1980-03-15"

    def test_mm_dd_yyyy_slashes(self):
        assert to_fhir_date("03/15/1980") == "1980-03-15"

    def test_unpadded_month_and_day(self):
        assert to_fhir_date("1/8/1973") == "1973-01-08"
        assert to_fhir_date("1-1-2023") == "2023-01-01"

    def test_iso_passes_through(self):
        assert to_fhir_date("1980-03-15") == "1980-03-15"

    def test_blank_returns_blank(self):
        assert to_fhir_date("") == ""

    def test_invalid_passes_through_unchanged(self):
        """Validation has already caught bad inputs; to_fhir_date is a
        normaliser, not a second validator — it must not raise."""
        assert to_fhir_date("not-a-date") == "not-a-date"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_prac(**overrides):
    """Return a minimal valid practitioner dict, with optional overrides."""
    base = {
        "first_name": "Jane",
        "last_name": "Smith",
        "role": "MD",
        "email": "jane.smith@example.com",
        "phone": "5555550100",
        "dob": "1980-03-15",
        "primary_practice_location": "Main Clinic",
        "fax": "",
        "npi": "",
        "state": "",
        "zip": "",
        "licenses": [],
    }
    base.update(overrides)
    return base


def make_license(**overrides):
    base = {
        "type": "State license",
        "name": "NY Medical Board",
        "license_state": "NY",
        "number": "MD12345",
        "issue_date": "2020-01-01",
        "expiration_date": "2026-01-01",
        "primary_raw": "TRUE",
        "is_primary": True,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _is_valid_date
# ---------------------------------------------------------------------------

class TestIsValidDate:
    def test_valid_date(self):
        assert _is_valid_date("2020-01-15") is True

    def test_leap_year_valid(self):
        assert _is_valid_date("2024-02-29") is True

    def test_non_leap_year_feb29_invalid(self):
        assert _is_valid_date("2023-02-29") is False

    def test_invalid_month(self):
        assert _is_valid_date("2020-13-01") is False

    def test_invalid_day(self):
        assert _is_valid_date("2020-01-32") is False

    def test_wrong_format(self):
        # Two-digit year, no separator, and text are all rejected.
        assert _is_valid_date("03-15-80") is False
        assert _is_valid_date("1980.03.15") is False
        assert _is_valid_date("not-a-date") is False

    def test_mm_dd_yyyy_dashes_accepted(self):
        assert _is_valid_date("03-15-1980") is True
        assert _is_valid_date("3-15-1980") is True  # unpadded

    def test_mm_dd_yyyy_slashes_accepted(self):
        assert _is_valid_date("03/15/1980") is True
        assert _is_valid_date("1/1/2023") is True  # unpadded, slashes

    def test_iso_still_accepted(self):
        assert _is_valid_date("1980-03-15") is True

    def test_invalid_month_rejected(self):
        assert _is_valid_date("13-01-1980") is False
        assert _is_valid_date("1980-13-01") is False

    def test_empty_string(self):
        assert _is_valid_date("") is False

    def test_partial_date(self):
        assert _is_valid_date("2020-01") is False


# ---------------------------------------------------------------------------
# validate_practitioner — happy path
# ---------------------------------------------------------------------------

class TestValidatePractitionerHappyPath:
    def test_minimal_valid_record(self):
        errors, warnings = validate_practitioner(2, make_prac())
        assert errors == []
        assert warnings == []

    def test_valid_with_all_optional_fields(self):
        prac = make_prac(
            fax="5555550199",
            npi="1234567890",
            state="CA",
            zip="90210",
            licenses=[make_license()],
        )
        errors, warnings = validate_practitioner(2, prac)
        assert errors == []
        assert warnings == []

    def test_valid_with_multiple_licenses_one_primary(self):
        lic1 = make_license(primary_raw="TRUE", is_primary=True)
        lic2 = make_license(type="DEA", number="AB1234567", primary_raw="FALSE", is_primary=False)
        prac = make_prac(licenses=[lic1, lic2])
        errors, warnings = validate_practitioner(2, prac)
        assert errors == []
        assert warnings == []


# ---------------------------------------------------------------------------
# Rule 1: Required fields
# ---------------------------------------------------------------------------

class TestRequiredFields:
    @pytest.mark.parametrize("field", [
        "first_name", "last_name", "role", "email", "phone", "dob",
        "primary_practice_location",
    ])
    def test_missing_required_field(self, field):
        prac = make_prac(**{field: ""})
        errors, _ = validate_practitioner(2, prac)
        assert any(e.field.lower().replace(" ", "_") == field for e in errors)

    @pytest.mark.parametrize("field", [
        "first_name", "last_name", "role", "email", "phone", "dob",
        "primary_practice_location",
    ])
    def test_missing_required_field_value_is_empty_string(self, field):
        prac = make_prac(**{field: ""})
        errors, _ = validate_practitioner(2, prac)
        matching = [e for e in errors if e.field.lower().replace(" ", "_") == field]
        assert matching, f"Expected error for {field}"
        assert matching[0].value == ""


# ---------------------------------------------------------------------------
# Rule 2: Email format
# ---------------------------------------------------------------------------

class TestEmailValidation:
    @pytest.mark.parametrize("bad_email", [
        "not-an-email",
        "missing@",
        "@nodomain.com",
        "spaces in@email.com",
    ])
    def test_bad_email_formats(self, bad_email):
        prac = make_prac(email=bad_email)
        errors, _ = validate_practitioner(2, prac)
        assert any(e.field == "Email" for e in errors)

    @pytest.mark.parametrize("good_email", [
        "user@example.com",
        "user.name+tag@sub.domain.org",
        "x@x.co",
    ])
    def test_good_email_formats(self, good_email):
        prac = make_prac(email=good_email)
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "Email" for e in errors)

    def test_email_value_is_raw_string(self):
        """value must be the exact CSV string that failed — not normalised."""
        bad = "not-an-email"
        prac = make_prac(email=bad)
        errors, _ = validate_practitioner(2, prac)
        email_errs = [e for e in errors if e.field == "Email"]
        assert email_errs, "Expected Email error"
        assert email_errs[0].value == bad


# ---------------------------------------------------------------------------
# Rule 3: Phone digits-only
# ---------------------------------------------------------------------------

class TestPhoneValidation:
    def test_phone_with_dashes_fails(self):
        errors, _ = validate_practitioner(2, make_prac(phone="555-555-0100"))
        assert any(e.field == "Phone" for e in errors)

    def test_phone_with_spaces_fails(self):
        errors, _ = validate_practitioner(2, make_prac(phone="555 555 0100"))
        assert any(e.field == "Phone" for e in errors)

    def test_phone_digits_only_passes(self):
        errors, _ = validate_practitioner(2, make_prac(phone="5555550100"))
        assert not any(e.field == "Phone" for e in errors)


# ---------------------------------------------------------------------------
# Rule 4: Fax digits-only
# ---------------------------------------------------------------------------

class TestFaxValidation:
    def test_fax_with_parens_fails(self):
        errors, _ = validate_practitioner(2, make_prac(fax="(555)5550100"))
        assert any(e.field == "Fax" for e in errors)

    def test_fax_digits_only_passes(self):
        errors, _ = validate_practitioner(2, make_prac(fax="5555550100"))
        assert not any(e.field == "Fax" for e in errors)

    def test_empty_fax_ignored(self):
        errors, _ = validate_practitioner(2, make_prac(fax=""))
        assert not any(e.field == "Fax" for e in errors)


# ---------------------------------------------------------------------------
# Rule 5: NPI exactly 10 digits
# ---------------------------------------------------------------------------

class TestNPIValidation:
    def test_npi_9_digits_fails(self):
        errors, _ = validate_practitioner(2, make_prac(npi="123456789"))
        assert any(e.field == "NPI" for e in errors)

    def test_npi_11_digits_fails(self):
        errors, _ = validate_practitioner(2, make_prac(npi="12345678901"))
        assert any(e.field == "NPI" for e in errors)

    def test_npi_10_digits_passes(self):
        errors, _ = validate_practitioner(2, make_prac(npi="1234567890"))
        assert not any(e.field == "NPI" for e in errors)

    def test_empty_npi_ignored(self):
        errors, _ = validate_practitioner(2, make_prac(npi=""))
        assert not any(e.field == "NPI" for e in errors)

    def test_npi_value_is_raw_string(self):
        """value must be the exact CSV string that failed (e.g. alphabetic NPI)."""
        bad = "abc123"
        prac = make_prac(npi=bad)
        errors, _ = validate_practitioner(2, prac)
        npi_errs = [e for e in errors if e.field == "NPI"]
        assert npi_errs, "Expected NPI error"
        assert npi_errs[0].value == bad


# ---------------------------------------------------------------------------
# Rule 6: DOB format
# ---------------------------------------------------------------------------

class TestDOBValidation:
    def test_invalid_dob_format_fails(self):
        # Two-digit year is not an accepted format.
        errors, _ = validate_practitioner(2, make_prac(dob="03-15-80"))
        assert any(e.field == "DOB" for e in errors)

    def test_dob_mm_dd_yyyy_accepted(self):
        errors, _ = validate_practitioner(2, make_prac(dob="03-15-1980"))
        assert not any(e.field == "DOB" for e in errors)

    def test_dob_slash_mm_dd_yyyy_accepted(self):
        errors, _ = validate_practitioner(2, make_prac(dob="1/8/1973"))
        assert not any(e.field == "DOB" for e in errors)

    def test_invalid_dob_date_fails(self):
        errors, _ = validate_practitioner(2, make_prac(dob="1980-13-01"))
        assert any(e.field == "DOB" for e in errors)

    def test_valid_dob_passes(self):
        errors, _ = validate_practitioner(2, make_prac(dob="1980-03-15"))
        assert not any(e.field == "DOB" for e in errors)

    def test_dob_value_is_raw_string(self):
        bad = "not-a-real-date"
        prac = make_prac(dob=bad)
        errors, _ = validate_practitioner(2, prac)
        dob_errs = [e for e in errors if e.field == "DOB"]
        assert dob_errs, "Expected DOB error"
        assert dob_errs[0].value == bad


# ---------------------------------------------------------------------------
# Rule 7: State abbreviation
# ---------------------------------------------------------------------------

class TestStateValidation:
    def test_lowercase_state_fails(self):
        errors, _ = validate_practitioner(2, make_prac(state="ca"))
        assert any(e.field == "State" for e in errors)

    def test_three_letter_state_fails(self):
        errors, _ = validate_practitioner(2, make_prac(state="CAL"))
        assert any(e.field == "State" for e in errors)

    def test_two_uppercase_state_passes(self):
        errors, _ = validate_practitioner(2, make_prac(state="CA"))
        assert not any(e.field == "State" for e in errors)

    def test_ny_passes(self):
        errors, _ = validate_practitioner(2, make_prac(state="NY"))
        assert not any(e.field == "State" for e in errors)

    def test_dc_passes(self):
        """DC matches Canvas's license-state dropdown."""
        errors, _ = validate_practitioner(2, make_prac(state="DC"))
        assert not any(e.field == "State" for e in errors)

    def test_puerto_rico_passes(self):
        errors, _ = validate_practitioner(2, make_prac(state="PR"))
        assert not any(e.field == "State" for e in errors)

    def test_zz_fails(self):
        """ZZ is not a real code."""
        errors, _ = validate_practitioner(2, make_prac(state="ZZ"))
        assert any(e.field == "State" for e in errors)

    def test_empty_state_ignored(self):
        errors, _ = validate_practitioner(2, make_prac(state=""))
        assert not any(e.field == "State" for e in errors)

    def test_state_error_message_format(self):
        errors, _ = validate_practitioner(2, make_prac(state="ZZ"))
        state_err = next(e for e in errors if e.field == "State")
        assert "valid 2-letter US state code" in state_err.message

    def test_state_value_is_raw_string(self):
        bad = "ca"
        prac = make_prac(state=bad)
        errors, _ = validate_practitioner(2, prac)
        state_errs = [e for e in errors if e.field == "State"]
        assert state_errs, "Expected State error"
        assert state_errs[0].value == bad


# ---------------------------------------------------------------------------
# Rule 8: Zip 5 digits or ZIP+4 (12345 or 12345-6789)
# ---------------------------------------------------------------------------

class TestZipValidation:
    def test_zip_4_digits_fails(self):
        errors, _ = validate_practitioner(2, make_prac(zip="9021"))
        assert any(e.field == "Zip" for e in errors)

    def test_zip_5_digits_passes(self):
        errors, _ = validate_practitioner(2, make_prac(zip="90210"))
        assert not any(e.field == "Zip" for e in errors)

    def test_zip_plus_4_passes(self):
        errors, _ = validate_practitioner(2, make_prac(zip="90210-1234"))
        assert not any(e.field == "Zip" for e in errors)

    @pytest.mark.parametrize("bad", [
        "902100",       # 6 digits
        "90210-12",     # +4 suffix too short
        "90210-12345",  # +4 suffix too long
        "ABCDE",        # letters
        "90210 1234",   # space instead of dash
    ])
    def test_invalid_zip_format_fails(self, bad):
        errors, _ = validate_practitioner(2, make_prac(zip=bad))
        zip_errs = [e for e in errors if e.field == "Zip"]
        assert zip_errs, f"Expected Zip error for {bad!r}"
        assert zip_errs[0].value == bad


# ---------------------------------------------------------------------------
# Rule 9: License Type enum
# ---------------------------------------------------------------------------

class TestLicenseTypeValidation:
    def test_invalid_license_type_fails(self):
        prac = make_prac(licenses=[make_license(type="INVALID")])
        errors, _ = validate_practitioner(2, prac)
        assert any(e.field == "License Type" for e in errors)

    def test_foo_fails(self):
        prac = make_prac(licenses=[make_license(type="FOO")])
        errors, _ = validate_practitioner(2, prac)
        assert any(e.field == "License Type" for e in errors)

    @pytest.mark.parametrize("lic_type", [
        "CLIA", "DEA", "PTAN", "State license", "Taxonomy", "SPI", "Other",
    ])
    def test_canonical_license_types_pass(self, lic_type):
        prac = make_prac(licenses=[make_license(type=lic_type)])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "License Type" for e in errors)

    def test_spi_passes(self):
        prac = make_prac(licenses=[make_license(type="SPI")])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "License Type" for e in errors)

    def test_state_license_lowercase_passes(self):
        """Case-insensitive: 'state license' matches canonical 'State license'."""
        prac = make_prac(licenses=[make_license(type="state license")])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "License Type" for e in errors)

    def test_state_license_mixed_case_passes(self):
        """Case-insensitive: 'State License' matches canonical 'State license'."""
        prac = make_prac(licenses=[make_license(type="State License")])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "License Type" for e in errors)

    def test_other_uppercase_passes(self):
        """Case-insensitive: 'OTHER' matches canonical 'Other'."""
        prac = make_prac(licenses=[make_license(type="OTHER", name="Custom Board")])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "License Type" for e in errors)

    def test_other_lowercase_passes(self):
        """Case-insensitive: 'other' matches canonical 'Other'."""
        prac = make_prac(licenses=[make_license(type="other", name="Custom Board")])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "License Type" for e in errors)

    def test_license_type_value_is_raw_string(self):
        bad = "INVALID"
        prac = make_prac(licenses=[make_license(type=bad)])
        errors, _ = validate_practitioner(2, prac)
        lt_errs = [e for e in errors if e.field == "License Type"]
        assert lt_errs, "Expected License Type error"
        assert lt_errs[0].value == bad


# ---------------------------------------------------------------------------
# Rule 10: License State
# ---------------------------------------------------------------------------

class TestLicenseStateValidation:
    def test_lowercase_license_state_fails(self):
        prac = make_prac(licenses=[make_license(license_state="ny")])
        errors, _ = validate_practitioner(2, prac)
        assert any(e.field == "License State" for e in errors)

    def test_ca_passes(self):
        prac = make_prac(licenses=[make_license(license_state="CA")])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "License State" and "valid 2-letter" in e.message for e in errors)

    def test_valid_license_state_passes(self):
        prac = make_prac(licenses=[make_license(license_state="NY")])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "License State" and "valid 2-letter" in e.message for e in errors)

    def test_dc_license_state_passes(self):
        prac = make_prac(licenses=[make_license(license_state="DC")])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "License State" and "valid 2-letter" in e.message for e in errors)

    def test_territory_license_state_passes(self):
        prac = make_prac(licenses=[make_license(license_state="PR")])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "License State" and "valid 2-letter" in e.message for e in errors)

    def test_zz_license_state_fails(self):
        """ZZ is not a real code."""
        prac = make_prac(licenses=[make_license(license_state="ZZ")])
        errors, _ = validate_practitioner(2, prac)
        assert any(e.field == "License State" and "valid 2-letter" in e.message for e in errors)

    def test_license_state_error_message_format(self):
        prac = make_prac(licenses=[make_license(license_state="ZZ")])
        errors, _ = validate_practitioner(2, prac)
        ls_err = next(e for e in errors if e.field == "License State" and "valid 2-letter" in e.message)
        assert "License 1" in ls_err.message
        assert "valid 2-letter US state code" in ls_err.message

    def test_license_state_value_is_raw_string(self):
        bad = "ny"
        prac = make_prac(licenses=[make_license(license_state=bad)])
        errors, _ = validate_practitioner(2, prac)
        ls_errs = [e for e in errors if e.field == "License State" and "valid 2-letter" in e.message]
        assert ls_errs, "Expected License State format error"
        assert ls_errs[0].value == bad


# ---------------------------------------------------------------------------
# Rule 11: License date format
# ---------------------------------------------------------------------------

class TestLicenseDateValidation:
    def test_invalid_issue_date_fails(self):
        prac = make_prac(licenses=[make_license(issue_date="not-a-date")])
        errors, _ = validate_practitioner(2, prac)
        assert any(e.field == "License Issue Date" for e in errors)

    def test_license_date_slash_format_accepted(self):
        """Real-world CSV format: 1/1/2023 should pass."""
        prac = make_prac(licenses=[make_license(
            issue_date="1/1/2023", expiration_date="12/31/2025"
        )])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field in ("License Issue Date", "License Expiration Date")
                       for e in errors)

    def test_invalid_expiration_date_fails(self):
        prac = make_prac(licenses=[make_license(expiration_date="2026-13-01")])
        errors, _ = validate_practitioner(2, prac)
        assert any(e.field == "License Expiration Date" for e in errors)

    def test_valid_dates_pass(self):
        prac = make_prac(licenses=[make_license(issue_date="2020-01-01", expiration_date="2026-01-01")])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field in ("License Issue Date", "License Expiration Date") for e in errors)


# ---------------------------------------------------------------------------
# Rule 12: Primary accepts TRUE/FALSE/YES/NO (blank = FALSE)
# ---------------------------------------------------------------------------

class TestLicensePrimaryValidation:
    def test_invalid_primary_value_fails(self):
        prac = make_prac(licenses=[make_license(primary_raw="MAYBE")])
        errors, _ = validate_practitioner(2, prac)
        assert any(e.field == "Primary" for e in errors)

    @pytest.mark.parametrize("val", [
        "TRUE", "FALSE", "true", "false", "True", "False",
        "YES", "NO", "yes", "no", "Yes", "No",
    ])
    def test_valid_primary_values_pass(self, val):
        prac = make_prac(licenses=[make_license(primary_raw=val)])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "Primary" for e in errors)

    def test_blank_primary_passes_as_false(self):
        prac = make_prac(licenses=[make_license(primary_raw="", is_primary=False)])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "Primary" for e in errors)

    def test_license_primary_value_is_raw_string(self):
        """value must be the original string (before .upper()) that failed."""
        bad = "Maybe"
        prac = make_prac(licenses=[make_license(primary_raw=bad)])
        errors, _ = validate_practitioner(2, prac)
        lp_errs = [e for e in errors if e.field == "Primary"]
        assert lp_errs, "Expected Primary error"
        assert lp_errs[0].value == bad

    def test_error_message_lists_accepted_values(self):
        prac = make_prac(licenses=[make_license(primary_raw="MAYBE")])
        errors, _ = validate_practitioner(2, prac)
        lp_errs = [e for e in errors if e.field == "Primary"]
        assert lp_errs
        msg = lp_errs[0].message
        # All four accepted values must appear so users know what to type.
        assert "TRUE" in msg and "FALSE" in msg and "YES" in msg and "NO" in msg


# ---------------------------------------------------------------------------
# Rule 13: Exactly one primary license
# ---------------------------------------------------------------------------

class TestPrimaryLicenseCount:
    def test_no_primary_license_warns(self):
        lic = make_license(primary_raw="FALSE", is_primary=False)
        _, warnings = validate_practitioner(2, make_prac(licenses=[lic]))
        assert any("primary" in w.message.lower() for w in warnings)

    def test_two_primary_licenses_warns(self):
        lic1 = make_license(primary_raw="TRUE", is_primary=True)
        lic2 = make_license(type="DEA", number="DEA999", primary_raw="TRUE", is_primary=True)
        _, warnings = validate_practitioner(2, make_prac(licenses=[lic1, lic2]))
        assert any("2 licenses" in w.message for w in warnings)

    def test_no_licenses_no_primary_warning(self):
        # Rule 13 only fires if there are licenses
        _, warnings = validate_practitioner(2, make_prac(licenses=[]))
        assert not any("primary" in w.message.lower() for w in warnings)


# ---------------------------------------------------------------------------
# Rule 14: Continuation row field conflict
# ---------------------------------------------------------------------------

class TestContinuationRowValidation:
    def test_matching_rows_produce_no_warnings(self):
        first = {"first_name": "Jane", "last_name": "Smith", "phone": "5555550100", "role": "MD",
                 "fax": "", "npi": "", "dob": "1980-03-15", "address_line1": "",
                 "address_line2": "", "city": "", "state": "", "zip": "",
                 "primary_practice_location": "Main Clinic"}
        cont = {"first_name": "Jane", "last_name": "Smith", "phone": "5555550100", "role": "MD",
                "fax": "", "npi": "", "dob": "1980-03-15", "address_line1": "",
                "address_line2": "", "city": "", "state": "", "zip": "",
                "primary_practice_location": "Main Clinic"}
        warnings = validate_continuation_row(3, first, cont)
        assert warnings == []

    def test_differing_phone_produces_warning(self):
        first = {"first_name": "Jane", "phone": "1111111111", "last_name": "",
                 "role": "", "fax": "", "npi": "", "dob": "", "address_line1": "",
                 "address_line2": "", "city": "", "state": "", "zip": "",
                 "primary_practice_location": ""}
        cont = {"first_name": "Jane", "phone": "9999999999", "last_name": "",
                "role": "", "fax": "", "npi": "", "dob": "", "address_line1": "",
                "address_line2": "", "city": "", "state": "", "zip": "",
                "primary_practice_location": ""}
        warnings = validate_continuation_row(3, first, cont)
        assert len(warnings) == 1
        assert "Phone" in warnings[0].message

    def test_empty_continuation_field_not_warned(self):
        # If continuation row leaves a field blank, it's not a conflict
        first = {"first_name": "Jane", "phone": "1111111111", "last_name": "",
                 "role": "", "fax": "", "npi": "", "dob": "", "address_line1": "",
                 "address_line2": "", "city": "", "state": "", "zip": "",
                 "primary_practice_location": ""}
        cont = {"first_name": "", "phone": "", "last_name": "", "role": "", "fax": "",
                "npi": "", "dob": "", "address_line1": "", "address_line2": "",
                "city": "", "state": "", "zip": "", "primary_practice_location": ""}
        warnings = validate_continuation_row(3, first, cont)
        assert warnings == []


# ---------------------------------------------------------------------------
# to_dict methods
# ---------------------------------------------------------------------------

class TestToDictMethods:
    def test_validation_error_to_dict(self):
        e = ValidationError(5, "Email", "bad@", "Bad email")
        d = e.to_dict()
        assert d == {"row": 5, "field": "Email", "value": "bad@", "message": "Bad email"}

    def test_validation_error_to_dict_empty_value(self):
        """Required-field errors have value='' (empty string)."""
        e = ValidationError(3, "First Name", "", "First Name is required.")
        d = e.to_dict()
        assert d["value"] == ""

    def test_validation_warning_to_dict(self):
        w = ValidationWarning(3, "No primary license")
        d = w.to_dict()
        assert d == {"row": 3, "message": "No primary license"}

    def test_validation_warning_has_no_value_key(self):
        """Warnings intentionally omit the value key."""
        w = ValidationWarning(3, "Some warning")
        d = w.to_dict()
        assert "value" not in d


# ---------------------------------------------------------------------------
# Rule 15: (removed) — role codes are no longer pre-flight validated.
# Canvas authoritatively rejects unknown role codes at POST /Practitioner with
# a 422 OperationOutcome, which the API handler surfaces in the results table.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Rule 16: License Name required when License Type is OTHER
# ---------------------------------------------------------------------------

class TestLicenseNameConditional:
    def test_other_canonical_empty_name_fails(self):
        """Type='Other' (canonical) with no License Name → hard error."""
        prac = make_prac(licenses=[make_license(type="Other", name="")])
        errors, _ = validate_practitioner(2, prac)
        assert any(e.field == "License Name" and "Other" in e.message for e in errors)

    def test_other_lowercase_empty_name_fails(self):
        """Type='other' (lowercase) → case-insensitive match fires Rule 16."""
        prac = make_prac(licenses=[make_license(type="other", name="")])
        errors, _ = validate_practitioner(2, prac)
        assert any(e.field == "License Name" for e in errors)

    def test_other_uppercase_empty_name_fails(self):
        """Type='OTHER' (legacy uppercase) → case-insensitive match fires Rule 16."""
        prac = make_prac(licenses=[make_license(type="OTHER", name="")])
        errors, _ = validate_practitioner(2, prac)
        assert any(e.field == "License Name" for e in errors)

    def test_other_type_with_name_passes(self):
        """Type='Other' with a name → no error."""
        prac = make_prac(licenses=[make_license(type="Other", name="Custom Board")])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "License Name" for e in errors)

    def test_dea_type_empty_name_ok(self):
        """Type=DEA with empty name → no License Name error."""
        prac = make_prac(licenses=[make_license(type="DEA", name="", license_state="")])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "License Name" for e in errors)

    @pytest.mark.parametrize("lic_type", ["State license", "PTAN", "CLIA", "Taxonomy"])
    def test_non_other_empty_name_ok(self, lic_type):
        """Non-Other types with empty name → no License Name error (Rule 16 does not apply)."""
        prac = make_prac(licenses=[make_license(type=lic_type, name="")])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "License Name" for e in errors)

    def test_error_message_format(self):
        """Error message includes the 1-based license index and canonical casing."""
        prac = make_prac(licenses=[make_license(type="Other", name="")])
        errors, _ = validate_practitioner(2, prac)
        name_error = next(e for e in errors if e.field == "License Name")
        assert "License 1" in name_error.message
        assert "License Name is required when License Type is Other" in name_error.message

    def test_license_name_empty_value_is_empty_string(self):
        """value for a required-but-empty License Name error is the empty string."""
        prac = make_prac(licenses=[make_license(type="Other", name="")])
        errors, _ = validate_practitioner(2, prac)
        name_errs = [e for e in errors if e.field == "License Name"]
        assert name_errs, "Expected License Name error"
        assert name_errs[0].value == ""


# ---------------------------------------------------------------------------
# Rule 17: License State required when License Type is STATE or PTAN
# ---------------------------------------------------------------------------

class TestLicenseStateConditional:
    def test_state_license_canonical_empty_state_fails(self):
        """Type='State license' with empty License State → hard error."""
        prac = make_prac(licenses=[make_license(type="State license", license_state="")])
        errors, _ = validate_practitioner(2, prac)
        assert any(e.field == "License State" and "required" in e.message for e in errors)

    def test_state_license_lowercase_empty_state_fails(self):
        """Type='state license' (lowercase) → case-insensitive match fires Rule 17."""
        prac = make_prac(licenses=[make_license(type="state license", license_state="")])
        errors, _ = validate_practitioner(2, prac)
        assert any(e.field == "License State" and "required" in e.message for e in errors)

    def test_state_license_mixed_case_empty_state_fails(self):
        """Type='State License' (mixed case) → case-insensitive match fires Rule 17."""
        prac = make_prac(licenses=[make_license(type="State License", license_state="")])
        errors, _ = validate_practitioner(2, prac)
        assert any(e.field == "License State" and "required" in e.message for e in errors)

    def test_ptan_type_empty_state_fails(self):
        """Type=PTAN with empty License State → hard error."""
        prac = make_prac(licenses=[make_license(type="PTAN", license_state="")])
        errors, _ = validate_practitioner(2, prac)
        assert any(e.field == "License State" and "PTAN" in e.message for e in errors)

    def test_state_license_valid_state_passes(self):
        """Type='State license' + valid 2-letter state → no conditional error."""
        prac = make_prac(licenses=[make_license(type="State license", license_state="CA")])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "License State" and "required" in e.message for e in errors)

    def test_state_license_invalid_format_still_fails(self):
        """Type='State license' + lowercase state → Rule 10 format error fires."""
        prac = make_prac(licenses=[make_license(type="State license", license_state="california")])
        errors, _ = validate_practitioner(2, prac)
        assert any(e.field == "License State" for e in errors)

    def test_dea_type_empty_state_ok(self):
        """Type=DEA with empty License State → no error (not required)."""
        prac = make_prac(licenses=[make_license(type="DEA", license_state="")])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "License State" and "required" in e.message for e in errors)

    @pytest.mark.parametrize("lic_type", ["CLIA", "Taxonomy", "Other"])
    def test_non_state_ptan_types_empty_state_ok(self, lic_type):
        """CLIA/Taxonomy/Other with empty License State → no conditional error."""
        prac = make_prac(licenses=[make_license(type=lic_type, license_state="",
                                                name="Some Name" if lic_type == "Other" else "")])
        errors, _ = validate_practitioner(2, prac)
        assert not any(e.field == "License State" and "required" in e.message for e in errors)

    def test_error_message_ptan_includes_ptan(self):
        """Error message includes 1-based license index and 'PTAN'."""
        prac = make_prac(licenses=[make_license(type="PTAN", license_state="")])
        errors, _ = validate_practitioner(2, prac)
        state_error = next(e for e in errors if e.field == "License State" and "required" in e.message)
        assert "License 1" in state_error.message
        assert "PTAN" in state_error.message

    def test_error_message_state_license_uses_canonical_casing(self):
        """Error message uses the canonical (all-caps) form regardless of
        what casing/alias the user typed in the CSV."""
        prac = make_prac(licenses=[make_license(type="state license", license_state="")])
        errors, _ = validate_practitioner(2, prac)
        state_error = next(e for e in errors if e.field == "License State" and "required" in e.message)
        assert "STATE" in state_error.message

    def test_license_state_empty_value_is_empty_string(self):
        """value for a required-but-empty License State error is the empty string."""
        prac = make_prac(licenses=[make_license(type="State license", license_state="")])
        errors, _ = validate_practitioner(2, prac)
        req_errs = [e for e in errors if e.field == "License State" and "required" in e.message]
        assert req_errs, "Expected License State required error"
        assert req_errs[0].value == ""

    def test_state_canonical_form_empty_state_fails(self):
        """Type=STATE (the canonical form the CSV template recommends)
        with empty License State → hard error.

        Regression: a prior implementation matched only the alias
        ``"state license"`` after .lower(), which missed canonical
        ``"STATE"`` inputs entirely — every row using the template's
        recommended value silently skipped Rule 17 and downstream Canvas
        validation either failed cryptically or stored a stateless
        license. Fixing this requires canonicalising before the check."""
        prac = make_prac(licenses=[make_license(type="STATE", license_state="")])
        errors, _ = validate_practitioner(2, prac)
        assert any(
            e.field == "License State" and "required" in e.message and "STATE" in e.message
            for e in errors
        )

    def test_state_lowercase_canonical_form_empty_state_fails(self):
        """Type=state → canonicalises to STATE → Rule 17 fires."""
        prac = make_prac(licenses=[make_license(type="state", license_state="")])
        errors, _ = validate_practitioner(2, prac)
        assert any(
            e.field == "License State" and "required" in e.message
            for e in errors
        )

    def test_ptan_lowercase_canonical_form_empty_state_fails(self):
        """Type=ptan (lowercase canonical) → canonicalises to PTAN → Rule 17 fires."""
        prac = make_prac(licenses=[make_license(type="ptan", license_state="")])
        errors, _ = validate_practitioner(2, prac)
        assert any(
            e.field == "License State" and "PTAN" in e.message
            for e in errors
        )


# ---------------------------------------------------------------------------
# canonicalize_license_type
# ---------------------------------------------------------------------------

class TestCanonicalizeLicenseType:
    """Canonical license types are the all-caps codes Canvas's API actually
    accepts on `qualification.code.text`. We accept user-friendly aliases
    ('State license', 'state license') and normalise to all-caps."""

    def test_state_license_alias_normalises_to_all_caps(self):
        assert canonicalize_license_type("State license") == "STATE"

    def test_lowercase_state_license_alias(self):
        assert canonicalize_license_type("state license") == "STATE"

    def test_canonical_state_passes_through(self):
        assert canonicalize_license_type("STATE") == "STATE"

    def test_other_lowercase(self):
        assert canonicalize_license_type("other") == "OTHER"

    def test_other_mixed(self):
        assert canonicalize_license_type("Other") == "OTHER"

    def test_taxonomy_mixed(self):
        assert canonicalize_license_type("Taxonomy") == "TAXONOMY"

    def test_spi_passes_through(self):
        assert canonicalize_license_type("SPI") == "SPI"

    def test_dea_passes_through(self):
        assert canonicalize_license_type("DEA") == "DEA"

    def test_dea(self):
        assert canonicalize_license_type("DEA") == "DEA"

    def test_unknown_returns_raw(self):
        """Unknown values fall back to the raw input (validation already rejected them)."""
        assert canonicalize_license_type("BOGUS") == "BOGUS"

    def test_empty_returns_empty(self):
        assert canonicalize_license_type("") == ""
