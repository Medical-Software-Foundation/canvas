"""Tests for patient_tags.services.label_service.

Covers serialization helpers, CRUD wrappers around the Canvas custom models,
patient-assignment workflows (save/add/remove), rule application, audit
writing, and validation helpers.
"""
from unittest.mock import MagicMock, patch

import pytest

from patient_tags.services import label_service


def _make_group(*, dbid: int, name: str, intent: str = "info",
                placements: list[str] | None = None,
                separator: str = " • ", href: str = "") -> MagicMock:
    """Build a MagicMock that mirrors a BannerGroup row.

    Setting `.name` directly is required because MagicMock treats a `name=`
    constructor kwarg as the mock's display name, not as a real attribute.
    """
    g = MagicMock(dbid=dbid, intent=intent, separator=separator, href=href)
    g.name = name
    g.placements = placements if placements is not None else ["CHART"]
    return g


def _make_label(*, dbid: int, name: str, description: str = "",
                color: str = "blue", assignable_in_chart: bool = True,
                assignable_in_profile: bool = True,
                banner_group_id: int | None = None) -> MagicMock:
    label = MagicMock(
        dbid=dbid, description=description, color=color,
        assignable_in_chart=assignable_in_chart,
        assignable_in_profile=assignable_in_profile,
        banner_group_id=banner_group_id,
    )
    label.name = name
    return label


class TestSerializeGroup:
    def test_without_label_count(self) -> None:
        group = _make_group(
            dbid=7, name="G", intent="warning",
            placements=["CHART"], separator=" · ", href="/x",
        )
        result = label_service._serialize_group(group)
        assert result == {
            "id": 7,
            "name": "G",
            "intent": "warning",
            "placements": ["CHART"],
            "separator": " · ",
            "href": "/x",
        }

    def test_with_label_count_and_null_placements(self) -> None:
        # Setting placements directly to None to verify the `or []` fallback.
        group = _make_group(dbid=1, name="G")
        group.placements = None
        result = label_service._serialize_group(group, label_count=3)
        assert result["label_count"] == 3
        assert result["placements"] == []


class TestSerializeLabel:
    def test_full_payload(self) -> None:
        label = _make_label(
            dbid=5, name="VIP", description="desc", color="blue",
            assignable_in_chart=True, assignable_in_profile=False,
            banner_group_id=9,
        )
        result = label_service._serialize_label(label, banner_group_name="Care")
        assert result == {
            "id": 5,
            "name": "VIP",
            "description": "desc",
            "color": "blue",
            "assignable_in_chart": True,
            "assignable_in_profile": False,
            "banner_group_id": 9,
            "banner_group_name": "Care",
        }


class TestResolveGroupName:
    def test_returns_none_when_no_id(self) -> None:
        assert label_service._resolve_group_name(None) is None
        assert label_service._resolve_group_name(0) is None

    @patch("patient_tags.services.label_service.BannerGroup")
    def test_returns_name_when_present(self, mock_group: MagicMock) -> None:
        mock_group.objects.filter.return_value.values_list.return_value.first.return_value = "Care"
        assert label_service._resolve_group_name(5) == "Care"

    @patch("patient_tags.services.label_service.BannerGroup")
    def test_returns_none_when_missing(self, mock_group: MagicMock) -> None:
        mock_group.objects.filter.return_value.values_list.return_value.first.return_value = None
        assert label_service._resolve_group_name(99) is None


class TestListBannerGroups:
    @patch("patient_tags.services.label_service.BannerGroup")
    def test_empty(self, mock_group: MagicMock) -> None:
        mock_group.objects.all.return_value.order_by.return_value = []
        assert label_service.list_banner_groups() == []

    @patch("patient_tags.services.label_service.Label")
    @patch("patient_tags.services.label_service.BannerGroup")
    def test_with_groups_counts_labels(self, mock_group: MagicMock, mock_label: MagicMock) -> None:
        g1 = _make_group(dbid=1, name="A")
        g2 = _make_group(dbid=2, name="B", intent="alert", placements=["PROFILE"])
        mock_group.objects.all.return_value.order_by.return_value = [g1, g2]
        mock_label.objects.filter.return_value.values_list.return_value = [1, 1, 2]

        result = label_service.list_banner_groups()

        assert result[0]["label_count"] == 2
        assert result[1]["label_count"] == 1


class TestCreateBannerGroup:
    @patch("patient_tags.services.label_service.BannerGroup")
    def test_happy_path(self, mock_group: MagicMock) -> None:
        mock_group.objects.filter.return_value.exists.return_value = False
        created = _make_group(dbid=1, name="A")
        mock_group.objects.create.return_value = created

        result = label_service.create_banner_group(name="  A  ")

        mock_group.objects.create.assert_called_once_with(
            name="A", intent="info", placements=["CHART"], separator=" • ", href=""
        )
        assert result["name"] == "A"

    @patch("patient_tags.services.label_service.BannerGroup")
    def test_duplicate_raises(self, mock_group: MagicMock) -> None:
        mock_group.objects.filter.return_value.exists.return_value = True

        with pytest.raises(ValueError, match="already exists"):
            label_service.create_banner_group(name="A")

    def test_blank_name_raises(self) -> None:
        with pytest.raises(ValueError, match="name is required"):
            label_service.create_banner_group(name="   ")

    def test_invalid_intent_raises(self) -> None:
        with pytest.raises(ValueError, match="intent must be one of"):
            label_service.create_banner_group(name="A", intent="bogus")

    def test_invalid_placement_raises(self) -> None:
        with pytest.raises(ValueError, match="placement"):
            label_service.create_banner_group(name="A", placements=["BOGUS"])


