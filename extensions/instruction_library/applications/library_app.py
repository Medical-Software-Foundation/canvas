"""Global admin app for managing the instruction library."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.templates import render_to_string


class InstructionLibraryAdmin(Application):
    def on_open(self) -> Effect:
        staff_id = self.context.get("user", {}).get("id", "")
        return LaunchModalEffect(
            content=render_to_string(
                "templates/instruction_library.html",
                {"staff_id": staff_id},
            ),
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
