"""Wait-time and fill figures."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

from scheduling_waitlist.services.metrics import format_summary, median, summarize

TODAY = date(2026, 8, 3)


def entry(status="waiting", days_ago=10):
    record = MagicMock()
    record.status = status
    record.created_at = datetime(2026, 8, 3, tzinfo=timezone.utc) - timedelta(days=days_ago)
    return record


class TestMedian:
    def test_an_empty_list_is_zero(self):
        assert median([]) == 0.0

    def test_an_odd_count_takes_the_middle_value(self):
        assert median([1, 9, 5]) == 5.0

    def test_an_even_count_averages_the_two_middle_values(self):
        assert median([1, 2, 8, 10]) == 5.0

    def test_input_order_does_not_matter(self):
        assert median([10, 1, 8, 2]) == 5.0


class TestSummarize:
    def test_an_empty_list_reports_zeroes_rather_than_failing(self):
        summary = summarize([], today=TODAY)

        assert summary["open_entries"] == 0
        assert summary["average_wait_days"] == 0.0
        assert summary["fill_rate"] == 0.0

    def test_entries_are_counted_by_status(self):
        summary = summarize(
            [entry(), entry(status="offered"), entry(status="scheduled")], today=TODAY
        )

        assert summary["counts"]["waiting"] == 1
        assert summary["counts"]["offered"] == 1
        assert summary["counts"]["scheduled"] == 1

    def test_open_entries_include_both_waiting_and_offered(self):
        summary = summarize([entry(), entry(status="offered")], today=TODAY)

        assert summary["open_entries"] == 2

    def test_only_open_entries_count_toward_the_wait_figures(self):
        # A closed entry's age says nothing about how long people are waiting
        # now.
        summary = summarize(
            [entry(days_ago=10), entry(status="scheduled", days_ago=500)], today=TODAY
        )

        assert summary["average_wait_days"] == 10.0
        assert summary["longest_wait_days"] == 10

    def test_the_longest_wait_is_reported(self):
        summary = summarize([entry(days_ago=5), entry(days_ago=40)], today=TODAY)

        assert summary["longest_wait_days"] == 40

    def test_fill_rate_is_bookings_over_concluded_entries(self):
        summary = summarize(
            [entry(status="scheduled"), entry(status="removed")], today=TODAY
        )

        assert summary["fill_rate"] == 0.5

    def test_entries_still_waiting_are_not_counted_as_failures(self):
        # Otherwise a healthy list with a long tail reads as broken.
        summary = summarize(
            [entry(status="scheduled"), entry(), entry(), entry()], today=TODAY
        )

        assert summary["fill_rate"] == 1.0

    def test_no_concluded_entries_gives_a_zero_rate_rather_than_dividing_by_zero(self):
        assert summarize([entry(), entry()], today=TODAY)["fill_rate"] == 0.0

    def test_an_unrecognised_status_is_ignored_rather_than_crashing(self):
        summary = summarize([entry(status="parked"), entry()], today=TODAY)

        assert summary["open_entries"] == 1


class TestFormatSummary:
    def test_the_line_names_the_key_figures(self):
        line = format_summary(summarize([entry(), entry(status="scheduled")], today=TODAY))

        assert "scheduling_waitlist metrics" in line
        assert "average wait" in line
        assert "fill rate" in line

    def test_the_fill_rate_reads_as_a_percentage(self):
        line = format_summary(
            summarize([entry(status="scheduled"), entry(status="removed")], today=TODAY)
        )

        assert "50%" in line
