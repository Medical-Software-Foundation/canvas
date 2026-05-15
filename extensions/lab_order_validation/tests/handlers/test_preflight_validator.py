"""Tests for the LabOrderPreflightValidator handler."""

from unittest.mock import MagicMock, patch

from lab_order_validation.handlers.preflight_validator import (
    LabOrderPreflightValidator,
)


PATIENT_PATH = "lab_order_validation.handlers.preflight_validator.Patient"
LAB_PARTNER_PATH = "lab_order_validation.handlers.preflight_validator.LabPartner"


def _electronic_partner(name="Labcorp"):
    return {
        "text": name,
        "value": name,
        "extra": {"electronic_ordering_enabled": True},
    }


def _paper_partner(name="Paper Lab"):
    return {
        "text": name,
        "value": name,
        "extra": {"electronic_ordering_enabled": False},
    }


def _build_handler(*, lab_partner_field, patient_id="patient-1", note_uuid="note-1"):
    event = MagicMock()
    event.context = {
        "fields": {"lab_partner": lab_partner_field},
        "patient": {"id": patient_id},
        "note": {"uuid": note_uuid},
    }
    return LabOrderPreflightValidator(event)


def _patch_lab_partner_lookup(mock_lab_partner_cls, *, electronic, name="Labcorp"):
    """Configure the LabPartner mock to return a partner with the given flag.

    Pass electronic=None to simulate the partner not being found in the DB.
    """
    if electronic is None:
        mock_lab_partner_cls.objects.filter.return_value.first.return_value = None
        return None
    partner = MagicMock()
    partner.name = name
    partner.electronic_ordering_enabled = electronic
    mock_lab_partner_cls.objects.filter.return_value.first.return_value = partner
    return partner


def test_no_op_when_lab_partner_not_electronic():
    handler = _build_handler(lab_partner_field=_paper_partner())

    with patch(PATIENT_PATH) as mock_patient_cls, patch(LAB_PARTNER_PATH) as mock_lab_partner_cls:
        _patch_lab_partner_lookup(mock_lab_partner_cls, electronic=False, name="Paper Lab")
        effects = handler.compute()

        assert effects == []
        assert mock_patient_cls.mock_calls == []


def test_no_op_when_no_lab_partner_selected():
    handler = _build_handler(lab_partner_field=None)

    with patch(PATIENT_PATH) as mock_patient_cls, patch(LAB_PARTNER_PATH) as mock_lab_partner_cls:
        effects = handler.compute()

        assert effects == []
        assert mock_patient_cls.mock_calls == []
        # No lookup attempted when there's nothing to look up
        assert mock_lab_partner_cls.objects.filter.mock_calls == []


def test_no_op_when_partner_not_found_in_db():
    """A lab_partner value that doesn't match any LabPartner record should skip validation."""
    handler = _build_handler(lab_partner_field="Stale Partner Name")

    with patch(PATIENT_PATH) as mock_patient_cls, patch(LAB_PARTNER_PATH) as mock_lab_partner_cls:
        _patch_lab_partner_lookup(mock_lab_partner_cls, electronic=None)
        effects = handler.compute()

        assert effects == []
        assert mock_patient_cls.mock_calls == []


def test_lookup_succeeds_for_string_field_automation_path():
    """Automation may pass lab_partner as a plain string (no dropdown extra)."""
    handler = _build_handler(lab_partner_field="Labcorp")

    with patch(PATIENT_PATH) as mock_patient_cls, patch(LAB_PARTNER_PATH) as mock_lab_partner_cls:
        _patch_lab_partner_lookup(mock_lab_partner_cls, electronic=True)
        # Patient not found so we exit before running rules; we only care
        # that the lookup was attempted and is_electronic is True.
        mock_patient_cls.objects.filter.return_value.prefetch_related.return_value.first.return_value = None

        handler.compute()

        # Patient lookup happened, meaning the electronic check returned True
        # for the bare-string lab_partner field.
        assert mock_patient_cls.objects.filter.called


def test_no_op_when_no_patient_id():
    event = MagicMock()
    event.context = {
        "fields": {"lab_partner": _electronic_partner()},
        "patient": {},
        "note": {"uuid": "note-1"},
    }
    handler = LabOrderPreflightValidator(event)

    with patch(PATIENT_PATH) as mock_patient_cls, patch(LAB_PARTNER_PATH) as mock_lab_partner_cls:
        _patch_lab_partner_lookup(mock_lab_partner_cls, electronic=True)
        effects = handler.compute()

        assert effects == []
        assert mock_patient_cls.mock_calls == []


def test_no_op_when_patient_not_found():
    handler = _build_handler(lab_partner_field=_electronic_partner())

    with patch(PATIENT_PATH) as mock_patient_cls, patch(LAB_PARTNER_PATH) as mock_lab_partner_cls:
        _patch_lab_partner_lookup(mock_lab_partner_cls, electronic=True)
        mock_patient_cls.objects.filter.return_value.prefetch_related.return_value.first.return_value = None

        effects = handler.compute()

        assert effects == []


