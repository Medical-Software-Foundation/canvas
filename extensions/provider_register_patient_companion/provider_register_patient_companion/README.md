# provider_register_patient_companion

A global companion tool for registering a new patient from the provider companion launcher. Collects the minimum fields Canvas needs to create a record — first name, last name, date of birth, sex at birth, phone — warns about likely duplicates before it commits, and drops the provider on the new patient's companion page once the record exists.

## What providers see

An icon titled **Register Patient** appears in the provider companion launcher. Tapping it opens a modal with a five-field form.

On submit:

1. The plugin checks for existing patients that may be the same person.
2. If any are found, they're shown in an alert-style callout with each match reason. The provider must tick a **"I've reviewed these and want to register a new patient"** checkbox before the modal will let them proceed.
3. Once created, the modal dismisses and the companion harness navigates to the new patient's page.

While the submission is in flight, the **Register** button swaps to a spinner labeled **"Creating patient"** and stays that way through the entire check → create → lookup sequence. It only returns to **Register** when the provider needs to do something (address validation errors, review duplicates) or when creation fails — not during any intermediate step.

If the backend can't confirm the patient was created within ~5 seconds, the form surfaces an error — it does **not** silently claim success.

## What counts as a "possible duplicate"

Two independent passes, unioned by patient:

- **Name + DOB pass.** Normalizes first and last name (lowercased, stripped of non-alphanumerics — so `Jim-bob` matches `Jim Bob`) and looks within ±1 year of the submitted DOB. This catches off-by-one typos on day, month, or year as well as transposed day/month. Each match is labeled:
  - `name + dob` when the DOB is exact.
  - `name, dob off by N day(s)` when within a week.
  - `name, dob differs (YYYY-MM-DD)` when the name matches but the DOB is further off; the listed DOB helps the provider spot their own typo.
- **Phone pass.** Digits-only equality against any of the candidate's contact points where `system == "phone"`. Narrows by the last four digits at the DB layer, then verifies in Python.

The callout shows name, DOB, phone, and the match reason(s) for each hit. The provider eyeballs the list and decides — nothing is blocked.

## Installation

No environment variables or secrets required.

```sh
canvas install --host <host> \
    ~/src/plugin-development/msf-canvas/extensions/provider_register_patient_companion/provider_register_patient_companion
```

---

## For developers

### Scope

This plugin uses the `provider_companion_global` `ApplicationScope` — it surfaces on the provider companion main page, no patient or note context.

### Architecture

```
provider_register_patient_companion/
├── CANVAS_MANIFEST.json                # scope: provider_companion_global
├── README.md
├── LICENSE
├── applications/
│   └── register_patient_app.py         # Application → LaunchModalEffect
├── handlers/
│   └── register_patient_api.py         # SimpleAPI: form, /check, /create, /find, static
├── static/
│   ├── index.html                      # form shell
│   ├── main.js                         # client validation, dup check, create, /find poll
│   └── styles.css                      # mobile-first, green accent
└── assets/
    ├── icon.png                        # 256×256 launcher icon
    └── register-patient-icon.svg       # source SVG
```

### Request flow

1. Provider taps the launcher → `RegisterPatientApp.on_open()` → `LaunchModalEffect` pointing at `/plugin-io/api/provider_register_patient_companion/app/`.
2. The iframe loads the form HTML + static assets.
3. On submit, the client validates locally, then `POST /app/check` with the form body. Server returns `{duplicates: [...]}`.
4. If duplicates are present, client renders the callout and blocks submit behind the acknowledgment checkbox. Any edit to a field re-runs `/check` on next submit.
5. On confirmed submit, client calls `POST /app/create` with `acknowledged: true` when appropriate. Server re-validates, re-runs duplicate detection, and (on pass) returns `[Patient(...).create() effect, JSONResponse(202, {lookup_params, lookup_started_at})]`.
6. The `CREATE_PATIENT` effect is dispatched asynchronously by the platform after the handler returns — the plugin can't see the new patient's UUID from inside the same handler.
7. Client polls `GET /app/find?first_name=…&last_name=…&birth_date=…&after=<iso>` every 500 ms for up to 5 s. On first hit, `window.top.location = "/companion/patient/<uuid>/"` tears down the iframe and navigates the companion harness to the new patient.
8. If the poll times out (or `/create` returned non-2xx), the form surfaces "There was an issue creating the patient." and re-enables Register.

