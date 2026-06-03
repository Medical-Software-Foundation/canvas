import base64
import json

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import NoteType
from canvas_sdk.v1.data.staff import Staff
from logger import log

APP_CLASS_PATH = "chart_command_search.handlers.application:ChartSearchApp"


class ChartSearchApp(Application):
    """Application handler that opens the chart command search UI."""

    def on_open(self) -> Effect | list[Effect]:
        patient_data = self.event.context.get("patient") or {}
        patient_id = patient_data.get("id", "")
        if not patient_id:
            return []
        app_id = base64.b64encode(APP_CLASS_PATH.encode()).decode()

        providers = []
        try:
            for s in Staff.objects.filter(active=True).order_by("last_name", "first_name")[:200]:
                first = getattr(s, "first_name", "") or ""
                last = getattr(s, "last_name", "") or ""
                name = f"{first} {last}".strip()
                if name:
                    providers.append({"id": str(s.id), "name": name})
        except Exception as exc:
            log.error("Failed to fetch providers: %s", exc)

        note_types: list[dict[str, str]] = []
        try:
            for nt in NoteType.objects.filter(
                category="encounter", is_active=True, is_visible=True
            ).order_by("rank", "name")[:100]:
                note_types.append({"id": str(nt.dbid), "name": nt.name})
        except Exception as exc:
            log.error("Failed to fetch note types: %s", exc)

        ai_enabled = self.secrets.get("AI_SEARCH_ENABLED", "true").lower() == "true"

        # Practice-wide suggested prompts from admin-configured secret
        practice_prompts: list[str] = []
        try:
            raw = self.secrets.get("SUGGESTED_PROMPTS", "")
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    practice_prompts = [str(p) for p in parsed if p]
        except (json.JSONDecodeError, TypeError) as exc:
            log.error("Failed to parse SUGGESTED_PROMPTS: %s", exc)

        rendered_html = render_to_string(
            "templates/search.html",
            {
                "patient_id": patient_id,
                "app_id": app_id,
                "providers": providers,
                "note_types": note_types,
                "practice_prompts": practice_prompts,
                "ai_enabled": ai_enabled,
            },
        )
        return LaunchModalEffect(
            content=rendered_html,
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            title="Chart Command Search",
        ).apply()
