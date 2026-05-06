"""Tests for the LastReviewedSectionContent handler and its helpers."""

import json
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from canvas_sdk.effects.base import EffectType

from last_reviewed.handlers import section_content
from last_reviewed.handlers.section_config import SECTION_KEY
from last_reviewed.handlers.section_content import (
    _SECTIONS,
    LastReviewedSectionContent,
    _committer_name,
    _format_row,
)
from tests.conftest import make_review_command, make_staff_user


# ─── handler/config alignment ─────────────────────────────────────────────────


def test_handler_section_key_matches_config() -> None:
    """If the keys diverge, the GET_CUSTOM_SECTION event won't route to us."""
    assert LastReviewedSectionContent.SECTION_KEY == SECTION_KEY


def test_section_values_match_chart_section_review_command() -> None:
    """The value strings here must match what Canvas writes into Command.data."""
    from canvas_sdk.commands.commands.chart_section_review import (
        ChartSectionReviewCommand,
    )

    expected = {member.value for member in ChartSectionReviewCommand.Sections}
    actual = {value for _, value in _SECTIONS}
    assert actual == expected


# ─── _committer_name ──────────────────────────────────────────────────────────


class TestCommitterName:
    def test_returns_full_name_for_staff(self) -> None:
        user = make_staff_user(first_name="Alice", last_name="Adams")
        assert _committer_name(user) == "Alice Adams"

    def test_returns_none_for_none_user(self) -> None:
        assert _committer_name(None) is None

    def test_returns_none_for_non_staff_user(self) -> None:
        user = make_staff_user(is_staff=False)
        assert _committer_name(user) is None

    def test_returns_none_when_staff_names_blank(self) -> None:
        user = make_staff_user(first_name="", last_name="")
        assert _committer_name(user) is None

    def test_returns_none_if_staff_lookup_raises(self) -> None:
        """A user marked is_staff but missing the related Staff row should not crash."""
        user = make_staff_user(raises_on_staff_access=True)
        assert _committer_name(user) is None

    def test_returns_none_when_staff_attribute_is_none(self) -> None:
        """SDK access path that returns None instead of raising must also be handled."""
        from types import SimpleNamespace

        user = SimpleNamespace(is_staff=True, staff=None)
        assert _committer_name(user) is None


# ─── _format_row ──────────────────────────────────────────────────────────────


class TestFormatRow:
    def test_unreviewed_row(self) -> None:
        assert _format_row("Conditions", None) == {
            "label": "Conditions",
            "reviewed": False,
        }

    def test_reviewed_row_includes_relative_absolute_and_reviewer(
        self, utc_now
    ) -> None:
        cmd = make_review_command(
            section="conditions",
            created=utc_now - timedelta(hours=2),
            committer=make_staff_user(first_name="Jane", last_name="Smith"),
        )
        row = _format_row("Conditions", cmd)
        assert row["label"] == "Conditions"
        assert row["reviewed"] is True
        assert row["reviewer"] == "Jane Smith"
        # arrow.humanize() is locale-/clock-dependent, so just sanity-check shape.
        assert isinstance(row["relative"], str) and row["relative"]
        assert row["absolute"].startswith("2026-05-01")

    def test_reviewed_row_with_unknown_committer_has_null_reviewer(
        self, utc_now
    ) -> None:
        cmd = make_review_command("medications", created=utc_now, committer=None)
        row = _format_row("Medications", cmd)
        assert row["reviewed"] is True
        assert row["reviewer"] is None


# ─── handler.handle() ─────────────────────────────────────────────────────────


def _make_handler(event_factory, patient_id: str = "patient-1") -> LastReviewedSectionContent:
    return LastReviewedSectionContent(event=event_factory(patient_id=patient_id))