class TestUpdateBannerGroup:
    @patch("patient_tags.services.label_service.BannerGroup")
    def test_update_all_fields(self, mock_group: MagicMock) -> None:
        existing = _make_group(dbid=1, name="Old", placements=[])
        mock_group.objects.get.return_value = existing
        mock_group.objects.filter.return_value.exclude.return_value.exists.return_value = False

        result = label_service.update_banner_group(
            1,
            name="New",
            intent="warning",
            placements=["TIMELINE"],
            separator="; ",
            href="/h",
        )

        existing.save.assert_called_once()
        assert existing.name == "New"
        assert existing.intent == "warning"
        assert existing.placements == ["TIMELINE"]
        assert existing.separator == "; "
        assert existing.href == "/h"
        assert result["id"] == 1

    @patch("patient_tags.services.label_service.BannerGroup")
    def test_name_unchanged_skips_uniqueness_check(self, mock_group: MagicMock) -> None:
        existing = _make_group(dbid=1, name="Same", placements=[])
        mock_group.objects.get.return_value = existing

        label_service.update_banner_group(1, name="Same")

        existing.save.assert_called_once()

    @patch("patient_tags.services.label_service.BannerGroup")
    def test_name_conflict_raises(self, mock_group: MagicMock) -> None:
        existing = _make_group(dbid=1, name="Old", placements=[])
        mock_group.objects.get.return_value = existing
        mock_group.objects.filter.return_value.exclude.return_value.exists.return_value = True

        with pytest.raises(ValueError, match="already exists"):
            label_service.update_banner_group(1, name="Taken")

    @patch("patient_tags.services.label_service.BannerGroup")
    def test_blank_name_raises(self, mock_group: MagicMock) -> None:
        existing = _make_group(dbid=1, name="x", placements=[])
        mock_group.objects.get.return_value = existing

        with pytest.raises(ValueError, match="name is required"):
            label_service.update_banner_group(1, name="   ")

    @patch("patient_tags.services.label_service.BannerGroup")
    def test_href_falsy_becomes_empty_string(self, mock_group: MagicMock) -> None:
        existing = _make_group(dbid=1, name="N", placements=[])
        mock_group.objects.get.return_value = existing

        label_service.update_banner_group(1, href=None)
        assert existing.href == ""


class TestDeleteBannerGroup:
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service.BannerGroup")
    @patch("patient_tags.services.label_service.Label")
    def test_unsets_labels_and_deletes_group(
        self, mock_label: MagicMock, mock_group: MagicMock, mock_pl: MagicMock
    ) -> None:
        # New behavior: also queries patient UUIDs and emits RemoveBannerAlert
        # for each. With no labels in the group, no patient lookup is needed
        # and no effects are emitted.
        mock_label.objects.filter.return_value.values_list.return_value = []

        effects = label_service.delete_banner_group(7)

        # Filter is now called twice on Label: once to gather label_ids,
        # once to clear banner_group=None. Both with banner_group_id=7.
        filter_calls = mock_label.objects.filter.call_args_list
        assert all(c.kwargs == {"banner_group_id": 7} for c in filter_calls)
        mock_label.objects.filter.return_value.update.assert_called_once_with(banner_group=None)
        mock_group.objects.filter.assert_called_once_with(dbid=7)
        mock_group.objects.filter.return_value.delete.assert_called_once()
        assert effects == []


class TestListLabels:
    @patch("patient_tags.services.label_service.Label")
    def test_empty(self, mock_label: MagicMock) -> None:
        mock_label.objects.order_by.return_value = []
        assert label_service.list_labels() == []

    @patch("patient_tags.services.label_service.BannerGroup")
    @patch("patient_tags.services.label_service.Label")
    def test_with_labels_resolves_group_names(
        self, mock_label: MagicMock, mock_group: MagicMock
    ) -> None:
        l1 = _make_label(dbid=1, name="A", banner_group_id=10)
        l2 = _make_label(dbid=2, name="B", color="red", banner_group_id=None)
        mock_label.objects.order_by.return_value = [l1, l2]
        mock_group.objects.filter.return_value.values_list.return_value = [(10, "Care")]

        result = label_service.list_labels()

        assert result[0]["banner_group_name"] == "Care"
        assert result[1]["banner_group_name"] is None

    @patch("patient_tags.services.label_service.BannerGroup")
    @patch("patient_tags.services.label_service.Label")
    def test_no_group_ids_skips_banner_lookup(
        self, mock_label: MagicMock, mock_group: MagicMock
    ) -> None:
        l1 = _make_label(dbid=1, name="A", banner_group_id=None)
        mock_label.objects.order_by.return_value = [l1]

        result = label_service.list_labels()

        assert result[0]["banner_group_name"] is None
        mock_group.objects.filter.assert_not_called()


