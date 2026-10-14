"""The chart panel, the admin app, and the JSON API behind them.

Every request runs as the signed-in staff member (StaffSessionAuthMixin). Personal phrases can
only be changed by their owner. Practice phrases, practice info, settings, and import need the
staff member to be on the ADMIN_TEAM team; when that setting is empty, nobody can change them.
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
from canvas_sdk.v1.data import Command, Note
from canvas_sdk.v1.data.note import CurrentNoteStateEvent

from dot_phrases.catalog import (
    COMMAND_LABELS,
    FIELD_LIMITS,
    INSERT_FIELD,
    INSERTABLE,
    NOTE_COMMAND_KEYS,
    RX_FIELDS,
    RX_SCHEMA_KEYS,
)
from dot_phrases.handlers.note_events import leftovers_key
from dot_phrases.handlers.panel_button import EDITABLE_NOTE_STATES
from dot_phrases.library import (
    favorite_ids,
    get_setting,
    admin_team_name,
    hidden_ids,
    is_admin,
    placeholder_values,
    practice_values,
    record_use,
    set_setting,
    staff_dbid,
    staff_name,
    usable_phrases,
)
from dot_phrases.models import Phrase, PhraseFavorite, PhraseHidden, PracticeValue
from dot_phrases.text import (
    MAX_TEXT_LENGTH,
    PATIENT_PLACEHOLDERS,
    PRACTICE_NAME_RULE,
    fill,
    fill_ins,
    is_valid_code,
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

    @api.get("/icon.svg")
    def icon(self) -> list[Response | Effect]:
        return self._asset("assets/icon.svg", "image/svg+xml")

    @api.get("/admin/")
    def admin_page(self) -> list[Response | Effect]:
        if not self._admin():
            html = render_to_string("static/admin/not_admin.html") or ""
            return [HTMLResponse(html, status_code=HTTPStatus.FORBIDDEN)]
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
        note = Note.objects.filter(id=note_id).select_related("patient", "provider").defer(*NOTE_BLOBS).first() if note_id else None
        values = placeholder_values(note.patient if note else None, note)
        favorites = favorite_ids(me)
        hidden = hidden_ids(me)
        phrases = [_phrase_json(p, me, favorites, values, hidden) for p in usable_phrases(me).values()]
        rx_targets: list[str] = []
        if note is not None and self._staged_rx(note.id) is not None:
            rx_targets = list(RX_FIELDS)
        return [
            JSONResponse(
                {
                    "phrases": phrases,
                    "is_admin": self._admin(),
                    "admin_team": admin_team_name(self.secrets),
                    "allow_copy_text": bool(get_setting("allow_copy_text")),
                    "rx_targets": rx_targets,
                    "commands": [{"key": k, "label": COMMAND_LABELS[k]} for k in NOTE_COMMAND_KEYS],
                    "field_limits": FIELD_LIMITS,
                    "rx_fields": {k: {"label": v[0], "max": v[1]} for k, v in RX_FIELDS.items()},
                    "practice_names": sorted(practice_values()),
                    "patient_placeholders": PATIENT_PLACEHOLDERS,
                    "values": values,
                }
            )
        ]

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
        unknown = unknown_placeholders(text, set(practice_values()))
        if unknown:
            return None, f"{', '.join(unknown)} isn't a placeholder. Add it on the Practice settings tab, or fix the spelling."
        # Only practice phrases can be limited to certain commands; personal phrases work in any
        # note field.
        use_in = body.get("use_in") if scope == "practice" else None
        if use_in is not None:
            if not isinstance(use_in, list) or any(k not in COMMAND_LABELS for k in use_in):
                return None, "Use in has a command this plugin doesn't work in."
            use_in = [k for k in NOTE_COMMAND_KEYS if k in use_in]
        rx_sig = bool(body.get("rx_sig"))
        rx_ntp = bool(body.get("rx_note_to_pharmacist"))
        if use_in == [] and not rx_sig and not rx_ntp:
            return None, "Pick at least one place to use it, or choose All commands."
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
            return _error("Pick at least one phrase.")
        try:
            wanted = {int(str(i)) for i in raw_ids}
        except (TypeError, ValueError):
            return _error("Pick at least one phrase.")
        practice = {p.dbid for p in usable_phrases(me).values() if p.scope == "practice"}
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
        if me is None or phrase is None or usable_phrases(me).get(phrase.code) is None:
            return _error("Phrase not found.", HTTPStatus.NOT_FOUND)
        record_use([phrase.dbid])
        return [JSONResponse({"ok": True})]

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
        note = Note.objects.filter(id=self.request.path_params.get("note_id")).select_related("patient", "provider").defer(*NOTE_BLOBS).first()
        if note is None:
            return _error("Note not found.", HTTPStatus.NOT_FOUND)
        state = CurrentNoteStateEvent.objects.filter(note__dbid=note.dbid).values_list("state", flat=True).first()
        if state not in EDITABLE_NOTE_STATES:
            return _error("This note can't be edited.", HTTPStatus.CONFLICT)
        body = self.request.json() or {}
        try:
            phrase_id = int(str(body.get("phrase_id")))
        except (TypeError, ValueError):
            return _error("Pick a phrase.")
        phrase = next((p for p in usable_phrases(me).values() if p.dbid == phrase_id), None)
        if phrase is None:
            return _error("Phrase not found.", HTTPStatus.NOT_FOUND)
        target = str(body.get("target") or "")
        answers = [str(a) for a in (body.get("answers") or []) if isinstance(a, (str, int, float))]

        if target in RX_FIELDS:
            fits = phrase.rx_sig if target == "sig" else phrase.rx_note_to_pharmacist
            if not fits:
                return _error(f".{phrase.code} isn't set up for the {RX_FIELDS[target][0].lower()}.")
            issue, _ = rx_issue(RX_FIELDS[target][1], phrase.text)
            if issue:
                return _error(f".{phrase.code} can't go in the {rx_field_name(RX_FIELDS[target][0])}: {issue}.")
            rx = self._staged_rx(note.id)
            if rx is None:
                return _error("There's no prescription waiting in this note.", HTTPStatus.CONFLICT)
            record_use([phrase.dbid])
            command_class = RX_SCHEMA_KEYS[rx.schema_key]
            return [
                command_class(command_uuid=str(rx.id), **{target: phrase.text}).edit(),
                JSONResponse({"ok": True, "target": target}),
            ]

        if target not in INSERTABLE:
            return _error("Pick where to add it.")
        if phrase.use_in is not None and target not in phrase.use_in:
            return _error(f".{phrase.code} isn't set up for {COMMAND_LABELS[target]}.")
        filled = fill(phrase.text, placeholder_values(note.patient, note), answers)
        command_uuid = str(uuid4())
        if filled.leftovers:
            get_cache().set(leftovers_key(command_uuid), list(filled.leftovers))
        record_use([phrase.dbid])
        # Instruct and Perform still need their instruction or procedure picked before recording.
        command = INSERTABLE[target](note_uuid=str(note.id), command_uuid=command_uuid, **{INSERT_FIELD[target]: filled.text})
        return [command.originate(), JSONResponse({"ok": True, "target": target})]

    # ---------- admin: practice phrases, practice settings, import ----------

    @api.get("/admin/data")
    def admin_data(self) -> list[Response | Effect]:
        if not self._admin():
            return _error("Only your practice's admins can open this.", HTTPStatus.FORBIDDEN)
        me = self._me()
        values = practice_values()
        phrases = [
            _phrase_json(p, me, set(), None)
            for p in Phrase.objects.filter(scope="practice", archived=False).select_related("owner").order_by("code")
        ]
        used = {name: sum(1 for p in phrases if "{" + name + "}" in p["text"]) for name in values}
        return [
            JSONResponse(
                {
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
        return [JSONResponse({"allow_copy_text": bool(get_setting("allow_copy_text"))})]

    def _check_import(self, raw: str) -> list[dict[str, Any]]:
        existing = set(Phrase.objects.filter(scope="practice", archived=False).values_list("code", flat=True))
        names = set(practice_values())
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
