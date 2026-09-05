"""The whole HTTP surface of Fax Queue Inboxes.

Every route here is served by FaxQueueAPI, mixed with StaffSessionAuthMixin so
every request, including the page route itself, reaches a route only when it
carries a logged in staff session. That mixin ordering is Behaviour step 3 of
02-spec/SPEC.md and needs no override in this class, StaffSessionAuthMixin's
own authenticate method already does the whole job.

The two routes serving canvas-plugin-ui.css and canvas-plugin-ui.js sit here
too, added by the orchestrator rather than by the call that wrote the rest of
this module, because the same two files go into every plugin this pipeline
produces and their route form belongs to the UI skill rather than to this
plugin's own specification, which names neither route.
"""

from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any
from uuid import UUID

from django.db.models import Count, Prefetch

# django.utils.timezone is not importable inside the plugin sandbox, only
# django.utils.functional is on its allow list, so the current moment comes
# from datetime.now(UTC) instead. Same timezone aware instant, and UTC is
# what the platform's own default is anyway.

from canvas_sdk.effects import Effect
from canvas_sdk.effects.data_integration.assign_document_reviewer import AssignDocumentReviewer
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import IntegrationTask, IntegrationTaskReview, Staff, Team

from fax_queue_inboxes.models import FaxLabel, FaxRecord, PracticeLabel

# The five starter labels a practice sees on its first call to GET /labels,
# named in Behaviour step 12.
STARTER_LABELS = ("Referral", "Insurance", "Lab Result", "Prior Authorization", "Other")

# The stated page cap Behaviour step 9 asks for, with no number named there.
# Proposed by this module, shown on screen next to the count per that step.
TASK_PAGE_SIZE = 50

# The header Behaviour step 8 names, carrying the signed in staff member's id
# whenever the session belongs to a staff member.
_STAFF_HEADER = "canvas-logged-in-user-id"

# The deploy time cache bust CPA's own deploy-lite step requires, computed once
# at import rather than per request, so a page and the two design system
# assets it loads all carry the same version for the life of one deploy.
_CACHE_BUST = str(int(datetime.now(UTC).timestamp()))


class FaxQueueAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the dashboard page and every JSON route behind it.

    StaffSessionAuthMixin coming before SimpleAPI in the base list is what
    satisfies Behaviour step 3, every route including the page route itself
    reaches a handler only once the session carries a logged in staff member.
    """

    PREFIX = "/fax-queue-inboxes"

    # ------------------------------------------------------------------
    # Behaviour step 4, the dashboard page.
    # ------------------------------------------------------------------

    @api.get("/app")
    def get_app(self) -> list[Response | Effect]:
        """Render the dashboard page markup."""
        return [
            HTMLResponse(
                render_to_string(
                    "templates/dashboard.html", {"cache_bust": _CACHE_BUST}
                ),
                status_code=HTTPStatus.OK,
            )
        ]

    # ------------------------------------------------------------------
    # The two design system routes. Added by superproduct-build rather than by
    # an implementation call, because the same two files are copied into every
    # plugin this pipeline produces and the route form belongs to the UI skill
    # rather than to this plugin's own specification, which names neither.
    #
    # The plugin sandbox allows no os, no pathlib and no open, so the only way
    # to read a packaged file is render_to_string against the static path. Both
    # routes sit on this class rather than a second handler, because the
    # manifest declares exactly one API handler and the manifest is fixed.
    # ------------------------------------------------------------------

    @api.get("/canvas-plugin-ui.css")
    def plugin_ui_css(self) -> list[Response | Effect]:
        """Serve the design system stylesheet."""
        return [
            Response(
                render_to_string("static/canvas-plugin-ui.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/canvas-plugin-ui.js")
    def plugin_ui_js(self) -> list[Response | Effect]:
        """Serve the design system component bundle."""
        return [
            Response(
                render_to_string("static/canvas-plugin-ui.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
            )
        ]

    # ------------------------------------------------------------------
    # Behaviour steps 5 through 10, the three tabs over the fax queue.
    # ------------------------------------------------------------------

    @api.get("/tasks")
    def list_tasks(self) -> list[Response | Effect]:
        """Return one tab's worth of the pending fax queue, counted and capped."""
        tab = self.request.query_params.get("tab", "all")
        if tab not in ("unassigned", "my-team", "all"):
            tab = "all"

        base = self._base_task_queryset()

        # --- Why the two narrowed tabs decide on keys before they hydrate
        #
        # Whether a fax is unassigned, or belongs to one of my teams, cannot be
        # asked of the database in one query. The answer lives half in an SDK
        # review row and half in this plugin's own FaxRecord, which sits in a
        # separate namespace schema that no join reaches. So the decision is
        # made here rather than in SQL, and that is not the part worth
        # changing.
        #
        # What was worth changing is what the decision was made over. It used
        # to run over the whole pending queue hydrated in full, every task with
        # its provider joined and its reviews prefetched, plus a FaxRecord and
        # a FaxLabel query keyed to all of them, and only then cut to fifty. A
        # practice with thousands of faxes waiting paid for every one of them
        # on every load of either tab, which the database performance gate
        # raised on 2026-08-31.
        #
        # Now the narrowing runs over primary keys and nothing else, three
        # light queries returning integers, and only the fifty keys that
        # survive are hydrated. The count stays exact, because every key is
        # still examined, which is what a bounded window would have cost.
        if tab == "all":
            count = base.count()
            page_tasks = list(base.order_by("-created")[:TASK_PAGE_SIZE])
        else:
            matching_ids = self._matching_task_ids(tab)
            count = len(matching_ids)
            page_ids = matching_ids[:TASK_PAGE_SIZE]
            page_tasks = (
                list(base.filter(dbid__in=page_ids).order_by("-created")) if page_ids else []
            )
        page = self._resolve_tasks(page_tasks)

        return [
            JSONResponse(
                {
                    "tab": tab,
                    "count": count,
                    "cap": TASK_PAGE_SIZE,
                    "tasks": [
                        self._row(task, review, record, labels)
                        for task, review, record, labels in page
                    ],
                }
            )
        ]

    def _base_task_queryset(self) -> Any:
        """The base pending fax queryset every tab narrows from, per step 5."""
        return (
            IntegrationTask.objects.faxes()
            .pending_review()
            .select_related("service_provider")
            .prefetch_related(
                Prefetch(
                    "reviews",
                    queryset=IntegrationTaskReview.objects.filter(junked=False)
                    .exclude(reviewer__isnull=True, team_reviewer__isnull=True)
                    .select_related("reviewer", "team_reviewer"),
                    # No leading underscore on purpose. The plugin sandbox
                    # refuses to read any attribute whose name starts with
                    # one, so a Prefetch to_attr that carries it raises
                    # AttributeError at request time and nowhere else.
                    to_attr="authoritative_reviews",
                )
            )
        )

    def _resolve_tasks(
        self, tasks: list[Any]
    ) -> list[tuple[Any, Any, FaxRecord | None, list[dict[str, Any]]]]:
        """Pair every task with its review, its FaxRecord and its labels, per step 6.

        task.dbid is read straight off each task already held in memory, the
        inherited primary key named in Section 2 of the specification, so
        pairing a whole page of tasks with their FaxRecord rows costs one
        query rather than one query per task.

        The labels cost one more query for the whole page rather than one per
        fax, which is the same shape and the reason a fax carrying several
        labels did not reintroduce the N plus one the performance gate passed
        on. A FaxLabel whose PracticeLabel was deleted is skipped rather than
        raising, the same forgiveness criterion 18 already asks of the row.
        """
        keys = [task.dbid for task in tasks]
        fax_records = {
            record.task_id: record
            for record in FaxRecord.objects.filter(task_id__in=keys).select_related(
                "assigned_staff", "assigned_team"
            )
        }
        labels_by_task: dict[Any, list[dict[str, Any]]] = {}
        for row in (
            FaxLabel.objects.filter(task_id__in=keys)
            .select_related("label")
            .order_by("label__name")
        ):
            if row.label is None:
                continue
            labels_by_task.setdefault(row.task_id, []).append(
                {"id": row.label.dbid, "name": row.label.name}
            )
        resolved = []
        for task in tasks:
            review = self._authoritative_review(task)
            record = fax_records.get(task.dbid)
            resolved.append((task, review, record, labels_by_task.get(task.dbid, [])))
        return resolved

    def _authoritative_review(self, task: Any) -> IntegrationTaskReview | None:
        """The one committed, non junked review naming a reviewer, per step 6."""
        reviews = getattr(task, "authoritative_reviews", [])
        return reviews[0] if reviews else None

    def _pending_task_ids(self) -> list[Any]:
        """Every pending fax task's own key, newest first, and nothing else.

        Deliberately not the base queryset. That one joins the provider and
        prefetches the reviews so a row can be rendered, and none of that is
        wanted while the question is only which keys survive the narrowing.
        """
        return list(
            IntegrationTask.objects.faxes()
            .pending_review()
            .order_by("-created")
            .values_list("dbid", flat=True)
        )

    def _review_teams_by_task(self, task_ids: list[Any]) -> dict[Any, set[Any]]:
        """Each task carrying an authoritative review, against that review's team.

        The predicate is the one _base_task_queryset already prefetches by, not
        junked and naming at least one of a reviewer or a team, so the two
        agree by construction rather than by two readings of step 6.

        A set rather than one team, because a task carrying two authoritative
        reviews is a case Section 4 of the specification says cannot arise, and
        the old code silently picked whichever the prefetch returned first in
        an order nothing specified. Matching on any of them is a decision where
        there used to be an accident.
        """
        teams: dict[Any, set[Any]] = {}
        for task_id, team_id in (
            IntegrationTaskReview.objects.filter(task_id__in=task_ids, junked=False)
            .exclude(reviewer__isnull=True, team_reviewer__isnull=True)
            .values_list("task_id", "team_reviewer_id")
        ):
            teams.setdefault(task_id, set()).add(team_id)
        return teams

    def _record_teams_by_task(self, task_ids: list[Any]) -> dict[Any, Any]:
        """Each task this plugin's own record assigns, against the team it names.

        A record naming only a staff member lands here with a team of None,
        which is what keeps it out of every team tab while still counting as
        assigned, exactly as step 6 reads it.
        """
        return {
            task_id: team_id
            for task_id, team_id, staff_id in FaxRecord.objects.filter(
                task_id__in=task_ids
            ).values_list("task_id", "assigned_team_id", "assigned_staff_id")
            if team_id or staff_id
        }

    def _matching_task_ids(self, tab: str) -> list[Any]:
        """The keys one narrowed tab holds, in order, per steps 7 and 8."""
        ids = self._pending_task_ids()
        review_teams = self._review_teams_by_task(ids)
        record_teams = self._record_teams_by_task(ids)

        if tab == "unassigned":
            return [
                task_id
                for task_id in ids
                if task_id not in review_teams and task_id not in record_teams
            ]

        staff_id = self.request.headers.get(_STAFF_HEADER)
        my_team_ids = set(
            Team.objects.filter(members__id=staff_id).values_list("dbid", flat=True)
        )
        matching = []
        for task_id in ids:
            teams = review_teams.get(task_id)
            if teams is not None:
                # A committed review outranks the plugin's own record, per
                # criterion 7, so a fax it assigns elsewhere never falls
                # through to the record for a second chance at this tab.
                if teams & my_team_ids:
                    matching.append(task_id)
                continue
            if record_teams.get(task_id) in my_team_ids:
                matching.append(task_id)
        return matching

    def _row(
        self,
        task: Any,
        review: Any,
        record: FaxRecord | None,
        labels: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """One task's row shape, per step 10.

        The labels arrive already resolved by _resolve_tasks rather than being
        read off the record here, because a fax carries several of them and
        reading them per row is the N plus one the page query exists to avoid.
        A FaxLabel pointing at a deleted PracticeLabel is dropped there rather
        than reported empty here, which is what criterion 18 asks for.

        document_url travels on the row for the same reason the note does. The
        design system requires a new tab link to be an anchor rather than a
        script calling window.open, and an anchor needs its href before anybody
        clicks it, so the row carries the address the link route also answers
        with rather than the page fetching it per click.
        """
        return {
            "id": str(task.id),
            "type": task.type,
            "title": task.title,
            "created": task.created.isoformat(),
            "provider": (
                task.service_provider.full_name
                if task.service_provider_id
                else "Unknown Provider"
            ),
            "labels": labels,
            "assignee": self._assignee_name(review, record),
            # The note travels with the row rather than through a route of its
            # own. Nothing could read a note back before this, there is no GET
            # for it among the fourteen routes and the row shape did not carry
            # it, so a note saved correctly was invisible everywhere afterwards
            # and read as never having saved. Sending it here also means the
            # popover prefills with no request of its own and the row can say
            # that a note exists without anybody opening it. Notes are one
            # short field per fax, so the page of fifty carries no real weight.
            "note": record.note if record is not None else "",
            "document_url": f"/data-integration/{task.dbid}",
        }

    def _assignee_name(self, review: Any, record: FaxRecord | None) -> str | None:
        """The assignee name resolved per step 6, the committed review winning first.

        The two team branches wrap the name in str rather than returning the
        attribute straight. canvas_sdk ships no py.typed marker, so every SDK
        model reads as Any here and a bare team name return is an untyped value
        escaping a function that promises str or None. The two staff branches
        need no wrap because an f string is already str. This costs nothing at
        runtime, both fields are text columns, and it makes the declared return
        type true rather than merely unchecked.
        """
        if review is not None:
            if review.reviewer_id:
                return f"{review.reviewer.first_name} {review.reviewer.last_name}"
            if review.team_reviewer_id:
                return str(review.team_reviewer.name)
            return None
        if record is not None:
            if record.assigned_staff_id:
                return f"{record.assigned_staff.first_name} {record.assigned_staff.last_name}"
            if record.assigned_team_id:
                return str(record.assigned_team.name)
        return None

    # ------------------------------------------------------------------
    # Behaviour step 11, the escape hatch into the native screen.
    # ------------------------------------------------------------------

    @api.get("/tasks/<task_id>/link")
    def get_task_link(self) -> list[Response | Effect]:
        """Resolve a task's own database primary key and hand back the native url."""
        refusal = self._refuse_malformed_id()
        if refusal is not None:
            return [refusal]

        task_id = self.request.path_params["task_id"]
        task = self._get_task(task_id)
        if task is None:
            return [JSONResponse({"error": "Task not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse({"url": f"/data-integration/{task.dbid}"})]

    def _refuse_malformed_id(self) -> Response | None:
        """The refusal to answer with when a path parameter cannot be what it must be.

        One home for the rule rather than one check per route, because every
        route that reads an id reads it under the same two names and the shape
        of each is fixed by the column behind it. A `task_id` must be a UUID,
        since `IntegrationTask.id` is a `UUIDField`, and a `label_id` must be an
        integer, since `PracticeLabel.dbid` is a `BigAutoField`.

        Each route calls this for itself rather than the check being hidden in a
        lookup, because two of the eight never call a lookup at all. Both delete
        routes go straight to a filtered delete, so a guard living inside
        `_get_task` would have left those two raising.

        Why 400 rather than 404, per criterion 22. A well formed id that names
        no row is an ordinary miss and stays a 404. An id that could never name
        a row is a malformed request, and the two deserve different answers.

        Before this nothing validated either value, so Django's own field
        conversion is what failed, the exception left the route, and
        `SimpleAPIBase.compute` answered a bare 500 with an empty body. A
        mistyped address is not a server fault and should never have read as
        one.
        """
        params = self.request.path_params

        raw_task = params.get("task_id")
        if raw_task is not None:
            try:
                UUID(str(raw_task))
            except (ValueError, TypeError, AttributeError):
                return JSONResponse(
                    {"error": "A task id must be a UUID"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )

        raw_label = params.get("label_id")
        if raw_label is not None:
            try:
                int(raw_label)
            except (ValueError, TypeError):
                return JSONResponse(
                    {"error": "A label id must be a number"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )

        return None

    def _get_task(self, task_id: str) -> IntegrationTask | None:
        """The task named by a route's task_id path parameter, or None.

        task.dbid is read straight off the returned instance wherever this
        plugin needs the row's own inherited database primary key, per
        Section 2 of the specification. No route in this module reads that
        value through anything but this ordinary lookup.
        """
        return IntegrationTask.objects.filter(id=task_id).first()

    # ------------------------------------------------------------------
    # Behaviour step 12 and step 13, the practice's own label list.
    # ------------------------------------------------------------------

    @api.get("/labels")
    def list_labels(self) -> list[Response | Effect]:
        """Return every PracticeLabel, seeding the five starter labels first call.

        Each label also carries fax_count, per Behaviour step 24, the number of
        FaxLabel rows pointing at it, so a deletion confirmation in the modal
        can state its consequence before anybody touches the delete control.
        The count is read in one grouped query over every label id rather than
        one query per label read in a loop, which is the shape the database
        performance gate already made the task list learn once, and id and
        name keep the exact shape criterion 8 already covers.
        """
        if not PracticeLabel.objects.exists():
            for name in STARTER_LABELS:
                PracticeLabel.objects.get_or_create(name=name)
        labels = list(PracticeLabel.objects.order_by("name"))
        counts = {
            row["label_id"]: row["fax_count"]
            for row in FaxLabel.objects.filter(label_id__in=[label.dbid for label in labels])
            .values("label_id")
            .annotate(fax_count=Count("label_id"))
        }
        return [
            JSONResponse(
                {
                    "labels": [
                        {
                            "id": label.dbid,
                            "name": label.name,
                            "fax_count": counts.get(label.dbid, 0),
                        }
                        for label in labels
                    ]
                }
            )
        ]

    @api.post("/labels")
    def create_label(self) -> list[Response | Effect]:
        """Create a practice defined label, with no categorisation effect of any kind.

        Matches an existing PracticeLabel case insensitively before creating, per
        criterion 31 of the 2026-09-04 change request. get_or_create used to match
        the submitted name exactly, so referral typed through the row picker's new
        create offer would sit beside Referral as a second row, the near duplicate
        defect the change request's own reversal section names as the one risk
        still worth guarding against now that a row anybody can grow gets a create
        trigger back. A genuine miss is the only case that reaches create, so the
        practice's own capitalisation on the first row survives untouched.
        """
        name = self._json_body().get("name", "").strip()
        if not name:
            return [
                JSONResponse(
                    {"error": "A label name is required"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]
        label = PracticeLabel.objects.filter(name__iexact=name).first()
        if label is None:
            label = PracticeLabel.objects.create(name=name)
        return [
            JSONResponse({"id": label.dbid, "name": label.name}, status_code=HTTPStatus.CREATED)
        ]

    @api.put("/labels/<label_id>")
    def rename_label(self) -> list[Response | Effect]:
        """Rename an existing PracticeLabel."""
        refusal = self._refuse_malformed_id()
        if refusal is not None:
            return [refusal]

        label_id = self.request.path_params["label_id"]
        name = self._json_body().get("name", "").strip()
        if not name:
            return [
                JSONResponse(
                    {"error": "A label name is required"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]
        try:
            label = PracticeLabel.objects.get(dbid=label_id)
        except PracticeLabel.DoesNotExist:
            return [JSONResponse({"error": "Label not found"}, status_code=HTTPStatus.NOT_FOUND)]
        label.name = name
        label.save()
        return [JSONResponse({"id": label.dbid, "name": label.name})]

    @api.delete("/labels/<label_id>")
    def remove_label(self) -> list[Response | Effect]:
        """Remove a PracticeLabel."""
        refusal = self._refuse_malformed_id()
        if refusal is not None:
            return [refusal]

        label_id = self.request.path_params["label_id"]
        PracticeLabel.objects.filter(dbid=label_id).delete()
        return [Response(status_code=HTTPStatus.NO_CONTENT)]

    # ------------------------------------------------------------------
    # Behaviour step 14, labelling a fax.
    # ------------------------------------------------------------------

    def _labels_for(self, task: Any) -> list[dict[str, Any]]:
        """Every label currently on one fax, in the order the row shows them.

        Both label routes answer with this rather than with the one label they
        just touched, so the page patches a row from the server's own view of
        it instead of maintaining a second copy of the list in the browser.
        """
        return [
            {"id": row.label.dbid, "name": row.label.name}
            for row in FaxLabel.objects.filter(task_id=task.dbid)
            .select_related("label")
            .order_by("label__name")
            if row.label is not None
        ]

    @api.post("/tasks/<task_id>/label")
    def add_task_label(self) -> list[Response | Effect]:
        """Put one more label on a fax, per criterion 10.

        A fax carries several labels, so this adds rather than replaces, and
        the unique constraint on task and label is what makes it idempotent.
        A replayed request or a double click on the picker lands on the row
        that is already there instead of creating a second one.

        The label is written through label_id rather than through the relation,
        and that is a correctness fix rather than a style choice. The sandbox
        reads an attribute before it writes it, plugin_runner/sandbox.py in
        _safe_write calls getattr on the object first, and its None default does
        not catch what a Django foreign key descriptor raises on a dangling id,
        which is DoesNotExist rather than AttributeError. FaxLabel.label carries
        on_delete DO_NOTHING and criterion 18's own DELETE /labels route removes
        PracticeLabel rows, so a row here can genuinely hold a label_id whose
        row is gone.
        """
        refusal = self._refuse_malformed_id()
        if refusal is not None:
            return [refusal]

        task_id = self.request.path_params["task_id"]
        label_id = self._json_body().get("label_id")
        if not label_id:
            return [
                JSONResponse(
                    {"error": "A label_id is required"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]

        task = self._get_task(task_id)
        if task is None:
            return [JSONResponse({"error": "Task not found"}, status_code=HTTPStatus.NOT_FOUND)]

        try:
            label = PracticeLabel.objects.get(dbid=label_id)
        except PracticeLabel.DoesNotExist:
            return [JSONResponse({"error": "Label not found"}, status_code=HTTPStatus.NOT_FOUND)]

        FaxLabel.objects.get_or_create(
            task_id=task.dbid,
            label_id=label.dbid,
            defaults={"set_by": self._acting_staff(), "set_at": datetime.now(UTC)},
        )

        return [JSONResponse({"labels": self._labels_for(task)})]

    @api.delete("/tasks/<task_id>/label/<label_id>")
    def remove_task_label(self) -> list[Response | Effect]:
        """Take one label off a fax, per criterion 10.

        Removing a label the fax does not carry is not an error. The caller
        wanted that label gone and it is gone, so the response is the same
        list either way and the page needs no special case for a chip somebody
        dismissed twice.
        """
        refusal = self._refuse_malformed_id()
        if refusal is not None:
            return [refusal]

        task_id = self.request.path_params["task_id"]
        label_id = self.request.path_params["label_id"]

        task = self._get_task(task_id)
        if task is None:
            return [JSONResponse({"error": "Task not found"}, status_code=HTTPStatus.NOT_FOUND)]

        FaxLabel.objects.filter(task_id=task.dbid, label_id=label_id).delete()

        return [JSONResponse({"labels": self._labels_for(task)})]

    # ------------------------------------------------------------------
    # Behaviour step 15, the one note per fax.
    # ------------------------------------------------------------------

    @api.post("/tasks/<task_id>/note")
    def set_task_note(self) -> list[Response | Effect]:
        """Overwrite FaxRecord.note and its audit fields for one task."""
        refusal = self._refuse_malformed_id()
        if refusal is not None:
            return [refusal]

        task_id = self.request.path_params["task_id"]
        note = self._json_body().get("note", "")

        task = self._get_task(task_id)
        if task is None:
            return [JSONResponse({"error": "Task not found"}, status_code=HTTPStatus.NOT_FOUND)]

        fax_record, _ = FaxRecord.objects.get_or_create(task_id=task.dbid)
        fax_record.note = note
        fax_record.note_written_by = self._acting_staff()
        fax_record.note_written_at = datetime.now(UTC)
        fax_record.save()

        return [JSONResponse({"note": fax_record.note})]

    # ------------------------------------------------------------------
    # Behaviour step 16 and step 17, assigning and clearing a fax.
    # ------------------------------------------------------------------

    @api.post("/tasks/<task_id>/assign")
    def assign_task(self) -> list[Response | Effect]:
        """Set the plugin's own assignment and queue a native prefill suggestion.

        The AssignDocumentReviewer effect emitted here only ever queues a
        prefill on the native review form. It never commits an
        IntegrationTaskReview row itself, per Section 2 of the specification,
        so nothing in this response should be read as a committed assignment.
        """
        refusal = self._refuse_malformed_id()
        if refusal is not None:
            return [refusal]

        task_id = self.request.path_params["task_id"]
        body = self._json_body()
        team_id = body.get("team_id")
        staff_id = body.get("staff_id")
        if not team_id and not staff_id:
            return [
                JSONResponse(
                    {"error": "A team_id or a staff_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        task = self._get_task(task_id)
        if task is None:
            return [JSONResponse({"error": "Task not found"}, status_code=HTTPStatus.NOT_FOUND)]

        fax_record, _ = FaxRecord.objects.get_or_create(task_id=task.dbid)

        if team_id:
            team = Team.objects.filter(id=team_id).first()
            fax_record.assigned_team = team
            fax_record.assigned_staff = None
        else:
            staff = Staff.objects.filter(id=staff_id).first()
            fax_record.assigned_staff = staff
            fax_record.assigned_team = None

        fax_record.assigned_by = self._acting_staff()
        fax_record.assigned_at = datetime.now(UTC)
        fax_record.save()

        effect = AssignDocumentReviewer(
            document_id=task_id,
            reviewer_id=staff_id or None,
            team_id=team_id or None,
        )

        return [
            JSONResponse(
                {
                    "assigned_team": fax_record.assigned_team.name
                    if fax_record.assigned_team_id
                    else None,
                    "assigned_staff": (
                        f"{fax_record.assigned_staff.first_name} "
                        f"{fax_record.assigned_staff.last_name}"
                    )
                    if fax_record.assigned_staff_id
                    else None,
                }
            ),
            effect.apply(),
        ]

    @api.delete("/tasks/<task_id>/assign")
    def clear_task_assignment(self) -> list[Response | Effect]:
        """Clear the plugin's own assignment only.

        Nothing this SDK exports can reverse a commit to IntegrationTaskReview,
        so a native assignment already committed through Canvas's own screen
        keeps showing as authoritative per step 6 regardless of this call, per
        Behaviour step 17.
        """
        refusal = self._refuse_malformed_id()
        if refusal is not None:
            return [refusal]

        task_id = self.request.path_params["task_id"]
        task = self._get_task(task_id)
        if task is None:
            return [JSONResponse({"error": "Task not found"}, status_code=HTTPStatus.NOT_FOUND)]

        FaxRecord.objects.filter(task_id=task.dbid).update(assigned_team=None, assigned_staff=None)

        return [Response(status_code=HTTPStatus.NO_CONTENT)]

    # ------------------------------------------------------------------
    # Behaviour step 19, the teams and staff a fax may be assigned to.
    # ------------------------------------------------------------------

    @api.get("/assignees")
    def list_assignees(self) -> list[Response | Effect]:
        """Return every team and every active staff member a fax may go to.

        Both models are already declared in the Platform contract, so this
        route adds no new data reach, per Behaviour step 19. Each entry
        carries an id and a display name so the assign control can offer a
        choice rather than requiring somebody to know an id.

        Both ids are sent as strings on purpose rather than left as whatever
        type each model happens to declare. Team.id is a UUIDField and
        Staff.id is a CharField, so the two models are not interchangeable
        here, JSONResponse cannot serialise a UUID on its own. Sending both
        as strings makes the route's own handling explicit instead of
        depending on which field type a given model happens to carry, and it
        is what criterion 17 needs, since an id this route returns has to be
        accepted unchanged by POST /tasks/<id>/assign, whose own filters
        match a string id against either field without complaint.
        """
        teams = [
            {"id": str(team.id), "name": team.name}
            for team in Team.objects.order_by("name")
        ]
        staff = [
            {"id": str(member.id), "name": f"{member.first_name} {member.last_name}"}
            for member in Staff.objects.filter(active=True).order_by("first_name", "last_name")
        ]
        return [JSONResponse({"teams": teams, "staff": staff})]

    # ------------------------------------------------------------------
    # Shared helpers.
    # ------------------------------------------------------------------

    def _acting_staff(self) -> Staff | None:
        """The signed in staff member performing the current call, per step 8's header."""
        staff_id = self.request.headers.get(_STAFF_HEADER)
        if not staff_id:
            return None
        return Staff.objects.filter(id=staff_id).first()

    def _json_body(self) -> dict[str, Any]:
        """The request body as a dict, empty rather than raised on anything else."""
        try:
            body = self.request.json()
        except (ValueError, TypeError):
            return {}
        return body if isinstance(body, dict) else {}


# No __exports__ here on purpose. The SDK's own modules declare one and the
# plugin sandbox refuses it in plugin code, RestrictedPython rejecting the
# module outright with "Assignments to '__exports__' are not allowed". No
# shipped example plugin declares one either. The handler is found through
# CANVAS_MANIFEST.json rather than through a module export list.
