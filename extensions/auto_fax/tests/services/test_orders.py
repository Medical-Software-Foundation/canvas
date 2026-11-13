from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from auto_fax.services import orders
from auto_fax.services.config import (
    SEND_ORDER_DOCUMENTS,
    SEND_WHOLE_NOTE,
    TRIGGER_FAX_ORDERS_BUTTON,
    Config,
    CoverSheet,
    RecipientSpec,
    Rule,
)
from auto_fax.services.delivery import CANVAS_BOT_STAFF_ID
from auto_fax.services.recipients import Recipient

MODULE = "auto_fax.services.orders"
T0 = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)
T1 = datetime(2026, 11, 4, 16, 0, tzinfo=UTC)
T2 = datetime(2026, 11, 4, 17, 0, tzinfo=UTC)


class QS:
    """A stand-in queryset: records every call, returns fixed rows."""

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        return self

    def filter(self, *args, **kwargs):
        return self._record("filter", *args, **kwargs)

    def exclude(self, *args, **kwargs):
        return self._record("exclude", *args, **kwargs)

    def order_by(self, *args):
        return self._record("order_by", *args)

    def select_related(self, *args):
        return self._record("select_related", *args)

    def values_list(self, *args, **kwargs):
        self._record("values_list", *args, **kwargs)
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


def _model(rows=()):
    return SimpleNamespace(objects=QS(rows))


def _rule(
    name="orders",
    order_types=("lab",),
    send_as=SEND_ORDER_DOCUMENTS,
    metadata=(),
    codes=("*",),
    cover=None,
    trigger=TRIGGER_FAX_ORDERS_BUTTON,
):
    return Rule(
        name=name,
        note_type_codes=frozenset(codes),
        trigger_states=frozenset(),
        recipients=(RecipientSpec(type="facility"),),
        cover_sheet=cover,
        trigger=trigger,
        order_types=frozenset(order_types),
        command_metadata=tuple(metadata),
        send_as=send_as,
    )


def _config(rules, mode="live", test=None):
    return Config(mode=mode, rules=tuple(rules), test_fax_digits=test, errors=())


def _command(cid, schema_key, data=None, modified=T0, anchor=None):
    return SimpleNamespace(
        id=cid,
        schema_key=schema_key,
        data=data or {},
        modified=modified,
        anchor_object_dbid=anchor,
    )


def _note(code="office_visit", location="loc-1", patient=True):
    return SimpleNamespace(
        id="note-1",
        dbid=7,
        note_type_version=SimpleNamespace(code=code) if code else None,
        location=SimpleNamespace(id=location) if location else None,
        patient=SimpleNamespace(id="patient-1") if patient else None,
        provider=None,
    )


def _facility(rule, digits="5552340111", name="Oak House", problem=None):
    return Recipient(rule, "facility", name, digits, problem=problem)


@pytest.fixture
def db():
    """Every model and effect the planner touches, as fakes."""
    docs = {
        "referral": (
            _model(),
            _model(),
            "referral",
            MagicMock(name="FaxReferralEffect"),
            "referral_id",
        ),
        "imaging": (
            _model(),
            _model(),
            "imaging_order",
            MagicMock(name="FaxImagingOrderEffect"),
            "imaging_order_id",
        ),
        "lab": (
            _model(),
            _model(),
            "lab_order",
            MagicMock(name="FaxLabOrderEffect"),
            "lab_order_id",
        ),
    }
    state = SimpleNamespace(
        command=_model(),
        metadata=_model(),
        note=_model(),
        note_events=_model(),
        docs=docs,
        resolve=MagicMock(),
        fax_note=MagicMock(name="FaxNoteEffect"),
    )
    with (
        patch(f"{MODULE}.Command", state.command),
        patch(f"{MODULE}.CommandMetadata", state.metadata),
        patch(f"{MODULE}.Note", state.note),
        patch(f"{MODULE}.NoteActionEvent", state.note_events),
        patch(f"{MODULE}.resolve_recipients", state.resolve),
        patch(f"{MODULE}.FaxNoteEffect", state.fax_note),
        patch(f"{MODULE}.log") as log,
        patch.dict(orders._DOCUMENTS, docs),
    ):
        state.log = log
        yield state