def test_pass_when_all_rules_satisfied(healthy_patient):
    handler = _build_handler(lab_partner_field=_electronic_partner())

    with patch(PATIENT_PATH) as mock_patient_cls, patch(LAB_PARTNER_PATH) as mock_lab_partner_cls:
        _patch_lab_partner_lookup(mock_lab_partner_cls, electronic=True)
        mock_patient_cls.objects.filter.return_value.prefetch_related.return_value.first.return_value = healthy_patient

        effects = handler.compute()

        assert effects == []


def test_extra_says_paper_but_db_says_electronic_uses_db(healthy_patient):
    """If the field's `extra` blob disagrees with the DB, trust the DB."""
    # Field claims paper, DB says electronic - we should validate.
    handler = _build_handler(lab_partner_field=_paper_partner(name="Labcorp"))

    with patch(PATIENT_PATH) as mock_patient_cls, patch(LAB_PARTNER_PATH) as mock_lab_partner_cls:
        _patch_lab_partner_lookup(mock_lab_partner_cls, electronic=True, name="Labcorp")
        mock_patient_cls.objects.filter.return_value.prefetch_related.return_value.first.return_value = healthy_patient

        # Healthy patient passes all rules, so result is []; what we're proving
        # is that Patient.objects.filter was called - meaning we ran validation.
        handler.compute()

        assert mock_patient_cls.objects.filter.called


def test_extra_says_electronic_but_db_says_paper_uses_db(healthy_patient):
    """If the field's `extra` blob disagrees with the DB, trust the DB - the
    other direction. Extra claims electronic, DB says paper - we should skip."""
    handler = _build_handler(lab_partner_field=_electronic_partner(name="Paper Lab"))

    with patch(PATIENT_PATH) as mock_patient_cls, patch(LAB_PARTNER_PATH) as mock_lab_partner_cls:
        _patch_lab_partner_lookup(mock_lab_partner_cls, electronic=False, name="Paper Lab")

        effects = handler.compute()

        assert effects == []
        assert mock_patient_cls.mock_calls == []


def test_blocks_when_address_rule_fails(patient_with, make_patient_address, make_coverage):
    bad_patient = patient_with(
        coverages=[make_coverage(rank=1, issuer=MagicMock(dbid=1, name="Acme"))],
        addresses=[make_patient_address(use="home", type="physical")],
    )
    bad_patient.coverages.all.return_value[0].issuer.addresses.all.return_value = [
        _ok_transactor_address()
    ]
    bad_patient.coverages.all.return_value[0].issuer.phones.all.return_value = [
        _ok_transactor_phone()
    ]

    handler = _build_handler(lab_partner_field=_electronic_partner())

    with patch(PATIENT_PATH) as mock_patient_cls, patch(LAB_PARTNER_PATH) as mock_lab_partner_cls:
        _patch_lab_partner_lookup(mock_lab_partner_cls, electronic=True)
        mock_patient_cls.objects.filter.return_value.prefetch_related.return_value.first.return_value = bad_patient

        effects = handler.compute()

        assert len(effects) == 1


def test_blocks_when_rule2_fires(
    patient_with, make_coverage, make_issuer, make_patient_address
):
    duplicate_issuer = make_issuer(dbid=99, name="Acme")
    patient = patient_with(
        coverages=[
            make_coverage(rank=1, issuer=duplicate_issuer),
            make_coverage(rank=2, issuer=duplicate_issuer),
        ],
        addresses=[make_patient_address()],
    )

    handler = _build_handler(lab_partner_field=_electronic_partner())

    with patch(PATIENT_PATH) as mock_patient_cls, patch(LAB_PARTNER_PATH) as mock_lab_partner_cls:
        _patch_lab_partner_lookup(mock_lab_partner_cls, electronic=True)
        mock_patient_cls.objects.filter.return_value.prefetch_related.return_value.first.return_value = patient

        effects = handler.compute()

        assert len(effects) == 1


def test_blocks_when_subscriber_address_missing(
    patient_with, make_coverage, make_issuer, make_patient_address
):
    issuer = make_issuer(dbid=1, name="Acme")
    bare_subscriber = MagicMock()
    bare_subscriber.id = "subscriber-uuid"
    bare_subscriber.full_name = "Jane Doe"
    bare_subscriber.first_name = "Jane"
    bare_subscriber.last_name = "Doe"
    bare_subscriber.addresses.all.return_value = []

    patient = patient_with(
        coverages=[make_coverage(rank=1, issuer=issuer, subscriber=bare_subscriber)],
        addresses=[make_patient_address()],
    )

    handler = _build_handler(lab_partner_field=_electronic_partner())

    with patch(PATIENT_PATH) as mock_patient_cls, patch(LAB_PARTNER_PATH) as mock_lab_partner_cls:
        _patch_lab_partner_lookup(mock_lab_partner_cls, electronic=True)
        mock_patient_cls.objects.filter.return_value.prefetch_related.return_value.first.return_value = patient

        effects = handler.compute()

        assert len(effects) == 1


