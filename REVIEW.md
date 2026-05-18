# Review instructions

Authors in this repo are Certified Plugin Builders (CPBs). Many are not full-time software engineers. Reviews must surface a small number of clearly actionable problems, not a long list of every concern.

Before this review runs, the author has already run `/wrap-up`, which has verified: project structure, mypy, ≥90% branch coverage, no leftover `print()` / `[DEBUG]` / `# TODO`, no dead code or unused imports, manifest entries match files on disk, cache-bust tokens on HTML asset URLs, 48×48 application icon when an Application is declared, README handler/event lists match code, and license correctness for the repo. Do not re-flag any of those — assume they pass.

Repo-specific patterns and longer-form guidance (reference codebases, anti-pattern explanations, plugin architecture checklist) live in `CLAUDE.md`. Code Review reads `CLAUDE.md` and flags new violations as 🟡 Nit by default; the rules called out under "Always check" below are promoted to 🔴 Important.

## Audience and tone

Each finding will be acted on by the plugin author directly. Write findings the way you would tell a non-engineer what to change: name the file and line, name the symbol, say what to change. Skip the "why this matters in general" explanation unless it changes the fix.

## What 🔴 Important means here

Reserve 🔴 Important for findings that, if merged, would:

- Break the plugin at runtime — uncaught exceptions on the happy path, missing imports, wrong handler signatures, manifest entries that don't resolve to real code
- Mishandle patient data — PHI in logs, error messages, or outbound HTTP calls; missing `authenticate` on a SimpleAPI or WebSocket route; FHIR client requests outside the scopes declared in the manifest
- Corrupt or destroy data — non-idempotent writes on event handlers that can replay, effects targeting the wrong object ID, deletes without an explicit user confirmation path
- Leak secrets — hardcoded credentials, API keys, or tokens in code; secrets read at runtime but not declared in the manifest
- Block install or deploy — invalid `CANVAS_MANIFEST.json`, missing files declared in the manifest, syntax errors
- Violate any "Always check" rule below

Everything else is 🟡 Nit at most. Style preferences, naming, refactor opportunities, additional test ideas, docstring wording, comment polish, and "this could be cleaner" suggestions are always Nit.

## Cap the nits

Post at most three 🟡 Nit findings per review. If more were found, summarize the rest as "plus N similar items" in the review body — do not post them inline.

## Re-review convergence

After the first review on a PR, post 🔴 Important findings only. Suppress all 🟡 Nit findings on subsequent runs — the author saw round one and chose not to act. Do not re-surface them.

## Verification bar

Before posting a 🔴 Important finding, read the code path and cite `file:line` for the problem. When the finding claims a behavior elsewhere ("this caller passes None", "this field is unset"), cite `file:line` for that claim too. Do not infer behavior from names. If you cannot verify, drop the finding rather than posting it speculatively — a wrong Important costs the author a deploy cycle.

## Do not report

- Anything `/wrap-up` already enforces (see top of this file)
- Anything ruff would catch (formatting, import order, unused vars)
- Suggestions to add tests when coverage is already ≥90%
- Suggestions to refactor working code into a different pattern
- Naming preferences for variables, functions, classes, files
- Docstring or comment wording
- Generated files (`*.lock`, `__pycache__/`, anything under a path containing `generated`, anything under `.cpa-workflow-artifacts/`)
- Test-only code that intentionally violates production rules

## Always check

These are repo-specific 🔴 Important rules. Each has been a real bug in past reviews — see `CLAUDE.md` for the longer explanation and code examples.

- **No all-patient batch operations on plugin or patient lifecycle events.** Do not subscribe `PLUGIN_CREATED`, `PLUGIN_UPDATED`, or broad `PATIENT_UPDATED` to a handler that iterates every patient. Reinstalls then trigger instance-killing batches. Use a global-scope `Application` + SimpleAPI button instead.
- **Fail closed when secrets or config are missing.** Origin checks, admin checks, and auth gates must deny when the required secret is empty or unset. A missing secret that grants access is an immediate Important.
- **No blanket `try/except Exception` around handler logic.** Errors must reach Sentry. Catch only the specific expected exception from an external call.
- **Clinical-data queries filter `entered_in_error`.** Any query against `Condition`, `Medication`, `LabReport`, etc. must include `entered_in_error__isnull=True` (or equivalent). Without it, retracted records appear in results.
- **No placeholder values for missing required data.** Don't write `"unknown"`, `"N/A"`, or empty strings into the database when an authenticated user, patient, or note ID is required. Return an error instead.
- **Effects target the correct object ID.** `Patient.id`, `Note.id`, command IDs from the originating event. Wrong target IDs silently no-op in production and are very hard to debug.
- **SimpleAPI and WebSocket routes have `authenticate` set, and manifest scopes match the code.** Missing or misaligned auth is an Important.
- **FHIR client calls stay within manifest scopes.** Calls outside the scopes declared in `CANVAS_MANIFEST.json` are an Important.
- **Loops over data-model querysets use `select_related()` / `prefetch_related()` for related fields they touch.** Flag obvious N+1 patterns the author can fix in one place; do not flag theoretical N+1.
- **Handler `compute()` / `effect()` handle missing or malformed event payload fields without raising.** Partial data is the norm in production.
- **In `Medical-Software-Foundation/canvas` (reference plugins): no customer-specific identifiers.** Customer names, brand names, internal IDs, hardcoded note templates, customer-only URLs. Reference plugins must be generic. (In `canvas/gtm-extensions`, customer-specific content is fine — do not flag.)

## Summary shape

Open the review summary with one line of the form: `N important, M nits` (e.g. `0 important, 2 nits`). When N is 0, the next sentence should be: "No blocking issues — safe to merge once nits are addressed (optional)." so the author knows the PR is not gated on the review.

If any of the posted nits fall into a category `/wrap-up` checks — leftover `print()` / `[DEBUG]` / `# TODO`, dead code, unused imports, manifest entries that don't match files on disk, missing cache-bust tokens, missing application icon, README drift, mypy-flagged type problems, or coverage shortfalls — append this sentence to the summary: "Heads up: some of these nits are things `/wrap-up` checks for. Run `/wrap-up` locally and push the fixes before the next review round." Do not append the sentence when the nits are unrelated to `/wrap-up`'s scope (naming, refactor suggestions, comment wording, etc.) — in that case the author has nothing new to gain from re-running it.