class TestCreateLabel:
    @patch("patient_tags.services.label_service._resolve_group_name", return_value=None)
    @patch("patient_tags.services.label_service.Label")
    def test_happy_path(self, mock_label: MagicMock, _mock_resolve: MagicMock) -> None:
        mock_label.objects.filter.return_value.exists.return_value = False
        created = _make_label(dbid=1, name="VIP", description="d")
        mock_label.objects.create.return_value = created

        result = label_service.create_label(name="  VIP  ", description="d")

        mock_label.objects.create.assert_called_once_with(
            name="VIP", description="d", color="blue",
            assignable_in_chart=True, assignable_in_profile=True, banner_group_id=None,
        )
        assert result["name"] == "VIP"

    @patch("patient_tags.services.label_service.Label")
    def test_duplicate_raises(self, mock_label: MagicMock) -> None:
        mock_label.objects.filter.return_value.exists.return_value = True
        with pytest.raises(ValueError, match="already exists"):
            label_service.create_label(name="A")

    def test_blank_name_raises(self) -> None:
        with pytest.raises(ValueError, match="name is required"):
            label_service.create_label(name="")

    def test_oversize_description_raises(self) -> None:
        with pytest.raises(ValueError, match="description exceeds"):
            label_service.create_label(name="A", description="x" * 5000)

    def test_invalid_color_raises(self) -> None:
        with pytest.raises(ValueError, match="color must be one of"):
            label_service.create_label(name="A", color="bogus")


class TestUpdateLabel:
    @patch("patient_tags.services.label_service._compute_banner_effects_for", return_value=[])
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service._resolve_group_name", return_value=None)
    @patch("patient_tags.services.label_service.Label")
    def test_full_update(
        self, mock_label: MagicMock, _mock_resolve: MagicMock,
        _mock_pl: MagicMock, _mock_reconcile: MagicMock,
    ) -> None:
        existing = _make_label(dbid=1, name="Old")
        mock_label.objects.get.return_value = existing
        mock_label.objects.filter.return_value.exclude.return_value.exists.return_value = False

        result = label_service.update_label(
            1,
            name="New",
            description="d",
            color="red",
            assignable_in_chart=False,
            assignable_in_profile=False,
            banner_group_id=10,
        )

        # Returns (label, effects) tuple now.
        label_dict, effects = result
        assert existing.name == "New"
        assert existing.description == "d"
        assert existing.color == "red"
        assert existing.assignable_in_chart is False
        assert existing.assignable_in_profile is False
        assert existing.banner_group_id == 10
        existing.save.assert_called_once()
        assert effects == []

    @patch("patient_tags.services.label_service._compute_banner_effects_for", return_value=[])
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service._resolve_group_name", return_value=None)
    @patch("patient_tags.services.label_service.Label")
    def test_name_unchanged_skips_uniqueness(
        self, mock_label: MagicMock, _mock_resolve: MagicMock,
        _mock_pl: MagicMock, _mock_reconcile: MagicMock,
    ) -> None:
        existing = _make_label(dbid=1, name="Same")
        mock_label.objects.get.return_value = existing

        label_dict, effects = label_service.update_label(1, name="Same")

        existing.save.assert_called_once()

    @patch("patient_tags.services.label_service.Label")
    def test_name_conflict_raises(self, mock_label: MagicMock) -> None:
        existing = _make_label(dbid=1, name="Old")
        mock_label.objects.get.return_value = existing
        mock_label.objects.filter.return_value.exclude.return_value.exists.return_value = True

        with pytest.raises(ValueError, match="already exists"):
            label_service.update_label(1, name="Taken")


class TestDeleteLabel:
    @patch("patient_tags.services.label_service._compute_banner_effects_for", return_value=[])
    @patch("patient_tags.services.label_service.Label")
    @patch("patient_tags.services.label_service.LabelRule")
    @patch("patient_tags.services.label_service.PatientLabel")
    def test_cleans_up_assignments_rules_and_label(
        self, mock_pl: MagicMock, mock_rule: MagicMock, mock_label: MagicMock,
        _mock_reconcile: MagicMock,
    ) -> None:
        # Delete now also queries affected patient UUIDs first, then runs
        # the same delete sequence as before.
        mock_pl.objects.filter.return_value.values_list.return_value.distinct.return_value = []

        effects = label_service.delete_label(5)

        # PatientLabel.filter is called twice now: once to gather UUIDs,
        # once to delete. Both with label_id=5.
        pl_filter_calls = mock_pl.objects.filter.call_args_list
        assert all(c.kwargs == {"label_id": 5} for c in pl_filter_calls)
        mock_pl.objects.filter.return_value.delete.assert_called_once()
        # Two LabelRule.filter calls — trigger + target.
        assert mock_rule.objects.filter.call_count == 2
        mock_label.objects.filter.assert_called_once_with(dbid=5)
        mock_label.objects.filter.return_value.delete.assert_called_once()
        assert effects == []

    @patch("patient_tags.services.label_service._compute_banner_effects_for")
    @patch("patient_tags.services.label_service.Label")
    @patch("patient_tags.services.label_service.LabelRule")
    @patch("patient_tags.services.label_service.PatientLabel")
    def test_returns_reconcile_effects_for_affected_patients(
        self, mock_pl: MagicMock, mock_rule: MagicMock, mock_label: MagicMock,
        mock_reconcile: MagicMock,
    ) -> None:
        # Label is assigned to 2 patients; reconcile should fire for both
        # so their banner narratives drop the deleted label.
        mock_pl.objects.filter.return_value.values_list.return_value.distinct.return_value = [
            "uuid-a", "uuid-b",
        ]
        sentinel_effect = MagicMock()
        mock_reconcile.return_value = [sentinel_effect, sentinel_effect]

        effects = label_service.delete_label(5)

        mock_reconcile.assert_called_once_with(["uuid-a", "uuid-b"])
        assert effects == [sentinel_effect, sentinel_effect]