# --- describe ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (None, ""),
        ([], ""),
        ({}, ""),
        ({"service_provider": {"text": " Cardiology "}}, "Cardiology"),
        ({"tests": [{"text": "CBC"}, {"text": "BMP"}, "x", {"text": 3}]}, "CBC, BMP"),
        ({"note": "free text", "item": {"text": "Walker"}}, "Walker"),
        ({"item": {"text": "  "}, "other": {"text": "Cane"}}, "Cane"),
        ({"item": {"text": "x" * 100}}, "x" * 79 + "…"),
    ],
)
def test_describe(data, expected):
    assert orders.describe(data) == expected


def test_type_names():
    meds = orders.MEDICATION_ORDER_TYPES
    assert (
        orders.type_names(meds | {"lab", "dme"}) == "Medications, DME order, Lab order"
    )
    assert orders.type_names(frozenset({"prescribe"})) == "Prescription"


def test_order_type_label():
    order = orders.Order("c", "lab", "", T0)
    assert order.type_label == "Lab order"


def test_delivery_fax_count():
    rule = _rule()
    whole = orders.Delivery("n", "facility", "5550000000", rule, SEND_WHOLE_NOTE)
    assert whole.fax_count == 1
    docs = orders.Delivery("n", "facility", "5550000000", rule, SEND_ORDER_DOCUMENTS)
    docs.unsent = [orders.Order("a", "lab", "", T0), orders.Order("b", "lab", "", T0)]
    assert docs.fax_count == 2


def test_plan_flags():
    plan = orders.Plan(note_id="n", location_id=None)
    assert not plan.has_orders
    assert not plan.all_already_sent  # nothing to send is not "already sent"


# --- find_note ----------------------------------------------------------------


@pytest.mark.parametrize(
    "config",
    [
        _config([_rule()], mode="off"),
        _config([_rule(trigger="note_state")]),
        _config([]),
    ],
)
def test_find_note_runs_no_query_without_a_live_button_rule(db, config):
    assert orders.find_note(config, dbid=7) is None
    assert db.note.objects.calls == []


def test_find_note_needs_an_id(db):
    assert orders.find_note(_config([_rule()])) is None
    assert db.note.objects.calls == []


def test_find_note_by_dbid(db):
    db.note.objects.rows = [_note()]
    rule = _rule()
    found = orders.find_note(_config([rule, _rule(trigger="note_state")]), dbid=7)
    assert found == (db.note.objects.rows[0], [rule])
    assert ("filter", (), {"dbid": 7}) in db.note.objects.calls


def test_find_note_by_id(db):
    db.note.objects.rows = [_note()]
    assert orders.find_note(_config([_rule()]), note_id="note-1") is not None
    assert ("filter", (), {"id": "note-1"}) in db.note.objects.calls


@pytest.mark.parametrize("note", [None, _note(patient=False)])
def test_find_note_missing_note_or_patient(db, note):
    db.note.objects.rows = [note] if note else []
    assert orders.find_note(_config([_rule()]), dbid=7) is None


def test_find_note_rule_must_cover_the_note_type(db):
    db.note.objects.rows = [_note(code=None)]
    assert orders.find_note(_config([_rule(codes=("office_visit",))]), dbid=7) is None


def test_button_rules_filter_by_location():
    rule = Rule(
        name="x",
        note_type_codes=frozenset({"*"}),
        trigger_states=frozenset(),
        recipients=(),
        location_ids=frozenset({"loc-1"}),
        trigger=TRIGGER_FAX_ORDERS_BUTTON,
        order_types=frozenset({"lab"}),
    )
    assert orders.button_rules(_config([rule]), "a", "loc-1") == [rule]
    assert orders.button_rules(_config([rule]), "a", "loc-2") == []
    assert orders.location_id_of(_note(location=None)) is None


# --- build_plan -------------------------------------------------------------


def test_plan_without_orders(db):
    rule = _rule(order_types=("lab", "referral"))
    db.resolve.return_value = [_facility(rule)]
    plan = orders.build_plan(_note(), [rule], None)

    assert not plan.has_orders
    assert plan.deliveries == []
    assert plan.order_types == {"lab", "referral"}
    filt = db.command.objects.calls[0]
    assert filt == (
        "filter",
        (),
        {
            "note__id": "note-1",
            "schema_key__in": ["labOrder", "refer"],
            "state": "committed",
            "entered_in_error__isnull": True,
        },
    )
    assert db.metadata.objects.calls == []
    assert db.note_events.objects.calls == []