def _ok_transactor_address():
    addr = MagicMock()
    addr.line1 = "1 Health Way"
    addr.city = "Boston"
    addr.state_code = "MA"
    addr.postal_code = "02101"
    return addr


def _ok_transactor_phone():
    phone = MagicMock()
    phone.value = "617-555-0100"
    return phone


# ------------------------------------------------------------------
# _lookup_partner unit tests - exercise the resolver directly
# ------------------------------------------------------------------


class TestLookupPartner:
    """Direct tests for the static _lookup_partner resolver.

    These verify each lookup path (UUID, name, name__iexact) and the
    defensive try/except behavior, without going through the full handler.
    """

    UUID = "a74592ae-8a6c-4d0e-be07-99d3fb3713d1"

    def _matched_partner(self, name="Labcorp"):
        partner = MagicMock()
        partner.name = name
        return partner

    def test_uuid_value_calls_filter_by_id(self):
        with patch(LAB_PARTNER_PATH) as mock_lp:
            expected = self._matched_partner()
            mock_lp.objects.filter.return_value.first.return_value = expected

            result = LabOrderPreflightValidator._lookup_partner(
                {"value": self.UUID, "text": "Labcorp"}
            )

            assert result is expected
            # First call should be filter(id=<uuid>)
            mock_lp.objects.filter.assert_any_call(id=self.UUID)

    def test_non_uuid_string_skips_id_filter_and_uses_name(self):
        """Critical regression: passing a name to filter(id=...) raises in
        Django (UUIDField). The UUID-shape guard prevents this crash."""
        with patch(LAB_PARTNER_PATH) as mock_lp:
            # First call (name=) misses; we won't reach iexact in this test
            mock_lp.objects.filter.return_value.first.side_effect = [
                self._matched_partner(),
            ]

            result = LabOrderPreflightValidator._lookup_partner("Labcorp")

            assert result is not None
            # filter(id=...) should NOT have been called
            id_calls = [
                c for c in mock_lp.objects.filter.call_args_list
                if "id" in c.kwargs
            ]
            assert id_calls == []
            # filter(name=...) SHOULD have been called
            mock_lp.objects.filter.assert_any_call(name="Labcorp")

    def test_name_iexact_fallback_when_exact_name_misses(self):
        """If case differs (e.g. 'labcorp' vs 'Labcorp'), iexact saves us."""
        with patch(LAB_PARTNER_PATH) as mock_lp:
            # Sequence: exact name miss (None), then iexact hit
            mock_lp.objects.filter.return_value.first.side_effect = [
                None,
                self._matched_partner(name="Labcorp"),
            ]

            result = LabOrderPreflightValidator._lookup_partner("labcorp")

            assert result is not None
            assert result.name == "Labcorp"
            mock_lp.objects.filter.assert_any_call(name__iexact="labcorp")

    def test_tries_both_value_and_text_candidates(self):
        """If value misses but text matches, we should still resolve."""
        with patch(LAB_PARTNER_PATH) as mock_lp:
            # value="stale-id" misses every path; text="Labcorp" hits name=
            mock_lp.objects.filter.return_value.first.side_effect = [
                None,  # name="stale-id"
                self._matched_partner(),  # name="Labcorp"
            ]

            result = LabOrderPreflightValidator._lookup_partner(
                {"value": "stale-id", "text": "Labcorp"}
            )

            assert result is not None

    def test_returns_none_when_no_candidates(self):
        for field in (None, {}, "", {"value": "", "text": ""}):
            assert LabOrderPreflightValidator._lookup_partner(field) is None

    def test_returns_none_when_no_match_anywhere(self):
        with patch(LAB_PARTNER_PATH) as mock_lp:
            mock_lp.objects.filter.return_value.first.return_value = None

            result = LabOrderPreflightValidator._lookup_partner("Unknown Lab")

            assert result is None

    def test_returns_none_when_lookup_raises(self):
        """Defensive: an unexpected DB-layer exception must not crash the handler."""
        with patch(LAB_PARTNER_PATH) as mock_lp:
            mock_lp.objects.filter.return_value.first.side_effect = ValueError(
                "simulated db error"
            )

            result = LabOrderPreflightValidator._lookup_partner("Labcorp")

            assert result is None

    def test_uuid_in_value_with_dashes_or_without(self):
        """Both dashed and undashed UUIDs should match the UUID pattern."""
        with patch(LAB_PARTNER_PATH) as mock_lp:
            mock_lp.objects.filter.return_value.first.return_value = self._matched_partner()

            for shape in (
                self.UUID,  # dashed
                self.UUID.replace("-", ""),  # undashed
            ):
                LabOrderPreflightValidator._lookup_partner(shape)

            # Both invocations should have used filter(id=...)
            id_calls = [
                c for c in mock_lp.objects.filter.call_args_list
                if "id" in c.kwargs
            ]
            assert len(id_calls) == 2
