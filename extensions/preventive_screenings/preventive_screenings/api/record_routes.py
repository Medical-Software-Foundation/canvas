"""Serve one patient's screening record to the chart-side app, and take its writes.

Separate from ``ScreeningAdminAPI`` on purpose, because the access question is
a different one. The editor changes what the whole practice is measured
against, so it is gated to an ``ADMIN_STAFF_KEYS`` allowlist. This is a chart
view: any clinician looking after the patient needs it, and gating it to
administrators would make it useless to the people the brief was written for.

So it requires a valid staff session - ``StaffSessionAuthMixin``, which Canvas
backs by stripping ``canvas-logged-in-user-*`` headers from client requests and
setting them only for a real session - and nothing more. That is the same bar
Canvas applies to the chart this data already appears on, which is the right
comparison: everything here is derived from records the same staff member can
read directly.

It is **not** public. Without a session the mixin refuses before any of this
runs, which matters because the patient id is a query parameter.

**This endpoint now writes, and that reopens a question the security review
closed.** The accepted LOW finding - any staff member can read any patient's
record - was accepted on the grounds that it is a *read* of data the same
person can already see in the chart. A write is not that, and the acceptance
does not carry over by itself. What makes it defensible here instead:

* **Nothing is destroyed or hidden.** An attestation is merged with the chart,
  never substituted for it, and a more recent real result always wins. The
  worst a bad write can do is make a screening read as handled when it is not,
  and the next real result corrects it.
* **Every write carries its author, in the record rather than in a log.** The
  staff id goes on the row and the name is rendered beside the screening, so
  "up to date" always shows whose say-so it rests on. That is the chart's own
  standard for an attestation, and it is deliberately not the staff+patient
  audit log CLAUDE.md rules out.
* **Every write is reversible** from the same panel, by anyone who can see it.

The SDK offers no care-team or role check to tighten this with -
``StaffSessionAuthMixin``'s own docstring says it works "with no regard to
roles or any other permissioning schemes" - so a narrower rule is not
available, only a narrower audience. ⚠️ **Say this to the practice** alongside
the read finding.
"""

from datetime import UTC, date, datetime
from http import HTTPStatus
from typing import Any
from uuid import UUID

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, api
from canvas_sdk.handlers.simple_api.security import StaffSessionAuthMixin
from canvas_sdk.v1.data import Patient
from logger import log

from preventive_screenings.services.attestations import (
    KINDS,
    KIND_COMPLETED,
    KIND_ORDERED,
    recording_date,
    clear_attestation,
    parse_effective_date,
    record_attestation,
    staff_names,
)
from preventive_screenings.services.chart_section import RecordActions, build_section
from preventive_screenings.services.config_store import (
    DEFAULTS_CURRENT_AS_OF,
    MAX_TEXT_CHARS,
    active_screenings,
    carded_screenings,
    load_config,
)
from preventive_screenings.services.ordering import open_note_id, stage_order
from preventive_screenings.services.review import review_patient
from preventive_screenings.services.sweep_store import invalidate_patient

# Wrapped so the fragment the chart section would have used renders standalone
# in a modal. Everything is inline - the security review's "no third-party
# resources" finding applies here exactly as it does to the editor - including
# the script, which is a handful of lines rather than a dependency.
_PAGE = (
    "<!doctype html><html><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>Preventive screenings</title>"
    "<style>body{margin:0;padding:18px;background:#fff;"
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}"
    "h1{font-size:15px;margin:0 0 12px;color:#2b2f33}"
    # By id, because `.ps-msg{display:none}` in the section's own stylesheet is
    # rendered after this one and would otherwise win on equal specificity.
    "#ps-msg.ps-err{background:#fdecec;color:#8a1c12;display:block}</style></head>"
    "<body><h1>Preventive screenings</h1>"
    "<div class='ps-msg' id='ps-msg'></div>{body}{script}</body></html>"
)