def test_facility_without_fax_number_is_a_problem(db):
    rule = _rule()
    db.command.objects.rows = [_command("c1", "labOrder", anchor=11)]
    db.resolve.return_value = [
        _facility(rule, digits=None, problem="facility has no fax number"),
        Recipient(rule, "facility", "", None, problem="no facility on file"),
        Recipient(rule, "facility", "", None, problem="no facility on file"),
    ]
    plan = orders.build_plan(_note(), [rule], None)
    assert plan.problems == [
        "Oak House (facility): facility has no fax number",
        "facility: no facility on file",
    ]
    assert not plan.has_orders


def test_order_documents_without_any_document_is_a_problem_not_already_sent(db):
    rule = _rule(order_types=("referral", "imaging"))
    db.command.objects.rows = [
        _command("c1", "refer", {"to": {"text": "Cardiology"}}, anchor=None),
        _command("c2", "imagingOrder", anchor=None),
    ]
    db.resolve.return_value = [_facility(rule)]

    plan = orders.build_plan(_note(), [rule], None)
    assert plan.deliveries == []
    assert not plan.has_orders
    assert not plan.all_already_sent
    assert plan.problems == [
        "Referral (Cardiology), Imaging order: no document on file to fax yet"
    ]


def test_order_documents_plan_marks_unsent_documents(db):
    rule = _rule(order_types=("lab", "referral", "imaging"))
    db.command.objects.rows = [
        _command("c1", "labOrder", {"tests": [{"text": "CBC"}]}, anchor=11),
        _command("c2", "refer", {"to": {"text": "Cardiology"}}, anchor=21),
        _command("c3", "imagingOrder", anchor=None),  # no record yet
    ]
    lab_model, lab_events = db.docs["lab"][0], db.docs["lab"][1]
    lab_model.objects.rows = [(11, "lab-uuid")]
    db.docs["referral"][0].objects.rows = [(21, "ref-uuid")]
    lab_events.objects.rows = [
        ("lab-uuid", "+15552340111", T0),
        ("lab-uuid", "+15552340111", T1),
        ("lab-uuid", None, T2),
    ]
    db.resolve.return_value = [_facility(rule)]

    plan = orders.build_plan(_note(), [rule], None)
    (delivery,) = plan.deliveries
    assert [o.label for o in delivery.orders] == ["CBC", "Cardiology"]
    assert [o.document_id for o in delivery.orders] == ["lab-uuid", "ref-uuid"]
    assert plan.problems == ["Imaging order: no document on file to fax yet"]
    assert [o.command_id for o in delivery.unsent] == ["c2"]
    assert delivery.last_sent == T1
    assert not delivery.already_sent
    assert delivery.fax_count == 1
    assert ("filter", (), {"dbid__in": [11]}) in lab_model.objects.calls
    assert lab_events.objects.calls[0] == (
        "filter",
        (),
        {"lab_order__id__in": ["lab-uuid"]},
    )
    assert lab_events.objects.calls[1] == (
        "filter",
        (),
        {"event_type": "FAXED", "originator__staff__id": CANVAS_BOT_STAFF_ID},
    )
    assert lab_events.objects.calls[2] == (
        "exclude",
        (),
        {"delivered_by_fax": False},
    )
    # The imaging model is never queried: no imaging command has a record.
    assert db.docs["imaging"][0].objects.calls == []


def test_order_documents_all_faxed_is_already_sent(db):
    rule = _rule()
    db.command.objects.rows = [_command("c1", "labOrder", anchor=11)]
    db.docs["lab"][0].objects.rows = [(11, "lab-uuid")]
    db.docs["lab"][1].objects.rows = [("lab-uuid", "+15552340111", T1)]
    db.resolve.return_value = [_facility(rule)]
    plan = orders.build_plan(_note(), [rule], None)
    assert plan.all_already_sent
    assert plan.deliveries[0].fax_count == 0


