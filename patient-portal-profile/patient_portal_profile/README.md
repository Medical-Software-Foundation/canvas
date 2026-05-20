patient-portal-profile
======================

## Description

Adds a **My Profile** menu item to the Canvas patient portal. When a logged-in
patient opens it, the plugin renders a read-only page that displays the
personal information Canvas holds for them:

- Photo
- Full name (and preferred name)
- Birthdate
- Patient-portal registration email and phone number
- All addresses on file
- Active care team members
- Preferred pharmacy

v1 is read-only.

## How it works

- `ProfileApplication` (scope `portal_menu_item`) handles `Application.on_open`
  and returns a `LaunchModalEffect` targeting `PAGE`. The iframed URL points to
  this plugin's own SimpleAPI endpoint.
- `ProfileWebApp` is a `SimpleAPI` protected by `PatientSessionAuthMixin`, so
  only logged-in patients can reach it. It serves:
  - `GET /app/profile` — server-rendered HTML for the currently authenticated
    patient (resolved from `canvas-logged-in-user-id`).
  - `GET /app/main.js`, `GET /app/styles.css` — the static assets the page
    references.
- The care-team membership list is fetched with a single
  `CareTeamMembership.objects.values(...).filter(...)` call to avoid N+1.
- Patient data is loaded once via
  `Patient.objects.select_related("user").prefetch_related("addresses").get(...)`.

## Layout

```
patient_portal_profile/
├── CANVAS_MANIFEST.json
├── applications/
│   └── profile_application.py    # ProfileApplication (portal_menu_item)
├── handlers/
│   └── profile_web_app.py        # ProfileWebApp (SimpleAPI)
├── assets/
│   └── icon.png                  # 48x48 menu-item icon
└── static/
    ├── index.html                # Django template rendered server-side
    ├── styles.css
    └── main.js
```
