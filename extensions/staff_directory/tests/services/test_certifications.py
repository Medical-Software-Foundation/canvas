from datetime import date
from unittest.mock import MagicMock, patch

from staff_directory.services import certifications as cert


class TestDateParser:
    def test_none(self):
        assert cert._date(None) is None

    def test_empty_string(self):
        assert cert._date("") is None

    def test_date_object_passthrough(self):
        d = date(2025, 5, 1)
        assert cert._date(d) == d

    def test_valid_iso_string(self):
        assert cert._date("2025-12-31") == date(2025, 12, 31)

    def test_invalid_string(self):
        assert cert._date("nope") is None


class TestStatus:
    today = date(2025, 6, 15)

    def test_none_expiration_is_unknown(self):
        entry = MagicMock()
        entry.expiration_date = None
        assert cert.status(entry, today=self.today) == "unknown"

    def test_past_date_is_expired(self):
        entry = MagicMock()
        entry.expiration_date = date(2025, 1, 1)
        assert cert.status(entry, today=self.today) == "expired"

    def test_within_warning_window_is_expiring_soon(self):
        entry = MagicMock()
        entry.expiration_date = date(2025, 8, 1)
        assert cert.status(entry, today=self.today) == "expiring_soon"

    def test_far_future_is_current(self):
        entry = MagicMock()
        entry.expiration_date = date(2028, 1, 1)
        assert cert.status(entry, today=self.today) == "current"


class TestSerialize:
    def test_serialize_with_dates(self):
        entry = MagicMock()
        entry.dbid = 3
        entry.board_name = "ABIM"
        entry.specialty = "Internal Medicine"
        entry.certification_number = "ABC123"
        entry.issued_date = date(2020, 1, 1)
        entry.expiration_date = date(2030, 1, 1)
        entry.notes = ""

        out = cert.serialize(entry, today=date(2025, 6, 15))
        assert out["board_name"] == "ABIM"
        assert out["issued_date"] == "2020-01-01"
        assert out["expiration_date"] == "2030-01-01"
        assert out["status"] == "current"
        assert out["days_until_expiration"] > 0

    def test_serialize_without_dates(self):
        entry = MagicMock()
        entry.dbid = 1
        entry.board_name = "X"
        entry.specialty = "Y"
        entry.certification_number = ""
        entry.issued_date = None
        entry.expiration_date = None
        entry.notes = ""
        out = cert.serialize(entry, today=date(2025, 6, 15))
        assert out["issued_date"] is None
        assert out["expiration_date"] is None
        assert out["status"] == "unknown"
        assert out["days_until_expiration"] is None


class TestExpiringWithin:
    def test_filters_by_cutoff(self):
        with patch("staff_directory.services.certifications.BoardCertification") as mock_cls:
            qs = mock_cls.objects.filter.return_value
            qs.order_by.return_value = ["row1"]
            result = cert.expiring_within(30, today=date(2025, 6, 15))
            assert result == ["row1"]


class TestCrud:
    def test_create_with_string_dates(self):
        with patch("staff_directory.services.certifications.CustomStaff") as mock_staff_cls:
            with patch("staff_directory.services.certifications.BoardCertification") as mock_cls:
                mock_staff_cls.objects.get.return_value = "STAFF"
                mock_cls.objects.create.return_value = "ENTRY"

                result = cert.create(7, {
                    "board_name": "ABIM",
                    "specialty": "Internal Medicine",
                    "certification_number": "X1",
                    "issued_date": "2020-01-01",
                    "expiration_date": "2030-01-01",
                    "notes": "",
                })

                kwargs = mock_cls.objects.create.call_args.kwargs
                assert result == "ENTRY"
                assert kwargs["issued_date"] == date(2020, 1, 1)
                assert kwargs["expiration_date"] == date(2030, 1, 1)

    def test_update_missing(self):
        with patch("staff_directory.services.certifications.BoardCertification") as mock_cls:
            mock_cls.objects.filter.return_value.first.return_value = None
            assert cert.update(5, {"specialty": "x"}) is None

    def test_update_applies(self):
        entry = MagicMock()
        entry.board_name = "old"
        entry.specialty = "old"
        entry.certification_number = ""
        entry.issued_date = None
        entry.expiration_date = None
        entry.notes = ""

        with patch("staff_directory.services.certifications.BoardCertification") as mock_cls:
            mock_cls.objects.filter.return_value.first.return_value = entry
            cert.update(1, {"specialty": "New", "expiration_date": "2030-05-01"})

        assert entry.specialty == "New"
        assert entry.expiration_date == date(2030, 5, 1)

    def test_delete(self):
        entry = MagicMock()
        with patch("staff_directory.services.certifications.BoardCertification") as mock_cls:
            mock_cls.objects.filter.return_value.first.return_value = entry
            assert cert.delete(1) is True
            entry.delete.assert_called_once()
