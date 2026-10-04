"""Tests for template rendering service."""
from datetime import datetime, timezone

from pytest_mock import MockerFixture

from patient_notify.services.config import CampaignConfig
from patient_notify.services.templates import get_template_variables, render_template


def test_render_template_simple() -> None:
    """Test rendering a simple template."""
    template = "Hello {{name}}, welcome to {{place}}!"
    variables = {"name": "Alice", "place": "Wonderland"}

    result = render_template(template, variables)

    assert result == "Hello Alice, welcome to Wonderland!"


def test_render_template_multiple_occurrences() -> None:
    """Test rendering template with repeated variables."""
    template = "{{name}} said {{name}} loves {{name}}"
    variables = {"name": "Bob"}

    result = render_template(template, variables)

    assert result == "Bob said Bob loves Bob"


def test_render_template_unused_variable() -> None:
    """Test rendering template with unused variables."""
    template = "Hello {{name}}"
    variables = {"name": "Charlie", "age": "30", "city": "Boston"}

    result = render_template(template, variables)

    assert result == "Hello Charlie"


def test_render_template_missing_variable() -> None:
    """Test rendering template with missing variables leaves placeholder."""
    template = "Hello {{name}}, you are {{age}} years old"
    variables = {"name": "Dana"}

    result = render_template(template, variables)

    assert result == "Hello Dana, you are {{age}} years old"


def test_get_template_variables(mocker: MockerFixture) -> None:
    """Test extracting template variables from patient and appointment."""
    patient = mocker.Mock()
    patient.first_name = "John"
    patient.last_name = "Doe"
    patient.preferred_name = ""

    provider = mocker.Mock()
    provider.first_name = "Dr. Sarah"
    provider.last_name = "Smith"
    provider.top_role_abbreviation = ""

    location = mocker.Mock()
    location.full_name = "Main Clinic"
    location.short_name = "MC"
    location.addresses = []
    location.telecom = []

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    appointment.provider = provider
    appointment.location = location
    appointment.telehealth_link = ""

    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        return_value=None,
    )

    variables = get_template_variables(patient, appointment)

    assert variables["patient_first_name"] == "John"
    assert variables["patient_last_name"] == "Doe"
    assert variables["patient_full_name"] == "John Doe"
    assert variables["patient_preferred_name"] == "John"
    assert variables["provider_name"] == "Dr. Sarah Smith"
    assert variables["location_name"] == "Main Clinic"
    assert variables["location_full_name"] == "Main Clinic"
    assert variables["location_short_name"] == "MC"
    assert "March 15, 2026" in variables["appointment_date"]
    assert "02:30 PM" in variables["appointment_time"]


def test_get_template_variables_no_provider(mocker: MockerFixture) -> None:
    """Test template variables with no provider."""
    patient = mocker.Mock()
    patient.first_name = "Jane"
    patient.last_name = "Smith"
    patient.preferred_name = ""

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    appointment.provider = None
    appointment.location = None
    appointment.telehealth_link = ""

    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        return_value=None,
    )

    variables = get_template_variables(patient, appointment)

    assert variables["provider_name"] == "your provider"
    assert variables["location_name"] == "our clinic"
    assert variables["location_full_name"] == "our clinic"
    assert variables["telehealth_link"] == ""


def test_get_template_variables_with_location_details(mocker: MockerFixture) -> None:
    """Test template variables include location address and phone."""
    patient = mocker.Mock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_name = ""

    addr = mocker.Mock()
    addr.line1 = "123 Main St"
    addr.line2 = ""
    addr.city = "Springfield"
    addr.state = "IL"
    addr.zip = "62701"

    phone_telecom = mocker.Mock()
    phone_telecom.system = "phone"
    phone_telecom.value = "555-1234"

    location = mocker.Mock()
    location.full_name = "Springfield Clinic"
    location.short_name = "SC"
    location.addresses = [addr]
    location.telecom = [phone_telecom]

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    appointment.provider = None
    appointment.location = location
    appointment.telehealth_link = ""

    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        return_value=None,
    )

    variables = get_template_variables(patient, appointment)

    assert variables["location_address"] == "123 Main St, Springfield, IL, 62701"
    assert variables["location_phone"] == "555-1234"


def test_get_template_variables_with_organization(mocker: MockerFixture) -> None:
    """Test template variables include organization name."""
    patient = mocker.Mock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_name = ""

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    appointment.provider = None
    appointment.location = None
    appointment.telehealth_link = ""

    mock_org = mocker.Mock()
    mock_org.name = "Acme Health"
    mock_org.full_name = "Acme Health Systems"
    mock_org.short_name = "AHS"
    mock_org.addresses.all.return_value = []
    mock_org.telecom.all.return_value = []
    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        return_value=mock_org,
    )

    variables = get_template_variables(patient, appointment)

    assert variables["organization_name"] == "Acme Health"
    assert variables["organization_full_name"] == "Acme Health Systems"
    assert variables["organization_short_name"] == "AHS"
    assert variables["organization_address"] == ""
    assert variables["organization_phone"] == ""


