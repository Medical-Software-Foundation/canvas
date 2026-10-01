"""Which Data Integration document a received fax became.

Canvas records the pairing in a table plugins can't read, so it is matched by timing: the
document is created 0 to 5 seconds after the Fax record. The match is used only when it is
unambiguous, and otherwise the link goes to the Data Integration queue.
"""

from datetime import timedelta

from canvas_sdk.v1.data import Fax, FaxDirection, IntegrationTask
from django.db.models import Q

from failed_fax_dashboard.services.sources import DATA_INTEGRATION_PATH
from failed_fax_dashboard.services.util import chunked, seconds_apart

WINDOW_SECONDS = 5
RANGE_CHUNK = 50


def document_path(task: IntegrationTask | None) -> str:
    """Path to a single document, or to the queue when there is none."""
    if task is None:
        return DATA_INTEGRATION_PATH
    return f"{DATA_INTEGRATION_PATH}/{task.dbid}"


def match_documents(faxes: list[Fax]) -> dict[str, IntegrationTask | None]:
    """The document each received fax became (by fax id), or None when unclear.

    Matched only when exactly one fax-channel document was created 0 to 5 seconds after the
    Fax and exactly one inbound Fax was created within 5 seconds either side of it.
    """
    window = timedelta(seconds=WINDOW_SECONDS)
    tasks: list[IntegrationTask] = []
    neighbors: list[Fax] = []
    for chunk in chunked(faxes, RANGE_CHUNK):
        task_ranges = Q()
        fax_ranges = Q()
        for fax in chunk:
            task_ranges = task_ranges | Q(created__gte=fax.created, created__lte=fax.created + window)
            fax_ranges = fax_ranges | Q(created__gte=fax.created - window, created__lte=fax.created + window)
        tasks.extend(
            IntegrationTask.objects.filter(channel="fax")
            .filter(task_ranges)
            .select_related("service_provider")
        )
        neighbors.extend(Fax.objects.filter(direction=FaxDirection.INBOUND).filter(fax_ranges))

    matched: dict[str, IntegrationTask | None] = {}
    for fax in faxes:
        documents = [
            task
            for task in tasks
            if 0 <= seconds_apart(fax.created, task.created) <= WINDOW_SECONDS
        ]
        nearby = {
            other.dbid
            for other in neighbors
            if abs(seconds_apart(fax.created, other.created)) <= WINDOW_SECONDS
        }
        matched[str(fax.id)] = documents[0] if len(documents) == 1 and len(nearby) == 1 else None
    return matched
