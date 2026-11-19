"""The review surface, the configuration screen, and the reads and writes behind them.

Staff session authenticated throughout, because the surface loads inside an
authenticated Canvas frame and the design system assets have to come back to that
same frame rather than to an anonymous request.

Every read recomputes from history rather than returning anything stored, so the
page a person is looking at is always the current answer and a tag they just
changed shows up on the next read with no repair step.

The configuration screen is gated twice, once when the page is rendered so its
markup never reaches a browser that may not have it, and again on the save route
so the gate cannot be walked around by calling the route directly. The second
check is the one that matters, the first only keeps the screen honest.
"""

import json
from http import HTTPStatus
from typing import Any

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note import RemoveAppointmentLabel
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.note import NoteStateChangeEvent
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.task import TaskLabel
from canvas_sdk.v1.data.team import Team

from attendance_policy_tracker.canvas.settings_store import NamespaceSettingsStore
from attendance_policy_tracker.canvas.source import CanvasVisitSource
from attendance_policy_tracker.canvas.states import CANCELLED_STATES, NO_SHOW_STATES
from attendance_policy_tracker.composition import build, config_from, to_raw
from attendance_policy_tracker.core.access import AccessList
from attendance_policy_tracker.core.attribution import is_correctable
from attendance_policy_tracker.core.clock import Clock
from attendance_policy_tracker.core.config import ALL_KINDS, ConfigError
from attendance_policy_tracker.core.contracts import ATTRIBUTIONS
from attendance_policy_tracker.core.view_preference import (
    set_show_non_counting,
    show_non_counting,
    truthy,
)
from attendance_policy_tracker.sweep import Sweep, union_patient_ids

from logger import log

# How far back the surface looks for patients worth showing. A person opening
# this wants the people who have moved recently, not every patient on the
# instance, and a name search reaches the rest.
RECENT_DAYS = 90

# The administration variable naming who may open the configuration screen.
ACCESS_VARIABLE = "config_access_staff_ids"

# How many options a picker offers. Enough to cover a real practice, capped so a
# misconfigured instance cannot turn one screen render into an unbounded read.
PICKER_LIMIT = 200

# How many patients the review surface returns in one read. This is not
# pagination, it is a ceiling. Before it existed, one load of this surface paid
# a full history recompute plus a name lookup for every patient who had moved
# in the recent window with nothing capping how many that could be, an audit
# costed that at roughly two to four thousand queries on a busy practice. The
# cap is applied after sorting by count, so a busy day still shows who is
# closest to a line rather than an arbitrary slice of whoever loaded first, and
# the response says plainly when it was truncated rather than looking complete.
PATIENTS_LIMIT = 300

# How many effects one evaluate call hands back in a single response. The
# sweep runs synchronously inside a staff request here, and returning every
# effect it found with no ceiling let one click ask for an unbounded batch.
# Anything past this cap is simply not emitted by this run, which is safe
# because the sweep is idempotent and either the schedule or the next
# evaluate call picks up whatever is left.
EFFECT_LIMIT = 200

# The only two directions the tag route understands. Anything else is refused
# rather than falling into the add branch by accident, which is what an
# unvalidated typo used to do.
TAG_ACTIONS = ("add", "remove")

# The moment this module was imported, stamped onto every asset URL the page
# asks for. Installing a new version reimports the module, so the value moves
# on every deploy and a browser still holding the previous stylesheet or
# component bundle is made to ask for the new one instead of serving what it
# already had. Taken from the clock rather than read from a file, because the
# plugin sandbox refuses filesystem access, and arrow is already the clock
# this module uses everywhere else.
_CACHE_BUST = f"{arrow.utcnow().int_timestamp}"


class AttendancePolicyAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the review surface, the configuration screen, and their reads."""

    PREFIX = "/app"

    def _parts(self) -> dict[str, Any]:
        """Build the policy and the engine from stored configuration."""
        clock = Clock()
        source = CanvasVisitSource()
        store = NamespaceSettingsStore()
        parts = build(store, clock=clock, source=source)
        parts["clock"] = clock
        parts["source"] = source
        parts["store"] = store
        return parts

    def _staff_key(self) -> str:
        """The key of the staff member making this request.

        Canvas sets this header itself on a valid session, so it is not something
        a caller can assert. It is the thirty two character staff key rather than
        the integer shown in the administration user list.
        """
        return f"{self.request.headers.get('canvas-logged-in-user-id') or ''}".strip()

    def _access(self) -> AccessList:
        """The configuration access list, from Canvas administration."""
        return AccessList(self.secrets.get(ACCESS_VARIABLE))

    def _may_configure(self) -> bool:
        """True when this staff member may open and save configuration."""
        return self._access().permits(self._staff_key())

    @api.get("/index")
    def index(self) -> list[Response]:
        """The review surface, with the configuration screen when permitted.

        The staff key is rendered for everybody and gated for nobody. It is not a
        secret, and showing it is what lets a person read their own identifier and
        hand it to an administrator. Gating it would deadlock the first grant.
        """
        return [
            HTMLResponse(
                render_to_string(
                    "templates/index.html",
                    {
                        "can_configure": self._may_configure(),
                        "staff_key": self._staff_key(),
                        "cache_bust": _CACHE_BUST,
                    },
                )
                or "",
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/canvas-plugin-ui.css")
    def plugin_ui_css(self) -> list[Response]:
        """The design system stylesheet."""
        return [
            Response(
                (render_to_string("static/canvas-plugin-ui.css") or "").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/canvas-plugin-ui.js")
    def plugin_ui_js(self) -> list[Response]:
        """The design system components."""
        return [
            Response(
                (render_to_string("static/canvas-plugin-ui.js") or "").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
            )
        ]

    @api.get("/policy")
    def policy(self) -> list[Response]:
        """The resolved policy, so the surface can label its own thresholds.

        The shared view preference rides along beside the policy rather than
        inside it, because it is not policy. The page already reads this on load
        and again on every live refresh, so returning it here is how a change one
        person makes reaches everybody else with no request of its own.
        """
        parts = self._parts()
        return [
            JSONResponse(
                {
                    "policy": parts["config"].as_dict(),
                    "show_non_counting": show_non_counting(parts["store"]),
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/preferences")
    def save_preferences(self) -> list[Response]:
        """Store the one view preference the whole clinic shares.

        Deliberately not gated behind the configuration permission, unlike every
        other stored setting and unlike the route below. The requirement is that
        anybody can move this switch and have it stay moved wherever they go, and
        gating it would leave most people unable to change what their own screen
        shows. The trade, accepted knowingly, is that this is the one setting a
        person changes for everybody.

        Written through the store directly rather than through the policy save,
        so it never reaches the validation that keeps policy coherent. It has
        nothing to be coherent with.
        """
        body = self._body()
        if "show_non_counting" not in body:
            return [
                JSONResponse(
                    {"error": "Nothing to save."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        value = truthy(body.get("show_non_counting"))
        set_show_non_counting(NamespaceSettingsStore(), value)
        log.info(
            f"attendance shared filter set to {value} "
            f"by staff {self._staff_key()}"
        )
        return [
            JSONResponse(
                {"ok": True, "show_non_counting": value},
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/config")
    def config(self) -> list[Response]:
        """Stored policy together with the options each picker offers."""
        if not self._may_configure():
            return [self._forbidden()]
        parts = self._parts()
        return [
            JSONResponse(
                {
                    "policy": parts["config"].as_dict(),
                    "options": {
                        "teams": self._teams(),
                        "appointment_labels": self._labels("appointments"),
                        "task_labels": self._labels("tasks"),
                        "kinds": list(ALL_KINDS),
                        "attributions": list(ATTRIBUTIONS),
                    },
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/config")
    def save_config(self) -> list[Response]:
        """Store submitted policy, refusing anything incoherent.

        Validated against the state that will actually exist rather than against
        the submission alone, so a change that is fine by itself but contradicts
        something already stored is caught before it is written.
        """
        if not self._may_configure():
            return [self._forbidden()]

        submitted = to_raw(self._body())
        if not submitted:
            return [
                JSONResponse(
                    {"error": "Nothing to save."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        store = NamespaceSettingsStore()
        merged = dict(store.read())
        merged.update(submitted)
        try:
            config_from(merged)
        except ConfigError as error:
            return [
                JSONResponse(
                    {"error": f"{error}"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        store.write(submitted)
        log.info(
            f"attendance policy saved by staff {self._staff_key()}, "
            f"{len(submitted)} settings written"
        )
        return [JSONResponse({"ok": True}, status_code=HTTPStatus.OK)]

    @api.get("/activity")
    def activity(self) -> list[Response]:
        """One day of attendance changes, newest first.

        The span arrives as two instants rather than as a date, because a day only
        means something in somebody's timezone and the browser is the only party
        that knows which one. The server does no calendar arithmetic at all.
        """
        raw_from = self.request.query_params.get("from")
        raw_to = self.request.query_params.get("to")
        if not raw_from or not raw_to:
            return [
                JSONResponse(
                    {"error": "A from and a to instant are both required."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        try:
            start = arrow.get(raw_from).datetime
            end = arrow.get(raw_to).datetime
        except Exception:
            return [
                JSONResponse(
                    {"error": "The from and to values must be timestamps."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        if end <= start:
            return [
                JSONResponse(
                    {"error": "The to instant must be after the from instant."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        parts = self._parts()
        source = parts["source"]
        watched = list(CANCELLED_STATES) + list(NO_SHOW_STATES)
        patient_ids = source.patients_with_changes_between(start, end, watched)
        # A reschedule writes a booked event rather than a cancellation, so a
        # day whose only activity was a late move needs this second path to
        # be found at all.
        moved_ids = source.patients_with_moves_between(start, end)
        patient_ids = union_patient_ids(patient_ids, moved_ids)

        incidents = parts["engine"].activity_between(start, end, patient_ids)
        # One name query for the whole day rather than one per row, see
        # _names_for.
        names = self._names_for([f"{incident.patient_id}" for incident in incidents])

        rows = []
        for incident in incidents:
            rows.append(
                {
                    "appointment_id": f"{incident.appointment_id}",
                    "patient_id": f"{incident.patient_id}",
                    "name": names.get(f"{incident.patient_id}", f"{incident.patient_id}"),
                    "kind": incident.kind,
                    "anchor": f"{incident.anchor}",
                    "occurred_at": f"{incident.occurred_at}",
                    "attribution": incident.attribution,
                    "by_patient_portal": incident.by_patient_portal,
                    "correctable": is_correctable(incident),
                    "pending": incident.pending,
                    "counts_at": f"{incident.counts_at}" if incident.counts_at else None,
                }
            )
        return [JSONResponse({"activity": rows}, status_code=HTTPStatus.OK)]

    @api.get("/patients")
    def patients(self) -> list[Response]:
        """Patients whose visits moved recently, with their current totals."""
        parts = self._parts()
        clock = parts["clock"]
        source = parts["source"]
        engine = parts["engine"]

        since = clock.minutes_before(clock.now(), RECENT_DAYS * 24 * 60)
        watched = list(CANCELLED_STATES) + list(NO_SHOW_STATES)
        patient_ids = source.patients_with_changes_since(since, watched)
        # So a patient whose only history is moves still appears on this
        # review surface rather than only on the day they happened.
        moved_ids = source.patients_with_moves_between(since, clock.now())
        patient_ids = union_patient_ids(patient_ids, moved_ids)

        # One name query for the whole page rather than one per patient, see
        # _names_for.
        names = self._names_for(patient_ids)

        rows = []
        for patient_id in patient_ids:
            total = engine.total_for(patient_id)
            rows.append(
                {
                    "patient_id": f"{patient_id}",
                    "name": names.get(f"{patient_id}", f"{patient_id}"),
                    "count": total.count,
                    "lines_reached": list(total.lines_reached),
                }
            )
        # Highest first, because the whole point of the surface is who is closest
        # to a line.
        rows = sorted(rows, key=lambda row: row["count"], reverse=True)
        truncated = len(rows) > PATIENTS_LIMIT
        # Cut after sorting, so the rows kept are the ones closest to a line
        # rather than an arbitrary slice of whoever was discovered first.
        rows = rows[:PATIENTS_LIMIT]
        return [
            JSONResponse(
                {"patients": rows, "truncated": truncated}, status_code=HTTPStatus.OK
            )
        ]

    @api.get("/incidents")
    def incidents(self) -> list[Response]:
        """One patient's incidents, recomputed now."""
        patient_id = self.request.query_params.get("patient")
        if not patient_id:
            return [
                JSONResponse(
                    {"error": "A patient is required."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        parts = self._parts()
        total = parts["engine"].total_for(patient_id)
        payload = total.as_dict()
        payload["name"] = self._name_of(patient_id)
        payload["clinic_tag"] = parts["config"].clinic_tag
        return [JSONResponse(payload, status_code=HTTPStatus.OK)]

    @api.post("/tag")
    def tag(self) -> list[Response | Effect]:
        """Add or remove the clinic tag on one cancellation.

        Both directions are one route because a correction is symmetrical from
        the desk's point of view. The total follows on the next read, so there is
        nothing else to update.
        """
        body = self._body()
        appointment_id = body.get("appointment_id")
        action = f"{body.get('action') or 'add'}"
        if not appointment_id:
            return [
                JSONResponse(
                    {"error": "An appointment is required."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        if action not in TAG_ACTIONS:
            # A typo here used to fall silently into the add branch, tagging an
            # appointment the caller meant to untag. Refusing anything outside
            # the two known actions is what stops that.
            return [
                JSONResponse(
                    {"error": "The action must be add or remove."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        if not self._correctable_cancellation(appointment_id):
            # An arbitrary or absent identifier used to reach the effect and no
            # op silently. A no show is refused here too, since nothing tagged
            # on a no show changes who it counts against, see is_correctable.
            return [
                JSONResponse(
                    {"error": "That appointment is not a correctable cancellation."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        parts = self._parts()
        config = parts["config"]
        actions = parts["actions"]

        if action == "remove":
            effect = RemoveAppointmentLabel(
                appointment_id=appointment_id,
                labels={config.clinic_tag},
            ).apply()
        else:
            effect = actions.tag_as_clinic(appointment_id)

        log.info(f"attendance tag {action} on appointment {appointment_id}")
        return [
            JSONResponse({"ok": True, "action": action}, status_code=HTTPStatus.OK),
            effect,
        ]

    @api.post("/evaluate")
    def evaluate(self) -> list[Response | Effect]:
        """Run the sweep now rather than waiting for the schedule.

        The same computation the schedule runs, so the two cannot drift. Useful
        from the desk after correcting a tag, and it is also the only way to
        exercise the sweep on an instance whose scheduler is not running.
        """
        parts = self._parts()
        sweep = Sweep(
            config=parts["config"],
            engine=parts["engine"],
            actions=parts["actions"],
            source=parts["source"],
            clock=parts["clock"],
        )
        result = sweep.run()
        effects: list[Effect] = result["effects"]
        truncated = len(effects) > EFFECT_LIMIT
        if truncated:
            # Loud on purpose. A synchronous staff request finding more than
            # the cap is worth knowing about even though the response still
            # answers, since it means this run left work for the schedule or
            # a repeat call to pick up.
            log.info(
                f"attendance evaluate found {len(effects)} effects, "
                f"returning only the first {EFFECT_LIMIT}"
            )
        emitted = effects[:EFFECT_LIMIT]
        summary: Response = JSONResponse(
            {
                "swept": result["swept"],
                "runs_tagged": result["runs_tagged"],
                "effects": len(emitted),
                "truncated": truncated,
            },
            status_code=HTTPStatus.OK,
        )
        outcome: list[Response | Effect] = [summary]
        return outcome + list(emitted)

    def _forbidden(self) -> Response:
        """The refusal used by both configuration routes."""
        return JSONResponse(
            {"error": "You do not have access to the attendance policy configuration."},
            status_code=HTTPStatus.FORBIDDEN,
        )

    def _teams(self) -> list[dict[str, str]]:
        """Teams a task can be addressed to."""
        return [
            {"id": f"{team.id}", "name": f"{team.name}"}
            for team in Team.objects.all()[:PICKER_LIMIT]
        ]

    def _labels(self, module: str) -> list[dict[str, str]]:
        """Active labels belonging to one Canvas module.

        Filtered by module because a label without the Appointments module never
        appears on an appointment card, so offering one would produce a tag
        nobody at the desk can see or remove.
        """
        rows = TaskLabel.objects.filter(active=True, modules__contains=[module]).order_by(
            "position"
        )[:PICKER_LIMIT]
        return [{"id": f"{row.name}", "name": f"{row.name}"} for row in rows]

    def _body(self) -> dict[str, Any]:
        """The request body as a mapping, empty when it is not usable."""
        raw = getattr(self.request, "body", None)
        if not raw:
            return {}
        try:
            if isinstance(raw, bytes):
                parsed = json.loads(raw.decode())
            else:
                parsed = json.loads(raw)
        except ValueError:
            return {}
        if isinstance(parsed, dict):
            return parsed
        return {}

    def _name_of(self, patient_id: str) -> str:
        """A patient's name for display, or their identifier when absent.

        For the single patient routes, where one query costs nothing. The page
        routes above batch instead, through _names_for, so a page of rows never
        pays one query per row.
        """
        return self._names_for([patient_id]).get(f"{patient_id}", f"{patient_id}")

    def _names_for(self, patient_ids: list[str]) -> dict[str, str]:
        """A name lookup for a whole page of patients, built from one query.

        Collecting the identifiers first and filtering once is what turns what
        used to be a query per row into a query per page. Only the two name
        fields are selected, since nothing else about the patient is needed
        here. A patient absent from the result, or carrying no readable name,
        is simply absent from the dictionary, and the caller falls back to the
        identifier the same way the single patient lookup always has.
        """
        if not patient_ids:
            return {}
        lookup: dict[str, str] = {}
        rows = Patient.objects.filter(id__in=set(patient_ids)).values(
            "id", "first_name", "last_name"
        )
        for row in rows:
            first = f"{row.get('first_name') or ''}".strip()
            last = f"{row.get('last_name') or ''}".strip()
            joined = f"{first} {last}".strip()
            if joined:
                # Named as a plain local before the write. The sandbox rewrites
                # a subscript assignment into a guarded write and names the key
                # from the source text, and an f-string is named __unknown__,
                # which trips its rule against keys beginning with an
                # underscore and refuses the assignment at runtime.
                key = f"{row['id']}"
                lookup[key] = joined
        return lookup

    def _correctable_cancellation(self, appointment_id: str) -> bool:
        """True when this appointment exists and is presently cancelled.

        Guards the tag route from an arbitrary or absent identifier, which used
        to reach the label effect and no op silently. A no show is refused too,
        matching is_correctable, since a no show is unambiguous and a label
        cannot move it off the patient.
        """
        # The note id alone, rather than select_related("note__current_state").
        # current_state is a view defined as DISTINCT ON (note_id) over the whole
        # note state history with no bound of its own, and the planner does not
        # push a note_id predicate into it, so joining it sorts and dedups every
        # state change row on the instance to read one note's state. Measured on a
        # small instance it was 0.388ms against 0.010ms for the point lookup
        # below, and the gap grows with every row a practice adds, on a route that
        # fires on each staff correction.
        note_id = (
            Appointment.objects.filter(id=appointment_id)
            .values_list("note_id", flat=True)
            .first()
        )
        if note_id is None:
            return False
        latest = (
            NoteStateChangeEvent.objects.filter(note_id=note_id)
            .order_by("-created", "-dbid")
            .values_list("state", flat=True)
            .first()
        )
        return latest in CANCELLED_STATES
