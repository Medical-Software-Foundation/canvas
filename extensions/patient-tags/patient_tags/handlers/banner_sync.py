from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler

from patient_tags.services.banner_service import compute_banner_effects


class BannerSyncHandler(BaseHandler):
    """Reconciles a patient's banner alerts whenever the patient is updated."""

    RESPONDS_TO = [
        EventType.Name(EventType.PATIENT_UPDATED),
    ]

    def compute(self) -> list[Effect]:
        return compute_banner_effects(self.target)
