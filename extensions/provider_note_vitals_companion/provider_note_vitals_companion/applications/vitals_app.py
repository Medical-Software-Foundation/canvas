from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class VitalsApp(Application):
    """Note-scoped companion app: mobile vitals entry form for the current note."""

    def on_open(self) -> Effect:
        note_id = self.event.context.get("note", {}).get("id", "")
        return LaunchModalEffect(
            url=f"/plugin-io/api/provider_note_vitals_companion/app/?note_id={note_id}",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
