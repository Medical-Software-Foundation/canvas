"""The chart banner, one per running program, and deliberately not a link.

The no href assertion below is the one most worth having. The platform renders a banner
carrying an href as a single anchor hardcoded to open a new browser tab, which is why the
link was rejected, and nothing in the code says so loudly enough that a later reader would
not add one back. This test is what fails when they do.
"""

import datetime
import json

import pytest

NARRATIVE_LIMIT = 90


def payload(effect):
    """The whole payload an effect carries, keys and data together."""
    return json.loads(effect.payload)


@pytest.fixture
def enrolment_with_key(enrolment):
    """The enrolment fixture, carrying the banner key the API mints at creation."""
    from medication_followup_protocol.services.banner import new_banner_key

    enrolment.banner_key = new_banner_key()
    enrolment.save()
    return enrolment


def test_the_banner_is_text_only_and_carries_no_link(enrolment_with_key):
    """Covers scenario: AC24, the chart banner is text only, added on enrolment and removed on stop without touching another enrolment's banner. Covers criterion: AC24.

    A banner with an href is rendered by the platform as one anchor hardcoded to open a
    new browser tab, so the design deliberately carries none. A provider reads the banner
    and reaches the detail through the all programs control instead.
    """
    from medication_followup_protocol.services.banner import apply_banner

    data = payload(apply_banner(enrolment_with_key))["data"]

    assert data["href"] is None


def test_the_banner_is_placed_on_the_chart(enrolment_with_key):
    """Covers criterion: AC24."""
    from medication_followup_protocol.services.banner import apply_banner

    data = payload(apply_banner(enrolment_with_key))["data"]

    assert data["placement"] == ["chart"]


def test_the_banner_is_keyed_on_its_own_enrolment(enrolment_with_key):
    """Covers criterion: AC24.

    The key is what makes one program stopping remove one banner. Keyed on the patient
    alone, stopping either program would clear both.
    """
    from medication_followup_protocol.services.banner import apply_banner

    assert payload(apply_banner(enrolment_with_key))["key"] == enrolment_with_key.banner_key


def test_stopping_removes_that_enrolment_key_and_no_other(
    enrolment_with_key, medication_class, patient, staff
):
    """Covers scenario: AC24, the chart banner is text only, added on enrolment and removed on stop without touching another enrolment's banner. Covers criterion: AC24.

    Two programs on one patient, and stopping the first removes a key the second does not
    share. This is the half of the criterion easiest to get wrong, because keying on the
    patient looks correct until a patient is on two programs at once.
    """
    from medication_followup_protocol.models import Enrollment
    from medication_followup_protocol.services.banner import (
        apply_banner,
        new_banner_key,
        remove_banner,
    )

    second = Enrollment.objects.create(
        patient_id=patient.dbid,
        medication_class=medication_class,
        medication_label="warfarin",
        sender_staff_id=staff.dbid,
        prescriber_staff_id=staff.dbid,
        start_date=datetime.date(2026, 8, 20),
        recheck_note_type_id=medication_class.recheck_note_type_id,
        banner_key=new_banner_key(),
    )

    removed = payload(remove_banner(enrolment_with_key))
    still_standing = payload(apply_banner(second))

    assert removed["key"] == enrolment_with_key.banner_key
    assert removed["key"] != still_standing["key"]


def test_two_enrolments_never_share_a_key(enrolment_with_key):
    """Covers criterion: AC24."""
    from medication_followup_protocol.services.banner import new_banner_key

    assert new_banner_key() != new_banner_key()


def test_the_narrative_names_the_program_and_its_next_due_date(enrolment_with_key, add_step):
    """Covers criterion: AC24.

    The date a provider acts on is the next step still pending, not the start date, so
    that is what the banner reports.
    """
    from medication_followup_protocol.services.banner import apply_banner

    add_step(day_offset=14, due_date=datetime.date(2026, 9, 10))
    add_step(day_offset=21, due_date=datetime.date(2026, 9, 17))

    narrative = payload(apply_banner(enrolment_with_key))["data"]["narrative"]

    assert enrolment_with_key.medication_class.name in narrative
    assert "2026-09-10" in narrative


def test_the_narrative_fits_the_platform_cap(enrolment_with_key, add_step):
    """Covers criterion: AC24.

    The platform caps the narrative at ninety characters. A practice writing a long class
    name is the likely way past it, so the name is what gives way rather than the date
    being silently cut off the end.
    """
    from medication_followup_protocol.services.banner import apply_banner

    enrolment_with_key.medication_class.name = "A" * 200
    enrolment_with_key.medication_class.save()
    add_step(day_offset=3, due_date=datetime.date(2026, 9, 1))

    narrative = payload(apply_banner(enrolment_with_key))["data"]["narrative"]

    assert len(narrative) <= NARRATIVE_LIMIT
    assert "2026-09-01" in narrative


def test_an_enrolment_with_nothing_pending_still_reads_as_running(enrolment_with_key):
    """Covers criterion: AC24.

    No pending step means no date to report, and the banner says the program is running
    rather than naming a date it does not have.
    """
    from medication_followup_protocol.services.banner import apply_banner

    narrative = payload(apply_banner(enrolment_with_key))["data"]["narrative"]

    assert enrolment_with_key.medication_class.name in narrative
    assert len(narrative) <= NARRATIVE_LIMIT
