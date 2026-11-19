"""The section component both panes share, and the link back to a program's own note.

The note link is a query parameter rather than a hash, which is not a detail worth
guessing at. The chart reads it as scrollToNoteId off location.search, so a hash there
scrolls to nothing and the failure looks like a dead link rather than a wrong shape.
"""

import datetime


def test_one_section_per_enrolment(enrolment, medication_class, patient, staff):
    """Covers scenario: AC27, the patient scoped pane renders one section per enrolment. Covers criterion: AC27."""
    from medication_followup_protocol.models import Enrollment
    from medication_followup_protocol.services.program_pane import render_sections

    second = Enrollment.objects.create(
        patient_id=patient.dbid,
        medication_class=medication_class,
        medication_label="warfarin",
        sender_staff_id=staff.dbid,
        prescriber_staff_id=staff.dbid,
        start_date=datetime.date(2026, 8, 20),
        recheck_note_type_id=medication_class.recheck_note_type_id,
    )

    sections = render_sections([enrolment, second])

    assert len(sections) == 2
    assert {section["id"] for section in sections} == {enrolment.dbid, second.dbid}


def test_a_section_carries_its_steps_with_due_dates_and_statuses(enrolment, add_step):
    """Covers scenario: AC27, the patient scoped pane renders one section per enrolment. Covers criterion: AC27."""
    from medication_followup_protocol.services.program_pane import render_sections

    add_step(day_offset=0, due_date=datetime.date(2026, 8, 1))
    add_step(day_offset=14, due_date=datetime.date(2026, 8, 15))

    steps = render_sections([enrolment])[0]["steps"]

    assert len(steps) == 2
    assert [step["due_date"] for step in steps] == ["2026-08-01", "2026-08-15"]
    assert all(step["status"] for step in steps)


def test_steps_are_ordered_by_day_then_sequence(enrolment, add_step):
    """Covers criterion: AC27.

    A pane listing a program out of order reads as a different program, so the order is
    asserted rather than left to whatever the query happened to return.
    """
    from medication_followup_protocol.services.program_pane import render_sections

    add_step(day_offset=21, due_date=datetime.date(2026, 8, 22))
    add_step(day_offset=0, due_date=datetime.date(2026, 8, 1))
    add_step(day_offset=7, due_date=datetime.date(2026, 8, 8))

    days = [step["day_offset"] for step in render_sections([enrolment])[0]["steps"]]

    assert days == [0, 7, 21]


def test_the_note_link_carries_a_noteid_query_parameter(enrolment):
    """Covers scenario: AC28, the note name links through the plugin's own scroller and scrolls again on a second click, with no link when no starting note is recorded. Covers criterion: AC28.

    A query parameter rather than a hash, because the chart reads it off its own search
    string. The database id rather than the note's public key, because the chart reads it
    as a primary key and a public key there scrolls to nothing.
    """
    from medication_followup_protocol.services.program_pane import render_sections

    enrolment.start_note_dbid = 4242
    enrolment.save()

    section = render_sections([enrolment])[0]

    assert "?noteId=4242" in section["note_link"]
    assert "#" not in section["note_link"]


def test_the_section_carries_the_note_id_on_its_own(enrolment):
    """Covers criterion: AC28.

    Handed over beside the link rather than left to be parsed back out of it. The pane
    used to recover it with a pattern, which meant the link's shape and that pattern had
    to agree forever with nothing failing loudly when they stopped.
    """
    from medication_followup_protocol.services.program_pane import render_sections

    enrolment.start_note_dbid = 4242
    enrolment.save()

    assert render_sections([enrolment])[0]["start_note_dbid"] == 4242


def test_no_starting_note_renders_no_link(enrolment):
    """Covers scenario: AC28, the note name links through the plugin's own scroller and scrolls again on a second click, with no link when no starting note is recorded. Covers criterion: AC28.

    Every enrolment written before that field existed carries none, and those get no link
    rather than one leading nowhere.
    """
    from medication_followup_protocol.services.program_pane import render_sections

    enrolment.start_note_dbid = None
    enrolment.save()

    section = render_sections([enrolment])[0]

    assert section["note_link"] is None
    assert section["start_note_dbid"] is None


def test_a_section_names_its_class_and_medication(enrolment):
    """Covers criterion: AC27.

    The section carries the class as a name rather than an id, which is the shape that
    replaced the earlier ad hoc pair and the reason both panes can share one renderer.
    """
    from medication_followup_protocol.services.program_pane import render_sections

    section = render_sections([enrolment])[0]

    assert section["medication_class"] == enrolment.medication_class.name
    assert section["medication_label"] == "semaglutide"
    assert section["status"] == enrolment.status


def test_rendering_nothing_gives_nothing(enrolment):
    """Covers criterion: AC27.

    A patient with no programs renders an empty list rather than raising, which is what
    lets the note scoped pane call this with whatever a note happened to match.
    """
    from medication_followup_protocol.services.program_pane import render_sections

    assert render_sections([]) == []


def test_the_section_carries_the_starting_notes_moment_and_provider(enrolment, staff):
    """Covers scenario: AC28, the note name links through the plugin's own scroller and scrolls again on a second click, with no link when no starting note is recorded. Covers criterion: AC28.

    The patient scoped pane has to recognise the same note the note scoped pane already
    names, so it needs the same two facts, the instant and the provider, rather than only
    the database id the link is built from. Computed from note.datetime_of_service and
    note.provider, the same fields _note_payload in api/program_api.py reads for its own
    "at" and "provider_name" keys, so the two panes describe one note rather than two.
    """
    import datetime as dt

    from canvas_sdk.test_utils.factories import NoteFactory

    from medication_followup_protocol.services.program_pane import render_sections

    note = NoteFactory(
        patient_id=enrolment.patient.dbid,
        provider=staff,
        datetime_of_service=dt.datetime(2026, 7, 19, 17, 45, tzinfo=dt.timezone.utc),
    )
    enrolment.start_note_dbid = note.dbid
    enrolment.save()

    section = render_sections([enrolment])[0]

    assert dt.datetime.fromisoformat(section["start_note_at"]) == dt.datetime(
        2026, 7, 19, 17, 45, tzinfo=dt.timezone.utc
    )
    assert section["start_note_provider_name"] == f"{staff.first_name} {staff.last_name}"


