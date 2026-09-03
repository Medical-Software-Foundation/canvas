# HCC Problem List Hygiene

### Target Population

Any patient whose problem list contains one or more active HCC (Hierarchical Condition Category) conditions.

### Recommendations

When the protocol identifies one or more active HCC conditions that have not been assessed within the last year (or the per-patient override cycle), it surfaces a protocol card recommending that the clinician either assess/update or resolve those conditions.

### Importance

HCC conditions drive risk adjustment factor (RAF) scores used for reimbursement and population-health analytics. CMS requires that significant chronic conditions be reassessed at least annually. This protocol keeps the problem list current, prevents lapses in documentation, and protects accurate RAF capture.

### Behaviour

- The protocol recomputes whenever a condition or protocol override changes on the patient.
- If the patient has no active HCC conditions, the card is marked `NOT_APPLICABLE`.
- If every active HCC condition has been assessed within the configured window, the card is marked `SATISFIED` with a `due_in` that reflects when the next assessment will fall due.
- If one or more active HCC conditions are overdue, the card is marked `DUE` and includes per-condition narratives (HCC label, ICD-10 description, last assessment date, RAF value), plus recommendation buttons to launch the `assess` or `resolveCondition` commands.
- A `ProtocolOverride` row with `is_adjustment=True` for the protocol key `HCC001v1` overrides the default one-year window with its `cycle_in_days` value.
