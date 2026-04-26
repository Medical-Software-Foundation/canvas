from datetime import date
from unittest.mock import MagicMock, patch

from staff_directory.services import profiles


class TestFullName:
    def test_both_names(self):
        staff = MagicMock()
        staff.first_name = "Alice"
        staff.last_name = "Chen"
        staff.credentialed_name = ""
        assert profiles._full_name(staff) == "Alice Chen"

    def test_only_last(self):
        staff = MagicMock()
        staff.first_name = ""
        staff.last_name = "Chen"
        staff.credentialed_name = ""
        assert profiles._full_name(staff) == "Chen"

    def test_falls_back_to_credentialed_name(self):
        staff = MagicMock()
        staff.first_name = ""
        staff.last_name = ""
        staff.credentialed_name = "Dr. A. Chen, MD"
        assert profiles._full_name(staff) == "Dr. A. Chen, MD"


class TestRoleName:
    def test_display(self):
        staff = MagicMock()
        staff.top_clinical_role.display = "Physician"
        staff.top_clinical_role.internal_code = "MD"
        assert profiles._role_name(staff) == "Physician"

    def test_falls_back_to_internal_code(self):
        staff = MagicMock()
        staff.top_clinical_role.display = None
        staff.top_clinical_role.internal_code = "RN"
        assert profiles._role_name(staff) == "RN"

    def test_no_top_role(self):
        staff = MagicMock()
        staff.top_clinical_role = None
        assert profiles._role_name(staff) == ""


class TestGetStaffByUserHeader:
    def test_empty_returns_none(self):
        with patch("staff_directory.services.profiles.Staff") as mock_staff:
            assert profiles.get_staff_by_user_header("") is None
            assert mock_staff.mock_calls == []

    def test_tries_with_and_without_dashes(self):
        with patch("staff_directory.services.profiles.Staff") as mock_staff:
            mock_staff.objects.filter.return_value.first.return_value = "FOUND"
            result = profiles.get_staff_by_user_header("abc-123")
            assert result == "FOUND"
            # The filter was called with a set of candidates that include both forms
            ids_arg = mock_staff.objects.filter.call_args.kwargs["id__in"]
            assert "abc-123" in ids_arg
            assert "abc123" in ids_arg


class TestSummarize:
    def test_basic_summary(self):
        staff = MagicMock()
        staff.id = "uuid-1"
        staff.dbid = 7
        staff.first_name = "Alice"
        staff.last_name = "Chen"
        staff.credentialed_name = ""
        staff.top_clinical_role.display = "MD"
        staff.top_clinical_role.internal_code = "MD"

        specialty = MagicMock()
        specialty.is_primary = True
        specialty.nucc_code.code = "207R"
        specialty.nucc_code.display_name = "Internal Medicine"

        data = profiles._summarize(
            staff,
            today=date(2025, 1, 1),
            certifications=[],
            specialties=[specialty],
            education_count=0,
            training_count=0,
        )
        assert data["full_name"] == "Alice Chen"
        assert data["primary_specialty"] == {
            "code": "207R",
            "display_name": "Internal Medicine",
        }
        assert data["specialty_count"] == 1
        assert data["has_expiring_cert"] is False
