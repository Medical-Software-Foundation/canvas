from chart_command_search.searchers.types import Result
from chart_command_search.searchers.constants import (
    ALL_CATEGORY_LIMIT,
    COMMAND_TYPE_LABELS,
    MAX_RESULTS,
)
from chart_command_search.searchers.helpers import (
    build_command_link,
    build_note_link,
    detail,
    extract_body_text,
    fmt_date,
    fmt_datetime,
    make_result,
    match_snippet,
    note_type_name,
    parse_multi,
    resolve_command_query,
    staff_name,
    strip_html,
)
from chart_command_search.searchers.command_helpers import (
    extract_command_details,
    extract_command_heading,
    readable_value,
)
from chart_command_search.searchers.commands import (
    search_commands_all,
    search_medications,
)
from chart_command_search.searchers.appointments import search_appointments
from chart_command_search.searchers.letters import search_letters
from chart_command_search.searchers.messages import search_messages
from chart_command_search.searchers.notes import search_notes
from chart_command_search.searchers.labs import search_labs

CATEGORY_SEARCHERS = {
    "commands": search_commands_all,
    "appointments": search_appointments,
    "letters": search_letters,
    "messages": search_messages,
    "notes": search_notes,
    "labs": search_labs,
}
