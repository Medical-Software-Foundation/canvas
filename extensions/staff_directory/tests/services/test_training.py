from unittest.mock import MagicMock, patch

from staff_directory.services import training as tr


class TestProgramTypeCoercion:
    def test_residency_allowed(self):
        assert tr._program_type("residency") == "residency"

    def test_uppercase_coerces(self):
        assert tr._program_type("FELLOWSHIP") == "fellowship"

    def test_unknown_becomes_other(self):
        assert tr._program_type("mystery-rotation") == "other"

    def test_none_becomes_other(self):
        assert tr._program_type(None) == "other"


class TestSerialize:
    def test_serialize_fields(self):
        entry = MagicMock()
        entry.dbid = 5
        entry.institution = "Mass General"
        entry.program_type = "residency"
        entry.specialty_area = "Internal Medicine"
        entry.start_year = 2018
        entry.end_year = 2021
        entry.notes = "Chief"

        assert tr.serialize(entry) == {
            "id": 5,
            "institution": "Mass General",
            "program_type": "residency",
            "specialty_area": "Internal Medicine",
            "start_year": 2018,
            "end_year": 2021,
            "notes": "Chief",
        }

    def test_zero_years_render_none(self):
        entry = MagicMock()
        entry.dbid = 1
        entry.institution = "X"
        entry.program_type = "residency"
        entry.specialty_area = ""
        entry.start_year = 0
        entry.end_year = 0
        entry.notes = ""
        data = tr.serialize(entry)
        assert data["start_year"] is None
        assert data["end_year"] is None


class TestCreateUpdate:
    def test_create_normalizes_program_type(self):
        with patch("staff_directory.services.training.CustomStaff") as mock_staff_cls:
            with patch("staff_directory.services.training.ClinicalTraining") as mock_cls:
                mock_staff_cls.objects.get.return_value = "STAFF"
                mock_cls.objects.create.return_value = "ENTRY"

                tr.create(1, {
                    "institution": "MGH",
                    "program_type": "WEIRD",
                    "specialty_area": "Peds",
                    "start_year": "2019",
                    "end_year": "2022",
                    "notes": "",
                })

                kwargs = mock_cls.objects.create.call_args.kwargs
                assert kwargs["program_type"] == "other"
                assert kwargs["start_year"] == 2019

    def test_update_ignored_when_missing(self):
        with patch("staff_directory.services.training.ClinicalTraining") as mock_cls:
            mock_cls.objects.filter.return_value.first.return_value = None
            assert tr.update(5, {"institution": "X"}) is None

    def test_update_applies_partial(self):
        entry = MagicMock()
        entry.institution = "old"
        entry.program_type = "residency"
        entry.specialty_area = ""
        entry.start_year = 2000
        entry.end_year = 2003
        entry.notes = ""

        with patch("staff_directory.services.training.ClinicalTraining") as mock_cls:
            mock_cls.objects.filter.return_value.first.return_value = entry
            tr.update(5, {"institution": "New", "end_year": "2005"})

        assert entry.institution == "New"
        assert entry.end_year == 2005
        entry.save.assert_called_once()

    def test_delete_missing(self):
        with patch("staff_directory.services.training.ClinicalTraining") as mock_cls:
            mock_cls.objects.filter.return_value.first.return_value = None
            assert tr.delete(5) is False

    def test_delete_found(self):
        entry = MagicMock()
        with patch("staff_directory.services.training.ClinicalTraining") as mock_cls:
            mock_cls.objects.filter.return_value.first.return_value = entry
            assert tr.delete(5) is True
            entry.delete.assert_called_once()
