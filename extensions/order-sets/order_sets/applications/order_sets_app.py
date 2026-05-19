import json

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


def _js_safe(value: str) -> str:
    """Encode `value` as a JS string literal that's also safe inside <script>.

    `json.dumps` handles JS string escaping but does not protect against the
    HTML tokenizer ending the surrounding <script> tag early when the value
    contains "</script>". Replacing every "</" with "<\\/" (a valid JS string
    escape that decodes back to "/") prevents the tokenizer from seeing a
    closing tag while keeping the runtime value unchanged.
    """
    return json.dumps(value).replace("</", "<\\/")


class OrderSetsApp(Application):
    def on_open(self) -> Effect:
        patient_id = self.event.context.get("patient", {}).get("id", "")
        patient_id_js = _js_safe(patient_id)
        html = (
            '<html><head><style>'
            'body { font-family: -apple-system, sans-serif; background: #f9fafb; margin: 0; padding: 0; }'
            '.loader { display: flex; justify-content: center; align-items: center; min-height: 100vh; flex-direction: column; color: #6b7280; }'
            '.spinner { width: 40px; height: 40px; border: 4px solid #e5e7eb; border-top-color: #4F46E5; border-radius: 50%; animation: spin 0.8s linear infinite; margin-bottom: 16px; }'
            '@keyframes spin { to { transform: rotate(360deg); } }'
            '#error { display: none; color: #ef4444; padding: 20px; }'
            '</style></head><body>'
            '<div class="loader" id="loading"><div class="spinner"></div><div>Loading Order Sets...</div></div>'
            '<div id="error"></div>'
            '<script>'
            f'var __patientId = {patient_id_js};'
            'fetch("/plugin-io/api/order_sets/ui?patient_id=" + encodeURIComponent(__patientId), {credentials: "same-origin"})'
            '.then(function(r) { return r.text(); })'
            '.then(function(html) { document.open(); document.write(html); document.close(); })'
            '.catch(function(err) {'
            'document.getElementById("loading").style.display = "none";'
            'var el = document.getElementById("error");'
            'el.style.display = "block";'
            'el.textContent = "Error loading Order Sets: " + err;'
            '});'
            '</script></body></html>'
        )
        return LaunchModalEffect(
            content=html,
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
        ).apply()