def test_get_template_variables_with_organization_details(mocker: MockerFixture) -> None:
    """Test template variables include organization address and phone."""
    patient = mocker.Mock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_name = ""

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    appointment.provider = None
    appointment.location = None
    appointment.telehealth_link = ""

    addr = mocker.Mock()
    addr.line1 = "100 Health Blvd"
    addr.line2 = ""
    addr.city = "Springfield"
    addr.state = "IL"
    addr.zip = "62701"

    phone_telecom = mocker.Mock()
    phone_telecom.system = "phone"
    phone_telecom.value = "555-000-1234"

    mock_org = mocker.Mock()
    mock_org.name = "Acme Health"
    mock_org.full_name = "Acme Health"
    mock_org.short_name = ""
    mock_org.addresses.all.return_value = [addr]
    mock_org.telecom.all.return_value = [phone_telecom]
    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        return_value=mock_org,
    )

    variables = get_template_variables(patient, appointment)

    assert variables["organization_address"] == "100 Health Blvd, Springfield, IL, 62701"
    assert variables["organization_phone"] == "555-000-1234"


def test_get_template_variables_with_provider_credentials(mocker: MockerFixture) -> None:
    """Test template variables include provider credentials from top_role_abbreviation."""
    patient = mocker.Mock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_name = ""

    provider = mocker.Mock()
    provider.first_name = "Sarah"
    provider.last_name = "Smith"
    provider.top_role_abbreviation = "MD"

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    appointment.provider = provider
    appointment.location = None
    appointment.telehealth_link = ""

    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        return_value=None,
    )

    variables = get_template_variables(patient, appointment)

    assert variables["provider_credentials"] == "MD"


def test_get_template_variables_with_preferred_name(mocker: MockerFixture) -> None:
    """Test patient_preferred_name uses preferred_name when available."""
    patient = mocker.Mock()
    patient.first_name = "William"
    patient.last_name = "Smith"
    patient.preferred_name = "Bill"

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    appointment.provider = None
    appointment.location = None
    appointment.telehealth_link = ""

    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        return_value=None,
    )

    variables = get_template_variables(patient, appointment)

    assert variables["patient_preferred_name"] == "Bill"


def test_get_template_variables_with_note_type(mocker: MockerFixture) -> None:
    """Test appointment_type populated from note_type."""
    patient = mocker.Mock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_name = ""

    note_type = mocker.Mock()
    note_type.name = "Office Visit"

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    appointment.provider = None
    appointment.location = None
    appointment.telehealth_link = ""

    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        return_value=None,
    )

    variables = get_template_variables(patient, appointment, note_type=note_type)

    assert variables["appointment_type"] == "Office Visit"


def test_get_template_variables_with_telehealth_link(mocker: MockerFixture) -> None:
    """Test telehealth_link populated from appointment."""
    patient = mocker.Mock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_name = ""

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    appointment.provider = None
    appointment.location = None
    appointment.telehealth_link = "https://telehealth.example.com/join/abc123"

    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        return_value=None,
    )

    variables = get_template_variables(patient, appointment)

    assert variables["telehealth_link"] == "https://telehealth.example.com/join/abc123"


def test_get_template_variables_custom_variables_merged(mocker: MockerFixture) -> None:
    """Test custom_variables from config are merged into template variables."""
    patient = mocker.Mock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_name = ""

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    appointment.provider = None
    appointment.location = None
    appointment.telehealth_link = ""

    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        return_value=None,
    )

    config = CampaignConfig(custom_variables={"office_hours": "9am-5pm", "website": "example.com"})
    variables = get_template_variables(patient, appointment, config=config)

    assert variables["office_hours"] == "9am-5pm"
    assert variables["website"] == "example.com"


def test_get_template_variables_custom_variables_shadow_builtins(mocker: MockerFixture) -> None:
    """Test custom variables can shadow built-in variables."""
    patient = mocker.Mock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_name = ""

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    appointment.provider = None
    appointment.location = None
    appointment.telehealth_link = ""

    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        return_value=None,
    )

    config = CampaignConfig(custom_variables={"location_name": "Custom Location"})
    variables = get_template_variables(patient, appointment, config=config)

    assert variables["location_name"] == "Custom Location"


def test_get_template_variables_handles_provider_credentials_error(
    mocker: MockerFixture,
) -> None:
    """Test graceful handling when provider.top_role_abbreviation raises."""
    patient = mocker.Mock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_name = ""

    provider = mocker.Mock()
    provider.first_name = "Dr."
    provider.last_name = "Smith"
    type(provider).top_role_abbreviation = mocker.PropertyMock(side_effect=Exception("DB error"))

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    appointment.provider = provider
    appointment.location = None
    appointment.telehealth_link = ""

    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        return_value=None,
    )

    variables = get_template_variables(patient, appointment)

    assert variables["provider_name"] == "Dr. Smith"
    assert variables["provider_credentials"] == ""


