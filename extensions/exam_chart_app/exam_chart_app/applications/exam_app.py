"""ExamChartingApp — the 'Exam' tab on the note body.

`visible()` consults the `exam-note-types` secret (comma-separated keyword
list, case-insensitive substring match against the note-type name). Unset or
empty secret = visible on every note (fail-soft, matches intake_chart_app).
`handle()` returns a LaunchModalEffect with the stub HTML rendered from
templates/exam.html — form sections land in later checkpoints.
"""
from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import NoteApplication
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note
from logger import log

EXAM_NOTE_TYPES_SECRET = "exam-note-types"
ICD10_SEARCH_URL_SECRET = "icd10-search-url"

# Hostnames the icd10-search-url secret is NOT allowed to point at.
# Browser-side fetches without credentials still leak query terms to
# whichever URL receives them — restricting to public-ish hostnames
# prevents an operator from accidentally pointing at internal
# infrastructure or loopback that would silently break in production
# while looking fine in dev. Exact-match list keeps the rule simple.
_ICD10_URL_BLOCKED_HOSTS = frozenset({
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
})

# Private IPv4 prefixes blocked for the same reason. Substring-prefix
# matching on the literal first octet(s) is sufficient — operators
# pointing at internal mirrors should DNS-name them, not raw private IPs.
_ICD10_URL_BLOCKED_PREFIXES = (
    "10.", "192.168.",
    "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.",
    "172.24.", "172.25.", "172.26.", "172.27.",
    "172.28.", "172.29.", "172.30.", "172.31.",
    "169.254.",  # link-local
)


def _validate_icd10_search_url(value: object) -> str:
    """Return `value` if it's a safe-looking https URL, else `""`.

    Accepts ``object`` rather than ``str`` because the secret is read
    from ``self.secrets.get(...)`` which is loosely typed — defensive
    against a non-string value sneaking in from an admin UI edit.

    Rejected:
      - Non-string / empty / whitespace-only
      - Schemes other than https (no http, file, javascript, data, ftp)
      - Missing hostname
      - Loopback / unspecified hosts (localhost, 127.0.0.1, 0.0.0.0, ::1)
      - Private IPv4 ranges (10.x, 172.16-31.x, 192.168.x, 169.254.x)

    Caller logs the rejected value's reason and falls back to the
    JS-side public default (NLM Clinical Tables).

    Manual parsing (not ``urllib.parse.urlparse``) because the Canvas
    plugin sandbox blocks ``urlparse`` even though ``urlencode`` is
    allowed — per-name allowlists within ``urllib.parse``.
    """
    if not isinstance(value, str):
        return ""
    raw = value.strip()
    if not raw:
        return ""
    if not raw.lower().startswith("https://"):
        return ""
    # Extract host portion: chars between "https://" and the first of
    # "/" / "?" / "#" — i.e. before path / query / fragment.
    rest = raw[len("https://"):]
    if not rest:
        return ""
    end = len(rest)
    for sep in ("/", "?", "#"):
        idx = rest.find(sep)
        if 0 <= idx < end:
            end = idx
    host_with_port = rest[:end].lower()
    if not host_with_port:
        return ""
    # Strip optional `:port`; handle IPv6 bracket form `[::1]:port`.
    if host_with_port.startswith("["):
        bracket = host_with_port.find("]")
        if bracket < 0:
            return ""
        host = host_with_port[1:bracket]
    else:
        colon = host_with_port.rfind(":")
        host = host_with_port[:colon] if colon >= 0 else host_with_port
    if not host:
        return ""
    if host in _ICD10_URL_BLOCKED_HOSTS:
        return ""
    if any(host.startswith(p) for p in _ICD10_URL_BLOCKED_PREFIXES):
        return ""
    return raw


def _allowed_keywords(secret_value: str | None) -> list[str]:
    raw = (secret_value or "").strip()
    if not raw:
        return []
    return [kw.strip().lower() for kw in raw.split(",") if kw.strip()]


def _note_type_name(note_dbid: str | int | None) -> str:
    if not note_dbid:
        return ""
    try:
        note = Note.objects.select_related("note_type_version").get(dbid=note_dbid)
    except Note.DoesNotExist:
        return ""
    return (note.note_type_version.name or "").lower()


def is_exam_note(note_dbid: str | int | None, secret_value: str | None) -> bool:
    """Decide whether the Exam tab is visible on this note.

    No note context (i.e. Canvas is asking whether to show this entry in
    the global application drawer, or anywhere else outside a note) ->
    always False. Without this guard the tab would surface as a top-level
    app icon, which is wrong: this is a note tab, not a standalone app.

    Inside a note context, with an empty/unset `exam-note-types` secret,
    show on every note type. Otherwise: case-insensitive substring match
    between the note type's name and any comma-separated keyword in the
    secret.
    """
    if not note_dbid:
        return False
    keywords = _allowed_keywords(secret_value)
    if not keywords:
        return True
    name = _note_type_name(note_dbid)
    if not name:
        return False
    return any(kw in name for kw in keywords)


class ExamChartingApp(NoteApplication):
    """In-note tab rendering the guided Exam form (provider portion)."""

    NAME = "Exam"
    IDENTIFIER = "exam_chart_app__exam_tab"

    def visible(self) -> bool:
        return is_exam_note(
            self.event.context.get("note_id"),
            self.secrets.get(EXAM_NOTE_TYPES_SECRET),
        )

    def handle(self) -> list[Effect]:
        note_dbid = self.event.context.get("note_id")
        patient_id = self.event.context.get("patient_id", "") or str(
            self.event.target.id or ""
        )

        note_uuid = ""
        note_type_name = ""
        if note_dbid:
            try:
                note = Note.objects.select_related("note_type_version").get(dbid=note_dbid)
                note_uuid = str(note.id)
                note_type_name = note.note_type_version.name or ""
            except Note.DoesNotExist:
                log.warning(f"[ExamChartingApp] Note dbid={note_dbid} not found")

        api_base = "/plugin-io/api/exam_chart_app"
        raw_icd10_url = self.secrets.get(ICD10_SEARCH_URL_SECRET) or ""
        icd10_search_url = _validate_icd10_search_url(raw_icd10_url)
        if raw_icd10_url and not icd10_search_url:
            log.warning(
                f"[ExamChartingApp] icd10-search-url secret rejected "
                f"(must be https://, non-loopback, non-private). "
                f"Falling back to the public NLM default. value_len="
                f"{len(raw_icd10_url.strip())}"
            )
        exam_config: dict[str, str] = {
            "note_uuid": note_uuid,
            "patient_id": patient_id,
            "api_base": api_base,
        }
        if icd10_search_url:
            # Only emit when validation passed so the JS-side `|| default`
            # fallback fires for unset / rejected values rather than the
            # JS seeing an empty string and treating it as truthy.
            exam_config["icd10_search_url"] = icd10_search_url
        html = render_to_string(
            "templates/exam.html",
            {
                "note_uuid": note_uuid,
                "patient_id": patient_id,
                "note_type_name": note_type_name,
                "api_base": api_base,
                "exam_config": exam_config,
            },
        )
        return [
            LaunchModalEffect(
                target=LaunchModalEffect.TargetType.NOTE,
                content=html,
                title="Exam",
            ).apply()
        ]
