from unittest.mock import patch

from staff_directory.data import nucc_seeder


class TestEnsureNuccSeed:
    def setup_method(self):
        nucc_seeder.reset_seed_memo()

    def test_skips_when_already_seeded(self):
        nucc_seeder._seeded_once = True
        with patch("staff_directory.data.nucc_seeder.seed_nucc_codes") as mock_seed:
            result = nucc_seeder.ensure_nucc_seed()
            assert result == (0, 0)
            assert mock_seed.mock_calls == []
        nucc_seeder.reset_seed_memo()

    def test_noops_when_table_populated(self):
        with patch("staff_directory.models.nucc.NuccTaxonomyCode") as mock_model:
            mock_model.objects.exists.return_value = True
            with patch("staff_directory.data.nucc_seeder.seed_nucc_codes") as mock_seed:
                result = nucc_seeder.ensure_nucc_seed()
                assert result == (0, 0)
                assert mock_seed.mock_calls == []

    def test_loads_and_seeds(self, monkeypatch):
        monkeypatch.setattr(
            nucc_seeder,
            "_load_seed_rows",
            lambda: [{"code": "X1", "classification": "C", "specialization": ""}],
        )

        with patch("staff_directory.models.nucc.NuccTaxonomyCode") as mock_model:
            mock_model.objects.exists.return_value = False
            with patch("staff_directory.data.nucc_seeder.seed_nucc_codes") as mock_seed:
                mock_seed.return_value = (1, 0)
                result = nucc_seeder.ensure_nucc_seed()
                assert result == (1, 0)
                mock_seed.assert_called_once_with(
                    [{"code": "X1", "classification": "C", "specialization": ""}]
                )

    def test_empty_seed_rows_still_seeds(self, monkeypatch):
        monkeypatch.setattr(nucc_seeder, "_load_seed_rows", lambda: [])

        with patch("staff_directory.models.nucc.NuccTaxonomyCode") as mock_model:
            mock_model.objects.exists.return_value = False
            with patch("staff_directory.data.nucc_seeder.seed_nucc_codes") as mock_seed:
                mock_seed.return_value = (0, 0)
                result = nucc_seeder.ensure_nucc_seed()
                assert result == (0, 0)


class TestLoadSeedRows:
    def test_returns_bundled_codes(self):
        rows = nucc_seeder._load_seed_rows()
        assert isinstance(rows, list)
        assert len(rows) > 0
        # Every row has a code
        assert all("code" in row for row in rows)

    def test_returns_fresh_list_each_call(self):
        rows1 = nucc_seeder._load_seed_rows()
        rows2 = nucc_seeder._load_seed_rows()
        assert rows1 is not rows2
        assert rows1 == rows2
