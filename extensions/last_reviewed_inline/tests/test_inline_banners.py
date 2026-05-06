"""Tests for the inline 'Last reviewed' banner handlers."""

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from canvas_sdk.effects.base import EffectType
from canvas_sdk.events import EventType
from canvas_sdk.v1.data.note import NoteStates

from last_reviewed_inline.handlers import inline_banners
from last_reviewed_inline.handlers.inline_banners import (
    _BANNER_PRIORITY,
    ConditionsLastReviewed,
    MedicationsLastReviewed,
    _banner_text,
    _committer_name,
    _latest_review,
)
from tests.conftest import make_review_command, make_staff_user


# ─── handler wiring ───────────────────────────────────────────────────────────


def test_conditions_handler_responds_to_conditions_event() -> None:
    assert ConditionsLastReviewed.RESPONDS_TO == EventType.Name(
        EventType.PATIENT_CHART__CONDITIONS
    )
    assert ConditionsLastReviewed.SECTION_VALUE == "conditions"


def test_medications_handler_responds_to_medications_event() -> None:
    assert MedicationsLastReviewed.RESPONDS_TO == EventType.Name(
        EventType.PATIENT_CHART__MEDICATIONS
    )
    assert MedicationsLastReviewed.SECTION_VALUE == "medications"


# ─── _committer_name ──────────────────────────────────────────────────────────


class TestCommitterName:
    def test_returns_full_name_for_staff(self) -> None:
        assert _committer_name(make_staff_user("Alice", "Adams")) == "Alice Adams"

    def test_returns_none_for_none_user(self) -> None:
        assert _committer_name(None) is None

    def test_returns_none_for_non_staff_user(self) -> None:
        assert _committer_name(make_staff_user(is_staff=False)) is None

    def test_returns_none_when_staff_names_blank(self) -> None:
        assert _committer_name(make_staff_user(first_name="", last_name="")) is None

    def test_returns_none_if_staff_lookup_raises(self) -> None:
        assert _committer_name(make_staff_user(raises_on_staff_access=True)) is None

    def test_returns_none_when_staff_attribute_is_none(self) -> None:
        user = SimpleNamespace(is_staff=True, staff=None)
        assert _committer_name(user) is None


# ─── _banner_text ─────────────────────────────────────────────────────────────


class TestBannerText:
    def test_never_reviewed_when_no_command(self) -> None:
        assert _banner_text(None) == "Never reviewed"

    def test_includes_relative_time_and_reviewer(self, utc_now) -> None:
        cmd = make_review_command(
            "conditions",
            created=utc_now - timedelta(hours=2),
            committer=make_staff_user("Jane", "Smith"),
        )
        text = _banner_text(cmd)
        assert text.startswith("Last reviewed ")
        assert text.endswith(" by Jane Smith")

    def test_drops_by_name_when_reviewer_unresolvable(self, utc_now) -> None:
        cmd = make_review_command("conditions", created=utc_now, committer=None)
        text = _banner_text(cmd)
        assert text.startswith("Last reviewed ")
        assert " by " not in text


# ─── _latest_review ───────────────────────────────────────────────────────────