def test_metadata_filter_drops_orders(db):
    rule = _rule(
        order_types=("prescribe",),
        send_as=SEND_WHOLE_NOTE,
        metadata=(("alert_facility", "Yes"),),
    )
    db.command.objects.rows = [
        _command("c1", "prescribe", {"prescribe": {"text": "Drug A"}}),
        _command("c2", "prescribe", {"prescribe": {"text": "Drug B"}}),
        _command("c3", "prescribe"),
    ]
    db.metadata.objects.rows = [
        ("c1", "alert_facility", "Yes"),
        ("c2", "alert_facility", "No"),
        ("c1", "other", "x"),
    ]
    db.resolve.return_value = [_facility(rule)]
    plan = orders.build_plan(_note(), [rule], None)
    (delivery,) = plan.deliveries
    assert [o.command_id for o in delivery.orders] == ["c1"]
    assert plan.metadata_notes == [
        "Prescription: only orders marked alert_facility = Yes"
    ]
    # Whole-note rules don't need the order records.
    assert all(d[0].objects.calls == [] for d in db.docs.values())


def test_metadata_filter_can_leave_nothing(db):
    rule = _rule(
        order_types=("prescribe",),
        send_as=SEND_WHOLE_NOTE,
        metadata=(("alert_facility", "Yes"),),
    )
    db.command.objects.rows = [_command("c1", "prescribe")]
    db.resolve.return_value = [_facility(rule)]
    plan = orders.build_plan(_note(), [rule], None)
    assert not plan.has_orders
    assert db.note_events.objects.calls == []


def test_two_rules_to_one_number_merge_into_one_whole_note_fax(db):
    meds = _rule(
        name="meds",
        order_types=("prescribe",),
        send_as=SEND_WHOLE_NOTE,
        metadata=(("alert_facility", "Yes"),),
    )
    labs = _rule(name="labs", order_types=("lab", "dme"), send_as=SEND_WHOLE_NOTE)
    db.command.objects.rows = [
        _command("c1", "prescribe", modified=T0),
        _command("c2", "labOrder", modified=T1),
        _command("c3", "orderDme", modified=T0),
    ]
    db.metadata.objects.rows = [("c1", "alert_facility", "yes")]
    db.resolve.return_value = [_facility(meds), _facility(labs), _facility(labs)]
    plan = orders.build_plan(_note(), [meds, labs], None)
    (delivery,) = plan.deliveries
    assert [o.command_id for o in delivery.orders] == ["c1", "c2", "c3"]
    assert delivery.send_as == SEND_WHOLE_NOTE
    assert delivery.fax_count == 1


def test_whole_note_rule_wins_when_rules_share_a_number(db):
    docs_rule = _rule(name="docs", order_types=("lab",))
    whole_rule = _rule(name="whole", order_types=("dme",), send_as=SEND_WHOLE_NOTE)
    db.command.objects.rows = [_command("c1", "labOrder", anchor=11)]
    db.docs["lab"][0].objects.rows = [(11, "lab-uuid")]
    db.resolve.return_value = [_facility(docs_rule), _facility(whole_rule)]
    plan = orders.build_plan(_note(), [docs_rule, whole_rule], None)
    (delivery,) = plan.deliveries
    assert delivery.send_as == SEND_WHOLE_NOTE


def test_whole_note_already_sent_until_a_newer_order(db):
    rule = _rule(order_types=("lab",), send_as=SEND_WHOLE_NOTE)
    db.command.objects.rows = [_command("c1", "labOrder", modified=T0)]
    db.note_events.objects.rows = [
        ("+15552340111", T1),
        ("+15552340111", T0),
        (None, T2),
    ]
    db.resolve.return_value = [_facility(rule)]
    plan = orders.build_plan(_note(), [rule], None)
    assert plan.deliveries[0].last_sent == T1
    assert plan.all_already_sent

    # An order committed after the last fax makes it new again.
    db.command.objects.rows = [
        _command("c1", "labOrder", modified=T0),
        _command("c2", "labOrder", modified=T2),
    ]
    plan = orders.build_plan(_note(), [rule], None)
    assert not plan.deliveries[0].already_sent
    assert plan.deliveries[0].last_sent == T1


def test_test_number_replaces_the_destination(db):
    rule = _rule(send_as=SEND_WHOLE_NOTE)
    db.command.objects.rows = [_command("c1", "labOrder")]
    db.resolve.return_value = [_facility(rule)]
    plan = orders.build_plan(_note(), [rule], "5550000199")
    assert plan.test_number
    assert plan.deliveries[0].digits == "5550000199"