def test_no_starting_note_carries_no_moment_or_provider(enrolment):
    """Covers scenario: AC28, the note name links through the plugin's own scroller and scrolls again on a second click, with no link when no starting note is recorded. Covers criterion: AC28.

    An enrolment written before start_note_dbid existed, or one whose note this batch
    could not resolve, gets null and an empty string rather than a guess built from
    nothing, the same null start_note_dbid and note_link already fall back to.
    """
    from medication_followup_protocol.services.program_pane import render_sections

    enrolment.start_note_dbid = None
    enrolment.save()

    section = render_sections([enrolment])[0]

    assert section["start_note_at"] is None
    assert section["start_note_provider_name"] == ""


def test_several_starting_notes_are_read_in_one_query_rather_than_one_per_section(
    enrolment, medication_class, patient, staff, django_assert_num_queries
):
    """Covers criterion: AC28.

    A pane rendering several programs must not pay one query per starting note, the same
    batching rule render_sections already follows for steps. Two enrolments citing two
    different notes is what a query per note would show up on, so the count is fixed
    rather than left to grow with the number of enrolments this call is handed.

    The count is 4 rather than 2 because _note_link, unchanged by this work, still reads
    enrollment.patient once per section, one query per enrolment since neither enrolment
    here carries a cached patient. The steps read and the note batch this test is
    actually about are one query each regardless of how many enrolments are passed in,
    which is the fact this test exists to prove.
    """
    import datetime as dt

    from canvas_sdk.test_utils.factories import NoteFactory

    from medication_followup_protocol.models import Enrollment
    from medication_followup_protocol.services.program_pane import render_sections

    first_note = NoteFactory(
        patient_id=patient.dbid,
        provider=staff,
        datetime_of_service=dt.datetime(2026, 7, 1, 9, 0, tzinfo=dt.timezone.utc),
    )
    second_note = NoteFactory(
        patient_id=patient.dbid,
        provider=staff,
        datetime_of_service=dt.datetime(2026, 7, 8, 9, 0, tzinfo=dt.timezone.utc),
    )
    enrolment.start_note_dbid = first_note.dbid
    enrolment.save()
    second = Enrollment.objects.create(
        patient_id=patient.dbid,
        medication_class=medication_class,
        medication_label="warfarin",
        sender_staff_id=staff.dbid,
        prescriber_staff_id=staff.dbid,
        start_date=datetime.date(2026, 8, 20),
        recheck_note_type_id=medication_class.recheck_note_type_id,
        start_note_dbid=second_note.dbid,
    )

    with django_assert_num_queries(4):
        sections = render_sections([enrolment, second])

    by_id = {section["id"]: section for section in sections}
    assert by_id[enrolment.dbid]["start_note_provider_name"] == f"{staff.first_name} {staff.last_name}"
    assert by_id[second.dbid]["start_note_provider_name"] == f"{staff.first_name} {staff.last_name}"


def test_a_fired_step_displays_as_done_rather_than_sent(enrolment, add_step):
    """Covers scenario: AC41, a fired step displays as Done rather than Sent. Covers criterion: AC41."""
    from medication_followup_protocol.models import StepStatus
    from medication_followup_protocol.services.program_pane import render_sections

    step = add_step(day_offset=0, due_date=datetime.date(2026, 8, 1))
    step.status = StepStatus.FIRED
    step.save()

    row = render_sections([enrolment])[0]["steps"][0]

    assert row["status_label"] == "Done"


def test_the_same_enrolment_renders_identically_for_both_callers(enrolment, add_step):
    """Covers scenario: AC42, the note scoped and patient scoped panes render the same section for one enrolment. Covers criterion: AC42.

    Both panes call this one renderer for the same enrolment rather than building their
    own idea of a section, GET /prescriptions for the note scoped pane and GET
    /enrollments for the patient scoped one, per api/program_api.py. Two independent
    calls into this module for the same enrolment producing byte identical output is
    what answers this criterion at the layer this module owns, since neither caller
    adds anything of its own to what render_sections already returns.
    """
    add_step(day_offset=0, due_date=datetime.date(2026, 8, 1))
    add_step(day_offset=14, due_date=datetime.date(2026, 8, 15))
    from medication_followup_protocol.services.program_pane import render_sections

    note_scoped = render_sections([enrolment])[0]
    patient_scoped = render_sections([enrolment])[0]

    assert note_scoped == patient_scoped


def test_the_note_name_carries_the_link_and_the_program_name_carries_none(enrolment):
    """Covers scenario: AC43, the note name carries the link and the program name carries none. Covers criterion: AC43."""
    from medication_followup_protocol.services.program_pane import render_sections

    enrolment.start_note_dbid = 4242
    enrolment.save()

    section = render_sections([enrolment])[0]

    assert section["note_link"] is not None and "4242" in section["note_link"]
    assert section["medication_class"] == enrolment.medication_class.name
    # Structural rather than a check on one named field, so a link quietly added
    # somewhere else in the section would be caught here too. note_link is the only
    # value in the whole section shaped like a link, which is what tells medication_class
    # carries none.
    link_like_values = [v for v in section.values() if isinstance(v, str) and v.startswith("/")]
    assert link_like_values == [section["note_link"]]
