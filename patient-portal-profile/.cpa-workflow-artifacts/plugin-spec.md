# Patient Portal Profile

## Plugin name
`patient-portal-profile`

Snake-case module: `patient_portal_profile`

## Problem
Canvas patient portal users need a single place to view their own profile information. v1 of this plugin adds a dedicated "My Profile" menu item in the patient portal where patients can review the personal information held by Canvas:

- Photo
- Full name (and preferred name)
- Birthdate
- Email registration (the email used to register for the patient portal — also used for password reset)
- Phone number registration (the phone number used to register for the patient portal, if available)
- Addresses (all)
- Care team members (active)
- Preferred pharmacy

v1 is read-only.

## User role
**Patient** — authenticated in the Canvas patient portal. No staff/provider exposure.

## Trigger
- **Event:** `Application.on_open` — fires when the patient clicks the "My Profile" menu item.
- **Manifest scope:** `portal_menu_item` (verified against the canonical `example_patient_portal_page` reference plugin in the Canvas SDK docs).

## Effects
- **`LaunchModalEffect`** with `target=LaunchModalEffect.TargetType.PAGE` — opens the profile UI as an iframed page inside the patient portal. The iframe URL points to this plugin's own `SimpleAPI` endpoint.

## Data model

All data is read for the **currently-authenticated patient** (resolved from the `canvas-logged-in-user-id` request header, which is guaranteed present and valid because the endpoint is protected by `PatientSessionAuthMixin`).

| Field | Source | Notes |
|---|---|---|
| Photo | `Patient.photo_url` (computed) | Presigned S3 URL for the patient's uploaded avatar; falls back to the SDK's default avatar URL when no photo is on file. The browser fetches the image directly via the `<img src>` attribute — no proxying needed. |
| Prefix / suffix | `Patient.prefix`, `Patient.suffix` | |
| First name | `Patient.first_name` | |
| Middle name | `Patient.middle_name` | |
| Last name | `Patient.last_name` | |
| Preferred name | `Patient.preferred_full_name` (computed) | Falls back to `nickname` / legal name |
| Birthdate | `Patient.birth_date` | Formatted in the UI |
| Email registration | `CanvasUser.email` via `Patient.user.filter(is_portal_registered=True).first()` | The email used when the patient registered for the portal (and used for password-reset). Distinct from `Patient.telecom` email entries, which are clinical contact data. |
| Phone number registration | `CanvasUser.phone_number` via `Patient.user.filter(is_portal_registered=True).first()` | The phone number used when the patient registered for the portal. Distinct from `Patient.telecom` phone entries, which are clinical contact data. Hide the row if `None`/empty. |
| Addresses (all) | `Patient.addresses.all()` | Show every address with `use` / `type` labels, lines, city, state, postal code, country. |
| Care team (active) | `CareTeamMembership.objects.values("staff__first_name", "staff__last_name", "staff__prefix", "staff__suffix", "staff__photos__url", "role__display").filter(patient__id=<id>, status=CareTeamMembershipStatus.ACTIVE)` | Same pattern as the SDK's `patient_portal_plugin` care-team widget — fetches in one query. Empty list renders nothing. |
| Preferred pharmacy | `Patient.preferred_pharmacy` (computed JSON) | Display the pharmacy details Canvas returns (name, address, phone if present). Empty/None renders nothing. |

