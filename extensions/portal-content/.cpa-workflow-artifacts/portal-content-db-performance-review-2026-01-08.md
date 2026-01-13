# Database Performance Review: portal_content

**Date:** 2026-01-08
**Reviewer:** Claude Code
**Plugin Version:** 0.0.1
**Status:** PASS

---

## Overview

This review evaluates database query patterns in the portal_content plugin, focusing on N+1 query detection and Django ORM optimization.

---

## Database Access Patterns

### Components Using Database

| Component | Data Access Method | Status |
|-----------|-------------------|--------|
| visits.py | Canvas SDK Data Models (Note, Patient) | ✅ Optimized |
| education.py | FHIR API only | N/A |
| imaging.py | FHIR API only | N/A |
| labs.py | FHIR API only | N/A |

**Note:** Education, imaging, and labs components use FHIR API calls (via `requests` library) rather than direct database access, so N+1 concerns don't apply to those modules.

---

## Visits Component Analysis

### Query Patterns Reviewed

#### 1. Note Listing (`_handle_list`)

**Location:** `visits.py:393-415`

**Query:**
```python
notes = (
    Note.objects.select_related(
        "patient",
        "provider",
        "note_type_version",
    )
    .filter(
        patient__id=patient_id,
        current_state__in=Note.State.objects.filter(
            label__in=FINALIZED_STATES
        ),
    )
    .order_by("-created")
)
```

**Optimization Applied:**
- ✅ `select_related("patient")` - Fetches patient in same query
- ✅ `select_related("provider")` - Fetches provider in same query
- ✅ `select_related("note_type_version")` - Fetches note type in same query

**Result:** Single query with JOINs instead of N+1 queries.

#### 2. Note Detail (`_handle_detail`)

**Location:** `visits.py:454-470`

**Query:**
```python
note = (
    Note.objects.select_related(
        "patient",
        "provider",
        "note_type_version",
    )
    .filter(id=note_id)
    .first()
)
```

**Optimization Applied:**
- ✅ Same `select_related()` pattern as listing
- ✅ Single note fetch with related data

#### 3. Note State Check

**Location:** `visits.py:480-490`

**Query:**
```python
current_state = note.current_state.first()
```

**Analysis:**
- This accesses a related manager, which issues a separate query
- Acceptable because it's a single query per note detail request (not N+1)
- The state check is necessary for security (finalized notes only)

---

## N+1 Issues Fixed

### Issue: Missing select_related on Note queries

**Before (N+1 pattern):**
```python
notes = Note.objects.filter(patient__id=patient_id)
for note in notes:
    provider_name = note.provider.full_name  # N queries!
    note_type = note.note_type_version.name  # N more queries!
```

**After (optimized):**
```python
notes = Note.objects.select_related(
    "patient", "provider", "note_type_version"
).filter(patient__id=patient_id)
# All data fetched in single query with JOINs
```

---

## Query Count Analysis

### Note Listing Endpoint

| Operation | Queries (Before) | Queries (After) |
|-----------|------------------|-----------------|
| Fetch notes | 1 | 1 |
| Fetch patient per note | N | 0 (JOINed) |
| Fetch provider per note | N | 0 (JOINed) |
| Fetch note_type per note | N | 0 (JOINed) |
| **Total** | **1 + 3N** | **1** |

For a patient with 20 notes: **61 queries → 1 query**

### Note Detail Endpoint

| Operation | Queries (Before) | Queries (After) |
|-----------|------------------|-----------------|
| Fetch note | 1 | 1 |
| Fetch related data | 3 | 0 (JOINed) |
| Fetch current_state | 1 | 1 |
| **Total** | **5** | **2** |

---

## FHIR API Calls

The education, imaging, and labs components make HTTP requests to the FHIR API rather than direct database queries. These are not subject to N+1 analysis but were reviewed for efficiency:

| Component | API Calls per List | API Calls per Detail |
|-----------|-------------------|---------------------|
| education.py | 1 (search) | 1 (get) |
| imaging.py | 1 (search) | 1 (get) |
| labs.py | 1 (search) | 1 (get) |

All FHIR components make efficient single-call patterns.

---

## Recommendations

### Implemented
1. ✅ Added `select_related()` for Note queries with patient, provider, note_type_version

### Future Considerations
1. **Pagination:** Note listing uses Python-side pagination after fetching all notes. For very large note sets, consider database-level pagination with `LIMIT`/`OFFSET`.

2. **Prefetch for Commands:** If note summary extraction needs to access many related commands, consider `prefetch_related("commands")`.

---

## Conclusion

**PASS** - Database queries are optimized:

- ✅ N+1 queries eliminated via `select_related()`
- ✅ Note listing: reduced from 1+3N queries to 1 query
- ✅ Note detail: reduced from 5 queries to 2 queries
- ✅ FHIR API calls are efficient (single calls)

No performance issues identified.