class TestHandle:
    @patch("last_reviewed.handlers.section_content.render_to_string")
    @patch("last_reviewed.handlers.section_content.Command")
    def test_no_reviews_renders_all_six_as_never_reviewed(
        self, mock_command, mock_render, mock_event, mock_command_queryset
    ) -> None:
        mock_command_queryset(mock_command, commands=[])
        mock_render.return_value = "<div/>"

        handler = _make_handler(mock_event)
        effects = handler.handle()

        assert len(effects) == 1
        ctx = mock_render.call_args.args[1]
        assert {row["label"] for row in ctx["rows"]} == {
            "Conditions",
            "Medications",
            "Allergies",
            "Immunizations",
            "Surgical History",
            "Family History",
        }
        assert all(row["reviewed"] is False for row in ctx["rows"])

    @patch("last_reviewed.handlers.section_content.render_to_string")
    @patch("last_reviewed.handlers.section_content.Command")
    def test_picks_latest_command_per_section(
        self,
        mock_command,
        mock_render,
        mock_event,
        mock_command_queryset,
        utc_now,
    ) -> None:
        """Commands arrive newest-first; the first one per section wins."""
        latest = make_review_command(
            "conditions",
            created=utc_now,
            committer=make_staff_user("Latest", "Reviewer"),
        )
        older = make_review_command(
            "conditions",
            created=utc_now - timedelta(days=3),
            committer=make_staff_user("Earlier", "Reviewer"),
        )
        mock_command_queryset(mock_command, commands=[latest, older])
        mock_render.return_value = "<div/>"

        handler = _make_handler(mock_event)
        handler.handle()

        ctx = mock_render.call_args.args[1]
        conditions_row = next(r for r in ctx["rows"] if r["label"] == "Conditions")
        assert conditions_row["reviewer"] == "Latest Reviewer"

    @patch("last_reviewed.handlers.section_content.render_to_string")
    @patch("last_reviewed.handlers.section_content.Command")
    def test_unknown_section_values_are_ignored(
        self, mock_command, mock_render, mock_event, mock_command_queryset, utc_now
    ) -> None:
        unknown = make_review_command("not_a_real_section", created=utc_now)
        mock_command_queryset(mock_command, commands=[unknown])
        mock_render.return_value = "<div/>"

        handler = _make_handler(mock_event)
        handler.handle()

        ctx = mock_render.call_args.args[1]
        assert all(row["reviewed"] is False for row in ctx["rows"])

    @patch("last_reviewed.handlers.section_content.render_to_string")
    @patch("last_reviewed.handlers.section_content.Command")
    def test_query_filters_by_patient_and_committed_state(
        self, mock_command, mock_render, mock_event, mock_command_queryset
    ) -> None:
        mock_command_queryset(mock_command, commands=[])
        mock_render.return_value = "<div/>"

        handler = _make_handler(mock_event, patient_id="patient-42")
        handler.handle()

        mock_command.objects.filter.assert_called_once_with(
            patient__id="patient-42",
            schema_key="chartSectionReview",
            state="committed",
            entered_in_error__isnull=True,
        )

    @patch("last_reviewed.handlers.section_content.render_to_string")
    @patch("last_reviewed.handlers.section_content.Command")
    def test_breaks_early_after_finding_all_sections(
        self, mock_command, mock_render, mock_event, utc_now
    ) -> None:
        """Once a review has been found for every covered section, the handler
        should stop iterating the queryset instead of scanning every remaining
        chart-section review on the patient."""
        six = [
            make_review_command(value, created=utc_now - timedelta(seconds=i))
            for i, (_, value) in enumerate(_SECTIONS)
        ]
        poison = make_review_command(
            "conditions", created=utc_now - timedelta(days=1)
        )
        iter_obj = iter(six + [poison])

        # Build the queryset chain by hand so we can keep a reference to the
        # iterator and assert that it was not exhausted.
        ordered = Mock()
        ordered.iterator.return_value = iter_obj
        select_related_result = Mock()
        select_related_result.order_by.return_value = ordered
        exclude_result = Mock()
        exclude_result.select_related.return_value = select_related_result
        filter_result = Mock()
        filter_result.exclude.return_value = exclude_result
        mock_command.objects.filter.return_value = filter_result
        mock_render.return_value = "<div/>"

        _make_handler(mock_event).handle()

        # If the loop broke after the 6th command, the poison still sits at
        # the head of the iterator.
        assert next(iter_obj, None) is poison

    @patch("last_reviewed.handlers.section_content.render_to_string")
    @patch("last_reviewed.handlers.section_content.Command")
    def test_excludes_reviews_whose_parent_note_is_deleted(
        self, mock_command, mock_render, mock_event, mock_command_queryset
    ) -> None:
        """A 'deleted' chart-section review is realized by Canvas as the
        parent note transitioning to NoteStates.DELETED, not by mutating the
        Command row. The handler must exclude these so the section rolls back
        to the prior valid review."""
        from canvas_sdk.v1.data.note import NoteStates

        chain = mock_command_queryset(mock_command, commands=[])
        mock_render.return_value = "<div/>"

        handler = _make_handler(mock_event)
        handler.handle()

        chain.filter_result.exclude.assert_called_once_with(
            note__current_state__state=NoteStates.DELETED
        )

    @patch("last_reviewed.handlers.section_content.render_to_string")
    @patch("last_reviewed.handlers.section_content.Command")
    def test_emits_custom_section_effect_with_html_and_icon(
        self, mock_command, mock_render, mock_event, mock_command_queryset
    ) -> None:
        mock_command_queryset(mock_command, commands=[])
        mock_render.return_value = "<section>hi</section>"

        handler = _make_handler(mock_event)
        [effect] = handler.handle()

        assert effect.type == EffectType.PATIENT_CHART_SUMMARY__CUSTOM_SECTION
        data = json.loads(effect.payload)["data"]
        assert data["content"] == "<section>hi</section>"
        assert data["url"] is None
        assert data["icon_url"].startswith("data:image/svg+xml;base64,")
        assert data["icon"] is None

    @patch("last_reviewed.handlers.section_content.render_to_string")
    @patch("last_reviewed.handlers.section_content.Command")
    def test_template_path_is_static_section_html(
        self, mock_command, mock_render, mock_event, mock_command_queryset
    ) -> None:
        mock_command_queryset(mock_command, commands=[])
        mock_render.return_value = ""

        handler = _make_handler(mock_event)
        handler.handle()

        assert mock_render.call_args.args[0] == "static/section.html"


# ─── icon ─────────────────────────────────────────────────────────────────────


def test_icon_url_decodes_to_valid_svg() -> None:
    """Sanity: the embedded icon round-trips and looks like an SVG."""
    import base64

    prefix = "data:image/svg+xml;base64,"
    assert section_content._ICON_URL.startswith(prefix)
    decoded = base64.b64decode(section_content._ICON_URL[len(prefix) :])
    assert decoded.startswith(b"<svg")
    assert decoded.rstrip().endswith(b"</svg>")
