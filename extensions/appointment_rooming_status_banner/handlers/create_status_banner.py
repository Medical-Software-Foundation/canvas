from canvas_sdk.effects import Effect
from canvas_sdk.effects.banner_alert import AddBannerAlert, RemoveBannerAlert
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.appointment import Appointment


class CreateStatusBanner(BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_UPDATED)

    def compute(self) -> list[Effect]:
        effects = []

        appointment_id = self.event.target.id
        appointment = Appointment.objects.get(id=appointment_id)
        patient = appointment.patient
        if appointment.status in ['roomed', 'arrived']:
            message = 'has arrived' if appointment.status == 'arrived' else 'has been roomed'
            banner = AddBannerAlert(
                patient_id=patient.id,
                key="rooming-status",
                narrative=f"{patient.first_name} {message}.",
                placement=[
                    AddBannerAlert.Placement.TIMELINE,
                ],
                intent=AddBannerAlert.Intent.INFO,
            )
            effects.append(banner.apply())
        else:
            remove_banner = RemoveBannerAlert(
                key='rooming-status',
                patient_id=patient.id,
            )
            effects.append(remove_banner.apply())

        return effects