### SDK references confirmed
- `canvas_sdk.v1.data.patient.Patient` — fields: `first_name`, `last_name`, `middle_name`, `birth_date`, `prefix`, `suffix`, `nickname`, `addresses` (PatientAddress[]), `telecom` (PatientContactPoint[]), `user` (CanvasUser[]), `photos` (PatientPhoto[]); computed: `full_name`, `preferred_full_name`, `preferred_first_name`, `primary_phone_number`, `preferred_pharmacy`, `photo`, `photo_url` (added in canvas-medical/canvas-plugins#1690, merged 2026-05-14)
- `canvas_sdk.v1.data.CanvasUser` — fields: `email`, `phone_number`, `is_staff`, `is_portal_registered`
- `canvas_sdk.v1.data.patient.PatientAddress` — `line1`, `line2`, `city`, `district`, `state_code`, `postal_code`, `use`, `type`, `country`, `state`
- `canvas_sdk.v1.data.patient.PatientContactPoint` — `system`, `value`, `use`, `rank`
- `canvas_sdk.v1.data.care_team.CareTeamMembership` — relations: `patient`, `staff`, `role`; status: `CareTeamMembershipStatus.ACTIVE`

## Handlers

### `Application` — `applications/profile_application.py`
- Class: `ProfileApplication(Application)`
- Implements `on_open()` returning `LaunchModalEffect(url=..., target=LaunchModalEffect.TargetType.PAGE).apply()`
- URL: `/plugin-io/api/patient_portal_profile/app/profile`

### `SimpleAPI` — `handlers/profile_web_app.py`
- Class: `ProfileWebApp(PatientSessionAuthMixin, SimpleAPI)`
- `PREFIX = "/app"`
- Endpoints:
  - `GET /profile` → renders the HTML profile page (`static/index.html`) with the logged-in patient's data via `render_to_string`. Returns `HTMLResponse`.
  - `GET /main.js` → returns the static JS file as `text/javascript`.
  - `GET /styles.css` → returns the static CSS file as `text/css`.
- Patient lookup: `Patient.objects.prefetch_related("user", "addresses").get(id=self.request.headers["canvas-logged-in-user-id"])`.
- Care team query: as listed in the data table above — single `.values()` query, no N+1.
- Preferred pharmacy: read directly from the computed `patient.preferred_pharmacy` property.

### Why `PatientSessionAuthMixin`
The canonical Canvas portal example uses a hand-rolled `authenticate` that accepts any logged-in user (staff included). `PatientSessionAuthMixin` is stricter: it only accepts logged-in patient sessions, which matches the requirement that patients view their own data and nothing else.

## Suggested file structure

```
patient-portal-profile/
├── pyproject.toml
├── mypy.ini
├── tests/
│   ├── __init__.py
│   ├── test_profile_application.py
│   └── test_profile_web_app.py
└── patient_portal_profile/
    ├── __init__.py
    ├── CANVAS_MANIFEST.json
    ├── README.md
    ├── applications/
    │   ├── __init__.py
    │   └── profile_application.py
    ├── handlers/
    │   ├── __init__.py
    │   └── profile_web_app.py
    ├── assets/
    │   └── icon.png            # 48x48, generated via cpa:icon-generation
    └── static/
        ├── index.html
        ├── main.js
        └── styles.css
```

## CANVAS_MANIFEST.json sketch

```json
{
  "sdk_version": "0.1.4",
  "plugin_version": "0.0.1",
  "name": "patient_portal_profile",
  "description": "Patient portal application that lets patients view their own profile: photo, name, birthdate, registration email, registration phone, addresses, care team, and preferred pharmacy.",
  "url_permissions": [],
  "components": {
    "applications": [
      {
        "class": "patient_portal_profile.applications.profile_application:ProfileApplication",
        "name": "My Profile",
        "description": "View your personal information on file.",
        "scope": "portal_menu_item",
        "icon": "assets/icon.png"
      }
    ],
    "handlers": [
      {
        "class": "patient_portal_profile.handlers.profile_web_app:ProfileWebApp",
        "description": "Serves the profile HTML/JS/CSS for the My Profile menu item."
      }
    ],
    "commands": [],
    "content": [],
    "effects": [],
    "views": []
  },
  "secrets": [],
  "tags": {},
  "references": [],
  "license": "",
  "diagram": false,
  "readme": "./README.md"
}
```

## UI sketch (HTML rendered server-side)

```
┌───────────────────────────────────────────────────────┐
│  My Profile                                           │
├───────────────────────────────────────────────────────┤
│  [   photo   ]   Jane Q. Doe                          │
│                  Preferred: Janie                     │
│                  DOB: 1985-04-12                      │
│                                                       │
│  Patient portal registration                          │
│   Email:  jane.doe@example.com                        │
│   Phone:  +1 (555) 123-4567                           │
│                                                       │
│  Addresses                                            │
│   • Home — 123 Main St, Boston MA 02118               │
│   • Work — 1 Boylston Pl, Boston MA 02116             │
│                                                       │
│  Care team                                            │
│   • Dr. Steven Magee — Primary care physician   [pic] │
│   • Annalies Hines, NP — Nurse practitioner     [pic] │
│                                                       │
│  Preferred pharmacy                                   │
│   CVS Pharmacy #1234                                  │
│   500 Boylston St, Boston MA 02116                    │
│   (617) 555-0100                                      │
└───────────────────────────────────────────────────────┘
```

## Testing strategy (function-based, per CLAUDE.md)

- `test_profile_application.py`
  - `on_open` returns a single `LaunchModalEffect` with `target=PAGE` and URL pointing at the SimpleAPI endpoint.
- `test_profile_web_app.py`
  - GET `/profile` with a logged-in patient header returns 200 and HTML containing the patient's name, formatted birthdate, registration email, registration phone, one row per address, each care team member, the preferred pharmacy block, and a photo `<img>` whose `src` matches `Patient.photo_url`.
  - GET `/profile` for a patient with no uploaded photo renders the default-avatar URL from the SDK (no manual fallback logic in the template).
  - Patient whose `CanvasUser.phone_number` is `None`/empty → registration phone row is omitted.
  - GET `/profile` without `canvas-logged-in-user-id` is rejected by `PatientSessionAuthMixin` (401/403).
  - Patient with no addresses → addresses section is omitted.
  - Patient with no active care team → care team section is omitted.
  - Patient with no preferred pharmacy → preferred pharmacy section is omitted.
  - `/main.js` and `/styles.css` return the expected content types.
- At least one test uses the test DB with Factories per CLAUDE.md. Mocks are fine where the mocked behavior is also tested elsewhere.