class TestGetPatientAssignmentIds:
    @patch("patient_tags.services.label_service.PatientLabel")
    def test_returns_list_of_ids(self, mock_pl: MagicMock) -> None:
        mock_pl.objects.filter.return_value.values_list.return_value = [1, 2, 3]
        assert label_service.get_patient_assignment_ids("p1") == [1, 2, 3]


class TestSavePatientAssignments:
    @patch("patient_tags.services.label_service._apply_rules_for_triggers")
    @patch("patient_tags.services.label_service._write_assignment_audits")
    @patch("patient_tags.services.label_service.Label")
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service.PatientProxy")
    def test_creates_and_deletes_to_match_desired_set(
        self,
        mock_proxy: MagicMock,
        mock_pl: MagicMock,
        mock_label: MagicMock,
        mock_audit: MagicMock,
        mock_rules: MagicMock,
    ) -> None:
        patient = MagicMock()
        mock_proxy.objects.get.return_value = patient
        # Label.objects.filter(...).values_list(...) returns the IDs that
        # exist — both 2 and 3 are valid here.
        mock_label.objects.filter.return_value.values_list.return_value = [2, 3]

        existing_pl = MagicMock(label_id=1, dbid=100)
        existing_qs = MagicMock()
        existing_qs.__iter__ = lambda self: iter([existing_pl])
        delete_qs = MagicMock()
        mock_pl.objects.filter.side_effect = [existing_qs, delete_qs]

        label_service.save_patient_assignments("p1", [2, 3], actor_id="u1", actor_name="N")

        kwargs = mock_audit.call_args.kwargs
        assert sorted(kwargs["added_ids"]) == [2, 3]
        assert kwargs["removed_ids"] == [1]
        assert kwargs["via"] == "manual"
        delete_qs.delete.assert_called_once()
        mock_rules.assert_called_once()

    @patch("patient_tags.services.label_service._apply_rules_for_triggers")
    @patch("patient_tags.services.label_service._write_assignment_audits")
    @patch("patient_tags.services.label_service.Label")
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service.PatientProxy")
    def test_no_creates_skips_rule_application(
        self,
        mock_proxy: MagicMock,
        mock_pl: MagicMock,
        mock_label: MagicMock,
        mock_audit: MagicMock,
        mock_rules: MagicMock,
    ) -> None:
        mock_proxy.objects.get.return_value = MagicMock()
        mock_label.objects.filter.return_value.values_list.return_value = [1]
        existing_pl = MagicMock(label_id=1, dbid=100)
        existing_qs = MagicMock()
        existing_qs.__iter__ = lambda self: iter([existing_pl])
        mock_pl.objects.filter.return_value = existing_qs

        # desired == existing (only 1) → no creates, no deletes.
        label_service.save_patient_assignments("p1", [1])

        mock_rules.assert_not_called()

    @patch("patient_tags.services.label_service.Label")
    @patch("patient_tags.services.label_service.PatientProxy")
    def test_unknown_label_id_raises_value_error(
        self, mock_proxy: MagicMock, mock_label: MagicMock
    ) -> None:
        mock_proxy.objects.get.return_value = MagicMock()
        # Label.objects.filter(dbid__in=...) returns only label 1; 99 is unknown.
        mock_label.objects.filter.return_value.values_list.return_value = [1]

        with pytest.raises(ValueError, match="Unknown label IDs"):
            label_service.save_patient_assignments("p1", [1, 99])


