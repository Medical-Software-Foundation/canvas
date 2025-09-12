import json
import uuid
from datetime import datetime
from http import HTTPStatus
from typing import TypedDict

import arrow

from django.db.models import Case, When, Value, Q, CharField

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.effects.simple_api import Response, JSONResponse
from canvas_sdk.effects.task import AddTaskComment, AddTask
from canvas_sdk.handlers.application import Application
from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import ImagingOrder, LabOrder, Referral, PracticeLocation
from canvas_sdk.v1.data.staff import Staff
from canvas_sdk.v1.data.task import TaskStatus
from logger import log
from canvas_sdk.caching.plugins import get_cache


# priority
ROUTINE = "routine"
URGENT = "urgent"

# STATUS
UNCOMMITTED = "uncommitted"
DELEGATED = "delegated"
OPEN = "open/sent"
CLOSED = "closed"


class OrderingProvider(TypedDict):
    """Provider information for orders."""

    preferred_name: str
    id: str


class OrderNote(TypedDict):
    """Note information for orders."""

    title: str
    permalink: str


class OrderPayload(TypedDict):
    """Standardized order payload structure."""

    id: str
    patient_name: str
    patient_id: str
    dob: str
    status: str
    order: str
    ordered_date: str | None
    created_date: str | None
    priority: str
    sent_to: str
    permalink: str
    ordering_provider: OrderingProvider
    note: OrderNote
    type: str


