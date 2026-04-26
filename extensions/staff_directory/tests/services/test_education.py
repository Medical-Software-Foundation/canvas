from unittest.mock import MagicMock, patch

from staff_directory.services import education as edu


class TestHelpers:
    def test_s_none_returns_default(self):
        assert edu._s(None) == ""

    def test_s_none_with_default(self):
        assert edu._s(None, default="x") == "x"

    def test_s_strips(self):
        assert edu._s("  hi  ") == "hi"

    def test_s_stringifies_numbers(self):
        assert edu._s(42) == "42"

    def test_int_none(self):
        assert edu._int(None) == 0

    def test_int_empty_string(self):
        assert edu._int("") == 0

    def test_int_valid(self):
        assert edu._int("2025") == 2025

    def test_int_invalid(self):
        assert edu._int("nope") == 0


class TestSerialize:
    def test_serialize_fields(self):
        entry = MagicMock()
        entry.dbid = 7
        entry.institution = "Harvard Medical School"
        entry.degree = "MD"
        entry.field_of_study = ""
        entry.graduation_year = 2012
        entry.notes = "Honors"

        assert edu.serialize(entry) == {
            "id": 7,
            "institution": "Harvard Medical School",
            "degree": "MD",
            "field_of_study": "",
            "graduation_year": 2012,
            "notes": "Honors",
        }

    def test_serialize_zero_year_renders_none(self):
        entry = MagicMock()
        entry.dbid = 1
        entry.institution = "X"
        entry.degree = "Y"
        entry.field_of_study = ""
        entry.graduation_year = 0
        entry.notes = ""
        assert edu.serialize(entry)["graduation_year"] is None


class TestCreateUpdateDelete:
    def test_create_uses_cleaned_fields(self):
        with patch("staff_directory.services.education.CustomStaff") as mock_staff_cls:
            with patch("staff_directory.services.education.Education") as mock_edu_cls:
                mock_staff_cls.objects.get.return_value = "STAFF"
                mock_edu_cls.objects.create.return_value = "ENTRY"

                result = edu.create(101, {
                    "institution": "  Harvard  ",
                    "degree": " MD ",
                    "field_of_study": "",
                    "graduation_year": "2015",
                    "notes": None,
                })

                assert result == "ENTRY"
                mock_edu_cls.objects.create.assert_called_with(
                    staff="STAFF",
                    institution="Harvard",
                    degree="MD",
                    field_of_study="",
                    graduation_year=2015,
                    notes="",
                )

    def test_update_missing_returns_none(self):
        with patch("staff_directory.services.education.Education") as mock_edu_cls:
            mock_edu_cls.objects.filter.return_value.first.return_value = None
            assert edu.update(999, {"institution": "X"}) is None

    def test_update_applies_partial(self):
        entry = MagicMock()
        entry.institution = "old"
        entry.degree = "old"
        entry.field_of_study = "old"
        entry.graduation_year = 1999
        entry.notes = "old"

        with patch("staff_directory.services.education.Education") as mock_edu_cls:
            mock_edu_cls.objects.filter.return_value.first.return_value = entry
            edu.update(1, {"institution": "  New Inst  ", "graduation_year": "2030"})

        assert entry.institution == "New Inst"
        assert entry.graduation_year == 2030
        assert entry.degree == "old"  # Untouched
        entry.save.assert_called_once()

    def test_delete_missing(self):
        with patch("staff_directory.services.education.Education") as mock_edu_cls:
            mock_edu_cls.objects.filter.return_value.first.return_value = None
            assert edu.delete(999) is False

    def test_delete_found(self):
        entry = MagicMock()
        with patch("staff_directory.services.education.Education") as mock_edu_cls:
            mock_edu_cls.objects.filter.return_value.first.return_value = entry
            assert edu.delete(1) is True
            entry.delete.assert_called_once()