### Why a client-side poll rather than a server-side wait

Effects dispatched from a `SimpleAPI` handler execute in the platform worker **after** the handler returns. A server-side `time.sleep + Patient.objects.filter(...)` loop inside `/create` would always run before the effect landed and always return nothing. The client-side poll is simple, responsive, and lets the UI show progress.

### Why `window.top.location` instead of updating the iframe's `location`

The iframe is the modal; its parent is the companion harness page. Navigating `window.top` destroys the iframe and leaves the provider on the new patient's companion view. Updating only the iframe's location would leave the modal sitting on top of the companion launcher showing the patient page, which isn't what we want.

### Auth

- `StaffSessionAuthMixin` on the handler — non-staff sessions raise `InvalidCredentialsError` at the auth layer.
- Logged-in staff UUID is read from the `canvas-logged-in-user-id` header but not used by this plugin (no provider-scoped filtering).

### Cache busting

Two layers, because the HTML shell and its static children are cached differently by browsers:

- **JS and CSS**: the HTML shell appends `?v={{cache_bust}}` to `main.js` / `styles.css` references, where `cache_bust` is a module-level UTC timestamp generated when the plugin process starts. A redeploy or worker restart produces a new token, invalidating the old URLs.
- **HTML shell itself**: `GET /` sends `Cache-Control: no-store`. Without this, the browser can cache the shell and serve the stale HTML on the next modal open — that would reference the *old* `cache_bust` token, so JS/CSS get refreshed but HTML edits (new fields, restructured rows, etc.) wouldn't reach the provider without a hard refresh.

### Validation

Client-side and server-side checks are kept identical:

| Field | Rule |
|---|---|
| `first_name` | Required, non-empty after trim. |
| `last_name` | Required, non-empty after trim. |
| `birth_date` | Required, valid `YYYY-MM-DD`, not in the future. Client uses `<input type="date">`. |
| `sex_at_birth` | Required, one of `F` / `M` / `O` / `UNK` (the `PersonSex` choices the SDK's `Patient` effect accepts). |
| `phone` | Required, ≥ 10 digits after stripping non-digits. Formatting is preserved as entered when stored. |

Server-side errors come back as `{errors: {field: message}}` and are rendered inline next to the offending field.

### Endpoints

All mounted under `/plugin-io/api/provider_register_patient_companion/app/`.

| Method & path | Purpose |
|---|---|
| `GET /` | HTML shell |
| `POST /check` | Validates the submission and returns any possible duplicates |
| `POST /create` | Validates, re-checks duplicates (requires `acknowledged: true` if any), dispatches `CreatePatient` effect, returns the `lookup_params` for the polling step |
| `GET /find?first_name=…&last_name=…&birth_date=…&after=<iso>` | Returns `{patient_id}` for a record matching those fields with `created >= after`, or `null` |
| `GET /main.js` | Served JS |
| `GET /styles.css` | Served CSS |

### Known considerations

- **No way to know the new patient's UUID synchronously.** The post-create poll is the workaround; it's bounded at 5 s.
- **Rare polling ambiguity.** If two staff register patients with identical normalized name + DOB inside the same 2-second window, `order_by("-created")` picks the latest — statistically ours, not guaranteed.
- **Phone format round-trip.** The phone is stored exactly as entered (punctuation included). Duplicate detection always compares on digits-only, so `(555) 123-4567` and `555-123-4567` match as expected.
- **No address / insurance / email at registration.** Scope is deliberately minimal to keep the bedside flow fast. Those live in the full patient profile.

## Testing

```sh
cd ~/src/canvas-plugins && uv run pytest \
    ~/src/plugin-development/msf-canvas/extensions/provider_register_patient_companion/tests \
    --cov=provider_register_patient_companion --cov-branch --cov-report=term-missing
```

Current coverage: **100%** (142 stmts, 44 branches, 44 tests).

## License

MIT. See [LICENSE](./LICENSE).
