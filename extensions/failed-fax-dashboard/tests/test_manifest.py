import json
from pathlib import Path

MANIFEST = Path(__file__).parent.parent / "failed_fax_dashboard" / "CANVAS_MANIFEST.json"


def test_the_manifest_lists_the_records_each_handler_writes() -> None:
    handlers = json.loads(MANIFEST.read_text())["components"]["handlers"]
    writes = {handler["class"].rsplit(":", 1)[1]: handler["data_access"]["write"] for handler in handlers}

    assert writes == {
        "FailedFaxDashboardAPI": ["Task", "TaskComment", "Note"],
        "FaxAlertCron": ["Task", "TaskComment"],
    }
