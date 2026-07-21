from unittest.mock import MagicMock, patch

from sleep_screening.applications.sleep_screening_app import SleepScreeningApp


def _app(context, secrets=None):
    app = SleepScreeningApp.__new__(SleepScreeningApp)
    app.event = MagicMock()
    app.event.context = context
    app.secrets = secrets or {}
    return app


def test_visible_true_when_rfv_matches():
    app = _app({"note_id": 123, "patient": {"id": "p1"}})
    with patch("sleep_screening.applications.sleep_screening_app.note_matches_trigger",
               return_value=True):
        assert app.visible() is True


def test_visible_false_when_rfv_absent():
    app = _app({"note_id": 123, "patient": {"id": "p1"}})
    with patch("sleep_screening.applications.sleep_screening_app.note_matches_trigger",
               return_value=False):
        assert app.visible() is False


def test_visible_passes_note_dbid_and_trigger():
    app = _app({"note_id": 123}, secrets={"RFV_TRIGGER_CODE": "custom-code"})
    with patch("sleep_screening.applications.sleep_screening_app.note_matches_trigger",
               return_value=True) as m:
        app.visible()
        assert m.call_args.args[0] == 123
        assert m.call_args.args[1] == "custom-code"


def test_visible_false_when_no_note_id():
    app = _app({"patient": {"id": "p1"}})
    with patch("sleep_screening.applications.sleep_screening_app.note_matches_trigger",
               return_value=False) as m:
        assert app.visible() is False
        assert m.call_args.args[0] is None


def test_on_open_resolves_dbid_to_uuid_in_url():
    app = _app({"note_id": 123, "patient": {"id": "p1"}})
    note = MagicMock()
    note.id = "note-uuid-abc"
    note.patient = MagicMock(id="p1")
    with patch("sleep_screening.applications.sleep_screening_app.Note") as N, \
         patch("sleep_screening.applications.sleep_screening_app.LaunchModalEffect") as LME:
        N.objects.get.return_value = note
        app.on_open()
        kwargs = LME.call_args.kwargs
        assert "note_id=note-uuid-abc" in kwargs["url"]
        assert "patient_id=p1" in kwargs["url"]
        assert kwargs["target"] == LME.TargetType.NOTE


def test_on_open_falls_back_to_note_patient_when_context_has_none():
    app = _app({"note_id": 123})  # no patient in context
    note = MagicMock()
    note.id = "note-uuid-abc"
    note.patient = MagicMock(id="p-from-note")
    with patch("sleep_screening.applications.sleep_screening_app.Note") as N, \
         patch("sleep_screening.applications.sleep_screening_app.LaunchModalEffect") as LME:
        N.objects.get.return_value = note
        app.on_open()
        kwargs = LME.call_args.kwargs
        assert "patient_id=p-from-note" in kwargs["url"]


def test_on_open_handles_missing_note():
    app = _app({"note_id": 999, "patient": {"id": "p1"}})
    with patch("sleep_screening.applications.sleep_screening_app.Note") as N, \
         patch("sleep_screening.applications.sleep_screening_app.LaunchModalEffect") as LME:
        N.DoesNotExist = Exception
        N.objects.get.side_effect = N.DoesNotExist
        app.on_open()
        kwargs = LME.call_args.kwargs
        # note_uuid empty but patient still passed from context
        assert "note_id=" in kwargs["url"]
        assert "patient_id=p1" in kwargs["url"]