def test_get_template_variables_handles_location_field_errors(
    mocker: MockerFixture,
) -> None:
    """Test graceful handling when location fields raise exceptions."""
    patient = mocker.Mock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_name = ""

    location = mocker.Mock()
    location.full_name = "Test Clinic"
    type(location).short_name = mocker.PropertyMock(side_effect=Exception("fail"))
    type(location).addresses = mocker.PropertyMock(side_effect=Exception("fail"))
    type(location).telecom = mocker.PropertyMock(side_effect=Exception("fail"))

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    appointment.provider = None
    appointment.location = location
    appointment.telehealth_link = ""

    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        return_value=None,
    )

    variables = get_template_variables(patient, appointment)

    assert variables["location_name"] == "Test Clinic"
    assert variables["location_short_name"] == ""
    assert variables["location_address"] == ""
    assert variables["location_phone"] == ""


def test_get_template_variables_handles_org_error(mocker: MockerFixture) -> None:
    """Test graceful handling when Organization query raises."""
    patient = mocker.Mock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_name = ""

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    appointment.provider = None
    appointment.location = None
    appointment.telehealth_link = ""

    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        side_effect=Exception("DB error"),
    )

    variables = get_template_variables(patient, appointment)

    assert variables["organization_name"] == ""
    assert variables["organization_full_name"] == ""
    assert variables["organization_short_name"] == ""
    assert variables["organization_address"] == ""
    assert variables["organization_phone"] == ""


def test_get_template_variables_org_addresses_exception(mocker: MockerFixture) -> None:
    """Test graceful handling when org.addresses.all raises."""
    patient = mocker.Mock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_name = ""

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    appointment.provider = None
    appointment.location = None
    appointment.telehealth_link = ""

    mock_org = mocker.Mock()
    mock_org.name = "Acme Health"
    mock_org.full_name = "Acme Health"
    mock_org.short_name = ""
    mock_org.addresses.all.side_effect = Exception("DB error")
    mock_org.telecom.all.return_value = []
    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        return_value=mock_org,
    )

    variables = get_template_variables(patient, appointment)

    assert variables["organization_name"] == "Acme Health"
    assert variables["organization_address"] == ""


def test_get_template_variables_org_telecom_exception(mocker: MockerFixture) -> None:
    """Test graceful handling when org.telecom.all raises."""
    patient = mocker.Mock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_name = ""

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    appointment.provider = None
    appointment.location = None
    appointment.telehealth_link = ""

    mock_org = mocker.Mock()
    mock_org.name = "Acme Health"
    mock_org.full_name = "Acme Health"
    mock_org.short_name = ""
    mock_org.addresses.all.return_value = []
    mock_org.telecom.all.side_effect = Exception("DB error")
    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        return_value=mock_org,
    )

    variables = get_template_variables(patient, appointment)

    assert variables["organization_name"] == "Acme Health"
    assert variables["organization_phone"] == ""


def test_get_template_variables_handles_preferred_name_error(
    mocker: MockerFixture,
) -> None:
    """Test graceful handling when preferred_name access raises."""
    patient = mocker.Mock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    type(patient).preferred_name = mocker.PropertyMock(side_effect=Exception("fail"))

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    appointment.provider = None
    appointment.location = None
    appointment.telehealth_link = ""

    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        return_value=None,
    )

    variables = get_template_variables(patient, appointment)

    assert variables["patient_preferred_name"] == "Jane"


def test_get_template_variables_handles_note_type_error(
    mocker: MockerFixture,
) -> None:
    """Test graceful handling when note_type.name raises."""
    patient = mocker.Mock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_name = ""

    note_type = mocker.Mock()
    type(note_type).name = mocker.PropertyMock(side_effect=Exception("fail"))

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    appointment.provider = None
    appointment.location = None
    appointment.telehealth_link = ""

    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        return_value=None,
    )

    variables = get_template_variables(patient, appointment, note_type=note_type)

    assert variables["appointment_type"] == ""


def test_get_template_variables_handles_telehealth_link_error(
    mocker: MockerFixture,
) -> None:
    """Test graceful handling when telehealth_link access raises."""
    patient = mocker.Mock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.preferred_name = ""

    appointment = mocker.Mock()
    appointment.start_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
    appointment.provider = None
    appointment.location = None
    type(appointment).telehealth_link = mocker.PropertyMock(
        side_effect=Exception("fail")
    )

    mocker.patch(
        "patient_notify.services.templates.Organization.objects.first",
        return_value=None,
    )

    variables = get_template_variables(patient, appointment)

    assert variables["telehealth_link"] == ""
