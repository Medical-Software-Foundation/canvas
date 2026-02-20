# Documents by Type

Counts of documents broken down by type and category as recorded in the document reference table, with date ranges.

## SQL

```sql
SELECT
    drt.display                   AS document_type,
    COALESCE(drc.display, 'N/A')  AS document_category,
    COUNT(*)                      AS document_count,
    MIN(dr.date)                  AS earliest_date,
    MAX(dr.date)                  AS latest_date
FROM api_documentreference dr
JOIN api_documentreferencecoding   drt ON drt.id = dr.type_id
LEFT JOIN api_documentreferencecategory drc ON drc.id = dr.category_id
WHERE dr.status = 'current'
GROUP BY drt.display, drc.display
ORDER BY document_count DESC;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `document_type` | Document type display name |
| `document_category` | Document category display name (or N/A if uncategorized) |
| `document_count` | Number of documents of this type/category |
| `earliest_date` | Date of the oldest document in this group |
| `latest_date` | Date of the most recent document in this group |

## Notes

- Only documents with status `'current'` are included (excludes superseded or entered-in-error records).
- Categories are optional — documents without a category show as "N/A."