class TestAddPatientAssignments:
    @patch("patient_tags.services.label_service._apply_rules_for_triggers")
    @patch("patient_tags.services.label_service._write_assignment_audits")
    @patch("patient_tags.services.label_service.Label")
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service.PatientProxy")
    def test_skips_already_present_and_adds_new(
        self,
        mock_proxy: MagicMock,
        mock_pl: MagicMock,
        mock_label: MagicMock,
        mock_audit: MagicMock,
        mock_rules: MagicMock,
    ) -> None:
        mock_proxy.objects.get.return_value = MagicMock()
        mock_pl.objects.filter.return_value.values_list.return_value = [1]
        mock_label.objects.filter.return_value.values_list.return_value = [2]

        result = label_service.add_patient_assignments("p1", [1, 2])

        assert result == {"added": [2], "already_present": [1]}
        mock_audit.assert_called_once()
        mock_rules.assert_called_once()

    @patch("patient_tags.services.label_service.Label")
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service.PatientProxy")
    def test_unknown_label_id_raises(
        self, mock_proxy: MagicMock, mock_pl: MagicMock, mock_label: MagicMock
    ) -> None:
        mock_proxy.objects.get.return_value = MagicMock()
        mock_pl.objects.filter.return_value.values_list.return_value = []
        mock_label.objects.filter.return_value.values_list.return_value = []  # nothing valid

        with pytest.raises(ValueError, match="Unknown label IDs"):
            label_service.add_patient_assignments("p1", [99])

    @patch("patient_tags.services.label_service._apply_rules_for_triggers")
    @patch("patient_tags.services.label_service._write_assignment_audits")
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service.PatientProxy")
    def test_all_already_present_short_circuits(
        self,
        mock_proxy: MagicMock,
        mock_pl: MagicMock,
        mock_audit: MagicMock,
        mock_rules: MagicMock,
    ) -> None:
        mock_proxy.objects.get.return_value = MagicMock()
        mock_pl.objects.filter.return_value.values_list.return_value = [1, 2]

        result = label_service.add_patient_assignments("p1", [1, 2])

        assert result == {"added": [], "already_present": [1, 2]}
        mock_audit.assert_not_called()
        mock_rules.assert_not_called()


class TestRemovePatientAssignments:
    @patch("patient_tags.services.label_service._write_assignment_audits")
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service.PatientProxy")
    def test_removes_present_and_skips_absent(
        self,
        mock_proxy: MagicMock,
        mock_pl: MagicMock,
        mock_audit: MagicMock,
    ) -> None:
        patient = MagicMock()
        mock_proxy.objects.get.return_value = patient
        mock_pl.objects.filter.return_value.values_list.return_value = [1, 2]

        result = label_service.remove_patient_assignments("p1", [2, 3])

        assert result == {"removed": [2], "not_present": [3]}
        mock_audit.assert_called_once()

    @patch("patient_tags.services.label_service._write_assignment_audits")
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service.PatientProxy")
    def test_nothing_to_remove_skips_audit(
        self,
        mock_proxy: MagicMock,
        mock_pl: MagicMock,
        mock_audit: MagicMock,
    ) -> None:
        mock_proxy.objects.get.return_value = MagicMock()
        mock_pl.objects.filter.return_value.values_list.return_value = []

        result = label_service.remove_patient_assignments("p1", [99])

        assert result == {"removed": [], "not_present": [99]}
        mock_audit.assert_not_called()


class TestApplyRulesForTriggers:
    @patch("patient_tags.services.label_service._write_assignment_audits")
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service.LabelRule")
    def test_auto_assign_creates_missing_targets(
        self,
        mock_rule: MagicMock,
        mock_pl: MagicMock,
        mock_audit: MagicMock,
    ) -> None:
        rule = MagicMock(action="auto_assign", target_label_id=99)
        mock_rule.objects.filter.return_value = [rule]
        # patient currently has nothing
        mock_pl.objects.filter.return_value.values_list.return_value = []

        patient = MagicMock()
        label_service._apply_rules_for_triggers(patient, [1])

        mock_pl.objects.create.assert_called_once_with(patient=patient, label_id=99)
        mock_audit.assert_called_once()


class TestWriteAssignmentAudits:
    @patch("patient_tags.services.label_service.PatientLabelAudit")
    @patch("patient_tags.services.label_service.Label")
    def test_no_changes_short_circuits(
        self, mock_label: MagicMock, mock_audit: MagicMock
    ) -> None:
        label_service._write_assignment_audits(
            patient_uuid="p1", added_ids=[], removed_ids=[],
            via="manual", actor_id="", actor_name="",
        )
        mock_label.objects.filter.assert_not_called()
        mock_audit.objects.create.assert_not_called()

    @patch("patient_tags.services.label_service.PatientLabelAudit")
    @patch("patient_tags.services.label_service.Label")
    def test_writes_audit_row_per_change_with_meta_fallback(
        self, mock_label: MagicMock, mock_audit: MagicMock
    ) -> None:
        # Label 1 has metadata, label 2 does not (missing entry).
        mock_label.objects.filter.return_value.values.return_value = [
            {"dbid": 1, "name": "Known", "color": "blue"},
        ]

        label_service._write_assignment_audits(
            patient_uuid="p1",
            added_ids=[1, 2],
            removed_ids=[],
            via="manual",
            actor_id="u1",
            actor_name="N",
        )

        assert mock_audit.objects.create.call_count == 2
        # Second call should use fallback name "label #2"
        second_call = mock_audit.objects.create.call_args_list[1]
        assert "label #2" == second_call.kwargs["label_name"]
        assert "blue" == second_call.kwargs["label_color"]


