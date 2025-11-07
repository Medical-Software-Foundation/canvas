from http import HTTPStatus

import arrow
from django.db.models import Count, Q, F, Case, When, Value

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.effects.simple_api import Response, JSONResponse
from canvas_sdk.handlers.application import Application
from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Note, Command, Referral, ImagingOrder, Staff
from canvas_sdk.v1.data.note import NoteStates, NoteTypeCategories
from canvas_sdk.v1.data.task import TaskStatus
from logger import log


class MyApplication(Application):
    """An embeddable application that can be registered to Canvas."""

    def on_open(self) -> Effect:
        """Handle the on_open event."""
        return LaunchModalEffect(
            content=render_to_string("templates/encounter_list.html"),
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()


class EncounterListApi(StaffSessionAuthMixin, SimpleAPI):
    """API for encounter list functionality."""

    @api.get("/encounters")
    def get_encounters(self) -> list[Response | Effect]:
        """Get list of open encounters with pagination."""
        provider_ids = self.request.query_params.get("provider_ids")
        location_ids = self.request.query_params.get("location_ids")
        billable_only = self.request.query_params.get("billable_only") == "true"
        note_type_ids = self.request.query_params.get("note_type_ids")
        claim_queue_names = self.request.query_params.get("claim_queue_names")

        # Pagination parameters
        page = int(self.request.query_params.get("page", 1))
        page_size = int(self.request.query_params.get("page_size", 25))

        # Sorting parameters
        sort_by = self.request.query_params.get("sort_by", "created")
        sort_direction = self.request.query_params.get("sort_direction", "desc")

        note_queryset = Note.objects.exclude(current_state__state__in=(
            NoteStates.LOCKED,
            NoteStates.DELETED,
            NoteStates.DISCHARGED,
            NoteStates.SCHEDULING,
            NoteStates.BOOKED,
            NoteStates.CANCELLED,
            NoteStates.CONFIRM_IMPORT,
            NoteStates.REVERTED
        ))

        note_queryset = note_queryset.exclude(note_type_version__category__in=(NoteTypeCategories.MESSAGE,
                                                               NoteTypeCategories.LETTER,))

        if provider_ids:
            clean_ids = [pid.strip() for pid in provider_ids.split(',') if pid.strip()]
            if clean_ids:
                note_queryset = note_queryset.filter(provider__id__in=clean_ids)

        if location_ids:
            clean_location_ids = [lid.strip() for lid in location_ids.split(',') if lid.strip()]
            if clean_location_ids:
                note_queryset = note_queryset.filter(location__id__in=clean_location_ids)

        if note_type_ids:
            clean_note_type_ids = [nid.strip() for nid in note_type_ids.split(',') if nid.strip()]
            if clean_note_type_ids:
                note_queryset = note_queryset.filter(note_type_version__id__in=clean_note_type_ids)

        if claim_queue_names:
            clean_claim_queue_names = [cqn.strip() for cqn in claim_queue_names.split(',') if cqn.strip()]
            if clean_claim_queue_names:
                note_queryset = note_queryset.filter(claims__current_queue__name__in=clean_claim_queue_names)

        # Add annotations
        note_queryset = note_queryset.annotate(
            staged_commands_count=Count(
                'commands',
                filter=Q(commands__state__in=('staged', 'in_review',))
            )
        )

        if billable_only:
            note_queryset = note_queryset.filter(note_type_version__is_billable=True)

        # Apply sorting and pagination
        if sort_by == "delegatedOrders":
            # For delegated orders, calculate count first, then sort
            paginated_notes, total_count, total_pages = self._sort_and_paginate_delegated_orders(
                note_queryset, sort_direction, page, page_size
            )
        else:
            # For other columns, use normal database sorting
            paginated_notes, total_count, total_pages = self._sort_and_paginate_database(
                note_queryset, sort_by, sort_direction, page, page_size
            )

        # Convert queryset to encounter data
        encounters = []
        for note in paginated_notes:
            claim_queue = note.get_claim().current_queue.name if note.get_claim() else None

            delegated_commands = self._calculate_delegated_orders_count(note)

            try:
                note_title = note.note_type_version.name or "Untitled Note"
            except:
                note_title = "Untitled Note"

            encounter_data = {
                "id": str(note.id),
                "dbid": note.dbid,
                "patient_name": (f"{note.patient.first_name} ({note.patient.nickname}) {note.patient.last_name}" if note.patient.nickname else f"{note.patient.first_name} {note.patient.last_name}" if note.patient else "Unknown Patient"),
                "patient_id": str(note.patient.id) if note.patient else None,
                "patient_dob": arrow.get(note.patient.birth_date).format(
                    "MMM DD, YYYY") if note.patient and note.patient.birth_date else "Unknown",
                "provider": note.provider.credentialed_name if note.provider else "Unknown Provider",
                "provider_id": str(note.provider.id) if note.provider else None,
                "note_title": note_title,
                "dos": arrow.get(note.datetime_of_service).format(
                    "MMM DD, YYYY") if note.datetime_of_service else "Unknown",
                "dos_iso": note.datetime_of_service.isoformat() if note.datetime_of_service else None,
                "billable": self._get_billable_status(note),
                "uncommitted_commands": note.staged_commands_count,
                "delegated_orders": delegated_commands,
                "claim_queue": claim_queue,
                "location": note.location.full_name if note.location else "Unknown Location",
                "location_id": str(note.location.id) if note.location else None,
                "created": note.created.isoformat() if note.created else None,
            }
            encounters.append(encounter_data)

        return [JSONResponse({
            "encounters": encounters,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "page_size": page_size,
                "has_previous": page > 1,
                "has_next": page < total_pages,
            }
        }, status_code=HTTPStatus.OK)]

    @api.get("/providers")
    def get_providers(self) -> list[Response | Effect]:
        """Get list of providers who have notes."""
        logged_in_staff = self.request.headers["canvas-logged-in-user-id"]

        providers = [{"id": s.id, "name": s.credentialed_name}
                     for s in
                     Staff.objects.filter(active=True).order_by("first_name", "last_name")]


        return [JSONResponse({
            "logged_in_staff_id": logged_in_staff,
            "providers": providers
        }, status_code=HTTPStatus.OK)]

    @api.get("/locations")
    def get_locations(self) -> list[Response | Effect]:
        """Get list of practice locations that have notes."""

        locations = [{"id": str(n.location.id), "name": n.location.full_name}
                     for n in
                     Note.objects.filter(current_state__state__in=(NoteStates.NEW, NoteStates.UNLOCKED))
                     .filter(location__isnull=False)
                     .order_by("location__full_name", "location__id")
                     .distinct("location__id", "location__full_name")]

        return [JSONResponse({
            "locations": locations
        }, status_code=HTTPStatus.OK)]

    @api.get("/note_types")
    def get_note_types(self) -> list[Response | Effect]:
        """Get list of note types that have open encounters."""
        note_types = [{"id": str(n.note_type_version.id), "name": n.note_type_version.name}
                      for n in
                      Note.objects.exclude(current_state__state__in=(
                          NoteStates.LOCKED,
                          NoteStates.DELETED,
                          NoteStates.DISCHARGED,
                          NoteStates.SCHEDULING,
                          NoteStates.BOOKED,
                          NoteStates.CANCELLED,
                          NoteStates.CONFIRM_IMPORT,
                          NoteStates.REVERTED
                      ))
                      .exclude(note_type_version__category__in=(NoteTypeCategories.MESSAGE, NoteTypeCategories.LETTER))
                      .filter(note_type_version__isnull=False)
                      .order_by("note_type_version__name", "note_type_version__id")
                      .distinct("note_type_version__id", "note_type_version__name")
                      if n.note_type_version and n.note_type_version.name]

        return [JSONResponse({
            "note_types": note_types
        }, status_code=HTTPStatus.OK)]

    @api.get("/claim_queues")
    def get_claim_queues(self) -> list[Response | Effect]:
        """Get list of claim queue statuses."""
        # Return all possible claim queue statuses
        claim_queues = [
            {"name": "NeedsClinicianReview"},
            {"name": "NeedsCodingReview"},
            {"name": "QueuedForSubmission"},
            {"name": "FiledAwaitingResponse"},
            {"name": "RejectedNeedsReview"},
            {"name": "AdjudicatedOpenBalance"},
            {"name": "PatientBalance"},
            {"name": "ZeroBalance"},
            {"name": "Trash"},
            {"name": "Appointment"}
        ]

        return [JSONResponse({
            "claim_queues": claim_queues
        }, status_code=HTTPStatus.OK)]

    def _get_sort_fields(self, sort_by: str) -> list[str]:
        """Map frontend sort field names to database field names, returning a list of fields."""
        sort_mapping = {
            "patientName": ["patient__first_name", "patient__last_name"],
            "provider": ["provider__first_name", "provider__last_name"],
            "location": ["location__full_name"],
            "noteTitle": ["note_type_version__name"],
            "dos": ["datetime_of_service"],
            "billable": ["note_type_version__is_billable"],  # Will be handled specially in sorting logic
            "uncommittedCommands": ["staged_commands_count"],
            "delegatedOrders": ["created"],  # Handled specially in sorting logic
            "claimQueue": ["claims__current_queue__name"],
            "created": ["created"]
        }
        return sort_mapping.get(sort_by, ["created"])

    def _sort_and_paginate_delegated_orders(self, note_queryset, sort_direction, page, page_size):
        """Sort and paginate for delegated orders using Python calculation."""
        # Get all notes without pagination to calculate delegated orders
        all_notes = list(note_queryset)
        
        # Calculate delegated orders count for each note
        notes_with_delegated_count = []
        for note in all_notes:
            delegated_commands = self._calculate_delegated_orders_count(note)
            notes_with_delegated_count.append((note, delegated_commands))
        
        # Sort by delegated orders count
        notes_with_delegated_count.sort(
            key=lambda x: x[1], 
            reverse=(sort_direction == "desc")
        )
        
        # Extract the sorted notes
        sorted_notes = [note for note, _ in notes_with_delegated_count]
        
        # Apply pagination
        return self._apply_pagination(sorted_notes, page, page_size)

    def _sort_and_paginate_database(self, note_queryset, sort_by, sort_direction, page, page_size):
        """Sort and paginate using database sorting."""
        # Apply database sorting
        sort_fields = self._get_sort_fields(sort_by)
        
        # Handle billable field specially to treat None as False
        if sort_by == "billable":
            # Use Case/When to treat None as False for sorting
            billable_sort = Case(
                When(note_type_version__is_billable__isnull=True, then=Value(False)),
                default='note_type_version__is_billable'
            )
            if sort_direction == "desc":
                sort_fields = [billable_sort.desc(), "created"]
            else:
                sort_fields = [billable_sort.asc(), "created"]
        else:
            # Handle other fields normally
            if sort_direction == "desc":
                sort_fields = [f"-{field}" for field in sort_fields]
        
        note_queryset = note_queryset.order_by(*sort_fields)
        
        # Get total count
        total_count = note_queryset.count()
        
        # Apply pagination using the helper method
        paginated_notes, _, _ = self._apply_pagination(list(note_queryset), page, page_size)
        
        return paginated_notes, total_count, (total_count + page_size - 1) // page_size

    def _get_billable_status(self, note):
        """Safely get the billable status of a note, handling cases where note_type_version doesn't exist."""
        try:
            return note.note_type_version.is_billable
        except (AttributeError, Exception):
            return False

    def _calculate_delegated_orders_count(self, note):
        """Calculate the delegated orders count for a note using the exact same logic as display."""
        delegated_commands = 0
        # Fetch commands that can be delegated related to the note
        delegatable_commands = Command.objects.filter(note=note, schema_key__in=("imagingOrder", "refer",))
        for command in delegatable_commands:
            # Get the anchor object for the command
            anchor_object = command.anchor_object
            if not anchor_object:
                continue

            should_increase = False
            # If the command is delegated increment the count
            if isinstance(anchor_object, Referral) and anchor_object.forwarded:
                should_increase = True
            elif isinstance(anchor_object, ImagingOrder) and anchor_object.delegated:
                should_increase = True

            if should_increase and anchor_object.get_task_objects().filter(status=TaskStatus.OPEN).exists():
                delegated_commands = delegated_commands + 1
        
        return delegated_commands

    def _apply_pagination(self, items, page, page_size):
        """Apply pagination to a list of items."""
        total_count = len(items)
        total_pages = (total_count + page_size - 1) // page_size
        
        # Validate page number
        if page < 1:
            page = 1
        elif page > total_pages and total_pages > 0:
            page = total_pages
        
        # Calculate offset and apply slicing
        offset = (page - 1) * page_size
        paginated_items = items[offset:offset + page_size]
        
        return paginated_items, total_count, total_pages