# Posts the click, then reloads. Reloading rather than patching the DOM is
# deliberate: the page is three to six queries, and every status on it can move
# when one screening changes - a completion can take a screening from overdue
# to satisfied and reorder the whole list. Re-rendering from the server keeps
# one source of truth for what a screening says.
#
# `__PATIENT__` is substituted with the already-validated patient id, never
# read back out of the DOM.
_SCRIPT = """<script>
(function(){
  var P='__PATIENT__';
  // The date fields are set here, not server-side, because the server's
  // "today" is UTC and the provider's is not. At 9pm in Chicago the server is
  // already on tomorrow, so a server-rendered default offered a date the
  // provider had not reached yet - and a completion recorded a day late moves
  // the next due date with it.
  function localDate(){
    var d=new Date(), pad=function(n){return (n<10?'0':'')+n;};
    return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());
  }
  (function(){
    var local=localDate();
    var fields=document.querySelectorAll('.ps-when');
    for(var i=0;i<fields.length;i++){fields[i].value=local;fields[i].max=local;}
  })();
  function msg(t){var e=document.getElementById('ps-msg');e.textContent=t;e.className='ps-msg ps-err';}
  document.addEventListener('click',function(ev){
    var t=ev.target;
    if(!t||!t.closest)return;
    var b=t.closest('[data-act]');
    if(!b)return;
    var id=b.getAttribute('data-s'),act=b.getAttribute('data-act');
    var row=b.closest('.ps-row')||document;
    var when=row.querySelector('.ps-when'),sig=row.querySelector('.ps-sig');
    // Sent on every action: the server stamps `recorded_at` with this rather
    // than its own UTC date, so one click never produces two different days.
    var body={patient:P,screening_id:id,action:act,local_date:localDate()};
    if(when)body.effective_date=when.value;
    if(sig)body.signal=sig.value;
    b.disabled=true;
    fetch('/plugin-io/api/preventive_screenings/record/attest',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)
    }).then(function(r){return r.json();}).then(function(d){
      if(d&&d.success){location.reload();}
      else{b.disabled=false;msg((d&&d.error)||'Could not save that.');}
    }).catch(function(){b.disabled=false;msg('Could not save that.');});
  });
})();
</script>"""

_NO_PATIENT = (
    "<div style='color:#5b6770;font:13px sans-serif'>"
    "No patient in context, so there is nothing to show.</div>"
)

# Undo. Not one of the stored kinds - it removes the row rather than writing a
# third state - so it is named here rather than in `services.attestations`.
_ACTION_CLEAR = "clear"

# Everything a patient id may contain. A UUID is hex and dashes, so an id that
# passes this cannot carry a quote, an angle bracket, a backslash or anything
# else that could break out of the JS string literal the read route embeds it
# in - and **that is what makes it safe to embed**, rather than escaping,
# which is one forgotten call away from an XSS on a route any staff session can
# reach with any query string it likes.
_ID_CHARS = frozenset("0123456789abcdef-")


def _is_patient_id(raw: str) -> bool:
    """Whether this could be a Canvas patient id at all.

    Checked on both routes, for two reasons with the same answer. The write
    path needs it because ``Patient.id`` is a UUID column, so a malformed value
    raises inside the ORM rather than matching nothing - and an exception is a
    worse answer than a refusal. The read path needs it because of the comment
    above.
    """
    if not raw or not _ID_CHARS.issuperset(raw.lower()):
        return False
    try:
        UUID(raw)
    except (TypeError, ValueError):
        return False
    return True


