# Backwards-compatibility shim. The model classes are defined in
# `external_calendar_busy_blocks.models` so Canvas's custom-data migration
# generator can discover them (it keys off `__module__` being under
# `<plugin_package>.models`). Existing code imports them from here; keep that
# working by re-exporting.
from external_calendar_busy_blocks.models import ImportedEvent, StaffCalendarFeed

__all__ = ["StaffCalendarFeed", "ImportedEvent"]
