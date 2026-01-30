from canvas_sdk.commands.validation import CommandValidationErrorEffect
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.command import Command
from logger import log


class RequireDaysSupplyHandler(BaseHandler):
    """Prevents committing prescription commands without a valid days_supply."""

    RESPONDS_TO = [
        EventType.Name(EventType.PRESCRIBE_COMMAND__POST_VALIDATION),
        EventType.Name(EventType.REFILL_COMMAND__POST_VALIDATION),
        EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_VALIDATION),
    ]

    def compute(self) -> list[Effect]:
        """Block prescription commit if days_supply is empty or 0."""
        command_id = self.event.target.id

        log.info(f"[RequireDaysSupplyHandler] Validating prescription command {command_id}")

        command = Command.objects.get(id=command_id)
        data = command.data

        if not data:
            log.warning(f"[RequireDaysSupplyHandler] No data found for command {command_id}")
            return []

        days_supply = data.get("days_supply")

        if days_supply is None or days_supply == 0 or days_supply == "":
            log.info(
                f"[RequireDaysSupplyHandler] Blocking commit - "
                f"days_supply is empty or 0 for command {command_id}"
            )

            validation_error = CommandValidationErrorEffect()
            validation_error.add_error(
                "Cannot commit prescription: Days supply is required and must be greater than 0."
            )
            return [validation_error.apply()]

        log.info(f"[RequireDaysSupplyHandler] Days supply valid ({days_supply}), allowing commit for command {command_id}")
        return []
