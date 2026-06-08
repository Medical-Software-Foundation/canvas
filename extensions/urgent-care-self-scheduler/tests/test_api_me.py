from types import SimpleNamespace

from urgent_care_self_scheduler.handlers.api import (
    MeAPI,
    _allergy_label,
    _format_allergies,
    _format_medications,
    _medication_label,
    _patient_review,
)


def _fake_med(med_id: str, display: str | None) -> SimpleNamespace:
    # Helpers must mock `codings.all()` because production now uses
    # `list(record.codings.all())[0]` to honor prefetch_related caches.
    coding_list = [SimpleNamespace(display=display)] if display else []
    codings = SimpleNamespace(all=lambda: coding_list)
    return SimpleNamespace(id=med_id, codings=codings)


def _fake_allergy(allergy_id: str, *, narrative: str = "", coding_display: str | None = None) -> SimpleNamespace:
    coding_list = [SimpleNamespace(display=coding_display)] if coding_display else []
    codings = SimpleNamespace(all=lambda: coding_list)
    return SimpleNamespace(id=allergy_id, narrative=narrative, codings=codings)


# ---- _medication_label ------------------------------------------------------


def test_medication_label_returns_first_coding_display() -> None:
    assert _medication_label(_fake_med("m1", "Lisinopril 10mg daily")) == "Lisinopril 10mg daily"


def test_medication_label_falls_back_when_no_coding() -> None:
    assert _medication_label(_fake_med("m1", None)) == "Unknown medication"


# ---- _allergy_label ---------------------------------------------------------


def test_allergy_label_prefers_coding_display() -> None:
    # Coding is the structured allergen; narrative may only contain the reaction
    # (e.g. "rash"), which alone wouldn't tell the patient what they're allergic to.
    a = _fake_allergy("a1", narrative="rash", coding_display="Penicillin")
    assert _allergy_label(a) == "Penicillin"


def test_allergy_label_falls_back_to_narrative() -> None:
    a = _fake_allergy("a1", narrative="Bee sting (anaphylaxis)", coding_display=None)
    assert _allergy_label(a) == "Bee sting (anaphylaxis)"


def test_allergy_label_falls_back_to_unknown() -> None:
    assert _allergy_label(_fake_allergy("a1", narrative="", coding_display=None)) == "Unknown allergy"


# ---- _format_medications / _format_allergies -------------------------------


def test_format_medications_empty() -> None:
    assert _format_medications([]) == []


def test_format_medications_returns_id_and_label() -> None:
    meds = [_fake_med("m1", "Lisinopril 10mg"), _fake_med("m2", "Atorvastatin 20mg")]
    assert _format_medications(meds) == [
        {"id": "m1", "label": "Lisinopril 10mg"},
        {"id": "m2", "label": "Atorvastatin 20mg"},
    ]


def test_format_medications_coerces_id_to_string() -> None:
    # Patient.id is a UUID; stringify so JSON serialization is safe.
    import uuid
    uid = uuid.uuid4()
    meds = [_fake_med(uid, "Lisinopril")]
    out = _format_medications(meds)
    assert out[0]["id"] == str(uid)


def test_format_allergies_returns_id_and_label() -> None:
    allergies = [_fake_allergy("a1", narrative="Penicillin (rash)")]
    assert _format_allergies(allergies) == [{"id": "a1", "label": "Penicillin (rash)"}]


# ---- MeAPI ------------------------------------------------------------------


def test_me_api_path() -> None:
    assert MeAPI.PATH == "/api/me"


def test_me_api_authenticate_accepts_patient() -> None:
    api = MeAPI.__new__(MeAPI)  # bypass __init__ which needs a real event
    creds = SimpleNamespace(logged_in_user={"id": "p-1", "type": "Patient"})
    assert api.authenticate(creds) is True


def test_me_api_authenticate_rejects_staff() -> None:
    import pytest
    from canvas_sdk.handlers.simple_api.security import InvalidCredentialsError

    api = MeAPI.__new__(MeAPI)
    creds = SimpleNamespace(logged_in_user={"id": "s-1", "type": "Staff"})
    with pytest.raises(InvalidCredentialsError):
        api.authenticate(creds)


def test_me_api_returns_401_without_session_header() -> None:
    api = MeAPI.__new__(MeAPI)
    api.request = SimpleNamespace(headers={})  # type: ignore[attr-defined]
    response = api.get()
    assert response[0].status_code == 401


