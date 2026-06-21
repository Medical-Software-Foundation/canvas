"""Tests for the admin CSV-email parser used by the bulk-import fallback."""

from gcal_sync.routes.google_admin import parse_provider_emails


def test_parses_first_column_emails_and_skips_header():
    csv = "Email,Contact.FirstName,Contact.LastName\naaustin@example.com,Alexis,Austin\ncwong@example.com,Carmen,Wong\n"
    assert parse_provider_emails(csv) == ["aaustin@example.com", "cwong@example.com"]


def test_ignores_blank_and_non_email_rows():
    csv = "Email\n\n   \nnot-an-email,foo\nvalid@example.com,Jane,Doe\n"
    assert parse_provider_emails(csv) == ["valid@example.com"]


def test_handles_no_header():
    csv = "a@example.com,A,B\nb@example.com,C,D"
    assert parse_provider_emails(csv) == ["a@example.com", "b@example.com"]


def test_empty_input_returns_empty():
    assert parse_provider_emails("") == []
