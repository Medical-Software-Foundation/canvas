"""Pagination URL + page-number helpers for the patient panel table.

Pure functions: callers pass the API's BASE_PATH/PREFIX explicitly so these
have no dependency on the SimpleAPI instance.
"""

from urllib.parse import urlencode


def create_paginated_url_multi(
    base_path: str,
    prefix: str,
    path: str,
    page: int,
    facility_ids: list[str] | None = None,
    protocols: list[str] | None = None,
    patient_search: str | None = None,
    staff_ids: list[str] | None = None,
    insurances: list[str] | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
    no_auto_filter: bool = True,
    flagged_only: bool = False,
    page_size: int | None = None,
    metadata_filters: dict[str, list[str]] | None = None,
) -> str:
    """Build a table URL with multi-select filter support."""
    query_params: dict[str, str | int] = {"page": page}
    if page_size:
        query_params["page_size"] = page_size
    if facility_ids:
        query_params["facility_ids"] = ",".join(facility_ids)
    if protocols:
        query_params["protocols"] = ",".join(protocols)
    if patient_search:
        query_params["patient_search"] = patient_search
    if staff_ids:
        query_params["staff_ids"] = ",".join(staff_ids)
    if insurances:
        query_params["insurances"] = ",".join(insurances)
    if sort_by:
        query_params["sort_by"] = sort_by
    if sort_dir:
        query_params["sort_dir"] = sort_dir
    if no_auto_filter:
        query_params["no_auto_filter"] = "1"
    if flagged_only:
        query_params["flagged_only"] = "1"
    if metadata_filters:
        for key, values in metadata_filters.items():
            if values:
                query_params[f"metadata_{key}"] = ",".join(values)
    return f"{base_path}{prefix}/{path}?{urlencode(query_params)}"


def build_page_numbers(
    base_path: str,
    prefix: str,
    page: int,
    total_pages: int,
    pagination_args: dict,
) -> list[dict]:
    """Build the visible page-number list for the pagination controls."""
    max_visible = 5
    if total_pages <= max_visible:
        start_page = 1
        end_page = total_pages
    else:
        start_page = max(1, page - 2)
        end_page = min(total_pages, start_page + max_visible - 1)
        if end_page - start_page < max_visible - 1:
            start_page = max(1, end_page - max_visible + 1)

    return [
        {
            "number": p,
            "url": create_paginated_url_multi(base_path, prefix, "table", p, **pagination_args),
            "is_current": p == page,
        }
        for p in range(start_page, end_page + 1)
    ]
