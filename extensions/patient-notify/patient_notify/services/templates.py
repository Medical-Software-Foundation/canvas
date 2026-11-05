"""Template rendering for notification messages."""
from typing import Any

from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.organization import Organization
from canvas_sdk.v1.data.patient import Patient

from patient_notify.services.config import CampaignConfig


def render_template(template: str, variables: dict[str, Any]) -> str:
    """Render a template string by replacing {{variable}} placeholders."""
    result = template
    for key, value in variables.items():
        placeholder = f"{{{{{key}}}}}"
        result = result.replace(placeholder, str(value))
    return result


def get_template_variables(
    patient: Patient,
    appointment: Appointment,
    config: CampaignConfig | None = None,
    note_type: Any | None = None,
) -> dict[str, str]:
    """Extract template variables from patient and appointment."""
    appointment_date = appointment.start_time.strftime("%B %d, %Y")
    appointment_time = appointment.start_time.strftime("%I:%M %p")

    provider_name = "your provider"
    provider_credentials = ""
    if appointment.provider:
        provider_name = f"{appointment.provider.first_name} {appointment.provider.last_name}"
        try:
            abbr = appointment.provider.top_role_abbreviation
            if abbr:
                provider_credentials = abbr
        except Exception:
            pass

    location_name = "our clinic"
    location_full_name = "our clinic"
    location_short_name = ""
    location_address = ""
    location_phone = ""
    if appointment.location:
        location_name = appointment.location.full_name
        location_full_name = appointment.location.full_name
        try:
            location_short_name = appointment.location.short_name or ""
        except Exception:
            pass
        try:
            for addr in appointment.location.addresses:
                parts = []
                for field_name in ("line1", "line2", "city", "state", "zip"):
                    val = getattr(addr, field_name, "")
                    if val:
                        parts.append(str(val))
                if parts:
                    location_address = ", ".join(parts)
                    break
        except Exception:
            pass
        try:
            for telecom in appointment.location.telecom:
                system = getattr(telecom, "system", "")
                if system == "phone":
                    location_phone = getattr(telecom, "value", "")
                    break
        except Exception:
            pass

    organization_name = ""
    organization_full_name = ""
    organization_short_name = ""
    organization_address = ""
    organization_phone = ""
    try:
        org = Organization.objects.first()
        if org:
            organization_name = org.name
            organization_full_name = org.full_name or org.name
            organization_short_name = org.short_name or ""
            try:
                for addr in org.addresses.all():
                    parts = []
                    for field_name in ("line1", "line2", "city", "state", "zip"):
                        val = getattr(addr, field_name, "")
                        if val:
                            parts.append(str(val))
                    if parts:
                        organization_address = ", ".join(parts)
                        break
            except Exception:
                pass
            try:
                for telecom in org.telecom.all():
                    system = getattr(telecom, "system", "")
                    if system == "phone":
                        organization_phone = getattr(telecom, "value", "")
                        break
            except Exception:
                pass
    except Exception:
        pass

    patient_preferred_name = patient.first_name
    try:
        preferred = getattr(patient, "preferred_name", "")
        if preferred:
            patient_preferred_name = preferred
    except Exception:
        pass

    patient_full_name = f"{patient.first_name} {patient.last_name}"

    appointment_type = ""
    if note_type:
        try:
            appointment_type = note_type.name
        except Exception:
            pass

    telehealth_link = ""
    try:
        link = getattr(appointment, "telehealth_link", "")
        if link:
            telehealth_link = link
    except Exception:
        pass

    variables: dict[str, str] = {
        "patient_first_name": patient.first_name,
        "patient_last_name": patient.last_name,
        "patient_preferred_name": patient_preferred_name,
        "patient_full_name": patient_full_name,
        "provider_name": provider_name,
        "provider_credentials": provider_credentials,
        "appointment_date": appointment_date,
        "appointment_time": appointment_time,
        "appointment_type": appointment_type,
        "location_name": location_name,
        "location_full_name": location_full_name,
        "location_short_name": location_short_name,
        "location_address": location_address,
        "location_phone": location_phone,
        "organization_name": organization_name,
        "organization_full_name": organization_full_name,
        "organization_short_name": organization_short_name,
        "organization_address": organization_address,
        "organization_phone": organization_phone,
        "telehealth_link": telehealth_link,
    }

    if config and config.custom_variables:
        variables.update(config.custom_variables)

    return variables
