# Migrations

Procedures for non-trivial maintenance changes that would otherwise leave existing user data behind.

If you're a future maintainer evaluating a rename, please follow the relevant procedure here in full. Skipping the migration step orphans existing AttributeHub rows or causes the plugin to delete-and-recreate Canvas commands instead of editing them in place.

---

## 1. Renaming the AttributeHub namespace

The plugin stores per-note form-state in `AttributeHub` rows keyed by `(type=NAMESPACE, id=<note_uuid>)`. The current namespace is `canvas__nutrition_charting`, declared in two places:

- `nutrition_charting/data/form_state.py` → `NAMESPACE = "canvas__nutrition_charting"`
- `nutrition_charting/CANVAS_MANIFEST.json` → `custom_data.namespace`

Renaming both without a migration step orphans every existing row: the plugin will read empty form-state on every previously-saved note, the `Save` flow will originate fresh duplicate commands instead of editing in place, and `NutritionChartingNoteLifecycle` will silently no-op on subsequent deletes (it queries by the new namespace, so the old rows are invisible to it).

### Procedure

1. **Rename in code** — update both call sites above. Bump the plugin version.
2. **Write a one-shot mapper** as a Cron-style handler the SDK can run once per instance. Pseudo-code:

   ```python
   from canvas_sdk.v1.data import AttributeHub

   OLD_NAMESPACE = "<previous-namespace>"
   NEW_NAMESPACE = "canvas__nutrition_charting"

   class RenameNutritionChartingNamespace(BaseHandler):
       """One-shot: copy every (OLD_NAMESPACE, *) row over to NEW_NAMESPACE,
       then delete the old rows. Idempotent — safe to re-run."""

       def compute(self) -> list:
           old_rows = AttributeHub.objects.filter(type=OLD_NAMESPACE)
           moved = 0
           for old in old_rows:
               new, _ = AttributeHub.objects.get_or_create(
                   type=NEW_NAMESPACE, id=old.id,
               )
               for attr in old.custom_attributes.all():
                   new.set_attribute(attr.name, attr.value)
               old.delete()
               moved += 1
           log.info(f"[RenameNamespace] moved {moved} row(s)")
           return []
   ```

3. **Ship the rename + mapper together** in the same release so no instance ever runs the new code without the migration available.
4. **Drop the mapper** in a follow-up release (after every instance has reported it ran successfully — easiest to confirm via the `[RenameNamespace] moved N row(s)` log line).

### Verification

After the deploy:

- Open a Nutrition note that was charted before the rename. Confirm form-state still loads (sections, visit_type, command_uuid map) — i.e. the rename was transparent to the dietician.
- Confirm the old-namespace rows are gone via `AttributeHub.objects.filter(type=OLD_NAMESPACE).count() == 0`.

---

## 2. Renaming or adding educational-materials canonical keys

The Educational Materials section persists user selections as `material:<canonical_key>` row-ids in the multi-command map. The canonical keys are declared in:

- `nutrition_charting/data/multi_command_sections.py` → `EDUCATIONAL_MATERIAL_OPTIONS`

Current keys: `dash_diet`, `mediterranean`, `low_fodmap`, `diabetic_carb_counting`, `weight_management`.

These keys are part of the public contract because they're persisted as `row_id` strings and double as the stable identity that lets resaves edit existing `Instruct` commands in place. Renaming a key without a migration causes the next save to:

1. See `material:<old_key>` in the saved row-ids and `material:<new_key>` in the form's selected options,
2. Treat the renamed material as a *new* row → originate a fresh `Instruct` command,
3. Treat the old key as a deselected row → delete the `Instruct` command that was originally created for it.

That delete + originate is visible to the dietician and clutters the note's command history.

### Procedure for a rename

1. **Rename the key + label** in `EDUCATIONAL_MATERIAL_OPTIONS`. Bump the plugin version.
2. **Write a one-shot mapper** that walks every `multi_commands:educational_materials` AttributeHub attribute and rewrites `material:<old_key>` row-ids in place to `material:<new_key>`. Pseudo-code:

   ```python
   from canvas_sdk.v1.data import AttributeHub
   from nutrition_charting.data.form_state import NAMESPACE

   OLD_KEY = "<old>"
   NEW_KEY = "<new>"
   ATTR_NAME = "multi_commands:educational_materials"

   class RenameEducationalMaterialKey(BaseHandler):
       def compute(self) -> list:
           rewritten = 0
           for hub in AttributeHub.objects.filter(type=NAMESPACE):
               mapping = hub.get_attribute(ATTR_NAME) or {}
               if not isinstance(mapping, dict):
                   continue
               old_id = f"material:{OLD_KEY}"
               new_id = f"material:{NEW_KEY}"
               if old_id in mapping:
                   mapping[new_id] = mapping.pop(old_id)
                   hub.set_attribute(ATTR_NAME, mapping)
                   rewritten += 1
           log.info(f"[RenameMaterialKey] rewrote {rewritten} hub(s)")
           return []
   ```

3. **Ship rename + mapper together.** Drop the mapper in a follow-up release.

### Procedure for adding a new key

No migration needed. Just append to `EDUCATIONAL_MATERIAL_OPTIONS`. Existing notes pick up the new option as a fresh selectable row; deselecting it is a no-op on AttributeHub (no row-id stored yet).

### Procedure for removing a key

Removing a key without a migration leaves orphan `material:<removed_key>` row-ids in AttributeHub that no longer correspond to any selectable option. The plugin tolerates this — the row-id is just ignored on render — but it leaks complexity over time.

Cleanup mapper (run once after the removal release ships):

```python
class CleanupRemovedMaterialKey(BaseHandler):
    REMOVED_KEY = "<key>"

    def compute(self) -> list:
        cleaned = 0
        for hub in AttributeHub.objects.filter(type=NAMESPACE):
            mapping = hub.get_attribute(ATTR_NAME) or {}
            if not isinstance(mapping, dict):
                continue
            old_id = f"material:{self.REMOVED_KEY}"
            if old_id in mapping:
                del mapping[old_id]
                hub.set_attribute(ATTR_NAME, mapping)
                cleaned += 1
        return []
```

The removed `Instruct` commands stay on the original notes; the mapper only clears the plugin's tracking-map entry so the next save doesn't try to edit them.

---

## 3. Other lifecycle events the plugin doesn't sweep

`NutritionChartingNoteLifecycle` removes the per-note `AttributeHub` row on `state=DELETED`. It does **not** sweep:

- **Patient deletes.** If a Patient record is removed but the patient's notes weren't, the AttributeHub rows remain; the next chart-review on a fresh-but-same-note-uuid would still try to read them. (In practice patient-deletes cascade through Note records first, so this is rare.)
- **Namespace renames.** Covered by section 1 above.
- **Educational-material key renames.** Covered by section 2 above.
- **Plugin uninstall.** AttributeHub rows live in Canvas storage independent of the plugin; uninstalling the plugin leaves them in place. Cleaning them up requires a one-shot DELETE handler shipped before uninstall — or accepting the rows as historical noise.

If storage cost ever becomes measurable, a periodic `Cron`-style sweeper that finds rows whose `id` (note UUID) no longer maps to a live `Note` is the cleanest fix; the implementation is small (one query + one filter + one delete per stale row).