class ScreeningRecordAPI(StaffSessionAuthMixin, SimpleAPI):
    """The patient's screening record, for the chart-side app."""

    PREFIX = ""

    def _staff_id(self) -> str:
        """The staff member whose session this is, for the attestation's author."""
        return str(self.request.headers.get("canvas-logged-in-user-id", ""))

    def _patient_id(self) -> str:
        """The patient the app was opened on."""
        raw: Any = self.request.query_params.get("patient", "")
        return str(raw or "").strip()

    def _parse_body(self) -> dict[str, Any]:
        """Parse the request body as a JSON object; anything else reads as empty.

        ``ValueError`` covers every way the SDK's ``json()`` fails on a bad
        body: base64, UTF-8 and JSON decoding errors all subclass it.
        """
        try:
            parsed = self.request.json()
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @api.get("/record/ui")
    def serve_record(self) -> list[Response | Effect]:
        """Every screening that applies to this patient, and when it was last done.

        Computed on request, so it is never stale - unlike the protocol cards,
        which are stored state and need a sweep to keep current.

        **Every tracked screening, carded or not.** The card toggle decides
        what goes on the chart summary; it has no bearing on what the record
        shows, because this costs nothing to keep current and there is no
        reason to hide a screening the practice tracks.
        """
        patient_id = self._patient_id()
        if not _is_patient_id(patient_id):
            # Covers an app opened outside a chart, and anything that is not a
            # patient id at all. The second is not merely tidiness: this id is
            # embedded in the page's script below, and refusing everything that
            # is not a UUID is what makes that safe.
            return [
                HTMLResponse(
                    _PAGE.replace("{body}", _NO_PATIENT).replace("{script}", ""),
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        screenings = active_screenings(load_config())
        today = datetime.now(UTC).date()
        review = review_patient(patient_id, screenings, today)

        # Only for the attestations actually on this page, so a record with
        # nothing attested - which is almost all of them - costs no extra read.
        names = staff_names(
            [row.attestation.recorded_by for row in review.rows if row.attestation]
        )
        body = build_section(
            review.rows, DEFAULTS_CURRENT_AS_OF, RecordActions(today=today, names=names)
        )
        page = _PAGE.replace("{body}", body).replace(
            "{script}", _SCRIPT.replace("__PATIENT__", patient_id)
        )
        return [HTMLResponse(page)]

    @api.post("/record/attest")
    def attest(self) -> list[Response | Effect]:
        """Record, or take back, what a staff member says about one screening.

        Three actions: the screening was done ("completed"), it does not apply
        to this patient ("not_applicable"), or undo whichever of those is
        stored ("clear").
        """
        # CSRF defence, before the body is parsed. The SDK parses a JSON body
        # whatever its declared type, so a cross-site `<form
        # enctype="text/plain">` could otherwise post one of these with a
        # clinician's session. A cross-origin `application/json` request needs
        # a CORS preflight a foreign site cannot pass.
        if self.request.content_type != "application/json":
            return [
                self._refuse(
                    "Content-Type must be application/json",
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                )
            ]

        body = self._parse_body()
        patient_id = str(body.get("patient") or "").strip()
        screening_id = str(body.get("screening_id") or "").strip()
        action = str(body.get("action") or "").strip()

        if action not in (*KINDS, _ACTION_CLEAR):
            return [self._refuse("Unknown action.", HTTPStatus.BAD_REQUEST)]

        doc = load_config()
        screening = next(
            (
                found
                for found in active_screenings(doc)
                if found["id"] == screening_id
            ),
            None,
        )
        if screening is None:
            # Including a screening that exists but is switched off. Attesting
            # against a rule the practice is not tracking would store a row
            # nothing reads and nobody can see to undo.
            return [
                self._refuse(
                    "That screening is not being tracked.", HTTPStatus.BAD_REQUEST
                )
            ]

        if not self._patient_exists(patient_id):
            # Checked rather than trusted. Without it, a session could write
            # rows against any string it liked, and nothing would ever read or
            # clean them up - storage growth with no ceiling and no owner.
            return [self._refuse("Unknown patient.", HTTPStatus.BAD_REQUEST)]

        today = datetime.now(UTC).date()
        # Everything below is dated in the provider's frame, not the server's.
        recorded = recording_date(body.get("local_date"), today)
        staged: list[Effect] = []
        stored: bool | None
        if action == _ACTION_CLEAR:
            stored = clear_attestation(patient_id, screening_id)
        elif action == KIND_ORDERED:
            staged, stored = self._order(patient_id, screening, recorded)
            if stored is None:
                return [
                    self._refuse(
                        "Open a note on this patient before ordering, so the "
                        "order has somewhere to go.",
                        HTTPStatus.CONFLICT,
                    )
                ]
        else:
            stored = self._record(body, patient_id, screening, action, today, recorded)
            if stored is None:
                return [
                    self._refuse(
                        "That date is not one we can record.", HTTPStatus.BAD_REQUEST
                    )
                ]

        if not stored:
            # 200 with success false, matching the editor: the request was
            # fine, the storage was not, and the page has to say so rather than
            # look like it worked.
            #
            # **A staged order still goes.** A provider who clicked "order" and
            # got an order is better served than one who got a refusal because
            # a custom-data table was unavailable - but the message has to say
            # which half failed, or the screening silently goes on reading as
            # due with nobody knowing why.
            return [
                self._refuse(
                    "The order was staged, but it could not be recorded - the "
                    "custom data namespace may not be set up, so this screening "
                    "will still read as due."
                    if staged
                    else "Could not save - the custom data namespace may not be set up.",
                    HTTPStatus.OK,
                ),
                *staged,
            ]

        return [
            JSONResponse({"success": True}),
            *staged,
            *self._refresh(doc, patient_id, today),
        ]

    def _order(
        self, patient_id: str, screening: dict, recorded: date
    ) -> tuple[list[Effect], bool | None]:
        """Stage this screening's order, and record that it is awaited.

        Returns ``(effects, stored)``, where ``stored`` is None when there is
        no open note to put the command in - the one failure this has that the
        other actions do not, and the only one the provider can fix themselves.

        **The order is recorded as placed at the moment it is staged**, not
        when it is signed, and that is a deliberate trade worth stating. The
        alternative is reading it back off the chart, and nothing there ties an
        order to a screening: `ImagingOrder.imaging` is an opaque string and
        `Referral` carries no code at all. So a provider who stages an order
        and then abandons it leaves a screening reading "awaiting result" that
        nobody is waiting on - bounded by `AWAITING_RESULT_DAYS`, visible with
        its date in the panel, and undoable from the same row.
        """
        if not screening["order_command"]:
            return [], False

        note_uuid = open_note_id(patient_id)
        if not note_uuid:
            return [], None

        effect = stage_order(screening, note_uuid)
        if effect is None:
            return [], False

        stored = record_attestation(
            patient_id,
            screening["id"],
            KIND_ORDERED,
            recorded,
            label=str(screening["order_comment"] or screening["name"])[:MAX_TEXT_CHARS],
            recorded_by=self._staff_id(),
            today=recorded,
        )
        # The command goes to the note whether or not our bookkeeping landed.
        # A provider who clicked "order" and got an order is better served than
        # one who got a refusal because a custom-data table was unavailable.
        return [effect], stored

    def _record(
        self,
        body: dict[str, Any],
        patient_id: str,
        screening: dict,
        action: str,
        today: date,
        recorded: date,
    ) -> bool | None:
        """Write one statement, or None if the date it carries is not usable.

        ``today`` is the server's, and bounds what a person may claim.
        ``recorded`` is the provider's, and is what gets stored and shown.
        """
        effective = (
            parse_effective_date(body.get("effective_date"), today)
            if action == KIND_COMPLETED
            else recorded
        )
        if effective is None:
            return None

        # Which way the screening was satisfied, so the right interval is
        # stored. Out-of-range or missing falls back to the first signal, which
        # is the one `cards.order_filter` already treats as the representative
        # one. A screening with a single completion never sends this.
        completions = screening["completions"]
        try:
            index = int(body.get("signal", 0))
        except (TypeError, ValueError):
            index = 0
        signal = completions[index] if 0 <= index < len(completions) else completions[0]

        return record_attestation(
            patient_id,
            screening["id"],
            action,
            effective,
            interval_quantity=int(signal["interval_quantity"]),
            interval_unit=str(signal["interval_unit"]),
            # Already capped in the config, but truncated again because this is
            # what reaches a fixed-width column.
            label=str(signal["label"] or "")[:MAX_TEXT_CHARS],
            recorded_by=self._staff_id(),
            today=recorded,
        )

    def _patient_exists(self, patient_id: str) -> bool:
        """Whether this is a patient on this instance."""
        if not _is_patient_id(patient_id):
            return False
        try:
            found: bool = Patient.objects.filter(id=patient_id).exists()
            return found
        except Exception as exc:  # pragma: no cover - defensive; the id is valid here
            log.warning(f"preventive_screenings: could not check the patient ({exc})")
            return False

    def _refresh(self, doc: dict[str, Any], patient_id: str, today: date) -> list[Effect]:
        """Get this patient's protocol cards back in step with what just changed.

        Two mechanisms on purpose, and the first is the one that actually
        does the work:

        1. **Return the recomputed cards from this response.** Measured
           working on a real chart on 2026-10-06: the card cleared inside a
           47-second window with no sweep activity, so nothing else could have
           written it. ⚠️ Nothing in the SDK documents this - `Response |
           Effect` being the return type is the only hint - so it is a measured
           fact about one Canvas version, not a guarantee.
        2. **Requeue the patient**, leaving the stored fingerprint stale, so the
           sweep rewrites the cards on its next tick whether or not (1) worked.

        (2) is kept now that (1) is confirmed, deliberately. It costs one UPDATE
        and one redundant card rewrite a minute later, and it buys cover for an
        effect being dropped on an instance or a version where (1) does not
        hold - which is precisely the failure this plugin has already shipped
        twice, and which is invisible from here.

        Neither runs for a practice that cards nothing, which is the default:
        there is no card to be out of step, because the record app computed the
        answer live.
        """
        carded = carded_screenings(doc)
        if not carded:
            return []
        invalidate_patient(patient_id, today)
        return review_patient(patient_id, carded, today).effects

    def _refuse(self, why: str, status: HTTPStatus) -> Response:
        """Tell the clinician their click did not land, and why.

        A write that silently does nothing is the failure this plugin has found
        in itself three times. The page shows this text rather than reloading.
        """
        return JSONResponse({"success": False, "error": why}, status_code=status)
