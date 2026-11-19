"""The chart panel, the admin app, and the JSON API behind them.

Every request runs as the signed-in staff member (StaffSessionAuthMixin). Every staff member can
open the app. Personal phrases can only be changed by their owner. Practice phrases, practice info,
settings, and import need the staff member to be on the ADMIN_TEAM team; when that setting is
empty, nobody can change them.
GET /phrases also serves other tools that want the signed-in staff member's phrases.
"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any
from uuid import uuid4

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Command, Note, PatientMetadata
from canvas_sdk.v1.data.note import CurrentNoteStateEvent
from django.db.models import Q

from dot_phrases.catalog import (
    COMMAND_LABELS,
    DEFAULT_USE_IN,
    FIELD_LIMITS,
    INSERT_FIELD,
    INSERTABLE,
    NOTE_COMMAND_KEYS,
    RX_FIELDS,
    RX_SCHEMA_KEYS,
    works_in,
)
from dot_phrases.handlers.note_events import leftovers_key
from dot_phrases.handlers.panel_button import EDITABLE_NOTE_STATES
from dot_phrases.library import (
    admin_team_name,
    custom_placeholders,
    enabled_chart_placeholders,
    favorite_ids,
    get_setting,
    hidden_ids,
    note_label,
    is_admin,
    known_names,
    phrase_fits_rx,
    placeholder_values,
    practice_values,
    record_use,
    remember_timezone,
    set_setting,
    staff_dbid,
    staff_name,
    usable_phrases,
)
from dot_phrases.models import Phrase, PhraseFavorite, PhraseHidden, PracticeValue
from dot_phrases.text import (
    CHART_GROUPS,
    MAX_TEXT_LENGTH,
    PATIENT_PLACEHOLDERS,
    PRACTICE_NAME_RULE,
    fill,
    fill_ins,
    is_valid_code,
    placeholder_names,
    rx_field_name,
    rx_issue,
    rx_message,
    unknown_placeholders,
)

API_BASE = "/plugin-io/api/dot_phrases"
# Changes on every plugin load, so browsers fetch fresh scripts and styles after an update.
# A note's body columns can be large and nothing here reads them.
NOTE_BLOBS = ("_body", "_body_content", "_body_order", "related_data")
CACHE_BUST = str(int(datetime.now(UTC).timestamp()))
MAX_VALUE_LENGTH = 500
MAX_IMPORT_LINES = 2000
MAX_METADATA_KEYS = 200
MAX_VALUE_NAMES = 20
METADATA_KEYS_CACHE = "dot-phrases:metadata-keys"
IMPORT_USE_IN = {"plan": "plan", "hpi": "hpi", "instruct": "instruct", "perform": "perform"}


def _error(message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> list[Response | Effect]:
    return [JSONResponse({"error": message}, status_code=status)]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _phrase_json(
    phrase: Phrase, me: int | None, favorites: set[int], values: dict[str, str] | None, hidden: set[int] | None = None
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": phrase.dbid,
        "code": phrase.code,
        "text": phrase.text,
        "scope": phrase.scope,
        "mine": phrase.scope == "personal" and phrase.owner_id == me,
        "owner": staff_name(phrase.owner),
        "use_in": phrase.use_in,
        "rx_sig": bool(phrase.rx_sig),
        "rx_note_to_pharmacist": bool(phrase.rx_note_to_pharmacist),
        "favorite": phrase.dbid in favorites,
        "hidden": phrase.dbid in (hidden or set()),
        "uses": phrase.uses or 0,
        "last_used_at": _iso(phrase.last_used_at),
        "fill_ins": [f._asdict() for f in fill_ins(phrase.text)],
    }
    if values is not None:
        data["preview"] = fill(phrase.text, values).text
    return data


class DotPhrasesAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the chart panel and admin pages, and the JSON API they use."""

    # ---------- who is asking ----------

    def _staff_id(self) -> str | None:
        staff_id = self.request.headers.get("canvas-logged-in-user-id")
        return str(staff_id) if staff_id else None

    def _me(self) -> int | None:
        return staff_dbid(self._staff_id())

    def _admin(self) -> bool:
        return is_admin(self._staff_id(), self.secrets)

    # ---------- pages and assets ----------

    def _asset(self, path: str, content_type: str) -> list[Response | Effect]:
        body = render_to_string(path) or ""
        return [Response(body.encode(), status_code=HTTPStatus.OK, content_type=content_type, headers={"Cache-Control": "no-cache"})]

    @api.get("/panel/")
    def panel_page(self) -> list[Response | Effect]:
        note_id = self.request.query_params.get("note_id") or ""
        html = render_to_string("static/panel/index.html", {"api_base": API_BASE, "note_id": note_id, "cache_bust": CACHE_BUST}) or ""
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/panel/app.js")
    def panel_js(self) -> list[Response | Effect]:
        return self._asset("static/panel/app.js", "application/javascript")

    @api.get("/panel/app.css")
    def panel_css(self) -> list[Response | Effect]:
        return self._asset("static/panel/app.css", "text/css")

    @api.get("/shared/use_in.js")
    def shared_use_in_js(self) -> list[Response | Effect]:
        return self._asset("static/shared/use_in.js", "application/javascript")

    @api.get("/shared/use_in.css")
    def shared_use_in_css(self) -> list[Response | Effect]:
        return self._asset("static/shared/use_in.css", "text/css")

    @api.get("/icon.svg")
    def icon(self) -> list[Response | Effect]:
        return self._asset("assets/icon.svg", "image/svg+xml")

    @api.get("/admin/")
    def admin_page(self) -> list[Response | Effect]:
        # Everyone gets the page. What they can change is checked by each write endpoint.
        html = render_to_string("static/admin/index.html", {"api_base": API_BASE, "cache_bust": CACHE_BUST}) or ""
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/admin/app.js")
    def admin_js(self) -> list[Response | Effect]:
        return self._asset("static/admin/app.js", "application/javascript")

    @api.get("/admin/app.css")
    def admin_css(self) -> list[Response | Effect]:
        return self._asset("static/admin/app.css", "text/css")

    # ---------- chart panel data ----------

    @api.get("/phrases")
    def list_phrases(self) -> list[Response | Effect]:
        """Phrases the signed-in staff member can use, with previews for the note's patient."""
        me = self._me()
        if me is None:
            return _error("No signed-in staff member.", HTTPStatus.UNAUTHORIZED)
        note_id = self.request.query_params.get("note_id") or ""
        note = Note.objects.filter(id=note_id).select_related("patient", "provider", "note_type_version", "location").defer(*NOTE_BLOBS).first() if note_id else None
        # The panel sends the browser's time zone; remember it so this person's typed codes use it too.
        zone = remember_timezone(me, self.request.query_params.get("tz"))
        usable = usable_phrases(me)
        # Each setting is read once for this request.
        enabled, custom, practice = enabled_chart_placeholders(), custom_placeholders(), practice_values()
        # Only the values the panel shows or uses: its menu placeholders, practice info, and whatever
        # this person's phrases contain. A hidden placeholder no phrase uses never reaches the browser.
        needed = set(enabled) | set(custom) | set(practice) | placeholder_names([p.text for p in usable.values()])
        values = placeholder_values(
            note.patient if note else None, note, zone_name=zone, owner_dbid=me, needed=needed, practice=practice, custom=custom
        )
        favorites = favorite_ids(me)
        hidden = hidden_ids(me)
        phrases = [_phrase_json(p, me, favorites, values, hidden) for p in usable.values()]
        rx_targets: list[str] = []
        if note is not None and self._staged_rx(note.id) is not None:
            rx_targets = list(RX_FIELDS)
        return [
            JSONResponse(
                {
                    "phrases": phrases,
                    "is_admin": self._admin(),
                    "admin_team": admin_team_name(self.secrets),
                    "note": note_label(note) if note else None,
                    "allow_copy_text": bool(get_setting("allow_copy_text")),
                    "rx_targets": rx_targets,
                    "commands": [{"key": k, "label": COMMAND_LABELS[k]} for k in NOTE_COMMAND_KEYS],
                    "field_limits": FIELD_LIMITS,
                    "rx_fields": {k: {"label": v[0], "max": v[1]} for k, v in RX_FIELDS.items()},
                    "practice_names": sorted(practice),
                    "patient_placeholders": self._patient_placeholders(custom),
                    "menu_placeholders": self._menu_placeholders(enabled, custom),
                    "values": values,
                }
            )
        ]

    def _patient_placeholders(self, custom: dict[str, str]) -> dict[str, str]:
        """Every chart and custom patient placeholder, with its label."""
        return {**PATIENT_PLACEHOLDERS, **{name: name.replace("_", " ").capitalize() for name in custom}}

    def _menu_placeholders(self, enabled: list[str], custom: dict[str, str]) -> list[dict[str, str]]:
        """The patient placeholders the editor's Patient menu shows: the chart ones the practice chose, then custom ones."""
        labels = self._patient_placeholders(custom)
        return [{"name": name, "label": labels[name]} for name in enabled + sorted(custom)]

    def _metadata_keys(self) -> list[str]:
        """Patient metadata keys in use, for the custom placeholder picker, plus one extra when there are
        more than MAX_METADATA_KEYS so the app can say the list is cut off. Listing them reads the whole
        metadata table, so the list is kept in the plugin cache for 10 minutes and refreshed after a save."""
        cache = get_cache()
        keys = cache.get(METADATA_KEYS_CACHE)
        if keys is None:
            keys = list(PatientMetadata.objects.order_by("key").values_list("key", flat=True).distinct()[: MAX_METADATA_KEYS + 1])
            cache.set(METADATA_KEYS_CACHE, keys, timeout_seconds=600)
        return [str(k) for k in keys]

    # ---------- phrase writes ----------

    def _validate(self, body: dict[str, Any], scope: str, exclude: Phrase | None, me: int) -> tuple[dict[str, Any] | None, str]:
        code = str(body.get("code") or "").strip().lstrip(".")
        text = str(body.get("text") or "").strip()
        if not is_valid_code(code):
            return None, "Codes start with a lowercase letter, then letters and numbers, up to 64 characters."
        if not text:
            return None, "Write the text this phrase puts in the note."
        if len(text) > MAX_TEXT_LENGTH:
            return None, f"Phrase text is limited to {MAX_TEXT_LENGTH:,} characters."
        unknown = unknown_placeholders(text, known_names())
        if unknown:
            fix = "Add it on the Practice settings tab, or fix the spelling." if self._admin() else "Fix the spelling, or ask your Dot Phrases admins to add it as practice info."
            return None, f"{', '.join(unknown)} isn't a placeholder. {fix}"
        # None means every note command; a list names the commands. An empty list with a prescription
        # box checked means prescriptions only. Personal and practice phrases work the same way.
        use_in = body.get("use_in")
        if use_in is not None:
            if not isinstance(use_in, list) or any(k not in COMMAND_LABELS for k in use_in):
                return None, "Use in has a command this plugin doesn't work in."
            use_in = [k for k in NOTE_COMMAND_KEYS if k in use_in]
            if set(use_in) == DEFAULT_USE_IN:
                use_in = None
        rx_sig = bool(body.get("rx_sig"))
        rx_ntp = bool(body.get("rx_note_to_pharmacist"))
        if use_in == [] and not rx_sig and not rx_ntp:
            return None, "Select at least one place to use this phrase."
        for field, on in (("sig", rx_sig), ("note_to_pharmacist", rx_ntp)):
            message = rx_message(RX_FIELDS[field][0], RX_FIELDS[field][1], text) if on else ""
            if message:
                return None, message
        clash = Phrase.objects.filter(code=code, scope=scope, archived=False)
        if scope == "personal":
            clash = clash.filter(owner_id=me)
        if exclude is not None:
            clash = clash.exclude(dbid=exclude.dbid)
        existing = clash.first()
        if existing is not None:
            return None, f".{code} already exists{' in the practice list' if scope == 'practice' else ''}."
        return {"code": code, "text": text, "use_in": use_in, "rx_sig": rx_sig, "rx_note_to_pharmacist": rx_ntp}, ""

    def _can_change(self, phrase: Phrase, me: int) -> bool:
        if phrase.scope == "practice":
            return self._admin()
        return bool(phrase.owner_id == me)

    def _get_phrase(self) -> Phrase | None:
        try:
            dbid = int(self.request.path_params["phrase_id"])
        except (KeyError, TypeError, ValueError):
            return None
        phrase: Phrase | None = Phrase.objects.filter(dbid=dbid).select_related("owner").first()
        return phrase

    @api.post("/phrases")
    def create_phrase(self) -> list[Response | Effect]:
        me = self._me()
        if me is None:
            return _error("No signed-in staff member.", HTTPStatus.UNAUTHORIZED)
        body = self.request.json() or {}
        scope = "practice" if body.get("scope") == "practice" else "personal"
        if scope == "practice" and not self._admin():
            return _error("Only your practice's admins can make practice phrases.", HTTPStatus.FORBIDDEN)
        data, message = self._validate(body, scope, None, me)
        if data is None:
            return _error(message)
        phrase = Phrase.objects.create(scope=scope, owner_id=me, **data)
        return [JSONResponse({"phrase": _phrase_json(phrase, me, set(), None)}, status_code=HTTPStatus.CREATED)]

    @api.patch("/phrases/<phrase_id>")
    def update_phrase(self) -> list[Response | Effect]:
        me = self._me()
        phrase = self._get_phrase()
        if me is None or phrase is None:
            return _error("Phrase not found.", HTTPStatus.NOT_FOUND)
        if not self._can_change(phrase, me):
            return _error("You can't change this phrase.", HTTPStatus.FORBIDDEN)
        data, message = self._validate(self.request.json() or {}, phrase.scope, phrase, me)
        if data is None:
            return _error(message)
        phrase.code = data["code"]
        phrase.text = data["text"]
        phrase.use_in = data["use_in"]
        phrase.rx_sig = data["rx_sig"]
        phrase.rx_note_to_pharmacist = data["rx_note_to_pharmacist"]
        phrase.save()
        return [JSONResponse({"phrase": _phrase_json(phrase, me, favorite_ids(me), None)})]

    @api.delete("/phrases/<phrase_id>")
    def delete_phrase(self) -> list[Response | Effect]:
        """Delete a phrase for good. Owners delete their own; only admins delete practice phrases.

        Text already put into notes is unaffected. Stars and hides on the phrase go with it.
        """
        me = self._me()
        phrase = self._get_phrase()
        if me is None or phrase is None:
            return _error("Phrase not found.", HTTPStatus.NOT_FOUND)
        if not self._can_change(phrase, me):
            return _error("You can't delete this phrase.", HTTPStatus.FORBIDDEN)
        code = phrase.code
        PhraseFavorite.objects.filter(phrase_id=phrase.dbid).delete()
        PhraseHidden.objects.filter(phrase_id=phrase.dbid).delete()
        phrase.delete()
        return [JSONResponse({"deleted": code})]

    @api.post("/phrases/<phrase_id>/favorite")
    def toggle_favorite(self) -> list[Response | Effect]:
        me = self._me()
        phrase = self._get_phrase()
        usable = usable_phrases(me).get(phrase.code) if me is not None and phrase is not None else None
        if me is None or phrase is None or usable is None or usable.dbid != phrase.dbid:
            return _error("Phrase not found.", HTTPStatus.NOT_FOUND)
        existing = PhraseFavorite.objects.filter(staff_id=me, phrase_id=phrase.dbid)
        if existing.exists():
            existing.delete()
            return [JSONResponse({"favorite": False})]
        PhraseFavorite.objects.create(staff_id=me, phrase_id=phrase.dbid)
        return [JSONResponse({"favorite": True})]

    @api.post("/phrases/hide")
    def hide_phrases(self) -> list[Response | Effect]:
        """Hide or show practice phrases on the signed-in staff member's own list.

        Body: {"phrase_ids": [...], "hidden": true|false}. Only practice phrases can be hidden, and
        hiding only affects the list; typing a hidden phrase's code still works.
        """
        me = self._me()
        if me is None:
            return _error("No signed-in staff member.", HTTPStatus.UNAUTHORIZED)
        body = self.request.json() or {}
        raw_ids = body.get("phrase_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            return _error("Select at least one phrase.")
        try:
            wanted = {int(str(i)) for i in raw_ids}
        except (TypeError, ValueError):
            return _error("Select at least one phrase.")
        # Checked against all practice phrases, so one this person also has a copy of can still be hidden.
        practice = set(Phrase.objects.filter(scope="practice", archived=False, dbid__in=sorted(wanted)).values_list("dbid", flat=True))
        ids = sorted(wanted & practice)
        if not ids:
            return _error("Only practice phrases can be hidden.")
        if bool(body.get("hidden", True)):
            already = hidden_ids(me)
            PhraseHidden.objects.bulk_create([PhraseHidden(staff_id=me, phrase_id=i) for i in ids if i not in already])
        else:
            PhraseHidden.objects.filter(staff_id=me, phrase_id__in=ids).delete()
        return [JSONResponse({"phrase_ids": ids, "hidden": bool(body.get("hidden", True))})]

    @api.post("/phrases/<phrase_id>/used")
    def phrase_used(self) -> list[Response | Effect]:
        """Count a copy as a use, so Recently used reflects it."""
        me = self._me()
        phrase = self._get_phrase()
        usable = usable_phrases(me).get(phrase.code) if me is not None and phrase is not None else None
        if me is None or phrase is None or usable is None or usable.dbid != phrase.dbid:
            return _error("Phrase not found.", HTTPStatus.NOT_FOUND)
        record_use([phrase.dbid])
        return [JSONResponse({"ok": True})]

    @api.get("/notes/<note_id>/values")
    def note_values(self) -> list[Response | Effect]:
        """Values for a few chart or custom placeholders, for the panel editor's preview.

        The panel only gets the values it shows up front; this fills in others as they're typed.
        """
        me = self._me()
        if me is None:
            return _error("No signed-in staff member.", HTTPStatus.UNAUTHORIZED)
        note = Note.objects.filter(id=self.request.path_params.get("note_id")).select_related("patient", "provider", "location").defer(*NOTE_BLOBS).first()
        if note is None:
            return _error("Note not found.", HTTPStatus.NOT_FOUND)
        custom = custom_placeholders()
        allowed = set(PATIENT_PLACEHOLDERS) | set(custom)
        raw = str(self.request.query_params.get("names") or "")
        names = {n.strip().lower() for n in raw.split(",") if n.strip().lower() in allowed}
        if not names or len(names) > MAX_VALUE_NAMES:
            return _error("Ask for between 1 and 20 placeholders.")
        zone = remember_timezone(me, self.request.query_params.get("tz"))
        values = placeholder_values(note.patient, note, zone_name=zone, owner_dbid=me, needed=names, custom=custom)
        return [JSONResponse({"values": values})]

    # ---------- insert into the note ----------

    def _staged_rx(self, note_uuid: Any) -> Command | None:
        return (
            Command.objects.filter(note__id=note_uuid, schema_key__in=list(RX_SCHEMA_KEYS), state="staged")
            .order_by("-dbid")
            .first()
        )

    @api.post("/notes/<note_id>/insert")
    def insert(self) -> list[Response | Effect]:
        """Add a phrase to the note as a new command, or fill a staged prescription's Sig."""
        me = self._me()
        if me is None:
            return _error("No signed-in staff member.", HTTPStatus.UNAUTHORIZED)
        note = Note.objects.filter(id=self.request.path_params.get("note_id")).select_related("patient", "provider", "location").defer(*NOTE_BLOBS).first()
        if note is None:
            return _error("Note not found.", HTTPStatus.NOT_FOUND)
        state = CurrentNoteStateEvent.objects.filter(note__dbid=note.dbid).values_list("state", flat=True).first()
        if state not in EDITABLE_NOTE_STATES:
            return _error("This note can't be edited.", HTTPStatus.CONFLICT)
        body = self.request.json() or {}
        try:
            phrase_id = int(str(body.get("phrase_id")))
        except (TypeError, ValueError):
            return _error("Select a phrase.")
        phrase = next((p for p in usable_phrases(me).values() if p.dbid == phrase_id), None)
        if phrase is None:
            return _error("Phrase not found.", HTTPStatus.NOT_FOUND)
        target = str(body.get("target") or "")
        answers = [str(a) for a in (body.get("answers") or []) if isinstance(a, (str, int, float))]

        zone = remember_timezone(me, str(body.get("tz") or "") or None)
        values = placeholder_values(note.patient, note, zone_name=zone, owner_dbid=me, needed=placeholder_names([phrase.text]))
        if target in RX_FIELDS:
            if not phrase_fits_rx(phrase, target):
                return _error(f".{phrase.code} isn't set up for the {RX_FIELDS[target][0].lower()}.")
            rx_filled = fill(phrase.text, values, answers)
            issue, _ = rx_issue(RX_FIELDS[target][1], rx_filled.text)
            if issue:
                return _error(f".{phrase.code} can't go in the {rx_field_name(RX_FIELDS[target][0])}: {issue}.")
            rx = self._staged_rx(note.id)
            if rx is None:
                return _error("There's no prescription waiting in this note.", HTTPStatus.CONFLICT)
            if rx_filled.leftovers:
                # Anything left to fill in keeps the prescription from being reviewed or sent.
                cache = get_cache()
                existing = cache.get(leftovers_key(str(rx.id))) or []
                cache.set(leftovers_key(str(rx.id)), list(existing) + list(rx_filled.leftovers))
            record_use([phrase.dbid])
            command_class = RX_SCHEMA_KEYS[rx.schema_key]
            return [
                command_class(command_uuid=str(rx.id), **{target: rx_filled.text}).edit(),
                JSONResponse({"ok": True, "target": target}),
            ]

        if target not in INSERTABLE:
            return _error("Select where to add it.")
        if not works_in(phrase.use_in, target):
            return _error(f".{phrase.code} isn't set up for {COMMAND_LABELS[target]}.")
        filled = fill(phrase.text, values, answers)
        limit = FIELD_LIMITS.get(target)
        if limit is not None and len(filled.text) > limit:
            return _error(f".{phrase.code} is too long for {COMMAND_LABELS[target]}: {len(filled.text):,} characters, and the limit is {limit:,}.")
        command_uuid = str(uuid4())
        if filled.leftovers:
            get_cache().set(leftovers_key(command_uuid), list(filled.leftovers))
        record_use([phrase.dbid])
        # Instruct and Perform still need their instruction or procedure picked before recording.
        command = INSERTABLE[target](note_uuid=str(note.id), command_uuid=command_uuid, **{INSERT_FIELD[target]: filled.text})
        return [command.originate(), JSONResponse({"ok": True, "target": target})]

    # ---------- the app: my phrases, practice phrases, practice settings, import ----------

    @api.get("/admin/data")
    def admin_data(self) -> list[Response | Effect]:
        """Everything the app shows: the signed-in staff member's own phrases and the practice phrases.

        Open to all staff. Practice phrases come back for everyone, read-only unless is_admin is true.
        """
        me = self._me()
        if me is None:
            return _error("No signed-in staff member.", HTTPStatus.UNAUTHORIZED)
        values = practice_values()
        hidden = hidden_ids(me)
        rows = Phrase.objects.filter(Q(scope="practice") | Q(scope="personal", owner_id=me), archived=False).select_related("owner").order_by("code")
        mine: list[dict[str, Any]] = []
        phrases: list[dict[str, Any]] = []
        for p in rows:
            (phrases if p.scope == "practice" else mine).append(_phrase_json(p, me, set(), None, hidden))
        texts = [p["text"] for p in phrases]
        used = {name: sum(1 for t in texts if "{" + name + "}" in t) for name in values}
        custom = custom_placeholders()
        admin = self._admin()
        enabled = enabled_chart_placeholders()
        keys = self._metadata_keys() if admin else []
        return [
            JSONResponse(
                {
                    "chart_groups": [{"name": g, "items": [{"name": n, "label": label} for n, label in items]} for g, items in CHART_GROUPS],
                    "chart_enabled": enabled,
                    "custom": [{"name": n, "key": k, "used_in": sum(1 for t in texts if "{" + n + "}" in t)} for n, k in sorted(custom.items())],
                    # Admins pick a custom placeholder's source from the metadata keys already in use.
                    "metadata_keys": keys[:MAX_METADATA_KEYS],
                    "metadata_keys_capped": len(keys) > MAX_METADATA_KEYS,
                    "menu_placeholders": self._menu_placeholders(enabled, custom),
                    "is_admin": admin,
                    "admin_team": admin_team_name(self.secrets),
                    "mine": mine,
                    "phrases": phrases,
                    "values": [{"name": n, "value": v, "used_in": used[n]} for n, v in sorted(values.items())],
                    "allow_copy_text": bool(get_setting("allow_copy_text")),
                    "commands": [{"key": k, "label": COMMAND_LABELS[k]} for k in NOTE_COMMAND_KEYS],
                    "field_limits": FIELD_LIMITS,
                    "rx_fields": {k: {"label": v[0], "max": v[1]} for k, v in RX_FIELDS.items()},
                    "patient_placeholders": PATIENT_PLACEHOLDERS,
                }
            )
        ]

    @api.post("/admin/values")
    def save_value(self) -> list[Response | Effect]:
        if not self._admin():
            return _error("Only your practice's admins can change practice info.", HTTPStatus.FORBIDDEN)
        body = self.request.json() or {}
        name = str(body.get("name") or "").strip().lower()
        value = str(body.get("value") or "").strip()
        if not PRACTICE_NAME_RULE.fullmatch(name):
            return _error("Name it with lowercase letters and underscores, like clinic_fax.")
        if name in PATIENT_PLACEHOLDERS:
            return _error(f"{{{name}}} already comes from the chart.")
        if name in custom_placeholders():
            return _error(f"{{{name}}} is already a custom patient placeholder.")
        if len(value) > MAX_VALUE_LENGTH or "\n" in value:
            return _error(f"Values are one line, up to {MAX_VALUE_LENGTH} characters.")
        PracticeValue.objects.update_or_create(name=name, defaults={"value": value})
        return [JSONResponse({"name": name, "value": value})]

    @api.delete("/admin/values/<name>")
    def delete_value(self) -> list[Response | Effect]:
        if not self._admin():
            return _error("Only your practice's admins can change practice info.", HTTPStatus.FORBIDDEN)
        PracticeValue.objects.filter(name=str(self.request.path_params.get("name") or "")).delete()
        return [JSONResponse({"ok": True})]

    @api.post("/admin/settings")
    def save_settings(self) -> list[Response | Effect]:
        if not self._admin():
            return _error("Only your practice's admins can change settings.", HTTPStatus.FORBIDDEN)
        body = self.request.json() or {}
        if "allow_copy_text" in body:
            set_setting("allow_copy_text", bool(body["allow_copy_text"]))
        if "chart_placeholders" in body:
            chosen = body["chart_placeholders"]
            if not isinstance(chosen, list) or any(n not in PATIENT_PLACEHOLDERS for n in chosen):
                return _error("That isn't a chart placeholder.")
            set_setting("chart_placeholders", [n for n in PATIENT_PLACEHOLDERS if n in chosen])
        return [JSONResponse({"allow_copy_text": bool(get_setting("allow_copy_text")), "chart_enabled": enabled_chart_placeholders()})]

    @api.post("/admin/custom-placeholders")
    def save_custom_placeholder(self) -> list[Response | Effect]:
        """Add or change a custom patient placeholder: a name and the patient metadata key it reads."""
        if not self._admin():
            return _error("Only your practice's admins can change placeholders.", HTTPStatus.FORBIDDEN)
        body = self.request.json() or {}
        name = str(body.get("name") or "").strip().lower()
        key = str(body.get("key") or "").strip()
        if not PRACTICE_NAME_RULE.fullmatch(name):
            return _error("Name it with lowercase letters and underscores, like care_coordinator.")
        if name in PATIENT_PLACEHOLDERS:
            return _error(f"{{{name}}} already comes from the chart.")
        if name in practice_values():
            return _error(f"{{{name}}} is already practice info.")
        if not key or len(key) > 256:
            return _error("Select the patient detail it reads from.")
        custom = custom_placeholders()
        custom[name] = key
        set_setting("custom_placeholders", custom)
        get_cache().delete(METADATA_KEYS_CACHE)
        return [JSONResponse({"name": name, "key": key})]

    @api.delete("/admin/custom-placeholders/<name>")
    def delete_custom_placeholder(self) -> list[Response | Effect]:
        if not self._admin():
            return _error("Only your practice's admins can change placeholders.", HTTPStatus.FORBIDDEN)
        custom = custom_placeholders()
        custom.pop(str(self.request.path_params.get("name") or ""), None)
        set_setting("custom_placeholders", custom)
        return [JSONResponse({"ok": True})]

    def _check_import(self, raw: str) -> list[dict[str, Any]]:
        existing = set(Phrase.objects.filter(scope="practice", archived=False).values_list("code", flat=True))
        names = known_names()
        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        for line in [ln.strip() for ln in raw.splitlines() if ln.strip()][:MAX_IMPORT_LINES]:
            parts = line.split(",", 2)
            code = parts[0].strip().lstrip(".").lower() if parts else ""
            use = parts[1].strip() if len(parts) > 1 else ""
            text = parts[2].strip() if len(parts) > 2 else ""
            use_in: list[str] | None = []
            rx = {"rx_sig": False, "rx_note_to_pharmacist": False}
            why = ""
            if use.lower() in ("all", "any"):
                use_in = None
            else:
                for item in [u.strip().lower() for u in use.split("/") if u.strip()]:
                    if item == "sig":
                        rx["rx_sig"] = True
                    elif item == "note to pharmacist":
                        rx["rx_note_to_pharmacist"] = True
                    elif item in IMPORT_USE_IN and use_in is not None:
                        use_in.append(IMPORT_USE_IN[item])
                    else:
                        why = why or f'"{item}" isn\'t a place a phrase can go. Use All, Plan, HPI, Instruct, Perform, Sig, or Note to pharmacist.'
            if not is_valid_code(code):
                why = "The code has to start with a letter and use only letters and numbers."
            elif not text:
                why = why or "This line has no text."
            elif len(text) > MAX_TEXT_LENGTH:
                why = why or f"The text is over {MAX_TEXT_LENGTH:,} characters."
            elif use_in == [] and not any(rx.values()):
                why = why or "Say where it can go: All, or a command like Plan."
            if not why:
                unknown = unknown_placeholders(text, names)
                if unknown:
                    why = f"{', '.join(unknown)} isn't a placeholder."
                for field, key in (("sig", "rx_sig"), ("note_to_pharmacist", "rx_note_to_pharmacist")):
                    issue = rx_issue(RX_FIELDS[field][1], text)[0] if rx[key] else ""
                    if issue and not why:
                        why = f"Can't go in the {rx_field_name(RX_FIELDS[field][0])}: {issue}."
            if not why and code in existing:
                why = f"There's already a practice phrase .{code}, so this line is skipped."
            if not why and code in seen:
                why = f".{code} is in this list twice, so this line is skipped."
            if not why:
                # Only a line that will import claims its code, so a fixed copy below a broken line still imports.
                seen.add(code)
            rows.append({"code": code, "use_in": use_in, "text": text, "why": why, **rx})
        return rows

    @api.post("/admin/import/check")
    def import_check(self) -> list[Response | Effect]:
        if not self._admin():
            return _error("Only your practice's admins can import phrases.", HTTPStatus.FORBIDDEN)
        body = self.request.json() or {}
        return [JSONResponse({"rows": self._check_import(str(body.get("text") or ""))})]

    @api.post("/admin/import")
    def import_phrases(self) -> list[Response | Effect]:
        me = self._me()
        if me is None or not self._admin():
            return _error("Only your practice's admins can import phrases.", HTTPStatus.FORBIDDEN)
        body = self.request.json() or {}
        rows = [r for r in self._check_import(str(body.get("text") or "")) if not r["why"]]
        Phrase.objects.bulk_create(
            [
                Phrase(
                    code=r["code"],
                    text=r["text"],
                    scope="practice",
                    owner_id=me,
                    use_in=r["use_in"],
                    rx_sig=r["rx_sig"],
                    rx_note_to_pharmacist=r["rx_note_to_pharmacist"],
                    created_at=datetime.now(UTC),
                )
                for r in rows
            ]
        )
        return [JSONResponse({"imported": len(rows)})]
