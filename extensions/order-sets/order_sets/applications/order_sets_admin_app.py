from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class OrderSetsAdminApp(Application):
    """Global-scope admin app for managing order-set definitions.

    Per REVIEW.md item #10, admin operations (configuration, settings
    management) belong in global-scope Applications rather than patient-scoped
    ones. This app surfaces the same admin UI as the in-modal gear icon in
    `OrderSetsApp`, but it can be opened directly from the global app drawer
    with no patient chart context required.
    """

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/order_sets/admin-ui",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Order Sets Admin",
        ).apply()