class TestListPatientHistory:
    @patch("patient_tags.services.label_service.PatientLabelAudit")
    def test_serializes_rows(self, mock_audit: MagicMock) -> None:
        ts = MagicMock()
        ts.isoformat.return_value = "2026-05-01T00:00:00"
        rows = [{
            "label_id": 1, "label_name": "A", "label_color": "blue",
            "action": "assigned", "via": "manual",
            "actor_name": "Alice", "actor_id": "u1", "at": ts,
        }]
        # The chained .filter().order_by().values()[:limit] expression
        # supports __getitem__ via MagicMock by default — just return rows
        mock_audit.objects.filter.return_value.order_by.return_value.values.return_value.__getitem__.return_value = rows

        result = label_service.list_patient_history("p1")

        assert result == [{
            "label_id": 1, "label_name": "A", "label_color": "blue",
            "action": "assigned", "via": "manual",
            "actor_name": "Alice", "actor_id": "u1",
            "at": "2026-05-01T00:00:00",
        }]

    @patch("patient_tags.services.label_service.PatientLabelAudit")
    def test_actor_name_falls_back_to_unknown(self, mock_audit: MagicMock) -> None:
        ts = MagicMock()
        ts.isoformat.return_value = "2026-05-01T00:00:00"
        rows = [{
            "label_id": 1, "label_name": "A", "label_color": "blue",
            "action": "assigned", "via": "manual",
            "actor_name": "", "actor_id": "", "at": ts,
        }]
        mock_audit.objects.filter.return_value.order_by.return_value.values.return_value.__getitem__.return_value = rows

        result = label_service.list_patient_history("p1")
        assert result[0]["actor_name"] == "Unknown"

    @patch("patient_tags.services.label_service.PatientLabelAudit")
    def test_at_empty_when_missing(self, mock_audit: MagicMock) -> None:
        rows = [{
            "label_id": 1, "label_name": "A", "label_color": "blue",
            "action": "assigned", "via": "manual",
            "actor_name": "x", "actor_id": "", "at": None,
        }]
        mock_audit.objects.filter.return_value.order_by.return_value.values.return_value.__getitem__.return_value = rows

        result = label_service.list_patient_history("p1")
        assert result[0]["at"] == ""


class TestListRulesForLabel:
    @patch("patient_tags.services.label_service.LabelRule")
    def test_empty(self, mock_rule: MagicMock) -> None:
        mock_rule.objects.filter.return_value = []
        assert label_service.list_rules_for_label(1) == []

    @patch("patient_tags.services.label_service.Label")
    @patch("patient_tags.services.label_service.LabelRule")
    def test_with_rules_resolves_target_names(
        self, mock_rule: MagicMock, mock_label: MagicMock
    ) -> None:
        rule = MagicMock(dbid=1, trigger_label_id=10, action="auto_assign", target_label_id=20)
        mock_rule.objects.filter.return_value = [rule]
        mock_label.objects.filter.return_value.values_list.return_value = [(20, "VIP")]

        result = label_service.list_rules_for_label(10)

        assert result[0]["target_label_name"] == "VIP"


class TestCreateRule:
    @patch("patient_tags.services.label_service.LabelRule")
    @patch("patient_tags.services.label_service.Label")
    def test_happy_path(self, mock_label: MagicMock, mock_rule: MagicMock) -> None:
        mock_label.objects.filter.return_value.exists.return_value = True
        mock_rule.objects.filter.return_value.exists.side_effect = [False, False]
        created = MagicMock(dbid=1, trigger_label_id=10, action="auto_assign", target_label_id=20)
        mock_rule.objects.create.return_value = created
        mock_label.objects.filter.return_value.values_list.return_value.first.return_value = "VIP"

        result = label_service.create_rule(trigger_label_id=10, action="auto_assign", target_label_id=20)

        assert result["target_label_name"] == "VIP"
        mock_rule.objects.create.assert_called_once()

    def test_invalid_action_raises(self) -> None:
        with pytest.raises(ValueError, match="action must be one of"):
            label_service.create_rule(trigger_label_id=1, action="x", target_label_id=2)

    def test_self_reference_raises(self) -> None:
        with pytest.raises(ValueError, match="must be different"):
            label_service.create_rule(trigger_label_id=5, action="auto_assign", target_label_id=5)

    @patch("patient_tags.services.label_service.Label")
    def test_unknown_trigger_raises(self, mock_label: MagicMock) -> None:
        mock_label.objects.filter.return_value.exists.return_value = False
        with pytest.raises(ValueError, match="Trigger label does not exist"):
            label_service.create_rule(trigger_label_id=1, action="auto_assign", target_label_id=2)

    @patch("patient_tags.services.label_service.Label")
    def test_unknown_target_raises(self, mock_label: MagicMock) -> None:
        # First exists() (trigger) → True, second (target) → False.
        mock_label.objects.filter.return_value.exists.side_effect = [True, False]
        with pytest.raises(ValueError, match="Target label does not exist"):
            label_service.create_rule(trigger_label_id=1, action="auto_assign", target_label_id=2)

    @patch("patient_tags.services.label_service.LabelRule")
    @patch("patient_tags.services.label_service.Label")
    def test_duplicate_rule_raises(self, mock_label: MagicMock, mock_rule: MagicMock) -> None:
        mock_label.objects.filter.return_value.exists.return_value = True
        mock_rule.objects.filter.return_value.exists.return_value = True
        with pytest.raises(ValueError, match="already exists"):
            label_service.create_rule(trigger_label_id=1, action="auto_assign", target_label_id=2)

    @patch("patient_tags.services.label_service.LabelRule")
    @patch("patient_tags.services.label_service.Label")
    def test_opposing_rule_blocks_with_auto_remove_message(
        self, mock_label: MagicMock, mock_rule: MagicMock
    ) -> None:
        mock_label.objects.filter.return_value.exists.return_value = True
        # Duplicate check False, opposing check True.
        mock_rule.objects.filter.return_value.exists.side_effect = [False, True]

        with pytest.raises(ValueError, match="Auto-remove"):
            label_service.create_rule(trigger_label_id=1, action="auto_assign", target_label_id=2)


