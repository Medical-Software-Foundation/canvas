# Plugin Spec: salesforce-to-canvas-integration

**Status:** Draft
**Airtable:** [link]
**PR:** [link]
**Prepared by:** Milos Djakovic | **Date:** 2026-06-15

## Problem

Canvas customers in the enterprise segment run Salesforce as their front of funnel system, and without a reference path every Salesforce using customer becomes a bespoke engagement that raises implementation cost and go live risk. Staff re key demographics by hand between the two systems, and any automated bridge that merges patients on its own is clinically dangerous. The customer needs a safe, generic way to move a patient record from Salesforce into Canvas with a human in control of every clinical write.

## Solution

The plugin captures patient sync events that a Salesforce org pushes to one signed webhook and records each one as an immutable row in a Canvas side audit table. A Canvas operator opens an admin app, reviews each row, and resolves it into a create, a modify, a delete, or a skip, so nothing reaches the chart without review. A configurable filter can promote a clearing sync to apply automatically while holding anything ambiguous for a human, and the sync is one directional from Salesforce into Canvas.

## Workflow

1. A Salesforce rep sets the Canvas Sync field on a source record to Sync or Delete, and a Record Triggered Flow posts the signed record to the plugin webhook.
2. The plugin verifies the signature, derives the action from the intent and the live patient link, and captures the payload as one immutable audit row.
3. A configurable filter evaluates the captured event, a record that clears the filter applies automatically, and anything else holds in needs action with its reasons recorded.
4. A Canvas operator opens the Salesforce Integration admin app and reviews the needs action rows, each collapsed to the newest pending event per contact.
5. The operator resolves a row, a create or modify writes the patient, a delete marks the linked patient, and a skip closes the row with no Canvas side change.
6. On a successful create the plugin writes the new patient id back to the Salesforce record, and a chart banner under the patient name links back to the linked Salesforce record.

## Acceptance Criteria

| # | Requirement | Source | Verified |
|---|-------------|--------|----------|
| 1 | The webhook verifies an HMAC SHA256 signature over the raw body and answers 202 with an entry id on success, 401 on a bad signature, 400 on a missing record Id or unparseable body, and 503 when required secrets are unset | | [ ] |
| 2 | The action is derived server side, a sync with no linked patient captures a create, a sync with a linked patient captures a modify, and a delete intent captures a delete | | [ ] |
| 3 | A repeated payload for the same record, action, and content is deduplicated and never produces a second actionable row | | [ ] |
| 4 | The records list shows one row per contact, the newest pending event, and reads the events it overrides as a history list inside the row details | | [ ] |
| 5 | A delete for a contact with no linked Canvas patient never becomes an actionable row and appears only in the activity ledger | | [ ] |
| 6 | Hard gates hold a record for a human and cannot be turned off, covering a failed mapping, a prior skip, a pending patient link, and a duplicate patient match on last name and birth date | | [ ] |
| 7 | A record that clears the configurable filter applies the same Canvas effect its manual resolution would, and any other record holds in needs action with each failing reason named | | [ ] |
| 8 | A create with no last name always holds for a human regardless of the saved settings | | [ ] |
| 9 | The operator resolves a row through create, modify, a delete action, or skip, and the server refuses a resolution on a row that a newer pending change has superseded | | [ ] |
| 10 | The Settings tab tunes every filter value without a code change or secret edit, stores the settings in the plugin namespace so they survive reinstall, and refuses an empty required field set | | [ ] |
| 11 | The admin app, the resolution endpoints, and the settings are reachable only by staff on the configured allowlist behind a live Canvas staff session | | [ ] |
| 12 | A successful create surfaces a chart banner under the patient name that links to the linked Salesforce record | | [ ] |
| 13 | A successful create writes the new patient id back to the Salesforce record over OAuth | | [ ] |

## Data & Dependencies

- **Reads:** Canvas Patient records and their external identifiers for the live link, the plugin custom data namespace rows, and the Canvas staff session identity from the request header.
- **Writes:** immutable audit rows in the `vicert__salesforce_integration` namespace, patient create and modify effects, a `salesforce_deleted_at` patient metadata entry for tag deleted, Canvas FHIR Patient updates for mark inactive and unlink only, and an OAuth writeback of the new patient id to the Salesforce record.
- **External:** Salesforce for the inbound signed webhook and the OAuth writeback, and the Canvas FUMAGE FHIR Patient endpoint for the delete resolutions. Secrets are `SF_CLIENT_ID`, `SF_CLIENT_SECRET`, `SF_LOGIN_URL`, `SF_WEBHOOK_SECRET`, `SF_ADMIN_STAFF_IDS`, the optional `SF_SOURCE_SOBJECT` and `SF_FIELD_MAPPING_JSON`, and the conditional `CANVAS_API_CLIENT_ID`, `CANVAS_API_CLIENT_SECRET`, and `FUMAGE_BASE_URL`.

