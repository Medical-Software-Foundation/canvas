# Prescribe Formulary & Benefits

Surfaces real-time Surescripts **formulary and benefits** information as custom
HTML inside the **Prescribe**, **Refill**, and **Adjust Prescription** commands,
right after the prescriber selects a medication.

## How it works

The plugin chains three Surescripts SDK capabilities across the
request/response cycle:

1. **Medication selected** — when a medication (and its dispensable form/NDC) is
   chosen in a prescribe-family command, `PrescribeBenefitsTrigger` fires a
   `SendSurescriptsEligibilityRequestEffect` and writes a "checking coverage…"
   placeholder into the command via `set_custom_html`.
2. **Eligibility response** — `EligibilityResponseHandler` receives the
   `SURESCRIPTS_ELIGIBILITY_RESPONSE` event, extracts the patient's plan, and
   fires a `SendSurescriptsBenefitsRequestEffect` for the chosen medication +
   plan.
3. **Benefits response** — `BenefitsResponseHandler` receives the
   `SURESCRIPTS_BENEFITS_RESPONSE` event and renders the formulary status, prior
   authorization / step therapy flags, quantity limits, copays, and formulary
   alternatives as the command's custom HTML.

Each request effect carries a `correlation_id` that the home-app interpreter
echoes back on the matching response. The plugin stashes per-command context
under that id (in the SDK cache) so each response can be matched to the
originating command — and so the handlers ignore responses they didn't start.

```
POST_UPDATE (medication chosen)
   └─> eligibility request  ──┐  (correlation_id A, context cached)
                              ▼
        SURESCRIPTS_ELIGIBILITY_RESPONSE (A)
   └─> benefits request  ─────┐  (correlation_id B, context cached)
                              ▼
        SURESCRIPTS_BENEFITS_RESPONSE (B)
   └─> command.set_custom_html(<formulary detail>)
```

## Requirements

This plugin depends on Surescripts SDK functionality:

- `SendSurescriptsEligibilityRequestEffect` / `SendSurescriptsBenefitsRequestEffect`
  with `correlation_id` support
- `SURESCRIPTS_ELIGIBILITY_RESPONSE` / `SURESCRIPTS_BENEFITS_RESPONSE` events and
  the `SurescriptsEligibilityResponse` / `SurescriptsBenefitsResponse` typed
  wrappers
- `Command.set_custom_html()`

These must be available on the target instance (the Surescripts effects are
gated server-side behind the Surescripts feature switch).

## Notes & assumptions

- **De-duplication:** `POST_UPDATE` fires on every field change. The trigger
  only acts when the chosen medication's **NDC** changes from the last one it
  processed for that command, so it issues one eligibility request per
  (command, medication) rather than one per keystroke.
- **NDC source:** the NDC is read from the command's medication fields
  (e.g. `type_to_dispense`'s representative NDC). If no NDC is present yet, the
  plugin waits — the benefits request requires one.
- **Plan label:** the `plan` sent on the benefits request is derived from the
  eligibility response (plan description → formulary number → PBM name).
- **Staged commands only:** `set_custom_html` requires a staged (uncommitted)
  command. If the prescriber commits before the responses return, the HTML
  write is rejected server-side.

## Install

```
canvas install prescribe_formulary_benefits
```

## Tests

```
pytest
```