def test_me_api_returns_404_when_patient_review_not_found(mocker) -> None:
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api._patient_review",
        return_value=None,
    )
    api = MeAPI.__new__(MeAPI)
    api.request = SimpleNamespace(headers={"canvas-logged-in-user-id": "missing-uuid"})  # type: ignore[attr-defined]
    response = api.get()
    assert response[0].status_code == 404


def test_me_api_returns_200_with_review_payload(mocker) -> None:
    import json as _json

    fake_review = {
        "medications": [{"id": "m1", "label": "Lisinopril 10mg"}],
        "allergies": [{"id": "a1", "label": "Penicillin"}],
    }
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api._patient_review",
        return_value=fake_review,
    )
    api = MeAPI.__new__(MeAPI)
    api.request = SimpleNamespace(headers={"canvas-logged-in-user-id": "p-1"})  # type: ignore[attr-defined]
    response = api.get()
    assert response[0].status_code == 200
    assert _json.loads(response[0].content) == fake_review


def test_patient_review_returns_none_when_patient_missing(mocker) -> None:
    """_patient_review handles the 'patient not found' branch cleanly."""
    from urgent_care_self_scheduler.handlers import api as api_mod
    from canvas_sdk.v1.data.patient import Patient

    mocker.patch.object(
        Patient.objects, "get", side_effect=Patient.DoesNotExist
    )
    assert api_mod._patient_review("not-a-real-uuid") is None


def test_patient_review_assembles_meds_and_allergies(mocker) -> None:
    """Happy path: queries return iterables, formatters convert them to label dicts."""
    from urgent_care_self_scheduler.handlers import api as api_mod
    from canvas_sdk.v1.data.patient import Patient
    from canvas_sdk.v1.data.medication import Medication
    from canvas_sdk.v1.data.allergy_intolerance import AllergyIntolerance

    mocker.patch.object(Patient.objects, "get", return_value=SimpleNamespace())

    fake_med_qs = SimpleNamespace(
        exclude=lambda **_: SimpleNamespace(
            active=lambda: SimpleNamespace(
                prefetch_related=lambda *_a: [_fake_med("m1", "Lisinopril 10mg")]
            )
        )
    )
    fake_allergy_qs = SimpleNamespace(
        exclude=lambda **_: SimpleNamespace(
            committed=lambda: SimpleNamespace(
                prefetch_related=lambda *_a: [_fake_allergy("a1", coding_display="Penicillin")]
            )
        )
    )
    mocker.patch.object(Medication.objects, "filter", return_value=fake_med_qs)
    mocker.patch.object(AllergyIntolerance.objects, "filter", return_value=fake_allergy_qs)

    out = api_mod._patient_review("p-1")
    assert out == {
        "medications": [{"id": "m1", "label": "Lisinopril 10mg"}],
        "allergies": [{"id": "a1", "label": "Penicillin"}],
    }


def test_patient_review_returns_only_active_allergies() -> None:
    # Guards the status="active" include + resolved/inactive exclude semantics with
    # REAL rows — not a mock that ignores the filter, and not re-asserting the literal
    # against itself. Only the active allergy comes back.
    import datetime

    from canvas_sdk.test_utils.factories import CanvasUserFactory, PatientFactory
    from canvas_sdk.v1.data.allergy_intolerance import AllergyIntolerance

    patient = PatientFactory.create()
    committer = CanvasUserFactory.create()  # required for .committed()

    def _mk_allergy(status: str, narrative: str) -> None:
        AllergyIntolerance.objects.create(
            patient=patient,
            committer=committer,
            deleted=False,
            note_id=1,
            allergy_intolerance_type="A",
            category=1,
            status=status,
            severity="",
            onset_date=datetime.date(2026, 1, 1),
            onset_date_original_input="",
            last_occurrence=datetime.date(2026, 1, 1),
            last_occurrence_original_input="",
            recorded_date=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
            narrative=narrative,
        )

    _mk_allergy("active", "Penicillin")
    _mk_allergy("resolved", "Sulfa")
    _mk_allergy("inactive", "Latex")

    review = _patient_review(str(patient.id))
    labels = [a["label"] for a in review["allergies"]]
    assert "Penicillin" in labels
    assert "Sulfa" not in labels
    assert "Latex" not in labels