class TestDeleteRule:
    @patch("patient_tags.services.label_service.LabelRule")
    def test_filters_by_dbid_and_deletes(self, mock_rule: MagicMock) -> None:
        label_service.delete_rule(7)
        mock_rule.objects.filter.assert_called_once_with(dbid=7)
        mock_rule.objects.filter.return_value.delete.assert_called_once()


class TestValidationHelpers:
    def test_require_nonempty_blank_raises(self) -> None:
        with pytest.raises(ValueError, match="x is required"):
            label_service._require_nonempty("   ", "x")

    def test_require_nonempty_passes(self) -> None:
        label_service._require_nonempty("ok", "x")  # no raise

    def test_require_max_length_over_raises(self) -> None:
        with pytest.raises(ValueError, match="exceeds 5 characters"):
            label_service._require_max_length("123456", 5, "f")

    def test_require_max_length_under_passes(self) -> None:
        label_service._require_max_length("ok", 5, "f")
        label_service._require_max_length("", 5, "f")

    def test_require_in_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="must be one of"):
            label_service._require_in("z", ["a", "b"], "f")

    def test_require_placements_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            label_service._require_placements([])

    def test_require_placements_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="not in"):
            label_service._require_placements(["BAD"])


class TestRequireSafeHref:
    """`_require_safe_href` must reject schemes that execute code when
    rendered as an anchor href in the Manage Banners UI.
    """

    def test_empty_allowed(self) -> None:
        label_service._require_safe_href("")
        label_service._require_safe_href("   ")

    def test_http_allowed(self) -> None:
        label_service._require_safe_href("http://example.com/path")

    def test_https_allowed(self) -> None:
        label_service._require_safe_href("https://example.com")

    def test_relative_path_allowed(self) -> None:
        label_service._require_safe_href("/internal/page")
        label_service._require_safe_href("./relative")

    def test_javascript_rejected(self) -> None:
        with pytest.raises(ValueError, match="href must be empty"):
            label_service._require_safe_href("javascript:alert(1)")

    def test_javascript_case_insensitive(self) -> None:
        with pytest.raises(ValueError):
            label_service._require_safe_href("JaVaScRiPt:alert(1)")

    def test_data_uri_rejected(self) -> None:
        with pytest.raises(ValueError):
            label_service._require_safe_href("data:text/html,<script>")

    def test_vbscript_rejected(self) -> None:
        with pytest.raises(ValueError):
            label_service._require_safe_href("vbscript:msgbox(1)")

    def test_file_rejected(self) -> None:
        with pytest.raises(ValueError):
            label_service._require_safe_href("file:///etc/passwd")


class TestCreateBannerGroupHrefValidation:
    @patch("patient_tags.services.label_service.BannerGroup")
    def test_javascript_href_blocked(self, mock_group: MagicMock) -> None:
        with pytest.raises(ValueError, match="href"):
            label_service.create_banner_group(name="X", href="javascript:alert(1)")


class TestUpdateBannerGroupHrefValidation:
    @patch("patient_tags.services.label_service.BannerGroup")
    def test_javascript_href_blocked(self, mock_group: MagicMock) -> None:
        existing = _make_group(dbid=1, name="N", placements=[])
        mock_group.objects.get.return_value = existing
        with pytest.raises(ValueError, match="href"):
            label_service.update_banner_group(1, href="javascript:alert(1)")


class TestAddPatientAssignmentsDedup:
    """Duplicate label IDs in input must not crash with IntegrityError."""

    @patch("patient_tags.services.label_service._apply_rules_for_triggers")
    @patch("patient_tags.services.label_service._write_assignment_audits")
    @patch("patient_tags.services.label_service.Label")
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service.PatientProxy")
    def test_duplicate_input_only_creates_once(
        self,
        mock_proxy: MagicMock,
        mock_pl: MagicMock,
        mock_label: MagicMock,
        mock_audit: MagicMock,
        mock_rules: MagicMock,
    ) -> None:
        mock_proxy.objects.get.return_value = MagicMock()
        mock_pl.objects.filter.return_value.values_list.return_value = []
        mock_label.objects.filter.return_value.values_list.return_value = [1]

        # Caller passes [1, 1] — must dedupe at entry, not crash on the
        # second create() with a unique-constraint violation.
        result = label_service.add_patient_assignments("p1", [1, 1])

        assert result == {"added": [1], "already_present": []}
        # PatientLabel.objects.create should be called exactly once.
        assert mock_pl.objects.create.call_count == 1