class TestLatestReview:
    @patch("last_reviewed_inline.handlers.inline_banners.Command")
    def test_filters_for_committed_non_errored_review_in_section(
        self, mock_command, mock_command_chain
    ) -> None:
        mock_command_chain(mock_command, command=None)

        _latest_review("patient-42", "conditions")

        mock_command.objects.filter.assert_called_once_with(
            patient__id="patient-42",
            schema_key="chartSectionReview",
            state="committed",
            entered_in_error__isnull=True,
            data__section="conditions",
        )

    @patch("last_reviewed_inline.handlers.inline_banners.Command")
    def test_excludes_reviews_whose_parent_note_is_deleted(
        self, mock_command, mock_command_chain
    ) -> None:
        chain = mock_command_chain(mock_command, command=None)

        _latest_review("patient-1", "medications")

        chain.filter_result.exclude.assert_called_once_with(
            note__current_state__state=NoteStates.DELETED
        )

    @patch("last_reviewed_inline.handlers.inline_banners.Command")
    def test_select_related_committer_and_order_by_created_desc(
        self, mock_command, mock_command_chain
    ) -> None:
        chain = mock_command_chain(mock_command, command=None)

        _latest_review("patient-1", "conditions")

        chain.exclude_result.select_related.assert_called_once_with("committer")
        chain.select_related_result.order_by.assert_called_once_with("-created")

    @patch("last_reviewed_inline.handlers.inline_banners.Command")
    def test_returns_first_command_from_query(
        self, mock_command, mock_command_chain, utc_now
    ) -> None:
        cmd = make_review_command("conditions", created=utc_now)
        mock_command_chain(mock_command, command=cmd)

        assert _latest_review("patient-1", "conditions") is cmd


# ─── handler.compute() ────────────────────────────────────────────────────────


class TestCompute:
    def _payload(self, effect):
        return json.loads(effect.payload)

    @patch("last_reviewed_inline.handlers.inline_banners.Command")
    def test_emits_single_chart_group_effect(
        self, mock_command, mock_command_chain, mock_event
    ) -> None:
        mock_command_chain(mock_command, command=None)

        effects = ConditionsLastReviewed(event=mock_event()).compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.PATIENT_CHART__GROUP_ITEMS

    @patch("last_reviewed_inline.handlers.inline_banners.Command")
    def test_group_uses_pinned_priority_and_empty_items(
        self, mock_command, mock_command_chain, mock_event
    ) -> None:
        mock_command_chain(mock_command, command=None)

        [effect] = ConditionsLastReviewed(event=mock_event()).compute()

        groups = self._payload(effect)["data"]["items"]
        assert len(groups) == 1
        group = groups[0]
        assert group["priority"] == _BANNER_PRIORITY
        assert group["items"] == []

    @patch("last_reviewed_inline.handlers.inline_banners.Command")
    def test_group_name_is_never_reviewed_when_no_review(
        self, mock_command, mock_command_chain, mock_event
    ) -> None:
        mock_command_chain(mock_command, command=None)

        [effect] = ConditionsLastReviewed(event=mock_event()).compute()

        [group] = self._payload(effect)["data"]["items"]
        assert group["name"] == "Never reviewed"

    @patch("last_reviewed_inline.handlers.inline_banners.Command")
    def test_group_name_includes_relative_time_and_reviewer(
        self, mock_command, mock_command_chain, mock_event, utc_now
    ) -> None:
        cmd = make_review_command(
            "medications",
            created=utc_now - timedelta(hours=3),
            committer=make_staff_user("Bob", "Jones"),
        )
        mock_command_chain(mock_command, command=cmd)

        [effect] = MedicationsLastReviewed(event=mock_event()).compute()

        [group] = self._payload(effect)["data"]["items"]
        assert group["name"].startswith("Last reviewed ")
        assert group["name"].endswith(" by Bob Jones")

    @patch("last_reviewed_inline.handlers.inline_banners.Command")
    def test_passes_patient_id_and_section_value_to_query(
        self, mock_command, mock_command_chain, mock_event
    ) -> None:
        mock_command_chain(mock_command, command=None)

        MedicationsLastReviewed(event=mock_event(patient_id="patient-99")).compute()

        mock_command.objects.filter.assert_called_once_with(
            patient__id="patient-99",
            schema_key="chartSectionReview",
            state="committed",
            entered_in_error__isnull=True,
            data__section="medications",
        )


# ─── module constants ─────────────────────────────────────────────────────────


def test_banner_priority_is_high_enough_to_outrank_known_grouping_plugins() -> None:
    """high-risk-medications uses priority=1000, so we need to be clearly above it."""
    assert inline_banners._BANNER_PRIORITY > 1000