# --- fax_effects ------------------------------------------------------------


def _plan(*deliveries, test_number=False, location="loc-1"):
    return orders.Plan(
        note_id="note-1",
        location_id=location,
        deliveries=list(deliveries),
        test_number=test_number,
    )


def _delivery(rule, send_as, orders_=(), unsent=(), already=False):
    return orders.Delivery(
        name="Oak House",
        kind="facility",
        digits="5552340111",
        rule=rule,
        send_as=send_as,
        orders=list(orders_),
        unsent=list(unsent),
        already_sent=already,
    )


LAB = orders.Order("c1", "lab", "CBC", T0, "lab-uuid")
REF = orders.Order("c2", "referral", "Cardio", T0, "ref-uuid")
NO_DOC = orders.Order("c3", "imaging", "", T0, None)


def test_whole_note_send(db):
    cover = CoverSheet(subject="Orders", comment="Please file.")
    rule = _rule(send_as=SEND_WHOLE_NOTE, cover=cover)
    effects, count = orders.fax_effects(
        _plan(_delivery(rule, SEND_WHOLE_NOTE, [LAB])), resend=False, dry_run=False
    )
    assert count == 1
    assert effects == [db.fax_note.return_value.apply.return_value]
    db.fax_note.assert_called_once_with(
        note_id="note-1",
        recipient_name="Oak House",
        recipient_fax_number="15552340111",
        include_coversheet=True,
        subject="Orders",
        comment="Please file.",
        location_id="loc-1",
    )
    db.log.info.assert_called_once_with(
        "[auto_fax] faxing whole note with 1 order(s): orders for note note-1 "
        "rule 'orders' -> facility at ***-***-0111"
    )


def test_order_documents_send_only_unsent(db):
    rule = _rule(order_types=("lab", "referral", "imaging"))
    delivery = _delivery(rule, SEND_ORDER_DOCUMENTS, [LAB, REF, NO_DOC], unsent=[REF])
    effects, count = orders.fax_effects(_plan(delivery), resend=False, dry_run=False)
    referral_effect = db.docs["referral"][3]
    assert count == 1
    assert effects == [referral_effect.return_value.apply.return_value]
    referral_effect.assert_called_once_with(
        referral_id="ref-uuid",
        recipient_name="Oak House",
        recipient_fax_number="15552340111",
    )
    db.docs["lab"][3].assert_not_called()


def test_resend_sends_every_document_again(db):
    rule = _rule(order_types=("lab", "referral", "imaging"))
    delivery = _delivery(
        rule, SEND_ORDER_DOCUMENTS, [LAB, REF, NO_DOC], unsent=[], already=True
    )
    effects, count = orders.fax_effects(
        _plan(delivery, test_number=True), resend=True, dry_run=False
    )
    assert count == 2
    assert len(effects) == 2
    db.docs["lab"][3].assert_called_once()
    db.log.info.assert_any_call(
        "[auto_fax] faxing lab order c1: orders for note note-1 rule 'orders' -> "
        "facility at ***-***-0111 (test number)"
    )


def test_already_sent_is_skipped_without_resend(db):
    rule = _rule(send_as=SEND_WHOLE_NOTE)
    effects, count = orders.fax_effects(
        _plan(_delivery(rule, SEND_WHOLE_NOTE, [LAB], already=True)),
        resend=False,
        dry_run=False,
    )
    assert (effects, count) == ([], 0)
    db.fax_note.assert_not_called()


def test_dry_run_counts_and_logs_but_sends_nothing(db):
    whole = _rule(name="whole", send_as=SEND_WHOLE_NOTE)
    docs = _rule(name="docs")
    effects, count = orders.fax_effects(
        _plan(
            _delivery(whole, SEND_WHOLE_NOTE, [LAB]),
            _delivery(docs, SEND_ORDER_DOCUMENTS, [LAB], unsent=[LAB]),
        ),
        resend=False,
        dry_run=True,
    )
    assert effects == []
    assert count == 2
    db.fax_note.assert_not_called()
    db.docs["lab"][3].assert_not_called()
    assert all(
        call.args[0].startswith("[auto_fax] dry run, would fax")
        for call in db.log.info.call_args_list
    )