class TestRemovePatientAssignmentsDedup:
    @patch("patient_tags.services.label_service._write_assignment_audits")
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service.PatientProxy")
    def test_duplicate_input_audits_once(
        self,
        mock_proxy: MagicMock,
        mock_pl: MagicMock,
        mock_audit: MagicMock,
    ) -> None:
        mock_proxy.objects.get.return_value = MagicMock()
        mock_pl.objects.filter.return_value.values_list.return_value = [1]

        result = label_service.remove_patient_assignments("p1", [1, 1])

        # Removed list should have one entry, not two; audit only one row.
        assert result == {"removed": [1], "not_present": []}


class TestDeleteBannerGroupCleanup:
    """Deleting a BannerGroup must emit RemoveBannerAlert for affected
    patients so stale clinical banners don't linger after group deletion.
    """

    @patch("patient_tags.services.label_service.BannerGroup")
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service.Label")
    def test_emits_remove_for_each_affected_patient(
        self, mock_label: MagicMock, mock_pl: MagicMock, mock_group: MagicMock
    ) -> None:
        # Group 7 has labels 10 and 11; patients UUID-A and UUID-B have those
        # labels assigned. Both must get a RemoveBannerAlert(key="…group-7").
        mock_label.objects.filter.return_value.values_list.return_value = [10, 11]
        mock_pl.objects.filter.return_value.values_list.return_value.distinct.return_value = [
            "uuid-a", "uuid-b",
        ]

        effects = label_service.delete_banner_group(7)

        assert len(effects) == 2

    @patch("patient_tags.services.label_service.BannerGroup")
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service.Label")
    def test_no_labels_returns_no_effects(
        self, mock_label: MagicMock, mock_pl: MagicMock, mock_group: MagicMock
    ) -> None:
        # Group has no labels → no patients → no effects, but still delete.
        mock_label.objects.filter.return_value.values_list.return_value = []

        effects = label_service.delete_banner_group(7)

        assert effects == []

    @patch("patient_tags.services.label_service.BannerGroup")
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service.Label")
    def test_no_assigned_patients_returns_no_effects(
        self, mock_label: MagicMock, mock_pl: MagicMock, mock_group: MagicMock
    ) -> None:
        mock_label.objects.filter.return_value.values_list.return_value = [10]
        mock_pl.objects.filter.return_value.values_list.return_value.distinct.return_value = []

        effects = label_service.delete_banner_group(7)

        assert effects == []


class TestUpdateLabelBannerReconcile:
    """update_label must trigger compute_banner_effects when name or
    banner_group_id changes — those are the fields that affect the
    rendered banner narrative.
    """

    @patch("patient_tags.services.label_service._compute_banner_effects_for")
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service._resolve_group_name", return_value=None)
    @patch("patient_tags.services.label_service.Label")
    def test_name_change_triggers_reconcile(
        self, mock_label: MagicMock, _mock_resolve: MagicMock,
        mock_pl: MagicMock, mock_reconcile: MagicMock,
    ) -> None:
        existing = _make_label(dbid=1, name="Old")
        mock_label.objects.get.return_value = existing
        mock_label.objects.filter.return_value.exclude.return_value.exists.return_value = False
        mock_pl.objects.filter.return_value.values_list.return_value.distinct.return_value = ["uuid-a"]
        sentinel = MagicMock()
        mock_reconcile.return_value = [sentinel]

        _, effects = label_service.update_label(1, name="New")

        mock_reconcile.assert_called_once_with(["uuid-a"])
        assert effects == [sentinel]

    @patch("patient_tags.services.label_service._compute_banner_effects_for")
    @patch("patient_tags.services.label_service.PatientLabel")
    @patch("patient_tags.services.label_service._resolve_group_name", return_value=None)
    @patch("patient_tags.services.label_service.Label")
    def test_banner_group_change_triggers_reconcile(
        self, mock_label: MagicMock, _mock_resolve: MagicMock,
        mock_pl: MagicMock, mock_reconcile: MagicMock,
    ) -> None:
        existing = _make_label(dbid=1, name="X", banner_group_id=5)
        mock_label.objects.get.return_value = existing
        mock_pl.objects.filter.return_value.values_list.return_value.distinct.return_value = ["uuid-a"]
        mock_reconcile.return_value = []

        _, effects = label_service.update_label(1, banner_group_id=7)

        mock_reconcile.assert_called_once_with(["uuid-a"])

    @patch("patient_tags.services.label_service._compute_banner_effects_for")
    @patch("patient_tags.services.label_service._resolve_group_name", return_value=None)
    @patch("patient_tags.services.label_service.Label")
    def test_color_only_change_skips_reconcile(
        self, mock_label: MagicMock, _mock_resolve: MagicMock,
        mock_reconcile: MagicMock,
    ) -> None:
        # Color doesn't affect banner narrative — no reconcile fired.
        existing = _make_label(dbid=1, name="X", color="blue")
        mock_label.objects.get.return_value = existing

        _, effects = label_service.update_label(1, color="red")

        mock_reconcile.assert_not_called()
        assert effects == []