class OrderTrackingApplication(Application):
    """An embeddable application that can be registered to Canvas."""

    def on_open(self) -> Effect:
        enable_task_comments = self.secrets.get("ENABLE_TASK_COMMENTS", "true") or "true"

        return LaunchModalEffect(
            content=render_to_string(
                "templates/worklist_orders.html",
                context={
                    "patientChartApplication": "order_tracking.applications.patient_order_tracking_app:PatientOrderTrackingApplication",
                    "enableTaskComments": enable_task_comments,
                },
            ),
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()


class OrderTrackingApi(StaffSessionAuthMixin, SimpleAPI):
    @api.get("/main.css")
    def get_main_css(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/main.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/main.js")
    def get_main_js(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/main.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    def _get_permalink_for_command(
        self, order: LabOrder | ImagingOrder | Referral, commandType: str
    ) -> str:
        return f"noteId={order.note.dbid}&commandId={order.dbid}&commandType={commandType}"

    def _get_note_from_order(self, order: LabOrder | ImagingOrder | Referral) -> OrderNote:
        try:
            note_title = order.note.note_type_version.name or "Untitled Note"
        except:
            note_title = "Untitled Note"

        date = (
            arrow.get(order.note.datetime_of_service)
            .to("local")
            .format("dddd, M/D/YY [at] h:mm A ZZZ")
        )
        provider_name = order.note.provider.credentialed_name

        return {
            "title": f"{note_title} on {date} with {provider_name}",
            "permalink": f"noteId={order.note.dbid}",
        }

    def _create_imaging_order_payload(self, imaging_order: ImagingOrder) -> OrderPayload:
        """Create a standardized payload for imaging order."""
        return {
            "id": str(imaging_order.id),
            "patient_name": imaging_order.patient.preferred_full_name,
            "patient_id": str(imaging_order.patient.id),
            "dob": arrow.get(imaging_order.patient.birth_date).format("YYYY-MM-DD"),
            "status": imaging_order.order_status,
            "order": imaging_order.imaging or "Imaging Order",
            "ordered_date": imaging_order.date_time_ordered.isoformat()
            if imaging_order.date_time_ordered
            else None,
            "created_date": imaging_order.created.isoformat() if imaging_order.created else None,
            "priority": imaging_order.priority or ROUTINE,
            "sent_to": imaging_order.imaging_center.full_name_and_specialty
            if imaging_order.imaging_center
            else "Not specified",
            "permalink": self._get_permalink_for_command(imaging_order, "imagingOrder"),
            "ordering_provider": {
                "preferred_name": imaging_order.ordering_provider.credentialed_name
                if imaging_order.ordering_provider
                else "Unknown Provider",
                "id": str(imaging_order.ordering_provider.id),
            },
            "note": self._get_note_from_order(imaging_order),
            "type": "Imaging",
        }

    def _create_lab_order_payload(self, lab_order: LabOrder) -> OrderPayload:
        """Create a standardized payload for lab order."""
        lab_tests = list(lab_order.tests.values_list("ontology_test_name", flat=True).all())
        return {
            "id": str(lab_order.id),
            "patient_name": lab_order.patient.preferred_full_name,
            "patient_id": str(lab_order.patient.id),
            "dob": arrow.get(lab_order.patient.birth_date).format("YYYY-MM-DD"),
            "status": lab_order.order_status,
            "order": ", ".join(lab_tests) or "Lab Order",
            "created_date": lab_order.created.isoformat() if lab_order.created else None,
            "ordered_date": lab_order.date_ordered.isoformat() if lab_order.date_ordered else lab_order.created.isoformat(),
            "sent_to": lab_order.ontology_lab_partner
            if lab_order.ontology_lab_partner
            else "Not specified",
            "permalink": self._get_permalink_for_command(lab_order, "labOrder"),
            "priority": ROUTINE,
            "ordering_provider": {
                "preferred_name": lab_order.ordering_provider.credentialed_name
                if lab_order.ordering_provider
                else "Unknown Provider",
                "id": str(lab_order.ordering_provider.id),
            },
            "note": self._get_note_from_order(lab_order),
            "type": "Lab",
        }

    def _create_referral_order_payload(self, referral_order: Referral) -> OrderPayload:
        """Create a standardized payload for referral order."""

        order = ["Referral"]
        if referral_order.service_provider and referral_order.service_provider.specialty:
            order.append(f"to {referral_order.service_provider.specialty}")

        return {
            "id": str(referral_order.id),
            "patient_name": referral_order.patient.preferred_full_name,
            "patient_id": str(referral_order.patient.id),
            "dob": arrow.get(referral_order.patient.birth_date).format("YYYY-MM-DD"),
            "order": " ".join(order) or "Referral",
            "status": referral_order.order_status,
            "created_date": referral_order.created.isoformat() if referral_order.created else None,
            "priority": referral_order.priority or ROUTINE,
            "sent_to": referral_order.service_provider.full_name_and_specialty
            if referral_order.service_provider
            else "Not specified",
            "permalink": self._get_permalink_for_command(referral_order, "referral"),
            "ordered_date": referral_order.date_referred.isoformat()
            if referral_order.date_referred
            else None,
            "ordering_provider": {
                "preferred_name": referral_order.note.provider.credentialed_name
                if referral_order.note.provider
                else "Unknown Provider",
                "id": str(referral_order.note.provider.id),
            },
            "note": self._get_note_from_order(referral_order),
            "type": "Referral",
        }

    @api.get("/providers")
    def providers(self) -> list[Response | Effect]:
        logged_in_staff = self.request.headers["canvas-logged-in-user-id"]

        # Get staff with imaging orders and lab orders separately, then combine
        imaging_staff_ids = set(
            Staff.objects.filter(imaging_orders__isnull=False)
            .values_list("id", flat=True)
            .distinct()
        )

        lab_staff_ids = set(
            Staff.objects.filter(lab_orders__isnull=False).values_list("id", flat=True).distinct()
        )

        # for referral, we have to get the note provider
        referral_note_provider_ids = (
            Referral.objects.values_list("note__provider__id", flat=True)
            .order_by("note__provider__id")
            .distinct("note__provider__id")
        )
        referral_staff_ids = set(
            Staff.objects.filter(id__in=referral_note_provider_ids)
            .values_list("id", flat=True)
            .distinct()
        )

        # Combine the sets to get all staff with either type of order
        all_ordering_staff_ids = imaging_staff_ids | lab_staff_ids | referral_staff_ids

        ordering_providers = [
            {
                "preferred_name": staff.credentialed_name,
                "id": str(staff.id),
            }
            for staff in Staff.objects.filter(id__in=all_ordering_staff_ids).order_by(
                "first_name", "last_name"
            )
        ]

        return [
            JSONResponse(
                {
                    "logged_in_staff_id": logged_in_staff,
                    "providers": ordering_providers,
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/locations")
    def locations(self) -> list[Response | Effect]:
        logged_in_staff = self.request.headers["canvas-logged-in-user-id"]

        locations = (
            PracticeLocation.objects.values("id", "full_name")
            .filter(active=True)
            .order_by("full_name")
        )
        locations = [
            {"name": location["full_name"], "value": str(location["id"])} for location in locations
        ]

        return [
            JSONResponse(
                {
                    "logged_in_staff_id": logged_in_staff,
                    "locations": locations,
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/orders")
    def orders(self) -> list[Response | Effect]:
        logged_in_staff = Staff.objects.values_list("id", flat=True).get(
            id=self.request.headers["canvas-logged-in-user-id"]
        )

        # Get query parameters for filtering and pagination
        provider_ids = self.request.query_params.get("provider_ids")
        if provider_ids:
            provider_ids = provider_ids.split(",")

        patient_id = self.request.query_params.get("patient_id")
        patient_name = self.request.query_params.get("patient_name")
        patient_dob = self.request.query_params.get("patient_dob")
        location_id = self.request.query_params.get("location")
        sent_to = self.request.query_params.get("sent_to")
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")

        status = self.request.query_params.get("status")
        order_types = self.request.query_params.get("types")
        priority = self.request.query_params.get("priority", "all")

        if order_types:
            order_types = [order_type.lower() for order_type in order_types.split(",")]

        if status:
            status = [s.lower() for s in status.split(",")]

        page = int(self.request.query_params.get("page", 1))
        page_size = int(self.request.query_params.get("page_size", 20))

        # Build base querysets with common fields for union - all must have an identical structure
        imaging_orders_queryset = (
            ImagingOrder.objects.select_related("patient", "ordering_provider")
            .annotate(
                order_status=Case(
                    When(
                        Q(results__isnull=True) & Q(delegated=True),
                        then=Value(DELEGATED),
                    ),
                    When(
                        Q(committer__isnull=True),
                        then=Value(UNCOMMITTED),
                    ),
                    When(
                        Q(committer__isnull=False)
                        & Q(results__isnull=True)
                        & Q(delegated=False),
                        then=Value(OPEN),
                    ),
                    default=Value(CLOSED),
                    output_field=CharField(),
                ),
                order_date=Case(
                    When(date_time_ordered__isnull=False, then="date_time_ordered"),
                    default="created",
                ),
                order_type=Value("imaging", output_field=CharField()),
            )
            .values(
                "id",
                "order_status",
                "order_date",
                "order_type",
                "patient__id",
                "patient__first_name",
                "patient__last_name",
                "patient__birth_date",
                "created",
            )
            .filter(
                deleted=False,
                entered_in_error__isnull=True,
            )
        )

        refer_queryset = (
            Referral.objects.select_related("patient", "note__provider")
            .annotate(
                order_status=Case(
                    When(
                        Q(reports__isnull=True) & Q(forwarded=True),
                        then=Value(DELEGATED),
                    ),
                    When(
                        Q(committer__isnull=True),
                        then=Value(UNCOMMITTED),
                    ),
                    When(
                        Q(committer__isnull=False)
                        & Q(reports__isnull=True)
                        & Q(forwarded=False),
                        then=Value(OPEN),
                    ),
                    default=Value(CLOSED),
                    output_field=CharField(),
                ),
                order_date=Case(
                    When(date_referred__isnull=False, then="date_referred"), default="created"
                ),
                order_type=Value("referral", output_field=CharField()),
            )
            .values(
                "id",
                "order_status",
                "order_date",
                "order_type",
                "patient__id",
                "patient__first_name",
                "patient__last_name",
                "patient__birth_date",
                "created",
            )
            .filter(
                deleted=False,
                entered_in_error__isnull=True,
            )
        )

        lab_orders_queryset = (
            LabOrder.objects.select_related("patient", "ordering_provider")
            .annotate(
                order_status=Case(
                    When(
                        Q(committer__isnull=True),
                        then=Value(UNCOMMITTED),
                    ),
                    When(
                        Q(committer__isnull=False) & Q(reports__isnull=True), then=Value(OPEN)
                    ),
                    default=Value(CLOSED),
                    output_field=CharField(),
                ),
                order_date=Case(
                    When(date_ordered__isnull=False, then="date_ordered"), default="created"
                ),
                order_type=Value("lab", output_field=CharField()),
            )
            .values(
                "id",
                "order_status",
                "order_date",
                "order_type",
                "patient__id",
                "patient__first_name",
                "patient__last_name",
                "patient__birth_date",
                "created",
            )
            .filter(
                deleted=False,
                entered_in_error__isnull=True,
            )
        )

        # Apply provider filter if specified
        if provider_ids:
            imaging_orders_queryset = imaging_orders_queryset.filter(
                ordering_provider__id__in=provider_ids
            )
            lab_orders_queryset = lab_orders_queryset.filter(ordering_provider__id__in=provider_ids)
            refer_queryset = refer_queryset.filter(note__provider__id__in=provider_ids)

        if patient_id:
            imaging_orders_queryset = imaging_orders_queryset.filter(patient__id=patient_id)
            lab_orders_queryset = lab_orders_queryset.filter(patient__id=patient_id)
            refer_queryset = refer_queryset.filter(patient__id=patient_id)

        if location_id:
            imaging_orders_queryset = imaging_orders_queryset.filter(note__location__id=location_id)
            lab_orders_queryset = lab_orders_queryset.filter(note__location__id=location_id)
            refer_queryset = refer_queryset.filter(note__location__id=location_id)

        if status:
            imaging_orders_queryset = imaging_orders_queryset.filter(order_status__in=status)
            refer_queryset = refer_queryset.filter(order_status__in=status)
            lab_orders_queryset = lab_orders_queryset.filter(order_status__in=status)
        # by default we exclude closed orders
        elif not status:
            imaging_orders_queryset = imaging_orders_queryset.exclude(order_status=CLOSED)
            refer_queryset = refer_queryset.exclude(order_status=CLOSED)
            lab_orders_queryset = lab_orders_queryset.exclude(order_status=CLOSED)

        if patient_name and not patient_id:

            def _full_name_filter(_patient_name: str):
                terms = _patient_name.strip().split()
                q_filter = Q()

                for term in terms:
                    term_q = (
                        Q(**{"patient__first_name__icontains": term})
                        | Q(**{"patient__last_name__icontains": term})
                        | Q(**{"patient__middle_name__icontains": term})
                    )
                    q_filter &= term_q

                return q_filter

            imaging_orders_queryset = imaging_orders_queryset.filter(
                _full_name_filter(patient_name)
            )
            lab_orders_queryset = lab_orders_queryset.filter(_full_name_filter(patient_name))
            refer_queryset = refer_queryset.filter(_full_name_filter(patient_name))

        if patient_dob:
            try:
                dob_date = datetime.strptime(patient_dob, "%Y-%m-%d").date()
                imaging_orders_queryset = imaging_orders_queryset.filter(
                    patient__birth_date=dob_date
                )
                lab_orders_queryset = lab_orders_queryset.filter(patient__birth_date=dob_date)
                refer_queryset = refer_queryset.filter(patient__birth_date=dob_date)
            except ValueError:
                pass  # Invalid date format, skip filter

        if sent_to:
            imaging_orders_queryset = imaging_orders_queryset.filter(
                Q(imaging_center__first_name__icontains=sent_to)
                | Q(imaging_center__last_name__icontains=sent_to)
                | Q(imaging_center__specialty__icontains=sent_to)
                | Q(imaging_center__practice_name__icontains=sent_to)
            )
            lab_orders_queryset = lab_orders_queryset.filter(
                ontology_lab_partner__icontains=sent_to
            )
            refer_queryset = refer_queryset.filter(
                Q(service_provider__first_name__icontains=sent_to)
                | Q(service_provider__last_name__icontains=sent_to)
                | Q(service_provider__specialty__icontains=sent_to)
                | Q(service_provider__practice_name__icontains=sent_to)
            )

        if date_from:
            try:
                from_date = datetime.strptime(date_from, "%Y-%m-%d").date()
                imaging_orders_queryset = imaging_orders_queryset.filter(
                    date_time_ordered__gte=from_date
                )
                lab_orders_queryset = lab_orders_queryset.filter(date_ordered__gte=from_date)
                refer_queryset = refer_queryset.filter(date_referred__gte=from_date)
            except ValueError:
                pass

        if date_to:
            try:
                to_date = datetime.strptime(date_to, "%Y-%m-%d").date()
                imaging_orders_queryset = imaging_orders_queryset.filter(
                    date_time_ordered__lte=to_date
                )
                lab_orders_queryset = lab_orders_queryset.filter(date_ordered__lte=to_date)
                refer_queryset = refer_queryset.filter(date_referred__lte=to_date)
            except ValueError:
                pass

        if priority == "urgent":
            # Filter for urgent orders only
            imaging_orders_queryset = imaging_orders_queryset.filter(priority="Urgent")
            refer_queryset = refer_queryset.filter(priority="Urgent")
            # Lab orders don't have a priority, so exclude them for urgent
            lab_orders_queryset = lab_orders_queryset.none()  # Empty queryset
        elif priority == "routine":
            # Filter for routine orders
            imaging_orders_queryset = imaging_orders_queryset.exclude(priority="Urgent")
            refer_queryset = refer_queryset.exclude(priority="Urgent")
            # Lab orders are always routine (keep as is)

        # Handle type filtering
        include_imaging = order_types is None or "imaging" in order_types
        include_lab = order_types is None or "lab" in order_types
        include_referrals = order_types is None or "referral" in order_types

        # Create unified queryset using union
        querysets_to_union = []

        if include_imaging:
            querysets_to_union.append(imaging_orders_queryset)
        if include_lab:
            querysets_to_union.append(lab_orders_queryset)
        if include_referrals:
            querysets_to_union.append(refer_queryset)

        if not querysets_to_union:
            return [
                JSONResponse(
                    {
                        "logged_in_staff_id": logged_in_staff,
                        "orders": [],
                        "pagination": {
                            "current_page": 1,
                            "page_size": page_size,
                            "total_count": 0,
                            "total_pages": 0,
                            "has_next": False,
                            "has_previous": False,
                        },
                    },
                    status_code=HTTPStatus.OK,
                )
            ]

        # Union all querysets and order by common field
        unified_queryset = querysets_to_union[0]
        for qs in querysets_to_union[1:]:
            unified_queryset = unified_queryset.union(qs)

        unified_queryset = unified_queryset.order_by("-order_date")

        # Calculate counts for urgent/routine
        total_count = unified_queryset.count()

        if priority == "urgent":
            urgent_order_count = total_count
            routine_order_count = 0
        elif priority == "routine":
            urgent_order_count = 0
            routine_order_count = total_count
        else:
            # For mixed priority, we need to count separately
            imaging_urgent_count = (
                imaging_orders_queryset.filter(priority="Urgent").count() if include_imaging else 0
            )
            referral_urgent_count = (
                refer_queryset.filter(priority="Urgent").count() if include_referrals else 0
            )
            urgent_order_count = imaging_urgent_count + referral_urgent_count
            routine_order_count = total_count - urgent_order_count

        if total_count == 0:
            return [
                JSONResponse(
                    {
                        "logged_in_staff_id": logged_in_staff,
                        "orders": [],
                        "pagination": {
                            "current_page": 1,
                            "page_size": page_size,
                            "total_count": 0,
                            "total_pages": 0,
                            "has_next": False,
                            "has_previous": False,
                        },
                    },
                    status_code=HTTPStatus.OK,
                )
            ]

        # Calculate pagination metadata
        total_pages = (total_count + page_size - 1) // page_size
        start_index = (page - 1) * page_size
        end_index = start_index + page_size

        # Get paginated results from a unified queryset
        paginated_orders = unified_queryset[start_index:end_index]

        # Collect IDs by type for efficient bulk fetching
        imaging_ids = []
        lab_ids = []
        referral_ids = []

        for order in paginated_orders:
            if order["order_type"] == "imaging":
                imaging_ids.append(order["id"])
            elif order["order_type"] == "lab":
                lab_ids.append(order["id"])
            elif order["order_type"] == "referral":
                referral_ids.append(order["id"])

        # Bulk fetch full objects to maintain order from a unified queryset
        imaging_objects = {}
        lab_objects = {}
        referral_objects = {}

        if imaging_ids:
            imaging_objects = {
                obj.id: obj
                for obj in ImagingOrder.objects.select_related(
                    "patient",
                    "ordering_provider",
                    "imaging_center",
                    "note__provider",
                    "note__note_type_version",
                )
                .annotate(
                    order_status=Case(
                        When(
                            Q(results__isnull=True) & Q(delegated=True),
                            then=Value(DELEGATED),
                        ),
                        When(
                            Q(committer__isnull=True),
                            then=Value(UNCOMMITTED),
                        ),
                        When(
                            Q(committer__isnull=False)
                            & Q(results__isnull=True)
                            & Q(delegated=False),
                            then=Value(OPEN),
                        ),
                        default=Value(CLOSED),
                        output_field=CharField(),
                    )
                )
                .filter(id__in=imaging_ids)
            }
        if lab_ids:
            lab_objects = {
                obj.id: obj
                for obj in LabOrder.objects.select_related(
                    "patient", "ordering_provider", "note__provider", "note__note_type_version"
                )
                .prefetch_related("tests")
                .annotate(
                    order_status=Case(
                        When(
                            Q(committer__isnull=True),
                            then=Value(UNCOMMITTED),
                        ),
                        When(
                            Q(committer__isnull=False) & Q(reports__isnull=True), then=Value(OPEN)
                        ),
                        default=Value(CLOSED),
                        output_field=CharField(),
                    )
                )
                .filter(id__in=lab_ids)
            }
        if referral_ids:
            referral_objects = {
                obj.id: obj
                for obj in Referral.objects.select_related(
                    "patient", "service_provider", "note__provider", "note__note_type_version"
                )
                .annotate(
                    order_status=Case(
                        When(
                            Q(reports__isnull=True) & Q(forwarded=True),
                            then=Value(DELEGATED),
                        ),
                        When(
                            Q(committer__isnull=True),
                            then=Value(UNCOMMITTED),
                        ),
                        When(
                            Q(committer__isnull=False)
                            & Q(reports__isnull=True)
                            & Q(forwarded=False),
                            then=Value(OPEN),
                        ),
                        default=Value(CLOSED),
                        output_field=CharField(),
                    ),
                )
                .filter(id__in=referral_ids)
            }

        orders_data = []

        for order in paginated_orders:
            if order["order_type"] == "imaging" and (imaging := imaging_objects.get(order["id"])):
                orders_data.append(self._create_imaging_order_payload(imaging))
            elif order["order_type"] == "lab" and (lab := lab_objects.get(order["id"])):
                orders_data.append(self._create_lab_order_payload(lab))
            elif order["order_type"] == "referral" and (
                referral := referral_objects.get(order["id"])
            ):
                orders_data.append(self._create_referral_order_payload(referral))

        return [
            JSONResponse(
                {
                    "logged_in_staff_id": logged_in_staff,
                    "orders": orders_data,
                    "count": {"urgent": urgent_order_count, "routine": routine_order_count},
                    "pagination": {
                        "current_page": page,
                        "page_size": page_size,
                        "total_count": total_count,
                        "total_pages": total_pages,
                        "has_next": page < total_pages,
                        "has_previous": page > 1,
                    },
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/task-comments")
    def get_task_comments(self) -> list[Response | Effect]:
        order_type = self.request.query_params.get("order_type")

        if not order_type:
            return [
                JSONResponse(
                    {"error": "order_type is required"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]

        try:
            comments_data = []
            task_list = []

            # Handle referral orders using the task_list property
            if order_type.lower() == "referral":
                referral_id = self.request.query_params.get("referral_id")

                if not referral_id:
                    return [
                        JSONResponse(
                            {"error": "referral_id is required for referral orders"},
                            status_code=HTTPStatus.BAD_REQUEST,
                        )
                    ]

                try:
                    referral = Referral.objects.get(id=referral_id, deleted=False)
                    task_list = list(referral.get_task_objects().filter(status=TaskStatus.OPEN))

                except Referral.DoesNotExist:
                    return [
                        JSONResponse(
                            {"error": "Referral not found"}, status_code=HTTPStatus.NOT_FOUND
                        )
                    ]

            # Handle imaging orders using the task_list property
            elif order_type.lower() == "imaging":
                imaging_id = self.request.query_params.get("imaging_id")

                if not imaging_id:
                    return [
                        JSONResponse(
                            {"error": "imaging_id is required for imaging orders"},
                            status_code=HTTPStatus.BAD_REQUEST,
                        )
                    ]

                try:
                    imaging_order = ImagingOrder.objects.get(id=imaging_id, deleted=False)
                    task_list = list(
                        imaging_order.get_task_objects().filter(status=TaskStatus.OPEN)
                    )

                except ImagingOrder.DoesNotExist:
                    return [
                        JSONResponse(
                            {"error": "Imaging order not found"}, status_code=HTTPStatus.NOT_FOUND
                        )
                    ]

            # For lab orders, we could implement similar logic if they get the task_list property
            elif order_type.lower() == "lab":
                # For now, return empty comments for lab orders
                # This could be extended when lab orders get the task_list property
                pass

            if task_list:
                # Get the last (most recent) task
                last_task = task_list[-1] if task_list else None

                if last_task:
                    # Get comments for this task
                    task_comments = (
                        last_task.comments.all().order_by("created").select_related("creator")
                    )

                    for comment in task_comments:
                        comments_data.append(
                            {
                                "id": str(comment.id),
                                "text": comment.body,
                                "author": comment.creator.credentialed_name
                                if comment.creator
                                else "Unknown",
                                "date": comment.created.strftime("%Y-%m-%d %H:%M"),
                                "task_id": str(last_task.id),
                            }
                        )

            return [JSONResponse({"comments": comments_data}, status_code=HTTPStatus.OK)]

        except Exception as e:
            return [
                JSONResponse(
                    {"error": f"Failed to load comments: {str(e)}"},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

    @api.post("/task-comments")
    def add_task_comment(self) -> list[Response | Effect]:
        json_body = json.loads(self.request.body)
        patient_id = json_body.get("patient_id")
        comment = json_body.get("comment")
        task_id = json_body.get("task_id")
        order_type = json_body.get("order_type")
        order_id = json_body.get("order_id")
        log.info(f"Received task comment data: {json_body}")

        effects: list[Effect] = []
        if not task_id:
            task_id = uuid.uuid4()
            linked_task_type = None
            title = ""
            if order_type.lower() == "imaging":
                linked_task_type = AddTask.LinkableObjectType.IMAGING
                order = ImagingOrder.objects.get(id=order_id)
                title = (
                    f"Complete patient's imaging order to {order.imaging}"
                    if order.imaging
                    else "Complete patient's imaging order"
                )
            elif order_type.lower() == "referral":
                linked_task_type = AddTask.LinkableObjectType.REFERRAL
                order = Referral.objects.get(id=order_id)
                title = (
                    f"Refer patient to {order.service_provider.full_name_and_specialty}"
                    if order.service_provider
                    else "Complete patient referral"
                )

            if not linked_task_type:
                return [
                    JSONResponse(
                        {"error": f"Invalid order type {order_type}"},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]

            effects.append(
                AddTask(
                    id=task_id,
                    author_id=self.request.headers["canvas-logged-in-user-id"],
                    title=title,
                    patient_id=patient_id,
                    linked_object_id=order_id,
                    linked_object_type=linked_task_type,
                ).apply()
            )

        effects.extend(
            [
                AddTaskComment(
                    task_id=task_id,
                    body=comment,
                    author_id=self.request.headers["canvas-logged-in-user-id"],
                ).apply(),
                JSONResponse({}, status_code=HTTPStatus.OK),
            ]
        )

        return effects


class StaffFilterAPI(StaffSessionAuthMixin, SimpleAPI):
    cache_key = "FILTERS"

    @api.post("/filter")
    def create_filters(self) -> list[Response | Effect]:
        logged_in_staff = self.request.headers["canvas-logged-in-user-id"]

        cache = get_cache()
        # get current filters
        filters = cache.get(self.cache_key, default={})
        user_filters = filters.get(logged_in_staff) or []

        # get filters passed by in the URL
        new_filters = self.request.json()
        user_filters.append(new_filters)
        filters[logged_in_staff] = user_filters
        cache.set(self.cache_key, filters)

        return [JSONResponse({"filter": new_filters}, status_code=HTTPStatus.OK)]

    @api.get("/filters")
    def get_filters(self) -> list[Response | Effect]:
        logged_in_staff = Staff.objects.values_list("id", flat=True).get(
            id=self.request.headers["canvas-logged-in-user-id"]
        )
        cache = get_cache()

        # this cache is deprecated in favor of a general cache key
        # so we can keep the cache alive "ignoring" the TTL, by re-saving
        deprecated_user_cache_key = f"{self.cache_key}--{logged_in_staff}"

        # get current filters
        filters = cache.get(self.cache_key, default={})
        if (user_filters := filters.get(logged_in_staff)) is not None:
            cache.set(self.cache_key, filters)
            return [JSONResponse({"filters": user_filters}, status_code=HTTPStatus.OK)]
        # check the deprecated key and convert to the new structure
        else:
            user_filters = cache.get(deprecated_user_cache_key) or []
            filters[logged_in_staff] = user_filters

            cache.set(self.cache_key, filters)
            return [JSONResponse({"filters": user_filters}, status_code=HTTPStatus.OK)]


    @api.delete("/filter/<id>")
    def delete_filters(self) -> list[Response | Effect]:
        logged_in_staff = Staff.objects.values_list("id", flat=True).get(
            id=self.request.headers["canvas-logged-in-user-id"]
        )

        filter_id = self.request.path_params["id"]

        cache = get_cache()
        # get current filters
        filters = cache.get(self.cache_key, default={})
        user_filters = filters.get(logged_in_staff) or []

        updated_user_filters = [_filter for _filter in user_filters if _filter["id"] != filter_id]
        filters[logged_in_staff] = updated_user_filters
        cache.set(self.cache_key, filters)

        return [JSONResponse({"filters": updated_user_filters}, status_code=HTTPStatus.OK)]
