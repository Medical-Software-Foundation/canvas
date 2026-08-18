"""The chart button that puts the patient in front of you on the waitlist.

The banner answers "is this patient waiting?". This button answers "put them on
the list" -- a different question, and one a passive banner cannot serve. Without
it a scheduler looking at a chart has to open the app drawer and search for the
patient they are already looking at.
"""

from unittest.mock import MagicMock, patch

from scheduling_waitlist.handlers.chart_button import AddToWaitlistButton

MODULE = "scheduling_waitlist.handlers.chart_button"


def _button(patient_id="patient-uuid"):
    button = AddToWaitlistButton.__new__(AddToWaitlistButton)
    event = MagicMock()
    event.target.id = patient_id
    button.event = event
    button.secrets = {}
    return button


class TestPlacement:
    def test_the_button_sits_in_the_chart_patient_header(self):
        assert (
            AddToWaitlistButton.BUTTON_LOCATION
            == AddToWaitlistButton.ButtonLocation.CHART_PATIENT_HEADER
        )

    def test_the_button_has_a_stable_key(self):
        # The key identifies the click; changing it orphans the handler.
        assert AddToWaitlistButton.BUTTON_KEY == "scheduling_waitlist__add"


class TestVisibility:
    def test_hidden_when_there_is_no_patient(self):
        assert _button(patient_id=None).visible() is False

    def test_shown_for_a_patient_not_yet_waiting(self):
        button = _button()
        with patch(f"{MODULE}.has_live_entry", return_value=False):
            assert button.visible() is True

    def test_offers_to_add_a_patient_who_is_not_waiting(self):
        button = _button()
        with patch(f"{MODULE}.has_live_entry", return_value=False):
            button.visible()

        assert button.BUTTON_TITLE == "Add to waitlist"

    def test_says_the_patient_is_already_waiting(self):
        # Same button, different question: it opens the roster rather than
        # inviting a duplicate entry.
        button = _button()
        with patch(f"{MODULE}.has_live_entry", return_value=True):
            button.visible()

        assert button.BUTTON_TITLE == "On waitlist"

    def test_a_label_computed_for_one_patient_does_not_leak_to_another(self):
        # The label is per-render state. Assigning it to the class would show
        # "On waitlist" on the next patient's chart.
        listed = _button(patient_id="listed")
        with patch(f"{MODULE}.has_live_entry", return_value=True):
            listed.visible()

        assert AddToWaitlistButton.BUTTON_TITLE == "Add to waitlist"

        unlisted = _button(patient_id="unlisted")
        with patch(f"{MODULE}.has_live_entry", return_value=False):
            unlisted.visible()

        assert unlisted.BUTTON_TITLE == "Add to waitlist"

    def test_the_live_entry_check_is_keyed_on_the_patients_row_id(self):
        button = _button()
        with patch(f"{MODULE}.has_live_entry", return_value=False) as lookup:
            with patch(f"{MODULE}.Patient") as patient_model:
                patient_model.objects.filter.return_value.only.return_value.first.return_value = (
                    MagicMock(dbid=77)
                )
                button.visible()

        lookup.assert_called_once_with(77)

    def test_hidden_when_the_patient_cannot_be_resolved(self):
        # Nothing to add, and a button that opens a form for an unknown patient
        # would only fail on submit.
        button = _button()
        with patch(f"{MODULE}.Patient") as patient_model:
            patient_model.objects.filter.return_value.only.return_value.first.return_value = None

            assert button.visible() is False


class TestClick:
    """The two labels have to lead to two different places.

    "On waitlist" promising status and then handing over an add form is the bug
    these pin: that form refuses the obvious resubmission with a 409 and manages
    nothing.
    """

    def _click(self, patient_id="abc-123", listed=False):
        button = _button(patient_id=patient_id)
        with (
            patch(f"{MODULE}.Patient") as patient_model,
            patch(f"{MODULE}.has_live_entry", return_value=listed),
        ):
            found = patient_model.objects.filter.return_value.only.return_value.first
            found.return_value = MagicMock(dbid=55)
            return button.handle()

    def test_a_click_opens_the_waitlist_for_this_patient(self):
        effects = self._click()

        assert len(effects) == 1
        assert "patient=abc-123" in effects[0].url

    def test_a_patient_not_yet_listed_gets_the_compact_form(self):
        url = self._click(listed=False)[0].url

        assert url.startswith("/plugin-io/api/scheduling_waitlist/app/add?")

    def test_a_patient_already_listed_gets_the_roster(self):
        # Editing, marking scheduled and removing all live on the roster, so
        # that is where "On waitlist" has to lead. The practice-wide list: a
        # patient-scoped roster was a decision that got reverted.
        url = self._click(listed=True)[0].url

        assert url.startswith("/plugin-io/api/scheduling_waitlist/app/?")
        assert "patient=" not in url

    def test_a_patient_key_needing_encoding_is_escaped(self):
        url = self._click(patient_id="a b/c")[0].url

        assert "a b/c" not in url
        assert "a%20b%2Fc" in url

    def test_an_unresolvable_patient_opens_nothing(self):
        button = _button(patient_id="ghost")
        with patch(f"{MODULE}.Patient") as patient_model:
            patient_model.objects.filter.return_value.only.return_value.first.return_value = None

            assert button.handle() == []

    def test_a_click_with_no_patient_does_nothing(self):
        assert _button(patient_id=None).handle() == []
