from unittest.mock import MagicMock, patch

import pytest

from staff_directory.services import specialties as spec
from staff_directory.services.specialties import SpecialtyError


class TestCreate:
    def test_empty_code_raises(self):
        with pytest.raises(SpecialtyError, match="required"):
            spec.create(1, "")

    def test_unknown_code_raises(self):
        with patch("staff_directory.services.specialties.NuccTaxonomyCode") as mock_nucc:
            mock_nucc.objects.filter.return_value.first.return_value = None
            with pytest.raises(SpecialtyError, match="Unknown NUCC"):
                spec.create(1, "NOPE")

    def test_success_creates_entry(self):
        nucc = MagicMock()
        with patch("staff_directory.services.specialties.NuccTaxonomyCode") as mock_nucc:
            with patch("staff_directory.services.specialties.CustomStaff") as mock_staff:
                with patch("staff_directory.services.specialties.StaffSpecialty") as mock_spec_cls:
                    mock_nucc.objects.filter.return_value.first.return_value = nucc
                    mock_staff.objects.get.return_value = "STAFF"
                    mock_spec_cls.objects.create.return_value = "ENTRY"

                    result = spec.create(1, "207RC0000X", is_primary=False)

                    assert result == "ENTRY"

    def test_primary_true_demotes_others(self):
        nucc = MagicMock()
        with patch("staff_directory.services.specialties.NuccTaxonomyCode") as mock_nucc:
            with patch("staff_directory.services.specialties.CustomStaff") as mock_staff:
                with patch("staff_directory.services.specialties.StaffSpecialty") as mock_spec_cls:
                    mock_nucc.objects.filter.return_value.first.return_value = nucc
                    mock_staff.objects.get.return_value = "STAFF"
                    mock_spec_cls.objects.create.return_value = "ENTRY"

                    spec.create(1, "X", is_primary=True)
                    # The demotion path must have been called
                    filt = mock_spec_cls.objects.filter.return_value
                    assert filt.update.called is True


class TestSetPrimary:
    def test_missing_returns_none(self):
        with patch("staff_directory.services.specialties.StaffSpecialty") as mock_cls:
            mock_cls.objects.filter.return_value.select_related.return_value.first.return_value = None
            assert spec.set_primary(999) is None

    def test_promotes_entry(self):
        entry = MagicMock()
        entry.staff_id = 50
        with patch("staff_directory.services.specialties.StaffSpecialty") as mock_cls:
            mock_cls.objects.filter.return_value.select_related.return_value.first.return_value = entry
            result = spec.set_primary(1)
            assert result is entry
            assert entry.is_primary is True
            entry.save.assert_called_once()


class TestSerialize:
    def test_serialize_includes_flags(self):
        entry = MagicMock()
        entry.dbid = 7
        entry.is_primary = True
        entry.nucc_code.code = "207R00000X"
        entry.nucc_code.grouping = "G"
        entry.nucc_code.classification = "C"
        entry.nucc_code.specialization = ""
        entry.nucc_code.display_name = "C"
        entry.nucc_code.definition = ""

        data = spec.serialize(entry)
        assert data["id"] == 7
        assert data["is_primary"] is True
        assert data["nucc"]["code"] == "207R00000X"
