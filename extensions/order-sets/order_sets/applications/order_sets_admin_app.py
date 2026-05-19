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
        html = (
            '<html><head><style>'
            'body { font-family: -apple-system, sans-serif; background: #f9fafb; margin: 0; padding: 0; }'
            '.loader { display: flex; justify-content: center; align-items: center; min-height: 100vh; flex-direction: column; color: #6b7280; }'
            '.spinner { width: 40px; height: 40px; border: 4px solid #e5e7eb; border-top-color: #4F46E5; border-radius: 50%; animation: spin 0.8s linear infinite; margin-bottom: 16px; }'
            '@keyframes spin { to { transform: rotate(360deg); } }'
            '#error { display: none; color: #ef4444; padding: 20px; }'
            '</style></head><body>'
            '<div class="loader" id="loading"><div class="spinner"></div><div>Loading Order Sets Admin...</div></div>'
            '<div id="error"></div>'
            '<script>'
            'fetch("/plugin-io/api/order_sets/admin-ui", {credentials: "same-origin"})'
            '.then(function(r) { return r.text(); })'
            '.then(function(html) { document.open(); document.write(html); document.close(); })'
            '.catch(function(err) {'
            'document.getElementById("loading").style.display = "none";'
            'var el = document.getElementById("error");'
            'el.style.display = "block";'
            'el.textContent = "Error loading Order Sets Admin: " + err;'
            '});'
            '</script></body></html>'
        )
        return LaunchModalEffect(
            content=html,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Order Sets Admin",
        ).apply()