## Open Questions

- None.

---

## Delivery Verification (complete AFTER implementation, not before)

> Completed by: Milos Djakovic | Date: 2026-06-15

| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 1 | Signed POST verified, response codes | Pass | `handlers/webhook_base.py` `authenticate` and `_verify_request` return 401 on a bad or missing signature, `_parse_payload` returns 400 on a bad Id or unparseable body, `_handle_sync` returns 503 on a config error and 202 with `entry_id` on success. Covered by `tests/test_webhook_api.py` and `tests/test_hmac_verify.py` |
| 2 | Server side action derivation | Pass | `handlers/webhook_base.py` `_derive_action`, delete intent gives delete, sync gives modify when linked else create. Covered by `tests/test_effective_action.py` and `tests/test_webhook_api.py` |
| 3 | Duplicate payload deduped | Pass | `handlers/webhook_base.py` `_capture` drops a resend whose content hash matches the newest row for the same id and action. Covered by `tests/test_webhook_api.py` and `tests/test_storage.py` |
| 4 | One row per contact, history in details | Pass | `handlers/status_api.py` collapses to the newest pending row and folds the overridden events into the row trail. Covered by `tests/test_status_buckets_and_history.py` |
| 5 | Delete with no link is activity only | Pass | `handlers/webhook_base.py` `_evaluate_and_apply` and `_auto_apply_delete` return no actionable row when no patient is linked. Covered by `tests/test_webhook_auto_apply.py` and `tests/test_event_gap.py` |
| 6 | Hard gates always hold | Pass | `services/sync_rules.py` `_hard_gate_reasons`, mapping failed, previously skipped, link pending and duplicate match, the last two create only. Covered by `tests/test_sync_rules.py` and `tests/test_duplicate_check.py` |
| 7 | Filter auto applies or holds with reasons | Pass | `services/sync_rules.py` `evaluate` and `handlers/webhook_base.py` `_evaluate_and_apply`, a hold writes the reasons onto the row, an auto apply runs the same effect the manual resolution would. Covered by `tests/test_sync_rules.py` and `tests/test_webhook_auto_apply.py` |
| 8 | Create last name floor | Pass | `services/sync_rules.py` `CREATE_REQUIRED_FLOOR` applied to the create path only in `evaluate`. Covered by `tests/test_sync_rules.py` `test_last_name_floored_for_create_even_when_settings_omit_it` and `test_last_name_not_floored_for_modify` |
| 9 | Resolution actions and supersede refusal | Pass | `handlers/status_api.py` routes accept, promote, review-and-update, tag-deleted, mark-inactive, unlink-only, skip, plus `_superseded_conflict` reached through `_guard_actionable_row` and `accept_record`. Covered by `tests/test_audit_routes.py`, `tests/test_modify_routes.py`, `tests/test_delete_routes.py`, `tests/test_promote_routes.py` |
| 10 | Settings tuning, persistence, empty set refused | Pass | `handlers/status_api.py` `put_settings` rejects an empty or unknown required set with 400 and persists through `save_sync_settings`. Covered by `tests/test_settings_routes.py` `test_put_rejects_empty_required_fields` and `tests/test_sync_settings.py`. Survival across reinstall is a Canvas namespace property, not exercised by the unit suite |
| 11 | Staff allowlist gating | Pass | `handlers/status_api.py` `SalesforceStatusAPI.authenticate` gates on `admin_staff_ids` behind a live session, and `SalesforceAdminPage.admin_page` gates inside after serving HTML. Covered by `tests/test_admin_app.py` and `tests/test_admin_page.py` |
| 12 | Chart banner links to the Salesforce record | Pass | `handlers/chart_banner.py` emits an `AddBannerAlert` under the patient name with the record href. Covered by `tests/test_chart_banner.py` |
| 13 | OAuth writeback of the patient id on create | Pass | `handlers/canvas_id_writeback.py` `SalesforceCanvasIdWriteback` listens on `PATIENT_CREATED`, resolves the patient's `salesforce` identifier, and calls `write_canvas_id` with `config.source_sobject` over the stored OAuth tokens, degrading to a logged skip when disconnected. Covered by `tests/test_canvas_id_writeback.py`. End to end against a live org is a human step, the local runner does not deliver `PATIENT_*` events |
