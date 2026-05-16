from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class PathwayBuilderApp(Application):
    """Provider-menu entry point for the pathway builder SPA."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/clinical_pathways/builder/",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Pathway Builder",
        ).apply()
